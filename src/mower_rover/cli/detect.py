"""`mower detect` — read-only hardware enumeration over MAVLink (FR-1).

Connects to the autopilot, collects identity / GNSS / servo / radio / EKF status,
and prints a high-contrast table (default) or JSON report (`--json`).

This command does not touch actuators and does not require confirmation, but it
still routes through structured logging.
"""

from __future__ import annotations

import json as _json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from mower_rover.logging_setup.setup import get_logger
from mower_rover.mavlink.connection import ConnectionConfig, open_link

# MAVLink constant — duplicated here to avoid importing pymavlink at module load.
_MAV_TYPE_GROUND_ROVER = 11


@dataclass
class GnssStatus:
    instance: int
    fix_type: int | None = None
    satellites_visible: int | None = None
    hdop: float | None = None
    yaw_deg: float | None = None
    rtk_baseline_mm: int | None = None
    rtk_iar_num_hypotheses: int | None = None


@dataclass
class ServoStatus:
    channel: int
    pwm_us: int | None = None


@dataclass
class RadioStatus:
    rssi: int | None = None
    remrssi: int | None = None
    txbuf_pct: int | None = None
    noise: int | None = None
    remnoise: int | None = None


@dataclass
class DetectReport:
    endpoint: str
    autopilot_version: str | None = None
    vehicle_type: int | None = None
    vehicle_is_rover: bool = False
    autopilot_id: int | None = None
    firmware_version_raw: int | None = None
    gnss: list[GnssStatus] = field(default_factory=list)
    servos: list[ServoStatus] = field(default_factory=list)
    radio: RadioStatus | None = None
    ekf_flags: int | None = None
    warnings: list[str] = field(default_factory=list)


def _collect(conn: Any, *, sample_window_s: float = 3.0) -> DetectReport:
    """Collect a snapshot of vehicle state by reading messages for `sample_window_s`."""
    log = get_logger("detect")
    report = DetectReport(endpoint=str(getattr(conn, "address", "?")))

    # Vehicle type comes from the heartbeat we already received in open_link.
    # Re-read once to capture it explicitly.
    hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=2.0)
    if hb is not None:
        report.vehicle_type = hb.type
        report.autopilot_id = hb.autopilot
        report.vehicle_is_rover = hb.type == _MAV_TYPE_GROUND_ROVER
        if not report.vehicle_is_rover:
            report.warnings.append(
                f"vehicle type {hb.type} is not MAV_TYPE_GROUND_ROVER ({_MAV_TYPE_GROUND_ROVER})"
            )

    # Request AUTOPILOT_VERSION explicitly (not streamed by default on most setups).
    try:
        from pymavlink import mavutil

        conn.mav.command_long_send(
            conn.target_system,
            conn.target_component,
            mavutil.mavlink.MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES,
            0, 1, 0, 0, 0, 0, 0, 0,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("request_autopilot_caps_failed", error=str(exc))

    gnss_by_instance: dict[int, GnssStatus] = {}
    servo_by_channel: dict[int, ServoStatus] = {}

    deadline = time.monotonic() + sample_window_s
    while time.monotonic() < deadline:
        msg = conn.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            continue
        mtype = msg.get_type()

        if mtype == "AUTOPILOT_VERSION":
            fw = getattr(msg, "flight_sw_version", None)
            report.firmware_version_raw = fw
            report.autopilot_version = f"0x{fw:08x}" if fw is not None else None

        elif mtype in ("GPS_RAW_INT", "GPS2_RAW"):
            instance = 0 if mtype == "GPS_RAW_INT" else 1
            g = gnss_by_instance.setdefault(instance, GnssStatus(instance=instance))
            g.fix_type = getattr(msg, "fix_type", g.fix_type)
            g.satellites_visible = getattr(msg, "satellites_visible", g.satellites_visible)
            eph = getattr(msg, "eph", None)
            g.hdop = (eph / 100.0) if isinstance(eph, int) and eph != 65535 else g.hdop
            yaw_raw = getattr(msg, "yaw", None)  # cdeg, 0 = unavailable, 36000 = north
            if isinstance(yaw_raw, int) and yaw_raw not in (0, 65535):
                g.yaw_deg = yaw_raw / 100.0

        elif mtype in ("GPS_RTK", "GPS2_RTK"):
            instance = 0 if mtype == "GPS_RTK" else 1
            g = gnss_by_instance.setdefault(instance, GnssStatus(instance=instance))
            g.rtk_baseline_mm = getattr(msg, "baseline_a_mm", g.rtk_baseline_mm)
            g.rtk_iar_num_hypotheses = getattr(msg, "iar_num_hypotheses", g.rtk_iar_num_hypotheses)

        elif mtype == "SERVO_OUTPUT_RAW":
            for ch in (1, 3):
                pwm = getattr(msg, f"servo{ch}_raw", None)
                if pwm:
                    servo_by_channel[ch] = ServoStatus(channel=ch, pwm_us=pwm)

        elif mtype == "RADIO_STATUS":
            report.radio = RadioStatus(
                rssi=getattr(msg, "rssi", None),
                remrssi=getattr(msg, "remrssi", None),
                txbuf_pct=getattr(msg, "txbuf", None),
                noise=getattr(msg, "noise", None),
                remnoise=getattr(msg, "remnoise", None),
            )

        elif mtype == "EKF_STATUS_REPORT":
            report.ekf_flags = getattr(msg, "flags", None)

    report.gnss = [gnss_by_instance[k] for k in sorted(gnss_by_instance)]
    report.servos = [servo_by_channel[k] for k in sorted(servo_by_channel)]

    if not report.gnss:
        report.warnings.append("no GPS messages observed")
    if not any(s.channel == 1 for s in report.servos):
        report.warnings.append("SERVO1 (steering left) not reporting")
    if not any(s.channel == 3 for s in report.servos):
        report.warnings.append("SERVO3 (steering right) not reporting")

    log.info("detect_complete", warnings=report.warnings)
    return report


def _render_human(report: DetectReport, console: Console) -> None:
    console.print(f"[bold]Endpoint[/bold]: {report.endpoint}")
    console.print(
        f"[bold]Vehicle[/bold]: type={report.vehicle_type} "
        f"rover={'yes' if report.vehicle_is_rover else 'NO'} "
        f"fw={report.autopilot_version or 'unknown'}"
    )

    g_table = Table(title="GNSS")
    for col in ("instance", "fix_type", "sats", "hdop", "yaw°", "rtk_iar"):
        g_table.add_column(col)
    for g in report.gnss:
        g_table.add_row(
            str(g.instance),
            str(g.fix_type),
            str(g.satellites_visible),
            f"{g.hdop:.2f}" if g.hdop is not None else "-",
            f"{g.yaw_deg:.1f}" if g.yaw_deg is not None else "-",
            str(g.rtk_iar_num_hypotheses) if g.rtk_iar_num_hypotheses is not None else "-",
        )
    console.print(g_table)

    s_table = Table(title="Servos")
    s_table.add_column("channel")
    s_table.add_column("pwm_us")
    for s in report.servos:
        s_table.add_row(str(s.channel), str(s.pwm_us))
    console.print(s_table)

    if report.radio is not None:
        console.print(
            f"[bold]Radio[/bold]: rssi={report.radio.rssi} remrssi={report.radio.remrssi} "
            f"txbuf={report.radio.txbuf_pct}%"
        )
    else:
        console.print("[bold]Radio[/bold]: no RADIO_STATUS observed (USB link?)")

    console.print(
        f"[bold]EKF flags[/bold]: {report.ekf_flags if report.ekf_flags is not None else 'unknown'}"
    )

    if report.warnings:
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for w in report.warnings:
            console.print(f"  - {w}")


def detect_command(
    endpoint: str = typer.Option(
        "udp:127.0.0.1:14550",
        "--port",
        "--endpoint",
        help="MAVLink endpoint. SITL default: udp:127.0.0.1:14550. Hardware: COM5 or /dev/ttyUSB0.",
    ),
    baud: int = typer.Option(57600, help="Serial baud (ignored for UDP/TCP endpoints)."),
    sample_seconds: float = typer.Option(3.0, help="How long to listen for messages."),
    json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON instead of a table."),  # noqa: E501
) -> None:
    """Detect and report connected hardware (autopilot, GNSS, servos, radio, EKF)."""
    config = ConnectionConfig(endpoint=endpoint, baud=baud)
    with open_link(config) as conn:
        report = _collect(conn, sample_window_s=sample_seconds)

    if json:
        typer.echo(_json.dumps(asdict(report), indent=2))
    else:
        _render_human(report, Console())


__all__ = ["DetectReport", "detect_command"]
