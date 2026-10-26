# CI na PR

Kiedy PR jest gotowy i jak go scalić, mówi sekcja `PR: od pushu do merge'a` w [`AGENTS.md`](../../AGENTS.md).

## Zadanie CI padło

- Porażkę zadania odtwarzasz przez `.venv/bin/python tools/ci_lokalnie.py --tylko <zadanie>` (Windows: `py -3 tools/ci_lokalnie.py --tylko <zadanie>`).
- Ciężkie zadania (`change-mutations`, `mutations`) liczy GitHub po pushu, w częściach, a ich stan sprawdzasz przez `tools/praca_w_toku.py` albo `gh pr checks`.
  `change-mutations` startuje tylko na PR, który ma mutacje zmiany, a `mutations` (Mutation checks) tylko z krokami skilli, które wybrał plan runu.
  Część skryptu mutacji z planu (`#k/n` w nazwie jednostki) odtwarzasz przez `MUTACJE_CZESC=k/n` w środowisku polecenia tego skryptu.
  Porażkę z runu Actions tej gałęzi odtwarzasz przez `.venv/bin/python tools/mutacje_zmiany.py --odtwarzam <id albo URL runu>` (Windows: `py -3 tools/mutacje_zmiany.py --odtwarzam …`), na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`.

## Plan runu, zadania pytest i Mutation checks

- Ile zadań pytest startuje i które pliki testów (albo udziały długiego pliku) bierze każde, ustala zadanie `Plan CI` (`tools/plan_ci.py`) z czasów ostatnich zielonych runów `main`, a E2E i straż czasu dokłada do zadań Windows.
- Kroki skilli (podstawę `ci:` i każdy skrypt `check_*_mutations.py`) plan bierze z wyboru `tools/mutacje_skilli.py`: na PR tylko te, których werdykt mogą zmienić zmiany, a na pushu do `main` wszystkie.
- Plan dzieli je między zadania Mutation checks w tym samym limicie zadań runu i z tym samym celem ściany co pytest, a skrypt mutacji dłuższy niż zadanie dzieli na części, najwyżej po jednej na mutację.
- Podstawy `ci:` plan nie dzieli, więc linia każdego toru w planie nazywa najdłuższą jednostkę po podziale, poniżej której ściana zadania nie zejdzie.
- Chromium instaluje tylko zadanie Mutation checks z krokiem skilla, którego skrypty importują Playwright.
- Plan dla swojej gałęzi drukujesz przez `.venv/bin/python tools/plan_ci.py plan --baza origin/main` (Windows: `py -3 tools/plan_ci.py plan --baza origin/main`), z prognozą ściany każdego zadania.
- `Required CI status` czerwienieje także wtedy, gdy planu nie ma albo zadanie planu (pytest albo Mutation checks) nie zgłosiło w zapisie czasów ostatniej próby którejś swojej jednostki albo zgłosiło ją z porażką, a linia `REQUIRED FAIL` nazywa zadanie i jednostkę.
- Skrypt mutacji, którego wybór skilli by nie uruchomił (nazwa spoza wzorca, wskazany w `SKILL.md`, a usunięty), i zły klucz `ci:` plan zgłasza w `Required CI status` linią `REQUIRED FAIL | mutacje skilli: …`.
- Porażkę jednego zadania pytest odtwarzasz przez `tools/ci_lokalnie.py --tylko pytest` albo przez pytest na plikach tego zadania.
- Linia zadania w planie podaje liczbę jego plików i nazywa tylko udziały i kroki, a listę plików ma pole `jednostki` zadania w artefakcie `plan` runu (`gh run download <id runu> --name plan`).

## Status `scalenie z main`

- Status `scalenie z main` na HEAD PR mówi, czy scalenie PR z obecnym `main` przechodzi bez konfliktu, ruff i mypy dla obu systemów (`tools/scalenia_pr.py` w workflow `scalenia.yml`, po każdym pushu do `main`).
- Ruleset go nie wymaga, więc gotowość PR od niego nie zależy, choć `gh pr checks` kończy się kodem 1, gdy jest czerwony.
- `failure` znaczy, że PR trzeba zaktualizować z `origin/main` i poprawić, a opis statusu nazywa pliki z konfliktem albo kroki, które padły.
- `error` z „sam nie przechodzi” znaczy, że czerwony jest `main`, nie PR.
- Brak statusu znaczy, że `main` nie zmienił się od pushu PR albo przebieg jeszcze trwa.

## Czerwony `main`

- Czerwony `main` naprawia od razu osobny PR, a PR, nad którym pracujesz, zostaje przy swojej zmianie.

## Każdy commit gałęzi

- Każdy commit gałęzi sprawdzasz, gdy tego potrzebujesz (nic tego nie wymaga), przez `tools/ci_lokalnie.py --kazdy-commit`.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Rebase albo merge `main` do gałęzi robisz tylko przy konflikcie albo gdy `main` zmienił te same pliki co PR. | werdykt `AKTUALIZACJA` z `tools/praca_w_toku.py --aktualizacja`, drukowany też przez bramę `tools/hooks/pre-push`; `tests/test_praca_w_toku.py`, `tests/test_brama_pre_push.py` |
| Ciężkie zadania CI (`change-mutations`, `mutations`) liczy GitHub, a lokalnie biegną tylko do odtworzenia porażki z runu Actions tej gałęzi. | `tools/ciezkie_ci.py`, `tests/test_ciezkie_ci.py`, `tests/test_na_scalonych_pr.py` |
| Lista dłuższa niż `TARGETED` mutacji w `tools/mutacje.py` to ręczne `change-mutations`, więc poza CI biegnie tylko z tymi samymi wyjątkami, a skrypty mutacji skilli `verify-*` (`check_all`) nie mają tego limitu. | `tools/ciezkie_ci.py` (`TARGETED`), `tests/test_ciezkie_ci.py` |
