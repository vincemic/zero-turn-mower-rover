"""`mower vslam` — laptop-side VSLAM health monitoring commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from mower_rover.logging_setup.setup import get_logger
from mower_rover.mavlink.connection import ConnectionConfig, open_link
from mower_rover.vslam.health_listener import listen_vslam_health

app = typer.Typer(name="vslam", help="VSLAM bridge monitoring (laptop-side, over SiK radio).")


@app.command("health")
def health_command(
    endpoint: str = typer.Option(
        "udp:127.0.0.1:14550",
        "--port",
        "--endpoint",
        help="MAVLink endpoint (SiK radio COM port or SITL UDP).",
    ),
    baud: int = typer.Option(57600, help="Serial baud (ignored for UDP/TCP)."),
    timeout: float = typer.Option(5.0, help="Seconds to wait for health metrics."),
) -> None:
    """Display VSLAM bridge health received over MAVLink."""
    log = get_logger("cli.vslam").bind(op="health")
    console = Console()

    with open_link(ConnectionConfig(endpoint=endpoint, baud=baud)) as conn:
        log.info("listening_for_vslam_health", endpoint=endpoint)
        health = listen_vslam_health(conn, timeout_s=timeout)

    if health is None:
        console.print(
            "[bold red]No VSLAM health metrics received[/bold red] "
            f"(waited {timeout:.0f}s on {endpoint})"
        )
        raise typer.Exit(code=1)

    table = Table(
        title="VSLAM Bridge Health",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Status", justify="center")

    # Pose rate
    hz_status = "[green]OK[/green]" if health.pose_rate_hz >= 5.0 else "[red]LOW[/red]"
    table.add_row("Pose Rate", f"{health.pose_rate_hz:.1f} Hz", hz_status)

    # Confidence
    conf_labels = {0: "[red]LOST[/red]", 1: "[yellow]LOW[/yellow]", 2: "[green]MED[/green]"}
    conf_str = conf_labels.get(health.confidence, "[bold green]HIGH[/bold green]")
    table.add_row("Confidence", str(health.confidence), conf_str)

    # Pose age
    age_status = "[green]OK[/green]" if health.pose_age_ms < 500 else "[red]STALE[/red]"
    table.add_row("Pose Age", f"{health.pose_age_ms:.0f} ms", age_status)

    # Covariance norm
    cov_status = "[green]OK[/green]" if health.covariance_norm < 1.0 else "[yellow]HIGH[/yellow]"
    table.add_row("Covariance Norm", f"{health.covariance_norm:.4f}", cov_status)

    # Connection state
    bridge_str = "[green]YES[/green]" if health.bridge_connected else "[red]NO[/red]"
    table.add_row("Bridge Connected", "", bridge_str)

    slam_str = "[green]YES[/green]" if health.slam_connected else "[red]NO[/red]"
    table.add_row("SLAM Connected", "", slam_str)

    console.print(table)
