"""SITL verification of the `safety-defaults` profile (plan 016 Phase 3).

These tests are SMOKE-LEVEL only: they verify that ArduPilot Rover SITL acts on
the failsafe parameters delivered by the profile (FR-5 round-trip, FR-6 fence
breach -> HOLD, FR-7 GCS heartbeat loss -> HOLD).

Per copilot-instructions: SITL is a kinematic harness — these tests validate
plumbing, not tuning.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from typer.testing import CliRunner

from mower_rover.cli.laptop import app
from mower_rover.params.baseline import load_profile
from mower_rover.params.mav import fetch_params

pytestmark = pytest.mark.sitl

SAFETY_KEYS = (
    "FENCE_ENABLE",
    "FENCE_ACTION",
    "FS_EKF_ACTION",
    "FS_ACTION",
    "FS_GCS_ENABLE",
    "FS_GCS_TIMEOUT",
    "ARMING_CHECK",
)

# ArduPilot Rover mode numbers (see Rover `mode.h`).
ROVER_MODE_MANUAL = 0
ROVER_MODE_HOLD = 4
ROVER_MODE_GUIDED = 15
ROVER_MODE_AUTO = 10


def _apply_safety_defaults(sitl_endpoint: str) -> None:
    """Helper: invoke the CLI to apply the safety-defaults profile."""
    result = CliRunner().invoke(
        app,
        [
            "params", "apply",
            "--profile", "safety-defaults",
            "--port", sitl_endpoint,
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output


def _wait_for_mode(conn: Any, mode_num: int, timeout_s: float) -> int | None:
    """Poll HEARTBEAT.custom_mode until == mode_num or timeout. Returns last seen mode or None."""
    deadline = time.monotonic() + timeout_s
    last: int | None = None
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg is None:
            continue
        last = int(msg.custom_mode)
        if last == mode_num:
            return last
    return last


def test_safety_defaults_round_trip(
    sitl_endpoint: str, sitl_connection: Any
) -> None:
    """FR-5: apply via CLI; fetch back via direct link; bit-exact match."""
    _apply_safety_defaults(sitl_endpoint)
    after = fetch_params(sitl_connection)
    desired = load_profile("safety-defaults")
    for k in SAFETY_KEYS:
        assert k in after, f"{k} missing from autopilot params after apply"
        assert after[k] == desired[k], (
            f"{k}: autopilot={after[k]!r} desired={desired[k]!r}"
        )


def test_fence_breach_enters_hold(
    sitl_endpoint: str, sitl_connection: Any
) -> None:
    """FR-6: with safety-defaults applied, fence breach in Auto -> HOLD.

    Uses a tiny circular fence (radius 30 m) centred on home; arms in Guided
    and commands a velocity outward. ArduPilot's fence breach action is
    governed by FENCE_ACTION=2 (Hold) under the applied profile.
    """
    from pymavlink import mavutil

    _apply_safety_defaults(sitl_endpoint)
    conn = sitl_connection

    # Set a small circular fence (FENCE_TYPE=2 = circle only, FENCE_RADIUS=30m).
    conn.mav.param_set_send(
        conn.target_system, conn.target_component,
        b"FENCE_TYPE", 2.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )
    conn.mav.param_set_send(
        conn.target_system, conn.target_component,
        b"FENCE_RADIUS", 30.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )
    # Wait for ack of the radius set.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
        if msg is not None and msg.param_id.strip("\x00") == "FENCE_RADIUS":
            break

    # Switch to Guided so we can command velocity, then arm.
    conn.set_mode(ROVER_MODE_GUIDED)
    time.sleep(0.5)
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 0, 0, 0, 0, 0, 0,
    )
    # Allow arming attempt; not all SITL configurations will arm without GPS,
    # so don't hard-fail on disarm — instead command motion and observe.
    time.sleep(2.0)

    # Command 5 m/s NED-frame velocity due north for several seconds.
    # Even if disarmed, repeatedly sending the velocity setpoint will drive
    # SITL once arming completes. We poll for HOLD as the success signal.
    type_mask = (
        # ignore position, accel, yaw — only velocity bits enabled
        0b0000_1111_1100_0111
    )
    for _ in range(20):  # ~10 seconds at 0.5s pace
        conn.mav.set_position_target_local_ned_send(
            0,
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            type_mask,
            0, 0, 0,        # x,y,z position (ignored)
            5.0, 0.0, 0.0,  # vx,vy,vz
            0, 0, 0,        # ax,ay,az (ignored)
            0, 0,           # yaw, yaw_rate (ignored)
        )
        time.sleep(0.5)

    final = _wait_for_mode(conn, ROVER_MODE_HOLD, timeout_s=15.0)
    assert final == ROVER_MODE_HOLD, (
        f"Expected HOLD ({ROVER_MODE_HOLD}) after fence breach, got {final}"
    )


def test_gcs_heartbeat_loss_enters_hold(
    sitl_endpoint: str, sitl_connection: Any
) -> None:
    """FR-7: stop heartbeats for FS_GCS_TIMEOUT+1s -> HOLD."""
    from pymavlink import mavutil

    _apply_safety_defaults(sitl_endpoint)
    conn = sitl_connection

    # Send heartbeats so SITL considers GCS present, then arm in Manual.
    def _hb() -> None:
        conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0,
        )

    for _ in range(5):
        _hb()
        time.sleep(0.3)

    conn.set_mode(ROVER_MODE_MANUAL)
    time.sleep(0.5)
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 0, 0, 0, 0, 0, 0,
    )
    time.sleep(1.0)

    # Confirm we're not already in HOLD.
    initial = _wait_for_mode(conn, ROVER_MODE_HOLD, timeout_s=1.0)
    if initial == ROVER_MODE_HOLD:
        pytest.skip("Vehicle already in HOLD before heartbeat-drop test could run")

    # Stop heartbeats. FS_GCS_TIMEOUT=5 from the profile; wait timeout+2s.
    fs_timeout = float(load_profile("safety-defaults")["FS_GCS_TIMEOUT"])
    deadline = time.monotonic() + fs_timeout + 2.0
    final: int | None = None
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg is not None:
            final = int(msg.custom_mode)
            if final == ROVER_MODE_HOLD:
                break

    assert final == ROVER_MODE_HOLD, (
        f"Expected HOLD ({ROVER_MODE_HOLD}) after GCS heartbeat loss, got {final}"
    )
