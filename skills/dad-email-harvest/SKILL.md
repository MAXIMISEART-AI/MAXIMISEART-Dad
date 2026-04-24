---
name: dad-email-harvest
description: Harvest pracownicy Gmail emaili za dzień + normalizacja polskich znaków. Use dla Step 1 w daily_workflow.py. Phase 1 implementation.
---

# dad-email-harvest

**Status:** Phase 0 stub. Phase 1 target: 2h effort.

## Purpose

Step 1 workflowu MAXIMISEART-Dad — czyta Gmail taty przez MCP, normalizuje polskie znaki, zapisuje do JSONL dla downstream steps.

## Inputs

- `cfg: DadConfig` — runtime config z `scripts/lib/config.py`
- `date: str` — YYYY-MM-DD, zakres harvest window (schedule.harvest_lookback_hours)
- `feedback_state: FeedbackState` — opcjonalny context z Step 7

## Outputs

- `runtime/state/raw/emails-YYYY-MM-DD.jsonl` — append-only
  - Format per email: `{id, from, to, subject, body_text, received_at_iso, attachments_count, labels}`
- Return value: `list[dict]` normalized emails

## Algorithm

1. Load OAuth token z `cfg.oauth_token_path`
2. Gmail API `users.messages.list(q='newer_than:1d label:inbox')`
3. For each message_id → `users.messages.get(format=full)`
4. Extract body z multipart MIME (prefer text/plain, fallback text/html → strip tags)
5. Normalize UTF-8 + polskie znaki (NFC, strip BOM)
6. Append to JSONL

## Fallback modes

- OAuth token expired → write `state/ALERT-oauth-expired.md` + exit 2
- Rate limit 429 → exponential backoff (2/4/8s) + cache results
- Empty list → return `[]`, orchestrator handles graceful skip (Rule #7)

## Red Team / MIR

- Nie halucynuj maili — tylko to co zwraca API
- Deduplication via `id` (Gmail message-id jest unique)
- Attachments count only — binary payloads NIE są czytane (privacy + RODO)

## Reuse

- `mcp__claude_ai_Gmail__authenticate` + `mcp__claude_ai_Gmail__complete_authentication` MCP tools
- `google-api-python-client` jeśli MCP insufficient (bypass path)
