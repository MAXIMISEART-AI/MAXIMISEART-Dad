# Agent Router

- Worktree: zanim uruchomisz Pythona, utwórz własne `.venv` przez `python3 tools/setup_worktree.py` (Windows: `py -3`); `.venv` głównego checkoutu sprawdza kod `main`.
- Issue N: przed startem uruchom `tools/praca_w_toku.py --issue N`. Gdy issue dotyczy gałęzi otwartego PR albo ktoś ma już na nim commity, poprawka należy do właściciela tej gałęzi: powiedz o tym użytkownikowi i zostaw ją jemu.
- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Implementacja i review: przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Po każdej zmianie uruchom `.venv/bin/python tools/szybko.py` (Windows: `py -3 tools/szybko.py`), na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`. Co sprawdza, a co zostawia CI, mówi jego `--help`.
- Skille: przeczytaj [`docs/agents/skille.md`](docs/agents/skille.md) przed pushem i przed utworzeniem albo zmianą skilla.
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues i specyfikacje: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- Triage: użyj [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

## PR: od pushu do merge'a

- Dziecko `delegate_task` kończy zadanie na pushu i utworzeniu PR, a zwraca URL PR i pełny SHA HEAD. Rodzic wywołuje `watch_pull_request` i kończy turę, a T3 budzi go po końcu CI.
- Przegląd PR zlecaj zaraz po pushu, równolegle z CI.
- PR jest gotowy do merge'a, gdy `Required CI status` na GitHubie jest zielony dla HEAD PR, a agent wykonał workflow skilli `verify-*` z linii `SKILLE VERIFY` narzędzia `tools/skille_dla_zmiany.py`. `SZYBKO OK` i `CI LOKALNIE OK` gotowości nie dają.
- Merge PR: tylko `.venv/bin/python tools/scal_pr.py N` (Windows: `py -3 tools/scal_pr.py N`), nigdy gołe `gh pr merge`; warunki scalenia i postać werdyktów podaje jego `--help`. Zgoda to komentarz albo recenzja niezależnego recenzenta, której pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>`.
- CI na PR: przeczytaj [`docs/agents/pr-i-ci.md`](docs/agents/pr-i-ci.md), gdy zadanie CI padło, status `scalenie z main` nie jest zielony, werdykt `AKTUALIZACJA` mówi `potrzebna`, `main` jest czerwony albo chcesz sprawdzić każdy commit gałęzi.

## Reguły i co ich pilnuje

Gdy operator Cię poprawi, dopisz regułę do tej tabeli, a regułę o skillach do tabeli w [`docs/agents/skille.md`](docs/agents/skille.md). Jeśli reguła już tam była, a nic jej nie pilnowało, to błąd się powtórzył: w tej samej zmianie dodaj sprawdzenie, które go łapie. Wyjątek zapisz na linii, której dotyczy, z powodem, terminem i zgodą Maksa (wzór: `KNOWN` w `tests/test_uszkodzone_wejscia.py`). Szczegóły strażnika, jego wyjątki i granicę (co łapie tylko przegląd) opisuje jego docstring.

### Pliki taty

| Reguła | Co jej pilnuje |
|---|---|
| Plik albo folder taty w złym stanie (uszkodzony, z BOM, w UTF-16, bez dostępu) daje Komunikat, który go nazywa, a plik bez dostępu jest w nim „niedostępny”, nie „uszkodzony”: skoroszyt czytaj przez `_file_bytes` (`workbook_files.py`), a folder okresu przez `reading` (`period_folder.py`). | `tests/test_uszkodzone_wejscia.py`, `tests/test_jeden_odczyt_skoroszytu.py` |
| Skoroszyt zapisują tylko `template_file.py`, `template_copy.py`, `row_look.py` i `workbook_save.py`. | `tests/test_jeden_zapis_skoroszytu.py` |

### Silnik i Centrum rozliczeń

| Reguła | Co jej pilnuje |
|---|---|
| Silnik (`src/rozliczenia/*.py`) nie importuje Centrum rozliczeń, moduły z `STDLIB_ONLY` przy wczytaniu importują tylko bibliotekę standardową i siebie nawzajem, a moduły kopii opiekuna ponownego startu (`_COPIED` w `restart_guardian.py`) tylko bibliotekę standardową i `_COPIED`. | `tests/test_granice_importow.py` |
| Silnik decyduje na faktach planu, nie na kodzie Komunikatu: plan procesu oddaje typowane fakty, a jedno miejsce na proces (`collective_preparation`, `engine`) tłumaczy je na ostrzeżenia, Zatrzymania, wynik i Decyzję taty. | `tests/test_decyzje_na_faktach.py` |
| Frontend łączy się z serwerem (`fetch`, `EventSource`, `WebSocket`, `XMLHttpRequest`, `sendBeacon`) i woła `JSON.parse` tylko w plikach z `NETWORK_FILES`, które parsują każdą odpowiedź serwera schematem z kontraktu. | `npm run rules` (reguła 3 w `frontend/scripts/rules.mjs`) w zadaniu CI `Ruff, mypy, Frontend` |
| Po zmianie modeli serwera, a także po scaleniu albo rebase, wygeneruj kontrakt i build Centrum na nowo (`npm run regen` we `frontend/`), bo sterownik `merge=wygenerowane` zostawia w nich wersję bieżącego HEAD. | krok „Require the committed contract and build to be fresh” zadania CI `Ruff, mypy, Frontend` |

### Testy

| Reguła | Co jej pilnuje |
|---|---|
| Każdą zmienioną linię `src/` pilnuje test, który pada, gdy ją zepsuć, a opis PR obiecuje tylko tyle, ile potwierdzają mutacje. | `tools/mutacje_zmiany.py` (zadanie CI `Change mutations`) |
| Moduł testów importuje pomocniki tylko z `tests/fixtures`. | `tests/test_struktura_testow.py` |
| Test czeka na stan Centrum albo mierzy czas zegarem testu, a czas kodu pod testem sprawdza równością na podróbce zegara `ManualClock` (`tests/fixtures/clock.py`), nigdy stałą liczbą milisekund. | `tests/test_struktura_testow.py` |
| Git w testach ma jedną konfigurację, tę samą na każdym komputerze: test buduje `env=` z `os.environ` bez podstawiania `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM`, konfigurację komputera z czymś więcej podstawia przez `computer_git_config` (`tests/fixtures/git_config.py`), a proces kodu narzędzia (`src/`) ma puste `user.name` i `user.email`, więc jego `git commit` pada jak u taty. | fixture `git_bez_konfiguracji_komputera` w `tests/conftest.py`, `tests/test_git_w_testach.py` |
| Skrypt narzędzia albo skilla uruchamiany osobnym procesem sam dopisuje `src` do `sys.path`, bo CI na Windows nie instaluje pakietu. | `tests/test_skrypty_bez_instalacji.py` |
| Test z tabeli reguł, który sprawdza całe repozytorium, biegnie przy każdym `tools/szybko.py`. | `tests/test_szybko.py` |

### Narzędzia, push i CI

| Reguła | Co jej pilnuje |
|---|---|
| Push agenta, który wysyła HEAD, przechodzi tylko wtedy, gdy ruff i mypy dla obu systemów nie zgłaszają błędów w drzewie roboczym. | brama `tools/hooks/pre-push`, `tests/test_brama_pre_push.py` |
| Tag Wydania `v*` i GitHub Release tworzy tylko narzędzie Wydań (#316), które ustawia `MAXIMISEART_WYDANIE=1` (ADR 0014), a agent nie robi tego ani `git push`, także z `--no-verify`, ani `gh release create`, `gh api` czy stroną GitHuba. | brama `tools/hooks/pre-push`, `tests/test_brama_pre_push.py` |
| Rebase albo merge `main` do gałęzi tylko przy konflikcie albo gdy `main` zmienił te same pliki co PR. | werdykt `AKTUALIZACJA` z `tools/praca_w_toku.py` i bramy `tools/hooks/pre-push`, `tests/test_praca_w_toku.py`, `tests/test_brama_pre_push.py` |
| Ciężkie zadania CI (`change-mutations`, `mutations`) liczy GitHub, a lokalnie biegną tylko do odtworzenia porażki z runu Actions tej gałęzi. | `tools/ciezkie_ci.py`, `tests/test_ciezkie_ci.py`, `tests/test_na_scalonych_pr.py` |
| Agent nie czeka blokująco: na CI czeka rodzic przez `watch_pull_request`, a na własny proces powiadomienie `run_in_background`. | hook `PreToolUse` `tools/hooks/czekanie.py` (`.claude/settings.json`), `tests/test_czekanie.py` |
| Polecenie narzędzia z `tools/`, które trwa albo uruchamia własne procesy, uruchamiaj przez `potomne.run`, a kopię commitu twórz przez `potomne.commit_copy` ([`tools/potomne.py`](tools/potomne.py)), bo giną razem z narzędziem, także zabitym przez SIGKILL. | `tests/test_potomne.py` |
| Pliki, które systemowy Python uruchamia przed `.venv` (lista w `per-file-target-version` w `pyproject.toml`), działają pod Pythonem 3.9 z macOS. | ruff `per-file-target-version`, `tests/test_systemowy_python.py` |
| System sprawdzaj przez `sys.platform == "win32"`. | ruff `TID251` (`pyproject.toml`), mypy dla obu systemów w `tools/ci_lokalnie.py` |

### Dokumenty

| Reguła | Co jej pilnuje |
|---|---|
| Numer ADR jest unikalny i zgadza się z nagłówkiem pliku. | `tests/test_adr.py` |
| W `AGENTS.md`, `CODING_STANDARDS.md`, `docs/agents/pr-i-ci.md` i `docs/agents/skille.md` łam linię prozy tylko na końcu zdania, żeby zmiana słowa zmieniała jedną linię, a nie cały akapit. | `tests/test_dokumenty_regul.py` |
| Pojęcie wycofane przez ADR (CLI, terminal, Rich, `run.py`, launchery `.cmd` taty) nie wraca. | `tests/test_wycofane_pojecia.py` |
