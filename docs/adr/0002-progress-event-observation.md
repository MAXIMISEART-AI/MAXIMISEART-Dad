# ADR 0002: Kontrakt obserwacji Przebiegu rozliczeń

## Status

Zaakceptowana

## Decyzja

Silnik emituje Zdarzenia przebiegu przez walidowany kontrakt `ProgressEvent` i
centralne fabryki. `run_settlements()` przyjmuje opcjonalnego obserwatora;
reguły i wynik silnika nie zależą od jego obecności.

W ścieżce CLI `Dashboard` przekazuje każde zdarzenie dokładnie raz do jednej
projekcji postępu. Projekcja jest jedynym miejscem, które interpretuje surowe
zdarzenia. Zwraca niemutowalny snapshot i bezpieczne, neutralne powiadomienie o
zmianie. Adapter plain i adapter Rich renderują wyłącznie ten wspólny wynik; nie
interpretują `ProgressEvent`, nie utrzymują własnych liczników ani stanów faz.
Dashboard koordynuje wybór adaptera.

Awaria obserwatora odłącza go na resztę Przebiegu rozliczeń i nie przerywa pracy
silnika. Uruchomienie CLI zawsze obserwuje postęp.

Protokół etapów należy do sekwencera etapów (`PhaseRunner`), wspólnego dla
Przebiegu rozliczeń i Przygotowania pliku zbiorczego. Proces wywołuje cztery
nazwane etapy i podaje tylko wartości; START, END, FAILED etapów i zdarzenia
pośrednie `ISSUE_COUNT` oraz `PLAN_READY` wysyła sekwencer w stałej kolejności.
Proces przekazuje przez sekwencer tylko zdarzenia wykonawców z trwającego
Zapisywania. Pomylona kolejność albo niedozwolone zdarzenie to błąd kodu:
sekwencer zgłasza `ProgressProtocolError` w miejscu wywołania, także bez
obserwatora, zamiast traktować go jak awarię obserwatora. Sekwencer sprawdza
kolejność sam, bez projekcji, więc projekcja pozostaje niezależną kontrolą tego,
co wysyła.

Dotychczasowe pola `ProgressEvent` i wartości stanów pozostają zgodne; typed
states porządkują kontrakt, a `FAILED` dodaje jawny stan przerwania. Końcowa
telemetryka ukończonego uruchomienia, w tym czasy faz, pochodzi z
`SettlementSummary`. Silnik mierzy te czasy niezależnie od obecności obserwatora.
Telemetryka przerwanego uruchomienia pochodzi z ostatniego poprawnie
zredukowanego snapshotu. Schemat metryk pozostaje bez zmian.

## Uzasadnienie

Jedna projekcja utrzymuje wspólne znaczenie faz, liczników, bieżącego
Wykonawcy i wyniku Przetworzenia Szablonu pracownika dla trybu Rich i fallbacku
tekstowego. Walidacja przy wejściu odrzuca kombinacje, których projekcja nie
może bezpiecznie zinterpretować. `FAILED` oznacza przerwanie, więc nie udaje
zakończenia fazy ani Przetworzenia Szablonu pracownika.

Zdarzenia zawierają wyłącznie bezpieczne fakty procesu. Exception text,
adresy klientów, numery zleceń i treści Wierszy danych pozostają poza seamem
obserwacji.

## Konsekwencje

- CLI może zmieniać sposób prezentacji bez ponownego interpretowania zdarzeń.
- Zmiana reguł projekcji nie wymaga zsynchronizowanej zmiany adapterów Rich i
  plain.
- Awaria adaptera terminala nie zmienia wyniku, zapisu ani kodu wyjścia silnika;
  po pierwszym wyjątku nie jest on ponownie wywoływany w tym przebiegu.
  Odłączony obserwator jest sygnalizowany jedną neutralną linią na końcu
  uruchomienia, bez tekstu wyjątku.
- Telemetryka końcowego snapshotu zachowuje istniejący schemat i pozostaje
  oparta na `SettlementSummary` dla ukończonego Przebiegu rozliczeń.
- Zwykłe CLI obserwuje postęp; bez Rich używa adaptera plain z tą samą
  projekcją i informacjami operacyjnymi.
- Nowy stan i walidacja są częścią lokalnego kontraktu; nie są formatem
  zewnętrznej usługi ani zapisem danych klientów.
