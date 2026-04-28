"""Zone management commands for laptop-side CLI.

Provides `mower zone` and `mower mission` command groups for zone selection,
mission planning, and upload orchestration with hardware safety checks.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path

import typer

from mower_rover.zone.config import ZoneConfig, load_zone_config, load_all_zones
from mower_rover.zone.planner import generate_waypoints
from mower_rover.zone.mission_items import zone_to_mission, zone_to_fence, zone_to_rally
from mower_rover.zone.geojson import export_multi_zone_geojson
from mower_rover.mavlink.connection import ConnectionConfig, open_link
from mower_rover.mavlink.mission import (
    upload_mission, clear_mission, verify_round_trip, download_mission,
)
from mower_rover.safety.confirm import requires_confirmation, SafetyContext
from mower_rover.transport.ssh import JetsonClient
from mower_rover.config.laptop import JetsonEndpoint
from mower_rover.logging_setup.setup import get_logger

# Create Typer sub-apps
zone_app = typer.Typer(name="zone", help="Zone management commands.", no_args_is_help=True)
mission_app = typer.Typer(name="mission", help="Mission planning commands.", no_args_is_help=True)


@mission_app.callback()
def _mission_callback() -> None:
    """Mission planning commands."""

logger = get_logger()


class ZoneUploadError(RuntimeError):
    """Raised when zone upload fails."""


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------


def _check_not_armed(conn) -> None:
    """Check that the flight controller is not armed."""
    from pymavlink import mavutil

    hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    if hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
        raise typer.BadParameter("FC is armed — cannot switch zones. Disarm first.")


def _upload_zone_atomically(conn, mission_items, fence_items, rally_items):
    """Upload zone mission items atomically with clear-on-failure.
    
    Args:
        conn: MAVLink connection
        mission_items: Mission waypoints
        fence_items: Fence boundary/exclusions  
        rally_items: Rally points
        
    Raises:
        ZoneUploadError: If upload fails (after clearing all missions for safety)
    """
    try:
        upload_mission(conn, mission_items, mission_type=0)  # MISSION
        upload_mission(conn, fence_items, mission_type=1)    # FENCE
        upload_mission(conn, rally_items, mission_type=2)    # RALLY
        verify_round_trip(conn, mission_items, 0)
        verify_round_trip(conn, fence_items, 1)
        verify_round_trip(conn, rally_items, 2)
    except Exception:
        # Clear all missions for safety
        try:
            clear_mission(conn, 0)  # MISSION
            clear_mission(conn, 1)  # FENCE
            clear_mission(conn, 2)  # RALLY
        except Exception:
            pass  # Best effort cleanup
        raise ZoneUploadError("Zone upload FAILED. All missions cleared for safety.")


def _write_zone_snapshot(zone_id: str, waypoint_count: int, fence_count: int, 
                        rally_point, path: Path) -> None:
    """Write zone upload snapshot to JSON file.
    
    Args:
        zone_id: Zone identifier
        waypoint_count: Number of waypoints uploaded
        fence_count: Number of fence vertices uploaded
        rally_point: Rally point LatLon
        path: Output path for snapshot
    """
    payload = {
        "schema": "mower-rover.zone-upload.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "zone_id": zone_id,
        "waypoint_count": waypoint_count,
        "fence_vertex_count": fence_count,
        "rally_point": {"lat": rally_point.lat, "lon": rally_point.lon},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _get_jetson_endpoint() -> JetsonEndpoint:
    """Get Jetson endpoint configuration (placeholder - would load from config)."""
    # TODO: Load from actual config file in real implementation
    return JetsonEndpoint(
        host="jetson-orin.local",
        user="mower",
        port=22,
        key_path=None  # Use default SSH key
    )


def _activate_zone_on_jetson(zone_id: str, correlation_id: str, *, dry_run: bool = False) -> None:
    """Activate zone on Jetson via SSH and wait for VSLAM readiness.
    
    Args:
        zone_id: Zone to activate
        correlation_id: Logging correlation ID
        dry_run: If True, skip actual SSH calls
    """
    if dry_run:
        logger.info("dry_run: would SSH to activate zone", zone_id=zone_id)
        return
        
    endpoint = _get_jetson_endpoint()
    client = JetsonClient(endpoint, correlation_id=correlation_id)
    
    # Run zone activate command on Jetson
    result = client.run([
        "mower-jetson", "zone", "activate", zone_id
    ], timeout=30.0)
    
    if not result.ok:
        raise typer.ClickException(
            f"Zone activation failed on Jetson: {result.stderr.strip()}"
        )
    
    logger.info("zone activated on jetson", zone_id=zone_id)


# ------------------------------------------------------------------
# Zone commands
# ------------------------------------------------------------------


@zone_app.command("list")
def list_zones(
    zones_dir: Path = typer.Option(
        Path("zones"), "--zones-dir", help="Directory containing zone YAML files"
    )
) -> None:
    """List all available zones with basic info."""
    logger.info("scanning zones directory", path=str(zones_dir))
    
    if not zones_dir.exists():
        typer.echo(f"Zones directory not found: {zones_dir}")
        raise typer.Exit(1)
    
    zones = load_all_zones(zones_dir)
    
    if not zones:
        typer.echo("No valid zone files found.")
        return
    
    # Display table header
    typer.echo("Zone ID      | Name                     | Boundary | Area Est.")
    typer.echo("-------------|--------------------------|----------|----------")
    
    for zone in zones:
        # Rough area estimate (very approximate)
        boundary_count = len(zone.boundary)
        area_est = f"~{boundary_count * 100}m²"  # Placeholder calculation
        
        # Truncate long names
        name = zone.name[:24] if len(zone.name) <= 24 else zone.name[:21] + "..."
        
        typer.echo(
            f"{zone.zone_id:<12} | {name:<24} | {boundary_count:>8} | {area_est:>8}"
        )
    
    typer.echo(f"\nTotal: {len(zones)} zones")


# Separate confirmation function for zone selection
@requires_confirmation("This will upload new mission/fence/rally to the flight controller")
def _confirm_zone_select(*, ctx: SafetyContext) -> None:
    """Confirmation wrapper for zone selection."""


@zone_app.command("select")
def select_zone(
    zone_file: Path = typer.Argument(..., help="Zone YAML file to select"),
    mavlink_endpoint: str = typer.Option(
        "udp:127.0.0.1:14550",
        "--mavlink",
        help="MAVLink connection endpoint",
    ),
    skip_slam: bool = typer.Option(
        False, "--skip-slam", help="Skip SSH zone activation (VSLAM setup)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Skip uploads and SSH — planning only",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt",
    ),
    correlation_id: str = typer.Option("", "--correlation-id", hidden=True),
) -> None:
    """Select and upload a zone configuration to the flight controller."""
    logger.info("zone select starting", zone_file=str(zone_file))

    safety_ctx = SafetyContext(dry_run=dry_run, assume_yes=yes)
    _confirm_zone_select(ctx=safety_ctx)

    # Load zone configuration
    try:
        zone = load_zone_config(zone_file)
        logger.info("loaded zone config", zone_id=zone.zone_id, name=zone.name)
    except Exception as e:
        typer.echo(f"Failed to load zone config: {e}")
        raise typer.Exit(1)

    if dry_run:
        waypoints = generate_waypoints(zone)
        mission_items = zone_to_mission(zone, waypoints)
        fence_items = zone_to_fence(zone)
        rally_items = zone_to_rally(zone)
        typer.echo("DRY RUN - Zone selection complete (no upload)")
        typer.echo(f"  Would upload {len(waypoints)} waypoints")
        typer.echo(f"  Would upload {len(fence_items)} fence vertices")
        typer.echo(f"  Would upload {len(rally_items)} rally points")
        return

    # Connect to flight controller
    config = ConnectionConfig(endpoint=mavlink_endpoint)
    with open_link(config) as conn:
        logger.info("connected to flight controller")
        _check_not_armed(conn)
        logger.info("confirmed FC not armed")

        # SSH zone activation (unless skipped)
        if not skip_slam:
            _activate_zone_on_jetson(zone.zone_id, correlation_id or "zone-select")
        else:
            logger.info("skipping VSLAM activation (--skip-slam)")

        # Generate waypoints
        waypoints = generate_waypoints(zone)
        logger.info("waypoint generation complete", count=len(waypoints))

        if not waypoints:
            typer.echo("No waypoints generated - zone may be too small")
            raise typer.Exit(1)

        # Convert to mission items
        mission_items = zone_to_mission(zone, waypoints)
        fence_items = zone_to_fence(zone)
        rally_items = zone_to_rally(zone)

        # Upload atomically
        _upload_zone_atomically(conn, mission_items, fence_items, rally_items)
        logger.info("zone upload successful")

        # Write snapshot
        snapshot_dir = Path("snapshots/missions") / zone.zone_id
        snapshot_file = snapshot_dir / f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
        _write_zone_snapshot(
            zone.zone_id,
            len(waypoints),
            len(fence_items),
            zone.rally_point,
            snapshot_file,
        )
        logger.info("snapshot written", path=str(snapshot_file))

        typer.echo(f"Zone '{zone.zone_id}' selected successfully")
        typer.echo(f"  Waypoints: {len(waypoints)}")
        typer.echo(f"  Fence vertices: {len(fence_items)}")
        typer.echo(f"  Rally point: {zone.rally_point.lat:.6f}, {zone.rally_point.lon:.6f}")
        typer.echo(f"  Snapshot: {snapshot_file}")


@zone_app.command("resume")  
def resume_zone(
    zone_file: Path = typer.Argument(..., help="Zone YAML file to resume"),
    mavlink_endpoint: str = typer.Option(
        "udp:127.0.0.1:14550", 
        "--mavlink", 
        help="MAVLink connection endpoint"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show info only, don't change mission index"),
) -> None:
    """Resume mission from current waypoint.
    
    Reads MISSION_CURRENT from FC, displays resume info, and sets mission index.
    Does NOT arm or change mode - operator uses RC transmitter for that.
    """
    logger.info("zone resume starting", zone_file=str(zone_file))
    
    # Load zone for display info
    try:
        zone = load_zone_config(zone_file)
    except Exception as e:
        typer.echo(f"Failed to load zone config: {e}")
        raise typer.Exit(1)
    
    # Connect to FC and get current mission state
    config = ConnectionConfig(endpoint=mavlink_endpoint)
    with open_link(config) as conn:
        # Download current mission to get total count
        mission_items = download_mission(conn, mission_type=0)
        total_waypoints = len([item for item in mission_items
                             if item.command == 16])  # NAV_WAYPOINT

        # Get current mission index
        msg = conn.recv_match(type="MISSION_CURRENT", blocking=True, timeout=5)
        if not msg:
            typer.echo("Could not read current mission state")
            raise typer.Exit(1)

        current_seq = msg.seq

        typer.echo(f"Zone: {zone.name} ({zone.zone_id})")
        typer.echo(f"  Current waypoint: {current_seq}")
        typer.echo(f"  Total waypoints: {total_waypoints}")
        typer.echo(f"  Progress: {current_seq}/{total_waypoints}")

        if dry_run:
            typer.echo("DRY RUN - Would resume from current position")
            return

        # Confirm resume
        if current_seq >= total_waypoints:
            typer.echo("Mission complete - nothing to resume")
            return

        proceed = typer.confirm(f"Resume {zone.zone_id} from waypoint {current_seq + 1}?")
        if not proceed:
            typer.echo("Resume cancelled")
            return

        # Set mission index (MISSION_SET_CURRENT)
        conn.mav.mission_set_current_send(
            conn.target_system,
            conn.target_component,
            current_seq,
        )

        logger.info("mission resume index set", seq=current_seq)
        typer.echo(f"Mission index set to {current_seq}")
        typer.echo("  Use RC transmitter to arm and set Auto mode")


# ------------------------------------------------------------------
# Mission planning commands
# ------------------------------------------------------------------


@mission_app.command("plan")
def plan_mission(
    zone_file: Path = typer.Argument(..., help="Zone YAML file to plan"),
    output_dir: Path = typer.Option(
        Path("zones/generated"), 
        "--output-dir", 
        help="Output directory for generated files"
    ),
) -> None:
    """Generate waypoints and write ArduPilot .waypoints file.
    
    Runs the coverage planner and outputs mission in QGroundControl format.
    """
    logger.info("mission planning starting", zone_file=str(zone_file))
    
    # Load zone config
    try:
        zone = load_zone_config(zone_file)
        logger.info("loaded zone config", zone_id=zone.zone_id)
    except Exception as e:
        typer.echo(f"Failed to load zone config: {e}")
        raise typer.Exit(1)
    
    # Generate waypoints
    try:
        waypoints = generate_waypoints(zone)
        logger.info("waypoints generated", count=len(waypoints))
    except Exception as e:
        typer.echo(f"Waypoint generation failed: {e}")
        raise typer.Exit(1)
    
    if not waypoints:
        typer.echo("No waypoints generated - zone may be too small")
        raise typer.Exit(1)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate output filename
    output_file = output_dir / f"{zone.zone_id}.waypoints"
    
    # Write QGroundControl format
    with output_file.open("w", encoding="utf-8") as f:
        f.write("QGC WPL 110\n")  # QGroundControl waypoints header
        
        # Home position (seq 0)
        f.write(f"0\t1\t0\t16\t0\t0\t0\t0\t{zone.home.lat:.8f}\t{zone.home.lon:.8f}\t0\t1\n")
        
        # Waypoints (seq 1+)
        for i, wp in enumerate(waypoints, 1):
            f.write(f"{i}\t0\t0\t16\t0\t0\t0\t0\t{wp.lat:.8f}\t{wp.lon:.8f}\t0\t1\n")
    
    logger.info("waypoints file written", path=str(output_file))
    typer.echo("Mission planned successfully")
    typer.echo(f"  Zone: {zone.name} ({zone.zone_id})")
    typer.echo(f"  Waypoints: {len(waypoints)}")
    typer.echo(f"  Output: {output_file}")


@mission_app.command("export-map")
def export_map(
    zones_dir: Path = typer.Option(
        Path("zones"), 
        "--zones-dir", 
        help="Directory containing zone YAML files"
    ),
    output: Path = typer.Option(
        Path("zones/generated/map.geojson"), 
        "--output", 
        help="Output GeoJSON file path"
    ),
) -> None:
    """Export all zones as a combined GeoJSON map.
    
    Creates a GeoJSON file containing boundaries, exclusions, home points,
    and rally points for all zones. Suitable for loading in QGIS or web maps.
    Coverage paths are not included in multi-zone export.
    """
    logger.info("exporting zone map", zones_dir=str(zones_dir), output=str(output))
    
    # Load all zones
    try:
        zones = load_all_zones(zones_dir)
    except Exception as e:
        typer.echo(f"Error loading zones: {e}", err=True)
        raise typer.Exit(1)
    
    if not zones:
        typer.echo("No zones found in directory", err=True)
        raise typer.Exit(1)
    
    # Export to GeoJSON
    try:
        geojson = export_multi_zone_geojson(zones)
    except Exception as e:
        typer.echo(f"Error exporting GeoJSON: {e}", err=True)
        raise typer.Exit(1)
    
    # Write output file
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(geojson, indent=2) + "\n")
    except Exception as e:
        typer.echo(f"Error writing file: {e}", err=True)
        raise typer.Exit(1)
    
    logger.info("map export complete", 
                zone_count=len(zones), 
                feature_count=len(geojson["features"]), 
                output_path=str(output))
    
    typer.echo(f"Map exported to {output}")
    typer.echo(f"  Zones: {len(zones)}")
    typer.echo(f"  Features: {len(geojson['features'])}")
    
    zone_names = [zone.name for zone in zones]
    typer.echo(f"  Included: {', '.join(zone_names)}")