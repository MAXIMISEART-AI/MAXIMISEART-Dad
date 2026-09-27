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
