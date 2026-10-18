# Instrukcja dla taty

Co tydzień są dwa kroki, zawsze w tej kolejności:

1. **Przygotowanie pliku zbiorczego**: z Rejestru zleceń powstają Rozliczenie
   wewnętrzne i Plik zbiorczy okresu (`Przygotuj plik zbiorczy.cmd`).
2. **Przebieg rozliczeń**: z Pliku zbiorczego powstają rozliczenia
   pracowników (`Utwórz rozliczenia.cmd`).

## Pierwsza instalacja

1. Zainstaluj Python 3.11 lub nowszy.
2. W folderze narzędzia uruchom:

   ```powershell
   py -3 -m pip install -r requirements.txt
   ```

Lista zależności zawiera `rich`, potrzebny do kolorowego dashboardu. Bez
kolorów lub bez interaktywnego terminala narzędzie przełącza się na zwykły tekst.

Osoba utrzymująca narzędzie umieszcza w folderze `config` narzędzia trzy
wzorce: `Wzorzec rozliczenia wewnętrznego.xlsx`, `Wzorzec pliku zbiorczego.xlsx`
i `Wzorzec rozliczenia pracownika.xlsx`. Ten ostatni to pusty plik rozliczenia
pracownika bez nazwy wykonawcy (u Ciebie `Rozliczenie {okres} -.xlsx`); z niego
powstają pliki pracowników.
Nie zmieniaj ich i nie podmieniaj plikami z poprzedniego tygodnia.

## Przygotowanie pliku zbiorczego

### Kiedy uruchomić

- Eksport zleceń całego okresu (od wtorku do poniedziałku) jest już w Rejestrze
  zleceń `ZLECENIA INTERMAX OD 08_11_2021.xlsx`.
- Rejestr zleceń jest zapisany i **zamknięty** w Excelu.
- W Folderze okresu nie ma jeszcze plików `Rozliczenie wew. {okres}.xlsx` ani
  `Rozliczenie {okres} - zbiorcze.xlsx`. Pusty Folder okresu założony wcześniej
  nie przeszkadza.

Narzędzie tylko czyta Rejestr zleceń i wzorce. Nigdy ich nie zmienia.

### Kroki

1. Dwukrotnie kliknij `Przygotuj plik zbiorczy.cmd`.
2. W pierwszym oknie wybierz plik Rejestru zleceń
   `ZLECENIA INTERMAX OD 08_11_2021.xlsx`.
3. W drugim oknie wybierz folder okresów, w którym są foldery poprzednich
   tygodni, np. `INEA`.
4. Narzędzie pokaże `Proponowany okres:`, czyli ostatni pełny tydzień od wtorku
   do poniedziałku przed dzisiejszą datą.
   - Naciśnij Enter, żeby go potwierdzić.
   - Żeby przygotować inny tydzień, wpisz okres tak jak nazwę folderu, np.
     `08_14_09_2026` (wtorek 8, poniedziałek 14 września 2026) i naciśnij Enter.
     Na przełomie miesięcy miesiąc i rok są z wtorku, np. `27_02_10_2026`
     dla 27 października – 2 listopada 2026 albo `29_04_12_2026` dla
     29 grudnia 2026 – 4 stycznia 2027.
   - Po złym zapisie narzędzie wyjaśni, co poprawić, i zapyta ponownie.
5. Jeśli po etapie `Planowanie` pojawi się `Ostrzeżenie: niepełny okres`,
   sprawdź liczby `Zlecenia na dzień`. Wpisz `t`, żeby kontynuować, albo `n`,
   żeby przerwać bez tworzenia plików.
6. Poczekaj na `Status końcowy`. Potem naciśnij dowolny klawisz, żeby zamknąć
   okno. Nie zamykaj okna wcześniej: w trakcie zapisu może zostać samo
   Rozliczenie wewnętrzne.

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
4. Uruchom Przebieg rozliczeń (`Utwórz rozliczenia.cmd`).

### Komunikat → co zrobić

Każdy komunikat ma trzy linie: `Co się stało`, `Gdzie` i `Co zrobić`. Znajdź w
tabeli wiersz z fragmentem pierwszej linii. `Gdzie` wskazuje plik, arkusz albo
numery wierszy Rejestru zleceń. Po każdym zatrzymaniu nie powstał żaden plik,
więc po poprawce wystarczy uruchomić proces ponownie. Wyjątkiem jest komunikat
o niepokazanym podsumowaniu: wtedy pliki okresu już są.

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
| „Nie znaleziono folderu okresów” | Uruchom ponownie i wybierz istniejący folder okresów, np. `INEA`. |
| „Okres nie ma postaci dd_dd_mm_rrrr od wtorku do poniedziałku” | Wpisz okres jak nazwę folderu: dzień wtorku, dzień poniedziałku, miesiąc i rok, np. `08_14_09_2026`. Na przełomie miesięcy miesiąc i rok są z wtorku, np. `27_02_10_2026` (27 października – 2 listopada 2026). |
| „Nie wybrano pliku Rejestru zleceń” | Uruchom ponownie i w pierwszym oknie wybierz plik Rejestru zleceń. |
| „Nie wybrano folderu okresów” | Uruchom ponownie i w drugim oknie wybierz folder okresów, np. `INEA`. |
| „Nie potwierdzono okresu ani nie wpisano innego” | Uruchom ponownie. Przy pytaniu `Okres:` naciśnij Enter albo wpisz okres. |
| „Przerwano z powodu niepełnego okresu” | Uzupełnij eksport zleceń w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli okres jest pełny, przy pytaniu wpisz `t`. |
| „Nie znaleziono wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. Nie twórz wzorca z pliku poprzedniego tygodnia. |
| „Wzorzec jest otwarty w Excelu” | Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu `config` pozostawiony plik `~$` wskazany w komunikacie. |
| „Nie można odczytać wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu brakuje nagłówka” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie” | Przebieg rozliczeń czyta wykonawcę tylko z kolumny H. Otwórz `config\Wzorzec pliku zbiorczego.xlsx` i w wierszu 17 przenieś WYKONAWCA do kolumny H, a nagłówek z kolumny H do kolumny wskazanej w komunikacie. Zapisz i zamknij wzorzec, uruchom ponownie. Jeśli nie wiesz, jak to zrobić, przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu są scalone komórki” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać konfiguracji wykonawców” | Przekaż komunikat osobie utrzymującej narzędzie. Ta sama konfiguracja jest potrzebna w Przebiegu rozliczeń. |
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
2. Wybierz plik zakończony słowami `- zbiorcze.xlsx`.
3. Poczekaj na komunikat końcowy.
4. Otwórz pliki pracowników i sprawdź ich zawartość.

### Gdy pojawi się problem

- Jeśli plik jest otwarty, zamknij go i uruchom proces ponownie.
- Jeśli pojawi się komunikat „Nie znaleziono Wzorca rozliczenia pracownika” z prośbą o zmianę nazwy pliku `placeholder.xlsx`, zmień w folderze `config` narzędzia nazwę tego pliku na `Wzorzec rozliczenia pracownika.xlsx` i uruchom proces ponownie. Bez tej prośby przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się komunikat „Nie można odczytać Pliku zbiorczego”, sprawdź, czy ten plik otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom proces ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się informacja o braku szablonu, nie twórz pliku ręcznie z innego pracownika. Przekaż tę informację osobie utrzymującej narzędzie.
- Jeśli plik pracownika ma już dane, narzędzie go nie nadpisze.
- Jeśli pojawi się komunikat „Wystąpił nieoczekiwany błąd; folder rozliczeń pracowników nie został opublikowany”, nie powstał żaden plik pracownika. Uruchom proces ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się komunikat „Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania”, pliki pracowników już są w Folderze okresu, więc nie uruchamiaj procesu ponownie. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli w podglądzie bez zapisu (tryb `DRY-RUN`) pojawi się komunikat „Nie udało się pokazać planu. DRY-RUN: Nic nie zapisano”, nie powstał żaden plik. Przekaż komunikat osobie utrzymującej narzędzie.
