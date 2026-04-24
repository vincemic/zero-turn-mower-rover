"""Structured logging setup for mower-rover CLIs.

JSON file sink + rich console renderer with a per-invocation correlation ID.
Avoid shadowing stdlib `logging` by living under `logging_setup`.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog


def _default_log_dir() -> Path:
    """Return the OS-appropriate per-user log directory."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "mower-rover" / "logs"
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "mower-rover" / "logs"


def configure_logging(
    *,
    correlation_id: str | None = None,
    log_dir: Path | None = None,
    console_level: str = "INFO",
) -> tuple[str, Path]:
    """Configure structlog with a JSON file sink + rich console renderer.

    Returns the (correlation_id, log_file_path) used for this invocation.
    """
    cid = correlation_id or uuid.uuid4().hex[:12]
    target_dir = log_dir or _default_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_file = target_dir / f"mower-{stamp}-{cid}.jsonl"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(message)s"))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.DEBUG)
    console_handler.setLevel(console_level.upper())

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(correlation_id=cid)
    return cid, log_file


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return logger  # type: ignore[no-any-return]
