"""Tests for zone GeoJSON export functionality.

Validates RFC 7946 compliance, coordinate ordering, and feature properties
for single-zone and multi-zone GeoJSON exports.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from mower_rover.zone.config import (
    ZoneConfig, LatLon, RallyPoint, ExclusionZone, 
    CoverageParams, MissionCommands, SlamOverrides, OutputConfig
)
from mower_rover.zone.geojson import export_zone_geojson, export_multi_zone_geojson


@pytest.fixture
def sample_zone() -> ZoneConfig:
    """Create a sample zone for testing."""
    return ZoneConfig(
        schema="zone.v1",
        zone_id="test-zone",
        name="Test Zone",
        description="A test zone for unit tests",
        home=LatLon(lat=40.7128, lon=-74.0060),  # NYC
        rally_point=RallyPoint(lat=40.7130, lon=-74.0058, description="Test rally"),
        boundary=[
            LatLon(lat=40.7120, lon=-74.0070),
            LatLon(lat=40.7120, lon=-74.0050), 
            LatLon(lat=40.7140, lon=-74.0050),
            LatLon(lat=40.7140, lon=-74.0070),
        ],
        exclusion_zones=[
            ExclusionZone(
                name="tree",
                buffer_m=2.0,
                polygon=[
                    LatLon(lat=40.7125, lon=-74.0065),
                    LatLon(lat=40.7125, lon=-74.0055),
                    LatLon(lat=40.7135, lon=-74.0055),
                    LatLon(lat=40.7135, lon=-74.0065),
                ]
            )
        ],
        coverage=CoverageParams(pattern="boustrophedon", mow_speed_mps=1.5),
        commands=MissionCommands(fence_enable=True),
        slam=SlamOverrides(mode="localization"),
        output=OutputConfig(),
    )


@pytest.fixture  
def sample_waypoints() -> list[LatLon]:
    """Create sample waypoints for testing."""
    return [
        LatLon(lat=40.7122, lon=-74.0068),
        LatLon(lat=40.7124, lon=-74.0068),
        LatLon(lat=40.7126, lon=-74.0068),
        LatLon(lat=40.7128, lon=-74.0068),
    ]


def test_export_zone_geojson_structure(sample_zone: ZoneConfig, sample_waypoints: list[LatLon]) -> None:
    """Test that exported GeoJSON has correct structure."""
    geojson = export_zone_geojson(sample_zone, sample_waypoints)
    
    # Check top-level structure
    assert geojson["type"] == "FeatureCollection"
    assert "properties" in geojson
    assert "features" in geojson
    
    # Check collection properties
    props = geojson["properties"]
    assert props["zone_id"] == "test-zone"
    assert props["zone_name"] == "Test Zone"
    assert props["description"] == "A test zone for unit tests"
    
    # Check feature count (boundary + exclusion + home + rally + coverage_path)
    assert len(geojson["features"]) == 5


def test_export_zone_geojson_coordinate_order(sample_zone: ZoneConfig, sample_waypoints: list[LatLon]) -> None:
    """Test that coordinates follow RFC 7946 [longitude, latitude] order."""
    geojson = export_zone_geojson(sample_zone, sample_waypoints)
    
    # Find boundary feature
    boundary_feature = next(
        f for f in geojson["features"] 
        if f["properties"]["feature_type"] == "boundary"
    )
    
    # Check coordinate ordering [lon, lat] not [lat, lon]
    coords = boundary_feature["geometry"]["coordinates"][0]  # First ring
    first_point = coords[0]
    
    # First boundary point: LatLon(lat=40.7120, lon=-74.0070)
    # Should be exported as [-74.0070, 40.7120]
    assert first_point == [-74.0070, 40.7120]
    
    # Check that ring is closed (first == last)
    assert coords[0] == coords[-1]


def test_export_zone_geojson_feature_types(sample_zone: ZoneConfig, sample_waypoints: list[LatLon]) -> None:
    """Test that all expected feature types are present with correct properties."""
    geojson = export_zone_geojson(sample_zone, sample_waypoints)
    
    feature_types = {f["properties"]["feature_type"] for f in geojson["features"]}
    expected_types = {"boundary", "exclusion", "home", "rally", "coverage_path"}
    assert feature_types == expected_types
    
    # Test boundary feature
    boundary = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "boundary")
    assert boundary["geometry"]["type"] == "Polygon"
    assert boundary["properties"]["zone_id"] == "test-zone"
    assert boundary["properties"]["name"] == "Test Zone"
    
    # Test exclusion feature
    exclusion = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "exclusion")
    assert exclusion["geometry"]["type"] == "Polygon"
    assert exclusion["properties"]["zone_id"] == "test-zone"
    assert exclusion["properties"]["name"] == "tree"
    assert exclusion["properties"]["buffer_m"] == 2.0
    
    # Test home feature
    home = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "home")
    assert home["geometry"]["type"] == "Point"
    assert home["geometry"]["coordinates"] == [-74.0060, 40.7128]
    
    # Test rally feature
    rally = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "rally")
    assert rally["geometry"]["type"] == "Point"
    assert rally["geometry"]["coordinates"] == [-74.0058, 40.7130]
    assert rally["properties"]["description"] == "Test rally"
    
    # Test coverage path feature
    path = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "coverage_path")
    assert path["geometry"]["type"] == "LineString"
    assert path["properties"]["waypoint_count"] == 4
    assert path["properties"]["pattern"] == "boustrophedon"
    assert path["properties"]["mow_speed_mps"] == 1.5


def test_export_zone_geojson_no_waypoints(sample_zone: ZoneConfig) -> None:
    """Test export without waypoints (no coverage path)."""
    geojson = export_zone_geojson(sample_zone, [])
    
    feature_types = {f["properties"]["feature_type"] for f in geojson["features"]}
    # Should have all features except coverage_path
    expected_types = {"boundary", "exclusion", "home", "rally"}
    assert feature_types == expected_types
    assert len(geojson["features"]) == 4


def test_export_zone_geojson_no_exclusions(sample_waypoints: list[LatLon]) -> None:
    """Test export with zone that has no exclusion zones."""
    zone = ZoneConfig(
        schema="zone.v1",
        zone_id="simple-zone",
        name="Simple Zone",
        home=LatLon(lat=40.7128, lon=-74.0060),
        rally_point=RallyPoint(lat=40.7130, lon=-74.0058),
        boundary=[
            LatLon(lat=40.7120, lon=-74.0070),
            LatLon(lat=40.7120, lon=-74.0050),
            LatLon(lat=40.7140, lon=-74.0050),
            LatLon(lat=40.7140, lon=-74.0070),
        ],
        exclusion_zones=[],  # No exclusions
    )
    
    geojson = export_zone_geojson(zone, sample_waypoints)
    
    feature_types = {f["properties"]["feature_type"] for f in geojson["features"]}
    # Should not have exclusion feature
    expected_types = {"boundary", "home", "rally", "coverage_path"}
    assert feature_types == expected_types
    assert len(geojson["features"]) == 4


def test_export_multi_zone_geojson(sample_zone: ZoneConfig) -> None:
    """Test multi-zone GeoJSON export."""
    # Create second zone
    zone2 = ZoneConfig(
        schema="zone.v1",
        zone_id="zone-2", 
        name="Second Zone",
        home=LatLon(lat=40.8128, lon=-74.0160),
        rally_point=RallyPoint(lat=40.8130, lon=-74.0158),
        boundary=[
            LatLon(lat=40.8120, lon=-74.0170),
            LatLon(lat=40.8120, lon=-74.0150),
            LatLon(lat=40.8140, lon=-74.0150),
            LatLon(lat=40.8140, lon=-74.0170),
        ],
    )
    
    zones = [sample_zone, zone2]
    geojson = export_multi_zone_geojson(zones)
    
    # Check collection properties
    assert geojson["type"] == "FeatureCollection"
    assert geojson["properties"]["zone_count"] == 2
    assert geojson["properties"]["export_type"] == "multi_zone"
    assert set(geojson["properties"]["zone_names"]) == {"Test Zone", "Second Zone"}
    
    # Check that both zones are represented
    zone_ids = {f["properties"]["zone_id"] for f in geojson["features"]}
    assert zone_ids == {"test-zone", "zone-2"}
    
    # Check that coverage paths are excluded from multi-zone export
    feature_types = {f["properties"]["feature_type"] for f in geojson["features"]}
    assert "coverage_path" not in feature_types
    
    # Should have: 2 boundaries + 1 exclusion (from sample_zone) + 2 homes + 2 rallies = 7
    expected_feature_count = 7
    assert len(geojson["features"]) == expected_feature_count


def test_polygon_ring_closure(sample_zone: ZoneConfig) -> None:
    """Test that polygon rings are properly closed."""
    geojson = export_zone_geojson(sample_zone, [])
    
    # Check boundary polygon
    boundary = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "boundary")
    coords = boundary["geometry"]["coordinates"][0]
    assert coords[0] == coords[-1], "Boundary polygon ring should be closed"
    
    # Check exclusion polygon
    exclusion = next(f for f in geojson["features"] if f["properties"]["feature_type"] == "exclusion")
    coords = exclusion["geometry"]["coordinates"][0]
    assert coords[0] == coords[-1], "Exclusion polygon ring should be closed"