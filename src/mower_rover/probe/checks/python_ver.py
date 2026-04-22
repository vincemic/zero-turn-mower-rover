"""Python version check — verifies Python 3.11+ is available."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mower_rover.probe.registry import Severity, register


@register("python_ver", severity=Severity.CRITICAL, depends_on=("jetpack_version",))
def check_python_ver(sysroot: Path) -> tuple[bool, str]:
    """Verify Python 3.11+ is available on the system."""
    for cmd in ("python3.11", "python3"):
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

        if result.returncode != 0:
            continue

        # Output like "Python 3.11.9"
        version_str = result.stdout.strip()
        parts = version_str.split()
        if len(parts) >= 2:
            ver = parts[1]
            try:
                major, minor = int(ver.split(".")[0]), int(ver.split(".")[1])
                if major >= 3 and minor >= 11:
                    return True, version_str
            except (ValueError, IndexError):
                pass

    return False, "Python 3.11+ not found; install via uv python install 3.11"
