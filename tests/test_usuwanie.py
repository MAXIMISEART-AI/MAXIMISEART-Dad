"""Hook ``tools/hooks/usuwanie.py``: kształty ``rm``, które Claude Code zatrzymuje na zgodzie człowieka, dostają odmowę.

Polecenia z historii (``tests/fixtures/usuwanie_historia.jsonl``) to prawdziwe wywołania Basha agentów z 22–25.10.2026,
z ``/Users/Max`` skróconym do ``/Users/x``: 6, które czekały na zgodę (do 66 min), i próbka tych, które przeszły bez
niej, po dwa na każdy zestaw cech (``cd``, pętla, ``$(…)``, ``&&``, ``sh -c``, ``rm -r``, ``*``, heredoc).
Przypadki wyroczni (``tools/wyrocznia_usuwania.jsonl``) to odpowiedzi prawdziwego Claude Code 2.1.309–2.1.310,
z katalogami piaskownicy zastąpionymi ścieżkami tego samego rodzaju (bezwzględna, przez ``~``).
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "usuwanie.py"
ORACLE = ROOT / "tools" / "wyrocznia_usuwania.py"
CASES = ROOT / "tools" / "wyrocznia_usuwania.jsonl"
HISTORY = ROOT / "tests" / "fixtures" / "usuwanie_historia.jsonl"
SETTINGS = ROOT / ".claude" / "settings.json"
FIX = "Uruchom rm osobnym wywołaniem Basha z dosłowną ścieżką bezwzględną"
GUARDED = "${VAR:?}"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _placed(command: str) -> str:
    return command.replace("@WS@", "/srv/ws").replace("@FAR@", "/srv/far").replace("@TFAR@", "~/far")


HISTORY_ROWS = _rows(HISTORY)
STALLED = [row for row in HISTORY_ROWS if row["pyta_o_zgode"]]
RAN = [row["polecenie"] for row in HISTORY_ROWS if not row["pyta_o_zgode"]]
ORACLE_CASES = [pytest.param(_placed(row["polecenie"]), row["pyta_o_zgode"], id=row["nazwa"]) for row in _rows(CASES)]


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("usuwanie", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False)


def _bash(command: str) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x"}
    return _hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}))


def test_historia_ma_szesc_polecen_ktore_czekaly_na_zgode_i_probke_tych_ktore_przeszly() -> None:
    assert (len(STALLED), len(RAN) >= 100) == (6, True)


@pytest.mark.parametrize("command", [row["polecenie"] for row in STALLED], ids=[row["sesja"] for row in STALLED])
def test_polecenie_ktore_czekalo_na_zgode_dostaje_odmowe_z_poprawka(command: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert FIX in hooked.stderr
    assert GUARDED in hooked.stderr


@pytest.mark.parametrize("command", RAN)
def test_polecenie_ktore_przeszlo_bez_zgody_przechodzi(hook: ModuleType, command: str) -> None:
    assert hook.judge(command) is None


@pytest.mark.parametrize(("command", "asks"), ORACLE_CASES)
def test_hook_odrzuca_dokladnie_to_co_claude_code_zatrzymuje_w_wyroczni(hook: ModuleType, command: str, asks: bool) -> None:
    assert (hook.judge(command) is not None) == asks


@pytest.mark.parametrize(
    ("command", "shape"),
    [
        ("cd /srv/far && rm -f logi/*; echo b", "goły * po cd"),
        ("V=/srv/far; for w in a b; do rm -f $V/$w-x; done", "cel ze zmienną pętli"),
        ('V=/srv/far; for w in a b; do rm -f "${V}/${w}-x"; done', "cel ze zmienną pętli"),
        ('X=a; echo "$( [ "$X" = a ] && echo y || (echo n))"; rm -f /srv/far/x', "podpowłoka przed końcem $(…)"),
        ("echo a && rm -r /srv/far/t; S=env\n$S sh -c 'echo A'", "polecenie ze zmiennej z sh -c"),
        ('echo a; rm -rf "$(echo /srv/far/logi-x)"', "rm -r z celem z $(…)"),
        ("echo a; rm --recursive `echo /srv/far/logi-x`", "rm -r z celem z $(…)"),
    ],
)
def test_odmowa_nazywa_ksztalt_i_poprawke(command: str, shape: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert hooked.stderr.startswith(f"Odmowa ({shape}):")
    assert FIX in hooked.stderr
    assert GUARDED in hooked.stderr


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("rm -f /abs/logi/*", id="sciezka-bezwzgledna"),
        pytest.param("cd /srv/far; rm -f /srv/far/logi/*", id="sciezka-bezwzgledna-po-cd"),
        pytest.param("cd /srv/far && rm -f 'logi/*'", id="gwiazdka-w-apostrofach"),
        pytest.param("cd /srv/far && rm -rf logi*", id="gwiazdka-bez-ukosnika"),
        pytest.param("cd /srv/far && rm -f ~/far/logi/* $D/*", id="gwiazdka-od-domu-i-zmiennej"),
        pytest.param("V=/srv/far; for w in a b; do rm -f ${V:?}/${w:?}-x; done", id="zmienne-z-pytajnikiem"),
        pytest.param("V=/srv/far; for w in a b; do rm -f $V/$x-y; done", id="zmienna-spoza-petli"),
        pytest.param('echo a; rm -f "$(echo /srv/far/x)"', id="rm-bez-r-z-podstawienia"),
        pytest.param("echo a && S=env; $S sh -c 'echo A'; echo rm", id="sh-c-bez-rm"),
        pytest.param("echo $((1 | (2))); rm -f /srv/far/x", id="arytmetyka-z-nawiasem"),
        pytest.param('cd /srv/far && git commit -m "rm -f logi/* przed testem"', id="rm-w-opisie-commitu"),
        pytest.param("cd /srv/far && cat > skrypt.sh <<'EOF'\nrm -f logi/*\nEOF\nsh skrypt.sh", id="rm-w-heredocu"),
        pytest.param("cd /srv/far && cat <<-EOF > s.sh\n\trm -f logi/*\n\tEOF\necho ok", id="rm-w-heredocu-z-tabulatorem"),
        pytest.param("cd /srv/far && echo 'rm -f logi/*' | tee notatka.txt", id="rm-w-napisie"),
        pytest.param("cd /srv/far && ls logi/* | grep -c x", id="gwiazdka-bez-rm"),
    ],
)
def test_bezpieczne_rm_i_rm_w_napisie_przechodza_bez_slowa(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "stdin",
    ["", "nie json", "[]", '["tool_input"]', '{"tool_input": null}', '{"tool_input": {"command": 5}}', '{"tool_name": "Bash"}'],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout) == (0, "")


def _configured_hooks() -> list[dict[str, Any]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    return [hook for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]


def _configured_timeout() -> float:
    (timeout,) = [hook["timeout"] for hook in _configured_hooks() if "usuwanie.py" in hook["command"]]
    return float(timeout)


def test_limit_hooka_w_ustawieniach_opoznia_polecenie_najwyzej_o_10_s() -> None:
    # Claude Code po limicie puszcza polecenie bez oceny, więc limit to najdłuższe opóźnienie każdego Basha.
    assert 0 < _configured_timeout() <= 10


@pytest.mark.parametrize(
    "command",
    [
        # Prototyp hooka z wyrażeniami o kwadratowym czasie liczył 1000 pętli z rm 49 s, a 4000 flag 0,3 s.
        "until x; do " * 40000 + "cd a; rm -f logi/*",
        "x; rm " + "-r " * 40000 + "x",
        "rm x && " + "($a " * 40000,
        "".join(f"for v{index} in a; do rm -f $V/x{index}; done; " for index in range(5000)),
        "for w in a; do :; done; rm " + " ".join(f"$A/$b{index}" for index in range(40000)),
        "rm x; " + "(" * 80000,
        "rm x; " + "${" * 80000,
    ],
    ids=["petle-bez-done", "ogon-flag", "nawiasy-ze-zmienna", "petle-z-rm", "cele-ze-zmiennymi", "nawiasy", "zmienne-bez-}"],
)
def test_hook_ocenia_wejscie_bez_konca_przed_limitem_z_ustawien(command: str) -> None:
    hooked = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=False,
        timeout=_configured_timeout(),
    )

    assert hooked.returncode in (0, 2), hooked.stderr


def _run_configured(project: Path, command: str) -> list[tuple[str, subprocess.CompletedProcess[str]]]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command, "run_in_background": False}})
    environment = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return [
        (
            re.findall(r"hooks/(\w+)\.py", configured["command"])[0],
            subprocess.run(
                configured["command"], shell=True, input=payload, env=environment, capture_output=True, text=True, check=False
            ),
        )
        for configured in _configured_hooks()
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_ustawienia_projektu_wpinaja_hook_obok_hooka_czekania() -> None:
    hooked = _run_configured(ROOT, "cd sub && rm -f logi/*")

    assert [(name, run.returncode, FIX in run.stderr) for name, run in hooked] == [
        ("czekanie", 0, False),
        ("usuwanie", 2, True),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_odmowa_hooka_czekania_dochodzi_bez_slowa_hooka_usuwania() -> None:
    waiting = "until ! pgrep -f pytest; do sleep 5; done"
    alone = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "hooks" / "czekanie.py")],
        input=json.dumps({"tool_input": {"command": waiting}}),
        capture_output=True,
        text=True,
        check=False,
    )

    hooked = _run_configured(ROOT, waiting)

    assert [(name, run.returncode, run.stderr) for name, run in hooked] == [
        ("czekanie", 2, alone.stderr),
        ("usuwanie", 0, ""),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_checkout_bez_skryptu_hooka_nie_blokuje_basha(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _run_configured(tmp_path, "cd sub && rm -f logi/*")

    assert [(name, run.returncode, run.stderr) for name, run in hooked] == [("czekanie", 0, ""), ("usuwanie", 0, "")]


FAKE_CLAUDE = '''#!{python}
"""Atrapa claude: wysyła polecenie z promptu (z ZMIEN zmienione), odmawia poleceń z ODMOWA i śpi na SPI."""
import json, sys, time
if sys.argv[1:] == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
command = sys.argv[-1].split("```\\n", 1)[1].rsplit("\\n```", 1)[0]
if "SPI" in command:
    time.sleep(30)
print("nie json")
print("[1]")
print(json.dumps({{"type": "user", "message": "tekst"}}))
bash = {{"type": "tool_use", "name": "Bash", "input": {{"command": command.replace("ZMIEN", "zmienione")}}}}
print(json.dumps({{"type": "assistant", "message": {{"content": [bash]}}}}))
print(json.dumps({{"type": "result", "permission_denials": [{{"tool_name": "Bash"}}] if "ODMOWA" in command else []}}))
'''


def _oracle(
    tmp_path: Path, cases: list[dict[str, Any]], *arguments: str, with_claude: bool = True
) -> subprocess.CompletedProcess[str]:
    programs = tmp_path / "bin"
    programs.mkdir()
    if with_claude:
        claude = programs / "claude"
        claude.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
        claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    listed = tmp_path / "przypadki.jsonl"
    listed.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")
    # Piaskownica wyroczni powstaje w ``~/.cache``, więc każdy test ma własny katalog domowy.
    (tmp_path / "dom").mkdir()
    return subprocess.run(
        [sys.executable, str(ORACLE), "--przypadki", str(listed), *arguments],
        env={**os.environ, "HOME": str(tmp_path / "dom"), "PATH": str(programs)},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_zgodna_z_hookiem_konczy_sie_ok(tmp_path: Path) -> None:
    ran = _oracle(
        tmp_path,
        [
            {"nazwa": "puszcza", "polecenie": "rm -f @FAR@/x", "pyta_o_zgode": False},
            {"nazwa": "pyta", "polecenie": "cd @TFAR@ && rm -f logi/* # ODMOWA", "pyta_o_zgode": True},
            {"nazwa": "zmieniony", "polecenie": "echo ZMIEN", "pyta_o_zgode": False},
            {"nazwa": "nowy", "polecenie": "rm -f @FAR@/z", "pyta_o_zgode": None},
            {"nazwa": "spi", "polecenie": "echo SPI", "pyta_o_zgode": False},
        ],
        "--limit-s",
        "2",
    )

    assert ran.stdout.splitlines() == [
        "Claude Code 9.9.9 (Claude Code), przypadki 5",
        "ZGODNE puszcza | Claude Code puszcza",
        "ZGODNE pyta | Claude Code pyta o zgodę",
        "NIEDOSŁOWNIE zmieniony | Claude Code puszcza",
        "ZGODNE nowy | Claude Code puszcza",
        "NIEDOSŁOWNIE spi | Claude Code puszcza",
        "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | NIEDOSŁOWNIE 2, ZGODNE 3",
    ], ran.stderr
    assert ran.returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_z_nowym_ksztaltem_albo_zmiana_claude_code_konczy_sie_rozjazdem(tmp_path: Path) -> None:
    ran = _oracle(
        tmp_path,
        [
            {"nazwa": "nowy-ksztalt", "polecenie": "rm -f @FAR@/x # ODMOWA", "pyta_o_zgode": True},
            {"nazwa": "zmiana", "polecenie": "rm -f @FAR@/y", "pyta_o_zgode": True},
        ],
    )

    assert ran.stdout.splitlines()[1:] == [
        "ROZJAZD nowy-ksztalt | Claude Code pyta o zgodę",
        "ZMIANA zmiana | Claude Code puszcza",
        "WYROCZNIA ROZJAZD | Claude Code 9.9.9 (Claude Code) | ROZJAZD 1, ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_wybiera_przypadki_z_nazwy_i_usuwa_piaskownice(tmp_path: Path) -> None:
    ran = _oracle(
        tmp_path,
        [
            {"nazwa": "wybrany", "polecenie": "rm -f @FAR@/logi/a", "pyta_o_zgode": False},
            {"nazwa": "pominiety", "polecenie": "rm -f @FAR@/logi/b # ODMOWA", "pyta_o_zgode": True},
        ],
        "wybrany",
    )

    assert ran.stdout.splitlines()[-1] == "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | ZGODNE 1", ran.stderr
    assert list((tmp_path / "dom" / ".cache").iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_bez_claude_na_path_konczy_sie_kodem_2(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, [], with_claude=False)

    assert (ran.returncode, ran.stdout) == (2, "WYROCZNIA BRAK | nie ma claude na PATH\n")
