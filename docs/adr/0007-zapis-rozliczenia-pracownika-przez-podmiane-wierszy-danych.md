# ADR 0007: Zapis Rozliczenia pracownika przez podmianę wierszy danych w kopii Wzorca

## Status

Zaakceptowana. Rozstrzyga eksperyment 1 (#147) wspinaczki „Przebieg rozliczeń
poniżej minuty” (#141); pomiar w dzienniku wspinaczki (#163).

## Kontekst

Przebieg rozliczeń trwał u taty ~4 minuty (234–240 s), na Macu M4 Max 72,5 s
w benchmarku na lustrze folderów taty. 96% tego czasu to Zapisywanie:
Wzorzec rozliczenia pracownika ma ~10 tys. sformatowanych Wierszy danych,
~500 tys. komórek i ~50 tys. formuł (wspólnych), a openpyxl wczytywał go w
całości (~1,7 s) i zapisywał w całości (~1,5 s) dla każdego z 20 Szablonów
pracowników, po czym zip był przepisywany drugi raz, żeby przywrócić
`xl/externalLinks/*`. Samo wpisanie Wierszy danych trwało milisekundy.
Skutkiem ubocznym były pliki większe od Wzorca (2,8 MB zamiast 1,9 MB): bez
wspólnych formuł i bez `calcChain`.

Rozliczenie pracownika różni się od Wzorca tylko Wierszami danych od wiersza
18 w kolumnach A:AT i flagami przeliczania w `calcPr`.

## Decyzja

Rozliczenie pracownika powstaje z kopii bajtów Wzorca wczytanego raz na
Przebieg rozliczeń, za interfejsem `workbook_files.WorkerSettlementTemplate`
(implementacja: `template_copy.py`):

- Każda część zip poza XML aktywnego arkusza i `xl/workbook.xml` jest
  przepisywana bajt w bajt razem ze skompresowaną treścią, w tym
  `xl/externalLinks/*`, `xl/calcChain.xml` i `xl/sharedStrings.xml`.
  `xl/styles.xml` zmienia się tylko wtedy, gdy data trafia do komórki bez
  formatu daty (dopisany styl, jak w openpyxl).
- W XML arkusza zmieniają się tylko wiersze od 18 do ostatniego wpisanego.
  Komórki A:AT dostają wartości z tą samą semantyką co wpisanie przez openpyxl
  (tekst, `=formuła`, kody błędów, liczby, prawda/fałsz, daty jako liczba
  seryjna, pusta wartość czyści zera Wzorca, brakująca komórka powstaje ze
  stylem domyślnym). Pozostałe komórki, w tym formuły AU:AY, wspólne formuły
  i style, zostają bajt w bajt.
- `calcPr` dostaje `calcMode="auto"`, `fullCalcOnLoad="1"` i
  `forceFullCalc="1"`, tak jak przy zapisie przez openpyxl.
- Arkusz jest kompresowany raz przy wczytaniu Wzorca, w kawałkach od granic
  wierszy (pełne opróżnienie zlib co 64 wiersze). Dla każdego Rozliczenia
  pracownika kompresowany jest tylko początek arkusza z wpisanymi wierszami,
  a reszta to gotowe kawałki.
- Kontrole Szablonu pracownika (WYKONAWCA w H17, dane w Wierszach danych) są
  liczone raz na Wzorcu; wyniki, Komunikaty, liczniki i zdarzenia postępu są
  takie same jak wcześniej.
- Sprawdzanie Wzorca rozliczenia pracownika (#149) używa tego samego Wzorca
  wczytanego raz: `validate_worker_template` zwraca Wzorzec, z którego etap
  Zapisywanie tworzy Rozliczenia pracowników. Kopia przyjmuje Wzorzec tylko
  wtedy, gdy każda część XML jest poprawnym XML-em; inaczej Sprawdzanie idzie
  przez openpyxl z dotychczasową klasyfikacją (brak, otwarty w Excelu,
  nieczytelny). Przy pierwszym Rozliczeniu pracownika bajty Wzorca są czytane
  ponownie: Wzorzec zmieniony albo otwarty w Excelu po Sprawdzaniu zatrzymuje
  Zapisywanie tak jak wcześniej. Zapis jest atomowy jak wcześniej (plik tymczasowy
  obok celu, `os.replace`).
- Wzorzec spoza kształtu, który zapisuje Excel (np. formuła albo scalenie w
  kolumnach A:AT Wierszy danych, XML z prefiksami przestrzeni nazw, komórki bez
  `r`), i wartości nieobsługiwanych typów (np. tekst sformatowany) idą dawną
  drogą: pełne wczytanie i zapis przez openpyxl. Wpisanie wartości w formułę
  Wierszy danych zmieniałoby `calcChain` i wspólne formuły, czego kopia nie
  robi.

Wynik: typowy tydzień 72,5 s → 2,8 s czasu ściany, Zapisywanie 70 s → 0,42 s
dla 20 Szablonów pracowników (jednorazowe wczytanie Wzorca ~0,35 s, potem
~3–8 ms na Rozliczenie pracownika); ciężki tydzień 73,6 s → 2,9 s. Bramka
poprawności `zgodny` w obu scenariuszach. Rozliczenie pracownika ma ~1,5 MB
(Wzorzec 1,9 MB).

Odrzucone kierunki:

- **Dalej openpyxl, tylko Wzorzec wczytany raz i kopiowany w pamięci.** Zostaje
  pełny zapis ~1,5 s na Szablon pracownika i utrata wspólnych formuł oraz
  `calcChain`; nie zbliża się do celu.
- **lxml pod openpyxl.** Zmierzone ~8% (72 → 67 s) za nową zależność binarną.
- **Równoległe Przetwarzanie Szablonów pracowników.** Nie usuwa pełnego
  wczytania i zapisu, tylko dzieli je na rdzenie, i komplikuje kolejność
  zdarzeń postępu oraz obsługę przerwanego zapisu (spec #141: poza zakresem).
- **Odchudzenie Wzorca** z 10 tys. sformatowanych wierszy. To zmiana w pliku
  taty, poza zakresem narzędzia, i nie usuwa kosztu pełnego wczytania i zapisu.

## Konsekwencje

- Repozytorium utrzymuje własny kod XML i zip (`template_copy.py`): indeks
  wierszy, scalanie komórek, escapowanie tekstu, znaki niedozwolone w XML,
  semantykę typów wartości openpyxl i zapis zip. Strażą jest test właściciel
  zapisu Rozliczenia pracownika w `tests/test_workbook_files.py`, który
  porównuje wynik z plikiem z Wzorca zapisanym przez openpyxl modułem bramki
  poprawności, oraz bramka benchmarku przy każdym eksperymencie.
- openpyxl zostaje do odczytu Pliku zbiorczego i Rejestru zleceń, do
  Sprawdzania Wzorców Przygotowania pliku zbiorczego i do drogi zapasowej.
  Wzorzec rozliczenia pracownika przechodzi Sprawdzanie bez openpyxl (#149):
  Wzorzec poprawny jako XML, ale semantycznie odrzucany przez openpyxl, nie
  jest już zatrzymywany w Sprawdzaniu. Do decyzji trzeba wrócić, jeśli taki
  Wzorzec się pojawi. Przygotowanie pliku zbiorczego
  nadal zapisuje oba pliki okresu przez openpyxl; jego wspinaczka to osobna
  decyzja.
- Bramka poprawności traktuje nazwę arkusza w apostrofach i bez nich w nazwie
  zdefiniowanej jako to samo odwołanie: openpyxl dodaje apostrofy, kopia
  zostawia definicję z Wzorca.
- Usunięcie `forceFullCalc` to osobna zmiana (spec #141, Out of Scope); po niej
  zmienia się tylko łatka `calcPr`.
- Do decyzji trzeba wrócić, jeśli Wzorzec zacznie mieć formuły albo scalenia w
  A:AT Wierszy danych (cały zapis wraca wtedy do openpyxl i do minut) albo
  jeśli Excel zacznie zgłaszać naprawę plików z kopii.
