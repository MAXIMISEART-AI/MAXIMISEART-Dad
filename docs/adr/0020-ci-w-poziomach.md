# ADR 0020: CI w poziomach

## Status

Zaakceptowana (decyzje Maksa z 26.10).
Wdrażana krokami, jeden PR na krok; do ich merge'a CI działa po staremu.
Opiera się na [ADR 0014](0014-tata-dostaje-tylko-wydania.md), według którego tata dostaje tylko Wydanie z commitu `main` z zielonym `Required CI status`.

## Kontekst

Do 26.10 każdy PR uruchamiał prawie pełne CI, czyli wszystkie pliki testów na trzech torach (Windows 3.11, Windows 3.14, Linux 3.14), E2E, podstawy i skrypty mutacji skilli `verify-*` oraz Change mutations bez limitu.
Każda poprawka jakości dokładała pracę do każdego PR (#406 Change mutations, #449 podstawy skilli), a nic nie liczyło jej kosztu.
Mediana czasu do werdyktu PR wzrosła z 4,3 min przed 21.10 do 26,6 min 26.10 (p90 39,7 min).
42% tego czasu to kolejka, bo konto ma limit 20 zadań naraz, a jeden run PR zajmował 14–19 zadań.

Wartość ciężkich zadań w 28 dniach do 26.10:
Change mutations zużyło 113 runner-godzin i nie złapało żadnego defektu produktu, którego nie złapał pytest w tym samym runie; dało 35 luk w testach.
Mutation checks zużyło 222 runner-godziny, złapało 1 unikalny defekt (#438), a 88% jego porażek to flaki, infrastruktura albo błąd samego sprawdzenia.
Tor Windows 3.11 sam złapał 2 defekty importu na Pythonie 3.11 (#282, #285).

## Decyzja

Zakres sprawdzeń na PR zależy od zmiany i jej blast radius.
Pełny zestaw biegnie po merge'u na `main`.
CI ma cztery stopnie:

1. **Lokalnie.** `tools/szybko.py` przed pushem.
2. **Bramka PR.** `Required CI status` na PR, warunek gotowości z `AGENTS.md`.
   pytest biegnie tylko na testach wybranych dla zmiany, na Windows 3.11 (minimum u taty) i Linux 3.14.
   Zmiana `.github/workflows/**` wybiera wszystko.
   Podstawa skilla `verify-*` biegnie, gdy zmiana trafia w jego `pilnuje:`, a jego skrypty mutacji, gdy zmienił się folder skilla.
   Change mutations nie blokuje. Biegnie po zadaniach bramki, jedna mutacja na zmienioną linię, a każdą przeżytą recenzent omawia w werdykcie.
3. **Pełne CI `main`.** Wszystko, co dziś, z Windows 3.14 i wszystkimi skillami.
   Trwający run `main` się kończy, a nowy merge podmienia tylko run, który czeka.
   Czerwony `main` nie blokuje merge'ów; naprawia go osobny PR, a winnego wśród kilku merge'ów wskazuje bisect.
4. **Wydanie.** Tylko commit `main` z zielonym pełnym CI (ADR 0014).
   To jest granica bezpieczeństwa taty, więc `main` może być czerwony nawet cały dzień.

Jakość bramki to odsetek prawdziwych defektów, które łapie w PR, a nie ilość wykonanej pracy.
Mierzy ją backtest na czerwonych runach z prawdziwym defektem.
Przed wdrożeniem bramka z torem Windows 3.11 łapała 11 z 11 defektów produktu z 28 dni.

### Gdy defekt przejdzie przez bramkę

Najpierw poprawka w codebase albo środowisku agenta, tak żeby ta klasa błędu nie wróciła (architektura, typy, lint, test, a proza na końcu).
Do bramki trafia tylko to, co złapałoby ten defekt, z dowodem z backtestu, czyli test, krawędź wyboru testów albo glob `pilnuje:`.
Pełnego zestawu ani całego zadania CI do bramki się nie dokłada.
Test kształtu planu bramki dla wzorcowych PR-ów (mały, tylko z testami, i Centrum) ma limit liczby zadań i prognozy czasu; przekroczenie to decyzja Maksa.

### Niestabilne testy

Bramka ponawia raz tylko test, który padł.
Przejście po ponowieniu przechodzi, ale trafia do zapisu, z którego powstaje issue dla tego testu; dwa padnięcia to prawdziwa porażka.
Kwarantanna to wpis z numerem issue i datą wygaśnięcia najwyżej 7 dni od wpisania; test w kwarantannie dalej biegnie na `main`, nie blokując.
Maks zgodził się 26.10 na takie wpisy z góry, więc nie wymagają osobnej zgody z `AGENTS.md`; wpis bez issue, z dłuższym terminem albo wygasły czerwieni strażnika.

## Konsekwencje

- Defekt, który przejdzie przez bramkę, pokazuje dopiero `main`, po kilkudziesięciu minutach; do taty nie trafi, bo Wydanie wymaga zielonego pełnego CI.
- Dwa PR-y zielone osobno mogą się zepsuć dopiero razem na `main` (2 razy w 28 dniach do 26.10).
  Issue czerwonego `main` rozpoznaje takie zderzenie; gdy zderzenia się powtarzają, wraca decyzja o merge queue.
- Przy 100 PR dziennie limit 20 zadań wydłuża bramkę w godzinach szczytu (w symulacji p50 10,2 min i p90 21,6 min wobec 6,2 i 7,4 min przy 40 zadaniach).
- Dalsze skracanie bramki to przyspieszanie samych testów, nie zdejmowanie ich z bramki.

## Odrzucone warianty

- Pełne CI na każdym PR, szybsze przez więcej równoległych zadań. Praca rośnie ze zmianą, a każde zadanie więcej to mniej slotów dla innych PR-ów.
- Anulowanie każdego starszego runu `main`. Przy częstych merge'ach pełny werdykt dostaje mało commitów, a Wydanie nie ma z czego wybierać.
- Merge queue od razu. Werdykt `PASS <SHA HEAD>` w `tools/scal_pr.py` dotyczy commitu PR, a kolejka testuje inny commit; zderzeń było za mało, żeby to uzasadnić.
- Runnery Blacksmith. Wymagają organizacji GitHuba zamiast konta osobistego, Windows mają w becie, a koszt to setki dolarów miesięcznie przy darmowych minutach repo publicznego.
