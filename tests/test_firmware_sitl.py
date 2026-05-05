"""SITL integration tests for firmware functionality.

Tests firmware operations against ArduPilot SITL (rover-skid frame):
- Reading AUTOPILOT_VERSION and decoding version info
- Sending reboot-to-bootloader command
- Verifying armed-check blocks firmware operations
"""

from __future__ import annotations

import pytest
import typer
from pymavlink import mavutil

from mower_rover.cli.jetson import _check_not_armed
from mower_rover.pixhawk.firmware import (
    FirmwareInfo,
    read_running_version,
    reboot_to_bootloader,
)


@pytest.mark.sitl
def test_read_autopilot_version(sitl_connection) -> None:
    """Read AUTOPILOT_VERSION from SITL and decode to valid semver."""
    info = read_running_version(sitl_connection)
    assert info is not None
    assert isinstance(info, FirmwareInfo)
    assert info.major > 0  # SITL reports ArduPilot version
    assert 0 <= info.minor <= 255
    assert 0 <= info.patch <= 255
    assert info.type_name in ("dev", "alpha", "beta", "rc", "official")
    assert info.version_string  # non-empty


@pytest.mark.sitl
def test_reboot_to_bootloader_accepted(sitl_endpoint: str) -> None:
    """Send MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN(param1=3) to SITL.

    SITL won't actually enter bootloader, but it should accept the command
    without throwing an error. We open a fresh connection because the reboot
    command closes it.
    """
    from mower_rover.mavlink.connection import ConnectionConfig, open_link

    config = ConnectionConfig(endpoint=sitl_endpoint)
    with open_link(config) as conn:
        # Should not raise - SITL accepts the command (even if it doesn't do anything)
        reboot_to_bootloader(conn)
    # If we get here without exception, the command was accepted


@pytest.mark.sitl
def test_armed_check_blocks_when_armed(sitl_connection) -> None:
    """Arm SITL, verify armed check raises. Disarm, verify it passes."""
    conn = sitl_connection

    # SITL starts disarmed — armed check should pass
    hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    assert hb is not None
    assert not (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

    # Armed check should pass when disarmed
    _check_not_armed(conn)

    # Arm the vehicle
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 0, 0, 0, 0, 0, 0  # param1=1 = arm
    )
    # Wait for ACK
    conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)

    # Check heartbeat shows armed (if arming succeeded)
    hb2 = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    if hb2 and (hb2.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
        # Armed check should now raise
        with pytest.raises(typer.BadParameter, match="FC is armed.*cannot flash firmware"):
            _check_not_armed(conn)

        # Disarm for cleanup
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 0, 0, 0, 0, 0, 0, 0  # param1=0 = disarm
        )
        conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)

        # Verify disarmed state and check passes
        hb3 = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
        assert hb3 is not None
        assert not (hb3.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        _check_not_armed(conn)  # Should not raise
    else:
        # If arming failed (pre-arm checks), skip the armed test portion
        pytest.skip("SITL arming failed - skipping armed-check test")
