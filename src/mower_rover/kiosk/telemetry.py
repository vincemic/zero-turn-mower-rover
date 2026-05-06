"""MAVLink telemetry reader loop for the kiosk display.

Connects to a MAVProxy UDP output and continuously parses incoming messages
to update :class:`~mower_rover.kiosk.state.SharedState`.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from mower_rover.kiosk.state import SharedState
from mower_rover.logging_setup.setup import get_logger

_log = get_logger("kiosk.telemetry")

# ArduPilot mode mapping for Rover (subset used by this mower)
_ROVER_MODES: dict[int, str] = {
    0: "MANUAL",
    1: "ACRO",
    3: "STEERING",
    4: "HOLD",
    5: "LOITER",
    6: "FOLLOW",
    7: "SIMPLE",
    10: "AUTO",
    11: "RTL",
    12: "SMART_RTL",
    15: "GUIDED",
}


def mavlink_reader_loop(
    state: SharedState,
    shutdown: threading.Event,
    *,
    endpoint: str = "udp:127.0.0.1:14550",
    source_system: int = 254,
    conn: Any | None = None,
) -> None:
    """Read MAVLink messages and update *state* until *shutdown* is set.

    Parameters
    ----------
    state:
        Shared state container to update with telemetry.
    shutdown:
        Event that signals the loop to exit.
    endpoint:
        pymavlink connection string (ignored if *conn* is provided).
    source_system:
        MAVLink source system ID for this GCS.
    conn:
        Optional pre-built MAVLink connection (for testing).
    """
    if conn is None:
        from pymavlink import mavutil

        _log.info("telemetry_connecting", endpoint=endpoint)
        conn = mavutil.mavlink_connection(
            endpoint,
            source_system=source_system,
            autoreconnect=True,
        )
        # Wait for initial heartbeat with unbounded retry
        while not shutdown.is_set():
            hb = conn.wait_heartbeat(timeout=10.0)
            if hb is not None:
                break
            _log.warning("telemetry_no_heartbeat_retry", endpoint=endpoint)
        if shutdown.is_set():
            return
        _log.info("telemetry_connected", target_system=conn.target_system)

    while not shutdown.is_set():
        msg = conn.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            continue

        mtype = msg.get_type()

        if mtype == "HEARTBEAT":
            _handle_heartbeat(state, msg)
        elif mtype == "VFR_HUD":
            _handle_vfr_hud(state, msg)
        elif mtype in ("GPS_RAW_INT", "GPS2_RAW"):
            _handle_gps_raw(state, msg, mtype)
        elif mtype in ("GPS_RTK", "GPS2_RTK"):
            _handle_gps_rtk(state, msg, mtype)
        elif mtype == "NAMED_VALUE_FLOAT":
            _handle_named_value_float(state, msg)
        elif mtype == "STATUSTEXT":
            _handle_statustext(state, msg)

    _log.info("telemetry_loop_exiting")


def _handle_heartbeat(state: SharedState, msg: Any) -> None:
    """Parse HEARTBEAT for armed state and flight mode."""
    # base_mode bit 7 = armed
    armed = bool(getattr(msg, "base_mode", 0) & 128)
    custom_mode = getattr(msg, "custom_mode", 0)
    mode_name = _ROVER_MODES.get(custom_mode, f"MODE_{custom_mode}")
    system_status = getattr(msg, "system_status", 0)

    state.update_mav(
        armed=armed,
        mode=mode_name,
        system_status=system_status,
        last_heartbeat_epoch=time.time(),
    )


def _handle_vfr_hud(state: SharedState, msg: Any) -> None:
    """Parse VFR_HUD for speed, heading, throttle."""
    state.update_mav(
        groundspeed_ms=getattr(msg, "groundspeed", 0.0),
        heading_deg=getattr(msg, "heading", 0),
        throttle_pct=getattr(msg, "throttle", 0),
    )


def _handle_gps_raw(state: SharedState, msg: Any, mtype: str) -> None:
    """Parse GPS_RAW_INT / GPS2_RAW for fix, sats, hdop."""
    is_gps1 = mtype == "GPS_RAW_INT"
    fix_type = getattr(msg, "fix_type", 0)
    sats = getattr(msg, "satellites_visible", 0)
    eph = getattr(msg, "eph", None)
    hdop = (eph / 100.0) if isinstance(eph, int) and eph != 65535 else 99.99

    if is_gps1:
        state.update_mav(
            gps1_fix=fix_type,
            gps1_sats=sats,
            gps1_hdop=hdop,
            last_gps_epoch=time.time(),
        )
    else:
        state.update_mav(
            gps2_fix=fix_type,
            gps2_sats=sats,
            gps2_hdop=hdop,
            last_gps_epoch=time.time(),
        )


def _handle_gps_rtk(state: SharedState, msg: Any, mtype: str) -> None:
    """Parse GPS_RTK / GPS2_RTK for baseline and IAR."""
    is_rtk1 = mtype == "GPS_RTK"
    baseline = getattr(msg, "baseline_a_mm", 0)
    iar = getattr(msg, "iar_num_hypotheses", 0)

    if is_rtk1:
        state.update_mav(rtk1_baseline_mm=baseline, rtk1_iar=iar)
    else:
        state.update_mav(rtk2_baseline_mm=baseline, rtk2_iar=iar)


_VSLAM_METRIC_NAMES: dict[str, str] = {
    "VSLAM_HZ": "rate_hz",
    "VSLAM_CONF": "confidence",
    "VSLAM_AGE": "age_ms",
    "VSLAM_COV": "covariance_norm",
}


def _handle_named_value_float(state: SharedState, msg: Any) -> None:
    """Parse NAMED_VALUE_FLOAT for VSLAM metrics."""
    name = msg.name
    # pymavlink may return bytes or str depending on version
    if isinstance(name, bytes):
        name = name.rstrip(b"\x00").decode("ascii", errors="replace")
    else:
        name = name.rstrip("\x00")
    key = _VSLAM_METRIC_NAMES.get(name)
    if key is not None:
        state.update_vslam(**{key: float(msg.value)})


def _handle_statustext(state: SharedState, msg: Any) -> None:
    """Parse STATUSTEXT for last message."""
    text = getattr(msg, "text", "")
    if text:
        state.update_mav(last_statustext=text)
