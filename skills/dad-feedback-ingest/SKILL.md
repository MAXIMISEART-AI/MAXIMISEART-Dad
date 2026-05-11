---
name: dad-feedback-ingest
description: Step 7 learning loop — czyta wczorajszy feedback taty z raportu, parsuje Haiku, updates learning files. Runs ZANIM Step 1 każdego dnia.
---

# dad-feedback-ingest

**Status:** Phase 4 shipped as deterministic parser + learning loop foundation. Implementation lives in `scripts/step7_feedback_ingest.py`; real API parsing remains gated.

## Purpose

Step 7 (execution order 0 — PIERWSZY każdego dnia). Czyta pole `## Feedback taty` z wczorajszego raportu, parsuje, propaguje do Brain learning layer. Agent następnego dnia używa tego kontekstu w Step 2/3/4 prompts.

## Inputs

- `cfg: DadConfig`
- `today: str` — YYYY-MM-DD

## Outputs

- `FeedbackState(corrections, approval_streak, fatigue_level)`
- Appends:
  - `runtime/learning/feedback-log.jsonl` (append-only, timestamped)
  - `runtime/vault/pracownicy/{slug}/_profil.md` (Key Patterns section)
  - `runtime/vault/learning/known-errors.md` ("Nie powtarzaj X")
- `runtime/state/approval-log.jsonl` (Mut #46 fatigue tracking)

## Algorithm

1. Read `runtime/vault/reports/{today-1day}.md`
2. Extract section `## Feedback taty`
3. If empty:
   - `approval_log.log(decision=AUTO_NO_FEEDBACK, streak++)` (Mut #46)
   - Return `FeedbackState.empty()` + increment fatigue streak
4. Parse feedback_block via Haiku 4.5:
   ```
   System: Jesteś parserem feedbacku. Input: polski tekst od użytkownika.
   Output JSON: [{employee_id, claim, correction_type, confidence}].
   Correction types: wrong_code, wrong_quantity, wrong_location, wrong_employee,
                     format_preference, unclear.
   ```
5. For each correction w parsed:
   - Append to `feedback-log.jsonl` (timestamp + raw + parsed)
   - Update `_profil.md` Key Patterns section (floor-never-drops — append-only)
   - Update `known-errors.md` z "Nie powtarzaj X"
6. Return `FeedbackState(corrections, approval_streak, fatigue_level)`

## FeedbackState injection

Step 2/3/4 prompts dostają context block:
```
KONTEKST Z FEEDBACK TATY (ostatnie 30 dni):
- Jan Kowalski: skrót "spaw" = kod 2 (NIE kod 1) [confirmed 2026-04-22]
- Anna Nowak: "bl.12" = "blok 12" [confirmed 2026-04-20]
- NEVER hallucinate pracownika spoza employees.yaml — tata zawsze to catchuje
```

## Reuse

- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_log.py` — JSONL append-only (Mut #46 Layer 1)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_fatigue_detector.py` — Layer 2 alerts
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_health_report.py` — Layer 3 weekly digest
- Pattern: `MAXIMISEART-Brain/raw/queries/2026-04-18-rule-5-auto-learn-post-delivery.md`
- Pattern: `MAXIMISEART-Brain/raw/queries/2026-04-19-per-expert-rich-profile-paradigm.md`

## Red Team / Safety

- `confidence < 0.7` w parsed correction → surfacuj "Niejasny feedback" w next-day raport (clarification ASK)
- 3 days bez feedback → fatigue CRITICAL → auto-suspend learning updates (Rule #3 Human in the Loop)
