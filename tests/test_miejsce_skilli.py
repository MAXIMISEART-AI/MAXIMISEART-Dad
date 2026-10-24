"""Skille projektu leżą tylko w ``.agents/skills/<skill>/SKILL.md`` (AGENTS.md: skille projektu).

Kopia w ``.claude/skills/`` albo ``.cursor/skills/`` rozjeżdża się z oryginałem, a harness jednego narzędzia widzi
inną wersję skilla niż drugi. Test patrzy na pliki śledzone i nieśledzone, a w ``.claude/`` i ``.cursor/`` także na
ignorowane, bo narzędzie czyta skille z dysku, nie z gita. Wielkość liter się nie liczy, bo NTFS i APFS jej nie
rozróżniają.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from tests.fixtures.git_repo import git

ROOT = Path(__file__).resolve().parents[1]
FOREIGN = ((".claude", "skills"), (".cursor", "skills"))
IGNORED_FOREIGN = tuple(f":(icase){directory}" for directory, _ in FOREIGN)
FIX = "przenieś skill do .agents/skills/<skill>/SKILL.md i usuń kopię (/pstack:create-verification-skill zapisuje tam)"


def _repository_paths() -> list[PurePosixPath]:
    listed = git(ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    ignored = git(ROOT, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", *IGNORED_FOREIGN)
    return [PurePosixPath(name) for name in sorted(set(filter(None, f"{listed}\0{ignored}".split("\0"))))]


def _misplaced(name: PurePosixPath) -> str | None:
    path = ROOT / name
    if tuple(part.casefold() for part in name.parts[:2]) in FOREIGN:
        return f"{name}: {'/'.join(name.parts[:2])}/ nie może istnieć w repozytorium"
    if name.name.casefold() == "skill.md" and (
        name.parts[:2] != (".agents", "skills") or len(name.parts) != 4 or name.name != "SKILL.md"
    ):
        return f"{name} nie jest .agents/skills/<skill>/SKILL.md"
    if path.is_symlink() and path.is_dir() and any(child.name.casefold() == "skill.md" for child in path.rglob("*")):
        return f"{name} to dowiązanie do katalogu ze SKILL.md"
    return None


def test_skille_projektu_leza_tylko_w_agents_skills() -> None:
    paths = _repository_paths()

    misplaced = [problem for problem in map(_misplaced, paths) if problem]

    assert PurePosixPath(".agents/skills/verify-rozliczenia/SKILL.md") in paths
    assert misplaced == [], f"{FIX}: {misplaced}"
