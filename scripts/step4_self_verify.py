"""Step 4 — Red Team self-verify.

STUB mode (default): deterministic mock verdicts, zero API cost.
Real API mode: post-first-klient gated (`DAD_USE_REAL_API=true`).

Aggregate gate per Rule #2: (ANSWER / total) >= threshold → proceed to Step 5.
Inaczej → REVIEW_REQUIRED raport mode.

Phase 1 note: w Phase 1 wejście to `routed_emails` dict (brak wierszy Excela jeszcze).
Verdict aggregate na poziomie emaili — każdy email = 1 "row-equivalent".
Phase 2+ wymiana na rows_added gdy Excel integration.

Reuse patterns (structural, NIE copy):
- MAXIMISEART-SEO/scripts/epistemic_gate.py (Mut #30 Three-Action Gate)
- MAXIMISEART-SEO/scripts/tiny_critic_router.py (Mut #29 Tiny-Critic)
- MAXIMISEART-SEO/scripts/persona_hyperstition_scanner.py (Mut #44)
"""
from __future__ import annotations

import hashlib


def verify(
    routed: dict[str, list[dict]],
    unknown_senders: list[dict],
    cfg,
    use_real_api: bool = False,
) -> dict:
    """Red Team vote per email-entry. STUB mode deterministic, no API calls.

    Args:
        routed: {slug: [emails]} z Step 2
        unknown_senders: BLOCKED Mut #44 (już odrzucone)
        cfg: DadConfig (thresholds)
        use_real_api: True → Haiku/Sonnet (post-first-klient); False → STUB (deterministic)

    Returns:
        dict z polami: total_count, answered_count, vote_ratio,
        verdicts (per-email list), top_uncertain, report_mode
    """
    if use_real_api:
        raise NotImplementedError(
            "Real Claude API verification — gated post-first-klient + Maks mandate. "
            "Reuse: MAXIMISEART-SEO/scripts/epistemic_gate.py Mutation #30."
        )

    threshold = cfg.red_team_threshold if cfg else 0.66
    verdicts = []
    row_counter = 0

    for slug, emails in routed.items():
        for email in emails:
            row_counter += 1
            row_verdict = _stub_verdict(email, slug)
            row_verdict["row_index"] = row_counter
            verdicts.append(row_verdict)

    for email in unknown_senders:
        row_counter += 1
        verdicts.append({
            "row_index": row_counter,
            "employee_name": "(nieznany)",
            "employee_slug": None,
            "email_id": email.get("id", ""),
            "subject": email.get("subject", ""),
            "status": "BLOCKED",
            "confidence": 1.0,
            "rationale": "Nadawca spoza listy pracowników (Mut #44 Persona Hyperstition).",
            "layer": "persona-hyperstition",
        })

    total = len(verdicts)
    answered = sum(1 for v in verdicts if v["status"] == "ANSWER")
    vote_ratio = answered / total if total > 0 else 1.0

    top_uncertain = sorted(
        [v for v in verdicts if v["status"] in ("ASK", "ABSTAIN", "BLOCKED")],
        key=lambda v: v.get("confidence", 0.0),
    )[:5]

    report_mode = "OK" if vote_ratio >= threshold else "REVIEW_REQUIRED"

    return {
        "total_count": total,
        "answered_count": answered,
        "vote_ratio": vote_ratio,
        "threshold": threshold,
        "verdicts": verdicts,
        "top_uncertain": top_uncertain,
        "report_mode": report_mode,
        "stub_mode": True,
    }


def _stub_verdict(email: dict, slug: str) -> dict:
    """Deterministic STUB verdict based on SHA256(email.id + slug).

    Produces consistent ANSWER/ASK/ABSTAIN distribution dla testów + demos.
    - 70% ANSWER (normal flow)
    - 20% ASK (ambiguous)
    - 10% ABSTAIN (high-risk)
    """
    seed_str = f"{slug}:{email.get('id', '')}:{email.get('subject', '')}"
    digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
    roll = digest[0] / 255.0

    if roll < 0.70:
        status = "ANSWER"
        confidence = 0.92 + (digest[1] / 255.0) * 0.07
        rationale = "Treść maila jest jednoznaczna, pattern rozpoznany."
    elif roll < 0.90:
        status = "ASK"
        confidence = 0.60 + (digest[1] / 255.0) * 0.15
        rationale = "Treść wymaga potwierdzenia — nietypowy skrót lub niejasny kontekst."
    else:
        status = "ABSTAIN"
        confidence = 0.30 + (digest[1] / 255.0) * 0.20
        rationale = "Niski poziom pewności — zalecana ręczna weryfikacja."

    return {
        "row_index": None,
        "employee_name": _guess_name_from_slug(slug),
        "employee_slug": slug,
        "email_id": email.get("id", ""),
        "subject": email.get("subject", ""),
        "status": status,
        "confidence": round(confidence, 3),
        "rationale": rationale,
        "layer": "stub-deterministic",
    }


def _guess_name_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))
