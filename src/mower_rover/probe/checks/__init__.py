"""Import all check modules to trigger ``@register`` decoration."""

from __future__ import annotations

from mower_rover.probe.checks import (  # noqa: F401
    cuda,
    disk,
    jetpack,
    oakd,
    power_mode,
    python_ver,
    ssh_hardening,
    thermal,
)
