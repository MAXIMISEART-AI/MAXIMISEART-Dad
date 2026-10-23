# ADR 0014: Tata dostaje tylko Stabilną wersję

## Status

Proponowana, czeka na zgodę Maksa. Zmienia dwa zdania
[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md):

- „Pobiera `main` z publicznego repozytorium bez logowania i przesuwa klon tylko
  do przodu”: Centrum pobiera gałąź `stabilna`, a lokalna gałąź klonu taty
  zostaje `main`.
- „Konfiguracja pamięta odpowiedź `main` przez 10 minut”: Aktualność narzędzia
  porównuje commit narzędzia z gałęzią `stabilna`, z tą samą pamięcią.

Pozostałe zasady ADR 0009 (wszystko albo nic, dziennik „Aktualizacja w toku”,
opiekun ponownego startu, pliki taty, tylko po kliknięciu) zostają.

## Kontekst

Centrum aktualizuje narzędzie z `main` po kliknięciu taty (ADR 0009). Maks
chce mergować bardzo dużo PR-ów dziennie, a ruleset `main` wymaga zielonego
`Required CI status` tylko na PR, bez aktualnej bazy. Z 40 ostatnich runów CI
na pushu do `main` (od 21.10 21:21 UTC) 6 skończyło się porażką. Tata, który
kliknie `Zaktualizuj narzędzie` w takim oknie, dostaje commit, którego CI nie
przeszło. Opiekun ponownego startu cofa tylko wersję, która nie wystartuje, a
nie taką, która startuje i źle liczy.

## Decyzja

Tata dostaje tylko Stabilną wersję: commit `main`, dla którego przeszło pełne
CI na pushu do `main`.

- **Gałąź `stabilna`.** Workflow `.github/workflows/stabilna.yml` biegnie po
  każdym zakończonym runie CI na pushu do `main` (`workflow_run`). Gdy ta
  próba runu skończyła się sukcesem (każdy job, także `Required CI status`),
  `tools/promuj_stabilna.py` przesuwa `stabilna` na ten commit zwykłym pushem,
  bez force. Sukces całego runu jest surowszy niż sam `Required CI status`:
  łapie też job, którego ktoś zapomni dopisać do `needs`. Skrypt wylicza
  wynik ze stanu GitHuba: `stabilna`, która już zawiera commit, zostaje (run
  starszego commitu skończył się po nowszym); commit albo `stabilna` spoza
  `main`, albo `stabilna`, która nie jest przodkiem commitu, to odmowa i
  czerwony job, a `stabilna` się nie zmienia. Push odrzucony, bo inny run przesunął ją w międzyczasie, liczy
  się od nowa. Brak gałęzi zakłada pierwszy zielony run.
- **Uprawnienia.** Tylko ten job ma `contents: write`. `workflow_run` bierze
  definicję z `main`, więc PR nie zmieni promocji, zanim się zmerguje. Reszta
  CI zostaje z `contents: read`. `GITHUB_TOKEN` z `contents: write` przesuwa
  gałąź także przez commity, które zmieniają albo dodają pliki w
  `.github/workflows/` (sprawdzone 23.10 na gałęzi próbnej, runy 39881543713
  i 39926967134), więc promocja nie potrzebuje osobnego klucza.
- **Centrum pobiera `stabilna`.** `ToolClone.update` pobiera
  `refs/heads/stabilna` i przesuwa lokalną `main` taty tylko do przodu.
  `INNA_GALAZ` znaczy dalej „klon nie stoi na `main`”, a commit narzędzia
  (`version.tool_commit`) czyta się jak dotąd. Klon, który już zawiera pobraną
  `stabilna`, jest aktualny i zostaje bez zmian, także gdy stoi na nowszym
  commicie `main`. Brak gałęzi `stabilna` na GitHubie też daje `AKTUALNA`: nie
  ma wersji, na którą można przejść.
- **Aktualność narzędzia.** Diagnoza i Konfiguracja pytają API GitHuba o
  `commits/stabilna` zamiast `commits/main`. Liczba pytań się nie zmienia
  (limit 60 na godzinę bez logowania): Konfiguracja pamięta odpowiedź przez 10
  minut, brak odpowiedzi przez minutę. Nazwę gałęzi trzyma jedna stała
  (`tool_update.STABLE_BRANCH`), więc Aktualność i Aktualizacja narzędzia
  patrzą na tę samą gałąź.

## Przejście

- Wersja u taty sprzed tej zmiany pobiera `main`. Jej ostatnia aktualizacja
  bierze `main` z chwili kliknięcia, także czerwony. Dopiero wersja, którą
  przyniesie, pobiera `stabilna`.
- Gdy po tej aktualizacji tata stoi na commicie `main` nowszym niż `stabilna`,
  `Zaktualizuj narzędzie` odpowiada `Masz najnowszą wersję.`, a Aktualność
  pokazuje `Jest nowsza wersja`, bo porównuje równość commitów, a nie
  przodków. Diagnoza tak samo: gdy nie znajdzie innej przyczyny Zatrzymania,
  wyjaśnia je nowszą wersją, a aktualizacja nic nie zmienia. Trwa to do
  najbliższego zielonego runu CI na `main`, który wyprzedzi jego commit. Żeby
  tego uniknąć, Maks po merge'u czeka, aż `git ls-remote origin
  refs/heads/main refs/heads/stabilna` pokaże ten sam SHA, nie merguje nic
  więcej, dopóki tata nie kliknie, i dopiero wtedy mówi mu o aktualizacji.
  Tata staje wtedy dokładnie na `stabilna`.
- Przed merge'em tej zmiany Maks zakłada `stabilna` na ostatnim commicie
  `main` z zielonym CI. Bez tego, do końca pierwszego zielonego runu po
  merge'u, Aktualność pokazuje `Nie sprawdzono`, Diagnoza „brak połączenia z
  GitHubem”, a aktualizacja `Masz najnowszą wersję.`.
- Ruleset dla `stabilna` blokuje force push i usunięcie, i nic więcej. Nie
  zatrzymuje zwykłego pushu do przodu.
- Po merge'u Maks sprawdza pierwszy run „Stabilna wersja” (`gh run list
  --workflow stabilna.yml --limit 3`) i to, że `stabilna` stoi na commicie
  merge'a. Run CI commitu sprzed merge'u, który skończy się po nim, daje
  czerwony run promocji (w jego commicie nie ma skryptu), a `stabilna` się
  nie zmienia.
- Nowa instalacja u taty: `git clone`, potem `git reset --hard
  origin/stabilna` na `main` (README).

## Konsekwencje

- Naprawa dociera do taty dopiero po pełnym CI pushu do `main`: mediana 16
  minut od pushu w 34 zielonych runach z 21-23.10. Czerwony `main` zatrzymuje
  tatę na ostatniej Stabilnej wersji, aż naprawa przejdzie CI.
- Powiadomienie o naprawie: Maks zamyka Zgłoszenie, gdy naprawa jest już na
  `stabilna`. Wcześniej tata kliknie aktualizację z Powiadomienia, dostanie
  `Masz najnowszą wersję.`, a Powiadomienie zostanie.
- `verify-centrum-na-windowsie` to osobny workflow, uruchamiany tylko przy
  zmianach w plikach startu i aktualizacji. Nie jest warunkiem promocji.
- Ręczny push na `stabilna` omija CI i trafia do taty. Gałąź agenta zbudowana
  na `main` jest potomkiem `stabilna`, więc `git push origin HEAD:stabilna`
  przechodzi jako push do przodu, a Centrum nie sprawdza, że `stabilna` leży
  na `main`. Ruleset `main` wymaga zielonego `Required CI status`, a
  `stabilna` takiej ochrony nie ma. Zabezpieczenie wybiera Maks, np. odmowę
  pushu na `refs/heads/stabilna` w `tools/hooks/pre-push` z regułą w
  `AGENTS.md`, wymagany status w rulesecie `stabilna` (trzeba sprawdzić, czy
  przepuszcza push z `GITHUB_TOKEN`) albo pobieranie w Centrum także `main`
  i odmowę, gdy `stabilna` na nim nie leży.
- Nazwa `stabilna` jest umową z kodem u taty. Zmiana nazwy potrzebuje
  takiego samego przejścia jak to.

## Odrzucone warianty

- Centrum pyta GitHuba o status CI commitów i przechodzi na najnowszy zielony:
  więcej pytań do API bez logowania, a logika wyboru wersji siedzi u taty, w
  module, który używa tylko biblioteki standardowej.
- Tag na każdy zielony commit albo jeden przesuwany tag: przesuwany tag wymaga
  force, a tag na każdy commit to setki tagów dziennie, z których Centrum i
  tak musiałoby wybrać najnowszy.
- Job promocji w `ci.yml` (`needs: required`): bez `workflow_run`, ale PR
  zmieniający `ci.yml` zmienia też job, który ma `contents: write`.
- Lokalna gałąź taty `stabilna`: przejście musiałoby przełączyć gałąź w klonie
  taty (nowy krok, który może się nie udać), a `INNA_GALAZ` zmieniłaby
  znaczenie.
- Tylko kolejka merge'y (merge queue) albo wymóg aktualnej bazy w rulesecie
  `main`: mniej czerwonych `main`, ale CI na pushu do `main` dalej może paść
  (niestabilny test, zmiana środowiska runnera), więc to uzupełnienie, nie
  zastępstwo.
