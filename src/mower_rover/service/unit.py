"""Systemd unit file generation and management for mower services.

Generates, installs, and removes systemd service units (``mower-health``,
``mower-vslam``, etc.) on the Jetson.  Supports both per-user (``--user``)
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
VSLAM_UNIT_NAME = "mower-vslam"
VSLAM_BRIDGE_UNIT_NAME = "mower-vslam-bridge"

# ---------------------------------------------------------------------------
# Generic unit templates
# ---------------------------------------------------------------------------

_GENERIC_SYSTEM_TEMPLATE = """\
[Unit]
Description={description}
After={after}
StartLimitIntervalSec=300
StartLimitBurst=5
{binds_to}
[Service]
Type=notify
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
User={user}
WorkingDirectory={home_dir}
WatchdogSec={watchdog_sec}
{timeout_start_sec}{runtime_directory}Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

_GENERIC_USER_TEMPLATE = """\
[Unit]
Description={description}
After={after}
StartLimitIntervalSec=300
StartLimitBurst=5
{binds_to}
[Service]
Type=notify
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
WorkingDirectory={home_dir}
WatchdogSec={watchdog_sec}
{timeout_start_sec}{runtime_directory}Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def generate_service_unit(
    *,
    description: str,
    exec_start: str,
    user: str,
    home_dir: str,
    user_level: bool = True,
    after: str = "network.target",
    binds_to: str | None = None,
    watchdog_sec: int = 30,
    timeout_start_sec: int | None = None,
    runtime_directory: str | None = None,
) -> str:
    """Return a systemd unit file from the generic template.

    This is the building block for all mower service units.
    """
    binds_to_line = f"BindsTo={binds_to}\n" if binds_to else ""
    runtime_dir_line = (
        f"RuntimeDirectory={runtime_directory}\n" if runtime_directory else ""
    )
    timeout_line = (
        f"TimeoutStartSec={timeout_start_sec}\n" if timeout_start_sec else ""
    )
    template = _GENERIC_USER_TEMPLATE if user_level else _GENERIC_SYSTEM_TEMPLATE
    return template.format(
        description=description,
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        after=after,
        binds_to=binds_to_line,
        watchdog_sec=watchdog_sec,
        timeout_start_sec=timeout_line,
        runtime_directory=runtime_dir_line,
    )


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
    return generate_service_unit(
        description="Mower Rover health monitor daemon",
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        user_level=user_level,
        after="network.target",
        watchdog_sec=30,
    )


def generate_vslam_unit_file(
    *,
    user: str,
    home_dir: str,
    config_path: str = "/etc/mower/vslam.yaml",
    node_binary: str = "/usr/local/bin/rtabmap_slam_node",
    user_level: bool = True,
) -> str:
    """Return the content of a systemd unit file for the mower-vslam daemon."""
    exec_start = f"{node_binary} --config {config_path}"
    return generate_service_unit(
        description="Mower Rover VSLAM (RTAB-Map) daemon",
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        user_level=user_level,
        after="network.target mower-health.service",
        binds_to=None,
        watchdog_sec=30,
        timeout_start_sec=300,
        runtime_directory="mower",
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


def _cleanup_user_unit(unit_name: str) -> bool:
    """Stop, disable, and remove a stale user-level unit file (migration helper).

    Runs as the current (unprivileged) user. All errors are swallowed —
    idempotent on fresh installs where no user-level unit exists.

    Returns True if a unit file was actually deleted, False otherwise.
    """
    log = _log.bind(op="cleanup_user_unit", unit=unit_name)
    service = f"{unit_name}.service"

    for action in ("stop", "disable"):
        try:
            _systemctl([action, service], user_level=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            pass

    user_unit_path = Path.home() / ".config" / "systemd" / "user" / service
    deleted = False
    if user_unit_path.exists():
        try:
            user_unit_path.unlink()
            deleted = True
            log.info("user_unit_migrated", path=str(user_unit_path))
        except OSError:
            pass

    try:
        _systemctl(["daemon-reload"], user_level=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    return deleted


@requires_confirmation("Install mower-health systemd service")
def install_service(
    ctx: SafetyContext,
    *,
    user_level: bool,
    target_user: str | None = None,
    target_home: str | None = None,
) -> None:
    """Write the mower-health unit file, reload systemd, and enable the unit."""
    log = _log.bind(op="install_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_install_service")
        return

    mower_jetson = (
        shutil.which("mower-jetson")
        or str(Path.home() / ".local" / "bin" / "mower-jetson")
    )
    user = target_user or getpass.getuser()
    home = target_home or str(Path.home())
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
    _systemctl(["enable", f"{UNIT_NAME}.service"], user_level=user_level)
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


# ---------------------------------------------------------------------------
# VSLAM service install / uninstall
# ---------------------------------------------------------------------------


@requires_confirmation("Install mower-vslam systemd service")
def install_vslam_service(
    ctx: SafetyContext,
    *,
    user_level: bool,
    target_user: str | None = None,
    target_home: str | None = None,
) -> None:
    """Write the mower-vslam unit file, reload systemd, and enable the unit."""
    log = _log.bind(op="install_vslam_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_install_vslam_service")
        return

    user = target_user or getpass.getuser()
    home = target_home or str(Path.home())

    content = generate_vslam_unit_file(
        user=user,
        home_dir=home,
        user_level=user_level,
    )

    target_dir = unit_dir(user_level)
    target_dir.mkdir(parents=True, exist_ok=True)
    unit_path = target_dir / f"{VSLAM_UNIT_NAME}.service"
    unit_path.write_text(content, encoding="utf-8")

    _systemctl(["daemon-reload"], user_level=user_level)
    _systemctl(["enable", f"{VSLAM_UNIT_NAME}.service"], user_level=user_level)
    log.info("vslam_service_installed", path=str(unit_path))


@requires_confirmation("Uninstall mower-vslam systemd service")
def uninstall_vslam_service(ctx: SafetyContext, *, user_level: bool) -> None:
    """Stop, disable, and remove the mower-vslam unit file, then reload systemd."""
    log = _log.bind(op="uninstall_vslam_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_uninstall_vslam_service")
        return

    for action in ("stop", "disable"):
        try:
            _systemctl(
                [action, f"{VSLAM_UNIT_NAME}.service"], user_level=user_level
            )
        except subprocess.CalledProcessError:
            log.debug(
                "systemctl_action_skipped",
                action=action,
                detail="vslam service may not be active/enabled",
            )

    target = unit_dir(user_level) / f"{VSLAM_UNIT_NAME}.service"
    if target.exists():
        target.unlink()
        log.info("vslam_unit_file_removed", path=str(target))

    _systemctl(["daemon-reload"], user_level=user_level)
    log.info("vslam_service_uninstalled")


# ---------------------------------------------------------------------------
# VSLAM bridge service install / uninstall
# ---------------------------------------------------------------------------


def generate_vslam_bridge_unit_file(
    *,
    mower_jetson_path: str,
    user: str,
    home_dir: str,
    user_level: bool = True,
) -> str:
    """Return the content of a systemd unit file for the mower-vslam-bridge daemon."""
    exec_start = f"{mower_jetson_path} vslam bridge-run"
    return generate_service_unit(
        description="Mower Rover VSLAM MAVLink bridge daemon",
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        user_level=user_level,
        after=f"network.target {VSLAM_UNIT_NAME}.service",
        binds_to="dev-pixhawk.device",
        watchdog_sec=30,
        runtime_directory="mower",
    )


@requires_confirmation("Install mower-vslam-bridge systemd service")
def install_vslam_bridge_service(
    ctx: SafetyContext,
    *,
    user_level: bool,
    target_user: str | None = None,
    target_home: str | None = None,
) -> None:
    """Write the mower-vslam-bridge unit file, reload systemd, and enable the unit."""
    log = _log.bind(op="install_vslam_bridge_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_install_vslam_bridge_service")
        return

    mower_jetson = (
        shutil.which("mower-jetson")
        or str(Path.home() / ".local" / "bin" / "mower-jetson")
    )
    user = target_user or getpass.getuser()
    home = target_home or str(Path.home())

    content = generate_vslam_bridge_unit_file(
        mower_jetson_path=mower_jetson,
        user=user,
        home_dir=home,
        user_level=user_level,
    )

    target_dir = unit_dir(user_level)
    target_dir.mkdir(parents=True, exist_ok=True)
    unit_path = target_dir / f"{VSLAM_BRIDGE_UNIT_NAME}.service"
    unit_path.write_text(content, encoding="utf-8")

    _systemctl(["daemon-reload"], user_level=user_level)
    _systemctl(["enable", f"{VSLAM_BRIDGE_UNIT_NAME}.service"], user_level=user_level)
    log.info("vslam_bridge_service_installed", path=str(unit_path))


@requires_confirmation("Uninstall mower-vslam-bridge systemd service")
def uninstall_vslam_bridge_service(ctx: SafetyContext, *, user_level: bool) -> None:
    """Stop, disable, and remove the mower-vslam-bridge unit file, then reload systemd."""
    log = _log.bind(op="uninstall_vslam_bridge_service", user_level=user_level)

    if ctx.dry_run:
        log.info("dry_run_uninstall_vslam_bridge_service")
        return

    for action in ("stop", "disable"):
        try:
            _systemctl(
                [action, f"{VSLAM_BRIDGE_UNIT_NAME}.service"],
                user_level=user_level,
            )
        except subprocess.CalledProcessError:
            log.debug(
                "systemctl_action_skipped",
                action=action,
                detail="vslam bridge service may not be active/enabled",
            )

    target = unit_dir(user_level) / f"{VSLAM_BRIDGE_UNIT_NAME}.service"
    if target.exists():
        target.unlink()
        log.info("vslam_bridge_unit_file_removed", path=str(target))

    _systemctl(["daemon-reload"], user_level=user_level)
    log.info("vslam_bridge_service_uninstalled")
