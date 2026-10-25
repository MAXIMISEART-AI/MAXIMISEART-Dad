# Skille projektu

## Skille weryfikacji przed pushem

- Przed pushem uruchom `tools/skille_dla_zmiany.py`, załaduj każdy skill `verify-*` z ostatniej linii jego wyniku (`SKILLE VERIFY: …`, drukuje ją też brama `pre-push`) i wykonaj workflow opisany w tym skillu.
- Polecenia z linii `LICZY CI: …` przed nią liczy CI na tym SHA: lokalnie uruchamiasz je tylko do odtworzenia czerwonego kroku CI albo przy pracy nad jedną funkcją.
- Resztę workflow (osąd modelu i zrzutów, prawdziwe Wzorce, Excel na Macu) robisz sam, a sekcja `What CI runs and what stays local` w `SKILL.md` skilla mówi, co to jest.
- `VERIFY SKIP` (kod 3) znaczy, że skill nic nie sprawdził, więc nie jest dowodem.

## Nowy albo zmieniony skill

- Skrypt mutacji skilla nazwij `scripts/check_<co>_mutations.py` i zostaw w nim tylko tabelę `Mutation` dla `check_all` z `tools/mutacje.py`; CI uruchamia go sam przez `tools/mutacje_skilli.py`.
  Człon `<co>` odróżnia go od skryptów innych skilli, bo mypy odrzuca dwa moduły o tej samej nazwie.
  Jego wywołanie w `SKILL.md` pilnuje, żeby nie wypadł z CI po zmianie nazwy albo usunięciu.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Skille projektu, także nowe `verify-*` z `/pstack:create-verification-skill`, leżą tylko w `.agents/skills/<skill>/SKILL.md`, nie w `.claude/skills/` ani `.cursor/skills/`. | `tests/test_miejsce_skilli.py` |
| Każdy skill `verify-*` deklaruje we frontmatterze `SKILL.md` klucz `pilnuje:` z globami ścieżek, przy których zmianie obowiązuje, a `tools/skille_dla_zmiany.py` i wybór mutacji w CI czytają ten sam klucz. | `tests/test_skille_dla_zmiany.py::test_kazdy_skill_verify_deklaruje_pilnuje` |
| `AGENTS.md`, `docs/agents/pr-i-ci.md` i ten plik nie wymieniają skilli `verify-*` z nazwy: routing żyje w ich `pilnuje:`, a te pliki odsyłają do `tools/skille_dla_zmiany.py`. | `tests/test_skille_dla_zmiany.py::test_agents_md_nie_wymienia_skilli_verify` |
| `SKILL.md` każe uruchamiać lokalnie polecenie, które liczy CI (polecenie `ci:` z frontmattera skilla, skrypt `check_*_mutations.py`, polecenie skilla w kroku `ci.yml`), tylko do odtworzenia czerwonego kroku CI albo przy pracy nad jedną funkcją, a nie przed pushem. | `tests/test_skille_dla_zmiany.py::test_skill_nie_kaze_uruchamiac_przed_pushem_tego_co_liczy_ci` |
| Skill, którego polecenia liczy CI, dalej obowiązuje dla zmiany (`tools/skille_dla_zmiany.py` wymienia go w `SKILLE VERIFY`, a jego polecenia z CI w `LICZY CI`), a jego `SKILL.md` ma sekcję `What CI runs and what stays local`, która mówi, co z workflow zostaje lokalnie. | `tests/test_skille_dla_zmiany.py::test_skill_z_poleceniami_w_ci_zostaje_w_skillach_verify_a_liczy_ci_wymienia_jego_polecenia` i `::test_skill_z_poleceniami_w_ci_mowi_co_liczy_ci_a_co_zostaje_lokalnie` |
| Skrypt skilla `verify-*` bierze `--root`, `--run-dir` i `--variant` tylko z `Parser` w [`tools/skrypt_skilla.py`](../../tools/skrypt_skilla.py), a sprzątanie usuwa tylko katalog runu ze znacznikiem `.katalog-runu`. | `tests/test_wywolanie_skryptow_skilli.py` |
| Mapa funkcji skilla `verify-*` (`features/`) zgadza się w obie strony z jego kodem i `SKILL.md`: każdy plik funkcji ma link w `features/README.md` i nagłówki H2 z szablonu, a każda funkcja ze skryptów skilla ma plik w mapie i wpis `--feature` w `SKILL.md`. | `tests/test_mapy_funkcji.py` |
| Zdanie skilla `verify-*` o kodzie, środowisku albo modelu (uprawnienie, plik ignorowany przez Git, straż w modelu TLA+) stoi na przebiegu, który mógł je obalić (bez uprawnienia, na tym pliku, bez tej straży), straż modelu ma odpowiednik w kodzie, a zdanie, którego nie dało się obalić, skill nazywa niesprawdzonym. | nic: decyduje osąd (werdykty FAIL #370, #376 i #378 z 2026-10-24) |
