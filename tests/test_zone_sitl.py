from __future__ import annotations

import pytest
from pathlib import Path
from mower_rover.mavlink.connection import ConnectionConfig, open_link
from mower_rover.mavlink.mission import (
    MissionItem, upload_mission, download_mission, clear_mission, verify_round_trip
)
from mower_rover.zone.config import load_zone_config, LatLon
from mower_rover.zone.planner import generate_waypoints
from mower_rover.zone.mission_items import zone_to_mission, zone_to_fence, zone_to_rally
from mower_rover.cli.zone_laptop import _check_not_armed


@pytest.fixture
def sitl_conn(sitl_endpoint: str):
    """MAVLink connection to SITL endpoint."""
    config = ConnectionConfig(endpoint=sitl_endpoint)
    with open_link(config) as conn:
        yield conn


@pytest.mark.sitl
def test_mission_round_trip(sitl_conn) -> None:
    """Test mission upload → download round-trip (mission_type=0)."""
    # Create ~10 waypoints with sequential coordinates
    mission_items = []
    for i in range(10):
        item = MissionItem(
            seq=i,
            frame=0,  # MAV_FRAME_GLOBAL
            command=16,  # MAV_CMD_NAV_WAYPOINT
            param1=0.0,
            param2=0.0,
            param3=0.0,
            param4=0.0,
            x=float(40.123456 + i * 0.0001),  # lat
            y=float(-74.654321 + i * 0.0001),  # lon
            z=0.0,
            mission_type=0,
            autocontinue=1,
            current=1 if i == 0 else 0
        )
        mission_items.append(item)
    
    try:
        # Clear any existing mission
        clear_mission(sitl_conn, mission_type=0)
        
        # Upload mission
        upload_mission(sitl_conn, mission_items, mission_type=0)
        
        # Download mission
        downloaded = download_mission(sitl_conn, mission_type=0)
        
        # Verify round-trip exact match for command, x, y, z
        assert len(downloaded) == len(mission_items)
        for orig, dl in zip(mission_items, downloaded):
            assert dl.command == orig.command
            # Coordinates may have int32×1e7 encoding precision limits (±1e-7 degrees)
            assert abs(dl.x - orig.x) < 1e-6  # lat tolerance
            assert abs(dl.y - orig.y) < 1e-6  # lon tolerance  
            assert abs(dl.z - orig.z) < 1e-6  # alt tolerance
    finally:
        # Cleanup
        clear_mission(sitl_conn, mission_type=0)


@pytest.mark.sitl
def test_fence_round_trip(sitl_conn) -> None:
    """Test fence upload → download round-trip (mission_type=1)."""
    # Load a zone fixture
    zone_path = Path("zones/ne.yaml")
    if not zone_path.exists():
        pytest.skip("Zone fixture zones/ne.yaml not found")
    
    zone = load_zone_config(zone_path)
    fence_items = zone_to_fence(zone)
    
    if not fence_items:
        pytest.skip("No fence items generated from zone")
    
    try:
        # Clear any existing fence
        clear_mission(sitl_conn, mission_type=1)
        
        # Upload fence
        upload_mission(sitl_conn, fence_items, mission_type=1)
        
        # Download fence
        downloaded = download_mission(sitl_conn, mission_type=1)
        
        # Verify fence vertices match within tolerance
        assert len(downloaded) == len(fence_items)
        for orig, dl in zip(fence_items, downloaded):
            assert dl.command == orig.command
            assert abs(dl.x - orig.x) < 1e-6  # lat tolerance
            assert abs(dl.y - orig.y) < 1e-6  # lon tolerance
    except Exception as e:
        # SITL rover-skid may not support fence operations
        if "not supported" in str(e).lower() or "nack" in str(e).lower() or "invalid" in str(e).lower():
            pytest.skip(f"SITL does not support fence operations: {e}")
        raise
    finally:
        # Cleanup
        try:
            clear_mission(sitl_conn, mission_type=1)
        except Exception:
            pass  # Ignore cleanup errors if fence not supported


@pytest.mark.sitl
def test_rally_round_trip(sitl_conn) -> None:
    """Test rally upload → download round-trip (mission_type=2)."""
    # Load a zone fixture
    zone_path = Path("zones/ne.yaml")
    if not zone_path.exists():
        pytest.skip("Zone fixture zones/ne.yaml not found")
    
    zone = load_zone_config(zone_path)
    rally_items = zone_to_rally(zone)
    
    if not rally_items:
        pytest.skip("No rally items generated from zone")
    
    try:
        # Clear any existing rally
        clear_mission(sitl_conn, mission_type=2)
        
        # Upload rally
        upload_mission(sitl_conn, rally_items, mission_type=2)
        
        # Download rally
        downloaded = download_mission(sitl_conn, mission_type=2)
        
        # Verify rally point lat/lon match
        assert len(downloaded) == len(rally_items)
        for orig, dl in zip(rally_items, downloaded):
            assert dl.command == orig.command
            assert abs(dl.x - orig.x) < 1e-6  # lat tolerance
            assert abs(dl.y - orig.y) < 1e-6  # lon tolerance
    except Exception as e:
        # SITL rover-skid may not support rally operations
        if "not supported" in str(e).lower() or "nack" in str(e).lower() or "invalid" in str(e).lower():
            pytest.skip(f"SITL does not support rally operations: {e}")
        raise
    finally:
        # Cleanup
        try:
            clear_mission(sitl_conn, mission_type=2)
        except Exception:
            pass  # Ignore cleanup errors if rally not supported


@pytest.mark.sitl
def test_clear_mission_all_types(sitl_conn) -> None:
    """Test clear mission for all three types (mission_type=0,1,2)."""
    # Test data for each mission type
    test_mission = [MissionItem(seq=0, command=16, x=40.123456, y=-74.654321, z=0.0)]  # NAV_WAYPOINT
    test_fence = [MissionItem(seq=0, command=5000, x=40.123456, y=-74.654321, z=0.0)]  # FENCE_POLYGON_VERTEX_INCLUSION
    test_rally = [MissionItem(seq=0, command=17, x=40.123456, y=-74.654321, z=100.0)]  # MAV_CMD_NAV_LOITER_UNLIM
    
    test_cases = [
        (0, test_mission, "mission"),
        (1, test_fence, "fence"), 
        (2, test_rally, "rally")
    ]
    
    for mission_type, items, type_name in test_cases:
        try:
            # Upload some items
            upload_mission(sitl_conn, items, mission_type=mission_type)
            
            # Verify they were uploaded
            downloaded = download_mission(sitl_conn, mission_type=mission_type)
            assert len(downloaded) > 0, f"Failed to upload {type_name} items"
            
            # Clear the mission
            clear_mission(sitl_conn, mission_type=mission_type)
            
            # Verify it's now empty (post-clear download returns 0 items)
            downloaded_after = download_mission(sitl_conn, mission_type=mission_type)
            assert len(downloaded_after) == 0, f"Failed to clear {type_name} (still has {len(downloaded_after)} items)"
            
        except Exception as e:
            if mission_type > 0 and ("not supported" in str(e).lower() or "nack" in str(e).lower() or "invalid" in str(e).lower()):
                pytest.skip(f"SITL does not support mission_type={mission_type} ({type_name}): {e}")
            raise


@pytest.mark.sitl
def test_armed_check_guard(sitl_conn) -> None:
    """Test _check_not_armed against SITL (which starts disarmed) → should pass."""
    # SITL starts disarmed by default, so _check_not_armed should pass without exception
    _check_not_armed(sitl_conn)
    # If we reach here without exception, the test passed


@pytest.mark.sitl
def test_coverage_planner_sitl_acceptance(sitl_conn) -> None:
    """Test coverage planner output is accepted by SITL (no NACK)."""
    # Load a zone fixture
    zone_path = Path("zones/ne.yaml")
    if not zone_path.exists():
        pytest.skip("Zone fixture zones/ne.yaml not found")
    
    zone = load_zone_config(zone_path)
    
    # Generate waypoints using coverage planner
    waypoints = generate_waypoints(zone)
    assert len(waypoints) > 0, "Coverage planner generated no waypoints"
    
    # Convert to mission items
    mission_items = zone_to_mission(zone, waypoints)
    assert len(mission_items) > 0, "No mission items generated from waypoints"
    
    try:
        # Clear any existing mission
        clear_mission(sitl_conn, mission_type=0)
        
        # Upload the full mission - should not get NACK from SITL
        upload_mission(sitl_conn, mission_items, mission_type=0)
        
        # Verify we can download it back
        downloaded = download_mission(sitl_conn, mission_type=0)
        assert len(downloaded) == len(mission_items), f"Downloaded {len(downloaded)} items, expected {len(mission_items)}"
        
        # Verify first waypoint matches
        assert downloaded[0].command == mission_items[0].command
        assert abs(downloaded[0].x - mission_items[0].x) < 1e-6
        assert abs(downloaded[0].y - mission_items[0].y) < 1e-6
        
    finally:
        # Cleanup
        clear_mission(sitl_conn, mission_type=0)