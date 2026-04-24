---
description: Deploy workflow na czystej maszynie — uruchamia init_wizard + setup-windows-task.
---

**Phase 5+ command.** Phase 0 stub.

Krok-po-krok deploy na nowej maszynie (tata):

1. `git clone https://github.com/<USER>/MAXIMISEART-Dad.git`
2. `cd MAXIMISEART-Dad`
3. `python -m venv .venv`
4. `.venv\Scripts\activate` (PowerShell) lub `.venv/bin/activate` (bash WSL)
5. `pip install -r requirements.txt`
6. `python scripts/init_wizard.py`
7. Follow wizard prompts — Gmail OAuth w przeglądarce, Excel path, godzina run
8. `powershell -ExecutionPolicy Bypass -File deploy/setup-windows-task.ps1`
9. Test: `Start-ScheduledTask -TaskName 'MAXIMISEART-Dad-Daily'`
10. Verify: `Get-Content %DAD_RUNTIME_PATH%\logs\cron-*.log`

Każdy błąd → zatrzymaj + debug z Maksem.
