"""MAVLink connection wrapper around pymavlink.

Provides a context manager that establishes a connection with retry/backoff,
sets `source_system=254` (GCS), enables autoreconnect, and waits for a heartbeat
before yielding. Designed to be the single place every CLI command opens a link.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from mower_rover.logging_setup.setup import get_logger


@dataclass(frozen=True)
class ConnectionConfig:
    """How to connect to the autopilot.

    `endpoint` follows pymavlink mavutil syntax, e.g.:
      - SITL UDP:   "udp:127.0.0.1:14550"
      - SiK radio:  "COM5" (Windows) or "/dev/ttyUSB0" (Linux)
    """

    endpoint: str = "udp:127.0.0.1:14550"
    baud: int = 57600
    source_system: int = 254
    heartbeat_timeout_s: float = 10.0
    retry_attempts: int = 3
    retry_backoff_s: float = 1.0


@contextmanager
def open_link(config: ConnectionConfig) -> Iterator[Any]:
    """Open a MAVLink link, wait for a heartbeat, yield the connection, then close.

    Raises `ConnectionError` if no heartbeat is received after all retries.
    """
    # Imported lazily so the module is importable in environments where pymavlink
    # is not yet installed (e.g. doc-only checks).
    from pymavlink import mavutil

    log = get_logger("mavlink").bind(endpoint=config.endpoint)
    last_error: Exception | None = None

    for attempt in range(1, config.retry_attempts + 1):
        log.info("connect_attempt", attempt=attempt, of=config.retry_attempts)
        try:
            conn = mavutil.mavlink_connection(
                config.endpoint,
                baud=config.baud,
                source_system=config.source_system,
                autoreconnect=True,
            )
            hb = conn.wait_heartbeat(timeout=config.heartbeat_timeout_s)
            if hb is None:
                raise ConnectionError("no heartbeat within timeout")
            log.info(
                "heartbeat_received",
                target_system=conn.target_system,
                target_component=conn.target_component,
                vehicle_type=hb.type,
                autopilot=hb.autopilot,
            )
            try:
                yield conn
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
            return
        except Exception as exc:  # noqa: BLE001 - we re-raise after retries
            last_error = exc
            log.warning("connect_failed", attempt=attempt, error=str(exc))
            if attempt < config.retry_attempts:
                time.sleep(config.retry_backoff_s * attempt)

    raise ConnectionError(
        f"Failed to connect to {config.endpoint} after "
        f"{config.retry_attempts} attempts: {last_error}"
    )


__all__ = ["ConnectionConfig", "open_link"]
