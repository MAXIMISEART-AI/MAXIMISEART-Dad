# ADR 0004: Przerwana publikacja plików okresu jako zaakceptowane ryzyko

## Status

Zaakceptowana. Rozstrzyga issue #91.

## Kontekst

Przygotowanie pliku zbiorczego obiecuje, że oba pliki okresu powstają razem
albo żaden (`GLOSSARY.md`). Gdy Folder okresu jeszcze nie istnieje, cały
katalog tymczasowy staje się Folderem okresu w jednym `rename`, więc obietnica
obowiązuje bez wyjątków. Gdy Folder okresu już istnieje, `_publish` przenosi
Rozliczenie wewnętrzne i Plik zbiorczy dwoma osobnymi `os.rename`. Windows nie
pozwala, żeby dwa pliki pojawiły się w istniejącym folderze atomowo. Jeśli
proces zginie między tymi wywołaniami (tata zamknie okno, zabraknie prądu), w
Folderze okresu zostaje samo Rozliczenie wewnętrzne.

## Decyzja

Akceptujemy to ryzyko i nie zmieniamy kodu publikacji. Okno trwa mikrosekundy.
Skutek jest jawny i bezpieczny: następne Uruchomienie procesu zatrzymuje się na
`PLIK_OKRESU_ISTNIEJE` (Nienadpisywanie), wskazuje plik i każe go przenieść
albo usunąć. Instrukcja taty opisuje, jak rozpoznać taki niedokończony zapis.

Odrzucone kierunki:

- **Podfolder publikowany jednym `rename`** zmienia układ Folderu okresu, do
  którego tata jest przyzwyczajony.
- **Dokończenie publikacji przez następne uruchomienie** z pozostałości katalogu
  tymczasowego wymaga przeszukiwania folderu okresów, nowego komunikatu, obsługi
  dwóch uruchomień naraz i rozbudowy sprawdzenia o uruchomienia po kolei. To
  dużo kodu jak na ryzyko tej skali.
- **Osobny komunikat o przerwanym zapisie** daje niewiele ponad obecny
  komunikat `PLIK_OKRESU_ISTNIEJE`, a kosztuje to samo rozpoznawanie
  pozostałości.

## Konsekwencje

- `explore_publication.py` zgłasza ten przypadek jako `ZAAKCEPTOWANE RYZYKO`
  (`ACCEPTED_RISKS`), a nie jako znane ustalenie. Inny ślad naruszenia
  RAZEM_ALBO_ZADEN nadal jest błędem sprawdzenia.
- Decyzja nie obejmuje nieudanego wycofania po błędzie zapisu (issue #92). Tam
  proces działa dalej, więc mówi tacie prawdę komunikatem
  `BLAD_ZAPISU_POZOSTAL_PLIK`.
- Do decyzji trzeba wrócić, jeśli publikacja zacznie trwać dłużej, na przykład
  przez kopiowanie zamiast przenoszenia albo przez folder sieciowy.
