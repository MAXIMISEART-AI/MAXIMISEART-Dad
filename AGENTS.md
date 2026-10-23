# Agent Router

- Praca w git worktree: zanim uruchomisz Pythona, utwórz własne `.venv` przez `python3 tools/setup_worktree.py` (Windows: `py -3`); `.venv` głównego checkoutu sprawdza kod `main`.
- Przed startem issue N: uruchom `tools/praca_w_toku.py --issue N`. Gdy issue dotyczy gałęzi otwartego PR albo ktoś ma już na nim commity, poprawka należy do właściciela tej gałęzi: powiedz o tym użytkownikowi zamiast zaczynać równoległą poprawkę.
- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Implementacja i review: przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Weryfikacja end-to-end: przy zmianach w `tools/uruchom_proces.py`, `src/`, obsłudze skoroszytów, regułach bezpieczeństwa albo metrykach załaduj [`verify-rozliczenia`](.agents/skills/verify-rozliczenia/SKILL.md) i wykonaj opisany tam workflow.
- Excel: przy zmianach w zapisie albo odczycie skoroszytów, łączach zewnętrznych, Wyróżnieniach, Wzorcach albo Gotowości załaduj na Macu z Excelem [`verify-skoroszyty-w-excelu`](.agents/skills/verify-skoroszyty-w-excelu/SKILL.md).
- Publikacja plików okresu: przy zmianach w `write_period_files`, `_publish` albo `ensure_period_files_absent` (`src/rozliczenia/preparation_files.py`) załaduj [`verify-publikacja-plikow-okresu`](.agents/skills/verify-publikacja-plikow-okresu/SKILL.md).
- Aktualizacja narzędzia: przy zmianach w `ToolClone.update`, `_DadFiles`, `_roll_back` (`tool_update.py`), `ToolUpdates._update`/`_restart` (`tool_updates.py`) albo `restart_guardian.main` załaduj [`verify-aktualizacja-narzedzia`](.agents/skills/verify-aktualizacja-narzedzia/SKILL.md) (model TLA+).
- Jedno Uruchomienie naraz i zamknięcie Centrum: przy zmianach w `RunHost`/`_Run` (`src/rozliczenia/centrum/runs.py`), `Shutdown` (`shutdown.py`), `stop_when_asked` (`server.py`) albo przy nowej akcji, która nie może biec w trakcie Uruchomienia, załaduj [`verify-jedno-uruchomienie-naraz`](.agents/skills/verify-jedno-uruchomienie-naraz/SKILL.md).
- Kopia Wzorca rozliczenia pracownika: przy zmianach w `src/rozliczenia/template_copy.py`, `sheet_data.py`, `highlights.py`, `row_look.py` albo w `TemplateFile` (`src/rozliczenia/workbook_files.py`) załaduj [`verify-kopia-wzorca`](.agents/skills/verify-kopia-wzorca/SKILL.md).
- Centrum rozliczeń: przy zmianach w jego serwerze, frontendzie albo launcherze przeczytaj [ADR 0004](docs/adr/0004-centrum-rozliczen-adapter.md) i załaduj [`verify-centrum-rozliczen`](.agents/skills/verify-centrum-rozliczen/SKILL.md).
- Centrum na Windowsie u taty: przy zmianach w starcie (`launcher.py`, `platform.py`, `shortcut.py`, `run_centrum.py`, `install_centrum_shortcut.py`), oknach systemu, `restart_guardian.py`, `tool_update.py`/`tool_updates.py` albo `requirements.txt` załaduj [`verify-centrum-na-windowsie`](.agents/skills/verify-centrum-na-windowsie/SKILL.md) (runner Windows na GitHubie).
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Wydajność frontendu Centrum: przy zmianach, które mogą zmienić jego szybkość, zmierz przed i po funkcją [`wydajnosc`](.agents/skills/verify-centrum-rozliczen/features/wydajnosc.md) (`--feature wydajnosc`) i zaktualizuj baseline według jej opisu.
- Dowód, że test albo sprawdzenie gryzie: użyj [`tools/mutacje.py`](tools/mutacje.py). Sprawdzenie każdego commitu gałęzi, gdy go potrzebujesz (nic go nie wymaga): `tools/ci_lokalnie.py --kazdy-commit`. Nie pisz własnego silnika mutacji ani `git rebase --exec`.
- PR jest gotowy do merge'a, gdy CI na GitHubie jest zielone dla HEAD PR i przeszły skille `verify-*`, które ta lista wskazuje dla tej zmiany. `CI LOKALNIE OK` tego nie oznacza. Brama `pre-push` sprawdza push agenta tylko ruffem i mypy, a `tools/ci_lokalnie.py` służy do odtworzenia porażki z CI.
- Status `scalenie z main` na HEAD PR mówi, czy scalenie PR z obecnym `main` przechodzi bez konfliktu, ruff i mypy dla obu systemów (`tools/scalenia_pr.py` w workflow `scalenia.yml`, po każdym pushu do `main`).
  Ruleset go nie wymaga, więc gotowość PR od niego nie zależy.
  `failure` znaczy, że PR trzeba zaktualizować z `origin/main` i poprawić, a opis statusu nazywa pliki z konfliktem albo kroki, które padły.
  `error` z „sam nie przechodzi” znaczy, że czerwony jest `main`, nie PR.
  Brak statusu znaczy, że `main` nie zmienił się od pushu PR albo przebieg jeszcze trwa.
  `gh pr checks` kończy się kodem 1, gdy ten status jest czerwony, więc agent, który czeka na zielone CI, patrzy na `Required CI status`.
- Przegląd PR zlecaj zaraz po pushu, równolegle z CI.
- Rebase na `main` rób tylko przy konflikcie albo gdy `main` zmienił te same pliki co PR. Czerwony `main` naprawia od razu osobny PR, nie poprawka w PR, nad którym pracujesz.
- Skille projektu: trzymaj je w `.agents/skills/`, także nowe `verify-*` z `/pstack:create-verification-skill` (nie w `.claude/skills/` ani `.cursor/skills/`). Ich `scripts/**/*.py` sprawdzają ruff i mypy bez wpisu w `pyproject.toml`. Skrypt mutacji skilla nazwij `scripts/check_<co>_mutations.py` i zostaw w nim tylko tabelę `Mutation` dla `check_all` z `tools/mutacje.py`; CI uruchamia go sam przez `tools/mutacje_skilli.py`. Człon `<co>` odróżnia go od skryptów innych skilli, bo mypy odrzuca dwa moduły o tej samej nazwie. `check_all` kończy go linią `MUTACJE OK`, a jego wywołanie w `SKILL.md` pilnuje, żeby nie wypadł z CI po zmianie nazwy albo usunięciu.
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues i specyfikacje: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- Triage: użyj [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

## Reguły i co ich pilnuje

Gdy operator Cię poprawi, popraw błąd i dopisz tu regułę. Jeśli reguła już tu była, a nic jej nie pilnowało, to błąd się powtórzył: w tej samej zmianie dodaj sprawdzenie, które go łapie. Wyjątek zapisz na linii, której dotyczy, z powodem, terminem i zgodą Maksa (wzór: `KNOWN` w `tests/test_uszkodzone_wejscia.py`).

| Reguła | Co jej pilnuje |
|---|---|
| Plik albo folder taty w złym stanie (uszkodzony, z BOM, w UTF-16, bez dostępu) daje Komunikat, który go nazywa. Plik bez dostępu jest „niedostępny”, nie „uszkodzony”. Skoroszyt czytaj przez `_file_bytes` (`workbook_files.py`), a folder okresu przez `reading` (`period_folder.py`). | `tests/test_uszkodzone_wejscia.py`: każda kombinacja pliku, uszkodzenia i operacji kontraktu Centrum. Nowa operacja, której nie ma w `ENTRIES` ani w `NOT_SWEPT` (z powodem), wywraca test |
| Skoroszyt zapisują tylko `workbook_files.py`, `template_copy.py` i `row_look.py`. | `tests/test_jeden_zapis_skoroszytu.py`: przypisanie wartości, wyglądu, hiperłącza albo autofiltru i `.save` w `src/` poza tymi modułami; `.save`, które nie zapisuje skoroszytu, ma wpis w `NOT_WORKBOOK_SAVES` |
| Push agenta, który wysyła HEAD, przechodzi tylko wtedy, gdy ruff i mypy dla obu systemów nie zgłaszają błędów w drzewie roboczym. | brama `tools/hooks/pre-push` z krokami z `tools/ci_lokalnie.py`; jej test `tests/test_brama_pre_push.py` biegnie w CI w zadaniu `pytest (Python 3.14, Linux)` |
| System sprawdzaj przez `sys.platform == "win32"`. | ruff `TID251` (`pyproject.toml`) oraz mypy dla obu systemów w `tools/ci_lokalnie.py` |
| Polecenie narzędzia z `tools/`, które trwa albo uruchamia własne procesy, uruchamiaj przez `potomne.run`, a kopię commitu twórz przez `potomne.commit_copy` ([`tools/potomne.py`](tools/potomne.py)): giną razem z narzędziem, także zabitym przez SIGKILL. | `tests/test_potomne.py`: testy struktury odrzucają w `tools/` poza `potomne.py` `killpg`, `taskkill`, `start_new_session`, grupy procesów, `CreateJobObject` i `git worktree add` oraz każde uruchomienie przez zwykłe `subprocess` poza `gh`, `ps` i `git` z podpoleceniem z `FAST_GIT` (także przez funkcję, która przekazuje gitowi swoje `*args`) |
| Numer ADR jest unikalny i zgadza się z nagłówkiem pliku. | `tests/test_adr.py` |
| W `AGENTS.md` i `CODING_STANDARDS.md` łam linię prozy tylko na końcu zdania, żeby zmiana słowa zmieniała jedną linię, a nie cały akapit. | `tests/test_dokumenty_regul.py`: linia prozy, po której następna ciągnie ten sam akapit, kończy się na `.`, `!` albo `?`; bloki kodu, tabele i nagłówki są pominięte |
| Pojęcie wycofane przez ADR (CLI, terminal, Rich, `run.py`, launchery `.cmd` taty) nie wraca. | `tests/test_wycofane_pojecia.py`: `src/`, `frontend/src`, skille, `docs/`, `README.md`, `requirements.txt`; zdanie o historii ma wpis w `HISTORY`, a starszy ADR jest historią, gdy jego Status prowadzi do ADR-u, który pojęcie wycofał |
| Moduł testów importuje pomocniki tylko z `tests/fixtures`. | `tests/test_struktura_testow.py` |
| Po zmianie modeli serwera wygeneruj kontrakt Centrum na nowo. | zadanie CI `Frontend`, krok „Require the committed contract and build to be fresh” |
| Opis PR obiecuje tylko tyle, ile potwierdzają mutacje z `tools/mutacje.py`. | nic: decyduje osąd (dwa przeglądy z 2026-10-21 i 2026-10-22) |
| Test czeka na stan Centrum albo mierzy czas zegarem testu, nigdy stałą liczbą milisekund. | `tests/test_struktura_testow.py`: `time.sleep` w testach tylko w pętli, która pyta `time.monotonic()` o termin, w lambdzie albo funkcji wewnętrznej podróbki albo w teście z `SIMULATED_TIME` z powodem |
