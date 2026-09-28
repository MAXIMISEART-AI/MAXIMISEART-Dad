# MAXIMISEART-Dad

## Zakres

Lokalna automatyzacja końcowego kroku rozliczenia tygodniowego w Excelu:
`Rozliczenie {okres} - zbiorcze.xlsx` -> osobne szablony pracowników.

## Reguły bezpieczeństwa

- Proces działa lokalnie na komputerze taty.
- Nie używa AI, zewnętrznych API ani usług analitycznych.
- Źródłem jest wyłącznie plik zbiorczy; pliki `Rozliczenie wew.` są poza zakresem.
- Nie wolno zapisywać adresów klientów, numerów zleceń ani treści wierszy w logach.
- Kopiowane są tylko wartości `A:AT` od wiersza 18.
- Formuły, stawki i formatowanie szablonu pozostają własnością pliku docelowego.
- Przy zapisie trzeba zachować całe `xl/externalLinks/*`; szablony zawierają odwołania do zewnętrznego skoroszytu.
- Plik docelowy z istniejącymi danymi nie jest nadpisywany.
- Nieznany identyfikator wykonawcy jest pomijany i zgłaszany.
- Placeholder bez nazwy wykonawcy jest pomijany.
- Przykładowe arkusze z danymi nie są commitowane.

## Uruchamianie

Ten sam silnik ma dwie ścieżki:

1. `Utwórz rozliczenia.cmd` — uruchomienie lokalnego procesu z wyborem pliku.
2. Moduł `deploy/AutomatyzacjaRozliczen.bas` — przycisk w osobnym pliku `.xlsm`.

`tools/repair_external_links.py` służy do jednorazowej naprawy plików zapisanych
starszą wersją silnika. Przed naprawą tworzy kopie zapasowe.

## Weryfikacja

Zmiany muszą być sprawdzone testami na syntetycznych arkuszach. Przed użyciem
na prawdziwych plikach trzeba wykonać `--dry-run`.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues for MAXIMISEART-AI/MAXIMISEART-Dad. See `docs/agents/issue-tracker.md`.

### Triage labels

This repo uses the default five triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo with `CONTEXT.md` at the root and ADRs under `docs/adr/`. See `docs/agents/domain.md`.

## Coding standards

During code review, read `CODING_STANDARDS.md` for project-specific judgement calls about domain vocabulary, module depth, error ownership, and test surfaces.
