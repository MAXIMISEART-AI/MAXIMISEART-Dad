#!/usr/bin/env python3
"""Hook ``PreToolUse`` Claude Code dla Basha: odrzuca ``rm``, którego Claude Code nie może sprawdzić statycznie.

Claude Code 2.1.309–2.1.310 w trybie ``bypassPermissions`` puszcza ``rm`` bez pytania, ale ``rm`` w poleceniu
złożonym, którego skutku nie umie ustalić z samego tekstu, zatrzymuje na zgodzie, której udziela tylko człowiek.
Agent w tle stoi wtedy bez słowa: 24.10 do 66 min, 26.10 do 104 min. Hook odrzuca takie polecenie kodem 2
z przyczyną i poprawką na stderr, więc agent od razu je poprawia. Reguła jest jedna: polecenie złożone (lista
``; && || | &``, nowa linia, pętla, funkcja, podpowłoka, ``$(…)``) z ``rm`` dostaje odmowę, gdy nie da się go
rozwiązać statycznie:

- argument ``rm`` zależy od wartości z chwili uruchomienia: ma `` ` ``, ``$(…)``, ``$((…))``, glob ``* ? [``
  poza apostrofami albo zmienną, której polecenie wcześniej nie nadało dosłownej wartości (``D=/abs; rm -rf $D/x``
  przechodzi, a ``for w in a; do rm -rf $D/$w; done`` i ``mk() { rm -rf $D/$1; }`` nie); ``${VAR:?}`` jest
  rozwiązany, bo pusta wartość przerywa polecenie;
- nazwa któregoś polecenia ma ``$`` albo `` ` `` (``$S sh -c …``), więc nie wiadomo, co uruchomi;
- ``))`` zamyka podpowłokę i ``$(…)`` naraz (``"$( a || (echo n))"``), co parser Claude Code czyta jak koniec
  arytmetyki, więc nie widzi, gdzie stoi ``rm``.

Tę samą regułę hook stosuje do tekstu w cudzysłowie i w ciele heredoca, czytanego jak polecenie, bo Claude Code
też go czyta: ``echo "for w in a; do rm -f $V/$w; done"`` czeka na zgodę, a ``python3 - <<'EOF'`` z takim
napisem czekał 26.10 104 min. Odmowa radzi wtedy zapisać plik narzędziem Write albo Edit. Tekst w apostrofach to
dosłowny tekst, a nie polecenie, więc ``echo a; rm -rf '$(echo x)'`` przechodzi.

Reguła jest szersza niż kontrola Claude Code, która rozstrzyga kształt po kształcie: zatrzymuje na przykład
``cd X && rm -f logi/*``, a ``echo a; rm -f /abs/logi/*`` puszcza, choć hook odrzuca oba. Hook nie naśladuje
tych kształtów, bo lista kształtów odtworzona z wyroczni nie uogólnia się na nowe polecenia (25.10 przeoczyła
``mk() { d=$S/$1; rm -rf $d; }``, na którym agent czekał 4 min). Odmowa zbędna wobec Claude Code kosztuje agenta
jedno poprawione polecenie, a przeoczenie stoi do powrotu człowieka. Wejście, którego nie da się odczytać, też
przechodzi, bo hook nie może zatrzymać pracy.

Granica: zgodność z Claude Code sprawdza wyrocznia (``tools/wyrocznia_usuwania.py``) na przypadkach z
``tools/wyrocznia_usuwania.jsonl``. Po aktualizacji Claude Code uruchom ją ponownie: ``ROZJAZD`` to polecenie,
które Claude Code zatrzymuje, a hook puszcza. Inne harnessy niż Claude Code (Codex, opencode), ``rm`` w skrypcie
uruchomionym z pliku, w ``xargs``, ``find -delete`` i ``eval`` łapie tylko przegląd.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sys
from typing import Optional

GUARDED = re.compile(r"\$\{[A-Za-z_]\w*:\?[^}]*\}")
BRACED = re.compile(r"\$\{([A-Za-z_]\w*)\}")
NAME = re.compile(r"[A-Za-z_]\w*|[0-9@#$!-]")
ASSIGNMENT = re.compile(r"([A-Za-z_]\w*)\+?=")
# Słowa przed nazwą polecenia: słowa kluczowe Basha i polecenia, które uruchamiają swoje argumenty.
PREFIXES = frozenset(
    {"!", "{", "do", "then", "else", "elif", "if", "while", "until", "time", "sudo", "command", "builtin", "exec", "nohup"}
)

WHY = (
    "Claude Code w trybie bypass zatrzymuje rm, którego nie umie rozwiązać statycznie, na zgodzie, "
    "której udziela tylko człowiek, a agent w tle czekałby na nią bez końca."
)
FIX = (
    "Uruchom rm osobnym wywołaniem Basha z dosłowną ścieżką bezwzględną (rm -f /abs/katalog/logi/a.txt, "
    "rm -rf /abs/katalog/logi) albo ze zmienną w postaci ${VAR:?}, a resztę polecenia w następnym wywołaniu. "
    "Worktree usuwa git worktree remove <ścieżka>."
)
TEXT_FIX = (
    "To rm stoi w tekście w cudzysłowie albo w heredocu, który Claude Code też sprawdza: kod albo dane z rm zapisz "
    "do pliku narzędziem Write albo Edit i uruchom ten plik, a w poleceniu Basha rozwiąż ścieżkę (dosłowna ścieżka "
    "albo ${VAR:?})."
)


@dataclass
class Word:
    text: str = ""
    # Wartość zależy od chwili uruchomienia: glob albo rozwinięcie bez dosłownej wartości.
    dynamic: bool = False
    # Ma ``$`` albo `` ` ``, także zmienną z dosłowną wartością.
    expanded: bool = False


@dataclass(frozen=True)
class Refusal:
    reason: str
    fix: str = FIX

    @property
    def message(self) -> str:
        return f"Odmowa: {self.reason} {WHY} {self.fix}"


class _Reader:
    """Czyta tekst polecenia znak po znaku: cudzysłowy, rozwinięcia ``$``, podstawienia, przekierowania i heredoki."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.at = 0
        self.commands: list[list[Word]] = []
        self.subshell = False
        self.ambiguous_close = False
        # Tekst w cudzysłowie i ciała heredoców, które Claude Code też czyta jak polecenie.
        self.texts: list[str] = []
        # Zmienne, którym polecenie nadało już dosłowną wartość.
        self.known: set[str] = set()
        self.heredocs: list[tuple[str, bool]] = []

    def peek(self) -> str:
        return self.text[self.at : self.at + 1]

    def commands_until(self, stop: str) -> None:
        """Polecenia do ``stop`` (``)`` po ``$(``, `` ` ``) poza cudzysłowem albo do końca tekstu."""

        words: list[Word] = []
        subshells = 0
        redirected = False
        while self.at < len(self.text):
            char = self.text[self.at]
            if char == stop and not subshells:
                self.at += 1
                break
            if char in " \t":
                self.at += 1
            elif char == "#":
                newline = self.text.find("\n", self.at)
                self.at = len(self.text) if newline < 0 else newline
            elif char in "<>":
                redirected = self.redirection()
            elif char not in "\n;&|()":
                word = self.word()
                if not redirected:
                    words.append(word)
                redirected = False
            else:
                self.end(words)
                words, redirected = [], False
                self.at += 1
                if char == "\n":
                    self.heredoc_bodies()
                elif char == "(" and self.peek() == "(":
                    self.at = self.arithmetic(self.at + 1)
                elif char == "(":
                    self.subshell = True
                    subshells += 1
                elif char == ")" and subshells:
                    subshells -= 1
                    if not subshells and self.peek() == ")":
                        self.ambiguous_close = True
        self.end(words)

    def end(self, words: list[Word]) -> None:
        # Słowo kończące pętlę albo grupę (``done``, ``fi``, ``}``) zostaje osobnym poleceniem, więc pętla, funkcja
        # i grupa są złożone tak jak lista.
        start = 0
        while start < len(words):
            if words[start].text == "function":
                start += 2
            elif words[start].text in PREFIXES or ASSIGNMENT.match(words[start].text):
                start += 1
            else:
                break
        if start >= len(words):
            # Same przypisania nadają wartość do końca polecenia, a przypisanie przed poleceniem tylko jemu.
            for word in words:
                assigned = ASSIGNMENT.match(word.text)
                if assigned and word.dynamic:
                    self.known.discard(assigned.group(1))
                elif assigned:
                    self.known.add(assigned.group(1))
        elif words[start].text in ("for", "select") and start + 1 < len(words):
            self.known.discard(words[start + 1].text)
        else:
            self.commands.append(words[start:])

    def redirection(self) -> bool:
        """Operator przekierowania; ``True``, gdy następne słowo to jego cel, a nie argument polecenia."""

        if self.text.startswith("<<", self.at) and not self.text.startswith("<<<", self.at):
            self.at += 2
            strip = self.peek() == "-"
            self.at += strip
            while self.peek() in (" ", "\t"):
                self.at += 1
            self.heredocs.append((self.word().text, strip))
            return False
        while self.peek() in ("<", ">", "&", "|"):
            self.at += 1
        return True

    def heredoc_bodies(self) -> None:
        for delimiter, strip in self.heredocs:
            body: list[str] = []
            while self.at < len(self.text):
                newline = self.text.find("\n", self.at)
                end = len(self.text) if newline < 0 else newline
                line = self.text[self.at : end]
                self.at = end + 1
                if (line.lstrip("\t") if strip else line) == delimiter:
                    break
                body.append(line)
            self.texts.append("\n".join(body))
        self.heredocs = []

    def word(self) -> Word:
        word = Word()
        parts: list[str] = []
        while self.at < len(self.text):
            char = self.text[self.at]
            if char in " \t\n;&|()<>":
                break
            if char == "'":
                close = self.text.find("'", self.at + 1)
                end = len(self.text) if close < 0 else close
                parts.append(self.text[self.at + 1 : end])
                self.at = end + 1
            elif char == '"':
                self.at += 1
                start = len(parts)
                while self.at < len(self.text) and self.text[self.at] != '"':
                    self.part(word, parts, self.text[self.at])
                self.at += 1
                self.texts.append("".join(parts[start:]))
            else:
                self.part(word, parts, char)
        word.text = "".join(parts)
        return word

    def part(self, word: Word, parts: list[str], char: str) -> None:
        """Jeden znak słowa poza apostrofami: ``\\x``, rozwinięcie albo zwykły znak."""

        if char == "\\":
            parts.append(self.text[self.at + 1 : self.at + 2])
            self.at += 2
        elif char in "$`":
            start = self.at
            word.dynamic = self.expansion() or word.dynamic
            word.expanded = True
            parts.append(self.text[start : self.at])
        else:
            word.dynamic = word.dynamic or char in "*?["
            parts.append(char)
            self.at += 1

    def expansion(self) -> bool:
        """Rozwinięcie od ``$`` albo `` ` ``; ``True``, gdy jego wartość zależy od chwili uruchomienia."""

        if self.text[self.at] == "`":
            self.at += 1
            self.commands_until("`")
            return True
        if self.text.startswith("$((", self.at):
            self.at = self.arithmetic(self.at + 3)
            return True
        if self.text.startswith("$(", self.at):
            self.at += 2
            self.commands_until(")")
            return True
        if self.text.startswith("${", self.at):
            close = self.text.find("}", self.at)
            end = len(self.text) if close < 0 else close + 1
            expansion = self.text[self.at : end]
            self.at = end
            braced = BRACED.fullmatch(expansion)
            return not GUARDED.fullmatch(expansion) and not (braced and braced.group(1) in self.known)
        name = NAME.match(self.text, self.at + 1)
        self.at = self.at + 1 if name is None else name.end()
        return name is not None and name.group() not in self.known

    def arithmetic(self, start: int) -> int:
        """Indeks za ``))`` arytmetyki, której ``((`` kończy się przed ``start``."""

        depth, index = 2, start
        while index < len(self.text) and depth:
            depth += {"(": 1, ")": -1}.get(self.text[index], 0)
            index += 1
        return index


def _judge(command: str, fix: str) -> Optional[Refusal]:
    reader = _Reader(command)
    reader.commands_until("")
    removals = [words for words in reader.commands if words[0].text.rsplit("/", 1)[-1] == "rm"]
    if removals and (reader.subshell or len(reader.commands) > 1):
        for word in [word for words in removals for word in words[1:]]:
            if word.dynamic:
                return Refusal(f"argument rm {word.text} zależy od wartości z chwili uruchomienia (zmienna, $(…) albo glob).", fix)
        for words in reader.commands:
            if words[0].expanded:
                return Refusal(f"polecenie {words[0].text} bierze nazwę ze zmiennej, więc nie wiadomo, co uruchomi obok rm.", fix)
        if reader.ambiguous_close:
            return Refusal("\"))\" zamyka podpowłokę i $(…) naraz, więc parser Claude Code nie widzi, gdzie stoi rm.", fix)
    for text in reader.texts:
        refusal = _judge(text, TEXT_FIX)
        if refusal is not None:
            return refusal
    return None


def judge(command: str) -> Optional[Refusal]:
    try:
        return _judge(command, FIX)
    except RecursionError:
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
