# Red Team Spec — Step 4 self-verify

**Status:** Phase 3 shipped as deterministic STUB in `scripts/step4_self_verify.py`. Real API mode remains gated.

## Cel

Step 4 jest bramą między Excel-write (Step 3) a report-send (Step 6). Dla każdego appended Excel row waliduje: czy dane w wierszu są consistent z source emailem + feedback history? Czy pracownik istnieje w roster? Czy kod nie halucynowany?

**Bez Step 4 = agent halucynuje wiersze → tata ma brudny Excel → fail learning loop.**

## Mutacje wykorzystane

| Mutation | Layer | Cost | When |
|----------|-------|------|------|
| #29 Tiny-Critic Cheap-Router | 1 (first gate) | ~$0.001/row (Haiku) | Każdy row — fast check |
| #30 Three-Action Epistemic Gate | 2 (escalation) | ~$0.01/row (Sonnet) | Gdy Haiku confidence < 0.9 |
| #39 Three-Signal Hallucination Vote | 3 (high-stakes) | ~$0.03/row (3× Sonnet) | Gdy amount > threshold OR rare code |
| #44 Persona Hyperstition | Layer 0 (pre-Step 3) | $0 (stdlib) | Sender NOT in employees.yaml → BLOCKED |
| #43 Cross-Lineage Vote | 4 (optional) | ~$0.05/row | Gdy `DAD_CROSS_LINEAGE_VOTE=true` |
| #46 Approval Fatigue Monitor | meta | $0 (stdlib) | Aggregate daily — Step 7 integration |

## Per-row decision tree

```python
def verify_row(row, source_email, feedback_history, cfg):
    # Layer 0: Persona check (Mut #44) — already done w Step 2, re-check dla safety
    if row.employee_id not in cfg.employees.roster:
        return Verdict(status="BLOCKED", rationale="Unknown sender")

    # Layer 1: Tiny-Critic (Mut #29)
    haiku = tiny_critic.check(
        row=row,
        source=source_email,
        feedback_context=feedback_history.for_employee(row.employee_id),
    )
    if haiku.confidence >= 0.9:
        return Verdict(status="ANSWER", rationale=haiku.rationale)

    # Layer 2: Epistemic Gate (Mut #30)
    gate = epistemic_gate.decide(
        row=row,
        source=source_email,
        feedback_context=feedback_history,
    )
    # gate.action ∈ {ANSWER, ASK, ABSTAIN}

    # Layer 3: High-stakes triple-vote (Mut #39)
    is_high_stakes = (
        row.amount > cfg.high_stakes_pln
        or row.code in cfg.rare_codes
        or gate.action == "ASK"
    )
    if is_high_stakes:
        triple = three_signal_vote.run(row, source_email)
        if triple.disagreement > 1:
            return Verdict(status="ABSTAIN", rationale=triple.breakdown)

    return Verdict(status=gate.action, rationale=gate.rationale)
```

## Aggregate gate

```python
vote_ratio = sum(1 for v in verdicts if v.status == "ANSWER") / len(verdicts)

if vote_ratio >= cfg.red_team_threshold:  # 0.66 default
    proceed_to_step_5()
else:
    report_mode = "REVIEW_REQUIRED"
    top_5_uncertain = sorted(
        [v for v in verdicts if v.status in ("ASK", "ABSTAIN")],
        key=lambda v: v.confidence,
    )[:5]
    generate_review_report(top_5_uncertain)
```

## Floor Never Drops

**Step 4 NIGDY nie usuwa wierszy Step 3.** Tylko flaguje w kolumnie `status` Excela:

- `ANSWER` — confident, tata nie musi review
- `ASK` — niepewny, tata zdecyduje w feedback polu raportu
- `ABSTAIN` — system odmawia odpowiedzi, tata ręcznie uzupełni
- `BLOCKED` — persona hyperstition hit, NIE zapisane do Excela

Tata widzi wszystkie 4 statusy w kolumnie G Excela + szczegóły w raporcie markdown.

## Reuse skrypty (MAXIMISEART-SEO)

- `scripts/tiny_critic_router.py` — Mut #29 z flagą `--use-real-api`
- `scripts/epistemic_gate.py` — Mut #30 stdlib-only
- `scripts/cross_lineage_vote.py` — Wave 6 #43 L2 (opt-in)
- `scripts/persona_hyperstition_scanner.py` — Mut #44

## Testing strategy

### Unit tests
- `tests/test_step4_self_verify.py` — każdy fixture email z `_fixture_expected.red_team_status`
- Fixture `02_ambiguous_code.json` MUST result `ASK`
- Fixture `03_unknown_sender.json` MUST result `BLOCKED`

### Integration test
- Maks wysyła 5 test-emaili z intentionally bad data (wrong employee, wrong code)
- Expected: 1× ANSWER, 2× ASK, 2× ABSTAIN lub BLOCKED
- Aggregate vote < 0.66 → raport REVIEW_REQUIRED

## Cost breakdown (daily)

- 50 emaili → 50 rows
- Tier 1 Haiku: 50 × $0.001 = $0.05
- Tier 2 Sonnet (10% escalate): 5 × $0.01 = $0.05
- Tier 3 Triple-vote (5% high-stakes): 2 × $0.03 = $0.06
- **Total: ~$0.16 per day = ~5 PLN/miesiąc**

Pod cap w `schedule.yaml: max_api_cost_pln_per_day: 5.0`.
