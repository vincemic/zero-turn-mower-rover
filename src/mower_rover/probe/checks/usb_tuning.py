"""USB tuning checks — autosuspend, usbfs memory, quirks, hub, udev rule, and thermal gate for OAK-D."""

from __future__ import annotations

import glob
from pathlib import Path

from mower_rover.health.thermal import read_thermal_zones
from mower_rover.probe.registry import Severity, register

_THERMAL_GATE_C = 85.0


@register("oakd_usb_autosuspend", severity=Severity.WARNING, depends_on=("jetpack_version",))
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


@register("oakd_usbfs_memory", severity=Severity.WARNING, depends_on=("jetpack_version",))
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


# ---------------------------------------------------------------------------
# usbcore quirks check (R-6)
# ---------------------------------------------------------------------------

_REQUIRED_QUIRKS = ("03e7:2485:gk", "03e7:f63b:gk")


@register("usbcore_quirks", severity=Severity.WARNING, depends_on=("jetpack_version",))
def check_usbcore_quirks(sysroot: Path) -> tuple[bool, str]:
    """Verify usbcore.quirks contains NO_LPM entries for both OAK-D PIDs."""
    quirks_file = sysroot / "sys" / "module" / "usbcore" / "parameters" / "quirks"
    try:
        content = quirks_file.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "Cannot read usbcore quirks parameter (missing sysfs)"
    missing = [q for q in _REQUIRED_QUIRKS if q not in content]
    if not missing:
        return True, f"usbcore.quirks contains both OAK-D NO_LPM entries"
    return False, f"usbcore.quirks missing: {', '.join(missing)}"


# ---------------------------------------------------------------------------
# Waveshare USB hub check (R-7)
# ---------------------------------------------------------------------------

_HUB_VID = "2109"
_HUB_PID_USB3 = "0817"
_HUB_PID_USB2 = "2817"


@register("waveshare_hub", severity=Severity.WARNING, depends_on=("jetpack_version",))
def check_waveshare_hub(sysroot: Path) -> tuple[bool, str]:
    """Detect Waveshare 4-Ch USB 3.2 hub (VIA Labs 2109:0817 / 2109:2817)."""
    pattern = str(sysroot / "sys" / "bus" / "usb" / "devices" / "*" / "idVendor")
    found_usb3 = False
    found_usb2 = False
    for vendor_file in glob.glob(pattern):
        try:
            vid = Path(vendor_file).read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if vid == _HUB_VID:
            device_dir = Path(vendor_file).parent
            pid_file = device_dir / "idProduct"
            try:
                pid = pid_file.read_text(encoding="utf-8").strip().lower()
            except OSError:
                continue
            if pid == _HUB_PID_USB3:
                found_usb3 = True
            elif pid == _HUB_PID_USB2:
                found_usb2 = True
    if found_usb3 and found_usb2:
        return True, "Waveshare hub detected (USB 3.0 + USB 2.0 controllers)"
    if found_usb3:
        return True, "Waveshare hub partial (USB 3.0 controller only, USB 2.0 missing)"
    if found_usb2:
        return False, "Waveshare hub partial (USB 2.0 controller only, USB 3.0 missing)"
    return False, "Waveshare USB hub not detected (expected VIA Labs 2109:0817 + 2109:2817)"


# ---------------------------------------------------------------------------
# OAK-D udev rule check (R-8)
# ---------------------------------------------------------------------------

_UDEV_RULE_PATH = "etc/udev/rules.d/80-oakd-usb.rules"
_OAK_VENDOR_ID = "03e7"


@register("oakd_udev_rule", severity=Severity.WARNING, depends_on=("jetpack_version",))
def check_oakd_udev_rule(sysroot: Path) -> tuple[bool, str]:
    """Verify OAK-D udev rule exists and references vendor 03e7."""
    rule_path = sysroot / _UDEV_RULE_PATH
    if not rule_path.is_file():
        return False, f"OAK-D udev rule missing: {rule_path}"
    try:
        content = rule_path.read_text(encoding="utf-8")
    except OSError:
        return False, f"Cannot read OAK-D udev rule: {rule_path}"
    if _OAK_VENDOR_ID in content:
        return True, f"OAK-D udev rule present with vendor {_OAK_VENDOR_ID}"
    return False, f"OAK-D udev rule exists but does not reference vendor {_OAK_VENDOR_ID}"
