"""`mower` CLI — laptop-side entry point."""

from __future__ import annotations

import typer

from mower_rover import __version__
from mower_rover.cli.detect import detect_command
from mower_rover.cli.jetson_remote import app as jetson_remote_app
from mower_rover.cli.params import app as params_app
from mower_rover.logging_setup.setup import configure_logging, get_logger

app = typer.Typer(
    name="mower",
    help="Laptop-side tooling for the zero-turn mower rover.",
    no_args_is_help=True,
)


@app.callback()
def _root(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Skip any actuator-touching action; planning + read-only ops still run.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose console output."),
) -> None:
    cid, log_file = configure_logging(console_level="DEBUG" if verbose else "INFO")
    ctx.ensure_object(dict)
    ctx.obj["dry_run"] = dry_run
    ctx.obj["correlation_id"] = cid
    ctx.obj["log_file"] = log_file
    get_logger("cli").info(
        "cli_invoked",
        version=__version__,
        dry_run=dry_run,
        log_file=str(log_file),
    )


app.command("detect")(detect_command)
app.add_typer(params_app, name="params")
app.add_typer(jetson_remote_app, name="jetson")


@app.command("version")
def version() -> None:
    """Print the installed mower-rover version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
