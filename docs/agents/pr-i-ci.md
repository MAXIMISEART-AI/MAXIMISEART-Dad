# CI na PR

Kiedy PR jest gotowy i jak go scalić, mówi sekcja `PR: od pushu do merge'a` w [`AGENTS.md`](../../AGENTS.md).
Dlaczego PR dostaje mniej sprawdzeń niż `main`, mówi [ADR 0020](../adr/0020-ci-w-poziomach.md).

## Co biegnie na PR

- `Required CI status` przechodzi, gdy przeszły `Ruff, mypy, Frontend`, `Plan CI` i każde zadanie pytest i Mutation checks z planu runu.
- `Ruff, mypy, Frontend` biegnie na każdym PR.
- pytest biegnie na torach Windows 3.11 i Linux 3.14.
  Każdy tor bierze pliki, które `tools/szybko.py` wybiera dla zmiany od bazy (bez jego budżetu czasu), i testy `szybko.STRUCTURE`.
  Lokalne `tools/szybko.py` uruchamia z tego wyboru tylko pliki, które mieszczą się w jego budżecie, a resztę wypisuje jako „zostawione CI”.
- Zmiana pliku z `szybko.FULL` albo pod `.github/workflows/` wybiera wszystkie pliki testów, E2E i straż czasu.
- E2E biegnie na Windows 3.11 przy zmianie pod `src/`, a straż czasu przy zmianie w domknięciu jej skryptów (`STRAZ` w `tools/plan_ci.py`).
- Mutation checks biegną tylko wtedy, gdy `tools/mutacje_skilli.py` wybrał dla zmiany krok skilla.
  Kiedy wybiera krok, mówi [`docs/agents/skille.md`](skille.md).
- Change mutations startują po zielonym `Required CI status`, więc go nie blokują (sekcja `Change mutations` niżej).
- Nowy push do PR anuluje run jego starszego commitu.
- Co biegnie na Twojej gałęzi, drukuje `.venv/bin/python tools/plan_ci.py plan --baza origin/main` (Windows: `py -3 tools/plan_ci.py plan --baza origin/main`).
  Linia `PLAN CI` podaje źródło plików (`wybór <n> plików` albo `FULL (<pliki>)`) i liczbę mutacji zmiany, a linie `WYBRANY` i `POMINIĘTY` kroki skilli z powodem.

## Pełne CI na `main`

- Push do `main` uruchamia każdy plik testów na Windows 3.11, Windows 3.14 i Linux 3.14, E2E na obu torach Windows, straż czasu na Windows 3.14 i wszystkie kroki skilli.
- Change mutations na `main` nie biegną, bo mutują linie zmienione przez PR.
- Trwający run `main` kończy się, a nowy merge podmienia tylko run, który czeka.

## Change mutations

- Startują po zielonym `Required CI status`, w trzech częściach, gdy PR zmienia linie plików `src/**/*.py`, które `tools/mutacje_zmiany.py` mutuje, albo zmieniony plik ma wyjątek `# mutacje-zmiany:` w złej postaci.
- Ich wynik nie zmienia `Required CI status`, ale `tools/scal_pr.py` nie scala PR, dopóki trwają.
- Gdy któraś mutacja przeżyła, `tools/scal_pr.py` scala PR dopiero wtedy, gdy `PASS` omawia ją w linii `MUTACJA`, w postaci z [`AGENTS.md`](../../AGENTS.md).
  Przeżyte mutacje części są w liniach `NIEWYKRYTA` jej zadania i w artefakcie `mutacje-zmiany-<k>` runu.

## Zadanie CI padło

- Porażkę zadania odtwarzasz przez `.venv/bin/python tools/ci_lokalnie.py --tylko <zadanie>` (Windows: `py -3 tools/ci_lokalnie.py --tylko <zadanie>`).
- Ciężkie zadania (`change-mutations`, `mutations`) liczy GitHub po pushu, w częściach, a ich stan sprawdzasz przez `tools/praca_w_toku.py` albo `gh pr checks`.
  Część skryptu mutacji z planu (`#k/n` w nazwie jednostki) odtwarzasz przez `MUTACJE_CZESC=k/n` w środowisku polecenia tego skryptu.
  Porażkę z runu Actions tej gałęzi odtwarzasz przez `.venv/bin/python tools/mutacje_zmiany.py --odtwarzam <id albo URL runu>` (Windows: `py -3 tools/mutacje_zmiany.py --odtwarzam …`), na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`.

## Plan runu, zadania pytest i Mutation checks

- Ile zadań pytest startuje na każdym torze i które pliki testów (albo udziały długiego pliku) bierze każde, ustala zadanie `Plan CI` (`tools/plan_ci.py`) z czasów ostatnich zielonych runów `main`, a E2E i straż czasu dokłada do zadań Windows.
- Plan dzieli kroki skilli (podstawę `ci:` i każdy skrypt `check_*_mutations.py`) między zadania Mutation checks w tym samym limicie zadań runu i z tym samym celem ściany co pytest, a skrypt mutacji dłuższy niż zadanie dzieli na części, najwyżej po jednej na mutację.
- Podstawy `ci:` plan nie dzieli, więc linia każdego toru w planie nazywa najdłuższą jednostkę po podziale, poniżej której ściana zadania nie zejdzie.
- Chromium instaluje tylko zadanie Mutation checks z krokiem skilla, którego skrypty importują Playwright.
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

- Czerwony `main` nie blokuje merge'ów, a naprawia go od razu osobny PR.
  PR, nad którym pracujesz, zostaje przy swojej zmianie.

## Każdy commit gałęzi

- Każdy commit gałęzi sprawdzasz, gdy tego potrzebujesz (nic tego nie wymaga), przez `tools/ci_lokalnie.py --kazdy-commit`.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Rebase albo merge `main` do gałęzi robisz tylko przy konflikcie albo gdy `main` zmienił te same pliki co PR. | werdykt `AKTUALIZACJA` z `tools/praca_w_toku.py --aktualizacja`, drukowany też przez bramę `tools/hooks/pre-push`; `tests/test_praca_w_toku.py`, `tests/test_brama_pre_push.py` |
| Ciężkie zadania CI (`change-mutations`, `mutations`) liczy GitHub, a lokalnie biegną tylko do odtworzenia porażki z runu Actions tej gałęzi. | `tools/ciezkie_ci.py`, `tests/test_ciezkie_ci.py`, `tests/test_na_scalonych_pr.py` |
| Lista dłuższa niż `TARGETED` mutacji w `tools/mutacje.py` to ręczne `change-mutations`, więc poza CI biegnie tylko z tymi samymi wyjątkami, a skrypty mutacji skilli `verify-*` (`check_all`) nie mają tego limitu. | `tools/ciezkie_ci.py` (`TARGETED`), `tests/test_ciezkie_ci.py` |
| Bramka PR uruchamia pytest na Windows 3.11 i Linux 3.14 na wyborze `tools/szybko.py` dla zmiany, a zmiana pliku z `szybko.FULL` albo pod `.github/workflows/` wybiera wszystkie pliki, E2E i straż czasu. | `tests/test_plan_ci.py::test_bramka_pr_biegnie_na_windows_311_i_linuksie_z_wyborem_szybko_a_e2e_i_straz_czasu_tylko_przy_ich_zmianie` |
| Do bramki PR dokładasz tylko to, co złapałoby defekt, który przez nią przeszedł, z dowodem z backtestu, a plan wzorcowych PR-ów L i C ponad limit testów, zadań albo prognozy ściany to decyzja Maksa. | `tests/test_ksztalt_bramki.py` |
| Trwający run `main` kończy się, a nowy push do PR anuluje run jego starszego commitu. | `tests/test_zadania_ci.py::test_push_do_main_nie_anuluje_trwajacego_runu_a_nowy_push_pr_anuluje_stary` |
| `Required CI status` biegnie także w anulowanym runie, bo pominięty wymagany check przepuszcza merge. | `tests/test_zadania_ci.py::test_required_biegnie_takze_w_anulowanym_runie_bo_pominiety_wymagany_check_przepuszcza_merge` |
| Change mutations startują po zielonym `Required CI status` i go nie blokują, a `tools/scal_pr.py` nie scala PR, dopóki trwają. | `tests/test_zadania_ci.py::test_required_czeka_na_kazde_zadanie_bramki_a_change_mutations_startuja_po_zielonym_required_z_mutacjami_planu`, `tests/test_scal_pr.py::test_change_mutations_po_zielonym_required_musza_sie_skonczyc_a_pass_omawia_kazda_przezyta` |
