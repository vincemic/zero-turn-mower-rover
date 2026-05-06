"""Kiosk application entry point.

Creates SharedState, starts background reader threads (MAVLink,
slow poller), and runs the GTK4 main loop.  Integrates sdnotify for
systemd watchdog support.
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mower_rover.kiosk.state import SharedState
from mower_rover.logging_setup.setup import get_logger

_log = get_logger("kiosk.app")

# ── sdnotify integration ─────────────────────────────────────────────────────

try:
    import sdnotify

    _notifier: object = sdnotify.SystemdNotifier()
except ImportError:

    class _NoOpNotifier:
        def notify(self, state: str) -> None: ...

    _notifier = _NoOpNotifier()


# ── Background reader threads ────────────────────────────────────────────────


def _mavlink_reader_thread(
    state: SharedState,
    shutdown: threading.Event,
    endpoint: str,
) -> None:
    """Run the MAVLink telemetry reader loop."""
    from mower_rover.kiosk.telemetry import mavlink_reader_loop

    try:
        mavlink_reader_loop(state, shutdown, endpoint=endpoint)
    except Exception as exc:  # noqa: BLE001
        if not shutdown.is_set():
            _log.error("mavlink_reader_error", error=str(exc), exc_info=exc)


def _slow_poller_thread(
    state: SharedState,
    shutdown: threading.Event,
    sysroot: Path,
    service_units: list[str] | None = None,
) -> None:
    """Poll slow-changing system state every 5 seconds.

    Reads thermal zones, power state, disk usage, Wi-Fi, and service
    statuses.
    """

    while not shutdown.is_set():
        try:
            _poll_health(state, sysroot, service_units=service_units)
        except Exception as exc:  # noqa: BLE001
            _log.error("slow_poller_error", error=str(exc), exc_info=exc)

        # Sleep in small increments so we respond to shutdown quickly
        for _ in range(50):
            if shutdown.is_set():
                return
            time.sleep(0.1)


def _poll_health(
    state: SharedState,
    sysroot: Path,
    service_units: list[str] | None = None,
) -> None:
    """Single health poll cycle."""
    from mower_rover.health import (
        read_disk_usage,
        read_power_state,
        read_thermal_zones,
        read_wifi_status,
    )

    # Thermal
    thermal = read_thermal_zones(sysroot)
    cpu_temp = 0.0
    gpu_temp = 0.0
    for zone in thermal.zones:
        name_lower = zone.name.lower()
        if "cpu" in name_lower and zone.temp_c > cpu_temp:
            cpu_temp = zone.temp_c
        if "gpu" in name_lower and zone.temp_c > gpu_temp:
            gpu_temp = zone.temp_c

    # Power
    power = read_power_state(sysroot)

    # Disk
    disks = read_disk_usage(sysroot)
    nvme_pct = 0.0
    nvme_free_gb = "--"
    root_pct = 0.0
    for d in disks:
        if d.is_nvme:
            if d.total_gb > 0:
                nvme_pct = (d.used_gb / d.total_gb) * 100
            nvme_free_gb = f"{d.free_gb:.1f} GB"
        if d.mount_point == "/" and d.total_gb > 0:
            root_pct = (d.used_gb / d.total_gb) * 100

    # Wi-Fi
    wifi = read_wifi_status(sysroot)
    if wifi is not None:
        state.update_wifi(wifi.interface, wifi.signal_dbm, wifi.link_quality)

    # Service statuses
    services = _check_services(service_units)

    # Update state with health and storage
    state.update_health(
        cpu_temp_c=round(cpu_temp, 1),
        gpu_temp_c=round(gpu_temp, 1),
        power_mode=power.mode_name or "--",
        fan_status=power.fan_profile or "--",
    )
    state.update_storage(
        nvme_pct=round(nvme_pct, 1),
        nvme_free_gb=nvme_free_gb,
        root_pct=round(root_pct, 1),
    )
    state.update_services(services)


def _unit_display_key(unit: str) -> str:
    """Derive a display key from a systemd unit name.

    Strips ``mower-`` prefix and ``.service`` suffix, then replaces
    ``-`` with ``_``.  For example ``mower-vslam-bridge.service`` →
    ``vslam_bridge``.
    """
    name = unit
    if name.startswith("mower-"):
        name = name[len("mower-"):]
    if name.endswith(".service"):
        name = name[: -len(".service")]
    return name.replace("-", "_")


def _check_services(
    units: list[str] | None = None,
) -> dict[str, str]:
    """Check systemd service statuses for key services.

    Parameters
    ----------
    units:
        List of systemd unit names to check.  When *None*, falls back
        to :func:`~mower_rover.config.jetson._default_kiosk_service_units`.
    """
    import subprocess

    if units is None:
        from mower_rover.config.jetson import _default_kiosk_service_units

        units = _default_kiosk_service_units()

    result: dict[str, str] = {}
    for unit in units:
        key = _unit_display_key(unit)
        try:
            proc = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=5,
            )
            result[key] = proc.stdout.strip() or "unknown"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            result[key] = "unknown"
    return result


# ── Main entry point ─────────────────────────────────────────────────────────


def run_kiosk(
    *,
    mavlink_endpoint: str = "udp:127.0.0.1:14550",
    sysroot: Path = Path("/"),
    _shutdown_event: threading.Event | None = None,
    _state: SharedState | None = None,
) -> None:
    """Start the kiosk operational display.

    Creates SharedState, launches background threads, and runs the GTK4
    main loop.  Sends sdnotify ``READY=1`` once the window is realized
    and ``WATCHDOG=1`` every 15 s via a GLib timer.

    Parameters
    ----------
    mavlink_endpoint:
        pymavlink connection string for telemetry.
    sysroot:
        Root for health readers (``/`` on real hardware).
    _shutdown_event:
        For testing — external shutdown control.
    _state:
        For testing — pre-built SharedState.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib

    from mower_rover.kiosk.dashboard import KioskApp

    state = _state or SharedState()
    shutdown = _shutdown_event or threading.Event()

    # Signal handling for graceful shutdown
    def _handle_signal(signum: int, _frame: Any) -> None:
        _log.info("kiosk_signal_received", signal=signum)
        shutdown.set()

    if threading.current_thread() is threading.main_thread():
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    # Start background reader threads
    threads: list[threading.Thread] = []

    t_mav = threading.Thread(
        target=_mavlink_reader_thread,
        args=(state, shutdown, mavlink_endpoint),
        name="kiosk-mavlink-reader",
        daemon=True,
    )
    t_mav.start()
    threads.append(t_mav)

    # Load service units from config
    from mower_rover.config.jetson import load_jetson_config

    cfg = load_jetson_config()
    service_units = cfg.kiosk.service_check_units

    t_poller = threading.Thread(
        target=_slow_poller_thread,
        args=(state, shutdown, sysroot, service_units),
        name="kiosk-slow-poller",
        daemon=True,
    )
    t_poller.start()
    threads.append(t_poller)

    _log.info("kiosk_threads_started", count=len(threads))

    # Create the GTK application
    app = KioskApp(state)

    # sdnotify READY=1 after window is realized — hook into activate signal.
    # NOTE: must use connect() not instance monkey-patch — GObject dispatches
    # signals through the class vtable, not instance attributes.
    def _on_activate(_app: KioskApp) -> None:
        _notifier.notify("READY=1")  # type: ignore[attr-defined]
        _log.info("kiosk_ready")

        # Start watchdog timer (every 15s)
        def _watchdog_tick() -> bool:
            if shutdown.is_set():
                return False
            _notifier.notify("WATCHDOG=1")  # type: ignore[attr-defined]
            return True

        GLib.timeout_add_seconds(15, _watchdog_tick)

    app.connect("activate", _on_activate)

    # Run GTK main loop (blocks until app quits)
    try:
        app.run(None)
    finally:
        shutdown.set()
        _log.info("kiosk_shutting_down")

        # Wait for threads to exit
        for t in threads:
            t.join(timeout=3.0)

        _log.info("kiosk_exited")
