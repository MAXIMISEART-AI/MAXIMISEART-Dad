"""Wyrocznia hooka ``tools/hooks/usuwanie.py``: pyta zainstalowany Claude Code, które polecenia z ``rm`` zatrzymuje na zgodzie.

Hook ma regułę szerszą niż kontrola Claude Code, więc po każdej aktualizacji Claude Code ta wyrocznia sprawdza, czy
hook dalej odrzuca każde polecenie, które Claude Code zatrzymuje. Dla każdego przypadku z
``tools/wyrocznia_usuwania.jsonl`` uruchamia ``claude -p`` w trybie ``bypassPermissions`` z odrzucaną zgodą
(``--permission-prompts none``), każe mu wysłać polecenie Bashem bajt w bajt i czyta z ``stream-json`` pierwsze
polecenie Basha, które model wysłał, i to, czy Claude Code odmówił (``permission_denials``). Polecenia naprawdę
biegną, więc ścieżki ``@WS@``, ``@FAR@`` i ``@TFAR@`` (ta sama co ``@FAR@``, ale przez ``~``) prowadzą do katalogu
tymczasowego w ``~/.cache``, który narzędzie usuwa na końcu.
Katalog roboczy ``@WS@`` nie jest repozytorium, więc hooki projektu w nim nie działają.

Wiersz na przypadek: ``ZGODNE`` (Claude Code i hook rozstrzygają tak samo), ``SZERSZY`` (hook odrzuca polecenie,
które Claude Code puszcza), ``ROZJAZD`` (Claude Code zatrzymuje polecenie, które hook puszcza), ``ZMIANA`` (Claude
Code rozstrzyga inaczej, niż zapisał plik przypadków) albo ``NIEDOSŁOWNIE`` (model zmienił polecenie albo nie wysłał
go przed limitem czasu, więc przypadek nic nie mówi). Ostatnia linia to ``WYROCZNIA OK | …`` (kod 0) albo
``WYROCZNIA ROZJAZD | …`` (kod 1), gdy któryś przypadek ma ``ROZJAZD`` albo ``ZMIANA``: wtedy popraw hook, test
``tests/test_usuwanie.py`` i pole ``pyta_o_zgode`` w pliku przypadków. Bez ``claude`` na PATH kończy się kodem 2.

    .venv/bin/python tools/wyrocznia_usuwania.py                      # wszystkie przypadki, ok. 60 min
    .venv/bin/python tools/wyrocznia_usuwania.py var-loop abs-cd-glob  # wybrane przypadki
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/hooks"))

import potomne
import usuwanie

CASES = Path(__file__).resolve().parent / "wyrocznia_usuwania.jsonl"
MODEL = "claude-opus-5-5"
TIMEOUT_S = 300
PROMPT = (
    "Use the Bash tool exactly once to run the command below, byte for byte, without changing it. "
    "Do not run anything else. If it is denied, do not retry. Then reply DONE.\n\n```\n{command}\n```"
)


@dataclass(frozen=True)
class Case:
    name: str
    command: str
    asks: bool | None


@dataclass(frozen=True)
class Answer:
    sent: str | None
    asks: bool


def cases(path: Path) -> list[Case]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [Case(row["nazwa"], row["polecenie"], row["pyta_o_zgode"]) for row in rows]


def placed(command: str, sandbox: Path) -> str:
    far = sandbox / "far"
    tilde = "~/" + far.relative_to(Path.home()).as_posix()
    return command.replace("@WS@", str(sandbox / "ws")).replace("@FAR@", str(far)).replace("@TFAR@", tilde)


def answer(stream: str) -> Answer:
    """Pierwsze polecenie Basha, które model wysłał, i to, czy Claude Code odmówił bez zgody człowieka."""

    sent, asks = None, False
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        parts = (message.get("content") or []) if isinstance(message, dict) else []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash" and sent is None:
                sent = part.get("input", {}).get("command")
        if event.get("type") == "result":
            asks = bool(event.get("permission_denials"))
    return Answer(sent, asks)


def ask(command: str, workspace: Path, model: str, limit_s: float) -> Answer:
    done = potomne.run(
        ["claude", "-p", "--model", model, "--permission-mode", "bypassPermissions", "--permission-prompts", "none",
         "--output-format", "stream-json", "--verbose", "--max-turns", "3", PROMPT.format(command=command)],
        cwd=workspace,
        timeout=limit_s,
    )
    return answer(done.stdout)


def verdict(case: Case, command: str, got: Answer) -> str:
    if got.sent != command:
        return "NIEDOSŁOWNIE"
    refused = usuwanie.judge(command) is not None
    if got.asks and not refused:
        return "ROZJAZD"
    if case.asks is not None and got.asks != case.asks:
        return "ZMIANA"
    return "SZERSZY" if refused and not got.asks else "ZGODNE"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("nazwy", nargs="*", help="Nazwy przypadków (pole nazwa); bez nich wszystkie.")
    parser.add_argument("--przypadki", type=Path, default=CASES, help="Plik przypadków JSONL.")
    parser.add_argument("--model", default=MODEL, help=f"Model, który przepisuje polecenie (domyślnie {MODEL}).")
    parser.add_argument(
        "--limit-s", type=float, default=TIMEOUT_S, help=f"Limit jednego claude -p w sekundach (domyślnie {TIMEOUT_S})."
    )
    args = parser.parse_args(argv)
    chosen = [case for case in cases(args.przypadki) if not args.nazwy or case.name in args.nazwy]
    if shutil.which("claude") is None:
        print("WYROCZNIA BRAK | nie ma claude na PATH")
        return 2
    version = potomne.run(["claude", "--version"], cwd=Path.home(), timeout=60).stdout.strip()
    print(f"Claude Code {version}, przypadki {len(chosen)}", flush=True)
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="wyrocznia-usuwania-", dir=cache))
    counts: dict[str, int] = {}
    try:
        for folder in ("ws", "far/logi"):
            (sandbox / folder).mkdir(parents=True)
        for case in chosen:
            command = placed(case.command, sandbox)
            try:
                got = ask(command, sandbox / "ws", args.model, args.limit_s)
            except subprocess.TimeoutExpired:
                got = Answer(None, False)
            result = verdict(case, command, got)
            counts[result] = counts.get(result, 0) + 1
            print(f"{result} {case.name} | Claude Code {'pyta o zgodę' if got.asks else 'puszcza'}", flush=True)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    summary = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    failed = counts.get("ROZJAZD", 0) + counts.get("ZMIANA", 0)
    print(f"WYROCZNIA {'ROZJAZD' if failed else 'OK'} | Claude Code {version} | {summary}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
