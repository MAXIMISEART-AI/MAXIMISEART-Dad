# MAXIMISEART-Dad

Automatyzacja codziennych raportów z maili pracowników do Excela — dla wykonawców FTTH.

---

## Co to robi

Codziennie rano o 06:30:

1. Czyta maile z Gmaila (raporty dzienne pracowników)
2. Sortuje per pracownik do lokalnego Obsidian vault
3. Ekstraktuje dane (ilość pracy, kody, lokacje) do Excela
4. Sprawdza własną pracę (Red Team self-verify)
5. Aktualizuje Obsidian z podsumowaniem
6. Generuje 1-stronicowy raport w Obsidian
7. Czeka na Twoje zatwierdzenie lub feedback

Ty otwierasz Obsidian rano, czytasz raport, klikasz OK lub piszesz co poprawić. Następnego dnia system się uczy i nie powtarza błędu.

---

## Instalacja (u taty — one-time)

**Wymagania:**
- Windows 10/11
- Python 3.11+
- Konto Anthropic (Pro lub Max) + Claude Code zainstalowany
- Obsidian zainstalowany
- Excel + OneDrive/Microsoft 365

**Kroki:**

1. Zainstaluj Python 3.11+ z [python.org](https://python.org)
2. Otwórz PowerShell w katalogu gdzie chcesz trzymać system (np. `C:\MAXIMISEART-Dad\`)
3. Sklonuj repo:
   ```powershell
   git clone https://github.com/<USER>/MAXIMISEART-Dad.git
   cd MAXIMISEART-Dad
   ```
4. Utwórz środowisko Python:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
5. Uruchom wizard instalacyjny:
   ```powershell
   python scripts\init_wizard.py
   ```
   Wizard poprowadzi przez:
   - Wskazanie pliku Excel
   - Ustawienie godziny daily run
   - Autoryzację Gmail (otworzy przeglądarkę)
   - Smoke test
   - Instalację Task Scheduler

Po wizard: następnego dnia o 06:30 pierwszy raport pojawi się w Obsidian (folder `reports/`).

---

## Codzienne użycie (tata)

**Rano przy kawie:**
1. Otwórz Obsidian
2. Folder `reports/` → otwórz dzisiejszy plik `YYYY-MM-DD.md`
3. Przeczytaj 1 stronę
4. Na dole jest pole `## Feedback taty`:
   - Jeśli wszystko OK → wpisz `OK` i zapisz
   - Jeśli coś źle → opisz (np. "Jan miał kod 2 nie 1")

System następnego dnia przeczyta Twój feedback i nie powtórzy tego błędu.

---

## Struktura projektu

Szczegóły w `docs/architecture.md`.

## Dla programisty (Maks)

Szczegóły w `CLAUDE.md` (rules + D-decisions) i `docs/`:
- `architecture.md` — high-level flow
- `red-team-spec.md` — self-verify Step 4
- `learning-loop-spec.md` — feedback → pattern propagation
- `tata-instrukcja.md` — manual PL dla end-user

## Licencja

Private — zero dystrybucji bez zgody. Wszystkie dane pracowników = RODO.
