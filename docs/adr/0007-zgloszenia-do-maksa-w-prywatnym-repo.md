# ADR 0007: Zgłoszenia do Maksa w prywatnym repo

## Status

Zaakceptowana. Rewiduje regułę prywatności z
[ADR 0004](0004-centrum-rozliczen-adapter.md) dla jednej treści: Zgłoszenia.
Pozostałe zasady ADR 0004 (tylko `127.0.0.1`, kontrola `Host` i `Origin`,
pliki wyłącznie z wyliczonych ścieżek) zostają bez zmian.

## Decyzja

Przy Zatrzymaniu, którego tata nie usunie sam, Centrum rozliczeń wysyła
Zgłoszenie jako issue z etykietą `zgloszenie` do prywatnego repozytorium
`MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia`, nie do publicznego repozytorium
narzędzia. Tata wysyła je jednym kliknięciem po Diagnozie i przed wysłaniem
widzi jego dokładną treść.

To pierwsze połączenie narzędzia z internetem z własnej inicjatywy taty i
pierwszy sekret na jego komputerze:

- Centrum łączy się wyłącznie z API GitHuba: przy wysyłce Zgłoszenia, przy
  sprawdzaniu stanu wysłanych Zgłoszeń (także przy pytaniu w Diagnozie, czy
  problem ma już otwarte Zgłoszenie) i przy sprawdzeniu aktualności
  narzędzia w Diagnozie. Brak sieci nie daje Komunikatu, dopóki tata niczego
  nie wysyła.
- Klucz to token fine-grained, który Maks tworzy ręcznie: tylko repozytorium
  Zgłoszeń, uprawnienie Issues (odczyt i zapis), ważność najwyżej rok. Maks
  wpisuje go do `config/zgloszenia-klucz.txt` poza Gitem; tata nie ma pola na
  klucz. Klucz nie trafia do odpowiedzi Centrum, dziennika, Zgłoszenia ani
  przeglądarki; Konfiguracja pokazuje tylko „gotowe” albo „brak klucza”.
- Skrzynka Zgłoszeń jest adapterem wstrzykiwanym do Centrum obok platformy.
  Testy i `verify-centrum-rozliczen` nigdy nie łączą się z prawdziwym GitHubem.
- Gdy wysyłka się nie uda (brak klucza, odmowa, brak połączenia), Zgłoszenie
  zostaje jako plik Markdown w `config/zgloszenia/` poza Gitem, tata dostaje
  Komunikat i może przesłać plik mailem albo spróbować ponownie.
- Wysłane Zgłoszenia (odcisk problemu, numer issue, commit narzędzia) Centrum
  pamięta w `config/zgloszenia-wyslane.json` poza Gitem. Jeden problem ma jedno
  otwarte Zgłoszenie: przed wysłaniem Centrum szuka w skrzynce otwartego
  Zgłoszenia z tym samym odciskiem (wiersz `Odcisk problemu` w treści). Gdy
  Maks je zamknął, a problem wraca, nowe Zgłoszenie ma odnośnik do
  poprzedniego. Bez odpowiedzi skrzynki problem wysłany z tego komputera
  czeka na naprawę, także po restarcie Centrum.

Rewizja reguły prywatności: Zgłoszenie opuszcza komputer taty, ale niesie tylko
to, co reguła ADR 0004 już dopuszcza w Centrum (Komunikat w trzech częściach,
ze skróconymi ścieżkami, wynik sprawdzeń Diagnozy, bezpieczne wpisy dziennika
Centrum) oraz proces, okres, tryb, wersję i commit narzędzia. Bez treści
wierszy, adresów, numerów zleceń, stawek, treści wyjątków i pełnych ścieżek.

Naprawa odbywa się w publicznym repozytorium narzędzia. PR odwołuje się do
Zgłoszenia samym numerem, a przypadek testowy powstaje na danych syntetycznych;
treść Zgłoszenia nie trafia do publicznych PR-ów, commitów ani issue.

## Zagrożenia, przed którymi chroni prywatne repo

- Wyciek: nawet bezpieczna treść mówi o pracy taty (okresy, nazwy plików,
  Wykonawcy w Komunikatach), a publiczne issue czyta każdy.
- Wstrzykiwanie poleceń: publiczne issue może skomentować każdy. Zgłoszenia
  naprawia także agent, więc obcy tekst w wątku Zgłoszenia byłby poleceniem dla
  agenta z dostępem do repozytorium narzędzia. Do prywatnego repo piszą tylko
  Maks i klucz taty.

## Odrzucone warianty

- Prywatne repozytorium samego narzędzia: CI ma 6 z 7 zadań na
  `windows-latest` (podwójne minuty Actions, ok. 140 uruchomień CI tygodniowo),
  a `git pull` u taty wymagałby logowania.
- Publiczne issue z okrojoną treścią: bez ścieżek i Komunikatu Maks i tak
  dopytywałby tatę, a wstrzykiwanie poleceń przez komentarze obcych zostaje.
