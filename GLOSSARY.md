# Model Domeny

Ten plik opisuje język procesu. Nie opisuje implementacji.

## Okres rozliczeniowy

Tygodniowy przedział pracy od wtorku do poniedziałku. Jest identyfikowany przez
token zawierający dzień wtorku, dzień poniedziałku, miesiąc i rok, na przykład
`08_14_09_2026`. Miesiąc i rok są z poniedziałku, tak jak w folderach taty: na
przełomie miesięcy i lat liczy się nowszy miesiąc, więc okres od 27 października
do 2 listopada 2026 ma token
`27_02_11_2026`, a od 29 grudnia 2026 do 4 stycznia 2027 token `29_04_01_2027`.
Każdy okres ma jeden token.

## Rejestr zleceń

Skoroszyt `ZLECENIA INTERMAX OD 08_11_2021.xlsx`, do którego tata eksportuje
zlecenia z aplikacji firmowej. Jest jedynym źródłem prawdy o zleceniach
wszystkich okresów. Po eksporcie zawiera między zleceniami całkowicie puste
wiersze. Procesy go czytają, ale nigdy nie zmieniają.

## Zlecenie skuteczne

Zlecenie, którego wartość `SKUTECZNE` to `tak`, bez względu na wielkość liter i
otaczające spacje. Każde zlecenie skuteczne z Rozliczenia wewnętrznego trafia
do Pliku zbiorczego.

## Zlecenie nieskuteczne

Zlecenie, którego wartość `SKUTECZNE` to `nie`, bez względu na wielkość liter i
otaczające spacje. Każde zlecenie okresu jest skuteczne albo nieskuteczne.
Puste `SKUTECZNE` albo inna wartość, na przykład `???` czy `tsk`, to brak w
Rejestrze, który tata uzupełnia, a nie trzeci stan zlecenia.

## Rozliczenie wewnętrzne

Skoroszyt `Rozliczenie wew. {okres}.xlsx` zawierający wszystkie zlecenia
jednego okresu rozliczeniowego z Rejestru zleceń, skuteczne i nieskuteczne, w
kolejności z Rejestru, bez pustych wierszy. Zachowuje formatowanie, do którego
tata jest przyzwyczajony.

## Wzorzec rozliczenia wewnętrznego

Wspólny skoroszyt bazowy, z którego powstaje Rozliczenie wewnętrzne nowego
okresu. Jest jedynym źródłem szerokości kolumn Rozliczenia wewnętrznego, nie
poprzedni okres. Nie zawiera zleceń i pozostaje niezmieniony.

## Wzorzec pliku zbiorczego

Wspólny skoroszyt bazowy, z którego powstaje Plik zbiorczy nowego okresu.
Zachowuje stawki, sumy, formuły i formatowanie. Jest jedynym źródłem szerokości
kolumn Pliku zbiorczego, nie poprzedni okres. Nie zawiera zleceń i pozostaje
niezmieniony.

## Wzorzec rozliczenia pracownika

Wspólny skoroszyt bazowy bez nazwy wykonawcy, z którego powstają Szablony
pracowników. Ma ten sam układ kolumn co Plik zbiorczy, ale własne stawki
pracownika. Jest jedynym źródłem szerokości kolumn Rozliczeń pracowników, nie
poprzedni okres; ma te same szerokości co Wzorzec pliku zbiorczego. U taty to
pusty plik `Rozliczenie {okres} -.xlsx` w Folderze rozliczeń pracowników. Nie
jest rozliczeniem konkretnej osoby i pozostaje niezmieniony.
_Avoid_: Placeholder

## Przygotowanie pliku zbiorczego

Proces poprzedzający Przebieg rozliczeń: z Rejestru zleceń tworzy Rozliczenie
wewnętrzne okresu, a z jego zleceń skutecznych Plik zbiorczy. Oba pliki
powstają razem albo żaden. Jedyny wyjątek: jeśli po nieudanym zapisie nie da
się usunąć pliku, który już trafił do Folderu okresu, Zatrzymanie wskazuje ten
plik. Uruchamiany osobno od Przebiegu rozliczeń.

## Plik zbiorczy

Skoroszyt `Rozliczenie {okres} - zbiorcze.xlsx`: zlecenia skuteczne wszystkich
wykonawców dla jednego okresu rozliczeniowego. Jest wynikiem Przygotowania
pliku zbiorczego i jedynym wejściem Przebiegu rozliczeń.

## Wykonawca

Osoba wskazana w kolumnie `WYKONAWCA` pliku zbiorczego. Wartość w tej kolumnie
jest identyfikatorem źródłowym, który nie musi być identyczny z nazwą człowieka
w nazwie pliku docelowego.

## Konfiguracja wykonawców

Plik konfiguracji w folderze `config`, który łączy identyfikator Wykonawcy z
kolumny `WYKONAWCA` (H) z nazwą Wykonawcy w Rozliczeniu pracownika. Wspólny
dla Przebiegu rozliczeń i Przygotowania pliku zbiorczego.

## Szablon pracownika

Skoroszyt przygotowany dla konkretnego wykonawcy na podstawie Wzorca
rozliczenia pracownika. Zachowuje jego strukturę, formuły, stawki i
formatowanie; jedynie Wiersze danych mają Wyróżnienia z Pliku zbiorczego.
Zawiera dane tylko z własnego okresu i może pozostać pusty, jeśli wykonawca nie
ma wierszy w Pliku zbiorczym.

## Folder okresu

Folder o nazwie równej tokenowi okresu, wspólny dla wszystkich plików jednego
okresu rozliczeniowego: Rozliczenia wewnętrznego, Pliku zbiorczego i Folderu
rozliczeń pracowników. Może istnieć wcześniej, zanim powstaną te pliki.
Folder, którego nazwa nie jest tokenem żadnego okresu (na przykład
`09_15_09_2026`, bo 9 września 2026 to nie wtorek), nie jest Folderem okresu.

## Folder okresów

Folder, w którym narzędzie szuka Folderów okresu. W układzie folderów taty to
`Załączniki`, a Foldery okresu leżą w `Rozliczenia {rok}\{miesiąc}\INEA`.
Miesiąc to cykl rozliczeniowy taty, nie kalendarz, więc Folder okresu zakłada
tata, a narzędzie go odszukuje. Folder wskazany wewnątrz `Rozliczenia {rok}`
(np. `INEA` jednego miesiąca) to ten sam układ liczony od `Załączniki`. Bez
folderów `Rozliczenia {rok}` Foldery okresu leżą w folderze okresów
bezpośrednio (np. `INEA`).

## Ustawienia taty

Rejestr zleceń i folder okresów wskazane raz w Centrum rozliczeń. Czyta je
tylko Centrum rozliczeń.

## Folder rozliczeń pracowników

Folder danego okresu zawierający osobny skoroszyt dla każdego wykonawcy.

## Przygotowanie skoroszytów pracowników

Etap tworzenia plików nowego okresu przez skopiowanie Wzorca rozliczenia
pracownika dla każdego wykonawcy. Token okresu i nazwa wykonawcy trafiają do
nazw folderu i plików; struktura, formuły, stawki i formatowanie Wzorca
rozliczenia pracownika pozostają zachowane, a sam Wzorzec pozostaje
niezmieniony.

## Przetworzenie Szablonu pracownika

Obsłużenie jednego Szablonu pracownika w ramach przygotowania Rozliczeń
pracowników. Kończy się uzupełnieniem danych albo pozostawieniem pustego
szablonu. Gdy zapis nie jest bezpieczny, Przebieg rozliczeń się zatrzymuje i
nie publikuje żadnego Rozliczenia pracownika.

## Rozliczenie pracownika

Szablon pracownika uzupełniony wierszami tego wykonawcy z danego okresu.
Plik jest identyfikowany nazwą `Rozliczenie {okres} - {nazwa wykonawcy}.xlsx`;
`{okres}` to token okresu rozliczeniowego.

## Wiersz danych

Wiersz od 18. w dół zawierający dane wejściowe pracy. Formuły i techniczne
wartości szablonu nie są same w sobie wierszami danych.

## Wyróżnienie

Wygląd komórki, którym tata zaznacza zlecenie: kolor wypełnienia, kolor
czcionki, pogrubienie i kursywa. Przechodzi razem z wartością z Rejestru zleceń
do plików okresu, a z Pliku zbiorczego do Rozliczeń pracowników. Wyróżnienia
zastępują wygląd komórki wzorca w całości: komórka bez Wyróżnień daje komórkę
bez wypełnienia, z kolorem automatycznym, bez pogrubienia i bez kursywy. Krój i
rozmiar czcionki nie są Wyróżnieniem i zawsze pochodzą z wzorca.
_Avoid_: formatowanie (szersze: obejmuje też krój, obramowania i formaty liczb)

## Gotowość

Świadoma decyzja taty, że plik zbiorczy jest zakończony i można przygotować
rozliczenia pracowników. W pierwszej wersji gotowość jest potwierdzana przez
uruchomienie procesu, a nie zgadywana na podstawie samego zapisu pliku.

## Status okresu

Etap okresu rozliczeniowego wynikający z plików w jego Folderze okresu: Brak
plików okresu, gdy nie ma Pliku zbiorczego; Plik zbiorczy przygotowany, gdy
jest Plik zbiorczy, ale nie ma Folderu rozliczeń pracowników; Rozliczenia
pracowników gotowe, gdy jest Folder rozliczeń pracowników. Nie zastępuje
Gotowości: Plik zbiorczy przygotowany nie znaczy, że tata go zakończył.

## Przebieg rozliczeń

Jedno uruchomienie procesu od wskazania Pliku zbiorczego do wyniku końcowego
albo bezpiecznego przerwania. Obejmuje Przygotowanie skoroszytów pracowników,
a następnie ich uzupełnienie danymi z Pliku zbiorczego.

## Uruchomienie procesu

Jedno uruchomienie Przebiegu rozliczeń albo Przygotowania pliku zbiorczego z
Centrum rozliczeń albo ze Skryptu dla maszyn, od gotowych plików i okresu do
wyniku końcowego. Decyzja taty należy do Uruchomienia procesu bez względu na
to, skąd wystartowało.
Kończy się sukcesem, wynikiem wymagającym sprawdzenia albo Zatrzymaniem z
bezpiecznym Komunikatem zrozumiałym dla taty, nigdy z treścią błędu
technicznego.
_Avoid_: Przebieg (zarezerwowany dla Przebiegu rozliczeń)

## Decyzja taty

Pytanie, które proces zadaje tacie w trakcie Uruchomienia procesu; dziś tylko
o niepełny okres w Przygotowaniu pliku zbiorczego. Składa ją proces i sam
zatrzymuje się po odmowie; rozmówca tylko pyta i mówi, jak wyrazić zgodę
(`Kontynuuj` w Centrum rozliczeń). Skrypt dla maszyn zawsze odmawia. Czas czekania na Decyzję
taty nie wlicza się do `Czas uruchomienia` ani do metryk.

## Centrum rozliczeń

Lokalna aplikacja w przeglądarce na komputerze taty, z której uruchamia
Przygotowanie pliku zbiorczego i Przebieg rozliczeń oraz widzi Status okresu
każdego okresu i historię Uruchomień procesu. Jest jedynym wejściem taty do
tych procesów, nie osobnym procesem.
_Avoid_: dashboard, panel, centrum dowodzenia

## Skrypt dla maszyn

Jedyne wejście do procesów spoza Centrum rozliczeń, dla testów, pomiarów czasu
i osoby utrzymującej narzędzie. Przyjmuje pliki i okres parametrami, z nikim
nie rozmawia i oddaje wynik w kształcie karty Uruchomienia. Jego Uruchomienia
procesu mają w historii Centrum odznakę `.cmd`, tę samą co stare Uruchomienia
z dawnych launcherów.
_Avoid_: CLI, launcher

## Zdarzenie przebiegu

Bezpieczny fakt opisujący zmianę lub wynik jednego uruchomienia Przebiegu
rozliczeń albo Przygotowania pliku zbiorczego, na przykład rozpoczęcie etapu,
zakończenie etapu albo przerwanie etapu. Oba procesy przechodzą te same etapy:
Sprawdzanie, Odczyt danych, Planowanie i Zapisywanie. Tylko Przebieg rozliczeń
zgłasza też rozpoczęcie i zakończenie przetwarzania Szablonu pracownika.
Zdarzenie nie zawiera adresów klientów, numerów zleceń ani treści wierszy.

## Komunikat

Bezpieczny tekst dla taty w trzech częściach: Co się stało, Gdzie, Co zrobić.
Trzy części nie zawierają pełnych ścieżek, treści wyjątków, adresów ani treści
wierszy; wskazują tylko nazwę pliku, folder, arkusz, kolumnę, wiersz albo
Wykonawcę. Jedynym wyjątkiem jest Zatrzymanie o brakach w `SKUTECZNE`:
pokazuje dokładną zawartość komórki innej niż `tak` i `nie`, żeby tata od razu
widział, co poprawić. Komunikat niesie Zatrzymanie, ostrzeżenie, problem z
podsumowania albo problem startu Centrum rozliczeń. Jego kod jest unikalny w
obrębie procesu.
_Avoid_: błąd, wiadomość

## Zatrzymanie

Zakończenie Uruchomienia procesu bez wyniku, z jednym Komunikatem: własne
zatrzymanie procesu (np. Nienadpisywanie) albo nieoczekiwany wyjątek, także po
zakończeniu zapisu.
_Avoid_: przerwanie, awaria, błąd

## Nieoczekiwany wyjątek

Zatrzymanie, którego przyczyną jest wyjątek w kodzie narzędzia, a nie reguła
procesu. Tata dostaje ogólny Komunikat; typ wyjątku i ślad wywołań trafiają
tylko do Zgłoszenia.
_Avoid_: nieoczekiwany błąd, crash

## Rodzaj Zatrzymania

Kto usuwa przyczynę Zatrzymania: „dla taty”, gdy Komunikat mówi, co zrobić,
albo „do Maksa”, gdy bezwarunkowo każe przekazać go osobie utrzymującej
narzędzie. Nieoczekiwany wyjątek jest zawsze „do Maksa”. Powtórka zmienia
Zatrzymanie „dla taty” w takie, przy którym Centrum proponuje Diagnozę.

## Powtórka

Następne Uruchomienie procesu tego samego procesu, które kończy się
Zatrzymaniem o tym samym odcisku problemu co poprzednie. Centrum pamięta
poprzednie Zatrzymanie tylko do swojego zamknięcia.

## Odcisk problemu

Tożsamość problemu: proces, kod Komunikatu i jego trzy części. Proces należy
do odcisku, bo kody Komunikatów są unikalne tylko w obrębie procesu.

## Diagnoza

Sprawdzenie tylko do odczytu, które tata uruchamia w Centrum rozliczeń przy
Zatrzymaniu „do Maksa” albo Powtórce; przy nieoczekiwanym wyjątku zaczyna się
sama. Ustala przyczynę na komputerze taty i wyjaśnia ją w trzech częściach, jak
Komunikat. Niczego nie zmienia ani nie naprawia.

## Zgłoszenie

Komunikat Zatrzymania razem z wynikiem Diagnozy, wysłany z Centrum rozliczeń
do Maksa. Jeden odcisk problemu ma najwyżej jedno otwarte Zgłoszenie; gdy Maks
je zamknie, a problem wraca, powstaje nowe z odnośnikiem do poprzedniego.

## Skrzynka Zgłoszeń

Miejsce, do którego trafiają Zgłoszenia i w którym Maks je zamyka: prywatne
repozytorium Zgłoszeń. Centrum pyta ją o otwarte Zgłoszenie odcisku problemu i
o stan wysłanych Zgłoszeń.
_Avoid_: issue tracker, publiczne issue

## Powiadomienie o naprawie

Zdanie na stronie Okresy, że Maks zamknął Zgłoszenie wysłane z wersji
narzędzia, która nadal działa u taty, więc trzeba zaktualizować narzędzie.
Znika samo po aktualizacji i ponownym otwarciu Centrum.

## Aktualizacja narzędzia

Przejście narzędzia na komputerze taty na jego najnowszą wersję, które
tata zleca jednym przyciskiem w Centrum rozliczeń. Udaje się w całości albo
zostawia poprzednią wersję; pliki taty pozostają nietknięte.
_Avoid_: upgrade, git pull, instalacja

## Nienadpisywanie

Jeśli folder lub pliki docelowe nowego okresu już istnieją, proces zatrzymuje
się bez ich nadpisywania. Wzorce i Rejestr zleceń również pozostają
niezmienione.
