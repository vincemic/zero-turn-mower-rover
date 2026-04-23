"""`mower jetson setup` — interactive first-time Jetson connectivity wizard.

Runs on the **laptop** (Windows or Linux). Walks the operator through:

1. SSH key generation
2. Jetson endpoint configuration (host / user)
3. Network connectivity check (ping)
4. SSH key deployment to the Jetson
5. laptop.yaml config file write
6. End-to-end verification via remote probe
"""

from __future__ import annotations

import json as _json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.console import Console

from mower_rover.config.laptop import (
    JetsonEndpoint,
    LaptopConfig,
    LaptopConfigError,
    load_laptop_config,
    save_laptop_config,
)
from mower_rover.logging_setup.setup import get_logger
from mower_rover.transport.ssh import JetsonClient, SshError

_DEFAULT_KEY_PATH = Path.home() / ".ssh" / "mower_id_ed25519"
_DEFAULT_HOST = "10.0.0.42"
_DEFAULT_USER = "mower"

_console = Console()


# ---------------------------------------------------------------------------
# Setup context — mutable state shared across steps
# ---------------------------------------------------------------------------


@dataclass
class SetupContext:
    """Mutable bag of state threaded through each setup step."""

    host: str | None = None
    user: str | None = None
    key_path: Path = field(default_factory=lambda: _DEFAULT_KEY_PATH)
    config_path: Path | None = None
    force: bool = False
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# SetupStep descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetupStep:
    """One logical step in the setup wizard."""

    name: str
    description: str
    check: Callable[[SetupContext], bool]
    execute: Callable[[SetupContext], None]


# ---------------------------------------------------------------------------
# Step 1 — SSH key
# ---------------------------------------------------------------------------


def _key_exists(ctx: SetupContext) -> bool:
    return ctx.key_path.exists()


def _generate_key(ctx: SetupContext) -> None:
    log = get_logger("setup").bind(step="ssh_key")
    key = ctx.key_path
    key.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        "ssh-keygen",
        "-t", "ed25519",
        "-f", str(key),
        "-N", "",
        "-C", "mower-rover-setup",
    ]
    log.info("ssh_keygen_start", key=str(key))
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, check=False,
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=3) from exc
    if result.returncode != 0:
        _console.print(f"[red]ssh-keygen failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(code=3)
    _console.print(f"  Key generated: {key}")


# ---------------------------------------------------------------------------
# Step 2 — Endpoint
# ---------------------------------------------------------------------------


def _endpoint_configured(ctx: SetupContext) -> bool:
    if ctx.host and ctx.user:
        return True
    env_host = os.environ.get("MOWER_JETSON_HOST")
    env_user = os.environ.get("MOWER_JETSON_USER")
    if env_host and env_user:
        ctx.host = env_host
        ctx.user = env_user
        return True
    try:
        cfg = load_laptop_config(ctx.config_path)
    except LaptopConfigError:
        return False
    if cfg.jetson and cfg.jetson.host and cfg.jetson.user:
        ctx.host = cfg.jetson.host
        ctx.user = cfg.jetson.user
        return True
    return False


def _prompt_endpoint(ctx: SetupContext) -> None:
    if not ctx.host:
        ctx.host = typer.prompt("Jetson host / IP", default=_DEFAULT_HOST)
    if not ctx.user:
        ctx.user = typer.prompt("Jetson SSH user", default=_DEFAULT_USER)


# ---------------------------------------------------------------------------
# Step 3 — Connectivity (ping)
# ---------------------------------------------------------------------------


def _ping_ok(ctx: SetupContext) -> bool:
    assert ctx.host is not None
    if sys.platform == "win32":
        argv = ["ping", "-n", "1", "-w", "3000", ctx.host]
    else:
        argv = ["ping", "-c", "1", "-W", "3", ctx.host]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=10, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _report_ping_failure(ctx: SetupContext) -> None:
    _console.print(f"[red]Cannot reach {ctx.host}.[/red]")
    _console.print("  • Verify the Jetson is powered on and on the same network.")
    _console.print("  • Check firewall rules on both ends.")
    _console.print("  • Try pinging manually and re-run setup.")
    raise typer.Exit(code=3)


def _check_connectivity(ctx: SetupContext) -> None:
    """Run ping; report and exit on failure."""
    if _ping_ok(ctx):
        return
    _report_ping_failure(ctx)


# ---------------------------------------------------------------------------
# Step 4 — Key deployment
# ---------------------------------------------------------------------------


def _key_auth_works(ctx: SetupContext) -> bool:
    assert ctx.host and ctx.user
    ssh_bin = _find_ssh()
    if ssh_bin is None:
        return False
    argv = [
        ssh_bin,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "PasswordAuthentication=no",
        "-i", str(ctx.key_path),
        f"{ctx.user}@{ctx.host}",
        "true",
    ]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=15, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _find_ssh() -> str | None:
    import shutil
    return shutil.which("ssh")


def _deploy_key(ctx: SetupContext) -> None:
    log = get_logger("setup").bind(step="key_deployed")
    assert ctx.host and ctx.user
    pub = ctx.key_path.with_suffix(".pub")
    if not pub.exists():
        _console.print(f"[red]Public key not found:[/red] {pub}")
        raise typer.Exit(code=3)
    ssh_bin = _find_ssh()
    if ssh_bin is None:
        _console.print("[red]ssh binary not found on PATH.[/red]")
        raise typer.Exit(code=3)

    target = f"{ctx.user}@{ctx.host}"
    mkdir_cmd = "mkdir -p ~/.ssh && chmod 700 ~/.ssh"
    cat_cmd = "cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    remote_cmd = f"{mkdir_cmd} && {cat_cmd}"

    _console.print(
        f"  Deploying public key to {target} — you may be prompted for the password."
    )
    log.info("key_deploy_start", target=target, pub=str(pub))

    if sys.platform == "win32":
        # Windows: pipe the public key via `type` into ssh
        shell_cmd = (
            f'type "{pub}" | "{ssh_bin}"'
            f' -o StrictHostKeyChecking=accept-new {target}'
            f' "{remote_cmd}"'
        )
        try:
            result = subprocess.run(
                shell_cmd, shell=True, timeout=60, check=False,
                capture_output=False,
            )
        except subprocess.TimeoutExpired:
            _console.print("[red]Key deployment timed out.[/red]")
            raise typer.Exit(code=3) from None
    else:
        # Linux/macOS: use ssh-copy-id for a cleaner UX
        ssh_copy_id = _find_binary("ssh-copy-id")
        if ssh_copy_id:
            argv = [ssh_copy_id, "-i", str(pub), target]
            try:
                result = subprocess.run(argv, timeout=60, check=False, capture_output=False)
            except subprocess.TimeoutExpired:
                _console.print("[red]Key deployment timed out.[/red]")
                raise typer.Exit(code=3) from None
        else:
            # Fallback: pipe via cat
            shell_cmd = (
                f'cat "{pub}" | "{ssh_bin}"'
                f" -o StrictHostKeyChecking=accept-new {target}"
                f" '{remote_cmd}'"
            )
            try:
                result = subprocess.run(
                    shell_cmd, shell=True, timeout=60, check=False,
                    capture_output=False,
                )
            except subprocess.TimeoutExpired:
                _console.print("[red]Key deployment timed out.[/red]")
                raise typer.Exit(code=3) from None

    if result.returncode != 0:
        _console.print("[red]Key deployment failed.[/red] Check the password and try again.")
        raise typer.Exit(code=3)
    _console.print("  Key deployed successfully.")


def _find_binary(name: str) -> str | None:
    import shutil
    return shutil.which(name)


# ---------------------------------------------------------------------------
# Step 5 — Config write
# ---------------------------------------------------------------------------


def _config_exists(ctx: SetupContext) -> bool:
    assert ctx.host and ctx.user
    try:
        cfg = load_laptop_config(ctx.config_path)
    except LaptopConfigError:
        return False
    if cfg.jetson is None:
        return False
    return (
        cfg.jetson.host == ctx.host
        and cfg.jetson.user == ctx.user
        and cfg.jetson.key_path == ctx.key_path
    )


def _write_config(ctx: SetupContext) -> None:
    log = get_logger("setup").bind(step="config")
    assert ctx.host and ctx.user
    try:
        existing = load_laptop_config(ctx.config_path)
    except LaptopConfigError:
        existing = LaptopConfig()
    existing.jetson = JetsonEndpoint(
        host=ctx.host,
        user=ctx.user,
        port=22,
        key_path=ctx.key_path,
    )
    saved = save_laptop_config(existing, ctx.config_path)
    log.info("config_written", path=str(saved))
    _console.print(f"  Config saved: {saved}")


# ---------------------------------------------------------------------------
# Step 6 — Verify (remote probe)
# ---------------------------------------------------------------------------


def _remote_probe_ok(ctx: SetupContext) -> bool:
    assert ctx.host and ctx.user
    endpoint = JetsonEndpoint(
        host=ctx.host, user=ctx.user, port=22, key_path=ctx.key_path,
    )
    client = JetsonClient(endpoint, correlation_id=ctx.correlation_id)
    try:
        result = client.run(
            ["mower-jetson", "probe", "--json"], check=False, timeout=30.0,
        )
    except SshError:
        return False
    if not result.ok:
        return False
    try:
        checks = _json.loads(result.stdout)
    except (ValueError, _json.JSONDecodeError):
        return False
    # Pass if no critical failures
    critical_fails = [
        c for c in checks
        if c.get("status") == "fail" and c.get("severity") == "critical"
    ]
    return len(critical_fails) == 0


def _run_remote_probe(ctx: SetupContext) -> None:
    """Run remote probe and print results; raise Exit on hard failure."""
    assert ctx.host and ctx.user
    endpoint = JetsonEndpoint(
        host=ctx.host, user=ctx.user, port=22, key_path=ctx.key_path,
    )
    client = JetsonClient(endpoint, correlation_id=ctx.correlation_id)
    try:
        result = client.run(
            ["mower-jetson", "probe", "--json"], check=False, timeout=30.0,
        )
    except SshError as exc:
        _console.print(f"[red]Remote probe failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        _console.print(
            f"[red]Remote probe exited {result.returncode}:[/red] {result.stderr.strip()}"
        )
        raise typer.Exit(code=3)
    try:
        checks = _json.loads(result.stdout)
    except (ValueError, _json.JSONDecodeError) as exc:
        _console.print(f"[red]Remote probe returned invalid JSON:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    _console.print("  Remote probe results:")
    for c in checks:
        status = c.get("status", "?")
        name = c.get("name", "?")
        detail = c.get("detail", "")
        icon = {"pass": "\u2705", "fail": "\u274c", "skip": "\u23ed\ufe0f"}.get(status, "?")
        _console.print(f"    {icon} {name}: {detail}")


# ---------------------------------------------------------------------------
# Step table
# ---------------------------------------------------------------------------

# Late-bound lambdas so that unittest.mock.patch on the module attribute
# is visible at call time (direct references would capture the original object).
SETUP_STEPS: list[SetupStep] = [
    SetupStep(
        name="ssh_key",
        description="SSH key pair exists",
        check=lambda ctx: _key_exists(ctx),
        execute=lambda ctx: _generate_key(ctx),
    ),
    SetupStep(
        name="endpoint",
        description="Jetson host/user configured",
        check=lambda ctx: _endpoint_configured(ctx),
        execute=lambda ctx: _prompt_endpoint(ctx),
    ),
    SetupStep(
        name="connectivity",
        description="Network connectivity to Jetson",
        check=lambda ctx: _ping_ok(ctx),
        execute=lambda ctx: _check_connectivity(ctx),
    ),
    SetupStep(
        name="key_deployed",
        description="SSH key deployed to Jetson",
        check=lambda ctx: _key_auth_works(ctx),
        execute=lambda ctx: _deploy_key(ctx),
    ),
    SetupStep(
        name="config",
        description="laptop.yaml written with endpoint",
        check=lambda ctx: _config_exists(ctx),
        execute=lambda ctx: _write_config(ctx),
    ),
    SetupStep(
        name="verify",
        description="Remote probe passes",
        check=lambda ctx: _remote_probe_ok(ctx),
        execute=lambda ctx: _run_remote_probe(ctx),
    ),
]


# ---------------------------------------------------------------------------
# Main setup command
# ---------------------------------------------------------------------------


def setup_command(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="Jetson hostname or IP."),
    user: str | None = typer.Option(None, "--user", help="SSH username on the Jetson."),
    key: Path | None = typer.Option(None, "--key", help="Path to SSH private key."),
    config: Path | None = typer.Option(None, "--config", help="Override laptop YAML config path."),
    force: bool = typer.Option(False, "--force", help="Re-run all steps even if checks pass."),
) -> None:
    """Interactive first-time setup wizard for Jetson SSH connectivity."""
    log = get_logger("setup").bind(op="setup")

    sctx = SetupContext(
        host=host,
        user=user,
        key_path=key or _DEFAULT_KEY_PATH,
        config_path=config,
        force=force,
        correlation_id=ctx.obj.get("correlation_id") if ctx.obj else None,
    )

    _console.print("[bold]Jetson Setup Wizard[/bold]\n")
    total = len(SETUP_STEPS)

    for i, step in enumerate(SETUP_STEPS, 1):
        _console.print(f"[bold]Step {i}/{total}:[/bold] {step.description}")

        if not sctx.force and step.check(sctx):
            _console.print("  [green]\u2714 Already satisfied — skipping.[/green]")
            log.info("step_skipped", step=step.name)
            continue

        log.info("step_executing", step=step.name)
        step.execute(sctx)
        _console.print("  [green]\u2714 Done.[/green]")

    _console.print("\n[bold green]Setup complete![/bold green]")


# ---------------------------------------------------------------------------
# Health command (renders remote probe results)
# ---------------------------------------------------------------------------


def health_command(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="Jetson hostname or IP."),
    user: str | None = typer.Option(None, "--user", help="SSH username on the Jetson."),
    port: int | None = typer.Option(None, "--port", help="SSH port (default 22)."),
    key: Path | None = typer.Option(None, "--key", help="Path to SSH private key."),
    config: Path | None = typer.Option(None, "--config", help="Override laptop YAML config path."),
    strict_host_keys: str = typer.Option(
        "accept-new", "--strict-host-keys",
        help="OpenSSH StrictHostKeyChecking policy.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON from remote probe."),
) -> None:
    """Run `mower-jetson probe --json` over SSH and render results locally."""
    from rich.table import Table

    from mower_rover.cli.jetson_remote import _client_for, _resolve_endpoint

    log = get_logger("cli.jetson").bind(op="health")
    endpoint = _resolve_endpoint(host, user, port, key, config)
    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    client = _client_for(ctx, endpoint, strict_host_keys)

    remote_argv = ["mower-jetson", "probe", "--json"]

    if dry_run:
        argv = client.build_ssh_argv(remote_argv)
        log.info("dry_run", argv=argv)
        typer.echo("DRY RUN — would execute:")
        typer.echo("  " + " ".join(argv))
        return

    try:
        result = client.run(remote_argv, check=False, timeout=30.0)
    except SshError as exc:
        log.error("ssh_error", error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if json_out:
        typer.echo(result.stdout, nl=False)
        raise typer.Exit(code=result.returncode)

    try:
        checks = _json.loads(result.stdout)
    except (_json.JSONDecodeError, ValueError) as exc:
        log.error("remote_json_invalid", stdout=result.stdout[:500], error=str(exc))
        typer.echo("ERROR: remote returned non-JSON output:", err=True)
        typer.echo(result.stdout, err=True)
        raise typer.Exit(code=3) from exc

    STATUS_EMOJI = {"pass": "\u2705", "fail": "\u274c", "skip": "\u23ed\ufe0f"}
    table = Table(title="Jetson Health (Remote Probe)")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Detail")
    for c in checks:
        emoji = STATUS_EMOJI.get(c.get("status", ""), "?")
        table.add_row(
            c.get("name", "?"),
            emoji,
            c.get("severity", "?"),
            c.get("detail", ""),
        )
    _console.print(table)
    raise typer.Exit(code=result.returncode)


__all__ = [
    "SETUP_STEPS",
    "SetupContext",
    "SetupStep",
    "health_command",
    "setup_command",
]
