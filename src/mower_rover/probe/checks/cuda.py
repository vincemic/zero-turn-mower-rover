"""CUDA availability check — runs nvcc --version."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mower_rover.probe.registry import Severity, register


@register("cuda", severity=Severity.CRITICAL, depends_on=("jetpack_version",))
def check_cuda(sysroot: Path) -> tuple[bool, str]:
    """Verify CUDA 12.x is installed via ``nvcc --version``."""
    try:
        result = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "CUDA not found"

    if result.returncode != 0:
        return False, "CUDA not found"

    # Look for "release 12." in nvcc output.
    for line in result.stdout.splitlines():
        if "release" in line.lower():
            if "release 12." in line.lower():
                return True, line.strip()
            return False, f"Expected 12.x, found: {line.strip()}"

    return False, "CUDA not found"
