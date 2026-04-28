"""Zone to MAVLink mission item conversion.

Converts ZoneConfig and generated waypoints to MAVLink mission items
for upload to ArduPilot autopilot.
"""

from __future__ import annotations

from mower_rover.zone.config import ZoneConfig, LatLon
from mower_rover.mavlink.mission import MissionItem
from mower_rover.logging_setup.setup import get_logger

logger = get_logger()

# MAVLink constants
MAV_FRAME_GLOBAL_INT = 5
MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_DO_CHANGE_SPEED = 178
MAV_CMD_DO_SET_RESUME_REPEAT_DIST = 215
MAV_CMD_DO_FENCE_ENABLE = 207
MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION = 5001
MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION = 5002
MAV_CMD_NAV_RALLY_POINT = 5100


def _latlng_to_int32(lat: float, lon: float) -> tuple[int, int]:
    """Convert lat/lon degrees to int32 (×1e7) for MAVLink."""
    return int(lat * 1e7), int(lon * 1e7)


def zone_to_mission(zone: ZoneConfig, waypoints: list[LatLon]) -> list[MissionItem]:
    """Convert zone config and waypoints to mission items.
    
    Creates a mission sequence with:
    - Home position (seq 0)
    - DO_CHANGE_SPEED for mow speed
    - DO_SET_RESUME_REPEAT_DIST 
    - DO_FENCE_ENABLE (if enabled)
    - NAV_WAYPOINT for each generated waypoint
    
    Args:
        zone: Zone configuration
        waypoints: Generated waypoint list from planner
        
    Returns:
        List of mission items ready for upload
    """
    log = logger.bind(
        zone_id=zone.zone_id,
        waypoint_count=len(waypoints),
        fence_enable=zone.commands.fence_enable
    )
    log.info("Converting zone to mission items")
    
    items = []
    seq = 0
    
    # Item 0: Home position
    home_x, home_y = _latlng_to_int32(zone.home.lat, zone.home.lon)
    items.append(MissionItem(
        seq=seq,
        frame=MAV_FRAME_GLOBAL_INT,
        command=MAV_CMD_NAV_WAYPOINT,
        param1=0.0,  # Hold time
        param2=0.0,  # Acceptance radius
        param3=0.0,  # Pass through
        param4=0.0,  # Yaw
        x=home_x,
        y=home_y,
        z=0.0,
        mission_type=0,  # MISSION
        autocontinue=1,
        current=1  # Home is current waypoint initially
    ))
    seq += 1
    
    # DO_CHANGE_SPEED: Set mowing speed
    items.append(MissionItem(
        seq=seq,
        frame=MAV_FRAME_GLOBAL_INT,
        command=MAV_CMD_DO_CHANGE_SPEED,
        param1=1.0,  # Speed type: 1 = ground speed
        param2=zone.coverage.mow_speed_mps,  # Target speed m/s
        param3=0.0,  # Throttle (not used for ground speed)
        param4=0.0,  # Relative (0 = absolute)
        x=0,
        y=0,
        z=0.0,
        mission_type=0,  # MISSION
        autocontinue=1,
        current=0
    ))
    seq += 1
    
    # DO_SET_RESUME_REPEAT_DIST: Set resume distance
    items.append(MissionItem(
        seq=seq,
        frame=MAV_FRAME_GLOBAL_INT,
        command=MAV_CMD_DO_SET_RESUME_REPEAT_DIST,
        param1=zone.commands.resume_dist_m,  # Resume distance in meters
        param2=0.0,
        param3=0.0,
        param4=0.0,
        x=0,
        y=0,
        z=0.0,
        mission_type=0,  # MISSION
        autocontinue=1,
        current=0
    ))
    seq += 1
    
    # DO_FENCE_ENABLE: Enable geo-fence if configured
    if zone.commands.fence_enable:
        items.append(MissionItem(
            seq=seq,
            frame=MAV_FRAME_GLOBAL_INT,
            command=MAV_CMD_DO_FENCE_ENABLE,
            param1=1.0,  # Enable fence
            param2=0.0,
            param3=0.0,
            param4=0.0,
            x=0,
            y=0,
            z=0.0,
            mission_type=0,  # MISSION
            autocontinue=1,
            current=0
        ))
        seq += 1
    
    # NAV_WAYPOINT for each mowing waypoint
    for waypoint in waypoints:
        wp_x, wp_y = _latlng_to_int32(waypoint.lat, waypoint.lon)
        items.append(MissionItem(
            seq=seq,
            frame=MAV_FRAME_GLOBAL_INT,
            command=MAV_CMD_NAV_WAYPOINT,
            param1=0.0,  # Hold time
            param2=2.0,  # Acceptance radius (meters)
            param3=0.0,  # Pass through waypoint
            param4=0.0,  # Yaw angle (0 = don't change)
            x=wp_x,
            y=wp_y,
            z=0.0,  # Ground level
            mission_type=0,  # MISSION
            autocontinue=1,
            current=0
        ))
        seq += 1
    
    log.info("Mission conversion complete", total_items=len(items))
    return items


def zone_to_fence(zone: ZoneConfig) -> list[MissionItem]:
    """Convert zone boundary and exclusions to fence mission items.
    
    Creates fence items for:
    - Boundary vertices as FENCE_POLYGON_VERTEX_INCLUSION
    - Exclusion zone vertices as FENCE_POLYGON_VERTEX_EXCLUSION
    
    Args:
        zone: Zone configuration
        
    Returns:
        List of fence mission items (mission_type=1)
    """
    log = logger.bind(
        zone_id=zone.zone_id,
        boundary_vertices=len(zone.boundary),
        exclusion_zones=len(zone.exclusion_zones)
    )
    log.info("Converting zone to fence items")
    
    items = []
    seq = 0
    
    # Boundary inclusion fence (must be first fence item)
    vertex_count = len(zone.boundary)
    for i, vertex in enumerate(zone.boundary):
        vertex_x, vertex_y = _latlng_to_int32(vertex.lat, vertex.lon)
        
        # First vertex has the total vertex count in param1
        param1 = float(vertex_count) if i == 0 else 0.0
        
        items.append(MissionItem(
            seq=seq,
            frame=MAV_FRAME_GLOBAL_INT,
            command=MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION,
            param1=param1,  # Vertex count for first vertex, 0 for others
            param2=0.0,
            param3=0.0,
            param4=0.0,
            x=vertex_x,
            y=vertex_y,
            z=0.0,
            mission_type=1,  # FENCE
            autocontinue=1,
            current=0
        ))
        seq += 1
    
    # Exclusion zone fences
    for exclusion in zone.exclusion_zones:
        exclusion_vertex_count = len(exclusion.polygon)
        
        for i, vertex in enumerate(exclusion.polygon):
            vertex_x, vertex_y = _latlng_to_int32(vertex.lat, vertex.lon)
            
            # First vertex of each exclusion zone has the vertex count
            param1 = float(exclusion_vertex_count) if i == 0 else 0.0
            
            items.append(MissionItem(
                seq=seq,
                frame=MAV_FRAME_GLOBAL_INT,
                command=MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION,
                param1=param1,  # Vertex count for first vertex, 0 for others
                param2=0.0,
                param3=0.0,
                param4=0.0,
                x=vertex_x,
                y=vertex_y,
                z=0.0,
                mission_type=1,  # FENCE
                autocontinue=1,
                current=0
            ))
            seq += 1
    
    log.info("Fence conversion complete", total_items=len(items))
    return items


def zone_to_rally(zone: ZoneConfig) -> list[MissionItem]:
    """Convert zone rally point to rally mission items.
    
    Creates a single rally point from the zone's rally_point configuration.
    
    Args:
        zone: Zone configuration
        
    Returns:
        List with one rally mission item (mission_type=2)
    """
    log = logger.bind(
        zone_id=zone.zone_id,
        rally_lat=zone.rally_point.lat,
        rally_lon=zone.rally_point.lon
    )
    log.info("Converting zone to rally items")
    
    rally_x, rally_y = _latlng_to_int32(zone.rally_point.lat, zone.rally_point.lon)
    
    item = MissionItem(
        seq=0,
        frame=MAV_FRAME_GLOBAL_INT,
        command=MAV_CMD_NAV_RALLY_POINT,
        param1=0.0,  # Break altitude (not used for ground vehicles)
        param2=0.0,  # Landing direction (not used)
        param3=0.0,
        param4=0.0,
        x=rally_x,
        y=rally_y,
        z=0.0,
        mission_type=2,  # RALLY
        autocontinue=1,
        current=0
    )
    
    log.info("Rally conversion complete")
    return [item]