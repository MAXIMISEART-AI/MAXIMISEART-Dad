# CI na PR

Kiedy PR jest gotowy i jak go scalić, mówi sekcja `PR: od pushu do merge'a` w [`AGENTS.md`](../../AGENTS.md).

## Zadanie CI padło

- Porażkę zadania odtwarzasz przez `.venv/bin/python tools/ci_lokalnie.py --tylko <zadanie>` (Windows: `py -3 tools/ci_lokalnie.py --tylko <zadanie>`).
- Ciężkie zadania (`change-mutations`, `mutations`) liczy GitHub po pushu, w trzech częściach każde, a ich stan sprawdzasz przez `tools/praca_w_toku.py` albo `gh pr checks`.
  Lokalnie uruchamiasz je tylko do odtworzenia porażki z runu Actions tej gałęzi, w którym to zadanie padło: `.venv/bin/python tools/mutacje_zmiany.py --odtwarzam <id albo URL runu>`, na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`.
  Inne przebiegi odrzuca `tools/ciezkie_ci.py`.

## Status `scalenie z main`

- Status `scalenie z main` na HEAD PR mówi, czy scalenie PR z obecnym `main` przechodzi bez konfliktu, ruff i mypy dla obu systemów (`tools/scalenia_pr.py` w workflow `scalenia.yml`, po każdym pushu do `main`).
- Ruleset go nie wymaga, a `gh pr checks` kończy się kodem 1, gdy jest czerwony, więc o gotowości mówi `Required CI status`.
- `failure` znaczy, że PR trzeba zaktualizować z `origin/main` i poprawić, a opis statusu nazywa pliki z konfliktem albo kroki, które padły.
- `error` z „sam nie przechodzi” znaczy, że czerwony jest `main`, nie PR.
- Brak statusu znaczy, że `main` nie zmienił się od pushu PR albo przebieg jeszcze trwa.

## Aktualizacja gałęzi z `main`

- O rebase albo merge `main` do gałęzi rozstrzyga werdykt `AKTUALIZACJA` z `tools/praca_w_toku.py --aktualizacja`, który drukuje też brama `pre-push`.
- Czerwony `main` naprawia od razu osobny PR, a PR, nad którym pracujesz, zostaje przy swojej zmianie.

## Każdy commit gałęzi

- Każdy commit gałęzi sprawdzasz, gdy tego potrzebujesz (nic tego nie wymaga), przez `tools/ci_lokalnie.py --kazdy-commit`.
