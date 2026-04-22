"""Disk usage reader for Jetson.

Reads ``/proc/mounts`` (Linux) for key mount points and calls
:func:`os.statvfs` to obtain usage figures.  On platforms where
``/proc/mounts`` does not exist (Windows), returns an empty list.
The ``sysroot`` parameter governs the root for ``/proc/mounts``;
``statvfs`` is always called on the real mount point path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mower_rover.logging_setup.setup import get_logger

_log = get_logger("health.disk")

_INTERESTING_MOUNTS = frozenset({"/", "/home", "/data"})


@dataclass(frozen=True)
class DiskUsage:
    """Disk usage for a single mount point."""

    mount_point: str
    device: str
    total_gb: float
    used_gb: float
    free_gb: float
    is_nvme: bool


def _parse_proc_mounts(sysroot: Path) -> list[tuple[str, str]]:
    """Return ``(device, mount_point)`` pairs from ``/proc/mounts``."""
    mounts_file = sysroot / "proc" / "mounts"
    if not mounts_file.is_file():
        return []
    try:
        text = mounts_file.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("proc_mounts_read_error", error=str(exc))
        return []

    results: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        device, mount = parts[0], parts[1]
        if mount in _INTERESTING_MOUNTS:
            results.append((device, mount))
    return results


def _statvfs(mount_point: str) -> tuple[float, float, float] | None:
    """Return ``(total_gb, used_gb, free_gb)`` via :func:`os.statvfs`.

    Returns ``None`` when the call is unavailable (Windows) or fails.
    """
    if not hasattr(os, "statvfs"):
        return None
    try:
        st = os.statvfs(mount_point)
    except OSError as exc:
        _log.warning("statvfs_error", mount=mount_point, error=str(exc))
        return None
    total = st.f_frsize * st.f_blocks / (1024**3)
    free = st.f_frsize * st.f_bavail / (1024**3)
    used = total - free
    return round(total, 2), round(used, 2), round(free, 2)


def read_disk_usage(sysroot: Path = Path("/")) -> list[DiskUsage]:
    """Read disk usage for key mount points.

    On non-Linux platforms (no ``/proc/mounts``), returns an empty list.
    """
    mounts = _parse_proc_mounts(sysroot)
    results: list[DiskUsage] = []
    for device, mount in mounts:
        stats = _statvfs(mount)
        if stats is None:
            # Can't read real statvfs (e.g. Windows or permission error).
            # Still report mount presence for NVMe detection.
            results.append(
                DiskUsage(
                    mount_point=mount,
                    device=device,
                    total_gb=0.0,
                    used_gb=0.0,
                    free_gb=0.0,
                    is_nvme="nvme" in device.lower(),
                )
            )
            continue
        total_gb, used_gb, free_gb = stats
        results.append(
            DiskUsage(
                mount_point=mount,
                device=device,
                total_gb=total_gb,
                used_gb=used_gb,
                free_gb=free_gb,
                is_nvme="nvme" in device.lower(),
            )
        )
    _log.debug("disk_usage_read", mount_count=len(results))
    return results
