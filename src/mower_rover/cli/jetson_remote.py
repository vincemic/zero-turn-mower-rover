"""`mower jetson ...` — laptop-side commands that talk to the Jetson over SSH."""

from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path

import typer

from mower_rover.config.laptop import (
    JetsonEndpoint,
    LaptopConfigError,
    load_laptop_config,
)
from mower_rover.logging_setup.setup import get_logger
from mower_rover.safety.confirm import (
    ConfirmationAborted,
    SafetyContext,
    requires_confirmation,
)
from mower_rover.transport.ssh import HOST_KEY_POLICIES, JetsonClient, SshError

app = typer.Typer(
    name="jetson",
    help="Run commands and pull files on the rover's Jetson over SSH.",
    no_args_is_help=True,
)


# --- endpoint resolution ----------------------------------------------------


def _resolve_endpoint(
    host: str | None,
    user: str | None,
    port: int | None,
    key: Path | None,
    config_path: Path | None,
) -> JetsonEndpoint:
    """Merge flags > env vars > YAML config; raise typer.Exit on failure."""
    log = get_logger("cli.jetson").bind(op="resolve_endpoint")
    env_host = os.environ.get("MOWER_JETSON_HOST")
    env_user = os.environ.get("MOWER_JETSON_USER")
    env_port = os.environ.get("MOWER_JETSON_PORT")
    env_key = os.environ.get("MOWER_JETSON_KEY")

    cfg_endpoint: JetsonEndpoint | None = None
    try:
        cfg_endpoint = load_laptop_config(config_path).jetson
    except LaptopConfigError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    resolved_host = host or env_host or (cfg_endpoint.host if cfg_endpoint else None)
    resolved_user = user or env_user or (cfg_endpoint.user if cfg_endpoint else None)
    if resolved_host is None or resolved_user is None:
        typer.echo(
            "ERROR: Jetson endpoint not configured. Pass --host/--user, set"
            " MOWER_JETSON_HOST/MOWER_JETSON_USER, or write a `jetson:` block in"
            f" {config_path or 'the laptop YAML config'}.",
            err=True,
        )
        raise typer.Exit(code=2)

    resolved_port = (
        port if port is not None
        else (int(env_port) if env_port else (cfg_endpoint.port if cfg_endpoint else 22))
    )
    resolved_key: Path | None
    if key is not None:
        resolved_key = key
    elif env_key:
        resolved_key = Path(env_key).expanduser()
    elif cfg_endpoint and cfg_endpoint.key_path is not None:
        resolved_key = cfg_endpoint.key_path
    else:
        resolved_key = None

    endpoint = JetsonEndpoint(
        host=resolved_host, user=resolved_user, port=resolved_port, key_path=resolved_key
    )
    log.info(
        "endpoint_resolved",
        host=endpoint.host,
        user=endpoint.user,
        port=endpoint.port,
        key=str(endpoint.key_path) if endpoint.key_path else None,
    )
    return endpoint


def _client_for(
    ctx: typer.Context, endpoint: JetsonEndpoint, strict_host_keys: str
) -> JetsonClient:
    cid = ctx.obj.get("correlation_id") if ctx.obj else None
    return JetsonClient(
        endpoint, correlation_id=cid, strict_host_keys=strict_host_keys
    )


# --- shared options ---------------------------------------------------------

_HostOpt = typer.Option(None, "--host", help="Jetson hostname or IP.")
_UserOpt = typer.Option(None, "--user", help="SSH username on the Jetson.")
_PortOpt = typer.Option(None, "--port", help="SSH port (default 22).")
_KeyOpt = typer.Option(None, "--key", help="Path to SSH private key.")
_CfgOpt = typer.Option(None, "--config", help="Override laptop YAML config path.")
_StrictOpt = typer.Option(
    "accept-new",
    "--strict-host-keys",
    help=f"OpenSSH StrictHostKeyChecking policy. One of: {', '.join(HOST_KEY_POLICIES)}",
)


# --- run --------------------------------------------------------------------


@app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run_command(
    ctx: typer.Context,
    host: str | None = _HostOpt,
    user: str | None = _UserOpt,
    port: int | None = _PortOpt,
    key: Path | None = _KeyOpt,
    config: Path | None = _CfgOpt,
    strict_host_keys: str = _StrictOpt,
    timeout: float = typer.Option(60.0, "--timeout", help="Per-command timeout (seconds)."),
) -> None:
    """Run a command on the Jetson over SSH. Pass remote argv after `--`.

    Example: `mower jetson run --host 10.0.0.42 --user mower -- uname -a`
    """
    log = get_logger("cli.jetson").bind(op="run")
    remote_argv = list(ctx.args)
    if not remote_argv:
        typer.echo("ERROR: pass the remote command after `--`, e.g. `-- uname -a`.", err=True)
        raise typer.Exit(code=2)

    endpoint = _resolve_endpoint(host, user, port, key, config)
    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    client = _client_for(ctx, endpoint, strict_host_keys)

    try:
        argv = client.build_ssh_argv(remote_argv)
    except SshError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if dry_run:
        log.info("dry_run", argv=argv)
        typer.echo("DRY RUN — would execute:")
        typer.echo("  " + " ".join(argv))
        return

    try:
        result = client.run(remote_argv, timeout=timeout)
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


# --- pull -------------------------------------------------------------------


@requires_confirmation("Overwrite local file with the remote copy")
def _confirm_overwrite(*, ctx: SafetyContext) -> None:
    return None


@app.command("pull")
def pull_command(
    ctx: typer.Context,
    remote: str = typer.Argument(..., help="Remote path on the Jetson."),
    local: Path = typer.Argument(..., help="Local destination path."),
    host: str | None = _HostOpt,
    user: str | None = _UserOpt,
    port: int | None = _PortOpt,
    key: Path | None = _KeyOpt,
    config: Path | None = _CfgOpt,
    strict_host_keys: str = _StrictOpt,
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes on overwrite."),
    timeout: float = typer.Option(600.0, "--timeout", help="Transfer timeout (seconds)."),
) -> None:
    """Copy a file from the Jetson to the laptop via scp."""
    log = get_logger("cli.jetson").bind(op="pull", remote=remote, local=str(local))
    endpoint = _resolve_endpoint(host, user, port, key, config)
    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    client = _client_for(ctx, endpoint, strict_host_keys)

    try:
        argv = client.build_scp_pull_argv(remote, local)
    except SshError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if dry_run:
        log.info("dry_run", argv=argv)
        typer.echo("DRY RUN — would execute:")
        typer.echo("  " + " ".join(argv))
        return

    if local.exists():
        safety = SafetyContext(dry_run=False, assume_yes=yes)
        try:
            _confirm_overwrite(ctx=safety)
        except ConfirmationAborted:
            typer.echo("Aborted (would overwrite existing local file).", err=True)
            raise typer.Exit(code=1) from None

    try:
        client.pull(remote, local, timeout=timeout)
    except SshError as exc:
        log.error("ssh_error", error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    typer.echo(f"Pulled {remote} -> {local}")


# --- info -------------------------------------------------------------------


@app.command("info")
def info_command(
    ctx: typer.Context,
    host: str | None = _HostOpt,
    user: str | None = _UserOpt,
    port: int | None = _PortOpt,
    key: Path | None = _KeyOpt,
    config: Path | None = _CfgOpt,
    strict_host_keys: str = _StrictOpt,
    raw: bool = typer.Option(False, "--raw", help="Print remote JSON unparsed."),
) -> None:
    """Run `mower-jetson info --json` over SSH and pretty-print the result."""
    log = get_logger("cli.jetson").bind(op="info")
    endpoint = _resolve_endpoint(host, user, port, key, config)
    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    client = _client_for(ctx, endpoint, strict_host_keys)

    remote_argv = ["mower-jetson", "info", "--json"]
    if dry_run:
        argv = client.build_ssh_argv(remote_argv)
        log.info("dry_run", argv=argv)
        typer.echo("DRY RUN — would execute:")
        typer.echo("  " + " ".join(argv))
        return

    try:
        result = client.run(remote_argv, check=True, timeout=30.0)
    except SshError as exc:
        log.error("ssh_error", error=str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if raw:
        typer.echo(result.stdout, nl=False)
        return
    try:
        data = _json.loads(result.stdout)
    except _json.JSONDecodeError as exc:
        log.error("remote_json_invalid", stdout=result.stdout[:500], error=str(exc))
        typer.echo("ERROR: remote returned non-JSON output:", err=True)
        typer.echo(result.stdout, err=True)
        raise typer.Exit(code=3) from exc
    for k in (
        "package_version", "hostname", "fqdn", "system", "release", "machine",
        "python_version", "jetpack_release", "is_jetson",
    ):
        typer.echo(f"{k:18}: {data.get(k)}")
    for w in data.get("warnings") or []:
        typer.echo(f"WARN: {w}", err=True)


__all__ = ["app"]
