"""Kolejka Skrzynki Zgłoszeń (``outbox``): wysyłki, które Centrum wysyła samo, w częściach i po porażce skrzynki.

Seam z dwoma wejściami (Kontrola ilości teraz, Logi Uruchomienia od #320), więc podział na części i kolejka są
sprawdzone tu raz, przez ``Post`` i ``Outbox``, na fałszywej skrzynce. Treść ponad 65 536 znaków jest przez HTTP
Centrum nieosiągalna rozsądnym kosztem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import Frame, Outbox, PeriodThread, Post
from rozliczenia.centrum.report_box import COMMENT_LIMIT, Unreachable

from tests.fixtures.centrum import FakeReportBox
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


class Queue:
    def __init__(self, tmp_path: Path, box: FakeReportBox, key: str | None = KEY) -> None:
        self.directory = tmp_path / "config" / "zgloszenia" / "kolejka"
        self.log_path = tmp_path / "logs" / "centrum-rozliczen.log"
        self.box = box
        self.outbox = Outbox(self.directory, box, lambda: key, CentrumLog(self.log_path))

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


def test_bez_sieci_wysylka_czeka_w_pliku_i_idzie_przy_nastepnej_wysylce_po_kolei(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Unreachable()]))

    queue.outbox.post(post(["pierwsza\n"]))
    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    [waiting] = queue.files()
    assert waiting.endswith(f"-kontrola-ilosci-{RUN_ID[:8]}.json")
    assert "pierwsza" not in queue.log()

    queue.outbox.post(post(["druga\n"]))

    assert queue.box.wait_until(lambda box: len(box.issues) == 2)
    assert [issue.body.splitlines()[-1] for issue in queue.box.issues] == ["pierwsza", "druga"]
    assert wait_for(lambda: queue.files() == [])


def test_bez_klucza_wysylka_czeka_w_pliku_bez_pytania_skrzynki(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(), key=None)

    queue.outbox.post(post(["treść\n"]))

    waiting = "skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna=brak-klucza"
    assert wait_for(lambda: waiting in queue.log())
    assert len(queue.files()) == 1
    assert queue.box.keys == []


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
