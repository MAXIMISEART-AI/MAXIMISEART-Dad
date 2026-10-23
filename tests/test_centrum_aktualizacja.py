"""Aktualizacja narzędzia w Centrum rozliczeń przez HTTP API, na prawdziwym klonie z lokalnym „origin”.

Reguły samej aktualizacji sprawdza ``test_aktualizacja_narzedzia.py`` na
interfejsie modułu; tutaj jest to, co widzi przeglądarka: akcja, krok,
wynik, Konfiguracja, odmowy „jedno naraz” i dziennik Centrum.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any

import pytest

from rozliczenia.centrum.tool_update import NEW_VERSION_FAILED, RESULT_FILE, UPDATED, ToolClone, UpdateResult, write_result

from tests.fixtures.centrum import NO_RELEASE, views_until
from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum
from tests.fixtures.preparation import PERIOD, incomplete_period_rows
from tests.fixtures.tool_clone import (
    NEW_REQUIREMENTS,
    FakeInstaller,
    ToolRepository,
    git,
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
    installer: FakeInstaller | None = None,
    guardian_failure: Callable[[ToolRepository], None] | None = None,
) -> tuple[PreparingCentrum, ToolRepository]:
    repository = tool_repository(tmp_path / "repozytoria")
    surroundings = Surroundings(
        guardian_failure=None if guardian_failure is None else lambda: guardian_failure(repository),
        tool=repository,
        update_hold=hold,
        installer=installer or FakeInstaller(),
    )
    rows = incomplete_period_rows() if incomplete_period else None
    return preparing_centrum(tmp_path, rows, surroundings=surroundings), repository


def update_until_done(centrum: PreparingCentrum) -> dict[str, Any]:
    """Klika „Zaktualizuj narzędzie” i czeka na wynik albo na ponowny start Centrum."""

    started = centrum.client.post("/api/tool-update")
    assert started.status_code == 202, started.json()
    assert started.json() == {"state": "running", "step": "fetching"}
    return tool_update_until(centrum, lambda view: view["state"] != "running" or view["step"] == "restarting")


def update_until_result(centrum: PreparingCentrum) -> dict[str, Any]:
    """Klika „Zaktualizuj narzędzie” i czeka na wynik, także po nieudanej próbie ponownego startu."""

    assert centrum.client.post("/api/tool-update").status_code == 202
    return tool_update_until(centrum, lambda view: view["state"] != "running")


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
    version = configuration["version"]
    return {"commit": None if version is None else version["commit"], "freshness": configuration["freshness"]}


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

    assert (old_health["commit"], new_health["commit"]) == (before[:7], newest[:7])
    assert new_health["instance"] != old_health["instance"]
    assert view == {"state": "updated"}
    assert tool_on_configuration(centrum) == {"commit": newest[:7], "freshness": "current"}
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


def test_pominiete_wydanie_spoza_main_zostawia_slad_w_dzienniku_centrum(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    current = repository.head()
    git(repository.publisher, "checkout", "--quiet", "-b", "agent")
    git(repository.publisher, "commit", "--quiet", "--allow-empty", "--message", "Zmiana spoza main")
    repository.release(tag="v0.3.0")

    view = update_until_done(centrum)

    assert view == {"state": "up_to_date"}
    assert repository.head() == current
    assert log_entries(centrum, "aktualizacja-pominiete-wydania") == ["tagi=v0.3.0"]
    assert tool_on_configuration(centrum)["freshness"] == "current"


def test_udana_aktualizacja_z_pominietym_wydaniem_spoza_main_zostawia_slad_takze_po_ponownym_starcie(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    git(repository.publisher, "checkout", "--quiet", "-b", "agent")
    git(repository.publisher, "commit", "--quiet", "--allow-empty", "--message", "Zmiana spoza main")
    repository.release(tag="v0.9.0")
    update_until_done(centrum)
    [restart] = centrum.surroundings.restarts
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after, restart.installed))

    centrum.restart()

    assert repository.head() == newest
    assert log_entries(centrum, "aktualizacja-pominiete-wydania") == ["tagi=v0.9.0"]
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]


def test_przed_kliknieciem_nie_ma_aktualizacji(tmp_path: Path) -> None:
    centrum, _ = updating_centrum(tmp_path)

    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}


def test_brak_sieci_przy_sprawdzaniu_aktualnosci_to_nie_sprawdzono(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.surroundings.github.release = None

    assert tool_on_configuration(centrum)["freshness"] == "not_checked"


NEWER_MAIN = "f" * 40


def test_konfiguracja_pyta_githuba_o_main_najwyzej_raz_na_10_minut(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    first = tool_on_configuration(centrum)["freshness"]
    github.release = NEWER_MAIN

    within_ten_minutes = [tool_on_configuration(centrum)["freshness"] for _ in range(3)]
    clock.advance(minutes=10)
    after_ten_minutes = tool_on_configuration(centrum)["freshness"]

    assert (first, within_ten_minutes, after_ten_minutes) == ("current", ["current"] * 3, "newer")
    assert github.asked == 2


def test_github_bez_wydania_konfiguracja_pamieta_jak_kazda_odpowiedz_przez_10_minut(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    github.release = NO_RELEASE
    readings = []
    for _ in range(9):
        readings.append(tool_on_configuration(centrum)["freshness"])
        clock.advance(minutes=1)

    assert readings == ["not_checked"] * 9
    assert github.asked == 1


def test_bez_odpowiedzi_githuba_konfiguracja_pyta_znowu_po_minucie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    github.release = None
    offline = tool_on_configuration(centrum)["freshness"]
    github.release = NEWER_MAIN

    still_offline = tool_on_configuration(centrum)["freshness"]
    clock.advance(minutes=1)
    back_online = tool_on_configuration(centrum)["freshness"]

    assert (offline, still_offline, back_online) == ("not_checked", "not_checked", "newer")
    assert github.asked == 2


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


def test_po_przyjetym_zamknieciu_aktualizacja_i_uruchomienie_sa_odrzucone(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    assert centrum.client.post("/api/shutdown").status_code == 202

    update = centrum.client.post("/api/tool-update")
    run = centrum.start(dry_run=True)

    closing = "Centrum rozliczeń się zamyka. Kliknij skrót „Centrum rozliczeń” na pulpicie, potem"
    assert (update.status_code, update.json()) == (409, {"message": f"{closing} zaktualizuj narzędzie."})
    assert (run.status_code, run.json()) == (409, {"message": f"{closing} uruchom proces."})
    assert repository.head() == before
    assert "aktualizacja-start" not in log_events(centrum)


def test_nieprzewidziana_porazka_daje_komunikat_a_klon_zostaje_bez_zmian(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    running = repository.head()
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
    # Commit przed aktualizacją to ten, z którego działa Centrum, choć Git go już nie poda.
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NIEOCZEKIWANY_BLAD przed={running} po=- biblioteki=nie"
    ]
    assert centrum.client.post("/api/tool-update").status_code == 202



def test_karta_widzi_porazke_dopiero_gdy_ponowne_klikniecie_jest_przyjete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    repository.in_clone("update-ref", "-d", "refs/heads/main")
    remove_tree = shutil.rmtree

    def slow_cleanup(path: Any, *args: Any, **kwargs: Any) -> None:
        # Sprzątanie po aktualizacji bywa wolne (antywirus, OneDrive); tata może kliknąć w jego trakcie.
        time.sleep(0.3)
        remove_tree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", slow_cleanup)

    failed = update_until_done(centrum)
    again = centrum.client.post("/api/tool-update")
    tool_update_until(centrum, lambda view: view["state"] != "running")

    assert failed["state"] == "failed"
    assert again.status_code == 202, again.json()

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


def test_porazka_aktualizacji_karta_dostaje_jako_komunikat_w_trzech_czesciach_a_narzedzie_zostaje(
    tmp_path: Path,
) -> None:
    # Reguły porażek są w ``test_aktualizacja_narzedzia.py``; tu jedna zamiana kodu na Komunikat karty.
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    with github_out_of_reach(repository):
        view = update_until_done(centrum)

    what = "Nie zaktualizowano narzędzia: brak połączenia z GitHubem."
    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": what,
            "where": "narzędzie na tym komputerze",
            "action": f"{STILL_WORKS} Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz.",
        },
        "next_action": "retry",
        "report": {"state": "ready"},
    }
    assert view["draft"]["title"] == f"BRAK_POLACZENIA: {what}"
    assert repository.head() == before
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=BRAK_POLACZENIA przed={before} po=- biblioteki=nie"]


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
    fingerprint = re.search(r"^- Odcisk problemu: ([0-9a-f]{16})$", body, re.MULTILINE)
    assert fingerprint is not None
    head, log_block = body.split("## Dziennik Centrum rozliczeń\n")
    assert head.splitlines() == [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        "- Kod: INNA_GALAZ",
        "- Co się stało: Nie zaktualizowano narzędzia: na tym komputerze jest inna gałąź narzędzia niż main.",
        "- Gdzie: narzędzie na tym komputerze",
        f"- Co zrobić: {TO_MAKS}",
        "",
        "## Aktualizacja narzędzia",
        "",
        "- Wynik: INNA_GALAZ",
        f"- Commit przed: {before}",
        "- Commit po: brak",
        "- Biblioteki instalowane: nie",
        "",
        "## Narzędzie",
        "",
        f"- Odcisk problemu: {fingerprint[1]}",
        "",
    ]
    log = centrum.log_path.read_text(encoding="utf-8").splitlines()
    started = next(line for line in log if " aktualizacja-start " in line)
    finished = next(line for line in log if " aktualizacja-koniec " in line)
    assert log_block.startswith("\n```text\n") and log_block.endswith(f"\n{started}\n{finished}\n```\n")
    assert re.search(r"fatal|error:|hint:|proba-maksa|origin\.git", body) is None
    assert centrum.client.get("/api/tool-update").json()["report"] == {"state": "sent"}
    assert "zgloszenie-wyslane z=aktualizacja numer=1" in centrum.log_path.read_text(encoding="utf-8")


def test_druga_nieudana_aktualizacja_wysyla_wlasne_zgloszenie(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    with github_out_of_reach(repository):
        update_until_done(centrum)
        assert send_report(centrum) == {"state": "sent"}
        box.close(1)

        again = update_until_done(centrum)
        state = send_report(centrum)

    assert (again["report"], state) == ({"state": "ready"}, {"state": "sent"})
    assert [report.title.split(":")[0] for report in box.sent] == ["BRAK_POLACZENIA"] * 2
    assert "- Poprzednie Zgłoszenie: #1" in box.sent[1].body.splitlines()


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


def nothing(repository: ToolRepository) -> None:
    pass


def test_gdy_opiekun_nie_wystartuje_klon_wraca_do_poprzedniej_wersji_a_karta_dostaje_komunikat(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, guardian_failure=nothing)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    view = update_until_result(centrum)

    assert (view["state"], view["message"]["what"], view["next_action"]) == (
        "failed",
        "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        "retry",
    )
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert centrum.surroundings.restarts == []
    assert "zamkniecie" not in log_events(centrum)
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie"
    ]
    assert centrum.start(dry_run=True).status_code == 200


def changes_new_version_file(repository: ToolRepository) -> None:
    repository.write("src/narzedzie.py", "WERSJA = 2  # zmienione, zanim opiekun miał wystartować\n")


def test_gdy_cofniecie_sie_nie_uda_karta_nie_mowi_ze_narzedzie_dziala_w_poprzedniej_wersji(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, guardian_failure=changes_new_version_file)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    view = update_until_result(centrum)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Aktualizacja narzędzia się nie udała i nie dało się przywrócić poprzedniej wersji.",
            "where": "narzędzie na tym komputerze",
            "action": "Kliknij „Zaktualizuj narzędzie” jeszcze raz. Jeśli komunikat wraca, kliknij „Wyślij do Maksa”.",
        },
        "next_action": "retry",
        "report": {"state": "ready"},
    }
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=COFNIECIE_NIEUDANE przed={before} po={newest} biblioteki=nie"
    ]
    interrupted = ToolClone(repository.clone).interrupted_update()
    assert interrupted is not None
    assert (interrupted.before, interrupted.after) == (before, newest)


def test_po_nieudanym_cofnieciu_kolejne_klikniecie_nie_mowi_ze_narzedzie_jest_aktualne_i_cofa_klon(
    tmp_path: Path,
) -> None:
    lock_once = threading.Event()

    def locks_index_once(repository: ToolRepository) -> None:
        if not lock_once.is_set():
            lock_once.set()
            (repository.clone / ".git" / "index.lock").touch()

    centrum, repository = updating_centrum(tmp_path, guardian_failure=locks_index_once)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    failed = update_until_result(centrum)
    (repository.clone / ".git" / "index.lock").unlink()

    view = update_until_result(centrum)

    assert failed["message"]["what"] == "Aktualizacja narzędzia się nie udała i nie dało się przywrócić poprzedniej wersji."
    assert (view["state"], view.get("message", {}).get("what")) == (
        "failed",
        "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
    )
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert ToolClone(repository.clone).interrupted_update() is None
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=COFNIECIE_NIEUDANE przed={before} po={newest} biblioteki=nie",
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie",
    ]
