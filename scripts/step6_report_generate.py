"""Step 6 — Generate 1-pager markdown raport PL dla taty.

Phase 0 stub. Phase 3 implementation:

Output: vault/reports/YYYY-MM-DD.md

Sections (polski, tata-friendly):
  # Raport dzienny — YYYY-MM-DD (dzień-tygodnia)
  frontmatter: {date, emails_processed, excel_rows_added, red_team_vote,
                abstain_entries, fatigue_level, status: AWAITING_FEEDBACK}

  ## Podsumowanie
  - N emaili przetworzonych
  - N wierszy dopisanych do Excela
  - K pracowników aktywnych

  ## Per pracownik
  - Jan Kowalski: 3 emaile, 5 wierszy (kod 1 x3, kod 2 x2)
  - Anna Nowak: 1 email, 2 wiersze

  ## Wymagają uwagi (REVIEW)
  - Wiersz #42: ambiguous — email od Jana nie jasny czy kod 1 czy 2
  - Wiersz #58: nowy kod "7" — nie ma w code_mapping.yaml

  ## Feedback taty
  <pole do wypełnienia — OK lub komentarz>

  ## Statystyki
  - Approval streak: 3 dni z rzędu
  - Fatigue level: GREEN

Constraints:
- ZERO mention "Claude", "Anthropic", "AI" (CLAUDE.md Rule anti-pattern)
- Polski formalny ton
- Jedna strona max (≤400 linii markdown)
- Injected fatigue warning gdy Mut #46 CRITICAL
"""
from __future__ import annotations


def build(cfg, date: str, rows_added: list[dict], verdict: dict, feedback_state=None) -> str:
    """Returns path do wygenerowanego raportu."""
    raise NotImplementedError("Phase 3: implement raport generator PL")
