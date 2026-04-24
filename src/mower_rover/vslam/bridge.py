"""VSLAM → ArduPilot MAVLink bridge.

Reads pose messages from the RTAB-Map SLAM node via Unix socket IPC,
converts FLU → NED, and forwards ``VISION_POSITION_ESTIMATE`` /
``VISION_SPEED_ESTIMATE`` to the Cube Orange over USB serial
(``/dev/ttyACM0``).  Sends a component heartbeat at 1 Hz.

Designed to run as a systemd ``Type=notify`` daemon
(``mower-vslam-bridge.service``).
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from collections import deque

from mower_rover.config.vslam import VslamConfig, load_vslam_config
from mower_rover.logging_setup.setup import get_logger
from mower_rover.mavlink.connection import ConnectionConfig, open_link
from mower_rover.vslam.frames import flu_to_ned_pose, flu_to_ned_velocity
from mower_rover.vslam.health import TimestampedPose, compute_health
from mower_rover.vslam.ipc import PoseMessage, PoseReader
from mower_rover.vslam.lua_deploy import check_and_deploy_lua

try:
    import sdnotify

    _notifier: object = sdnotify.SystemdNotifier()
except ImportError:

    class _NoOpNotifier:
        def notify(self, state: str) -> None: ...

    _notifier = _NoOpNotifier()


def _build_connection_config(cfg: VslamConfig) -> ConnectionConfig:
    """Build a ``ConnectionConfig`` for the bridge from VSLAM YAML."""
    return ConnectionConfig(
        endpoint=cfg.bridge.serial_device,
        baud=0,  # USB CDC — pymavlink ignores baud for /dev/ttyACM*
        source_system=cfg.bridge.source_system,
        source_component=cfg.bridge.source_component,
        heartbeat_timeout_s=30.0,
        retry_attempts=5,
        retry_backoff_s=2.0,
    )


def _send_heartbeat(conn: object, log: object) -> None:
    """Send a component heartbeat (MAV_TYPE_ONBOARD_CONTROLLER, component 197)."""
    from pymavlink import mavutil

    conn.mav.heartbeat_send(  # type: ignore[attr-defined]
        type=mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
        autopilot=mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        base_mode=0,
        custom_mode=0,
        system_status=mavutil.mavlink.MAV_STATE_ACTIVE,
    )
    log.debug("heartbeat_sent")  # type: ignore[attr-defined]


def _send_named_value_float(conn: object, name: str, value: float) -> None:
    """Send a NAMED_VALUE_FLOAT message with null-padded 10-char name."""
    padded = name.encode("ascii").ljust(10, b"\x00")[:10]
    conn.mav.named_value_float_send(  # type: ignore[attr-defined]
        time_boot_ms=int(time.monotonic() * 1000) & 0xFFFFFFFF,
        name=padded,
        value=value,
    )


def _send_health_metrics(conn: object, health: object, log: object) -> None:
    """Emit NAMED_VALUE_FLOAT messages for all VSLAM health metrics."""
    from mower_rover.vslam.health import BridgeHealth

    h: BridgeHealth = health  # type: ignore[assignment]
    _send_named_value_float(conn, "VSLAM_HZ", h.pose_rate_hz)
    _send_named_value_float(conn, "VSLAM_CONF", float(h.confidence))
    _send_named_value_float(conn, "VSLAM_AGE", h.pose_age_ms)
    _send_named_value_float(conn, "VSLAM_COV", h.covariance_norm)
    log.debug(  # type: ignore[attr-defined]
        "health_emitted",
        hz=h.pose_rate_hz,
        conf=h.confidence,
        age_ms=h.pose_age_ms,
        cov=h.covariance_norm,
    )


def _send_statustext(conn: object, text: str) -> None:
    """Send a STATUSTEXT INFO message (max 50 chars)."""
    from pymavlink import mavutil

    conn.mav.statustext_send(  # type: ignore[attr-defined]
        severity=mavutil.mavlink.MAV_SEVERITY_INFO,
        text=text.encode("ascii")[:50],
    )


def _send_vision_position(
    conn: object,
    msg: PoseMessage,
    ned: tuple[float, float, float, float, float, float],
    reset_counter: int,
) -> None:
    """Send VISION_POSITION_ESTIMATE (msg_id 102)."""
    x, y, z, roll, pitch, yaw = ned
    # Covariance: MAVLink expects row-major upper-right triangle as a flat
    # array.  Our IPC sends the same layout — pass through.
    conn.mav.vision_position_estimate_send(  # type: ignore[attr-defined]
        usec=msg.timestamp_us,
        x=x,
        y=y,
        z=z,
        roll=roll,
        pitch=pitch,
        yaw=yaw,
        covariance=list(msg.covariance),
        reset_counter=reset_counter,
    )


def _send_vision_speed(
    conn: object,
    timestamp_us: int,
    ned_vel: tuple[float, float, float],
    reset_counter: int,
) -> None:
    """Send VISION_SPEED_ESTIMATE (msg_id 103)."""
    vx, vy, vz = ned_vel
    conn.mav.vision_speed_estimate_send(  # type: ignore[attr-defined]
        usec=timestamp_us,
        x=vx,
        y=vy,
        z=vz,
        covariance=[0.0] * 9,  # 3×3 identity-ish — placeholder until covariance propagation
        reset_counter=reset_counter,
    )


def _differentiate_velocity(
    prev: PoseMessage | None,
    cur: PoseMessage,
) -> tuple[float, float, float] | None:
    """Compute FLU velocity by differencing consecutive poses.

    Returns ``None`` when there is no previous pose or the timestamps
    are non-monotonic.
    """
    if prev is None:
        return None
    dt_s = (cur.timestamp_us - prev.timestamp_us) / 1_000_000.0
    if dt_s <= 0:
        return None
    return (
        (cur.x - prev.x) / dt_s,
        (cur.y - prev.y) / dt_s,
        (cur.z - prev.z) / dt_s,
    )


def run_bridge(
    *,
    config_path: str | None = None,
    _shutdown_event: threading.Event | None = None,
) -> None:
    """Main bridge loop — read poses, convert, and forward to ArduPilot.

    Parameters
    ----------
    config_path:
        Override path to ``vslam.yaml``.  ``None`` uses the default.
    _shutdown_event:
        For testing — external event to break the loop.
    """
    from pathlib import Path

    cfg = load_vslam_config(Path(config_path) if config_path else None)
    conn_cfg = _build_connection_config(cfg)
    log = get_logger("vslam.bridge").bind(
        serial=cfg.bridge.serial_device,
        component=cfg.bridge.source_component,
    )

    shutdown = _shutdown_event or threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("bridge_signal_received", signal=signum)
        shutdown.set()

    if _shutdown_event is None and threading.current_thread() is threading.main_thread():
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    reader = PoseReader(cfg.socket_path)

    with open_link(conn_cfg) as conn:
        # Deploy AHRS source-switching Lua script before entering pose loop
        check_and_deploy_lua(conn)

        _notifier.notify("READY=1")  # type: ignore[attr-defined]
        log.info("bridge_started")

        last_heartbeat = 0.0
        prev_msg: PoseMessage | None = None
        last_reset_counter = -1
        bridge_reset_counter = 0
        recent_poses: deque[TimestampedPose] = deque(maxlen=200)
        last_confidence = -1

        try:
            for msg in reader.read_poses():
                if shutdown.is_set():
                    break

                # Track confidence-driven reset counter
                if msg.reset_counter != last_reset_counter:
                    if last_reset_counter >= 0:
                        bridge_reset_counter += 1
                        log.info(
                            "reset_counter_changed",
                            old=last_reset_counter,
                            new=msg.reset_counter,
                            bridge_resets=bridge_reset_counter,
                        )
                    last_reset_counter = msg.reset_counter

                # FLU → NED
                ned_pose = flu_to_ned_pose(
                    msg.x, msg.y, msg.z, msg.roll, msg.pitch, msg.yaw
                )
                _send_vision_position(conn, msg, ned_pose, bridge_reset_counter)

                # Velocity from consecutive pose differencing
                flu_vel = _differentiate_velocity(prev_msg, msg)
                if flu_vel is not None:
                    ned_vel = flu_to_ned_velocity(*flu_vel)
                    _send_vision_speed(
                        conn, msg.timestamp_us, ned_vel, bridge_reset_counter
                    )
                prev_msg = msg

                # Track timestamped pose for health rate computation
                recent_poses.append((msg, time.monotonic()))

                # Confidence transition → STATUSTEXT
                if last_confidence >= 0 and msg.confidence != last_confidence:
                    if msg.confidence > 0 and last_confidence == 0:
                        _send_statustext(conn, "VSLAM tracking recovered")
                        log.info("vslam_tracking_recovered")
                    elif msg.confidence == 0 and last_confidence > 0:
                        _send_statustext(conn, "VSLAM tracking lost")
                        log.warning("vslam_tracking_lost")
                    else:
                        _send_statustext(
                            conn,
                            f"VSLAM conf {last_confidence}->{msg.confidence}",
                        )
                        log.info(
                            "vslam_confidence_changed",
                            old=last_confidence,
                            new=msg.confidence,
                        )
                last_confidence = msg.confidence

                # Heartbeat + health at ~1 Hz
                now = time.monotonic()
                if now - last_heartbeat >= 1.0:
                    _send_heartbeat(conn, log)
                    health = compute_health(
                        recent_poses,
                        bridge_connected=True,
                        slam_connected=True,
                        now_mono=now,
                    )
                    _send_health_metrics(conn, health, log)
                    _notifier.notify("WATCHDOG=1")  # type: ignore[attr-defined]
                    last_heartbeat = now

        except KeyboardInterrupt:
            log.info("bridge_keyboard_interrupt")
        finally:
            reader.close()
            log.info("bridge_stopped")
