"""Hook ``tools/hooks/usuwanie.py``: ``rm``, którego Claude Code nie może rozwiązać statycznie, dostaje odmowę.

Polecenia z historii (``tests/fixtures/usuwanie_historia.jsonl``) to prawdziwe wywołania Basha agentów z 22–26.10.2026,
z ``/Users/Max`` skróconym do ``/Users/x``: 10, które czekały na zgodę (do 104 min), i próbka tych, które przeszły bez
niej, z werdyktem hooka w polu ``odmowa_hooka``, bo reguła hooka jest szersza niż kontrola Claude Code.
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
TEXT_FIX = "To rm stoi w tekście w cudzysłowie albo w heredocu, który Claude Code też sprawdza"
WRITE = "narzędziem Write albo Edit"
GUARDED = "${VAR:?}"
# Przypadki wyroczni, które hook odrzuca, choć Claude Code je puszcza: reguła jest szersza niż kontrola Claude Code.
BROADER = frozenset(
    {
        # Argument rm z globem w poleceniu złożonym.
        "abs-glob", "tilde-glob", "cwd-glob-nomatch", "abs-cd-glob-andand-chain", "abs-cd-glob-dir-star",
        "glob-no-cd-relative-match",
        # Argument rm ze zmiennej bez dosłownej wartości albo z $(…).
        "var-unassigned", "var-from-subst", "subst-target-f", "mktemp-var", "var-loop-midcomponent",
        "subst-in-loop-list-rm-var", "pid-var", "loop-literal-no-v", "loop-var-bare-after-cd", "fn-sam-pozycyjny",
        "g-subst-force", "var-cmd-sh-c-subst-bg",
        # Nazwa polecenia ze zmiennej obok rm.
        "var-command-name", "var-command-sh-c", "var-command-sh-c-rm-var", "rm-tilde-then-var-cmd-sh-c",
        "shc-a-var-rm-var-cmd-dashdash", "shc-d-var-cmd-semicolon", "abl33-a2-var-unknown-wrapper", "abl33-a3-one-line",
        "exp-e1-export-var-cmd-sh-c", "abl33-b1-no-sed",
        # Tekst w heredocu czytany jak polecenie.
        "t-python-heredoc-petla", "t-cat-heredoc-petla", "t-python-heredoc-ansi-c", "t-cat-heredoc-ansi-c",
    }
)


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _placed(command: str) -> str:
    return command.replace("@WS@", "/srv/ws").replace("@FAR@", "/srv/far").replace("@TFAR@", "~/far")


HISTORY_ROWS = _rows(HISTORY)
STALLED = [row for row in HISTORY_ROWS if row["pyta_o_zgode"]]
RAN = [row for row in HISTORY_ROWS if not row["pyta_o_zgode"]]
ORACLE_ROWS = _rows(CASES)


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("usuwanie", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configured_hooks() -> list[dict[str, Any]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    return [hook for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]


def _configured_timeout() -> float:
    (timeout,) = [hook["timeout"] for hook in _configured_hooks() if "usuwanie.py" in hook["command"]]
    return float(timeout)


def _hook(stdin: str) -> subprocess.CompletedProcess[str]:
    # Claude Code po limicie z ustawień puszcza polecenie bez oceny, więc hook, który go przekracza, nie działa.
    return subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False, timeout=_configured_timeout()
    )


def _bash(command: str) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x"}
    return _hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}))


def test_historia_ma_dziesiec_polecen_ktore_czekaly_na_zgode_i_probke_tych_ktore_przeszly() -> None:
    assert (len(STALLED), len(RAN) >= 100) == (10, True)


@pytest.mark.parametrize("command", [row["polecenie"] for row in STALLED], ids=[row["sesja"] for row in STALLED])
def test_polecenie_ktore_czekalo_na_zgode_dostaje_odmowe_z_poprawka(command: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert FIX in hooked.stderr or TEXT_FIX in hooked.stderr
    assert GUARDED in hooked.stderr


@pytest.mark.parametrize(("command", "refused"), [(row["polecenie"], row["odmowa_hooka"]) for row in RAN])
def test_polecenie_ktore_przeszlo_bez_zgody_ma_werdykt_z_historii(hook: ModuleType, command: str, refused: bool) -> None:
    assert (hook.judge(command) is not None) == refused


def test_hook_odrzuca_najwyzej_co_trzecie_polecenie_z_probki_tych_ktore_przeszly() -> None:
    # Próbka ma po dwa polecenia na zestaw cech rm, więc odrzuca częściej niż historia (0,4% z 49 299 poleceń).
    assert sum(row["odmowa_hooka"] for row in RAN) <= len(RAN) // 3


@pytest.mark.parametrize(
    ("command", "asks", "name"),
    [(_placed(row["polecenie"]), row["pyta_o_zgode"], row["nazwa"]) for row in ORACLE_ROWS],
    ids=[row["nazwa"] for row in ORACLE_ROWS],
)
def test_hook_odrzuca_wszystko_co_claude_code_zatrzymuje_w_wyroczni(
    hook: ModuleType, command: str, asks: bool, name: str
) -> None:
    assert (hook.judge(command) is not None) == (asks or name in BROADER)


def test_kazdy_szerszy_przypadek_jest_w_wyroczni_i_claude_code_go_puszcza() -> None:
    assert BROADER <= {row["nazwa"] for row in ORACLE_ROWS if not row["pyta_o_zgode"]}


def test_wyrocznia_ma_przypadek_z_apostrofami_ktory_claude_code_puszcza() -> None:
    (row,) = [row for row in ORACLE_ROWS if row["nazwa"] == "g-subst-apostrof"]

    assert (row["polecenie"], row["pyta_o_zgode"]) == ("echo a; rm -rf '$(echo @FAR@/logi-x)'", False)


ARGUMENT = "Odmowa: argument rm"
COMMAND = "Odmowa: polecenie"
CLOSE = 'Odmowa: "))"'
TEXT = "tekst"

REFUSED = [
    # Argument rm zależy od wartości z chwili uruchomienia.
    ("zmienna-petli", "V=/srv/far; for w in a b; do rm -f $V/$w-x; done", ARGUMENT),
    ("zmienna-z-pozycyjnego-w-funkcji", "S=/srv/far; mk() { d=$S/$1; rm -rf $d; }; for v in a b; do mk $v; done", ARGUMENT),
    ("zmienna-while-read", "V=/srv/far; printf 'a\\nb\\n' | while read w; do rm -f $V/$w-x; done", ARGUMENT),
    ("zmienna-bez-wartosci", "echo a; rm -f $NIEMA/x", ARGUMENT),
    ("zmienna-w-klamrach-bez-wartosci", "echo a; rm -rf ${D}/x", ARGUMENT),
    ("zmienna-z-domyslna", "D=/srv; rm -rf ${D:-/srv}/x; echo b", ARGUMENT),
    ("zmienna-bez-zamkniecia-klamry", "echo a; rm -rf ${D", ARGUMENT),
    ("cel-bez-flag", "echo a; rm $T/x", ARGUMENT),
    ("flaga-ze-zmiennej", "echo a; rm -$F /srv/far/x", ARGUMENT),
    ("po-dwoch-myslnikach", "echo a; rm -f -- $D/x", ARGUMENT),
    ("glob-gwiazdka-po-cd", "cd /srv/far && rm -f logi/*", ARGUMENT),
    ("glob-pytajnik", "echo a; rm -f /srv/far/log?", ARGUMENT),
    ("glob-nawias", "echo a; rm -f /srv/far/log[12]", ARGUMENT),
    ("glob-w-cudzyslowie", 'echo a; rm -f "/srv/far/logi/*"', ARGUMENT),
    ("podstawienie", 'echo a; rm -rf "$(echo /srv/far/x)"', ARGUMENT),
    ("podstawienie-samo", 'rm -rf "$(echo /srv/far/x)"', ARGUMENT),
    ("odwrotny-apostrof", "echo a; rm --recursive `echo /srv/far/x`", ARGUMENT),
    ("arytmetyka", "echo a; rm -f /srv/far/x$((1 + 1))", ARGUMENT),
    *[(f"parametr-specjalny-{name}", f"echo a; rm -rf /srv/far/x${char}", ARGUMENT) for name, char in [
        ("pozycyjny", "1"), ("wszystkie", "@"), ("liczba", "#"), ("pid", "$"), ("tlo", "!"), ("opcje", "-")]],
    ("przypisanie-z-podstawienia", "D=$(echo /srv/far); rm -f $D/x; echo b", ARGUMENT),
    ("przypisanie-nadpisane-podstawieniem", "D=/srv/far; D=$(pwd); rm -rf $D/x; echo b", ARGUMENT),
    ("przypisanie-dopisane-podstawieniem", "D=/srv; D+=$(pwd); rm -rf $D/x; echo b", ARGUMENT),
    ("przypisanie-tylko-dla-polecenia", "D=/srv/far env; rm -rf $D/x", ARGUMENT),
    ("zmienna-petli-nadpisuje-wartosc", "w=/srv/far; for w in a b; do rm -rf $w; done", ARGUMENT),
    ("zmienna-select-nadpisuje-wartosc", "w=/srv/far; select w in a b; do rm -rf $w; done", ARGUMENT),
    ("petla-arytmetyczna", "for ((i = 0; i < 2; i++)); do rm -rf /srv/far/$i; done", ARGUMENT),
    ("funkcja-ze-slowem-function", "function mk { rm -rf $1; }; mk /srv/far/a", ARGUMENT),
    ("samo-slowo-function", "function\nfor w in a; do rm -rf $D/$w; done", ARGUMENT),
    ("podpowloka", "(rm -rf $T)", ARGUMENT),
    ("podpowloka-w-podstawieniu", 'echo "$( (echo a); rm -rf $T/x )"', ARGUMENT),
    ("rm-ze-sciezka", "echo a; /bin/rm -rf $T", ARGUMENT),
    ("arytmetyka-w-podstawieniu", 'echo "$(echo $((1)); rm -rf $T/x)"', ARGUMENT),
    ("tabulator","echo a;\trm -rf $T/x", ARGUMENT),
    *[(f"przed-rm-{prefix}", f"{prefix} rm -rf $T/x; echo b", ARGUMENT) for prefix in [
        "!", "{", "do", "then", "else", "elif", "if", "while", "until", "time", "sudo", "command", "builtin", "exec",
        "nohup"]],
    # Heredoc kończy się na swoim ograniczniku, a polecenia po nim są poleceniami, a nie tekstem.
    ("po-heredocu", "cat > s.sh <<'EOF'\nx\nEOF\necho a\nfor w in a; do rm -rf $D/$w; done", ARGUMENT),
    ("po-heredocu-z-tabulatorem", "cat <<-EOF > s.sh\n\tx\n\tEOF\nfor w in a; do rm -rf $D/$w; done", ARGUMENT),
    ("heredoc-bez-myslnika-nie-konczy-sie-na-tabulatorze", "cat > s <<EOF\n\tEOF\nfor w in a; do rm -rf $D/$w; done\nEOF", TEXT),
    ("po-heredocu-ze-spacja", "cat > s.sh << 'EOF'\nx\nEOF\nfor w in a; do rm -rf $D/$w; done", ARGUMENT),
    ("drugi-heredoc-w-linii", "cat <<A > a <<B\na\nA\nfor w in a; do rm -rf $D/$w; done\nB\necho b", TEXT),
    ("po-here-string", "cat <<< x\nfor w in a; do rm -rf $D/$w; done", ARGUMENT),
    # Nazwa polecenia ze zmiennej.
    ("polecenie-ze-zmiennej-sh-c", "echo a && rm -r /srv/far/t; S=env\n$S sh -c 'echo A'", COMMAND),
    ("polecenie-ze-zmiennej-z-wartoscia", "S=/bin/echo; $S x; rm -f /srv/far/x", COMMAND),
    ("polecenie-ze-zmiennej-po-rm", "rm -f /srv/far/x; ${S} x", COMMAND),
    ("polecenie-z-podstawienia", "`echo env` x; rm -f /srv/far/x", COMMAND),
    # Podpowłoka zamknięta tuż przed końcem $(…).
    ("podpowloka-przed-koncem-podstawienia", 'X=a; echo "$( [ "$X" = a ] && echo y || (echo n))"; rm -f /srv/far/x', CLOSE),
    # Tekst w cudzysłowie i w heredocu, który Claude Code też czyta.
    ("tekst-w-cudzyslowie", 'echo "V=/f; for w in a b; do rm -f $V/$w-x; done"', TEXT),
    ("tekst-w-heredocu", "python3 - <<'EOF'\nfor c in [\"V=/f; for w in a b; do rm -f $V/$w-x; done\"]:\n    print(c)\nEOF", TEXT),
    ("tekst-w-heredocu-bez-ogranicznika", "cat <<'EOF'\nV=/f; for w in a; do rm -f $V/$w; done", TEXT),
    ("tekst-w-cudzyslowie-z-ukosnikiem", 'echo "for w in a; do rm -f \\"$V/$w\\"; done"', TEXT),
    ("cytat-ansi-c", "printf '%s' $'a\\'b for w in a; do rm -f $V/$w; done'", ARGUMENT),
]

PASSED = [
    ("sam-rm-ze-zmienna", "rm -rf $T"),
    ("sam-rm-z-globem", "rm -f /abs/logi/*"),
    ("sam-rm-z-przekierowaniem-bledow", "rm -rf $T 2>&1"),
    ("sam-rm-z-przekierowaniem-nadpisujacym", "rm -rf $T >| log"),
    ("dosłowna-sciezka", "echo a && rm -f /srv/far/f; echo b"),
    ("dosłowna-sciezka-wzgledna-po-cd", "cd /srv/far && rm -f f; echo b"),
    ("zmienna-z-wartoscia", "D=/srv/far; rm -rf $D/x; echo b"),
    ("zmienna-z-wartoscia-w-klamrach", "D=/srv/far; rm -rf ${D}/x; echo b"),
    ("zmienna-z-wartoscia-dopisana", "D=/srv; D+=/far; rm -rf $D/x; echo b"),
    ("zmienna-ze-zmiennej-z-wartoscia", "S=/srv/far; d=$S/a; rm -rf $d; echo ok"),
    ("zmienne-z-pytajnikiem", "V=/srv/far; for w in a b; do rm -f ${V:?}/${w:?}-x; done"),
    ("zmienna-z-pytajnikiem-i-komunikatem", "for w in a; do rm -f /srv/${w:?brak}; done"),
    ("dolar-na-koncu", "echo a; rm -f /srv/far/x$"),
    ("apostrofy", "echo a; rm -rf '$(echo /srv/far/logi-x)'"),
    ("gwiazdka-w-apostrofach", "cd /srv/far && rm -f 'logi/*'"),
    ("apostrof-bez-zamkniecia", "echo a; rm -f '/srv/far/x"),
    ("ukosnik-przed-dolarem", "echo a; rm -f /srv/far/\\$x"),
    ("ukosnik-przed-gwiazdka", "cd /srv && rm -f logi/\\*"),
    ("przekierowanie-do-zmiennej", "echo a; rm -f /srv/far/x > $LOG"),
    ("komentarz", "echo a # x; rm -rf $T/x"),
    ("komentarz-na-koncu", "echo a; rm -f /srv/far/x # koniec"),
    ("arytmetyka-z-nawiasem", "echo $((1 | (2))); rm -f /srv/far/x"),
    ("arytmetyka-w-podstawieniu", 'echo "$( ((1)))"; rm -f /srv/far/x'),
    ("podpowloka-w-podpowloce-przed-koncem", 'echo "$( ( (echo n)) )"; rm -f /srv/far/x'),
    ("podpowloki-zagniezdzone-poza-podstawieniem", "(cd /srv && (ls)); rm -f /srv/far/x"),
    ("podpowloka-przed-koncem-bez-rm",'X=a; echo "$( [ "$X" = a ] && echo y || (echo n))"; echo b'),
    ("rm-innego-polecenia", "echo a; git rm -f $f"),
    ("sh-c-bez-rm", "echo a && S=env; $S sh -c 'echo A'; echo rm"),
    ("gwiazdka-bez-rm", "cd /srv/far && ls logi/* | grep -c x"),
    ("tekst-w-apostrofach", "echo 'V=/f; for w in a b; do rm -f $V/$w-x; done'"),
    ("tekst-w-cudzyslowie-proste-rm", 'echo a; echo "rm -rf $D/x" > n.txt'),
    ("rm-w-opisie-commitu", 'cd /srv/far && git commit -m "rm -f logi/* przed testem"'),
    ("heredoc-z-dosłownym-rm", "cd /srv/far && cat > skrypt.sh <<'EOF'\nrm -f logi/a\nEOF\nsh skrypt.sh"),
    ("heredoc-z-prostym-rm-ze-zmienna", "python3 - <<'EOF'\nprint(\"rm -rf $T\")\nEOF"),
]


@pytest.mark.parametrize(("command", "kind"), [case[1:] for case in REFUSED], ids=[case[0] for case in REFUSED])
def test_rm_ktorego_nie_da_sie_rozwiazac_statycznie_dostaje_odmowe_z_przyczyna_i_poprawka(command: str, kind: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert GUARDED in hooked.stderr
    if kind == TEXT:
        assert (hooked.stderr.startswith(ARGUMENT), TEXT_FIX in hooked.stderr, WRITE in hooked.stderr) == (True, True, True)
    else:
        assert (hooked.stderr.startswith(kind), FIX in hooked.stderr, TEXT_FIX in hooked.stderr) == (True, True, False)


@pytest.mark.parametrize("command", [case[1] for case in PASSED], ids=[case[0] for case in PASSED])
def test_rm_rozwiazany_statycznie_i_rm_w_tekscie_przechodza_bez_slowa(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def test_odmowa_nazywa_argument_i_mowi_dlaczego(hook: ModuleType) -> None:
    refusal = hook.judge("V=/srv/far; for w in a b; do rm -f $V/$w-x; done")

    assert refusal.message.startswith("Odmowa: argument rm $V/$w-x zależy od wartości z chwili uruchomienia")
    assert "agent w tle czekałby na nią bez końca" in refusal.message


@pytest.mark.parametrize(
    "stdin",
    ["", "nie json", "[]", '["tool_input"]', '{"tool_input": null}', '{"tool_input": {"command": 5}}', '{"tool_name": "Bash"}'],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout) == (0, "")


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
        "rm x; " + "$(" * 80000,
        "rm x; " + '"$(echo "' * 2000,
    ],
    ids=[
        "petle-bez-done", "ogon-flag", "nawiasy-ze-zmienna", "petle-z-rm", "cele-ze-zmiennymi", "nawiasy", "zmienne-bez-}",
        "zagniezdzone-podstawienia", "zagniezdzone-napisy",
    ],
)
def test_hook_ocenia_wejscie_bez_konca_przed_limitem_z_ustawien(command: str) -> None:
    hooked = _bash(command)

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
"""Atrapa claude: zapisuje argumenty, wysyła polecenie z promptu (z ZMIEN zmienione, z DWA i drugim poleceniem),
odmawia poleceń z ODMOWA i śpi na SPI."""
import json, os, sys, time
if sys.argv[1:] == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
with open(os.environ["ATRAPA_ARGUMENTY"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
command = sys.argv[-1].split("```\\n", 1)[1].rsplit("\\n```", 1)[0]
if "SPI" in command:
    time.sleep(30)
print("nie json")
print("[1]")
print(json.dumps({{"type": "user", "message": "tekst"}}))
bash = {{"type": "tool_use", "name": "Bash", "input": {{"command": command.replace("ZMIEN", "zmienione")}}}}
print(json.dumps({{"type": "assistant", "message": {{"content": [bash]}}}}))
if "DWA" in command:
    second = {{"type": "tool_use", "name": "Bash", "input": {{"command": "echo drugie"}}}}
    print(json.dumps({{"type": "assistant", "message": {{"content": [second]}}}}))
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
        env={
            **os.environ,
            "HOME": str(tmp_path / "dom"),
            "PATH": str(programs),
            "ATRAPA_ARGUMENTY": str(tmp_path / "argumenty.jsonl"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _claude_calls(tmp_path: Path) -> list[list[str]]:
    return _rows(tmp_path / "argumenty.jsonl")  # type: ignore[return-value]


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_zgodna_z_hookiem_konczy_sie_ok(tmp_path: Path) -> None:
    ran = _oracle(
        tmp_path,
        [
            {"nazwa": "puszcza", "polecenie": "rm -f @FAR@/x", "pyta_o_zgode": False},
            {"nazwa": "pyta", "polecenie": "cd @TFAR@ && rm -f logi/* # ODMOWA", "pyta_o_zgode": True},
            {"nazwa": "szerszy", "polecenie": "echo a; rm -f @FAR@/logi/*", "pyta_o_zgode": False},
            {"nazwa": "zmieniony", "polecenie": "echo ZMIEN", "pyta_o_zgode": False},
            {"nazwa": "nowy", "polecenie": "rm -f @FAR@/z", "pyta_o_zgode": None},
            {"nazwa": "spi", "polecenie": "echo SPI", "pyta_o_zgode": False},
        ],
        "--limit-s",
        "2",
    )

    assert ran.stdout.splitlines() == [
        "Claude Code 9.9.9 (Claude Code), przypadki 6",
        "ZGODNE puszcza | Claude Code puszcza",
        "ZGODNE pyta | Claude Code pyta o zgodę",
        "SZERSZY szerszy | Claude Code puszcza",
        "NIEDOSŁOWNIE zmieniony | Claude Code puszcza",
        "ZGODNE nowy | Claude Code puszcza",
        "NIEDOSŁOWNIE spi | Claude Code puszcza",
        "WYROCZNIA OK | Claude Code 9.9.9 (Claude Code) | NIEDOSŁOWNIE 2, SZERSZY 1, ZGODNE 3",
    ], ran.stderr
    assert ran.returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_z_poleceniem_ktore_hook_puszcza_a_claude_code_zatrzymuje_konczy_sie_rozjazdem(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, [{"nazwa": "nowy-ksztalt", "polecenie": "rm -f @FAR@/x # ODMOWA", "pyta_o_zgode": True}])

    assert ran.stdout.splitlines()[1:] == [
        "ROZJAZD nowy-ksztalt | Claude Code pyta o zgodę",
        "WYROCZNIA ROZJAZD | Claude Code 9.9.9 (Claude Code) | ROZJAZD 1",
    ], ran.stderr
    assert ran.returncode == 1


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_ze_zmiana_odpowiedzi_claude_code_konczy_sie_rozjazdem(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, [{"nazwa": "zmiana", "polecenie": "rm -f @FAR@/y", "pyta_o_zgode": True}])

    assert ran.stdout.splitlines()[1:] == [
        "ZMIANA zmiana | Claude Code puszcza",
        "WYROCZNIA ROZJAZD | Claude Code 9.9.9 (Claude Code) | ZMIANA 1",
    ], ran.stderr
    assert ran.returncode == 1


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_czyta_pierwsze_polecenie_basha_modelu(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, [{"nazwa": "dwa", "polecenie": "echo DWA", "pyta_o_zgode": False}])

    assert ran.stdout.splitlines()[1] == "ZGODNE dwa | Claude Code puszcza", ran.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="atrapa claude to skrypt z linią #!")
def test_wyrocznia_pyta_claude_code_w_trybie_bypass_z_odrzucana_zgoda_i_sciezka_przez_tylde(tmp_path: Path) -> None:
    ran = _oracle(tmp_path, [{"nazwa": "tylda", "polecenie": "rm -f @TFAR@/x", "pyta_o_zgode": False}])

    ((*options, prompt),) = [call for call in _claude_calls(tmp_path) if call != ["--version"]]
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert re.search(r"\nrm -f ~/\.cache/wyrocznia-usuwania-\w+/far/x\n", prompt), prompt
    assert [options[options.index(flag) + 1] for flag in ("--permission-mode", "--permission-prompts")] == [
        "bypassPermissions",
        "none",
    ]


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
