"""Wi-Fi signal quality reader for Jetson.

Parses ``/proc/net/wireless`` (Linux) to obtain link quality, signal level,
and noise level for the active wireless interface.  Returns ``None`` on
non-Linux or when no wireless interfaces are present.

The ``sysroot`` parameter exists for testability — on the real Jetson it is
always ``Path("/")``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mower_rover.logging_setup.setup import get_logger

_log = get_logger("health.wifi")


@dataclass(frozen=True)
class WifiStatus:
    """Parsed Wi-Fi status from /proc/net/wireless."""

    interface: str
    link_quality: float
    signal_dbm: float
    noise_dbm: float


def read_wifi_status(sysroot: Path = Path("/")) -> WifiStatus | None:
    """Read Wi-Fi status from *sysroot*/proc/net/wireless.

    Returns the first wireless interface found, or ``None`` if the file is
    missing, empty, or contains no interface lines.
    """
    wireless_file = sysroot / "proc" / "net" / "wireless"
    if not wireless_file.is_file():
        return None

    try:
        text = wireless_file.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("wifi_read_error", error=str(exc))
        return None

    # /proc/net/wireless format:
    #   Inter-| sta...  (header line 1)
    #    face | ...     (header line 2)
    #   wlan0: 0000  70.  -40.  -95.  ...
    lines = text.splitlines()
    for line in lines[2:]:  # skip 2 header lines
        line = line.strip()
        if not line:
            continue
        # Interface name ends with ':'
        parts = line.split()
        if len(parts) < 4:
            continue
        interface = parts[0].rstrip(":")
        try:
            link_quality = float(parts[2].rstrip("."))
            signal_dbm = float(parts[3].rstrip("."))
            noise_dbm = float(parts[4].rstrip(".")) if len(parts) > 4 else 0.0
        except (ValueError, IndexError):
            _log.warning("wifi_parse_error", line=line)
            continue

        return WifiStatus(
            interface=interface,
            link_quality=link_quality,
            signal_dbm=signal_dbm,
            noise_dbm=noise_dbm,
        )

    return None
