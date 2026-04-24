"""OAK-D camera presence check — scans USB vendor IDs and link speed.

The OAK-D's MyriadX bootloader enumerates at USB 2.0 (480 Mbps) in sysfs
before DepthAI uploads firmware.  After firmware boot the device re-enumerates
at SuperSpeed (5 Gbps).  When running on a live Jetson (sysroot ``/``) and
sysfs reports < 5 Gbps, the check falls back to DepthAI
``device.getUsbSpeed()`` which triggers firmware upload.
"""

from __future__ import annotations

import glob
from pathlib import Path

from mower_rover.probe.registry import Severity, register

_OAK_VENDOR_ID = "03e7"
_MIN_USB_SPEED_MBPS = 5000

# Map DepthAI UsbSpeed enum names to approximate Mbps.
_DAI_SPEED_MBPS: dict[str, int] = {
    "SUPER_PLUS": 10000,
    "SUPER": 5000,
    "HIGH": 480,
    "FULL": 12,
    "LOW": 1,
}


def _depthai_usb_speed() -> int | None:
    """Try to connect via DepthAI and return the negotiated speed in Mbps.

    Returns ``None`` if depthai is not installed or connection fails.
    """
    try:
        import depthai as dai  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        dev = dai.Device()
        speed_name = dev.getUsbSpeed().name
        dev.close()
        return _DAI_SPEED_MBPS.get(speed_name, 0)
    except Exception:  # noqa: BLE001
        return None


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
            # sysfs shows pre-boot speed; try DepthAI on a live system.
            if sysroot == Path("/"):
                dai_speed = _depthai_usb_speed()
                if dai_speed is not None and dai_speed >= _MIN_USB_SPEED_MBPS:
                    return True, (
                        f"OAK device at USB {dai_speed} Mbps via DepthAI"
                        f" (sysfs pre-boot: {speed} Mbps)"
                    )
                if dai_speed is not None:
                    return False, (
                        f"OAK device at USB {dai_speed} Mbps via DepthAI"
                        f" (need \u2265{_MIN_USB_SPEED_MBPS})"
                    )
            return False, f"OAK device at USB {speed} Mbps (need \u2265{_MIN_USB_SPEED_MBPS})"
    return False, "No OAK device detected"


_VSLAM_CONFIG_PATH = "etc/mower/vslam.yaml"


@register("oakd_vslam_config", severity=Severity.WARNING, depends_on=("oakd",))
def check_oakd_vslam_config(sysroot: Path) -> tuple[bool, str]:
    """Verify VSLAM extrinsic config file exists at /etc/mower/vslam.yaml."""
    cfg_path = sysroot / _VSLAM_CONFIG_PATH
    if cfg_path.is_file():
        return True, f"VSLAM config present: {cfg_path}"
    return False, f"VSLAM config missing: {cfg_path}"
