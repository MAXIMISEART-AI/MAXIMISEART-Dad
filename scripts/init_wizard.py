"""Init wizard for first deployment on tata's Windows machine."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.config import DadConfig  # noqa: E402
from lib.gmail_client import ClientSecretMissingError, run_oauth_flow  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="init_wizard")
    parser.add_argument("--configure", action="store_true", help="Write .env and optional deployment checks.")
    parser.add_argument("--phase-1-setup", action="store_true", help="Run Gmail OAuth only.")
    parser.add_argument("--reauth", action="store_true", help="Re-run Gmail OAuth.")
    parser.add_argument("--env", type=Path, default=PROJECT_ROOT / ".env", help="Path to .env file.")
    parser.add_argument("--runtime-path", type=Path, default=Path.home() / "MAXIMISEART-Dad-runtime")
    parser.add_argument("--vault-path", type=Path, default=None)
    parser.add_argument("--excel-path", type=Path, default=None)
    parser.add_argument("--run-time", default="06:30", help="Daily run time, HH:MM.")
    parser.add_argument("--port", type=int, default=0, help="Local server port for Gmail OAuth callback.")
    parser.add_argument("--client-secret", type=Path, default=None, help="Path to client_secret.json.")
    parser.add_argument("--skip-oauth", action="store_true", help="Skip Gmail OAuth during --configure.")
    parser.add_argument("--test-run", action="store_true", help="Run fixture workflow after writing .env.")
    parser.add_argument("--no-test-run", action="store_true", help="Do not run fixture workflow.")
    parser.add_argument("--install-task", action="store_true", help="Register Windows Task Scheduler task.")
    parser.add_argument("--no-install-task", action="store_true", help="Do not register Task Scheduler task.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.configure:
        return run_configure(args)

    if args.phase_1_setup or args.reauth:
        return run_gmail_oauth(args, DadConfig.load(env_file=args.env))

    print("Użyj jednego z trybów:")
    print("  python scripts/init_wizard.py --configure --excel-path C:\\ścieżka\\raport.xlsx")
    print("  python scripts/init_wizard.py --phase-1-setup")
    return 1


def run_configure(args: argparse.Namespace) -> int:
    runtime_path = args.runtime_path
    vault_path = args.vault_path or runtime_path / "vault"
    reports_dir = vault_path / "reports"
    logs_dir = runtime_path / "logs"

    runtime_path.mkdir(parents=True, exist_ok=True)
    vault_path.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (runtime_path / "state").mkdir(parents=True, exist_ok=True)

    write_env_file(
        args.env,
        runtime_path=runtime_path,
        vault_path=vault_path,
        excel_path=args.excel_path,
        reports_dir=reports_dir,
        logs_dir=logs_dir,
        run_time=args.run_time,
    )

    print(f"Zapisano konfigurację: {args.env}")
    print(f"Runtime: {runtime_path}")
    print(f"Vault: {vault_path}")
    if args.excel_path:
        print(f"Excel: {args.excel_path}")
    else:
        print("Excel: nie ustawiono, wskaż plik przed pierwszym wdrożeniem.")
    print(f"Godzina uruchomienia: {args.run_time}")

    cfg = DadConfig.load(env_file=args.env)
    cfg.ensure_runtime_dirs()

    if not args.skip_oauth:
        oauth_result = run_gmail_oauth(args, cfg)
        if oauth_result != 0:
            return oauth_result

    if args.test_run and not args.no_test_run:
        result = run_fixture_test(args.env)
        if result != 0:
            return result

    if args.install_task and not args.no_install_task:
        return install_task(runtime_path, args.run_time)

    print("Konfiguracja gotowa do testowego uruchomienia.")
    return 0


def write_env_file(
    env_path: Path,
    *,
    runtime_path: Path,
    vault_path: Path,
    excel_path: Path | None,
    reports_dir: Path,
    logs_dir: Path,
    run_time: str,
) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    excel_value = str(excel_path) if excel_path else ""
    content = "\n".join([
        "# MAXIMISEART-Dad local configuration",
        "# Runtime data stays outside git.",
        f"DAD_RUNTIME_PATH={runtime_path}",
        f"DAD_VAULT_PATH={vault_path}",
        f"DAD_EXCEL_PATH={excel_value}",
        f"DAD_REPORTS_DIR={reports_dir}",
        f"DAD_LOGS_DIR={logs_dir}",
        f"DAD_RUN_TIME={run_time}",
        f"DAD_OAUTH_TOKEN_PATH={runtime_path / 'state' / 'oauth-token.json'}",
        "DAD_RED_TEAM_THRESHOLD=0.66",
        "DAD_HIGH_STAKES_PLN=500",
        "DAD_FATIGUE_CRITICAL_DAYS=3",
        "DAD_BRAIN_RETENTION_DAYS=90",
        "DAD_USE_REAL_API=false",
        "DAD_CROSS_LINEAGE_VOTE=false",
        "DAD_FATIGUE_MONITOR=true",
        "DAD_LOG_LEVEL=INFO",
        "",
    ])
    env_path.write_text(content, encoding="utf-8")


def run_gmail_oauth(args: argparse.Namespace, cfg: DadConfig) -> int:
    client_secret = args.client_secret or (PROJECT_ROOT / "credentials" / "client_secret.json")

    print("=" * 60)
    print("MAXIMISEART-Dad - konfiguracja Gmail")
    print("=" * 60)
    print(f"Token będzie zapisany w: {cfg.oauth_token_path}")
    print(f"Client secret: {client_secret}")

    if not client_secret.exists():
        print(f"Brak {client_secret}")
        print("Pobierz plik z Google Cloud Console i zapisz jako credentials/client_secret.json.")
        return 2

    try:
        run_oauth_flow(client_secret, cfg.oauth_token_path, port=args.port)
    except ClientSecretMissingError as e:
        print(str(e))
        return 2
    except Exception as e:
        print(f"Konfiguracja Gmail nie powiodła się: {e}")
        return 3

    print("Token zapisany.")
    return 0


def run_fixture_test(env_path: Path) -> int:
    print("Uruchamiam test na fixture...")
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "daily_workflow.py"),
            "--env",
            str(env_path),
            "--test-mode",
            "--skip-feedback",
        ],
        cwd=str(PROJECT_ROOT),
        text=True,
    )
    return result.returncode


def install_task(runtime_path: Path, run_time: str) -> int:
    script = PROJECT_ROOT / "deploy" / "setup-windows-task.ps1"
    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-RuntimePath",
            str(runtime_path),
            "-ProjectPath",
            str(PROJECT_ROOT),
            "-RunTime",
            run_time,
        ],
        cwd=str(PROJECT_ROOT),
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
