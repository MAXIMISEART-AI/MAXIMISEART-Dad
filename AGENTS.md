# Agent Router

- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Implementacja i review: przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Weryfikacja end-to-end: przy zmianach w `run.py`, `src/`, obsłudze skoroszytów, regułach bezpieczeństwa, metrykach albo launcherach CMD załaduj [`verify-rozliczenia`](.agents/skills/verify-rozliczenia/SKILL.md) i wykonaj opisany tam workflow.
- Publikacja plików okresu: przy zmianach w `write_period_files`, `_publish` albo `ensure_period_files_absent` (`src/rozliczenia/preparation_files.py`) załaduj [`verify-publikacja-plikow-okresu`](.agents/skills/verify-publikacja-plikow-okresu/SKILL.md).
- Centrum rozliczeń: przy zmianach w jego serwerze, frontendzie albo launcherze przeczytaj [ADR 0004](docs/adr/0004-centrum-rozliczen-adapter.md) i załaduj [`verify-centrum-rozliczen`](.agents/skills/verify-centrum-rozliczen/SKILL.md).
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues i specyfikacje: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- Triage: użyj [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).
