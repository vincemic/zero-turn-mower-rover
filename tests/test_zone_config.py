"""Tests for zone configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from mower_rover.zone.config import (
    ZoneConfig,
    ZoneConfigError,
    LatLon,
    RallyPoint,
    ExclusionZone,
    CoverageParams,
    MissionCommands,
    SlamOverrides,
    OutputConfig,
    load_zone_config,
    validate_zone_config,
    load_all_zones,
)


def test_zone_config_dataclasses_frozen() -> None:
    """Test that all dataclasses are properly frozen."""
    lat_lon = LatLon(lat=38.0, lon=-77.0)
    with pytest.raises(AttributeError):
        lat_lon.lat = 39.0  # type: ignore
    
    rally = RallyPoint(lat=38.0, lon=-77.0, description="test")
    with pytest.raises(AttributeError):
        rally.description = "changed"  # type: ignore
    
    zone_cfg = ZoneConfig(
        schema="mower-rover.zone.v1",
        zone_id="test",
        name="Test Zone",
        home=LatLon(lat=38.0, lon=-77.0),
        rally_point=RallyPoint(lat=38.0, lon=-77.0),
        boundary=[LatLon(lat=38.0, lon=-77.0), LatLon(lat=38.1, lon=-77.0), LatLon(lat=38.1, lon=-77.1)],
    )
    with pytest.raises(AttributeError):
        zone_cfg.name = "changed"  # type: ignore


def test_load_valid_zone_yaml(tmp_path: Path) -> None:
    """Test loading a valid zone YAML file."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "test_zone",
        "name": "Test Zone",
        "description": "A test zone",
        "home": {"lat": 38.89510, "lon": -77.03660},
        "rally_point": {
            "lat": 38.89505,
            "lon": -77.03655,
            "description": "Test rally point"
        },
        "boundary": [
            [38.89510, -77.03660],
            [38.89510, -77.03400],
            [38.89350, -77.03400],
            [38.89350, -77.03660]
        ],
        "exclusion_zones": [
            {
                "name": "test_exclusion",
                "buffer_m": 1.0,
                "polygon": [
                    [38.89480, -77.03550],
                    [38.89480, -77.03520],
                    [38.89460, -77.03520],
                    [38.89460, -77.03550]
                ]
            }
        ],
        "coverage": {
            "pattern": "boustrophedon",
            "cutting_width_in": 54.0,
            "overlap_pct": 10.0,
            "angle_deg": 0.0,
            "headland_passes": 2,
            "mow_speed_mps": 2.0,
            "turn_speed_mps": 1.0
        },
        "commands": {
            "fence_enable": True,
            "resume_dist_m": 2.5,
            "blade_engage": True
        },
        "slam": {
            "mode": "localization"
        },
        "output": {
            "waypoints_file": "test.waypoints",
            "geojson_file": "test.geojson"
        }
    }
    
    yaml_file = tmp_path / "test_zone.yaml"
    with yaml_file.open("w") as f:
        yaml.dump(zone_yaml, f)
    
    cfg = load_zone_config(yaml_file)
    
    assert cfg.schema == "mower-rover.zone.v1"
    assert cfg.zone_id == "test_zone"
    assert cfg.name == "Test Zone"
    assert cfg.description == "A test zone"
    assert cfg.home.lat == 38.89510
    assert cfg.home.lon == -77.03660
    assert cfg.rally_point.lat == 38.89505
    assert cfg.rally_point.description == "Test rally point"
    assert len(cfg.boundary) == 4
    assert len(cfg.exclusion_zones) == 1
    assert cfg.exclusion_zones[0].name == "test_exclusion"
    assert cfg.coverage.cutting_width_in == 54.0
    assert cfg.commands.fence_enable is True
    assert cfg.slam.mode == "localization"
    assert cfg.output.waypoints_file == "test.waypoints"


def test_load_zone_with_minimal_fields(tmp_path: Path) -> None:
    """Test loading zone with only required fields."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "minimal",
        "name": "Minimal Zone",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [
            [38.89510, -77.03660],
            [38.89510, -77.03400],
            [38.89350, -77.03400]
        ]
    }
    
    yaml_file = tmp_path / "minimal.yaml"
    with yaml_file.open("w") as f:
        yaml.dump(zone_yaml, f)
    
    cfg = load_zone_config(yaml_file)
    
    assert cfg.zone_id == "minimal"
    assert cfg.description == ""  # Default value
    assert len(cfg.exclusion_zones) == 0  # Default empty list
    assert cfg.coverage.pattern == "boustrophedon"  # Default values
    assert cfg.commands.fence_enable is True  # Default values


def test_load_zone_missing_required_field(tmp_path: Path) -> None:
    """Test that missing required fields raise ZoneConfigError."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "incomplete",
        # Missing required 'name' field
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]]
    }
    
    yaml_file = tmp_path / "incomplete.yaml"
    with yaml_file.open("w") as f:
        yaml.dump(zone_yaml, f)
    
    with pytest.raises(ZoneConfigError, match="missing required field: name"):
        load_zone_config(yaml_file)


def test_load_zone_invalid_zone_id(tmp_path: Path) -> None:
    """Test that invalid zone_id raises ZoneConfigError."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "Invalid-Zone-ID-With-Capitals",  # Invalid: starts with capital
        "name": "Test Zone",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]]
    }
    
    yaml_file = tmp_path / "invalid_id.yaml"
    with yaml_file.open("w") as f:
        yaml.dump(zone_yaml, f)
    
    with pytest.raises(ZoneConfigError, match="zone_id: must match"):
        load_zone_config(yaml_file)


def test_load_zone_boundary_too_few_vertices(tmp_path: Path) -> None:
    """Test that boundary with < 3 vertices raises ZoneConfigError."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "small_boundary",
        "name": "Test Zone",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [
            [38.89510, -77.03660],
            [38.89510, -77.03400]  # Only 2 vertices
        ]
    }
    
    yaml_file = tmp_path / "small_boundary.yaml"
    with yaml_file.open("w") as f:
        yaml.dump(zone_yaml, f)
    
    with pytest.raises(ZoneConfigError, match="boundary: must have at least 3 vertices"):
        load_zone_config(yaml_file)


def test_load_zone_invalid_coverage_params(tmp_path: Path) -> None:
    """Test that invalid coverage parameters raise ZoneConfigError."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "bad_coverage",
        "name": "Test Zone",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]],
        "coverage": {
            "cutting_width_in": -5.0,  # Invalid: negative
            "overlap_pct": 75,  # Invalid: > 50
            "mow_speed_mps": 0  # Invalid: <= 0
        }
    }
    
    yaml_file = tmp_path / "bad_coverage.yaml"
    with yaml_file.open("w") as f:
        yaml.dump(zone_yaml, f)
    
    with pytest.raises(ZoneConfigError, match="coverage.cutting_width_in: must be > 0"):
        load_zone_config(yaml_file)


def test_load_zone_file_not_found() -> None:
    """Test that missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_zone_config(Path("/does/not/exist.yaml"))


def test_load_zone_invalid_yaml(tmp_path: Path) -> None:
    """Test that malformed YAML raises ZoneConfigError."""
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text("invalid: yaml: content: [unclosed")
    
    with pytest.raises(ZoneConfigError, match="Invalid YAML"):
        load_zone_config(yaml_file)


def test_load_zone_empty_yaml(tmp_path: Path) -> None:
    """Test that empty YAML raises ZoneConfigError."""
    yaml_file = tmp_path / "empty.yaml"
    yaml_file.write_text("")
    
    with pytest.raises(ZoneConfigError, match="Empty YAML file"):
        load_zone_config(yaml_file)


def test_validate_zone_config_valid() -> None:
    """Test validation of a valid zone config."""
    cfg = ZoneConfig(
        schema="mower-rover.zone.v1",
        zone_id="valid_zone",
        name="Valid Zone",
        home=LatLon(lat=38.89510, lon=-77.03660),
        rally_point=RallyPoint(lat=38.89505, lon=-77.03655),
        boundary=[
            LatLon(lat=38.89510, lon=-77.03660),
            LatLon(lat=38.89510, lon=-77.03400),
            LatLon(lat=38.89350, lon=-77.03400),
            LatLon(lat=38.89350, lon=-77.03660)
        ]
    )
    
    issues = validate_zone_config(cfg)
    # Should have no ERROR issues (may have some WARNs)
    error_issues = [issue for issue in issues if issue[0] == "ERROR"]
    assert len(error_issues) == 0


def test_validate_zone_config_invalid_lat_lon() -> None:
    """Test validation catches invalid lat/lon values."""
    cfg = ZoneConfig(
        schema="mower-rover.zone.v1",
        zone_id="invalid_coords",
        name="Invalid Coords",
        home=LatLon(lat=95.0, lon=-200.0),  # Invalid: lat > 90, lon < -180
        rally_point=RallyPoint(lat=38.89505, lon=-77.03655),
        boundary=[
            LatLon(lat=38.89510, lon=-77.03660),
            LatLon(lat=38.89510, lon=-77.03400),
            LatLon(lat=38.89350, lon=-77.03400)
        ]
    )
    
    issues = validate_zone_config(cfg)
    error_issues = [issue for issue in issues if issue[0] == "ERROR"]
    
    # Should catch both invalid lat and lon
    lat_errors = [issue for issue in error_issues if "lat: must be -90 to 90" in issue[1]]
    lon_errors = [issue for issue in error_issues if "lon: must be -180 to 180" in issue[1]]
    
    assert len(lat_errors) >= 1
    assert len(lon_errors) >= 1


def test_validate_zone_config_warnings() -> None:
    """Test validation generates appropriate warnings."""
    cfg = ZoneConfig(
        schema="mower-rover.zone.v1",
        zone_id="warning_zone",
        name="Warning Zone",
        home=LatLon(lat=38.89510, lon=-77.03660),
        rally_point=RallyPoint(lat=38.89000, lon=-77.04000),  # Outside boundary
        boundary=[
            LatLon(lat=38.89510, lon=-77.03660),
            LatLon(lat=38.89510, lon=-77.03400),
            LatLon(lat=38.89350, lon=-77.03400),
            LatLon(lat=38.89350, lon=-77.03660)
        ]
    )
    
    issues = validate_zone_config(cfg)
    warn_issues = [issue for issue in issues if issue[0] == "WARN"]
    
    # Should warn about rally point outside boundary
    rally_warnings = [issue for issue in warn_issues if "rally_point should be inside" in issue[1]]
    assert len(rally_warnings) >= 1


def test_load_all_zones_valid_directory(tmp_path: Path) -> None:
    """Test loading all zones from directory with valid files."""
    zones_dir = tmp_path / "zones"
    zones_dir.mkdir()
    
    # Create valid zone files
    zone1_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "zone1",
        "name": "Zone 1",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]]
    }
    
    zone2_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "zone2",
        "name": "Zone 2",
        "home": [38.89520, -77.03670],
        "rally_point": {"lat": 38.89515, "lon": -77.03665},
        "boundary": [[38.89520, -77.03670], [38.89520, -77.03410], [38.89360, -77.03410]]
    }
    
    with (zones_dir / "zone1.yaml").open("w") as f:
        yaml.dump(zone1_yaml, f)
    
    with (zones_dir / "zone2.yaml").open("w") as f:
        yaml.dump(zone2_yaml, f)
    
    configs = load_all_zones(zones_dir)
    
    assert len(configs) == 2
    zone_ids = {cfg.zone_id for cfg in configs}
    assert zone_ids == {"zone1", "zone2"}


def test_load_all_zones_skips_invalid_files(tmp_path: Path) -> None:
    """Test that load_all_zones skips invalid files gracefully."""
    zones_dir = tmp_path / "zones"
    zones_dir.mkdir()
    
    # Valid zone file
    valid_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "valid",
        "name": "Valid Zone",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]]
    }
    
    with (zones_dir / "valid.yaml").open("w") as f:
        yaml.dump(valid_yaml, f)
    
    # Invalid zone file (missing required fields)
    with (zones_dir / "invalid.yaml").open("w") as f:
        yaml.dump({"schema": "mower-rover.zone.v1", "zone_id": "invalid"}, f)
    
    # Non-zone YAML file  
    with (zones_dir / "other.yaml").open("w") as f:
        yaml.dump({"schema": "some-other.schema.v1", "data": "not a zone"}, f)
    
    # Malformed YAML file
    (zones_dir / "malformed.yaml").write_text("invalid: yaml: [")
    
    configs = load_all_zones(zones_dir)
    
    # Should only load the valid zone file
    assert len(configs) == 1
    assert configs[0].zone_id == "valid"


def test_load_all_zones_empty_directory(tmp_path: Path) -> None:
    """Test load_all_zones with empty directory."""
    zones_dir = tmp_path / "zones"
    zones_dir.mkdir()
    
    configs = load_all_zones(zones_dir)
    assert len(configs) == 0


def test_load_all_zones_nonexistent_directory(tmp_path: Path) -> None:
    """Test load_all_zones with nonexistent directory."""
    configs = load_all_zones(tmp_path / "nonexistent")
    assert len(configs) == 0


def test_latlng_coercion_from_list() -> None:
    """Test that lat/lon coordinates can be loaded from [lat, lon] format."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "list_coords",
        "name": "List Coords Zone",
        "home": [38.89510, -77.03660],  # List format
        "rally_point": {"lat": 38.89505, "lon": -77.03655},  # Dict format
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]]
    }
    
    # Use _coerce to test the conversion directly
    from mower_rover.zone.config import _coerce
    cfg = _coerce(zone_yaml)
    
    assert cfg.home.lat == 38.89510
    assert cfg.home.lon == -77.03660


def test_exclusion_zone_validation() -> None:
    """Test exclusion zone polygon validation."""
    zone_yaml = {
        "schema": "mower-rover.zone.v1",
        "zone_id": "exclusion_test",
        "name": "Exclusion Test Zone",
        "home": [38.89510, -77.03660],
        "rally_point": {"lat": 38.89505, "lon": -77.03655},
        "boundary": [[38.89510, -77.03660], [38.89510, -77.03400], [38.89350, -77.03400]],
        "exclusion_zones": [
            {
                "name": "valid_exclusion",
                "buffer_m": 1.0,
                "polygon": [
                    [38.89480, -77.03550],
                    [38.89480, -77.03520],
                    [38.89460, -77.03520],
                    [38.89460, -77.03550]
                ]
            }
        ]
    }
    
    from mower_rover.zone.config import _coerce
    cfg = _coerce(zone_yaml)
    
    assert len(cfg.exclusion_zones) == 1
    assert cfg.exclusion_zones[0].name == "valid_exclusion"
    assert cfg.exclusion_zones[0].buffer_m == 1.0
    assert len(cfg.exclusion_zones[0].polygon) == 4