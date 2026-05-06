"""Kiosk sub-app for `mower-jetson kiosk`.

Commands:
- run        — Start the kiosk GTK4 display (foreground).
- status     — Show service states via Rich table.
- enable     — Start weston + kiosk + mavproxy services.
- disable    — Stop weston + kiosk + mavproxy services.
- install    — Generate + deploy kiosk systemd unit files.
- uninstall  — Remove kiosk systemd unit files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mower_rover.config.jetson import load_jetson_config

kiosk_app = typer.Typer(
    name="kiosk",
    help="Manage the kiosk operational display.",
    no_args_is_help=True,
)

# Service unit names managed by the kiosk subsystem
KIOSK_UNITS = [
    "mower-weston.service",
    "mower-kiosk.service",
    "mower-mavproxy.service",
]


@kiosk_app.command("run")
def kiosk_run_command(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override Jetson config path."
    ),
    endpoint: str | None = typer.Option(
        None, "--endpoint", help="MAVLink endpoint override (e.g. udp:127.0.0.1:14551)."
    ),
) -> None:
    """Start the kiosk GTK4 operational display (foreground)."""
    from mower_rover.kiosk.app import run_kiosk

    cfg = load_jetson_config(config)
    mavlink_ep = endpoint or cfg.kiosk.mavproxy_endpoint
    run_kiosk(mavlink_endpoint=mavlink_ep)


@kiosk_app.command("status")
def kiosk_status_command(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override Jetson config path."
    ),
) -> None:
    """Show kiosk-related service statuses."""
    cfg = load_jetson_config(config)
    console = Console()
    table = Table(title="Kiosk Service Status")
    table.add_column("Unit", style="cyan")
    table.add_column("State", style="bold")

    for unit in KIOSK_UNITS:
        state = _get_unit_state(unit)
        style = "green" if state == "active" else "red" if state == "failed" else "yellow"
        table.add_row(unit, f"[{style}]{state}[/{style}]")

    console.print(table)

    # Also show units from config
    extra_units = [
        u for u in cfg.kiosk.service_check_units if u not in KIOSK_UNITS
    ]
    if extra_units:
        table2 = Table(title="Monitored Services")
        table2.add_column("Unit", style="cyan")
        table2.add_column("State", style="bold")
        for unit in extra_units:
            state = _get_unit_state(unit)
            style = "green" if state == "active" else "red" if state == "failed" else "yellow"
            table2.add_row(unit, f"[{style}]{state}[/{style}]")
        console.print(table2)


@kiosk_app.command("enable")
def kiosk_enable_command(
    ctx: typer.Context,
) -> None:
    """Enable and start kiosk services (weston, kiosk, mavproxy)."""
    obj = ctx.obj or {}
    dry_run = bool(obj.get("dry_run"))
    console = Console()

    for unit in KIOSK_UNITS:
        if dry_run:
            console.print(f"[dim]DRY-RUN: systemctl enable --now {unit}[/dim]")
        else:
            subprocess.run(
                ["systemctl", "enable", "--now", unit],
                check=False,
            )
            console.print(f"[green]Enabled:[/green] {unit}")


@kiosk_app.command("disable")
def kiosk_disable_command(
    ctx: typer.Context,
) -> None:
    """Stop and disable kiosk services (weston, kiosk, mavproxy)."""
    obj = ctx.obj or {}
    dry_run = bool(obj.get("dry_run"))
    console = Console()

    for unit in reversed(KIOSK_UNITS):
        if dry_run:
            console.print(f"[dim]DRY-RUN: systemctl disable --now {unit}[/dim]")
        else:
            subprocess.run(
                ["systemctl", "disable", "--now", unit],
                check=False,
            )
            console.print(f"[yellow]Disabled:[/yellow] {unit}")


@kiosk_app.command("install")
def kiosk_install_command(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Override Jetson config path."
    ),
    target_user: str | None = typer.Option(
        None, "--target-user", help="User for the unit's User= line."
    ),
    target_home: str | None = typer.Option(
        None, "--target-home", help="Home dir for WorkingDirectory=."
    ),
) -> None:
    """Install kiosk systemd unit files (weston, kiosk, mavproxy)."""
    # Unit file generation is implemented in Phase 4.
    # This wires up the CLI interface now.
    from mower_rover.kiosk.units import install_kiosk_units

    obj = ctx.obj or {}
    cfg = load_jetson_config(config)

    from mower_rover.safety.confirm import ConfirmationAborted, SafetyContext

    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        install_kiosk_units(
            safety,
            config=cfg,
            target_user=target_user,
            target_home=target_home,
        )
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


@kiosk_app.command("uninstall")
def kiosk_uninstall_command(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove kiosk systemd unit files."""
    # Unit file removal is implemented in Phase 4.
    from mower_rover.kiosk.units import uninstall_kiosk_units

    obj = ctx.obj or {}

    from mower_rover.safety.confirm import ConfirmationAborted, SafetyContext

    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)
    try:
        uninstall_kiosk_units(safety)
    except ConfirmationAborted:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(code=1) from None


def _get_unit_state(unit: str) -> str:
    """Query systemctl for the active state of a unit."""
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "unknown"
