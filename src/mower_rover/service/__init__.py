"""Systemd service management for the mower-health daemon.

Public surface:
- ``generate_unit_file`` — render a systemd unit file from template.
- ``install_service`` — write unit file and reload systemd.
- ``uninstall_service`` — stop, disable, remove unit file, reload.
- ``run_daemon`` — health monitoring loop with sd_notify integration.
"""

from __future__ import annotations

from mower_rover.service.daemon import run_daemon
from mower_rover.service.unit import generate_unit_file, install_service, uninstall_service

__all__ = [
    "generate_unit_file",
    "install_service",
    "run_daemon",
    "uninstall_service",
]
