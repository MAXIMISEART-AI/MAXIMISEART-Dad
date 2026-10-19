"""Konfiguracja w Centrum rozliczeń przez HTTP API: Wzorce, Wykonawcy i wersja narzędzia, tylko do odczytu."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.configuration import ConfigurationFiles
from tests.collective_preparation_fixtures import write_collective_template, write_internal_template
from tests.test_centrum_rozliczen import CENTRUM, FakePlatform, project_version
from tests.test_settlement_engine import write_mapping, write_template

INTERNAL = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE = "Wzorzec pliku zbiorczego.xlsx"
WORKER = "Wzorzec rozliczenia pracownika.xlsx"
REPORT_TO_MAINTAINER = "Przekaż ten komunikat osobie utrzymującej narzędzie."


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
    app = create_app(
        settings_path=config / "centrum-ustawienia.yaml",
        platform=FakePlatform(),
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
    ("file_name", "what"),
    [
        (INTERNAL, "Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku."),
        (COLLECTIVE, "Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku."),
        (WORKER, f"Nie znaleziono Wzorca rozliczenia pracownika: {WORKER}."),
    ],
)
def test_brak_wzorca_jest_komunikatem_w_trzech_czesciach(tmp_path: Path, file_name: str, what: str) -> None:
    app = configured(tmp_path)
    (tmp_path / "config" / file_name).unlink()

    templates = templates_by_file(read_configuration(app))

    assert templates[file_name]["state"] == "problem"
    assert templates[file_name]["problem"] == "missing"
    assert templates[file_name]["message"] == {
        "what": what,
        "where": f"plik {file_name}, folder config",
        "action": REPORT_TO_MAINTAINER,
    }
    assert [template["state"] for name, template in templates.items() if name != file_name] == ["ready", "ready"]


@pytest.mark.parametrize(
    ("file_name", "what"),
    [
        (INTERNAL, "Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku."),
        (COLLECTIVE, "Wzorzec jest otwarty w Excelu. Nie utworzono żadnego pliku."),
        (WORKER, "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany."),
    ],
)
def test_wzorzec_otwarty_w_excelu_mowi_jak_go_zamknac(tmp_path: Path, file_name: str, what: str) -> None:
    app = configured(tmp_path)
    lock_file = tmp_path / "config" / f"~${file_name}"
    lock_file.write_bytes(b"blokada Excela")

    template = templates_by_file(read_configuration(app))[file_name]

    assert template["problem"] == "open_in_excel"
    assert template["message"] == {
        "what": what,
        "where": f"plik {file_name}, folder config",
        "action": (
            "Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. "
            "Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu "
            f"pozostawiony plik ~${file_name} i uruchom ponownie."
        ),
    }
    assert lock_file.read_bytes() == b"blokada Excela"


UNREADABLE_TEMPLATE = (
    "Nie można odczytać wzorca. Plik jest uszkodzony albo nie jest skoroszytem .xlsx. Nie utworzono żadnego pliku."
)


@pytest.mark.parametrize(
    ("file_name", "what"),
    [
        (INTERNAL, UNREADABLE_TEMPLATE),
        (COLLECTIVE, UNREADABLE_TEMPLATE),
        (WORKER, "Nie można odczytać Wzorca rozliczenia pracownika."),
    ],
)
def test_nieczytelny_wzorzec_trzeba_przekazac_osobie_utrzymujacej_narzedzie(
    tmp_path: Path, file_name: str, what: str
) -> None:
    app = configured(tmp_path)
    (tmp_path / "config" / file_name).write_bytes(b"to nie jest skoroszyt")

    template = templates_by_file(read_configuration(app))[file_name]

    assert template["problem"] == "unreadable"
    assert template["message"] == {
        "what": what,
        "where": f"plik {file_name}, folder config",
        "action": REPORT_TO_MAINTAINER,
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
        "names": ["Adrian Maciejewski", "Darek Nowak", "Kamil Frontczak"],
    }


@pytest.mark.parametrize(
    "content",
    [
        None,
        "workers: [niedomknięta lista\n",
        "schema_version: 1\nworkers:\n  a: Ten Sam\n  b: ten sam\n",
    ],
    ids=["brak-pliku", "zly-yaml", "dwa-identyfikatory-na-jeden-plik"],
)
def test_nieczytelna_konfiguracja_wykonawcow_jest_komunikatem_w_trzech_czesciach(
    tmp_path: Path, content: str | None
) -> None:
    app = configured(tmp_path)
    if content is None:
        app.files.worker_config.unlink()
    else:
        app.files.worker_config.write_text(content, encoding="utf-8")

    configuration = read_configuration(app)

    assert configuration["workers"] == {
        "state": "unreadable",
        "message": {
            "what": "Nie można odczytać konfiguracji wykonawców.",
            "where": "plik worker_mapping.yaml",
            "action": "Przekaż to osobie utrzymującej narzędzie.",
        },
    }
    assert [template["state"] for template in templates_by_file(configuration).values()] == ["ready"] * 3


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
