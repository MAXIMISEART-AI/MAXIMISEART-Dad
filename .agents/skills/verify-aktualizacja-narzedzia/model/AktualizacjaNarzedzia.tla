------------------------- MODULE AktualizacjaNarzedzia -------------------------
(***************************************************************************)
(* Aktualizacja narzędzia z Centrum rozliczeń (ADR 0009) przy każdej       *)
(* kolejności awarii.                                                      *)
(*                                                                         *)
(* Obietnica: gdy aktualizacja się skończy, przerwie albo komputer zgaśnie, *)
(* klon narzędzia stoi na wersji, która wystartuje ze skrótu taty, a plik  *)
(* taty w config/ (dziś worker_mapping.yaml) ma treść taty. Albo zostaje   *)
(* dziennik „Aktualizacja w toku” z treścią taty, a skrót przy następnym   *)
(* starcie albo następne kliknięcie cofa z niego klon (Postep).            *)
(*                                                                         *)
(* Jedna akcja to jeden krok kodu, który kończy się, zanim zacznie się     *)
(* następny: jedno polecenie Gita, jedno shutil.copy2, jedno uruchomienie  *)
(* pip, jeden proces opiekuna. Komentarz przy akcji wskazuje ten kod w     *)
(* src/rozliczenia/centrum/: tool_update.py, tool_updates.py,              *)
(* restart_guardian.py (z cofaniem nowej wersji, która nie wystartuje),   *)
(* launcher.py (cofanie przerwanej aktualizacji przy starcie skrótu).      *)
(*                                                                         *)
(* Druga obietnica (OpiekunCofaTylkoNieudana): opiekun cofa nową wersję    *)
(* tylko wtedy, gdy ona naprawdę nie startuje, także gdy tata w trakcie    *)
(* ponownego startu kliknie skrót na pulpicie.                             *)
(*                                                                         *)
(* Trzecia obietnica (OkienkoTylkoGdyNicNieDziala): opiekun pokazuje       *)
(* okienko „nie wystartowało” tylko wtedy, gdy żadne Centrum nie działa.  *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS
    MaxKlikniec,        \* ile razy tata klika „Zaktualizuj narzędzie”
    OdmowaScalenia,     \* merge --ff-only odmawia przed zmianą czegokolwiek -> ZMIANY_NA_KOMPUTERZE
    AwariaPobrania,     \* _Git.fetch: brak sieci albo logowanie -> BRAK_POLACZENIA, LOGOWANIE
    AwariaBibliotek,    \* pip_install zwraca False (błąd pip, limit czasu) -> INSTALACJA_BIBLIOTEK
    AwariaOpiekuna,     \* restart_guardian.launch rzuca; stare Centrum nie zwalnia portu w PORT_TIMEOUT_S
    AwariaGita,         \* git checkout HEAD -- (set_aside), git diff (changed), git reset --keep (_roll_back): GitFailed
    AwariaKopiowania,   \* shutil.copy2 pliku taty albo zapis stan.json rzuca OSError (dysk, antywirus, OneDrive)
    NieudanyStart,      \* nowa wersja nie odpowiada w START_TIMEOUT_S, choć ma swoje biblioteki
    Wylaczenie,         \* komputer gaśnie albo proces ginie w dowolnym kroku
    MaxSkrotowWTrakcie, \* ile razy tata klika skrót na pulpicie, gdy opiekun ponownego startu działa
    Wybaczone           \* znane znaleziska, które TataMaDzialajacaWersjePozaZnanymi pomija (oczekiwane.json)

VARIABLES
    \* Dysk taty: przeżywa zamknięcie Centrum i wyłączenie komputera.
    head,          \* commit klonu: "stara" (sprzed kliknięcia) albo "nowa" (najnowsze Wydanie)
    plikTaty,      \* config/worker_mapping.yaml w klonie: "taty", "wzor" (treść z HEAD repozytorium) albo "brak"
    kopia,         \* kopia pliku taty w dzienniku (centrum-aktualizacja-w-toku/pliki-taty): "brak" albo "taty"
    biblioteki,    \* biblioteki Pythona taty: "stare", "czesciowe" (pip przerwany albo nieudany), "nowe"
    dziennik,      \* dziennik „Aktualizacja w toku” (stan.json): "brak" albo "w_toku"
    dzierzawa,     \* opiekun_do w stan.json: "wazna", dopóki opiekun ponownego startu może działać, albo "brak"
    \* Nowa wersja: wybrana raz na początku, potem stała.
    nowaUsuwaPlikTaty,     \* nowa wersja usuwa albo przestaje śledzić plik taty (_DadFiles.leaving go znajduje)
    nowaZmieniaWymagania,  \* nowa wersja zmienia requirements.txt (_Git.changed)
    nowaStartuje,          \* nowa wersja odpowiada na /api/health, gdy ma swoje biblioteki
    \* Procesy.
    centrum,       \* wersja działającego Centrum: "stara", "nowa" albo "brak"
    pc,            \* krok aktualizacji; "spoczynek", gdy żadna nie trwa
    klikniecia,
    krok,          \* ostatni krok, słowami kodu: z nich składa się kontrprzykład
    slady,         \* awarie znanych znalezisk, które już się zdarzyły (ZnaneZnaleziska)
    skrot,         \* skrót kliknięty w trakcie pracy opiekuna: "ma_port" od listen_locally do listener.close(), inaczej "brak"
    skrotyWTrakcie,\* ile razy tata kliknął skrót, gdy opiekun działał
    cofa           \* kto woła _roll_back: "centrum" (ToolClone.update, ToolUpdates._moved_back), "klik"
                   \* (ToolClone.update przed pobraniem, gdy zastaje dziennik bez terminu opiekuna), "opiekun"
                   \* (restart_guardian._rolled_back po nowej wersji, która nie odpowiada) albo "opiekun_bez_portu"
                   \* (restart_guardian._rolled_back, gdy port nie został zwolniony: potem nic nie startuje)
                   \* albo "skrot" (launcher._roll_back przy starcie); po odmowie scalenia "centrum"

dysk == <<head, plikTaty, kopia, biblioteki, dziennik, dzierzawa>>
nowa == <<nowaUsuwaPlikTaty, nowaZmieniaWymagania, nowaStartuje>>
vars == <<dysk, nowa, centrum, pc, klikniecia, krok, slady, cofa, skrot, skrotyWTrakcie>>

ZnaneZnaleziska == {}

Kroki == {"spoczynek", "pobieranie", "kopia_plikow", "checkout_head", "scalanie",
          "przywrocenie_po_odmowie", "przywrocenie_po_scaleniu", "instalacja",
          "instalacja_trwa", "cofanie_usun", "cofanie_reset", "cofanie_przywroc",
          "koniec_dziennika", "restart", "opiekun_port", "opiekun_start", "opiekun_koniec",
          "opiekun_port_stara", "opiekun_start_stara", "okienko"}

TypeOK ==
    /\ head \in {"stara", "nowa"}
    /\ plikTaty \in {"taty", "wzor", "brak"}
    /\ kopia \in {"brak", "taty"}
    /\ biblioteki \in {"stare", "czesciowe", "nowe"}
    /\ dziennik \in {"brak", "w_toku"}
    /\ dzierzawa \in {"brak", "wazna"}
    /\ nowa \in BOOLEAN \X BOOLEAN \X BOOLEAN
    /\ centrum \in {"stara", "nowa", "brak"}
    /\ pc \in Kroki
    /\ klikniecia \in 0..MaxKlikniec
    /\ slady \subseteq ZnaneZnaleziska
    /\ cofa \in {"centrum", "klik", "opiekun", "opiekun_bez_portu", "skrot"}
    /\ skrot \in {"brak", "ma_port"}
    /\ skrotyWTrakcie \in 0..MaxSkrotowWTrakcie

\* Czy wersja wystartuje ze skrótu taty (run_centrum.py z klonu). Założenie: stara
\* wersja startuje z każdymi bibliotekami, bo requirements.txt ma tylko dolne granice
\* wersji (docstring tool_update.py), więc pip nowej wersji jej nie psuje.
Startuje(wersja) ==
    \/ wersja = "stara"
    \/ /\ nowaStartuje
       /\ (~nowaZmieniaWymagania \/ biblioteki = "nowe")

\* --- Obietnica --------------------------------------------------------------

\* Treść taty jest na dysku: w klonie albo w kopii w dzienniku. Bez kopii (nowa wersja
\* nie usuwa pliku taty) cofanie go nie dotyka, więc wystarcza ten w klonie.
TrescTatyNaDysku == plikTaty = "taty" \/ kopia = "taty"

TataMaDzialajacaWersje ==
    pc = "spoczynek" =>
        \/ Startuje(head) /\ plikTaty = "taty"
        \/ dziennik = "w_toku" /\ TrescTatyNaDysku

\* Znane znalezisko z Wybaczone: przebieg, w którym zdarzyła się jego awaria. Każde
\* inne złamanie obietnicy zostaje naruszeniem, więc znane znalezisko nie zasłania nowego.
Znane == Wybaczone \cap slady /= {}

TataMaDzialajacaWersjePozaZnanymi == TataMaDzialajacaWersje \/ Znane

\* Opiekun cofa klon (cofa = "opiekun") tylko wtedy, gdy wersja, na której klon stoi,
\* naprawdę nie wystartuje. Sprawdzane w chwili wejścia w _roll_back, zanim klon się ruszy.
OpiekunCofaTylkoNieudana ==
    pc = "cofanie_usun" /\ cofa = "opiekun" => ~Startuje(head)

OpiekunCofaTylkoNieudanaPozaZnanymi == OpiekunCofaTylkoNieudana \/ Znane

\* Opiekun pokazuje okienko not_started_after_update (pc = "okienko") tylko wtedy, gdy żadne
\* Centrum nie działa: okienko przy starej wersji ze skrótu to fałszywy alarm (#368).
OkienkoTylkoGdyNicNieDziala ==
    pc = "okienko" => centrum = "brak"

OkienkoTylkoGdyNicNieDzialaPozaZnanymi == OkienkoTylkoGdyNicNieDziala \/ Znane


\* --- Start ------------------------------------------------------------------

Init ==
    /\ head = "stara"
    /\ plikTaty = "taty"
    /\ kopia = "brak"
    /\ biblioteki = "stare"
    /\ dziennik = "brak"
    /\ dzierzawa = "brak"
    /\ nowaUsuwaPlikTaty \in BOOLEAN
    /\ nowaZmieniaWymagania \in BOOLEAN
    /\ nowaStartuje \in (IF NieudanyStart THEN BOOLEAN ELSE {TRUE})
    /\ centrum = "stara"
    /\ pc = "spoczynek"
    /\ klikniecia = 0
    /\ krok = "Centrum dziala w starej wersji"
    /\ slady = {}
    /\ cofa = "centrum"
    /\ skrot = "brak"
    /\ skrotyWTrakcie = 0

\* Kroki kodu aktualizacji i opiekuna nie ruszają skrótu klikniętego w trakcie (skrot).
Idz(nastepny, opis) == pc' = nastepny /\ krok' = opis /\ slady' = slady /\ cofa' = cofa /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Krok awarii znanego znaleziska: zostawia jej ślad dla Znane.
Slad(nastepny, opis, slad) == pc' = nastepny /\ krok' = opis /\ slady' = slady \cup {slad} /\ cofa' = cofa /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Wejście w _roll_back; ``kto`` decyduje, co dzieje się po nim.
Cofaj(kto, opis) == pc' = "cofanie_usun" /\ krok' = opis /\ slady' = slady /\ cofa' = kto /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Klon się nie przesunął, a pliki taty są z powrotem: ToolClone.update usuwa dziennik.
PoOdmowie(opis) == pc' = "koniec_dziennika" /\ krok' = opis /\ slady' = slady /\ cofa' = "centrum" /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* --- ToolUpdates.start, ToolUpdates._result ----------------------------------

\* RunHost.begin_update zajmuje miejsce „jedno naraz”; restart_guardian.prepare
\* kopiuje opiekuna do nowego katalogu tymczasowego (work), zanim klon się zmieni.
\* Kliknięcie przy dzienniku w toku nie liczy się do MaxKlikniec: po COFNIECIE_NIEUDANE
\* Komunikat każe tacie kliknąć jeszcze raz.
Klik ==
    /\ pc = "spoczynek"
    /\ centrum /= "brak"
    /\ klikniecia < MaxKlikniec \/ dziennik = "w_toku"
    /\ klikniecia' = IF dziennik = "w_toku" THEN klikniecia ELSE klikniecia + 1
    /\ Idz("pobieranie", "ToolUpdates.start: tata klika 'Zaktualizuj narzedzie'")
    /\ UNCHANGED <<dysk, nowa, centrum>>

\* --- ToolClone.update ---------------------------------------------------------

\* Dziennik w toku bez terminu opiekuna (_Journal.read, guardian_may_run): _moved_back cofa
\* klon, zanim cokolwiek się pobierze. Inaczej run.fetch(self.origin) (`main` i tagi Wydań),
\* _main_tips i newest_on_main (Wydania spoza linii czubków main pominięte), is_ancestor(after, before), potem
\* _has_local_commits i _changed_tracked_files (te odmowy nie zmieniają klonu, tak jak porażka
\* fetch, więc model ich nie rozróżnia). GitHub bez Wydania, Wydanie na starszym commicie i klon na
\* nowszym commicie `main` niż Wydanie kończą się jak head = "nowa": AKTUALNA, klon bez zmian.
Pobranie ==
    /\ pc = "pobieranie"
    /\ \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "brak"
          /\ Cofaj("klik", "ToolClone.update: dziennik 'Aktualizacja w toku' bez terminu opiekuna, _roll_back przed pobraniem")
       \/ /\ dziennik = "brak" \/ dzierzawa = "wazna"
          /\ \/ /\ AwariaPobrania
                /\ Idz("spoczynek", "ToolClone.update: fetch nie przeszedl (BRAK_POLACZENIA), klon bez zmian")
             \/ /\ head = "nowa"
                /\ Idz("spoczynek", "ToolClone.update: klon zawiera najnowsze Wydanie (AKTUALNA), klon bez zmian")
             \/ /\ head = "stara"
                /\ Idz("kopia_plikow",
                       IF nowaUsuwaPlikTaty
                       THEN "ToolClone.update: najnowsze Wydanie usuwa plik taty z config/"
                       ELSE "ToolClone.update: fetch pobral nowe Wydanie")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* _Journal.begin: copy2 pliku taty do pliki-taty i fsync, potem stan.json (plik tymczasowy, fsync,
\* os.replace). Trwający dziennik to JournalKept, zanim cokolwiek się zmieni (NIEOCZEKIWANY_BLAD).
KopiaPlikow ==
    /\ pc = "kopia_plikow"
    /\ \/ /\ dziennik = "brak"
          /\ kopia' = IF nowaUsuwaPlikTaty THEN "taty" ELSE "brak"
          /\ dziennik' = "w_toku"
          /\ dzierzawa' = "brak"
          /\ Idz(IF nowaUsuwaPlikTaty THEN "checkout_head" ELSE "scalanie",
                 "_Journal.begin: kopia plikow taty, potem stan.json dziennika 'Aktualizacja w toku'")
       \/ /\ dziennik = "w_toku"
          /\ UNCHANGED <<kopia, dziennik, dzierzawa>>
          /\ Idz("spoczynek", "_Journal.begin: poprzednia aktualizacja w toku, JournalKept (NIEOCZEKIWANY_BLAD), klon bez zmian")
       \/ /\ AwariaKopiowania
          /\ dziennik = "brak"
          /\ UNCHANGED <<kopia, dziennik, dzierzawa>>
          /\ Idz("spoczynek", "_Journal.begin: copy2 albo zapis stan.json rzuca OSError (NIEOCZEKIWANY_BLAD), klon bez zmian")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside: git checkout HEAD -- <plik taty>, w try.
CheckoutHead ==
    /\ pc = "checkout_head"
    /\ \/ /\ plikTaty' = "wzor"
          /\ Idz("scalanie", "_DadFiles.set_aside: git checkout HEAD -- przywraca plikowi tresc z repozytorium")
       \/ /\ AwariaGita
          /\ plikTaty' = plikTaty
          /\ Idz("przywrocenie_po_odmowie", "_DadFiles.set_aside: git checkout HEAD -- sie nie udaje, _NotSetAside")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

\* ToolClone.update: git merge --ff-only, w bloku set_aside.
Scalanie ==
    /\ pc = "scalanie"
    /\ \/ /\ head' = "nowa"
          /\ plikTaty' = IF nowaUsuwaPlikTaty THEN "brak" ELSE plikTaty
          /\ Idz(IF nowaUsuwaPlikTaty THEN "przywrocenie_po_scaleniu" ELSE "instalacja",
                 "ToolClone.update: git merge --ff-only przesuwa klon na nowe Wydanie")
       \/ /\ OdmowaScalenia
          /\ UNCHANGED <<head, plikTaty>>
          /\ IF nowaUsuwaPlikTaty
             THEN Idz("przywrocenie_po_odmowie", "ToolClone.update: git merge --ff-only odmawia (ZMIANY_NA_KOMPUTERZE)")
             ELSE PoOdmowie("ToolClone.update: git merge --ff-only odmawia (ZMIANY_NA_KOMPUTERZE)")
    /\ UNCHANGED <<kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside, finally, gdy klon się nie przesunął: _put_back, czyli copy2(backup / name, target).
\* Potem ToolClone.update usuwa dziennik (po odmowie i po _NotSetAside z checkout). OSError staje się
\* _NotPutBack; ToolClone.update zwraca COFNIECIE_NIEUDANE, a dziennik z kopią zostaje.
PrzywroceniePoOdmowie ==
    /\ pc = "przywrocenie_po_odmowie"
    /\ \/ /\ plikTaty' = "taty"
          /\ PoOdmowie("_DadFiles.set_aside (finally): plik taty wraca z kopii, klon bez zmian")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE, tresc taty tylko w dzienniku)")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside, finally, po przesunięciu klonu. OSError z _put_back staje się
\* _NotPutBack, a ToolClone.update (except _NotPutBack, moved) woła _moved_back -> _roll_back.
PrzywroceniePoScaleniu ==
    /\ pc = "przywrocenie_po_scaleniu"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("instalacja", "_DadFiles.set_aside (finally): plik taty wraca z kopii")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Cofaj("centrum", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError; update() wola _roll_back")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

\* ToolClone._install_libraries, w try: run.changed(...requirements.txt), potem self.install.
Instalacja ==
    /\ pc = "instalacja"
    /\ \/ /\ ~nowaZmieniaWymagania
          /\ UNCHANGED biblioteki
          /\ Idz("restart", "ToolClone.update: requirements.txt bez zmian, wynik ok")
       \/ /\ nowaZmieniaWymagania
          /\ biblioteki' = "czesciowe"
          /\ Idz("instalacja_trwa", "pip_install: pip instaluje biblioteki nowej wersji (do 15 minut)")
       \/ /\ AwariaGita
          /\ UNCHANGED biblioteki
          /\ Cofaj("centrum", "_Git.changed: git diff rzuca GitFailed, update() wola _roll_back")
    /\ UNCHANGED <<head, plikTaty, kopia, dziennik, dzierzawa, nowa, centrum, klikniecia>>

InstalacjaKoniec ==
    /\ pc = "instalacja_trwa"
    /\ \/ /\ biblioteki' = "nowe"
          /\ Idz("restart", "pip_install: pip skonczyl, wynik ok")
       \/ /\ AwariaBibliotek
          /\ UNCHANGED biblioteki
          /\ Cofaj("centrum", "pip_install zwraca False, update() wola _roll_back (INSTALACJA_BIBLIOTEK)")
    /\ UNCHANGED <<head, plikTaty, kopia, dziennik, dzierzawa, nowa, centrum, klikniecia>>

\* --- _roll_back ---------------------------------------------------------------

\* _Journal.read i rev-parse HEAD (klon na przed albo po), potem (git.root / name).unlink()
\* dla każdego pliku z kopii w dzienniku.
CofanieUsun ==
    /\ pc = "cofanie_usun"
    /\ plikTaty' = IF kopia = "taty" THEN "brak" ELSE plikTaty
    /\ Idz("cofanie_reset", "_roll_back: plik taty znika z klonu przed reset")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

\* git reset --keep --quiet before, w try. Stara wersja śledzi plik taty, więc reset
\* zapisuje jej treść z repozytorium.
CofanieReset ==
    /\ pc = "cofanie_reset"
    /\ \/ /\ head' = "stara"
          /\ plikTaty' = IF kopia = "taty" THEN "wzor" ELSE plikTaty
          /\ Idz("cofanie_przywroc", "_roll_back: git reset --keep cofa klon do starego commitu")
       \/ /\ AwariaGita
          /\ UNCHANGED <<head, plikTaty>>
          /\ Idz("cofanie_przywroc", "_roll_back: git reset --keep rzuca GitFailed, klon zostaje na nowym commicie")
    /\ UNCHANGED <<kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

CofanieResetUdane == CofanieReset /\ head' = "stara"

\* finally: _put_back, czyli shutil.copy2(backup / name, target). Biblioteki zostają (docstring tool_update.py).
\* Po udanym resecie i kopiowaniu _roll_back usuwa dziennik (KoniecDziennika). Gdy reset się nie
\* udał, po finally wychodzi GitFailed, a dziennik zostaje: w Centrum _moved_back zwraca False i wynikiem
\* jest COFNIECIE_NIEUDANE; opiekun (_rolled_back zwraca False) zapisuje COFNIECIE_NIEUDANE, pokazuje
\* okienko i kończy się; skrót kończy się Komunikatem NIEOCZEKIWANY_BLAD_STARTU i niczego nie startuje.
CofaniePrzywroc ==
    /\ pc = "cofanie_przywroc"
    /\ \/ /\ plikTaty' = IF kopia = "taty" THEN "taty" ELSE plikTaty
          /\ Idz(CASE head = "stara" -> "koniec_dziennika"
                   [] cofa \in {"opiekun", "opiekun_bez_portu"} -> "okienko"
                   [] OTHER -> "spoczynek",
                 CASE head = "stara" -> "_roll_back (finally): plik taty wraca z kopii"
                   [] cofa \in {"centrum", "klik"} -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, Centrum pokazuje COFNIECIE_NIEUDANE"
                   [] cofa = "skrot" -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, skrot konczy sie Komunikatem startu"
                   [] OTHER -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, opiekun pokazuje okienko (return 1)")
       \/ /\ AwariaKopiowania
          /\ kopia = "taty"
          /\ plikTaty' = plikTaty
          /\ Idz(IF cofa \in {"opiekun", "opiekun_bez_portu"} THEN "okienko" ELSE "spoczynek",
                  CASE cofa \in {"centrum", "klik"} -> "_roll_back (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE, tresc taty tylko w dzienniku)"
                    [] cofa = "skrot" -> "_roll_back (finally): copy2 z kopii rzuca OSError, skrot konczy sie Komunikatem startu"
                    [] OTHER -> "_roll_back (finally): copy2 z kopii rzuca OSError, opiekun pokazuje okienko (return 1)")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia>>

CofaniePrzywrocUdane == CofaniePrzywroc /\ pc' = "koniec_dziennika"

\* _Journal.end: najpierw stan.json, potem katalog z kopią. Po nim każdy, kto cofał, idzie dalej:
\* opiekun startuje starą wersję, skrót startuje Centrum od nowa (subprocess.call z cofniętego klonu).
KoniecDziennika ==
    /\ pc = "koniec_dziennika"
    /\ dziennik' = "brak"
    /\ kopia' = "brak"
    /\ dzierzawa' = "brak"
    /\ \/ /\ cofa = "skrot"
          /\ centrum' = head
          /\ Idz("spoczynek", "_Journal.end: dziennik znika; skrot zapisuje wynik NIEOCZEKIWANY_BLAD i startuje Centrum od nowa")
       \/ /\ cofa /= "skrot"
          /\ UNCHANGED centrum
          /\ Idz(CASE cofa = "opiekun" -> "opiekun_port_stara"
                   [] cofa = "klik" -> "pobieranie"
                   [] cofa = "opiekun_bez_portu" -> "okienko"
                   [] OTHER -> "spoczynek",
                 CASE cofa = "opiekun" -> "_Journal.end: dziennik znika; opiekun cofnal klon"
                   [] cofa = "klik" -> "_Journal.end: dziennik znika; ToolClone.update pobiera Wydania jak zwykle"
                   [] cofa = "opiekun_bez_portu" -> "_Journal.end: dziennik znika; opiekun cofnal klon bez portu, pokazuje okienko (return 1)"
                   [] OTHER -> "_Journal.end: dziennik znika; Centrum pokazuje Komunikat porazki")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, klikniecia>>

\* --- ToolUpdates._restart, restart_guardian.main ------------------------------

\* ToolUpdates._restart; gdy restart_guardian.launch rzuca, ToolUpdates._moved_back woła
\* ToolClone.roll_back (-> _roll_back), a Centrum działa dalej w starej wersji.
\* ToolClone.leased_to_guardian zapisuje w dzienniku opiekun_do przed restart_guardian.launch, a gdy
\* launch rzuci, usuwa go.
Restart ==
    /\ pc = "restart"
    /\ \/ /\ AwariaOpiekuna
          /\ dzierzawa' \in IF AwariaKopiowania THEN {"brak", "wazna"} ELSE {"brak"}
          /\ UNCHANGED centrum
          /\ Cofaj("centrum", "ToolUpdates._restart: restart_guardian.launch rzuca; _moved_back cofa klon, Centrum dziala dalej")
       \/ /\ dzierzawa' = "wazna"
          /\ centrum' = "brak"
          /\ Idz("opiekun_port", "ToolUpdates._restart: opiekun startuje, Shutdown.close_for_update zamyka Centrum")
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, klikniecia>>

\* _port_released, potem write_result(ok). Bez portu main od razu woła _rolled_back
\* (ToolClone.roll_back -> _roll_back), a po nim pokazuje okienko i niczego nie startuje.
\* _port_released próbuje co _POLL_S przez PORT_TIMEOUT_S, a skrót trzyma port przez chwilę,
\* więc opiekun czeka, aż skrót go odda (skrot = "brak").
OpiekunPort ==
    /\ pc = "opiekun_port"
    /\ \/ /\ AwariaOpiekuna
          /\ Cofaj("opiekun_bez_portu", "restart_guardian.main: port nie zwolniony w PORT_TIMEOUT_S; _rolled_back bez startu nowej wersji")
       \/ /\ skrot = "brak"
          /\ Idz("opiekun_start", "restart_guardian.main: port zwolniony")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* _start_centrum (run_centrum.py --bez-okienek: skrót bez cofania), potem _answers. Gdy nowa
\* wersja nie odpowie: _stop, write_result z NOWA_WERSJA_NIE_WYSTARTOWALA i _rolled_back, czyli
\* ToolClone.roll_back -> _roll_back.
\* Akcja to chwila, w której nowe Centrum zajmuje port w launcher._listen_when_released. Gdy
\* port trzyma skrót, Centrum z --bez-okienek ponawia listen_locally przez _SHORTCUT_HOLDS_PORT_S,
\* a skrót oddaje port po odczycie dziennika z terminem opiekuna (SkrotOddajePort), więc akcja
\* czeka na skrot = "brak" (#246).
OpiekunStart ==
    /\ pc = "opiekun_start"
    /\ skrot = "brak"
    /\ \/ /\ Startuje(head)
          /\ centrum' = head
          /\ Idz("opiekun_koniec", "restart_guardian.main: nowa wersja odpowiada na /api/health")
       \/ /\ ~Startuje(head)
          /\ UNCHANGED centrum
          /\ Cofaj("opiekun", "restart_guardian.main: nowa wersja nie odpowiada w START_TIMEOUT_S; _stop, potem _rolled_back")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* ToolClone.confirm_update: aktualizacja skończona, dziennik znika (_Journal.end).
OpiekunKoniec ==
    /\ pc = "opiekun_koniec"
    /\ dziennik' = "brak"
    /\ kopia' = "brak"
    /\ dzierzawa' = "brak"
    /\ Idz("spoczynek", "restart_guardian.main: ToolClone.confirm_update usuwa dziennik")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia>>

\* Po udanym cofnięciu: _port_released, potem _start_centrum i _answers(before).
\* Port po cofnięciu może trzymać Centrum, które skrót uruchomił, gdy dziennika już nie było:
\* _port_released czeka na nie PORT_TIMEOUT_S, a potem opiekun pyta je _runs(before) i kończy bez
\* okienka. Port bez Centrum i bez skrótu trzyma inny program: wtedy okienko not_started_after_update.
OpiekunPortStara ==
    /\ pc = "opiekun_port_stara"
    /\ \/ /\ AwariaOpiekuna
          /\ centrum = "brak"
          /\ skrot = "brak"
          /\ Idz("okienko", "restart_guardian.main: port po cofnieciu trzyma inny program, _runs(before) nie odpowiada")
       \/ /\ centrum /= "brak"
          /\ Idz("spoczynek", "restart_guardian.main: port po cofnieciu trzyma Centrum ze skrotu, opiekun konczy bez okienka (_runs)")
       \/ /\ centrum = "brak"
          /\ skrot = "brak"
          /\ Idz("opiekun_start_stara", "restart_guardian.main: port zwolniony po cofnieciu")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* Stara wersja też startuje z --bez-okienek, więc jak nowa w OpiekunStart czeka, aż skrót odda
\* port. Gdy skrót bez dziennika został na porcie z Centrum w tej samej wersji, stara po
\* _SHORTCUT_HOLDS_PORT_S kończy się (już działa), a _answers(before) dostaje odpowiedź od tamtego
\* Centrum.
OpiekunStartStara ==
    /\ pc = "opiekun_start_stara"
    /\ skrot = "brak"
    /\ centrum' = CASE centrum /= "brak" -> centrum
                    [] Startuje(head) -> head
                    [] OTHER -> "brak"
    /\ Idz(IF centrum = "brak" /\ ~Startuje(head) THEN "okienko" ELSE "spoczynek",
           CASE centrum /= "brak" -> "restart_guardian.main: stara wersja juz dziala (Centrum ze skrotu odpowiada)"
             [] Startuje(head) -> "restart_guardian.main: stara wersja odpowiada, karta pokaze NOWA_WERSJA_NIE_WYSTARTOWALA"
             [] OTHER -> "restart_guardian.main: stara wersja nie odpowiada, opiekun pokazuje okienko")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* show_problem: natywne okienko not_started_after_update, potem return 1. Okienko pokazuje się
\* w tym samym kroku kodu, w którym opiekun o nim rozstrzyga (SkrotOddajePort na nie czeka).
OpiekunOkienko ==
    /\ pc = "okienko"
    /\ Idz("spoczynek", "restart_guardian.main: show_problem pokazuje okienko not_started_after_update (return 1)")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* --- Poza kodem aktualizacji ----------------------------------------------------

\* Komputer gaśnie albo proces ginie (Centrum, opiekun albo skrót w trakcie cofania). Na
\* dysku zostaje stan z ostatniego kroku, razem z dziennikiem i jego kopią.
Wylacz ==
    /\ Wylaczenie
    /\ pc /= "spoczynek"
    /\ centrum' = "brak"
    /\ skrot' = "brak"
    /\ pc' = "spoczynek"
    /\ krok' = "komputer gasnie w tym kroku"
    /\ UNCHANGED <<dysk, nowa, klikniecia, slady, cofa, skrotyWTrakcie>>

\* Mija GUARDIAN_LEASE_S od zapisu opiekun_do. Założenie (Scope): opiekun kończy się przed tym
\* terminem, więc termin mija dopiero wtedy, gdy nic już nie działa.
\* Skrót trzyma port przez ułamek sekundy, a termin to 10 minut, więc nie mija w tej chwili.
DzierzawaMija ==
    /\ pc = "spoczynek"
    /\ skrot = "brak"
    /\ dzierzawa = "wazna"
    /\ dzierzawa' = "brak"
    /\ krok' = "mija termin opiekuna (GUARDIAN_LEASE_S)"
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, centrum, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie>>

\* Tata uruchamia Centrum skrótem z pulpitu (launcher._start z klonu). Skrót zajmuje port
\* (listen_locally) i czyta dziennik (ToolClone.interrupted_update), zanim wczyta biblioteki.
\* Gdy nic nie działa, nikt inny nie walczy o port, więc cały start skrótu to jeden krok.
Skrot ==
    /\ pc = "spoczynek"
    /\ centrum = "brak"
    /\ skrot = "brak"
    /\ \/ /\ dziennik = "brak"
          /\ Startuje(head)
          /\ centrum' = head
          /\ krok' = "tata uruchamia Centrum skrotem z pulpitu"
          /\ UNCHANGED <<dysk, nowa, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie>>
       \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "wazna"
          /\ krok' = "skrot: dziennik z terminem opiekuna, Komunikat AKTUALIZACJA_SIE_KONCZY"
          /\ UNCHANGED <<dysk, nowa, centrum, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie>>
       \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "brak"
          /\ Cofaj("skrot", "skrot: dziennik 'Aktualizacja w toku', launcher._roll_back przed startem")
          /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* Opiekun ponownego startu działa (od Restart do jego ostatniego kroku), a port jest wolny:
\* stare Centrum już się zamknęło, a nowe jeszcze go nie zajęło.
DzialaOpiekun ==
    \/ pc \in {"opiekun_port", "opiekun_start", "opiekun_koniec", "opiekun_port_stara", "opiekun_start_stara"}
    \/ /\ pc \in {"cofanie_usun", "cofanie_reset", "cofanie_przywroc", "koniec_dziennika"}
       /\ cofa \in {"opiekun", "opiekun_bez_portu"}

\* Tata klika skrót, gdy opiekun działa (karta pokazuje ponowny start): launcher._start
\* z klonu (bez --bez-okienek) zajmuje wolny port w listen_locally. Gdy port trzyma
\* Centrum, bind rzuca, a skrót tylko pyta health: nic na dysku się nie zmienia, więc tego
\* przypadku model nie opisuje.
SkrotWTrakcie ==
    /\ DzialaOpiekun
    /\ centrum = "brak"
    /\ skrot = "brak"
    /\ skrotyWTrakcie < MaxSkrotowWTrakcie
    /\ skrot' = "ma_port"
    /\ skrotyWTrakcie' = skrotyWTrakcie + 1
    /\ krok' = "tata klika skrot w trakcie ponownego startu: launcher._start zajmuje port (listen_locally)"
    /\ UNCHANGED <<dysk, nowa, centrum, pc, klikniecia, slady, cofa>>

\* launcher._start po listen_locally: ToolClone.interrupted_update i guardian_may_run. Z terminem
\* opiekuna listener.close() i Komunikat update_finishing. Bez dziennika (opiekun już go usunął
\* po cofnięciu) skrót startuje Centrum i zostaje na porcie. Dziennik bez terminu nie zdarza się,
\* póki opiekun działa (DzierzawaMija).
SkrotOddajePort ==
    /\ skrot = "ma_port"
    /\ pc /= "okienko"
    /\ skrot' = "brak"
    /\ \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "wazna"
          /\ UNCHANGED centrum
          /\ krok' = "skrot: dziennik z terminem opiekuna, listener.close(), Komunikat AKTUALIZACJA_SIE_KONCZY"
       \/ /\ dziennik = "brak"
          /\ centrum' = IF Startuje(head) THEN head ELSE centrum
          /\ krok' = "skrot: dziennika juz nie ma, Centrum ze skrotu startuje i zostaje na porcie"
    /\ UNCHANGED <<dysk, nowa, pc, klikniecia, slady, cofa, skrotyWTrakcie>>

\* Kroki kodu: Centrum, opiekun i skrót, który cofa albo oddaje port.
Program ==
    \/ Pobranie \/ KopiaPlikow \/ CheckoutHead \/ Scalanie
    \/ PrzywroceniePoOdmowie \/ PrzywroceniePoScaleniu \/ Instalacja \/ InstalacjaKoniec
    \/ CofanieUsun \/ CofanieReset \/ CofaniePrzywroc \/ KoniecDziennika
    \/ Restart \/ OpiekunPort \/ OpiekunStart \/ OpiekunKoniec \/ OpiekunPortStara \/ OpiekunStartStara
    \/ OpiekunOkienko
    \/ SkrotOddajePort

Next == Program \/ Klik \/ Wylacz \/ DzierzawaMija \/ Skrot \/ SkrotWTrakcie

\* Działający kod robi następny krok, tata klika, póki Centrum działa i ma kliknięcia albo dziennik
\* jest w toku, uruchamia skrót, póki Centrum nie działa, a termin opiekuna kiedyś mija, także gdy
\* tata w międzyczasie klika. Awarie Gita i kopiowania są przejściowe: cofanie ponawiane bez końca
\* kiedyś się udaje (silna sprawiedliwość).
Sprawiedliwosc ==
    /\ WF_vars(Program)
    /\ WF_vars(Klik)
    /\ WF_vars(Skrot)
    /\ SF_vars(DzierzawaMija)
    /\ SF_vars(CofanieResetUdane)
    /\ SF_vars(CofaniePrzywrocUdane)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc


\* --- Postęp ------------------------------------------------------------------

\* Dziennik w toku w końcu znika: skrót, opiekun, Centrum albo następne kliknięcie kończy albo cofa
\* aktualizację.
\* Gdy znika w spoczynku, TataMaDzialajacaWersje wymaga wersji, która startuje, i pliku taty.
\* Założenie: komputer gaśnie skończenie wiele razy.
Postep == <>[][~Wylacz]_vars => (dziennik = "w_toku" ~> dziennik = "brak")

\* slady tylko rosną, więc <>Znane to przebieg, w którym awaria znanego znaleziska kiedyś się zdarzyła.
PostepPozaZnanymi == Postep \/ <>Znane

=============================================================================
