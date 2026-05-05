"""Kiosk display probe checks for Jetson operational display.

Verifies that the kiosk display stack (Weston compositor, kiosk dashboard,
MAVProxy telemetry forwarder) is operational.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mower_rover.probe.registry import Severity, register


@register("kiosk_weston_active", severity=Severity.WARNING)
def check_weston_active(sysroot: Path) -> tuple[bool, str]:
    """Check that mower-weston.service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "mower-weston.service"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "active"
        return False, "not active"
    except FileNotFoundError:
        return False, "systemctl not found (not running on systemd host)"
    except subprocess.TimeoutExpired:
        return False, "systemctl timed out"


@register("kiosk_active", severity=Severity.WARNING, depends_on=("kiosk_weston_active",))
def check_kiosk_active(sysroot: Path) -> tuple[bool, str]:
    """Check that mower-kiosk.service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "mower-kiosk.service"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "active"
        return False, "not active"
    except FileNotFoundError:
        return False, "systemctl not found (not running on systemd host)"
    except subprocess.TimeoutExpired:
        return False, "systemctl timed out"


@register("mavproxy_active", severity=Severity.WARNING)
def check_mavproxy_active(sysroot: Path) -> tuple[bool, str]:
    """Check that mower-mavproxy.service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "mower-mavproxy.service"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "active"
        return False, "not active"
    except FileNotFoundError:
        return False, "systemctl not found (not running on systemd host)"
    except subprocess.TimeoutExpired:
        return False, "systemctl timed out"
