"""GeoJSON export for zone configurations.

Converts ZoneConfig objects and generated waypoints to RFC 7946-compliant
GeoJSON for visualization in QGIS, web maps, and other geospatial tools.
"""

from __future__ import annotations

from mower_rover.zone.config import ZoneConfig, LatLon
from mower_rover.logging_setup.setup import get_logger

logger = get_logger()


def export_zone_geojson(zone: ZoneConfig, waypoints: list[LatLon]) -> dict:
    """Export a single zone as GeoJSON FeatureCollection.
    
    Creates a GeoJSON FeatureCollection with features for:
    - Zone boundary (Polygon) 
    - Exclusion zones (Polygons)
    - Home point (Point)
    - Rally point (Point)
    - Coverage path (LineString)
    
    Args:
        zone: Zone configuration to export
        waypoints: Generated coverage waypoints from planner
        
    Returns:
        GeoJSON FeatureCollection dict (RFC 7946 compliant)
        
    Note:
        Coordinates are in [longitude, latitude] order per RFC 7946.
    """
    log = logger.bind(
        zone_id=zone.zone_id,
        waypoint_count=len(waypoints),
        exclusion_count=len(zone.exclusion_zones)
    )
    log.info("Exporting zone as GeoJSON")
    
    features = []
    
    # Zone boundary polygon ([lon, lat] per RFC 7946)
    boundary_coords = [[pt.lon, pt.lat] for pt in zone.boundary]
    # Close the ring by repeating first coordinate
    boundary_coords.append(boundary_coords[0])
    
    features.append({
        "type": "Feature",
        "properties": {
            "zone_id": zone.zone_id,
            "feature_type": "boundary",
            "name": zone.name,
            "description": zone.description,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [boundary_coords],
        },
    })
    
    # Exclusion zones
    for ez in zone.exclusion_zones:
        ez_coords = [[pt.lon, pt.lat] for pt in ez.polygon]
        # Close the ring
        ez_coords.append(ez_coords[0])
        
        features.append({
            "type": "Feature", 
            "properties": {
                "zone_id": zone.zone_id,
                "feature_type": "exclusion",
                "name": ez.name,
                "buffer_m": ez.buffer_m,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [ez_coords],
            },
        })
    
    # Home point
    features.append({
        "type": "Feature",
        "properties": {
            "zone_id": zone.zone_id,
            "feature_type": "home",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [zone.home.lon, zone.home.lat],
        },
    })
    
    # Rally point
    features.append({
        "type": "Feature",
        "properties": {
            "zone_id": zone.zone_id,
            "feature_type": "rally",
            "description": zone.rally_point.description,
        },
        "geometry": {
            "type": "Point", 
            "coordinates": [zone.rally_point.lon, zone.rally_point.lat],
        },
    })
    
    # Coverage path as LineString (if waypoints provided)
    if waypoints:
        path_coords = [[wp.lon, wp.lat] for wp in waypoints]
        features.append({
            "type": "Feature",
            "properties": {
                "zone_id": zone.zone_id,
                "feature_type": "coverage_path",
                "waypoint_count": len(waypoints),
                "pattern": zone.coverage.pattern,
                "mow_speed_mps": zone.coverage.mow_speed_mps,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": path_coords,
            },
        })
    
    geojson = {
        "type": "FeatureCollection",
        "properties": {
            "zone_id": zone.zone_id,
            "zone_name": zone.name,
            "description": zone.description,
        },
        "features": features,
    }
    
    log.info("GeoJSON export complete", feature_count=len(features))
    return geojson


def export_multi_zone_geojson(zones: list[ZoneConfig]) -> dict:
    """Export multiple zones as a combined GeoJSON FeatureCollection.
    
    Combines all zone boundaries, exclusions, and points into a single
    GeoJSON for overview visualization. Coverage paths are not included
    in multi-zone export to reduce complexity.
    
    Args:
        zones: List of zone configurations to export
        
    Returns:
        Combined GeoJSON FeatureCollection dict
    """
    log = logger.bind(zone_count=len(zones))
    log.info("Exporting multi-zone GeoJSON")
    
    all_features = []
    zone_names = []
    
    for zone in zones:
        zone_names.append(zone.name)
        
        # Export without waypoints for multi-zone (cleaner overview)
        zone_geojson = export_zone_geojson(zone, [])
        
        # Add all features except coverage_path
        for feature in zone_geojson["features"]:
            if feature["properties"]["feature_type"] != "coverage_path":
                all_features.append(feature)
    
    combined_geojson = {
        "type": "FeatureCollection",
        "properties": {
            "zone_count": len(zones),
            "zone_names": zone_names,
            "export_type": "multi_zone",
        },
        "features": all_features,
    }
    
    log.info("Multi-zone GeoJSON export complete", 
             total_features=len(all_features), 
             zone_names=zone_names)
    return combined_geojson