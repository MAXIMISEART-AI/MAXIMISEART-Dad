"""``tools/zgloszenia_ci.py``: issue flaka, issue czerwonego `main` z rozpoznaniem zderzenia i jego zamknięcie.

Historia `main` to prawdziwy Git z PR-ami scalonymi merge'em, a GitHub to zapisane odpowiedzi API w kształcie
odpowiedzi z runów 26.10.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
import io
import json
from pathlib import Path
import sys
from typing import Any
import zipfile

import pytest

from tests.fixtures.git_repo import commit, git

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import zgloszenia_ci
from zgloszenia_ci import Skomentuj, Zaloz, Zamknij

REPO = "repos/{owner}/{repo}"
TERAZ = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
RUN_URL = "https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/{}"


class Nagrany:
    """GitHub z zapisanych odpowiedzi; brak odpowiedzi to ``KeyError`` z pytaną ścieżką."""

    def __init__(self, odpowiedzi: dict[str, Any]) -> None:
        self.odpowiedzi = odpowiedzi
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        return self.odpowiedzi[sciezka]

    def bajty(self, sciezka: str) -> bytes:
        odpowiedz: bytes = self.odpowiedzi[sciezka]
        return odpowiedz

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self.wyslane.append((metoda, sciezka, tresc))
        return {"number": 900 + len(self.wyslane)}


def _run(run_id: int, zdarzenie: str, sha: str, wynik: str = "failure", *, pr: tuple[int, ...] = ()) -> dict[str, Any]:
    return {
        "id": run_id,
        "html_url": RUN_URL.format(run_id),
        "event": zdarzenie,
        "head_branch": "main" if zdarzenie == "push" else "fix/x",
        "head_sha": sha,
        "conclusion": wynik,
        "pull_requests": [{"number": numer} for numer in pr],
        "created_at": "2026-10-26T10:00:00Z",
    }


def _zip(tresc: object) -> bytes:
    spakowane = io.BytesIO()
    with zipfile.ZipFile(spakowane, "w") as archiwum:
        archiwum.writestr("flaki.json", json.dumps(tresc))
    return spakowane.getvalue()


def _flak(test: str) -> dict[str, object]:
    return {"test": test, "zadanie": "pytest (Python 3.11, 1/2)", "sha": "a" * 40, "run": 1, "proba": 1}


def _artefakty(run_id: int, artefakty: dict[str, object]) -> dict[str, Any]:
    lista = [{"id": run_id * 10 + numer, "name": nazwa, "expired": False} for numer, nazwa in enumerate(artefakty)]
    return {
        f"{REPO}/actions/runs/{run_id}/artifacts?per_page=100": {"artifacts": [*lista, {"id": 7, "name": "czasy-ci", "expired": False}]},
        **{f"{REPO}/actions/artifacts/{run_id * 10 + numer}/zip": _zip(tresc) for numer, tresc in enumerate(artefakty.values())},
    }


def _issues(etykieta: str, stan: str, issues: list[dict[str, Any]], od: str = "") -> dict[str, Any]:
    zapytanie = f"labels={etykieta}&state={stan}&per_page=100" + (f"&since={od}" if od else "")
    return {f"{REPO}/issues?{zapytanie}": issues}


def test_kazdy_flak_runu_ma_jedno_otwarte_issue_a_obce_id_testu_z_artefaktu_nie_trafia_do_issue(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    for plik in ("test_skrzynka.py", "test_centrum.py"):
        (tmp_path / "tests" / plik).write_text("", encoding="utf-8")
    nowy = "tests/test_skrzynka.py::test_zatrzymanie_czeka_na_watki[przygotowanie]"
    znany = "tests/test_centrum.py::TestKarta::test_karta"
    github = Nagrany(
        {
            f"{REPO}/actions/runs/40380584486": _run(40380584486, "pull_request", "b" * 40, "success", pr=(540,)),
            **_artefakty(
                40380584486,
                {
                    "flaki-linux-3.14-1-1": [_flak(nowy), _flak(znany)],
                    "flaki-windows-3.11-1-1": [_flak(nowy)],
                    "flaki-windows-3.11-2-1": [_flak("tests/test_centrum.py::test_x @maks [link](https://zly.example)")],
                    "flaki-windows-3.11-3-1": [_flak("tests/test_nie_ma.py::test_x")],
                },
            ),
            **_issues("flak", "open", [{"number": 5, "title": f"Flak: {znany}"}, {"number": 6, "title": f"Flak: {nowy}", "pull_request": {}}]),
        }
    )

    akcje = zgloszenia_ci.akcje(github, tmp_path, 40380584486, TERAZ)

    assert [type(akcja) for akcja in akcje] == [Zaloz, Skomentuj]
    zalozone, komentarz = akcje
    assert isinstance(zalozone, Zaloz) and isinstance(komentarz, Skomentuj)
    assert (zalozone.tytul, zalozone.etykiety, komentarz.issue) == (f"Flak: {nowy}", ("flak",), 5)
    assert f"commit {'b' * 40}, PR #540" in zalozone.tresc
    assert "@maks" not in zalozone.tresc + komentarz.tresc


@pytest.fixture
def main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """`main`: początek, zielony merge PR #10 (10:00) i czerwony merge PR #11 (10:30)."""

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet", "--initial-branch=main")
    (repo / "a.txt").write_text("0\n", encoding="utf-8")
    shas = {"poczatek": commit(repo, "początek")}
    for numer, chwila in ((10, "2026-10-26T10:00:00+00:00"), (11, "2026-10-26T10:30:00+00:00")):
        monkeypatch.setenv("GIT_COMMITTER_DATE", chwila)
        git(repo, "switch", "--quiet", "--create", f"pr-{numer}", "main")
        (repo / f"pr{numer}.txt").write_text(f"{numer}\n", encoding="utf-8")
        shas[f"head{numer}"] = commit(repo, f"zmiana {numer}")
        git(repo, "switch", "--quiet", "main")
        git(repo, "merge", "--no-ff", "--quiet", "-m", f"Merge pull request #{numer} from maximiseartai/pr-{numer}", "-m", f"fix: zmiana {numer}", f"pr-{numer}")
        shas[f"pr{numer}"] = git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)
    yield shas


def _required(sha: str, wynik: str, run_id: int) -> dict[str, Any]:
    check = {"status": "completed", "conclusion": wynik, "started_at": "2026-10-26T10:40:00Z", "details_url": f"{RUN_URL.format(run_id)}/job/1"}
    return {f"{REPO}/commits/{sha}/check-runs?check_name=Required%20CI%20status&per_page=100": {"check_runs": [check]}}


def _czerwony_run(
    main: dict[str, str], *, bramka_b: str, otwarte: list[dict[str, Any]] | None = None, main_10: str = "success", required_b: str = "success"
) -> Nagrany:
    """Run pushu na `main` z czerwonym Required na merge'u #11, po merge'u #10 z Required ``main_10``; run bramki #11
    z wynikiem ``required_b`` utworzony ``bramka_b``."""

    log = "2026-10-26T10:41:00.1Z REQUIRED FAIL | pytest=failure\n2026-10-26T10:41:00.2Z REQUIRED FAIL | pytest (Python 3.14, 2/3): jednostki z porażką: pytest:tests/test_a.py\n"
    return Nagrany(
        {
            f"{REPO}/actions/runs/300": _run(300, "push", main["pr11"]),
            **_artefakty(300, {}),
            f"{REPO}/actions/runs/300/jobs?per_page=100": {"jobs": [{"id": 31, "name": "Required CI status", "conclusion": "failure"}]},
            f"{REPO}/actions/jobs/31/logs": log.encode(),
            **_issues("czerwony-main", "open", otwarte or []),
            **_required(main["pr10"], main_10, 200),
            **_required(main["poczatek"], "success", 199),
            **{f"{REPO}/pulls/{numer}": {"head": {"sha": main[f"head{numer}"]}} for numer in (10, 11)},
            **_required(main["head10"], "success", 100),
            **_required(main["head11"], required_b, 111),
            f"{REPO}/actions/runs/111": {"created_at": bramka_b},
            **_issues(
                "zderzenie",
                "all",
                [{"number": 3, "created_at": "2026-10-23T08:00:00Z"}, {"number": 2, "created_at": "2026-10-18T08:00:00Z"}],
                od="2026-10-19T20%3A00%3A00Z",
            ),
        }
    )


def test_czerwony_main_po_zielonym_zderzeniu_ma_ostatni_zielony_pr_y_bisect_i_licznik_zderzen(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z")

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert (akcja.tytul, akcja.etykiety) == (f"Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)", ("czerwony-main", "zderzenie"))
    assert f"Ostatni zielony commit: {main['pr10']}" in akcja.tresc
    assert "PR-y scalone pomiędzy (1):\n- #11 fix: zmiana 11" in akcja.tresc
    assert "REQUIRED FAIL | pytest (Python 3.14, 2/3): jednostki z porażką: pytest:tests/test_a.py" in akcja.tresc
    assert f"git bisect start {main['pr11']} {main['pr10']}\ngit bisect run .venv/bin/python -m pytest tests/test_a.py" in akcja.tresc
    assert "To 2. zderzenie w ostatnich 7 dniach" in akcja.tresc


def test_czerwony_main_bez_zderzenia_gdy_bramka_pr_testowala_main_z_poprzednim_scaleniem(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T10:05:00Z")

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert (akcja.tytul, akcja.etykiety) == (f"Czerwony main od {main['pr11'][:9]}", ("czerwony-main",))
    assert "Zderzenie" not in akcja.tresc


@pytest.mark.parametrize(("main_10", "required_b"), [("cancelled", "success"), ("success", "failure")])
def test_bez_zderzenia_gdy_main_nie_byl_zielony_tuz_przed_albo_bramka_pr_nie_byla_zielona(main: dict[str, str], main_10: str, required_b: str) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", main_10=main_10, required_b=required_b)

    [akcja] = zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)

    assert isinstance(akcja, Zaloz)
    assert akcja.etykiety == ("czerwony-main",)
    zielony = main["poczatek"] if main_10 == "cancelled" else main["pr10"]
    assert f"Ostatni zielony commit: {zielony}" in akcja.tresc


def test_kolejny_czerwony_main_komentuje_otwarte_issue_zamiast_drugiego(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z", otwarte=[{"number": 77, "body": f"<!-- czerwony-main {main['pr10']} -->"}])

    assert [type(akcja) for akcja in zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ)] == [Skomentuj]


@pytest.mark.parametrize(("wynik", "required", "zamkniete"), [("success", "success", [77]), ("cancelled", "failure", []), ("failure", "skipped", [])])
def test_zielony_main_zamyka_issue_czerwonego_przodka_z_linkiem_do_runu(main: dict[str, str], wynik: str, required: str, zamkniete: list[int]) -> None:
    otwarte = [{"number": 77, "body": f"... <!-- czerwony-main {main['pr10']} -->"}, {"number": 78, "body": f"<!-- czerwony-main {'c' * 40} -->"}]
    github = Nagrany(
        {
            f"{REPO}/actions/runs/400": _run(400, "push", main["pr11"], wynik),
            **_artefakty(400, {}),
            f"{REPO}/actions/runs/400/jobs?per_page=100": {"jobs": [{"id": 41, "name": "Required CI status", "conclusion": required}]},
            **_issues("czerwony-main", "open", otwarte),
        }
    )

    akcje = zgloszenia_ci.akcje(github, Path.cwd(), 400, TERAZ)
    linie = zgloszenia_ci.wykonaj(github, akcje, bez_zapisu=False)

    assert [akcja.issue for akcja in akcje if isinstance(akcja, Zamknij)] == zamkniete
    assert linie == [f"ZGŁOSZENIA | zamknięte #{issue}" for issue in zamkniete]
    assert github.wyslane == [
        call
        for issue in zamkniete
        for call in (
            ("POST", f"{REPO}/issues/{issue}/comments", {"body": f"Zielony `main` na commicie {main['pr11']} ([run]({RUN_URL.format(400)}))."}),
            ("PATCH", f"{REPO}/issues/{issue}", {"state": "closed", "state_reason": "completed"}),
        )
    ]


def test_bez_zapisu_tylko_drukuje_akcje(main: dict[str, str]) -> None:
    github = _czerwony_run(main, bramka_b="2026-10-26T09:50:00Z")

    linie = zgloszenia_ci.wykonaj(github, zgloszenia_ci.akcje(github, Path.cwd(), 300, TERAZ), bez_zapisu=True)

    assert linie[0].startswith(f"ZGŁOSZENIA BEZ ZAPISU | załóż issue „Czerwony main od {main['pr11'][:9]} (zderzenie #10 i #11)”")
    assert github.wyslane == []
