"""Cykl Zgłoszenia na interfejsie jego uchwytu (``Reports.handle``): podgląd, pytanie skrzynki w tle, wysyłka i stan.

Uchwytu używają Zatrzymanie (``stops``) i nieudana Aktualizacja narzędzia (``tool_updates``); tu źródłem jest
Aktualizacja, a okablowanie obu źródeł sprawdzają ich testy HTTP (``test_centrum_zgloszenie``,
``test_centrum_aktualizacja``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from rozliczenia.centrum import update_messages
from rozliczenia.centrum.keyed_box import REFUSED_KEPT_S, KeyedBox, read_report_key
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import IssuesOutcome, Label, Refused, SendOutcome, Unreachable
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, DadCases
from rozliczenia.centrum.reports import SEARCH_DEADLINE_S, NoPreview, ReportHandle, Reports, UpdateReport
from rozliczenia.centrum.tool_update import NO_CONNECTION, OTHER_BRANCH, UpdateResult
from rozliczenia.message import Message

from tests.fixtures.centrum import TOOL_COMMIT, FakeReportBox, dad_cases
from tests.fixtures.clock import ManualClock

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
READY = {"state": "ready"}
SENT = {"state": "sent"}
WAITING = {"state": "waiting"}
FILE_NAME = f"Zgłoszenie {NO_CONNECTION} aktualizacja.md"


class Owner:
    """Właściciel Zgłoszenia: zapamiętuje każdy stan, który dostał od uchwytu."""

    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []
        self._changed = threading.Condition()

    def __call__(self, state: BaseModel) -> None:
        with self._changed:
            self.states.append(dump(state))
            self._changed.notify_all()

    def wait_for(self, count: int, seconds: float = 10) -> list[dict[str, Any]]:
        with self._changed:
            assert self._changed.wait_for(lambda: len(self.states) >= count, seconds), self.states
            return list(self.states)


@dataclass
class Computer:
    """Katalog konfiguracji tego komputera, skrzynka Zgłoszeń i dziennik Centrum; ``reports()`` to start Centrum."""

    tmp_path: Path
    box: FakeReportBox = field(default_factory=FakeReportBox)
    search_deadline_s: float = SEARCH_DEADLINE_S
    clock: ManualClock = field(default_factory=ManualClock)

    @property
    def config(self) -> Path:
        return self.tmp_path / "config"

    @property
    def log(self) -> CentrumLog:
        return CentrumLog(self.tmp_path / "logs" / "centrum-rozliczen.log")

    def log_text(self) -> str:
        return (self.tmp_path / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")

    def with_key(self) -> None:
        self.config.mkdir(parents=True, exist_ok=True)
        (self.config / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")

    def reports(self) -> Reports:
        keyed = KeyedBox(self.box, lambda: read_report_key(self.config), clock=self.clock)
        return Reports(
            self.config,
            keyed,
            self.log,
            lambda: TOOL_COMMIT,
            DadCases(self.config, self.log),
            search_deadline_s=self.search_deadline_s,
        )

    def unsent(self) -> dict[str, str]:
        return {path.name: path.read_text(encoding="utf-8") for path in sorted((self.config / "zgloszenia").glob("*.md"))}


@pytest.fixture
def computer(tmp_path: Path) -> Computer:
    (tmp_path / "config").mkdir()
    return Computer(tmp_path)


def dump(state: BaseModel) -> dict[str, Any]:
    return state.model_dump()


def source(computer: Computer, code: str = NO_CONNECTION) -> UpdateReport:
    message: Message = update_messages.message_of(code)
    return UpdateReport.of(UpdateResult(code, TOOL_COMMIT, None), message, computer.log)


def prepared(reports: Reports, computer: Computer, code: str = NO_CONNECTION) -> tuple[ReportHandle, Owner, str]:
    """Uchwyt z podglądem po odpowiedzi skrzynki (albo jej braku) na pytanie z podglądu: uchwyt, właściciel i treść."""

    owner = Owner()
    report = source(computer, code)
    handle = reports.handle(report.fingerprint, shown=owner)
    draft = handle.prepare(report)
    owner.wait_for(1)
    return handle, owner, f"# {draft.title}\n\n{draft.body}"


def test_wyslanie_przed_podgladem_nie_ma_czego_wyslac(computer: Computer) -> None:
    computer.with_key()
    handle = computer.reports().handle(source(computer).fingerprint)

    with pytest.raises(NoPreview):
        handle.send()

    assert (dump(handle.state), computer.box.keys) == (READY, [])


def test_bez_klucza_zgloszenie_czeka_w_pliku_a_ponowna_proba_z_kluczem_wysyla_ten_sam_podglad(computer: Computer) -> None:
    handle, owner, saved_text = prepared(computer.reports(), computer)

    saved = dump(handle.send())

    assert saved == {
        "state": "saved",
        "message": {
            "what": "Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.",
            "where": f"plik {FILE_NAME}, folder zgloszenia",
            "action": "Prześlij ten plik Maksowi mailem. Gdy Maks wpisze klucz do Zgłoszeń, kliknij „Spróbuj ponownie”.",
        },
    }
    assert computer.unsent() == {FILE_NAME: saved_text}
    assert "zgloszenie-zapisane z=aktualizacja kod=ZGLOSZENIE_BEZ_KLUCZA" in computer.log_text()

    computer.with_key()
    again = dump(handle.send())

    assert again == SENT
    assert [f"# {report.title}\n\n{report.body}" for report in computer.box.sent] == [saved_text]
    assert computer.box.keys == [KEY]
    assert computer.unsent() == {}
    assert (owner.states, dump(handle.state)) == ([READY, saved, SENT], SENT)
    assert "zgloszenie-wyslane z=aktualizacja numer=1" in computer.log_text()


@pytest.mark.parametrize(
    ("failure", "what"),
    [
        (Refused(), "Nie wysłano Zgłoszenia: klucz do Zgłoszeń wygasł albo jest nieważny."),
        (Unreachable(), "Nie wysłano Zgłoszenia: brak połączenia z GitHubem."),
    ],
    ids=["odmowa", "brak-polaczenia"],
)
def test_nieudana_wysylka_zapisuje_zgloszenie_w_pliku_a_ponowna_proba_je_wysyla(
    computer: Computer, failure: SendOutcome, what: str
) -> None:
    computer.with_key()
    computer.box.outcomes.append(failure)
    handle, _, saved_text = prepared(computer.reports(), computer)

    saved = dump(handle.send())

    assert (saved["state"], saved["message"]["what"]) == ("saved", what)
    assert computer.unsent() == {FILE_NAME: saved_text}
    computer.clock.advance(REFUSED_KEPT_S)  # odrzucony klucz Skrzynka sprawdza znowu dopiero po kwadransie
    assert dump(handle.send()) == SENT
    assert (len(computer.box.keys), len(computer.box.sent), computer.unsent()) == (2, 1, {})


def test_zgloszenie_ktorego_nie_da_sie_ani_wyslac_ani_zapisac_w_pliku_daje_komunikat(computer: Computer) -> None:
    handle, _, _ = prepared(computer.reports(), computer)
    (computer.config / "zgloszenia").write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda

    state = dump(handle.send())

    assert state == {
        "state": "saved",
        "message": {
            "what": "Nie wysłano Zgłoszenia i nie udało się zapisać go w pliku na tym komputerze.",
            "where": "folder zgloszenia",
            "action": "Rozwiń „Co zostanie wysłane”, skopiuj treść i prześlij ją Maksowi mailem.",
        },
    }
    assert "zgloszenie-niezapisane z=aktualizacja przyczyna=ZGLOSZENIE_BEZ_KLUCZA" in computer.log_text()


def test_plik_niewyslanego_zgloszenia_ktorego_nie_da_sie_usunac_nie_cofa_wyslania(computer: Computer) -> None:
    computer.with_key()
    handle, _, _ = prepared(computer.reports(), computer)
    # Na miejscu pliku niewysłanego Zgłoszenia coś, czego nie da się usunąć jak pliku (w Windows: plik otwarty).
    (computer.config / "zgloszenia" / FILE_NAME).mkdir(parents=True)

    first = dump(handle.send())

    assert (first, dump(handle.state), dump(handle.send())) == (SENT, SENT, SENT)
    assert len(computer.box.sent) == 1


def test_wyslane_zgloszenie_nie_idzie_drugi_raz_takze_po_nowym_podgladzie(computer: Computer) -> None:
    computer.with_key()
    report = source(computer)
    handle, owner, _ = prepared(computer.reports(), computer)

    first, second = dump(handle.send()), dump(handle.send())
    handle.prepare(report)

    assert (first, second, owner.wait_for(3)) == (SENT, SENT, [READY, SENT, SENT])
    assert dump(handle.send()) == SENT
    assert (len(computer.box.keys), len(computer.box.sent)) == (1, 1)


def test_drugie_klikniecie_w_trakcie_wysylki_czeka_na_jej_wynik_i_nie_wysyla_drugi_raz(computer: Computer) -> None:
    computer.with_key()
    box = computer.box
    handle, _, _ = prepared(computer.reports(), computer)
    box.open_hold = threading.Event()
    answers: list[dict[str, Any]] = []
    clicks = [threading.Thread(target=lambda: answers.append(dump(handle.send())), daemon=True) for _ in range(2)]

    try:
        clicks[0].start()
        assert box.opening.wait(10)
        clicks[1].start()
        clicks[1].join(0.2)
        second_waits = clicks[1].is_alive()
    finally:
        box.open_hold.set()
    for click in clicks:
        click.join(10)

    assert second_waits
    assert answers == [SENT, SENT]
    assert len(box.sent) == 1


def test_wysylka_przerwana_wyjatkiem_nie_blokuje_nastepnej_ani_nie_zmienia_stanu(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    computer.with_key()
    box = computer.box
    handle, owner, _ = prepared(computer.reports(), computer)
    opened = box.open_issue

    def broken(label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        raise RuntimeError("syntetyczna awaria skrzynki")

    monkeypatch.setattr(box, "open_issue", broken)
    with pytest.raises(RuntimeError, match="syntetyczna awaria skrzynki"):
        handle.send()
    after_failure = dump(handle.state)
    monkeypatch.setattr(box, "open_issue", opened)

    answers: list[dict[str, Any]] = []
    again = threading.Thread(target=lambda: answers.append(dump(handle.send())), daemon=True)
    again.start()
    again.join(10)

    assert after_failure == READY
    assert answers == [SENT]
    assert owner.states == [READY, SENT]


def test_otwarte_zgloszenie_wyslane_spoza_tego_komputera_czeka_na_naprawe_bez_drugiej_wysylki(computer: Computer) -> None:
    computer.with_key()
    first, _, _ = prepared(computer.reports(), computer)
    first.send()
    (computer.config / DAD_CASES_FILE).unlink()

    restarted = computer.reports()
    report = source(computer)
    before = restarted.handle(report.fingerprint)
    handle, owner, _ = prepared(restarted, computer)

    assert (dump(before.state), owner.states) == (READY, [WAITING])
    assert dump(handle.send()) == WAITING
    assert len(computer.box.sent) == 1
    assert "zgloszenie-czeka z=aktualizacja numer=1" in computer.log_text()


def test_wyslane_zgloszenie_czeka_na_naprawe_po_restarcie_bez_pytania_skrzynki_a_inny_problem_nie(
    computer: Computer
) -> None:
    computer.with_key()
    handle, _, saved_text = prepared(computer.reports(), computer)
    handle.send()
    asked = len(computer.box.listed)

    restarted = computer.reports()
    same = restarted.handle(source(computer).fingerprint)
    other = restarted.handle(source(computer, OTHER_BRANCH).fingerprint)

    assert (dump(same.state), dump(other.state), len(computer.box.listed)) == (WAITING, READY, asked)
    sent = dad_cases(computer.config, "zgloszenie")
    [fingerprint] = [line.removeprefix("- Odcisk problemu: ") for line in saved_text.splitlines() if "Odcisk" in line]
    assert [{name: entry[name] for name in ("id", "number", "commit", "closure")} for entry in sent] == [
        {"id": fingerprint, "number": 1, "commit": TOOL_COMMIT, "closure": None}
    ]


def test_inny_problem_wysyla_sie_osobno_obok_otwartego_zgloszenia(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()

    other, owner, _ = prepared(reports, computer, OTHER_BRANCH)

    assert owner.states == [READY]
    assert dump(other.send()) == SENT
    assert [report.title.split(":")[0] for report in computer.box.sent] == [NO_CONNECTION, OTHER_BRANCH]


def test_po_zamknieciu_zgloszenia_powracajacy_problem_wysyla_nowe_z_odnosnikiem_do_poprzedniego(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, first_text = prepared(reports, computer)
    first.send()
    computer.box.close(1)

    before = reports.handle(source(computer).fingerprint)
    again, owner, text = prepared(reports, computer)

    assert (dump(before.state), owner.states) == (WAITING, [READY])
    assert "- Poprzednie Zgłoszenie: #1" in text.splitlines()
    assert "Poprzednie Zgłoszenie" not in first_text
    assert dump(again.send()) == SENT
    sent = dad_cases(computer.config, "zgloszenie")
    assert [entry["number"] for entry in sent] == [1, 2]


def test_bez_odpowiedzi_skrzynki_wyslany_problem_dalej_czeka_na_naprawe(computer: Computer) -> None:
    computer.with_key()
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()
    computer.box.close(1)
    computer.box.search_failure = Unreachable()

    _, owner, _ = prepared(reports, computer)

    assert owner.states == [WAITING]
    assert len(computer.box.sent) == 1


def test_gdy_skrzynka_nie_odpowiada_na_pytanie_o_otwarte_zgloszenie_zgloszenie_zostaje_w_pliku(computer: Computer) -> None:
    computer.with_key()
    computer.box.search_failure = Unreachable()
    handle, _, saved_text = prepared(computer.reports(), computer)

    saved = dump(handle.send())

    assert (saved["state"], saved["message"]["what"]) == ("saved", "Nie wysłano Zgłoszenia: brak połączenia z GitHubem.")
    assert computer.unsent() == {FILE_NAME: saved_text}
    assert computer.box.keys == []


def test_podglad_nie_czeka_na_skrzynke_a_spozniona_odpowiedz_to_brak_odpowiedzi(computer: Computer) -> None:
    computer.with_key()
    computer.search_deadline_s = 0.05
    box = computer.box
    reports = computer.reports()
    first, _, _ = prepared(reports, computer)
    first.send()
    box.close(1)
    box.search_hold = threading.Event()
    release = threading.Timer(10, box.search_hold.set)  # bez limitu stan czekałby na skrzynkę
    release.start()

    try:
        _, owner, _ = prepared(reports, computer)
        box_answered_first = box.search_hold.is_set()
    finally:
        box.search_hold.set()
        release.cancel()

    assert not box_answered_first
    assert owner.states == [WAITING]


@dataclass
class FirstSearchHeld(FakeReportBox):
    """Skrzynka, w której tylko pierwsze pytanie o otwarte Zgłoszenia (``first_asked``) czeka, aż test je puści
    (``first_search``)."""

    first_asked: threading.Event = field(default_factory=threading.Event)
    first_search: threading.Event = field(default_factory=threading.Event)

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        if not self.first_asked.is_set():
            self.first_asked.set()
            self.first_search.wait()
        return super().labelled_issues(label, include_closed=include_closed, key=key)


def test_odpowiedz_skrzynki_na_pytanie_sprzed_wysylki_nie_zmienia_wyniku_wysylki(tmp_path: Path) -> None:
    computer = Computer(tmp_path, FirstSearchHeld(outcomes=[Unreachable()]))
    computer.with_key()
    box = computer.box
    assert isinstance(box, FirstSearchHeld)
    report = source(computer)
    owner = Owner()
    handle = computer.reports().handle(report.fingerprint, shown=owner)

    try:
        handle.prepare(report)
        assert box.first_asked.wait(10)
        saved = dump(handle.send())
    finally:
        box.first_search.set()
    handle.wait_for_box()

    assert saved["state"] == "saved"
    assert (owner.states, dump(handle.state)) == ([saved], saved)
