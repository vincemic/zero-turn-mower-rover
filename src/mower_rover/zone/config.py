"""Zone config schema and loader.

Configuration for multi-zone lawn management, defining zone boundaries,
exclusion zones, coverage patterns, and mission commands for autonomous mowing.
Follows the same pattern as vslam.py (dataclass + coerce + load).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from shapely.geometry import Polygon, Point

from mower_rover.logging_setup.setup import get_logger

logger = get_logger()


class ZoneConfigError(ValueError):
    """Raised when a zone YAML is malformed."""


# ------------------------------------------------------------------
# Nested dataclasses
# ------------------------------------------------------------------


@dataclass(frozen=True)
class LatLon:
    """Latitude/longitude coordinates."""
    
    lat: float
    lon: float


@dataclass(frozen=True)
class RallyPoint:
    """Rally point for mission start/recovery."""
    
    lat: float
    lon: float
    description: str = ""


@dataclass(frozen=True)
class ExclusionZone:
    """Exclusion zone with buffered polygon."""
    
    name: str
    buffer_m: float
    polygon: list[LatLon]


@dataclass(frozen=True)
class CoverageParams:
    """Coverage pattern parameters for mowing."""
    
    pattern: str = "boustrophedon"
    cutting_width_in: float = 54.0
    overlap_pct: float = 10.0
    angle_deg: float = 0.0
    headland_passes: int = 2
    mow_speed_mps: float = 2.0
    turn_speed_mps: float = 1.0


@dataclass(frozen=True)
class MissionCommands:
    """Mission command parameters."""
    
    fence_enable: bool = True
    resume_dist_m: float = 2.5
    blade_engage: bool = True


@dataclass(frozen=True)
class SlamOverrides:
    """SLAM configuration overrides for this zone."""
    
    mode: str = "localization"


@dataclass(frozen=True)
class OutputConfig:
    """Output file configuration."""
    
    waypoints_file: str = ""
    geojson_file: str = ""


@dataclass(frozen=True)
class ZoneConfig:
    """Complete zone configuration."""
    
    schema: str
    zone_id: str
    name: str
    home: LatLon
    rally_point: RallyPoint
    boundary: list[LatLon]
    description: str = ""
    exclusion_zones: list[ExclusionZone] = field(default_factory=list)
    coverage: CoverageParams = field(default_factory=CoverageParams)
    commands: MissionCommands = field(default_factory=MissionCommands)
    slam: SlamOverrides = field(default_factory=SlamOverrides)
    output: OutputConfig = field(default_factory=OutputConfig)


# ------------------------------------------------------------------
# Coercion functions
# ------------------------------------------------------------------


def _coerce_latlng(raw: dict[str, Any], name: str) -> LatLon:
    """Coerce a lat/lon dict or list to LatLon."""
    if isinstance(raw, list) and len(raw) == 2:
        return LatLon(lat=float(raw[0]), lon=float(raw[1]))
    if isinstance(raw, dict) and "lat" in raw and "lon" in raw:
        return LatLon(lat=float(raw["lat"]), lon=float(raw["lon"]))
    raise ZoneConfigError(f"{name}: must be [lat, lon] or {{lat: ..., lon: ...}}")


def _coerce_rally_point(raw: dict[str, Any]) -> RallyPoint:
    """Coerce rally point dict to RallyPoint."""
    if not isinstance(raw, dict):
        raise ZoneConfigError("rally_point: must be dict")
    
    if "lat" not in raw or "lon" not in raw:
        raise ZoneConfigError("rally_point: missing lat/lon")
    
    return RallyPoint(
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        description=raw.get("description", ""),
    )


def _coerce_boundary(raw: list[Any]) -> list[LatLon]:
    """Coerce boundary list to list of LatLon."""
    if not isinstance(raw, list):
        raise ZoneConfigError("boundary: must be list")
    
    if len(raw) < 3:
        raise ZoneConfigError("boundary: must have at least 3 vertices")
    
    points = []
    for i, point in enumerate(raw):
        try:
            points.append(_coerce_latlng(point, f"boundary[{i}]"))
        except ZoneConfigError as e:
            raise ZoneConfigError(f"boundary[{i}]: {e}") from e
    
    # Validate as Shapely polygon
    try:
        coords = [(p.lat, p.lon) for p in points]
        poly = Polygon(coords)
        if not poly.is_valid:
            raise ZoneConfigError("boundary: invalid polygon geometry")
    except Exception as e:
        raise ZoneConfigError(f"boundary: Shapely validation failed: {e}") from e
    
    return points


def _coerce_exclusion_zones(raw: list[Any]) -> list[ExclusionZone]:
    """Coerce exclusion zones list to list of ExclusionZone."""
    if not isinstance(raw, list):
        raise ZoneConfigError("exclusion_zones: must be list")
    
    zones = []
    for i, zone_raw in enumerate(raw):
        if not isinstance(zone_raw, dict):
            raise ZoneConfigError(f"exclusion_zones[{i}]: must be dict")
        
        if "name" not in zone_raw:
            raise ZoneConfigError(f"exclusion_zones[{i}]: missing name")
        
        if "polygon" not in zone_raw:
            raise ZoneConfigError(f"exclusion_zones[{i}]: missing polygon")
        
        # Coerce polygon
        polygon_raw = zone_raw["polygon"]
        if not isinstance(polygon_raw, list) or len(polygon_raw) < 3:
            raise ZoneConfigError(f"exclusion_zones[{i}].polygon: must be list with ≥3 vertices")
        
        polygon_points = []
        for j, point in enumerate(polygon_raw):
            try:
                polygon_points.append(_coerce_latlng(point, f"exclusion_zones[{i}].polygon[{j}]"))
            except ZoneConfigError as e:
                raise ZoneConfigError(f"exclusion_zones[{i}].polygon[{j}]: {e}") from e
        
        # Validate polygon geometry
        try:
            coords = [(p.lat, p.lon) for p in polygon_points]
            poly = Polygon(coords)
            if not poly.is_valid:
                raise ZoneConfigError(f"exclusion_zones[{i}].polygon: invalid geometry")
        except Exception as e:
            raise ZoneConfigError(f"exclusion_zones[{i}].polygon: validation failed: {e}") from e
        
        zones.append(ExclusionZone(
            name=str(zone_raw["name"]),
            buffer_m=float(zone_raw.get("buffer_m", 0.0)),
            polygon=polygon_points,
        ))
    
    return zones


def _coerce_coverage(raw: dict[str, Any]) -> CoverageParams:
    """Coerce coverage dict to CoverageParams."""
    if not isinstance(raw, dict):
        return CoverageParams()
    
    # Validate numeric constraints
    cutting_width = float(raw.get("cutting_width_in", 54.0))
    if cutting_width <= 0:
        raise ZoneConfigError("coverage.cutting_width_in: must be > 0")
    
    overlap_pct = float(raw.get("overlap_pct", 10.0))
    if not (0 <= overlap_pct <= 50):
        raise ZoneConfigError("coverage.overlap_pct: must be 0-50")
    
    mow_speed = float(raw.get("mow_speed_mps", 2.0))
    if mow_speed <= 0:
        raise ZoneConfigError("coverage.mow_speed_mps: must be > 0")
    
    turn_speed = float(raw.get("turn_speed_mps", 1.0))
    if turn_speed <= 0:
        raise ZoneConfigError("coverage.turn_speed_mps: must be > 0")
    
    return CoverageParams(
        pattern=str(raw.get("pattern", "boustrophedon")),
        cutting_width_in=cutting_width,
        overlap_pct=overlap_pct,
        angle_deg=float(raw.get("angle_deg", 0.0)),
        headland_passes=int(raw.get("headland_passes", 2)),
        mow_speed_mps=mow_speed,
        turn_speed_mps=turn_speed,
    )


def _coerce_commands(raw: dict[str, Any]) -> MissionCommands:
    """Coerce commands dict to MissionCommands."""
    if not isinstance(raw, dict):
        return MissionCommands()
    
    return MissionCommands(
        fence_enable=bool(raw.get("fence_enable", True)),
        resume_dist_m=float(raw.get("resume_dist_m", 2.5)),
        blade_engage=bool(raw.get("blade_engage", True)),
    )


def _coerce_slam(raw: dict[str, Any]) -> SlamOverrides:
    """Coerce slam dict to SlamOverrides."""
    if not isinstance(raw, dict):
        return SlamOverrides()
    
    return SlamOverrides(
        mode=str(raw.get("mode", "localization")),
    )


def _coerce_output(raw: dict[str, Any]) -> OutputConfig:
    """Coerce output dict to OutputConfig."""
    if not isinstance(raw, dict):
        return OutputConfig()
    
    return OutputConfig(
        waypoints_file=str(raw.get("waypoints_file", "")),
        geojson_file=str(raw.get("geojson_file", "")),
    )


def _coerce(raw: dict[str, Any]) -> ZoneConfig:
    """Validate and coerce a raw YAML dict into a ZoneConfig."""
    # Required fields
    if "schema" not in raw:
        raise ZoneConfigError("missing required field: schema")
    
    if "zone_id" not in raw:
        raise ZoneConfigError("missing required field: zone_id")
    
    if "name" not in raw:
        raise ZoneConfigError("missing required field: name")
    
    if "home" not in raw:
        raise ZoneConfigError("missing required field: home")
    
    if "rally_point" not in raw:
        raise ZoneConfigError("missing required field: rally_point")
    
    if "boundary" not in raw:
        raise ZoneConfigError("missing required field: boundary")
    
    # Validate zone_id format
    zone_id = str(raw["zone_id"])
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", zone_id):
        raise ZoneConfigError("zone_id: must match ^[a-z][a-z0-9_-]{0,31}$")
    
    # Coerce all fields
    return ZoneConfig(
        schema=str(raw["schema"]),
        zone_id=zone_id,
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        home=_coerce_latlng(raw["home"], "home"),
        rally_point=_coerce_rally_point(raw["rally_point"]),
        boundary=_coerce_boundary(raw["boundary"]),
        exclusion_zones=_coerce_exclusion_zones(raw.get("exclusion_zones", [])),
        coverage=_coerce_coverage(raw.get("coverage", {})),
        commands=_coerce_commands(raw.get("commands", {})),
        slam=_coerce_slam(raw.get("slam", {})),
        output=_coerce_output(raw.get("output", {})),
    )


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def load_zone_config(path: Path) -> ZoneConfig:
    """Load and validate a zone config YAML file.
    
    Args:
        path: Path to zone YAML file
        
    Returns:
        Validated ZoneConfig instance
        
    Raises:
        ZoneConfigError: If YAML is invalid or malformed
        FileNotFoundError: If file doesn't exist
    """
    if not path.exists():
        raise FileNotFoundError(f"Zone config not found: {path}")
    
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ZoneConfigError(f"Invalid YAML in {path}: {e}") from e
    
    if raw is None:
        raise ZoneConfigError(f"Empty YAML file: {path}")
    
    if not isinstance(raw, dict):
        raise ZoneConfigError(f"YAML root must be dict, got {type(raw)}")
    
    return _coerce(raw)


def validate_zone_config(cfg: ZoneConfig) -> list[tuple[str, str]]:
    """Validate a zone config and return warnings/errors.
    
    Args:
        cfg: Zone config to validate
        
    Returns:
        List of (severity, message) tuples where severity is "ERROR" or "WARN"
    """
    issues = []
    
    # Check lat/lon ranges
    def check_latlng(point: LatLon, name: str) -> None:
        if not (-90 <= point.lat <= 90):
            issues.append(("ERROR", f"{name}.lat: must be -90 to 90, got {point.lat}"))
        if not (-180 <= point.lon <= 180):
            issues.append(("ERROR", f"{name}.lon: must be -180 to 180, got {point.lon}"))
    
    check_latlng(cfg.home, "home")
    check_latlng(cfg.rally_point, "rally_point")
    
    for i, point in enumerate(cfg.boundary):
        check_latlng(point, f"boundary[{i}]")
    
    # Check boundary area (approximate)
    try:
        coords = [(p.lat, p.lon) for p in cfg.boundary]
        poly = Polygon(coords)
        # Convert to projected coordinates for area calculation (rough approximation)
        # Using UTM zone 33N (EPSG:32633) as example - in practice would need proper projection
        area_deg_sq = poly.area
        # Very rough conversion: 1 degree ≈ 111 km at equator
        area_m_sq = area_deg_sq * (111000 ** 2)
        
        if area_m_sq < 100:
            issues.append(("WARN", f"boundary area very small: ~{area_m_sq:.0f} m²"))
        elif area_m_sq > 100_000:
            issues.append(("WARN", f"boundary area very large: ~{area_m_sq:.0f} m²"))
    except Exception:
        pass  # Skip area check if calculation fails
    
    # Check rally point inside boundary
    try:
        boundary_coords = [(p.lat, p.lon) for p in cfg.boundary]
        boundary_poly = Polygon(boundary_coords)
        rally_point_geom = Point(cfg.rally_point.lat, cfg.rally_point.lon)
        
        if not (boundary_poly.contains(rally_point_geom) or 
                boundary_poly.touches(rally_point_geom)):
            issues.append(("WARN", "rally_point should be inside or at edge of boundary"))
    except Exception:
        pass  # Skip check if geometry fails
    
    # Check exclusion zones inside boundary
    try:
        boundary_coords = [(p.lat, p.lon) for p in cfg.boundary]
        boundary_poly = Polygon(boundary_coords)
        
        for zone in cfg.exclusion_zones:
            zone_coords = [(p.lat, p.lon) for p in zone.polygon]
            zone_poly = Polygon(zone_coords)
            
            if not boundary_poly.contains(zone_poly):
                issues.append(("WARN", f"exclusion zone '{zone.name}' extends outside boundary"))
    except Exception:
        pass  # Skip check if geometry fails
    
    return issues


def load_all_zones(zones_dir: Path) -> list[ZoneConfig]:
    """Load all zone configs from a directory.
    
    Args:
        zones_dir: Directory containing *.yaml zone files
        
    Returns:
        List of valid ZoneConfig instances
        
    Note:
        Invalid files are logged as warnings and skipped
    """
    if not zones_dir.exists() or not zones_dir.is_dir():
        logger.warning("zones directory not found", path=str(zones_dir))
        return []
    
    configs = []
    
    for yaml_file in zones_dir.glob("*.yaml"):
        try:
            cfg = load_zone_config(yaml_file)
            # Quick validation to ensure it's a zone file
            if not cfg.schema.startswith("mower-rover.zone."):
                logger.debug("skipping non-zone YAML", file=yaml_file.name)
                continue
            
            configs.append(cfg)
            logger.debug("loaded zone config", zone_id=cfg.zone_id, file=yaml_file.name)
            
        except (ZoneConfigError, FileNotFoundError, yaml.YAMLError) as e:
            logger.warning("failed to load zone config", file=yaml_file.name, error=str(e))
            continue
    
    logger.info("loaded zone configs", count=len(configs), directory=str(zones_dir))
    return configs