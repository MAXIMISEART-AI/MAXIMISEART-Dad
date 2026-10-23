"""Skrypty narzędzi i skilli startują osobnym procesem bez zainstalowanego pakietu ``rozliczenia``.

CI na Windows instaluje tylko ``requirements.txt``, więc skrypt widzi ``src`` tylko wtedy, gdy sam dopisze go do
``sys.path`` (jak ``tools/uruchom_proces.py``). Na Macu ``.venv`` ma instalację edytowalną, która to chowa, więc
test usuwa z ``sys.path`` każdy katalog z pakietem ``rozliczenia`` i uruchamia ``--help`` każdego skryptu z parserem
argumentów, tak jak ``python skrypt.py``. Skrypty bez parsera pomija, bo ``--help`` nie zatrzymałoby ich pracy.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*(ROOT / "tools").glob("**/*.py"), *(ROOT / ".agents" / "skills").glob("*/scripts/**/*.py")])
WITHOUT_INSTALL = (
    "import runpy, sys\n"
    "from pathlib import Path\n"
    "script = sys.argv[1]\n"
    "sys.path[:] = [entry for entry in sys.path if not (Path(entry or '.') / 'rozliczenia').is_dir()]\n"
    "sys.path.insert(0, str(Path(script).parent))\n"
    "sys.argv = [script, '--help']\n"
    "runpy.run_path(script, run_name='__main__')\n"
)


def _runs_with_parser(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    entry = any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in tree.body)
    parser = any(
        isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in ("ArgumentParser", "Parser")
        for node in ast.walk(tree)
    )
    return entry and parser


@pytest.mark.skipif(sys.platform == "win32", reason="CI na Windows i tak uruchamia skrypty bez instalacji pakietu")
@pytest.mark.parametrize(
    "script", [path for path in SCRIPTS if _runs_with_parser(path)], ids=lambda path: path.relative_to(ROOT).as_posix()
)
def test_skrypt_odpowiada_na_help_bez_zainstalowanego_pakietu(tmp_path: Path, script: Path) -> None:
    answered = subprocess.run(
        [sys.executable, "-c", WITHOUT_INSTALL, str(script)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert answered.returncode == 0, answered.stderr
