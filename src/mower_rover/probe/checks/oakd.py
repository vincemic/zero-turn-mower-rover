"""OAK-D camera presence check — service-aware PID + speed state machine.

Cross-references ``systemctl is-active mower-vslam.service`` with the USB
product ID visible in sysfs to classify five operational states:

- active + f63b  → PASS  (firmware booted, USB 3.x SuperSpeed)
- active + 2485  → FAIL  (crash-loop suspected — bootloader PID with active service)
- active + absent → FAIL  (service active but camera missing)
- inactive + 2485 → PASS  (idle in bootloader, service stopped)
- inactive + absent → PASS (camera not present and service not running)

Does NOT invoke ``dai.Device()`` when the VSLAM service is active (FR-11).
"""

from __future__ import annotations

import glob
import subprocess
from collections.abc import Callable
from pathlib import Path

from mower_rover.probe.registry import Severity, register

_OAK_VENDOR_ID = "03e7"
_PID_BOOTLOADER = "2485"
_PID_BOOTED = "f63b"
_MIN_USB_SPEED_MBPS = 5000


def _vslam_service_active() -> bool:
    """Return True if mower-vslam.service is active (system-level)."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "mower-vslam.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _find_oakd_device(sysroot: Path) -> tuple[str | None, int | None]:
    """Scan sysfs for OAK-D device. Returns (idProduct, speed) or (None, None)."""
    pattern = str(sysroot / "sys" / "bus" / "usb" / "devices" / "*" / "idVendor")
    for vendor_file in glob.glob(pattern):
        try:
            vid = Path(vendor_file).read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if vid == _OAK_VENDOR_ID:
            device_dir = Path(vendor_file).parent
            # Read product ID
            pid_file = device_dir / "idProduct"
            try:
                pid = pid_file.read_text(encoding="utf-8").strip().lower()
            except OSError:
                pid = None
            # Read link speed
            speed_file = device_dir / "speed"
            try:
                speed = int(speed_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                speed = None
            return pid, speed
    return None, None


@register("oakd", severity=Severity.CRITICAL, depends_on=("jetpack_version",))
def check_oakd(
    sysroot: Path,
    *,
    _service_active_fn: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    """Service-aware OAK-D state machine (Q6 cross-reference table)."""
    service_active_fn = _service_active_fn or _vslam_service_active
    active = service_active_fn()
    pid, speed = _find_oakd_device(sysroot)

    # Determine device presence category
    if pid == _PID_BOOTED:
        # Camera is booted (firmware loaded)
        speed_str = f" at USB {speed} Mbps" if speed is not None else ""
        if active:
            return True, f"OAK-D booted (PID f63b){speed_str}, service active"
        # inactive + f63b: unusual but acceptable (someone stopped service)
        return True, f"OAK-D booted (PID f63b){speed_str}, service inactive"
    elif pid == _PID_BOOTLOADER:
        # Camera in bootloader
        if active:
            return False, (
                "Crash-loop suspected: OAK-D in bootloader (PID 2485) "
                "but mower-vslam.service is active"
            )
        return True, "OAK-D idle in bootloader (PID 2485), service stopped"
    else:
        # Camera absent (no vendor 03e7 found)
        if active:
            return False, "mower-vslam.service active but no OAK-D camera detected in sysfs"
        return True, "OAK-D not present, service not running"


_VSLAM_CONFIG_PATH = "etc/mower/vslam.yaml"


@register("oakd_vslam_config", severity=Severity.WARNING, depends_on=("oakd",))
def check_oakd_vslam_config(sysroot: Path) -> tuple[bool, str]:
    """Verify VSLAM extrinsic config file exists at /etc/mower/vslam.yaml."""
    cfg_path = sysroot / _VSLAM_CONFIG_PATH
    if cfg_path.is_file():
        return True, f"VSLAM config present: {cfg_path}"
    return False, f"VSLAM config missing: {cfg_path}"
