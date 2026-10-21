# ADR 0008: Zapis Rozliczenia pracownika przez podmianę Wierszy danych w kopii Wzorca

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
18 w kolumnach A:AT (wartości i, od zmiany z 2026-10-21, Wyróżnienia) i
flagami przeliczania w `calcPr`.

## Decyzja

Rozliczenie pracownika powstaje z kopii bajtów Wzorca wczytanego raz na
Przebieg rozliczeń, za interfejsem `workbook_files.WorkerSettlementTemplate`
(implementacja: `template_copy.py`):

- Każda część zip poza XML aktywnego arkusza i `xl/workbook.xml` jest
  przepisywana bajt w bajt razem ze skompresowaną treścią, w tym
  `xl/externalLinks/*`, `xl/calcChain.xml` i `xl/sharedStrings.xml`.
  `xl/styles.xml` zmienia się tylko wtedy, gdy data trafia do komórki bez
  formatu daty (dopisany styl, jak w openpyxl) albo gdy Wyróżnienia wpisanej
  komórki różnią się od komórki Wzorca (zmiana z 2026-10-21).
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

## Zmiana z 2026-10-21

Przebieg rozliczeń czytał z Pliku zbiorczego same wartości, więc każda komórka
A:AT Wierszy danych dostawała wygląd komórki Wzorca. Wyróżnienia, które
Przygotowanie pliku zbiorczego przeniosło z Rejestru zleceń (wypełnienie, kolor
czcionki, pogrubienie, kursywa), znikały. Na kopii prawdziwego Pliku zbiorczego
różniło się tak 1981 z 7906 niepustych komórek.

Teraz `read_data_rows` czyta też Wyróżnienia każdej komórki A:AT, a obie drogi
zapisu nakładają je na komórkę Wzorca tą samą regułą co Przygotowanie z
Rejestru: Wyróżnienia zastępują wypełnienie, kolor, pogrubienie i kursywę
komórki Wzorca (komórka bez Wyróżnień daje komórkę bez wypełnienia, z kolorem
automatycznym); krój i rozmiar czcionki, format liczby, obramowanie,
wyrównanie i ochrona zostają z Wzorca. Kopia dopisuje brakujące czcionki,
wypełnienia i style komórek na końcu ich list w `xl/styles.xml`, każdy raz na
Rozliczenie pracownika; istniejące wpisy zostają bajt w bajt, a gdy żadna
komórka nie potrzebuje nowego stylu, `xl/styles.xml` jest przepisany bez zmian.
Test właściciel zapisu porównuje Wyróżnienia z drogi kopii i drogi przez
openpyxl.

Czcionki i wypełnienia są serializowane przez openpyxl (`to_tree`), więc zapis
jest deterministyczny i ma kształt, który openpyxl już zapisuje w drodze
zapasowej. Oba Wzorce taty mają ten sam motyw (`theme1.xml`), więc kolory
motywu z Pliku zbiorczego znaczą w Rozliczeniu pracownika to samo.

Odrzucone kierunki:

- **Przeniesienie całego stylu komórki Pliku zbiorczego** (jak „Wklej
  wszystko”). Zmieniłoby krój, rozmiar i obramowania, które pochodzą z Wzorca
  rozliczenia pracownika, i wymagałoby kopiowania obramowań oraz formatów
  liczb między dwoma plikami stylów.
- **Wspólny typ z `CellFormat` Przygotowania.** `CellFormat` niesie też format
  liczby z Rejestru i zawsze ustawia pogrubienie i kursywę; w Przebiegu każda
  zwykła komórka dostałaby wtedy nową czcionkę i nowy styl. Ujednolicenie
  zmieniłoby zapis Przygotowania, które jest poza zakresem tej zmiany.

Koszt: na lustrze `typowy-tydzien` (Mac M4 Max) mediana czasu ściany 681 → 709
ms; Odczyt danych tworzy komórki openpyxl zamiast samych wartości (+17 ms), a
Zapisywanie szuka stylu dla każdej wpisanej komórki (+12 ms).

## Zmiana z 2026-10-21: Hiperłącza

Numer zlecenia w `NUMER ZL.` Pliku zbiorczego jest u taty Hiperłączem do
zlecenia w aplikacji firmowej, a w Rozliczeniu pracownika nie dało się go
kliknąć: Przebieg rozliczeń hiperłączy nie czytał ani nie zapisywał.

Teraz `read_data_rows` czyta też Hiperłącza każdej komórki A:AT z wartością
(`hyperlinks.read_sheet_hyperlinks`: blok `<hyperlinks>` za `</sheetData>` i
relacje arkusza, bez parsowania wierszy), a obie drogi zapisu wpisują je w te
same komórki Rozliczenia pracownika. Hiperłącze zastępuje hiperłącze komórki
Wzorca w zapisywanym Wierszu danych, jak Wyróżnienia.

Kopia ma dwa nowe wyjątki od przepisania bajt w bajt, oba tylko wtedy, gdy
któraś wpisana komórka ma Hiperłącze:

- w ogonie XML arkusza pojawia się jeden blok `<hyperlinks>` w miejscu, które
  wyznacza mu schemat arkusza (za `mergeCells`, `conditionalFormatting` i
  `dataValidations`, przed `pageMargins`); pozostałe bajty ogona zostają;
- relacje arkusza (`xl/worksheets/_rels/sheetN.xml.rels`) dostają na końcu po
  jednej relacji `TargetMode="External"` na Hiperłącze, pod numerami `rId` za
  najwyższym numerem we Wzorcu; istniejące relacje (u taty `rId1` rysunek VML
  i `rId2` komentarze) zostają bajt w bajt. Wzorzec bez relacji arkusza dostaje
  nową część na końcu zip; `[Content_Types].xml` się nie zmienia, bo typ
  rozszerzenia `rels` już w nim jest. Wzorzec bez takiego typu idzie dawną
  drogą.

Bez Hiperłączy wszystkie części Rozliczenia pracownika mają po rozpakowaniu te
same bajty co przed zmianą. Skompresowany arkusz ma jedną granicę kawałka
więcej: ostatni kawałek zaczyna się w miejscu bloku `<hyperlinks>`, więc kopia z
Hiperłączami kompresuje od nowa tylko ogon arkusza (u taty 128 B).

Wzorzec, którego arkusz ma już własny blok `<hyperlinks>`, idzie dawną drogą
(`UnsupportedShape`). Wzorzec taty go nie ma, a zasada dla hiperłącza Wzorca w
Wierszach danych wymagałaby scalania dwóch bloków.

Wygląd komórki się nie zmienia: podkreślenie i styl komórki „Hiperłącze” nie
są Wyróżnieniem, więc nie przechodzą z Pliku zbiorczego.

Adres Hiperłącza to treść wiersza (np. numer sprawy klienta). `Hyperlink` nie
pokazuje go w `repr`, a żaden Komunikat, Zdarzenie przebiegu, rekord metryk ani
Zgłoszenie go nie zawiera.
