"""FLU ↔ NED coordinate frame conversions.

RTAB-Map outputs poses in a Forward-Left-Up (FLU / camera / ROS) frame.
ArduPilot expects North-East-Down (NED).  The transforms below apply the
sign flips documented in research 007 §E-2 reference table.

    x_ned =  x_flu          vx_ned =  vx_flu
    y_ned = -y_flu          vy_ned = -vy_flu
    z_ned = -z_flu          vz_ned = -vz_flu

    roll_ned  =  roll_flu
    pitch_ned = -pitch_flu
    yaw_ned   = -yaw_flu
"""

from __future__ import annotations


def flu_to_ned_pose(
    x: float,
    y: float,
    z: float,
    roll: float,
    pitch: float,
    yaw: float,
) -> tuple[float, float, float, float, float, float]:
    """Convert a 6-DOF pose from FLU to NED."""
    return (x, -y, -z, roll, -pitch, -yaw)


def flu_to_ned_velocity(
    vx: float,
    vy: float,
    vz: float,
) -> tuple[float, float, float]:
    """Convert a velocity vector from FLU to NED."""
    return (vx, -vy, -vz)
