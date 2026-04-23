"""`mower jetson bringup` — automated end-to-end Jetson provisioning.

Runs on the **laptop** (Windows or Linux). Walks through:

1. SSH connectivity check (gate)
2. Field hardening script
3. uv + Python 3.11 install
4. mower-jetson CLI install (wheel build + push)
5. Remote probe verification
6. systemd health service install + start
"""

from __future__ import annotations

import contextlib
import json as _json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mower_rover.logging_setup.setup import get_logger
from mower_rover.transport.ssh import JetsonClient, SshError

STEP_NAMES = ("check-ssh", "harden", "install-uv", "install-cli", "verify", "service")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BringupStep:
    """One logical step in the bringup sequence."""

    name: str
    description: str
    check: Callable[[JetsonClient], bool]
    execute: Callable[[JetsonClient, BringupContext], None]
    needs_confirm: bool = False


@dataclass
class BringupContext:
    """Shared state threaded through each bringup step."""

    project_root: Path
    dry_run: bool
    yes: bool
    correlation_id: str | None
    console: Console


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Walk up from this file looking for ``pyproject.toml``."""
    current = Path(__file__).resolve().parent
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    typer.echo(
        "ERROR: Could not locate pyproject.toml in any parent directory.\n"
        "Run this command from the source checkout: uv run mower jetson bringup",
        err=True,
    )
    raise typer.Exit(code=3)


def _confirm_or_skip(action: str, bctx: BringupContext) -> bool:
    """Return True if the operator confirms (or --yes); False to skip."""
    if bctx.yes:
        return True
    try:
        answer = input(f"{action} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


# ---------------------------------------------------------------------------
# Step: check-ssh
# ---------------------------------------------------------------------------


def _check_ssh_ok(client: JetsonClient) -> bool:
    try:
        result = client.run(["echo", "ok"], timeout=30)
        return result.ok and "ok" in result.stdout
    except SshError:
        return False


def _run_check_ssh(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print(
        "  [red]SSH connectivity failed.[/red]\n"
        "  Run [bold]mower jetson setup[/bold] first to configure SSH keys and connectivity."
    )
    raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: harden
# ---------------------------------------------------------------------------


def _harden_done(client: JetsonClient) -> bool:
    try:
        r1 = client.run(
            ["test", "-f", "/etc/ssh/sshd_config.d/90-mower-hardening.conf"],
            timeout=10,
        )
        r2 = client.run(["systemctl", "get-default"], timeout=10)
        return r1.ok and r2.stdout.strip() == "multi-user.target"
    except SshError:
        return False


def _run_harden(client: JetsonClient, bctx: BringupContext) -> None:
    if not _confirm_or_skip("Apply field-hardening script to the Jetson?", bctx):
        bctx.console.print("  Skipped by operator.")
        return

    script = bctx.project_root / "scripts" / "jetson-harden.sh"
    if not script.exists():
        bctx.console.print(f"  [red]Script not found:[/red] {script}")
        raise typer.Exit(code=3)

    bctx.console.print("  Pushing jetson-harden.sh…")
    try:
        client.push(script, "~/jetson-harden.sh")
    except SshError as exc:
        bctx.console.print(f"  [red]Push failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    bctx.console.print("  Running sudo bash jetson-harden.sh…")
    try:
        result = client.run(
            ["sudo", "bash", "~/jetson-harden.sh"], timeout=1200,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Hardening failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if result.stdout:
        bctx.console.print(result.stdout, highlight=False)
    if result.stderr:
        bctx.console.print(result.stderr, style="dim", highlight=False)

    if not result.ok:
        bctx.console.print(
            f"  [red]Hardening script exited {result.returncode}.[/red]"
        )
        raise typer.Exit(code=3)

    # Clean up temp file
    with contextlib.suppress(SshError):
        client.run(["rm", "-f", "~/jetson-harden.sh"], timeout=10)


# ---------------------------------------------------------------------------
# Step: install-uv
# ---------------------------------------------------------------------------


def _uv_installed(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["~/.local/bin/uv", "--version"],
            timeout=15,
        )
        return result.ok
    except SshError:
        return False


def _run_install_uv(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Installing uv…")
    # Prefer curl, fall back to wget
    try:
        has_curl = client.run(["which", "curl"], timeout=10)
    except SshError:
        has_curl = None
    if has_curl and has_curl.ok:
        dl_cmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"
    else:
        dl_cmd = "wget -qO- https://astral.sh/uv/install.sh | sh"
    try:
        result = client.run(
            [dl_cmd],
            timeout=120,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]uv install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]uv install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    bctx.console.print("  Installing Python 3.11 via uv…")
    try:
        result = client.run(
            ["~/.local/bin/uv", "python", "install", "3.11"],
            timeout=300,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Python install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Python install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: install-cli
# ---------------------------------------------------------------------------


def _cli_installed(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["~/.local/bin/mower-jetson", "--version"],
            timeout=15,
        )
        return result.ok
    except SshError:
        return False


def _run_install_cli(client: JetsonClient, bctx: BringupContext) -> None:
    log = get_logger("bringup").bind(step="install-cli")

    bctx.console.print("  Building wheel locally…")
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            build_result = subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(tmp_dir)],
                cwd=bctx.project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            bctx.console.print(f"  [red]Wheel build failed:[/red] {exc}")
            raise typer.Exit(code=3) from exc

        if build_result.returncode != 0:
            bctx.console.print(
                f"  [red]uv build exited {build_result.returncode}:[/red]"
            )
            if build_result.stderr:
                bctx.console.print(build_result.stderr, style="dim", highlight=False)
            raise typer.Exit(code=3)

        tmp_path = Path(tmp_dir)
        whls = list(tmp_path.glob("*.whl"))
        if not whls:
            bctx.console.print("  [red]No .whl file found after build.[/red]")
            raise typer.Exit(code=3)
        whl = whls[0]
        whl_name = whl.name
        log.info("wheel_built", whl=whl_name)

        bctx.console.print(f"  Pushing {whl_name}…")
        try:
            client.push(whl, f"~/{whl_name}")
        except SshError as exc:
            bctx.console.print(f"  [red]Push failed:[/red] {exc}")
            raise typer.Exit(code=3) from exc

    bctx.console.print("  Installing mower-jetson via uv tool…")
    try:
        result = client.run(
            [
                f"~/.local/bin/uv tool install --python 3.11 --force"
                f" --with sdnotify ~/{whl_name}",
            ],
            timeout=300,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Tool install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Tool install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    # Clean up remote wheel
    with contextlib.suppress(SshError):
        client.run(["rm", "-f", f"~/{whl_name}"], timeout=10)


# ---------------------------------------------------------------------------
# Step: verify
# ---------------------------------------------------------------------------


def _verify_check(_client: JetsonClient) -> bool:
    return False  # always runs


def _run_verify(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Running remote probe…")
    try:
        result = client.run(
            ["~/.local/bin/mower-jetson", "probe", "--json"],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Remote probe failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok and not result.stdout.strip():
        bctx.console.print(
            f"  [red]Remote probe exited {result.returncode}:[/red] {result.stderr.strip()}"
        )
        raise typer.Exit(code=3)

    try:
        checks = _json.loads(result.stdout)
    except (_json.JSONDecodeError, ValueError) as exc:
        bctx.console.print(f"  [red]Remote probe returned invalid JSON:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    status_emoji = {"pass": "\u2705", "fail": "\u274c", "skip": "\u23ed\ufe0f"}
    table = Table(title="Remote Probe Results")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Detail")
    critical_fails = []
    for c in checks:
        status = c.get("status", "?")
        emoji = status_emoji.get(status, "?")
        table.add_row(
            c.get("name", "?"),
            emoji,
            c.get("severity", "?"),
            c.get("detail", ""),
        )
        if status == "fail" and c.get("severity") == "critical":
            critical_fails.append(c.get("name", "?"))
    bctx.console.print(table)

    if critical_fails:
        bctx.console.print(
            f"  [red]Critical failures:[/red] {', '.join(critical_fails)}"
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Step: service
# ---------------------------------------------------------------------------


def _service_active(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["systemctl", "--user", "is-active", "mower-health.service"],
            timeout=10,
        )
        return result.ok
    except SshError:
        return False


def _run_service(client: JetsonClient, bctx: BringupContext) -> None:
    if not _confirm_or_skip("Install and start mower-health.service?", bctx):
        bctx.console.print("  Skipped by operator.")
        return

    bctx.console.print("  Installing service…")
    try:
        result = client.run(
            [
                "~/.local/bin/mower-jetson service install --yes",
            ],
            timeout=60,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Service install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Service install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    bctx.console.print("  Starting service…")
    try:
        result = client.run(
            [
                "~/.local/bin/mower-jetson service start",
            ],
            timeout=120,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Service start failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Service start exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step table
# ---------------------------------------------------------------------------

BRINGUP_STEPS: list[BringupStep] = [
    BringupStep(
        name="check-ssh",
        description="SSH connectivity",
        check=lambda c: _check_ssh_ok(c),
        execute=lambda c, b: _run_check_ssh(c, b),
    ),
    BringupStep(
        name="harden",
        description="Field hardening",
        check=lambda c: _harden_done(c),
        execute=lambda c, b: _run_harden(c, b),
        needs_confirm=True,
    ),
    BringupStep(
        name="install-uv",
        description="uv + Python 3.11",
        check=lambda c: _uv_installed(c),
        execute=lambda c, b: _run_install_uv(c, b),
    ),
    BringupStep(
        name="install-cli",
        description="mower-jetson CLI",
        check=lambda c: _cli_installed(c),
        execute=lambda c, b: _run_install_cli(c, b),
    ),
    BringupStep(
        name="verify",
        description="Remote probe verification",
        check=lambda c: _verify_check(c),
        execute=lambda c, b: _run_verify(c, b),
    ),
    BringupStep(
        name="service",
        description="mower-health.service",
        check=lambda c: _service_active(c),
        execute=lambda c, b: _run_service(c, b),
        needs_confirm=True,
    ),
]


# ---------------------------------------------------------------------------
# Main bringup command
# ---------------------------------------------------------------------------


def bringup_command(
    ctx: typer.Context,
    step: str | None = typer.Option(
        None,
        "--step",
        help=f"Run only this step: {', '.join(STEP_NAMES)}",
    ),
    host: str | None = typer.Option(None, "--host"),
    user: str | None = typer.Option(None, "--user"),
    port: int | None = typer.Option(None, "--port"),
    key: Path | None = typer.Option(None, "--key"),
    config: Path | None = typer.Option(None, "--config"),
    strict_host_keys: str = typer.Option("accept-new", "--strict-host-keys"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
) -> None:
    """Automated end-to-end Jetson provisioning.

    Walks through SSH check, hardening, uv/Python install, CLI deploy,
    remote probe, and service setup — skipping steps already satisfied.
    """
    from mower_rover.cli.jetson_remote import client_for, resolve_endpoint

    log = get_logger("bringup").bind(op="bringup")

    if step is not None and step not in STEP_NAMES:
        typer.echo(
            f"ERROR: Unknown step '{step}'. Valid steps: {', '.join(STEP_NAMES)}",
            err=True,
        )
        raise typer.Exit(code=2)

    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    project_root = _find_project_root()
    console = Console()

    bctx = BringupContext(
        project_root=project_root,
        dry_run=dry_run,
        yes=yes,
        correlation_id=ctx.obj.get("correlation_id") if ctx.obj else None,
        console=console,
    )

    endpoint = resolve_endpoint(host, user, port, key, config)
    client = client_for(ctx, endpoint, strict_host_keys)

    # Filter to single step if --step given
    steps = [s for s in BRINGUP_STEPS if s.name == step] if step is not None else BRINGUP_STEPS

    console.print("[bold]Jetson Bringup[/bold]\n")
    total = len(steps)

    for i, s in enumerate(steps, 1):
        console.print(f"[bold]Step {i}/{total}:[/bold] {s.description}")

        if dry_run:
            console.print(f"  DRY RUN — would execute step '{s.name}'.")
            log.info("dry_run_step", step=s.name)
            continue

        # When --step is given, always execute (skip the check)
        if step is None and s.check(client):
            console.print("  [green]\u2714 Already satisfied — skipping.[/green]")
            log.info("step_skipped", step=s.name)
            continue

        log.info("step_executing", step=s.name)
        s.execute(client, bctx)
        console.print("  [green]\u2714 Done.[/green]")

    console.print("\n[bold green]Bringup complete![/bold green]")
