"""Power mode check — verifies nvpmodel is parseable."""

from __future__ import annotations

from pathlib import Path

from mower_rover.health.power import read_power_state
from mower_rover.probe.registry import Severity, register


@register("power_mode", severity=Severity.WARNING, depends_on=("jetpack_version",))
def check_power_mode(sysroot: Path) -> tuple[bool, str]:
    """Verify nvpmodel mode is readable."""
    state = read_power_state(sysroot=sysroot)
    if state.mode_id is not None:
        return True, f"Power mode: {state.mode_name} (id={state.mode_id})"
    return False, "nvpmodel not found or failed"
