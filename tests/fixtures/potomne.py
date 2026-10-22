"""Wnuk polecenia co 0,1 s dopisuje znak do pliku; plik, który przestał rosnąć, znaczy, że wnuk nie żyje.

Na Windows ``os.kill(pid, 0)`` nie sprawdza procesu, tylko wysyła mu Ctrl+C (``CTRL_C_EVENT`` to 0).
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import potomne  # noqa: E402

__all__ = ["TOOLS", "beating", "potomne", "with_grandchild"]

GRANDCHILD = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('.')\n    time.sleep(0.1)\n"


def with_grandchild(beats: Path, then: str, *, grandchild_output: str = "") -> list[str]:
    """``then`` biegnie, gdy wnuk już dopisuje do ``beats``.

    ``grandchild_output`` to kod doklejony do argumentów ``Popen`` wnuka, np. ``", stdout=subprocess.DEVNULL"``;
    bez niego wnuk dziedziczy wyjście polecenia.
    """

    code = (
        "import pathlib, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {GRANDCHILD!r}, {str(beats)!r}]{grandchild_output})\n"
        f"while not pathlib.Path({str(beats)!r}).exists():\n"
        "    time.sleep(0.05)\n"
        f"{then}\n"
    )
    return [sys.executable, "-c", code]


def beating(beats: Path) -> bool:
    before = beats.stat().st_size
    time.sleep(2)
    return beats.stat().st_size != before
