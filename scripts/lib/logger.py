"""Structured JSON logger dla daily pipeline.

Pisze do runtime/logs/YYYY-MM-DD.jsonl (append-only).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def get_logger(logs_dir: Path, date: str, level: str = "INFO") -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"dad.{date}")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    log_file = logs_dir / f"{date}.jsonl"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(_JsonFormatter())
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console)

    return logger


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(ZoneInfo("Europe/Warsaw")).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k in ("args", "msg", "levelname", "levelno", "name", "pathname", "filename",
                     "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                     "created", "msecs", "relativeCreated", "thread", "threadName",
                     "processName", "process", "getMessage"):
                continue
            payload[k] = v
        return json.dumps(payload, ensure_ascii=False, default=str)
