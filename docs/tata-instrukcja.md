# Instrukcja dla taty

Co tydzień są dwa kroki, zawsze w tej kolejności:

1. **Przygotowanie pliku zbiorczego**: z Rejestru zleceń powstają Rozliczenie
   wewnętrzne i Plik zbiorczy okresu (`Przygotuj plik zbiorczy.cmd`).
2. **Przebieg rozliczeń**: z Pliku zbiorczego powstają rozliczenia
   pracowników (`Utwórz rozliczenia.cmd`).

Narzędzie ma dwa wejścia, które działają obok siebie:

| Co chcesz zrobić | Centrum rozliczeń (skrót na pulpicie) | Launchery `.cmd` w folderze narzędzia |
|---|---|---|
| Zobaczyć Status okresu każdego tygodnia | Strona `Okresy` | — |
| Otworzyć Plik zbiorczy, Rozliczenie wewnętrzne albo Folder okresu | Jedno kliknięcie w wierszu okresu | Ręcznie w Eksploratorze |
| Przygotować plik zbiorczy | Strona `Uruchomienia`, proces `Przygotowanie pliku zbiorczego` | `Przygotuj plik zbiorczy.cmd` |
| Utworzyć rozliczenia pracowników | Strona `Uruchomienia`, proces `Przebieg rozliczeń` | `Utwórz rozliczenia.cmd` |

Oba procesy możesz uruchomić w Centrum rozliczeń albo launcherami `.cmd`,
opisanymi niżej. Launchery działają też wtedy, gdy Centrum rozliczeń nie
wystartuje.

## Pierwsza instalacja

1. Zainstaluj Python 3.11 lub nowszy.
2. W folderze narzędzia uruchom:

   ```powershell
   py -3 -m pip install -r requirements.txt
   ```

3. Dwukrotnie kliknij `Zainstaluj skrót Centrum rozliczeń.cmd`. Na pulpicie
   pojawi się skrót „Centrum rozliczeń” z ikoną. Naciśnij dowolny klawisz, żeby
   zamknąć okno. Ten krok powtórz tylko po przeniesieniu folderu narzędzia albo
   po instalacji nowego Pythona.

Lista zależności zawiera `rich`, potrzebny do kolorowego dashboardu. Bez
kolorów lub bez interaktywnego terminala narzędzie przełącza się na zwykły tekst.

Osoba utrzymująca narzędzie umieszcza w folderze `config` narzędzia trzy
wzorce: `Wzorzec rozliczenia wewnętrznego.xlsx`, `Wzorzec pliku zbiorczego.xlsx`
i `Wzorzec rozliczenia pracownika.xlsx`. Ten ostatni to pusty plik rozliczenia
pracownika bez nazwy wykonawcy (u Ciebie `Rozliczenie {okres} -.xlsx`); z niego
powstają pliki pracowników.
Nie zmieniaj ich i nie podmieniaj plikami z poprzedniego tygodnia.

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
   `Rozliczenia 2026`), i Rejestr zleceń. Centrum je zapamięta, a launchery
   `.cmd` też z nich skorzystają.

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
- `Diagnoza`: komunikat każe przekazać go osobie utrzymującej narzędzie, wystąpił
  nieoczekiwany błąd albo po ponownym uruchomieniu wrócił ten sam komunikat.
  Kliknij `Diagnoza`. Centrum sprawdzi Twój komputer tylko do odczytu i wyjaśni
  przyczynę w trzech częściach. Niczego nie zmienia w Twoich plikach.

Gdy przyczyną jest sam komunikat zatrzymania, Centrum pisze tylko `Diagnoza
potwierdza ten komunikat.` Gdy wyjaśnienie mówi, co zrobić, popraw to i kliknij
`Uruchom ponownie`. Lista `Sprawdzono` pokazuje każde sprawdzenie Diagnozy.

### Wyjaśnienie Diagnozy → co zrobić

Diagnoza wyjaśnia przyczynę komunikatem z tabel procesów (np. Rejestr zleceń
otwarty w Excelu) albo jednym z tych:

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znalazłem przyczyny na tym komputerze” | Przyczyna nie leży na Twoim komputerze. Kliknij `Wyślij do Maksa`. |
| „Jest nowsza wersja narzędzia” | Zaktualizuj narzędzie. Potem w karcie Centrum kliknij `Zamknij Centrum rozliczeń`, otwórz Centrum skrótem i uruchom proces ponownie. Bez internetu Diagnoza tego nie sprawdza. |
| „Plik okresu jest otwarty w Excelu” | Zapisz i zamknij wskazany plik w Excelu i uruchom ponownie. Jeśli Excel jest zamknięty, usuń z tego samego folderu pozostawiony plik zaczynający się od `~$`. |
| „Plik jest tylko w OneDrive w chmurze” | W Eksploratorze plików kliknij wskazany plik prawym przyciskiem myszy i wybierz „Zawsze zachowuj na tym urządzeniu”. Gdy ikona chmurki zmieni się w zielony znacznik, uruchom ponownie. |
| „jest nieoczekiwany wyjątek narzędzia” | Przekaż komunikat osobie utrzymującej narzędzie. |

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

Na stronie `Konfiguracja` widać `Zgłoszenia: gotowe`, gdy klucz do Zgłoszeń
jest na komputerze, albo `Zgłoszenia: brak klucza`, gdy go nie ma. Klucz wpisuje
Maks; Ty niczego tam nie wpisujesz.

### Powiadomienie o naprawie

Gdy Maks naprawi zgłoszony problem i zamknie Zgłoszenie, na stronie `Okresy`
pod tytułem pojawi się `Maks naprawił zgłoszony problem. Zaktualizuj
narzędzie.`

1. Zaktualizuj narzędzie.
2. W karcie Centrum kliknij `Zamknij Centrum rozliczeń` i otwórz Centrum
   skrótem.

Po aktualizacji powiadomienie zniknie samo; niczego nie zamykasz. Centrum
sprawdza to przy otwarciu i przy wejściu na `Okresy`, najwyżej raz na 10 minut.
Bez internetu nic się nie pokazuje i nic się nie psuje; Centrum sprawdzi
ponownie później.

### Komunikaty startu Centrum rozliczeń

Gdy Centrum nie może wystartować, zamiast karty pojawi się okienko z trzema
częściami: `Co się stało`, `Gdzie` i `Co zrobić`. Znajdź w tabeli wiersz z
fragmentem pierwszej części. Przebieg rozliczeń i Przygotowanie pliku
zbiorczego możesz zawsze uruchomić launcherami `.cmd`.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „zajmuje inny program” | Uruchom ponownie komputer i kliknij skrót. Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie. |
| „Działa już Centrum rozliczeń w innej wersji” | Zdarza się po aktualizacji narzędzia. W otwartej karcie Centrum kliknij `Zamknij Centrum rozliczeń`, potem kliknij skrót ponownie. |
| „Brakuje biblioteki potrzebnej Centrum rozliczeń” | W folderze narzędzia uruchom `py -3 -m pip install -r requirements.txt` i kliknij skrót ponownie. |
| „nie wystartowało z nieoczekiwanego powodu” | Kliknij skrót ponownie. Jeśli komunikat wraca, przekaż osobie utrzymującej narzędzie plik `logs\centrum-rozliczen.log` z folderu narzędzia. |

Plik `logs\centrum-rozliczen.log` to dziennik Centrum: zapisuje tylko start,
zamknięcie, port i rodzaj błędu, bez danych z Twoich plików. Możesz go
bezpiecznie przekazać do diagnozy.

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

1. Dwukrotnie kliknij `Przygotuj plik zbiorczy.cmd`.
2. Rejestr zleceń i folder okresów narzędzie bierze z Centrum rozliczeń. Okno
   wyboru pojawi się tylko wtedy, gdy nie wskazano ich w Centrum albo plik
   zniknął z dysku: wtedy w pierwszym oknie wybierz plik Rejestru zleceń
   `ZLECENIA INTERMAX OD 08_11_2021.xlsx`,
3. a w drugim folder okresów `Załączniki`.
4. Narzędzie pokaże `Proponowany okres:`, czyli ostatni pełny tydzień od wtorku
   do poniedziałku przed dzisiejszą datą.
   - Naciśnij Enter, żeby go potwierdzić.
   - Żeby przygotować inny tydzień, wpisz okres tak jak nazwę folderu, np.
     `08_14_09_2026` (wtorek 8, poniedziałek 14 września 2026) i naciśnij Enter.
     Na przełomie miesięcy miesiąc i rok są z poniedziałku, np. `27_02_11_2026`
     dla 27 października – 2 listopada 2026 albo `29_04_01_2027` dla
     29 grudnia 2026 – 4 stycznia 2027.
   - Po złym zapisie narzędzie wyjaśni, co poprawić, i zapyta ponownie.
5. Jeśli po etapie `Planowanie` pojawi się `Ostrzeżenie: niepełny okres`,
   sprawdź liczby `Zlecenia na dzień`. Wpisz `t`, żeby kontynuować, albo `n`,
   żeby przerwać bez tworzenia plików.
6. Poczekaj na `Status końcowy`. Potem naciśnij dowolny klawisz, żeby zamknąć
   okno. Nie zamykaj okna wcześniej: w trakcie zapisu może zostać samo
   Rozliczenie wewnętrzne.

### Kroki w Centrum rozliczeń

To samo Przygotowanie pliku zbiorczego można zrobić w Centrum rozliczeń, bez
okna terminala. Rejestr zleceń i folder okresów wskazujesz raz w `Ustawieniach`
na stronie `Okresy`; potem Centrum je pamięta.

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
gdzie (pinezka) i co zrobić (klucz). To ta sama treść co w terminalu, więc
tabela niżej też pasuje. Po poprawce kliknij `Uruchom ponownie`. Ostrzeżenia
są osobno, pod wynikiem: pliki powstały, ale coś wymaga uwagi.

Zamknięcie karty przeglądarki nie przerywa pracy. Gdy coś już trwa, drugie
uruchomienie dostaje komunikat, że trwa już Uruchomienie procesu. Zakładka
`Historia` pokazuje wszystkie uruchomienia, także te z `.cmd` (z odznaką
`.cmd`).

### Co sprawdzić po zakończeniu

- `Status końcowy: OK` oznacza, że oba pliki powstały razem.
  `Status końcowy: ZATRZYMANO` albo `BŁĄD` oznacza, że nie powstał żaden plik.
  Wtedy znajdź komunikat w tabeli poniżej. Jedyny wyjątek to komunikat, że
  pliki okresu powstały, ale nie udało się pokazać podsumowania.
- Sprawdź podsumowanie: `Okres`, `Zlecenia okresu`, `Zlecenia skuteczne`,
  `Pominięte puste wiersze` i `Zlecenia na dzień`. Dzień z liczbą `0` może
  oznaczać brakujący eksport.
- `Pominięte puste wiersze` to wszystkie całkowicie puste wiersze Rejestru od
  pierwszego do ostatniego zlecenia okresu, także te między zleceniami innych
  tygodni. Nie trafiają do żadnego pliku.
- Liczba przy `Ostrzeżenia:` większa od `0` oznacza, że pliki powstały, ale coś wymaga
  uwagi. Każde ostrzeżenie jest opisane w tabeli poniżej.
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
4. Uruchom Przebieg rozliczeń w Centrum rozliczeń albo `Utwórz rozliczenia.cmd`.

### Komunikat → co zrobić

Każdy komunikat ma trzy linie: `Co się stało`, `Gdzie` i `Co zrobić`. Znajdź w
tabeli wiersz z fragmentem pierwszej linii. `Gdzie` wskazuje plik, arkusz albo
numery wierszy Rejestru zleceń. Po każdym zatrzymaniu nie powstał żaden plik,
więc po poprawce wystarczy uruchomić proces ponownie. Wyjątki: po komunikacie
o niepokazanym podsumowaniu pliki okresu już są, a po komunikacie o pliku,
którego nie udało się usunąć, w Folderze okresu został wskazany plik.

#### Zatrzymania

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń jest otwarty w Excelu” | Zapisz i zamknij Rejestr zleceń, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu Rejestru pozostawiony plik `~$ZLECENIA INTERMAX OD 08_11_2021.xlsx`. |
| „Nie znaleziono Rejestru zleceń” | Uruchom ponownie i wybierz właściwy plik Rejestru zleceń. |
| „Nie można odczytać Rejestru zleceń” | Sprawdź, czy Rejestr otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „nie znaleziono arkusza ze zleceniami” | Sprawdź, czy wybrano plik Rejestru zleceń. Pierwszy wiersz arkusza ze zleceniami musi mieć wszystkie nagłówki wymienione w komunikacie. |
| „W Rejestrze zleceń brakuje” | Dopisz albo popraw wymieniony nagłówek w pierwszym wierszu arkusza ze zleceniami. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „więcej niż raz, więc nie wiadomo, z której kolumny brać dane” | Zostaw wymieniony nagłówek tylko w jednej kolumnie: zmień nazwę drugiej kolumny albo ją usuń. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „Zlecenia tego okresu są w więcej niż jednym arkuszu” | Przenieś zlecenia tego okresu do jednego z wymienionych arkuszy. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „bez poprawnej daty w kolumnie DATA GODZ. POCZ.” | We wskazanych wierszach wpisz datę zlecenia albo wyczyść cały wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „puste albo nieznane SKUTECZNE” | We wskazanych wierszach wpisz w `SKUTECZNE` `tak` albo `nie`. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „spoza konfiguracji wykonawców” | Literówkę w `WYKONAWCA` popraw we wskazanych wierszach Rejestru. Nowego wykonawcę trzeba dopisać do konfiguracji wykonawców (`config\worker_mapping.yaml`, tej samej co w Przebiegu rozliczeń); poproś o to osobę utrzymującą narzędzie. |
| „nie ma żadnego zlecenia z tego okresu” | Sprawdź, czy wybrano właściwy okres i czy eksport zleceń jest zapisany w Rejestrze. Uruchom ponownie. |
| „Plik tego okresu już istnieje” | Narzędzie nie nadpisuje plików okresu, żeby nie stracić ręcznych poprawek. Sprawdź okres. Jeśli plik ma powstać od nowa, przenieś albo usuń wskazany plik i uruchom ponownie. Jeśli w Folderze okresu jest samo Rozliczenie wewnętrzne, bez Pliku zbiorczego, a poprzednie uruchomienie nie doszło do `Status końcowy` (okno zostało zamknięte albo zabrakło prądu), to jest niedokończony zapis: usuń to Rozliczenie wewnętrzne i uruchom ponownie. |
| „Nie znaleziono folderu okresów” | Uruchom ponownie i wybierz istniejący folder okresów, np. `Załączniki`. |
| „w żadnym folderze miesiąca” | W `Rozliczenia {rok}` nie ma folderu tego tygodnia. W folderze `INEA` miesiąca, do którego należy tydzień, załóż pusty folder o nazwie okresu, np. `13_19_10_2026`, i uruchom ponownie. Pliki w nim zrobi narzędzie. |
| „jest w więcej niż jednym folderze miesiąca” | `Gdzie` pokazuje oba miesiące z folderem tego tygodnia. Zostaw folder tylko w tym miesiącu, w którym ma być rozliczony: drugi usuń albo zmień mu nazwę, np. dopisz na końcu ` stary`. Uruchom ponownie. |
| „Okres nie ma postaci dd_dd_mm_rrrr od wtorku do poniedziałku” | Wpisz okres jak nazwę folderu: dzień wtorku, dzień poniedziałku, miesiąc i rok, np. `08_14_09_2026`. Na przełomie miesięcy miesiąc i rok są z poniedziałku, np. `27_02_11_2026` (27 października – 2 listopada 2026). |
| „Nie wybrano pliku Rejestru zleceń” | Uruchom ponownie i w pierwszym oknie wybierz plik Rejestru zleceń. |
| „Nie wybrano folderu okresów” | Uruchom ponownie i w drugim oknie wybierz folder okresów, np. `Załączniki`. |
| „Nie potwierdzono okresu ani nie wpisano innego” | Uruchom ponownie. Przy pytaniu `Okres:` naciśnij Enter albo wpisz okres. |
| „Przerwano z powodu niepełnego okresu” | Uzupełnij eksport zleceń w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli okres jest pełny, przy pytaniu wpisz `t`. |
| „Nie znaleziono wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. Nie twórz wzorca z pliku poprzedniego tygodnia. |
| „Wzorzec jest otwarty w Excelu” | Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu `config` pozostawiony plik `~$` wskazany w komunikacie. |
| „Nie można odczytać wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu brakuje nagłówka” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie” | Przebieg rozliczeń czyta wykonawcę tylko z kolumny H. Otwórz `config\Wzorzec pliku zbiorczego.xlsx` i w wierszu 17 przenieś WYKONAWCA do kolumny H, a nagłówek z kolumny H do kolumny wskazanej w komunikacie. Zapisz i zamknij wzorzec, uruchom ponownie. Jeśli nie wiesz, jak to zrobić, przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu są scalone komórki” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać konfiguracji wykonawców” | Przekaż komunikat osobie utrzymującej narzędzie. Ta sama konfiguracja jest potrzebna w Przebiegu rozliczeń. |
| „Zapisano tylko jeden z dwóch plików okresu” | Usuń z Folderu okresu plik wskazany w `Gdzie` i uruchom ponownie. Jeśli Windows nie pozwala go usunąć, odczekaj chwilę, bo plik może sprawdzać antywirus albo OneDrive. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się zapisać plików okresu” | Sprawdź, czy folder okresów jest dostępny i czy pliki okresu nie są otwarte w Excelu, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Pojawia się ze `Status końcowy: BŁĄD`. Uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Pliki okresu powstały, ale nie udało się pokazać podsumowania” | Pojawia się ze `Status końcowy: BŁĄD` po zapisie plików (tryb `RUN`). Oba pliki są już w Folderze okresu, więc nie uruchamiaj procesu ponownie. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się pokazać planu” | Pojawia się ze `Status końcowy: BŁĄD` tylko w podglądzie bez zapisu (tryb `DRY-RUN`). Nic nie zapisano. Przekaż komunikat osobie utrzymującej narzędzie. |

#### Ostrzeżenia

Ostrzeżenie nie zatrzymuje procesu. Ostrzeżenie o niepełnym okresie pojawia
się przed zapisem razem z pytaniem. Ostrzeżenie o wierszach z zerami pojawia
się w podsumowaniu, gdy pliki już powstały.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu” | Sprawdź `Zlecenia na dzień`. Jeśli brakuje zleceń z końca tygodnia, wpisz `n`, uzupełnij eksport w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli w te dni naprawdę nie było zleceń, wpisz `t`. |
| „Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości” | Pliki powstały. We wskazanych wierszach Pliku zbiorczego wpisz ilości ręcznie. Jeśli zdarza się to często, poproś osobę utrzymującą narzędzie o dodanie wierszy z zerami we Wzorcu pliku zbiorczego. |

Linia `Nie zapisano metryk` dotyczy tylko lokalnej historii czasów działania.
Pliki okresu powstały niezależnie od niej.

## Przebieg rozliczeń

### Przed uruchomieniem

1. Zakończ pracę w pliku `Rozliczenie {okres} - zbiorcze.xlsx`.
2. Zamknij ten plik w Excelu.
3. Upewnij się, że folder `Rozliczenie pracowników {okres}` jest dostępny.

### Uruchomienie

1. Dwukrotnie kliknij `Utwórz rozliczenia.cmd`.
2. Narzędzie pokaże `Proponowany okres:`. Naciśnij Enter albo wpisz inny okres,
   jak przy Przygotowaniu pliku zbiorczego. Plik zbiorczy narzędzie samo
   znajdzie w folderze tygodnia. Gdy w Centrum rozliczeń nie wskazano folderu
   okresów, zamiast pytania pojawi się okno wyboru: wybierz plik zakończony
   słowami `- zbiorcze.xlsx`.
3. Poczekaj na komunikat końcowy.
4. Otwórz pliki pracowników i sprawdź ich zawartość.

### Kroki w Centrum rozliczeń

Ten sam Przebieg rozliczeń można zrobić w Centrum rozliczeń, bez okna terminala
i bez szukania pliku. Plik zbiorczy wynika z okresu: Centrum bierze
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
   pracowników gotowe`.

Wynik z żółtym znakiem `Podgląd wymaga sprawdzenia · nic nie zapisano` to nie
sukces: pod nim są problemy w Pliku zbiorczym, każdy w trzech częściach. Popraw
je, zapisz i zamknij Plik zbiorczy i kliknij `Uruchom ponownie`. Zapis
(`Uruchom`) z takimi problemami zatrzyma się bez tworzenia plików.

Zatrzymanie pokazuje od razu trzy części komunikatu: co się stało (tytuł),
gdzie (pinezka) i co zrobić (klucz). Komunikaty Centrum są w tabeli niżej; w
terminalu ten sam problem ma jedną linię po `Nie wykonano:`.

### Komunikat w Centrum rozliczeń → co zrobić

Po każdym zatrzymaniu nie powstał żaden plik pracownika. Wyjątkiem jest
komunikat o niepokazanym podsumowaniu: wtedy rozliczenia pracowników już są.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znaleziono Pliku zbiorczego tego okresu” | Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod nazwą `Rozliczenie {okres} - zbiorcze.xlsx`. Jeśli okresu nie przygotowano, najpierw przygotuj plik zbiorczy. |
| „Plik zbiorczy jest otwarty w Excelu” | Zapisz i zamknij Plik zbiorczy, potem kliknij `Uruchom ponownie`. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z Folderu okresu pozostawiony plik `~$` z nazwą Pliku zbiorczego. |
| „Plik zbiorczy nie nadaje się do Przebiegu rozliczeń” | Dalsza część komunikatu mówi, co jest nie tak (np. plik nie otwiera się w Excelu albo nie ma nagłówka WYKONAWCA). Popraw Plik zbiorczy, zapisz go, zamknij i uruchom ponownie. |
| „Folder rozliczeń pracowników tego okresu już istnieje” | Rozliczenia pracowników tego okresu już są; narzędzie ich nie nadpisze. Sprawdź, czy wybrano właściwy okres. Żeby utworzyć je od nowa, najpierw przenieś ten folder poza Folder okresu. |
| „Konfiguracja wykonawców jest niepoprawna” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można użyć Wzorca rozliczenia pracownika” | Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania i uruchom ponownie. Jeśli komunikat prosi o zmianę nazwy `placeholder.xlsx`, zrób to jak wyżej. W innym wypadku przekaż komunikat osobie utrzymującej narzędzie. |
| „W Pliku zbiorczym jest WYKONAWCA, którego nie ma w konfiguracji wykonawców” | Uruchom `Podgląd bez zapisu`, żeby zobaczyć problemy. Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy. Zapisz, zamknij i uruchom ponownie. |
| „Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ” | Uruchom `Podgląd bez zapisu`: problemy pokażą numery wierszy. Wpisz w nich WYKONAWCĘ w kolumnie H, zapisz, zamknij i uruchom ponownie. |
| „Nieznany identyfikator WYKONAWCA” | Problem z podglądu (wynik wymaga sprawdzenia). Popraw WYKONAWCĘ w kolumnie H albo poproś o dopisanie Wykonawcy do konfiguracji wykonawców. |
| „ma dane, ale nie ma wykonawcy w kolumnie H” | Problem z podglądu (wynik wymaga sprawdzenia). Wpisz WYKONAWCĘ we wskazanym wierszu albo wyczyść wiersz, jeśli jest zbędny. |
| „Nie udało się przygotować skoroszytu pracownika” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można opublikować gotowego Folderu rozliczeń pracowników” | Sprawdź, czy Folder okresu jest dostępny, i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można przygotować Folderu rozliczeń pracowników” | Sprawdź, czy Folder okresu jest dostępny, i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania” | Nie uruchamiaj ponownie: folder rozliczeń pracowników już jest. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się pokazać planu” | Nic nie zapisano. Przekaż komunikat osobie utrzymującej narzędzie. |

### Gdy pojawi się problem

- Jeśli plik jest otwarty, zamknij go i uruchom proces ponownie.
- Jeśli narzędzie napisze, że nie znalazło folderu tygodnia w żadnym folderze miesiąca, ten tydzień nie ma jeszcze folderu albo wpisano zły okres. Sprawdź okres. Rozliczenia pracowników powstają z Pliku zbiorczego, więc najpierw przygotuj plik zbiorczy w folderze tego tygodnia.
- Jeśli narzędzie napisze, że folder tygodnia jest w więcej niż jednym folderze miesiąca, zostaw go tylko w jednym miesiącu: drugi usuń albo zmień mu nazwę. Uruchom proces ponownie.
- Jeśli pojawi się komunikat „Nie znaleziono Wzorca rozliczenia pracownika” z prośbą o zmianę nazwy pliku `placeholder.xlsx`, zmień w folderze `config` narzędzia nazwę tego pliku na `Wzorzec rozliczenia pracownika.xlsx` i uruchom proces ponownie. Bez tej prośby przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się komunikat „Nie można odczytać Pliku zbiorczego”, sprawdź, czy ten plik otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom proces ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się informacja o braku szablonu, nie twórz pliku ręcznie z innego pracownika. Przekaż tę informację osobie utrzymującej narzędzie.
- Jeśli plik pracownika ma już dane, narzędzie go nie nadpisze.
- Jeśli pojawi się komunikat „Wystąpił nieoczekiwany błąd; folder rozliczeń pracowników nie został opublikowany”, nie powstał żaden plik pracownika. Uruchom proces ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się komunikat „Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania”, pliki pracowników już są w Folderze okresu, więc nie uruchamiaj procesu ponownie. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli w podglądzie bez zapisu (tryb `DRY-RUN`) pojawi się komunikat „Nie udało się pokazać planu. DRY-RUN: Nic nie zapisano”, nie powstał żaden plik. Przekaż komunikat osobie utrzymującej narzędzie.
