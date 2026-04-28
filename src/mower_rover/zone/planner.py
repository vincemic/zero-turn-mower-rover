"""Coverage path planner for zone-based mowing.

Generates mowing waypoints using boustrophedon pattern with headland passes.
Handles geodetic coordinates (lat/lon) to planar projection (UTM) conversion
for geometric operations.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Polygon, LineString, Point
from shapely.affinity import rotate
import pyproj

from mower_rover.zone.config import ZoneConfig, LatLon, ExclusionZone
from mower_rover.logging_setup.setup import get_logger

logger = get_logger()


class PlannerError(ValueError):
    """Raised when path planning fails."""


# ------------------------------------------------------------------
# Geodetic ↔ Planar Projection Helpers
# ------------------------------------------------------------------


class GeodeticProjector:
    """Handles geodetic (lat/lon) to planar (UTM) coordinate conversion."""
    
    def __init__(self, reference_latlons: list[LatLon]) -> None:
        """Initialize projector with auto-detected UTM zone from centroid.
        
        Args:
            reference_latlons: List of lat/lon points to determine UTM zone
        """
        if not reference_latlons:
            raise PlannerError("reference_latlons cannot be empty")
        
        # Calculate centroid to determine UTM zone
        centroid_lat = sum(ll.lat for ll in reference_latlons) / len(reference_latlons)
        centroid_lon = sum(ll.lon for ll in reference_latlons) / len(reference_latlons)
        
        # Auto-detect UTM zone from longitude
        utm_zone = int((centroid_lon + 180) / 6) + 1
        
        # Determine hemisphere (north/south)
        hemisphere = 'north' if centroid_lat >= 0 else 'south'
        
        logger.debug(
            f"Auto-detected UTM zone {utm_zone} ({hemisphere}) from centroid "
            f"lat={centroid_lat:.6f}, lon={centroid_lon:.6f}"
        )
        
        # Create coordinate systems
        self._wgs84 = pyproj.CRS('EPSG:4326')  # WGS84 lat/lon
        self._utm = pyproj.CRS(f'+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84 +units=m +no_defs')
        
        # Create transformers
        self._to_utm = pyproj.Transformer.from_crs(self._wgs84, self._utm, always_xy=True)
        self._to_wgs84 = pyproj.Transformer.from_crs(self._utm, self._wgs84, always_xy=True)
    
    def to_planar(self, latlons: list[LatLon]) -> list[tuple[float, float]]:
        """Convert lat/lon coordinates to planar UTM (x,y) coordinates.
        
        Args:
            latlons: List of latitude/longitude coordinates
            
        Returns:
            List of (x, y) coordinates in UTM meters
        """
        if not latlons:
            return []
        
        # Extract lon, lat arrays (note: pyproj expects lon,lat order)
        lons = [ll.lon for ll in latlons]
        lats = [ll.lat for ll in latlons]
        
        # Transform to UTM
        xs, ys = self._to_utm.transform(lons, lats)
        
        # Handle single point case
        if not isinstance(xs, (list, tuple)):
            xs, ys = [xs], [ys]
        
        return list(zip(xs, ys))
    
    def to_geodetic(self, xys: list[tuple[float, float]]) -> list[LatLon]:
        """Convert planar UTM (x,y) coordinates to lat/lon coordinates.
        
        Args:
            xys: List of (x, y) coordinates in UTM meters
            
        Returns:
            List of LatLon coordinates
        """
        if not xys:
            return []
        
        # Extract x, y arrays
        xs, ys = zip(*xys)
        
        # Transform to WGS84
        lons, lats = self._to_wgs84.transform(xs, ys)
        
        # Handle single point case
        if not isinstance(lons, (list, tuple)):
            lons, lats = [lons], [lats]
        
        return [LatLon(lat=lat, lon=lon) for lat, lon in zip(lats, lons)]


# ------------------------------------------------------------------
# Headland Pass Generation
# ------------------------------------------------------------------


def generate_headland_passes(
    boundary_xy: list[tuple[float, float]],
    exclusions_xy: list[list[tuple[float, float]]],
    cutting_width_m: float,
    overlap_pct: float,
    num_passes: int,
) -> list[list[tuple[float, float]]]:
    """Generate headland passes by insetting boundary polygon.
    
    Args:
        boundary_xy: Boundary polygon as (x,y) coordinates in meters
        exclusions_xy: List of exclusion polygons as (x,y) coordinates 
        cutting_width_m: Cutting width in meters
        overlap_pct: Overlap percentage (0-100)
        num_passes: Number of headland passes to generate
        
    Returns:
        List of headland pass waypoint sequences
    """
    if num_passes <= 0:
        return []
    
    # Create boundary polygon
    boundary_poly = Polygon(boundary_xy)
    if not boundary_poly.is_valid:
        boundary_poly = boundary_poly.buffer(0)  # Fix invalid geometry
    
    # Create exclusion polygons and subtract them from boundary
    mowable_poly = boundary_poly
    for excl_xy in exclusions_xy:
        excl_poly = Polygon(excl_xy)
        if not excl_poly.is_valid:
            excl_poly = excl_poly.buffer(0)
        # Buffer exclusion slightly to ensure clearance
        mowable_poly = mowable_poly.difference(excl_poly.buffer(0.5))
    
    if mowable_poly.is_empty:
        logger.debug("No mowable area after exclusions")
        return []
    
    # Calculate inset distance for each pass
    inset_distance = cutting_width_m * (1.0 - overlap_pct / 100.0)
    
    passes = []
    current_poly = mowable_poly
    
    for pass_num in range(num_passes):
        if current_poly.is_empty or current_poly.area < 1.0:  # Skip if too small (< 1 m²)
            break
        
        # Extract waypoints from polygon boundary/boundaries
        if hasattr(current_poly, 'exterior'):
            # Simple polygon - extract exterior and any interior holes
            coords = list(current_poly.exterior.coords[:-1])  # Remove duplicate last point
            if coords:
                passes.append(coords)
            
            # Add interior boundaries (holes from exclusions) as separate passes
            for interior in current_poly.interiors:
                hole_coords = list(interior.coords[:-1])
                if hole_coords:
                    passes.append(hole_coords)
                    
        elif hasattr(current_poly, 'geoms'):
            # MultiPolygon - add waypoints for each polygon part
            for geom in current_poly.geoms:
                if hasattr(geom, 'exterior') and geom.area > 1.0:
                    coords = list(geom.exterior.coords[:-1])
                    if coords:
                        passes.append(coords)
                    
                    # Add interior boundaries for this geometry too
                    for interior in geom.interiors:
                        hole_coords = list(interior.coords[:-1])
                        if hole_coords:
                            passes.append(hole_coords)
        
        # Inset for next pass
        current_poly = current_poly.buffer(-inset_distance)
        if current_poly.is_empty:
            break
    
    logger.debug(f"Generated {len(passes)} headland passes")
    return passes


# ------------------------------------------------------------------
# Boustrophedon Fill Pattern
# ------------------------------------------------------------------


def generate_boustrophedon_fill(
    mowable_poly: Polygon,
    cutting_width_m: float,
    overlap_pct: float,
    angle_deg: float = 0.0,
) -> list[tuple[float, float]]:
    """Generate boustrophedon (back-and-forth) fill pattern.
    
    Args:
        mowable_poly: Mowable area polygon (after headlands and exclusions)
        cutting_width_m: Cutting width in meters
        overlap_pct: Overlap percentage (0-100)
        angle_deg: Sweep line angle in degrees (0 = east-west)
        
    Returns:
        List of waypoints following boustrophedon pattern
    """
    if mowable_poly.is_empty or mowable_poly.area < 1.0:
        return []
    
    # Calculate line spacing
    line_spacing = cutting_width_m * (1.0 - overlap_pct / 100.0)
    
    # Get bounding box
    minx, miny, maxx, maxy = mowable_poly.bounds
    
    # Rotate polygon to align with sweep direction
    rotated_poly = rotate(mowable_poly, -angle_deg, origin=(minx, miny))
    rotated_minx, rotated_miny, rotated_maxx, rotated_maxy = rotated_poly.bounds
    
    # Generate sweep lines
    waypoints = []
    y = rotated_miny + line_spacing / 2  # Start with offset
    direction = 1  # 1 for left-to-right, -1 for right-to-left
    
    while y <= rotated_maxy - line_spacing / 2:
        # Create sweep line across full width
        if direction == 1:
            line = LineString([(rotated_minx - 10, y), (rotated_maxx + 10, y)])
        else:
            line = LineString([(rotated_maxx + 10, y), (rotated_minx - 10, y)])
        
        # Clip line to mowable polygon
        intersection = rotated_poly.intersection(line)
        
        if not intersection.is_empty:
            geom_type = intersection.geom_type
            
            if geom_type == 'LineString':
                # Single LineString
                line_coords = list(intersection.coords)
                waypoints.extend(line_coords)
            elif geom_type == 'MultiLineString':
                # MultiLineString - process each segment
                segments = list(intersection.geoms)
                if segments:
                    # Use the longest segment or concatenate all if direction matters
                    if direction == 1:
                        # Left to right - use segments in order
                        for segment in segments:
                            line_coords = list(segment.coords)
                            waypoints.extend(line_coords)
                    else:
                        # Right to left - reverse segment order and coordinates
                        for segment in reversed(segments):
                            line_coords = list(reversed(segment.coords))
                            waypoints.extend(line_coords)
            # Note: Points and other geometry types are ignored
        
        y += line_spacing
        direction *= -1  # Alternate direction
    
    # Rotate waypoints back to original orientation
    if waypoints and angle_deg != 0:
        rotated_waypoints = []
        for x, y in waypoints:
            # Rotate point back
            cos_a = math.cos(math.radians(angle_deg))
            sin_a = math.sin(math.radians(angle_deg))
            
            # Translate to origin, rotate, translate back
            tx = x - minx
            ty = y - miny
            rx = tx * cos_a - ty * sin_a + minx
            ry = tx * sin_a + ty * cos_a + miny
            
            rotated_waypoints.append((rx, ry))
        waypoints = rotated_waypoints
    
    logger.debug(f"Generated {len(waypoints)} boustrophedon waypoints")
    return waypoints


# ------------------------------------------------------------------
# Main Path Planning Function
# ------------------------------------------------------------------


def generate_waypoints(zone: ZoneConfig) -> list[LatLon]:
    """Generate complete mowing waypoints for a zone.
    
    Combines headland passes and boustrophedon fill pattern.
    
    Args:
        zone: Zone configuration with boundary, exclusions, and coverage params
        
    Returns:
        Ordered list of mowing waypoints in lat/lon coordinates
        
    Raises:
        PlannerError: If planning fails due to invalid geometry or parameters
    """
    logger.info(f"Generating waypoints for zone {zone.zone_id}: {zone.name}")
    
    try:
        # Initialize geodetic projector
        projector = GeodeticProjector(zone.boundary)
        
        # Convert to planar coordinates
        boundary_xy = projector.to_planar(zone.boundary)
        exclusions_xy = []
        for excl in zone.exclusion_zones:
            excl_buffered = projector.to_planar(excl.polygon)
            exclusions_xy.append(excl_buffered)
        
        # Convert cutting width from inches to meters
        cutting_width_m = zone.coverage.cutting_width_in * 0.0254
        
        # Generate headland passes
        headland_passes = generate_headland_passes(
            boundary_xy=boundary_xy,
            exclusions_xy=exclusions_xy,
            cutting_width_m=cutting_width_m,
            overlap_pct=zone.coverage.overlap_pct,
            num_passes=zone.coverage.headland_passes,
        )
        
        # Combine all headland waypoints
        all_waypoints_xy = []
        for headland_pass in headland_passes:
            all_waypoints_xy.extend(headland_pass)
        
        # Generate fill pattern for innermost area
        if headland_passes:
            # Use the area after all headland passes for fill
            boundary_poly = Polygon(boundary_xy)
            
            # Subtract exclusion zones from boundary first
            mowable_poly = boundary_poly
            for excl_xy in exclusions_xy:
                excl_poly = Polygon(excl_xy).buffer(0.5)  # Small buffer for clearance
                mowable_poly = mowable_poly.difference(excl_poly)
            
            # Inset by all headland passes
            inset_distance = cutting_width_m * (1.0 - zone.coverage.overlap_pct / 100.0)
            innermost_poly = mowable_poly
            for _ in range(zone.coverage.headland_passes):
                innermost_poly = innermost_poly.buffer(-inset_distance)
                if innermost_poly.is_empty:
                    break
            
            # Generate boustrophedon fill
            if not innermost_poly.is_empty and innermost_poly.area > 1.0:
                fill_waypoints = generate_boustrophedon_fill(
                    mowable_poly=innermost_poly,
                    cutting_width_m=cutting_width_m,
                    overlap_pct=zone.coverage.overlap_pct,
                    angle_deg=zone.coverage.angle_deg,
                )
                all_waypoints_xy.extend(fill_waypoints)
        
        # Convert back to geodetic coordinates
        if not all_waypoints_xy:
            logger.warning(f"No waypoints generated for zone {zone.zone_id}")
            return []
        
        waypoints_latlons = projector.to_geodetic(all_waypoints_xy)
        
        logger.info(
            f"Generated {len(waypoints_latlons)} total waypoints for zone {zone.zone_id} "
            f"({len(headland_passes)} headland passes)"
        )
        
        return waypoints_latlons
        
    except Exception as e:
        raise PlannerError(f"Failed to generate waypoints for zone {zone.zone_id}: {e}") from e