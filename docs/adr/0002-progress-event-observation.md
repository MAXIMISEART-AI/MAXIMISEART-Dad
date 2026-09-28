# ADR 0002: Kontrakt obserwacji Przebiegu rozliczeń

## Status

Zaakceptowana

## Decyzja

Silnik emituje Zdarzenia przebiegu przez jeden, walidowany kontrakt
`ProgressEvent` i centralne fabryki. Kontrakt zachowuje dotychczasowe pola oraz
wartości stringowe, a typed states dodają jawny stan `FAILED`.

Surowe zdarzenia są redukowane dokładnie raz przez projekcję postępu bez efektów
zewnętrznych.
Adaptery terminala otrzymują wyłącznie niemutowalny snapshot oraz bezpieczne,
neutralne powiadomienie o zmianie. Wyjątek adaptera odłącza obserwatora i nie
przerywa właściwego silnika.

## Uzasadnienie

Jedna projekcja utrzymuje wspólne znaczenie faz, liczników, bieżącego
Wykonawcy i wyniku Przetworzenia Szablonu pracownika dla trybu Rich i fallbacku
tekstowego. Walidacja przy wejściu odrzuca kombinacje, których adapter nie może
bezpiecznie zinterpretować. `FAILED` oznacza przerwanie, więc nie udaje
zakończenia fazy ani Przetworzenia Szablonu pracownika.

Zdarzenia zawierają wyłącznie bezpieczne fakty procesu. Exception text,
adresy klientów, numery zleceń i treści Wierszy danych pozostają poza seamem
obserwacji.

## Konsekwencje

- CLI może zmieniać sposób prezentacji bez ponownego interpretowania zdarzeń.
- Telemetryka końcowego snapshotu zachowuje istniejący schemat i pozostaje
  oparta na `SettlementSummary` dla ukończonego Przebiegu rozliczeń.
- Obserwator jest opcjonalny, więc ścieżka VBA nadal uruchamia ten sam silnik
  bez adaptera.
- Nowy stan i walidacja są częścią lokalnego kontraktu; nie są formatem
  zewnętrznej usługi ani zapisem danych klientów.
