# Model Domeny

Ten plik opisuje język procesu. Nie opisuje implementacji.

## Okres rozliczeniowy

Tygodniowy przedział pracy od wtorku do poniedziałku. Jest identyfikowany przez
token zawierający dzień wtorku, dzień poniedziałku, miesiąc i rok, na przykład
`08_14_09_2026`.

## Plik zbiorczy

Jedyny plik wejściowy tego procesu. Zawiera dane wszystkich wykonawców dla
jednego okresu rozliczeniowego.

## Wykonawca

Osoba wskazana w kolumnie `WYKONAWCA` pliku zbiorczego. Wartość w tej kolumnie
jest identyfikatorem źródłowym, który nie musi być identyczny z nazwą człowieka
w nazwie pliku docelowego.

## Szablon pracownika

Plik przygotowany dla konkretnego wykonawcy. Ma stałą strukturę, formuły,
stawki i formatowanie. Może pozostać pusty, jeśli wykonawca nie ma wierszy w
pliku zbiorczym.

## Rozliczenie pracownika

Szablon pracownika uzupełniony wierszami tego wykonawcy z danego okresu.

## Wiersz danych

Wiersz od 18. w dół zawierający dane wejściowe pracy. Formuły i techniczne
wartości szablonu nie są same w sobie wierszami danych.

## Placeholder

Plik bez nazwy wykonawcy, na przykład `Rozliczenie {okres} -.xlsx`. Nie jest
rozliczeniem konkretnej osoby i pozostaje nietknięty.

## Gotowość

Świadoma decyzja taty, że plik zbiorczy jest zakończony i można przygotować
rozliczenia pracowników. W pierwszej wersji gotowość jest potwierdzana przez
uruchomienie procesu, a nie zgadywana na podstawie samego zapisu pliku.

## Nienadpisywanie

Plik pracownika zawierający już dane wejściowe nie jest automatycznie czyszczony
ani zastępowany. Proces pomija go i zgłasza problem.
