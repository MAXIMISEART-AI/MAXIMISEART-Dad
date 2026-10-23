"""``tools/promuj_stabilna.py`` przesuwa `stabilna` tylko do przodu, tylko na commit `main` (ADR 0014).

Prawdziwy Git: „origin” bez katalogu roboczego zamiast GitHuba i jego klon z pełną historią jako checkout
workflow. Żaden test nie łączy się z siecią.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from tests.fixtures.tool_clone import git, isolated_git_environment

TOOL = Path(__file__).resolve().parents[1] / "tools" / "promuj_stabilna.py"


@dataclass(frozen=True)
class Repositories:
    publisher: Path
    origin: Path
    checkout: Path
    main: tuple[str, ...]

    def stabilna(self) -> str | None:
        found = subprocess.run(
            ["git", "-C", str(self.origin), "rev-parse", "--verify", "--quiet", "refs/heads/stabilna"],
            env=isolated_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        return found.stdout.strip() or None

    def set_stabilna(self, commit: str) -> None:
        git(self.origin, "update-ref", "refs/heads/stabilna", commit)


@pytest.fixture
def repositories(tmp_path: Path) -> Repositories:
    publisher, origin, checkout = tmp_path / "wydawca", tmp_path / "origin.git", tmp_path / "checkout"
    publisher.mkdir()
    git(publisher, "init", "--quiet", "--initial-branch", "main")
    commits = []
    for number in range(1, 4):
        (publisher / "wersja.txt").write_text(f"{number}\n", encoding="utf-8")
        git(publisher, "add", "--all")
        git(publisher, "commit", "--quiet", "--message", f"Wersja {number}")
        commits.append(git(publisher, "rev-parse", "HEAD"))
    git(tmp_path, "clone", "--quiet", "--bare", str(publisher), str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(checkout))
    return Repositories(publisher, origin, checkout, tuple(commits))


def promote(repositories: Repositories, commit: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), commit],
        cwd=repositories.checkout,
        env=isolated_git_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_pierwszy_zielony_main_zaklada_stabilna(repositories: Repositories) -> None:
    first, _, _ = repositories.main

    result = promote(repositories, first)

    assert result.returncode == 0, result.stderr
    assert repositories.stabilna() == first


def test_zielony_main_przesuwa_stabilna_do_przodu_dokladnie_na_swoj_commit(repositories: Repositories) -> None:
    first, green, _ = repositories.main
    repositories.set_stabilna(first)

    result = promote(repositories, green)

    assert result.returncode == 0, result.stderr
    assert repositories.stabilna() == green


def test_spozniony_run_starszego_commitu_nie_cofa_stabilna(repositories: Repositories) -> None:
    _, older, newer = repositories.main
    repositories.set_stabilna(newer)

    result = promote(repositories, older)

    assert result.returncode == 0, result.stderr
    assert repositories.stabilna() == newer


def test_commit_spoza_main_nie_trafia_na_stabilna(repositories: Repositories) -> None:
    first, _, _ = repositories.main
    repositories.set_stabilna(first)
    git(repositories.publisher, "checkout", "--quiet", "-b", "pr", first)
    (repositories.publisher / "wersja.txt").write_text("z PR\n", encoding="utf-8")
    git(repositories.publisher, "commit", "--quiet", "--all", "--message", "Commit z PR")
    git(repositories.publisher, "push", "--quiet", str(repositories.origin), "pr")
    branch_commit = git(repositories.publisher, "rev-parse", "HEAD")
    git(repositories.checkout, "fetch", "--quiet", "origin", "pr")

    result = promote(repositories, branch_commit)

    assert result.returncode == 1
    assert "nie jest na main" in result.stderr
    assert repositories.stabilna() == first


def test_stabilna_spoza_historii_main_zostaje_bez_zmian(repositories: Repositories) -> None:
    first, _, newest = repositories.main
    git(repositories.publisher, "checkout", "--quiet", "--orphan", "inna-historia")
    git(repositories.publisher, "commit", "--quiet", "--message", "Inna historia")
    git(repositories.publisher, "push", "--quiet", str(repositories.origin), "inna-historia:stabilna")
    rewritten = repositories.stabilna()

    result = promote(repositories, newest)

    assert result.returncode == 1
    assert "nie jest przodkiem" in result.stderr
    assert repositories.stabilna() == rewritten != first


def test_stabilna_przesunieta_przez_inny_run_w_trakcie_pushu_nie_cofa_sie(
    repositories: Repositories, tmp_path: Path
) -> None:
    first, older, newer = repositories.main
    repositories.set_stabilna(first)
    moved = tmp_path / "inny-run-przesunal"
    hook = repositories.checkout / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        f'if [ ! -e "{moved.as_posix()}" ]; then\n'
        f'  touch "{moved.as_posix()}"\n'
        f'  GIT_DIR="{repositories.origin.as_posix()}" git update-ref refs/heads/stabilna {newer}\n'
        "fi\n",
        encoding="utf-8",
        newline="\n",
    )
    hook.chmod(0o755)

    result = promote(repositories, older)

    assert result.returncode == 0, result.stderr
    assert moved.exists()
    assert repositories.stabilna() == newer


def test_workflow_promocji_czeka_na_status_ktory_ci_naprawde_ma() -> None:
    # Inna nazwa workflow albo statusu nie daje błędu: `stabilna` po cichu przestaje się przesuwać.
    workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    ci = yaml.safe_load((workflows / "ci.yml").read_text(encoding="utf-8"))
    promotion = (workflows / "stabilna.yml").read_text(encoding="utf-8")
    trigger = yaml.safe_load(promotion)[True]["workflow_run"]

    assert trigger["workflows"] == [ci["name"]]
    assert "push" in ci[True] and ci[True]["push"]["branches"] == ["main"]
    assert f'select(.name == "{ci["jobs"]["required"]["name"]}")' in promotion
