"""Systemd service probe checks for Jetson user-level services.

Verifies that operator-facing systemd services (health monitor, linger)
are configured and running.  All checks accept a ``sysroot`` path for
interface consistency with the rest of the probe framework.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mower_rover.probe.registry import Severity, register


@register("health_service", severity=Severity.CRITICAL)
def check_health_service(sysroot: Path) -> tuple[bool, str]:
    """Check that mower-health.service is active (system scope).

    Plan 014 Phase 1 step 1.6a: services are installed at the system tier by
    default; query without ``--user`` so the probe matches production.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "mower-health.service"],
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


@register("loginctl_linger", severity=Severity.WARNING)
def check_loginctl_linger(sysroot: Path) -> tuple[bool, str]:
    """Check that loginctl linger is enabled for the current user."""
    user = os.environ.get("USER") or os.environ.get("USERNAME", "")
    if not user:
        return False, "Cannot determine current user"
    try:
        result = subprocess.run(
            ["loginctl", "show-user", user, "-p", "Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        value = result.stdout.strip().lower()
        if value == "yes":
            return True, "Linger=yes"
        return False, f"Linger={value or 'no'}"
    except FileNotFoundError:
        return False, "loginctl not found (not running on systemd host)"
    except subprocess.TimeoutExpired:
        return False, "loginctl timed out"
