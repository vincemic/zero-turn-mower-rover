"""VSLAM bridge health metrics computation.

Computes health statistics from a sliding window of recent pose messages
for emission as ``NAMED_VALUE_FLOAT`` over MAVLink.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

from mower_rover.vslam.ipc import PoseMessage

#: Type alias for a timestamped pose: ``(pose, monotonic_receipt_time)``.
TimestampedPose = tuple[PoseMessage, float]


@dataclass(frozen=True, slots=True)
class BridgeHealth:
    """Point-in-time health snapshot of the VSLAM bridge."""

    pose_rate_hz: float
    pose_age_ms: float
    confidence: int
    covariance_norm: float
    bridge_connected: bool
    slam_connected: bool


def _frobenius_norm(covariance: tuple[float, ...]) -> float:
    """Frobenius norm of the covariance (from upper-triangle elements)."""
    return math.sqrt(sum(c * c for c in covariance))


def compute_health(
    recent_poses: deque[TimestampedPose],
    *,
    bridge_connected: bool = True,
    slam_connected: bool = True,
    now_mono: float | None = None,
    window_s: float = 2.0,
) -> BridgeHealth:
    """Compute bridge health from a sliding window of recent poses.

    Parameters
    ----------
    recent_poses:
        Deque of ``(PoseMessage, recv_mono)`` tuples (newest last).
    bridge_connected:
        Whether the MAVLink connection to the Cube is alive.
    slam_connected:
        Whether the SLAM IPC socket is connected.
    now_mono:
        Override for ``time.monotonic()`` (testing).
    window_s:
        Duration of the rate-computation window in seconds.
    """
    now = now_mono if now_mono is not None else time.monotonic()

    if not recent_poses:
        return BridgeHealth(
            pose_rate_hz=0.0,
            pose_age_ms=float("inf"),
            confidence=0,
            covariance_norm=0.0,
            bridge_connected=bridge_connected,
            slam_connected=slam_connected,
        )

    latest_pose, latest_recv = recent_poses[-1]

    # Pose age: wall-clock time since the most recent pose was received.
    pose_age_ms = (now - latest_recv) * 1000.0

    # Rate: count poses within the window
    cutoff = now - window_s
    count = sum(1 for _, recv_t in recent_poses if recv_t >= cutoff)
    pose_rate_hz = count / window_s if window_s > 0 else 0.0

    return BridgeHealth(
        pose_rate_hz=round(pose_rate_hz, 1),
        pose_age_ms=round(pose_age_ms, 1),
        confidence=latest_pose.confidence,
        covariance_norm=round(_frobenius_norm(latest_pose.covariance), 4),
        bridge_connected=bridge_connected,
        slam_connected=slam_connected,
    )
