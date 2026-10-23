"""Skoroszyt, którego nie da się użyć: Komunikat każdej roli pliku przy każdym powodzie (``Problem``).

Powód, którego plik w danej roli mieć nie może, nie ma wiersza. Pełną treść i pozostałe skutki Zatrzymań
przypinają testy procesów; tu jest tylko to, który Komunikat odpowiada któremu powodowi.
"""

from __future__ import annotations

from collections.abc import Callable
import errno
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
import pytest

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.domain import ProgressEvent, WorkerStarted
from rozliczenia.engine import run_settlements
from rozliczenia.message import Message, StopError
from rozliczenia.workbook_files import WORKER_HEADER

from tests.fixtures.centrum import CENTRUM, FakeGitHub, FakePlatform
from tests.fixtures.preparation import (
    make_preparation_fixture,
    run_preparation,
    write_collective_template,
    write_internal_template,
)
from tests.fixtures.settlement import make_fixture, write_mapping, write_template
from tests.fixtures.workbooks import active_worksheet

Damage = Callable[[Path, pytest.MonkeyPatch], None]


def missing(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path.unlink()


def open_in_excel(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path.with_name(f"~${path.name}").write_bytes(b"")


def inaccessible(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    read_bytes = Path.read_bytes

    def blocked(read: Path) -> bytes:
        if read == path:
            raise PermissionError(errno.EACCES, "Plik jest używany przez inny proces")
        return read_bytes(read)

    monkeypatch.setattr(Path, "read_bytes", blocked)


def unreadable(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path.write_bytes(b"to nie jest skoroszyt")


def edited(change: Callable[[Worksheet], None]) -> Damage:
    def damage(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workbook = load_workbook(path)
        try:
            change(active_worksheet(workbook))
            workbook.save(path)
        finally:
            workbook.close()

    return damage


def cell(address: str, value: str) -> Damage:
    def change(sheet: Worksheet) -> None:
        sheet[address] = value

    return edited(change)


def merged(cells: str) -> Damage:
    return edited(lambda sheet: sheet.merge_cells(cells))


def _swap_g17_and_h17(sheet: Worksheet) -> None:
    sheet["G17"].value, sheet["H17"].value = sheet["H17"].value, sheet["G17"].value


worker_outside_h = edited(_swap_g17_and_h17)

WORKER_HEADER_CELL = str(WORKER_HEADER)
INTERNAL_ORDER_NUMBER_HEADER = "G1"
INTERNAL_FOURTH_ORDER = "C5:D5"
COLLECTIVE_SECOND_AND_THIRD_ORDER = "B19:C20"
FIRST_DATA_ROW_CELL = "A18"

PREPARATION = [
    pytest.param("register_path", missing, "BRAK_REJESTRU", id="rejestr-brak"),
    pytest.param("register_path", open_in_excel, "REJESTR_OTWARTY", id="rejestr-otwarty"),
    pytest.param("register_path", inaccessible, "NIEDOSTEPNY_REJESTR", id="rejestr-niedostepny"),
    pytest.param("register_path", unreadable, "USZKODZONY_REJESTR", id="rejestr-nieczytelny"),
    pytest.param("internal_template_path", missing, "BRAK_WZORCA", id="wewnetrzny-brak"),
    pytest.param("internal_template_path", open_in_excel, "WZORZEC_OTWARTY", id="wewnetrzny-otwarty"),
    pytest.param("internal_template_path", inaccessible, "NIEDOSTEPNY_WZORZEC", id="wewnetrzny-niedostepny"),
    pytest.param("internal_template_path", unreadable, "USZKODZONY_WZORZEC", id="wewnetrzny-nieczytelny"),
    pytest.param("internal_template_path", cell(INTERNAL_ORDER_NUMBER_HEADER, "inna kolumna"), "ZLY_WZORZEC", id="wewnetrzny-bez-naglowka"),
    pytest.param("internal_template_path", merged(INTERNAL_FOURTH_ORDER), "SCALONE_KOMORKI_WZORCA", id="wewnetrzny-scalenie"),
    pytest.param("collective_template_path", missing, "BRAK_WZORCA", id="zbiorczy-brak"),
    pytest.param("collective_template_path", open_in_excel, "WZORZEC_OTWARTY", id="zbiorczy-otwarty"),
    pytest.param("collective_template_path", inaccessible, "NIEDOSTEPNY_WZORZEC", id="zbiorczy-niedostepny"),
    pytest.param("collective_template_path", unreadable, "USZKODZONY_WZORZEC", id="zbiorczy-nieczytelny"),
    pytest.param("collective_template_path", cell(WORKER_HEADER_CELL, "inna kolumna"), "ZLY_WZORZEC", id="zbiorczy-bez-naglowka"),
    pytest.param("collective_template_path", worker_outside_h, "WYKONAWCA_POZA_H", id="zbiorczy-wykonawca-poza-h"),
    pytest.param("collective_template_path", merged(COLLECTIVE_SECOND_AND_THIRD_ORDER), "SCALONE_KOMORKI_WZORCA", id="zbiorczy-scalenie"),
]


@pytest.mark.parametrize(("role", "damage", "code"), PREPARATION)
def test_przygotowanie_zatrzymuje_sie_komunikatem_roli_pliku_i_powodu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, damage: Damage, code: str
) -> None:
    fixture = make_preparation_fixture(tmp_path)
    damage(getattr(fixture, role), monkeypatch)

    with pytest.raises(StopError) as raised:
        run_preparation(fixture)

    assert raised.value.message.code == code


SOURCE_UNFIT = "Plik zbiorczy nie nadaje się do Przebiegu rozliczeń."
WORKER_TEMPLATE_UNUSABLE = "Nie można użyć Wzorca rozliczenia pracownika."
WORKER_TEMPLATE_UNREADABLE = f"{WORKER_TEMPLATE_UNUSABLE} Nie można odczytać Wzorca rozliczenia pracownika."
TEMPLATE_NOT_COPIED = "Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika."
WORKER_FILE_FAILED = "Nie udało się przygotować skoroszytu pracownika Adrian Testowy."

SETTLEMENT = [
    pytest.param("source", missing, "BRAK_PLIKU_ZBIORCZEGO", None, id="zbiorczy-brak"),
    pytest.param("source", open_in_excel, "PLIK_ZBIORCZY_OTWARTY", None, id="zbiorczy-otwarty"),
    pytest.param("source", inaccessible, "NIEDOSTEPNY_PLIK_ZBIORCZY", None, id="zbiorczy-niedostepny"),
    pytest.param(
        "source", unreadable, "ZLY_PLIK_ZBIORCZY", f"{SOURCE_UNFIT} Nie można odczytać Pliku zbiorczego", id="zbiorczy-nieczytelny"
    ),
    pytest.param(
        "source",
        cell(WORKER_HEADER_CELL, "inna kolumna"),
        "ZLY_PLIK_ZBIORCZY",
        f"{SOURCE_UNFIT} W wierszu 17 nie znaleziono nagłówka WYKONAWCA w kolumnie H.",
        id="zbiorczy-bez-wykonawca-w-h17",
    ),
    pytest.param(
        "worker_template",
        missing,
        "ZLY_WZORZEC_PRACOWNIKA",
        f"{WORKER_TEMPLATE_UNUSABLE} Nie znaleziono Wzorca rozliczenia pracownika: Wzorzec rozliczenia pracownika.xlsx.",
        id="wzorzec-pracownika-brak",
    ),
    pytest.param(
        "worker_template",
        open_in_excel,
        "ZLY_WZORZEC_PRACOWNIKA",
        f"{WORKER_TEMPLATE_UNUSABLE} Wzorzec rozliczenia pracownika jest otwarty lub zablokowany.",
        id="wzorzec-pracownika-otwarty",
    ),
    pytest.param(
        "worker_template", inaccessible, "ZLY_WZORZEC_PRACOWNIKA", WORKER_TEMPLATE_UNREADABLE, id="wzorzec-pracownika-niedostepny"
    ),
    pytest.param(
        "worker_template", unreadable, "ZLY_WZORZEC_PRACOWNIKA", WORKER_TEMPLATE_UNREADABLE, id="wzorzec-pracownika-nieczytelny"
    ),
    pytest.param(
        "worker_template",
        cell(WORKER_HEADER_CELL, "inna kolumna"),
        "ZLY_WZORZEC_PRACOWNIKA",
        f"{WORKER_TEMPLATE_UNUSABLE} Wzorzec rozliczenia pracownika nie ma nagłówka WYKONAWCA w H:17.",
        id="wzorzec-pracownika-bez-wykonawca-w-h17",
    ),
    pytest.param(
        "worker_template",
        cell(FIRST_DATA_ROW_CELL, "dane"),
        "ZLY_WZORZEC_PRACOWNIKA",
        f"{WORKER_TEMPLATE_UNUSABLE} Wzorzec rozliczenia pracownika zawiera dane i nie może być użyty jako wzór.",
        id="wzorzec-pracownika-z-danymi",
    ),
]


@pytest.mark.parametrize(("role", "damage", "code", "what"), SETTLEMENT)
def test_przebieg_zatrzymuje_sie_w_sprawdzaniu_komunikatem_roli_pliku_i_powodu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, damage: Damage, code: str, what: str | None
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"
    damage({"source": source_path, "worker_template": worker_template_path}[role], monkeypatch)

    with pytest.raises(StopError) as raised:
        run_settlements(source_path, config_path, worker_template_path=worker_template_path)

    assert_message(raised.value.message, code, what)


SAVING = [
    pytest.param(missing, "BLAD_KOPII_WZORCA", TEMPLATE_NOT_COPIED, id="brak"),
    pytest.param(open_in_excel, "BLAD_KOPII_WZORCA", TEMPLATE_NOT_COPIED, id="otwarty"),
    pytest.param(inaccessible, "BLAD_KOPII_WZORCA", TEMPLATE_NOT_COPIED, id="niedostepny"),
    pytest.param(unreadable, "BLAD_KOPII_WZORCA", TEMPLATE_NOT_COPIED, id="nieczytelny"),
    pytest.param(cell(WORKER_HEADER_CELL, "inna kolumna"), "BLAD_SZABLONU_PRACOWNIKA", WORKER_FILE_FAILED, id="bez-wykonawca-w-h17"),
    pytest.param(cell(FIRST_DATA_ROW_CELL, "dane"), "BLAD_SZABLONU_PRACOWNIKA", WORKER_FILE_FAILED, id="z-danymi"),
]


@pytest.mark.parametrize(("damage", "code", "what"), SAVING)
def test_przebieg_zatrzymuje_sie_w_zapisywaniu_komunikatem_powodu_dla_wzorca_rozliczenia_pracownika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: Damage, code: str, what: str
) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"

    def damage_before_first_file(event: ProgressEvent) -> None:
        if isinstance(event, WorkerStarted) and event.template_index == 1:
            damage(worker_template_path, monkeypatch)

    with pytest.raises(StopError) as raised:
        run_settlements(
            source_path, config_path, worker_template_path=worker_template_path, observer=damage_before_first_file
        )

    assert_message(raised.value.message, code, what)


def assert_message(message: Message, code: str, what: str | None) -> None:
    assert message.code == code
    if what is not None:
        assert message.what.startswith(what)


INTERNAL = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE = "Wzorzec pliku zbiorczego.xlsx"
WORKER = "Wzorzec rozliczenia pracownika.xlsx"

CONFIGURATION = [
    pytest.param(INTERNAL, missing, "missing", "Nie znaleziono wzorca", id="wewnetrzny-brak"),
    pytest.param(INTERNAL, open_in_excel, "open_in_excel", "Wzorzec jest otwarty w Excelu", id="wewnetrzny-otwarty"),
    pytest.param(INTERNAL, inaccessible, "unreadable", "Nie można teraz odczytać wzorca", id="wewnetrzny-niedostepny"),
    pytest.param(INTERNAL, unreadable, "unreadable", "Nie można odczytać wzorca. Plik jest uszkodzony", id="wewnetrzny-nieczytelny"),
    pytest.param(
        INTERNAL, cell(INTERNAL_ORDER_NUMBER_HEADER, "inna kolumna"), "unreadable", "We wzorcu brakuje nagłówka NUMER ZL.", id="wewnetrzny-bez-naglowka"
    ),
    pytest.param(COLLECTIVE, missing, "missing", "Nie znaleziono wzorca", id="zbiorczy-brak"),
    pytest.param(COLLECTIVE, open_in_excel, "open_in_excel", "Wzorzec jest otwarty w Excelu", id="zbiorczy-otwarty"),
    pytest.param(COLLECTIVE, inaccessible, "unreadable", "Nie można teraz odczytać wzorca", id="zbiorczy-niedostepny"),
    pytest.param(COLLECTIVE, unreadable, "unreadable", "Nie można odczytać wzorca. Plik jest uszkodzony", id="zbiorczy-nieczytelny"),
    pytest.param(
        COLLECTIVE, worker_outside_h, "unreadable", "Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie G", id="zbiorczy-wykonawca-poza-h"
    ),
    pytest.param(
        WORKER,
        missing,
        "missing",
        f"{WORKER_TEMPLATE_UNUSABLE} Nie znaleziono Wzorca rozliczenia pracownika",
        id="wzorzec-pracownika-brak",
    ),
    pytest.param(
        WORKER,
        open_in_excel,
        "open_in_excel",
        f"{WORKER_TEMPLATE_UNUSABLE} Wzorzec rozliczenia pracownika jest otwarty lub zablokowany.",
        id="wzorzec-pracownika-otwarty",
    ),
    pytest.param(WORKER, inaccessible, "unreadable", WORKER_TEMPLATE_UNREADABLE, id="wzorzec-pracownika-niedostepny"),
    pytest.param(WORKER, unreadable, "unreadable", WORKER_TEMPLATE_UNREADABLE, id="wzorzec-pracownika-nieczytelny"),
    pytest.param(
        WORKER,
        cell(WORKER_HEADER_CELL, "inna kolumna"),
        "unreadable",
        f"{WORKER_TEMPLATE_UNUSABLE} Wzorzec rozliczenia pracownika nie ma nagłówka WYKONAWCA",
        id="wzorzec-pracownika-bez-wykonawca-w-h17",
    ),
    pytest.param(
        WORKER,
        cell(FIRST_DATA_ROW_CELL, "dane"),
        "unreadable",
        f"{WORKER_TEMPLATE_UNUSABLE} Wzorzec rozliczenia pracownika zawiera dane",
        id="wzorzec-pracownika-z-danymi",
    ),
]


@pytest.mark.parametrize(("file_name", "damage", "kind", "what"), CONFIGURATION)
def test_konfiguracja_pokazuje_rodzaj_problemu_i_komunikat_wzorca_przy_kazdym_powodzie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_name: str, damage: Damage, kind: str, what: str
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    files = ConfigurationFiles(
        worker_config=write_mapping(config / "worker_mapping.yaml"),
        internal_template=write_internal_template(config / INTERNAL),
        collective_template=write_collective_template(config / COLLECTIVE),
        worker_template=config / WORKER,
    )
    write_template(files.worker_template)
    damage(config / file_name, monkeypatch)
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    app = create_app(
        settings_path=config / "centrum-ustawienia.yaml",
        platform=FakePlatform(),
        log=log,
        shutdown=Shutdown(log),
        configuration_files=files,
        tool_freshness=FakeGitHub().freshness(),
    )

    response = TestClient(app, base_url=CENTRUM, headers={"Origin": CENTRUM}).get("/api/configuration")

    templates = {template["file_name"]: template for template in response.json()["templates"]}
    assert (templates[file_name]["state"], templates[file_name]["problem"]) == ("problem", kind)
    assert templates[file_name]["message"]["what"].startswith(what)
    assert [template["state"] for name, template in templates.items() if name != file_name] == ["ready", "ready"]
