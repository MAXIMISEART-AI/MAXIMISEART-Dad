"""DadConfig — env var loader + path resolver.

Rule #6 Portability: ZERO hardcoded C:\\Users\\Arek\\. All paths via env vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class DadConfig:
    runtime_path: Path
    vault_path: Path
    excel_path: Path
    reports_dir: Path
    logs_dir: Path
    state_dir: Path
    learning_dir: Path

    run_time: str = "06:30"
    red_team_threshold: float = 0.66
    high_stakes_pln: float = 500.0
    fatigue_critical_days: int = 3
    brain_retention_days: int = 90
    oauth_token_path: Path | None = None

    use_real_api: bool = False
    cross_lineage_vote: bool = False
    fatigue_monitor: bool = True

    log_level: str = "INFO"

    employees: dict = field(default_factory=dict)
    code_mapping: dict = field(default_factory=dict)
    excel_schema: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "DadConfig":
        if env_file is None:
            env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file)

        runtime = Path(os.path.expandvars(os.environ.get(
            "DAD_RUNTIME_PATH",
            str(Path.home() / "MAXIMISEART-Dad-runtime"),
        )))

        vault = Path(os.path.expandvars(os.environ.get("DAD_VAULT_PATH", str(runtime / "vault"))))
        excel = Path(os.path.expandvars(os.environ.get("DAD_EXCEL_PATH", "")))
        reports = Path(os.path.expandvars(os.environ.get("DAD_REPORTS_DIR", str(vault / "reports"))))
        logs = Path(os.path.expandvars(os.environ.get("DAD_LOGS_DIR", str(runtime / "logs"))))
        state = runtime / "state"
        learning = runtime / "learning"

        config_dir = PROJECT_ROOT / "config"
        employees = _load_yaml(config_dir / "employees.yaml")
        code_mapping = _load_yaml(config_dir / "code_mapping.yaml")
        excel_schema = _load_yaml(config_dir / "excel_schema.yaml")
        schedule = _load_yaml(config_dir / "schedule.yaml")

        return cls(
            runtime_path=runtime,
            vault_path=vault,
            excel_path=excel,
            reports_dir=reports,
            logs_dir=logs,
            state_dir=state,
            learning_dir=learning,
            run_time=os.environ.get("DAD_RUN_TIME", schedule.get("daily_run_time", "06:30")),
            red_team_threshold=float(os.environ.get("DAD_RED_TEAM_THRESHOLD", "0.66")),
            high_stakes_pln=float(os.environ.get("DAD_HIGH_STAKES_PLN", "500")),
            fatigue_critical_days=int(os.environ.get("DAD_FATIGUE_CRITICAL_DAYS", "3")),
            brain_retention_days=int(os.environ.get("DAD_BRAIN_RETENTION_DAYS", "90")),
            oauth_token_path=Path(os.path.expandvars(os.environ.get(
                "DAD_OAUTH_TOKEN_PATH", str(state / "oauth-token.json")
            ))),
            use_real_api=os.environ.get("DAD_USE_REAL_API", "false").lower() == "true",
            cross_lineage_vote=os.environ.get("DAD_CROSS_LINEAGE_VOTE", "false").lower() == "true",
            fatigue_monitor=os.environ.get("DAD_FATIGUE_MONITOR", "true").lower() == "true",
            log_level=os.environ.get("DAD_LOG_LEVEL", "INFO"),
            employees=employees,
            code_mapping=code_mapping,
            excel_schema=excel_schema,
            schedule=schedule,
        )

    def ensure_runtime_dirs(self) -> None:
        for path in [
            self.runtime_path, self.vault_path, self.reports_dir,
            self.logs_dir, self.state_dir, self.learning_dir,
            self.state_dir / "excel-snapshots",
            self.vault_path / "pracownicy",
            self.vault_path / "prace",
            self.vault_path / "lokacje",
            self.vault_path / "reports",
            self.vault_path / "learning",
        ]:
            path.mkdir(parents=True, exist_ok=True)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
