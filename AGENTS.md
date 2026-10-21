# Agent Router

- Praca w git worktree: zanim uruchomisz Pythona, utwórz własne `.venv` przez `python3 tools/setup_worktree.py` (Windows: `py -3`); `.venv` głównego checkoutu sprawdza kod `main`.
- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Implementacja i review: przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Weryfikacja end-to-end: przy zmianach w `run.py`, `src/`, obsłudze skoroszytów, regułach bezpieczeństwa albo metrykach załaduj [`verify-rozliczenia`](.agents/skills/verify-rozliczenia/SKILL.md) i wykonaj opisany tam workflow.
- Publikacja plików okresu: przy zmianach w `write_period_files`, `_publish` albo `ensure_period_files_absent` (`src/rozliczenia/preparation_files.py`) załaduj [`verify-publikacja-plikow-okresu`](.agents/skills/verify-publikacja-plikow-okresu/SKILL.md).
- Aktualizacja narzędzia: przy zmianach w `ToolClone.update`, `_DadFiles`, `_roll_back` (`tool_update.py`), `ToolUpdates._update`/`_restart` (`tool_updates.py`) albo `restart_guardian.main` załaduj [`verify-aktualizacja-narzedzia`](.agents/skills/verify-aktualizacja-narzedzia/SKILL.md) (model TLA+).
- Centrum rozliczeń: przy zmianach w jego serwerze, frontendzie albo launcherze przeczytaj [ADR 0004](docs/adr/0004-centrum-rozliczen-adapter.md) i załaduj [`verify-centrum-rozliczen`](.agents/skills/verify-centrum-rozliczen/SKILL.md).
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Wydajność frontendu Centrum: przy zmianach, które mogą zmienić jego szybkość, zmierz przed i po funkcją [`wydajnosc`](.agents/skills/verify-centrum-rozliczen/features/wydajnosc.md) (`--feature wydajnosc`) i zaktualizuj baseline według jej opisu.
- Skille projektu: trzymaj je w `.agents/skills/`, także nowe `verify-*` z `/pstack:create-verification-skill` (nie w `.claude/skills/` ani `.cursor/skills/`).
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues i specyfikacje: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- Triage: użyj [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).
