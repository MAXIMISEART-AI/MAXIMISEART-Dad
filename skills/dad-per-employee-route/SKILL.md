---
name: dad-per-employee-route
description: Classify maile per pracownik + Mutation #44 Persona Hyperstition roster validation. Unknown senderzy BLOCKED. Use dla Step 2.
---

# dad-per-employee-route

**Status:** Phase 1 shipped. Implementation lives in `scripts/step2_per_employee_route.py`; Obsidian daily writes are performed by `scripts/lib/obsidian_writer.py` from the orchestrator.

## Purpose

Step 2 workflowu — grupuje emaile per pracownik, waliduje że sender jest w `employees.yaml`, loguje unknown senders jako `BLOCKED`.

## Inputs

- `emails: list[dict]` — output Step 1
- `employees_config: dict` — z `config/employees.yaml`
- `feedback_state: FeedbackState`

## Outputs

- `dict[slug -> list[email]]` — zrejestrowani pracownicy
- `list[dict]` — unknown_senders (do raportu dla taty, status=BLOCKED)
- File writes: `vault/pracownicy/{slug}/YYYY-MM-DD.md` per-employee daily log

## Algorithm (Mutation #44 check)

1. For each email:
   - Match `email.from` against `employees.yaml.employees[].email` (exact, case-insensitive)
   - Check `aliases[]` field jako fallback
2. Match → append do routed[slug]
3. No match → append do unknown_senders + flag HIGH severity
4. If any unknown senders → do NOT silently drop — surfacuj w Step 6 raport

## Anti-patterns

- ❌ Fuzzy matching imion w domain part emaila ("jk@" → "Jan Kowalski"?) — za ryzykowne
- ❌ Auto-add nowego pracownika do `employees.yaml` — to SOURCE OF TRUTH taty, tylko on decyduje
- ❌ Silent skip unknown — MUSI być widoczne w raporcie (Rule #1 Floor Never Drops)

## Reuse

- `MAXIMISEART-SEO/scripts/persona_hyperstition_scanner.py` — adaptacja `validate_entity_exists` pattern
- `~/.claude/skills/brain-ingest-review/SKILL.md` — section-tiered routing pattern
