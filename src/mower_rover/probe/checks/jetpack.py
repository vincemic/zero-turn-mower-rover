"""JetPack version check — reads /etc/nv_tegra_release."""

from __future__ import annotations

from pathlib import Path

from mower_rover.probe.registry import Severity, register


@register("jetpack_version", severity=Severity.CRITICAL)
def check_jetpack_version(sysroot: Path) -> tuple[bool, str]:
    """Verify the Jetson is running L4T R36.x (JetPack 6)."""
    release_file = sysroot / "etc" / "nv_tegra_release"
    if not release_file.is_file():
        return False, "Not a Jetson (file missing)"
    try:
        first_line = release_file.read_text(encoding="utf-8").strip().splitlines()[0]
    except (OSError, IndexError):
        return False, "Not a Jetson (file missing)"

    if "R36" in first_line:
        return True, first_line
    return False, f"Expected L4T R36.x, found: {first_line}"
