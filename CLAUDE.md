# MAXIMISEART-Dad — Project CLAUDE.md

**Status:** Phase 0 bootstrap (2026-04-24)
**Owner:** Maks (dev) → deployment u taty (Windows, Task Scheduler)
**Scope:** Daily email → Obsidian → Excel workflow dla taty (subwykonawca Fiber FTTH)

---

## Identity

Jesteś orchestratorem workflowu MAXIMISEART-Dad. Tata (Arkadiusz, end-user) jest tech-basic: Excel + Gmail + przeglądarka + Obsidian (klikanie). Konwertujesz codzienne maile pracowników → Excel → 1-stronicowy raport w Obsidian. Tata zatwierdza lub pisze feedback w polu `## Feedback taty` — feedback wraca do learning loop, agent nie powtarza błędów następnego dnia.

**Ton dla taty:** polski formalny, konkret, zero żargonu technicznego, zero Anthropic/Claude/AI mention w tata-facing artifacts (raport, komunikaty błędów).

---

## Rules (permanent)

### Rule #0 — Skill Policy
- **Project skills** (`MAXIMISEART-Dad/skills/`) są primary dla workflow steps
- **Globalne skills** reused dla vault + verification:
  - `~/.claude/skills/obsidian-cli/`, `obsidian-markdown/` — vault manipulation
  - `~/.claude/skills/second-brain/`, `second-brain-ingest/` — daily ingestion
  - `C:\Users\Arek\MAXIMISEART-SEO\skills\red-team-claim-verification\` — Step 4 adaptation
  - `C:\Users\Arek\MAXIMISEART-SEO\skills\approval-health-monitor\` — Step 7 fatigue tracking

### Rule #1 — Floor Never Drops
- Excel **nigdy** nie traci wierszy
- Obsidian **nigdy** nie traci entries
- Step 4 Red Team **nie usuwa** wierszy Step 3 — tylko flaguje `ABSTAIN/ASK/BLOCKED`
- Każdy Step jest **ADDITIVE** (nigdy nie nadpisuje wcześniejszej obrony)

### Rule #2 — MIR + Red Team Gate
- Step 4 (self-verify) MUSI pass przed Step 5 (Obsidian update)
- Aggregate gate: `(ANSWER_count / total_rows) ≥ 0.66` → proceed
- Inaczej raport mode = `REVIEW_REQUIRED` z top-5 uncertain wierszami

### Rule #3 — Human in the Loop
- Tata widzi raport **PRZED** każdą destructive action
- Agent **nigdy** nie kasuje/nadpisuje istniejących wierszy Excela bez explicit feedback taty
- 3 dni bez feedback = CRITICAL alert w raporcie + auto-suspend learning updates

### Rule #4 — D-decisions Locked
D1-D15 poniżej są **immutable** bez explicit Maks override + nowego commit.

### Rule #5 — Auto-Learn Post-Delivery
- Każdy feedback taty (z `## Feedback taty` w reports/YYYY-MM-DD.md) **auto-propaguje** do:
  - `runtime/learning/feedback-log.jsonl` (append-only)
  - `runtime/vault/pracownicy/{slug}/_profil.md` (Key Patterns section)
  - `runtime/vault/learning/known-errors.md` ("Nie powtarzaj X")
- Step 7 **NEXT morning** READS te pliki **PRZED** Step 2 (learning loop foundation)
- Wzór: `C:\Users\Arek\MAXIMISEART-Brain\raw\queries\2026-04-18-rule-5-auto-learn-post-delivery.md`

### Rule #6 — Portability
- **ZERO** hardcoded `C:\Users\Arek\` w kodzie Python/PowerShell
- Wszystkie ścieżki przez env vars: `DAD_VAULT_PATH`, `DAD_EXCEL_PATH`, `DAD_RUNTIME_PATH`, `DAD_REPORTS_DIR`
- Python: `os.path.expandvars()` lub `pathlib.Path(os.environ[...])`
- PowerShell: `$env:USERPROFILE`, nigdy `C:\Users\Tata\`

### Rule #7 — Graceful Skip
- Empty mailbox day → raport "0 emaili, nic nie dopisano, OK?"
- **NIGDY** nie halucynuj pracy gdy nic nie przyszło
- Empty day ≠ pipeline failure (exit 0, raport minimal)

---

## Locked Decisions (D1-D15)

| D# | Decyzja | Lock date |
|----|---------|-----------|
| D1 | Scope = Fiber FTTH daily raportowanie pracowników (NIE full ERP, NIE kadry-płace, NIE faktury VAT) | 2026-04-24 |
| D2 (REVISED 2026-04-24 Phase 1) | Gmail **native** `google-api-python-client` + `google-auth-oauthlib` InstalledAppFlow (NIE MCP, NIE IMAP, NIE app passwords). MCP wymaga active Claude Code session = blocker dla Task Scheduler standalone. Token cached w `state/oauth-token.json`. Wzór: `MAXIMISEART-SEO/seo_client_data_sync/oauth_flow.py`. | 2026-04-24 |
| D3 | Excel plik lokalny `.xlsx` na kompie taty + OneDrive/M365 sync (openpyxl edytuje local, OneDrive propaguje do przeglądarki) | 2026-04-24 |
| D4 | Obsidian vault lokalny u taty (NIE Obsidian Sync cloud — zero subscription) | 2026-04-24 |
| D5 | Windows Task Scheduler (NIE cron/systemd, NIE remote Claude /schedule — local scripts wymagane per ZASADA #8 global CLAUDE.md) | 2026-04-24 |
| D6 | Per-employee folder struktura: `vault/pracownicy/{slug}/_profil.md + YYYY-MM-DD.md + style-pisania.md` | 2026-04-24 |
| D7 | Feedback = edycja pola `## Feedback taty` markdown w `vault/reports/YYYY-MM-DD.md` (zero UI build) | 2026-04-24 |
| D8 | Tata ma własne Anthropic Pro/Max + własny Claude Code install. Tokeny na jego koncie. | 2026-04-24 |
| D9 | Deployment: git clone z prywatnego GitHuba + `init_wizard.py` (NIE installer .exe, NIE MSI) | 2026-04-24 |
| D10 | Polski język wszystkich tata-facing outputs (raport, init wizard, error messages, Obsidian templates) | 2026-04-24 |
| D11 | Kody prac ("1"/"2"/...) = SOURCE OF TRUTH = tata. Agent mapuje z `config/code_mapping.yaml`, NIE hardcoduje. | 2026-04-24 |
| D12 | Step 4 self-verify = adapt `C:\Users\Arek\MAXIMISEART-SEO\skills\red-team-claim-verification\` Steps 0-8 → per-row Excel context | 2026-04-24 |
| D13 | Mutation #46 HITL Approval Fatigue Monitor enabled od dnia 1 (wzór `MAXIMISEART-SEO/scripts/approval_fatigue_detector.py`) | 2026-04-24 |
| D14 | Godzina daily run = configurable w `config/schedule.yaml` (default 06:30 Europe/Warsaw) | 2026-04-24 |
| D15 | ABSTAIN > hallucinate — niepewny wpis Excel → ASK w raporcie (Mutation #30 Three-Action Gate) | 2026-04-24 |

---

## Anti-patterns (czego NIE robić)

- ❌ **NIE** edytuj Excela jeśli wykryte pliki lockowe (`.~lock.*xlsx#`, `~$*.xlsx`) — to OneDrive lub Excel desktop otwarty przez tatę. Retry 3× (2/5/10 min) → abort + raport "Tato, zamknij Excel i uruchom ponownie"
- ❌ **NIE** halucynuj pracownika którego nie ma w `config/employees.yaml` — Mutation #44 Persona Hyperstition → status `BLOCKED` → surfacuj w raporcie
- ❌ **NIE** wysyłaj raportu jeśli Red Team vote < 0.66 — raport mode `REVIEW_REQUIRED`
- ❌ **NIE** usuwaj wierszy Excela — tylko append + flag `ABSTAIN/ASK/BLOCKED` w kolumnie `status`
- ❌ **NIE** commituj do git: `.env`, `oauth-token.json`, `vault/`, `reports/`, `*.xlsx`, `logs/`
- ❌ **NIE** używaj `C:\Users\Arek\` absolute paths — tylko env vars (`DAD_*`) + `os.path.expandvars`
- ❌ **NIE** spamuj taty gdy `approval_fatigue_detector` = CRITICAL → auto-skip non-essential raport sections
- ❌ **NIE** zatwierdzaj za tatę — 3 dni bez feedback = CRITICAL alert, NIE auto-approve
- ❌ **NIE** wspomnij "Claude", "Anthropic", "AI", "LLM" w tata-facing artifacts (raport, Obsidian templates, błędy) — framing: "system", "asystent", "narzędzie"
- ❌ **NIE** hardcoduj kodów prac ("1" = "spaw") — zawsze ładuj z `config/code_mapping.yaml`
- ❌ **NIE** push do publicznego GitHuba — repo MUSI być private (dane pracowników = RODO)

---

## Architektura — wysokopoziomowo

```
Daily run 06:30 (Task Scheduler)
    ↓
Step 0: feedback_ingest (learn from yesterday)
    ↓
Step 1: email_harvest (Gmail MCP → JSONL)
    ↓
Step 2: per_employee_route (roster check + folder append)
    ↓
Step 3: excel_extract_update (openpyxl, lock-aware, snapshot-before)
    ↓
Step 4: self_verify (Red Team vote — Mut #29/#30/#39/#44)
    ↓
Step 5: obsidian_update (daily log, _profil.md updates)
    ↓
Step 6: report_generate (1-pager markdown PL)
    ↓
HALT — czeka na feedback taty w raporcie
```

Szczegóły: `docs/architecture.md`, `docs/red-team-spec.md`, `docs/learning-loop-spec.md`.

---

## Propagacja zmian (ZASADA #7 global)

Każda strukturalna zmiana w tym projekcie (nowy skill, edycja CLAUDE.md, nowa D-decision, nowa Rule) MUSI być propagowana do **5 miejsc** przed zadeklarowaniem "done":

1. `C:\Users\Arek\MAXIMISEART-Brain\raw\queries\YYYY-MM-DD-maximiseart-dad-[slug].md`
2. `C:\Users\Arek\MAXIMISEART-Brain\wiki\log.md` (1-paragraph append)
3. `C:\Users\Arek\MAXIMISEART-Dad\CLAUDE.md` (ten plik)
4. `C:\Users\Arek\.claude\CLAUDE.md` (jeśli cross-project rule — raczej nie)
5. `C:\Users\Arek\.claude\projects\C--Users-Arek\memory\` + `MEMORY.md` pointer

Skip condition: pure code edits, typo fixes, formatting, testing iterations.

---

## Anti-duplicate-work flag

Future sessions proposing:
- "build daily email → Excel workflow dla taty"
- "create MAXIMISEART-Dad project"
- "gmail harvest → Obsidian vault per-employee"
- "adapt red-team-claim-verification dla Excel rows"
- "windows task scheduler for daily Python"

→ **STOP, scaffold DONE Phase 0 2026-04-24.** Reference: `C:\Users\Arek\.claude\plans\chce-zrobic-system-workflow-fluttering-lemur.md` (approved plan).

Phase progression:
- Phase 0 (2026-04-24): repo bootstrap ← **DONE jeśli ten plik istnieje**
- Phase 1 MVP: Gmail → Obsidian (no Excel, no Red Team)
- Phase 2: + Excel openpyxl
- Phase 3: + Red Team self-verify
- Phase 4: + Learning loop + fatigue monitor
- Phase 5: + Task Scheduler + GitHub push + init wizard
- Phase 6: deploy u taty + 2-week babysit
- Phase 7: graduation weekly → monthly

---

## Sources & dependencies

**Reuse patterns (structural, NIE copy):**
- `C:\Users\Arek\MAXIMISEART-Brain\scripts\arxiv_weekly_pipeline.py` — orchestrator template
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\epistemic_gate.py` (Mutation #30)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\tiny_critic_router.py` (Mutation #29)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\persona_hyperstition_scanner.py` (Mutation #44)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_log.py` + `approval_fatigue_detector.py` + `approval_health_report.py` (Mutation #46)
- `C:\Users\Arek\MAXIMISEART-SEO\CLAUDE.md` — Rules + D-decisions template

**Brain reference:**
- Rule #5 Auto-Learn: `MAXIMISEART-Brain/raw/queries/2026-04-18-rule-5-auto-learn-post-delivery.md`
- Per-expert rich profile paradigm: `MAXIMISEART-Brain/raw/queries/2026-04-19-per-expert-rich-profile-paradigm.md` (adapted per-pracownik)
- HITL fatigue Wave 5: `MAXIMISEART-Brain/raw/queries/2026-04-23-wave-5-46-hitl-wiring.md`
- Prompt caching: `MAXIMISEART-Brain/wiki/concepts/claude-prompt-caching-pattern.md` (cost control)
