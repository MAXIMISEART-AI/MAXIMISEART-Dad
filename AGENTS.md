# Agent Router

- Worktree: zanim uruchomisz Pythona, utwórz własne `.venv` przez `python3 tools/setup_worktree.py` (Windows: `py -3`); `.venv` głównego checkoutu sprawdza kod `main`.
- Issue N: przed startem uruchom `tools/praca_w_toku.py --issue N`. Gdy issue dotyczy gałęzi otwartego PR albo ktoś ma już na nim commity, poprawka należy do właściciela tej gałęzi: powiedz o tym użytkownikowi i zostaw ją jemu.
- Po każdej zmianie uruchom `.venv/bin/python tools/szybko.py` (Windows: `py -3 tools/szybko.py`), na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`. Co sprawdza, a co zostawia CI, mówi jego `--help`.
- Kod i testy: zanim napiszesz albo zrecenzujesz kod (także w `tools/`, `frontend/` i skryptach skilli) albo test, przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Skille: przeczytaj [`docs/agents/skille.md`](docs/agents/skille.md) przed pushem i przed utworzeniem albo zmianą skilla.
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues i specyfikacje: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- Triage: użyj [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

## PR: od pushu do merge'a

- Dziecko `delegate_task` kończy zadanie na pushu i utworzeniu PR, a zwraca URL PR i pełny SHA HEAD. Rodzic wywołuje `watch_pull_request` i kończy turę, a T3 budzi go po końcu CI.
- Przegląd PR zlecaj zaraz po pushu, równolegle z CI.
  Change mutations startują dopiero po zielonym `Required CI status`, więc recenzent pisze werdykt po ich końcu, a gdy dał `PASS` wcześniej i mutacje przeżyły, uzupełnia go nowym `PASS` z liniami `MUTACJA`.
- PR jest gotowy do merge'a, gdy na HEAD PR zielony jest `Required CI status` (i każdy inny workflow niż `CI`, który biegnie na PR), Change mutations się skończyły, przeszły skille `verify-*` z linii `SKILLE VERIFY` narzędzia `tools/skille_dla_zmiany.py` i jest `PASS` niezależnego recenzenta.
  Skille `verify-*` przeszły, gdy ich polecenia z linii `LICZY CI` przechodzą w zielonym CI, a resztę ich workflow agent wykonał i skończył bez FAIL.
  `PASS` ma dla każdej przeżytej mutacji linię `MUTACJA <id> | test dodany` albo `MUTACJA <id> | nie warto, bo <powód>`, a `<id>` to `<plik>:<linia> <opis>` z linii `NIEWYKRYTA` zadania Change mutations.
  Czerwone Change mutations z omówionymi przeżytymi mutacjami gotowości nie odbierają, a pilnuje tego `tools/scal_pr.py`.
  `SZYBKO OK` i `CI LOKALNIE OK` gotowości nie dają.
- Merge PR: tylko `.venv/bin/python tools/scal_pr.py N` (Windows: `py -3 tools/scal_pr.py N`), nigdy gołe `gh pr merge`; warunki scalenia i postać werdyktów podaje jego `--help`. Zgoda to komentarz albo recenzja niezależnego recenzenta, której pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>`.
- CI i gałąź: przeczytaj [`docs/agents/pr-i-ci.md`](docs/agents/pr-i-ci.md), zanim uruchomisz lokalnie zadanie CI albo zrobisz rebase lub merge `main` do gałęzi, i gdy zadanie CI padło, status `scalenie z main` nie jest zielony, `main` jest czerwony albo chcesz sprawdzić każdy commit gałęzi.

## Reguły i co ich pilnuje

Gdy operator Cię poprawi, dopisz regułę z jej strażnikiem do tabeli, do której należy: regułę o tym, jak pisać kod i testy, do tabeli jej sekcji w [`CODING_STANDARDS.md`](CODING_STANDARDS.md) (po angielsku), regułę procesu gałęzi z [`docs/agents/pr-i-ci.md`](docs/agents/pr-i-ci.md) albo [`docs/agents/skille.md`](docs/agents/skille.md) do tabeli tego pliku, a pozostałą regułę procesu do tabeli niżej.
Jeśli reguła już tam była, a nic jej nie pilnowało, to błąd się powtórzył: w tej samej zmianie dodaj sprawdzenie, które go łapie.
Wyjątek zapisz na linii, której dotyczy, z powodem, terminem i zgodą Maksa (wzór: `KNOWN` w `tests/test_uszkodzone_wejscia.py`).
Szczegóły strażnika, jego wyjątki i granicę (co łapie tylko przegląd) opisuje jego docstring.

| Reguła | Co jej pilnuje |
|---|---|
| Push agenta, który wysyła HEAD, przechodzi tylko wtedy, gdy ruff i mypy dla obu systemów nie zgłaszają błędów w drzewie roboczym. | brama `tools/hooks/pre-push`, `tests/test_brama_pre_push.py` |
| Tag Wydania `v*` i GitHub Release tworzy tylko narzędzie Wydań (#316), które ustawia `MAXIMISEART_WYDANIE=1` (ADR 0014), a agent nie robi tego ani `git push`, także z `--no-verify`, ani `gh release create`, `gh api` czy stroną GitHuba. | brama `tools/hooks/pre-push`, `tests/test_brama_pre_push.py` |
| Na własny proces agent czeka na powiadomienie `run_in_background`, a na CI rodzic przez `watch_pull_request`. | hook `PreToolUse` `tools/hooks/czekanie.py` (`.claude/settings.json`), `tests/test_czekanie.py` |
| Agent w trybie bypass nie czeka na zgodę człowieka na polecenie Basha: gdy Claude Code by o nią zapytał (kontrola `rm`, której nie zdejmuje `permissions.allow`, albo reguła `permissions.ask`), od razu oddaje mu odmowę z poprawką, którą podaje komunikat hooka; po aktualizacji Claude Code uruchom `tools/wyrocznia_zgody.py`. | hook `PermissionRequest` `tools/hooks/zgoda.py` (`.claude/settings.json`), `tests/test_zgoda.py` |
| W `AGENTS.md`, `CODING_STANDARDS.md`, `docs/agents/pr-i-ci.md` i `docs/agents/skille.md` łam linię prozy tylko na końcu zdania, żeby zmiana słowa zmieniała jedną linię, a nie cały akapit. | `tests/test_dokumenty_regul.py` |
