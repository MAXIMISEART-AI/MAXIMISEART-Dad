#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca kształty ``rm``, które Claude Code zatrzymuje na zgodzie człowieka.

Claude Code 2.1.309–2.1.310 w trybie ``bypassPermissions`` puszcza ``rm`` bez pytania, ale kilka kształtów polecenia
zatrzymuje na zgodzie, której udziela tylko człowiek. Agent w tle stoi wtedy bez słowa: 24.10 do 66 min.
Hook odrzuca je kodem 2 z przyczyną na stderr, która nazywa kształt i poprawkę, więc agent od razu poprawia polecenie:

- ``cd`` i potem cel ``rm`` z gołym względnym ``*`` (``cd X && rm -f logi/*``);
- cel ``$VAR/$w…``, gdzie ``w`` to zmienna pętli ``for`` (``for w in a b; do rm -f $V/$w-x; done``);
- podpowłoka zamknięta tuż przed końcem ``$(…)`` (``"$( … || (echo n))"``), którą Claude Code parsuje inaczej niż
  powłoka, w poleceniu z dowolnym ``rm``;
- lista ``&&`` z poleceniem ze zmiennej, które uruchamia skrypt ``sh -c`` (``S=env; $S sh -c '…'``), w poleceniu
  z dowolnym ``rm``;
- ``rm -r`` z celem z podstawienia ``"$(…)"``.

Kształty pochodzą z wyroczni: prawdziwy Claude Code (``claude -p`` w trybie bypass, zgoda odrzucana sama) na
przypadkach z ``tools/wyrocznia_usuwania.jsonl``. Powtórka 43 012 poleceń Basha agentów z 22–25.10.2026 przez ten
hook odrzuca dokładnie 6 poleceń, które czekały na zgodę, i żadnego, które przeszło bez niej.
Wszystko inne przechodzi bez słowa (kod 0), także ``rm`` w napisie w cudzysłowie i w ciele heredoca.
Wejście, którego nie da się odczytać, też przechodzi, bo hook nie może zatrzymać pracy.

Granica: hook naśladuje zachowanie wersji Claude Code, na których biegła wyrocznia (2.1.309–2.1.310), a nie
reguły z jego kodu. Po aktualizacji Claude Code uruchom wyrocznię ponownie (``tools/wyrocznia_usuwania.py``):
rozjazd z hookiem to nowy albo zniknięty kształt, który trzeba dopisać do hooka i do pliku przypadków.
Inne harnessy niż Claude Code (Codex, opencode), ``rm`` w skrypcie uruchomionym z pliku, w ``xargs``,
``find -delete`` i ``eval`` oraz kształty, których wyrocznia nie sprawdziła, łapie tylko przegląd.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sys
from typing import Optional

RM_WORD = re.compile(r"(?:^|[^\w.-])rm(?:dir)?(?![\w.-])")
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
PREFIXES = frozenset({"sudo", "command", "builtin", "nohup", "time", "!", "then", "do", "else"})
# Katalogi przed ``rm`` bez separatorów list, więc start po każdym ``(`` czyta tylko do następnego.
_RM_START = r"(?:^|[;&|(\n]|&&|\|\|)\s*(?:[^\s/;&|()]*/)*rm\s+"
# Flagi jedna po drugiej: ``-\S+\s+`` nie może się podzielić, więc dopasowanie jest liniowe.
SUBSTITUTED_TARGET = re.compile(_RM_START + r"((?:-\S+\s+)+)[\"']?(?:\$\(|`)")
RECURSIVE_FLAG = re.compile(r"--r\S*|-[A-Za-z]*[rR][A-Za-z]*")
LOOP_VARIABLE = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\b")
VARIABLE_THEN_VARIABLE = re.compile(r"\$\{?[A-Za-z_]\w*\}?/\$\{?([A-Za-z_]\w*)")
ARITHMETIC = re.compile(r"\$?\(\((?:[^()]|\([^()]*\))*\)\)")
SUBSHELL_THEN_CLOSE = re.compile(r"(?:\|\||&&|[;|])\s*\([^()]*\)\)")
# Bez ``(`` w środku: start po każdym ``(`` czyta tylko do następnego.
VARIABLE_COMMAND_SHELL_SCRIPT = re.compile(
    r"(?:^|[;&|(\n]|&&|\|\|)\s*\$\{?[A-Za-z_]\w*\}?\s[^;&|\n(]*\b(?:sh|bash|zsh)\s+-\w*c\b"
)
CD = re.compile(r"^cd(?:\s|$)")
BARE_STAR = re.compile(r"(?:^|/)\*$")

WHY = (
    "Claude Code w trybie bypass zatrzymałby to polecenie na zgodzie, której udziela tylko człowiek, "
    "a agent w tle czekałby na nią bez końca."
)
FIX = (
    "Uruchom rm osobnym wywołaniem Basha z dosłowną ścieżką bezwzględną (rm -f /abs/katalog/logi/a.txt, "
    "rm -rf /abs/katalog/logi) albo ze zmienną w postaci ${VAR:?}, a resztę polecenia w następnym wywołaniu. "
    "Worktree usuwa git worktree remove <ścieżka>."
)


@dataclass(frozen=True)
class Refusal:
    shape: str
    reason: str

    @property
    def message(self) -> str:
        return f"Odmowa ({self.shape}): {self.reason} {WHY} {FIX}"


PARSE_DIVERGENCE = Refusal(
    "podpowłoka przed końcem $(…)",
    "podpowłoka zamyka się tuż przed końcem $(…) (\"))\"), co Claude Code parsuje inaczej niż powłoka, "
    "więc nie sprawdzi rm w tym poleceniu.",
)
SUBSTITUTED = Refusal("rm -r z celem z $(…)", "rm -r bierze cel z podstawienia $(…).")
VARIABLE_SHELL_SCRIPT = Refusal(
    "polecenie ze zmiennej z sh -c",
    "lista && i polecenie ze zmiennej, które uruchamia skrypt sh -c, więc Claude Code nie sprawdzi rm w tym poleceniu.",
)


def _without_heredocs(command: str) -> str:
    kept: list[str] = []
    lines = command.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for _, delimiter in HEREDOC.findall(line):
            while index < len(lines) and lines[index].strip() != delimiter:
                index += 1
            index += 1
    return "\n".join(kept)


def _segments(command: str) -> list[str]:
    """Proste polecenia: podział na ``; & | && || ( ) { }`` i nowej linii oraz wokół ciał ``$(…)``, poza cudzysłowami."""

    segments: list[str] = []
    current: list[str] = []
    # Cudzysłów, w którym stało każde otwarte ``$(``: po jego ``)`` napis trwa dalej.
    open_substitutions: list[Optional[str]] = []
    quote: Optional[str] = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            current.append(char)
            if char == "'":
                quote = None
        elif char == "\\" and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 1
        elif command.startswith("$(", index):
            current.append("$(")
            segments.append("".join(current))
            current = []
            open_substitutions.append(quote)
            quote = None
            index += 1
        elif quote == '"':
            current.append(char)
            if char == '"':
                quote = None
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == ")" and open_substitutions:
            segments.append("".join(current))
            current = [")"]
            quote = open_substitutions.pop()
        elif char in ";&|\n(){}":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def _words(segment: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    quote: Optional[str] = None
    index = 0
    while index < len(segment):
        char = segment[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "\\" and index + 1 < len(segment):
            current.append(segment[index : index + 2])
            index += 1
        elif char.isspace():
            if current:
                words.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    if current:
        words.append("".join(current))
    return words


def _rm_targets(segment: str) -> Optional[list[str]]:
    """Cele ``rm``/``rmdir``, gdy proste polecenie je uruchamia, a inaczej ``None``."""

    words = _words(segment)
    start = 0
    while start < len(words) and ASSIGNMENT.match(words[start]):
        start += 1
    while start < len(words) and words[start] in PREFIXES:
        start += 1
    if start == len(words) or words[start].rsplit("/", 1)[-1] not in ("rm", "rmdir"):
        return None
    arguments = words[start + 1 :]
    end = arguments.index("--") if "--" in arguments else len(arguments)
    return [word for word in arguments[:end] if not word.startswith("-")] + arguments[end + 1 :]


def _unquoted(word: str) -> tuple[str, str]:
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"":
        return word[1:-1], word[0]
    return word, ""


def _substituted_recursive_target(command: str) -> bool:
    return any(
        any(RECURSIVE_FLAG.fullmatch(flag) for flag in match.group(1).split())
        for match in SUBSTITUTED_TARGET.finditer(command)
    )


def judge(command: str) -> Optional[Refusal]:
    shell = _without_heredocs(command)
    if not RM_WORD.search(shell):
        return None
    segments = _segments(shell)
    targets: dict[str, list[str]] = {}
    for segment in segments:
        found = _rm_targets(segment)
        if found is not None:
            targets[segment] = found
    if not targets:
        return None
    if "$(" in shell and SUBSHELL_THEN_CLOSE.search(ARITHMETIC.sub("", shell)):
        return PARSE_DIVERGENCE
    if _substituted_recursive_target(shell):
        return SUBSTITUTED
    if "&&" in shell and VARIABLE_COMMAND_SHELL_SCRIPT.search(shell):
        return VARIABLE_SHELL_SCRIPT
    loop_variables = set(LOOP_VARIABLE.findall(shell))
    after_cd = False
    for segment in segments:
        if CD.match(segment):
            after_cd = True
            continue
        for target in targets.get(segment, ()):
            path, quote = _unquoted(target)
            for variable in VARIABLE_THEN_VARIABLE.findall(path):
                if variable in loop_variables:
                    return Refusal(
                        "cel ze zmienną pętli",
                        f"cel rm {target} to $VAR/${variable}…, gdzie {variable} to zmienna pętli for: "
                        "z pustą wartością cel staje się ścieżką od korzenia.",
                    )
            if after_cd and quote != "'" and not path.startswith(("/", "~", "$")) and BARE_STAR.search(path):
                return Refusal(
                    "goły * po cd", f"cel rm {target} to goły względny * po cd, którego Claude Code nie umie rozwiązać."
                )
    return None


def main() -> int:
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError, IndexError):
        return 0
    if not isinstance(command, str):
        return 0
    refusal = judge(command)
    if refusal is None:
        return 0
    print(refusal.message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
