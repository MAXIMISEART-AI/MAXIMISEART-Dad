# ADR 0015: Logi Uruchomienia, Uwagi taty i Powiadomienia

## Status

Zaakceptowana. Zakłada Wydania z ADR 0014 (tata dostaje tylko Wydanie, nigdy
bieżący `main`). Zmienia trzy zdania
[ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md) w ten sam sposób co
[ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md):

- „Centrum łączy się wyłącznie z API GitHuba: przy wysyłce Zgłoszenia, przy
  sprawdzaniu stanu wysłanych Zgłoszeń…”: dochodzi wysyłka Logów Uruchomienia
  i Uwag taty, stan Uwag oraz lista Wydań publicznego repozytorium;
- „Bez treści wierszy”: Logi Uruchomienia niosą treść kolumn według reguły
  Kontroli ilości;
- własne pliki Centrum: dochodzą Logi Uruchomienia w `logs/uruchomienia/` i
  stan przeczytanych Powiadomień w `config/`, oba poza Gitem.

[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md) traci Powiadomienie o
naprawie na stronie Okresy: zastępuje je Powiadomienie o nowej wersji.

## Kontekst

Wszystko, co Maks wiedział o pracy narzędzia u taty, to rekord metryk (czasy,
liczniki, kod Zatrzymania) i linie dziennika Centrum. Pełny wynik Uruchomienia
procesu, czyli Komunikaty, podsumowanie i przebieg Szablonów pracownika, ginął
przy zamknięciu Centrum. Do Maksa trafiało tylko Zgłoszenie, a to wymaga
Zatrzymania „do Maksa” i kliknięcia taty; Skrzynka Zgłoszeń nie dostała
żadnego. Tata nie miał jak napisać do Maksa z narzędzia ani jak się dowiedzieć,
co stało się z tym, co wysłał.

## Decyzja

- **Logi Uruchomienia powstają na końcu każdego Uruchomienia z Centrum**, w
  każdym trybie i z każdym wynikiem, także przy Zatrzymaniu i nieoczekiwanym
  wyjątku. Mówią wprost, czy był to podgląd, czy zapis. Centrum przerwane w
  trakcie zostawia tylko `uruchomienie-start` w dzienniku; zapis przyrostowy
  dokładałby pracy każdemu Przebiegowi. Skrypt dla maszyn Logów nie tworzy.
- **Na komputerze taty jeden plik JSON na Uruchomienie** w `logs/uruchomienia/`
  na `C:`, z wersją schematu, zapisany atomowo i trzymany bez rotacji. Urwany
  zapis psuje jeden plik, nie historię, a ten sam plik jest treścią w Skrzynce.
- **Centrum wysyła Logi samo i po cichu.** Jeden okres to jedno issue z
  etykietą `logi-uruchomienia`, także po zamknięciu przez Maksa, a każde
  Uruchomienie to komentarz: podsumowanie w Markdown i pełny JSON w
  `<details>`, dzielony na kolejne komentarze ponad limitem GitHuba.
  Uruchomienia bez ustalonego okresu trafiają do jednego stałego issue. Brak
  sieci albo klucza zostawia je w kolejce ponawianej przy starcie, wspólnej z
  Kontrolą ilości. Diagnoza dopisuje się do Logów swojego Uruchomienia, a
  Zgłoszenie do nich prowadzi.
- **Treść Logów:** proces, tryb, okres, Wydanie i commit, Komunikaty w trzech
  częściach, podsumowanie, plan plików, czasy etapów i Szablonów pracownika z
  liczbą problemów, środowisko (system, Python, rozmiary plików, OneDrive) i
  przy nieoczekiwanym wyjątku ślad wywołań jak w Zgłoszeniu. Treść komórek
  według reguły Kontroli ilości: nigdy adres, numer zlecenia, numer umowy,
  Wykonawca przy wierszu, data dzienna, `CZYNNOŚCI ZREALIZOWANE` ani opis
  technika. Komunikaty i przebieg Szablonów zachowują nazwę Wykonawcy, tak jak
  w Zgłoszeniu.
- **Uwaga taty** to tytuł i opcjonalna treść, pisane w oknie otwieranym ikoną
  obok dzwonka w każdym widoku, ogólne albo przypięte do jednego Uruchomienia
  procesu. Każda to osobne issue z etykietą `uwaga-taty`. Tata widzi w oknie
  dokładnie to, co wyśle; bez sieci Uwaga czeka w kolejce z jednym zdaniem
  dla taty, bez Komunikatu.
- **Powiadomienia** to osobny widok otwierany dzwonkiem, z trzema rodzajami:
  nowa wersja, Uwaga i Zgłoszenie. Wejście do widoku oznacza wszystkie jako
  przeczytane. Sprawę zamkniętą przez Maksa przed Wydaniem Powiadomienie
  nazywa rozwiązaną, z dopiskiem, że będzie w następnej wersji; zamkniętą bez
  zmiany w kodzie jako przeczytaną. Powiadomienie o nowej wersji ma notkę
  Wydania, rozwiązane sprawy taty i przycisk Aktualizacji narzędzia. Centrum
  sprawdza Wydania i stan spraw przy starcie i najwyżej raz na 10 minut; bez
  sieci nie ma nowych Powiadomień ani Komunikatu.

## Odrzucone warianty

- **Logi wysyłane kliknięciem taty.** Maks dostawałby dane tylko wtedy, gdy
  tata sam zauważy problem, a to luka, którą Logi zamykają.
- **Jedno issue na Uruchomienie.** Kilkanaście issue miesięcznie, a sekwencja
  okresu (podgląd, Zatrzymanie, poprawka taty, Przebieg) rozbita na wątki.
- **Baza danych u taty.** Postgres to usługa systemowa z instalacją i
  aktualizacjami na Windowsie taty, a SQLite to plik binarny, którego nie da
  się wkleić do issue. Zapytania są potrzebne dopiero przy analizie, która
  odbywa się u Maksa na pobranych Logach.
- **Powiadomienie o każdej nowej wersji `main`.** Na `main` trafia kilkanaście
  zmian dziennie, więc kropka na dzwonku świeciłaby stale i tata przestałby
  ją zauważać.
- **Odpowiedź Maksa w Powiadomieniu.** Na razie tylko stan sprawy; komentarze
  z issue wejdą, gdy okaże się, że Maks dzwoni do taty z wyjaśnieniem.
