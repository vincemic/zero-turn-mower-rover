"""Tests for zone pre-flight probe checks.

Validates fence matching, mission counting, VSLAM zone configuration,
and relocalization status checks.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from mower_rover.zone.config import ZoneConfig, LatLon, RallyPoint
from mower_rover.mavlink.mission import MissionItem
from mower_rover.probe.checks.zone import (
    check_fence_match,
    check_mission_count, 
    check_vslam_zone_match,
    check_vslam_relocalized,
    _zone_fence_match_probe,
    _zone_mission_count_probe,
    _zone_vslam_match_probe,
    _zone_vslam_relocalized_probe,
)


@pytest.fixture
def sample_zone() -> ZoneConfig:
    """Create a sample zone for testing."""
    return ZoneConfig(
        schema="zone.v1",
        zone_id="test-zone",
        name="Test Zone",
        home=LatLon(lat=40.7128, lon=-74.0060),
        rally_point=RallyPoint(lat=40.7130, lon=-74.0058),
        boundary=[
            LatLon(lat=40.7120, lon=-74.0070),
            LatLon(lat=40.7120, lon=-74.0050),
            LatLon(lat=40.7140, lon=-74.0050),
            LatLon(lat=40.7140, lon=-74.0070),
        ],
    )


@pytest.fixture
def matching_fence_items() -> list[MissionItem]:
    """Create fence items that match the sample zone boundary."""
    # These coordinates match sample_zone boundary converted to int32
    # Note: MissionItem x=lat*1e7, y=lon*1e7
    return [
        MissionItem(
            seq=0,
            frame=5,
            command=5001,
            param1=4.0,  # Vertex count for first item
            x=407120000,  # lat * 1e7: 40.7120
            y=-740070000,  # lon * 1e7: -74.0070
            mission_type=1,  # FENCE
        ),
        MissionItem(
            seq=1,
            frame=5,
            command=5001,
            param1=0.0,
            x=407120000,  # lat * 1e7: 40.7120
            y=-740050000,  # lon * 1e7: -74.0050
            mission_type=1,
        ),
        MissionItem(
            seq=2,
            frame=5,
            command=5001,
            param1=0.0,
            x=407140000,  # lat * 1e7: 40.7140
            y=-740050000,  # lon * 1e7: -74.0050
            mission_type=1,
        ),
        MissionItem(
            seq=3,
            frame=5,
            command=5001,
            param1=0.0,
            x=407140000,  # lat * 1e7: 40.7140
            y=-740070000,  # lon * 1e7: -74.0070
            mission_type=1,
        ),
    ]


def test_check_fence_match_success(sample_zone: ZoneConfig, matching_fence_items: list[MissionItem]) -> None:
    """Test successful fence matching."""
    passed, detail = check_fence_match(sample_zone, matching_fence_items)
    
    assert passed is True
    assert "4 vertices" in detail
    assert "tolerance" in detail


def test_check_fence_match_count_mismatch(sample_zone: ZoneConfig) -> None:
    """Test fence matching with wrong vertex count."""
    wrong_count_items = [
        MissionItem(seq=0, frame=5, command=5001, x=407120000, y=-740070000, mission_type=1),
        MissionItem(seq=1, frame=5, command=5001, x=407120000, y=-740050000, mission_type=1),
        # Missing 2 vertices
    ]
    
    passed, detail = check_fence_match(sample_zone, wrong_count_items)
    
    assert passed is False
    assert "count mismatch" in detail
    assert "expected 4" in detail
    assert "got 2" in detail


def test_check_fence_match_coordinate_mismatch(sample_zone: ZoneConfig) -> None:
    """Test fence matching with wrong coordinates."""
    wrong_coord_items = [
        MissionItem(seq=0, frame=5, command=5001, x=407120000, y=-740070000, mission_type=1),
        MissionItem(seq=1, frame=5, command=5001, x=407120000, y=-740050000, mission_type=1),
        MissionItem(seq=2, frame=5, command=5001, x=407140000, y=-740050000, mission_type=1),
        MissionItem(seq=3, frame=5, command=5001, x=407150000, y=-740070000, mission_type=1),  # Wrong coordinate
    ]
    
    passed, detail = check_fence_match(sample_zone, wrong_coord_items, tolerance=1e-7)
    
    assert passed is False
    assert "vertex 3 mismatch" in detail
    assert "40.7150000" in detail  # Shows the wrong coordinate


def test_check_fence_match_tolerance(sample_zone: ZoneConfig) -> None:
    """Test fence matching respects tolerance parameter."""
    # Create items with small coordinate difference
    slight_diff_items = [
        MissionItem(seq=0, frame=5, command=5001, x=407120000, y=-740070000, mission_type=1),
        MissionItem(seq=1, frame=5, command=5001, x=407120000, y=-740050000, mission_type=1),
        MissionItem(seq=2, frame=5, command=5001, x=407140000, y=-740050000, mission_type=1),
        MissionItem(seq=3, frame=5, command=5001, x=407140005, y=-740070000, mission_type=1),  # +5e-7 degrees diff
    ]
    
    # Should fail with tight tolerance
    passed, _ = check_fence_match(sample_zone, slight_diff_items, tolerance=1e-8)
    assert passed is False
    
    # Should pass with looser tolerance
    passed, _ = check_fence_match(sample_zone, slight_diff_items, tolerance=1e-6)
    assert passed is True


def test_check_mission_count_within_tolerance() -> None:
    """Test mission count check passes within tolerance."""
    passed, detail = check_mission_count(expected=100, actual=98, tolerance=5)
    
    assert passed is True
    assert "98 items" in detail
    assert "expected ~100" in detail


def test_check_mission_count_outside_tolerance() -> None:
    """Test mission count check fails outside tolerance."""
    passed, detail = check_mission_count(expected=100, actual=85, tolerance=5)
    
    assert passed is False
    assert "got 85" in detail
    assert "expected 100" in detail
    assert "(±5)" in detail


def test_check_mission_count_exact_boundary() -> None:
    """Test mission count at tolerance boundary."""
    # Exactly at tolerance boundary should pass
    passed, _ = check_mission_count(expected=100, actual=95, tolerance=5)
    assert passed is True
    
    passed, _ = check_mission_count(expected=100, actual=105, tolerance=5) 
    assert passed is True
    
    # Just outside tolerance boundary should fail
    passed, _ = check_mission_count(expected=100, actual=94, tolerance=5)
    assert passed is False
    
    passed, _ = check_mission_count(expected=100, actual=106, tolerance=5)
    assert passed is False


def test_check_vslam_zone_match_success() -> None:
    """Test VSLAM zone matching with correct database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        # Create vslam config with matching zone
        vslam_config = {
            "database_path": "/var/lib/mower/zones/test-zone/rtabmap.db",
            "mode": "localization"
        }
        
        config_path = sysroot / "etc/mower/vslam.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.dump(vslam_config))
        
        passed, detail = check_vslam_zone_match(sysroot, "test-zone")
        
        assert passed is True
        assert "matches zone test-zone" in detail
        assert "/zones/test-zone/" in detail


def test_check_vslam_zone_match_wrong_zone() -> None:
    """Test VSLAM zone matching with wrong database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        # Create vslam config with different zone
        vslam_config = {
            "database_path": "/var/lib/mower/zones/other-zone/rtabmap.db"
        }
        
        config_path = sysroot / "etc/mower/vslam.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.dump(vslam_config))
        
        passed, detail = check_vslam_zone_match(sysroot, "test-zone")
        
        assert passed is False
        assert "does not contain" in detail
        assert "zones/test-zone/" in detail


def test_check_vslam_zone_match_missing_config() -> None:
    """Test VSLAM zone matching with missing config file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        passed, detail = check_vslam_zone_match(sysroot, "test-zone")
        
        assert passed is False
        assert "config file not found" in detail


def test_check_vslam_relocalized_success() -> None:
    """Test VSLAM relocalization check with good confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        # Create status file with good confidence
        status_data = {
            "confidence": 2.5,
            "last_update": "2024-01-15T10:30:00Z"
        }
        
        status_path = sysroot / "run/mower/vslam-status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status_data))
        
        passed, detail = check_vslam_relocalized(sysroot, min_confidence=1.0)
        
        assert passed is True
        assert "relocalized" in detail
        assert "confidence=2.50" in detail


def test_check_vslam_relocalized_low_confidence() -> None:
    """Test VSLAM relocalization check with low confidence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        # Create status file with low confidence
        status_data = {"confidence": 0.3}
        
        status_path = sysroot / "run/mower/vslam-status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status_data))
        
        passed, detail = check_vslam_relocalized(sysroot, min_confidence=1.0)
        
        assert passed is False
        assert "not relocalized" in detail
        assert "confidence=0.30" in detail
        assert "need≥1" in detail


def test_check_vslam_relocalized_missing_status() -> None:
    """Test VSLAM relocalization check with missing status file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        passed, detail = check_vslam_relocalized(sysroot)
        
        assert passed is False
        assert "status file not found" in detail


def test_zone_fence_match_probe_missing_active_zone() -> None:
    """Test registered fence match probe with missing active zone."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        passed, detail = _zone_fence_match_probe(sysroot)
        
        assert passed is False
        assert "No active zone configuration found" in detail


def test_zone_mission_count_probe_missing_cache() -> None:
    """Test registered mission count probe with missing cache files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        passed, detail = _zone_mission_count_probe(sysroot)
        
        assert passed is False
        assert "No cached mission plan found" in detail


def test_zone_vslam_match_probe_missing_active_zone() -> None:
    """Test registered VSLAM match probe with missing active zone."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        passed, detail = _zone_vslam_match_probe(sysroot)
        
        assert passed is False
        assert "No active zone configuration found" in detail


def test_zone_vslam_relocalized_probe_delegates() -> None:
    """Test registered VSLAM relocalized probe delegates to core function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sysroot = Path(tmpdir)
        
        # This should call the core function and get the "missing status file" result
        passed, detail = _zone_vslam_relocalized_probe(sysroot)
        
        assert passed is False
        assert "status file not found" in detail