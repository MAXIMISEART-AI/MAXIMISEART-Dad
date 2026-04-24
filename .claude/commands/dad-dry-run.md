---
description: Test dry-run daily workflow — używa tests/fixtures/ zamiast Gmail, NIE pisze do Excela.
---

Uruchom:

```bash
python scripts/daily_workflow.py --test-mode --dry-run --date $(date +%Y-%m-%d)
```

Oczekiwane zachowanie:
- Read fixtures z tests/fixtures/sample_emails/*.json
- Step 1-6 execute ale NIE zapisuje Excela ani raportu
- Log trace w logs/dry-run-YYYY-MM-DD.jsonl
- Sanity: wszystkie 3 fixtures (normal, ambiguous, unknown-sender) poprawnie sklasyfikowane

Failure = red flag przed deploy.
