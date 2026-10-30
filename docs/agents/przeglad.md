# Przegląd PR

Ten plik czyta niezależny recenzent, zanim napisze werdykt, i autor, zanim zleci przegląd.
`PASS` mówi też, że skille `verify-*` z linii `SKILLE VERIFY` przeszły na tym SHA (gotowość w [`AGENTS.md`](../../AGENTS.md)).
Postać werdyktu, którą przyjmuje `tools/scal_pr.py`, podaje jego `--help`.

## Co jest porażką

Ważne znalezisko to defekt zachowania z dowodem, który da się powtórzyć: polecenie, jego wynik i plik:linia.
Tylko Ważne daje `FAIL`.
W tym repo Ważne były zwykle:

- test, który przestał sprawdzać to, co sprawdzał (pokrycie zgubione przy refaktorze, asercja na tekst zamiast na zachowanie);
- zachowanie widoczne tylko na Windows albo na Pythonie 3.11 (brak `tzdata`, krok zegara `time.monotonic()`, import, który pada tylko pod 3.11);
- stan, który jedna część przebiegu zakłada po innej (część podstawy skilla startująca od środka porządku);
- przypisanie albo zakres liczony od złej linii lub złego commitu (np. `git blame` pierwszej linii wielowierszowej instrukcji).

Drobne znalezisko to luka bez defektu: przeżyta mutacja, której nic nie łapie, nieaktualne zdanie w dokumencie, kosztowna, ale poprawna droga.
Drobnych podaj najwyżej 3, najważniejsze.
Defekt, który zmiana PR wywołuje albo ujawnia, liczy się do werdyktu także wtedy, gdy siedzi w pliku, którego PR nie zmienia (np. nowa konfiguracja uruchamia niezmieniony kod w nowym stanie).
Istniejące wcześniej to tylko defekt, który powtarzasz na merge-base bez tej zmiany, i do werdyktu się nie liczy.
Styl, nazwy i formatowanie zostawiasz ruffowi, mypy i lintom frontendu.

## Dowody

Każde znalezisko ma plik:linia i dowód: polecenie z wynikiem, repro albo mutację z `tools/mutacje.py` (`NIEWYKRYTA` albo `WYKRYTA`).
Recenzent refaktoru, czyli zmiany, która nie ma zmieniać zachowania procesów, uruchamia `.venv/bin/python tools/rownowaznosc.py --baza <merge-base>` i wkleja do werdyktu jego ostatnią linię.
Recenzent PR-u, który dodaje albo zmienia sprawdzenie (test struktury, regułę lintu, zadanie CI, narzędzie sprawdzające), uruchamia samo to sprawdzenie przez `tools/na_scalonych_pr.py --commit <SHA>` na jednym z commitów, które opis PR podaje jako złapane, i wkleja ostatnią linię wyniku.
Mutacje recenzenta biegną po kolei, z `PYTEST_XDIST_AUTO_NUM_WORKERS=1`, najwyżej kilkanaście.
Pełnych mutacji i pełnego CI recenzent nie uruchamia lokalnie, bo liczy je CI i noc (ADR 0021).

## Postać werdyktu

Pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>` albo `WERDYKT: FAIL <pełny SHA HEAD>`.
Druga podaje liczbę znalezisk w postaci `Znaleziska: N (Ważne a, Drobne b)`.
Dalej znaleziska od najważniejszego, każde z oznaczeniem, plik:linia i dowodem, a na końcu krótko, co sprawdzone i z jakim wynikiem.

## Kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i to, czy każde znalezisko poprzedniej rundy jest zamknięte.
Zamkniętych znalezisk nie powtarza.
Nowe znalezisko w kodzie, którego ta runda nie zmieniła, jest Ważne tylko wtedy, gdy to defekt zachowania z dowodem.
Po trzeciej rundzie z `FAIL` koordynator nie zleca czwartej, tylko zmienia podejście albo dzieli PR.
Każdą rundę robi nowy recenzent, który nie pisał kodu, z linkiem do poprzednich werdyktów.
