# MAXIMISEART-Dad: rozliczenia pracowników

Lokalne narzędzie z dwoma procesami uruchamianymi co tydzień, w tej kolejności:

1. [Przygotowanie pliku zbiorczego](#przygotowanie-pliku-zbiorczego) tworzy z
   Rejestru zleceń Rozliczenie wewnętrzne i Plik zbiorczy okresu.
2. Przebieg rozliczeń rozdziela dane z Pliku zbiorczego na osobne szablony
   pracowników.

Narzędzie nie używa AI ani zewnętrznych API. Instrukcja dla taty jest w
[`docs/tata-instrukcja.md`](docs/tata-instrukcja.md).

## Reguły Przebiegu rozliczeń

- Wejście: `Rozliczenie {okres} - zbiorcze.xlsx`.
- Folder wejścia ma nazwę identyczną jak `{okres}`.
- Wyjście: `Rozliczenie pracowników {okres}`.
- Każdy skoroszyt pracownika powstaje z kopii wspólnego Wzorca rozliczenia pracownika.
- Powstaje dokładnie jeden skoroszyt dla każdego pracownika z konfiguracji.
- Wykonawca jest odczytywany z kolumny `H=WYKONAWCA`.
- Identyfikatory wykonawców są mapowane jawnie w `config/worker_mapping.yaml`.
- Kopiowane są wartości `A:AT` od wiersza 18, zwarte od wiersza 18.
- Arkusze, formuły, stawki i formatowanie Wzorca rozliczenia pracownika pozostają zachowane.
- Pusty szablon pozostaje pusty.
- Istniejący Folder rozliczeń pracowników nie jest nadpisywany ani scalany.
- Nieznany wykonawca lub błąd tworzenia skoroszytu wstrzymuje publikację całego folderu.

## Instalacja lokalna

Wymagany jest Python 3.11 lub nowszy na komputerze taty.

```powershell
py -3 -m pip install -r requirements.txt
```

Potem jednorazowo dwukrotne kliknięcie `Zainstaluj skrót Centrum rozliczeń.cmd`
tworzy na pulpicie skrót „Centrum rozliczeń” (zob.
[Centrum rozliczeń](#centrum-rozliczeń-rozwój)).

Instalacja obejmuje `rich`, używany przez kolorowy dashboard CLI. Jeśli terminal
nie obsługuje kolorów albo pakiet jest chwilowo niedostępny, narzędzie używa
tekstowego fallbacku z tymi samymi informacjami operacyjnymi.

Przed pierwszym prawdziwym Przebiegiem rozliczeń użyj kontroli bez zapisu:

```powershell
py -3 run.py --dry-run --source "C:\Dane\08_14_09_2026\Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --worker-template "C:\Dane\Wzorzec rozliczenia pracownika.xlsx"
```

`--worker-template` wskazuje wspólny skoroszyt bazowy. Domyślna ścieżka to
`config\Wzorzec rozliczenia pracownika.xlsx`; parametr pozwala wskazać Wzorzec
rozliczenia pracownika poza repozytorium. Plik wcześniej nazywał się
`config\placeholder.xlsx`, a opcja `--placeholder`; starej opcji już nie ma.
Gdy brakuje Wzorca rozliczenia pracownika, a obok leży `placeholder.xlsx`,
komunikat podpowiada zmianę nazwy pliku.
Podgląd sprawdza, czy folder wynikowy jest wolny, i pokazuje okres, folder,
nazwy wszystkich planowanych plików oraz liczbę wierszy dla każdego wykonawcy.
Nie tworzy folderu ani skoroszytów. Zwykły przebieg przygotowuje wszystkie kopie
i uzupełnia je w katalogu tymczasowym, a Folder rozliczeń pracowników publikuje
dopiero po powodzeniu całej partii. Błąd nie zostawia częściowego folderu.
Uruchomienie pokazuje też etapy, postęp skoroszytów pracownika i końcowe liczniki.
W przekierowanym wyjściu lub terminalu bez kolorów używany jest zwykły tekst.
Historia czasów jest dopisywana lokalnie do `.rozliczenia-metrics.jsonl`; można
wskazać inne miejsce parametrem `--metrics`. P50 i P95 pojawiają się po pięciu
ukończonych obserwacjach tego samego trybu (`RUN` albo `DRY-RUN`).

## Uruchomienie Przebiegu rozliczeń przez CMD

Dwuklik `Utwórz rozliczenia.cmd` otwiera wybór pliku zbiorczego. Ścieżkę można
też podać od razu:

```powershell
Utwórz rozliczenia.cmd "C:\Dane\08_14_09_2026\Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
```

## Przygotowanie pliku zbiorczego

Proces poprzedzający Przebieg rozliczeń, uruchamiany osobno. Z Rejestru zleceń
tworzy w Folderze okresu razem Rozliczenie wewnętrzne i Plik zbiorczy. Oba pliki
powstają razem albo żaden.

### Reguły procesu

- Wejście: Rejestr zleceń (`ZLECENIA INTERMAX OD 08_11_2021.xlsx`), folder
  okresów (np. `INEA`) i token okresu.
- Okres rozliczeniowy trwa od wtorku 00:00 do następnego wtorku 00:00. Token
  `dd_dd_mm_rrrr` zawiera dzień wtorku, dzień poniedziałku oraz miesiąc i rok
  wtorku, np. `08_14_09_2026`, a na przełomie miesięcy `27_02_10_2026`
  (27.10–02.11.2026) i lat `29_04_12_2026` (29.12.2026–04.01.2027).
- Arkusz ze zleceniami jest wybierany po wymaganych nagłówkach w pierwszym
  wierszu, nie po nazwie. Inne arkusze są ignorowane.
- Zlecenie należy do okresu po dacie w `DATA GODZ. POCZ.`, niezależnie od
  miejsca w arkuszu. Kolejność z Rejestru jest zachowana, a całkowicie puste
  wiersze są pomijane.
- Zakres okresu w Rejestrze to wiersze od pierwszego do ostatniego zlecenia
  okresu. `Pominięte puste wiersze` to liczba wszystkich całkowicie pustych
  wierszy w tym zakresie, także leżących między zleceniami innych okresów
  (np. przed spóźnionym zleceniem dopisanym na końcu). W tym samym zakresie
  wiersz z danymi bez poprawnej daty zatrzymuje proces.
- Rozliczenie wewnętrzne (`Rozliczenie wew. {okres}.xlsx`) zawiera wszystkie
  zlecenia okresu, skuteczne i nieskuteczne, w kolumnach dopasowanych po
  nagłówkach. `zwrot` i `UWAGI` zostają puste.
- Kolumny docelowe są ustalane wyłącznie po nagłówkach wzorca. Trzy pary o
  innym zapisie są jawne w mapowaniu: `DATA GODZ. POCZ.` → `DATA`, `adres` →
  `ADRES`, `nr zlecenia` → `NUMER ZL.`. Wzorzec z nagłówkiem w zapisie Rejestru
  zamiast własnego oznacza zatrzymanie.
- Plik zbiorczy (`Rozliczenie {okres} - zbiorcze.xlsx`) zawiera każde Zlecenie
  skuteczne w `A:K` od wiersza 18, bez przerw. Wiersze 1–17, kolumny ilości
  `N:AP`, formuły i odwołania zewnętrzne (`xl/externalLinks/*`) zostają z wzorca.
  openpyxl nie zapisuje wyników formuł, więc Plik zbiorczy, tak jak Szablony
  pracowników, prosi Excela o przeliczenie formuł przy otwarciu.
- Wypełnienia, kolory czcionki, pogrubienia, kursywa i formaty dat przechodzą z
  Rejestru. Krój i rozmiar czcionki, szerokości kolumn, wysokości wierszy,
  nagłówek i blokada nagłówka pochodzą z wzorca. Autofiltr obejmuje nagłówek i
  wiersze danych.
- Folder okresu `{folder okresów}\{okres}` może już istnieć. Nienadpisywanie:
  jeśli istnieje w nim którykolwiek z dwóch plików okresu, proces się
  zatrzymuje.
- Oba pliki są przygotowywane w katalogu tymczasowym i publikowane razem. Błąd
  nie zostawia żadnego z nich ani nowo założonego Folderu okresu. Wyjątek
  zaakceptowany w [ADR 0004](docs/adr/0004-przerwana-publikacja-plikow-okresu.md):
  do istniejącego Folderu okresu pliki trafiają dwoma przeniesieniami, więc
  proces zamknięty między nimi zostawia samo Rozliczenie wewnętrzne.
- Rejestr zleceń i wzorce są tylko czytane.
- Zatrzymania i ostrzeżenia mają trzy części: co się stało, gdzie, co zrobić.
  Pełna lista z instrukcją postępowania jest w tabeli „komunikat → co zrobić”
  w [`docs/tata-instrukcja.md`](docs/tata-instrukcja.md). Wykonawcy Zleceń
  skutecznych są sprawdzani w tej samej `config/worker_mapping.yaml` co w
  Przebiegu rozliczeń.

### Wzorce

Oba wzorce leżą w katalogu konfiguracji obok Wzorca rozliczenia pracownika
używanego przez Przebieg rozliczeń:

- `config\Wzorzec rozliczenia wewnętrznego.xlsx`: nagłówki w wierszu 1
  aktywnego arkusza, bez zleceń;
- `config\Wzorzec pliku zbiorczego.xlsx`: stawki i sumy w wierszach 1–16,
  nagłówki `A17:K17`, wiersze przygotowane zerami w `N:AP`, formuły i link do
  Słownika.

Pliki `*.xlsx` nie trafiają do repozytorium. Wzorce przygotowuje człowiek z
pustych plików taty; kod nie poprawia ich wyglądu. Komórki wzorca, do których
trafiają zlecenia, nie mogą być scalone; sprawdza to już `--dry-run`. Ścieżki domyślne nadpisują
parametry `--internal-template` i `--collective-template`, tak jak
`--worker-template` w Przebiegu rozliczeń.

### Uruchomienie

Dla taty: dwuklik `Przygotuj plik zbiorczy.cmd`. Launcher otwiera kolejno okno
wyboru pliku Rejestru i okno wyboru folderu okresów, proponuje ostatni pełny
okres przed dzisiejszą datą (Enter potwierdza, można wpisać inny token) i po
zakończeniu czeka na klawisz. Argumenty podane launcherowi trafiają bez zmian do
`run_preparation.py`.

Kontrola bez zapisu z wiersza poleceń:

```powershell
py -3 run_preparation.py --dry-run --register "C:\Dane\ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory "C:\Dane\INEA" --period 08_14_09_2026
```

| Parametr | Domyślnie | Znaczenie |
|---|---|---|
| `--register` | okno wyboru pliku | Rejestr zleceń. |
| `--periods-directory` | okno wyboru folderu | Folder okresów, w którym powstaje Folder okresu. |
| `--period` | pytanie z propozycją | Token okresu. |
| `--config` | `config\worker_mapping.yaml` | Konfiguracja wykonawców. |
| `--internal-template` | `config\Wzorzec rozliczenia wewnętrznego.xlsx` | Wzorzec rozliczenia wewnętrznego. |
| `--collective-template` | `config\Wzorzec pliku zbiorczego.xlsx` | Wzorzec pliku zbiorczego. |
| `--metrics` | `.przygotowanie-pliku-zbiorczego-metrics.jsonl` | Lokalna historia czasów. |
| `--dry-run` | wyłączony | Podgląd bez zapisu. |

`--dry-run` wykonuje w całości etapy Sprawdzanie, Odczyt danych i Planowanie,
łącznie z Nienadpisywaniem, regułami zleceń i ostrzeżeniami. Pokazuje plan:
okres, liczbę zleceń okresu, Zleceń skutecznych i pominiętych pustych wierszy,
liczby zleceń na każdy dzień, ostrzeżenia oraz nazwy obu plików, a na końcu
`DRY-RUN: Nic nie zapisano`. Nie tworzy plików ani Folderu okresu; dopisuje
tylko rekord do historii czasów.

Bez `--dry-run`, gdy ostatnie zlecenie okresu jest sprzed poniedziałku, CLI
po etapie Planowanie, a przed Zapisywaniem, pokazuje ostrzeżenie o niepełnym
okresie z liczbami na dzień i pyta o kontynuację, także gdy okres podano
parametrem. Odpowiedź `t` albo `tak` kontynuuje, każda inna przerywa bez
zapisu. Silnik o nic nie pyta: przekazuje plan, a decyzję podejmuje CLI.
Rejestr jest czytany raz, a czas oczekiwania na odpowiedź nie wlicza się do
czasu uruchomienia ani do historii czasów.

Kody wyjścia: `0` sukces, także z ostrzeżeniami i po potwierdzeniu niepełnego
okresu; `1` zatrzymanie, błąd, odmowa kontynuacji albo zamknięte okno wyboru.

Historia czasów jest dopisywana do `.przygotowanie-pliku-zbiorczego-metrics.jsonl`,
osobno od historii Przebiegu rozliczeń, w tym samym formacie rekordu i trybach
`RUN`/`DRY-RUN`. Liczniki to zlecenia okresu, Zlecenia skuteczne, pominięte
puste wiersze i ostrzeżenia. P50 i P95 pojawiają się po pięciu ukończonych
obserwacjach tego samego trybu.

## Testy

Testy tworzą syntetyczne pliki `.xlsx` w katalogu tymczasowym. Nie używają
plików z `praca-tata` i nie zawierają prawdziwych danych klientów.

```powershell
py -3 -m pytest
```

### Lokalne lintowanie i sprawdzanie typów

Kontrybutorzy mogą zainstalować zestaw developerski, a następnie uruchamiać
lintowanie i ścisły typecheck całego utrzymywanego kodu Pythona:

```powershell
py -3 -m pip install -e ".[dev]"
py -3 -m ruff check
py -3 -m mypy
```

Ruff i mypy obejmują aplikację, testy, narzędzia oraz skrypty weryfikacyjne.
Zakres plików jest ustawiony tylko w `pyproject.toml`; nowy plik `*.py` w
katalogu głównym jest sprawdzany automatycznie.

Na macOS i Linuksie (bez `py -3`) zestaw developerski instaluje się przez
[`uv`](https://docs.astral.sh/uv/), a komendy uruchamia z `.venv`:

```sh
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m ruff check
.venv/bin/python -m mypy
```
Check formatowania nie jest wymagany.

Na Windows testy uruchamiają także `Utwórz rozliczenia.cmd`,
`Przygotuj plik zbiorczy.cmd` i `Centrum rozliczeń (konsola).cmd` przez
`cmd.exe`, tworzą skrót przez `Zainstaluj skrót Centrum rozliczeń.cmd` i
uruchamiają Centrum przez `pythonw.exe`.

## Centrum rozliczeń (rozwój)

Centrum rozliczeń to lokalny serwer (`src/rozliczenia/centrum/`) z
frontendem w przeglądarce (`frontend/`), opisany w
[ADR 0004](docs/adr/0004-centrum-rozliczen-adapter.md). Zbudowany frontend jest
commitowany w `src/rozliczenia/centrum/static/`, więc do uruchomienia
wystarczają zależności z `requirements.txt`, bez Node.

- Tata uruchamia Centrum skrótem „Centrum rozliczeń” z pulpitu. Skrót tworzy
  jednorazowo `Zainstaluj skrót Centrum rozliczeń.cmd`: wskazuje `pythonw.exe`
  tego samego Pythona co `py -3` i `run_centrum.py`, więc nie ma okna konsoli.
  Ponowne kliknięcie rozpoznaje działające Centrum po `/api/health` (tożsamość
  i wersja) i tylko otwiera kartę. Błąd startu (port zajęty przez inny
  program, inna wersja Centrum, brak biblioteki) bez konsoli pokazuje
  natywne okienko, z konsolą trzy linie komunikatu
  (`src/rozliczenia/centrum/start_problems.py`).
- `Centrum rozliczeń (konsola).cmd` (albo `py -3 run_centrum.py`) uruchamia
  Centrum z widoczną konsolą na `http://127.0.0.1:47811/` i otwiera kartę w
  przeglądarce. `--port` zmienia port, `--no-browser` nie otwiera karty.
- Serwer działa do kliknięcia „Zamknij Centrum rozliczeń” w karcie
  (`POST /api/shutdown`), Ctrl+C w konsoli albo wylogowania; zamknięcie karty
  go nie wyłącza.
- Dziennik Centrum `logs/centrum-rozliczen.log` (poza gitem) ma jedną linię na
  fakt: `start`, `juz-dziala`, `blad-startu`, `zamkniecie`, `stop`,
  `nieoczekiwany-wyjatek` (tylko typ i trasa, bez tekstu wyjątku).
- Ustawienia Centrum (Rejestr zleceń, folder okresów, motyw) są w
  `config/centrum-ustawienia.yaml`, poza gitem.
- Metryki czytają przy każdym odczycie oba pliki metryk CLI
  (`.rozliczenia-metrics.jsonl`, `.przygotowanie-pliku-zbiorczego-metrics.jsonl`)
  bez zmiany schematu, więc widać w nich także Uruchomienia procesu z `.cmd`.

Zmiana frontendu wymaga Node 24 i kończy się commitem źródeł razem z
odbudowanym buildem; CI sprawdza, że build i kontrakt odpowiadają źródłom:

```sh
cd frontend
npm ci
npm run contract   # OpenAPI z modeli Pydantic → typy i schematy zod (Python z zależnościami: zmienna PYTHON)
npm run typecheck  # tsc strict
npm run lint       # Oxlint z wtyczkami anti-slop
npm run build      # build do src/rozliczenia/centrum/static/
```

Podczas pracy nad UI `npm run dev` działa obok `run_centrum.py --no-browser`
i przekazuje `/api` do serwera. Zmiany w Centrum weryfikuje end-to-end skill
[`verify-centrum-rozliczen`](.agents/skills/verify-centrum-rozliczen/SKILL.md).

## Naprawa plików zapisanych starą wersją

Jeśli wcześniejsze uruchomienie pokazało w Excelu komunikat o naprawie
odwołania zewnętrznego, zamknij Excel i uruchom jednorazowo tryb kontrolny:

```powershell
py -3 tools\repair_external_links.py --directory "C:\Dane\08_14_09_2026\Rozliczenie pracowników 08_14_09_2026" --reference "C:\Dane\08_14_09_2026\Rozliczenie pracowników 08_14_09_2026\Rozliczenie 08_14_09_2026 - Kamil Frontczak.xlsx"
```

Jeśli lista plików jest poprawna, dodaj `--apply`. Narzędzie zapisze kopie w
`_backup_przed_naprawa_linkow` i zmieni wyłącznie części ZIP odpowiedzialne za
odwołania zewnętrzne, nie komórki ani formuły.

## Zakres poza pierwszą wersją

Synchronizacja OneDrive, współbieżna edycja przez innych użytkowników oraz
automatyczne wykrywanie gotowości po samym zapisie pliku są poza zakresem.

Poza zakresem Przygotowania pliku zbiorczego są też:

- połączenie Przygotowania pliku zbiorczego i Przebiegu rozliczeń w jeden
  proces działający w tle;
- automatyczne uzupełnianie ilości 0/1 w kolumnach `N:AP` Pliku zbiorczego.
