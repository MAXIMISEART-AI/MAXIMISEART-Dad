"""Step 4 — Red Team self-verify (Mutation #29 / #30 / #39 / #44).

Phase 0 stub. Phase 3 implementation:

Per-row decision tree:
  1. Mut #29 Tiny-Critic Cheap-Router — Haiku check. conf >= 0.9 → ANSWER, skip rest
  2. Mut #30 Three-Action Epistemic Gate — Sonnet escalation. ANSWER | ASK | ABSTAIN
  3. Mut #39 Three-Signal Hallucination Vote — IF high-stakes (amount > threshold
     or rare code), triple-vote. disagreement > 1 → ABSTAIN
  4. Mut #44 Persona Hyperstition — roster validation (already done Step 2,
     re-check dla safety)

Aggregate gate:
  (ANSWER / total) < threshold → REVIEW_REQUIRED raport mode

Reuse scripts:
  - MAXIMISEART-SEO/scripts/epistemic_gate.py (Mut #30)
  - MAXIMISEART-SEO/scripts/tiny_critic_router.py (Mut #29, --use-real-api)
  - MAXIMISEART-SEO/scripts/cross_lineage_vote.py (Wave 6 #43 L2 — opcjonalnie)

Reuse SKILL adaptation:
  - MAXIMISEART-SEO/skills/red-team-claim-verification/SKILL.md Steps 0-8
"""
from __future__ import annotations


def verify(emails: list[dict], rows_added: list[dict], cfg) -> dict:
    """Returns {vote: float, verdicts: [row_status], abstain_details: [...]}."""
    raise NotImplementedError("Phase 3: wire Mut #29/#30/#39/#44")
