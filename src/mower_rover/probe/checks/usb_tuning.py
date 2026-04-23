"""USB tuning checks — autosuspend, usbfs memory, and thermal gate for OAK-D."""

from __future__ import annotations

from pathlib import Path

from mower_rover.health.thermal import read_thermal_zones
from mower_rover.probe.registry import Severity, register

_THERMAL_GATE_C = 85.0


@register("oakd_usb_autosuspend", severity=Severity.WARNING, depends_on=("oakd",))
def check_usb_autosuspend(sysroot: Path) -> tuple[bool, str]:
    """Verify USB autosuspend is disabled (value must be ``-1``)."""
    param_file = sysroot / "sys" / "module" / "usbcore" / "parameters" / "autosuspend"
    try:
        val = param_file.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "Cannot read autosuspend parameter (missing sysfs)"
    if val == "-1":
        return True, "USB autosuspend disabled (autosuspend=-1)"
    return False, f"USB autosuspend={val} (expected -1 to prevent OAK-D dropouts)"


@register("oakd_usbfs_memory", severity=Severity.WARNING, depends_on=("oakd",))
def check_usbfs_memory(sysroot: Path) -> tuple[bool, str]:
    """Verify usbfs_memory_mb is at least 1000 for high-bandwidth USB3 streams."""
    param_file = sysroot / "sys" / "module" / "usbcore" / "parameters" / "usbfs_memory_mb"
    try:
        raw = param_file.read_text(encoding="utf-8").strip()
        val = int(raw)
    except OSError:
        return False, "Cannot read usbfs_memory_mb parameter (missing sysfs)"
    except ValueError:
        return False, f"Cannot parse usbfs_memory_mb value: {raw!r}"
    if val >= 1000:
        return True, f"usbfs_memory_mb={val} (>= 1000)"
    return False, f"usbfs_memory_mb={val} (need >= 1000 for OAK-D streaming)"


@register("oakd_thermal_gate", severity=Severity.WARNING, depends_on=("thermal",))
def check_thermal_gate(sysroot: Path) -> tuple[bool, str]:
    """Block OAK-D startup if any thermal zone is above 85 °C."""
    snap = read_thermal_zones(sysroot=sysroot)
    if not snap.zones:
        return True, "No thermal zones found (gate passes)"
    max_zone = max(snap.zones, key=lambda z: z.temp_c)
    if max_zone.temp_c >= _THERMAL_GATE_C:
        return False, (
            f"Thermal gate: {max_zone.name} at {max_zone.temp_c:.0f}°C "
            f"(>= {_THERMAL_GATE_C:.0f}°C limit)"
        )
    return True, f"Thermal gate OK (max {max_zone.temp_c:.1f}°C on {max_zone.name})"
