# Model Domeny

Ten plik opisuje język procesu. Nie opisuje implementacji.

## Okres rozliczeniowy

Tygodniowy przedział pracy od wtorku do poniedziałku. Jest identyfikowany przez
token zawierający dzień wtorku, dzień poniedziałku, miesiąc i rok, na przykład
`08_14_09_2026`. Miesiąc i rok są z wtorku: na przełomie miesięcy i lat liczy
się starszy miesiąc, więc okres od 27 października do 2 listopada 2026 ma token
`27_02_10_2026`, a od 29 grudnia 2026 do 4 stycznia 2027 token `29_04_12_2026`.
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

## Rozliczenie wewnętrzne

Skoroszyt `Rozliczenie wew. {okres}.xlsx` zawierający wszystkie zlecenia
jednego okresu rozliczeniowego z Rejestru zleceń, skuteczne i nieskuteczne, w
kolejności z Rejestru, bez pustych wierszy. Zachowuje formatowanie, do którego
tata jest przyzwyczajony.

## Wzorzec rozliczenia wewnętrznego

Wspólny skoroszyt bazowy, z którego powstaje Rozliczenie wewnętrzne nowego
okresu. Nie zawiera zleceń i pozostaje niezmieniony.

## Wzorzec pliku zbiorczego

Wspólny skoroszyt bazowy, z którego powstaje Plik zbiorczy nowego okresu.
Zachowuje stawki, sumy, formuły i formatowanie; nie zawiera zleceń i pozostaje
niezmieniony.

## Wzorzec rozliczenia pracownika

Wspólny skoroszyt bazowy bez nazwy wykonawcy, z którego powstają Szablony
pracowników. Ma ten sam układ kolumn co Plik zbiorczy, ale własne stawki
pracownika. U taty to pusty plik `Rozliczenie {okres} -.xlsx` w Folderze
rozliczeń pracowników. Nie jest rozliczeniem konkretnej osoby i pozostaje
niezmieniony.
_Avoid_: Placeholder

## Przygotowanie pliku zbiorczego

Proces poprzedzający Przebieg rozliczeń: z Rejestru zleceń tworzy Rozliczenie
wewnętrzne okresu, a z jego zleceń skutecznych Plik zbiorczy. Oba pliki
powstają razem albo żaden. Jedyny wyjątek: jeśli po nieudanym zapisie nie da
się usunąć pliku, który już trafił do Folderu okresu, zatrzymanie wskazuje ten
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
formatowanie; zawiera dane tylko z własnego okresu i może pozostać pusty, jeśli
wykonawca nie ma wierszy w Pliku zbiorczym.

## Folder okresu

Folder o nazwie równej tokenowi okresu, wspólny dla wszystkich plików jednego
okresu rozliczeniowego: Rozliczenia wewnętrznego, Pliku zbiorczego i Folderu
rozliczeń pracowników. Może istnieć wcześniej, zanim powstaną te pliki.
Folder, którego nazwa nie jest tokenem żadnego okresu (na przykład
`09_15_09_2026`, bo 9 września 2026 to nie wtorek), nie jest Folderem okresu.

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
pracowników. Może zakończyć się uzupełnieniem danych, pozostawieniem pustego
szablonu albo pominięciem, gdy dalsze działanie nie jest bezpieczne.

## Rozliczenie pracownika

Szablon pracownika uzupełniony wierszami tego wykonawcy z danego okresu.
Plik jest identyfikowany nazwą `Rozliczenie {okres} - {nazwa wykonawcy}.xlsx`;
`{okres}` to token okresu rozliczeniowego.

## Wiersz danych

Wiersz od 18. w dół zawierający dane wejściowe pracy. Formuły i techniczne
wartości szablonu nie są same w sobie wierszami danych.

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
launchera albo z Centrum rozliczeń, od ustalenia plików i okresu do wyniku
końcowego. Decyzja taty należy do Uruchomienia procesu bez względu na to,
skąd wystartowało; nie jest z definicji pytaniem w terminalu.
Kończy się sukcesem, wynikiem wymagającym sprawdzenia albo zatrzymaniem z
bezpiecznym komunikatem zrozumiałym dla taty, nigdy z treścią błędu
technicznego.
_Avoid_: Przebieg (zarezerwowany dla Przebiegu rozliczeń)

## Decyzja taty

Pytanie, które proces zadaje tacie w trakcie Uruchomienia procesu; dziś tylko
o niepełny okres w Przygotowaniu pliku zbiorczego. Składa ją proces i sam
zatrzymuje się po odmowie; rozmówca tylko pyta i mówi, jak wyrazić zgodę
(`t` w terminalu, `Kontynuuj` w Centrum rozliczeń). Czas czekania na Decyzję
taty nie wlicza się do `Czas uruchomienia` ani do metryk.

## Centrum rozliczeń

Lokalna aplikacja w przeglądarce na komputerze taty, z której uruchamia
Przygotowanie pliku zbiorczego i Przebieg rozliczeń oraz widzi Status okresu
każdego okresu i historię Uruchomień procesu. Jest drugim wejściem do tych
samych procesów obok launcherów, nie osobnym procesem.
_Avoid_: dashboard, panel, centrum dowodzenia

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
Wykonawcę. Wyjątkiem jest wyłącznie terminalowa dawna jedna linia zatrzymania
Przebiegu rozliczeń (ADR 0004): może mieć pełną ścieżkę i nie trafia do
Centrum rozliczeń. Komunikat niesie zatrzymanie, ostrzeżenie, problem z
podsumowania albo problem startu Centrum rozliczeń. Jego kod jest unikalny w
obrębie procesu.
_Avoid_: błąd, wiadomość

## Nienadpisywanie

Jeśli folder lub pliki docelowe nowego okresu już istnieją, proces zatrzymuje
się bez ich nadpisywania. Wzorce i Rejestr zleceń również pozostają
niezmienione.
