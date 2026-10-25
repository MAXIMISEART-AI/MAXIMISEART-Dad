"""Wiersze bez ilości w ustawieniu Przebiegu rozliczeń (#415, #421, ADR 0016), przez HTTP API jak przeglądarka.

Każdy test przygotowuje Plik zbiorczy z syntetycznego Rejestru zleceń w Centrum, zmienia go jak tata w Excelu
(openpyxl) i pyta ustawienie Uruchomień o okres, który okno „Uruchomić z zapisem?” pokaże.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, run_to_end
from tests.fixtures.preparation import PERIOD, register_order

TUE = datetime(2026, 9, 8, 10, 0)
MON = datetime(2026, 9, 14, 9, 0)

# Zlecenia skuteczne okresu po kolei, więc w Pliku zbiorczym od wiersza 18: wiersz → URZĄDZENIA.
DEVICES = {
    18: "nokia zte",  # Reguły ilości znają każdy składnik
    19: "przeniesienie",  # wiersz bez reguły
    20: "prewencja",  # wiersz z opisu
    21: "",  # wiersz z opisu
    22: "router x9",  # wiersz bez reguły
}


def _prepared(tmp_path: Path) -> PreparingCentrum:
    # Ostatnie zlecenie w poniedziałek: okres jest pełny, więc Przygotowanie nie czeka na Decyzję taty.
    starts = [TUE.replace(hour=8 + index) for index in range(len(DEVICES) - 1)] + [MON]
    rows = [
        {**register_order(index, started), "URZĄDZENIA": text}
        for index, (text, started) in enumerate(zip(DEVICES.values(), starts, strict=True), start=1)
    ]
    centrum = preparing_centrum(tmp_path, list(rows))
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    return centrum


def _choice(centrum: PreparingCentrum) -> dict[str, Any]:
    """Okres ``PERIOD`` w ustawieniu Przebiegu rozliczeń."""

    response = centrum.client.get("/api/runs/setup")
    assert response.status_code == 200, response.text
    settlement = next(setup for setup in response.json()["processes"] if setup["process"] == "settlement")
    choice: dict[str, Any] = next(choice for choice in settlement["periods"] if choice["token"] == PERIOD)
    return choice


def _write(path: Path, cells: dict[str, int | str | None], *, header: str | None = None) -> None:
    """Zmiana Pliku zbiorczego jak tata w Excelu; ``header`` to nagłówek wiersza 17, który tata usuwa."""

    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for cell, value in cells.items():
        sheet[cell] = value
    for found in sheet[17]:
        if header is not None and found.value == header:
            found.value = None
    workbook.save(path)


def test_ustawienie_przebiegu_wymienia_wiersze_bez_ilosci_rosnaco(tmp_path: Path) -> None:
    choice = _choice(_prepared(tmp_path))

    assert choice["without_quantity"] == {"state": "read", "rows": [19, 20, 21, 22]}


def test_po_uzupelnieniu_w_pliku_ustawienie_przestaje_wymieniac_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path

    _write(path, {"O19": 1, "AP21": 2})
    assert _choice(centrum)["without_quantity"] == {"state": "read", "rows": [20, 22]}

    _write(path, {"N20": 45, "AE22": 3})
    assert _choice(centrum)["without_quantity"] == {"state": "read", "rows": []}


def test_v_t_i_n_nie_zdejmuja_wiersza_bez_reguly_a_zero_nie_jest_iloscia(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum.fixture.collective_file_path, {"V19": 1, "T19": 1, "N19": 45, "O22": 0, "Y20": "0"})

    assert _choice(centrum)["without_quantity"] == {"state": "read", "rows": [19, 20, 21, 22]}


def test_plik_otwarty_w_excelu_dalej_wymienia_wiersze(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    path.with_name(f"~${path.name}").write_bytes(b"blokada Excela")

    choice = _choice(centrum)

    assert choice["without_quantity"] == {"state": "read", "rows": [19, 20, 21, 22]}
    assert choice["open_in_excel"] != []


def test_nieczytelny_plik_zbiorczy_nie_psuje_ustawienia_przebiegu(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.write_bytes(b"to nie jest skoroszyt")

    choice = _choice(centrum)

    assert choice["without_quantity"] == {"state": "unread"}
    assert choice["collective_file"] is not None


def test_plik_zbiorczy_bez_naglowka_urzadzen_nie_psuje_ustawienia_przebiegu(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    _write(centrum.fixture.collective_file_path, {}, header="URZĄDZENIA")

    assert _choice(centrum)["without_quantity"] == {"state": "unread"}

