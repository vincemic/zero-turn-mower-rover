"""Tests for FLU → NED frame conversions — no hardware required."""

from __future__ import annotations

import math

import pytest

from mower_rover.vslam.frames import flu_to_ned_pose, flu_to_ned_velocity

# ------------------------------------------------------------------
# flu_to_ned_pose
# ------------------------------------------------------------------


class TestFluToNedPose:
    """Verify sign flips per research 007 reference table."""

    def test_identity(self) -> None:
        """All zeros → all zeros."""
        assert flu_to_ned_pose(0, 0, 0, 0, 0, 0) == (0, 0, 0, 0, 0, 0)

    def test_x_preserved(self) -> None:
        result = flu_to_ned_pose(1.0, 0, 0, 0, 0, 0)
        assert result[0] == pytest.approx(1.0)

    def test_y_negated(self) -> None:
        result = flu_to_ned_pose(0, 2.5, 0, 0, 0, 0)
        assert result[1] == pytest.approx(-2.5)

    def test_z_negated(self) -> None:
        result = flu_to_ned_pose(0, 0, 3.0, 0, 0, 0)
        assert result[2] == pytest.approx(-3.0)

    def test_roll_preserved(self) -> None:
        result = flu_to_ned_pose(0, 0, 0, 0.1, 0, 0)
        assert result[3] == pytest.approx(0.1)

    def test_pitch_negated(self) -> None:
        result = flu_to_ned_pose(0, 0, 0, 0, 0.2, 0)
        assert result[4] == pytest.approx(-0.2)

    def test_yaw_negated(self) -> None:
        result = flu_to_ned_pose(0, 0, 0, 0, 0, math.pi / 4)
        assert result[5] == pytest.approx(-math.pi / 4)

    def test_full_pose(self) -> None:
        """Combined pose — all components at once."""
        x, y, z, r, p, ya = flu_to_ned_pose(1.0, 2.0, 3.0, 0.1, 0.2, 0.3)
        assert x == pytest.approx(1.0)
        assert y == pytest.approx(-2.0)
        assert z == pytest.approx(-3.0)
        assert r == pytest.approx(0.1)
        assert p == pytest.approx(-0.2)
        assert ya == pytest.approx(-0.3)

    def test_negative_inputs(self) -> None:
        """Negative FLU values should also flip correctly."""
        x, y, z, r, p, ya = flu_to_ned_pose(-1.0, -2.0, -3.0, -0.1, -0.2, -0.3)
        assert x == pytest.approx(-1.0)
        assert y == pytest.approx(2.0)
        assert z == pytest.approx(3.0)
        assert r == pytest.approx(-0.1)
        assert p == pytest.approx(0.2)
        assert ya == pytest.approx(0.3)

    def test_returns_tuple(self) -> None:
        result = flu_to_ned_pose(1, 2, 3, 0.1, 0.2, 0.3)
        assert isinstance(result, tuple)
        assert len(result) == 6


# ------------------------------------------------------------------
# flu_to_ned_velocity
# ------------------------------------------------------------------


class TestFluToNedVelocity:
    """Verify velocity sign flips (same pattern as position)."""

    def test_identity(self) -> None:
        assert flu_to_ned_velocity(0, 0, 0) == (0, 0, 0)

    def test_vx_preserved(self) -> None:
        assert flu_to_ned_velocity(1.5, 0, 0)[0] == pytest.approx(1.5)

    def test_vy_negated(self) -> None:
        assert flu_to_ned_velocity(0, 2.5, 0)[1] == pytest.approx(-2.5)

    def test_vz_negated(self) -> None:
        assert flu_to_ned_velocity(0, 0, 3.5)[2] == pytest.approx(-3.5)

    def test_full_velocity(self) -> None:
        vx, vy, vz = flu_to_ned_velocity(1.0, 2.0, 3.0)
        assert vx == pytest.approx(1.0)
        assert vy == pytest.approx(-2.0)
        assert vz == pytest.approx(-3.0)

    def test_returns_tuple(self) -> None:
        result = flu_to_ned_velocity(1, 2, 3)
        assert isinstance(result, tuple)
        assert len(result) == 3
