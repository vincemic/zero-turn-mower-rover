"""Tests for VSLAM bridge health computation and MAVLink health listener."""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

import pytest

from mower_rover.vslam.health import (
    BridgeHealth,
    TimestampedPose,
    _frobenius_norm,
    compute_health,
)
from mower_rover.vslam.health_listener import listen_vslam_health
from mower_rover.vslam.ipc import PoseMessage

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_pose(
    *,
    timestamp_us: int = 1_000_000,
    confidence: int = 3,
    covariance: tuple[float, ...] | None = None,
) -> PoseMessage:
    """Create a PoseMessage for testing."""
    cov = covariance if covariance is not None else tuple(0.01 * i for i in range(21))
    return PoseMessage(
        timestamp_us=timestamp_us,
        x=1.0,
        y=2.0,
        z=3.0,
        roll=0.0,
        pitch=0.0,
        yaw=0.0,
        covariance=cov,
        confidence=confidence,
        reset_counter=0,
    )


# ------------------------------------------------------------------
# BridgeHealth dataclass
# ------------------------------------------------------------------


class TestBridgeHealth:
    def test_frozen(self) -> None:
        h = BridgeHealth(
            pose_rate_hz=15.0,
            pose_age_ms=50.0,
            confidence=3,
            covariance_norm=0.1,
            bridge_connected=True,
            slam_connected=True,
        )
        with pytest.raises(AttributeError):
            h.pose_rate_hz = 0.0  # type: ignore[misc]

    def test_fields(self) -> None:
        h = BridgeHealth(
            pose_rate_hz=10.0,
            pose_age_ms=100.0,
            confidence=2,
            covariance_norm=0.5,
            bridge_connected=False,
            slam_connected=True,
        )
        assert h.pose_rate_hz == 10.0
        assert h.confidence == 2
        assert h.bridge_connected is False


# ------------------------------------------------------------------
# _frobenius_norm
# ------------------------------------------------------------------


class TestFrobeniusNorm:
    def test_zero_covariance(self) -> None:
        assert _frobenius_norm(tuple(0.0 for _ in range(21))) == 0.0

    def test_unit_covariance(self) -> None:
        cov = (1.0,) + tuple(0.0 for _ in range(20))
        assert _frobenius_norm(cov) == pytest.approx(1.0)

    def test_known_value(self) -> None:
        # sqrt(1^2 + 2^2 + 3^2) = sqrt(14)
        cov = (1.0, 2.0, 3.0) + tuple(0.0 for _ in range(18))
        assert _frobenius_norm(cov) == pytest.approx(14**0.5)


# ------------------------------------------------------------------
# compute_health
# ------------------------------------------------------------------


class TestComputeHealth:
    def test_empty_window(self) -> None:
        h = compute_health(deque(), now_mono=100.0)
        assert h.pose_rate_hz == 0.0
        assert h.pose_age_ms == float("inf")
        assert h.confidence == 0

    def test_single_pose(self) -> None:
        poses: deque[TimestampedPose] = deque()
        poses.append((_make_pose(confidence=3), 99.95))
        h = compute_health(poses, now_mono=100.0, window_s=2.0)
        assert h.confidence == 3
        assert h.pose_age_ms == pytest.approx(50.0, abs=1.0)
        assert h.pose_rate_hz == pytest.approx(0.5)  # 1 pose in 2s window

    def test_rate_computation(self) -> None:
        """15 poses in 1s window → 15 Hz."""
        now = 100.0
        poses: deque[TimestampedPose] = deque()
        for i in range(15):
            recv_t = now - 1.0 + i * (1.0 / 15)
            poses.append((_make_pose(), recv_t))
        h = compute_health(poses, now_mono=now, window_s=1.0)
        assert h.pose_rate_hz == pytest.approx(15.0)

    def test_bridge_and_slam_connected_flags(self) -> None:
        poses: deque[TimestampedPose] = deque()
        poses.append((_make_pose(), 100.0))
        h = compute_health(
            poses,
            bridge_connected=False,
            slam_connected=False,
            now_mono=100.0,
        )
        assert h.bridge_connected is False
        assert h.slam_connected is False

    def test_covariance_norm_computed(self) -> None:
        cov = tuple(1.0 for _ in range(21))
        poses: deque[TimestampedPose] = deque()
        poses.append((_make_pose(covariance=cov), 100.0))
        h = compute_health(poses, now_mono=100.0)
        # sqrt(21 * 1^2) = sqrt(21) ≈ 4.5826
        assert h.covariance_norm == pytest.approx(21**0.5, abs=0.001)


# ------------------------------------------------------------------
# listen_vslam_health — mock MAVLink
# ------------------------------------------------------------------


def _mock_named_value_float(name: str, value: float) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = "NAMED_VALUE_FLOAT"
    msg.name = name
    msg.value = value
    return msg


def _mock_heartbeat(component: int = 197) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = "HEARTBEAT"
    msg.get_srcComponent.return_value = component
    return msg


class TestListenVslamHealth:
    def test_complete_metrics(self) -> None:
        """Returns BridgeHealth when all 4 metrics + heartbeat received."""
        messages = [
            _mock_heartbeat(197),
            _mock_named_value_float("VSLAM_HZ", 15.0),
            _mock_named_value_float("VSLAM_CONF", 3.0),
            _mock_named_value_float("VSLAM_AGE", 50.0),
            _mock_named_value_float("VSLAM_COV", 0.05),
        ]
        conn = MagicMock()
        conn.recv_match.side_effect = messages

        health = listen_vslam_health(conn, timeout_s=5.0)
        assert health is not None
        assert health.pose_rate_hz == 15.0
        assert health.confidence == 3
        assert health.pose_age_ms == 50.0
        assert health.covariance_norm == 0.05
        assert health.bridge_connected is True
        assert health.slam_connected is True

    def test_timeout_no_messages(self) -> None:
        """Returns None when no messages arrive."""
        conn = MagicMock()
        conn.recv_match.return_value = None

        health = listen_vslam_health(conn, timeout_s=0.1)
        assert health is None

    def test_partial_metrics_on_timeout(self) -> None:
        """Returns partial BridgeHealth if some metrics arrive before timeout."""
        conn = MagicMock()
        real_msgs = [
            _mock_named_value_float("VSLAM_HZ", 10.0),
            _mock_named_value_float("VSLAM_CONF", 2.0),
        ]
        call_count = 0

        def _recv(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            idx = call_count
            call_count += 1
            return real_msgs[idx] if idx < len(real_msgs) else None

        conn.recv_match.side_effect = _recv

        health = listen_vslam_health(conn, timeout_s=0.2)
        assert health is not None
        assert health.pose_rate_hz == 10.0
        assert health.confidence == 2

    def test_bytes_name_handling(self) -> None:
        """Handles NAMED_VALUE_FLOAT with bytes name (null-padded)."""
        messages = [
            _mock_named_value_float(b"VSLAM_HZ\x00\x00", 12.0),  # type: ignore[arg-type]
            _mock_named_value_float(b"VSLAM_CONF\x00", 3.0),  # type: ignore[arg-type]
            _mock_named_value_float(b"VSLAM_AGE\x00", 30.0),  # type: ignore[arg-type]
            _mock_named_value_float(b"VSLAM_COV\x00", 0.1),  # type: ignore[arg-type]
        ]
        conn = MagicMock()
        conn.recv_match.side_effect = messages

        health = listen_vslam_health(conn, timeout_s=5.0)
        assert health is not None
        assert health.pose_rate_hz == 12.0

    def test_ignores_non_vslam_named_values(self) -> None:
        """Non-VSLAM NAMED_VALUE_FLOAT messages are ignored."""
        messages = [
            _mock_named_value_float("OTHER_VAL", 999.0),
            _mock_named_value_float("VSLAM_HZ", 15.0),
            _mock_named_value_float("VSLAM_CONF", 3.0),
            _mock_named_value_float("VSLAM_AGE", 50.0),
            _mock_named_value_float("VSLAM_COV", 0.05),
        ]
        conn = MagicMock()
        conn.recv_match.side_effect = messages

        health = listen_vslam_health(conn, timeout_s=5.0)
        assert health is not None
        assert health.pose_rate_hz == 15.0

    def test_heartbeat_from_wrong_component_ignored(self) -> None:
        """Heartbeat from non-197 component doesn't set bridge_connected."""
        messages = [
            _mock_heartbeat(1),  # autopilot, not bridge
            _mock_named_value_float("VSLAM_HZ", 15.0),
            _mock_named_value_float("VSLAM_CONF", 3.0),
            _mock_named_value_float("VSLAM_AGE", 50.0),
            _mock_named_value_float("VSLAM_COV", 0.05),
        ]
        conn = MagicMock()
        conn.recv_match.side_effect = messages

        health = listen_vslam_health(conn, timeout_s=5.0)
        assert health is not None
        assert health.bridge_connected is False

    def test_slam_not_connected_when_hz_zero(self) -> None:
        """slam_connected is False when VSLAM_HZ is 0."""
        messages = [
            _mock_named_value_float("VSLAM_HZ", 0.0),
            _mock_named_value_float("VSLAM_CONF", 0.0),
            _mock_named_value_float("VSLAM_AGE", 5000.0),
            _mock_named_value_float("VSLAM_COV", 0.0),
        ]
        conn = MagicMock()
        conn.recv_match.side_effect = messages

        health = listen_vslam_health(conn, timeout_s=5.0)
        assert health is not None
        assert health.slam_connected is False
