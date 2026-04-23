"""Power state reader for Jetson sysfs and nvpmodel.

Reads nvpmodel mode, online CPU count, GPU frequency, and fan profile.
The ``sysroot`` parameter exists for testability.  Subprocess calls
(``nvpmodel -q``) are not rooted under ``sysroot`` — they run on the
live system (or are mocked in tests).
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mower_rover.logging_setup.setup import get_logger

_log = get_logger("health.power")


@dataclass(frozen=True)
class PowerState:
    """Point-in-time Jetson power / performance state."""

    mode_id: int | None  # nvpmodel mode number
    mode_name: str | None  # e.g. "30W", "MAXN"
    online_cpus: int | None  # count of online CPUs
    gpu_freq_mhz: int | None  # current GPU frequency
    fan_profile: str | None  # fan PWM profile name
    timestamp: str  # ISO 8601 UTC


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_nvpmodel() -> tuple[int | None, str | None]:
    """Run ``nvpmodel -q`` and parse mode ID + name."""
    try:
        result = subprocess.run(
            ["nvpmodel", "-q"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _log.debug("nvpmodel_unavailable", error=str(exc))
        return None, None

    if result.returncode != 0:
        _log.debug("nvpmodel_failed", returncode=result.returncode, stderr=result.stderr.strip())
        return None, None

    # Example output:
    #   NV Power Mode: MAXN
    #   0
    mode_id: int | None = None
    mode_name: str | None = None
    for line in result.stdout.splitlines():
        m = re.match(r"NV Power Mode:\s*(.+)", line.strip())
        if m:
            mode_name = m.group(1).strip()
        # Bare integer line is the mode ID.
        stripped = line.strip()
        if stripped.isdigit():
            mode_id = int(stripped)
    return mode_id, mode_name


def _read_online_cpus(sysroot: Path) -> int | None:
    """Count online CPUs from ``sys/devices/system/cpu/online``."""
    cpu_online = sysroot / "sys" / "devices" / "system" / "cpu" / "online"
    if not cpu_online.is_file():
        return None
    try:
        raw = cpu_online.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    # Format: "0-11" or "0-3,6-7" — count individual CPUs.
    count = 0
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            with contextlib.suppress(ValueError):
                count += int(hi) - int(lo) + 1
        else:
            try:
                int(part)
                count += 1
            except ValueError:
                pass
    return count if count > 0 else None


def _read_gpu_freq(sysroot: Path) -> int | None:
    """Read current GPU frequency in MHz from sysfs.

    Tries the Jetson Orin path first, then the generic devfreq path.
    """
    candidates = [
        sysroot / "sys" / "devices" / "17000000.gpu" / "devfreq" / "17000000.gpu" / "cur_freq",
        sysroot / "sys" / "class" / "devfreq" / "17000000.gpu" / "cur_freq",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
            # cur_freq is in Hz; convert to MHz.
            return int(raw) // 1_000_000
        except (OSError, ValueError):
            continue
    return None


def _read_fan_profile(sysroot: Path) -> str | None:
    """Read the active fan PWM profile name."""
    profile_path = sysroot / "sys" / "devices" / "pwm-fan" / "cur_pwm_profile"
    if not profile_path.is_file():
        return None
    try:
        return profile_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_power_state(sysroot: Path = Path("/")) -> PowerState:
    """Read Jetson power state from sysfs + ``nvpmodel``.

    Fields that cannot be read are returned as ``None``.
    """
    mode_id, mode_name = _read_nvpmodel()
    online_cpus = _read_online_cpus(sysroot)
    gpu_freq_mhz = _read_gpu_freq(sysroot)
    fan_profile = _read_fan_profile(sysroot)
    timestamp = datetime.now(UTC).isoformat()

    _log.debug(
        "power_state_read",
        mode_id=mode_id,
        mode_name=mode_name,
        online_cpus=online_cpus,
        gpu_freq_mhz=gpu_freq_mhz,
        fan_profile=fan_profile,
    )
    return PowerState(
        mode_id=mode_id,
        mode_name=mode_name,
        online_cpus=online_cpus,
        gpu_freq_mhz=gpu_freq_mhz,
        fan_profile=fan_profile,
        timestamp=timestamp,
    )
