------------------------- MODULE AktualizacjaNarzedzia -------------------------
(***************************************************************************)
(* Aktualizacja narzędzia z Centrum rozliczeń (ADR 0009) przy każdej       *)
(* kolejności awarii.                                                      *)
(*                                                                         *)
(* Obietnica: gdy aktualizacja się skończy, przerwie albo komputer zgaśnie, *)
(* klon narzędzia stoi na wersji, która wystartuje ze skrótu taty, a plik  *)
(* taty w config/ (dziś worker_mapping.yaml) ma treść taty. Albo zostaje   *)
(* dziennik „Aktualizacja w toku” z treścią taty, a skrót przy następnym   *)
(* starcie cofa z niego klon (Postep).                                     *)
(*                                                                         *)
(* Jedna akcja to jeden krok kodu, który kończy się, zanim zacznie się     *)
(* następny: jedno polecenie Gita, jedno shutil.copy2, jedno uruchomienie  *)
(* pip, jeden proces opiekuna. Komentarz przy akcji wskazuje ten kod w     *)
(* src/rozliczenia/centrum/: tool_update.py, tool_updates.py,              *)
(* restart_guardian.py (z cofaniem nowej wersji, która nie wystartuje),   *)
(* launcher.py (cofanie przerwanej aktualizacji przy starcie skrótu).      *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS
    MaxKlikniec,        \* ile razy tata klika „Zaktualizuj narzędzie”
    OdmowaScalenia,     \* merge --ff-only odmawia przed zmianą czegokolwiek -> ZMIANY_NA_KOMPUTERZE
    AwariaPobrania,     \* _Git.fetch: brak sieci albo logowanie -> BRAK_POLACZENIA, LOGOWANIE
    AwariaBibliotek,    \* pip_install zwraca False (błąd pip, limit czasu) -> INSTALACJA_BIBLIOTEK
    AwariaOpiekuna,     \* restart_guardian.launch rzuca; stare Centrum nie zwalnia portu w PORT_TIMEOUT_S
    AwariaGita,         \* git checkout HEAD -- (set_aside), git diff (changed), git reset --keep (_roll_back): GitFailed
    AwariaKopiowania,   \* shutil.copy2 pliku taty rzuca OSError (dysk, antywirus, OneDrive)
    NieudanyStart,      \* nowa wersja nie odpowiada w START_TIMEOUT_S, choć ma swoje biblioteki
    Wylaczenie,         \* komputer gaśnie albo proces ginie w dowolnym kroku
    Wybaczone           \* znane znaleziska, które TataMaDzialajacaWersjePozaZnanymi pomija (oczekiwane.json)

VARIABLES
    \* Dysk taty: przeżywa zamknięcie Centrum i wyłączenie komputera.
    head,          \* commit klonu: "stara" (sprzed kliknięcia) albo "nowa" (pobrany main)
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
    cofa           \* kto woła _roll_back: "centrum" (ToolClone.update, ToolUpdates._moved_back), "opiekun"
                   \* (restart_guardian._rolled_back po nowej wersji, która nie odpowiada) albo "opiekun_bez_portu"
                   \* (restart_guardian._rolled_back, gdy port nie został zwolniony: potem nic nie startuje)
                   \* albo "skrot" (launcher._roll_back przy starcie); po odmowie scalenia "centrum"

dysk == <<head, plikTaty, kopia, biblioteki, dziennik, dzierzawa>>
nowa == <<nowaUsuwaPlikTaty, nowaZmieniaWymagania, nowaStartuje>>
vars == <<dysk, nowa, centrum, pc, klikniecia, krok, slady, cofa>>

ZnaneZnaleziska == {"reset", "kopiowanie"}

Kroki == {"spoczynek", "pobieranie", "kopia_plikow", "checkout_head", "scalanie",
          "przywrocenie_po_odmowie", "przywrocenie_po_scaleniu", "instalacja",
          "instalacja_trwa", "cofanie_usun", "cofanie_reset", "cofanie_przywroc",
          "koniec_dziennika", "restart", "opiekun_port", "opiekun_start", "opiekun_koniec",
          "opiekun_port_stara", "opiekun_start_stara"}

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
    /\ cofa \in {"centrum", "opiekun", "opiekun_bez_portu", "skrot"}

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

Idz(nastepny, opis) == pc' = nastepny /\ krok' = opis /\ slady' = slady /\ cofa' = cofa

\* Krok awarii znanego znaleziska: zostawia jej ślad dla Znane.
Slad(nastepny, opis, slad) == pc' = nastepny /\ krok' = opis /\ slady' = slady \cup {slad} /\ cofa' = cofa

\* Wejście w _roll_back; ``kto`` decyduje, co dzieje się po nim.
Cofaj(kto, opis) == pc' = "cofanie_usun" /\ krok' = opis /\ slady' = slady /\ cofa' = kto

\* Klon się nie przesunął, a pliki taty są z powrotem: ToolClone.update usuwa dziennik.
PoOdmowie(opis) == pc' = "koniec_dziennika" /\ krok' = opis /\ slady' = slady /\ cofa' = "centrum"

\* Awaria w Centrum, które działa dalej: tylko ona zostawia znane znalezisko. Ta sama awaria
\* u opiekuna albo przy starcie skrótu zostawia dziennik, a następny start skrótu go kończy.
SladCentrum(nastepny, opis, slad) ==
    IF cofa = "centrum" THEN Slad(nastepny, opis, slad) ELSE Idz(nastepny, opis)

\* --- ToolUpdates.start, ToolUpdates._result ----------------------------------

\* RunHost.begin_update zajmuje miejsce „jedno naraz”; restart_guardian.prepare
\* kopiuje opiekuna do nowego katalogu tymczasowego (work), zanim klon się zmieni.
Klik ==
    /\ pc = "spoczynek"
    /\ centrum /= "brak"
    /\ klikniecia < MaxKlikniec
    /\ klikniecia' = klikniecia + 1
    /\ Idz("pobieranie", "ToolUpdates.start: tata klika 'Zaktualizuj narzedzie'")
    /\ UNCHANGED <<dysk, nowa, centrum>>

\* --- ToolClone.update ---------------------------------------------------------

\* run.fetch(self.origin), potem after == before, potem _has_local_commits i
\* _changed_tracked_files (te odmowy nie zmieniają klonu, tak jak porażka fetch).
Pobranie ==
    /\ pc = "pobieranie"
    /\ \/ /\ AwariaPobrania
          /\ Idz("spoczynek", "ToolClone.update: fetch nie przeszedl (BRAK_POLACZENIA), klon bez zmian")
       \/ /\ head = "nowa"
          /\ Idz("spoczynek", "ToolClone.update: after == before (AKTUALNA), klon bez zmian")
       \/ /\ head = "stara"
          /\ Idz("kopia_plikow",
                 IF nowaUsuwaPlikTaty
                 THEN "ToolClone.update: fetch pobral main, ktory usuwa plik taty z config/"
                 ELSE "ToolClone.update: fetch pobral nowy main")
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
                 "ToolClone.update: git merge --ff-only przesuwa klon na nowy main")
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
          /\ Slad("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE, tresc taty tylko w dzienniku)", "kopiowanie")
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
          /\ SladCentrum("cofanie_przywroc", "_roll_back: git reset --keep rzuca GitFailed, klon zostaje na nowym commicie", "reset")
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
          /\ Idz(IF head = "stara" THEN "koniec_dziennika" ELSE "spoczynek",
                 CASE head = "stara" -> "_roll_back (finally): plik taty wraca z kopii"
                   [] cofa = "centrum" -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, Centrum pokazuje COFNIECIE_NIEUDANE"
                   [] cofa = "skrot" -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, skrot konczy sie Komunikatem startu"
                   [] OTHER -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, opiekun pokazuje okienko (return 1)")
       \/ /\ AwariaKopiowania
          /\ kopia = "taty"
          /\ plikTaty' = plikTaty
          /\ SladCentrum("spoczynek",
                  CASE cofa = "centrum" -> "_roll_back (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE, tresc taty tylko w dzienniku)"
                    [] cofa = "skrot" -> "_roll_back (finally): copy2 z kopii rzuca OSError, skrot konczy sie Komunikatem startu"
                    [] OTHER -> "_roll_back (finally): copy2 z kopii rzuca OSError, opiekun pokazuje okienko (return 1)",
                  "kopiowanie")
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
          /\ Idz(IF cofa = "opiekun" THEN "opiekun_port_stara" ELSE "spoczynek",
                 CASE cofa = "opiekun" -> "_Journal.end: dziennik znika; opiekun cofnal klon"
                   [] cofa = "opiekun_bez_portu" -> "_Journal.end: dziennik znika; opiekun cofnal klon bez portu, pokazuje okienko (return 1)"
                   [] OTHER -> "_Journal.end: dziennik znika; Centrum pokazuje Komunikat porazki")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, klikniecia>>

\* --- ToolUpdates._restart, restart_guardian.main ------------------------------

\* ToolUpdates._restart; gdy restart_guardian.launch rzuca, ToolUpdates._moved_back woła
\* ToolClone.roll_back (-> _roll_back), a Centrum działa dalej w starej wersji.
\* Przed restart_guardian.launch ToolClone.lease_to_guardian zapisuje w dzienniku opiekun_do.
Restart ==
    /\ pc = "restart"
    /\ dzierzawa' = "wazna"
    /\ \/ /\ AwariaOpiekuna
          /\ UNCHANGED centrum
          /\ Cofaj("centrum", "ToolUpdates._restart: restart_guardian.launch rzuca; _moved_back cofa klon, Centrum dziala dalej")
       \/ /\ centrum' = "brak"
          /\ Idz("opiekun_port", "ToolUpdates._restart: opiekun startuje, Shutdown.close_for_update zamyka Centrum")
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, klikniecia>>

\* _port_released, potem write_result(ok). Bez portu main od razu woła _rolled_back
\* (ToolClone.roll_back -> _roll_back), a po nim pokazuje okienko i niczego nie startuje.
OpiekunPort ==
    /\ pc = "opiekun_port"
    /\ \/ /\ AwariaOpiekuna
          /\ Cofaj("opiekun_bez_portu", "restart_guardian.main: port nie zwolniony w PORT_TIMEOUT_S; _rolled_back bez startu nowej wersji")
       \/ Idz("opiekun_start", "restart_guardian.main: port zwolniony")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* _start_centrum (run_centrum.py --bez-okienek: skrót bez cofania), potem _answers. Gdy nowa
\* wersja nie odpowie: _stop, write_result z NOWA_WERSJA_NIE_WYSTARTOWALA i _rolled_back, czyli
\* ToolClone.roll_back -> _roll_back.
OpiekunStart ==
    /\ pc = "opiekun_start"
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
\* Każda porażka kończy się okienkiem not_started_after_update.
OpiekunPortStara ==
    /\ pc = "opiekun_port_stara"
    /\ \/ /\ AwariaOpiekuna
          /\ Idz("spoczynek", "restart_guardian.main: port nie zwolniony po cofnieciu, opiekun pokazuje okienko")
       \/ Idz("opiekun_start_stara", "restart_guardian.main: port zwolniony po cofnieciu")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

OpiekunStartStara ==
    /\ pc = "opiekun_start_stara"
    /\ centrum' = IF Startuje(head) THEN head ELSE "brak"
    /\ Idz("spoczynek",
           IF Startuje(head)
           THEN "restart_guardian.main: stara wersja odpowiada, karta pokaze NOWA_WERSJA_NIE_WYSTARTOWALA"
           ELSE "restart_guardian.main: stara wersja nie odpowiada, opiekun pokazuje okienko")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* --- Poza kodem aktualizacji ----------------------------------------------------

\* Komputer gaśnie albo proces ginie (Centrum, opiekun albo skrót w trakcie cofania). Na
\* dysku zostaje stan z ostatniego kroku, razem z dziennikiem i jego kopią.
Wylacz ==
    /\ Wylaczenie
    /\ pc /= "spoczynek"
    /\ centrum' = "brak"
    /\ Idz("spoczynek", "komputer gasnie w tym kroku")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* Mija GUARDIAN_LEASE_S od zapisu opiekun_do. Założenie (Scope): opiekun kończy się przed tym
\* terminem, więc termin mija dopiero wtedy, gdy nic już nie działa.
DzierzawaMija ==
    /\ pc = "spoczynek"
    /\ dzierzawa = "wazna"
    /\ dzierzawa' = "brak"
    /\ krok' = "mija termin opiekuna (GUARDIAN_LEASE_S)"
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, centrum, pc, klikniecia, slady, cofa>>

\* Tata uruchamia Centrum skrótem z pulpitu (launcher._start z klonu). Skrót zajmuje port
\* (listen_locally) i czyta dziennik (ToolClone.interrupted_update), zanim wczyta biblioteki.
Skrot ==
    /\ pc = "spoczynek"
    /\ centrum = "brak"
    /\ \/ /\ dziennik = "brak"
          /\ Startuje(head)
          /\ centrum' = head
          /\ krok' = "tata uruchamia Centrum skrotem z pulpitu"
          /\ UNCHANGED <<dysk, nowa, pc, klikniecia, slady, cofa>>
       \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "wazna"
          /\ krok' = "skrot: dziennik z terminem opiekuna, Komunikat AKTUALIZACJA_SIE_KONCZY"
          /\ UNCHANGED <<dysk, nowa, centrum, pc, klikniecia, slady, cofa>>
       \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "brak"
          /\ Cofaj("skrot", "skrot: dziennik 'Aktualizacja w toku', launcher._roll_back przed startem")
          /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* Kroki kodu: Centrum, opiekun i skrót, który cofa.
Program ==
    \/ Pobranie \/ KopiaPlikow \/ CheckoutHead \/ Scalanie
    \/ PrzywroceniePoOdmowie \/ PrzywroceniePoScaleniu \/ Instalacja \/ InstalacjaKoniec
    \/ CofanieUsun \/ CofanieReset \/ CofaniePrzywroc \/ KoniecDziennika
    \/ Restart \/ OpiekunPort \/ OpiekunStart \/ OpiekunKoniec \/ OpiekunPortStara \/ OpiekunStartStara

Next == Program \/ Klik \/ Wylacz \/ DzierzawaMija \/ Skrot

\* Działający kod robi następny krok, tata klika, póki Centrum działa i ma kliknięcia, uruchamia
\* skrót, póki Centrum nie działa, a termin opiekuna kiedyś mija. Awarie Gita i kopiowania są
\* przejściowe: cofanie ponawiane bez końca kiedyś się udaje (silna sprawiedliwość).
Sprawiedliwosc ==
    /\ WF_vars(Program)
    /\ WF_vars(Klik)
    /\ WF_vars(Skrot)
    /\ WF_vars(DzierzawaMija)
    /\ SF_vars(CofanieResetUdane)
    /\ SF_vars(CofaniePrzywrocUdane)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc


\* --- Postęp ------------------------------------------------------------------

\* Dziennik w toku w końcu znika: skrót, opiekun albo Centrum kończy albo cofa aktualizację.
\* Gdy znika w spoczynku, TataMaDzialajacaWersje wymaga wersji, która startuje, i pliku taty.
\* Założenie: komputer gaśnie skończenie wiele razy.
Postep == <>[][~Wylacz]_vars => (dziennik = "w_toku" ~> dziennik = "brak")

\* slady tylko rosną, więc <>Znane to przebieg, w którym awaria znanego znaleziska kiedyś się zdarzyła.
PostepPozaZnanymi == Postep \/ <>Znane

=============================================================================
