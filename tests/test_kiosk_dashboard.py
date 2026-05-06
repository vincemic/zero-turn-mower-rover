"""Tests for kiosk dashboard components (GTK4).

Skips cleanly on systems without GTK4 (Windows CI, headless Linux without
display server).
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi", reason="GTK4 not available")


def _require_gtk4():
    """Try to load GTK 4.0; skip test if unavailable or no display."""
    try:
        gi.require_version("Gtk", "4.0")
        # GTK4 needs a display — skip if headless
        from gi.repository import Gdk

        if Gdk.Display.get_default() is None:
            pytest.skip("No display available (headless environment)")
    except (ValueError, ImportError) as exc:
        pytest.skip(f"GTK4 not available: {exc}")


class TestStatusCard:
    """Tests for StatusCard widget."""

    def test_creation(self):
        """StatusCard can be instantiated with title and metrics."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test Card", num_metrics=4)
        assert card is not None

    def test_set_status_ok(self):
        """set_status('ok') applies the correct CSS class."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test", num_metrics=2)
        card.set_status("ok")
        assert card.has_css_class("status-ok")
        assert not card.has_css_class("status-warn")
        assert not card.has_css_class("status-fail")

    def test_set_status_warn(self):
        """set_status('warn') applies the correct CSS class."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test", num_metrics=2)
        card.set_status("warn")
        assert card.has_css_class("status-warn")
        assert not card.has_css_class("status-ok")

    def test_set_status_fail(self):
        """set_status('fail') applies the correct CSS class."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test", num_metrics=2)
        card.set_status("fail")
        assert card.has_css_class("status-fail")
        assert not card.has_css_class("status-ok")

    def test_set_metric(self):
        """set_metric updates the label and value text."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test", num_metrics=3)
        card.set_metric(0, "Speed", "4.2 m/s")
        card.set_metric(1, "Heading", "180°")
        card.set_metric(2, "Mode", "AUTO")

        # Verify via internal labels
        assert card._metric_labels[0].get_label() == "Speed"
        assert card._metric_values[0].get_label() == "4.2 m/s"
        assert card._metric_labels[1].get_label() == "Heading"
        assert card._metric_values[1].get_label() == "180°"

    def test_set_metric_out_of_range(self):
        """set_metric with invalid index does not crash."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test", num_metrics=2)
        # Should not raise
        card.set_metric(99, "Bad", "Index")
        card.set_metric(-1, "Bad", "Index")

    def test_status_transition(self):
        """Transitioning status removes old class, adds new."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import StatusCard

        card = StatusCard("Test", num_metrics=1)
        card.set_status("ok")
        assert card.has_css_class("status-ok")

        card.set_status("fail")
        assert card.has_css_class("status-fail")
        assert not card.has_css_class("status-ok")


class TestDashboardWindow:
    """Tests for DashboardWindow refresh logic."""

    def test_refresh_updates_from_snapshot(self):
        """_refresh() reads SharedState and updates card metrics."""
        _require_gtk4()
        from gi.repository import Gtk

        from mower_rover.kiosk.dashboard import DashboardWindow
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        state.update_mav(mode="AUTO", armed=True, groundspeed_ms=2.5, heading_deg=90)
        state.update_mav(gps1_fix=6, gps1_sats=12, gps1_hdop=0.8)
        state.update_wifi("wlan0", -45.0, 85.0)
        state.update_vslam(rate_hz=30.0, confidence=3, age_ms=50, covariance_norm=0.01)
        state.update_health(cpu_temp_c=55.0, gpu_temp_c=50.0, power_mode="50W", fan_status="active")
        state.update_storage(nvme_pct=45.0, nvme_free_gb="950.2 GB", root_pct=30.0)
        state.update_services({"slam_node": "active", "vslam_bridge": "active"})

        app = Gtk.Application(application_id="org.mower.kiosk.test")

        win = DashboardWindow(app, state)

        # Call refresh manually
        result = win._refresh()
        assert result is True  # Timer should stay alive

        # Verify Vehicle State card (index 1)
        assert win._cards[1]._metric_values[0].get_label() == "AUTO"
        assert win._cards[1]._metric_values[1].get_label() == "YES"

        # Verify GPS card (index 2) — fix type 6 = ok status
        assert win._cards[2].has_css_class("status-ok")

        # Verify Wi-Fi card (index 5)
        assert win._cards[5]._metric_values[0].get_label() == "wlan0"


class TestKioskApp:
    """Tests for KioskApp creation."""

    def test_app_instantiation(self):
        """KioskApp can be instantiated without errors."""
        _require_gtk4()
        from mower_rover.kiosk.dashboard import KioskApp
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        app = KioskApp(state)
        assert app is not None
        assert app._state is state


class TestSharedStateExtensions:
    """Test the new SharedState methods added for dashboard panels."""

    def test_update_vslam(self):
        """update_vslam stores pose data retrievable via snapshot."""
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        state.update_vslam(rate_hz=30.0, confidence=3, age_ms=50)
        snap = state.snapshot()
        assert snap["vslam"]["rate_hz"] == 30.0
        assert snap["vslam"]["confidence"] == 3

    def test_update_health(self):
        """update_health stores thermal/power data."""
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        state.update_health(cpu_temp_c=65.0, power_mode="50W")
        snap = state.snapshot()
        assert snap["health"]["cpu_temp_c"] == 65.0
        assert snap["health"]["power_mode"] == "50W"

    def test_update_storage(self):
        """update_storage stores disk data."""
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        state.update_storage(nvme_pct=42.0, root_pct=25.0)
        snap = state.snapshot()
        assert snap["storage"]["nvme_pct"] == 42.0

    def test_update_services(self):
        """update_services stores service statuses."""
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        state.update_services({"slam_node": "active", "health_monitor": "failed"})
        snap = state.snapshot()
        assert snap["services"]["slam_node"] == "active"
        assert snap["services"]["health_monitor"] == "failed"

    def test_snapshot_includes_all_sections(self):
        """snapshot() returns all expected top-level keys."""
        from mower_rover.kiosk.state import SharedState

        state = SharedState()
        snap = state.snapshot()
        assert "mav" in snap
        assert "wifi_interface" in snap
        assert "vslam" in snap
        assert "health" in snap
        assert "storage" in snap
        assert "services" in snap
        assert "last_update" in snap
