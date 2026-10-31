# ADR 0023: Przegląd PR jako skill z narzędziem recenzenta

## Status

Zaakceptowana na próbę (decyzja Maksa z 31.10 w wątku T3 po hillclimbie przeglądu 30–31.10).
Przez tydzień od merge'a obserwujemy ją na żywo, a potem Maks decyduje, czy zostaje.
Zastępuje `docs/agents/przeglad.md`: jego reguły są teraz w skillu `przeglad`.

## Kontekst

47% PR-ów dostawało `FAIL` w pierwszej rundzie przeglądu, a PR-y z `FAIL` zajmowały 68% godzin otwartych PR-ów (23–30.10).
Recenzent czytał reguły z `docs/agents/przeglad.md`, sam zbierał kontekst (SHA HEAD, merge-base, skille `verify-*`, poprzednie werdykty) i sam pisał komentarz z werdyktem, więc postać werdyktu sprawdzał dopiero `tools/scal_pr.py` przy merge'u.
Hillclimb zmierzył warianty przeglądu na poligonie (`maximiseartai/rozliczenia`) na 72 przypadkach z historii repo: 52 z defektem znanym z późniejszej poprawki i 20 czystych.
Stan wyjściowy (`main` 99703a21, dwa powtórzenia) trafiał defekt jako Ważne w 0,50 przypadków, a w 0,19 widział go, ale oceniał jako Drobne.
Rozrzut dwóch powtórzeń tego samego wariantu to ok. ±0,12 trafności, więc mniejsza różnica nie jest mierzalna.

## Decyzja

- Reguły przeglądu są w skillu [`przeglad`](../../.agents/skills/przeglad/SKILL.md): co jest porażką, dowody, postać werdyktu i kolejne rundy, wspólne dla autora i recenzenta.
- Tryb recenzenta ma kroki: `tools/scal_pr.py N --przeglad` drukuje kontekst, recenzent dopisuje każde potwierdzone znalezisko od razu do pliku rundy, a `tools/scal_pr.py N --werdykt <plik>` sprawdza obie pierwsze linie, SHA HEAD i zgodność `PASS`/`FAIL` z liczbą Ważnych, zanim opublikuje werdykt jako komentarz PR.
- Tryb autora to tylko to, co autor czyta, zanim zleci przegląd po pushu: autor nie przegląda własnego diffu przed pushem.

## Dowód

Wariant L1 (ta decyzja) względem stanu wyjściowego:

- „widziane, ale ocenione jako Drobne” 0,19 → 0,04, czyli spadek poza szumem pomiaru;
- trafność 0,52 → 0,58, czyli w szumie: wariant jej nie pogarsza, ale też nie dowodzi poprawy;
- 0 fałszywych Ważnych na czystych przypadkach poza spornym #408.

## Odrzucone warianty

- Przegląd autora przed pushem (L2): autor zleca świeżemu agentowi przegląd swojego diffu przed pushem i poprawia Ważne, zanim przegląd zrobi niezależny recenzent.
  W pomiarze czas do werdyktu urósł o 27%, a koszt dwa razy, bez zysku w trafności, więc skill nie każe autorowi przeglądać diffu przed pushem.

## Konsekwencje

- Werdykt w złej postaci (brak linii `Znaleziska:`, `PASS` z Ważnym, SHA innego commitu) odrzuca `--werdykt` przed publikacją, a nie `tools/scal_pr.py` przy merge'u.
- Przez tydzień od merge'a koordynator liczy na żywo: odsetek PR-ów z `PASS` w pierwszej rundzie, błędy przepuszczone przez przegląd (znalezione po merge'u) i czerwony `main`.
  Po tygodniu Maks decyduje na tych liczbach, czy skill zostaje, a do tego czasu `docs/agents/przeglad.md` nie wraca.
