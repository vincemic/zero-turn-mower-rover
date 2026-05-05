"""Kiosk systemd unit file generation and management.

Deploys mower-weston, mower-kiosk, and mower-mavproxy systemd services.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from mower_rover.config.jetson import JetsonConfig
from mower_rover.logging_setup.setup import get_logger
from mower_rover.safety.confirm import ConfirmationAborted, SafetyContext
from mower_rover.service.unit import (
    KIOSK_UNIT_NAME,
    MAVPROXY_UNIT_NAME,
    WESTON_UNIT_NAME,
    generate_kiosk_unit_file,
    generate_mavproxy_unit_file,
    generate_weston_unit_file,
    unit_dir,
)

_log = get_logger("kiosk.units")

_KIOSK_UNITS = [WESTON_UNIT_NAME, MAVPROXY_UNIT_NAME, KIOSK_UNIT_NAME]


def _confirm_or_abort(safety: SafetyContext, message: str) -> None:
    """Inline confirmation check matching the requires_confirmation pattern."""
    if safety.dry_run or safety.assume_yes:
        return
    try:
        answer = input(f"{message} [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        raise ConfirmationAborted(f"Operator declined: {message}")


def _systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a system-level systemctl command."""
    cmd = ["systemctl"] + args
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def install_kiosk_units(
    safety: SafetyContext,
    *,
    config: JetsonConfig,
    target_user: str | None = None,
    target_home: str | None = None,
) -> None:
    """Generate and deploy kiosk systemd unit files.

    Creates unit files for mower-weston, mower-kiosk, and mavproxy services.
    All are system-level units.
    """
    _confirm_or_abort(safety, "Install kiosk systemd unit files (weston, kiosk, mavproxy)?")
    log = _log.bind(op="install_kiosk_units")

    if safety.dry_run:
        log.info("dry_run_install_kiosk_units")
        return

    user = target_user or "vincent"
    home = target_home or "/home/vincent"

    if target_home is not None:
        mower_jetson = f"{target_home.rstrip('/')}/.local/bin/mower-jetson"
    else:
        mower_jetson = (
            shutil.which("mower-jetson")
            or str(Path.home() / ".local" / "bin" / "mower-jetson")
        )

    kiosk_cfg = config.kiosk

    # Generate all 3 unit files
    units: dict[str, str] = {
        WESTON_UNIT_NAME: generate_weston_unit_file(user=user, home_dir=home),
        MAVPROXY_UNIT_NAME: generate_mavproxy_unit_file(
            master=kiosk_cfg.mavproxy_master,
            outputs=kiosk_cfg.mavproxy_outputs,
            user=user,
            home_dir=home,
        ),
        KIOSK_UNIT_NAME: generate_kiosk_unit_file(
            mower_jetson_path=mower_jetson,
            user=user,
            home_dir=home,
        ),
    }

    target_dir = unit_dir(user_level=False)
    target_dir.mkdir(parents=True, exist_ok=True)

    for name, content in units.items():
        unit_path = target_dir / f"{name}.service"
        unit_path.write_text(content, encoding="utf-8")
        log.info("unit_file_written", path=str(unit_path))

    _systemctl(["daemon-reload"])

    for name in _KIOSK_UNITS:
        _systemctl(["enable", f"{name}.service"])
        log.info("unit_enabled", unit=name)

    log.info("kiosk_units_installed")


def uninstall_kiosk_units(safety: SafetyContext) -> None:
    """Remove kiosk systemd unit files.

    Stops, disables, and removes unit files for mower-weston, mower-kiosk,
    and mavproxy services.
    """
    _confirm_or_abort(safety, "Uninstall kiosk systemd unit files?")
    log = _log.bind(op="uninstall_kiosk_units")

    if safety.dry_run:
        log.info("dry_run_uninstall_kiosk_units")
        return

    # Stop and disable in reverse order (kiosk depends on weston)
    for name in reversed(_KIOSK_UNITS):
        service = f"{name}.service"
        for action in ("stop", "disable"):
            try:
                _systemctl([action, service])
            except subprocess.CalledProcessError:
                log.debug(
                    "systemctl_action_skipped",
                    action=action,
                    unit=name,
                    detail="service may not be active/enabled",
                )

    # Remove unit files
    target_dir = unit_dir(user_level=False)
    for name in _KIOSK_UNITS:
        unit_path = target_dir / f"{name}.service"
        if unit_path.exists():
            unit_path.unlink()
            log.info("unit_file_removed", path=str(unit_path))

    _systemctl(["daemon-reload"])
    log.info("kiosk_units_uninstalled")
