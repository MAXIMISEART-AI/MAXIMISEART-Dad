# ADR 0003: Tylko CLI uruchamiane przez CMD, bez adaptera VBA

## Status

Zaakceptowana. Zastępuje część ADR 0001 dotyczącą adaptera VBA. Część o
uruchamianiu procesów wyłącznie przez CLI zastąpiona przez
[ADR 0004](0004-centrum-rozliczen-adapter.md). Launchery `.cmd` usunięte przez
[ADR 0010](0010-centrum-jedynym-wejsciem-taty.md).

## Decyzja

Wszystkie procesy, w tym Przebieg rozliczeń i Przygotowanie pliku zbiorczego,
są uruchamiane wyłącznie przez CLI Pythona. Dla taty każdy proces ma własny
launcher `.cmd`. Rezygnujemy z adaptera VBA w pliku `.xlsm` i nie budujemy go
dla nowych procesów.

## Uzasadnienie

Druga ścieżka uruchomienia wymaga osobnej, ręcznej bramy walidacji w
desktopowym Excelu, zależy od polityki makr i dokłada ukryte przełączniki do
CLI, nie dając tacie nowych możliwości. Docelowo cały proces taty ma działać
jako jedna całość w tle, a to łatwiej osiągnąć z jednego wejścia CLI niż z
przycisku w Excelu.

## Konsekwencje

- `deploy/AutomatyzacjaRozliczen.bas`, ukryty przełącznik `--no-observer`
  (ADR 0002), `docs/adapter-validation.md` oraz sekcje README i instrukcji taty
  dotyczące Excela zostały usunięte w osobnym zadaniu porządkowym.
- Nowe procesy nie potrzebują trybu bez obserwatora dla VBA.
