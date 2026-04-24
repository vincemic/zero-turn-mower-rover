"""Field validation tests for VSLAM–ArduPilot integration.

Every test in this module requires physical hardware and is marked
``@pytest.mark.field``.  They are **never** run in CI — execute them
on-site with the mower powered and all sensors connected.

Each test corresponds to a procedure document under ``docs/procedures/``.
The tests serve as executable checklists: run them from the Jetson (or
laptop for health monitoring) and confirm the assertions manually or via
the connected hardware.

Run only field tests::

    pytest -m field tests/test_vslam_field.py -v
"""

from __future__ import annotations

import pytest

# All tests in this module require physical hardware.
pytestmark = pytest.mark.field


class TestUSBEnumeration:
    """Procedure 001 — Verify Pixhawk USB enumeration on the Jetson.

    See ``docs/procedures/001-usb-enumeration.md`` for the full
    step-by-step procedure.
    """

    def test_field_usb_enumeration(self) -> None:
        """Pixhawk enumerates as /dev/ttyACM0 with udev symlink.

        **Run on Jetson only.**

        Checks:
        - /dev/ttyACM0 exists
        - /dev/pixhawk symlink exists and points to ttyACM0
        - Device is world-read/writable (mode 0666)
        - MAVLink heartbeat received within 5 s

        Procedure: docs/procedures/001-usb-enumeration.md
        """
        import os
        import platform
        import stat
        from pathlib import Path

        if platform.system() != "Linux":
            pytest.skip("USB enumeration test requires Linux/Jetson")

        dev_acm = Path("/dev/ttyACM0")
        dev_symlink = Path("/dev/pixhawk")

        assert dev_acm.exists(), "/dev/ttyACM0 not found — is Pixhawk USB connected?"
        assert dev_symlink.is_symlink(), (
            "/dev/pixhawk symlink missing — deploy 90-pixhawk-usb.rules"
        )
        assert os.readlink(str(dev_symlink)).endswith("ttyACM0"), (
            "/dev/pixhawk does not point to ttyACM0"
        )

        mode = stat.S_IMODE(dev_acm.stat().st_mode)
        assert mode & 0o666 == 0o666, (
            f"Permissions {oct(mode)} — expected 0666; check udev rule"
        )

        # Heartbeat check via pymavlink
        from pymavlink import mavutil

        conn = mavutil.mavlink_connection("/dev/pixhawk")
        try:
            hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
            assert hb is not None, "No MAVLink heartbeat within 5 s"
        finally:
            conn.close()


class TestExtrinsicCalibration:
    """Procedure 002 — Extrinsic calibration verification.

    See ``docs/procedures/002-extrinsic-calibration.md``.
    """

    def test_field_extrinsic_calibration(self) -> None:
        """VISO_POS params match vslam.yaml extrinsics after apply.

        **Run on laptop** (connected to Pixhawk via SiK radio).

        Checks:
        - vslam.yaml extrinsics are non-default (operator has measured)
        - VISO_POS_X/Y/Z on Pixhawk match vslam.yaml values

        Procedure: docs/procedures/002-extrinsic-calibration.md
        """
        pytest.skip(
            "Manual field procedure — run interactively with hardware. "
            "See docs/procedures/002-extrinsic-calibration.md"
        )


class TestVSLAMTrajectory:
    """Procedure 003 — VSLAM trajectory vs. RTK GPS comparison.

    See ``docs/procedures/003-vslam-trajectory-validation.md``.
    """

    def test_field_vslam_trajectory_vs_rtk(self) -> None:
        """VSLAM trajectory within 0.5 m of GPS on straight segments.

        **Run in the field** — drive a 10 m × 10 m rectangle, then
        analyse the ArduPilot log to compare VISO and GPS tracks.

        Procedure: docs/procedures/003-vslam-trajectory-validation.md
        """
        pytest.skip(
            "Post-drive log analysis — run interactively after driving the "
            "test pattern. See docs/procedures/003-vslam-trajectory-validation.md"
        )


class TestLuaSourceSwitching:
    """Procedure 004 — Lua EKF source switching validation.

    See ``docs/procedures/004-lua-source-switching.md``.
    """

    def test_field_lua_source_switching(self) -> None:
        """Lua script switches EKF3 source on GPS degradation.

        **Run in the field** — drive under tree cover to degrade RTK,
        observe automatic switch to VSLAM (SRC2), then return to open
        sky and confirm switch back to GPS (SRC1).

        Checks:
        - GPS→VSLAM switch within ~2 s of degradation
        - VSLAM→GPS switch when RTK recovers
        - STATUSTEXT messages visible on laptop

        Procedure: docs/procedures/004-lua-source-switching.md
        """
        pytest.skip(
            "Manual field procedure — requires GPS degradation scenario. "
            "See docs/procedures/004-lua-source-switching.md"
        )


class TestHealthMonitoringE2E:
    """Procedure 005 — End-to-end health monitoring over SiK radio.

    See ``docs/procedures/005-health-monitoring-e2e.md``.
    """

    def test_field_health_monitoring_e2e(self) -> None:
        """VSLAM health metrics visible on laptop via SiK radio.

        **Run on laptop** — with no SSH to Jetson, run
        ``mower vslam health`` and verify all VSLAM_* metrics are
        updating at ~1 Hz.

        Checks:
        - Health table populates within 5 s
        - All VSLAM_* named values present
        - ~1 Hz update rate
        - No SSH dependency

        Procedure: docs/procedures/005-health-monitoring-e2e.md
        """
        pytest.skip(
            "Manual field procedure — requires SiK radio link. "
            "See docs/procedures/005-health-monitoring-e2e.md"
        )
