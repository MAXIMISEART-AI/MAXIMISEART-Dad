# Learning Loop Spec — Step 7 feedback propagation

**Status:** Phase 4 shipped as deterministic parser + learning loop foundation in `scripts/step7_feedback_ingest.py`. Real API parsing remains gated.

## Problem

Tata co rano daje feedback (1 zdanie w polu `## Feedback taty`). Bez learning loopu system powtarza te same błędy. Z loopem każdy feedback per-pracownik patterns content podnosi quality następnego raportu.

## Rule #5 Auto-Learn Post-Delivery

Wzór z MAXIMISEART-SEO: każdy tata-approved/corrected raport **auto-propaguje** feedback do 3 warstw (agent czyta je PRZED następnym run):

### Layer 1: Per-pracownik rich profile
- Path: `runtime/vault/pracownicy/{slug}/_profil.md`
- Section: `## Key Patterns` (append-only)
- Treść: "Jan Kowalski używa skrótu 'spaw' = kod 2 (NIE kod 1) [confirmed 2026-04-22]"
- Wzór paradygmatu: `MAXIMISEART-Brain/raw/queries/2026-04-19-per-expert-rich-profile-paradigm.md`

### Layer 2: Known errors catalog
- Path: `runtime/vault/learning/known-errors.md`
- Format: timestamped entries "Nie powtarzaj X w kontekście Y"
- Global — nie per-pracownik, dla cross-employee patterns
- Przykład: "Błąd dat: kod 12 sugerowany jako 1+2 — Jan pisze 'kod 12' = specyficzny typ instalacji"

### Layer 3: Approval log (Mut #46 fatigue)
- Path: `runtime/state/approval-log.jsonl`
- Format: JSONL per-day z fieldami `{ts, decision, context, item_hash, duration_sec}`
- Decision enum: `APPROVE | CORRECT | NO_FEEDBACK | AUTO_SKIP`
- Uzywany przez `approval_fatigue_detector.py` dla CRITICAL alerts

## Step 7 algorithm

```python
def load_previous_feedback(cfg: DadConfig, today: str) -> FeedbackState:
    yesterday = (datetime.fromisoformat(today).date() - timedelta(days=1)).isoformat()
    yesterday_report = cfg.reports_dir / f"{yesterday}.md"

    if not yesterday_report.exists():
        return FeedbackState.empty()

    feedback_block = extract_section(yesterday_report.read_text("utf-8"), "## Feedback taty")

    if not feedback_block.strip() or feedback_block.strip().lower() in ("ok", "ok.", ""):
        # Either approved silently or empty
        streak = approval_log.increment_streak(cfg.state_dir / "approval-log.jsonl")
        if streak >= cfg.fatigue_critical_days:
            return FeedbackState(approval_streak=streak, fatigue_level="CRITICAL")
        return FeedbackState(approval_streak=streak, fatigue_level="GREEN")

    # Parse via Haiku
    parsed = anthropic_parse_feedback(
        feedback_block,
        prompt_cache_breakpoints=["system", "context"],  # Wave 1 Rohit caching
    )
    # parsed: [{employee_id, claim, correction_type, confidence}, ...]

    # Append to JSONL (Floor Never Drops — append-only)
    append_jsonl(cfg.learning_dir / "feedback-log.jsonl", {
        "ts": datetime.now(ZoneInfo("Europe/Warsaw")).isoformat(),
        "report_date": yesterday,
        "raw": feedback_block,
        "parsed": parsed,
    })

    # Update Layer 1 — per-employee profiles
    for correction in parsed:
        if correction["confidence"] >= 0.7:
            update_employee_patterns(
                cfg.vault_path / "pracownicy" / correction["employee_id"] / "_profil.md",
                correction,
            )

    # Update Layer 2 — known errors
    update_known_errors(cfg.vault_path / "learning" / "known-errors.md", parsed)

    # Mut #46 — log corrections separately
    approval_log.log(
        cfg.state_dir / "approval-log.jsonl",
        decision="CORRECT" if parsed else "APPROVE",
        context="daily_report",
        item_hash=sha256(feedback_block),
    )

    return FeedbackState(
        corrections=parsed,
        approval_streak=0,  # reset streak on actual feedback
        fatigue_level="GREEN",
    )
```

## Injection jako CONTEXT

W Step 2/3/4 prompts, `FeedbackState` jest injected jako prefix:

```
KONTEKST Z FEEDBACK TATY (ostatnie 30 dni):
- Jan Kowalski: skrót "spaw" = kod 2 (NIE kod 1) [2026-04-22]
- Anna Nowak: "bl.12" = "blok 12" [2026-04-20]
- NIGDY nie halucynuj pracownika spoza employees.yaml
- Kody rzadkie (7, 8, 9) wymagają dokładnej weryfikacji — tata historycznie łapie je 3/3 razy

PROCEED WITH CAUTION on these patterns.
```

## Prompt caching (Wave 1 Rohit)

Feedback context rośnie (30-90 dni x 5-10 korekcji per day). Cache:

- **System prompt** (pattern instructions) — cache 2 breakpoints
- **Feedback context** (static per-day) — cache 1 breakpoint
- **Dynamic row claim** — no cache

Expected cache hit rate: ~70% po 2 tygodniach. Cost reduction: ~40%.

## Confidence handling

| Confidence | Action |
|-----------|--------|
| >= 0.9 | Auto-apply do Layer 1 + Layer 2 |
| 0.7-0.9 | Auto-apply ALE log jako "soft" w JSONL |
| < 0.7 | NIE apply. Surface "Niejasny feedback" w NEXT-DAY raporcie jako clarification ASK |

Rule #3 Human in the Loop: niejasny feedback = ASK clarification, NIGDY silent interpretation.

## Fatigue states (Mut #46)

| State | Trigger | Action |
|-------|---------|--------|
| GREEN | Daily feedback OK | Normal operation |
| YELLOW | 2 dni bez feedback | Raport header: "Zauważyłem 2 dni bez Twojego feedback" |
| RED | 2 dni + approve-rate > 80% | Suggest batch review weekend |
| CRITICAL | 3 dni bez feedback | Auto-suspend learning updates + CRITICAL banner raport |

CRITICAL trigger = system NIE robi niczego novel do czasu tata review. Continues core pipeline ale:
- NIE updatuje Layer 1/2 patterns
- Raport zawiera tylko "Pilne: zatwierdź ostatnie 3 raporty"
- Excel update pauses (rows written but status=BLOCKED)

## Testing (Phase 4)

### Unit
- `tests/test_step7_feedback_ingest.py`:
  - Empty feedback → streak++
  - "OK" → streak=0, no corrections
  - "Jan miał kod 2 nie 1" → parsed correction confidence > 0.9
  - 3 days streak → CRITICAL state

### Integration
- Dzień 1: tata daje feedback "Jan spaw = kod 2"
- Dzień 2: agent przetwarza maila Jana z "spaw przy Krańcowej"
- Expected: Step 3 used kod 2 (NIE 1) z rationale "per feedback 2026-04-22"
- Verify: `_profil.md` ma Pattern entry + `known-errors.md` ma "Nie pomyl 'spaw' Jan = kod 2"

## Reuse

- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_log.py` (Mut #46 L1)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_fatigue_detector.py` (Mut #46 L2)
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\approval_health_report.py` (Mut #46 L3)
- Pattern: `MAXIMISEART-Brain/raw/queries/2026-04-18-rule-5-auto-learn-post-delivery.md`
- Pattern: `MAXIMISEART-Brain/raw/queries/2026-04-19-per-expert-rich-profile-paradigm.md`
