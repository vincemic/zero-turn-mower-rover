"""Health monitoring readers for Jetson thermal, power, disk, and Wi-Fi state.

Public surface:
- ``ThermalZone``, ``ThermalSnapshot``, ``read_thermal_zones`` — thermal zone readings.
- ``PowerState``, ``read_power_state`` — nvpmodel / CPU / GPU / fan state.
- ``DiskUsage``, ``read_disk_usage`` — mount point usage and NVMe detection.
- ``WifiStatus``, ``read_wifi_status`` — wireless interface signal quality.
"""

from __future__ import annotations

from mower_rover.health.disk import DiskUsage, read_disk_usage
from mower_rover.health.power import PowerState, read_power_state
from mower_rover.health.thermal import ThermalSnapshot, ThermalZone, read_thermal_zones
from mower_rover.health.wifi import WifiStatus, read_wifi_status

__all__ = [
    "DiskUsage",
    "PowerState",
    "ThermalSnapshot",
    "ThermalZone",
    "WifiStatus",
    "read_disk_usage",
    "read_power_state",
    "read_thermal_zones",
    "read_wifi_status",
]
