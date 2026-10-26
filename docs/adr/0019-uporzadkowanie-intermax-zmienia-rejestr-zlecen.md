# ADR 0019: Uporządkowanie INTERMAX zmienia Rejestr zleceń

## Status

Zaakceptowana (2026-10-25, grilling z Maksem i tatą, spec #462). Zmienia
zasadę ze słownika, że procesy Rejestr zleceń tylko czytają. Dopełnia
[ADR 0004](0004-centrum-rozliczen-adapter.md) (Kopie INTERMAX to nowe własne
pliki narzędzia), [ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md)
i [ADR 0017](0017-karta-uruchomienia-z-logow.md) (okres Uruchomienia, które nie
porządkuje okresu).

## Kontekst

Tata albo jego pracownik kopiuje co dzień zlecenia następnego dnia z aplikacji
firmowej, do której narzędzie nie ma dostępu, i wkleja je na dół INTERMAX
(Rejestru zleceń). Wklejone Surowe zlecenia mają wygląd z aplikacji (Roboto 4,
białe i szare tła), pierwszy wiersz przesunięty o dwie kolumny w lewo i
zlecenia Wykonawcy nieułożone po godzinie. Tata porządkuje je dziś ręcznie,
zanim pracownicy dopiszą resztę. Rejestr to jedyne źródło prawdy o zleceniach
od 2021 roku: około 42 tys. wierszy, cztery arkusze, około 6,5 MB, w OneDrive.

## Decyzja

- **Uporządkowanie INTERMAX to trzeci proces** z tym samym kontraktem co
  Przygotowanie pliku zbiorczego i Przebieg rozliczeń (etapy, Komunikaty,
  Zatrzymania, Logi Uruchomienia, Skrypt dla maszyn). Porządkuje dzień, nie
  okres, więc w Centrum rozliczeń ma własną kartę poza okresami.
- **Zmienia tylko Surowe zlecenia i widok po otwarciu.** Surowe zlecenia to
  blok na dole arkusza zleceń z wyglądem z aplikacji. Zapis podmienia w XML
  arkusza zleceń wiersze od początku tego bloku w dół, dopisuje do arkusza
  stylów nowe style, ustawia widok arkusza na dzisiejszy dzień z kalendarza i
  robi arkusz zleceń aktywnym i jedynym zaznaczonym (aktywna karta w
  `xl/workbook.xml` i znacznik zaznaczenia karty w pozostałych arkuszach), tak
  jak zapis Rozliczenia pracownika w
  [ADR 0008](0008-zapis-rozliczenia-pracownika-przez-podmiane-wierszy-danych.md).
  Każda inna część pliku i każdy wiersz nad blokiem, także kolumny za `UWAGI`,
  zostają bajt w bajt. Nie wczytuje i nie zapisuje całego skoroszytu w
  openpyxl. Dzień widoku to najpóźniejszy dzień ze zleceniami nie późniejszy
  niż dziś, szukany od dołu arkusza tą samą granicą 10 wierszy wcześniejszego
  dnia co przegląd nad wklejeniem, a bez takiego dnia uporządkowany dzień.
- **Zapis dotyka w arkuszu zleceń jeszcze dwóch miejsc** (sprawdzone na kopii
  INTERMAX taty z doklejonym wklejeniem z aplikacji, #467): `<dimension ref>`
  rośnie, gdy dzień sięga dalej niż ostatni wiersz albo przesunięty pierwszy
  wiersz dalej niż ostatnia kolumna, a `ref` Hiperłączy `NUMER ZL.` Surowych
  zleceń idzie razem z ich komórką; relacje arkusza zostają. Zmieniane wiersze
  to wszystkie pod żółtym wierszem albo pod ostatnim uporządkowanym zleceniem,
  także puste między nimi a wklejeniem: pusty wiersz, który zostaje pusty, ma
  te same bajty, a wiersz, z którego zlecenie odeszło, jest pustym wierszem
  taty. Wiersze nowego dnia biorą wygląd `<row>` (styl wiersza, wysokość) z
  ostatniego uporządkowanego dnia: wiersz zlecenia i pusty wiersz między
  segmentami z ostatniego uporządkowanego wiersza, a inny pusty wiersz z
  pierwszego pustego, nieżółtego wiersza pod nim. Żółty wiersz to u taty styl
  całego wiersza bez komórek, więc rozpoznanie patrzy na styl wiersza i komórek. Autofiltr,
  formatowanie warunkowe, sprawdzanie poprawności i scalenia nie zmieniają się:
  gdy któreś sięga tych wierszy, Uporządkowanie zatrzymuje się „do Maksa”, tak
  samo przy formule albo Hiperłączu na kilka komórek w Surowych zleceniach. Na
  kopii INTERMAX taty nie ma ich pod uporządkowanymi dniami. „Bajt w bajt”
  znaczy tę samą treść części po rozpakowaniu: zip jest zapisany od nowa, bo
  arkusz zleceń i tak trzeba skompresować w całości (~0,4 s dla 43 MB XML).
- **Przed podmianą narzędzie sprawdza swój zapis.** Plik tymczasowy obok
  INTERMAX zostaje odczytany jeszcze raz i porównany z oryginałem: poza
  zmianami z poprzedniego punktu wszystko musi się zgadzać, a zlecenia bloku
  mają te same wartości co Surowe zlecenia po przesunięciu. Inaczej
  Zatrzymanie „do Maksa”, a INTERMAX zostaje nietknięty.
- **Przed każdą podmianą powstaje Kopia INTERMAX** w folderze narzędzia na
  `C:`, poza OneDrive, żeby nie synchronizować 6,5 MB codziennie: `INTERMAX
  przed uporządkowaniem RRRR-MM-DD GG-MM-SS.xlsx`. Zostaje 10 ostatnich Kopii.
  Centrum przywraca wybraną Kopię z Konfiguracji, a przedtem robi Kopię stanu
  bieżącego `INTERMAX przed przywróceniem RRRR-MM-DD GG-MM-SS.xlsx`.
  Przywracanie to osobne zadanie, gotowe przed pierwszym Uporządkowaniem u
  taty.
- **INTERMAX musi być zapisany i zamknięty.** Otwarty plik albo plik, który
  OneDrive dalej trzyma po krótkiej ponownej próbie, daje Zatrzymanie „dla
  taty”. Przed każdą ponowną próbą narzędzie czyta INTERMAX jeszcze raz, a
  inna wersja, którą OneDrive wgrał w przerwie, też daje to Zatrzymanie.
- **Drugie wklejenie dnia, który już jest uporządkowany, daje Zatrzymanie
  „dla taty”.** Dzień jest już uporządkowany, gdy nad wklejeniem stoją dwa
  kolejne uporządkowane wiersze z jego datą albo jeden, pod którym nie ma
  wiersza wcześniejszego dnia. Przegląd w górę od wklejenia kończy 10
  kolejnych wierszy wcześniejszego dnia. Zlecenie na jutro wpisane w środku
  dzisiejszego dnia, z wierszem dzisiejszego dnia pod nim, nie czyni więc
  jutra uporządkowanym. Zlecenie na jutro jako ostatni wiersz dnia albo dwa
  jedno pod drugim, z mniej niż 10 wierszami dzisiejszego dnia pod nimi,
  wyglądają jak uporządkowane jutro i dają to Zatrzymanie. U taty każde
  zlecenie na późniejszy dzień ma pod sobą co najmniej 10 wierszy dnia, w
  którym je wpisał (sprawdzone na historii kopii INTERMAX taty, #469).
- **Przygotowanie pliku zbiorczego nie zaczyna**, gdy okres ma Surowe
  zlecenia.
- **Uruchomienie Uporządkowania ma okres dzisiejszej daty** z zegara,
  ustalony przy starcie. ADR 0015 i 0017 wymagają okresu przed startem (issue
  Logów okresu, plik ostatniego startu), a uporządkowany dzień narzędzie zna
  dopiero po odczycie, a przy Zatrzymaniu przed nim (plik otwarty, brak
  Surowych zleceń, kilka dni) wcale. Logi Uruchomienia trafiają więc do issue
  okresu dzisiejszej daty, także gdy tata porządkuje zlecenia na jutro z
  następnego okresu. Podsumowanie podaje uporządkowany dzień: to nowy wyjątek
  od zakazu daty dziennej w Logach z ADR 0015, tego samego rodzaju co liczba
  zleceń na każdy dzień okresu w podsumowaniu Przygotowania, bez adresu i
  numeru zlecenia.

## Konsekwencje

- Własne pliki narzędzia z ADR 0004 obejmują Kopie INTERMAX. Nie są źródłem
  Statusu okresu, wyniku ani metryk; Centrum je wylicza z folderu Kopii i
  przywraca tylko Kopię, którą samo wymieniło.
- Reguła w `CODING_STANDARDS.md` o modułach, które zapisują skoroszyt, i jej test
  dostają moduł zapisu INTERMAX. Odczyt idzie przez to samo jedyne miejsce
  odczytu bajtów skoroszytu co w innych procesach.
- Nienadpisywanie przestaje obejmować Rejestr zleceń.

## Odrzucone warianty

- **Osobny plik eksportu, który tata wkleja po obróbce.** Tata i pracownicy
  pracują w INTERMAX; dodatkowy plik to dodatkowy krok ręczny.
- **Zapis całego skoroszytu w openpyxl.** Długi na laptopie taty i ryzykuje
  utratę tego, czego openpyxl nie zachowuje, w pliku, którego nie da się
  odtworzyć.
- **Same wersje OneDrive zamiast własnej Kopii.** Są tylko ze
  zsynchronizowanych zapisów, a tata nie przywróci ich sam.
- **„Cofnij” na karcie wyniku.** Kopia i przywracanie z Konfiguracji pokrywają
  awarię narzędzia, a cofnięcie po ręcznych poprawkach pracowników by je
  skasowało.
