# Instrukcja — jak używać systemu

**Dla:** Tata (Arkadiusz)
**Status:** Phase 0 draft. Finalna wersja PL w Phase 5 wraz z init wizardem.

---

## Codziennie rano (3 minuty przy kawie)

1. Włącz komputer (jeśli nie był włączony — system działa sam w tle kiedy komp śpi)
2. Otwórz **Obsidian** (ikona fioletowa na pulpicie)
3. W lewym panelu kliknij folder `reports/`
4. Otwórz dzisiejszy plik: `YYYY-MM-DD.md` (dzisiejsza data)
5. Przeczytaj raport — 1 strona:
   - Podsumowanie: ile emaili, ile wierszy w Excelu
   - Per pracownik: kto co zrobił
   - **Wymagają uwagi**: system oznaczył wiersze niepewne — review te
6. Na dole strony jest pole:
   ```
   ## Feedback taty
   <wpisz tu>
   ```
7. **Jeśli wszystko OK** — wpisz `OK` i zapisz (Ctrl+S)
8. **Jeśli coś źle** — napisz krótko co poprawić, np:
   - "Jan miał kod 2 nie 1"
   - "Anna pracowała na Krańcowej 12, nie 22"
   - "Kowalski nie był dzisiaj w pracy, nie wiem skąd ten email"
9. Zapisz (Ctrl+S) — gotowe

Następnego dnia system:
- Przeczyta Twój feedback
- Zaktualizuje Excel jeśli trzeba
- Nauczy się nie powtarzać tego błędu

---

## Otwieranie Excela

Excel działa tak jak zawsze:
- **Lokalnie** — ikona na pulpicie lub w OneDrive/Fiber/
- **W przeglądarce** — na telefonie/innym kompie przez excel.office.com

System aktualizuje lokalny plik, OneDrive synchronizuje do przeglądarki automatycznie (zwykle w ciągu 30 sekund).

**⚠️ WAŻNE:** Gdy Excel jest otwarty w desktop Excel (niebieska ikona) — system wykryje i poczeka z zapisem. Jeśli zobaczysz raport "Tato zamknij Excel" — to znaczy trzeba zamknąć Excel i za 5 min system spróbuje jeszcze raz.

---

## Co jeśli coś się popsuło?

### Raport się nie pojawił rano
1. Sprawdź czy komputer był włączony o 06:30
2. Otwórz Obsidian → folder `reports/`
3. Jeśli nadal nic — zadzwoń do Maksa

### Wiadomość "System nie mógł połączyć z Gmail"
- Token Gmail wygasł (zdarza się raz na kilka tygodni)
- Otwórz PowerShell (Win+R → `powershell` → Enter)
- Wklej i Enter:
  ```
  cd C:\MAXIMISEART-Dad
  python scripts\init_wizard.py --reauth
  ```
- Kliknij w przeglądarce link i daj dostęp ponownie

### System wypełnił Excel błędnie
1. Znajdź wiersz w Excelu (kolumna G pokazuje status)
2. Popraw ręcznie komórkę
3. W dzisiejszym raporcie Obsidian wpisz co było źle:
   ```
   ## Feedback taty
   Wiersz 42 — Jan miał kod 2 nie 1, poprawiłem ręcznie
   ```
4. System się nauczy na następny raz

### "PILNE: 3 dni bez zatwierdzenia"
- System wykrył że nie czytałeś raportów 3 dni
- Przejrzyj ostatnie 3 raporty w `reports/`
- System wstrzymał uczenie się do czasu Twojego feedbacku — to bezpieczeństwo

---

## Co system zapisuje

| Folder | Co tam jest |
|--------|-------------|
| `reports/` | Dzienne raporty markdown (ty czytasz rano) |
| `pracownicy/` | Folder per każdy pracownik — maile z każdego dnia |
| `learning/` | Pamięć systemu — co się nauczył z Twojego feedbacku |
| (Excel) | W OneDrive jak zawsze |

---

## Gdzie system NIE może działać

- Nie wysyła maili pracownikom
- Nie tworzy nowych wierszy Excela bez emaila od pracownika
- Nie zatwierdza sam za Ciebie
- Nie odpowiada pracownikom (tylko czyta)

Wszystkie ważne decyzje zatwierdzasz Ty — system tylko pomaga Ci oszczędzić czas na sortowaniu maili i wpisywaniu do Excela.

---

## Kontakt

Maks — na WhatsAppie.
