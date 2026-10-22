"""Skrypty skilli ``verify-*`` mają jeden kontrakt wywołania: katalog runu, warianty i dowolny bieżący katalog.

Kontrakt trzyma ``tools/skrypt_skilla.py``. Test struktury pada, gdy skrypt skilla parsuje te argumenty po swojemu.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fixtures.skrypty_skilli import skrypt_skilla

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / ".agents" / "skills"
CLEANUPS = (
    SKILLS / "verify-rozliczenia" / "scripts" / "cleanup.py",
    SKILLS / "verify-centrum-rozliczen" / "scripts" / "centrum_cleanup.py",
)
CONTRACT_OPTIONS = {"--root", "--run-dir", "--variant"}
CWD_CALLS = {"chdir", "getcwd", "cwd"}

# Pliki otwartych PR-ów innych wątków przejdą na Parser po ich merge'u. Po terminie przypadek znów pada.
OPEN_PR_UNTIL = date(2026, 10, 29)
OPEN_PR = {
    "verify-centrum-rozliczen/scripts/serve_centrum.py": "#282 zmienia ten plik; --root z Parser po jego merge'u",
}
NOT_A_RUN = {
    "verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py": "pamięć podręczna narzędzi modelu TLA+, nie run",
}


def _script(script: Path, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _own_contract(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            options = {argument.value for argument in node.args if isinstance(argument, ast.Constant)} & CONTRACT_OPTIONS
            found += [f"{node.lineno}: add_argument({option})" for option in sorted(map(str, options))]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == ".verification" or node.value.startswith((".verification/", ".verification\\")):
                found.append(f"{node.lineno}: {node.value!r}")
        elif isinstance(node, ast.Attribute) and node.attr in CWD_CALLS:
            found.append(f"{node.lineno}: .{node.attr}")
    return found


def test_skrypty_skilli_biora_katalog_runu_warianty_i_sciezki_tylko_z_parsera() -> None:
    found = {
        path.relative_to(SKILLS).as_posix(): lines
        for path in sorted(SKILLS.glob("*/scripts/**/*.py"))
        if (lines := _own_contract(path))
    }
    allowed = {**NOT_A_RUN, **(OPEN_PR if date.today() <= OPEN_PR_UNTIL else {})}

    assert {path: lines for path, lines in found.items() if path not in allowed} == {}, (
        "--root, --run-dir i --variant dodają metody skrypt_skilla.Parser, katalog domyślny to skrypt_skilla.VERIFICATION, "
        "a skrypt nie zależy od bieżącego katalogu"
    )
    assert sorted(set(allowed) - set(found)) == [], "wyjątek bez znaleziska: usuń go"


@pytest.mark.parametrize("cleanup", CLEANUPS, ids=lambda path: path.name)
def test_sprzatanie_nie_usuwa_katalogu_ktorego_nie_utworzyla_fixture(tmp_path: Path, cleanup: Path) -> None:
    foreign = tmp_path / "dane-kogos"
    foreign.mkdir()
    (foreign / "wazne.txt").write_text("zostaje\n", encoding="utf-8")

    done = _script(cleanup, "--root", str(foreign), cwd=tmp_path)

    assert done.returncode == 1, done.stdout + done.stderr
    assert (foreign / "wazne.txt").read_text(encoding="utf-8") == "zostaje\n"


def test_fixture_nie_pisze_do_niepustego_katalogu(tmp_path: Path) -> None:
    occupied = tmp_path / "zajety"
    occupied.mkdir()
    (occupied / "wazne.txt").write_text("zostaje\n", encoding="utf-8")

    done = _script(SKILLS / "verify-rozliczenia" / "scripts" / "create_fixture.py", "--root", str(occupied), cwd=tmp_path)

    assert done.returncode == 1, done.stdout + done.stderr
    assert sorted(path.name for path in occupied.iterdir()) == ["wazne.txt"]


def test_katalog_runu_poza_repozytorium_wzgledny_wobec_biezacego_katalogu(tmp_path: Path) -> None:
    scripts = SKILLS / "verify-rozliczenia" / "scripts"
    (tmp_path / "tu").mkdir()
    (tmp_path / "gdzie-indziej").mkdir()
    root = (tmp_path / "tu" / "run" / "fx").resolve()

    created = _script(scripts / "create_fixture.py", "--root", "run/fx", cwd=tmp_path / "tu")
    removed = _script(scripts / "cleanup.py", "--root", str(root), cwd=tmp_path / "gdzie-indziej")

    assert created.returncode == 0 and f"root={root} " in created.stdout, created.stdout + created.stderr
    assert removed.returncode == 0 and f"removed={root}" in removed.stdout, removed.stdout + removed.stderr
    assert not root.exists()


VARIANTS = ("default", "existing", "locked", "chain-real-templates")
EVERY = ("default", "existing", "locked")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ("default",)),
        (["--variant", "existing", "locked"], ("existing", "locked")),
        (["--variant", "existing locked"], ("existing", "locked")),
        (["--variant existing"], ("existing",)),
        (["--variant existing locked"], ("existing", "locked")),
        (["--variant", "existing,locked"], ("existing", "locked")),
        (["--variant", "locked", "--variant", "existing"], ("locked", "existing")),
        (["--variant", "locked", "all", "chain-real-templates"], ("locked", "default", "existing", "chain-real-templates")),
    ],
)
def test_wariant_to_lista_takze_w_jednym_argumencie(argv: list[str], expected: tuple[str, ...]) -> None:
    parser = skrypt_skilla.Parser()
    parser.add_variants(VARIANTS, default="default", every=EVERY)

    assert parser.parse_args(argv).variant == expected


def test_nieznany_wariant_konczy_sie_lista_znanych(capsys: pytest.CaptureFixture[str]) -> None:
    parser = skrypt_skilla.Parser()
    parser.add_variants(VARIANTS, default="default", every=EVERY)

    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["--variant", "existing", "zablokowany"])

    error = capsys.readouterr().err
    assert stopped.value.code == 2
    assert "zablokowany" in error and "existing, locked, chain-real-templates, all" in error


def test_katalog_przebiegu_domyslnie_w_checkoucie_a_podany_bezwzgledny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = skrypt_skilla.Parser()
    parser.add_run_dir()
    monkeypatch.chdir(tmp_path)

    assert parser.parse_args([]).run_dir == REPO / ".verification"
    assert parser.parse_args(["--run-dir", "notatki/run"]).run_dir == tmp_path.resolve() / "notatki" / "run"
