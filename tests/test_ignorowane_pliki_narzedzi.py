"""Pliki, które narzędzia zostawiają w checkoucie, nie trafiają do ``git add -A``.

mypy wpisuje własny ``.gitignore`` do ``.mypy_cache`` dopiero na końcu przebiegu, więc przerwany przebieg zostawia
cache bez niego. Agent dowiązuje też ``.venv`` z innego worktree, a wzorzec katalogu ``.venv/`` dowiązania nie łapie.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from tests.fixtures.git_repo import git

ROOT = Path(__file__).resolve().parents[1]
LEFT_BY_TOOLS = (
    ".mypy_cache/3.11/cache.0.db",
    ".mypy_cache/win32/3.11/cache.0.db",
    ".ruff_cache/0.15.0/1234",
    ".hypothesis/constants/9b4d7b1f661b8540",
    ".pytest_cache/v/cache/nodeids",
    "tools/__pycache__/potomne.cpython-311.pyc",
)


def test_cache_narzedzi_bez_wlasnego_gitignore_i_dowiazane_venv_sa_ignorowane(tmp_path: Path) -> None:
    shutil.copy2(ROOT / ".gitignore", tmp_path / ".gitignore")
    for name in LEFT_BY_TOOLS:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("cache", encoding="utf-8")
    # Git widzi dowiązanie tak jak plik, nie jak katalog, a plik powstaje także na Windows bez uprawnień do dowiązań.
    (tmp_path / ".venv").write_text("dowiązanie", encoding="utf-8")
    git(tmp_path, "init", "--quiet")

    assert git(tmp_path, "status", "--porcelain", "--untracked-files=all") == "?? .gitignore"
