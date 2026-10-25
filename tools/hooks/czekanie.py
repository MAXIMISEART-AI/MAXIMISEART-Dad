#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca blokujące czekanie na CI i pętle ``pgrep -f``.

Agent na pierwszym planie, który pętli ``until/while/for … sleep`` na ``gh pr checks``, stoi do limitu 600 s
Basha, choć CI i tak powiadamia: wątek główny przez ``watch_pull_request`` T3, a polecenie w tle przez
powiadomienie ``run_in_background``. Pętla ``until ! pgrep -f X`` nigdy się nie kończy, bo ``pgrep -f``
znajduje powłokę, której linia polecenia zawiera tę samą pętlę, a więc i ``X``.

Odrzuca (kod 2, przyczyna na stderr trafia do agenta) tylko polecenie na pierwszym planie:
pętlę z ``sleep``, której ciało pyta o CI albo woła ``pgrep -f``, oraz ``gh pr checks --watch`` i ``gh run watch``.
Pętla ``for`` i ``while read`` czeka tylko z ``break``, ``exit``, ``return`` albo licznikiem prób, a pętla puszczona ``&``
nie czeka.
Wszystko inne, także te polecenia z ``run_in_background``, przechodzi bez słowa (kod 0).
Wejście, którego nie da się odczytać, też przechodzi, bo hook nie może zatrzymać pracy.

Ciała heredoców (skrypt Pythona, treść commitu) i napisy ze spacją w cudzysłowach (opis commitu, wiersz logu)
hook pomija, bo to nie są polecenia powłoki; zostawia z nich ``$(…)`` i ciało ``bash -c '…'``.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sys
from typing import Optional

_GH = r"\bgh(?:-axi)?\s+"
ASKS_CI = re.compile(
    _GH + r"(?:pr\s+(?:checks|view)|run\s+(?:view|list|watch)|api\b[^;&|\n]*(?:check-runs|actions/runs|/status\b))"
)
WATCH = re.compile(_GH + r"(?:pr\s+checks\b[^;&|\n]*--watch|run\s+watch)\b")
PGREP = re.compile(r"\bpgrep\s+(?:-\w+\s+)*-\w*f")
# Agenci śpią też przez `perl -e 'select(undef,undef,undef,N)'`, gdy harness blokuje sam `sleep`.
SLEEP = re.compile(r"(?<![\w.$-])sleep\s+\S|\bselect\(undef\b")
WHITESPACE = re.compile(r"\s")
# W napisie bez spacji (`perl -e 'select(undef,…)'`, wzorzec `rg 'while|until'`) słowo pętli nie stoi na pozycji polecenia.
QUOTED_SEPARATOR = re.compile(r"[;&|{!`]")
# Słowo pętli liczy się na pozycji polecenia, więc „done” w `grep -q done` nie zamyka pętli.
_STARTS = r"(?:^|(?<=[;&|({!`])|(?<=\bdo)|(?<=\bthen)|(?<=\belse))\s*"
_ENDS = r"(?:(?<=[;&\n])|(?<=\bdo))\s*"
LOOP_WORD = re.compile(rf"{_STARTS}(until|while|for)\b|{_ENDS}(done)\b", re.MULTILINE)
# `for` i `while read` z `sleep` to zwykle partia zapytań z limitem API (`for id in …; do sleep 2; gh run view $id`),
# a czekaniem są dopiero z wyjściem z pętli albo licznikiem prób od 0 albo 1 (`$(seq 247 264)` to numery PR).
OVER_LIST = re.compile(r"(?:for|while\s+(?:IFS=\S*\s+)?read)\b")
STOPS = re.compile(r"^for\s*\(\(|\b(?:break|exit|return)\b|\$\(seq\s+(?:[01]\s+)?\d+\s*\)|\{[01]\.\.\d+\}")
# Pętla puszczona `&` (próbnik obok pomiaru, ubijany potem `kill`) nie blokuje polecenia.
IN_BACKGROUND = re.compile(r"\s*\)?(?:\s*\d*[<>]{1,2}&?\s*[^\s;&|]+)*\s*&(?!&)")
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)(\w+)\1")
SHELL_ARGUMENT = re.compile(r"(?:^|\s)-c\s*$")

INSTEAD = (
    "Zamiast czekać: dziecko delegate_task kończy zadanie i zwraca URL PR i pełny SHA HEAD (rodzic ma "
    "watch_pull_request i scal_pr.py, który sam sprawdza CI na HEAD). Wątek główny wywołuje watch_pull_request "
    "i kończy turę, a T3 budzi go po końcu CI, albo uruchamia to samo polecenie z run_in_background: true "
    "i dostaje powiadomienie o jego końcu."
)


@dataclass(frozen=True)
class Refusal:
    reason: str


CI_LOOP = Refusal(f"Odmowa: pętla z sleep na pierwszym planie czeka na CI. {INSTEAD}")
WATCHING = Refusal(f"Odmowa: gh pr checks --watch i gh run watch blokują na pierwszym planie. {INSTEAD}")
PGREP_LOOP = Refusal(
    "Odmowa: pętla z sleep na pgrep -f nie kończy się, bo pgrep -f znajduje własną powłokę tej pętli. "
    "Na własny proces uruchom go Bashem z run_in_background: true i czekaj na powiadomienie o jego końcu, "
    "a na proces ze znanym PID sprawdzaj kill -0 $PID, nie pgrep."
)


def _without_heredocs(command: str) -> str:
    kept: list[str] = []
    delimiter: Optional[str] = None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        opened = HEREDOC.search(line)
        if opened:
            delimiter = opened.group(2)
    return "\n".join(kept)


def _code(command: str, start: int = 0, inside_substitution: bool = False) -> tuple[str, int]:
    """Polecenie bez tekstu w cudzysłowach, ale z ``$(…)`` w nich i z ciałem ``bash -c '…'``.

    Proza w argumentach (opis commitu, wiersz logu, wzorzec ``sed``) nie jest poleceniem, nawet gdy cytuje pętlę.
    Zwraca też indeks za ``)``, która zamyka ``$(`` przy ``inside_substitution``.
    """

    kept: list[str] = []
    depth, index = 0, start
    while index < len(command):
        char = command[index]
        if char == "\\":
            kept.append(command[index : index + 2])
            index += 2
            continue
        if char in "'\"":
            literal, end = _quoted(command, index)
            shell_argument = SHELL_ARGUMENT.search("".join(kept[-12:]))
            kept.append(";" + command[index + 1 : end] if shell_argument else literal)
            index = end
            continue
        if inside_substitution and char == ")":
            if depth == 0:
                return "".join(kept), index + 1
            depth -= 1
        elif char == "(":
            depth += 1
        kept.append(char)
        index += 1
    return "".join(kept), index


def _quoted(command: str, start: int) -> tuple[str, int]:
    """Napis w cudzysłowie od ``start`` i indeks za nim; z napisu ze spacją (proza) zostają tylko ``$(…)`` w ``"…"``."""

    if command[start] == "'":
        close = command.find("'", start + 1)
        end, kept = (len(command) if close < 0 else close + 1), "''"
    else:
        parts, index = ['"'], start + 1
        while index < len(command):
            char = command[index]
            if char == "\\":
                index += 2
            elif char == '"':
                break
            elif command.startswith("$(", index):
                substitution, index = _code(command, index + 2, inside_substitution=True)
                parts.append(f" $({substitution}) ")
            else:
                index += 1
        end, kept = index + 1, "".join(parts) + '"'
    literal = command[start:end]
    return (kept if WHITESPACE.search(literal) else QUOTED_SEPARATOR.sub("_", literal)), end


def _loop_bodies(command: str) -> list[str]:
    """Tekst każdej pętli na pierwszym planie od słowa ``until``/``while``/``for`` do jej ``done`` (albo do końca polecenia)."""

    words = list(LOOP_WORD.finditer(command))
    bodies = []
    for index, start in enumerate(words):
        if start.group(2):
            continue
        depth, end = 0, len(command)
        for word in words[index:]:
            depth += -1 if word.group(2) else 1
            if depth == 0:
                end = word.end()
                break
        if not IN_BACKGROUND.match(command, end):
            bodies.append(command[start.start(1) : end])
    return bodies


def judge(command: str, in_background: bool) -> Optional[Refusal]:
    if in_background:
        return None
    shell, _ = _code(_without_heredocs(command))
    if WATCH.search(shell):
        return WATCHING
    for body in _loop_bodies(shell):
        if not SLEEP.search(body) or (OVER_LIST.match(body) and not STOPS.search(body)):
            continue
        if ASKS_CI.search(body):
            return CI_LOOP
        if PGREP.search(body):
            return PGREP_LOOP
    return None


def main() -> int:
    try:
        tool_input = json.load(sys.stdin)["tool_input"]
        command = tool_input["command"]
        in_background = tool_input.get("run_in_background") is True
    except (ValueError, KeyError, TypeError, AttributeError):
        return 0
    if not isinstance(command, str):
        return 0
    refusal = judge(command, in_background)
    if refusal is None:
        return 0
    print(refusal.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
