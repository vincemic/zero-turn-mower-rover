"""Thermal check — verifies all thermal zones are below throttle threshold."""

from __future__ import annotations

from pathlib import Path

from mower_rover.health.thermal import read_thermal_zones
from mower_rover.probe.registry import Severity, register

_THROTTLE_THRESHOLD_C = 95.0


@register("thermal", severity=Severity.WARNING, depends_on=("jetpack_version",))
def check_thermal(sysroot: Path) -> tuple[bool, str]:
    """Verify all thermal zones are below 95 °C."""
    snap = read_thermal_zones(sysroot=sysroot)
    if not snap.zones:
        return True, "No thermal zones found"

    hot_zones = [z for z in snap.zones if z.temp_c >= _THROTTLE_THRESHOLD_C]
    if hot_zones:
        msgs = [f"Zone {z.index} at {z.temp_c:.0f}°C (throttle imminent)" for z in hot_zones]
        return False, "; ".join(msgs)

    max_zone = max(snap.zones, key=lambda z: z.temp_c)
    return True, f"All zones OK (max {max_zone.temp_c:.1f}°C on {max_zone.name})"
