"""Systemd unit file generation and management for mower services.

Generates, installs, and removes systemd service units (``mower-health``,
``mower-vslam``, etc.) on the Jetson.  Supports both per-user (``--user``)
and system-level installation.
"""

from __future__ import annotations

import contextlib
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
WESTON_UNIT_NAME = "mower-weston"
KIOSK_UNIT_NAME = "mower-kiosk"  # Legacy name — kept for cleanup of old unit
KIOSK_DATA_UNIT_NAME = "mower-kiosk-data"
KIOSK_RENDERER_UNIT_NAME = "mower-kiosk-renderer"
MAVPROXY_UNIT_NAME = "mower-mavproxy"

# ---------------------------------------------------------------------------
# Generic unit templates
# ---------------------------------------------------------------------------

_GENERIC_SYSTEM_TEMPLATE = """\
[Unit]
Description={description}
After={after}
StartLimitIntervalSec={start_limit_interval_sec}
StartLimitBurst=5
{binds_to}{requires}
[Service]
Type={service_type}
{exec_start_pre}ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
{extra_environment}User={user}
WorkingDirectory={home_dir}
WatchdogSec={watchdog_sec}
{timeout_start_sec}{runtime_directory}Restart=on-failure
RestartSec={restart_sec}

[Install]
WantedBy=multi-user.target
"""

_GENERIC_USER_TEMPLATE = """\
[Unit]
Description={description}
After={after}
StartLimitIntervalSec={start_limit_interval_sec}
StartLimitBurst=5
{binds_to}{requires}
[Service]
Type={service_type}
{exec_start_pre}ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
{extra_environment}WorkingDirectory={home_dir}
WatchdogSec={watchdog_sec}
{timeout_start_sec}{runtime_directory}Restart=on-failure
RestartSec={restart_sec}

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
    requires: str | None = None,
    binds_to: str | None = None,
    watchdog_sec: int = 30,
    timeout_start_sec: int | None = None,
    runtime_directory: str | None = None,
    service_type: str = "notify",
    extra_environment: dict[str, str] | None = None,
    restart_sec: int = 5,
    exec_start_pre: list[str] | None = None,
    start_limit_interval_sec: int = 300,
) -> str:
    """Return a systemd unit file from the generic template.

    This is the building block for all mower service units.
    """
    binds_to_line = f"BindsTo={binds_to}\n" if binds_to else ""
    requires_line = f"Requires={requires}\n" if requires else ""
    runtime_dir_line = (
        f"RuntimeDirectory={runtime_directory}\n" if runtime_directory else ""
    )
    timeout_line = (
        f"TimeoutStartSec={timeout_start_sec}\n" if timeout_start_sec else ""
    )
    extra_env_lines = ""
    if extra_environment:
        extra_env_lines = "".join(
            f"Environment={k}={v}\n" for k, v in extra_environment.items()
        )
    # Defensive: ensure extra_environment block always ends with \n to
    # prevent concatenation with the next directive (User= / WorkingDirectory=).
    if extra_env_lines and not extra_env_lines.endswith("\n"):
        extra_env_lines += "\n"
    exec_start_pre_lines = ""
    if exec_start_pre:
        exec_start_pre_lines = "".join(
            f"ExecStartPre={cmd}\n" for cmd in exec_start_pre
        )
    template = _GENERIC_USER_TEMPLATE if user_level else _GENERIC_SYSTEM_TEMPLATE
    return template.format(
        description=description,
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        after=after,
        requires=requires_line,
        binds_to=binds_to_line,
        watchdog_sec=watchdog_sec,
        timeout_start_sec=timeout_line,
        runtime_directory=runtime_dir_line,
        service_type=service_type,
        extra_environment=extra_env_lines,
        restart_sec=restart_sec,
        exec_start_pre=exec_start_pre_lines,
        start_limit_interval_sec=start_limit_interval_sec,
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
        with contextlib.suppress(subprocess.CalledProcessError, FileNotFoundError, OSError):
            _systemctl([action, service], user_level=True)

    user_unit_path = Path.home() / ".config" / "systemd" / "user" / service
    deleted = False
    if user_unit_path.exists():
        try:
            user_unit_path.unlink()
            deleted = True
            log.info("user_unit_migrated", path=str(user_unit_path))
        except OSError:
            pass

    with contextlib.suppress(subprocess.CalledProcessError, FileNotFoundError, OSError):
        _systemctl(["daemon-reload"], user_level=True)

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

    user = target_user or getpass.getuser()
    home = target_home or str(Path.home())
    # When target_home is provided (e.g. install run via sudo), prefer the
    # target user's binary over whatever shutil.which resolves under the
    # caller's environment (which may be /root/.local/bin under sudo).
    if target_home is not None:
        # Use forward-slash join: this path is written into a Linux systemd
        # unit file, so Path() on Windows would produce backslashes.
        mower_jetson = f"{target_home.rstrip('/')}/.local/bin/mower-jetson"
    else:
        mower_jetson = (
            shutil.which("mower-jetson")
            or str(Path.home() / ".local" / "bin" / "mower-jetson")
        )
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
        after=f"network.target {VSLAM_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
        requires=f"{MAVPROXY_UNIT_NAME}.service {VSLAM_UNIT_NAME}.service",
        binds_to=None,
        watchdog_sec=30,
        timeout_start_sec=120,
        runtime_directory=None,
        start_limit_interval_sec=900,
    )


# ---------------------------------------------------------------------------
# Kiosk-related unit templates
# ---------------------------------------------------------------------------

_WESTON_EXEC_START = (
    "/usr/bin/weston --shell=desktop-shell.so"
    " --drm-device=card0"
    " --renderer=pixman"
    " --idle-time=0"
    " --log=/var/log/mower-jetson/weston.log"
    " --continue-without-input"
)

_WESTON_UNIT_TEMPLATE = """\
[Unit]
Description=Weston kiosk compositor for mower display
After=seatd.service systemd-modules-load.service
Requires=seatd.service
StartLimitIntervalSec=120
StartLimitBurst=30

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p /var/log/mower-jetson
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /dev/dri/card0 ] && exit 0; sleep 1; done; echo "DRM device not found"; exit 1'
ExecStart={weston_exec_start}
Environment=XDG_RUNTIME_DIR=/run/user/1000
User={user}
WorkingDirectory={home_dir}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
"""

_MAVPROXY_UNIT_TEMPLATE = """\
[Unit]
Description=MAVProxy telemetry forwarder for mower
After=network.target dev-pixhawk.device
BindsTo=dev-pixhawk.device
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_start}
Environment=MOWER_CORRELATION_ID=daemon
User={user}
WorkingDirectory={home_dir}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def generate_weston_unit_file(
    *,
    user: str = "vincent",
    home_dir: str = "/home/vincent",
) -> str:
    """Return the content of a systemd unit file for the mower-weston service."""
    return _WESTON_UNIT_TEMPLATE.format(
        weston_exec_start=_WESTON_EXEC_START,
        user=user,
        home_dir=home_dir,
    )


def generate_mavproxy_unit_file(
    *,
    master: str,
    outputs: list[str],
    user: str = "vincent",
    home_dir: str = "/home/vincent",
) -> str:
    """Return the content of a systemd unit file for the mower-mavproxy service."""
    out_args = " ".join(f"--out={o}" for o in outputs)
    mavproxy_bin = f"{home_dir}/.local/share/uv/tools/mower-rover/bin/mavproxy.py"
    exec_start = f"{mavproxy_bin} --master={master} {out_args} --non-interactive"
    return _MAVPROXY_UNIT_TEMPLATE.format(
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
    )


def generate_kiosk_unit_file(
    *,
    mower_jetson_path: str,
    user: str = "vincent",
    home_dir: str = "/home/vincent",
) -> str:
    """Return the content of a systemd unit file for the mower-kiosk service.

    .. deprecated:: Use :func:`generate_kiosk_data_unit_file` instead.
    """
    exec_start = f"{mower_jetson_path} kiosk run"
    return generate_service_unit(
        description="Mower Rover kiosk operational display",
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        user_level=False,
        after=f"{WESTON_UNIT_NAME}.service mower-health.service {MAVPROXY_UNIT_NAME}.service",
        binds_to=f"{WESTON_UNIT_NAME}.service",
        watchdog_sec=30,
        service_type="notify",
        extra_environment={
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "WAYLAND_DISPLAY": "wayland-0",
            "GSK_RENDERER": "cairo",
        },
    )


def generate_kiosk_data_unit_file(
    *,
    mower_jetson_path: str,
    user: str = "vincent",
    home_dir: str = "/home/vincent",
) -> str:
    """Return the content of a systemd unit file for the mower-kiosk-data service.

    The data service runs the Python kiosk daemon that publishes telemetry
    to a Unix socket in ``/run/mower/``.  It no longer renders GTK4 UI.
    """
    exec_start = f"{mower_jetson_path} kiosk run"
    return generate_service_unit(
        description="Mower Kiosk Data Service",
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        user_level=False,
        after=f"{WESTON_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
        requires=f"{WESTON_UNIT_NAME}.service",
        watchdog_sec=30,
        service_type="notify",
        runtime_directory="mower",
    )


def generate_kiosk_renderer_unit_file(
    *,
    user: str = "vincent",
    home_dir: str = "/home/vincent",
) -> str:
    """Return the content of a systemd unit file for the mower-kiosk-renderer service.

    The renderer is a native C/LVGL binary that reads telemetry from the
    Unix socket and renders to the Wayland compositor.
    """
    return generate_service_unit(
        description="Mower Kiosk LVGL Renderer",
        exec_start="/usr/local/bin/mower-kiosk-renderer",
        user=user,
        home_dir=home_dir,
        user_level=False,
        after=f"{WESTON_UNIT_NAME}.service {KIOSK_DATA_UNIT_NAME}.service",
        binds_to=f"{WESTON_UNIT_NAME}.service",
        watchdog_sec=30,
        service_type="notify",
        extra_environment={
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "WAYLAND_DISPLAY": "wayland-0",
        },
        restart_sec=2,
        exec_start_pre=[
            "/bin/sh -c 'for i in $(seq 1 30); do [ -e /run/user/1000/wayland-0 ] && exit 0; sleep 0.5; done; echo \"Wayland socket not found\"; exit 1'",
        ],
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

    user = target_user or getpass.getuser()
    home = target_home or str(Path.home())
    if target_home is not None:
        mower_jetson = f"{target_home.rstrip('/')}/.local/bin/mower-jetson"
    else:
        mower_jetson = (
            shutil.which("mower-jetson")
            or str(Path.home() / ".local" / "bin" / "mower-jetson")
        )

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
