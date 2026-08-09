from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from constants import LOG_BACKUP_COUNT, LOG_MAX_BYTES
from paths import LOGS_DIR, ensure_runtime_dirs


def configure_logging() -> None:
    ensure_runtime_dirs()
    root = logging.getLogger()
    if any(getattr(handler, "_cloudlight_handler", False) for handler in root.handlers):
        return
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOGS_DIR / "watcher.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler._cloudlight_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)
