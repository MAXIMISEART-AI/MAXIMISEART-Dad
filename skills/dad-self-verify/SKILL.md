---
name: dad-self-verify
description: Step 4 Red Team self-verify łączący Mutation #29 Tiny-Critic + #30 Epistemic Gate + #39 Three-Signal Vote + #44 Persona Hyperstition. Adaptuje red-team-claim-verification Steps 0-8 do per-row Excel context.
---

# dad-self-verify

**Status:** Phase 0 stub. Phase 3 target: 5h effort.

## Purpose

Step 4 — bramka między Excel-write (Step 3) i report-send (Step 6). Dla każdego appended row waliduje przeciw source emailowi + feedback history. Decyzje: ANSWER / ASK / ABSTAIN / BLOCKED.

## Inputs

- `emails: list[dict]` — source (Step 1)
- `rows_added: list[dict]` — output Step 3
- `cfg: DadConfig` — config (thresholds)
- `feedback_state: FeedbackState` — z Step 7 (learned context)

## Outputs

- `dict`:
  - `vote: float` — aggregate (ANSWER / total)
  - `verdicts: list[dict]` — per-row decision
  - `abstain_details: list[dict]` — dla raportu "Review top 5"

## Per-row decision tree

```
FOR EACH row IN rows_added:
  # Mut #29 Tiny-Critic Cheap-Router (Haiku first)
  haiku_verdict = tiny_critic.check(row, source_email)
  if haiku_verdict.confidence >= cfg.schedule.haiku_confidence_threshold:
    row.status = "ANSWER"
    continue

  # Mut #30 Three-Action Epistemic Gate (Sonnet escalation)
  gate = epistemic_gate.decide(row, source_email, feedback_history)
  row.status = gate.action  # ANSWER | ASK | ABSTAIN

  # Mut #39 Three-Signal Hallucination Vote (high-stakes only)
  if row.amount > cfg.high_stakes_pln or row.code in RARE_CODES:
    vote = three_signal_vote.run(row, source_email)
    if vote.disagreement > 1:
      row.status = "ABSTAIN"

  # Mut #44 Persona Hyperstition (roster re-check)
  if row.employee_id not in employees_roster:
    row.status = "BLOCKED"

# Aggregate
vote = ANSWER_count / total
if vote < cfg.red_team_threshold and not cfg.force:
  report_mode = "REVIEW_REQUIRED"
```

## Reuse scripts

- `C:\Users\Arek\MAXIMISEART-SEO\scripts\tiny_critic_router.py` (Mut #29, `--use-real-api`)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\epistemic_gate.py` (Mut #30, stdlib-only decision matrix)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\cross_lineage_vote.py` (Wave 6 #43 L2, 6-vote — opcjonalnie gdy `DAD_CROSS_LINEAGE_VOTE=true`)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\persona_hyperstition_scanner.py` (Mut #44)
- `C:\Users\Arek\MAXIMISEART-SEO\skills\red-team-claim-verification\SKILL.md` — Steps 0-8 template

## Floor Never Drops

Step 4 **NIE usuwa** wierszy Step 3. Tylko flaguje `ABSTAIN/ASK/BLOCKED` w kolumnie `status`. Tata widzi wiersz w Excelu + uwagi w raporcie.
