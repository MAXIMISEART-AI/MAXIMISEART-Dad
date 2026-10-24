"""Powiadomienia (ADR 0015, #323) przez HTTP API Centrum z fałszywą Skrzynką Zgłoszeń i podstawionym zegarem."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from rozliczenia.centrum.notifications import CHECK_WAIT_S
from rozliczenia.centrum.report_box import CloseReason, Refused, Unreachable

from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, stopped_for_maks

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
NOTE_TITLE = "Plik zbiorczy otwiera się długo"
CLOSED_AT = datetime(2026, 10, 20, 9, 15, tzinfo=timezone.utc)


def with_key(centrum: PreparingCentrum) -> None:
    (centrum.tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")


def sent_report(centrum: PreparingCentrum) -> str:
    """Zgłoszenie „do Maksa” wysłane z tego komputera; zwraca jego „Co się stało”."""

    run_id = stopped_for_maks(centrum)
    assert centrum.client.post(f"/api/runs/{run_id}/diagnosis").status_code == 200
    assert centrum.client.post(f"/api/runs/{run_id}/report").json() == {"state": "sent"}
    return centrum.surroundings.report_box.sent[-1].title.split(": ", 1)[1]


def sent_note(centrum: PreparingCentrum, title: str = NOTE_TITLE) -> dict[str, Any]:
    response = centrum.client.post("/api/dad-notes", json={"title": title, "body": "Excel myśli minutę."})
    assert response.status_code == 200, response.json()
    answer: dict[str, Any] = response.json()
    return answer


def number_of(centrum: PreparingCentrum, title: str) -> int:
    return next(issue.number for issue in centrum.surroundings.report_box.issues if issue.title == title)


def notifications(centrum: PreparingCentrum) -> dict[str, Any]:
    response = centrum.client.get("/api/notifications")
    assert response.status_code == 200, response.json()
    answer: dict[str, Any] = response.json()
    return answer


def rows(centrum: PreparingCentrum) -> list[tuple[str, str, str, bool]]:
    """Powiadomienia jak w widoku: rodzaj, nazwa, stan i czy nowe."""

    return [
        (item["kind"], item["title"] if item["kind"] == "uwaga" else item["what"], item["state"], item["unread"])
        for item in notifications(centrum)["items"]
    ]


def polls(centrum: PreparingCentrum) -> int:
    """Ile razy Centrum pytało skrzynkę o stan spraw taty (issue z etykietą, także zamknięte)."""

    return sum(include_closed for _, include_closed in centrum.surroundings.report_box.listed)


def read(centrum: PreparingCentrum, ids: list[str]) -> dict[str, Any]:
    response = centrum.client.post("/api/notifications/read", json={"ids": ids})
    assert response.status_code == 200, response.json()
    answer: dict[str, Any] = response.json()
    return answer


def test_wyslana_uwaga_i_zgloszenie_daja_powiadomienia_a_zamkniecie_mowi_co_zrobil_maks(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    what = sent_report(centrum)
    assert sent_note(centrum) == {"state": "sent"}
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock

    assert rows(centrum) == [("uwaga", NOTE_TITLE, "wyslana", False), ("zgloszenie", what, "wyslana", False)]
    assert notifications(centrum)["unread"] == 0

    box.close(number_of(centrum, NOTE_TITLE), "completed", CLOSED_AT)
    box.close(box.sent[-1].number, "not_planned", CLOSED_AT + timedelta(hours=1))
    clock.advance(minutes=10)

    assert rows(centrum) == [("zgloszenie", what, "przeczytana", True), ("uwaga", NOTE_TITLE, "rozwiazana", True)]
    answer = notifications(centrum)
    assert answer["unread"] == 2
    assert [item["at"] for item in answer["items"]] == ["2026-10-20T10:15:00Z", "2026-10-20T09:15:00Z"]
    assert "Excel myśli minutę." not in str(answer)


@pytest.mark.parametrize(
    ("reason", "state"),
    [("completed", "rozwiazana"), ("not_planned", "przeczytana"), ("duplicate", "przeczytana"), (None, "rozwiazana")],
    ids=["completed", "not_planned", "duplicate", "bez-powodu"],
)
def test_powod_zamkniecia_issue_rozstrzyga_stan_sprawy(
    tmp_path: Path, reason: CloseReason | None, state: str
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    sent_note(centrum)
    centrum.surroundings.report_box.close(number_of(centrum, NOTE_TITLE), reason)

    assert rows(centrum) == [("uwaga", NOTE_TITLE, state, True)]


def test_uwaga_bez_klucza_czeka_na_internet_bez_kropki_a_skrzynka_nie_jest_pytana(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    assert sent_note(centrum) == {"state": "waiting"}

    assert rows(centrum) == [("uwaga", NOTE_TITLE, "czeka_na_internet", False)]
    assert notifications(centrum)["unread"] == 0
    assert centrum.surroundings.report_box.listed == []


def test_oznacz_przeczytane_gasi_kropke_takze_po_restarcie_a_nowy_stan_znow_jest_nowy(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    sent_note(centrum)
    sent_note(centrum, "Suma godzin na dole tabeli")
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock
    box.close(number_of(centrum, NOTE_TITLE))
    before = notifications(centrum)
    assert before["unread"] == 1

    after = read(centrum, [item["id"] for item in before["items"]])

    assert after["unread"] == 0
    assert [item["unread"] for item in after["items"]] == [False, False]
    centrum.restart()
    assert notifications(centrum)["unread"] == 0
    box.close(number_of(centrum, "Suma godzin na dole tabeli"), "not_planned")
    clock.advance(minutes=10)
    assert rows(centrum) == [
        ("uwaga", "Suma godzin na dole tabeli", "przeczytana", True),
        ("uwaga", NOTE_TITLE, "rozwiazana", False),
    ]


def test_przeczytane_sa_tylko_powiadomienia_ktore_tata_zobaczyl(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    sent_note(centrum)
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock
    seen = notifications(centrum)
    box.close(number_of(centrum, NOTE_TITLE))
    clock.advance(minutes=10)
    assert notifications(centrum)["unread"] == 1

    assert read(centrum, [item["id"] for item in seen["items"]])["unread"] == 1


def test_skrzynka_jest_pytana_przy_starcie_i_najwyzej_raz_na_10_minut(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    sent_report(centrum)
    clock = centrum.surroundings.clock
    asked = polls(centrum)

    notifications(centrum)
    notifications(centrum)
    clock.advance(minutes=9.9)
    notifications(centrum)

    assert polls(centrum) == asked + 1

    clock.advance(minutes=0.1)
    notifications(centrum)
    notifications(centrum)

    assert polls(centrum) == asked + 2

    centrum.restart()
    notifications(centrum)

    assert polls(centrum) == asked + 3


def test_zamknieta_sprawa_nie_jest_pytana_ponownie_a_jej_stan_zostaje_po_restarcie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number, "not_planned")
    assert rows(centrum) == [("zgloszenie", what, "przeczytana", True)]
    asked = polls(centrum)

    centrum.restart()
    box.search_failure = Unreachable()

    assert rows(centrum) == [("zgloszenie", what, "przeczytana", True)]
    assert polls(centrum) == asked


@pytest.mark.parametrize("failure", [Unreachable(), Refused()], ids=["brak-sieci", "odmowa"])
def test_porazka_skrzynki_przechodzi_po_cichu_z_ostatnim_znanym_stanem(
    tmp_path: Path, failure: Refused | Unreachable
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number)
    box.search_failure = failure
    log_before = centrum.log_path.read_text(encoding="utf-8")
    asked = polls(centrum)

    assert rows(centrum) == [("zgloszenie", what, "wyslana", False)]
    assert polls(centrum) == asked + 1
    assert centrum.log_path.read_text(encoding="utf-8") == log_before


def test_bez_wyslanych_spraw_albo_klucza_skrzynka_nie_jest_pytana(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    box = centrum.surroundings.report_box

    assert notifications(centrum) == {"unread": 0, "items": []}
    assert box.listed == []

    sent_report(centrum)
    asked = polls(centrum)
    (tmp_path / "config" / "zgloszenia-klucz.txt").unlink()

    notifications(centrum)
    assert polls(centrum) == asked


def test_przy_starcie_centrum_skrzynka_jest_pytana_w_tle_przed_odczytem_powiadomien(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number)
    centrum.restart()
    asked = polls(centrum)

    with centrum.client:  # start Centrum, jak po kliknięciu skrótu
        deadline = time.monotonic() + 5
        while polls(centrum) == asked and time.monotonic() < deadline:
            time.sleep(0.01)
        asked_at_start = polls(centrum)

        assert rows(centrum) == [("zgloszenie", what, "rozwiazana", True)]

    assert asked_at_start == polls(centrum) == asked + 1


def test_spozniona_odpowiedz_skrzynki_nie_wstrzymuje_powiadomien_a_jej_stan_i_tak_zostaje(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number)
    box.search_hold = threading.Event()
    started = time.monotonic()

    try:
        assert rows(centrum) == [("zgloszenie", what, "wyslana", False)]
        took = time.monotonic() - started
    finally:
        box.search_hold.set()

    assert took < CHECK_WAIT_S + 2
    deadline = time.monotonic() + 5
    while rows(centrum)[0][2] == "wyslana" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert rows(centrum) == [("zgloszenie", what, "rozwiazana", True)]
