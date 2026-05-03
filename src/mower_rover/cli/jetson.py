"""`mower-jetson` CLI — Jetson Orin-side entry point.

Subcommands ship as Release 1 progresses (log collection, OAK-D detect,
VSLAM bring-up). Current commands:

- `mower-jetson info`         — platform identity (hostname, kernel, JetPack release).
- `mower-jetson config show`  — print the resolved Jetson YAML config.
- `mower-jetson probe`        — run pre-flight probe checks.
- `mower-jetson thermal`      — live thermal zone monitor.
- `mower-jetson power`        — power / performance state snapshot.

Install convention: `pipx install .` on JetPack Ubuntu (aarch64). Systemd
units are intentionally deferred until a phase needs one.
"""

from __future__ import annotations

import getpass
import json as _json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from mower_rover import __version__
from mower_rover.cli.detect import _collect, _render_human
from mower_rover.config.jetson import (
    DEFAULT_JETSON_CONFIG_PATH,
    JetsonConfigError,
    load_jetson_config,
)
from mower_rover.config.vslam import (
    DEFAULT_VSLAM_CONFIG_PATH,
    load_vslam_config,
    save_vslam_config,
)
from mower_rover.health.disk import read_disk_usage
from mower_rover.health.power import PowerState, read_power_state
from mower_rover.health.thermal import ThermalSnapshot, read_thermal_zones
from mower_rover.logging_setup.setup import configure_logging, get_logger
from mower_rover.mavlink.connection import ConnectionConfig, open_link
from mower_rover.probe.registry import Status, derive_exit_code, run_checks
from mower_rover.safety.confirm import ConfirmationAborted, SafetyContext
from mower_rover.service.daemon import run_daemon
from mower_rover.service.unit import (
    UNIT_NAME,
    VSLAM_BRIDGE_UNIT_NAME,
    VSLAM_UNIT_NAME,
    _cleanup_user_unit,
    install_service,
    install_vslam_bridge_service,
    install_vslam_service,
    uninstall_service,
    uninstall_vslam_bridge_service,
    uninstall_vslam_service,
)

app = typer.Typer(
    name="mower-jetson",
    help="Jetson-side tooling for the zero-turn mower rover.",
    no_args_is_help=True,
)
config_app = typer.Typer(name="config", help="Inspect Jetson-side config.", no_args_is_help=True)
app.add_typer(config_app, name="config")

service_app = typer.Typer(
    name="service",
    help="Manage the mower-health systemd service.",
    no_args_is_help=True,
)
app.add_typer(service_app, name="service")

vslam_app = typer.Typer(
    name="vslam",
    help="Manage the mower-vslam (RTAB-Map) systemd service.",
    no_args_is_help=True,
)
app.add_typer(vslam_app, name="vslam")

zone_app = typer.Typer(name="zone", help="Multi-zone lawn management.", no_args_is_help=True)
app.add_typer(zone_app, name="zone")


@app.callback()
def _root(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    # Inherit the laptop-side correlation ID if we were invoked over SSH.
    inherited = os.environ.get("MOWER_CORRELATION_ID") or None
    cid, log_file = configure_logging(
        correlation_id=inherited,
        console_level="DEBUG" if verbose else "INFO",
    )
    ctx.ensure_object(dict)
    ctx.obj["dry_run"] = dry_run
    ctx.obj["correlation_id"] = cid
    ctx.obj["log_file"] = log_file
    get_logger("cli-jetson").info(
        "cli_invoked",
        version=__version__,
        dry_run=dry_run,
        log_file=str(log_file),
        inherited_correlation_id=inherited,
    )


@app.command("version")
def version() -> None:
    """Print the installed mower-rover version."""
    typer.echo(__version__)


# --- detect ------------------------------------------------------------------


@app.command("detect")
def detect_command(
    endpoint: str = typer.Option(
        "/dev/pixhawk",
        "--port",
        "--endpoint",
        help="MAVLink endpoint. Default: /dev/pixhawk (USB).",
    ),
    baud: int = typer.Option(0, help="Serial baud (0 for USB CDC)."),
    sample_seconds: float = typer.Option(3.0, help="How long to listen for messages."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Detect connected hardware over local USB."""
    log = get_logger("cli-jetson").bind(op="detect")
    config = ConnectionConfig(endpoint=endpoint, baud=baud)
    with open_link(config) as conn:
        report = _collect(conn, sample_window_s=sample_seconds)
    log.info("detect_complete", endpoint=endpoint, warnings=report.warnings)
    if json_out:
        typer.echo(_json.dumps(asdict(report), indent=2))
    else:
        _render_human(report, Console())


# --- info -------------------------------------------------------------------

_NV_TEGRA_RELEASE = Path("/etc/nv_tegra_release")


@dataclass
class PlatformInfo:
    package_version: str
    hostname: str
    fqdn: str
    system: str
    release: str
    machine: str
    python_version: str
    jetpack_release: str | None = None
    is_jetson: bool = False
    cuda_version: str | None = None
    nvme_present: bool = False
    power_mode: str | None = None
    oakd_detected: bool = False
    warnings: list[str] = field(default_factory=list)


def _read_jetpack_release() -> str | None:
    if not _NV_TEGRA_RELEASE.exists():
        return None
    try:
        return _NV_TEGRA_RELEASE.read_text(encoding="utf-8").strip().splitlines()[0]
    except OSError:
        return None


def _read_cuda_version() -> str | None:
    """Try ``nvcc --version`` to extract CUDA version string."""
    if shutil.which("nvcc") is None:
        return None
    try:
        result = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # Example line: "Cuda compilation tools, release 12.2, V12.2.140"
    import re

    for line in result.stdout.splitlines():
        m = re.search(r"release\s+([\d.]+)", line)
        if m:
            return m.group(1)
    return None


def _detect_oakd() -> bool:
    """Check if a Luxonis OAK-D device is present by scanning USB vendor IDs."""
    # Luxonis USB vendor ID is 03e7
    usb_devices = Path("/sys/bus/usb/devices")
    if not usb_devices.is_dir():
        return False
    for vendor_file in usb_devices.glob("*/idVendor"):
        try:
            vid = vendor_file.read_text(encoding="utf-8").strip().lower()
            if vid == "03e7":
                return True
        except OSError:
            continue
    return False


def _collect_platform_info() -> PlatformInfo:
    jp = _read_jetpack_release()
    disk_usage = read_disk_usage()
    nvme_present = any(d.is_nvme for d in disk_usage)
    power = read_power_state()
    info = PlatformInfo(
        package_version=__version__,
        hostname=socket.gethostname(),
        fqdn=socket.getfqdn(),
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        jetpack_release=jp,
        is_jetson=jp is not None,
        cuda_version=_read_cuda_version(),
        nvme_present=nvme_present,
        power_mode=power.mode_name,
        oakd_detected=_detect_oakd(),
    )
    if not info.is_jetson and info.machine.lower() != "aarch64":
        info.warnings.append(
            "running on non-aarch64 host; this CLI is intended for the Jetson AGX Orin"
        )
    return info


@app.command("info")
def info_command(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Report platform identity (hostname, kernel, JetPack release)."""
    log = get_logger("cli-jetson").bind(op="info")
    info = _collect_platform_info()
    log.info("platform_info", **{k: v for k, v in asdict(info).items() if k != "warnings"})
    if json_out:
        typer.echo(_json.dumps(asdict(info), indent=2, sort_keys=True))
        return
    typer.echo(f"mower-rover {info.package_version}")
    typer.echo(f"host       : {info.hostname} ({info.fqdn})")
    typer.echo(f"system     : {info.system} {info.release} ({info.machine})")
    typer.echo(f"python     : {info.python_version}")
    typer.echo(f"jetpack    : {info.jetpack_release or '-'}")
    typer.echo(f"is_jetson  : {'yes' if info.is_jetson else 'no'}")
    typer.echo(f"cuda       : {info.cuda_version or '-'}")
    typer.echo(f"nvme       : {'yes' if info.nvme_present else 'no'}")
    typer.echo(f"power_mode : {info.power_mode or '-'}")
    typer.echo(f"oakd       : {'yes' if info.oakd_detected else 'no'}")
    for w in info.warnings:
        typer.echo(f"WARN: {w}", err=True)


# --- config show ------------------------------------------------------------


@config_app.command("show")
def config_show_command(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path (default: per-user XDG)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Print the resolved Jetson YAML config (defaults shown if file is absent)."""
    log = get_logger("cli-jetson").bind(op="config_show")
    target = config or DEFAULT_JETSON_CONFIG_PATH
    try:
        cfg = load_jetson_config(target)
    except JetsonConfigError as exc:
        log.error("config_load_failed", path=str(target), error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    merged = cfg.to_dict()
    merged.pop("extra", None)
    if cfg.extra:
        merged.update(cfg.extra)
    payload = {
        "config_path": str(target),
        "exists": target.exists(),
        "config": merged,
    }
    log.info("config_resolved", path=str(target), exists=target.exists())
    if json_out:
        typer.echo(_json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"path   : {payload['config_path']}")
    typer.echo(f"exists : {payload['exists']}")
    for k, v in merged.items():
        typer.echo(f"  {k} = {v}")


# --- probe -------------------------------------------------------------------

_STATUS_EMOJI = {
    Status.PASS: "\u2705",   # ✅
    Status.FAIL: "\u274c",   # ❌
    Status.SKIP: "\u23ed\ufe0f",  # ⏭️
}


@app.command("probe")
def probe_command(
    ctx: typer.Context,
    check: list[str] | None = typer.Option(None, "--check", help="Run only named checks."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run pre-flight probe checks on the Jetson."""
    log = get_logger("cli-jetson").bind(op="probe")

    # Import checks to trigger @register decorators.
    import mower_rover.probe.checks  # noqa: F401

    only = frozenset(check) if check else None
    results = run_checks(sysroot=Path("/"), only=only)
    log.info("probe_complete", count=len(results))

    if json_out:
        payload = [
            {
                "name": r.name,
                "status": r.status.value,
                "severity": r.severity.value,
                "detail": r.detail,
            }
            for r in results
        ]
        typer.echo(_json.dumps(payload, indent=2))
        raise typer.Exit(code=derive_exit_code(results))

    console = Console()
    table = Table(title="Probe Results")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Detail")
    for r in results:
        emoji = _STATUS_EMOJI.get(r.status, "?")
        table.add_row(r.name, emoji, r.severity.value, r.detail)
    console.print(table)

    raise typer.Exit(code=derive_exit_code(results))


# --- thermal -----------------------------------------------------------------

def _thermal_color(temp_c: float) -> str:
    if temp_c >= 95.0:
        return "red"
    if temp_c >= 70.0:
        return "yellow"
    return "green"


def _render_thermal_table(snapshot: ThermalSnapshot) -> Table:
    table = Table(title=f"Thermal Zones  ({snapshot.timestamp})")
    table.add_column("Zone")
    table.add_column("Temp °C", justify="right")
    for z in snapshot.zones:
        color = _thermal_color(z.temp_c)
        table.add_row(z.name or f"zone{z.index}", f"[{color}]{z.temp_c:.1f}[/{color}]")
    return table


@app.command("thermal")
def thermal_command(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    watch: bool = typer.Option(False, "--watch", help="Continuously refresh."),
    interval: float = typer.Option(2.0, "--interval", help="Refresh interval in seconds."),
) -> None:
    """Monitor thermal zones."""
    log = get_logger("cli-jetson").bind(op="thermal")

    if json_out:
        snapshot = read_thermal_zones()
        log.info("thermal_read", zones=len(snapshot.zones))
        typer.echo(_json.dumps(asdict(snapshot), indent=2))
        return

    if watch:
        console = Console()
        try:
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    snapshot = read_thermal_zones()
                    live.update(_render_thermal_table(snapshot))
                    time.sleep(interval)
        except KeyboardInterrupt:
            pass
        return

    snapshot = read_thermal_zones()
    log.info("thermal_read", zones=len(snapshot.zones))
    Console().print(_render_thermal_table(snapshot))


# --- power -------------------------------------------------------------------

def _render_power_panel(state: PowerState) -> Panel:
    mode_id_str = state.mode_id if state.mode_id is not None else "-"
    lines = [
        f"Mode       : {state.mode_name or '-'} (ID: {mode_id_str})",
        f"Online CPUs: {state.online_cpus if state.online_cpus is not None else '-'}",
        f"GPU Freq   : {f'{state.gpu_freq_mhz} MHz' if state.gpu_freq_mhz is not None else '-'}",
        f"Fan Profile: {state.fan_profile or '-'}",
        f"Timestamp  : {state.timestamp}",
    ]
    return Panel("\n".join(lines), title="Power State")


@app.command("power")
def power_command(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    watch: bool = typer.Option(False, "--watch", help="Continuously refresh."),
    interval: float = typer.Option(2.0, "--interval", help="Refresh interval in seconds."),
) -> None:
    """Display Jetson power / performance state."""
    log = get_logger("cli-jetson").bind(op="power")

    if json_out:
        state = read_power_state()
        log.info("power_read", mode=state.mode_name)
        typer.echo(_json.dumps(asdict(state), indent=2))
        return

    if watch:
        console = Console()
        try:
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    state = read_power_state()
                    live.update(_render_power_panel(state))
                    time.sleep(interval)
        except KeyboardInterrupt:
            pass
        return

    state = read_power_state()
    log.info("power_read", mode=state.mode_name)
    Console().print(_render_power_panel(state))


# --- service -----------------------------------------------------------------


@service_app.command("install")
def service_install_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path."
    ),
    target_user: str | None = typer.Option(
        None, "--target-user", help="User for the unit's User= line (default: current user)."
    ),
    target_home: str | None = typer.Option(
        None, "--target-home", help="Home dir for the unit's WorkingDirectory= (default: current home)."
    ),
) -> None:
    """Install the mower-health systemd service."""
    obj = ctx.obj or {}
    cfg = load_jetson_config(config)
    level = user_level if user_level is not None else cfg.service_user_level
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        install_service(
            safety,
            user_level=level,
            target_user=target_user,
            target_home=target_home,
        )
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@service_app.command("uninstall")
def service_uninstall_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path."
    ),
) -> None:
    """Uninstall the mower-health systemd service."""
    obj = ctx.obj or {}
    cfg = load_jetson_config(config)
    level = user_level if user_level is not None else cfg.service_user_level
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        uninstall_service(safety, user_level=level)
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@service_app.command("start")
def service_start_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path."
    ),
) -> None:
    """Start the mower-health systemd service."""
    cfg = load_jetson_config(config)
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["start", f"{UNIT_NAME}.service"])
    subprocess.run(cmd, check=True)
    typer.echo("Service started.")


@service_app.command("stop")
def service_stop_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path."
    ),
) -> None:
    """Stop the mower-health systemd service."""
    cfg = load_jetson_config(config)
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["stop", f"{UNIT_NAME}.service"])
    subprocess.run(cmd, check=True)
    typer.echo("Service stopped.")


@service_app.command("status")
def service_status_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path."
    ),
) -> None:
    """Show the mower-health systemd service status."""
    cfg = load_jetson_config(config)
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["status", f"{UNIT_NAME}.service"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    raise typer.Exit(code=result.returncode)


@service_app.command("run")
def service_run_command(
    ctx: typer.Context,
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override config path."
    ),
    health_interval: int | None = typer.Option(
        None, "--health-interval", help="Health snapshot interval in seconds."
    ),
) -> None:
    """Run the health monitoring daemon (foreground)."""
    cfg = load_jetson_config(config)
    interval = health_interval if health_interval is not None else cfg.health_interval_s
    run_daemon(health_interval_s=interval, sysroot=Path("/"))


@service_app.command("cleanup-user-units")
def service_cleanup_user_units_command(
    ctx: typer.Context,
    unit: list[str] = typer.Option(
        ..., "--unit", help="Unit name(s) to clean up (e.g., mower-health)."
    ),
) -> None:
    """Remove stale user-level systemd units (migration helper).

    Idempotent: safe to run even if no user-level units exist.
    Runs as the current unprivileged user (no sudo required).
    """
    log = get_logger("cli-jetson").bind(op="cleanup_user_units")
    any_cleaned = False
    for name in unit:
        cleaned = _cleanup_user_unit(name)
        if cleaned:
            any_cleaned = True
            typer.echo(f"Cleaned up user-level unit: {name}.service")
    if not any_cleaned:
        typer.echo("No stale user-level units found.")
    log.info("cleanup_user_units_done", units=unit, any_cleaned=any_cleaned)


# --- vslam -------------------------------------------------------------------


@vslam_app.command("install")
def vslam_install_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    target_user: str | None = typer.Option(
        None, "--target-user", help="User for the unit's User= line (default: current user)."
    ),
    target_home: str | None = typer.Option(
        None, "--target-home", help="Home dir for the unit's WorkingDirectory= (default: current home)."
    ),
) -> None:
    """Install the mower-vslam systemd service."""
    obj = ctx.obj or {}
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        install_vslam_service(
            safety,
            user_level=level,
            target_user=target_user,
            target_home=target_home,
        )
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@vslam_app.command("uninstall")
def vslam_uninstall_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Uninstall the mower-vslam systemd service."""
    obj = ctx.obj or {}
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        uninstall_vslam_service(safety, user_level=level)
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@vslam_app.command("start")
def vslam_start_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Start the mower-vslam systemd service."""
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["start", f"{VSLAM_UNIT_NAME}.service"])
    subprocess.run(cmd, check=True)
    typer.echo("VSLAM service started.")


@vslam_app.command("stop")
def vslam_stop_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Stop the mower-vslam systemd service."""
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["stop", f"{VSLAM_UNIT_NAME}.service"])
    subprocess.run(cmd, check=True)
    typer.echo("VSLAM service stopped.")


@vslam_app.command("status")
def vslam_status_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Show the mower-vslam systemd service status."""
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["status", f"{VSLAM_UNIT_NAME}.service"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    raise typer.Exit(code=result.returncode)


# --- vslam bridge ------------------------------------------------------------


@vslam_app.command("bridge-install")
def vslam_bridge_install_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    target_user: str | None = typer.Option(
        None, "--target-user", help="User for the unit's User= line (default: current user)."
    ),
    target_home: str | None = typer.Option(
        None, "--target-home", help="Home dir for the unit's WorkingDirectory= (default: current home)."
    ),
) -> None:
    """Install the mower-vslam-bridge systemd service."""
    obj = ctx.obj or {}
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        install_vslam_bridge_service(
            safety,
            user_level=level,
            target_user=target_user,
            target_home=target_home,
        )
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@vslam_app.command("bridge-uninstall")
def vslam_bridge_uninstall_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Uninstall the mower-vslam-bridge systemd service."""
    obj = ctx.obj or {}
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        uninstall_vslam_bridge_service(safety, user_level=level)
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@vslam_app.command("bridge-run")
def vslam_bridge_run_command(
    ctx: typer.Context,
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override vslam.yaml path."
    ),
) -> None:
    """Run the VSLAM MAVLink bridge daemon (foreground)."""
    from mower_rover.vslam.bridge import run_bridge

    run_bridge(config_path=str(config) if config else None)


@vslam_app.command("bridge-health")
def vslam_bridge_health_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Show mower-vslam-bridge systemd service status."""
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["status", f"{VSLAM_BRIDGE_UNIT_NAME}.service"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    raise typer.Exit(code=result.returncode)


@vslam_app.command("bridge-start")
def vslam_bridge_start_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Start the VSLAM bridge service."""
    log = get_logger("cli-jetson").bind(op="bridge_start")
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["start", f"{VSLAM_BRIDGE_UNIT_NAME}.service"])
    log.info("bridge_start", cmd=cmd, user_level=level)
    subprocess.run(cmd, check=True)
    typer.echo("VSLAM bridge service started.")


@vslam_app.command("bridge-stop")
def vslam_bridge_stop_command(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Stop the VSLAM bridge service."""
    log = get_logger("cli-jetson").bind(op="bridge_stop")
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["stop", f"{VSLAM_BRIDGE_UNIT_NAME}.service"])
    log.info("bridge_stop", cmd=cmd, user_level=level)
    subprocess.run(cmd, check=True)
    typer.echo("VSLAM bridge service stopped.")


# --- zone -------------------------------------------------------------------


@zone_app.command("activate")
def zone_activate_command(
    ctx: typer.Context,
    zone_id: str = typer.Argument(..., help="Zone identifier (e.g., 'ne', 'south')"),
    slam_mode: str = typer.Option(
        "auto", "--slam-mode", help="SLAM mode: 'auto', 'mapping', or 'localization'"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Activate a zone and configure VSLAM for that zone."""
    log = get_logger("cli-jetson").bind(op="zone_activate", zone_id=zone_id)
    
    # Validate zone_id format: ^[a-z][a-z0-9_-]{0,31}$
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", zone_id):
        error_msg = f"Invalid zone_id format: '{zone_id}'. Must start with lowercase letter, contain only lowercase letters, numbers, underscores, or hyphens, and be 1-32 characters long."
        log.error("invalid_zone_id", zone_id=zone_id)
        if json_out:
            typer.echo(_json.dumps({"error": error_msg}, indent=2))
        else:
            typer.echo(f"ERROR: {error_msg}", err=True)
        raise typer.Exit(code=1)

    # Validate slam_mode
    if slam_mode not in ("auto", "mapping", "localization"):
        error_msg = f"Invalid slam_mode: '{slam_mode}'. Must be 'auto', 'mapping', or 'localization'."
        log.error("invalid_slam_mode", slam_mode=slam_mode)
        if json_out:
            typer.echo(_json.dumps({"error": error_msg}, indent=2))
        else:
            typer.echo(f"ERROR: {error_msg}", err=True)
        raise typer.Exit(code=1)

    # Create zone directory
    zone_dir = Path(f"/var/lib/mower/zones/{zone_id}")
    zone_dir.mkdir(parents=True, exist_ok=True)
    log.info("zone_directory_created", zone_dir=str(zone_dir))

    # Determine actual SLAM mode
    db_path = zone_dir / "rtabmap.db"
    if slam_mode == "auto":
        actual_slam_mode = "localization" if db_path.exists() else "mapping"
    else:
        actual_slam_mode = slam_mode

    log.info("slam_mode_determined", requested=slam_mode, actual=actual_slam_mode, db_exists=db_path.exists())

    try:
        # Load current VSLAM config
        vslam_config = load_vslam_config()
        
        # Update config
        vslam_config.database_path = db_path.as_posix()
        vslam_config.slam_mode = actual_slam_mode
        
        # Save updated config
        save_vslam_config(vslam_config)
        log.info("vslam_config_updated", database_path=str(db_path), slam_mode=actual_slam_mode)
        
        # Restart VSLAM services
        for service_name in [VSLAM_UNIT_NAME, VSLAM_BRIDGE_UNIT_NAME]:
            cmd = ["systemctl", "restart", f"{service_name}.service"]
            log.info("restarting_service", service=service_name, cmd=cmd)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log.error("service_restart_failed", service=service_name, 
                         returncode=result.returncode, stderr=result.stderr)
                error_msg = f"Failed to restart {service_name}.service: {result.stderr}"
                if json_out:
                    typer.echo(_json.dumps({"error": error_msg}, indent=2))
                else:
                    typer.echo(f"ERROR: {error_msg}", err=True)
                raise typer.Exit(code=1)
        
        log.info("zone_activated_successfully", zone_id=zone_id, slam_mode=actual_slam_mode)
        
        if json_out:
            typer.echo(_json.dumps({
                "zone_id": zone_id,
                "slam_mode": actual_slam_mode,
                "database_path": db_path.as_posix(),
                "status": "ok"
            }, indent=2))
        else:
            typer.echo(f"Zone '{zone_id}' activated successfully.")
            typer.echo(f"SLAM mode: {actual_slam_mode}")
            typer.echo(f"Database path: {db_path}")
            typer.echo("VSLAM services restarted.")

    except Exception as e:
        log.error("zone_activation_failed", zone_id=zone_id, error=str(e))
        error_msg = f"Failed to activate zone '{zone_id}': {e}"
        if json_out:
            typer.echo(_json.dumps({"error": error_msg}, indent=2))
        else:
            typer.echo(f"ERROR: {error_msg}", err=True)
        raise typer.Exit(code=1)


@zone_app.command("status")
def zone_status_command(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show current zone status and VSLAM service status."""
    log = get_logger("cli-jetson").bind(op="zone_status")
    
    try:
        # Load current VSLAM config
        vslam_config = load_vslam_config()
        
        # Extract zone_id from database_path
        # Look for pattern: /var/lib/mower/zones/{zone_id}/rtabmap.db
        db_path = Path(vslam_config.database_path)
        zone_id = None
        db_size_mb = 0
        
        # Check if path matches zone pattern
        path_parts = db_path.parts
        if len(path_parts) >= 3 and "zones" in path_parts:
            zones_idx = path_parts.index("zones")
            if zones_idx + 1 < len(path_parts):
                zone_id = path_parts[zones_idx + 1]
        
        # Get DB file size if it exists
        if db_path.exists():
            db_size_bytes = db_path.stat().st_size
            db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
        
        # Check VSLAM service status
        result = subprocess.run(
            ["systemctl", "is-active", f"{VSLAM_UNIT_NAME}.service"],
            capture_output=True, text=True
        )
        service_active = result.returncode == 0 and result.stdout.strip() == "active"
        
        log.info("zone_status_collected", 
                zone_id=zone_id, 
                db_size_mb=db_size_mb, 
                service_active=service_active,
                slam_mode=vslam_config.slam_mode)
        
        if json_out:
            typer.echo(_json.dumps({
                "zone_id": zone_id,
                "slam_mode": vslam_config.slam_mode,
                "database_path": vslam_config.database_path,
                "database_size_mb": db_size_mb,
                "service_active": service_active,
                "status": "ok"
            }, indent=2))
        else:
            typer.echo(f"Active zone: {zone_id or 'unknown'}")
            typer.echo(f"SLAM mode: {vslam_config.slam_mode}")
            typer.echo(f"Database path: {vslam_config.database_path}")
            typer.echo(f"Database size: {db_size_mb} MB")
            typer.echo(f"VSLAM service: {'active' if service_active else 'inactive'}")
            
    except Exception as e:
        log.error("zone_status_failed", error=str(e))
        error_msg = f"Failed to get zone status: {e}"
        if json_out:
            typer.echo(_json.dumps({"error": error_msg}, indent=2))
        else:
            typer.echo(f"ERROR: {error_msg}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
