"""Małe repozytorium Gita w katalogu testu z narzędziami z ``tools/`` checkoutu."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
AUTHOR = {name: value for role in ("AUTHOR", "COMMITTER") for name, value in ((f"GIT_{role}_NAME", "test"), (f"GIT_{role}_EMAIL", "test@example.com"))}

__all__ = ["commit", "git", "repository"]


def git(repo: Path, *arguments: str) -> str:
    answered = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env={**os.environ, **AUTHOR},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return answered.stdout.strip()


def commit(repo: Path, subject: str) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", subject)
    return git(repo, "rev-parse", "HEAD")


def repository(path: Path, files: dict[str, str]) -> Path:
    """Repozytorium z ``pyproject.toml`` i narzędziami checkoutu oraz ``files``, bez commitu."""

    for name in ("pyproject.toml", "tools/ci_lokalnie.py", "tools/ciezkie_ci.py", "tools/czasy_ci.py", "tools/mutacje.py", "tools/potomne.py", "tools/sciezki_w_kodzie.py"):
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path / name)
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    git(path, "init", "--quiet")
    return path
