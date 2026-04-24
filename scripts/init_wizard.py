"""Init wizard — Phase 1 OAuth setup (minimal).

Phase 5 rozszerzymy do full wizard (Excel path auto-detect + Task Scheduler register).
Phase 1 skupia się tylko na Gmail OAuth bootstrap.

Usage:
    python scripts/init_wizard.py --phase-1-setup          # run OAuth flow
    python scripts/init_wizard.py --reauth                  # re-run OAuth (token expired)
    python scripts/init_wizard.py --phase-1-setup --port 8080  # custom callback port
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.config import DadConfig  # noqa: E402
from lib.gmail_client import ClientSecretMissingError, run_oauth_flow  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="init_wizard")
    parser.add_argument("--phase-1-setup", action="store_true",
                        help="Run Gmail OAuth flow (Phase 1 scope).")
    parser.add_argument("--reauth", action="store_true",
                        help="Re-run OAuth (token expired). Alias dla --phase-1-setup.")
    parser.add_argument("--port", type=int, default=0,
                        help="Local server port dla OAuth callback (0 = auto).")
    parser.add_argument("--client-secret", type=Path, default=None,
                        help="Path do client_secret.json (default: credentials/client_secret.json).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.phase_1_setup or args.reauth):
        print("Użyj: python scripts/init_wizard.py --phase-1-setup")
        print("  (albo --reauth jeśli token wygasł)")
        return 1

    cfg = DadConfig.load()
    cfg.ensure_runtime_dirs()

    project_root = Path(__file__).resolve().parents[1]
    client_secret = args.client_secret or (project_root / "credentials" / "client_secret.json")

    print("=" * 60)
    print("MAXIMISEART-Dad — konfiguracja dostępu do Gmail (Phase 1)")
    print("=" * 60)
    print()
    print(f"Token będzie zapisany w: {cfg.oauth_token_path}")
    print(f"Client secret: {client_secret}")
    print()

    if not client_secret.exists():
        print(f"❌ Brak {client_secret}")
        print()
        print("Jak pobrać client_secret.json:")
        print("  1. Wejdź na https://console.cloud.google.com/apis/credentials")
        print("  2. Utwórz projekt albo wybierz istniejący")
        print("  3. Enable Gmail API (APIs & Services → Library)")
        print("  4. Credentials → Create Credentials → OAuth client ID")
        print("  5. Application type: Desktop app")
        print("  6. Download JSON → zapisz jako credentials/client_secret.json")
        print()
        print("Szczegóły: https://developers.google.com/gmail/api/quickstart/python")
        return 2

    print("🌐 Otwieram przeglądarkę dla autoryzacji Gmail...")
    print("   (zaloguj się + kliknij 'Zezwól na dostęp do Gmaila')")
    print()

    try:
        run_oauth_flow(client_secret, cfg.oauth_token_path, port=args.port)
    except ClientSecretMissingError as e:
        print(f"❌ {e}")
        return 2
    except Exception as e:
        print(f"❌ OAuth flow failed: {e}")
        return 3

    print()
    print("✓ Token zapisany.")
    print(f"  → {cfg.oauth_token_path}")
    print()
    print("Test harvest (ostatnie 24h z prefixem [DAD-TEST]):")
    print("  python scripts/daily_workflow.py --query '[DAD-TEST] newer_than:1d' --dry-run")
    print()
    print("Phase 5 doda: Excel path + Task Scheduler + full init wizard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
