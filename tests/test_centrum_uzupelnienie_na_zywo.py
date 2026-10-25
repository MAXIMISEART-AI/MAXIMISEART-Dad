"""Uzupełnienie pliku zbiorczego na żywo (#419, ADR 0016), przez HTTP API jak przeglądarka.

Strona pyta co kilka sekund o znacznik zapisu Pliku zbiorczego i pobiera widok dopiero po jego zmianie. Gdy odczyt
się nie uda, widok przez minutę niesie ostatni dobry stan z godziną odczytu, a potem Komunikat. Minutę odmierza
zegar Centrum testu, nigdy uśpienie.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import workbook_files
from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, run_to_end
from tests.fixtures.preparation import PERIOD, register_order

TUE = datetime(2026, 9, 8, 10, 0)
MON = datetime(2026, 9, 14, 9, 0)
VIEW = f"/api/periods/{PERIOD}/quantities-to-fill"
VERSION = f"/api/periods/{PERIOD}/collective-file-version"
LOG_EVENT = "uzupelnienie-odczyt-nieudany"


def _prepared(tmp_path: Path) -> PreparingCentrum:
    # Wiersz 18 z URZĄDZENIAMI, których Reguły ilości nie znają (bez reguły); ostatnie zlecenie w poniedziałek,
    # więc okres jest pełny i Przygotowanie nie czeka na Decyzję taty.
    rows = [{**register_order(1, TUE), "URZĄDZENIA": "przeniesienie"}, {**register_order(2, MON), "URZĄDZENIA": ""}]
    centrum = preparing_centrum(tmp_path, list(rows))
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    return centrum


def _get(centrum: PreparingCentrum, url: str) -> dict[str, Any]:
    response = centrum.client.get(url)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def _without_rule(view: dict[str, Any]) -> list[tuple[int, bool]]:
    [kind] = (kind for kind in view["kinds"] if kind["kind"] == "without_rule")
    return [(row["row"], row["done"]) for row in kind["rows"]]


def _type_in_excel(path: Path, cell: str, value: int) -> None:
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet[cell] = value
    workbook.save(path)


def _log_lines(centrum: PreparingCentrum) -> list[str]:
    if not centrum.log_path.exists():
        return []
    return [line for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if LOG_EVENT in line]


def test_sprawdzenie_zapisu_bez_zmian_nie_otwiera_skoroszytu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = _prepared(tmp_path)
    shown = _get(centrum, VIEW)["read"]["version"]
    opened: list[Path] = []
    file_bytes = workbook_files._file_bytes

    def counted(path: Path) -> bytes:
        opened.append(path)
        return file_bytes(path)

    # Jedyny odczyt bajtów skoroszytu w src/ (tests/test_jeden_odczyt_skoroszytu.py).
    monkeypatch.setattr(workbook_files, "_file_bytes", counted)

    answers = [_get(centrum, VERSION)["version"] for _ in range(3)]

    assert shown is not None
    assert answers == [shown] * 3
    assert opened == []
    _get(centrum, VIEW)
    assert opened == [centrum.fixture.collective_file_path]


def test_zapis_taty_zmienia_znacznik_a_widok_niesie_nowy(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    before = _get(centrum, VIEW)["read"]["version"]

    _type_in_excel(centrum.fixture.collective_file_path, "O18", 1)
    changed = _get(centrum, VERSION)["version"]
    view = _get(centrum, VIEW)

    assert changed != before
    assert view["read"]["version"] == changed
    assert _without_rule(view) == [(18, True)]


def test_bez_pliku_zbiorczego_znacznik_jest_pusty(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.unlink()

    assert _get(centrum, VERSION) == {"version": None}


def test_nieudany_odczyt_przez_minute_pokazuje_ostatni_dobry_stan_potem_komunikat(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    good = _get(centrum, VIEW)
    original = path.read_bytes()
    path.write_bytes(b"Excel zapisuje")

    kept = _get(centrum, VIEW)
    centrum.surroundings.clock.advance(minutes=59 / 60)
    still_kept = _get(centrum, VIEW)
    centrum.surroundings.clock.advance(minutes=1 / 60)
    shown = _get(centrum, VIEW)
    path.write_bytes(original)
    back = _get(centrum, VIEW)

    assert kept == {**good, "read": {**good["read"], "retrying": True}}
    assert still_kept == kept
    assert shown["state"] == "problem"
    assert shown["message"]["what"] == "Plik zbiorczy jest uszkodzony albo nie jest skoroszytem Excela."
    assert shown["version"] != good["read"]["version"]
    assert back["state"] == "ready"
    assert back["read"]["retrying"] is False
    assert back["read"]["read_at"] > good["read"]["read_at"]


def test_seria_nieudanych_odczytow_to_jeden_wpis_w_dzienniku(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    original = path.read_bytes()
    path.write_bytes(b"")

    for _ in range(3):
        _get(centrum, VIEW)
    centrum.surroundings.clock.advance(minutes=2)
    _get(centrum, VIEW)
    path.write_bytes(original)
    _get(centrum, VIEW)
    path.write_bytes(b"")
    _get(centrum, VIEW)

    assert len(_log_lines(centrum)) == 2


def test_blokada_excela_bez_odpowiedzi_systemu_jest_nieznana(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    path.write_bytes(b"to nie jest skoroszyt")
    path.with_name(f"~${path.name}").write_bytes(b"blokada Excela")
    stat = Path.stat

    def denied(self: Path, *, follow_symlinks: bool = True) -> Any:
        # Jak ACL w Windows, której os.access nie widzi: system odmawia odpowiedzi o pliku blokady.
        if self.name.startswith("~$"):
            raise PermissionError(13, "Odmowa dostępu", str(self))
        return stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", denied)

    assert _get(centrum, VIEW)["state"] == "problem"
    [line] = _log_lines(centrum)
    assert "przyczyna=USZKODZONY_PLIK_ZBIORCZY excel=nieznany typ=BadZipFile" in line
