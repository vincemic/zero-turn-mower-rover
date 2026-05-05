"""Shared state for the kiosk operational display.

Holds all panel data behind a :class:`threading.Lock` for safe concurrent
access from multiple reader threads (MAVLink, Wi-Fi, thermal, etc.) and
the rendering loop.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class MavTelemetry:
    """Latest MAVLink telemetry values for kiosk display."""

    # HEARTBEAT
    armed: bool = False
    mode: str = ""
    system_status: int = 0

    # VFR_HUD
    groundspeed_ms: float = 0.0
    heading_deg: int = 0
    throttle_pct: int = 0

    # GPS_RAW_INT / GPS2_RAW
    gps1_fix: int = 0
    gps1_sats: int = 0
    gps1_hdop: float = 99.99
    gps2_fix: int = 0
    gps2_sats: int = 0
    gps2_hdop: float = 99.99

    # GPS_RTK / GPS2_RTK
    rtk1_baseline_mm: int = 0
    rtk1_iar: int = 0
    rtk2_baseline_mm: int = 0
    rtk2_iar: int = 0

    # STATUSTEXT
    last_statustext: str = ""

    # Timestamps
    last_heartbeat_epoch: float = 0.0
    last_gps_epoch: float = 0.0


class SharedState:
    """Thread-safe container for all kiosk display data.

    Writers call individual update methods; the rendering loop calls
    :meth:`snapshot` for an atomic copy of the full state.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mav = MavTelemetry()
        self._wifi_interface: str = ""
        self._wifi_signal_dbm: float = 0.0
        self._wifi_link_quality: float = 0.0
        self._vslam: dict[str, Any] = {}
        self._health: dict[str, Any] = {}
        self._storage: dict[str, Any] = {}
        self._services: dict[str, str] = {}
        self._last_update: str = ""

    @property
    def mav(self) -> MavTelemetry:
        """Direct access to MAV telemetry (caller must hold lock for writes)."""
        return self._mav

    def update_mav(self, **kwargs: Any) -> None:
        """Update MAVLink telemetry fields atomically."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._mav, key):
                    setattr(self._mav, key, value)
            self._last_update = datetime.now(UTC).isoformat()

    def update_wifi(
        self,
        interface: str,
        signal_dbm: float,
        link_quality: float,
    ) -> None:
        """Update Wi-Fi status fields atomically."""
        with self._lock:
            self._wifi_interface = interface
            self._wifi_signal_dbm = signal_dbm
            self._wifi_link_quality = link_quality
            self._last_update = datetime.now(UTC).isoformat()

    def update_vslam(self, **kwargs: Any) -> None:
        """Update VSLAM pose fields atomically."""
        with self._lock:
            self._vslam.update(kwargs)
            self._last_update = datetime.now(UTC).isoformat()

    def update_health(self, **kwargs: Any) -> None:
        """Update system health fields atomically."""
        with self._lock:
            self._health.update(kwargs)
            self._last_update = datetime.now(UTC).isoformat()

    def update_storage(self, **kwargs: Any) -> None:
        """Update storage fields atomically."""
        with self._lock:
            self._storage.update(kwargs)
            self._last_update = datetime.now(UTC).isoformat()

    def update_services(self, services: dict[str, str]) -> None:
        """Update service status fields atomically."""
        with self._lock:
            self._services.update(services)
            self._last_update = datetime.now(UTC).isoformat()

    def snapshot(self) -> dict[str, Any]:
        """Return an atomic copy of the entire state as a dict."""
        with self._lock:
            return {
                "mav": asdict(self._mav),
                "wifi_interface": self._wifi_interface,
                "wifi_signal_dbm": self._wifi_signal_dbm,
                "wifi_link_quality": self._wifi_link_quality,
                "vslam": dict(self._vslam),
                "health": dict(self._health),
                "storage": dict(self._storage),
                "services": dict(self._services),
                "last_update": self._last_update,
            }
