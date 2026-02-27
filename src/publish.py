"""publish.py — Write DeFi pipeline output to JSON files."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import cfg

logger = logging.getLogger(__name__)


def _root() -> Path:
    p = Path(cfg.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def publish_latest(date: str, payload: dict) -> None:
    path = _root() / "latest.json"
    _write(payload, path)
    logger.info(f"Published {path}")


def publish_snapshot(date: str, payload: dict) -> None:
    path = _root() / "history" / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(payload, path)


def _write(payload: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
