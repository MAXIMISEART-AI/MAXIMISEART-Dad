"""Step 7 — Feedback ingest (learning loop foundation).

Uruchamia się NA POCZĄTKU każdego daily run (PRZED Step 1).
Czyta wczorajszy raport, ekstraktuje feedback taty, updates learning files.

Phase 0 stub. Phase 4 implementation:

Algorithm:
  1. Read runtime/reports/YESTERDAY.md
  2. Extract section "## Feedback taty"
  3. If empty → log_streak_day(cfg.approval_log) dla Mut #46 fatigue tracking
     return FeedbackState.empty()
  4. Parse feedback_block via Haiku (tani classifier):
     → [{employee_id, claim, correction_type, confidence}, ...]
  5. Append to runtime/learning/feedback-log.jsonl (append-only, timestamped)
  6. For each correction:
     - Update vault/pracownicy/{slug}/_profil.md (Key Patterns)
     - Update vault/learning/known-errors.md ("Nie powtarzaj X")
  7. Return FeedbackState(corrections, approval_streak)

FeedbackState wstrzykiwane jako CONTEXT do Step 2/3/4 prompts:
  "KONTEKST Z FEEDBACK TATY:
   - Jan Kowalski: skrót 'spaw' = kod 2 (NIE kod 1) [confirmed 2026-04-22]"

Reuse: MAXIMISEART-SEO/scripts/approval_log.py + approval_fatigue_detector.py (Mut #46)
Reuse pattern: MAXIMISEART-Brain/raw/queries/2026-04-18-rule-5-auto-learn-post-delivery.md
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeedbackState:
    corrections: list[dict] = field(default_factory=list)
    approval_streak: int = 0
    fatigue_level: str = "GREEN"   # GREEN | YELLOW | RED | CRITICAL

    @classmethod
    def empty(cls) -> "FeedbackState":
        return cls()


def load_previous_feedback(cfg, today: str) -> FeedbackState:
    raise NotImplementedError("Phase 4: implement feedback parser + learning updates")
