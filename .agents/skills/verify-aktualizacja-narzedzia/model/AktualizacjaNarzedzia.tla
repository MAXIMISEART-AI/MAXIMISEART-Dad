------------------------- MODULE AktualizacjaNarzedzia -------------------------
(***************************************************************************)
(* Aktualizacja narzędzia z Centrum rozliczeń (ADR 0009) przy każdej       *)
(* kolejności awarii.                                                      *)
(*                                                                         *)
(* Obietnica: gdy aktualizacja się skończy, przerwie albo komputer zgaśnie, *)
(* klon narzędzia stoi na wersji, która wystartuje ze skrótu taty, a plik  *)
(* taty w config/ (dziś worker_mapping.yaml) ma treść taty.                *)
(*                                                                         *)
(* Jedna akcja to jeden krok kodu, który kończy się, zanim zacznie się     *)
(* następny: jedno polecenie Gita, jedno shutil.copy2, jedno uruchomienie  *)
(* pip, jeden proces opiekuna. Komentarz przy akcji wskazuje ten kod w     *)
(* src/rozliczenia/centrum/: tool_update.py, tool_updates.py,              *)
(* restart_guardian.py (z cofaniem nowej wersji, która nie wystartuje).   *)
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
    kopia,         \* kopia pliku taty w katalogu tymczasowym aktualizacji (work/pliki-taty): "brak" albo "taty"
    biblioteki,    \* biblioteki Pythona taty: "stare", "czesciowe" (pip przerwany albo nieudany), "nowe"
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
    cofa           \* kto woła _roll_back: "centrum" (ToolClone.update) albo "opiekun" (restart_guardian._rolled_back)

dysk == <<head, plikTaty, kopia, biblioteki>>
nowa == <<nowaUsuwaPlikTaty, nowaZmieniaWymagania, nowaStartuje>>
vars == <<dysk, nowa, centrum, pc, klikniecia, krok, slady, cofa>>

ZnaneZnaleziska == {"reset", "kopiowanie", "wylaczenie"}

Kroki == {"spoczynek", "pobieranie", "kopia_plikow", "checkout_head", "scalanie",
          "przywrocenie_po_odmowie", "przywrocenie_po_scaleniu", "instalacja",
          "instalacja_trwa", "cofanie_usun", "cofanie_reset", "cofanie_przywroc",
          "restart", "opiekun_port", "opiekun_start", "opiekun_port_stara",
          "opiekun_start_stara"}

TypeOK ==
    /\ head \in {"stara", "nowa"}
    /\ plikTaty \in {"taty", "wzor", "brak"}
    /\ kopia \in {"brak", "taty"}
    /\ biblioteki \in {"stare", "czesciowe", "nowe"}
    /\ nowa \in BOOLEAN \X BOOLEAN \X BOOLEAN
    /\ centrum \in {"stara", "nowa", "brak"}
    /\ pc \in Kroki
    /\ klikniecia \in 0..MaxKlikniec
    /\ slady \subseteq ZnaneZnaleziska
    /\ cofa \in {"centrum", "opiekun"}

\* Czy wersja wystartuje ze skrótu taty (run_centrum.py z klonu). Założenie: stara
\* wersja startuje z każdymi bibliotekami, bo requirements.txt ma tylko dolne granice
\* wersji (docstring tool_update.py), więc pip nowej wersji jej nie psuje.
Startuje(wersja) ==
    \/ wersja = "stara"
    \/ /\ nowaStartuje
       /\ (~nowaZmieniaWymagania \/ biblioteki = "nowe")

\* --- Obietnica --------------------------------------------------------------

TataMaDzialajacaWersje ==
    pc = "spoczynek" => (Startuje(head) /\ plikTaty = "taty")

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

\* --- ToolUpdates.start, ToolUpdates._result ----------------------------------

\* RunHost.begin_update zajmuje miejsce „jedno naraz”; restart_guardian.prepare
\* kopiuje opiekuna do nowego katalogu tymczasowego (work), zanim klon się zmieni.
Klik ==
    /\ pc = "spoczynek"
    /\ centrum /= "brak"
    /\ klikniecia < MaxKlikniec
    /\ klikniecia' = klikniecia + 1
    /\ kopia' = "brak"
    /\ Idz("pobieranie", "ToolUpdates.start: tata klika 'Zaktualizuj narzedzie'")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum>>

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
          /\ Idz(IF nowaUsuwaPlikTaty THEN "kopia_plikow" ELSE "scalanie",
                 IF nowaUsuwaPlikTaty
                 THEN "ToolClone.update: fetch pobral main, ktory usuwa plik taty z config/"
                 ELSE "ToolClone.update: fetch pobral nowy main")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside: shutil.copy2(git.root / name, backup / name), przed try.
KopiaPlikow ==
    /\ pc = "kopia_plikow"
    /\ \/ /\ kopia' = "taty"
          /\ Idz("checkout_head", "_DadFiles.set_aside: kopia pliku taty do work/pliki-taty")
       \/ /\ AwariaKopiowania
          /\ kopia' = kopia
          /\ Idz("spoczynek", "_DadFiles.set_aside: copy2 do kopii rzuca OSError (NIEOCZEKIWANY_BLAD), klon bez zmian")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside: git checkout HEAD -- <plik taty>, w try.
CheckoutHead ==
    /\ pc = "checkout_head"
    /\ \/ /\ plikTaty' = "wzor"
          /\ Idz("scalanie", "_DadFiles.set_aside: git checkout HEAD -- przywraca plikowi tresc z repozytorium")
       \/ /\ AwariaGita
          /\ plikTaty' = plikTaty
          /\ Idz("przywrocenie_po_odmowie", "_DadFiles.set_aside: git checkout HEAD -- rzuca GitFailed")
    /\ UNCHANGED <<head, kopia, biblioteki, nowa, centrum, klikniecia>>

\* ToolClone.update: git merge --ff-only, w bloku set_aside.
Scalanie ==
    /\ pc = "scalanie"
    /\ \/ /\ head' = "nowa"
          /\ plikTaty' = IF nowaUsuwaPlikTaty THEN "brak" ELSE plikTaty
          /\ Idz(IF nowaUsuwaPlikTaty THEN "przywrocenie_po_scaleniu" ELSE "instalacja",
                 "ToolClone.update: git merge --ff-only przesuwa klon na nowy main")
       \/ /\ OdmowaScalenia
          /\ UNCHANGED <<head, plikTaty>>
          /\ Idz(IF nowaUsuwaPlikTaty THEN "przywrocenie_po_odmowie" ELSE "spoczynek",
                 "ToolClone.update: git merge --ff-only odmawia (ZMIANY_NA_KOMPUTERZE)")
    /\ UNCHANGED <<kopia, biblioteki, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside, finally, gdy klon się nie przesunął: copy2(backup / name, target).
PrzywroceniePoOdmowie ==
    /\ pc = "przywrocenie_po_odmowie"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): plik taty wraca z kopii, klon bez zmian")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Slad("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (NIEOCZEKIWANY_BLAD)", "kopiowanie")
    /\ UNCHANGED <<head, kopia, biblioteki, nowa, centrum, klikniecia>>

\* _DadFiles.set_aside, finally, po przesunięciu klonu. Wyjątek stąd wychodzi z
\* update() przed try wokół _install_libraries, więc nic nie wywołuje _roll_back.
PrzywroceniePoScaleniu ==
    /\ pc = "przywrocenie_po_scaleniu"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("instalacja", "_DadFiles.set_aside (finally): plik taty wraca z kopii")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Slad("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError; update() konczy sie bez _roll_back (NIEOCZEKIWANY_BLAD)", "kopiowanie")
    /\ UNCHANGED <<head, kopia, biblioteki, nowa, centrum, klikniecia>>

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
    /\ UNCHANGED <<head, plikTaty, kopia, nowa, centrum, klikniecia>>

InstalacjaKoniec ==
    /\ pc = "instalacja_trwa"
    /\ \/ /\ biblioteki' = "nowe"
          /\ Idz("restart", "pip_install: pip skonczyl, wynik ok")
       \/ /\ AwariaBibliotek
          /\ UNCHANGED biblioteki
          /\ Cofaj("centrum", "pip_install zwraca False, update() wola _roll_back (INSTALACJA_BIBLIOTEK)")
    /\ UNCHANGED <<head, plikTaty, kopia, nowa, centrum, klikniecia>>

\* --- _roll_back ---------------------------------------------------------------

\* (git.root / name).unlink() dla każdego pliku z kopii.
CofanieUsun ==
    /\ pc = "cofanie_usun"
    /\ plikTaty' = IF kopia = "taty" THEN "brak" ELSE plikTaty
    /\ Idz("cofanie_reset", "_roll_back: plik taty znika z klonu przed reset")
    /\ UNCHANGED <<head, kopia, biblioteki, nowa, centrum, klikniecia>>

\* git reset --keep --quiet before, w try. Stara wersja śledzi plik taty, więc reset
\* zapisuje jej treść z repozytorium.
CofanieReset ==
    /\ pc = "cofanie_reset"
    /\ \/ /\ head' = "stara"
          /\ plikTaty' = IF kopia = "taty" THEN "wzor" ELSE plikTaty
          /\ Idz("cofanie_przywroc", "_roll_back: git reset --keep cofa klon do starego commitu")
       \/ /\ AwariaGita
          /\ UNCHANGED <<head, plikTaty>>
          /\ Slad("cofanie_przywroc", "_roll_back: git reset --keep rzuca GitFailed, klon zostaje na nowym commicie", "reset")
    /\ UNCHANGED <<kopia, biblioteki, nowa, centrum, klikniecia>>

\* finally: shutil.copy2(backup / name, target). Biblioteki zostają (docstring tool_update.py).
\* Gdy reset się nie udał, po finally wychodzi GitFailed. Centrum zamienia każdy wyjątek
\* na NIEOCZEKIWANY_BLAD; opiekun (_rolled_back zwraca False) pokazuje okienko i kończy się.
\* Po udanym cofnięciu opiekun startuje starą wersję.
CofaniePrzywroc ==
    /\ pc = "cofanie_przywroc"
    /\ \/ /\ plikTaty' = IF kopia = "taty" THEN "taty" ELSE plikTaty
          /\ Idz(IF cofa = "opiekun" /\ head = "stara" THEN "opiekun_port_stara" ELSE "spoczynek",
                 CASE cofa = "centrum" -> "_roll_back (finally): plik taty wraca z kopii; Centrum pokazuje Komunikat porazki"
                   [] head = "stara" -> "_roll_back (finally): plik taty wraca z kopii; opiekun cofnal klon"
                   [] OTHER -> "_roll_back (finally): plik taty wraca z kopii; GitFailed, opiekun pokazuje okienko (return 1)")
       \/ /\ AwariaKopiowania
          /\ kopia = "taty"
          /\ plikTaty' = plikTaty
          /\ Slad("spoczynek",
                  IF cofa = "centrum"
                  THEN "_roll_back (finally): copy2 z kopii rzuca OSError (NIEOCZEKIWANY_BLAD)"
                  ELSE "_roll_back (finally): copy2 z kopii rzuca OSError, opiekun pokazuje okienko (return 1)",
                  "kopiowanie")
    /\ UNCHANGED <<head, kopia, biblioteki, nowa, centrum, klikniecia>>

\* --- ToolUpdates._restart, restart_guardian.main ------------------------------

\* Gdy opiekun nie wystartuje, Centrum działa dalej i samo cofa klon
\* (ToolUpdates._rolled_back -> ToolClone.roll_back), wynik NIEOCZEKIWANY_BLAD.
Restart ==
    /\ pc = "restart"
    /\ \/ /\ AwariaOpiekuna
          /\ UNCHANGED centrum
          /\ Cofaj("centrum", "ToolUpdates._restart: restart_guardian.launch rzuca; Centrum dziala dalej i wola _roll_back (NIEOCZEKIWANY_BLAD)")
       \/ /\ centrum' = "brak"
          /\ Idz("opiekun_port", "ToolUpdates._restart: opiekun startuje, Shutdown.close_for_update zamyka Centrum")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* write_result, potem _port_released. Gdy port nie zwolni się, nikt nie sprawdził
\* nowej wersji: write_result z NIEOCZEKIWANY_BLAD i _rolled_back, a po nim to samo
\* co po nowej wersji, która nie odpowiedziała (OpiekunPortStara).
OpiekunPort ==
    /\ pc = "opiekun_port"
    /\ \/ /\ AwariaOpiekuna
          /\ Cofaj("opiekun", "restart_guardian.main: port nie zwolniony w PORT_TIMEOUT_S; write_result NIEOCZEKIWANY_BLAD, potem _rolled_back")
       \/ Idz("opiekun_start", "restart_guardian.main: port zwolniony")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia>>

\* _start_centrum, potem _answers. Gdy nowa wersja nie odpowie: _stop, write_result
\* z NOWA_WERSJA_NIE_WYSTARTOWALA i _rolled_back, czyli ToolClone.roll_back -> _roll_back.
OpiekunStart ==
    /\ pc = "opiekun_start"
    /\ \/ /\ Startuje(head)
          /\ centrum' = head
          /\ Idz("spoczynek", "restart_guardian.main: nowa wersja odpowiada na /api/health")
       \/ /\ ~Startuje(head)
          /\ UNCHANGED centrum
          /\ Cofaj("opiekun", "restart_guardian.main: nowa wersja nie odpowiada w START_TIMEOUT_S; _stop, potem _rolled_back")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

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

\* Kroki od git checkout HEAD do końca cofania przez opiekuna: klon albo plik taty jest
\* w połowie zmiany, albo nikt jeszcze nie sprawdził, czy nowa wersja startuje.
\* Wyłączenie w nich to znane znalezisko "wylaczenie".
OknoWylaczenia == Kroki \ {"spoczynek", "pobieranie", "kopia_plikow", "checkout_head",
                            "opiekun_port_stara", "opiekun_start_stara"}

\* Komputer gaśnie albo proces ginie. Na dysku zostaje stan z ostatniego kroku;
\* nikt nie czyta potem work/pliki-taty ani nie kończy cofania.
Wylacz ==
    /\ Wylaczenie
    /\ pc /= "spoczynek"
    /\ centrum' = "brak"
    /\ IF pc \in OknoWylaczenia
       THEN Slad("spoczynek", "komputer gasnie w tym kroku", "wylaczenie")
       ELSE Idz("spoczynek", "komputer gasnie w tym kroku")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* Tata uruchamia Centrum skrótem z pulpitu (launcher.main z klonu).
Skrot ==
    /\ pc = "spoczynek"
    /\ centrum = "brak"
    /\ Startuje(head)
    /\ centrum' = head
    /\ krok' = "tata uruchamia Centrum skrotem z pulpitu"
    /\ UNCHANGED <<dysk, nowa, pc, klikniecia, slady, cofa>>

Next ==
    \/ Klik \/ Pobranie \/ KopiaPlikow \/ CheckoutHead \/ Scalanie
    \/ PrzywroceniePoOdmowie \/ PrzywroceniePoScaleniu \/ Instalacja \/ InstalacjaKoniec
    \/ CofanieUsun \/ CofanieReset \/ CofaniePrzywroc
    \/ Restart \/ OpiekunPort \/ OpiekunStart \/ OpiekunPortStara \/ OpiekunStartStara
    \/ Wylacz \/ Skrot

Spec == Init /\ [][Next]_vars

=============================================================================
