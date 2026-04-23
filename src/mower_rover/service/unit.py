"""Systemd unit file generation and management for the mower-health service.

Generates, installs, and removes the ``mower-health.service`` unit that
runs health monitoring on the Jetson.  Supports both per-user (``--user``)
and system-level installation.
"""

from __future__ import annotations

import getpass
import shutil
import subprocess
from pathlib import Path

from mower_rover.config.jetson import load_jetson_config
from mower_rover.logging_setup.setup import get_logger
from mower_rover.safety.confirm import SafetyContext, requires_confirmation

_log = get_logger("service.unit")

UNIT_NAME = "mower-health"

_UNIT_TEMPLATE_SYSTEM = """\
[Unit]
Description=Mower Rover health monitor daemon
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
User={user}
WorkingDirectory={home_dir}
WatchdogSec=30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

_UNIT_TEMPLATE_USER = """\
[Unit]
Description=Mower Rover health monitor daemon
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
WorkingDirectory={home_dir}
WatchdogSec=30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def generate_unit_file(
    *,
    mower_jetson_path: str,
    user: str,
    home_dir: str,
    health_interval_s: int,
    user_level: bool = True,
) -> str:
    """Return the content of a systemd unit file for the mower-health daemon."""
    exec_start = (
        f"{mower_jetson_path} service run --health-interval {health_interval_s}"
    )
    template = _UNIT_TEMPLATE_USER if user_level else _UNIT_TEMPLATE_SYSTEM
    return template.format(
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
    )


def unit_dir(user_level: bool) -> Path:
    """Return the directory where the systemd unit file should live."""
    if user_level:
        return Path.home() / ".config" / "systemd" / "user"
    return Path("/etc/systemd/system")


def _systemctl(
    args: list[str], *, user_level: bool
) -> subprocess.CompletedProcess[str]:
    """Run a ``systemctl`` command, adding ``--user`` when appropriate."""
    cmd = ["systemctl"]
    if user_level:
        cmd.append("--user")
    cmd.extend(args)
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


@requires_confirmation("Install mower-health systemd service")
def install_service(ctx: SafetyContext, *, user_level: bool) -> None:
    """Write the mower-health unit file and reload systemd."""
    log = _log.bind(op="install_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_install_service")
        return

    mower_jetson = (
        shutil.which("mower-jetson")
        or str(Path.home() / ".local" / "bin" / "mower-jetson")
    )
    user = getpass.getuser()
    home = str(Path.home())
    cfg = load_jetson_config()

    content = generate_unit_file(
        mower_jetson_path=mower_jetson,
        user=user,
        home_dir=home,
        health_interval_s=cfg.health_interval_s,
        user_level=user_level,
    )

    target_dir = unit_dir(user_level)
    target_dir.mkdir(parents=True, exist_ok=True)
    unit_path = target_dir / f"{UNIT_NAME}.service"
    unit_path.write_text(content, encoding="utf-8")

    _systemctl(["daemon-reload"], user_level=user_level)
    log.info("service_installed", path=str(unit_path))


@requires_confirmation("Uninstall mower-health systemd service")
def uninstall_service(ctx: SafetyContext, *, user_level: bool) -> None:
    """Stop, disable, and remove the mower-health unit file, then reload systemd."""
    log = _log.bind(op="uninstall_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_uninstall_service")
        return

    # Stop and disable — ignore errors if the service is not active/enabled.
    for action in ("stop", "disable"):
        try:
            _systemctl([action, f"{UNIT_NAME}.service"], user_level=user_level)
        except subprocess.CalledProcessError:
            log.debug(
                "systemctl_action_skipped",
                action=action,
                detail="service may not be active/enabled",
            )

    # Remove the unit file.
    target = unit_dir(user_level) / f"{UNIT_NAME}.service"
    if target.exists():
        target.unlink()
        log.info("unit_file_removed", path=str(target))

    _systemctl(["daemon-reload"], user_level=user_level)
    log.info("service_uninstalled")
