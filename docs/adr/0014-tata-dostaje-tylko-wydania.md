# ADR 0014: Tata dostaje tylko Wydania

## Status

Proponowana, czeka na zgodę Maksa. Zmienia dwa zdania
[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md):

- „Pobiera `main` z publicznego repozytorium bez logowania i przesuwa klon tylko
  do przodu”: Centrum pobiera `main` i tagi Wydań, a przesuwa klon tylko do
  przodu, na commit najnowszego Wydania. Lokalna gałąź klonu taty zostaje
  `main`.
- „Konfiguracja pamięta odpowiedź `main` przez 10 minut”: Aktualność narzędzia
  porównuje commit narzędzia z commitem najnowszego Wydania, z tą samą pamięcią.

Pozostałe zasady ADR 0009 (wszystko albo nic, dziennik „Aktualizacja w toku”,
opiekun ponownego startu, pliki taty, tylko po kliknięciu) zostają.

## Kontekst

Centrum aktualizuje narzędzie z `main` po kliknięciu taty (ADR 0009). Na
`main` trafia 12-40 zmian dziennie, a ruleset `main` wymaga zielonego
`Required CI status` tylko na PR, bez aktualnej bazy. Z 40 runów CI na pushu
do `main` od 21.10 21:21 UTC do 23.10 rano 6 skończyło się porażką. Tata, który kliknie
`Zaktualizuj narzędzie` w takim oknie, dostaje commit, którego CI nie
przeszło. Okres rozliczeń taty jest tygodniowy, więc nie potrzebuje każdej
zmiany zaraz po merge'u.

## Decyzja

Tata dostaje tylko Wydanie: tag `vMAJOR.MINOR.PATCH` (pierwsze to `v0.1.0`) na
commicie `main` z zielonym CI. Wydanie powstaje tylko na prośbę Maksa. To
moment na `verify-*` na prawdziwych plikach taty i na jedną notkę „Co nowego”
zamiast każdej naprawy z osobna.

- **Najnowsze Wydanie.** To tag z najwyższym numerem
  (`tool_update.newest_release`), nie ostatni tag w porządku alfabetycznym
  (`v0.10.0` jest nowsze niż `v0.9.0`). Inne tagi nie są Wydaniami. Ten sam
  wybór robi Aktualizacja i Aktualność narzędzia.
- **Aktualizacja narzędzia.** `ToolClone.update` pobiera `main` i tagi `v*` do
  własnej przestrzeni refów klonu (`refs/wydania/`, z `--prune`, więc tag
  usunięty albo przesunięty na GitHubie nie zostaje u taty). Przesuwa lokalną
  `main` taty tylko do przodu, na commit najnowszego Wydania. Aktualizacja
  nigdy nie cofa wersji:
  - klon, który zawiera już commit najnowszego Wydania, jest `AKTUALNA` i
    zostaje bez zmian, także gdy stoi na nowszym commicie `main`;
  - GitHub bez żadnego Wydania to `AKTUALNA`;
  - Wydanie, którego commitu nie ma na pobranym `main`, to
    `WYDANIE_SPOZA_MAIN` z Komunikatem „przekaż Maksowi”, a klon zostaje bez
    zmian.
- **Aktualność narzędzia.** Diagnoza i Konfiguracja pytają API GitHuba o listę
  tagów (`tags?per_page=100`, wszystkie strony, najwyżej 10) i porównują commit
  narzędzia z commitem najnowszego Wydania. Bez Wydania albo bez pełnej listy
  Aktualność to `Nie sprawdzono`. Konfiguracja dalej pamięta odpowiedź przez 10
  minut, a brak odpowiedzi przez minutę (limit 60 pytań na godzinę bez
  logowania); jedna strona to jedno pytanie.
- **Tworzenie Wydania** (osobna zmiana, `tools/wydanie.py`) sprawdza, że commit
  leży na `main` i ma zielone `Required CI status`, i dopiero wtedy zakłada tag
  i Wydanie na GitHubie. Centrum zielonego CI nie sprawdza.

### Ochrona przed tagiem założonym ręcznie

Agenci pracują na tym samym koncie GitHuba co Maks (admin), więc żadne
uprawnienie nie odróżni tagu z tworzenia Wydania od tagu założonego ręcznie.
Ochrona ma dwie warstwy:

- **Centrum odrzuca Wydanie spoza `main`.** Commit najnowszego Wydania musi być
  przodkiem pobranego `main`, inaczej `WYDANIE_SPOZA_MAIN`. To jedyna warstwa,
  której nie ominie ręczny tag z gałęzi agenta, i jedyna, którą da się
  sprawdzić testem (`tests/test_aktualizacja_narzedzia.py`: tag spoza `main`
  i tag przesunięty na GitHubie poza `main`).
- **Tagi Wydań się nie zmieniają.** Ruleset dla tagów `v*` bez listy
  wyjątków blokuje ich przesunięcie i usunięcie, także adminowi. Niezmienne
  Wydania GitHuba (`immutable-releases`, dostępne w tym repozytorium, dziś
  wyłączone) robią to samo dla tagów z Wydaniem na GitHubie. Wybiera Maks.
  Żadne z nich nie blokuje założenia nowego tagu.

Nie chroni: tag ręcznie założony na commicie `main` bez zielonego CI (np. na
`main` zaraz po merge'u) trafi do taty. Gdyby to było potrzebne, Centrum może
pytać API o `Required CI status` commitu przed przesunięciem klonu.

## Przejście

- Wersja u taty sprzed tej zmiany pobiera `main`. Jej ostatnia aktualizacja
  bierze `main` z chwili kliknięcia. Dopiero wersja, którą przyniesie, pobiera
  Wydania.
- Gdy po tej aktualizacji tata stoi na commicie `main` nowszym niż najnowsze
  Wydanie, `Zaktualizuj narzędzie` odpowiada `Masz najnowszą wersję.`, a
  Konfiguracja i Diagnoza pokazują `Jest nowsza wersja`, bo porównują równość
  commitów, a nie przodków. Trwa to do następnego Wydania.
- Dlatego kolejność: `v0.1.0` na zielonym commicie `main` przed merge'em (bez
  niego Aktualność u taty pokazywałaby `Nie sprawdzono`), po merge'u i
  zielonym CI Wydanie `v0.2.0` na commicie merge'a, nic więcej do `main`,
  dopóki tata nie kliknie. Tata staje wtedy dokładnie na `v0.2.0`.
- Nowa instalacja u taty: `git clone`, potem `git reset --hard` na najnowszy
  tag Wydania (README).

## Konsekwencje

- Naprawa dociera do taty dopiero z następnym Wydaniem. Powiadomienie o
  naprawie: Maks zamyka Zgłoszenie, gdy naprawa jest w Wydaniu; wcześniej tata
  kliknie aktualizację z Powiadomienia i dostanie `Masz najnowszą wersję.`.
- Zielone, ale zepsute Wydanie naprawia się tylko do przodu: nowym Wydaniem z
  revertem. Usunięcie tagu nie cofa taty, bo aktualizacja nigdy nie cofa.
- Nazwy `v*` i schemat numeru są umową z kodem u taty.

## Odrzucone warianty

- Gałąź `stabilna`, którą CI przesuwa na każdy zielony commit `main` (pierwsza
  wersja tego ADR): tata dostawałby 12-40 zmian dziennie bez notki i bez
  `verify-*` na prawdziwych plikach, a ręczny push na `stabilna` omijał CI tak
  samo jak ręczny tag.
- Centrum wybiera najnowszy commit `main` z zielonym CI przez API: więcej
  pytań do API bez logowania, logika wyboru wersji u taty, i dalej każda
  zmiana od razu u taty.
- Najnowszy tag według porządku alfabetycznego albo daty: `v0.10.0` przegrałby
  z `v0.9.0`, a data tagu mówi, kiedy go założono, nie co zawiera.
- Lokalna gałąź taty na tagu (odłączony `HEAD`): `INNA_GALAZ` zmieniłaby
  znaczenie, a commit narzędzia czyta się dziś z gałęzi.
