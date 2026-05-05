"""GTK4 kiosk dashboard: StatusCard, DashboardWindow, and KioskApp.

Displays an 8-panel operational dashboard on the Jetson's display.
Designed for fullscreen use at 1024×600 or 1280×800.
"""

from __future__ import annotations

import importlib.resources

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from mower_rover.kiosk.state import SharedState  # noqa: E402


class StatusCard(Gtk.Frame):
    """A single status panel with a title, status dot, and metric rows."""

    def __init__(self, title: str, num_metrics: int = 4) -> None:
        super().__init__()
        self.add_css_class("status-card")

        self._status = "ok"

        # Outer vertical box
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_child(vbox)

        # Header: status dot + title label
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        vbox.append(header)

        self._dot = Gtk.Label(label="\u25CF")
        self._dot.add_css_class("status-dot")
        header.append(self._dot)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("status-card-title")
        title_label.set_halign(Gtk.Align.START)
        header.append(title_label)

        # Metric rows: label + value pairs
        self._metric_labels: list[Gtk.Label] = []
        self._metric_values: list[Gtk.Label] = []

        for _ in range(num_metrics):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            vbox.append(row)

            lbl = Gtk.Label(label="")
            lbl.add_css_class("metric-label")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_hexpand(False)
            row.append(lbl)
            self._metric_labels.append(lbl)

            val = Gtk.Label(label="--")
            val.add_css_class("metric-value")
            val.set_halign(Gtk.Align.END)
            val.set_hexpand(True)
            row.append(val)
            self._metric_values.append(val)

        self.set_status("ok")

    def set_status(self, status: str) -> None:
        """Set the card status: 'ok', 'warn', or 'fail'."""
        # Remove old status class
        self.remove_css_class(f"status-{self._status}")
        self._status = status
        self.add_css_class(f"status-{status}")

    def set_metric(self, index: int, label: str, value: str) -> None:
        """Update a metric row by index (0-based)."""
        if 0 <= index < len(self._metric_labels):
            self._metric_labels[index].set_label(label)
            self._metric_values[index].set_label(value)


# ──────────────────────────────────────────────────────────────────────────────
# Panel definitions — which cards exist and how to populate them
# ──────────────────────────────────────────────────────────────────────────────

_CARD_DEFS: list[tuple[str, int]] = [
    ("VSLAM Status", 4),
    ("Vehicle State", 4),
    ("GPS / RTK", 4),
    ("System Health", 4),
    ("Storage", 4),
    ("Wi-Fi", 4),
    ("Services", 4),
    ("Alerts", 4),
]


class DashboardWindow(Gtk.ApplicationWindow):
    """Fullscreen 4×2 grid of status cards, refreshed at 1 Hz."""

    def __init__(self, app: Gtk.Application, state: SharedState) -> None:
        super().__init__(application=app, title="Mower Kiosk")
        self._state = state

        self.fullscreen()

        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)
        grid.add_css_class("kiosk-grid")
        self.set_child(grid)

        self._cards: list[StatusCard] = []
        for idx, (title, num_metrics) in enumerate(_CARD_DEFS):
            card = StatusCard(title, num_metrics)
            col = idx % 4
            row = idx // 4
            grid.attach(card, col, row, 1, 1)
            self._cards.append(card)

        # Start periodic refresh
        GLib.timeout_add(1000, self._refresh)

    def _refresh(self) -> bool:
        """Update all cards from SharedState. Returns True to keep timer alive."""
        snap = self._state.snapshot()
        mav = snap["mav"]

        # Card 0: VSLAM Status
        vslam = snap.get("vslam", {})
        c = self._cards[0]
        c.set_metric(0, "Confidence", str(vslam.get("confidence", "--")))
        c.set_metric(1, "Resets", str(vslam.get("reset_counter", "--")))
        c.set_metric(2, "X", f"{vslam.get('x', 0.0):.2f}")
        c.set_metric(3, "Y", f"{vslam.get('y', 0.0):.2f}")
        vslam_conf = vslam.get("confidence", 0)
        if vslam_conf >= 2:
            c.set_status("ok")
        elif vslam_conf == 1:
            c.set_status("warn")
        else:
            c.set_status("fail")

        # Card 1: Vehicle State
        c = self._cards[1]
        c.set_metric(0, "Mode", mav.get("mode", "--"))
        c.set_metric(1, "Armed", "YES" if mav.get("armed") else "NO")
        c.set_metric(2, "Speed", f"{mav.get('groundspeed_ms', 0.0):.1f} m/s")
        c.set_metric(3, "Heading", f"{mav.get('heading_deg', 0)}°")
        armed = mav.get("armed", False)
        c.set_status("warn" if armed else "ok")

        # Card 2: GPS / RTK
        c = self._cards[2]
        fix1 = mav.get("gps1_fix", 0)
        c.set_metric(0, "GPS1 Fix", str(fix1))
        c.set_metric(1, "GPS1 Sats", str(mav.get("gps1_sats", 0)))
        c.set_metric(2, "RTK Base", f"{mav.get('rtk1_baseline_mm', 0)} mm")
        c.set_metric(3, "HDOP", f"{mav.get('gps1_hdop', 99.99):.2f}")
        if fix1 >= 6:  # RTK Fixed
            c.set_status("ok")
        elif fix1 >= 5:  # RTK Float
            c.set_status("warn")
        else:
            c.set_status("fail")

        # Card 3: System Health
        c = self._cards[3]
        health = snap.get("health", {})
        c.set_metric(0, "CPU Temp", f"{health.get('cpu_temp_c', '--')}°C")
        c.set_metric(1, "GPU Temp", f"{health.get('gpu_temp_c', '--')}°C")
        c.set_metric(2, "Power", health.get("power_mode", "--"))
        c.set_metric(3, "Fan", health.get("fan_status", "--"))
        cpu_temp = health.get("cpu_temp_c", 0)
        if isinstance(cpu_temp, (int, float)):
            if cpu_temp >= 85:
                c.set_status("fail")
            elif cpu_temp >= 70:
                c.set_status("warn")
            else:
                c.set_status("ok")

        # Card 4: Storage
        c = self._cards[4]
        storage = snap.get("storage", {})
        c.set_metric(0, "NVMe Used", f"{storage.get('nvme_pct', '--')}%")
        c.set_metric(1, "NVMe Free", storage.get("nvme_free_gb", "--"))
        c.set_metric(2, "Root Used", f"{storage.get('root_pct', '--')}%")
        c.set_metric(3, "RTAB-Map DB", storage.get("rtabmap_db_mb", "--"))
        nvme_pct = storage.get("nvme_pct", 0)
        if isinstance(nvme_pct, (int, float)):
            if nvme_pct >= 90:
                c.set_status("fail")
            elif nvme_pct >= 75:
                c.set_status("warn")
            else:
                c.set_status("ok")

        # Card 5: Wi-Fi
        c = self._cards[5]
        c.set_metric(0, "Interface", snap.get("wifi_interface", "--"))
        sig = snap.get("wifi_signal_dbm", 0.0)
        c.set_metric(1, "Signal", f"{sig} dBm")
        c.set_metric(2, "Quality", f"{snap.get('wifi_link_quality', 0.0):.0f}%")
        c.set_metric(3, "", "")
        if sig >= -50:
            c.set_status("ok")
        elif sig >= -70:
            c.set_status("warn")
        else:
            c.set_status("fail")

        # Card 6: Services
        c = self._cards[6]
        services = snap.get("services", {})
        c.set_metric(0, "SLAM Node", services.get("slam_node", "--"))
        c.set_metric(1, "VSLAM Bridge", services.get("vslam_bridge", "--"))
        c.set_metric(2, "Health Mon", services.get("health_monitor", "--"))
        c.set_metric(3, "MAVProxy", services.get("mavproxy", "--"))
        statuses = [v for v in services.values() if isinstance(v, str)]
        if any(s == "failed" for s in statuses):
            c.set_status("fail")
        elif any(s != "active" for s in statuses):
            c.set_status("warn")
        elif statuses:
            c.set_status("ok")

        # Card 7: Alerts
        c = self._cards[7]
        statustext = mav.get("last_statustext", "")
        c.set_metric(0, "Last Msg", statustext[:30] if statustext else "--")
        c.set_metric(1, "", statustext[30:60] if len(statustext) > 30 else "")
        c.set_metric(2, "", "")
        c.set_metric(3, "", "")
        if "FAIL" in statustext.upper() or "ERR" in statustext.upper():
            c.set_status("fail")
        elif "WARN" in statustext.upper():
            c.set_status("warn")
        else:
            c.set_status("ok")

        return True  # keep timer alive


class KioskApp(Gtk.Application):
    """GTK4 Application that creates the DashboardWindow and loads CSS."""

    def __init__(self, state: SharedState) -> None:
        super().__init__(application_id="org.mower.kiosk")
        self._state = state

    def do_activate(self) -> None:
        """Create the dashboard window and apply CSS theme."""
        self._load_css()
        win = DashboardWindow(self, self._state)
        win.present()

    def _load_css(self) -> None:
        """Load the dashboard CSS from package resources."""
        provider = Gtk.CssProvider()

        # Load CSS from the package
        css_path = importlib.resources.files("mower_rover.kiosk").joinpath(
            "dashboard.css"
        )
        css_bytes = css_path.read_bytes()
        provider.load_from_data(css_bytes.decode("utf-8"))

        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
