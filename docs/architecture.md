# Architecture — MAXIMISEART-Dad

## High-level flow

```
┌──────────────────────────────────────────────────────────────────────┐
│ Windows Task Scheduler 06:30 Europe/Warsaw                            │
│   → deploy/run-daily.bat                                              │
│     → python scripts/daily_workflow.py --date YYYY-MM-DD              │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 0 — step7_feedback_ingest.py (EXECUTED FIRST)                    │
│   Reads vault/reports/YESTERDAY.md "## Feedback taty"                 │
│   → runtime/learning/feedback-log.jsonl (append)                      │
│   → vault/pracownicy/{slug}/_profil.md (Key Patterns update)          │
│   Returns FeedbackState → injected jako CONTEXT w Step 2/3/4          │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 1 — step1_email_harvest.py                                       │
│   Gmail MCP (OAuth token cached z init_wizard)                        │
│   → runtime/state/raw/emails-YYYY-MM-DD.jsonl                         │
│   Fallback: empty → Rule #7 graceful skip + minimal raport            │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 2 — step2_per_employee_route.py                                  │
│   Match email.from → employees.yaml roster (Mut #44 check)            │
│   Unknown → status=BLOCKED, surfacuj w raporcie                       │
│   → vault/pracownicy/{slug}/YYYY-MM-DD.md per-employee daily log      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 3 — step3_excel_extract_update.py                                │
│   Pre-flight: excel_safe_writer.is_excel_locked → retry 3x            │
│   Snapshot: state/excel-snapshots/YYYY-MM-DD-HHMMSS.xlsx              │
│   openpyxl load → append rows per schema + code_mapping               │
│   Post-write: SHA-256 checksum verify                                 │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 4 — step4_self_verify.py (RED TEAM GATE)                         │
│   Per-row: Mut #29 Haiku → #30 Sonnet → #39 triple-vote → #44 check   │
│   Aggregate: (ANSWER / total) >= 0.66 → proceed                       │
│   Fail → report_mode=REVIEW_REQUIRED (top-5 uncertain)                │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 5 — step5_obsidian_update.py                                     │
│   Append vault/learning/log.md (chronological)                        │
│   Update _profil.md "Content ingestion log" per pracownik             │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Step 6 — step6_report_generate.py                                     │
│   → vault/reports/YYYY-MM-DD.md (1-pager PL)                          │
│   Inject fatigue warning gdy Mut #46 CRITICAL                         │
│   Status: AWAITING_FEEDBACK                                           │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       HALT — tata reviewuje raport
                       (następnego dnia Step 0 picks up feedback)
```

## Data flow

### Inputs (external)
- Gmail API (OAuth → `state/oauth-token.json`)
- Excel file at `cfg.excel_path` (OneDrive/M365 synced)

### Outputs (tata-visible)
- `runtime/vault/reports/YYYY-MM-DD.md` — 1-pager raport
- Excel append rows (OneDrive sync → przeglądarka)

### Outputs (agent-internal)
- `runtime/state/raw/emails-*.jsonl` — harvested emails
- `runtime/state/excel-snapshots/*.xlsx` — pre-write backups
- `runtime/state/approval-log.jsonl` — Mut #46 fatigue data
- `runtime/vault/pracownicy/{slug}/_profil.md` — per-employee rich profile
- `runtime/vault/pracownicy/{slug}/YYYY-MM-DD.md` — daily email log
- `runtime/vault/learning/*.md` — feedback propagation + known errors
- `runtime/learning/feedback-log.jsonl` — structured learning corpus
- `runtime/logs/YYYY-MM-DD.jsonl` — pipeline JSON logs

## Key integration points

### Claude API models
- **Haiku 4.5** (`claude-haiku-4-5-20251001`): Step 3 code classification + Step 4 Mut #29 tiny-critic + Step 7 feedback parsing
- **Sonnet 4.6** (`claude-sonnet-4-6`): Step 4 Mut #30 epistemic gate escalation + Step 4 Mut #39 triple-vote
- **Opus 4.7** (`claude-opus-4-7`): optional high-stakes escalation (if #43 L2 cross-lineage enabled)

### Cost budget
- Typical daily run (50 emaili): ~$0.10-0.30
- Monthly estimate: ~20 PLN (budget bar w `schedule.yaml: max_api_cost_pln_per_day: 5.0`)

### Failure recovery
- OAuth expired → `state/ALERT-oauth-expired.md` visible w vault + exit 2
- Excel locked → retry 3× then abort + raport "Tato zamknij Excel"
- Red Team < threshold → raport REVIEW_REQUIRED (NIE exit)
- API quota exceeded → exit + alert file
- Disk full → exit + alert file

## Deployment diagram

```
[GitHub Private Repo]
        │
        │ git clone
        ▼
[Tata's Windows PC]
├── MAXIMISEART-Dad/ (code, committed)
│   ├── scripts/, skills/, config/, deploy/, docs/, tests/
│   └── CLAUDE.md, pyproject.toml, .env.example
│
├── MAXIMISEART-Dad-runtime/ (NEVER committed — local data)
│   ├── vault/ (Obsidian)
│   ├── state/
│   ├── learning/
│   ├── logs/
│   └── .env (secrets)
│
└── OneDrive/Fiber/
    └── raporty-dzienne.xlsx (Excel file, cross-synced to Web)
```

## Extension points (Phase 6+)

- **Photo attachments**: Phase 8 vision model (Haiku 4.5 supports images)
- **Multi-operator split**: Phase 7 if Orange/T-Mobile/Play need separate raporty
- **Weekly rollup**: Phase 5 `synthesis/weekly-YYYY-WNN.md` auto-generator
- **Mobile notifications**: Phase 9 email raport do taty gdy CRITICAL alert
