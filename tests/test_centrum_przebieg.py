"""Przebieg rozliczeń z Centrum rozliczeń przez HTTP API i strumień zdarzeń, jak widzi je przeglądarka."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import StringIO
import json
from pathlib import Path
import threading
from typing import Any, NoReturn

from fastapi.testclient import TestClient
import pytest

from rozliczenia import cli, engine, template_settlement
from rozliczenia.centrum import run_view
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.metrics import MetricsFiles
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.telemetry import MetricsStore

from tests.test_centrum_przygotowanie import finished_view, phase_states, run_events
from tests.test_centrum_rozliczen import CENTRUM, FakePlatform, centrum as bare_centrum
from tests.test_settlement_engine import PERIOD, SOURCE_NAME, write_mapping, write_source, write_template

# Środa po okresie 08_14_09_2026, więc to on jest ostatnim pełnym okresem.
TODAY = date(2026, 9, 16)
WORKER_SETTLEMENTS = f"Rozliczenie pracowników {PERIOD}"


@dataclass
class SettlingCentrum:
    client: TestClient
    periods_directory: Path
    metrics_path: Path
    log_path: Path

    @property
    def period_directory(self) -> Path:
        return self.periods_directory / PERIOD

    @property
    def worker_settlements(self) -> Path:
        return self.period_directory / WORKER_SETTLEMENTS

    def start(self, *, dry_run: bool, period: str = PERIOD) -> Any:
        return self.client.post("/api/runs", json={"process": "settlement", "period": period, "dry_run": dry_run})

    def metric_records(self) -> list[dict[str, Any]]:
        text = self.metrics_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]


def settling_centrum(tmp_path: Path, *, include_unmapped: bool = False) -> SettlingCentrum:
    """Centrum z zapamiętanym folderem okresów, w którym okres ma tylko syntetyczny Plik zbiorczy."""

    periods_directory = tmp_path / "INEA"
    (periods_directory / PERIOD).mkdir(parents=True)
    write_source(periods_directory / PERIOD / SOURCE_NAME, include_unmapped=include_unmapped)
    config = tmp_path / "config"
    config.mkdir()
    worker_template = config / "Wzorzec rozliczenia pracownika.xlsx"
    write_template(worker_template)
    metrics_path = tmp_path / ".rozliczenia-metrics.jsonl"
    log_path = tmp_path / "logs" / "centrum-rozliczen.log"
    log = CentrumLog(log_path)
    app = create_app(
        settings_path=config / "centrum-ustawienia.yaml",
        platform=FakePlatform(chosen_folders=[periods_directory]),
        log=log,
        shutdown=Shutdown(log),
        today=lambda: TODAY,
        configuration_files=ConfigurationFiles(
            worker_config=write_mapping(config / "worker_mapping.yaml"),
            internal_template=config / "Wzorzec rozliczenia wewnętrznego.xlsx",
            collective_template=config / "Wzorzec pliku zbiorczego.xlsx",
            worker_template=worker_template,
        ),
        metrics_files=MetricsFiles(
            preparation=tmp_path / ".przygotowanie-pliku-zbiorczego-metrics.jsonl", settlement=metrics_path
        ),
    )
    client = TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM})
    client.post("/api/settings/periods-directory/choose")
    return SettlingCentrum(client, periods_directory, metrics_path, log_path)


def test_podglad_bez_zapisu_pokazuje_plan_plikow_na_wykonawce_bez_folderu_rozliczen_pracownikow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    started = centrum.start(dry_run=True)
    assert (started.status_code, started.json()["state"]) == (200, "running")
    finished = finished_view(centrum.client)

    assert (finished["run"]["process"], finished["run"]["title"]) == ("settlement", "Przebieg rozliczeń")
    assert finished["run"]["confirms_readiness"] is True
    result = finished["result"]
    assert (result["result"], result["ending"], result["next_action"]) == ("OK", "finished", "run")
    assert result["headline"] == "Podgląd gotowy · nic nie zapisano"
    assert result["summary"] == {
        "figures": [
            {"label": "Wiersze danych", "value": 3, "unit": "count"},
            {"label": "Planowane szablony", "value": 2, "unit": "count"},
            {"label": "Puste szablony", "value": 1, "unit": "count"},
        ],
        "counts": None,
        "files": [],
        "file_plan": [
            {"file": f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx", "rows": 2},
            {"file": f"Rozliczenie {PERIOD} - Darek Nowak.xlsx", "rows": 1},
            {"file": f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx", "rows": 0},
        ],
    }
    assert (result["stops"], result["warnings"]) == ([], [])
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["period"], record["result"]) == ("DRY-RUN", PERIOD, "OK")


def run_to_end(centrum: SettlingCentrum, *, dry_run: bool) -> dict[str, Any]:
    started = centrum.start(dry_run=dry_run)
    assert started.status_code == 200, started.json()
    return finished_view(centrum.client)


def test_uruchom_publikuje_folder_rozliczen_pracownikow_i_zmienia_status_okresu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    result = run_to_end(centrum, dry_run=False)["result"]
    board = centrum.client.get("/api/periods").json()

    assert (result["result"], result["ending"], result["next_action"]) == ("OK", "finished", "open_period_folder")
    assert result["headline"] == "Rozliczenia pracowników gotowe"
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Zapisane szablony", 2),
        ("Puste szablony", 1),
        ("Pominięte szablony", 0),
    ]
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME, WORKER_SETTLEMENTS]
    assert sorted(path.name for path in centrum.worker_settlements.iterdir()) == [
        file["file"] for file in result["summary"]["file_plan"]
    ]
    [row] = [row for row in board["periods"] if row["token"] == PERIOD]
    assert (row["status_label"], row["worker_settlement_count"]) == ("Rozliczenia pracowników gotowe", 3)
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"], record["counters"]["written"]) == ("RUN", "OK", 2)


def test_blad_przy_szablonie_pracownika_nie_publikuje_zadnego_pliku_pracownika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)
    process_template = template_settlement.process_template

    def fail_for_darek(worker_name: str, *args: Any) -> Any:
        if worker_name == "Darek Nowak":
            raise OSError("synthetic write failure")
        return process_template(worker_name, *args)

    monkeypatch.setattr(template_settlement, "process_template", fail_for_darek)

    view = run_to_end(centrum, dry_run=False)

    assert (view["result"]["ending"], view["result"]["next_action"]) == ("stop", "rerun")
    assert view["result"]["stops"] == [
        {
            "what": "Nie udało się przygotować skoroszytu pracownika Darek Nowak. Nie utworzono żadnego pliku pracownika.",
            "where": f"folder {PERIOD}\\{WORKER_SETTLEMENTS}",
            "action": "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie.",
        }
    ]
    assert view["progress"]["templates_completed"] == 1
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]


def test_nieoczekiwany_blad_pokazuje_komunikat_z_katalogu_bez_tekstu_wyjatku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)

    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    monkeypatch.setattr(engine, "run_settlements", fail_unexpectedly)

    result = run_to_end(centrum, dry_run=False)["result"]
    shown = json.dumps(result, ensure_ascii=False)

    assert (result["result"], result["ending"], result["headline"]) == ("BLAD_KRYTYCZNY", "unexpected", "Błąd")
    assert result["stops"] == [
        {
            "what": "Wystąpił nieoczekiwany błąd. Nie utworzono żadnego pliku pracownika.",
            "where": "Przebieg rozliczeń",
            "action": "Uruchom ponownie. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie.",
        }
    ]
    assert "SYN-" not in shown
    assert "RuntimeError" not in shown
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"]) == ("RUN", "BLAD_KRYTYCZNY")


def test_wynik_ktorego_nie_da_sie_pokazac_to_niepokazane_podsumowanie_z_tym_samym_wynikiem_co_w_metrykach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)

    def broken_summary(*args: object, **kwargs: object) -> NoReturn:
        raise ValueError("synthetic summary failure SYN-001")

    monkeypatch.setattr(run_view.ProcessView, "summary", broken_summary)

    result = run_to_end(centrum, dry_run=False)["result"]

    assert (result["ending"], result["headline"], result["next_action"]) == ("after_engine", "Błąd", "open_period_folder")
    assert result["stops"] == [
        {
            "what": "Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania.",
            "where": "Przebieg rozliczeń",
            "action": (
                "Nie uruchamiaj ponownie: Folder rozliczeń pracowników już jest. "
                "Sprawdź Folder okresu i przekaż ten komunikat osobie utrzymującej narzędzie."
            ),
        }
    ]
    assert (result["summary"], result["warnings"]) == (None, [])
    assert "SYN-" not in json.dumps(result, ensure_ascii=False)
    assert centrum.worker_settlements.is_dir()
    [record] = centrum.metric_records()
    assert record["result"] == result["result"] == "BLAD_KRYTYCZNY"


def test_strumien_pokazuje_postep_szablonow_pracownikow_z_biezacym_wykonawca(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    seen: list[tuple[str | None, int, int]] = []

    for event in run_events(centrum.client):
        view = event["view"]
        if view["state"] == "idle":
            centrum.start(dry_run=False)
            continue
        progress = view["progress"]
        shown = (progress["current_worker"], progress["templates_completed"], progress["template_total"])
        if view["state"] == "running" and progress["template_total"] > 0 and (not seen or seen[-1] != shown):
            seen.append(shown)
        if view["state"] == "finished":
            break

    assert seen == [
        (None, 0, 3),
        ("Adrian Maciejewski", 0, 3),
        (None, 1, 3),
        ("Darek Nowak", 1, 3),
        (None, 2, 3),
        ("Kamil Frontczak", 2, 3),
        (None, 3, 3),
    ]


def test_strumien_pokazuje_liczniki_szablonow_pracownikow_na_biezaco(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    seen: list[list[tuple[str, int]]] = []

    for event in run_events(centrum.client):
        view = event["view"]
        if view["state"] == "idle":
            centrum.start(dry_run=False)
            continue
        shown = [(figure["label"], figure["value"]) for figure in view["progress"]["figures"]]
        if view["state"] == "running" and (not seen or seen[-1] != shown):
            seen.append(shown)
        if view["state"] == "finished":
            break

    labels = ["Wiersze danych", "Zapisane szablony", "Puste szablony", "Pominięte szablony", "Problemy"]
    assert seen == [
        list(zip(labels, [0, 0, 0, 0, 0])),
        list(zip(labels, [2, 1, 0, 0, 0])),
        list(zip(labels, [3, 2, 0, 0, 0])),
        list(zip(labels, [3, 2, 1, 0, 0])),
    ]


def test_podglad_z_nieznanym_wykonawca_wymaga_sprawdzenia_inaczej_niz_sukces(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path, include_unmapped=True)

    result = run_to_end(centrum, dry_run=True)["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("WYMAGA_SPRAWDZENIA", "finished", "rerun")
    assert result["headline"] == "Podgląd wymaga sprawdzenia · nic nie zapisano"
    assert result["warnings"] == [
        {
            "what": "Nieznany identyfikator WYKONAWCA; sprawdź konfigurację pracowników.",
            "where": f"plik {SOURCE_NAME}, folder {PERIOD}",
            "action": (
                "Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy "
                "do konfiguracji wykonawców. Potem zapisz i zamknij Plik zbiorczy w Excelu i uruchom ponownie."
            ),
        }
    ]
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"]) == ("DRY-RUN", "WYMAGA_SPRAWDZENIA")


def test_nieznany_wykonawca_przy_uruchom_zatrzymuje_bez_publikacji_folderu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path, include_unmapped=True)

    result = run_to_end(centrum, dry_run=False)["result"]

    assert (result["result"], result["ending"], result["next_action"]) == ("BLAD_KRYTYCZNY", "stop", "rerun")
    assert result["headline"] == "Zatrzymano"
    [stop] = result["stops"]
    assert stop["what"] == (
        "W Pliku zbiorczym jest WYKONAWCA, którego nie ma w konfiguracji wykonawców. "
        "Nie utworzono żadnego pliku pracownika."
    )
    assert stop["where"] == f"plik {SOURCE_NAME}, folder {PERIOD}, kolumna H"
    assert stop["action"].startswith("Uruchom Podgląd bez zapisu: lista problemów pokaże wiersze.")
    assert sorted(path.name for path in centrum.period_directory.iterdir()) == [SOURCE_NAME]
    [record] = centrum.metric_records()
    assert (record["mode"], record["result"]) == ("RUN", "BLAD_KRYTYCZNY")


def test_nienadpisywanie_zatrzymuje_bez_zmiany_istniejacego_folderu_rozliczen_pracownikow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.worker_settlements.mkdir()
    corrected = centrum.worker_settlements / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx"
    corrected.write_bytes(b"reczne poprawki taty")

    view = run_to_end(centrum, dry_run=False)
    result = view["result"]

    assert (result["ending"], result["next_action"]) == ("stop", "rerun")
    assert result["stops"] == [
        {
            "what": (
                "Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany. "
                "Nie utworzono żadnego pliku pracownika."
            ),
            "where": f"folder {PERIOD}\\{WORKER_SETTLEMENTS}",
            "action": (
                "Sprawdź, czy wybrano właściwy okres. Rozliczenia pracowników tego okresu już są w Folderze okresu. "
                "Jeśli trzeba je utworzyć od nowa, najpierw przenieś ten folder poza Folder okresu i uruchom ponownie."
            ),
        }
    ]
    assert phase_states(view)["Sprawdzanie"] == "failed"
    assert [path.name for path in centrum.worker_settlements.iterdir()] == [corrected.name]
    assert corrected.read_bytes() == b"reczne poprawki taty"


def test_zatrzymanie_pokazuje_nazwe_pliku_bez_pelnej_sciezki(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (centrum.period_directory / SOURCE_NAME).unlink()

    result = run_to_end(centrum, dry_run=False)["result"]

    assert result["stops"] == [
        {
            "what": "Nie znaleziono Pliku zbiorczego tego okresu. Nie utworzono żadnego pliku pracownika.",
            "where": f"plik {SOURCE_NAME}, folder {PERIOD}",
            "action": (
                "Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod tą nazwą, i uruchom ponownie. "
                "Jeśli okresu jeszcze nie przygotowano, najpierw przygotuj plik zbiorczy."
            ),
        }
    ]
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_zamkniecie_centrum_w_trakcie_przebiegu_rozliczen_jest_odrzucone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)
    writing, release = threading.Event(), threading.Event()
    process_template = template_settlement.process_template

    def wait_while_writing(*args: Any) -> Any:
        writing.set()
        assert release.wait(10)
        return process_template(*args)

    monkeypatch.setattr(template_settlement, "process_template", wait_while_writing)
    centrum.start(dry_run=False)
    assert writing.wait(10)

    refused = centrum.client.post("/api/shutdown")
    release.set()
    finished_view(centrum.client)
    accepted = centrum.client.post("/api/shutdown")

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                f"Trwa Uruchomienie procesu: Przebieg rozliczeń, okres {PERIOD}. "
                "Poczekaj na jego wynik w Uruchomieniach, potem zamknij Centrum rozliczeń."
            )
        },
    )
    assert accepted.status_code == 202


def test_centrum_dopisuje_rekord_do_pliku_metryk_cli_i_rozpoznaje_swoje_uruchomienie(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_to_end(centrum, dry_run=True)
    config = tmp_path / "config"

    cli_exit_code = cli.main(
        [
            "--source", str(centrum.period_directory / SOURCE_NAME),
            "--config", str(config / "worker_mapping.yaml"),
            "--worker-template", str(config / "Wzorzec rozliczenia pracownika.xlsx"),
            "--metrics", str(centrum.metrics_path),
            "--dry-run",
        ],
        output=StringIO(),
    )
    records = MetricsStore(centrum.metrics_path, cli.PROCESS.counter_names).read()
    history = centrum.client.get("/api/metrics").json()["runs"]

    assert MetricsFiles.of_cli().settlement == cli.default_metrics_path()
    assert cli_exit_code == 0
    assert [(run["process"], run["origin"]) for run in history] == [("settlement", "cmd"), ("settlement", "centrum")]
    assert [(record["mode"], record["result"]) for record in records] == [("DRY-RUN", "OK"), ("DRY-RUN", "OK")]
    assert records[0].keys() == records[1].keys()
    assert records[0]["counters"] == records[1]["counters"]


def settlement_setup(client: TestClient) -> dict[str, Any]:
    processes = client.get("/api/runs/setup").json()["processes"]
    [setup] = [setup for setup in processes if setup["process"] == "settlement"]
    assert isinstance(setup, dict)
    return setup


def test_wybor_okresu_to_okresy_z_przygotowanym_plikiem_zbiorczym(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    older = centrum.periods_directory / "01_07_09_2026"
    older.mkdir()
    (older / "Rozliczenie 01_07_09_2026 - zbiorcze.xlsx").touch()
    (centrum.periods_directory / "25_31_08_2026" / "Rozliczenie pracowników 25_31_08_2026").mkdir(parents=True)

    setup = settlement_setup(centrum.client)

    assert (setup["title"], setup["creates"], setup["blocker"]) == ("Przebieg rozliczeń", "Rozliczenia pracowników", None)
    assert setup["reminder"] == "Zapisz i zamknij Plik zbiorczy w Excelu"
    assert (setup["confirms_readiness"], setup["preview_hint"]) == (
        True,
        "Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
    )
    assert setup["preselected_period"] == PERIOD
    assert [(choice["token"], choice["last_complete"], choice["collective_file"]) for choice in setup["periods"]] == [
        (PERIOD, True, SOURCE_NAME),
        ("01_07_09_2026", False, "Rozliczenie 01_07_09_2026 - zbiorcze.xlsx"),
    ]


def test_bez_okresu_z_plikiem_zbiorczym_przebieg_mowi_czego_brakuje(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (centrum.period_directory / SOURCE_NAME).unlink()
    client = bare_centrum(tmp_path / "bez-ustawien", today=TODAY).client

    without_periods = settlement_setup(centrum.client)
    without_settings = settlement_setup(client)
    refused = client.post("/api/runs", json={"process": "settlement", "period": PERIOD, "dry_run": True})

    assert without_periods["blocker"] == (
        "Żaden okres nie ma Statusu „Plik zbiorczy przygotowany”. Najpierw przygotuj plik zbiorczy."
    )
    assert without_settings["blocker"] == "Najpierw wskaż folder okresów."
    assert (refused.status_code, refused.json()) == (409, {"message": "Najpierw wskaż folder okresów."})
