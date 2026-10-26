#!/usr/bin/env python3
"""Hook ``PermissionRequest`` Claude Code dla Basha: w trybie bypass odmawia od razu, zamiast czekać na zgodę człowieka.

Claude Code 2.1.309–2.1.310 w trybie ``bypassPermissions`` (tak T3 uruchamia agentów) pyta człowieka o zgodę na
polecenie Basha tylko przy kontroli bezpieczeństwa, której nie zdejmuje reguła ``permissions.allow``.
We wszystkich znanych przypadkach to ``rm``, którego celu Claude Code nie umie ustalić z tekstu polecenia. Agent w tle
stał wtedy bez słowa: 24.10 do 66 min, 26.10 do 104 min. Claude Code uruchamia ten hook razem z pytaniem do hosta,
a po odmowie z hooka Claude Code w ciągu ok. 0,1 s anuluje pytanie u hosta i oddaje agentowi poprawkę. Kiedy pytać,
rozstrzyga więc sama kontrola Claude Code, a hook nie odtwarza jej reguł. W innym trybie (sesja człowieka w
``default``) hook nic nie wypisuje i pytanie idzie do człowieka jak zwykle. Wejście, którego nie da się odczytać,
też, bo hook nie zna wtedy trybu.

Granica: hook działa, dopóki Claude Code uruchamia hooki ``PermissionRequest`` przy pytaniu o ``rm``. Po aktualizacji
Claude Code sprawdza to ``tools/wyrocznia_zgody.py``. Inne harnessy niż Claude Code (Codex, opencode) łapie tylko
przegląd. Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

import json
import sys

MESSAGE = (
    "Claude Code zatrzymałby to polecenie Basha na zgodzie człowieka, a agent w trybie bypass nie czeka na zgodę, "
    "więc polecenie nie ruszyło. Uruchom rm osobnym wywołaniem Basha z dosłowną ścieżką bezwzględną "
    "(rm -rf /abs/katalog/logi) albo ze zmienną w postaci ${VAR:?}, a resztę polecenia w następnym wywołaniu. "
    "Kod i dane z rm zapisz do pliku narzędziem Write albo Edit, a nie w heredocu ani w napisie w poleceniu."
)


def decision(event: object) -> dict[str, object] | None:
    """Odpowiedź hooka na zdarzenie ``PermissionRequest``: odmowa w trybie bypass, inaczej ``None``."""

    if not isinstance(event, dict) or event.get("permission_mode") != "bypassPermissions":
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": MESSAGE},
        }
    }


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read())
    except ValueError:  # także UnicodeDecodeError
        return 0
    answer = decision(event)
    if answer is not None:
        # Same znaki ASCII (``ł`` zamiast ``ł``), bo konsola Windows nie zapisze polskich liter w swoim kodowaniu.
        print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
