"""Thermal zone reader for Jetson sysfs.

Reads ``/sys/class/thermal/thermal_zone*/temp`` and ``type`` files to produce
a snapshot of all thermal zones.  The ``sysroot`` parameter exists for
testability — on the real Jetson it is always ``Path("/")``.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mower_rover.logging_setup.setup import get_logger

_log = get_logger("health.thermal")


@dataclass(frozen=True)
class ThermalZone:
    """A single thermal zone reading."""

    index: int
    name: str  # e.g. "CPU-therm", "GPU-therm"
    temp_c: float  # millidegrees / 1000


@dataclass(frozen=True)
class ThermalSnapshot:
    """Point-in-time reading of all thermal zones."""

    zones: list[ThermalZone]
    timestamp: str  # ISO 8601 UTC


def read_thermal_zones(sysroot: Path = Path("/")) -> ThermalSnapshot:
    """Read all thermal zones under *sysroot*/sys/class/thermal/.

    Returns a :class:`ThermalSnapshot` with whatever zones are readable.
    Missing or unreadable zones are silently skipped.
    """
    base = sysroot / "sys" / "class" / "thermal"
    zones: list[ThermalZone] = []

    # glob.glob with str because Path.glob resolves symlinks differently
    # across platforms — str glob is more predictable for fake sysfs in tests.
    pattern = str(base / "thermal_zone*")
    for zone_dir_str in sorted(glob.glob(pattern)):
        zone_dir = Path(zone_dir_str)
        temp_file = zone_dir / "temp"
        type_file = zone_dir / "type"

        if not temp_file.is_file():
            continue

        try:
            with open(temp_file, "rb") as fh:
                raw = fh.read()
            if raw is None:
                continue
            raw_temp = raw.decode("utf-8").strip()
            temp_c = int(raw_temp) / 1000.0
        except (OSError, ValueError, TypeError) as exc:
            _log.warning("thermal_zone_read_error", path=str(temp_file), error=str(exc))
            continue

        name = ""
        if type_file.is_file():
            try:
                with open(type_file, "rb") as fh:
                    raw_name = fh.read()
                name = raw_name.decode("utf-8").strip() if raw_name else zone_dir.name
            except (OSError, TypeError):
                name = zone_dir.name

        # Extract index from directory name (e.g. "thermal_zone0" → 0).
        try:
            index = int(zone_dir.name.removeprefix("thermal_zone"))
        except ValueError:
            index = -1

        zones.append(ThermalZone(index=index, name=name, temp_c=temp_c))

    timestamp = datetime.now(UTC).isoformat()
    _log.debug("thermal_zones_read", zone_count=len(zones))
    return ThermalSnapshot(zones=zones, timestamp=timestamp)
