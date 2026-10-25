# ADR 0019: Uporządkowanie INTERMAX zmienia Rejestr zleceń

## Status

Zaakceptowana (2026-10-25, grilling z Maksem i tatą). Zmienia zasadę ze
słownika, że procesy Rejestr zleceń tylko czytają.

## Kontekst

Tata albo jego pracownik kopiuje co dzień zlecenia następnego dnia z aplikacji
firmowej, do której narzędzie nie ma dostępu, i wkleja je na dół INTERMAX
(Rejestru zleceń). Wklejone Surowe zlecenia mają wygląd z aplikacji (Roboto 4,
białe i szare tła), pierwszy wiersz przesunięty o dwie kolumny w lewo i
zlecenia Wykonawcy nieułożone po godzinie. Tata porządkuje je dziś ręcznie,
zanim pracownicy dopiszą resztę. Rejestr to jedyne źródło prawdy o zleceniach
od 2021 roku: ~42 tys. wierszy, cztery arkusze, około 6,5 MB, w OneDrive.

## Decyzja

- **Uporządkowanie INTERMAX to trzeci proces** z tym samym kontraktem co
  Przygotowanie pliku zbiorczego i Przebieg rozliczeń (etapy, Komunikaty,
  Zatrzymania, Logi Uruchomienia, Skrypt dla maszyn). Nie należy do okresu, więc
  w Centrum rozliczeń ma własną kartę.
- **Zmienia tylko Surowe zlecenia**: blok na dole arkusza zleceń z wyglądem
  z aplikacji. Reszta Rejestru, także kolumny za `UWAGI`, zostaje bajt w bajt.
  Zapis podmienia tylko te wiersze w XML arkusza, tak jak zapis Rozliczenia
  pracownika w [ADR 0008](0008-zapis-rozliczenia-pracownika-przez-podmiane-wierszy-danych.md),
  a nie wczytuje i nie zapisuje całego skoroszytu w openpyxl.
- **Przed podmianą narzędzie sprawdza swój zapis.** Plik tymczasowy obok
  INTERMAX zostaje otwarty jeszcze raz i porównany z oryginałem: poza Surowymi
  zleceniami wszystko musi się zgadzać. Inaczej Zatrzymanie „do Maksa”, a
  INTERMAX zostaje nietknięty.
- **Przed każdą podmianą powstaje kopia** `INTERMAX przed uporządkowaniem
  RRRR-MM-DD GG-MM-SS.xlsx` w folderze narzędzia na `C:`, poza OneDrive, żeby
  nie synchronizować 6,5 MB codziennie. Zostaje 10 ostatnich kopii. Centrum
  przywraca wybraną kopię z Konfiguracji, po zrobieniu kopii stanu bieżącego;
  to osobne zadanie, gotowe przed pierwszym Uporządkowaniem u taty.
- **INTERMAX musi być zapisany i zamknięty.** Otwarty plik albo plik, który
  OneDrive dalej synchronizuje po krótkiej ponownej próbie, daje Zatrzymanie
  „dla taty”.
- **Przygotowanie pliku zbiorczego nie zaczyna**, gdy okres ma Surowe
  zlecenia.

## Odrzucone warianty

- **Osobny plik eksportu, który tata wkleja po obróbce.** Tata i pracownicy
  pracują w INTERMAX; dodatkowy plik to dodatkowy krok ręczny.
- **Zapis całego skoroszytu w openpyxl.** Długi na laptopie taty i ryzykuje
  utratę tego, czego openpyxl nie zachowuje, w pliku, którego nie da się
  odtworzyć.
- **Same wersje OneDrive zamiast własnej kopii.** Są tylko ze
  zsynchronizowanych zapisów, a tata nie przywróci ich sam.
- **„Cofnij” na karcie wyniku.** Kopia i przywracanie z Konfiguracji pokrywają
  awarię narzędzia, a cofnięcie po ręcznych poprawkach pracowników by je
  skasowało.
