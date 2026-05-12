# MAXIMISEART-Dad

Deployment-ready workflow dla pierwszego wdrożenia u taty: Gmail -> Obsidian -> bezpieczny arkusz buforowy Excela -> raport dzienny -> feedback.

System nie modyfikuje istniejących arkuszy Excela taty. Dopisuje dane tylko do osobnego arkusza:

`MAXIMISEART_DAILY_APPEND`

Realny Gmail i realny Excel podpinacie dopiero razem przy pierwszym wdrożeniu.

## Dla Maksa: pierwszy deploy z tatą

Wymagania na komputerze taty:

- Windows 10/11
- Python 3.11+
- Git
- Obsidian
- Excel z lokalnym plikiem `.xlsx`

Kroki:

```powershell
git clone https://github.com/<konto>/MAXIMISEART-DAD.git
cd MAXIMISEART-DAD
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Uruchom wizard:

```powershell
python scripts\init_wizard.py --configure --excel-path "C:\ścieżka\do\pliku.xlsx" --test-run
```

Jeśli chcesz od razu zarejestrować codzienne uruchamianie:

```powershell
python scripts\init_wizard.py --configure --excel-path "C:\ścieżka\do\pliku.xlsx" --test-run --install-task
```

Gmail:

```powershell
python scripts\init_wizard.py --phase-1-setup
```

Test ręczny po konfiguracji:

```powershell
python scripts\daily_workflow.py --test-mode --date 2026-04-24 --skip-feedback
```

Pre-push verifier dla repo:

```powershell
python scripts\verify_pre_push.py
```

## Co ma działać po wdrożeniu

1. Rano Task Scheduler uruchamia `deploy\run-daily.bat`.
2. System czyta maile z Gmaila albo fixture w trybie testowym.
3. Znani pracownicy trafiają do Obsidian vault.
4. Dane robocze trafiają do arkusza `MAXIMISEART_DAILY_APPEND`.
5. Raport dzienny pojawia się w `vault\reports\YYYY-MM-DD.md`.
6. Tata czyta raport i wpisuje `OK` albo poprawkę w sekcji `## Feedback taty`.

## Dla taty: codzienne użycie

1. Otwórz Obsidian.
2. Wejdź w folder `reports`.
3. Otwórz dzisiejszy raport.
4. Przeczytaj podsumowanie.
5. Na dole wpisz `OK` albo krótką poprawkę.
6. Zapisz plik.

Excel działa jak wcześniej. Nowe wpisy systemu są w arkuszu `MAXIMISEART_DAILY_APPEND`; dotychczasowe arkusze zostają bez zmian.

## Troubleshooting

**Gmail prosi o ponowny dostęp**

Uruchom:

```powershell
python scripts\init_wizard.py --reauth
```

**Excel jest otwarty albo zablokowany**

Zamknij plik Excela na komputerze i poczekaj chwilę na OneDrive. System nie zapisze niczego, jeśli wykryje lock.

**Pusty dzień**

Jeśli nie przyszły maile, raport pokaże `0 emaili`. To nie jest awaria.

**Nieznany pracownik**

Dodaj pracownika do `config\employees.yaml`, potem uruchom workflow ponownie.

**Nieznany kod pracy**

Uzupełnij `config\code_mapping.yaml`. Niepewne wpisy dostaną status `ASK`, zamiast udawać pewność.

## Bezpieczeństwo danych

Nie commituj:

- `.env`
- tokenów Gmail
- `client_secret.json`
- plików Excela
- vaulta Obsidian
- raportów runtime
- logów
- danych pracowników poza kontrolowanym configiem

Repo na GitHubie musi być prywatne.
