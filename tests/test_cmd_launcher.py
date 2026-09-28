from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from openpyxl import load_workbook
import pytest

from tests.test_settlement_engine import PERIOD, active_worksheet, make_fixture


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _copy_launcher_runtime(destination: Path) -> Path:
    destination.mkdir()
    shutil.copy2(REPOSITORY_ROOT / "Utwórz rozliczenia.cmd", destination)
    shutil.copy2(REPOSITORY_ROOT / "run.py", destination)
    shutil.copytree(
        REPOSITORY_ROOT / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(REPOSITORY_ROOT / "config", destination / "config")
    return destination / "Utwórz rozliczenia.cmd"


def _input_value(path: Path) -> object:
    workbook = load_workbook(path, data_only=False)
    try:
        return active_worksheet(workbook)["A18"].value
    finally:
        workbook.close()


@pytest.mark.skipif(os.name != "nt", reason="The CMD launcher is Windows-only.")
def test_cmd_launcher_runs_the_settlement_path(tmp_path: Path) -> None:
    source_path, target_directory, _ = make_fixture(tmp_path / "fixture")
    launcher_path = _copy_launcher_runtime(tmp_path / "launcher")
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    command_line = f'cmd.exe /d /c ""{launcher_path}" "{source_path}""'

    result = subprocess.run(
        command_line,
        cwd=launcher_path.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=120,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Status końcowy: Wymaga sprawdzenia" in result.stdout
    assert _input_value(target_directory / f"Rozliczenie {PERIOD} - Adrian Maciejewski.xlsx") == "POZNAŃ"
    assert _input_value(target_directory / f"Rozliczenie {PERIOD} - Darek Nowak.xlsx") == "POZNAŃ"
    assert _input_value(target_directory / f"Rozliczenie {PERIOD} - Kamil Frontczak.xlsx") is None
    assert _input_value(target_directory / f"Rozliczenie {PERIOD} -.xlsx") is None
