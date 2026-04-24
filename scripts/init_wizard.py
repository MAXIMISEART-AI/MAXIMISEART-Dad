"""Init wizard — one-time setup u taty (PL).

Phase 0 stub. Phase 5 implementation:

Interactive wizard PL:
  1. Welcome message
  2. Ask: Excel path (auto-detect OneDrive glob OR manual)
  3. Ask: daily run hour (default 06:30)
  4. Gmail OAuth flow (opens browser)
  5. Write .env z user choices
  6. Smoke test (read 1 email, read 1 Excel row, verify encoding)
  7. Ask: test dry-run? [Y/n]
  8. Install Task Scheduler via deploy/setup-windows-task.ps1
  9. Final message

Constraints:
- Polski throughout (Rule D10)
- Zero mention "Claude/Anthropic/AI" w komunikatach
- Idempotent — ponowne uruchomienie wykrywa existing config i pozwala rekonfigurować
- Graceful errors — każdy fail z czytelnym PL komunikatem
"""
from __future__ import annotations

import sys


def main() -> int:
    print("[PLACEHOLDER] Phase 5: implement init wizard")
    print("Witaj Tato. (Phase 0 stub — pełny wizard w Phase 5)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
