---
name: dad-code-mapping
description: Fuzzy match email text → kod pracy ("1"/"2"/...) z confidence score + feedback history. Używany w Step 3 jako Haiku-first classifier.
---

# dad-code-mapping

**Status:** Phase 0 stub. Phase 2 target: 3h effort.

## Purpose

Rdzeń Step 3 Excel extraction — dla fragmentu tekstu z maila pracownika (np. "zrobiłem spaw przy Krańcowej 12") zwraca kod pracy z `config/code_mapping.yaml` + confidence.

## Inputs

- `text: str` — fragment emaila
- `code_mapping: dict` — z `config/code_mapping.yaml`
- `employee_slug: str` — dla per-employee patterns (feedback history)
- `feedback_state: FeedbackState` — learned corrections

## Outputs

- `dict`:
  - `code: int | None` — matched code lub None jeśli ambiguous
  - `confidence: float` — 0.0-1.0
  - `rationale: str` — krótkie uzasadnienie (dla raportu)
  - `alternatives: list[dict]` — top-3 candidates

## Algorithm (Mutation #29 Tiny-Critic pattern)

1. **Keyword match** (stdlib, szybki):
   - Dla każdego kodu sprawdź `keywords[]` (case-insensitive regex)
   - Score = (matched_keywords / total_keywords_in_code)
2. **Feedback history override**:
   - Jeśli `feedback_state` ma entry "pracownik X używa 'spaw' = kod 2" → priorytet
3. **Haiku classifier** (jeśli score < 0.9):
   - Prompt: "Klasyfikuj pracę: {text}. Kody: {code_mapping_summary}. Zwróć JSON {code, confidence, rationale}."
   - Model: `claude-haiku-4-5-20251001`
4. **Confidence threshold**:
   - conf >= 0.9 → return ANSWER
   - 0.7 <= conf < 0.9 → return ASK (ambiguous)
   - conf < 0.7 → return ABSTAIN + surface alternatives

## Reuse

- `C:\Users\Arek\MAXIMISEART-SEO\scripts\tiny_critic_router.py` — Haiku-first classification pattern
- `C:\Users\Arek\MAXIMISEART-SEO\scripts\epistemic_gate.py` — Three-Action decision matrix

## Cost

- Keyword match: $0 (stdlib)
- Haiku call: ~$0.001 per email (input ~500 tokens + output ~50 tokens)
- Daily budget: ~$0.05 (50 emaili, 10% escalate do Haiku)

## Floor Never Drops

- Nigdy nie "force" kod gdy ambiguous — lepiej ASK niż wrong code w Excelu (Rule #15 ABSTAIN > hallucinate)
- Keyword match pozostaje primary — Haiku tylko escalation
