#!/bin/sh
# Prefiks powłoki (CLAUDE_CODE_SHELL_PREFIX) wyroczni tools/wyrocznia_zgody.py. Claude Code podaje tu w jednym
# argumencie całe polecenie: narzędzia Bash albo hooka. Biegnie tylko hook zgody, a każde inne polecenie, także
# polecenie przypadku, wypisuje znacznik i kończy się bez wykonania.
case "$1" in
  *tools/hooks/zgoda.py*) exec /bin/sh -c "$1" ;;
esac
echo "WYROCZNIA-ZGODY-NIE-WYKONANO"
