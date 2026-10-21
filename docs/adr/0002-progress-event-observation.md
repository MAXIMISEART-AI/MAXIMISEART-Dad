# ADR 0002: Kontrakt obserwacji Przebiegu rozliczeń

## Status

Zaakceptowana. Zmieniona 2026-10-20: Zdarzenia przebiegu są osobnymi typami, a
kolejność sprawdza tylko sekwencer etapów (patrz „Zmiana z 2026-10-20”).
[ADR 0011](0011-bez-cli-i-adapterow-terminala.md) usuwa adaptery plain i Rich
oraz CLI: jedynym podglądem postępu jest Centrum rozliczeń, a projekcja zwraca
sam snapshot bez faktów, które czytał tylko terminal.

## Decyzja

Silnik emituje Zdarzenia przebiegu jako `ProgressEvent`: sumę typów
`PhaseStarted`, `PhaseEnded`, `PhaseFailed`, `IssueCountReady`, `PlanReady`,
`WorkerStarted`, `WorkerEnded` i `WorkerFailed`. Każdy typ ma tylko swoje pola,
więc niedozwolonej kombinacji pól nie da się zbudować. `run_settlements()`
przyjmuje opcjonalnego obserwatora; reguły i wynik silnika nie zależą od jego
obecności.

Rdzeń Uruchomienia procesu (`process_run`) jest obserwatorem silnika i
przekazuje każde zdarzenie dokładnie raz do jednej projekcji postępu. Projekcja
jest jedynym miejscem, które interpretuje surowe zdarzenia. Zwraca niemutowalny
snapshot razem ze zdarzeniem, które go zmieniło; rdzeń podaje oba podglądowi
postępu rozmówcy. Adapter plain i adapter Rich renderują wyłącznie
ten wspólny wynik; nie interpretują `ProgressEvent`, nie utrzymują własnych
liczników ani stanów faz. Podgląd postępu terminala
(`terminal_conversation`) koordynuje wybór adaptera.

Awaria obserwatora odłącza go na resztę Przebiegu rozliczeń i nie przerywa pracy
silnika. Uruchomienie CLI zawsze obserwuje postęp.

Protokół etapów należy do sekwencera etapów (`PhaseRunner`), wspólnego dla
Przebiegu rozliczeń i Przygotowania pliku zbiorczego. Proces wywołuje cztery
nazwane etapy i podaje tylko wartości; zdarzenia etapów oraz pośrednie
`IssueCountReady` i `PlanReady` wysyła sekwencer w stałej kolejności. Proces
przekazuje przez sekwencer tylko zdarzenia Szablonów pracownika z trwającego
Zapisywania. Sekwencer jest jedynym miejscem, które sprawdza kolejność: etapów,
Szablonów pracownika (po kolei od 1 do liczby z planu, zakończenie pasuje do
rozpoczęcia) i to, że Zapisywanie kończy się po wszystkich Szablonach
pracownika. Pomyłka to błąd kodu: sekwencer zgłasza `ProgressProtocolError` w
miejscu wywołania, także bez obserwatora, zamiast traktować go jak awarię
obserwatora. Projekcja redukuje zdarzenia bez ponownego sprawdzania.

`PhaseFailed` i `WorkerFailed` są jawnym przerwaniem. Końcowa
telemetryka ukończonego uruchomienia, w tym czasy faz, pochodzi z
`SettlementSummary`. Silnik mierzy te czasy niezależnie od obecności obserwatora.
Czasy etapów przerwanego uruchomienia pochodzą z ostatniego poprawnie
zredukowanego snapshotu; liczniki takiego rekordu mają wartość 0, a wynik to
`BLAD_KRYTYCZNY`, bo statystyki czytają tylko ukończone rekordy. Schemat metryk
pozostaje bez zmian.

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

## Zmiana z 2026-10-20

Dotąd `ProgressEvent` był jednym rekordem z polem stanu i jedenastoma polami
opcjonalnymi, a dozwolone kombinacje pól sprawdzał ręcznie konstruktor (ok. 140
linii). Kolejność sprawdzały dwa miejsca: sekwencer etapów i projekcja. Od
wprowadzenia sekwencera jest on jedynym nadawcą zdarzeń, więc druga kontrola
powtarzała pierwszą, a zdarzenia Szablonów pracownika sprawdzała tylko
projekcja.

Zdarzenia są teraz osobnymi typami, więc kontrola kształtu znika razem z
fabrykami i osobnym powiadomieniem projekcji. Kontrola kolejności Szablonów
pracownika przechodzi do sekwencera, a projekcja tylko redukuje. Odrzucony
kierunek: zostawienie projekcji jako drugiej kontroli. Testy projekcji musiałyby
budować zdarzenia, których sekwencer nigdy nie wyśle.
