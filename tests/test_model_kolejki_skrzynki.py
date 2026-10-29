"""Sprawdzenie modelu TLA+ Kolejki Skrzynki nie przechodzi w CI, gdy pokryty kod rozjechał się z modelem.

Podstawa skilla w CI (``sprawdz_kolejke.py``) uruchamia model i sprawdzenie prawdziwego kodu, każde do końca, i pada,
gdy padło którekolwiek.

Model opisuje kod z commitu synchronizacji w ``SKILL.md`` skilla ``verify-kolejka-skrzynki``. Javę, ``tla2tools.jar``
i porównanie z commitem bierze ze skryptu skilla ``verify-aktualizacja-narzedzia``, a zmienne ``TLC_JAVA`` i
``TLC_JAR`` (kopia checkoutu mutacji) zastępują jego Javę i jar.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tests.fixtures.git_repo import commit, git

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_model_kolejki.py"
BASELINE = ROOT / ".agents" / "skills" / "verify-kolejka-skrzynki" / "scripts" / "sprawdz_kolejke.py"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
COVERED = "src/rozliczenia/centrum/outbox.py"
DRIFT = "MODEL KOLEJKI: ROZJAZD MODELU Z KODEM"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sprawdz_model_kolejki", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w_ci_pokryty_kod_zmieniony_od_synchronizacji_konczy_sprawdzenie_modelu_kolejki_porazka(tmp_path: Path) -> None:
    (tmp_path / COVERED).parent.mkdir(parents=True)
    (tmp_path / COVERED).write_text("X = 1\n", encoding="utf-8")
    for script in (SCRIPT, TOOLS):
        copy = tmp_path / script.relative_to(ROOT)
        copy.parent.mkdir(parents=True)
        shutil.copy(script, copy)
    git(tmp_path, "init", "--quiet")
    sync = commit(tmp_path, "synchronizacja")
    (tmp_path / COVERED).write_text("X = 2\n", encoding="utf-8")
    commit(tmp_path, "zmiana pokrytego kodu")
    skill = tmp_path / SCRIPT.relative_to(ROOT).parents[1]
    (skill / "SKILL.md").write_text(f"Covered: `{COVERED}`.\n\n**Sync commit: `{sync[:8]}`** (main).\n", encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(skill / "scripts" / SCRIPT.name)],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == DRIFT
    assert f"pokryty kod zmienił się od {sync[:8]}: {COVERED}" in done.stdout


def test_java_i_jar_ze_zmiennych_srodowiska_zastepuja_narzedzia_aktualizacji(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()

    def unavailable() -> str:
        raise AssertionError("kopia checkoutu mutacji nie ma katalogu podręcznego z Javą i jarem")

    tools = SimpleNamespace(_drift=lambda root, skill_md: None, _java=unavailable, _tla_tools=unavailable)
    monkeypatch.setattr(module, "_tools", lambda: tools)
    (tmp_path / "oczekiwane.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "MODEL", tmp_path)  # model bez konfiguracji: sprawdzenie biegnie do końca bez TLC
    monkeypatch.setenv("TLC_JAVA", "java")
    monkeypatch.setenv("TLC_JAR", str(tmp_path / "tla2tools.jar"))

    assert module.main([]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "MODEL KOLEJKI OK"


def test_kontrprzyklad_skleja_wartosc_zmiennej_z_kilku_linii_tlc() -> None:
    output = "\n".join(
        [
            "Error: Invariant JednoIssue is violated.",
            "State 1: <Initial predicate>",
            '/\\ krok = "start"',
            "/\\ issues = <<>>",
            "State 2: <Zaloz line 296, col 5 to line 322, col 63 of module KolejkaSkrzynki>",
            '/\\ krok = "open_issue: Sent"',
            '/\\ issues = << [klucz |-> "L", tresc |-> <<<<1, 1>>>>],',
            '   [klucz |-> "L", tresc |-> <<<<1, 1>>>>] >>',
            '/\\ plik = <<"czeka">>',
            "State 3: Stuttering",
        ]
    )

    trace = _load()._trace(output)

    assert trace[1]["issues"] == '<< [klucz |-> "L", tresc |-> <<<<1, 1>>>>], [klucz |-> "L", tresc |-> <<<<1, 1>>>>] >>'
    assert trace[1]["plik"] == '<<"czeka">>'
    assert trace[2]["krok"] == "(dalej nic sie nie dzieje)"


@pytest.mark.parametrize(
    ("codes", "last", "returncode"),
    [
        ((0, 0), "KOLEJKA SKRZYNKI OK", 0),
        ((1, 0), "KOLEJKA SKRZYNKI: PADŁO sprawdz_model_kolejki.py", 1),
        ((0, 1), "KOLEJKA SKRZYNKI: PADŁO explore_outbox.py", 1),
    ],
)
def test_podstawa_ci_uruchamia_model_i_sprawdzenie_kodu_do_konca_i_pada_gdy_padlo_ktores(
    tmp_path: Path, codes: tuple[int, int], last: str, returncode: int
) -> None:
    shutil.copy(BASELINE, tmp_path / BASELINE.name)
    for name, code in zip(("sprawdz_model_kolejki.py", "explore_outbox.py"), codes, strict=True):
        (tmp_path / name).write_text(f"print('{name}')\nraise SystemExit({code})\n", encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(tmp_path / BASELINE.name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    lines = done.stdout.splitlines()
    assert (done.returncode, lines[-1]) == (returncode, last), done.stdout + done.stderr
    assert lines.index("sprawdz_model_kolejki.py") < lines.index("explore_outbox.py")
