# Instalacja

Maks installs the tool once on Dad's computer (README, `Instalacja lokalna`): a Git clone on `main`, Dad's own
konfiguracja wykonawców and Wzorce copied into `config/`, the libraries installed with `py -3 -m pip install -r
requirements.txt`, and the desktop shortcut „Centrum rozliczeń” made by `py -3 install_centrum_shortcut.py`. The
tool lives on Dad's `C:` in his user folder, whose name has a space and a Polish letter, and so does the tool's folder
here.

## Sub-features

- `klon`: the clone of the origin stands on `first`, on branch `main`, in `<root>\Users\Józef Kowalski\MAXIMISEART-Dad`, with `origin` pointing at the tool's GitHub address.
- `pliki-taty`: Dad's `worker_mapping.yaml` and three Wzorce in `config/` leave `git status --porcelain --untracked-files=all` empty (Git ignores them), so an update never sees them as local changes.
- `biblioteki`: `py -3 -m pip install --disable-pip-version-check -r requirements.txt` in the tool's folder exits 0.
- `skrot`: `install_centrum_shortcut.py --folder <root>\Pulpit` exits 0, prints `Utworzono skrót „Centrum rozliczeń”: <folder>…`, makes exactly one `.lnk` there, named `Centrum rozliczeń.lnk` when the machine's ANSI code page can write `ń` (Dad's 1250), and the `.lnk` starts `pythonw.exe` beside this Python with the argument `"<tool>\run_centrum.py"`, works in the tool's folder, and has the icon `<tool>\src\rozliczenia\centrum\centrum-rozliczen.ico,0`.

## How to get to it (user POV)

- Dad never does this himself; Maks does it once at Dad's computer, following README `Instalacja lokalna`. Dad sees only the shortcut on his desktop.

## Driving it with the Windows harness

Preconditions:

- A fresh run root from `windows_tool.prepare`; the tool's folder does not exist yet.

- **Clone.** `git clone --branch main <origin> "<tool>"` with this machine's Git configuration, then `git remote set-url origin https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad.git`. `git rev-parse HEAD` is `versions.first`, `git branch --show-current` is `main`.
- **Dad's files.** Copy every path of `dad_config` (`windows.json`) into `<tool>\config\`. `git status --porcelain --untracked-files=all` is empty.
- **Libraries.** Run `<python> -m pip install --disable-pip-version-check -r requirements.txt` in the tool's folder; exit 0. Output goes to `state/pip-instalacja.txt`.
- **Shortcut.** Run `<python> install_centrum_shortcut.py --folder <root>\Pulpit` in the tool's folder; exit 0 and the printed line. List the folder's `.lnk` files and print the ANSI code page (`GetACP`). When that code page cannot write the name, the one `.lnk` there is the shortcut (labelled `harness:`), and later features start that one. Read the `.lnk` through `WScript.Shell` (`state/skrot.json`): `TargetPath`, `Arguments`, `WorkingDirectory`, `IconLocation` as in the sub-feature.
- **Proof.** `drive.txt` steps `instalacja | …`, `state/skrot.json`, `state/pip-instalacja.txt`.

## Gotchas

- The shortcut goes to `<root>\Pulpit`, never to the real desktop: on a developer's Windows machine the real `Centrum rozliczeń.lnk` would be overwritten.
- `<python>` is the Python that runs the drive. On GitHub it comes from `actions/setup-python`, not from python.org through `py -3` like Dad's. That gap is listed in `SKILL.md` and stays unverified.
- `WScript.Shell`, which `shortcut.py` uses, writes the shortcut's paths through the ANSI code page. GitHub's runner has 1252, which has no `ń`, so there the shortcut is `Centrum rozliczen.lnk` and the step says so; Dad's Polish Windows has 1250. A path character outside Dad's code page would break his shortcut the same way, which is why the tool's folder here uses `ó`, a letter both code pages have.
- Child output is captured with `PYTHONIOENCODING=utf-8`, what Dad's console shows; without it a pipe on an English runner (code page 1252) cannot encode `ś` and the step would fail for a reason Dad never meets.
