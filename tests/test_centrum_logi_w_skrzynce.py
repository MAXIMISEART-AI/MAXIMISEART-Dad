"""Logi Uruchomienia w Skrzynce Zgłoszeń (ADR 0015, #320) przez HTTP API Centrum z fałszywą Skrzynką.

Maks czyta w Skrzynce jedno issue na okres, a w nim komentarz na każde Uruchomienie: podsumowanie i JSON, który
sklejony z części daje plik Logów z komputera taty. Diagnoza (#321) dopisuje się do pliku i dodaje kolejny komentarz
z całymi Logami, a Zgłoszenie prowadzi do komentarza Logów swojego Uruchomienia. Żaden test nie łączy się z GitHubem.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from collections.abc import Callable
from typing import Any, Final

import pytest

from rozliczenia.centrum import app
from rozliczenia.centrum.report_box import REPOSITORY, Refused, Unreachable

from tests.fixtures.centrum import TOOL_COMMIT, FakeIssue, FakeReportBox
from tests.fixtures.centrum_processes import SettlingCentrum, run_to_end, settling_centrum, stopped_for_maks
from tests.fixtures.potomne import wait_for
from tests.fixtures.settlement import PERIOD

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
LABEL: Final = "logi-uruchomienia"
LINE = f"- Logi Uruchomienia okresu: {PERIOD}"
JSON_PART = re.compile(r"\n````json\n(.*)\n````\n\n</details>\n\Z", re.DOTALL)


def watched_centrum(tmp_path: Path, *, key: bool = True, include_unmapped: bool = False) -> SettlingCentrum:
    """Centrum, którego fałszywa Skrzynka pokazuje Logi Uruchomienia w ``issues``, a nie w ruchu w tle."""

    centrum = settling_centrum(tmp_path, include_unmapped=include_unmapped)
    box(centrum).background = frozenset()
    if key:
        write_key(centrum)
    return centrum


def write_key(centrum: SettlingCentrum) -> None:
    (centrum.tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")


def box(centrum: SettlingCentrum) -> FakeReportBox:
    return centrum.surroundings.report_box


def threads(fake: FakeReportBox) -> list[FakeIssue]:
    return [issue for issue in fake.issues_with(LABEL) if issue.title == f"Logi Uruchomienia {PERIOD}"]


def thread_with(centrum: SettlingCentrum, comments: int) -> FakeIssue:
    """Jedyne issue Logów okresu, gdy ma już ``comments`` komentarzy."""

    def arrived(fake: FakeReportBox) -> bool:
        found = threads(fake)
        return len(found) == 1 and len(found[0].comments) == comments

    assert box(centrum).wait_until(arrived), f"issue Logów okresu nie ma {comments} komentarzy: {box(centrum).issues}"
    [thread] = threads(box(centrum))
    return thread


def local_logs(centrum: SettlingCentrum, run_id: str) -> str:
    [path] = (centrum.log_path.parent / "uruchomienia").glob(f"*-{run_id}.json")
    return path.read_text(encoding="utf-8")


def sent_json(comments: list[str]) -> str:
    """JSON Logów sklejony z bloków ``<details>`` kolejnych komentarzy."""

    parts = [JSON_PART.search(comment) for comment in comments]
    assert all(parts), comments
    return "".join(part.group(1) for part in parts if part)


def queued_logs(centrum: SettlingCentrum) -> list[Path]:
    return sorted((centrum.tmp_path / "config" / "zgloszenia" / "kolejka").glob(f"*-{LABEL}-*"))


def test_pierwsze_uruchomienie_okresu_zaklada_issue_logow_a_kolejne_dopisuja_komentarze_takze_po_zamknieciu(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    foreign = [
        FakeIssue(1, LABEL, "Logi Uruchomienia 01_07_09_2026", "- Logi Uruchomienia okresu: 01_07_09_2026\n"),
        FakeIssue(2, LABEL, f"Logi Uruchomienia {PERIOD}0", f"- Logi Uruchomienia okresu: {PERIOD}0\n"),
        FakeIssue(3, "zgloszenie", "BRAK_WZORCA: Nie znaleziono wzorca.", f"## Komunikat\n\n{LINE}\n"),
    ]
    box(centrum).issues.extend(foreign)

    first = run_to_end(centrum, dry_run=True)
    thread = thread_with(centrum, comments=1)
    second = run_to_end(centrum, dry_run=True)
    thread_with(centrum, comments=2)
    box(centrum).close(thread.number)
    third = run_to_end(centrum, dry_run=False)
    thread_with(centrum, comments=3)

    assert (thread.title, thread.body.splitlines()[0]) == (f"Logi Uruchomienia {PERIOD}", LINE)
    runs = [view["run"]["id"] for view in (first, second, third)]
    assert [sent_json([comment]) for comment in thread.comments] == [local_logs(centrum, run) for run in runs]
    assert [issue.comments for issue in foreign] == [[], [], []]
    assert wait_for(lambda: queued_logs(centrum) == [])


def test_komentarz_ma_podsumowanie_uruchomienia_a_pod_nim_pelny_json_logow_w_zwijanym_bloku(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    centrum.worker_settlements.mkdir()

    view = run_to_end(centrum, dry_run=False)

    [comment] = thread_with(centrum, comments=1).comments
    run_id = view["run"]["id"]
    local = local_logs(centrum, run_id)
    started = datetime.fromisoformat(json.loads(local)["started_at"])
    assert re.sub(r"\n- Czas: [^\n]+\n", "\n- Czas: …\n", comment) == (
        f"**Logi Uruchomienia**: Przebieg rozliczeń, zapis, okres {PERIOD}\n"
        "\n"
        "- Wynik: BLAD_KRYTYCZNY, Zatrzymanie dla taty\n"
        "- Czas: …\n"
        "- Komunikaty: `FOLDER_ROZLICZEN_ISTNIEJE` (Zatrzymanie)\n"
        f"- Wydanie: brak, commit {TOOL_COMMIT[:7]}\n"
        f"- Uruchomienie: {run_id}, start {started:%Y-%m-%d %H:%M:%S} UTC\n"
        "\n"
        "<details><summary>Logi JSON</summary>\n"
        "\n"
        f"````json\n{local}\n````\n"
        "\n"
        "</details>\n"
    )


def _broken_worker_config(centrum: SettlingCentrum) -> None:
    centrum.configuration.worker_config.write_text(":: nie yaml", encoding="utf-8")


def _failing_engine(centrum: SettlingCentrum) -> None:
    centrum.engines.fail_engine = True


def _failing_summary(centrum: SettlingCentrum) -> None:
    centrum.engines.fail_summary = True


def _as_is(centrum: SettlingCentrum) -> None:
    return None


SUMMARIES: Final[dict[str, tuple[Callable[[SettlingCentrum], None], bool, bool, list[str]]]] = {
    "ok": (_as_is, False, True, ["- Wynik: OK", "- Komunikaty: brak"]),
    "wymaga-sprawdzenia": (
        _as_is,
        True,
        True,
        ["- Wynik: WYMAGA_SPRAWDZENIA", "- Komunikaty: `BRAK_MAPOWANIA` (ostrzeżenie)"],
    ),
    "do-maksa": (
        _broken_worker_config,
        False,
        False,
        ["- Wynik: BLAD_KRYTYCZNY, Zatrzymanie do Maksa", "- Komunikaty: `ZLA_KONFIGURACJA_WYKONAWCOW` (Zatrzymanie)"],
    ),
    "nieoczekiwany-wyjatek": (
        _failing_engine,
        False,
        False,
        ["- Wynik: BLAD_KRYTYCZNY, nieoczekiwany wyjątek", "- Komunikaty: `BLAD_NIEOCZEKIWANY` (Zatrzymanie)"],
    ),
    "po-silniku": (
        _failing_summary,
        False,
        True,
        ["- Wynik: BLAD_KRYTYCZNY, błąd po zakończeniu silnika", "- Komunikaty: `BLAD_PLANU` (Zatrzymanie)"],
    ),
}


@pytest.mark.parametrize(("steer", "unmapped", "dry_run", "lines"), SUMMARIES.values(), ids=SUMMARIES.keys())
def test_podsumowanie_komentarza_nazywa_wynik_sposob_zakonczenia_i_kody_komunikatow(
    tmp_path: Path, steer: Callable[[SettlingCentrum], None], unmapped: bool, dry_run: bool, lines: list[str]
) -> None:
    centrum = watched_centrum(tmp_path, include_unmapped=unmapped)
    steer(centrum)

    view = run_to_end(centrum, dry_run=dry_run)

    [comment] = thread_with(centrum, comments=1).comments
    summary = comment.split("\n\n<details>")[0].splitlines()
    assert [line for line in lines if line not in summary] == []
    assert sent_json([comment]) == local_logs(centrum, view["run"]["id"])


@pytest.mark.parametrize(
    ("cause", "failure", "key"),
    [("brak-sieci", Unreachable(), True), ("odmowa", Refused(), True), ("brak-klucza", None, False)],
    ids=["brak-sieci", "odmowa", "brak-klucza"],
)
def test_logi_bez_skrzynki_czekaja_w_kolejce_bez_komunikatu_a_nastepny_start_je_wysyla(
    tmp_path: Path, cause: str, failure: Refused | Unreachable | None, key: bool
) -> None:
    centrum = watched_centrum(tmp_path, key=key)
    box(centrum).search_failure = failure

    view = run_to_end(centrum, dry_run=True)

    waiting = f"skrzynka-czeka etykieta={LABEL} okres={PERIOD} przyczyna={cause}"
    assert wait_for(lambda: waiting in centrum.log_path.read_text(encoding="utf-8"))
    assert (view["result"]["result"], view["result"]["stops"], view["result"]["warnings"]) == ("OK", [], [])
    assert view["result"]["technical_notes"] == []
    [queued] = queued_logs(centrum)
    assert [path.name for path in (tmp_path / "config" / "zgloszenia").iterdir()] == ["kolejka"]
    assert box(centrum).issues == []

    box(centrum).search_failure = None
    write_key(centrum)
    centrum.restart()
    with centrum.client:
        [comment] = thread_with(centrum, comments=1).comments

    assert sent_json([comment]) == local_logs(centrum, view["run"]["id"])
    assert wait_for(lambda: queued_logs(centrum) == [])
    assert not queued.exists()


def diagnose(centrum: SettlingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    return diagnosis


def test_diagnoza_po_zatrzymaniu_do_maksa_dopisuje_sie_do_pliku_logow_i_jako_kolejny_komentarz_w_issue_okresu(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    before = local_logs(centrum, run_id)
    thread_with(centrum, comments=1)

    shown = diagnose(centrum, run_id)

    thread = thread_with(centrum, comments=2)
    local = local_logs(centrum, run_id)
    diagnosis = json.loads(local)["diagnosis"]
    assert {**json.loads(local), "diagnosis": None} == json.loads(before)
    assert [{part: check[part] for part in ("label", "state", "detail")} for check in diagnosis["checks"]] == shown["checks"]
    assert {part: diagnosis["explanation"][part] for part in ("what", "where", "action")} == shown["explanation"]
    assert diagnosis["next_action"] == shown["next_action"]
    assert [sent_json([comment]) for comment in thread.comments] == [before, local]
    summary = thread.comments[1].split("\n\n<details>")[0].splitlines()
    assert f"- Diagnoza: `{diagnosis['explanation']['code']}`" in [line.split(";")[0] for line in summary]
    assert [issue.number for issue in box(centrum).issues_with(LABEL)] == [thread.number]


def test_wyslane_zgloszenie_prowadzi_do_komentarza_logow_swojego_uruchomienia(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_to_end(centrum, dry_run=True)
    thread_with(centrum, comments=1)
    run_id = stopped_for_maks(centrum)
    thread = thread_with(centrum, comments=2)

    preview = diagnose(centrum, run_id)["report"]
    response = centrum.client.post(f"/api/runs/{run_id}/report")

    assert response.json() == {"state": "sent"}
    [report] = box(centrum).sent
    assert report.body == preview["body"]
    link = f"- Logi: https://github.com/{REPOSITORY}/issues/{thread.number}#issuecomment-2"
    assert link in report.body.splitlines()
    assert sent_json([thread.comments[1]]).startswith('{\n  "schema_version": 1,\n  "run_id": "' + run_id)


def test_diagnoza_bez_sieci_jest_w_pliku_logow_jej_komentarz_czeka_w_kolejce_a_zgloszenie_dziala_jak_dotad(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    box(centrum).search_failure = Unreachable()
    run_id = stopped_for_maks(centrum)

    shown = diagnose(centrum, run_id)
    state = centrum.client.post(f"/api/runs/{run_id}/report").json()

    local = local_logs(centrum, run_id)
    assert json.loads(local)["diagnosis"]["checks"][0]["label"] == shown["checks"][0]["label"]
    assert f"- Logi: jeszcze niewysłane, Uruchomienie {run_id}" in shown["report"]["body"].splitlines()
    assert state["state"] == "saved"
    [saved] = (tmp_path / "config" / "zgloszenia").glob("Zgłoszenie *.md")
    assert saved.read_text(encoding="utf-8") == f"# {shown['report']['title']}\n\n{shown['report']['body']}"
    assert wait_for(lambda: len(queued_logs(centrum)) == 2)
    assert box(centrum).issues == []

    box(centrum).search_failure = None
    centrum.restart()
    with centrum.client:
        thread = thread_with(centrum, comments=2)

    assert sent_json([thread.comments[1]]) == local
    assert wait_for(lambda: queued_logs(centrum) == [])


def test_katalog_logow_bez_prawa_zapisu_nie_zmienia_diagnozy_ani_zgloszenia_a_diagnoza_idzie_do_skrzynki(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    blocked = centrum.log_path.parent / "uruchomienia"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("", encoding="utf-8")
    run_id = stopped_for_maks(centrum)
    thread_with(centrum, comments=1)

    shown = diagnose(centrum, run_id)

    thread = thread_with(centrum, comments=2)
    assert json.loads(sent_json([thread.comments[1]]))["diagnosis"]["next_action"] == shown["next_action"]
    assert "- Logi: https://github.com/" in shown["report"]["body"]
    assert blocked.read_text(encoding="utf-8") == ""
    log = centrum.log_path.read_text(encoding="utf-8")
    assert 'nieoczekiwany-wyjatek typ=FileExistsError miejsce="Diagnoza w Logach Uruchomienia"' in log


def test_diagnoza_uruchomienia_bez_logow_nie_trafia_do_logow_poprzedniego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = watched_centrum(tmp_path)
    earlier = run_to_end(centrum, dry_run=True)["run"]["id"]
    thread_with(centrum, comments=1)
    before = local_logs(centrum, earlier)

    def broken(*_: object, **__: object) -> list[Path]:
        raise RuntimeError("syntetyczny błąd budowy Logów")

    monkeypatch.setattr(app, "files_of_process", broken)
    run_id = stopped_for_maks(centrum)

    shown = diagnose(centrum, run_id)

    assert f"- Logi: jeszcze niewysłane, Uruchomienie {run_id}" in shown["report"]["body"].splitlines()
    assert local_logs(centrum, earlier) == before
    assert wait_for(lambda: queued_logs(centrum) == [])
    assert len(threads(box(centrum))[0].comments) == 1
