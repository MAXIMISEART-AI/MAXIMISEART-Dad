"""Zgłoszenie do Maksa z Centrum rozliczeń przez HTTP API, z fałszywą skrzynką Zgłoszeń."""

from __future__ import annotations

import codecs
from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, NoReturn

import pytest

from rozliczenia import preparation_register
from rozliczenia.centrum.report_box import Refused, SendOutcome, Unreachable

from tests.fixtures.centrum import TOOL_COMMIT
from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, run_to_end, stopped_for_maks
from tests.fixtures.preparation import PERIOD

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"


def with_key(centrum: PreparingCentrum) -> Path:
    """Klucz do Zgłoszeń w lokalnym pliku obok Ustawień taty, jak go wpisuje Maks."""

    key_file = centrum.tmp_path / "config" / "zgloszenia-klucz.txt"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    return key_file


def diagnose(centrum: PreparingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    return diagnosis


def send(centrum: PreparingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/report")
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def test_wyslane_zgloszenie_jest_dokladnie_podgladem_z_diagnozy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    state = send(centrum, run_id)

    assert state == {"state": "sent"}
    [report] = centrum.surroundings.report_box.sent
    assert {"title": report.title, "body": report.body} == preview
    assert centrum.surroundings.report_box.keys == [KEY]
    assert f"zgloszenie-wyslane proces=preparation okres={PERIOD} numer=1" in centrum.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        codecs.BOM_UTF8 + (KEY + "\r\n").encode("utf-8"),  # Notatnik, PowerShell 5.1: Set-Content -Encoding UTF8
        codecs.BOM_UTF16_LE + (KEY + "\r\n").encode("utf-16-le"),  # PowerShell 5.1: > albo Out-File
        codecs.BOM_UTF16_BE + (KEY + "\r\n").encode("utf-16-be"),  # Notatnik: UTF-16 BE
    ],
    ids=["utf-8-bom", "utf-16-le", "utf-16-be"],
)
def test_klucz_zapisany_z_bom_wysyla_zgloszenie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum).write_bytes(content)
    run_id = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, run_id)

    assert send(centrum, run_id) == {"state": "sent"}
    assert centrum.surroundings.report_box.keys == [KEY]


def test_zgloszenie_ma_komunikat_uruchomienie_narzedzie_diagnoze_i_dziennik(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    report = diagnosis["report"]
    assert report["title"] == "BRAK_WZORCA: Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku."
    body = report["body"]
    stop = stopped["result"]["stops"][0]
    for line in (
        "| Wzorzec rozliczenia wewnętrznego | przeszło | Wzorzec rozliczenia wewnętrznego.xlsx przechodzi Sprawdzanie. |",
        f"| Wzorzec pliku zbiorczego | nie przeszło | {stop['what']} |",
        "| Folder okresu | przeszło | Folderu 08_14_09_2026 jeszcze nie ma. |",
    ):
        assert line in body.splitlines()
    fingerprint = re.search(r"^- Odcisk problemu: ([0-9a-f]{16})$", body, re.MULTILINE)
    assert fingerprint is not None
    log_lines = centrum.log_path.read_text(encoding="utf-8").splitlines()
    diagnosed = next(index for index, line in enumerate(log_lines) if line.split(" ", 2)[1] == "diagnoza")
    results = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}
    assert body.splitlines() == [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        "- Kod: BRAK_WZORCA",
        f"- Co się stało: {stop['what']}",
        f"- Gdzie: {stop['where']}",
        f"- Co zrobić: {stop['action']}",
        "",
        "## Uruchomienie procesu",
        "",
        "- Proces: Przygotowanie pliku zbiorczego",
        f"- Okres: {PERIOD}",
        "- Tryb: DRY-RUN",
        "",
        "## Narzędzie",
        "",
        f"- Commit: {TOOL_COMMIT}",
        f"- Odcisk problemu: {fingerprint[1]}",
        "",
        "## Diagnoza",
        "",
        f"Wyjaśnienie: BRAK_WZORCA · {stop['what']}",
        "",
        "| Sprawdzenie | Wynik | Szczegóły |",
        "| --- | --- | --- |",
        *(f"| {check['label']} | {results[check['state']]} | {check['detail']} |" for check in diagnosis["checks"]),
        "",
        "## Dziennik Centrum rozliczeń",
        "",
        "```text",
        *log_lines[:diagnosed],
        "```",
    ]
    assert body.endswith("```\n")


def test_zgloszenie_nie_ma_tresci_wierszy_wyjatku_pelnych_sciezek_ani_klucza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)

    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    monkeypatch.setattr(preparation_register, "read_register", fail_unexpectedly)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    monkeypatch.undo()
    diagnose(centrum, run_id)
    send(centrum, run_id)

    [report] = centrum.surroundings.report_box.sent
    text = report.title + report.body
    for forbidden in ("SYN-", "nieprzewidziany błąd", KEY, str(tmp_path), tmp_path.as_posix(), "Traceback"):
        assert forbidden not in text
    assert KEY not in centrum.log_path.read_text(encoding="utf-8")


MARKER = "SYN-SLAD-158 treść wyjątku z Rejestru zleceń"


def raise_with_marker(*args: object, **kwargs: object) -> NoReturn:
    raise KeyError(MARKER)


def trace_section(body: str) -> list[str]:
    """Linie sekcji śladu wywołań w treści Zgłoszenia; pusta lista, gdy jej nie ma."""

    lines = body.splitlines()
    if "## Ślad wywołań" not in lines:
        return []
    section = lines[lines.index("## Ślad wywołań") + 1 :]
    return section[: next((i for i, line in enumerate(section) if line.startswith("## ")), len(section))]


def test_nieoczekiwany_wyjatek_daje_w_zgloszeniu_typ_i_ramki_kodu_narzedzia_bez_tresci_wyjatku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    monkeypatch.setattr(preparation_register, "read_register", raise_with_marker)
    stopped = run_to_end(centrum, dry_run=True)
    monkeypatch.undo()
    run_id = stopped["run"]["id"]

    preview = diagnose(centrum, run_id)["report"]
    send(centrum, run_id)

    assert stopped["result"]["ending"] == "unexpected"
    section = trace_section(preview["body"])
    assert "- Wyjątek: KeyError" in section
    frames = section[section.index("```text") + 1 : section.index("```")]
    assert all(re.fullmatch(r"(src|tests)/[\w/]+\.py:\d+ w \S+", frame) for frame in frames), frames
    assert re.fullmatch(r"src/rozliczenia/process_run\.py:\d+ w _run_engine", frames[0])
    assert any(re.fullmatch(r"src/rozliczenia/collective_preparation\.py:\d+ w <lambda>", frame) for frame in frames)
    raising_line = raise_with_marker.__code__.co_firstlineno + 1
    assert frames[-1] == f"tests/test_centrum_zgloszenie.py:{raising_line} w raise_with_marker"
    [report] = centrum.surroundings.report_box.sent
    assert report.body == preview["body"]
    for text in (
        preview["title"] + preview["body"],
        centrum.log_path.read_text(encoding="utf-8"),
        centrum.metrics_path.read_text(encoding="utf-8"),
        centrum.client.get("/api/runs/current").text,
    ):
        assert "SYN-SLAD" not in text
        assert str(Path.home()) not in text


def test_zatrzymanie_z_komunikatem_procesu_nie_ma_sladu_wywolan(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)

    report = diagnose(centrum, stopped["run"]["id"])["report"]

    assert trace_section(report["body"]) == []


def unsent_files(centrum: PreparingCentrum) -> dict[str, str]:
    directory = centrum.tmp_path / "config" / "zgloszenia"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.md"))}


def test_bez_klucza_zgloszenie_zostaje_w_pliku_a_ponowna_proba_z_kluczem_je_wysyla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    saved = send(centrum, run_id)

    name = f"Zgłoszenie BLAD_PLANU {PERIOD}.md"
    assert saved == {
        "state": "saved",
        "message": {
            "what": "Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.",
            "where": f"plik {name}, folder zgloszenia",
            "action": "Prześlij ten plik Maksowi mailem. Gdy Maks wpisze klucz do Zgłoszeń, kliknij „Spróbuj ponownie”.",
        },
    }
    assert unsent_files(centrum) == {name: f"# {preview['title']}\n\n{preview['body']}"}
    assert centrum.surroundings.report_box.sent == []
    log = centrum.log_path.read_text(encoding="utf-8")
    assert f"zgloszenie-zapisane proces=preparation okres={PERIOD} kod=ZGLOSZENIE_BEZ_KLUCZA" in log

    with_key(centrum)
    again = send(centrum, run_id)

    assert again == {"state": "sent"}
    assert [report.body for report in centrum.surroundings.report_box.sent] == [preview["body"]]
    assert unsent_files(centrum) == {}


def test_zgloszenie_ktorego_nie_da_sie_ani_wyslac_ani_zapisac_w_pliku_daje_komunikat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, run_id)
    (tmp_path / "config" / "zgloszenia").write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda

    state = send(centrum, run_id)

    assert state == {
        "state": "saved",
        "message": {
            "what": "Nie wysłano Zgłoszenia i nie udało się zapisać go w pliku na tym komputerze.",
            "where": "folder zgloszenia",
            "action": "Rozwiń „Co zostanie wysłane”, skopiuj treść i prześlij ją Maksowi mailem.",
        },
    }
    log = centrum.log_path.read_text(encoding="utf-8")
    assert f"zgloszenie-niezapisane proces=preparation okres={PERIOD} przyczyna=ZGLOSZENIE_BEZ_KLUCZA" in log


@pytest.mark.parametrize(
    ("failure", "what"),
    [
        (Refused(), "Nie wysłano Zgłoszenia: klucz do Zgłoszeń wygasł albo jest nieważny."),
        (Unreachable(), "Nie wysłano Zgłoszenia: brak połączenia z GitHubem."),
    ],
    ids=["odmowa", "brak-polaczenia"],
)
def test_nieudana_wysylka_zapisuje_zgloszenie_w_pliku_a_ponowna_proba_je_wysyla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: SendOutcome, what: str
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    centrum.surroundings.report_box.outcomes.append(failure)
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    saved = send(centrum, run_id)

    assert (saved["state"], saved["message"]["what"]) == ("saved", what)
    assert list(unsent_files(centrum).values()) == [f"# {preview['title']}\n\n{preview['body']}"]

    assert send(centrum, run_id) == {"state": "sent"}
    assert (len(centrum.surroundings.report_box.keys), len(centrum.surroundings.report_box.sent), unsent_files(centrum)) == (2, 1, {})


def test_plik_niewyslanego_zgloszenia_ktorego_nie_da_sie_usunac_nie_cofa_wyslania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, run_id)
    # Na miejscu pliku niewysłanego Zgłoszenia coś, czego nie da się usunąć jak pliku (w Windows: plik otwarty).
    (tmp_path / "config" / "zgloszenia" / f"Zgłoszenie BLAD_PLANU {PERIOD}.md").mkdir(parents=True)

    state = send(centrum, run_id)

    assert (state, current_report(centrum), send(centrum, run_id)) == ({"state": "sent"},) * 3
    assert len(centrum.surroundings.report_box.sent) == 1


def current_report(centrum: PreparingCentrum) -> object:
    view = centrum.client.get("/api/runs/current").json()
    return view["result"]["report"]


def test_wyslanie_jest_raz_na_zatrzymanie_a_wynik_uruchomienia_pokazuje_potwierdzenie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    assert current_report(centrum) == {"state": "ready"}
    diagnose(centrum, run_id)

    first, second = send(centrum, run_id), send(centrum, run_id)

    assert first == second == {"state": "sent"}
    assert len(centrum.surroundings.report_box.keys) == 1
    assert current_report(centrum) == {"state": "sent"}


def test_ponowna_diagnoza_po_wyslaniu_pokazuje_wyslane_zgloszenie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, run_id)
    send(centrum, run_id)

    diagnose(centrum, run_id)

    assert (current_report(centrum), send(centrum, run_id)) == ({"state": "sent"}, {"state": "sent"})
    assert len(centrum.surroundings.report_box.sent) == 1


def test_wyslane_zgloszenie_czeka_na_naprawe_takze_po_restarcie_centrum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    body = diagnose(centrum, run_id)["report"]["body"]
    send(centrum, run_id)

    centrum.restart()
    again = stopped_for_maks(centrum, monkeypatch)

    assert current_report(centrum) == {"state": "waiting"}
    diagnose(centrum, again)
    assert send(centrum, again) == {"state": "waiting"}
    assert len(centrum.surroundings.report_box.keys) == 1
    sent = json.loads((tmp_path / "config" / "zgloszenia-wyslane.json").read_text(encoding="utf-8"))
    [fingerprint] = [line.removeprefix("- Odcisk problemu: ") for line in body.splitlines() if "Odcisk problemu" in line]
    assert sent == [{"fingerprint": fingerprint, "number": 1, "commit": TOOL_COMMIT, "state": "open"}]


def test_zatrzymanie_dla_taty_nie_proponuje_zgloszenia(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    (centrum.fixture.register_path.parent / f"~${centrum.fixture.register_path.name}").touch()

    view = run_to_end(centrum, dry_run=True)

    assert (view["result"]["stop_kind"], view["result"]["report"]) == ("for_tata", None)
    assert centrum.client.post(f"/api/runs/{view['run']['id']}/report").status_code == 409


def test_wyslanie_bez_diagnozy_jest_odrzucone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)

    refused = centrum.client.post(f"/api/runs/{run_id}/report")

    assert (refused.status_code, refused.json()) == (
        409,
        {"message": "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”."},
    )
    assert centrum.surroundings.report_box.keys == []


def test_konfiguracja_pokazuje_stan_klucza_do_zgloszen_bez_jego_wartosci(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    missing = centrum.client.get("/api/configuration").json()
    with_key(centrum)

    ready = centrum.client.get("/api/configuration")

    assert (missing["reports"], ready.json()["reports"]) == ("missing_key", "ready")
    assert KEY not in ready.text


WAITING = {"state": "waiting"}


def test_kolejne_uruchomienie_z_otwartym_zgloszeniem_tego_problemu_czeka_na_naprawe_bez_drugiej_wysylki(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    first = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, first)
    send(centrum, first)

    again = stopped_for_maks(centrum, monkeypatch)

    assert current_report(centrum) == WAITING
    diagnose(centrum, again)
    assert (current_report(centrum), send(centrum, again)) == (WAITING, WAITING)
    assert len(centrum.surroundings.report_box.sent) == 1


def test_otwarte_zgloszenie_wyslane_spoza_tego_komputera_tez_czeka_na_naprawe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    first = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, first)
    send(centrum, first)
    (tmp_path / "config" / "zgloszenia-wyslane.json").unlink()
    centrum.restart()

    again = stopped_for_maks(centrum, monkeypatch)
    assert current_report(centrum) == {"state": "ready"}
    diagnose(centrum, again)

    assert current_report(centrum) == WAITING
    assert send(centrum, again) == WAITING
    assert len(centrum.surroundings.report_box.sent) == 1
    assert f"zgloszenie-czeka proces=preparation okres={PERIOD} numer=1" in centrum.log_path.read_text(encoding="utf-8")


def test_inny_komunikat_wysyla_sie_osobno_obok_otwartego_zgloszenia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    first = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, first)
    send(centrum, first)
    monkeypatch.undo()
    centrum.fixture.collective_template_path.unlink()

    other = run_to_end(centrum, dry_run=True)["run"]["id"]

    assert current_report(centrum) == {"state": "ready"}
    diagnose(centrum, other)
    assert send(centrum, other) == {"state": "sent"}
    sent_codes = [report.title.split(":")[0] for report in centrum.surroundings.report_box.sent]
    assert sent_codes == ["BLAD_PLANU", "BRAK_WZORCA"]


def test_po_zamknieciu_zgloszenia_powracajacy_problem_wysyla_nowe_z_odnosnikiem_do_poprzedniego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    first = stopped_for_maks(centrum, monkeypatch)
    first_body = diagnose(centrum, first)["report"]["body"]
    send(centrum, first)
    box.close(1)

    again = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, again)["report"]

    assert current_report(centrum) == {"state": "ready"}
    assert "- Poprzednie Zgłoszenie: #1" in preview["body"].splitlines()
    assert "Poprzednie Zgłoszenie" not in first_body
    assert send(centrum, again) == {"state": "sent"}
    assert [report.body for report in box.sent] == [first_body, preview["body"]]
    sent = json.loads((tmp_path / "config" / "zgloszenia-wyslane.json").read_text(encoding="utf-8"))
    assert [entry["number"] for entry in sent] == [1, 2]


def test_zgloszenie_zamkniete_wedlug_powiadomienia_o_naprawie_nie_czeka_juz_po_restarcie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    first = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, first)
    send(centrum, first)
    box.close(1)
    assert centrum.client.get("/api/reports/repair").json() == {"repaired": True}
    centrum.restart()

    again = stopped_for_maks(centrum, monkeypatch)

    assert current_report(centrum) == {"state": "ready"}
    preview = diagnose(centrum, again)["report"]
    assert "- Poprzednie Zgłoszenie: #1" in preview["body"].splitlines()
    assert send(centrum, again) == {"state": "sent"}
    sent = json.loads((tmp_path / "config" / "zgloszenia-wyslane.json").read_text(encoding="utf-8"))
    assert [(entry["number"], entry["state"]) for entry in sent] == [(1, "closed"), (2, "open")]
    assert centrum.client.get("/api/reports/repair").json() == {"repaired": True}


def test_bez_odpowiedzi_skrzynki_wyslany_problem_dalej_czeka_na_naprawe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    first = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, first)
    send(centrum, first)
    box.close(1)
    box.search_failure = Unreachable()

    again = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, again)

    assert current_report(centrum) == WAITING
    assert len(box.sent) == 1


def test_gdy_skrzynka_nie_odpowiada_na_pytanie_o_otwarte_zgloszenie_zgloszenie_zostaje_w_pliku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    centrum.surroundings.report_box.search_failure = Unreachable()
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    saved = send(centrum, run_id)

    assert (saved["state"], saved["message"]["what"]) == ("saved", "Nie wysłano Zgłoszenia: brak połączenia z GitHubem.")
    assert list(unsent_files(centrum).values()) == [f"# {preview['title']}\n\n{preview['body']}"]
    assert centrum.surroundings.report_box.keys == []


def test_diagnoza_bez_odpowiedzi_skrzynki_konczy_sie_w_kilka_sekund_a_wysylka_i_tak_pyta_skrzynke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    box.search_hold = threading.Event()
    run_id = stopped_for_maks(centrum, monkeypatch)
    release = threading.Timer(8, box.search_hold.set)  # bez limitu Diagnoza czekałaby na skrzynkę
    release.start()
    started = time.monotonic()

    try:
        diagnose(centrum, run_id)
        took = time.monotonic() - started
    finally:
        box.search_hold.set()
        release.cancel()

    assert took < 5
    assert current_report(centrum) == {"state": "ready"}
    assert box.keys == []
    assert send(centrum, run_id) == {"state": "sent"}
    assert len(box.sent) == 1


def test_spozniona_odpowiedz_skrzynki_w_diagnozie_to_brak_odpowiedzi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    first = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, first)
    send(centrum, first)
    box.close(1)
    box.search_hold = threading.Event()
    again = stopped_for_maks(centrum, monkeypatch)

    try:
        diagnose(centrum, again)
    finally:
        box.search_hold.set()

    assert current_report(centrum) == WAITING


def test_dwa_klikniecia_w_trakcie_wysylki_daja_jedno_zgloszenie_a_centrum_odpowiada_dalej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    run_id = stopped_for_maks(centrum, monkeypatch)
    diagnose(centrum, run_id)
    box.search_hold = threading.Event()
    box.searching.clear()

    with ThreadPoolExecutor(3) as pool:
        try:
            clicks = [pool.submit(send, centrum, run_id) for _ in range(2)]
            assert box.searching.wait(5)
            during_send = pool.submit(centrum.client.get, "/api/reports/repair").result(timeout=2)
        finally:
            box.search_hold.set()
        answers = [click.result(timeout=10) for click in clicks]

    assert during_send.json() == {"repaired": False}
    assert answers == [{"state": "sent"}, {"state": "sent"}]
    assert len(box.sent) == 1
