"""Tests for mower_rover.kiosk.state and kiosk.telemetry."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mower_rover.kiosk.state import MavTelemetry, SharedState
from mower_rover.kiosk.telemetry import mavlink_reader_loop


# ---------------------------------------------------------------------------
# MavTelemetry dataclass tests
# ---------------------------------------------------------------------------


class TestMavTelemetry:
    def test_defaults(self) -> None:
        """MavTelemetry initialises with safe defaults."""
        t = MavTelemetry()
        assert t.armed is False
        assert t.mode == ""
        assert t.groundspeed_ms == 0.0
        assert t.gps1_fix == 0
        assert t.gps1_hdop == 99.99
        assert t.gps2_fix == 0
        assert t.rtk1_baseline_mm == 0
        assert t.last_statustext == ""
        assert t.last_heartbeat_epoch == 0.0


# ---------------------------------------------------------------------------
# SharedState tests
# ---------------------------------------------------------------------------


class TestSharedState:
    def test_snapshot_has_all_keys(self) -> None:
        """snapshot() returns a dict with all expected top-level keys."""
        state = SharedState()
        snap = state.snapshot()
        assert "mav" in snap
        assert "wifi_interface" in snap
        assert "wifi_signal_dbm" in snap
        assert "wifi_link_quality" in snap
        assert "last_update" in snap

    def test_update_mav(self) -> None:
        """update_mav writes fields that appear in snapshot."""
        state = SharedState()
        state.update_mav(armed=True, mode="AUTO", groundspeed_ms=1.5)
        snap = state.snapshot()
        assert snap["mav"]["armed"] is True
        assert snap["mav"]["mode"] == "AUTO"
        assert snap["mav"]["groundspeed_ms"] == 1.5

    def test_update_wifi(self) -> None:
        """update_wifi writes wifi fields."""
        state = SharedState()
        state.update_wifi(interface="wlan0", signal_dbm=-42.0, link_quality=68.0)
        snap = state.snapshot()
        assert snap["wifi_interface"] == "wlan0"
        assert snap["wifi_signal_dbm"] == -42.0
        assert snap["wifi_link_quality"] == 68.0

    def test_thread_safety_no_corruption(self) -> None:
        """Concurrent writers and readers don't corrupt state."""
        state = SharedState()
        errors: list[Exception] = []
        stop = threading.Event()

        def writer() -> None:
            for i in range(200):
                try:
                    state.update_mav(groundspeed_ms=float(i), heading_deg=i % 360)
                    state.update_wifi(
                        interface="wlan0",
                        signal_dbm=-40.0 - (i % 20),
                        link_quality=70.0 - (i % 30),
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        def reader() -> None:
            for _ in range(200):
                try:
                    snap = state.snapshot()
                    # Verify snapshot is a consistent dict
                    assert isinstance(snap["mav"], dict)
                    assert isinstance(snap["wifi_interface"], str)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(writer),
                pool.submit(writer),
                pool.submit(reader),
                pool.submit(reader),
            ]
            for f in futures:
                f.result(timeout=10)

        assert errors == [], f"Thread safety errors: {errors}"


# ---------------------------------------------------------------------------
# mavlink_reader_loop tests
# ---------------------------------------------------------------------------


class _FakeMsg:
    """Minimal fake MAVLink message."""

    def __init__(self, mtype: str, **fields: object) -> None:
        self._mtype = mtype
        for k, v in fields.items():
            setattr(self, k, v)

    def get_type(self) -> str:
        return self._mtype


class TestMavlinkReaderLoop:
    def test_heartbeat_updates_state(self) -> None:
        """HEARTBEAT message updates armed/mode/status."""
        state = SharedState()
        shutdown = threading.Event()

        # Simulate: first call returns a HEARTBEAT, then shutdown
        messages = [
            _FakeMsg(
                "HEARTBEAT",
                base_mode=128 | 1,  # armed
                custom_mode=10,  # AUTO
                system_status=4,
            ),
        ]
        call_count = 0

        def fake_recv_match(blocking=True, timeout=0.5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages[0]
            # Signal shutdown after first message
            shutdown.set()
            return None

        conn = MagicMock()
        conn.recv_match = fake_recv_match

        mavlink_reader_loop(state, shutdown, conn=conn)

        snap = state.snapshot()
        assert snap["mav"]["armed"] is True
        assert snap["mav"]["mode"] == "AUTO"
        assert snap["mav"]["system_status"] == 4

    def test_gps_raw_updates_state(self) -> None:
        """GPS_RAW_INT updates GPS1 fields."""
        state = SharedState()
        shutdown = threading.Event()

        messages = [
            _FakeMsg(
                "GPS_RAW_INT",
                fix_type=6,
                satellites_visible=18,
                eph=120,  # hdop = 1.2
            ),
        ]
        call_count = 0

        def fake_recv_match(blocking=True, timeout=0.5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages[0]
            shutdown.set()
            return None

        conn = MagicMock()
        conn.recv_match = fake_recv_match

        mavlink_reader_loop(state, shutdown, conn=conn)

        snap = state.snapshot()
        assert snap["mav"]["gps1_fix"] == 6
        assert snap["mav"]["gps1_sats"] == 18
        assert snap["mav"]["gps1_hdop"] == pytest.approx(1.2)

    def test_vfr_hud_updates_state(self) -> None:
        """VFR_HUD updates speed/heading/throttle."""
        state = SharedState()
        shutdown = threading.Event()

        messages = [
            _FakeMsg("VFR_HUD", groundspeed=2.5, heading=180, throttle=45),
        ]
        call_count = 0

        def fake_recv_match(blocking=True, timeout=0.5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages[0]
            shutdown.set()
            return None

        conn = MagicMock()
        conn.recv_match = fake_recv_match

        mavlink_reader_loop(state, shutdown, conn=conn)

        snap = state.snapshot()
        assert snap["mav"]["groundspeed_ms"] == 2.5
        assert snap["mav"]["heading_deg"] == 180
        assert snap["mav"]["throttle_pct"] == 45

    def test_statustext_updates_state(self) -> None:
        """STATUSTEXT updates last message."""
        state = SharedState()
        shutdown = threading.Event()

        messages = [
            _FakeMsg("STATUSTEXT", text="PreArm: GPS not healthy"),
        ]
        call_count = 0

        def fake_recv_match(blocking=True, timeout=0.5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages[0]
            shutdown.set()
            return None

        conn = MagicMock()
        conn.recv_match = fake_recv_match

        mavlink_reader_loop(state, shutdown, conn=conn)

        snap = state.snapshot()
        assert snap["mav"]["last_statustext"] == "PreArm: GPS not healthy"

    def test_rtk_updates_state(self) -> None:
        """GPS_RTK updates RTK baseline and IAR."""
        state = SharedState()
        shutdown = threading.Event()

        messages = [
            _FakeMsg("GPS_RTK", baseline_a_mm=350, iar_num_hypotheses=1),
        ]
        call_count = 0

        def fake_recv_match(blocking=True, timeout=0.5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages[0]
            shutdown.set()
            return None

        conn = MagicMock()
        conn.recv_match = fake_recv_match

        mavlink_reader_loop(state, shutdown, conn=conn)

        snap = state.snapshot()
        assert snap["mav"]["rtk1_baseline_mm"] == 350
        assert snap["mav"]["rtk1_iar"] == 1

    def test_shutdown_event_stops_loop(self) -> None:
        """Loop exits promptly when shutdown event is set."""
        state = SharedState()
        shutdown = threading.Event()
        shutdown.set()  # pre-set

        conn = MagicMock()
        conn.recv_match = MagicMock(return_value=None)

        # Should return quickly without blocking
        mavlink_reader_loop(state, shutdown, conn=conn)
        # If we get here, the loop exited — pass
