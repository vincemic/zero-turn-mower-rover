"""OAK-D camera presence check — scans USB vendor IDs and link speed."""

from __future__ import annotations

import glob
from pathlib import Path

from mower_rover.probe.registry import Severity, register

_OAK_VENDOR_ID = "03e7"
_MIN_USB_SPEED_MBPS = 5000


@register("oakd", severity=Severity.CRITICAL, depends_on=("jetpack_version",))
def check_oakd(sysroot: Path) -> tuple[bool, str]:
    """Detect a Luxonis OAK device by USB vendor ID ``03e7`` and check link speed."""
    pattern = str(sysroot / "sys" / "bus" / "usb" / "devices" / "*" / "idVendor")
    for vendor_file in glob.glob(pattern):
        try:
            vid = Path(vendor_file).read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if vid == _OAK_VENDOR_ID:
            device_dir = Path(vendor_file).parent
            speed_file = device_dir / "speed"
            try:
                speed = int(speed_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                return True, f"OAK device found (vendor {_OAK_VENDOR_ID}, speed unknown)"
            if speed >= _MIN_USB_SPEED_MBPS:
                return True, f"OAK device found at USB {speed} Mbps"
            return False, f"OAK device at USB {speed} Mbps (need \u2265{_MIN_USB_SPEED_MBPS})"
    return False, "No OAK device detected"
