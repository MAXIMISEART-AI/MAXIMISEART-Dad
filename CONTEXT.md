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

Skoroszyt przygotowany dla konkretnego wykonawcy na podstawie Placeholdera.
Zachowuje jego strukturę, formuły, stawki i formatowanie; zawiera dane tylko z
własnego okresu i może pozostać pusty, jeśli wykonawca nie ma wierszy w Pliku
zbiorczym.

## Folder rozliczeń pracowników

Folder danego okresu zawierający osobny skoroszyt dla każdego wykonawcy.

## Przygotowanie skoroszytów pracowników

Etap tworzenia plików nowego okresu przez skopiowanie Placeholdera dla każdego
wykonawcy. Token okresu i nazwa wykonawcy trafiają do nazw folderu i plików;
struktura, formuły, stawki i formatowanie Placeholdera pozostają zachowane, a
sam Placeholder pozostaje niezmieniony.

## Przetworzenie Szablonu pracownika

Obsłużenie jednego Szablonu pracownika w ramach przygotowania Rozliczeń
pracowników. Może zakończyć się uzupełnieniem danych, pozostawieniem pustego
szablonu albo pominięciem, gdy dalsze działanie nie jest bezpieczne.

## Rozliczenie pracownika

Szablon pracownika uzupełniony wierszami tego wykonawcy z danego okresu.
Plik jest identyfikowany nazwą `Rozliczenie {okres} - {nazwa wykonawcy}.xlsx`;
`{okres}` to token okresu rozliczeniowego.

## Wiersz danych

Wiersz od 18. w dół zawierający dane wejściowe pracy. Formuły i techniczne
wartości szablonu nie są same w sobie wierszami danych.

## Placeholder

Wspólny skoroszyt bazowy bez nazwy wykonawcy, z którego powstają Szablony
pracowników. Nie jest rozliczeniem konkretnej osoby i pozostaje niezmieniony.

## Gotowość

Świadoma decyzja taty, że plik zbiorczy jest zakończony i można przygotować
rozliczenia pracowników. W pierwszej wersji gotowość jest potwierdzana przez
uruchomienie procesu, a nie zgadywana na podstawie samego zapisu pliku.

## Przebieg rozliczeń

Jedno uruchomienie procesu od wskazania Pliku zbiorczego do wyniku końcowego
albo bezpiecznego przerwania. Obejmuje Przygotowanie skoroszytów pracowników,
a następnie ich uzupełnienie danymi z Pliku zbiorczego.

## Zdarzenie przebiegu

Bezpieczny fakt opisujący zmianę lub wynik Przebiegu rozliczeń, na przykład
rozpoczęcie etapu, zakończenie etapu, rozpoczęcie przetwarzania Szablonu
pracownika albo zakończenie tego przetwarzania. Nie zawiera adresów klientów,
numerów zleceń ani treści wierszy.

## Nienadpisywanie

Jeśli folder lub pliki docelowe nowego okresu już istnieją, proces zatrzymuje
się bez ich nadpisywania. Placeholder również pozostaje niezmieniony.
