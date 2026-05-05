"""Systemd oneshot unit for Pixhawk configuration sync at boot."""

from __future__ import annotations

import contextlib
import getpass
import shutil
from pathlib import Path

from mower_rover.logging_setup.setup import get_logger
from mower_rover.safety.confirm import SafetyContext, requires_confirmation
from mower_rover.service.unit import _systemctl, unit_dir

_log = get_logger("pixhawk.unit")

PIXHAWK_SYNC_UNIT_NAME = "mower-pixhawk-sync"


def generate_pixhawk_sync_unit_file(
    *,
    mower_jetson_path: str,
    user: str,
    home_dir: str,
    user_level: bool = True,
) -> str:
    """Return a systemd oneshot unit that runs ``mower-jetson pixhawk sync``."""
    exec_start = f"{mower_jetson_path} pixhawk sync"

    after = "network.target dev-pixhawk.device"
    binds_to = "BindsTo=dev-pixhawk.device\n"

    if user_level:
        return f"""\
[Unit]
Description=Mower Rover Pixhawk config sync (params + Lua)
After={after}
{binds_to}
[Service]
Type=oneshot
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=pixhawk-sync
WorkingDirectory={home_dir}
TimeoutStartSec=120
RemainAfterExit=yes

[Install]
WantedBy=default.target
"""
    return f"""\
[Unit]
Description=Mower Rover Pixhawk config sync (params + Lua)
After={after}
{binds_to}
[Service]
Type=oneshot
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=pixhawk-sync
User={user}
WorkingDirectory={home_dir}
TimeoutStartSec=120
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""


@requires_confirmation("Install mower-pixhawk-sync systemd oneshot service")
def install_pixhawk_sync_service(
    ctx: SafetyContext,
    *,
    user_level: bool,
    target_user: str | None = None,
    target_home: str | None = None,
) -> None:
    """Write the pixhawk-sync oneshot unit, reload systemd, and enable it."""
    log = _log.bind(op="install_pixhawk_sync", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_install_pixhawk_sync")
        return

    user = target_user or getpass.getuser()
    home = target_home or str(Path.home())
    if target_home is not None:
        mower_jetson = f"{target_home.rstrip('/')}/.local/bin/mower-jetson"
    else:
        mower_jetson = (
            shutil.which("mower-jetson")
            or str(Path.home() / ".local" / "bin" / "mower-jetson")
        )

    content = generate_pixhawk_sync_unit_file(
        mower_jetson_path=mower_jetson,
        user=user,
        home_dir=home,
        user_level=user_level,
    )

    target_dir = unit_dir(user_level)
    target_dir.mkdir(parents=True, exist_ok=True)
    unit_path = target_dir / f"{PIXHAWK_SYNC_UNIT_NAME}.service"
    unit_path.write_text(content, encoding="utf-8")

    _systemctl(["daemon-reload"], user_level=user_level)
    _systemctl(["enable", f"{PIXHAWK_SYNC_UNIT_NAME}.service"], user_level=user_level)
    log.info("pixhawk_sync_service_installed", path=str(unit_path))


@requires_confirmation("Uninstall mower-pixhawk-sync systemd service")
def uninstall_pixhawk_sync_service(ctx: SafetyContext, *, user_level: bool) -> None:
    """Stop, disable, and remove the pixhawk-sync oneshot unit."""
    log = _log.bind(op="uninstall_pixhawk_sync", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_uninstall_pixhawk_sync")
        return

    for action in ("stop", "disable"):
        with contextlib.suppress(Exception):
            _systemctl(
                [action, f"{PIXHAWK_SYNC_UNIT_NAME}.service"],
                user_level=user_level,
            )

    target = unit_dir(user_level) / f"{PIXHAWK_SYNC_UNIT_NAME}.service"
    if target.exists():
        target.unlink()
        log.info("pixhawk_sync_unit_file_removed", path=str(target))

    _systemctl(["daemon-reload"], user_level=user_level)
    log.info("pixhawk_sync_service_uninstalled")
