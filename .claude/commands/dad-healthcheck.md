---
description: Sprawdź health systemu — Gmail token valid, Excel accessible, vault integrity, recent logs.
---

**Phase 5+ command.** Phase 0 stub.

Diagnostyka (run u taty gdy coś nie działa):

```bash
python scripts/daily_workflow.py --dry-run --date $(date +%Y-%m-%d)
```

Check manually:
- [ ] `%DAD_RUNTIME_PATH%\state\oauth-token.json` exists + not expired
- [ ] `%DAD_EXCEL_PATH%` accessible (no OneDrive lock)
- [ ] `%DAD_VAULT_PATH%\reports\` zawiera ostatnie 3 raporty
- [ ] `%DAD_RUNTIME_PATH%\logs\cron-*.log` ostatnie 3 dni bez ERROR
- [ ] Task Scheduler: `Get-ScheduledTask -TaskName 'MAXIMISEART-Dad-Daily'` = Ready

Anomalie:
- OAuth expired → `python scripts/init_wizard.py --reauth`
- Excel lock persists → zadzwoń do taty, zamknij Excel desktop
- Red Team < threshold od 3 dni → review `vault/reports/` + inspect Step 4 rationale
- Fatigue CRITICAL → manual trigger reports review + reset approval-log
