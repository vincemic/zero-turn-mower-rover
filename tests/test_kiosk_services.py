"""Tests for kiosk service-checking logic.

These tests do NOT require GTK4 and run on all platforms (including
Windows CI).
"""

from __future__ import annotations

import time


class TestWatchdogGating:
    """Tests for _should_notify_watchdog() heartbeat freshness gating."""

    def test_watchdog_fires_when_never_connected(self):
        """WATCHDOG=1 IS sent when last_heartbeat_epoch == 0.0 (never connected)."""
        from mower_rover.kiosk.app import _should_notify_watchdog

        assert _should_notify_watchdog(last_hb=0.0, now=time.time(), staleness_s=60.0) is True

    def test_watchdog_fires_when_heartbeat_fresh(self):
        """WATCHDOG=1 IS sent when heartbeat is within staleness threshold."""
        from mower_rover.kiosk.app import _should_notify_watchdog

        now = time.time()
        last_hb = now - 10.0  # 10 seconds ago, threshold is 60
        assert _should_notify_watchdog(last_hb=last_hb, now=now, staleness_s=60.0) is True

    def test_watchdog_suppressed_when_heartbeat_stale(self):
        """WATCHDOG=1 is NOT sent when heartbeat was received but is now stale."""
        from mower_rover.kiosk.app import _should_notify_watchdog

        now = time.time()
        last_hb = now - 120.0  # 120 seconds ago, threshold is 60
        assert _should_notify_watchdog(last_hb=last_hb, now=now, staleness_s=60.0) is False


class TestUnitDisplayKey:
    """Tests for _unit_display_key() helper."""

    def test_standard_unit(self):
        from mower_rover.kiosk.app import _unit_display_key

        assert _unit_display_key("mower-health.service") == "health"

    def test_hyphenated_unit(self):
        from mower_rover.kiosk.app import _unit_display_key

        assert _unit_display_key("mower-vslam-bridge.service") == "vslam_bridge"

    def test_no_prefix(self):
        from mower_rover.kiosk.app import _unit_display_key

        assert _unit_display_key("seatd.service") == "seatd"

    def test_no_suffix(self):
        from mower_rover.kiosk.app import _unit_display_key

        assert _unit_display_key("mower-health") == "health"


class TestCheckServices:
    """Tests for _check_services() subprocess invocation."""

    def test_no_user_flag(self, monkeypatch):
        """systemctl is called without --user."""
        import subprocess

        from mower_rover.kiosk.app import _check_services

        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="active\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        units = ["mower-health.service", "mower-vslam.service"]
        result = _check_services(units)

        assert len(calls) == 2
        for call in calls:
            assert "--user" not in call
            assert call[:2] == ["systemctl", "is-active"]

    def test_correct_unit_names_passed(self, monkeypatch):
        """The unit names passed to systemctl match the input list."""
        import subprocess

        from mower_rover.kiosk.app import _check_services

        called_units: list[str] = []

        def fake_run(cmd, **kwargs):
            called_units.append(cmd[2])
            return subprocess.CompletedProcess(cmd, 0, stdout="active\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        units = ["mower-vslam.service", "mower-mavproxy.service"]
        _check_services(units)

        assert called_units == ["mower-vslam.service", "mower-mavproxy.service"]

    def test_result_keys_derived_from_unit_names(self, monkeypatch):
        """Result dict keys are derived by stripping mower- and .service."""
        import subprocess

        from mower_rover.kiosk.app import _check_services

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="active\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        units = [
            "mower-health.service",
            "mower-vslam.service",
            "mower-vslam-bridge.service",
            "mower-weston.service",
            "mower-mavproxy.service",
        ]
        result = _check_services(units)

        assert set(result.keys()) == {"health", "vslam", "vslam_bridge", "weston", "mavproxy"}
        assert all(v == "active" for v in result.values())

    def test_default_units_from_config(self, monkeypatch):
        """When no units passed, defaults come from _default_kiosk_service_units."""
        import subprocess

        from mower_rover.config.jetson import _default_kiosk_service_units
        from mower_rover.kiosk.app import _check_services

        called_units: list[str] = []

        def fake_run(cmd, **kwargs):
            called_units.append(cmd[2])
            return subprocess.CompletedProcess(cmd, 0, stdout="active\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _check_services()  # no units arg

        assert called_units == _default_kiosk_service_units()

    def test_timeout_returns_unknown(self, monkeypatch):
        """TimeoutExpired results in 'unknown' for that service."""
        import subprocess

        from mower_rover.kiosk.app import _check_services

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = _check_services(["mower-health.service"])
        assert result == {"health": "unknown"}


class TestKioskUnitsCliConstant:
    """Verify KIOSK_UNITS in the CLI module has correct unit names."""

    def test_mavproxy_unit_name(self):
        from mower_rover.cli.kiosk import KIOSK_UNITS

        assert "mower-mavproxy.service" in KIOSK_UNITS
        assert "mavproxy.service" not in KIOSK_UNITS


class TestDefaultKioskServiceUnits:
    """Verify _default_kiosk_service_units includes all 5 units."""

    def test_all_five_units(self):
        from mower_rover.config.jetson import _default_kiosk_service_units

        units = _default_kiosk_service_units()
        assert len(units) == 5
        assert "mower-health.service" in units
        assert "mower-vslam.service" in units
        assert "mower-vslam-bridge.service" in units
        assert "mower-weston.service" in units
        assert "mower-mavproxy.service" in units
