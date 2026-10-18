# ADR 0004: Centrum rozliczeń jako adapter Uruchomienia procesu

## Status

Zaakceptowana. Zastępuje część [ADR 0003](0003-cli-only-launcher.md), według
której procesy są uruchamiane wyłącznie przez CLI i launchery `.cmd`.
Rezygnacja z adaptera VBA z ADR 0003 pozostaje w mocy.

## Decyzja

Przebieg rozliczeń i Przygotowanie pliku zbiorczego mają dwa wejścia do tych
samych procesów: CLI z launcherami `.cmd` jako ścieżkę zapasową oraz Centrum
rozliczeń, lokalną aplikację w przeglądarce. Oba wejścia są rozmówcami tego
samego rdzenia Uruchomienia procesu: ten sam pomiar czasu, te same metryki, te
same linie komunikatów i ta sama projekcja postępu z ADR 0002, dla której
Centrum jest trzecim adapterem obok plain i Rich. Reguły procesów pozostają
wyłącznie w silniku Python (ADR 0001). Przeglądarka niczego nie wylicza ani nie
interpretuje Zdarzeń przebiegu.

Centrum działa jako lokalny serwer w tle na komputerze taty, w tym samym
procesie co silnik, bez okna konsoli. Nasłuchuje wyłącznie na `127.0.0.1`.
Odrzuca każde żądanie z nagłówkiem `Host` spoza localhost, a akcje zmieniające
stan przyjmuje tylko z `Origin` Centrum. Nie ma logowania, zdalnego dostępu ani
własnej bazy danych: stan wylicza przy każdym odczycie z folderu okresów,
plików metryk i konfiguracji. Pliki i foldery otwiera tylko wtedy, gdy sam
wyliczył je z folderu okresów, nigdy dla ścieżki podanej w żądaniu.

Reguła prywatności: do Centrum trafia tylko to, co przechodzi przez seam
obserwacji z ADR 0002 (snapshoty projekcji i neutralne powiadomienia), oraz
bezpieczne linie komunikatów wspólne z terminalem. Adresy klientów, numery
zleceń, treści Wierszy danych i tekst wyjątków nie trafiają do przeglądarki,
dziennika Centrum ani metryk.

Launchery `.cmd` i CLI zostają bez zmian. Ich porzucenie to osobna, przyszła
decyzja z własnym ADR, podejmowana dopiero wtedy, gdy Centrum przejmie całą
pracę taty.

## Uzasadnienie

Terminal nie jest miejscem pracy taty: każde Uruchomienie procesu to okno
konsoli, ponowne wskazywanie tych samych plików, pytanie `t`/`n` wpisywane z
klawiatury i szukanie komunikatu w instrukcji. Stanu okresów i historii
Uruchomień procesu nie widać nigdzie.

ADR 0003 odrzucił drugie wejście, bo adapter VBA wymagał ręcznej bramy
walidacji w Excelu, zależał od polityki makr i dokładał ukryte przełączniki do
CLI. Centrum nie powtarza tych kosztów: działa w tym samym procesie co silnik i
przez ten sam rdzeń Uruchomienia procesu, więc nie powstaje druga kopia reguł,
drugi pomiar ani drugi zestaw komunikatów. Cel z ADR 0003, jeden proces taty
działający w tle, jest bliżej z Centrum niż z terminala.

Serwer HTTP na localhost jest osiągalny z każdej strony otwartej w przeglądarce
taty, a dane klientów są poufne. Stąd nasłuch tylko na `127.0.0.1`, kontrola
`Host` przeciw DNS rebinding, kontrola `Origin` przed akcjami zapisu i otwieranie
wyłącznie plików wyliczonych przez serwer.

Launchery `.cmd` zostają, bo działają dziś i mają testy. Do czasu, aż Centrum
przejmie całą pracę, są ścieżką zapasową, gdy Centrum nie wystartuje.

## Konsekwencje

- Zmiana reguł procesu odbywa się w silniku i działa w obu wejściach. Centrum
  nie dostaje własnych reguł.
- Moduł Uruchomienia procesu wydziela rdzeń, z którym rozmawiają terminal i
  Centrum. Decyzja taty o niepełnym okresie jest częścią tej rozmowy: w Centrum
  to stan czekający na odpowiedź taty, nie pytanie w terminalu. Czas czekania
  nie wlicza się do czasu Uruchomienia procesu ani do metryk.
- Wejście CLI zachowuje dzisiejsze zachowanie, a jego testy pilnują regresji
  wydzielenia rdzenia.
- Uruchomienia z obu wejść trafiają do tych samych plików metryk, bez zmiany
  schematu.
- Serwer prowadzi jedno Uruchomienie procesu naraz. Między CLI a Centrum nie ma
  blokady: przed zderzeniem chronią Nienadpisywanie i atomowa publikacja plików
  okresu.
- Awaria adaptera Centrum odłącza go bez wpływu na wynik, zapis i metryki, tak
  jak awaria adaptera terminala (ADR 0002).
- Zmiany w Centrum weryfikuje end-to-end skill `verify-centrum-rozliczen`.
- Edycja danych w Centrum wymaga osobnego ADR i rewizji reguły prywatności.
