# ADR 0016: Uzupełnienie pliku zbiorczego w Centrum: treść wierszy w przeglądarce i odczyt pliku otwartego w Excelu

## Status

Zaakceptowana. Zmienia dwie zasady [ADR 0004](0004-centrum-rozliczen-adapter.md) tylko dla stron
Uzupełnienia pliku zbiorczego (specyfikacja #415):

- regułę prywatności „Adresy klientów, numery zleceń, treści Wierszy danych i tekst wyjątków nie trafiają do
  przeglądarki”: przeglądarka dostaje wybrane pola wierszy Ilości do uzupełnienia (niżej);
- zasadę, że skoroszyt otwarty w Excelu daje Komunikat: te strony czytają ostatnią zapisaną wersję Pliku
  zbiorczego, który trzyma Excel.

## Kontekst

Po Przygotowaniu pliku zbiorczego tata wpisuje w Excelu Ilości do uzupełnienia. Numery wierszy dostawał tylko w
ostrzeżeniach na karcie wyniku, które giną z Uruchomieniem, a postępu nie widział nigdzie. Uzupełnianie trwa
godzinami, z Plikiem zbiorczym otwartym w Excelu, więc strona, która wymaga zamknięcia pliku, nic by mu nie dała.

## Decyzja

- **Stan zawsze z pliku.** Każdy odczyt strony przelicza Reguły ilości na Wierszach danych zapisanego Pliku
  zbiorczego i czyta Ilości usług taty tym samym odczytem i filtrem co Kontrola ilości (ADR 0013). Centrum nic
  nie przechowuje i nigdy nie zmienia Pliku zbiorczego z tych stron.
- **Co widzi przeglądarka.** Dla wierszy Ilości do uzupełnienia: numer wiersza Pliku zbiorczego, `WYKONAWCA`,
  `URZĄDZENIA`, `CZYNNOŚCI`, `CZYNNOŚCI ZREALIZOWANE`, litery kolumn `N:AP` z nazwami pozycji cennika ze Wzorca
  oraz Ilości usług narzędzia i taty. Nigdy adresu, numeru zlecenia ani `UMOWA`. Pierwsza strona (#417) pokazuje
  z tego tylko numery wierszy, stan „zrobione” i liczniki kolumn z opisu technika.
- **Dane nie wychodzą z komputera.** Te pola nie trafiają do Logów Uruchomienia, Zgłoszenia, Uwagi taty,
  dziennika Centrum ani pomiaru widoku. Dziennik dostaje przy nieudanym odczycie tylko token okresu, kod
  Komunikatu, stan pliku blokady Excela i nazwę typu błędu.
- **Odczyt mimo blokady Excela.** Jedyna funkcja czytająca Plik zbiorczy dostaje jawne pozwolenie na odczyt mimo
  pliku blokady `~$…`. To nie jest drugi czytnik: Przebieg rozliczeń dalej odmawia pliku otwartego w Excelu,
  bo czyta go do zapisu Rozliczeń pracowników, a tata ma najpierw zapisać i zamknąć plik.
- **Niesprawdzone założenie o Autozapisie OneDrive.** Zakładamy, że Autozapis zmienia plik na dysku kilka sekund
  po wpisie taty. Test Maksa na laptopie taty się nie udał, a to, czy Windows daje czytać plik, który trzyma
  Excel, sprawdzi dopiero pierwsze wdrożenie przez wpis `uzupelnienie-odczyt-nieudany` w dzienniku. Gdy
  założenie nie działa, zabezpieczeniem jest wskazówka „Nie widzisz zmian? Zapisz w Excelu (Ctrl+S)”.
- **Na żywo (#419).** Widoczna strona co 3 s pyta o znacznik zapisu Pliku zbiorczego (czas zmiany i rozmiar z
  `stat`, bez otwierania skoroszytu) i czyta widok dopiero po jego zmianie. Gdy odczyt się nie uda, Centrum przez
  minutę oddaje ostatni dobry odczyt z jego godziną, a dopiero potem Komunikat. Ten odczyt jest jedynym, co Centrum
  pamięta: tylko w pamięci procesu, po każdym dobrym odczycie, i pokazuje go tylko podczas serii nieudanych prób,
  więc zmienia tylko to, co strona pokazuje podczas porażki. Po ponownym starcie Centrum go nie ma, a źródłem stanu
  dalej jest plik. Przejścia serii nieudanych prób opisuje tabela w `LastGoodReads` (`live_file.py`). Kończy ją
  dobry odczyt. Serię, która jeszcze nie oddała Komunikatu, kończy też cisza dłuższa niż kilka odstępów
  odpytywania (ukryta karta, także zasłonięta przez zmaksymalizowany Excel), ale tylko wtedy, gdy znacznik zapisu
  zmienił się od ostatniej porażki. Bez zmiany znacznika plik nie mógł wrócić, więc trwała porażka oglądana
  zrywami daje Komunikat po około minucie, jak mówi historia 24. Przerwę mierzy się od końca ostatniej porażki
  do początku następnej próby, więc wolny nieudany odczyt (OneDrive pobiera plik) nie przerywa serii. Seria
  z Komunikatem, także oddanym od razu z braku dobrego odczytu, trwa do dobrego odczytu, bo po Komunikacie strona
  nie ponawia odczytu sama. Do dziennika trafia przyczyna (kod Komunikatu), której tam nie ma od ostatniego
  dobrego odczytu. Znany przypadek: po Komunikacie i naprawie pliku, której nikt nie czytał, chwilowa porażka
  przy następnej wizycie od razu daje Komunikat bez nowego wpisu. Znika on przy następnej zmianie znacznika,
  zwykle po sekundach.

## Odrzucone warianty

- **Kopia stanu w Centrum.** Lista wierszy zapisana przy Przygotowaniu przestaje być prawdziwa po usunięciu
  wiersza albo poprawce `URZĄDZENIA` w Excelu i trzeba ją przechowywać obok plików okresu.
- **Zaznaczenie komórek kolorem w samym Pliku zbiorczym.** Kolor zostaje po wpisie, bo Excel go nie zdejmie, a
  Wyróżnienia przechodzą do Rozliczeń pracowników.
- **Edycja ilości w Centrum.** Wymaga zapisu do pliku, który tata ma otwarty, i osobnej decyzji (ADR 0004).
