# Instrukcja codzienna

**Dla:** Tata

## Codziennie rano

1. Otwórz Obsidian.
2. Wejdź w folder `reports`.
3. Otwórz dzisiejszy plik `YYYY-MM-DD.md`.
4. Przeczytaj podsumowanie.
5. Na dole znajdź sekcję:

   ```text
   ## Feedback taty
   ```

6. Jeśli wszystko się zgadza, wpisz `OK`.
7. Jeśli coś trzeba poprawić, napisz krótko co jest źle, np.:
   - `Jan miał kod 2, nie 1`
   - `Krańcowa 12, nie Krańcowa 22`
   - `Tego pracownika nie ma na liście`
8. Zapisz plik.

## Excel

Excel działa normalnie. System dopisuje nowe dane tylko do arkusza:

`MAXIMISEART_DAILY_APPEND`

Dotychczasowe arkusze i formuły zostają bez zmian.

Jeśli Excel jest otwarty na komputerze, system może wstrzymać zapis. Wtedy zamknij plik Excela i uruchom workflow ponownie albo poczekaj na kolejne uruchomienie.

## Gdy rano nie ma raportu

1. Sprawdź, czy komputer był włączony o zaplanowanej godzinie.
2. Otwórz Obsidian i sprawdź folder `reports`.
3. Jeśli raportu nadal nie ma, daj znać Maksowi.

## Gdy Gmail prosi o ponowny dostęp

Powiedz Maksowi. Trzeba uruchomić:

```powershell
python scripts\init_wizard.py --reauth
```

## Gdy dzień jest pusty

Raport `0 emaili` oznacza, że skrzynka była pusta. To nie jest awaria.

## Gdy pojawi się nieznany pracownik

Raport pokaże nadawcę w sekcji wymagającej uwagi. Maks dopisze pracownika do listy i uruchomi system ponownie.

## Gdy pojawi się nieznany kod pracy

Raport oznaczy wpis statusem `ASK`. W feedbacku napisz, jaki kod powinien być użyty.
