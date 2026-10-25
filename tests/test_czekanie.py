"""Hook ``tools/hooks/czekanie.py``: agent nie czeka blokująco na CI ani w pętli na ``pgrep -f``.

Polecenia pochodzą z historii agentów z 20–25.10.2026 (``calls.jsonl`` pomiaru czasu narzędzi), skrócone tylko o
``cd`` do worktree i o długie ścieżki. Każdy test uruchamia hook tak jak Claude Code: JSON na stdin, a odmowa to
kod 2 z przyczyną na stderr.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "czekanie.py"
SETTINGS = ROOT / ".claude" / "settings.json"

CI_LOOPS = (
    "until s=$(gh pr checks 234 --json name,bucket 2>/dev/null) && [ -n \"$s\" ] && [ \"$s\" != \"[]\" ] && "
    "jq -e 'all(.bucket!=\"pending\")' <<<\"$s\" >/dev/null; do sleep 60; done; gh pr checks 234",
    'end=$((SECONDS+590)); while [ $SECONDS -lt $end ]; do s=$(gh pr checks 431 2>/dev/null | grep "^Required CI '
    'status" | cut -f2); [ -n "$s" ] && [ "$s" != pending ] && break; sleep 30; done; echo "required=$s"; '
    "gh pr checks 431 2>/dev/null | cut -f1,2 | sort -k2 | grep -v pass",
    "until ! gh pr checks 263 2>/dev/null | grep -q pending; do sleep 30; done; gh pr checks 263 2>&1 | cut -f1,2",
    'for i in $(seq 1 19); do n=$(gh pr checks 384 2>/dev/null | grep -c pending); [ "$n" -eq 0 ] && break; '
    'sleep 30; done; gh pr checks 384 2>&1 | grep -v "\\tpass\\t"',
    'for i in $(seq 1 10); do st=$(gh run view 40060154965 --json status -q .status); echo "$(date +%H:%M) $st"; '
    '[ "$st" = completed ] && break; sleep 28; done; gh pr checks 355 | grep -v pass',
    'until [ "$(gh run view 39959705242 --json status --jq .status 2>/dev/null)" = "completed" ]; do sleep 10; '
    "done; gh run view 39959705242 --json conclusion,headSha",
    "until c=$(gh run list --branch main --commit 5f6bbaa096e364da0c80672e948d90913c886683 --json "
    "status,conclusion --jq '.[0]|\"\\(.status) \\(.conclusion)\"') && [[ $c == completed* ]]; do sleep 30; done; "
    'echo "$c"',
    "until s=$(gh pr view 225 --json mergeable -q .mergeable); [ \"$s\" != \"UNKNOWN\" ] && "
    '[ "$s" != "CONFLICTING" ]; do sleep 15; done; gh pr view 225 --json mergeable,mergeStateStatus',
    'until [ "$(gh pr view 307 --json state --jq .state)" != "OPEN" ]; do sleep 30; done; '
    "gh pr view 307 --json state,mergedAt --jq '[.state,.mergedAt]|@tsv'",
    "for i in $(seq 1 56); do s=$(gh api repos/MAXIMISEART-AI/MAXIMISEART-Dad/commits/"
    "66f3e0301f6d6f965733d0e1c46baeb90d25c7b3/status --jq '.statuses[] | select(.context==\"Required CI status\") | "
    '.state\' 2>/dev/null | head -1); [ "$s" = success -o "$s" = failure ] && break; sleep 10; done',
    "perl -e 'alarm 570; exec @ARGV' bash -c 'until [ \"$(gh pr view 307 --json state --jq .state 2>/dev/null)\" = "
    '"MERGED" ]; do perl -e "select(undef,undef,undef,30)"; done\'; gh pr view 307 --json state,mergeCommit',
    'L=~/.claude/plugins/cache/pstack/skills/show-me-your-work/scripts/log.sh; $L wiersze.tsv ci "CI pytest/E2E '
    '3.11 czerwone" "Fix Root Causes" "run 39805093290" "push 087c55c, CI LOKALNIE OK"; sleep 30; '
    "until ! gh pr checks 282 2>/dev/null | grep -q pending; do sleep 30; done; gh pr checks 282 | cat",
    # Prawdziwe pętle z jednym zmienionym słowem: sen przez perl jak w pętlach na log i ``done`` jako argument.
    'for i in $(seq 1 19); do n=$(gh pr checks 384 2>/dev/null | grep -c pending); [ "$n" -eq 0 ] && break; '
    "perl -e 'select(undef,undef,undef,30)'; done",
    "until grep -q done $F && ! gh pr checks 282 2>/dev/null | grep -q pending; do sleep 30; done; "
    "gh pr checks 282 2>&1 | cat",
)
WATCHES = (
    "timeout 1500 gh pr checks 215 --watch > .audit/swarm-215/lane1-pr-checks.txt 2>&1; echo exit=$?",
    "timeout 540 gh pr checks 330 --watch --interval 60 2>&1 | tail -15; echo \"exit ${pipestatus[1]}\"",
    "timeout 580 gh run watch 40098178470 --exit-status > /dev/null 2>&1; echo rc=$?; "
    'gh pr checks 384 2>&1 | grep -v "pass" | head',
    "gh run watch 39930673572 --interval 30 --exit-status > /dev/null 2>&1; echo exit=$?; date -u +%T",
)
PGREP_LOOPS = (
    'until ! pgrep -f "tools/mutacje.py --plik ~/.t3/notes/arch-2026-10-24/K7/mutacje.json" >/dev/null; '
    "do sleep 20; done; tail -30 ~/.t3/notes/arch-2026-10-24/K7/mutacje.log",
    'until ! pgrep -f "mutacje-r2.json" >/dev/null; do sleep 20; done; '
    'grep -E "^(WYKRYTA|NIEWYKRYTA|MUTACJE)" ~/.t3/notes/arch-2026-10-24/K7/mutacje-r2.log',
    "until ! pgrep -f bench_k7.py >/dev/null && [ -s ~/.t3/notes/arch-2026-10-24/K7/bench.log ]; do sleep 15; "
    "done; tail -5 ~/.t3/notes/arch-2026-10-24/K7/bench.log | cut -c1-300",
    'until ! pgrep -f "gh pr checks 330" >/dev/null; do sleep 15; done; '
    "gh pr checks 330 --json name,bucket -q '.[] | select(.bucket != \"pass\") | .name'",
    'while pgrep -f "pytest -q$" >/dev/null 2>&1 && ! grep -q "passed\\|failed" .scratch/pytest-serial.txt; '
    "do sleep 15; done; tail -1 .scratch/pytest-serial.txt",
    "for i in $(seq 1 19); do pgrep -f mutacje_zmiany.py >/dev/null || break; sleep 30; done; "
    "tail -4 ~/.t3/notes/425/mutacje_zmiany.log",
)
PASSING = (
    "gh pr checks 405 2>&1 | head -20",
    "gh pr checks 405 2>&1 | awk -F'\\t' '{print $1\": \"$2}'; git status --porcelain; git rev-parse HEAD; "
    "gh pr view 405 --json headRefOid -q .headRefOid",
    "gh run view 40129178560 --log-failed 2>&1 | tail -40",
    'until grep -q "^SZYBKO" ~/.t3/notes/noc-2026-10-24/U5/szybko2.log; do sleep 5; done; '
    "tail -6 ~/.t3/notes/noc-2026-10-24/U5/szybko2.log; git rev-parse HEAD; gh pr checks 356 2>&1 | head -20",
    "until grep -q DONE $f; do sleep 15; done; cat $f; gh pr view 439 --json comments "
    "--jq '.comments[]|.body|split(\"\\n\")[0]'",
    'until grep -q "^exit" .audit/swarm-214/ci_lokalnie.log; do sleep 5; done; tail -8 .audit/swarm-214/ci_lokalnie.log',
    "until grep -c \"exit\" /tmp/bench-204/before_after.log | grep -q '^12$'; do sleep 5; done; "
    "cat /tmp/bench-204/before_after.log",
    "timeout 580 sh -c 'until grep -qE \"^MUTACJE\" ~/.t3/notes/arch-2026-10-24/K7b/mutacje.log; do sleep 10; done'; "
    'grep -E "^MUTACJE" ~/.t3/notes/arch-2026-10-24/K7b/mutacje.log',
    "sleep 20; for p in 326 327; do gh pr view $p --json number,mergeable,mergeStateStatus "
    "--jq '\"\\(.number) \\(.mergeable) \\(.mergeStateStatus)\"'; done",
    "sleep 10; for n in 268 269 270 271 272 273 274 276; do gh issue view $n --json number,state "
    "--jq '\"\\(.number) \\(.state)\"'; done",
    'for p in $(pgrep -f "ci_lokalnie.py --do-pierwszego-bledu"); do echo $p; lsof -a -p $p -d cwd -Fn | tail -1; done',
    "pkill -f 'until ! pgrep -f \"ci_lokalnie.py --kazdy-commit\"'; pkill -f 'until grep -qE \"OK\\$|FAIL\"'; "
    'sleep 1; pgrep -fl "ci_lokalnie" || echo "nothing running"',
    'pgrep -lf "Microsoft Excel" ; echo "pgrep=$?"; uptime; '
    "while [ \"$(uptime | awk -F'load averages: ' '{print int($2)}')\" -gt 16 ]; do sleep 20; done; uptime",
    'pgrep -fl "serve_centrum|pytest" | cut -c1-150',
    "for i in $(seq 1 38); do grep -q \"end head round 1\" wydajnosc/przebieg.log && break; "
    "perl -e 'select(undef,undef,undef,15)'; done; cat wydajnosc/przebieg.log",
    "gh run list --branch main --workflow ci.yml -L 4 --json databaseId,status --jq "
    "'.[]|select(.status==\"completed\")|.databaseId' | head -2 | while read id; do gh run view $id --json "
    "jobs,headSha --jq '.headSha[:7]'; done",
    'bash $L .audit/204.tsv babysit "watching CI with gh pr checks --watch instead of watch-pr" '
    '"watch-pr needs bun, which is not installed" "/tmp/bench-204/checks.log" "open"',
    "sed -i '' 's/CI_STATUS_PLACEHOLDER/SUCCESS (zmierzone: `gh pr view 381 --json statusCheckRollup` po "
    "`gh pr checks --watch`)/' ~/.t3/notes/arch-2026-10-24/K6/RAPORT.md",
    "cat > ~/.t3/notes/uzupelnienie-415/418/r2/czekaj.sh <<'EOF'\n#!/bin/zsh\nH=a6246f973bbff04407eb8e6c26917cd527ca3a9d\n"
    "while true; do\n  r=$(gh pr checks 433 --json name,bucket --jq '.[]|select(.name==\"Required CI status\")|"
    ".bucket')\n  [ \"$r\" != pending ] && break\n  sleep 60\ndone\nEOF\nchmod +x ~/.t3/notes/uzupelnienie-415/418/r2/czekaj.sh",
    "git commit -q -m \"docs(agents): nie pisz until gh pr checks; do sleep 30; done, tylko watch_pull_request\"",
    'git -c user.name=v311 commit -q -m "until ! pgrep -f mutacje; do sleep 5; done wisi"',
)


def _hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False)


def _bash(command: str, in_background: bool = False) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x", "run_in_background": in_background}
    return _hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}))


@pytest.mark.parametrize("command", CI_LOOPS + WATCHES)
def test_czekanie_na_ci_na_pierwszym_planie_dostaje_odmowe_z_droga_przez_powiadomienie(command: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert "pełny SHA" in hooked.stderr
    assert "watch_pull_request" in hooked.stderr
    assert "run_in_background: true" in hooked.stderr


@pytest.mark.parametrize("command", PGREP_LOOPS)
def test_petla_na_pgrep_dostaje_odmowe_z_powiadomieniem_zadania_w_tle(command: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert "pgrep -f znajduje własną powłokę" in hooked.stderr
    assert "run_in_background: true" in hooked.stderr


@pytest.mark.parametrize("command", PASSING)
def test_inne_polecenie_przechodzi_bez_slowa(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize("command", CI_LOOPS + WATCHES + PGREP_LOOPS)
def test_to_samo_czekanie_w_tle_przechodzi(command: str) -> None:
    hooked = _bash(command, in_background=True)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "stdin",
    ["", "nie json", "[]", '{"tool_input": null}', '{"tool_input": {"command": 5}}', '{"tool_name": "Bash"}'],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout) == (0, "")


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_ustawienia_projektu_wpinaja_hook_dla_basha() -> None:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [hook["command"] for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]
    tool_input = {"command": PGREP_LOOPS[0], "run_in_background": False}

    hooked = [
        subprocess.run(
            command,
            shell=True,
            input=json.dumps({"tool_name": "Bash", "tool_input": tool_input}),
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        for command in commands
    ]

    assert [(run.returncode, "pgrep -f" in run.stderr) for run in hooked] == [(2, True)]
