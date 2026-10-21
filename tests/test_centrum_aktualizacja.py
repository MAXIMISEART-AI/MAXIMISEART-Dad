"""Aktualizacja narzędzia w Centrum rozliczeń przez HTTP API, na prawdziwym klonie z lokalnym „origin”.

Reguły samej aktualizacji sprawdza ``test_aktualizacja_narzedzia.py`` na
interfejsie modułu; tutaj jest to, co widzi przeglądarka: akcja, krok,
wynik, Konfiguracja, odmowy „jedno naraz” i dziennik Centrum.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

import pytest

from rozliczenia.centrum.tool_update import NEW_VERSION_FAILED, RESULT_FILE, UPDATED, UpdateResult, write_result

from tests.fixtures.centrum import project_version, views_until
from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum
from tests.fixtures.preparation import PERIOD, incomplete_period_rows
from tests.fixtures.tool_clone import (
    NEW_REQUIREMENTS,
    FakeInstaller,
    ToolRepository,
    origin_asking_for_login,
    tool_repository,
)


@pytest.fixture(autouse=True)
def git_bez_konfiguracji_komputera_testow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def updating_centrum(
    tmp_path: Path,
    *,
    hold: threading.Event | None = None,
    incomplete_period: bool = False,
    git_installed: bool = True,
    origin: str | None = None,
    installer: FakeInstaller | None = None,
    guardian_starts: bool = True,
) -> tuple[PreparingCentrum, ToolRepository]:
    repository = tool_repository(tmp_path / "repozytoria")
    surroundings = Surroundings(
        tool=repository,
        update_hold=hold,
        git_installed=git_installed,
        update_origin=origin,
        installer=installer or FakeInstaller(),
        guardian_starts=guardian_starts,
    )
    rows = incomplete_period_rows() if incomplete_period else None
    return preparing_centrum(tmp_path, rows, surroundings=surroundings), repository


def update_until_done(centrum: PreparingCentrum) -> dict[str, Any]:
    """Klika „Zaktualizuj narzędzie” i czeka na wynik albo na ponowny start Centrum."""

    started = centrum.client.post("/api/tool-update")
    assert started.status_code == 202, started.json()
    assert started.json() == {"state": "running", "step": "fetching"}
    return tool_update_until(centrum, lambda view: view["state"] != "running" or view["step"] == "restarting")


def tool_update_until(centrum: PreparingCentrum, reached: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        view = dict(centrum.client.get("/api/tool-update").json())
        if reached(view):
            return view
        assert time.monotonic() < deadline, f"Aktualizacja narzędzia utknęła w {view}."
        time.sleep(0.02)


def tool_on_configuration(centrum: PreparingCentrum) -> dict[str, Any]:
    configuration = centrum.client.get("/api/configuration").json()
    return {key: configuration[key] for key in ("version", "commit", "freshness")}


def log_events(centrum: PreparingCentrum) -> list[str]:
    return [line.split(" ", 2)[1] for line in centrum.log_path.read_text(encoding="utf-8").splitlines()]


def log_entries(centrum: PreparingCentrum, event: str) -> list[str]:
    lines = centrum.log_path.read_text(encoding="utf-8").splitlines()
    return [line.split(" ", 2)[2] for line in lines if line.split(" ", 2)[1] == event]


def test_po_aktualizacji_centrum_zamyka_sie_i_prosi_opiekuna_o_start_nowej_wersji(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    outdated = tool_on_configuration(centrum)

    view = update_until_done(centrum)
    run = centrum.start(dry_run=True)

    assert outdated["commit"] == before[:7]
    assert outdated["freshness"] == "newer"
    assert view == {"state": "running", "step": "restarting"}
    assert repository.head() == newest
    [restart] = centrum.surroundings.restarts
    assert (restart.port, restart.before, restart.after, restart.installed) == (47811, before, newest, False)
    assert (restart.root, restart.result) == (repository.clone, tmp_path / "config" / RESULT_FILE)
    assert log_entries(centrum, "aktualizacja-start") == [f"przed={before}"]
    assert log_entries(centrum, "zamkniecie") == ["z=aktualizacja"]
    assert "aktualizacja-koniec" not in log_events(centrum)
    assert (run.status_code, run.json()) == (
        409,
        {"message": "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem uruchom proces."},
    )


def test_nowe_centrum_po_aktualizacji_zapisuje_wynik_od_opiekuna_w_dzienniku_i_pokazuje_go_karcie(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    old_health = centrum.client.get("/api/health").json()
    update_until_done(centrum)
    [restart] = centrum.surroundings.restarts
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after, restart.installed))

    centrum.restart()
    new_health = centrum.client.get("/api/health").json()
    view = centrum.client.get("/api/tool-update").json()
    centrum.restart()

    assert (old_health["commit"], new_health["commit"]) == (before, newest)
    assert new_health["instance"] != old_health["instance"]
    assert view == {"state": "updated", "commit": newest[:7]}
    assert tool_on_configuration(centrum) | {"version": None} == {
        "version": None,
        "commit": newest[:7],
        "freshness": "current",
    }
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]
    assert not restart.result.exists()
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}


def test_najnowsza_wersja_zostaje_bez_zmian(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    current = repository.head()

    view = update_until_done(centrum)

    assert view == {"state": "up_to_date"}
    assert repository.head() == current
    assert tool_on_configuration(centrum)["freshness"] == "current"
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=AKTUALNA przed={current} po={current} biblioteki=nie"
    ]


def test_przed_kliknieciem_nie_ma_aktualizacji(tmp_path: Path) -> None:
    centrum, _ = updating_centrum(tmp_path)

    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}


def test_brak_sieci_przy_sprawdzaniu_aktualnosci_to_nie_sprawdzono(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.surroundings.github.main = None

    assert tool_on_configuration(centrum)["freshness"] == "not_checked"


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "http://obca-strona.example"}, {"Host": "obca-strona.example"}],
    ids=["obcy-origin", "obcy-host"],
)
def test_aktualizacja_z_obcej_strony_jest_odrzucona(tmp_path: Path, headers: dict[str, str]) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    refused = centrum.client.post("/api/tool-update", headers=headers)

    assert refused.status_code == 403
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}
    assert repository.head() == before


def test_aktualizacja_w_trakcie_uruchomienia_procesu_jest_odrzucona(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, incomplete_period=True)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    centrum.start(dry_run=False)
    views_until(centrum.client, "awaiting_decision")

    refused = centrum.client.post("/api/tool-update")

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                f"Trwa Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
                "Poczekaj na jego wynik w Uruchomieniach, potem zaktualizuj narzędzie."
            )
        },
    )
    assert repository.head() == before
    assert "aktualizacja-start" not in log_events(centrum)


def test_w_trakcie_aktualizacji_uruchomienie_druga_aktualizacja_i_zamkniecie_sa_odrzucone(tmp_path: Path) -> None:
    hold = threading.Event()
    centrum, repository = updating_centrum(tmp_path, hold=hold)
    current = repository.head()
    assert centrum.client.post("/api/tool-update").status_code == 202

    run = centrum.start(dry_run=True)
    second = centrum.client.post("/api/tool-update")
    closing = centrum.client.post("/api/shutdown")
    hold.set()
    deadline = time.monotonic() + 30
    while centrum.client.get("/api/tool-update").json()["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    run_after = centrum.start(dry_run=True)

    assert (run.status_code, run.json()) == (
        409,
        {"message": "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem uruchom proces."},
    )
    assert (second.status_code, second.json()) == (
        409,
        {"message": "Trwa już aktualizacja narzędzia. Poczekaj na jej wynik."},
    )
    assert (closing.status_code, closing.json()) == (
        409,
        {"message": "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem zamknij Centrum rozliczeń."},
    )
    assert repository.head() == current
    assert run_after.status_code == 200
    assert log_events(centrum).count("aktualizacja-start") == 1


def test_nieprzewidziana_porazka_daje_komunikat_a_klon_zostaje_bez_zmian(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    # Gałąź main bez commitu: Git nie poda commitu narzędzia, czego aktualizacja nie przewiduje.
    repository.in_clone("update-ref", "-d", "refs/heads/main")

    view = update_until_done(centrum)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
            "where": "narzędzie na tym komputerze",
            "action": (
                "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
            ),
        },
        "next_action": "retry",
        "report": {"state": "ready"},
    }
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert log_entries(centrum, "aktualizacja-koniec") == ["wynik=NIEOCZEKIWANY_BLAD przed=- po=- biblioteki=nie"]
    assert centrum.client.post("/api/tool-update").status_code == 202


STILL_WORKS = "Narzędzie działa dalej w poprzedniej wersji."
TO_MAKS = f"{STILL_WORKS} Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"


@contextmanager
def github_out_of_reach(repository: ToolRepository) -> Iterator[None]:
    """Lokalny „origin” poza zasięgiem, jak GitHub bez internetu, aż internet wróci."""

    away = repository.origin.with_name("origin-poza-zasiegiem.git")
    repository.origin.rename(away)
    try:
        yield
    finally:
        away.rename(repository.origin)


def newer_version(centrum_and_repository: tuple[PreparingCentrum, ToolRepository]) -> tuple[PreparingCentrum, ToolRepository]:
    """Maks wydał nową wersję narzędzia: `main` w „origin” jest o commit przed klonem taty."""

    centrum_and_repository[1].publish({"src/narzedzie.py": "WERSJA = 2\n"})
    return centrum_and_repository


def without_git(tmp_path: Path, stack: ExitStack) -> tuple[PreparingCentrum, ToolRepository]:
    return newer_version(updating_centrum(tmp_path, git_installed=False))


def without_internet(tmp_path: Path, stack: ExitStack) -> tuple[PreparingCentrum, ToolRepository]:
    centrum, repository = newer_version(updating_centrum(tmp_path))
    stack.enter_context(github_out_of_reach(repository))
    return centrum, repository


def github_asking_for_login(tmp_path: Path, stack: ExitStack) -> tuple[PreparingCentrum, ToolRepository]:
    return newer_version(updating_centrum(tmp_path, origin=stack.enter_context(origin_asking_for_login())))


def on_other_branch(tmp_path: Path, stack: ExitStack) -> tuple[PreparingCentrum, ToolRepository]:
    centrum, repository = newer_version(updating_centrum(tmp_path))
    repository.in_clone("checkout", "--quiet", "-b", "proba-maksa")
    return centrum, repository


def with_local_change(tmp_path: Path, stack: ExitStack) -> tuple[PreparingCentrum, ToolRepository]:
    centrum, repository = newer_version(updating_centrum(tmp_path))
    repository.write("src/narzedzie.py", "WERSJA = 1  # poprawka na komputerze taty\n")
    return centrum, repository


Situation = Callable[[Path, ExitStack], tuple[PreparingCentrum, ToolRepository]]


@pytest.mark.parametrize(
    ("situation", "code", "what", "action", "next_action"),
    [
        (without_git, "BRAK_GITA", "Nie zaktualizowano narzędzia: na tym komputerze nie ma Gita.", TO_MAKS, "report"),
        (
            without_internet,
            "BRAK_POLACZENIA",
            "Nie zaktualizowano narzędzia: brak połączenia z GitHubem.",
            f"{STILL_WORKS} Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz.",
            "retry",
        ),
        (
            github_asking_for_login,
            "LOGOWANIE",
            "Nie zaktualizowano narzędzia: GitHub prosi o logowanie.",
            TO_MAKS,
            "report",
        ),
        (
            on_other_branch,
            "INNA_GALAZ",
            "Nie zaktualizowano narzędzia: na tym komputerze jest inna gałąź narzędzia niż main.",
            TO_MAKS,
            "report",
        ),
        (
            with_local_change,
            "ZMIANY_NA_KOMPUTERZE",
            "Nie zaktualizowano narzędzia: ma zmiany zrobione na tym komputerze.",
            TO_MAKS,
            "report",
        ),
    ],
    ids=["brak-gita", "brak-internetu", "logowanie", "inna-galaz", "zmiany-na-komputerze"],
)
def test_aktualizacja_ktora_nie_moze_sie_udac_daje_komunikat_w_trzech_czesciach_a_narzedzie_zostaje(
    tmp_path: Path, situation: Situation, code: str, what: str, action: str, next_action: str
) -> None:
    with ExitStack() as stack:
        centrum, repository = situation(tmp_path, stack)
        before = repository.head()

        view = update_until_done(centrum)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {"what": what, "where": "narzędzie na tym komputerze", "action": action},
        "next_action": next_action,
        "report": {"state": "ready"},
    }
    assert view["draft"]["title"] == f"{code}: {what}"
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") != "WERSJA = 2\n"
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik={code} przed={before} po=- biblioteki=nie"]


def with_key(centrum: PreparingCentrum) -> None:
    (centrum.tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")


def send_report(centrum: PreparingCentrum) -> dict[str, Any]:
    response = centrum.client.post("/api/tool-update/report")
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def test_zgloszenie_nieudanej_aktualizacji_ma_te_same_fakty_co_dziennik(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    with_key(centrum)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    repository.in_clone("checkout", "--quiet", "-b", "proba-maksa")
    preview = update_until_done(centrum)["draft"]

    state = send_report(centrum)

    assert state == {"state": "sent"}
    [report] = centrum.surroundings.report_box.sent
    assert {"title": report.title, "body": report.body} == preview
    assert report.title == "INNA_GALAZ: Nie zaktualizowano narzędzia: na tym komputerze jest inna gałąź narzędzia niż main."
    body = report.body
    assert "- Kod: INNA_GALAZ\n" in body
    assert f"- Co zrobić: {TO_MAKS}\n" in body
    assert (
        f"## Aktualizacja narzędzia\n\n- Wynik: INNA_GALAZ\n- Commit przed: {before}\n- Commit po: brak\n"
        "- Biblioteki instalowane: nie\n"
    ) in body
    assert f"- Wersja: {project_version()}\n" in body
    log = centrum.log_path.read_text(encoding="utf-8").splitlines()
    started = next(line for line in log if " aktualizacja-start " in line)
    finished = next(line for line in log if " aktualizacja-koniec " in line)
    assert f"```text\n{started}\n{finished}\n```" in body
    assert re.search(r"fatal|error:|hint:|proba-maksa|origin\.git", body) is None
    assert centrum.client.get("/api/tool-update").json()["report"] == {"state": "sent"}
    assert "zgloszenie-wyslane z=aktualizacja numer=1" in centrum.log_path.read_text(encoding="utf-8")


def test_zgloszenie_bez_nieudanej_aktualizacji_jest_odrzucone(tmp_path: Path) -> None:
    centrum, _ = updating_centrum(tmp_path)
    with_key(centrum)
    assert update_until_done(centrum)["state"] == "up_to_date"

    refused = centrum.client.post("/api/tool-update/report")

    assert refused.status_code == 409
    assert centrum.surroundings.report_box.sent == []


def test_gdy_wroci_internet_ponowna_aktualizacja_sie_udaje(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    with github_out_of_reach(repository):
        offline = update_until_done(centrum)

    retried = update_until_done(centrum)

    assert offline["message"]["what"] == "Nie zaktualizowano narzędzia: brak połączenia z GitHubem."
    assert retried == {"state": "running", "step": "restarting"}
    assert [restart.after for restart in centrum.surroundings.restarts] == [newest]
    assert repository.head() == newest
    # Koniec udanej aktualizacji zapisze nowe Centrum, z pliku wyniku od opiekuna.
    assert [entry.split(" ", 1)[0] for entry in log_entries(centrum, "aktualizacja-koniec")] == [
        "wynik=BRAK_POLACZENIA"
    ]


def test_nowe_biblioteki_karta_widzi_krok_instalowania_a_dziennik_zapisuje_instalacje(tmp_path: Path) -> None:
    hold = threading.Event()
    centrum, repository = updating_centrum(tmp_path, installer=FakeInstaller(hold=hold))
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS})
    assert centrum.client.post("/api/tool-update").status_code == 202

    installing = tool_update_until(centrum, lambda view: view.get("step") == "installing")
    hold.set()
    view = tool_update_until(centrum, lambda view: view.get("step") == "restarting")

    assert installing == {"state": "running", "step": "installing"}
    assert view == {"state": "running", "step": "restarting"}
    [restart] = centrum.surroundings.restarts
    # Opiekun przekaże nowemu Centrum, że instalowano biblioteki; koniec aktualizacji zapisze ono.
    assert (restart.before, restart.after, restart.installed) == (before, newest, True)


def test_nieudana_instalacja_bibliotek_daje_komunikat_a_narzedzie_zostaje_w_poprzedniej_wersji(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path, installer=FakeInstaller(succeeds=False))
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS, "src/narzedzie.py": "WERSJA = 2\n"})

    view = update_until_done(centrum)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Nie udało się zainstalować bibliotek nowej wersji narzędzia.",
            "where": "narzędzie na tym komputerze",
            "action": (
                "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
            ),
        },
        "next_action": "retry",
        "report": {"state": "ready"},
    }
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert tool_on_configuration(centrum)["commit"] == before[:7]
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=INSTALACJA_BIBLIOTEK przed={before} po={newest} biblioteki=tak"
    ]


def test_gdy_opiekun_nie_wystartuje_centrum_cofa_klon_z_plikiem_taty_i_pokazuje_komunikat(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, guardian_starts=False)
    before = repository.head()
    dad_mapping = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
    repository.write("config/worker_mapping.yaml", dad_mapping)
    newest = repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n", "src/narzedzie.py": "WERSJA = 2\n"},
        untrack=("config/worker_mapping.yaml",),
    )
    assert centrum.client.post("/api/tool-update").status_code == 202

    view = tool_update_until(centrum, lambda view: view["state"] != "running")
    run = centrum.start(dry_run=True)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
            "where": "narzędzie na tym komputerze",
            "action": (
                "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
            ),
        },
        "next_action": "retry",
        "report": {"state": "ready"},
    }
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert repository.read("config/worker_mapping.yaml") == dad_mapping
    assert repository.in_clone("status", "--porcelain", "--untracked-files=no") == "M config/worker_mapping.yaml"
    assert centrum.surroundings.restarts == []
    assert log_entries(centrum, "nieoczekiwany-wyjatek") == ['typ=OSError miejsce="ponowny start po aktualizacji"']
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie"
    ]
    assert "zamkniecie" not in log_events(centrum)
    assert run.status_code == 200


def test_stara_wersja_po_cofnieciu_pokazuje_komunikat_bez_czekania_na_skrzynke_zgloszen(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    result = tmp_path / "config" / RESULT_FILE
    write_result(result, UpdateResult(NEW_VERSION_FAILED, before, newest))
    centrum.restart()
    first = tool_update_until(centrum, lambda view: view["report"] == {"state": "ready"})
    assert send_report(centrum) == {"state": "sent"}
    box.close(1)  # Maks naprawił, ale nowa wersja znowu nie wystartowała
    write_result(result, UpdateResult(NEW_VERSION_FAILED, before, newest))
    box.search_hold = threading.Event()
    release = threading.Timer(8, box.search_hold.set)  # bez osobnego wątku start czekałby na skrzynkę
    release.start()
    started = time.monotonic()

    try:
        centrum.restart()
        took = time.monotonic() - started
        while_box_silent = centrum.client.get("/api/tool-update").json()
    finally:
        box.search_hold.set()
        release.cancel()
    answered = tool_update_until(centrum, lambda view: view["report"] == {"state": "ready"})

    assert took < 2
    assert {key: value for key, value in first.items() if key != "draft"} == {
        "state": "failed",
        "message": {"what": "Nowa wersja narzędzia nie wystartowała.", "where": "narzędzie na tym komputerze", "action": TO_MAKS},
        "next_action": "report",
        "report": {"state": "ready"},
    }
    assert first["draft"]["title"] == "NOWA_WERSJA_NIE_WYSTARTOWALA: Nowa wersja narzędzia nie wystartowała."
    assert (while_box_silent["state"], while_box_silent["report"]) == ("failed", {"state": "waiting"})
    assert answered["message"] == first["message"]
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie"
    ] * 2
