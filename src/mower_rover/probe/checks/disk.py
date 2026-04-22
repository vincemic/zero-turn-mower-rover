"""Disk space and NVMe presence checks."""

from __future__ import annotations

from pathlib import Path

from mower_rover.health.disk import read_disk_usage
from mower_rover.probe.registry import Severity, register


@register("disk_space", severity=Severity.CRITICAL)
def check_disk_space(sysroot: Path) -> tuple[bool, str]:
    """Verify root partition has at least 2 GB free."""
    usages = read_disk_usage(sysroot=sysroot)
    root = next((u for u in usages if u.mount_point == "/"), None)
    if root is None:
        return False, "Root mount point not found in /proc/mounts"
    if root.free_gb >= 2.0:
        return True, f"{root.free_gb:.1f} GB free on /"
    return False, f"Free space below 2 GB: {root.free_gb:.1f} GB"


@register("disk_nvme", severity=Severity.WARNING)
def check_disk_nvme(sysroot: Path) -> tuple[bool, str]:
    """Check whether the root partition is on an NVMe device."""
    usages = read_disk_usage(sysroot=sysroot)
    root = next((u for u in usages if u.mount_point == "/"), None)
    if root is None:
        return False, "Root mount point not found in /proc/mounts"
    if root.is_nvme:
        return True, f"Root on NVMe: {root.device}"
    return False, "Root not on NVMe — performance may be reduced"
