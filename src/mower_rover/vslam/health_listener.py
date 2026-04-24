"""Laptop-side listener for VSLAM bridge health over MAVLink.

Listens on any MAVLink connection (SiK radio or SITL) for
``NAMED_VALUE_FLOAT`` messages with the ``VSLAM_`` prefix and heartbeats
from component 197, assembles them into a :class:`BridgeHealth` snapshot.
"""

from __future__ import annotations

import time
from typing import Any

from mower_rover.vslam.health import BridgeHealth

# MAVLink component ID for the VSLAM bridge companion
_BRIDGE_COMPONENT_ID = 197

# Metric names emitted by the bridge
_METRIC_NAMES = frozenset({"VSLAM_HZ", "VSLAM_CONF", "VSLAM_AGE", "VSLAM_COV"})


def listen_vslam_health(
    conn: Any,
    *,
    timeout_s: float = 5.0,
) -> BridgeHealth | None:
    """Listen for VSLAM health metrics on *conn*.

    Collects ``NAMED_VALUE_FLOAT`` messages with ``VSLAM_*`` names and a
    heartbeat from component 197.  Returns a :class:`BridgeHealth` once
    all four metrics have been received, or ``None`` on timeout.

    Parameters
    ----------
    conn:
        An open pymavlink connection (from ``open_link``).
    timeout_s:
        Maximum time to wait for a complete health snapshot.
    """
    metrics: dict[str, float] = {}
    bridge_heartbeat_seen = False
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break

        msg = conn.recv_match(
            type=["NAMED_VALUE_FLOAT", "HEARTBEAT"],
            blocking=True,
            timeout=min(remaining_ms / 1000.0, 1.0),
        )
        if msg is None:
            continue

        msg_type = msg.get_type()

        if msg_type == "HEARTBEAT":
            src_component = msg.get_srcComponent()  # type: ignore[attr-defined]
            if src_component == _BRIDGE_COMPONENT_ID:
                bridge_heartbeat_seen = True
            continue

        if msg_type == "NAMED_VALUE_FLOAT":
            name = msg.name  # type: ignore[attr-defined]
            # pymavlink may return bytes or str depending on version
            if isinstance(name, bytes):
                name = name.rstrip(b"\x00").decode("ascii", errors="replace")
            else:
                name = name.rstrip("\x00")
            if name in _METRIC_NAMES:
                metrics[name] = float(msg.value)  # type: ignore[attr-defined]

        # Check if we have all metrics
        if metrics.keys() >= _METRIC_NAMES:
            return BridgeHealth(
                pose_rate_hz=metrics["VSLAM_HZ"],
                pose_age_ms=metrics["VSLAM_AGE"],
                confidence=int(metrics["VSLAM_CONF"]),
                covariance_norm=metrics["VSLAM_COV"],
                bridge_connected=bridge_heartbeat_seen,
                slam_connected=metrics["VSLAM_HZ"] > 0,
            )

    # Partial result on timeout — return what we have
    if metrics:
        return BridgeHealth(
            pose_rate_hz=metrics.get("VSLAM_HZ", 0.0),
            pose_age_ms=metrics.get("VSLAM_AGE", float("inf")),
            confidence=int(metrics.get("VSLAM_CONF", 0)),
            covariance_norm=metrics.get("VSLAM_COV", 0.0),
            bridge_connected=bridge_heartbeat_seen,
            slam_connected=metrics.get("VSLAM_HZ", 0.0) > 0,
        )

    return None
