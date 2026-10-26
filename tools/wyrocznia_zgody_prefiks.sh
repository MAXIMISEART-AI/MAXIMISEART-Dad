#!/bin/sh
# Prefiks powłoki (CLAUDE_CODE_SHELL_PREFIX) wyroczni tools/wyrocznia_zgody.py. Claude Code podaje tu w jednym
# argumencie całe polecenie: narzędzia Bash albo hooka, a polecenie hooka dosłownie tak, jak stoi w ustawieniach.
# Biegnie tylko polecenie równe co do znaku poleceniu hooka zgody z .claude/settings.json, które wyrocznia podaje
# w WYROCZNIA_ZGODY_HOOK. Każde inne, także polecenie przypadku z tą ścieżką w treści, wypisuje znacznik i kończy się
# bez wykonania.
if [ "$1" = "$WYROCZNIA_ZGODY_HOOK" ]; then
  exec /bin/sh -c "$1"
fi
echo "WYROCZNIA-ZGODY-NIE-WYKONANO"
