"""`mower-jetson` CLI — Jetson Orin-side entry point.

Subcommands ship as Release 1 progresses (log collection, OAK-D detect,
VSLAM bring-up). For Phase 3 we provide:

- `mower-jetson info`         — platform identity (hostname, kernel, JetPack release).
- `mower-jetson config show`  — print the resolved Jetson YAML config.

Install convention: `pipx install .` on JetPack Ubuntu (aarch64). Systemd
units are intentionally deferred until a phase needs one.
"""

from __future__ import annotations

import json as _json
import os
import platform
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path

import typer

from mower_rover import __version__
from mower_rover.config.jetson import (
    DEFAULT_JETSON_CONFIG_PATH,
    JetsonConfigError,
    load_jetson_config,
)
from mower_rover.logging_setup.setup import configure_logging, get_logger

app = typer.Typer(
    name="mower-jetson",
    help="Jetson-side tooling for the zero-turn mower rover.",
    no_args_is_help=True,
)
config_app = typer.Typer(name="config", help="Inspect Jetson-side config.", no_args_is_help=True)
app.add_typer(config_app, name="config")


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
    warnings: list[str] = field(default_factory=list)


def _read_jetpack_release() -> str | None:
    if not _NV_TEGRA_RELEASE.exists():
        return None
    try:
        return _NV_TEGRA_RELEASE.read_text(encoding="utf-8").strip().splitlines()[0]
    except OSError:
        return None


def _collect_platform_info() -> PlatformInfo:
    jp = _read_jetpack_release()
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


if __name__ == "__main__":
    app()
