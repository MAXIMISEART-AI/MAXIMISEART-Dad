"""Mapa funkcji skilla ``verify-*`` (``features/``) zgadza się z jego kodem i ``SKILL.md``.

Mapa to pamięć skilla: agent wybiera z niej funkcję do sprawdzenia, a harness skilla prowadzi funkcje z krotek
``FEATURES`` i ``EXPLICIT_FEATURES`` w swoich skryptach i z modułów pakietu ``scripts/<pakiet>/``. Rozjazd mapy z kodem
czerwieni CI, a nie dopiero przebieg skilla u agenta.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
MAPS = sorted(path.parent for path in SKILLS.glob("*/features"))
FEATURE_LISTS = ("FEATURES", "EXPLICIT_FEATURES")
PACKAGE_HELPERS = frozenset({"__init__", "common"})
LINK = re.compile(r"\]\(\./([^)]+\.md)\)")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
DRIVING = re.compile(r"## Driving it with \S.*")


@dataclass(frozen=True)
class Feature:
    name: str
    source: str


def _feature_files(skill: Path) -> list[Path]:
    return sorted(path for path in (skill / "features").glob("*.md") if path.name != "README.md")


def _feature_list_values(tree: ast.Module) -> list[tuple[str, ast.expr]]:
    return [
        (target.id, node.value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and node.value is not None
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id in FEATURE_LISTS
    ]


def _code_features(skill: Path) -> list[Feature]:
    features = []
    for path in sorted((skill / "scripts").rglob("*.py")):
        source = path.relative_to(skill).as_posix()
        for name, value in _feature_list_values(ast.parse(path.read_text(encoding="utf-8"))):
            try:
                features += [Feature(feature, f"{name} w {source}") for feature in ast.literal_eval(value)]
            except ValueError:
                pytest.fail(f"{name} w {source}:{value.lineno} nie jest krotką napisów: zapisz funkcje literałem")
    return features


def _package_modules(skill: Path) -> list[Feature]:
    return [
        Feature(module.stem.replace("_", "-"), module.relative_to(skill).as_posix())
        for package in sorted(path.parent for path in (skill / "scripts").glob("*/__init__.py"))
        for module in sorted(package.glob("*.py"))
        if module.stem not in PACKAGE_HELPERS
    ]


@pytest.mark.parametrize("skill", MAPS, ids=lambda skill: skill.name)
def test_kazdy_plik_funkcji_ma_link_w_mapie_skilla(skill: Path) -> None:
    index = skill / "features" / "README.md"
    linked = LINK.findall(HTML_COMMENT.sub("", index.read_text(encoding="utf-8"))) if index.is_file() else []
    files = [path.name for path in _feature_files(skill)]

    problems = [
        f"{skill.name}/features/README.md linkuje {name}, którego nie ma: dopisz plik funkcji albo usuń link"
        for name in linked
        if name not in files
    ] + [
        f"{skill.name}/features/{name} nie ma linku w features/README.md: "
        f"dopisz w sekcji ## Features linię `- [Nazwa funkcji](./{name}) covers …`"
        for name in files
        if name not in linked
    ]

    assert index.is_file(), f"{skill.name}/features/ nie ma README.md: dopisz mapę funkcji z linkiem do każdego pliku"
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("skill", MAPS, ids=lambda skill: skill.name)
def test_kazdy_plik_funkcji_ma_naglowki_h2_z_szablonu(skill: Path) -> None:
    headings = {
        path.name: [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
        for path in _feature_files(skill)
    }
    driving = {found[2] for found in headings.values() if len(found) == 4}

    problems = [
        f"{skill.name}/features/{name} ma nagłówki H2 {found}: zostaw dokładnie `## Sub-features`, "
        "`## How to get to it (user POV)`, `## Driving it with …` (jak w pozostałych plikach skilla) i `## Gotchas`, "
        "w tej kolejności (## Feature entry contract w features/README.md)"
        for name, found in headings.items()
        if len(found) != 4
        or found[:2] != ["## Sub-features", "## How to get to it (user POV)"]
        or not DRIVING.fullmatch(found[2])
        or found[3] != "## Gotchas"
    ]

    assert problems == [], "\n".join(problems)
    assert len(driving) <= 1, (
        f"pliki funkcji {skill.name} prowadzą funkcje różnymi nagłówkami {sorted(driving)}: ujednolić `## Driving it with …`"
    )


CODE_MAPS = [skill for skill in MAPS if _code_features(skill) or _package_modules(skill)]


@pytest.mark.parametrize("skill", CODE_MAPS, ids=lambda skill: skill.name)
def test_kazda_funkcja_z_kodu_skilla_ma_plik_w_mapie_i_wpis_w_skill_md(skill: Path) -> None:
    files = {path.stem for path in _feature_files(skill)}
    skill_md = (skill / "SKILL.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"--feature ([a-z0-9-]+)", skill_md))

    without_file = [
        f"funkcja `{feature.name}` z {feature.source} nie ma pliku {skill.name}/features/{feature.name}.md: "
        "dopisz go według ## Feature entry contract z features/README.md i link do niego w tej mapie"
        for feature in [*_code_features(skill), *_package_modules(skill)]
        if feature.name not in files
    ]
    not_in_skill_md = [
        f"funkcja `{feature.name}` z {feature.source} nie pada w {skill.name}/SKILL.md: "
        f"dopisz `--feature {feature.name}` tam, gdzie SKILL.md wymienia funkcje"
        for feature in _code_features(skill)
        if feature.name not in listed
    ]

    assert without_file == [], "\n".join(without_file)
    assert not_in_skill_md == [], "\n".join(not_in_skill_md)


@pytest.mark.parametrize("skill", CODE_MAPS, ids=lambda skill: skill.name)
def test_kazdy_plik_funkcji_i_modul_pakietu_ma_funkcje_w_kodzie_skilla(skill: Path) -> None:
    driven = {feature.name for feature in _code_features(skill)}
    lists = " albo ".join(sorted({feature.source for feature in _code_features(skill)}))

    problems = [
        f"{skill.name}/features/{path.name} nie ma funkcji w kodzie: dopisz `{path.stem}` do {lists} "
        "i jej moduł albo usuń plik i jego link z features/README.md"
        for path in _feature_files(skill)
        if path.stem not in driven
    ] + [
        f"moduł {skill.name}/{module.source} nie jest funkcją harnessu: dopisz `{module.name}` do {lists} "
        "albo przenieś wspólny kod do common.py"
        for module in _package_modules(skill)
        if module.name not in driven
    ]

    assert lists, f"{skill.name} ma pakiet funkcji bez krotki {' ani '.join(FEATURE_LISTS)} w scripts/"
    assert problems == [], "\n".join(problems)
