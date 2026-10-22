# Instrukcja dla taty

Co tydzień są dwa kroki, zawsze w tej kolejności:

1. **Przygotowanie pliku zbiorczego**: z Rejestru zleceń powstają Rozliczenie
   wewnętrzne i Plik zbiorczy okresu.
2. **Przebieg rozliczeń**: z Pliku zbiorczego powstają rozliczenia
   pracowników.

Oba kroki robisz w Centrum rozliczeń, które otwierasz skrótem na pulpicie:

| Co chcesz zrobić | Gdzie w Centrum rozliczeń |
|---|---|
| Zobaczyć Status okresu każdego tygodnia | Strona `Okresy` |
| Otworzyć Plik zbiorczy, Rozliczenie wewnętrzne albo Folder okresu | Jedno kliknięcie w wierszu okresu |
| Przygotować plik zbiorczy | Strona `Uruchomienia`, proces `Przygotowanie pliku zbiorczego` |
| Utworzyć rozliczenia pracowników | Strona `Uruchomienia`, proces `Przebieg rozliczeń` |
| Zaktualizować narzędzie | Przycisk `Zaktualizuj narzędzie`: na stronie `Konfiguracja`, w Powiadomieniu o naprawie i w Diagnozie |

## Pierwsza instalacja

Pierwszą instalację robi osoba utrzymująca narzędzie:

1. Zainstaluj Python 3.11 lub nowszy.
2. W folderze narzędzia uruchom:

   ```powershell
   py -3 -m pip install -r requirements.txt
   py -3 install_centrum_shortcut.py
   ```

   Na pulpicie pojawi się skrót „Centrum rozliczeń” z ikoną. Drugie polecenie
   powtórz tylko po przeniesieniu folderu narzędzia albo po instalacji nowego
   Pythona.

Osoba utrzymująca narzędzie umieszcza w folderze `config` narzędzia trzy
wzorce: `Wzorzec rozliczenia wewnętrznego.xlsx`, `Wzorzec pliku zbiorczego.xlsx`
i `Wzorzec rozliczenia pracownika.xlsx`. Ten ostatni to pusty plik rozliczenia
pracownika bez nazwy wykonawcy (u Ciebie `Rozliczenie {okres} -.xlsx`); z niego
powstają pliki pracowników.
Nie zmieniaj ich i nie podmieniaj plikami z poprzedniego tygodnia.

W tym samym folderze `config` osoba utrzymująca narzędzie umieszcza też
konfigurację wykonawców `worker_mapping.yaml`, czyli listę Twoich pracowników.
Ten plik jest tylko na Twoim komputerze, nie w internecie. Plik
`worker_mapping.example.yaml` obok to przykład z wymyślonymi nazwiskami;
narzędzie z niego nie korzysta.

### Foldery tygodni

Tygodnie leżą w OneDrive w `Załączniki\Rozliczenia {rok}\{miesiąc}\INEA`, np.
`Rozliczenia 2026\10_Październik_2026\INEA\13_19_10_2026`. Narzędzie szuka
folderu tygodnia we wszystkich miesiącach, bo tylko Ty wiesz, w którym miesiącu
rozliczasz dany tydzień.

- Zakładaj z góry **tylko pusty folder tygodnia**, tak jak dotąd. Nie kopiuj do
  niego pustych plików rozliczeń: narzędzie nie nadpisuje istniejących plików,
  więc pusty plik zablokuje Przygotowanie pliku zbiorczego.
- Nazwa folderu to okres: dzień wtorku, dzień poniedziałku, miesiąc i rok
  poniedziałku, np. `29_05_10_2026` dla 29 września – 5 października 2026.
- Jeden tydzień ma jeden folder. Ten sam tydzień w dwóch miesiącach zatrzyma
  narzędzie z komunikatem, który pokaże oba miejsca.

## Centrum rozliczeń

Centrum rozliczeń to strona w przeglądarce, która działa tylko na Twoim
komputerze. Nie otwiera czarnego okna konsoli.

### Uruchomienie

1. Dwukrotnie kliknij skrót „Centrum rozliczeń” na pulpicie.
2. Po chwili przeglądarka sama otworzy kartę Centrum rozliczeń
   (`http://127.0.0.1:47811/`).
3. Za pierwszym razem na stronie `Okresy` wskaż folder okresów, czyli
   `Załączniki` w OneDrive (ten z folderami `Rozliczenia 2025`,
   `Rozliczenia 2026`), i Rejestr zleceń. Centrum je zapamięta.

Zamknięcie karty przeglądarki nie wyłącza Centrum. Żeby wrócić, kliknij skrót
jeszcze raz: otworzy się karta działającego Centrum, a nie druga kopia.

### Zamknięcie

1. W menu po lewej kliknij `Zamknij Centrum rozliczeń`.
2. Potwierdź przyciskiem `Zamknij Centrum`.
3. Karta pokaże `Centrum rozliczeń jest zamknięte`. Możesz ją zamknąć.

Centrum kończy pracę także po wylogowaniu albo wyłączeniu komputera.

Gdy trwa Uruchomienie procesu (także gdy czeka na Twoją decyzję), Centrum się
nie zamknie: pokaże, że trwa Uruchomienie procesu. Poczekaj na wynik na stronie
`Uruchomienia` i zamknij Centrum potem.

### Zatrzymanie i Diagnoza

Gdy Uruchomienie procesu się zatrzyma, Centrum pokaże komunikat w trzech
częściach i podpowie, co dalej:

- `Uruchom ponownie`: przyczynę usuniesz sam według części `Co zrobić`. Po
  poprawce kliknij przycisk; ten sam proces ruszy dla tego samego okresu i w tym
  samym trybie.
- `Diagnoza`: komunikat każe przekazać go osobie utrzymującej narzędzie albo po
  ponownym uruchomieniu wrócił ten sam komunikat. Kliknij `Diagnoza`. Centrum
  sprawdzi Twój komputer tylko do odczytu i wyjaśni przyczynę w trzech
  częściach. Niczego nie zmienia w Twoich plikach. Przy nieoczekiwanym błędzie
  narzędzia Diagnoza zaczyna się sama, bez klikania.

Gdy przyczyną jest sam komunikat zatrzymania, Centrum pisze tylko `Diagnoza
potwierdza ten komunikat.` Gdy wyjaśnienie mówi, co zrobić, popraw to i kliknij
`Uruchom ponownie`. Lista `Sprawdzono` pokazuje każde sprawdzenie Diagnozy.

Nowsza wersja narzędzia jest wyjaśnieniem tylko wtedy, gdy Diagnoza nie
znalazła innej przyczyny. Wtedy przy wyjaśnieniu jest przycisk `Zaktualizuj
narzędzie`. Gdy Diagnoza znalazła inną przyczynę, pod wyjaśnieniem jest tylko
krótkie zdanie `Jest też nowsza wersja narzędzia.` z tym samym przyciskiem,
drugim po `Uruchom ponownie`. Najpierw usuń przyczynę według wyjaśnienia;
aktualizacja może poczekać.

### Wyjaśnienie Diagnozy → co zrobić

Diagnoza wyjaśnia przyczynę komunikatem z tabel procesów (np. Rejestr zleceń
otwarty w Excelu) albo jednym z tych:

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znalazłem przyczyny na tym komputerze” | Przyczyna nie leży na Twoim komputerze. Kliknij `Wyślij do Maksa`. |
| „Jest nowsza wersja narzędzia” | Kliknij `Zaktualizuj narzędzie` przy wyjaśnieniu (niżej, „Aktualizacja narzędzia”). Gdy karta Centrum sama się odświeży, uruchom proces ponownie. Bez internetu Diagnoza tego nie sprawdza. |
| „Plik okresu jest otwarty w Excelu” | Zapisz i zamknij wskazany plik w Excelu i uruchom ponownie. Jeśli Excel jest zamknięty, usuń z tego samego folderu pozostawiony plik zaczynający się od `~$`. |
| „Plik jest tylko w OneDrive w chmurze” | W Eksploratorze plików kliknij wskazany plik prawym przyciskiem myszy i wybierz „Zawsze zachowuj na tym urządzeniu”. Gdy ikona chmurki zmieni się w zielony znacznik, uruchom ponownie. |

### Zgłoszenie do Maksa

Pod wyjaśnieniem Diagnozy jest przycisk `Wyślij do Maksa`. Gdy wyjaśnienie
mówi, co poprawić, pierwszy jest `Uruchom ponownie`, a `Wyślij do Maksa` drugi.

1. Rozwiń `Co zostanie wysłane`, jeśli chcesz zobaczyć dokładną treść
   Zgłoszenia: komunikat, proces, okres, wersję narzędzia, wynik każdego
   sprawdzenia Diagnozy i ostatnie wpisy dziennika Centrum. Nie ma w niej
   adresów, numerów zleceń ani treści wierszy.
2. Kliknij `Wyślij do Maksa`. Nie ma dodatkowego pytania „Na pewno?”.
3. W miejscu przycisku pojawi się `Zgłoszenie wysłane do Maksa. Poczekaj na
   naprawę.` Potwierdzenie zostaje po odświeżeniu karty.

Gdy ten sam problem wróci przy kolejnym Uruchomieniu, a Maks jeszcze go nie
naprawił, zamiast przycisku zobaczysz `Zgłoszenie tego problemu już jest
wysłane i czeka na naprawę.` Drugie Zgłoszenie nie powstaje. Gdy Maks zamknie
Zgłoszenie, a problem wróci, po Diagnozie znowu będzie `Wyślij do Maksa`.

Zgłoszenie trafia do prywatnego repozytorium Zgłoszeń Maksa na GitHubie.
Brak internetu niczego nie psuje, dopóki niczego nie wysyłasz.

### Zgłoszenie → co zrobić

Gdy wysłanie się nie uda, Centrum zapisze Zgłoszenie w pliku w folderze
narzędzia, w `config\zgloszenia`, i pokaże komunikat z przyciskiem
`Spróbuj ponownie`. Plik możesz przesłać Maksowi mailem jako załącznik.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „na tym komputerze nie ma klucza do Zgłoszeń” | Prześlij wskazany plik Maksowi mailem. Gdy Maks wpisze klucz, kliknij `Spróbuj ponownie`. |
| „klucz do Zgłoszeń wygasł albo jest nieważny” | Prześlij wskazany plik Maksowi mailem i powiedz mu o kluczu. Gdy Maks go wymieni, kliknij `Spróbuj ponownie`. |
| „brak połączenia z GitHubem” | Sprawdź internet i kliknij `Spróbuj ponownie`. Jeśli to nie pomoże, prześlij wskazany plik Maksowi mailem. |
| „nie udało się zapisać go w pliku” | Pliku nie ma. Rozwiń `Co zostanie wysłane`, skopiuj treść i wklej ją do maila do Maksa. Po odświeżeniu karty najpierw kliknij `Diagnoza`. |

Na stronie `Konfiguracja` widać `Zgłoszenia: gotowe`, gdy klucz do Zgłoszeń
jest na komputerze, albo `Zgłoszenia: brak klucza`, gdy go nie ma. Klucz wpisuje
Maks; Ty niczego tam nie wpisujesz.

### Powiadomienie o naprawie

Gdy Maks naprawi zgłoszony problem i zamknie Zgłoszenie, na stronie `Okresy`
pod tytułem pojawi się `Maks naprawił zgłoszony problem.` z przyciskiem
`Zaktualizuj narzędzie`.

Kliknij `Zaktualizuj narzędzie` (niżej, „Aktualizacja narzędzia”). Gdy karta
sama się odświeży w nowej wersji, powiadomienia już nie ma; niczego nie
zamykasz. Centrum sprawdza to przy otwarciu i przy wejściu na `Okresy`,
najwyżej raz na 10 minut.
Bez internetu nic się nie pokazuje i nic się nie psuje; Centrum sprawdzi
ponownie później.

### Aktualizacja narzędzia

Na stronie `Konfiguracja`, w karcie `Narzędzie`, widać wersję narzędzia, np.
`Wersja 1a2b3c4 od 20.10.2026`, i czy jest najnowsza: `Aktualna`, `Jest nowsza
wersja` albo `Nie sprawdzono` (bez internetu). Gdy Maks zapyta, którą wersję
masz, przeczytaj mu ją.

1. Kliknij `Zaktualizuj narzędzie`: na stronie `Konfiguracja`, w
   Powiadomieniu o naprawie na `Okresach` albo w Diagnozie. Każdy z tych
   przycisków robi to samo.
2. Poczekaj. Pod przyciskiem widać `Pobieranie nowej wersji…`, a gdy nowa
   wersja potrzebuje nowych bibliotek, potem `Instalowanie bibliotek…` (to może
   potrwać kilka minut). Na końcu widać `Ponowne uruchamianie Centrum…`. Każdy
   przycisk aktualizacji jest wtedy wyłączony. Nie zamykaj karty i nie klikaj
   skrótu: Centrum samo uruchamia się w nowej wersji.
3. Na końcu zobaczysz jedno z dwóch:
   - Karta sama się odświeży i na chwilę pokaże `Zaktualizowano`. Działa już
     nowa wersja; niczego nie zamykasz.
   - `Masz najnowszą wersję.` Niczego więcej nie robisz.

Gdy trwa Uruchomienie procesu, Centrum nie zaktualizuje narzędzia: poczekaj
na wynik na stronie `Uruchomienia`. W trakcie aktualizacji nie uruchomisz
procesu ani nie zamkniesz Centrum.

### Aktualizacja narzędzia → co zrobić

Gdy aktualizacja się nie uda, narzędzie działa dalej w wersji sprzed
kliknięcia (chyba że komunikat mówi, że nie dało się jej przywrócić), a pod
przyciskiem pojawi się komunikat w trzech częściach i przycisk `Wyślij do
Maksa`. Rozwiń `Co zostanie wysłane`, żeby zobaczyć Zgłoszenie
przed wysłaniem.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „brak połączenia z GitHubem” | Sprawdź internet i kliknij `Zaktualizuj narzędzie` jeszcze raz. |
| „nie ma Gita” | Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „GitHub prosi o logowanie” | Nie loguj się nigdzie. Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „inna gałąź narzędzia” | Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „zmiany zrobione na tym komputerze” | Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „Nie udało się zainstalować bibliotek” | Kliknij `Zaktualizuj narzędzie` jeszcze raz. Jeśli komunikat wraca, kliknij `Wyślij do Maksa`. |
| „z nieoczekiwanego powodu” | Kliknij `Zaktualizuj narzędzie` jeszcze raz. Jeśli komunikat wraca, kliknij `Wyślij do Maksa`. |
| „Nowa wersja narzędzia nie wystartowała” | Niczego nie zamykasz: Centrum samo wróciło do poprzedniej wersji, a karta odświeżyła się na niej z tym komunikatem pod tytułem strony. Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „nie dało się przywrócić poprzedniej wersji” | Kliknij `Zaktualizuj narzędzie` jeszcze raz. Jeśli komunikat wraca, kliknij `Wyślij do Maksa`. |

Bez internetu `Wyślij do Maksa` zapisze Zgłoszenie w pliku: postępuj wtedy
według tabeli „Zgłoszenie → co zrobić”.

### Komunikaty startu Centrum rozliczeń

Gdy Centrum nie może wystartować, zamiast karty pojawi się okienko z trzema
częściami: `Co się stało`, `Gdzie` i `Co zrobić`. Znajdź w tabeli wiersz z
fragmentem pierwszej części.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „zajmuje inny program” | Uruchom ponownie komputer i kliknij skrót. Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie. |
| „Działa już Centrum rozliczeń w innej wersji” | Zdarza się po aktualizacji narzędzia bez przycisku w Centrum. W otwartej karcie Centrum kliknij `Zamknij Centrum rozliczeń`, potem kliknij skrót ponownie. |
| „Brakuje biblioteki potrzebnej Centrum rozliczeń” | W folderze narzędzia uruchom `py -3 -m pip install -r requirements.txt` i kliknij skrót ponownie. |
| „nie wystartowało z nieoczekiwanego powodu” | Kliknij skrót ponownie. Jeśli komunikat wraca, przekaż osobie utrzymującej narzędzie plik `logs\centrum-rozliczen.log` z folderu narzędzia. |
| „nie wystartowało po aktualizacji narzędzia” | Nie wystartowała ani nowa, ani poprzednia wersja. Przekaż komunikat Maksowi. |
| „Aktualizacja narzędzia jeszcze się kończy” | Centrum właśnie startuje w nowej wersji albo wraca do poprzedniej. Poczekaj 10 minut i kliknij skrót ponownie. |

Plik `logs\centrum-rozliczen.log` to dziennik Centrum: zapisuje tylko start,
zamknięcie, port, rodzaj błędu, aktualizacje narzędzia i czas otwierania
stron, bez danych z Twoich plików. Możesz go bezpiecznie przekazać do diagnozy.

## Przygotowanie pliku zbiorczego

### Kiedy uruchomić

- Eksport zleceń całego okresu (od wtorku do poniedziałku) jest już w Rejestrze
  zleceń `ZLECENIA INTERMAX OD 08_11_2021.xlsx`.
- Rejestr zleceń jest zapisany i **zamknięty** w Excelu.
- Folder tygodnia jest założony w folderze `INEA` właściwego miesiąca
  (zob. [Foldery tygodni](#foldery-tygodni)) i nie ma jeszcze plików
  `Rozliczenie wew. {okres}.xlsx` ani `Rozliczenie {okres} - zbiorcze.xlsx`.

Narzędzie tylko czyta Rejestr zleceń i wzorce. Nigdy ich nie zmienia.

### Kroki

Rejestr zleceń i folder okresów wskazujesz raz w `Ustawieniach` na stronie
`Okresy`; potem Centrum je pamięta.

1. Na stronie `Okresy` karta `Następny krok` pokazuje ostatni pełny okres.
   Kliknij `Podgląd bez zapisu`. Żeby przygotować inny tydzień, kliknij
   `Przygotuj plik zbiorczy` w jego wierszu Tablicy okresów albo wybierz okres
   z listy `Okres` na stronie `Uruchomienia`.
2. Podgląd bez zapisu niczego nie tworzy. Pokazuje plan: liczby zleceń,
   ostrzeżenia, `Zlecenia na dzień` (dzień z liczbą `0` ma żółty znak) i nazwy
   obu plików. Na górze widać etapy `Sprawdzanie`, `Odczyt danych`,
   `Planowanie` i `Zapisywanie`.
3. Zapisz i zamknij Rejestr zleceń w Excelu. Kliknij `Uruchom` i potwierdź w
   okienku `Uruchomić z zapisem?`. Jeśli dla tego okresu nie było jeszcze
   udanego podglądu, okienko pokazuje żółtą uwagę `Nie było podglądu bez
   zapisu`; Centrum pamięta podgląd także po odświeżeniu karty.
4. Jeśli okres jest niepełny, pojawi się okienko `Kontynuować mimo niepełnego
   okresu?` z liczbami `Zlecenia na dzień`. Kliknij `Kontynuuj` albo `Przerwij
   bez zapisu`. Okienko czeka na Ciebie także po odświeżeniu albo ponownym
   otwarciu karty.
5. Wynik `Plik zbiorczy przygotowany` oznacza, że oba pliki powstały razem.
   Przycisk `Folder okresu` otwiera folder z nimi, a na stronie `Okresy` okres
   ma Status `Plik zbiorczy przygotowany`.

Zatrzymanie pokazuje od razu trzy części komunikatu: co się stało (tytuł),
gdzie (pinezka) i co zrobić (klucz). Tabela niżej objaśnia każdy komunikat.
Po poprawce kliknij `Uruchom ponownie`. Ostrzeżenia są osobno, pod wynikiem:
pliki powstały, ale coś wymaga uwagi.

Zamknięcie karty przeglądarki nie przerywa pracy. Gdy coś już trwa, drugie
uruchomienie dostaje komunikat, że trwa już Uruchomienie procesu. Zakładka
`Historia` pokazuje wszystkie uruchomienia, także dawne z launcherów `.cmd`
(z odznaką `.cmd`).

### Co sprawdzić po zakończeniu

- Wynik `Plik zbiorczy przygotowany` oznacza, że oba pliki powstały razem.
  Zatrzymanie oznacza, że nie powstał żaden plik. Wtedy znajdź komunikat w
  tabeli poniżej. Jedyny wyjątek to komunikat, że pliki okresu powstały, ale
  nie udało się pokazać podsumowania.
- Sprawdź podsumowanie: `Zlecenia okresu`, `Zlecenia skuteczne`,
  `Pominięte puste wiersze` i `Zlecenia na dzień`. Dzień z liczbą `0` może
  oznaczać brakujący eksport.
- `Pominięte puste wiersze` to wszystkie całkowicie puste wiersze Rejestru od
  pierwszego do ostatniego zlecenia okresu, także te między zleceniami innych
  tygodni. Nie trafiają do żadnego pliku.
- Liczba `Ostrzeżenia` większa od `0` oznacza, że pliki powstały, ale coś
  wymaga uwagi. Każde ostrzeżenie jest opisane w tabeli poniżej.
- W Folderze okresu (np. `INEA\08_14_09_2026`) są dwa nowe pliki:
  `Rozliczenie wew. {okres}.xlsx` i `Rozliczenie {okres} - zbiorcze.xlsx`.
- Rozliczenie wewnętrzne ma wszystkie zlecenia okresu, skuteczne i
  nieskuteczne, w kolejności z Rejestru, bez pustych wierszy i z wyróżnieniami
  kolorem i pogrubieniem jak w Rejestrze.
- Plik zbiorczy ma wszystkie Zlecenia skuteczne od wiersza 18, bez przerw.
  Stawki, sumy, formuły i link do Słownika są jak we wzorcu.

### Co dalej ręcznie

1. Uzupełnij `UWAGI` i `zwrot` w Rozliczeniu wewnętrznym.
2. Wpisz ilości 0/1 w Pliku zbiorczym. Jeśli chcesz pominąć jakieś Zlecenie
   skuteczne, usuń je ręcznie.
3. Zapisz i zamknij oba pliki.
4. Uruchom Przebieg rozliczeń w Centrum rozliczeń.

### Komunikat → co zrobić

Każdy komunikat ma trzy części: co się stało, gdzie i co zrobić. Znajdź w
tabeli wiersz z fragmentem pierwszej części. `Gdzie` wskazuje plik, arkusz albo
numery wierszy Rejestru zleceń. Po każdym zatrzymaniu nie powstał żaden plik,
więc po poprawce wystarczy uruchomić proces ponownie. Wyjątki: po komunikacie
o niepokazanym podsumowaniu pliki okresu już są, a po komunikacie o pliku,
którego nie udało się usunąć, w Folderze okresu został wskazany plik.

#### Zatrzymania

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń jest otwarty w Excelu” | Zapisz i zamknij Rejestr zleceń, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu Rejestru pozostawiony plik `~$ZLECENIA INTERMAX OD 08_11_2021.xlsx`. |
| „Nie znaleziono Rejestru zleceń” | W `Ustawieniach` na stronie `Okresy` wskaż właściwy plik Rejestru zleceń i uruchom ponownie. |
| „Nie można teraz odczytać Rejestru zleceń” | Nie poprawiaj Rejestru. Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy Rejestr otwiera się w Excelu. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać Rejestru zleceń” | Sprawdź, czy Rejestr otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „nie znaleziono arkusza ze zleceniami” | Sprawdź, czy w `Ustawieniach` wskazano plik Rejestru zleceń. Pierwszy wiersz arkusza ze zleceniami musi mieć wszystkie nagłówki wymienione w komunikacie. |
| „W Rejestrze zleceń brakuje” | Dopisz albo popraw wymieniony nagłówek w pierwszym wierszu arkusza ze zleceniami. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „więcej niż raz, więc nie wiadomo, z której kolumny brać dane” | Zostaw wymieniony nagłówek tylko w jednej kolumnie: zmień nazwę drugiej kolumny albo ją usuń. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „Zlecenia tego okresu są w więcej niż jednym arkuszu” | Przenieś zlecenia tego okresu do jednego z wymienionych arkuszy. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „bez poprawnej daty w kolumnie DATA GODZ. POCZ.” | We wskazanych wierszach wpisz datę zlecenia albo wyczyść cały wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „tak ani nie w SKUTECZNE” | `Gdzie` pokazuje komórki Rejestru zleceń, np. `L42081`: osobno puste i osobno z inną wartością, z jej treścią w cudzysłowie. We wszystkich wskazanych komórkach wpisz `tak` albo `nie`. Braki w `SKUTECZNE` poprawiaj w Rejestrze zleceń przed uruchomieniem, a nie w Rozliczeniu wewnętrznym, bo Rozliczenie wewnętrzne powstaje z Rejestru. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „spoza konfiguracji wykonawców” | Literówkę w `WYKONAWCA` popraw we wskazanych wierszach Rejestru. Nowego wykonawcę trzeba dopisać do konfiguracji wykonawców (`config\worker_mapping.yaml`, tej samej co w Przebiegu rozliczeń); poproś o to osobę utrzymującą narzędzie. |
| „nie ma żadnego zlecenia z tego okresu” | Sprawdź, czy wybrano właściwy okres i czy eksport zleceń jest zapisany w Rejestrze. Uruchom ponownie. |
| „Plik tego okresu już istnieje” | Narzędzie nie nadpisuje plików okresu, żeby nie stracić ręcznych poprawek. Sprawdź okres. Jeśli plik ma powstać od nowa, przenieś albo usuń wskazany plik i uruchom ponownie. Jeśli w Folderze okresu jest samo Rozliczenie wewnętrzne, bez Pliku zbiorczego, a poprzednie uruchomienie nie doszło do wyniku (np. zabrakło prądu), to jest niedokończony zapis: usuń to Rozliczenie wewnętrzne i uruchom ponownie. |
| „Nie znaleziono folderu okresów” | W `Ustawieniach` na stronie `Okresy` wskaż istniejący folder okresów, np. `Załączniki`, i uruchom ponownie. |
| „Nie można teraz odczytać folderu” | Otwórz folder wskazany w `Gdzie` w Eksploratorze plików. Jeśli się nie otwiera albo OneDrive pokazuje błąd, uruchom OneDrive i poczekaj, aż skończy synchronizację, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „w żadnym folderze miesiąca” | W `Rozliczenia {rok}` nie ma folderu tego tygodnia. W folderze `INEA` miesiąca, do którego należy tydzień, załóż pusty folder o nazwie okresu, np. `13_19_10_2026`, i uruchom ponownie. Pliki w nim zrobi narzędzie. |
| „jest w więcej niż jednym folderze miesiąca” | `Gdzie` pokazuje oba miesiące z folderem tego tygodnia. Zostaw folder tylko w tym miesiącu, w którym ma być rozliczony: drugi usuń albo zmień mu nazwę, np. dopisz na końcu ` stary`. Uruchom ponownie. |
| „Przerwano z powodu niepełnego okresu” | Uzupełnij eksport zleceń w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli okres jest pełny, w okienku kliknij `Kontynuuj`. |
| „Nie znaleziono wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. Nie twórz wzorca z pliku poprzedniego tygodnia. |
| „Wzorzec jest otwarty w Excelu” | Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu `config` pozostawiony plik `~$` wskazany w komunikacie. |
| „Nie można odczytać wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu brakuje nagłówka” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie” | Przebieg rozliczeń czyta wykonawcę tylko z kolumny H. Otwórz `config\Wzorzec pliku zbiorczego.xlsx` i w wierszu 17 przenieś WYKONAWCA do kolumny H, a nagłówek z kolumny H do kolumny wskazanej w komunikacie. Zapisz i zamknij wzorzec, uruchom ponownie. Jeśli nie wiesz, jak to zrobić, przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu są scalone komórki” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać konfiguracji wykonawców” | Przekaż komunikat osobie utrzymującej narzędzie. Ta sama konfiguracja jest potrzebna w Przebiegu rozliczeń. |
| „Zapisano tylko jeden z dwóch plików okresu” | Usuń z Folderu okresu plik wskazany w `Gdzie` i uruchom ponownie. Jeśli Windows nie pozwala go usunąć, odczekaj chwilę, bo plik może sprawdzać antywirus albo OneDrive. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się zapisać plików okresu” | Sprawdź, czy folder okresów jest dostępny i czy pliki okresu nie są otwarte w Excelu, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Pliki okresu powstały, ale nie udało się pokazać podsumowania” | Pojawia się po zapisie plików. Oba pliki są już w Folderze okresu, więc nie uruchamiaj procesu ponownie. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się pokazać planu” | Pojawia się tylko w podglądzie bez zapisu. Nic nie zapisano. Przekaż komunikat osobie utrzymującej narzędzie. |

#### Ostrzeżenia

Ostrzeżenie nie zatrzymuje procesu. Ostrzeżenie o niepełnym okresie pojawia
się przed zapisem w okienku `Kontynuować mimo niepełnego okresu?`. Ostrzeżenie
o wierszach z zerami pojawia się w podsumowaniu, gdy pliki już powstały.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu” | Sprawdź `Zlecenia na dzień`. Jeśli brakuje zleceń z końca tygodnia, kliknij `Przerwij bez zapisu`, uzupełnij eksport w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli w te dni naprawdę nie było zleceń, kliknij `Kontynuuj`. |
| „Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości” | Pliki powstały. We wskazanych wierszach Pliku zbiorczego wpisz ilości ręcznie. Jeśli zdarza się to często, poproś osobę utrzymującą narzędzie o dodanie wierszy z zerami we Wzorcu pliku zbiorczego. |

## Przebieg rozliczeń

### Przed uruchomieniem

1. Zakończ pracę w pliku `Rozliczenie {okres} - zbiorcze.xlsx`.
2. Zamknij ten plik w Excelu.
3. Upewnij się, że folder `Rozliczenie pracowników {okres}` jest dostępny.

### Kroki

Plik zbiorczy wynika z okresu, więc go nie szukasz: Centrum bierze
`Rozliczenie {okres} - zbiorcze.xlsx` z Folderu okresu w folderze okresów.

1. Uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij (Gotowość). Centrum
   nie sprawdza, czy skończyłeś: to Ty decydujesz, kiedy plik jest gotowy.
2. Na stronie `Okresy` okres ma Status `Plik zbiorczy przygotowany`, a karta
   `Następny krok` pokazuje `Utwórz rozliczenia pracowników`. Kliknij
   `Podgląd bez zapisu`. Dla innego tygodnia kliknij `Utwórz rozliczenia
   pracowników` w jego wierszu Tablicy okresów albo na stronie `Uruchomienia`
   wybierz kafelek `Przebieg rozliczeń` i okres z listy `Okres`. Lista ma tylko
   okresy ze Statusem `Plik zbiorczy przygotowany`.
3. Podgląd bez zapisu niczego nie tworzy. Pokazuje liczby `Wiersze danych`,
   `Planowane szablony` i `Puste szablony` oraz zwijany `Plan plików`: nazwę
   pliku każdego Wykonawcy z liczbą wierszy (`Pusty skoroszyt`, gdy Wykonawca
   nie ma wierszy).
4. Kliknij `Uruchom` i potwierdź w okienku `Uruchomić z zapisem?`. To kliknięcie
   jest potwierdzeniem Gotowości, więc zrób je dopiero po zamknięciu Pliku
   zbiorczego w Excelu.
5. W trakcie widać etapy, liczniki (`Wiersze danych`, `Zapisane szablony`,
   `Puste szablony`, `Problemy`) i pasek `Szablony
   pracowników` z bieżącym Wykonawcą i liczbą, np. `2 z 7`. Zamknięcie Centrum
   rozliczeń jest wtedy zablokowane.
6. Wynik `Rozliczenia pracowników gotowe` oznacza, że cały folder
   `Rozliczenie pracowników {okres}` powstał naraz. Pokazuje liczby `Zapisane
   szablony` i `Puste szablony`. Przycisk `Folder okresu`
   otwiera folder, a na stronie `Okresy` okres ma Status `Rozliczenia
   pracowników gotowe`. Otwórz pliki pracowników i sprawdź ich zawartość.
7. Wiersze w pliku pracownika wyglądają jak w Pliku zbiorczym: mają te same
   kolory wypełnienia, kolory czcionki, pogrubienia i kursywy. Krój i rozmiar
   czcionki, format liczb i obramowania są jak we Wzorcu rozliczenia
   pracownika.

Wynik z żółtym znakiem `Podgląd wymaga sprawdzenia · nic nie zapisano` to nie
sukces: pod nim są problemy w Pliku zbiorczym, każdy w trzech częściach. Popraw
je, zapisz i zamknij Plik zbiorczy i kliknij `Uruchom ponownie`. Zapis
(`Uruchom`) z takimi problemami zatrzyma się bez tworzenia plików.

Zatrzymanie pokazuje od razu trzy części komunikatu: co się stało (tytuł),
gdzie (pinezka) i co zrobić (klucz). Komunikaty są w tabeli niżej.

### Komunikat w Centrum rozliczeń → co zrobić

Po każdym zatrzymaniu nie powstał Folder rozliczeń pracowników. Wyjątkiem jest
komunikat o niepokazanym podsumowaniu: wtedy rozliczenia pracowników już są.
Jeśli komunikat mówi, że pliki pracowników zostały w folderze tymczasowym,
najpierw usuń z Folderu okresu folder, który wskazuje (jego nazwa zaczyna się
kropką i ma w sobie `.staging-`). To nie jest Folder rozliczeń pracowników.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znaleziono Pliku zbiorczego tego okresu” | Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod nazwą `Rozliczenie {okres} - zbiorcze.xlsx`. Jeśli okresu nie przygotowano, najpierw przygotuj plik zbiorczy. |
| „Plik zbiorczy jest otwarty w Excelu” | Zapisz i zamknij Plik zbiorczy, potem kliknij `Uruchom ponownie`. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z Folderu okresu pozostawiony plik `~$` z nazwą Pliku zbiorczego. |
| „Nie można teraz odczytać Pliku zbiorczego” | Nie poprawiaj Pliku zbiorczego. Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy plik otwiera się w Excelu. Zamknij go i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Plik zbiorczy nie nadaje się do Przebiegu rozliczeń” | Dalsza część komunikatu mówi, co jest nie tak (np. plik nie otwiera się w Excelu albo nie ma nagłówka WYKONAWCA). Popraw Plik zbiorczy, zapisz go, zamknij i uruchom ponownie. |
| „Folder rozliczeń pracowników tego okresu już istnieje” | Rozliczenia pracowników tego okresu już są; narzędzie ich nie nadpisze. Sprawdź, czy wybrano właściwy okres. Żeby utworzyć je od nowa, najpierw przenieś ten folder poza Folder okresu. |
| „Konfiguracja wykonawców jest niepoprawna” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można użyć Wzorca rozliczenia pracownika” | Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania i uruchom ponownie. Jeśli komunikat prosi o zmianę nazwy `placeholder.xlsx`, zrób to jak w części „Gdy pojawi się problem” niżej. W innym wypadku przekaż komunikat osobie utrzymującej narzędzie. |
| „W Pliku zbiorczym jest WYKONAWCA, którego nie ma w konfiguracji wykonawców” | Uruchom `Podgląd bez zapisu`, żeby zobaczyć problemy. Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy. Zapisz, zamknij i uruchom ponownie. |
| „Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ” | Uruchom `Podgląd bez zapisu`: problemy pokażą numery wierszy. Wpisz w nich WYKONAWCĘ w kolumnie H, zapisz, zamknij i uruchom ponownie. |
| „Nieznany identyfikator WYKONAWCA” | Problem z podglądu (wynik wymaga sprawdzenia). Popraw WYKONAWCĘ w kolumnie H albo poproś o dopisanie Wykonawcy do konfiguracji wykonawców. |
| „ma dane, ale nie ma wykonawcy w kolumnie H” | Problem z podglądu (wynik wymaga sprawdzenia). Wpisz WYKONAWCĘ we wskazanym wierszu albo wyczyść wiersz, jeśli jest zbędny. |
| „Nie udało się przygotować skoroszytu pracownika” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można opublikować gotowego Folderu rozliczeń pracowników” | Jeśli komunikat prosi o usunięcie folderu tymczasowego, usuń go z Folderu okresu; gdy się nie daje, odczekaj chwilę. Sprawdź, czy Folder okresu jest dostępny, i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można przygotować Folderu rozliczeń pracowników” | Sprawdź, czy Folder okresu jest dostępny, i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania” | Nie uruchamiaj ponownie: folder rozliczeń pracowników już jest. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się pokazać planu” | Nic nie zapisano. Przekaż komunikat osobie utrzymującej narzędzie. |

### Gdy pojawi się problem

- Jeśli plik jest otwarty, zamknij go i uruchom proces ponownie.
- Jeśli narzędzie napisze, że folder tygodnia jest w więcej niż jednym folderze miesiąca, zostaw go tylko w jednym miesiącu: drugi usuń albo zmień mu nazwę. Uruchom proces ponownie.
- Jeśli pojawi się komunikat „Nie znaleziono Wzorca rozliczenia pracownika” z prośbą o zmianę nazwy pliku `placeholder.xlsx`, zmień w folderze `config` narzędzia nazwę tego pliku na `Wzorzec rozliczenia pracownika.xlsx` i uruchom proces ponownie. Bez tej prośby przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się komunikat „Nie można odczytać Pliku zbiorczego”, sprawdź, czy ten plik otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom proces ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się informacja o braku szablonu, nie twórz pliku ręcznie z innego pracownika. Przekaż tę informację osobie utrzymującej narzędzie.
- Jeśli plik pracownika ma już dane, narzędzie go nie nadpisze.
