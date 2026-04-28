"""Zone pre-flight probe checks.

Verifies zone configuration, mission upload, and VSLAM readiness for
autonomous mowing operations. Checks fence/mission alignment, VSLAM
database compatibility, and relocalization status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from mower_rover.zone.config import ZoneConfig, load_zone_config
from mower_rover.zone.mission_items import zone_to_fence
from mower_rover.mavlink.mission import MissionItem
from mower_rover.probe.registry import Severity, register
from mower_rover.logging_setup.setup import get_logger

logger = get_logger()


def check_fence_match(
    zone: ZoneConfig, 
    fence_items: list[MissionItem], 
    tolerance: float = 1e-7
) -> tuple[bool, str]:
    """Compare uploaded fence vertices against zone boundary.
    
    Verifies that the fence items uploaded to the flight controller
    match the zone boundary vertices within tolerance.
    
    Args:
        zone: Zone configuration with boundary
        fence_items: Mission items downloaded from flight controller (mission_type=1)
        tolerance: Maximum coordinate difference (degrees)
        
    Returns:
        (passed, detail) tuple
    """
    log = logger.bind(zone_id=zone.zone_id, fence_count=len(fence_items))
    log.debug("checking fence match")
    
    # Generate expected fence from zone
    expected_items = zone_to_fence(zone)
    
    if len(expected_items) != len(fence_items):
        detail = f"Fence vertex count mismatch: expected {len(expected_items)}, got {len(fence_items)}"
        log.warning("fence count mismatch", expected=len(expected_items), actual=len(fence_items))
        return False, detail
    
    # Compare each vertex
    for i, (expected, actual) in enumerate(zip(expected_items, fence_items)):
        # Convert int32 coordinates back to degrees for comparison
        expected_lat = expected.x / 1e7
        expected_lon = expected.y / 1e7
        actual_lat = actual.x / 1e7
        actual_lon = actual.y / 1e7
        
        lat_diff = abs(expected_lat - actual_lat)
        lon_diff = abs(expected_lon - actual_lon)
        
        if lat_diff > tolerance or lon_diff > tolerance:
            detail = (f"Fence vertex {i} mismatch: expected ({expected_lat:.7f}, {expected_lon:.7f}), "
                     f"got ({actual_lat:.7f}, {actual_lon:.7f}) "
                     f"(diff: lat={lat_diff:.2e}, lon={lon_diff:.2e})")
            log.warning("fence vertex mismatch", vertex=i, lat_diff=lat_diff, lon_diff=lon_diff)
            return False, detail
    
    detail = f"Fence matches zone boundary ({len(fence_items)} vertices, tolerance ±{tolerance:.0e}°)"
    log.info("fence match verified", vertex_count=len(fence_items))
    return True, detail


def check_mission_count(expected: int, actual: int, tolerance: int = 5) -> tuple[bool, str]:
    """Check mission item count is within tolerance.
    
    Verifies that the uploaded mission has approximately the expected
    number of waypoints, allowing for small variations in path planning.
    
    Args:
        expected: Expected number of mission items
        actual: Actual number of mission items
        tolerance: Acceptable difference
        
    Returns:
        (passed, detail) tuple
    """
    diff = abs(expected - actual)
    
    if diff <= tolerance:
        detail = f"Mission count OK: {actual} items (expected ~{expected}, tolerance ±{tolerance})"
        return True, detail
    
    detail = f"Mission count mismatch: got {actual}, expected {expected} (±{tolerance})"
    return False, detail


def check_vslam_zone_match(sysroot: Path, zone_id: str) -> tuple[bool, str]:
    """Check VSLAM database path matches active zone.
    
    Verifies that the VSLAM configuration points to the correct
    database for the specified zone.
    
    Args:
        sysroot: System root path for file access
        zone_id: Expected zone identifier
        
    Returns:
        (passed, detail) tuple
    """
    vslam_config_path = sysroot / "etc/mower/vslam.yaml"
    
    if not vslam_config_path.exists():
        return False, "VSLAM config file not found"
    
    try:
        config_data = yaml.safe_load(vslam_config_path.read_text())
    except Exception as e:
        return False, f"Failed to parse VSLAM config: {e}"
    
    database_path = config_data.get("database_path", "")
    expected_fragment = f"zones/{zone_id}/"
    
    if expected_fragment in database_path:
        detail = f"VSLAM database path matches zone {zone_id}: {database_path}"
        return True, detail
    
    detail = f"VSLAM database_path '{database_path}' does not contain '{expected_fragment}'"
    return False, detail


def check_vslam_relocalized(sysroot: Path, min_confidence: float = 1.0) -> tuple[bool, str]:
    """Check VSLAM relocalization status.
    
    Verifies that VSLAM has successfully relocalized in the zone
    database with sufficient confidence for autonomous operation.
    
    Args:
        sysroot: System root path for file access
        min_confidence: Minimum acceptable confidence level
        
    Returns:
        (passed, detail) tuple
    """
    status_path = sysroot / "run/mower/vslam-status.json"
    
    if not status_path.exists():
        return False, "VSLAM status file not found (service may not be running)"
    
    try:
        status_data = json.loads(status_path.read_text())
    except Exception as e:
        return False, f"Failed to parse VSLAM status: {e}"
    
    confidence = status_data.get("confidence", 0.0)
    
    if confidence >= min_confidence:
        detail = f"VSLAM relocalized (confidence={confidence:.2f}, threshold≥{min_confidence})"
        return True, detail
    
    detail = f"VSLAM not relocalized (confidence={confidence:.2f}, need≥{min_confidence})"
    return False, detail


# ------------------------------------------------------------------
# Registered probe checks
# ------------------------------------------------------------------

@register("zone_fence_match", severity=Severity.CRITICAL)
def _zone_fence_match_probe(sysroot: Path) -> tuple[bool, str]:
    """PF-37: Verify uploaded fence matches zone boundary.
    
    Reads active zone config and cached fence data to verify alignment.
    This is a filesystem-based wrapper for the core fence matching logic.
    """
    # Read active zone config
    active_zone_path = sysroot / "var/lib/mower/active-zone.yaml"
    if not active_zone_path.exists():
        return False, "No active zone configuration found"
    
    try:
        zone = load_zone_config(active_zone_path)
    except Exception as e:
        return False, f"Failed to load active zone config: {e}"
    
    # Read cached fence data
    fence_cache_path = sysroot / "var/cache/mower/fence-items.json"
    if not fence_cache_path.exists():
        return False, "No cached fence data found (run mission download first)"
    
    try:
        fence_data = json.loads(fence_cache_path.read_text())
        fence_items = [
            MissionItem(**item_data) for item_data in fence_data.get("items", [])
        ]
    except Exception as e:
        return False, f"Failed to parse cached fence data: {e}"
    
    return check_fence_match(zone, fence_items)


@register("zone_mission_count", severity=Severity.WARNING)
def _zone_mission_count_probe(sysroot: Path) -> tuple[bool, str]:
    """PF-38: Verify mission waypoint count is reasonable.
    
    Compares expected waypoint count from planning with actual uploaded count.
    """
    # Read mission planning results
    plan_cache_path = sysroot / "var/cache/mower/mission-plan.json" 
    if not plan_cache_path.exists():
        return False, "No cached mission plan found (run mission planning first)"
    
    try:
        plan_data = json.loads(plan_cache_path.read_text())
        expected_count = plan_data.get("waypoint_count", 0)
    except Exception as e:
        return False, f"Failed to parse mission plan cache: {e}"
    
    # Read cached mission data
    mission_cache_path = sysroot / "var/cache/mower/mission-items.json"
    if not mission_cache_path.exists():
        return False, "No cached mission data found (run mission download first)"
    
    try:
        mission_data = json.loads(mission_cache_path.read_text())
        actual_count = len(mission_data.get("items", []))
    except Exception as e:
        return False, f"Failed to parse cached mission data: {e}"
    
    return check_mission_count(expected_count, actual_count)


@register("zone_vslam_match", severity=Severity.WARNING, depends_on=("vslam_params",))
def _zone_vslam_match_probe(sysroot: Path) -> tuple[bool, str]:
    """PF-39: Verify VSLAM database path matches active zone."""
    # Read active zone ID
    active_zone_path = sysroot / "var/lib/mower/active-zone.yaml"
    if not active_zone_path.exists():
        return False, "No active zone configuration found"
    
    try:
        zone = load_zone_config(active_zone_path)
        zone_id = zone.zone_id
    except Exception as e:
        return False, f"Failed to load active zone config: {e}"
    
    return check_vslam_zone_match(sysroot, zone_id)


@register("zone_vslam_relocalized", severity=Severity.WARNING, depends_on=("vslam_bridge",))
def _zone_vslam_relocalized_probe(sysroot: Path) -> tuple[bool, str]:
    """PF-40: Verify VSLAM relocalization status."""
    return check_vslam_relocalized(sysroot)