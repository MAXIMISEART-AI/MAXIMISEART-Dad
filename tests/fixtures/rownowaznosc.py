"""Weryfikacja różnicowa w testach: moduł ``tools/rownowaznosc.py`` i drzewa ze skryptem dla maszyn na niby.

Drzewo na niby ma tylko ``tools/uruchom_proces.py``, który drukuje podany JSON, zapisuje podane pliki w folderze
scenariusza i kończy się podanym kodem, więc test porównania nie zależy od procesów.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from openpyxl import Workbook

from tests.fixtures.workbooks import active_worksheet

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import rownowaznosc  # noqa: E402

__all__ = ["rownowaznosc", "stub_tree", "write_workbook"]

_STUB = """import json, pathlib, sys
for name, text in {files!r}.items():
    path = pathlib.Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
sys.stdout.write({output!r})
raise SystemExit({code})
"""


def stub_tree(path: Path, result: object, *, code: int = 0, files: dict[str, str] | None = None) -> Path:
    """Drzewo, którego skrypt dla maszyn drukuje ``result`` jako JSON (napis: dosłownie) i zapisuje ``files``."""

    output = result if isinstance(result, str) else json.dumps(result)
    script = path / "tools" / "uruchom_proces.py"
    script.parent.mkdir(parents=True)
    script.write_text(_STUB.format(files=files or {}, output=output, code=code), encoding="utf-8")
    return path


def write_workbook(path: Path, value: str | int) -> Path:
    """Skoroszyt z jedną wartością w A1."""

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    active_worksheet(workbook)["A1"] = value
    workbook.save(path)
    return path
