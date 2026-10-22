"""Bajty plików z kopii Wzorca (ADR 0008) przypięte na czas ujednolicenia zapisu Wierszy danych.

Przypięcie jest tymczasowe: znika w ostatnim commicie tej zmiany, gdy bramka na kopiach danych taty
pokaże te same bajty. Kopia jest deterministyczna, więc każda rozpakowana część Pliku zbiorczego
i każdego Rozliczenia pracownika ma stały skrót SHA-256.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import replace
from pathlib import Path

from rozliczenia.engine import run_settlements

from tests.fixtures.benchmark import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, WORKER_TEMPLATE, write_synthetic_templates
from tests.fixtures.preparation import link_register_order_numbers, make_preparation_fixture, run_preparation


def _digest(path: Path) -> str:
    """Skrót rozpakowanych części w kolejności z pliku: nazwa i SHA-256 treści.

    ``docProps/*`` kopia przepisuje z Wzorca bez zmian, a Wzorce testowe zapisuje openpyxl ze znacznikiem czasu.
    """

    with zipfile.ZipFile(path) as archive:
        listing = "".join(
            f"{info.filename}\0{hashlib.sha256(archive.read(info)).hexdigest()}\n"
            for info in archive.infolist()
            if not info.filename.startswith("docProps/")
        )
    return hashlib.sha256(listing.encode()).hexdigest()


def _written_files(tmp_path: Path, *, synthetic: bool) -> dict[str, str]:
    fixture = make_preparation_fixture(tmp_path)
    link_register_order_numbers(fixture.register_path, "https://przyklad.invalid/zlecenie?caseId=SYN-1&tw=1")
    worker_template = None
    if synthetic:
        templates = write_synthetic_templates(tmp_path / "wzorce")
        fixture = replace(
            fixture,
            internal_template_path=templates / INTERNAL_TEMPLATE,
            collective_template_path=templates / COLLECTIVE_TEMPLATE,
        )
        worker_template = templates / WORKER_TEMPLATE
    run_preparation(fixture)
    files = {fixture.collective_file_path.name: _digest(fixture.collective_file_path)}
    if worker_template is not None:
        summary = run_settlements(fixture.collective_file_path, fixture.config_path, worker_template_path=worker_template)
        files.update({path.name: _digest(path) for path in sorted(summary.target_directory.iterdir())})
    return files


def test_plik_zbiorczy_z_kopii_wzorca_ma_przypiete_bajty(tmp_path: Path) -> None:
    assert _written_files(tmp_path, synthetic=False) == {
        "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx": "29022c8471d466e4a188ee9ac4618e411efe8096cf274a082305996845e9c04f",
    }


def test_plik_zbiorczy_i_rozliczenia_pracownikow_z_kopii_wzorcow_ksztaltu_taty_maja_przypiete_bajty(tmp_path: Path) -> None:
    assert _written_files(tmp_path, synthetic=True) == {
        "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx": "cc229b55caae1e1db8f54ca954fd1228bb30736d4c84b53beb28a10a7eb3b38a",
        "Rozliczenie 08_14_09_2026 - Adrian Testowy.xlsx": "95527dc8d1f721de2095a19b2557136a61b9124983854ee0f78ce13dbe0559b6",
        "Rozliczenie 08_14_09_2026 - Darek Fikcyjny.xlsx": "bfb53664b2f9c1cbc91f8fc0802cee7a7e7f5b4671bfec3728b35cb99621ce93",
        "Rozliczenie 08_14_09_2026 - Kamil Syntetyczny.xlsx": "1fa6465b9a7a3144cb9ca38686a8e98a33fe74c7ddde929a0851bef8800a44a8",
    }
