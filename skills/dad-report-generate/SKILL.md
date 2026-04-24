---
name: dad-report-generate
description: Generuje 1-stronicowy markdown raport PL dla taty w Obsidian. Polski ton, zero AI mention, injectuje fatigue warning gdy CRITICAL. Use dla Step 6.
---

# dad-report-generate

**Status:** Phase 0 stub. Phase 3 target: 2h effort.

## Purpose

Step 6 — tworzy 1-page markdown raport z podsumowaniem co zrobił system + wierszami REVIEW wymagającymi tata attention + polem `## Feedback taty`. To jedyny tata-facing artifact poza samym Excelem.

## Output path

`runtime/vault/reports/YYYY-MM-DD.md`

## Structure

```markdown
---
date: 2026-04-24
emails_processed: 12
excel_rows_added: 8
red_team_vote: 3/3
abstain_entries: 1
fatigue_level: GREEN
status: AWAITING_FEEDBACK
---

# Raport dzienny — 2026-04-24 (środa)

## Podsumowanie
- 12 emaili przetworzonych
- 8 wierszy dopisanych do Excela
- 5 pracowników aktywnych dzisiaj

## Per pracownik
| Pracownik | Emaile | Wiersze | Kody |
|-----------|--------|---------|------|
| Jan Kowalski | 3 | 5 | 1×3, 2×2 |
| Anna Nowak | 1 | 2 | 1×1, 5×1 |

## Wymagają uwagi
### Wiersz 42 — Jan Kowalski
- Niepewny kod: email mówi "spaw przy Krańcowej", ale Jan czasem używa "spaw" na kod 1 czasem 2
- Sugestia: kod 2 (per feedback 2026-04-20)
- Źródło: email-id 18f2a3b4...

## Feedback taty
<!-- Wpisz tu 'OK' jeśli wszystko się zgadza, albo opisz co poprawić -->

## Statystyki
- Seria zatwierdzeń: 3 dni z rzędu
- Poziom zmęczenia zatwierdzaniem: GREEN
- Ostatni error-fix: 2026-04-22 (Jan kod 2 vs 1)
```

## Constraints

- ZERO mention "Claude", "Anthropic", "AI", "LLM" (CLAUDE.md anti-pattern)
- Polski formalny ton
- ≤400 linii markdown (1 strona)
- Frontmatter jako structured data (Obsidian Bases-compatible)
- Inject fatigue warning gdy Mut #46 CRITICAL → header PILNE banner

## Injected states

- Empty mailbox day → raport minimal ("0 emaili, 0 dopisanych wierszy. System działa poprawnie. OK?")
- Red Team REVIEW_REQUIRED → "Wymagają uwagi" section expanded do top-5
- Fatigue CRITICAL → banner pre-header "PILNE: 3 dni bez zatwierdzenia. Przeglądnij ostatnie 3 raporty."
- OAuth expired → raport "System nie mógł połączyć z Gmail. Uruchom ponownie wizard: `python init_wizard.py --reauth`"
