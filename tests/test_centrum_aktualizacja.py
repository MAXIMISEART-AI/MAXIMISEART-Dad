"""Aktualizacja narzędzia w Centrum rozliczeń przez HTTP API, na prawdziwym klonie z lokalnym „origin”.

Reguły samej aktualizacji sprawdza ``test_aktualizacja_narzedzia.py`` na
interfejsie modułu; tutaj jest to, co widzi przeglądarka: akcja, krok,
wynik, Konfiguracja, odmowy „jedno naraz” i dziennik Centrum.
"""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from rozliczenia.centrum.tool_update import RESULT_FILE, UPDATED, UpdateResult, write_result

from tests.fixtures.centrum import views_until
from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum
from tests.fixtures.preparation import PERIOD, incomplete_period_rows
from tests.fixtures.tool_clone import ToolRepository, tool_repository


@pytest.fixture(autouse=True)
def git_bez_konfiguracji_komputera_testow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def updating_centrum(
    tmp_path: Path, *, hold: threading.Event | None = None, incomplete_period: bool = False
) -> tuple[PreparingCentrum, ToolRepository]:
    repository = tool_repository(tmp_path / "repozytoria")
    surroundings = Surroundings(tool=repository, update_hold=hold)
    rows = incomplete_period_rows() if incomplete_period else None
    return preparing_centrum(tmp_path, rows, surroundings=surroundings), repository


def update_until_done(centrum: PreparingCentrum) -> dict[str, Any]:
    """Klika „Zaktualizuj narzędzie” i czeka na wynik albo na ponowny start Centrum."""

    started = centrum.client.post("/api/tool-update")
    assert started.status_code == 202, started.json()
    assert started.json() == {"state": "running", "step": "fetching"}
    deadline = time.monotonic() + 30
    while True:
        view = centrum.client.get("/api/tool-update").json()
        if view["state"] != "running" or view["step"] == "restarting":
            return dict(view)
        assert time.monotonic() < deadline, "Aktualizacja narzędzia nie skończyła się."
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

    assert view == {
        "state": "failed",
        "message": {
            "what": "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
            "where": "narzędzie na tym komputerze",
            "action": (
                "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
            ),
        },
    }
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert log_entries(centrum, "aktualizacja-koniec") == ["wynik=NIEOCZEKIWANY_BLAD przed=- po=- biblioteki=nie"]
    assert centrum.client.post("/api/tool-update").status_code == 202
