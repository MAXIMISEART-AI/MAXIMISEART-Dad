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
  Teksty i komórki dostaje tylko strona rodzaju (#418), osobnym zasobem dla jednego rodzaju, więc podsumowanie
  ich nie niesie. Nazwy pozycji cennika są z wiersza 17 Pliku zbiorczego, który Przygotowanie kopiuje z Wzorca.
- **Komórka pokazuje plik.** Komórka `N:AP` strony rodzaju ma wartość z Pliku zbiorczego. W kolumnie, którą
  wyznaczają Reguły ilości, jest szara i nie robi wiersza zrobionym, a w pozostałych jest wpisem taty. Gdy tata
  nadpisze w Excelu wartość narzędzia, strona pokazuje jego wartość, jak plik. Przeglądarka nie dostaje wyniku
  Reguł ilości obok wartości z pliku, bo ich porównanie to Kontrola ilości, która zostaje dla Maksa.
  Teksty wierszy nie wchodzą do `OrderFacts`, więc nie trafiają do Kontroli ilości ani do Logów Uruchomienia.
- **Dane nie wychodzą z komputera.** Te pola nie trafiają do Logów Uruchomienia, Zgłoszenia, Uwagi taty,
  dziennika Centrum ani pomiaru widoku. Dziennik dostaje przy nieudanym odczycie tylko token okresu, kod
  Komunikatu, stan pliku blokady Excela i nazwę typu błędu.
- **Odczyt mimo blokady Excela.** Jedyna funkcja czytająca Plik zbiorczy dostaje jawne pozwolenie na odczyt mimo
  pliku blokady `~$…`. To nie jest drugi czytnik: Przebieg rozliczeń dalej odmawia pliku otwartego w Excelu,
  bo czyta go do zapisu Rozliczeń pracowników, a tata ma najpierw zapisać i zamknąć plik.
- **Wiersze bez ilości przy Gotowości (#421).** Okno „Uruchomić z zapisem?” Przebiegu rozliczeń wymienia numery
  wierszy z listą (bez reguły, z opisu), które nie są zrobione, z tego samego odczytu. Czyta je osobny zasób
  okresu, gdy karta pokazuje ten okres, a nie ustawienie Przebiegu dla każdego okresu do wyboru, bo jeden odczyt
  trwa u taty ponad sekundę. Wiersz objęty regułą nigdy tam nie trafia, bo ilości wpisało mu narzędzie.
  Nieudany odczyt nie blokuje startu: okno mówi, że wierszy nie dało się sprawdzić, a wpis w dzienniku i
  Komunikat daje strona Uzupełnienia. Gotowość dalej potwierdza tata, a Centrum nie przechowuje stanu „Gotowe”.
- **Niesprawdzone założenie o Autozapisie OneDrive.** Zakładamy, że Autozapis zmienia plik na dysku kilka sekund
  po wpisie taty. Test Maksa na laptopie taty się nie udał, a to, czy Windows daje czytać plik, który trzyma
  Excel, sprawdzi dopiero pierwsze wdrożenie przez wpis `uzupelnienie-odczyt-nieudany` w dzienniku. Gdy
  założenie nie działa, zabezpieczeniem jest wskazówka „Nie widzisz zmian? Zapisz w Excelu (Ctrl+S)”.

## Odrzucone warianty

- **Kopia stanu w Centrum.** Lista wierszy zapisana przy Przygotowaniu przestaje być prawdziwa po usunięciu
  wiersza albo poprawce `URZĄDZENIA` w Excelu i trzeba ją przechowywać obok plików okresu.
- **Zaznaczenie komórek kolorem w samym Pliku zbiorczym.** Kolor zostaje po wpisie, bo Excel go nie zdejmie, a
  Wyróżnienia przechodzą do Rozliczeń pracowników.
- **Edycja ilości w Centrum.** Wymaga zapisu do pliku, który tata ma otwarty, i osobnej decyzji (ADR 0004).
