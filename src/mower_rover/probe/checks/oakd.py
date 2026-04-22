"""OAK-D camera presence check — scans USB vendor IDs."""

from __future__ import annotations

import glob
from pathlib import Path

from mower_rover.probe.registry import Severity, register

_OAK_VENDOR_ID = "03e7"


@register("oakd", severity=Severity.WARNING, depends_on=("jetpack_version",))
def check_oakd(sysroot: Path) -> tuple[bool, str]:
    """Detect a Luxonis OAK device by USB vendor ID ``03e7``."""
    pattern = str(sysroot / "sys" / "bus" / "usb" / "devices" / "*" / "idVendor")
    for vendor_file in glob.glob(pattern):
        try:
            vid = Path(vendor_file).read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if vid == _OAK_VENDOR_ID:
            return True, f"OAK device found (vendor {_OAK_VENDOR_ID})"
    return False, f"No OAK device detected (vendor {_OAK_VENDOR_ID})"
