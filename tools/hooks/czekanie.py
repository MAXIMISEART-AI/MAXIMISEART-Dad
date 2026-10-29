#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca blokujące czekanie na CI i pętle ``pgrep -f``.

Agent na pierwszym planie, który pętli ``until/while/for … sleep`` na ``gh pr checks``, stoi do limitu 600 s
Basha, choć CI i tak powiadamia: wątek główny przez ``watch_pull_request`` T3, a polecenie w tle przez
powiadomienie ``run_in_background``. Pętla ``until ! pgrep -f X`` nigdy się nie kończy, bo ``pgrep -f``
znajduje powłokę, której linia polecenia zawiera tę samą pętlę, a więc i ``X`` (z tego samego powodu
``until pgrep -f X`` kończy się od razu).

Odrzuca (kod 2, przyczyna na stderr trafia do agenta) tylko polecenie na pierwszym planie:
pętlę z ``sleep``, której ciało pyta o CI (``gh pr checks``, ``gh pr view``, ``gh run view``/``list``, ``gh api``
o check-runs, actions/runs albo status commitu) albo woła ``pgrep -f``, oraz ``gh pr checks --watch`` i ``gh run watch``.
Pętla ``for`` i ``while read`` czeka tylko z ``break``, ``exit``, ``return`` albo licznikiem prób od 0 albo 1
(``$(seq N)``, ``$(seq 1 N)``, ``{1..N}``, ``for ((``), bo bez nich to partia zapytań z ``sleep`` jako limitem API,
a pętla puszczona ``&`` nie czeka.
Wszystko inne, także te polecenia z ``run_in_background``, przechodzi bez słowa (kod 0).
Wejście, którego nie da się odczytać, też przechodzi, bo hook nie może zatrzymać pracy.

Ciała heredoców (skrypt Pythona, treść commitu) i napisy ze spacją w cudzysłowach (opis commitu, wiersz logu)
hook pomija, bo to nie są polecenia powłoki; zostawia z nich ``$(…)`` i ciało ``bash -c '…'``.

Granica: inne harnessy niż Claude Code (Codex, opencode), pętlę w skrypcie uruchomionym z pliku, w Pythonie
(``time.sleep``) albo z adresem ``gh api`` w cudzysłowie, czekanie na plik wyjścia zadania w tle i pętle, których
wzorca hook nie zna, łapie tylko przegląd.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import json
import re
import sys
from typing import Optional

_GH = r"\bgh(?:-axi)?\s+"
ASKS_CI = re.compile(_GH + r"(?:pr\s+(?:checks|view)|run\s+(?:view|list|watch))")
# `gh api` pyta o CI, gdy w tym samym poleceniu prostym (do `;`, `&`, `|` albo nowej linii) stoi adres CI. Pary szuka
# `_in_one_command`, a nie wzorzec `api\b[^;&|\n]*adres`, bo ten od każdego `gh api` czyta do końca polecenia.
GH_API = re.compile(_GH + r"api\b")
CI_ADDRESS = re.compile(r"check-runs|actions/runs|/status\b")
CHECKS = re.compile(_GH + r"pr\s+checks\b")
WATCH_OPTION = re.compile(r"--watch\b")
RUN_WATCH = re.compile(_GH + r"run\s+watch\b")
SIMPLE_COMMAND_END = re.compile(r"[;&|\n]")
PGREP = re.compile(r"\bpgrep\s+(?:-\w+\s+)*-\w*f")
# Agenci śpią też przez `perl -e 'select(undef,undef,undef,N)'`, gdy harness blokuje sam `sleep`; w napisie bez
# spacji nawias jest już podkreśleniem (`QUOTED_SEPARATOR`).
SLEEP = re.compile(r"(?<![\w.$-])sleep\s+\S|\bselect[(_]undef\b")
WHITESPACE = re.compile(r"\s")
# W napisie bez spacji (`perl -e 'select(undef,…)'`, wzorzec `rg '(while|until)'`) słowo pętli nie stoi na pozycji
# polecenia, a nawias nie otwiera ani nie zamyka grupy.
QUOTED_SEPARATOR = re.compile(r"[;&|(){}!`]")
# Słowo pętli liczy się na pozycji polecenia, więc „done” w `grep -q done` nie zamyka pętli. Za początkiem wiersza
# odstęp bez nowej linii: inaczej od każdego z tysięcy pustych wierszy wzorzec czytałby wszystkie następne.
_STARTS = r"(?:^[^\S\n]*|(?:(?<=[;&|({!`])|(?<=\bdo)|(?<=\bthen)|(?<=\belse))\s*)"
_ENDS = r"(?:(?<=\n)[^\S\n]*|(?:(?<=[;&])|(?<=\bdo))\s*)"
LOOP_WORD = re.compile(rf"{_STARTS}(until|while|for)\b|{_ENDS}(done)\b", re.MULTILINE)
# `for` i `while read` z `sleep` to zwykle partia zapytań z limitem API (`for id in …; do sleep 2; gh run view $id`),
# a czekaniem są dopiero z wyjściem z pętli albo licznikiem prób od 0 albo 1 (`$(seq 247 264)` to numery PR).
OVER_LIST = re.compile(r"(?:for|while\s+(?:IFS=\S*\s+)?read)\b")
FOR_ARITHMETIC = re.compile(r"for\s*\(\(")
STOPS = re.compile(r"\b(?:break|exit|return)\b(?!=)|\$\(seq\s+(?:[01]\s+)?\d+\s*\)|\{[01]\.\.\d+\}")
# Pętla puszczona `&` (próbnik obok pomiaru, ubijany potem `kill`) nie blokuje polecenia, a `&>`, `>&2`, `2>&1`
# i `|&` to przekierowania. `&` puszcza w tło całą listę do `;` albo nowej linii, także z `|` i `||` (`done | tee log &`).
# Bez zagnieżdżonych kwantyfikatorów, bo cofanie po `2>1 2>1 …` nie miałoby końca.
LIST_END = re.compile(r"[;\n]")
LONE_AMPERSAND = re.compile(r"(?<![<>&|])&(?![&>])")
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)(\w+)\1")
# Skrypt powłoki to tylko argument `-c` powłoki: `grep -c '…'` liczy wiersze, a `python3 -c '…'` to Python.
SHELL_ARGUMENT = re.compile(r"(?:^|[\s/;&|(`])(?:ba|da|k|z)?sh\s+-c\s*$")

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
    "Odmowa: pętla z sleep na pgrep -f nie widzi procesu, bo pgrep -f znajduje własną powłokę tej pętli: "
    "until ! pgrep -f X i while pgrep -f X nie kończą się nigdy, a until pgrep -f X kończy się od razu. "
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
            shell_argument = SHELL_ARGUMENT.search("".join(kept[-24:]))
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


class _Matches:
    """Dopasowania wzorca w poleceniu, posortowane, z końcami rosnącymi razem z początkami.

    Pytanie, czy jedno z nich leży całe w pętli, kosztuje bisekcję, a nie przeszukanie ciała pętli: ciała pętli
    zagnieżdżonych albo niezamkniętych razem rosną z kwadratem długości polecenia.
    """

    def __init__(self, spans: Iterable[tuple[int, int]]) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []
        for start, end in spans:
            self.starts.append(start)
            self.ends.append(end)

    def inside(self, start: int, end: int) -> bool:
        index = bisect_left(self.starts, start)
        return index < len(self.starts) and self.ends[index] <= end


def _found(pattern: re.Pattern[str], command: str) -> _Matches:
    return _Matches(match.span() for match in pattern.finditer(command))


def _in_one_command(command: str, head: re.Pattern[str], tail: re.Pattern[str]) -> _Matches:
    """Od ``head`` do pierwszego za nim ``tail``, gdy oba stoją w jednym poleceniu prostym."""

    tails = [match.span() for match in tail.finditer(command)]
    tail_starts = [start for start, _ in tails]
    command_ends = [match.start() for match in SIMPLE_COMMAND_END.finditer(command)]
    spans: list[tuple[int, int]] = []
    for match in head.finditer(command):
        index = bisect_left(tail_starts, match.end())
        if index < len(tails) and tails[index][0] < _first_from(command_ends, match.end(), len(command)):
            spans.append((match.start(), tails[index][1]))
    return _Matches(spans)


def _loop_bodies(command: str) -> Iterator[tuple[int, int]]:
    """Początek i koniec każdej pętli na pierwszym planie od słowa ``until``/``while``/``for`` do jej ``done``
    (albo do końca polecenia)."""

    loops: list[list[int]] = []
    unclosed: list[int] = []
    for word in LOOP_WORD.finditer(command):
        if not word.group(2):
            unclosed.append(len(loops))
            loops.append([word.start(1), len(command)])
        elif unclosed:
            loops[unclosed.pop()][1] = word.end()
    # Pozycje policzone raz: szukanie od każdej pętli osobno kosztuje O(pętle × długość polecenia).
    list_ends = [match.start() for match in LIST_END.finditer(command)]
    ampersands = [match.start() for match in LONE_AMPERSAND.finditer(command)]
    for start, end in loops:
        stop = _first_from(list_ends, end, len(command))
        if _first_from(ampersands, end, stop) >= stop:
            yield start, end


def _first_from(positions: list[int], start: int, default: int) -> int:
    index = bisect_left(positions, start)
    return positions[index] if index < len(positions) else default


def judge(command: str, in_background: bool) -> Optional[Refusal]:
    if in_background:
        return None
    shell, _ = _code(_without_heredocs(command))
    if RUN_WATCH.search(shell) or _in_one_command(shell, CHECKS, WATCH_OPTION).starts:
        return WATCHING
    sleeps, stops, pgreps = _found(SLEEP, shell), _found(STOPS, shell), _found(PGREP, shell)
    queries, api_queries = _found(ASKS_CI, shell), _in_one_command(shell, GH_API, CI_ADDRESS)
    for start, end in _loop_bodies(shell):
        if not sleeps.inside(start, end):
            continue
        over_list = OVER_LIST.match(shell, start, end)
        if over_list and not (FOR_ARITHMETIC.match(shell, start, end) or stops.inside(start, end)):
            continue
        if queries.inside(start, end) or api_queries.inside(start, end):
            return CI_LOOP
        if pgreps.inside(start, end):
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
