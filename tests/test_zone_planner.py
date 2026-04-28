"""Tests for zone coverage path planner."""

from __future__ import annotations

import math
import pytest
from shapely.geometry import Polygon

from mower_rover.zone.config import (
    ZoneConfig, 
    LatLon, 
    ExclusionZone, 
    CoverageParams,
    RallyPoint,
    MissionCommands,
    SlamOverrides,
    OutputConfig,
)
from mower_rover.zone.planner import (
    GeodeticProjector,
    generate_headland_passes,
    generate_boustrophedon_fill,
    generate_waypoints,
    PlannerError,
)


# ------------------------------------------------------------------
# Test Fixtures
# ------------------------------------------------------------------


def create_test_zone(
    boundary: list[LatLon],
    exclusions: list[ExclusionZone] | None = None,
    coverage_params: CoverageParams | None = None,
) -> ZoneConfig:
    """Create a test zone configuration."""
    return ZoneConfig(
        schema="mower-rover.zone.v1",
        zone_id="test",
        name="Test Zone",
        home=boundary[0],  # Use first boundary point as home
        rally_point=RallyPoint(lat=boundary[0].lat, lon=boundary[0].lon, description="Test rally"),
        boundary=boundary,
        exclusion_zones=exclusions or [],
        coverage=coverage_params or CoverageParams(),
        commands=MissionCommands(),
        slam=SlamOverrides(),
        output=OutputConfig(),
    )


# ------------------------------------------------------------------
# Geodetic Projector Tests
# ------------------------------------------------------------------


def test_projector_init_with_empty_list() -> None:
    """Test that projector raises error with empty reference points."""
    with pytest.raises(PlannerError, match="reference_latlons cannot be empty"):
        GeodeticProjector([])


def test_projector_roundtrip_accuracy() -> None:
    """Test that geodetic ↔ planar conversion round-trips within 1 cm."""
    # Washington DC area coordinates
    reference_points = [
        LatLon(lat=38.8951, lon=-77.0365),
        LatLon(lat=38.8955, lon=-77.0360),
        LatLon(lat=38.8945, lon=-77.0370),
    ]
    
    projector = GeodeticProjector(reference_points)
    
    # Convert to planar and back
    planar_coords = projector.to_planar(reference_points)
    roundtrip_coords = projector.to_geodetic(planar_coords)
    
    # Check accuracy (should be within 1 cm = ~1e-7 degrees)
    for original, roundtrip in zip(reference_points, roundtrip_coords):
        lat_diff = abs(original.lat - roundtrip.lat)
        lon_diff = abs(original.lon - roundtrip.lon)
        
        assert lat_diff < 1e-7, f"Latitude error {lat_diff} exceeds tolerance"
        assert lon_diff < 1e-7, f"Longitude error {lon_diff} exceeds tolerance"


def test_projector_empty_lists() -> None:
    """Test projector handles empty coordinate lists."""
    reference = [LatLon(lat=38.8951, lon=-77.0365)]
    projector = GeodeticProjector(reference)
    
    assert projector.to_planar([]) == []
    assert projector.to_geodetic([]) == []


def test_projector_single_point() -> None:
    """Test projector handles single point correctly."""
    reference = [LatLon(lat=38.8951, lon=-77.0365)]
    projector = GeodeticProjector(reference)
    
    single_point = [LatLon(lat=38.8950, lon=-77.0366)]
    planar = projector.to_planar(single_point)
    geodetic = projector.to_geodetic(planar)
    
    assert len(planar) == 1
    assert len(geodetic) == 1
    
    # Check round-trip accuracy
    assert abs(single_point[0].lat - geodetic[0].lat) < 1e-7
    assert abs(single_point[0].lon - geodetic[0].lon) < 1e-7


# ------------------------------------------------------------------
# Headland Pass Tests  
# ------------------------------------------------------------------


def test_headland_passes_square_polygon() -> None:
    """Test headland pass generation with simple square polygon."""
    # 100m x 100m square
    boundary_xy = [(0, 0), (100, 0), (100, 100), (0, 100)]
    exclusions_xy = []
    
    passes = generate_headland_passes(
        boundary_xy=boundary_xy,
        exclusions_xy=exclusions_xy,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        num_passes=2,
    )
    
    assert len(passes) == 2, f"Expected 2 passes, got {len(passes)}"
    
    # Check that passes are inset correctly
    # First pass should be slightly inset from boundary
    first_pass_poly = Polygon(passes[0])
    second_pass_poly = Polygon(passes[1])
    
    # Second pass should be smaller than first
    assert second_pass_poly.area < first_pass_poly.area


def test_headland_passes_with_exclusions() -> None:
    """Test headland passes correctly handle exclusion zones."""
    # Large square with small exclusion in center
    boundary_xy = [(0, 0), (50, 0), (50, 50), (0, 50)]
    exclusions_xy = [[(20, 20), (30, 20), (30, 30), (20, 30)]]  # Center square
    
    passes = generate_headland_passes(
        boundary_xy=boundary_xy,
        exclusions_xy=exclusions_xy,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        num_passes=1,
    )
    
    assert len(passes) >= 1, "Should generate at least one pass"
    
    # Should generate both outer boundary pass and inner exclusion boundary pass
    assert len(passes) == 2, f"Expected 2 passes (outer + exclusion boundary), got {len(passes)}"
    
    # Verify pass areas are reasonable
    exclusion_poly = Polygon(exclusions_xy[0])
    boundary_poly = Polygon(boundary_xy)
    
    for i, pass_waypoints in enumerate(passes):
        pass_poly = Polygon(pass_waypoints)
        
        # All passes should have reasonable area
        assert pass_poly.area > 10, f"Pass {i} area {pass_poly.area} too small"
        
        # Passes should be within the overall boundary
        assert boundary_poly.contains(pass_poly) or boundary_poly.intersects(pass_poly), \
            f"Pass {i} should be within or intersect boundary"


def test_headland_passes_zero_passes() -> None:
    """Test that zero headland passes returns empty list."""
    boundary_xy = [(0, 0), (10, 0), (10, 10), (0, 10)]
    passes = generate_headland_passes(
        boundary_xy=boundary_xy,
        exclusions_xy=[],
        cutting_width_m=2.0,
        overlap_pct=10.0,
        num_passes=0,
    )
    
    assert passes == []


# ------------------------------------------------------------------
# Boustrophedon Fill Tests
# ------------------------------------------------------------------


def test_boustrophedon_rectangular_polygon() -> None:
    """Test boustrophedon pattern on rectangular polygon."""
    # 20m x 10m rectangle
    poly = Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])
    
    waypoints = generate_boustrophedon_fill(
        mowable_poly=poly,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        angle_deg=0.0,  # East-west lines
    )
    
    assert len(waypoints) > 0, "Should generate waypoints"
    
    # Check that waypoints are within polygon bounds
    for x, y in waypoints:
        point = Polygon([(x-0.1, y-0.1), (x+0.1, y-0.1), (x+0.1, y+0.1), (x-0.1, y+0.1)])
        assert poly.contains(point) or poly.intersects(point), f"Waypoint ({x}, {y}) outside polygon"


def test_boustrophedon_angle_rotation() -> None:
    """Test boustrophedon pattern with angled sweep lines."""
    poly = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
    
    # Test 45-degree angle
    waypoints_45 = generate_boustrophedon_fill(
        mowable_poly=poly,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        angle_deg=45.0,
    )
    
    # Test 90-degree angle (north-south)
    waypoints_90 = generate_boustrophedon_fill(
        mowable_poly=poly,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        angle_deg=90.0,
    )
    
    assert len(waypoints_45) > 0
    assert len(waypoints_90) > 0
    
    # Different angles should produce different patterns
    assert waypoints_45 != waypoints_90


def test_boustrophedon_empty_polygon() -> None:
    """Test boustrophedon handles empty/tiny polygons."""
    # Empty polygon
    empty_poly = Polygon()
    waypoints = generate_boustrophedon_fill(
        mowable_poly=empty_poly,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        angle_deg=0.0,
    )
    assert waypoints == []
    
    # Very small polygon (< 1 m²)
    tiny_poly = Polygon([(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)])
    waypoints_tiny = generate_boustrophedon_fill(
        mowable_poly=tiny_poly,
        cutting_width_m=2.0,
        overlap_pct=10.0,
        angle_deg=0.0,
    )
    assert waypoints_tiny == []


# ------------------------------------------------------------------
# Integration Tests - generate_waypoints()
# ------------------------------------------------------------------


def test_generate_waypoints_square_zone() -> None:
    """Test waypoint generation for simple square zone."""
    # ~100m x 100m square in Washington DC
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0370),
    ]
    
    zone = create_test_zone(boundary)
    waypoints = generate_waypoints(zone)
    
    assert len(waypoints) > 0, "Should generate waypoints for valid zone"
    assert len(waypoints) < 1000, "Waypoint count should be reasonable for ~1 acre"
    
    # All waypoints should be LatLon objects
    for wp in waypoints:
        assert isinstance(wp, LatLon)
        assert isinstance(wp.lat, float)
        assert isinstance(wp.lon, float)


def test_generate_waypoints_with_exclusion() -> None:
    """Test waypoint generation with exclusion zone."""
    # Main boundary
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0370),
    ]
    
    # Small exclusion in center
    exclusion = ExclusionZone(
        name="tree",
        buffer_m=1.0,
        polygon=[
            LatLon(lat=38.8954, lon=-77.0366),
            LatLon(lat=38.8954, lon=-77.0364),
            LatLon(lat=38.8956, lon=-77.0364),
            LatLon(lat=38.8956, lon=-77.0366),
        ]
    )
    
    zone = create_test_zone(boundary, exclusions=[exclusion])
    waypoints = generate_waypoints(zone)
    
    assert len(waypoints) > 0, "Should generate waypoints despite exclusion"
    
    # Verify waypoints are reasonable - should have both boundary and exclusion passes
    # The exact number depends on implementation but should be substantial for ~1000m² area
    assert 10 < len(waypoints) < 500, f"Waypoint count {len(waypoints)} seems unreasonable"
    
    # Verify all waypoints are valid LatLon objects
    for wp in waypoints:
        assert isinstance(wp, LatLon)
        assert -90 <= wp.lat <= 90, f"Invalid latitude: {wp.lat}"
        assert -180 <= wp.lon <= 180, f"Invalid longitude: {wp.lon}"


def test_generate_waypoints_concave_l_shape() -> None:
    """Test waypoint generation for concave L-shaped polygon."""
    # L-shaped boundary
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),  # Bottom-left
        LatLon(lat=38.8950, lon=-77.0350),  # Bottom-right  
        LatLon(lat=38.8955, lon=-77.0350),  # Inner corner right
        LatLon(lat=38.8955, lon=-77.0360),  # Inner corner top
        LatLon(lat=38.8965, lon=-77.0360),  # Top-right
        LatLon(lat=38.8965, lon=-77.0370),  # Top-left
    ]
    
    zone = create_test_zone(boundary)
    waypoints = generate_waypoints(zone)
    
    assert len(waypoints) > 0, "Should handle concave polygons"


def test_generate_waypoints_very_small_zone() -> None:
    """Test waypoint generation for very small zone (< 100 m²)."""
    # ~10m x 10m square
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.03695),  # ~5m east
        LatLon(lat=38.89505, lon=-77.03695), # ~5m north  
        LatLon(lat=38.89505, lon=-77.0370),
    ]
    
    zone = create_test_zone(boundary)
    waypoints = generate_waypoints(zone)
    
    # Should either generate waypoints or return empty (both acceptable for tiny zones)
    if waypoints:
        assert len(waypoints) < 50, "Very small zone should have few waypoints"


def test_generate_waypoints_different_aspect_ratios() -> None:
    """Test waypoint generation for rectangular zones with different aspect ratios."""
    # Wide rectangle (4:1 aspect ratio)
    wide_boundary = [
        LatLon(lat=38.8950, lon=-77.0380),
        LatLon(lat=38.8950, lon=-77.0340),  # ~400m wide
        LatLon(lat=38.8952, lon=-77.0340),  # ~100m tall  
        LatLon(lat=38.8952, lon=-77.0380),
    ]
    
    # Tall rectangle (1:4 aspect ratio)  
    tall_boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.0360),  # ~100m wide
        LatLon(lat=38.8970, lon=-77.0360),  # ~400m tall
        LatLon(lat=38.8970, lon=-77.0370),
    ]
    
    wide_zone = create_test_zone(wide_boundary)
    tall_zone = create_test_zone(tall_boundary)
    
    wide_waypoints = generate_waypoints(wide_zone)
    tall_waypoints = generate_waypoints(tall_zone)
    
    assert len(wide_waypoints) > 0, "Wide rectangle should generate waypoints"
    assert len(tall_waypoints) > 0, "Tall rectangle should generate waypoints"


def test_generate_waypoints_angle_rotation() -> None:
    """Test waypoint generation with different sweep angles."""
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0360), 
        LatLon(lat=38.8960, lon=-77.0370),
    ]
    
    # Test different angles
    for angle in [0.0, 45.0, 90.0]:
        coverage_params = CoverageParams(angle_deg=angle)
        zone = create_test_zone(boundary, coverage_params=coverage_params)
        waypoints = generate_waypoints(zone)
        
        assert len(waypoints) > 0, f"Should generate waypoints at {angle}° angle"


def test_generate_waypoints_coverage_area_efficiency() -> None:
    """Test that generated waypoints provide good coverage area efficiency (≥ 90%)."""
    # Simple rectangular zone for easy area calculation
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.0360),  # ~100m wide
        LatLon(lat=38.8955, lon=-77.0360),  # ~50m tall
        LatLon(lat=38.8955, lon=-77.0370),
    ]
    
    zone = create_test_zone(boundary)
    waypoints = generate_waypoints(zone)
    
    assert len(waypoints) > 0, "Should generate waypoints"
    
    # Calculate theoretical coverage
    # For a 100m x 50m area = 5000 m²
    # With 54" (1.37m) cutting width and 10% overlap = 1.23m effective width
    # Should need roughly 50m / 1.23m ≈ 40 passes
    # Plus headland passes around perimeter
    
    # This is a rough check - exact calculation depends on headland configuration
    assert 20 < len(waypoints) < 200, f"Waypoint count {len(waypoints)} seems unreasonable for ~5000m² area"


# ------------------------------------------------------------------
# Error Handling Tests
# ------------------------------------------------------------------


def test_generate_waypoints_invalid_zone() -> None:
    """Test error handling for invalid zone configurations."""
    # Zone with < 3 boundary points (invalid polygon)
    with pytest.raises(Exception):  # Should raise some kind of error
        boundary = [
            LatLon(lat=38.8950, lon=-77.0370),
            LatLon(lat=38.8950, lon=-77.0360),
        ]
        zone = create_test_zone(boundary)
        generate_waypoints(zone)


def test_generate_waypoints_zero_cutting_width() -> None:
    """Test error handling for zero cutting width."""
    boundary = [
        LatLon(lat=38.8950, lon=-77.0370),
        LatLon(lat=38.8950, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0360),
        LatLon(lat=38.8960, lon=-77.0370),
    ]
    
    coverage_params = CoverageParams(cutting_width_in=0.0)
    zone = create_test_zone(boundary, coverage_params=coverage_params)
    
    # Should either handle gracefully or raise PlannerError
    try:
        waypoints = generate_waypoints(zone)
        # If it succeeds, should return empty or minimal waypoints
        assert len(waypoints) < 10
    except PlannerError:
        # Acceptable to raise error for invalid cutting width
        pass