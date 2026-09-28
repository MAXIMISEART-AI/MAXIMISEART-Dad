# MAXIMISEART-Dad: rozliczenia pracowników

Lokalne narzędzie rozdzielające dane z pliku zbiorczego na osobne szablony
pracowników. Narzędzie nie używa AI ani zewnętrznych API.

## Reguły procesu

- Wejście: `Rozliczenie {okres} - zbiorcze.xlsx`.
- Folder wejścia ma nazwę identyczną jak `{okres}`.
- Wyjście: `Rozliczenie pracowników {okres}`.
- Placeholder `Rozliczenie {okres} -.xlsx` jest pomijany.
- Wykonawca jest odczytywany z kolumny `H=WYKONAWCA`.
- Identyfikatory wykonawców są mapowane jawnie w `config/worker_mapping.yaml`.
- Kopiowane są wartości `A:AT` od wiersza 18, zwarte od wiersza 18.
- Formuły `AU:AY` i formatowanie pozostają w szablonie pracownika.
- Pusty szablon pozostaje pusty.
- Szablon z istniejącymi danymi nie jest nadpisywany.
- Nieznany wykonawca jest pomijany i zgłaszany.

## Instalacja lokalna

Wymagany jest Python 3.11 lub nowszy na komputerze taty.

```powershell
py -3 -m pip install -r requirements.txt
```

Instalacja obejmuje `rich`, używany przez kolorowy dashboard CLI. Jeśli terminal
nie obsługuje kolorów albo pakiet jest chwilowo niedostępny, narzędzie używa
tekstowego fallbacku z tymi samymi informacjami operacyjnymi.

Przed pierwszym prawdziwym uruchomieniem użyj kontroli bez zapisu:

```powershell
py -3 run.py --dry-run --source "C:\Dane\08_14_09_2026\Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
```

Uruchomienie pokazuje etapy, postęp szablonów pracownika i końcowe liczniki.
W przekierowanym wyjściu lub terminalu bez kolorów używany jest zwykły tekst.
Historia czasów jest dopisywana lokalnie do `.rozliczenia-metrics.jsonl`; można
wskazać inne miejsce parametrem `--metrics`. P50 i P95 pojawiają się po pięciu
ukończonych obserwacjach tego samego trybu (`RUN` albo `DRY-RUN`).

## Uruchomienie przez CMD

Dwuklik `Utwórz rozliczenia.cmd` otwiera wybór pliku zbiorczego. Podanie ścieżki
jest alternatywą dla skryptu VBA:

```powershell
Utwórz rozliczenia.cmd "C:\Dane\08_14_09_2026\Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
```

## Uruchomienie z Excela

`deploy/AutomatyzacjaRozliczen.bas` jest adapterem VBA do osobnego pliku
`AutomatyzacjaRozliczen.xlsm`.

1. Utwórz pusty plik Excela i zapisz go jako `.xlsm` obok `Utwórz rozliczenia.cmd`.
2. Otwórz `Alt+F11`, wybierz `File > Import File` i wskaż plik `.bas`.
3. Dodaj przycisk formularza na arkuszu i przypisz mu `UruchomRozliczenia`.
4. Zapisz plik w zaufanej lokalizacji lub uruchom zawartość po świadomym zatwierdzeniu.

Ścieżka VBA nie zawiera osobnej logiki kopiowania. Wywołuje ten sam `run.py`,
więc obie metody mają te same zabezpieczenia.

## Testy

Testy tworzą syntetyczne pliki `.xlsx` w katalogu tymczasowym. Nie używają
plików z `praca-tata` i nie zawierają prawdziwych danych klientów.

```powershell
py -3 -m pytest
```

## Naprawa plików zapisanych starą wersją

Jeśli wcześniejsze uruchomienie pokazało w Excelu komunikat o naprawie
odwołania zewnętrznego, zamknij Excel i uruchom jednorazowo tryb kontrolny:

```powershell
py -3 tools\repair_external_links.py --directory "C:\Dane\08_14_09_2026\Rozliczenie pracowników 08_14_09_2026" --reference "C:\Dane\08_14_09_2026\Rozliczenie pracowników 08_14_09_2026\Rozliczenie 08_14_09_2026 - Kamil Frontczak.xlsx"
```

Jeśli lista plików jest poprawna, dodaj `--apply`. Narzędzie zapisze kopie w
`_backup_przed_naprawa_linkow` i zmieni wyłącznie części ZIP odpowiedzialne za
odwołania zewnętrzne, nie komórki ani formuły.

## Zakres poza pierwszą wersją

Synchronizacja OneDrive, współbieżna edycja przez innych użytkowników oraz
automatyczne wykrywanie gotowości po samym zapisie pliku są poza zakresem.
