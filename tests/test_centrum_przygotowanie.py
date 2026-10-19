"""Przygotowanie pliku zbiorczego z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
import json
import time
from pathlib import Path
from typing import Any, NoReturn

from fastapi.testclient import TestClient
import pytest

from rozliczenia import collective_preparation, preparation_cli, preparation_register
from rozliczenia.telemetry import MetricsStore
from rozliczenia.centrum import runs
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.tool_paths import ToolPaths

from tests.collective_preparation_fixtures import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    PreparationFixture,
    RegisterRow,
    make_preparation_fixture,
    register_order,
)
from tests.test_centrum_rozliczen import CENTRUM, FakePlatform, centrum as bare_centrum

# Wtorek po okresie 08_14_09_2026, więc to on jest ostatnim pełnym okresem.
TODAY = date(2026, 9, 16)


@dataclass
class PreparingCentrum:
    client: TestClient
    fixture: PreparationFixture
    metrics_path: Path

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any:
        return self.client.post("/api/runs", json={"process": "preparation", "period": period, "dry_run": dry_run})

    def metric_records(self) -> list[dict[str, Any]]:
        text = self.metrics_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]


def preparing_centrum(tmp_path: Path, rows: list[RegisterRow] | None = None) -> PreparingCentrum:
    """Centrum z zapamiętanym syntetycznym Rejestrem zleceń i folderem okresów oraz własnymi wzorcami i metrykami."""

    fixture = make_preparation_fixture(tmp_path, rows)
    metrics_path = tmp_path / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"
    platform = FakePlatform(chosen_files=[fixture.register_path], chosen_folders=[fixture.periods_directory])
    app = create_app(
        settings_path=tmp_path / "config" / "centrum-ustawienia.yaml",
        platform=platform,
        today=lambda: TODAY,
        tool_paths=ToolPaths(
            worker_config=fixture.config_path,
            internal_template=fixture.internal_template_path,
            collective_template=fixture.collective_template_path,
            preparation_metrics=metrics_path,
        ),
    )
    client = TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM})
    client.post("/api/settings/register/choose")
    client.post("/api/settings/periods-directory/choose")
    return PreparingCentrum(client, fixture, metrics_path)


def run_events(client: TestClient) -> Iterator[dict[str, Any]]:
    """Zdarzenia strumienia SSE Uruchomień procesu, każde jako sparsowany JSON z linii ``data:``."""

    with client.stream("GET", "/api/runs/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line.removeprefix("data: "))


def views_until(client: TestClient, *states: str) -> list[dict[str, Any]]:
    """Widoki bieżącego Uruchomienia ze strumienia, aż do pierwszego w jednym ze stanów ``states``."""

    views = []
    for event in run_events(client):
        views.append(event["view"])
        if event["view"]["state"] in states:
            return views
    raise AssertionError("Strumień skończył się przed oczekiwanym stanem.")


def finished_view(client: TestClient) -> dict[str, Any]:
    return views_until(client, "finished")[-1]


def test_podglad_bez_zapisu_pokazuje_plan_i_nie_tworzy_plikow_ani_folderu_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    started = centrum.start(dry_run=True)
    finished = finished_view(centrum.client)

    assert started.status_code == 200
    assert started.json()["state"] == "running"
    assert finished["run"]["process"] == "preparation"
    assert (finished["run"]["period"], finished["run"]["dry_run"]) == (PERIOD, True)
    result = finished["result"]
    assert (result["result"], result["ending"], result["next_action"]) == ("OK", "finished", "run")
    assert result["summary"] == {
        "period": PERIOD,
        "period_order_count": 4,
        "successful_order_count": 3,
        "skipped_empty_rows": 5,
        "orders_per_day": [
            {"label": "wt 08.09.2026", "count": 1},
            {"label": "śr 09.09.2026", "count": 1},
            {"label": "czw 10.09.2026", "count": 0},
            {"label": "pt 11.09.2026", "count": 0},
            {"label": "sob 12.09.2026", "count": 1},
            {"label": "niedz 13.09.2026", "count": 0},
            {"label": "pon 14.09.2026", "count": 1},
        ],
        "internal_settlement_file": INTERNAL_SETTLEMENT_NAME,
        "collective_file": COLLECTIVE_FILE_NAME,
    }
    assert (result["stops"], result["warnings"]) == ([], [])
    assert "DRY-RUN: Nic nie zapisano" in result["lines"]
    assert list(centrum.fixture.periods_directory.iterdir()) == []
    [record] = centrum.metric_records()
    assert (record["mode"], record["period"], record["result"]) == ("DRY-RUN", PERIOD, "OK")


def test_uruchom_publikuje_oba_pliki_okresu_i_zmienia_status_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    centrum.start(dry_run=False)
    result = finished_view(centrum.client)["result"]
    board = centrum.client.get("/api/periods").json()

    assert (result["result"], result["status_line"], result["next_action"]) == (
        "OK",
        "Status końcowy: OK",
        "open_period_folder",
    )
    assert sorted(path.name for path in centrum.fixture.period_directory.iterdir()) == [
        COLLECTIVE_FILE_NAME,
        INTERNAL_SETTLEMENT_NAME,
    ]
    [row] = [row for row in board["periods"] if row["token"] == PERIOD]
    assert row["status_label"] == "Plik zbiorczy przygotowany"
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"], record["counters"]["successful_orders"]) == ("RUN", "OK", 3)


def incomplete_period_rows() -> list[RegisterRow]:
    """Okres 08_14_09_2026, w którym ostatnie zlecenie jest z soboty."""

    return [
        register_order(1, datetime(2026, 9, 8, 8, 0)),
        None,
        register_order(2, datetime(2026, 9, 9, 10, 0), successful="nie"),
        register_order(3, datetime(2026, 9, 12, 12, 0)),
    ]


def awaiting_decision(tmp_path: Path) -> tuple[PreparingCentrum, dict[str, Any]]:
    """Uruchom na niepełnym okresie, które czeka na decyzję taty."""

    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    centrum.start(dry_run=False)
    return centrum, views_until(centrum.client, "awaiting_decision")[-1]


def decide(centrum: PreparingCentrum, view: dict[str, Any], answer: str) -> Any:
    return centrum.client.post(f"/api/runs/{view['run']['id']}/decision", json={"answer": answer})


INCOMPLETE_ORDERS_PER_DAY = [
    {"label": "wt 08.09.2026", "count": 1},
    {"label": "śr 09.09.2026", "count": 1},
    {"label": "czw 10.09.2026", "count": 0},
    {"label": "pt 11.09.2026", "count": 0},
    {"label": "sob 12.09.2026", "count": 1},
    {"label": "niedz 13.09.2026", "count": 0},
    {"label": "pon 14.09.2026", "count": 0},
]


def test_niepelny_okres_czeka_na_decyzje_taty_z_zleceniami_na_dzien(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    assert view["decision"] == {
        "question": "Kontynuować mimo niepełnego okresu?",
        "title": "Ostrzeżenie: niepełny okres",
        "message": {
            "what": (
                "Ostatnie zlecenie okresu jest z soboty 12.09.2026, a okres kończy się w poniedziałek 14.09.2026. "
                "Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu."
            ),
            "where": f"plik {centrum.fixture.register_path.name}, arkusz ZLECENIA, okres {PERIOD}",
            "action": (
                "Sprawdź liczby zleceń na dzień. Jeśli brakuje zleceń, przerwij, uzupełnij eksport w Rejestrze "
                "zleceń, zapisz go i uruchom ponownie. Jeśli okres jest pełny, kontynuuj."
            ),
        },
        "count_groups": [{"title": "Zlecenia na dzień", "counts": INCOMPLETE_ORDERS_PER_DAY}],
    }
    assert [phase["state"] for phase in view["progress"]["phases"]] == ["completed", "completed", "completed", "pending"]
    assert list(centrum.fixture.periods_directory.iterdir()) == []
    decide(centrum, view, "abort")


def test_kontynuuj_przy_niepelnym_okresie_publikuje_pliki_z_ostrzezeniem(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    decided = decide(centrum, view, "continue")
    result = finished_view(centrum.client)["result"]

    assert (decided.status_code, decided.json()["state"]) == (200, "running")
    assert (result["result"], result["ending"]) == ("OK", "finished")
    assert [warning["what"] for warning in result["warnings"]] == [view["decision"]["message"]["what"]]
    assert result["summary"]["orders_per_day"] == INCOMPLETE_ORDERS_PER_DAY
    assert centrum.fixture.collective_file_path.is_file()
    assert centrum.fixture.internal_settlement_path.is_file()


def test_przerwij_bez_zapisu_zatrzymuje_z_trzema_czesciami_dla_centrum(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    decide(centrum, view, "abort")
    result = finished_view(centrum.client)["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("BLAD_KRYTYCZNY", "stop", "rerun")
    assert result["status_line"] == "Status końcowy: ZATRZYMANO"
    assert result["stops"] == [
        {
            "what": "Przerwano z powodu niepełnego okresu, zgodnie z odpowiedzią. Nie utworzono żadnego pliku.",
            "where": f"okres {PERIOD}",
            "action": (
                "Uzupełnij eksport zleceń w Rejestrze zleceń, zapisz go, zamknij i uruchom ponownie. "
                "Jeśli okres jest pełny, przy decyzji wybierz „Kontynuuj”."
            ),
        }
    ]
    assert "wpisz t" not in " ".join(result["lines"])
    assert list(centrum.fixture.periods_directory.iterdir()) == []
    [record] = centrum.metric_records()
    assert (record["result"], record["phase_durations_ms"]["Zapisywanie"]) == ("BLAD_KRYTYCZNY", 0)


def test_czas_czekania_na_decyzje_nie_wlicza_sie_do_czasu_ani_metryk(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)
    waited_ms = 1500

    time.sleep(waited_ms / 1000)
    decide(centrum, view, "continue")
    result = finished_view(centrum.client)["result"]

    [record] = centrum.metric_records()
    assert result["total_duration_ms"] == record["total_duration_ms"]
    assert record["total_duration_ms"] < waited_ms
    assert f"Czas uruchomienia: {record['total_duration_ms']} ms" in result["lines"]


def test_decyzja_czeka_po_ponownym_podlaczeniu_i_odswiezeniu_karty(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    [first_after_reconnect] = views_until(centrum.client, "awaiting_decision")
    after_refresh = centrum.client.get("/api/runs/current").json()

    assert first_after_reconnect == view
    assert after_refresh == view
    decide(centrum, view, "abort")


def test_drugie_uruchomienie_w_trakcie_dostaje_bezpieczny_komunikat_trwa_juz(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)

    second = centrum.start(dry_run=True)

    assert second.status_code == 409
    assert second.json() == {
        "message": (
            f"Trwa już Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
            "Poczekaj na jego wynik w Uruchomieniach."
        )
    }
    assert centrum.client.get("/api/runs/current").json() == view
    decide(centrum, view, "abort")
    assert finished_view(centrum.client)["state"] == "finished"
    assert centrum.start(dry_run=True).status_code == 200


def test_decyzja_poza_oczekiwaniem_jest_odrzucona(tmp_path: Path) -> None:
    centrum, view = awaiting_decision(tmp_path)
    decide(centrum, view, "abort")
    finished_view(centrum.client)

    again = decide(centrum, view, "continue")
    unknown = centrum.client.post("/api/runs/nieznane/decision", json={"answer": "continue"})

    assert (again.status_code, again.json()) == (409, {"message": "To Uruchomienie procesu nie czeka na decyzję."})
    assert (unknown.status_code, unknown.json()) == (404, {"message": "Nie ma takiego Uruchomienia procesu."})


def test_strumien_pokazuje_etapy_po_kolei_z_licznikami_i_decyzja_miedzy_planowaniem_a_zapisywaniem(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    seen: list[tuple[str, str | None, str | None, int]] = []

    for event in run_events(centrum.client):
        view = event["view"]
        if view["state"] == "idle":
            centrum.start(dry_run=False)
            continue
        notice = view.get("notice")
        seen.append(
            (
                view["state"],
                notice and notice["kind"],
                notice and notice["phase"],
                view["progress"]["issue_count"],
            )
        )
        if view["state"] == "awaiting_decision":
            decide(centrum, view, "continue")
        if view["state"] == "finished":
            break

    assert seen == [
        ("running", None, None, 0),
        ("running", "PHASE_STARTED", "Sprawdzanie", 0),
        ("running", "PHASE_ENDED", "Sprawdzanie", 0),
        ("running", "PHASE_STARTED", "Odczyt danych", 0),
        ("running", "PHASE_ENDED", "Odczyt danych", 0),
        ("running", "ISSUE_COUNT", "Odczyt danych", 0),
        ("running", "PHASE_STARTED", "Planowanie", 0),
        ("running", "PHASE_ENDED", "Planowanie", 0),
        ("running", "PLAN_READY", "Planowanie", 1),
        ("awaiting_decision", None, None, 1),
        ("running", "PLAN_READY", "Planowanie", 1),
        ("running", "PHASE_STARTED", "Zapisywanie", 1),
        ("running", "PHASE_ENDED", "Zapisywanie", 1),
        ("finished", None, None, 1),
    ]


def phase_states(view: dict[str, Any]) -> dict[str, str]:
    return {phase["phase"]: phase["state"] for phase in view["progress"]["phases"]}


def test_nienadpisywanie_zatrzymuje_bez_zmiany_istniejacego_pliku_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.period_directory.mkdir()
    centrum.fixture.collective_file_path.write_bytes(b"reczne poprawki taty")

    centrum.start(dry_run=False)
    view = finished_view(centrum.client)
    result = view["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("BLAD_KRYTYCZNY", "stop", "rerun")
    assert result["status_line"] == "Status końcowy: ZATRZYMANO"
    [stop] = result["stops"]
    assert stop["what"].startswith("Plik tego okresu już istnieje, więc nie został nadpisany.")
    assert stop["where"] == f"folder INEA\\{PERIOD}, plik {COLLECTIVE_FILE_NAME}"
    assert stop["action"].startswith("Sprawdź, czy wybrano właściwy okres.")
    assert result["lines"][:4] == [
        "Status końcowy: ZATRZYMANO",
        f"Co się stało: {stop['what']}",
        f"Gdzie: {stop['where']}",
        f"Co zrobić: {stop['action']}",
    ]
    assert phase_states(view)["Sprawdzanie"] == "failed"
    assert centrum.fixture.collective_file_path.read_bytes() == b"reczne poprawki taty"
    assert not centrum.fixture.internal_settlement_path.exists()
    [record] = centrum.metric_records()
    assert (record["completed"], record["result"]) == (False, "BLAD_KRYTYCZNY")


def test_nieoczekiwany_blad_pokazuje_trzy_czesci_bez_tekstu_wyjatku_i_danych_klientow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)

    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    monkeypatch.setattr(preparation_register, "read_register", fail_unexpectedly)

    centrum.start(dry_run=False)
    view = finished_view(centrum.client)
    shown = json.dumps(view, ensure_ascii=False)

    assert (view["result"]["ending"], view["result"]["status_line"]) == ("unexpected", "Status końcowy: BŁĄD")
    assert view["result"]["stops"] == [
        {
            "what": "Wystąpił nieoczekiwany błąd. Nie utworzono żadnego pliku.",
            "where": "Przygotowanie pliku zbiorczego",
            "action": "Uruchom ponownie. Jeśli błąd wraca, przekaż to osobie utrzymującej narzędzie.",
        }
    ]
    assert phase_states(view)["Odczyt danych"] == "failed"
    assert "SYN-" not in shown
    assert "RuntimeError" not in shown
    assert list(centrum.fixture.periods_directory.iterdir()) == []


def test_niepokazane_podsumowanie_po_zapisie_mowi_zeby_nie_uruchamiac_ponownie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    prepare = collective_preparation.prepare_collective_file

    def prepare_with_unprintable_summary(*args: Any, **kwargs: Any) -> Any:
        summary = prepare(*args, **kwargs)
        summary.orders_per_day = {"SYN-001": 1}  # type: ignore[dict-item]  # podsumowanie, którego nie da się pokazać
        return summary

    monkeypatch.setattr(collective_preparation, "prepare_collective_file", prepare_with_unprintable_summary)

    centrum.start(dry_run=False)
    result = finished_view(centrum.client)["result"]

    assert (result["ending"], result["next_action"], result["summary"]) == ("after_engine", "open_period_folder", None)
    assert result["stops"] == [
        {
            "what": "Pliki okresu powstały, ale nie udało się pokazać podsumowania.",
            "where": "Przygotowanie pliku zbiorczego",
            "action": (
                "Nie uruchamiaj ponownie: oba pliki okresu już są. "
                "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
            ),
        }
    ]
    assert "SYN-" not in json.dumps(result, ensure_ascii=False)
    assert centrum.fixture.collective_file_path.is_file()


def test_wybor_okresu_proponuje_ostatni_pelny_okres_i_starsze_ze_statusem_okresu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.period_directory.mkdir()
    centrum.fixture.collective_file_path.touch()

    [setup] = centrum.client.get("/api/runs/setup").json()["processes"]

    assert (setup["process"], setup["title"], setup["blocker"]) == ("preparation", "Przygotowanie pliku zbiorczego", None)
    assert setup["reminder"] == "Zapisz i zamknij Rejestr zleceń w Excelu"
    assert setup["preselected_period"] == PERIOD
    assert [(choice["token"], choice["last_complete"]) for choice in setup["periods"][:3]] == [
        (PERIOD, True),
        ("01_07_09_2026", False),
        ("25_31_08_2026", False),
    ]
    assert len(setup["periods"]) == 8
    assert setup["periods"][0]["status_label"] == "Plik zbiorczy przygotowany"
    assert setup["periods"][1]["status_label"] == "Brak plików okresu"


def test_bez_wskazanego_rejestru_zlecen_uruchomienie_jest_odrzucone(tmp_path: Path) -> None:
    client = bare_centrum(tmp_path, today=TODAY).client

    [setup] = client.get("/api/runs/setup").json()["processes"]
    refused = client.post("/api/runs", json={"process": "preparation", "period": PERIOD, "dry_run": True})

    assert setup["blocker"] == "Najpierw wskaż Rejestr zleceń i folder okresów."
    assert (refused.status_code, refused.json()) == (409, {"message": "Najpierw wskaż Rejestr zleceń i folder okresów."})
    assert client.get("/api/runs/current").json() == {"state": "idle"}


def test_okres_spoza_kalendarza_okresow_jest_odrzucony(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    refused = centrum.start(dry_run=True, period="08_14_9_2026")

    assert (refused.status_code, refused.json()) == (404, {"message": "Nie ma takiego okresu."})
    assert not centrum.metrics_path.exists()


def test_uruchomienie_z_obcej_strony_jest_odrzucone(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    refused = centrum.client.post(
        "/api/runs",
        json={"process": "preparation", "period": PERIOD, "dry_run": False},
        headers={"Origin": "http://zly.example"},
    )

    assert refused.status_code == 403
    assert centrum.client.get("/api/runs/current").json() == {"state": "idle"}
    assert list(centrum.fixture.periods_directory.iterdir()) == []


def test_centrum_dopisuje_rekord_do_pliku_metryk_cli_w_jego_schemacie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.start(dry_run=True)
    finished_view(centrum.client)
    fixture = centrum.fixture

    cli_exit_code = preparation_cli.main(
        [
            "--register", str(fixture.register_path),
            "--periods-directory", str(fixture.periods_directory),
            "--period", PERIOD,
            "--config", str(fixture.config_path),
            "--internal-template", str(fixture.internal_template_path),
            "--collective-template", str(fixture.collective_template_path),
            "--metrics", str(centrum.metrics_path),
            "--dry-run",
        ],
        output=StringIO(),
    )
    records = MetricsStore(centrum.metrics_path, preparation_cli.PROCESS.counter_names).read()

    assert ToolPaths().preparation_metrics == preparation_cli.default_metrics_path()
    assert cli_exit_code == 0
    assert [(record["mode"], record["result"]) for record in records] == [("DRY-RUN", "OK"), ("DRY-RUN", "OK")]
    assert records[0].keys() == records[1].keys()
    assert records[0]["counters"] == records[1]["counters"]


def test_awaria_podgladu_na_zywo_nie_zmienia_wyniku_zapisu_ani_metryk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)

    def broken_view(*args: object) -> NoReturn:
        raise ValueError("synthetic Centrum view failure")

    monkeypatch.setattr(runs, "notice_view", broken_view)

    centrum.start(dry_run=False)
    views = views_until(centrum.client, "finished")
    result = views[-1]["result"]

    assert any(view["state"] == "running" and view["progress_stale"] for view in views)
    assert views[-1]["progress_stale"] is True
    assert (result["result"], result["ending"]) == ("OK", "finished")
    assert result["notices"] == ["Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."]
    assert centrum.fixture.collective_file_path.is_file()
    [record] = centrum.metric_records()
    assert (record["result"], record["completed"]) == ("OK", True)
