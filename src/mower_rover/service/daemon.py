"""Health monitoring daemon with systemd notify integration.

Runs a periodic health snapshot loop (thermal + power + disk), sends
``sd_notify`` READY/WATCHDOG heartbeats, and shuts down cleanly on
SIGTERM or SIGINT.  ``sdnotify`` is an optional dependency — the daemon
degrades to a no-op notifier when the package is not installed.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

from mower_rover.health.disk import read_disk_usage
from mower_rover.health.power import read_power_state
from mower_rover.health.thermal import read_thermal_zones
from mower_rover.logging_setup.setup import get_logger

try:
    import sdnotify

    _notifier: object = sdnotify.SystemdNotifier()
except ImportError:

    class _NoOpNotifier:
        def notify(self, state: str) -> None: ...

    _notifier = _NoOpNotifier()


def run_daemon(
    *,
    health_interval_s: int,
    sysroot: Path = Path("/"),
    _shutdown_event: threading.Event | None = None,
) -> None:
    """Run the health monitoring daemon loop.

    Sends ``READY=1`` on startup, ``WATCHDOG=1`` heartbeat every 15 s,
    and collects health snapshots every *health_interval_s* seconds.
    Exits cleanly on SIGTERM or SIGINT.

    The *_shutdown_event* parameter is for testing only — when provided the
    daemon waits on that event instead of installing signal handlers (which
    require the main thread).
    """
    log = get_logger("service.daemon")
    shutdown = _shutdown_event or threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("daemon_signal_received", signal=signum)
        shutdown.set()

    # Signal handlers can only be registered from the main thread.
    if _shutdown_event is None and threading.current_thread() is threading.main_thread():
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    _notifier.notify("READY=1")  # type: ignore[attr-defined]
    log.info("daemon_started", health_interval_s=health_interval_s)

    # Force immediate first health check and watchdog ping.
    last_health = -float(health_interval_s + 1)
    last_watchdog = -16.0

    while not shutdown.is_set():
        now = time.monotonic()

        # Watchdog heartbeat every 15 s (< WatchdogSec=30).
        if now - last_watchdog >= 15.0:
            _notifier.notify("WATCHDOG=1")  # type: ignore[attr-defined]
            last_watchdog = now

        # Health snapshot every health_interval_s.
        if now - last_health >= health_interval_s:
            try:
                thermal = read_thermal_zones(sysroot)
                power = read_power_state(sysroot)
                disk = read_disk_usage(sysroot)
                log.info(
                    "daemon_health",
                    op="daemon_health",
                    thermal_zones=len(thermal.zones),
                    power_mode=power.mode_name,
                    disk_mounts=len(disk),
                )
            except Exception as exc:  # noqa: BLE001
                log.error("daemon_health_error", error=str(exc))

            # Flush filesystem buffers (not available on Windows).
            if hasattr(os, "sync"):
                os.sync()

            last_health = now

        shutdown.wait(timeout=1.0)

    log.info("daemon_stopped")
