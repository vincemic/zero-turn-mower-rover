"""`mower params` — snapshot, diff, and apply ArduPilot Rover parameters (Phase 3).

Subcommands:
- `mower params snapshot`  — fetch all params from the autopilot, write JSON.
- `mower params diff`      — diff two snapshots, or snapshot vs the shipped baseline.
- `mower params apply`     — apply a YAML param file (snapshot first, diff, confirm).
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import typer
from rich.console import Console

from mower_rover.logging_setup.setup import get_logger
from mower_rover.mavlink.connection import ConnectionConfig, open_link
from mower_rover.params.baseline import BASELINE_PATH, PROFILES, load_baseline, load_profile
from mower_rover.params.diff import diff_params, render_diff
from mower_rover.params.io import (
    ParamSet,
    load_json_snapshot,
    load_param_file,
    write_json_snapshot,
)
from mower_rover.params.mav import apply_params, fetch_params
from mower_rover.safety.confirm import (
    ConfirmationAborted,
    SafetyContext,
    requires_confirmation,
)

app = typer.Typer(name="params", help="Snapshot, diff, and apply autopilot parameters.")


@app.command("snapshot")
def snapshot_command(
    output: Path = typer.Argument(..., help="Output JSON snapshot path."),
    endpoint: str = typer.Option(
        "udp:127.0.0.1:14550", "--port", "--endpoint", help="MAVLink endpoint."
    ),
    baud: int = typer.Option(57600, help="Serial baud (ignored for UDP/TCP)."),
    timeout: float = typer.Option(60.0, help="Overall fetch timeout (seconds)."),
) -> None:
    """Fetch every parameter from the autopilot and write a JSON snapshot."""
    log = get_logger("cli.params").bind(op="snapshot", output=str(output))
    with open_link(ConnectionConfig(endpoint=endpoint, baud=baud)) as conn:
        params = fetch_params(conn, timeout_s=timeout)
    write_json_snapshot(
        params,
        output,
        metadata={"endpoint": endpoint, "param_count": len(params)},
    )
    log.info("snapshot_written", count=len(params))
    typer.echo(f"Wrote {len(params)} params to {output}")


@app.command("diff")
def diff_command(
    left: Path = typer.Argument(
        ...,
        help="Left side: JSON snapshot, YAML, or .parm file. Use a profile name (e.g. 'baseline', 'safety-defaults') for a shipped profile.",  # noqa: E501
    ),
    right: Path = typer.Argument(
        ...,
        help="Right side (same formats as left).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Diff two param sets. Profile names ('baseline', 'safety-defaults', ...) resolve to shipped profiles."""  # noqa: E501
    left_set = _load_any(left)
    right_set = _load_any(right)
    diff = diff_params(left_set, right_set)
    if json_output:
        typer.echo(_json.dumps(diff.to_dict(), indent=2))
        return
    render_diff(diff, Console(), label_old=str(left), label_new=str(right))


@app.command("apply")
def apply_command(
    ctx: typer.Context,
    params_file: Path | None = typer.Argument(
        None,
        help="YAML/JSON/.parm file of params to apply. Use 'baseline' for the shipped baseline. Mutually exclusive with --profile.",  # noqa: E501
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help=f"Named profile to apply. Known: {', '.join(sorted(PROFILES))}. Mutually exclusive with PARAMS_FILE.",  # noqa: E501
    ),
    endpoint: str = typer.Option(
        "udp:127.0.0.1:14550", "--port", "--endpoint", help="MAVLink endpoint."
    ),
    baud: int = typer.Option(57600, help="Serial baud (ignored for UDP/TCP)."),
    snapshot_dir: Path | None = typer.Option(
        None,
        "--snapshot-dir",
        help="Directory to write a pre-apply JSON snapshot (default: skipped).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the interactive confirmation prompt."
    ),
) -> None:
    """Apply a param file. Snapshots first, shows the diff, requires confirmation."""
    if (params_file is None) == (profile is None):
        raise typer.BadParameter(
            "exactly one of PARAMS_FILE or --profile must be supplied"
        )
    if profile is not None:
        if profile not in PROFILES:
            known = ", ".join(sorted(PROFILES))
            raise typer.BadParameter(
                f"unknown profile {profile!r}; known: {known}"
            )
        desired = load_profile(profile)
        source_label = f"profile:{profile}"
    else:
        assert params_file is not None  # for mypy; guarded above
        desired = _load_any(params_file)
        source_label = str(params_file)
    log = get_logger("cli.params").bind(op="apply", source=source_label)
    console = Console()

    obj = ctx.obj or {}
    safety = SafetyContext(dry_run=bool(obj.get("dry_run")), assume_yes=yes)

    with open_link(ConnectionConfig(endpoint=endpoint, baud=baud)) as conn:
        log.info("snapshot_before_apply")
        before = fetch_params(conn)

        if snapshot_dir is not None:
            from datetime import UTC, datetime

            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            snap_path = snapshot_dir / f"params-pre-apply-{stamp}.json"
            write_json_snapshot(
                before,
                snap_path,
                metadata={"endpoint": endpoint, "purpose": "pre-apply"},
            )
            console.print(f"[dim]pre-apply snapshot: {snap_path}[/dim]")

        # Diff is computed against the *intersection* of names in `desired`,
        # so unrelated autopilot params don't show as "removed".
        before_subset = ParamSet.from_pairs(
            (n, before[n]) for n in desired if n in before
        )
        diff = diff_params(before_subset, desired)
        render_diff(diff, console, label_old="autopilot", label_new=source_label)

        if diff.is_empty:
            console.print("[bold green]Autopilot already matches; nothing to apply.[/bold green]")
            return

        try:
            _confirm_apply(
                ctx=safety,
                changes=len(diff.changed) + len(diff.added),
                source=source_label,
            )
        except ConfirmationAborted:
            console.print("[bold red]Aborted; no params written.[/bold red]")
            raise typer.Exit(code=1) from None

        if safety.dry_run:
            console.print("[bold yellow]--dry-run set; not writing to autopilot.[/bold yellow]")
            return

        apply_params(conn, desired)
        console.print(f"[bold green]Applied {len(desired)} params.[/bold green]")


@requires_confirmation(
    "Write parameters to the autopilot (this changes flight behaviour)",
)
def _confirm_apply(*, ctx: SafetyContext, changes: int, source: str) -> None:
    # Body intentionally empty — the decorator handles the prompt + log line;
    # the actual write happens after this returns.
    get_logger("cli.params").info("apply_confirmed", changes=changes, source=source)


def _load_any(path: Path) -> ParamSet:
    """Load a `ParamSet` from YAML, JSON snapshot, or .parm — or a named profile."""
    s = str(path)
    # Profile magic-strings (e.g. 'baseline', 'safety-defaults') resolve before
    # filesystem lookup so packaged profiles are addressable without a path.
    if s in PROFILES:
        return load_profile(s)
    if s.lower() == "baseline":
        return load_baseline()
    p = Path(s)
    if not p.exists():
        # Allow `baseline.yaml` as a friendly synonym.
        if s.lower() == BASELINE_PATH.name.lower():
            return load_baseline()
        raise typer.BadParameter(f"file not found: {p}")
    if p.suffix.lower() == ".json":
        try:
            return load_json_snapshot(p)
        except ValueError:
            # Plain JSON mapping fallback — let load_param_file handle it.
            return load_param_file(p)
    return load_param_file(p)


__all__ = ["app"]
