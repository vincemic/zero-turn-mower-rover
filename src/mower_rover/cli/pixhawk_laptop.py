"""`mower pixhawk ...` — laptop-side pixhawk commands that SSH to the Jetson."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from mower_rover.cli.jetson_remote import (
    _CfgOpt,
    _HostOpt,
    _KeyOpt,
    _StrictOpt,
    _UserOpt,
    client_for,
    resolve_endpoint,
)
from mower_rover.logging_setup.setup import get_logger
from mower_rover.transport.ssh import SshError

app = typer.Typer(
    name="pixhawk",
    help="Pixhawk firmware commands via SSH to the Jetson.",
    no_args_is_help=True,
)


# --- firmware-check ---------------------------------------------------------


@app.command("firmware-check")
def firmware_check_command(
    ctx: typer.Context,
    track: str = typer.Option("latest", "--track", help="Track to check: latest, beta, stable"),
    offline: bool = typer.Option(False, "--offline", help="Offline mode (no remote version check)"),
    json: bool = typer.Option(False, "--json", help="JSON output format"),
    port: str = typer.Option("/dev/ttyACM0", "--port", help="Pixhawk device path"),
    host: str | None = _HostOpt,
    user: str | None = _UserOpt,
    ssh_port: int | None = typer.Option(None, "--ssh-port", help="SSH port (default 22)."),
    key: Path | None = _KeyOpt,
    config: Path | None = _CfgOpt,
    strict_host_keys: str = _StrictOpt,
) -> None:
    """Check the current firmware version on the Pixhawk."""
    log = get_logger("cli.pixhawk").bind(op="firmware_check")

    # Build remote command
    remote_argv = ["mower-jetson", "pixhawk", "firmware-check"]
    if track != "latest":
        remote_argv.extend(["--track", track])
    if offline:
        remote_argv.append("--offline")
    if json:
        remote_argv.append("--json")
    if port != "/dev/ttyACM0":
        remote_argv.extend(["--port", port])

    endpoint = resolve_endpoint(host, user, ssh_port, key, config)
    client = client_for(ctx, endpoint, strict_host_keys)

    try:
        result = client.run(remote_argv, timeout=60.0)
    except SshError as exc:
        log.error("ssh_error", error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if result.stdout:
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()
    raise typer.Exit(code=result.returncode)


# --- firmware-update --------------------------------------------------------


@app.command("firmware-update")
def firmware_update_command(
    ctx: typer.Context,
    track: str = typer.Option("latest", "--track", help="Track to download: latest, beta, stable"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes on confirmations"),
    force: bool = typer.Option(False, "--force", help="Flash even if same version"),
    json: bool = typer.Option(False, "--json", help="JSON output format"),
    port: str = typer.Option("/dev/ttyACM0", "--port", help="Pixhawk device path"),
    host: str | None = _HostOpt,
    user: str | None = _UserOpt,
    ssh_port: int | None = typer.Option(None, "--ssh-port", help="SSH port (default 22)."),
    key: Path | None = _KeyOpt,
    config: Path | None = _CfgOpt,
    strict_host_keys: str = _StrictOpt,
) -> None:
    """Download and flash the latest firmware to the Pixhawk."""
    log = get_logger("cli.pixhawk").bind(op="firmware_update")

    # Build remote command
    remote_argv = ["mower-jetson", "pixhawk", "firmware-update"]
    if track != "latest":
        remote_argv.extend(["--track", track])
    if yes:
        remote_argv.append("--yes")
    if force:
        remote_argv.append("--force")
    if json:
        remote_argv.append("--json")
    if port != "/dev/ttyACM0":
        remote_argv.extend(["--port", port])

    # Pass through dry-run from context
    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    if dry_run:
        remote_argv.append("--dry-run")

    endpoint = resolve_endpoint(host, user, ssh_port, key, config)
    client = client_for(ctx, endpoint, strict_host_keys)

    try:
        result = client.run(remote_argv, timeout=300.0)  # Higher timeout for download + flash
    except SshError as exc:
        log.error("ssh_error", error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if result.stdout:
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()
    raise typer.Exit(code=result.returncode)


# --- firmware-flash ---------------------------------------------------------


@app.command("firmware-flash")
def firmware_flash_command(
    ctx: typer.Context,
    remote_path: str = typer.Argument(..., help="Path to .apj firmware file on the Jetson"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes on confirmations"),
    skip_snapshot: bool = typer.Option(
        False, "--skip-snapshot", help="Skip param backup before flash"
    ),
    json: bool = typer.Option(False, "--json", help="JSON output format"),
    port: str = typer.Option("/dev/ttyACM0", "--port", help="Pixhawk device path"),
    host: str | None = _HostOpt,
    user: str | None = _UserOpt,
    ssh_port: int | None = typer.Option(None, "--ssh-port", help="SSH port (default 22)."),
    key: Path | None = _KeyOpt,
    config: Path | None = _CfgOpt,
    strict_host_keys: str = _StrictOpt,
) -> None:
    """Flash a .apj firmware file that's already on the Jetson to the Pixhawk."""
    log = get_logger("cli.pixhawk").bind(op="firmware_flash", remote_path=remote_path)

    # Build remote command
    remote_argv = ["mower-jetson", "pixhawk", "firmware-flash", remote_path]
    if yes:
        remote_argv.append("--yes")
    if skip_snapshot:
        remote_argv.append("--skip-snapshot")
    if json:
        remote_argv.append("--json")
    if port != "/dev/ttyACM0":
        remote_argv.extend(["--port", port])

    # Pass through dry-run from context
    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    if dry_run:
        remote_argv.append("--dry-run")

    endpoint = resolve_endpoint(host, user, ssh_port, key, config)
    client = client_for(ctx, endpoint, strict_host_keys)

    try:
        result = client.run(remote_argv, timeout=300.0)  # Higher timeout for flash operation
    except SshError as exc:
        log.error("ssh_error", error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if result.stdout:
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()
    raise typer.Exit(code=result.returncode)
