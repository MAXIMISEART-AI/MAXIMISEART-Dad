"""Konfiguracja w Centrum rozliczeń przez HTTP API: Wzorce, Wykonawcy i wersja narzędzia, tylko do odczytu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.shutdown import Shutdown
from tests.fixtures.preparation import write_collective_template, write_internal_template
from tests.fixtures.centrum import CENTRUM, FakePlatform, project_version
from tests.fixtures.workbooks import cut_sheet_after_data_rows
from tests.fixtures.settlement import write_mapping, write_template

INTERNAL = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE = "Wzorzec pliku zbiorczego.xlsx"
WORKER = "Wzorzec rozliczenia pracownika.xlsx"
REPORT_TO_MAINTAINER = "Przekaż ten komunikat osobie utrzymującej narzędzie."
# Wzorzec rozliczenia pracownika ma ten sam komunikat, którym zatrzymałby się Przebieg rozliczeń.
WORKER_TEMPLATE_STOP = "Nie można użyć Wzorca rozliczenia pracownika."
WORKER_TEMPLATE_ACTION = (
    "Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania zmian i uruchom ponownie. "
    "W innym wypadku przekaż ten komunikat osobie utrzymującej narzędzie."
)


@dataclass
class Configured:
    client: TestClient
    files: ConfigurationFiles


def configured(tmp_path: Path) -> Configured:
    """Centrum z syntetycznym katalogiem konfiguracji: wszystkie trzy Wzorce i konfiguracja wykonawców."""

    config = tmp_path / "config"
    config.mkdir()
    files = ConfigurationFiles(
        worker_config=write_mapping(config / "worker_mapping.yaml"),
        internal_template=write_internal_template(config / INTERNAL),
        collective_template=write_collective_template(config / COLLECTIVE),
        worker_template=config / WORKER,
    )
    write_template(files.worker_template)
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    app = create_app(
        settings_path=config / "centrum-ustawienia.yaml",
        platform=FakePlatform(),
        log=log,
        shutdown=Shutdown(log),
        configuration_files=files,
    )
    return Configured(TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM}), files)


def read_configuration(app: Configured) -> dict[str, Any]:
    response = app.client.get("/api/configuration")
    assert response.status_code == 200
    configuration = response.json()
    assert isinstance(configuration, dict)
    return configuration


def templates_by_file(configuration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = configuration["templates"]
    assert isinstance(templates, list)
    return {template["file_name"]: template for template in templates}


def test_wszystkie_trzy_wzorce_sa_na_miejscu_i_czytelne(tmp_path: Path) -> None:
    configuration = read_configuration(configured(tmp_path))

    assert configuration["templates"] == [
        {"state": "ready", "label": "Wzorzec rozliczenia wewnętrznego", "file_name": INTERNAL},
        {"state": "ready", "label": "Wzorzec pliku zbiorczego", "file_name": COLLECTIVE},
        {"state": "ready", "label": "Wzorzec rozliczenia pracownika", "file_name": WORKER},
    ]


@pytest.mark.parametrize(
    ("file_name", "what", "action"),
    [
        (
            INTERNAL,
            "Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku.",
            REPORT_TO_MAINTAINER,
        ),
        (
            COLLECTIVE,
            "Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku.",
            REPORT_TO_MAINTAINER,
        ),
        (
            WORKER,
            f"{WORKER_TEMPLATE_STOP} Nie znaleziono Wzorca rozliczenia pracownika: {WORKER}.",
            WORKER_TEMPLATE_ACTION,
        ),
    ],
)
def test_brak_wzorca_jest_komunikatem_w_trzech_czesciach(
    tmp_path: Path, file_name: str, what: str, action: str
) -> None:
    app = configured(tmp_path)
    (tmp_path / "config" / file_name).unlink()

    templates = templates_by_file(read_configuration(app))

    assert templates[file_name]["state"] == "problem"
    assert templates[file_name]["problem"] == "missing"
    assert templates[file_name]["message"] == {
        "what": what,
        "where": f"plik {file_name}, folder config",
        "action": action,
    }
    assert [template["state"] for name, template in templates.items() if name != file_name] == ["ready", "ready"]


def closing_action(file_name: str) -> str:
    return (
        "Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. "
        "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
        f"pozostawiony plik ~${file_name} i uruchom ponownie."
    )


@pytest.mark.parametrize(
    ("file_name", "what", "action"),
    [
        (INTERNAL, "Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku.", closing_action(INTERNAL)),
        (COLLECTIVE, "Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku.", closing_action(COLLECTIVE)),
        (
            WORKER,
            f"{WORKER_TEMPLATE_STOP} Wzorzec rozliczenia pracownika jest otwarty lub zablokowany.",
            WORKER_TEMPLATE_ACTION,
        ),
    ],
)
def test_wzorzec_otwarty_w_excelu_mowi_jak_go_zamknac(tmp_path: Path, file_name: str, what: str, action: str) -> None:
    app = configured(tmp_path)
    lock_file = tmp_path / "config" / f"~${file_name}"
    lock_file.write_bytes(b"blokada Excela")

    template = templates_by_file(read_configuration(app))[file_name]

    assert template["problem"] == "open_in_excel"
    assert template["message"] == {
        "what": what,
        "where": f"plik {file_name}, folder config",
        "action": action,
    }
    assert lock_file.read_bytes() == b"blokada Excela"


UNREADABLE_TEMPLATE = (
    "Nie można odczytać wzorca. Plik jest uszkodzony albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku."
)


@pytest.mark.parametrize(
    ("file_name", "what", "action"),
    [
        (INTERNAL, UNREADABLE_TEMPLATE, REPORT_TO_MAINTAINER),
        (COLLECTIVE, UNREADABLE_TEMPLATE, REPORT_TO_MAINTAINER),
        (WORKER, f"{WORKER_TEMPLATE_STOP} Nie można odczytać Wzorca rozliczenia pracownika.", WORKER_TEMPLATE_ACTION),
    ],
)
@pytest.mark.parametrize(
    "damage",
    [
        lambda path: path.write_bytes(b"to nie jest skoroszyt"),
        cut_sheet_after_data_rows,
    ],
    ids=["nie-skoroszyt", "uciety-xml-arkusza"],
)
def test_nieczytelny_wzorzec_trzeba_przekazac_osobie_utrzymujacej_narzedzie(
    tmp_path: Path, file_name: str, what: str, action: str, damage: Callable[[Path], object]
) -> None:
    app = configured(tmp_path)
    damage(tmp_path / "config" / file_name)

    template = templates_by_file(read_configuration(app))[file_name]

    assert template["problem"] == "unreadable"
    assert template["message"] == {
        "what": what,
        "where": f"plik {file_name}, folder config",
        "action": action,
    }


def test_wzorzec_pliku_zbiorczego_z_wykonawca_poza_h_nie_przechodzi_sprawdzania(tmp_path: Path) -> None:
    app = configured(tmp_path)
    template_path = tmp_path / "config" / COLLECTIVE
    workbook = load_workbook(template_path, keep_links=True)
    sheet = workbook["Sheet1"]
    sheet["G17"].value, sheet["H17"].value = sheet["H17"].value, sheet["G17"].value
    workbook.save(template_path)
    workbook.close()

    template = templates_by_file(read_configuration(app))[COLLECTIVE]

    assert template["problem"] == "unreadable"
    assert template["message"]["what"] == (
        "Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie G zamiast w H (wiersz 17). "
        "Nie utworzono żadnego pliku."
    )


def test_naprawiony_albo_zamkniety_wzorzec_jest_gotowy_przy_nastepnym_odczycie(tmp_path: Path) -> None:
    app = configured(tmp_path)
    config = tmp_path / "config"
    (config / WORKER).write_bytes(b"to nie jest skoroszyt")
    lock_file = config / f"~${INTERNAL}"
    lock_file.touch()
    broken = templates_by_file(read_configuration(app))
    write_template(config / WORKER)
    lock_file.unlink()

    repaired = templates_by_file(read_configuration(app))

    assert [broken[WORKER]["state"], broken[INTERNAL]["state"]] == ["problem", "problem"]
    assert [repaired[WORKER]["state"], repaired[INTERNAL]["state"]] == ["ready", "ready"]


def config_directory_snapshot(config: Path) -> dict[str, tuple[bytes, int]]:
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(config.iterdir())}


def test_centrum_nie_zmienia_zadnego_pliku_konfiguracji_ani_wzorca(tmp_path: Path) -> None:
    app = configured(tmp_path)
    config = tmp_path / "config"
    (config / f"~${INTERNAL}").write_bytes(b"blokada Excela")
    before = config_directory_snapshot(config)

    read_configuration(app)
    change = app.client.put("/api/configuration", json={})

    assert change.status_code == 405
    assert config_directory_snapshot(config) == before


def test_wykonawcy_sa_wypisani_w_kolejnosci_z_konfiguracji_wykonawcow(tmp_path: Path) -> None:
    configuration = read_configuration(configured(tmp_path))

    assert configuration["workers"] == {
        "state": "ready",
        "names": ["Adrian Testowy", "Darek Fikcyjny", "Kamil Syntetyczny"],
    }


def test_zla_konfiguracja_wykonawcow_jest_komunikatem_w_trzech_czesciach(tmp_path: Path) -> None:
    app = configured(tmp_path)
    app.files.worker_config.write_text("schema_version: 1\nworkers:\n  a: Ten Sam\n  b: ten sam\n", encoding="utf-8")

    configuration = read_configuration(app)

    assert configuration["workers"] == {
        "state": "unreadable",
        "message": {
            "what": (
                "Konfiguracja wykonawców jest niepoprawna. "
                "Dwóch identyfikatorów wskazuje ten sam plik pracownika: Ten Sam / ten sam"
            ),
            "where": "plik worker_mapping.yaml, folder config",
            "action": REPORT_TO_MAINTAINER,
        },
    }
    assert [template["state"] for template in templates_by_file(configuration).values()] == ["ready"] * 3


def test_konfiguracja_wykonawcow_zapisana_w_ansi_jest_komunikatem_a_nie_bledem_strony(tmp_path: Path) -> None:
    app = configured(tmp_path)
    app.files.worker_config.write_text("schema_version: 1\nworkers:\n  łukasz: Łukasz Testowy\n", encoding="cp1250")

    configuration = read_configuration(app)

    assert configuration["workers"] == {
        "state": "unreadable",
        "message": {
            "what": (
                "Konfiguracja wykonawców jest niepoprawna. "
                "Plik nie jest zapisany w kodowaniu UTF-8; zapisz go ponownie jako UTF-8."
            ),
            "where": "plik worker_mapping.yaml, folder config",
            "action": REPORT_TO_MAINTAINER,
        },
    }


def test_nowy_wykonawca_dopisany_do_konfiguracji_jest_widoczny_bez_restartu(tmp_path: Path) -> None:
    app = configured(tmp_path)
    read_configuration(app)
    with app.files.worker_config.open("a", encoding="utf-8") as config:
        config.write("  nowy.wykonawca: Nowy Wykonawca\n")

    workers = read_configuration(app)["workers"]

    assert workers["names"][-1] == "Nowy Wykonawca"


def test_wersja_narzedzia_jest_wersja_projektu(tmp_path: Path) -> None:
    configuration = read_configuration(configured(tmp_path))

    assert configuration["version"] == project_version()
