# ADR 0021: Mutacje nocą

## Status

Zaakceptowana (decyzja Maksa z 29.10: „nie możemy na każdy nowy PR odpalać mutacji”).
Zastępuje część [ADR 0020](0020-ci-w-poziomach.md) o Change mutations na PR: poziom bramki PR i `tools/scal_pr.py` przestają na nie czekać.
Opiera się na [ADR 0014](0014-tata-dostaje-tylko-wydania.md) i ADR 0020, według których granicą bezpieczeństwa taty jest Wydanie, a nie PR.

## Kontekst

Cel Maksa to czas CI na PR z p50 najwyżej 2 min i p90 najwyżej 5 min, jak w najlepszych repo (Matt Pocock course-video-manager p50 2,6 min, t3code p50 4,2 min).
Po ADR 0020 Change mutations startowały po zielonym `Required CI status` na każdym PR, który zmieniał `src/` albo `tools/`, i trwały 15–18 min.
Na przykład w runie 40612759981 Required skończył się po 5,6 min, a Change mutations po 21 min.
`tools/scal_pr.py` czekał na ich koniec i wymagał w `PASS` linii `MUTACJA` dla każdej przeżytej mutacji, więc to one były ogonem czasu do merge'a.
W części mutacji 6–10 min zajmuje pokrycie testów zmienionych plików, a każda mutacja ok. 10 s (runy z 27–28.10).
ADR 0020 podaje, że Change mutations nie złapały żadnego defektu produktu, którego nie złapał pytest w tym samym runie, a dały luki w testach.
Luka w teście nie jest defektem, który trafi do taty: ten zatrzymuje Wydanie z zielonym pełnym CI `main`.

## Decyzja

- Change mutations nie biegną na PR.
  `ci.yml` nie ma ich zadania, plan CI ich nie liczy, a `tools/scal_pr.py` nie sprawdza ich ani linii `MUTACJA` w `PASS`.
- Workflow `mutacje-nocne.yml` biegnie raz na dobę na `main` i ręcznie z opcjonalnym `od`.
  Mutuje linie `src/` i `tools/` zmienione od commitu ostatniego udanego przebiegu (bez niego od 24 h wstecz) tym samym `tools/mutacje_zmiany.py`: jedna mutacja na linię, cofnięcie fragmentu, wyjątki `# mutacje-zmiany:`.
- Mutacje dzielą się na części po najwyżej 25, kolejne na liście posortowanej po plikach, żeby każda część liczyła pokrycie tylko dla kilku plików i trwała 10–15 min.
- Każda przeżyta mutacja trafia do issue `Przeżyte mutacje z #N` z etykietą `ready-for-agent` PR-u, który ostatni zmienił zmienione linie, które ona psuje (`git blame` na `main`, commit scalenia, a bez numeru w jego temacie API GitHuba).
  Jedno issue na PR, a ta sama mutacja nie trafia do niego drugi raz, także gdy jej linie się przesuną: porównuje się klucz z pliku i zmienionego kodu, bez numerów linii.
  Issue naprawia agent testem, który zabija mutację, albo linią `MUTACJA <id> | nie warto, bo <powód>`.
- Część, która nie dała wyniku, jest czerwona, a przebieg z nią jest czerwony i nie przesuwa bazy, więc następna noc sprawdza te linie jeszcze raz.
  Przeżyte mutacje to wynik, więc zostawiają część zieloną.

## Konsekwencje

- Luka w testach PR wychodzi najpóźniej następnego dnia, w issue jego PR, a nie przed merge'em.
  PR, który by ją zamknął, jest osobną pracą z kolejki `ready-for-agent`.
- Recenzent nie omawia już mutacji w `PASS`, a przegląd PR kończy się razem z bramką.
- Noc mutuje zmiany wielu PR-ów naraz, więc pokrycie biegnie na testach wielu plików; części po plikach trzymają je w 10–15 min, a gdy zmian jest więcej niż na 20 części, części rosną.
- Przebieg nocny, który nie skończył się sukcesem, nie zakłada issue o sobie; widać go w Actions, a następna noc powtarza jego zakres.

## Odrzucone warianty

- Change mutations na PR, ale bez czekania na nie w `tools/scal_pr.py`. Każdy PR dalej zajmowałby trzy runnery po 15 min, a wynik po merge'u i tak musiałby trafić do issue.
- Mutacje tylko PR-ów z etykietą albo powyżej rozmiaru zmiany. Luki w testach są w małych zmianach tak samo, a wybór PR-ów to osąd, którego nic nie sprawdza.
- Mutacje przy Wydaniu. Wydanie zbiera zmiany wielu dni, więc przebieg byłby długi, a luka wychodziłaby dopiero wtedy, gdy autor PR jest już przy innej pracy.
