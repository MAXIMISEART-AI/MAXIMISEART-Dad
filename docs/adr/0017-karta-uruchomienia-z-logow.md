# ADR 0017: Karta Uruchomienia wraca z Logów Uruchomienia

## Status

Zaakceptowana. Rozstrzyga główną część issue #427. Zmienia dwa miejsca
[ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md):

- „Centrum przerwane w trakcie zostawia tylko `uruchomienie-start` w
  dzienniku”: zostawia też plik ostatniego startu, po którym następny start
  Centrum nazywa je Urwanym Uruchomieniem;
- własne pliki Centrum: dochodzi `logs/ostatnie-uruchomienie.json`, poza
  Gitem i OneDrive.

## Kontekst

Centrum trzymało tylko bieżące Uruchomienie procesu w pamięci, więc karta
wyniku ginęła z zamknięciem Centrum, choć Logi Uruchomienia mają prawie całą
jej treść. Uruchomienie zabite razem z Centrum (zamknięte okno konsoli, brak
prądu) nie zostawiało nic trwałego: rekord metryk i Logi powstają dopiero na
końcu. Issue zakładało, że Telemetria zapisuje start i że Metryki pokazują
takie Uruchomienie jako „Przerwane”. To nieprawda: „Przerwane” w Metrykach to
Zatrzymania z rekordem metryk, a jedynym śladem startu była linia dziennika
Centrum bez identyfikatora Uruchomienia.

## Decyzja

- **Plik ostatniego startu.** Przy każdym starcie Uruchomienia z Centrum,
  zanim ruszy jego wątek, Centrum nadpisuje atomowo
  `logs/ostatnie-uruchomienie.json`: identyfikator, proces, tryb, okres i
  chwilę startu, te same bezpieczne fakty co linia `uruchomienie-start` i
  nagłówek Logów. Pliku nikt nie usuwa. Nieudany zapis to jedna linia
  dziennika, a Uruchomienie biegnie dalej.
- **Urwane Uruchomienie wynika z plików, nie jest zapisywane.** Po starcie
  Centrum ostatnie Uruchomienie to ostatni start. Gdy ma plik Logów, jego
  karta wraca z Logów. Gdy go nie ma, Centrum zamknęło się w trakcie i to
  Urwane Uruchomienie, bo Logi powstają przed końcem każdego Uruchomienia,
  także przy Zatrzymaniu. Nic nie jest zapisywane na końcu, więc nie ma
  kolejności względem działań po wyniku, a zabicie Centrum w dowolnej chwili
  daje właściwą kartę.
- **Karta z Logów niesie tylko to, co w nich jest**: Komunikaty w trzech
  częściach, podsumowanie, etapy, sposób zakończenia i Rodzaj Zatrzymania.
  Tytuł wyniku i akcję po nim wylicza ta sama reguła co na żywo. Diagnozy i
  „Wyślij do Maksa” nie ma: żyją tylko przy Zatrzymaniu bieżącego Uruchomienia
  tej pracy Centrum, a „Uruchom ponownie” odtwarza Zatrzymanie z Diagnozą.
  Reguła prywatności Logów obowiązuje bez zmian.
- **Ostatnie Uruchomienie nie jest stanem żadnego Uruchomienia tej pracy
  Centrum.** Przychodzi w pierwszym widoku jako dopisek do stanu „bez
  Uruchomienia”, a pierwszy start w tej pracy Centrum go zastępuje.
- **Wiersz Historii otwiera kartę swojego Uruchomienia** z jego Logów, po
  identyfikatorze Uruchomienia. Uruchomienie bez Logów (ze Skryptu dla maszyn,
  sprzed Logów albo z plikiem, którego nie da się odczytać) dostaje zwykłą
  odpowiedź „karty nie ma”, nie błąd, więc przeglądarka nie proponuje
  ponowienia.
- Urwane Uruchomienie zostaje w Centrum tylko do następnego startu
  Uruchomienia: nie ma Logów, rekordu metryk ani wiersza Historii.

## Odrzucone warianty

- **Niepełny plik Logów zapisany przy starcie.** Każdy czytelnik Logów
  (kolejka Skrzynki, podsumowanie, weryfikacja) musiałby pomijać niepełny
  plik, a Logi przestałyby być pełnym obrazem Uruchomienia.
- **Usuwanie pliku startu na końcu Uruchomienia.** Wymaga kolejności po
  zapisie Logów, a zabicie Centrum między tymi krokami źle nazywa
  Uruchomienie.
- **Szukanie startu bez końca w dzienniku Centrum.** To tekst dla pomocy
  technicznej, bez identyfikatora Uruchomienia.
- **Karta z Logów jako zakończone Uruchomienie na żywo.** Wymagałaby
  zmyślonego postępu i Diagnozy, której po zamknięciu Centrum nie ma kto
  obsłużyć.

## Konsekwencje

- Podwójna awaria (plik startu zapisany, a Logi na końcu nie) nazywa
  zakończone Uruchomienie urwanym. Rada „Uruchom ponownie” jest wtedy
  bezpieczna dzięki Nienadpisywaniu.
- Plik Logów bez pola Diagnozy (sprzed tego pola, tylko u Maksa) daje „karty
  nie ma”.
