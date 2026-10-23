"""Kolejka Skrzynki Zgłoszeń (``outbox``): wysyłki, które Centrum wysyła samo, w częściach i po porażce skrzynki.

Seam z dwoma wejściami (Kontrola ilości teraz, Logi Uruchomienia od #320), więc podział na części i kolejka są
sprawdzone tu raz, przez ``Post`` i ``Outbox``, na fałszywej skrzynce. Treść ponad 65 536 znaków jest przez HTTP
Centrum nieosiągalna rozsądnym kosztem.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import threading

import pytest

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import Frame, Outbox, PeriodThread, Post
from rozliczenia.centrum.report_box import COMMENT_LIMIT, Refused, Rejected, Unreachable

from tests.fixtures.centrum import FakeIssue, FakeReportBox
from tests.fixtures.potomne import wait_for

KEY = "github_pat_SYNTETYCZNY_KLUCZ"
THREAD = PeriodThread(
    label="kontrola-ilosci",
    line="- Kontrola ilości okresu: 08_14_09_2026",
    closed="new_issue",
    title="Kontrola ilości 08_14_09_2026: 3 różnice",
)
RUN_ID = "3f2a9c1b8e7d4f0a9b1c2d3e4f5a6b7c"


def unframed(_number: int, _count: int, text: str) -> str:
    return text


def numbered(number: int, count: int, text: str) -> str:
    return f"Część {number}/{count}\n\n{text}"


def post(blocks: list[str], *, frame: Frame = numbered) -> Post:
    return Post.of(THREAD, period="08_14_09_2026", run_id=RUN_ID, blocks=blocks, frame=frame)


ROOT = Path(__file__).resolve().parents[1]


class Queue:
    """Kolejka na folderze w ``tmp_path``; ``waiting_at_pass`` to liczba linii „skrzynka-czeka” na początku każdego
    przejścia (kolejka pyta o klucz raz na przejście, a przejścia idą po kolei w jednym wątku)."""

    def __init__(self, tmp_path: Path, box: FakeReportBox, key: str | None = KEY) -> None:
        self.directory = tmp_path / "config" / "zgloszenia" / "kolejka"
        self.log_path = tmp_path / "logs" / "centrum-rozliczen.log"
        self.box = box
        self.key = key
        self.waiting_at_pass: list[int] = []
        self.outbox = self.restarted()

    def restarted(self) -> Outbox:
        """Kolejka nowego startu Centrum na tym samym folderze."""

        return Outbox(self.directory, self.box, self._pass_key, CentrumLog(self.log_path))

    def _pass_key(self) -> str | None:
        self.waiting_at_pass.append(self.log().count("skrzynka-czeka"))
        return self.key

    def queued(self, *texts: str) -> list[str]:
        """Pliki kolejki z poprzedniej pracy Centrum, po jednym na tekst, w tej kolejności."""

        self.directory.mkdir(parents=True, exist_ok=True)
        names = [f"20261023T1015{second:02d}000000Z-0001-kontrola-ilosci-3f2a9c1b.json" for second in range(len(texts))]
        for name, text in zip(names, texts, strict=True):
            (self.directory / name).write_text(post([text]).to_json(), encoding="utf-8")
        return names

    def files(self) -> list[str]:
        return sorted(path.name for path in self.directory.glob("*"))

    def log(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.is_file() else ""


def test_bloki_ktore_sie_mieszcza_ida_w_calosci_w_kolejnosci() -> None:
    first, second, third = "a" * 30_000, "b" * 30_000, "c" * 30_000

    assert post([first, second, third], frame=unframed).parts == (first + second, third)


def test_blok_dluzszy_niz_komentarz_jest_ciety_a_nic_nie_ginie() -> None:
    blocks = ["poczatek\n", "x" * 150_000, "koniec\n"]

    parts = post(blocks, frame=unframed).parts

    assert "".join(parts) == "".join(blocks)
    assert len(parts) == 3
    assert all(len(part) <= COMMENT_LIMIT for part in parts)


def test_czesc_ponad_limit_komentarza_to_blad_programu() -> None:
    with pytest.raises(ValueError, match="komentarzu"):
        Post.of(
            THREAD,
            period="08_14_09_2026",
            run_id=RUN_ID,
            blocks=["x" * 60_000],
            frame=lambda _number, _count, text: "nagłówek " * 1_000 + text,
        )


def test_granica_tresci_liczy_znaki_a_nie_bajty_takze_z_polskimi_literami() -> None:
    first_line = len(f"{THREAD.line}\n\n")

    def opening(text: str) -> Post:
        return Post(THREAD, period="08_14_09_2026", run_id=RUN_ID, header=None, parts=(text,))

    longest = opening("ą" * (COMMENT_LIMIT - first_line))

    assert len(longest.opening()[0]) == COMMENT_LIMIT
    assert len(longest.opening()[0].encode("utf-8")) > COMMENT_LIMIT
    with pytest.raises(ValueError, match="komentarzu"):
        opening("ą" * (COMMENT_LIMIT - first_line + 1))


def test_wysylka_wraca_z_pliku_kolejki_taka_sama() -> None:
    queued = post(["## Różnice\n", "| Q | 2 | 1 |\n"])

    assert Post.from_json(queued.to_json()) == queued


@pytest.mark.parametrize(
    "text",
    ["{", "[]", '{"schema_version": 2}', post(["x"]).to_json().replace('"kontrola-ilosci"', '"inna-etykieta"')],
    ids=["urwany", "nie-obiekt", "nowszy-schemat", "nieznana-etykieta"],
)
def test_plik_kolejki_nieznany_albo_uszkodzony_nie_jest_wysylka(text: str) -> None:
    assert Post.from_json(text) is None


def test_wysylka_ponad_limit_to_issue_z_pierwsza_czescia_i_komentarze_z_kolejnymi(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    blocks = ["## Różnice\n", "x" * 40_000, "y" * 40_000]

    queue.outbox.post(post(blocks))

    assert queue.box.wait_until(lambda box: bool(box.issues) and len(box.issues[0].comments) == 1)
    [issue] = queue.box.issues_with("kontrola-ilosci")
    assert issue.title == THREAD.title
    assert issue.body.startswith(f"{THREAD.line}\n\nCzęść 1/2\n\n## Różnice\n")
    assert issue.comments == [f"Część 2/2\n\n{'y' * 40_000}"]
    assert wait_for(lambda: queue.files() == [])
    assert "skrzynka-wyslano etykieta=kontrola-ilosci okres=08_14_09_2026 numer=1" in queue.log()
    assert "x" * 10 not in queue.log()


def test_bez_sieci_wysylka_czeka_w_pliku_i_idzie_przy_nastepnej_wysylce_po_kolei_do_issue_okresu(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Unreachable()]))

    queue.outbox.post(post(["pierwsza\n"]))
    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    [waiting] = queue.files()
    assert waiting.endswith(f"-kontrola-ilosci-{RUN_ID[:8]}.json")
    assert "pierwsza" not in queue.log()

    queue.outbox.post(post(["druga\n"]))

    assert queue.box.wait_until(lambda box: bool(box.issues) and bool(box.issues[0].comments))
    [issue] = queue.box.issues
    assert issue.body.splitlines()[-1] == "pierwsza"
    assert issue.comments == ["Część 1/1\n\ndruga\n"]
    assert wait_for(lambda: queue.files() == [])


LOGS = PeriodThread(
    label="logi-uruchomienia",
    line="- Logi Uruchomień okresu: 08_14_09_2026",
    closed="reuse",
    title="Logi Uruchomień 08_14_09_2026",
)


def test_watek_ktory_zostaje_po_zamknieciu_dostaje_czesci_jako_komentarze_w_zamknietym_issue(tmp_path: Path) -> None:
    closed = FakeIssue(7, LOGS.label, LOGS.title, f"{LOGS.line}\n\nLogi Uruchomień tego okresu.\n")
    queue = Queue(tmp_path, FakeReportBox(issues=[closed], closed={7}))

    queue.outbox.post(
        Post.of(LOGS, period="08_14_09_2026", run_id=RUN_ID, blocks=["logi\n"], frame=numbered, header="Nagłówek")
    )

    assert queue.box.wait_until(lambda box: bool(closed.comments))
    assert queue.box.issues == [closed]
    assert closed.comments == ["Część 1/1\n\nlogi\n"]
    assert wait_for(lambda: queue.files() == [])


def test_bez_klucza_wysylka_czeka_w_pliku_bez_pytania_skrzynki(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(), key=None)

    queue.outbox.post(post(["treść\n"]))

    waiting = "skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna=brak-klucza"
    assert wait_for(lambda: waiting in queue.log())
    assert len(queue.files()) == 1
    assert queue.box.keys == []


def test_bez_klucza_przejscie_kolejki_daje_jedna_linie_dziennika_przy_wielu_plikach(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(), key=None)
    queue.queued("pierwsza\n", "druga\n", "trzecia\n")

    queue.outbox.resume()
    assert wait_for(lambda: len(queue.waiting_at_pass) == 1)
    queue.outbox.send_in_background()
    assert wait_for(lambda: len(queue.waiting_at_pass) == 2)

    assert queue.waiting_at_pass == [0, 1]
    assert "skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna=brak-klucza" in queue.log()
    assert len(queue.files()) == 3
    assert queue.box.keys == []


@pytest.mark.parametrize("failure", [Unreachable(), Refused()], ids=["brak-sieci", "odmowa-klucza"])
def test_brak_sieci_albo_odmowa_klucza_zatrzymuje_przejscie_z_jedna_linia_dziennika(
    tmp_path: Path, failure: Unreachable | Refused
) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=failure))
    queue.queued("pierwsza\n", "druga\n", "trzecia\n")

    queue.outbox.resume()
    assert wait_for(lambda: len(queue.waiting_at_pass) == 1)
    queue.outbox.send_in_background()
    assert wait_for(lambda: len(queue.waiting_at_pass) == 2)

    assert queue.waiting_at_pass == [0, 1]
    assert len(queue.files()) == 3


def test_tresc_ktorej_skrzynka_odmawia_zostaje_w_kolejce_a_nastepna_wychodzi_w_tym_samym_przejsciu(
    tmp_path: Path,
) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Rejected()]))
    refused, _sent = queue.queued("odrzucona\n", "przyjęta\n")

    queue.outbox.resume()

    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert queue.box.issues[0].body.splitlines()[-1] == "przyjęta"
    assert wait_for(lambda: queue.files() == [refused])
    assert (
        f"skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna=odmowa plik={refused}" in queue.log()
    )
    assert "brak-sieci" not in queue.log()

    queue.restarted().resume()

    assert queue.box.wait_until(lambda box: len(box.issues[0].comments) == 1)
    assert queue.box.issues[0].comments == ["Część 1/1\n\nodrzucona\n"]
    assert wait_for(lambda: queue.files() == [])


def test_wysylka_dodana_w_trakcie_przejscia_wychodzi_bez_kolejnego_budzenia(tmp_path: Path) -> None:
    hold = threading.Event()
    queue = Queue(tmp_path, FakeReportBox(search_hold=hold))

    queue.outbox.post(post(["pierwsza\n"]))
    assert queue.box.searching.wait(30), "przejście kolejki nie zaczęło pytać skrzynki"
    queue.outbox.post(post(["druga\n"]))
    hold.set()

    assert queue.box.wait_until(lambda box: bool(box.issues) and len(box.issues[0].comments) == 1)
    assert queue.box.issues[0].comments == ["Część 1/1\n\ndruga\n"]
    assert wait_for(lambda: queue.files() == [])


def test_gdy_skrzynka_odmawia_szukania_issue_okresu_wysylka_czeka_w_pliku_bez_nowego_issue(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Refused()))

    queue.outbox.post(post(["treść\n"]))

    assert wait_for(lambda: "przyczyna=odmowa" in queue.log())
    assert len(queue.files()) == 1
    assert (queue.box.issues, queue.box.keys) == ([], [])


def test_nieudany_komentarz_zostawia_wysylke_w_pliku(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(comment_outcomes=[Unreachable()]))

    queue.outbox.post(post(["x" * 40_000, "y" * 40_000]))

    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    assert len(queue.files()) == 1


def test_wysylka_ktorej_nie_da_sie_zapisac_przepada_bez_wyjatku(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.parent.mkdir(parents=True)
    queue.directory.write_text("plik zamiast folderu", encoding="utf-8")

    queue.outbox.post(post(["treść\n"]))

    assert "nieoczekiwany-wyjatek typ=" in queue.log()
    assert "zapis wysyłki do Skrzynki Zgłoszeń" in queue.log()
    assert queue.box.issues == []


def test_wysylka_zapisana_przez_wersje_z_273_wychodzi_po_starcie(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    shutil.copy(
        ROOT / "tests" / "fixtures" / "kolejka-v1-kontrola-ilosci.json",
        queue.directory / "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json",
    )

    queue.outbox.resume()

    assert queue.box.wait_until(lambda box: bool(box.issues))
    [issue] = queue.box.issues_with("kontrola-ilosci")
    assert issue.title == "Kontrola ilości 08_14_09_2026: 1 różnica"
    assert issue.body == (
        "- Kontrola ilości okresu: 08_14_09_2026\n\n"
        "Kontrola ilości z Centrum rozliczeń (plik kolejki w wersji 1 z #273).\n\n"
        "## Różnice\n\n| Kolumna | Reguła | Tata |\n| --- | --- | --- |\n| Q | 2 | 1 |\n"
    )
    assert wait_for(lambda: queue.files() == [])


def test_zapis_urwany_przez_utrate_zasilania_znika_przy_starcie_i_nie_jest_wysylany(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    (queue.directory / "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json.tmp").write_text(
        '{"schema_version": 1, "thr', encoding="utf-8"
    )

    queue.outbox.resume()

    assert queue.files() == []
    assert queue.box.keys == []


def test_plik_kolejki_ktorego_nie_da_sie_odczytac_zostaje_z_jednym_wpisem_i_nie_wstrzymuje_innych(
    tmp_path: Path,
) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    broken = "00000000T000000000000Z-0001-kontrola-ilosci-3f2a9c1b.json"
    (queue.directory / broken).write_text('{"schema_version": 2}', encoding="utf-8")

    queue.outbox.post(post(["treść\n"]))
    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: queue.files() == [broken])
    queue.outbox.post(post(["druga\n"]))
    assert queue.box.wait_until(lambda box: len(box.issues[0].comments) == 1)
    assert wait_for(lambda: queue.files() == [broken])

    assert queue.log().count(f"skrzynka-nieczytelny plik={broken}") == 1
    assert "nieoczekiwany-wyjatek" not in queue.log()


def test_wyslanej_wysylki_ktorej_nie_da_sie_usunac_skrzynka_nie_dostaje_drugi_raz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    unlink = Path.unlink

    def locked(path: Path, missing_ok: bool = False) -> None:
        if path.parent == queue.directory and path.suffix == ".json":
            raise PermissionError("plik otwarty w innym programie")
        unlink(path, missing_ok=missing_ok)

    def failed_removals() -> int:
        return queue.log().count("usunięcie wysłanej wysyłki")

    monkeypatch.setattr(Path, "unlink", locked)
    queue.outbox.post(post(["pierwsza\n"]))
    assert wait_for(lambda: failed_removals() == 1)
    queue.outbox.post(post(["druga\n"]))
    assert wait_for(lambda: failed_removals() == 2)
    queue.restarted().resume()
    assert wait_for(lambda: failed_removals() == 4)
    monkeypatch.setattr(Path, "unlink", unlink)
    queue.restarted().resume()

    assert wait_for(lambda: queue.files() == [])
    [issue] = queue.box.issues
    assert [issue.body.splitlines()[-1], *(comment.splitlines()[-1] for comment in issue.comments)] == [
        "pierwsza",
        "druga",
    ]
    assert queue.log().count("skrzynka-wyslano") == 2
    assert failed_removals() == 4


def test_po_wyslaniu_kolejka_zna_adres_pierwszego_komentarza_uruchomienia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Unreachable()]))
    logs = PeriodThread(
        label="logi-uruchomienia", line="- Logi Uruchomienia okresu: 08_14_09_2026", closed="reuse", title="Logi"
    )
    run_logs = Post.of(
        logs, period="08_14_09_2026", run_id=RUN_ID, blocks=["podsumowanie\n"], frame=numbered, header="Logi okresu"
    )

    queue.outbox.post(run_logs)
    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    waiting = queue.outbox.delivered(RUN_ID, "logi-uruchomienia")
    queue.outbox.resume()
    assert queue.box.wait_until(lambda box: bool(box.issues) and bool(box.issues[0].comments))
    assert wait_for(lambda: queue.outbox.delivered(RUN_ID, "logi-uruchomienia") is not None)

    assert waiting is None
    assert queue.outbox.delivered(RUN_ID, "logi-uruchomienia") == (
        "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/1#issuecomment-1"
    )
    assert queue.outbox.delivered(RUN_ID, "kontrola-ilosci") is None
    assert queue.outbox.delivered("inne-uruchomienie", "logi-uruchomienia") is None
