"""MAVLink mission protocol implementation.

Provides upload/download/clear operations for missions, fences, and rally points
using the MAVLink mission protocol (MISSION_COUNT → MISSION_REQUEST_INT → 
MISSION_ITEM_INT → MISSION_ACK handshake).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from mower_rover.logging_setup.setup import get_logger


class MissionUploadError(RuntimeError):
    """Raised when mission upload fails."""


class MissionDownloadError(RuntimeError):
    """Raised when mission download fails."""


@dataclass(frozen=True)
class MissionItem:
    """MAVLink MISSION_ITEM_INT representation.
    
    Matches the MAVLink MISSION_ITEM_INT message field layout for missions,
    fences, and rally points.
    """
    
    seq: int                    # Sequence number
    frame: int                  # Coordinate frame (MAV_FRAME_*)
    command: int                # MAV_CMD_* command ID
    param1: float = 0.0         # Command-specific parameter 1
    param2: float = 0.0         # Command-specific parameter 2  
    param3: float = 0.0         # Command-specific parameter 3
    param4: float = 0.0         # Command-specific parameter 4
    x: int = 0                  # Latitude × 1e7 (int32)
    y: int = 0                  # Longitude × 1e7 (int32)
    z: float = 0.0              # Altitude
    mission_type: int = 0       # 0=MISSION, 1=FENCE, 2=RALLY
    autocontinue: int = 1       # 1 for auto-continue, 0 otherwise
    current: int = 0            # 0 normally, 1 for current waypoint


def upload_mission(conn: Any, items: list[MissionItem], mission_type: int) -> None:
    """Upload mission items using MAVLink mission protocol.
    
    Protocol sequence:
    1. Send MISSION_COUNT with count and mission_type
    2. Wait for MISSION_REQUEST_INT for each seq
    3. Send MISSION_ITEM_INT for requested seq
    4. Repeat until MISSION_ACK received
    5. Check MISSION_ACK type for success (MAV_MISSION_ACCEPTED = 0)
    
    Args:
        conn: MAVLink connection from pymavlink
        items: List of mission items to upload
        mission_type: 0=MISSION, 1=FENCE, 2=RALLY
        
    Raises:
        MissionUploadError: If upload fails or times out
    """
    # Lazy import to keep module importable without pymavlink
    from pymavlink import mavutil
    
    log = get_logger("mavlink.mission").bind(
        mission_type=mission_type, 
        item_count=len(items)
    )
    log.info("Starting mission upload")
    
    if not items:
        log.warning("No items to upload")
        return
        
    # Step 1: Send MISSION_COUNT
    conn.mav.mission_count_send(
        conn.target_system,
        conn.target_component,
        len(items),
        mission_type
    )
    log.debug("Sent MISSION_COUNT", count=len(items))
    
    # Track which items we've sent
    items_sent = set()
    timeout_s = 10.0
    start_time = time.time()
    
    while len(items_sent) < len(items):
        if time.time() - start_time > timeout_s:
            raise MissionUploadError(
                f"Timeout waiting for MISSION_REQUEST_INT after {timeout_s}s"
            )
            
        # Step 2: Wait for MISSION_REQUEST_INT
        msg = conn.recv_match(
            type=['MISSION_REQUEST_INT', 'MISSION_REQUEST', 'MISSION_ACK'], 
            blocking=False
        )
        
        if msg is None:
            time.sleep(0.01)
            continue
            
        if msg.get_type() == 'MISSION_ACK':
            if msg.type == 0:  # MAV_MISSION_ACCEPTED
                log.info("Mission upload successful")
                return
            else:
                raise MissionUploadError(
                    f"Mission upload rejected with ACK type {msg.type}"
                )
                
        if msg.get_type() in ['MISSION_REQUEST_INT', 'MISSION_REQUEST']:
            seq = msg.seq
            
            if seq >= len(items):
                raise MissionUploadError(f"Requested seq {seq} >= item count {len(items)}")
                
            item = items[seq]
            
            # Step 3: Send MISSION_ITEM_INT for requested seq
            conn.mav.mission_item_int_send(
                conn.target_system,
                conn.target_component,
                item.seq,
                item.frame,
                item.command,
                item.current,
                item.autocontinue,
                item.param1,
                item.param2,
                item.param3,
                item.param4,
                item.x,
                item.y,
                item.z,
                item.mission_type
            )
            
            items_sent.add(seq)
            log.debug("Sent MISSION_ITEM_INT", seq=seq, command=item.command)
    
    # Wait for final MISSION_ACK
    ack_timeout = 5.0
    ack_start = time.time()
    
    while time.time() - ack_start < ack_timeout:
        msg = conn.recv_match(type='MISSION_ACK', blocking=False)
        if msg is not None:
            if msg.type == 0:  # MAV_MISSION_ACCEPTED
                log.info("Mission upload completed successfully")
                return
            else:
                raise MissionUploadError(
                    f"Mission upload rejected with final ACK type {msg.type}"
                )
        time.sleep(0.01)
        
    raise MissionUploadError(f"Timeout waiting for final MISSION_ACK after {ack_timeout}s")


def download_mission(conn: Any, mission_type: int) -> list[MissionItem]:
    """Download mission items using MAVLink mission protocol.
    
    Protocol sequence:
    1. Send MISSION_REQUEST_LIST with mission_type
    2. Wait for MISSION_COUNT
    3. For each item: send MISSION_REQUEST_INT, wait for MISSION_ITEM_INT
    4. Send MISSION_ACK when complete
    
    Args:
        conn: MAVLink connection from pymavlink
        mission_type: 0=MISSION, 1=FENCE, 2=RALLY
        
    Returns:
        List of mission items in sequence order
        
    Raises:
        MissionDownloadError: If download fails or times out
    """
    # Lazy import to keep module importable without pymavlink
    from pymavlink import mavutil
    
    log = get_logger("mavlink.mission").bind(mission_type=mission_type)
    log.info("Starting mission download")
    
    # Step 1: Send MISSION_REQUEST_LIST
    conn.mav.mission_request_list_send(
        conn.target_system,
        conn.target_component,
        mission_type
    )
    log.debug("Sent MISSION_REQUEST_LIST")
    
    # Step 2: Wait for MISSION_COUNT
    timeout_s = 10.0
    start_time = time.time()
    
    while time.time() - start_time < timeout_s:
        msg = conn.recv_match(type='MISSION_COUNT', blocking=False)
        if msg is not None and msg.mission_type == mission_type:
            item_count = msg.count
            log.debug("Received MISSION_COUNT", count=item_count)
            break
        time.sleep(0.01)
    else:
        raise MissionDownloadError(
            f"Timeout waiting for MISSION_COUNT after {timeout_s}s"
        )
    
    if item_count == 0:
        log.info("Mission is empty")
        return []
    
    # Step 3: Request each item
    items: list[MissionItem] = [None] * item_count  # type: ignore
    items_received = set()
    
    for seq in range(item_count):
        # Send MISSION_REQUEST_INT for this sequence number
        conn.mav.mission_request_int_send(
            conn.target_system,
            conn.target_component,
            seq,
            mission_type
        )
        log.debug("Sent MISSION_REQUEST_INT", seq=seq)
        
        # Wait for MISSION_ITEM_INT response
        item_timeout = 5.0
        item_start = time.time()
        
        while time.time() - item_start < item_timeout:
            msg = conn.recv_match(type='MISSION_ITEM_INT', blocking=False)
            if msg is not None and msg.seq == seq and msg.mission_type == mission_type:
                # Convert to MissionItem
                item = MissionItem(
                    seq=msg.seq,
                    frame=msg.frame,
                    command=msg.command,
                    param1=msg.param1,
                    param2=msg.param2,
                    param3=msg.param3,
                    param4=msg.param4,
                    x=msg.x,
                    y=msg.y,
                    z=msg.z,
                    mission_type=msg.mission_type,
                    autocontinue=msg.autocontinue,
                    current=msg.current
                )
                items[seq] = item
                items_received.add(seq)
                log.debug("Received MISSION_ITEM_INT", seq=seq, command=item.command)
                break
            time.sleep(0.01)
        else:
            raise MissionDownloadError(
                f"Timeout waiting for MISSION_ITEM_INT seq {seq} after {item_timeout}s"
            )
    
    # Step 4: Send MISSION_ACK to complete the transaction
    conn.mav.mission_ack_send(
        conn.target_system,
        conn.target_component,
        0,  # MAV_MISSION_ACCEPTED
        mission_type
    )
    log.debug("Sent MISSION_ACK")
    
    log.info("Mission download completed successfully", item_count=len(items))
    return items


def clear_mission(conn: Any, mission_type: int) -> None:
    """Clear all mission items of the specified type.
    
    Uses MISSION_CLEAR_ALL with mission_type field.
    Verifies clearance by downloading and checking count.
    
    Args:
        conn: MAVLink connection from pymavlink  
        mission_type: 0=MISSION, 1=FENCE, 2=RALLY
        
    Raises:
        MissionUploadError: If clear operation fails
    """
    # Lazy import to keep module importable without pymavlink
    from pymavlink import mavutil
    
    log = get_logger("mavlink.mission").bind(mission_type=mission_type)
    log.info("Clearing mission")
    
    # Send MISSION_CLEAR_ALL
    conn.mav.mission_clear_all_send(
        conn.target_system,
        conn.target_component,
        mission_type
    )
    log.debug("Sent MISSION_CLEAR_ALL")
    
    # Wait for MISSION_ACK
    timeout_s = 5.0
    start_time = time.time()
    
    while time.time() - start_time < timeout_s:
        msg = conn.recv_match(type='MISSION_ACK', blocking=False)
        if msg is not None and msg.mission_type == mission_type:
            if msg.type == 0:  # MAV_MISSION_ACCEPTED
                log.debug("Received MISSION_ACK for clear")
                break
            else:
                raise MissionUploadError(
                    f"Mission clear rejected with ACK type {msg.type}"
                )
        time.sleep(0.01)
    else:
        raise MissionUploadError(
            f"Timeout waiting for MISSION_ACK after clear operation"
        )
    
    # Verify by downloading - should be empty (or count=1 for mission home)
    try:
        items = download_mission(conn, mission_type)
        if mission_type == 0 and len(items) <= 1:
            # Mission type allows home point (seq 0)
            log.info("Mission cleared successfully", remaining_items=len(items))
        elif mission_type != 0 and len(items) == 0:
            # Fence/rally should be completely empty
            log.info("Mission cleared successfully")
        else:
            raise MissionUploadError(
                f"Clear verification failed: {len(items)} items still present"
            )
    except MissionDownloadError as e:
        raise MissionUploadError(f"Clear verification failed: {e}") from e


def verify_round_trip(
    conn: Any, 
    expected: list[MissionItem], 
    mission_type: int
) -> bool:
    """Download mission items and compare with expected list.
    
    Compares sequence-by-sequence with tolerance for lat/lon precision.
    Logs differences via structlog.
    
    Args:
        conn: MAVLink connection from pymavlink
        expected: Expected mission items
        mission_type: 0=MISSION, 1=FENCE, 2=RALLY
        
    Returns:
        True if downloaded items match expected within tolerance
    """
    log = get_logger("mavlink.mission").bind(
        mission_type=mission_type,
        expected_count=len(expected)
    )
    
    try:
        downloaded = download_mission(conn, mission_type)
    except MissionDownloadError as e:
        log.error("Round-trip verification failed: download error", error=str(e))
        return False
    
    if len(downloaded) != len(expected):
        log.error(
            "Round-trip verification failed: count mismatch",
            expected_count=len(expected),
            downloaded_count=len(downloaded)
        )
        return False
    
    # Compare each item
    tolerance = 1e-7  # For lat/lon integer encoding precision
    mismatches = []
    
    for i, (exp, got) in enumerate(zip(expected, downloaded)):
        if exp.seq != got.seq:
            mismatches.append(f"seq[{i}]: expected {exp.seq}, got {got.seq}")
        if exp.frame != got.frame:
            mismatches.append(f"frame[{i}]: expected {exp.frame}, got {got.frame}")
        if exp.command != got.command:
            mismatches.append(f"command[{i}]: expected {exp.command}, got {got.command}")
        if abs(exp.param1 - got.param1) > tolerance:
            mismatches.append(f"param1[{i}]: expected {exp.param1}, got {got.param1}")
        if abs(exp.param2 - got.param2) > tolerance:
            mismatches.append(f"param2[{i}]: expected {exp.param2}, got {got.param2}")
        if abs(exp.param3 - got.param3) > tolerance:
            mismatches.append(f"param3[{i}]: expected {exp.param3}, got {got.param3}")
        if abs(exp.param4 - got.param4) > tolerance:
            mismatches.append(f"param4[{i}]: expected {exp.param4}, got {got.param4}")
        if exp.x != got.x:  # int32 should match exactly
            mismatches.append(f"x[{i}]: expected {exp.x}, got {got.x}")
        if exp.y != got.y:  # int32 should match exactly  
            mismatches.append(f"y[{i}]: expected {exp.y}, got {got.y}")
        if abs(exp.z - got.z) > tolerance:
            mismatches.append(f"z[{i}]: expected {exp.z}, got {got.z}")
        if exp.mission_type != got.mission_type:
            mismatches.append(f"mission_type[{i}]: expected {exp.mission_type}, got {got.mission_type}")
        if exp.autocontinue != got.autocontinue:
            mismatches.append(f"autocontinue[{i}]: expected {exp.autocontinue}, got {got.autocontinue}")
        if exp.current != got.current:
            mismatches.append(f"current[{i}]: expected {exp.current}, got {got.current}")
    
    if mismatches:
        log.error(
            "Round-trip verification failed: field mismatches",
            mismatches=mismatches[:10]  # Limit log spam
        )
        return False
    
    log.info("Round-trip verification passed")
    return True