"""Unit tests for MAVLink mission protocol and zone conversion."""

from __future__ import annotations

import pytest
from unittest.mock import Mock, MagicMock, call
from dataclasses import dataclass
from typing import Any

from mower_rover.mavlink.mission import (
    MissionItem, 
    upload_mission, 
    download_mission, 
    clear_mission,
    verify_round_trip,
    MissionUploadError,
    MissionDownloadError
)
from mower_rover.zone.mission_items import (
    zone_to_mission, 
    zone_to_fence, 
    zone_to_rally,
    _latlng_to_int32
)
from mower_rover.zone.config import (
    ZoneConfig, 
    LatLon, 
    RallyPoint, 
    ExclusionZone,
    CoverageParams,
    MissionCommands
)


class TestMissionItem:
    """Test MissionItem dataclass."""
    
    def test_mission_item_creation(self):
        """Test basic MissionItem creation."""
        item = MissionItem(
            seq=0,
            frame=5,
            command=16,
            param1=1.0,
            x=123456789,
            y=987654321,
            z=0.0,
            mission_type=0
        )
        
        assert item.seq == 0
        assert item.frame == 5
        assert item.command == 16
        assert item.param1 == 1.0
        assert item.x == 123456789
        assert item.y == 987654321
        assert item.mission_type == 0
        assert item.autocontinue == 1  # default
        assert item.current == 0  # default


class TestCoordinateEncoding:
    """Test lat/lon to int32 conversion."""
    
    def test_latlng_to_int32(self):
        """Test coordinate encoding matches MAVLink spec."""
        # Test typical coordinates
        lat, lon = 45.12345678, -122.98765432
        x, y = _latlng_to_int32(lat, lon)
        
        expected_x = int(45.12345678 * 1e7)
        expected_y = int(-122.98765432 * 1e7)
        
        assert x == expected_x
        assert y == expected_y
    
    def test_latlng_precision(self):
        """Test precision of coordinate encoding."""
        # Should handle 7 decimal places precisely
        lat, lon = 45.1234567, -122.9876543
        x, y = _latlng_to_int32(lat, lon)
        
        # Convert back to verify precision
        recovered_lat = x / 1e7
        recovered_lon = y / 1e7
        
        assert abs(recovered_lat - lat) < 1e-7
        assert abs(recovered_lon - lon) < 1e-7


class TestZoneToMissionConversion:
    """Test zone configuration to mission item conversion."""
    
    @pytest.fixture
    def sample_zone(self) -> ZoneConfig:
        """Create a sample zone configuration."""
        return ZoneConfig(
            schema="zone-v1",
            zone_id="test-zone",
            name="Test Zone",
            home=LatLon(lat=45.0, lon=-122.0),
            rally_point=RallyPoint(lat=45.001, lon=-122.001, description="Rally"),
            boundary=[
                LatLon(lat=45.0, lon=-122.0),
                LatLon(lat=45.001, lon=-122.0),
                LatLon(lat=45.001, lon=-122.001),
                LatLon(lat=45.0, lon=-122.001),
            ],
            exclusion_zones=[
                ExclusionZone(
                    name="tree",
                    buffer_m=2.0,
                    polygon=[
                        LatLon(lat=45.0005, lon=-122.0005),
                        LatLon(lat=45.0006, lon=-122.0005),
                        LatLon(lat=45.0005, lon=-122.0006),
                    ]
                )
            ],
            coverage=CoverageParams(mow_speed_mps=2.5),
            commands=MissionCommands(
                fence_enable=True,
                resume_dist_m=3.0,
                blade_engage=True
            )
        )
    
    def test_zone_to_mission_basic(self, sample_zone):
        """Test basic zone to mission conversion."""
        waypoints = [
            LatLon(lat=45.0001, lon=-122.0001),
            LatLon(lat=45.0002, lon=-122.0002),
        ]
        
        items = zone_to_mission(sample_zone, waypoints)
        
        # Should have: home + speed + resume + fence + 2 waypoints = 6 items
        assert len(items) == 6
        
        # Check sequence numbers
        assert [item.seq for item in items] == [0, 1, 2, 3, 4, 5]
        
        # Check home waypoint
        home_item = items[0]
        assert home_item.command == 16  # MAV_CMD_NAV_WAYPOINT
        assert home_item.x == int(45.0 * 1e7)
        assert home_item.y == int(-122.0 * 1e7)
        assert home_item.current == 1  # Home is current
        assert home_item.mission_type == 0  # MISSION
        
        # Check speed command
        speed_item = items[1]
        assert speed_item.command == 178  # MAV_CMD_DO_CHANGE_SPEED
        assert speed_item.param1 == 1.0  # Ground speed type
        assert speed_item.param2 == 2.5  # mow_speed_mps
        
        # Check resume distance command
        resume_item = items[2]
        assert resume_item.command == 215  # MAV_CMD_DO_SET_RESUME_REPEAT_DIST
        assert resume_item.param1 == 3.0  # resume_dist_m
        
        # Check fence enable command
        fence_item = items[3]
        assert fence_item.command == 207  # MAV_CMD_DO_FENCE_ENABLE
        assert fence_item.param1 == 1.0  # Enable
        
        # Check waypoint items
        wp1_item = items[4]
        assert wp1_item.command == 16  # MAV_CMD_NAV_WAYPOINT
        assert wp1_item.x == int(45.0001 * 1e7)
        assert wp1_item.y == int(-122.0001 * 1e7)
        assert wp1_item.current == 0
        
        wp2_item = items[5]
        assert wp2_item.command == 16  # MAV_CMD_NAV_WAYPOINT
        assert wp2_item.x == int(45.0002 * 1e7)
        assert wp2_item.y == int(-122.0002 * 1e7)
    
    def test_zone_to_mission_no_fence(self, sample_zone):
        """Test mission conversion with fence disabled."""
        # Disable fence
        zone_no_fence = ZoneConfig(
            schema=sample_zone.schema,
            zone_id=sample_zone.zone_id,
            name=sample_zone.name,
            home=sample_zone.home,
            rally_point=sample_zone.rally_point,
            boundary=sample_zone.boundary,
            coverage=sample_zone.coverage,
            commands=MissionCommands(fence_enable=False, resume_dist_m=3.0)
        )
        
        waypoints = [LatLon(lat=45.0001, lon=-122.0001)]
        items = zone_to_mission(zone_no_fence, waypoints)
        
        # Should have: home + speed + resume + 1 waypoint = 4 items (no fence)
        assert len(items) == 4
        
        # Should not have fence enable command (207)
        commands = [item.command for item in items]
        assert 207 not in commands  # MAV_CMD_DO_FENCE_ENABLE
    
    def test_zone_to_fence(self, sample_zone):
        """Test zone boundary to fence conversion."""
        fence_items = zone_to_fence(sample_zone)
        
        # Should have 4 boundary + 3 exclusion = 7 fence items
        assert len(fence_items) == 7
        
        # Check boundary vertices (inclusion)
        boundary_items = fence_items[:4]
        for i, item in enumerate(boundary_items):
            assert item.seq == i
            assert item.command == 5001  # MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION
            assert item.mission_type == 1  # FENCE
            
            # First vertex should have vertex count in param1
            if i == 0:
                assert item.param1 == 4.0  # 4 boundary vertices
            else:
                assert item.param1 == 0.0
        
        # Check exclusion vertices
        exclusion_items = fence_items[4:7]
        for i, item in enumerate(exclusion_items):
            assert item.seq == i + 4
            assert item.command == 5002  # MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION
            assert item.mission_type == 1  # FENCE
            
            # First vertex of exclusion should have vertex count
            if i == 0:
                assert item.param1 == 3.0  # 3 exclusion vertices
            else:
                assert item.param1 == 0.0
        
        # Check coordinate encoding
        first_boundary = boundary_items[0]
        assert first_boundary.x == int(45.0 * 1e7)
        assert first_boundary.y == int(-122.0 * 1e7)
    
    def test_zone_to_rally(self, sample_zone):
        """Test zone rally point conversion."""
        rally_items = zone_to_rally(sample_zone)
        
        assert len(rally_items) == 1
        
        rally_item = rally_items[0]
        assert rally_item.seq == 0
        assert rally_item.command == 5100  # MAV_CMD_NAV_RALLY_POINT
        assert rally_item.mission_type == 2  # RALLY
        assert rally_item.x == int(45.001 * 1e7)
        assert rally_item.y == int(-122.001 * 1e7)


class TestMissionProtocol:
    """Test MAVLink mission protocol functions with mocked connection."""
    
    @pytest.fixture
    def mock_conn(self):
        """Create a mock MAVLink connection."""
        conn = Mock()
        conn.target_system = 1
        conn.target_component = 1
        conn.mav = Mock()
        return conn
    
    def test_upload_mission_success(self, mock_conn):
        """Test successful mission upload."""
        # Create test mission items
        items = [
            MissionItem(seq=0, frame=5, command=16, x=450000000, y=-1220000000),
            MissionItem(seq=1, frame=5, command=16, x=450010000, y=-1220010000),
        ]
        
        # Mock message sequence: MISSION_REQUEST_INT for each item, then MISSION_ACK
        request_msg_1 = Mock()
        request_msg_1.get_type.return_value = 'MISSION_REQUEST_INT'
        request_msg_1.seq = 0
        
        request_msg_2 = Mock()
        request_msg_2.get_type.return_value = 'MISSION_REQUEST_INT'
        request_msg_2.seq = 1
        
        ack_msg = Mock()
        ack_msg.get_type.return_value = 'MISSION_ACK'
        ack_msg.type = 0  # MAV_MISSION_ACCEPTED
        
        # Simulate message receive sequence
        mock_conn.recv_match.side_effect = [
            request_msg_1,
            request_msg_2,
            ack_msg
        ]
        
        # Should not raise exception
        upload_mission(mock_conn, items, mission_type=0)
        
        # Verify protocol calls
        mock_conn.mav.mission_count_send.assert_called_once_with(
            1, 1, 2, 0  # target_system, target_component, count, mission_type
        )
        
        # Should send mission items for requested sequences
        assert mock_conn.mav.mission_item_int_send.call_count == 2
    
    def test_upload_mission_rejected(self, mock_conn):
        """Test mission upload rejection."""
        items = [MissionItem(seq=0, frame=5, command=16)]
        
        # Mock MISSION_ACK with rejection
        ack_msg = Mock()
        ack_msg.get_type.return_value = 'MISSION_ACK'
        ack_msg.type = 1  # MAV_MISSION_ERROR
        
        mock_conn.recv_match.return_value = ack_msg
        
        with pytest.raises(MissionUploadError, match="rejected with ACK type 1"):
            upload_mission(mock_conn, items, mission_type=0)
    
    def test_upload_mission_empty(self, mock_conn):
        """Test uploading empty mission list."""
        # Should handle empty list gracefully
        upload_mission(mock_conn, [], mission_type=0)
        
        # Should not send any MAVLink messages
        mock_conn.mav.mission_count_send.assert_not_called()
    
    def test_download_mission_success(self, mock_conn):
        """Test successful mission download."""
        # Mock MISSION_COUNT response
        count_msg = Mock()
        count_msg.mission_type = 0
        count_msg.count = 2
        
        # Mock MISSION_ITEM_INT responses
        item_msg_1 = Mock()
        item_msg_1.seq = 0
        item_msg_1.mission_type = 0
        item_msg_1.frame = 5
        item_msg_1.command = 16
        item_msg_1.param1 = 0.0
        item_msg_1.param2 = 0.0
        item_msg_1.param3 = 0.0
        item_msg_1.param4 = 0.0
        item_msg_1.x = 450000000
        item_msg_1.y = -1220000000
        item_msg_1.z = 0.0
        item_msg_1.autocontinue = 1
        item_msg_1.current = 1
        
        item_msg_2 = Mock()
        item_msg_2.seq = 1
        item_msg_2.mission_type = 0
        item_msg_2.frame = 5
        item_msg_2.command = 16
        item_msg_2.param1 = 0.0
        item_msg_2.param2 = 0.0
        item_msg_2.param3 = 0.0
        item_msg_2.param4 = 0.0
        item_msg_2.x = 450010000
        item_msg_2.y = -1220010000
        item_msg_2.z = 0.0
        item_msg_2.autocontinue = 1
        item_msg_2.current = 0
        
        # Simulate message receive sequence
        mock_conn.recv_match.side_effect = [
            count_msg,    # MISSION_COUNT
            item_msg_1,   # First MISSION_ITEM_INT
            item_msg_2    # Second MISSION_ITEM_INT
        ]
        
        items = download_mission(mock_conn, mission_type=0)
        
        assert len(items) == 2
        assert items[0].seq == 0
        assert items[0].command == 16
        assert items[0].x == 450000000
        assert items[1].seq == 1
        assert items[1].x == 450010000
        
        # Verify protocol calls
        mock_conn.mav.mission_request_list_send.assert_called_once_with(1, 1, 0)
        assert mock_conn.mav.mission_request_int_send.call_count == 2
        mock_conn.mav.mission_ack_send.assert_called_once_with(1, 1, 0, 0)
    
    def test_download_mission_empty(self, mock_conn):
        """Test downloading empty mission."""
        # Mock MISSION_COUNT with count=0
        count_msg = Mock()
        count_msg.mission_type = 0
        count_msg.count = 0
        
        mock_conn.recv_match.return_value = count_msg
        
        items = download_mission(mock_conn, mission_type=0)
        
        assert len(items) == 0
        mock_conn.mav.mission_request_list_send.assert_called_once()
        # Should not request any items for empty mission
        mock_conn.mav.mission_request_int_send.assert_not_called()
    
    def test_clear_mission_success(self, mock_conn):
        """Test successful mission clear."""
        # Mock MISSION_ACK for clear
        ack_msg = Mock()
        ack_msg.mission_type = 0
        ack_msg.type = 0  # MAV_MISSION_ACCEPTED
        
        # Mock empty mission download for verification
        count_msg = Mock()
        count_msg.mission_type = 0
        count_msg.count = 0
        
        mock_conn.recv_match.side_effect = [ack_msg, count_msg]
        
        clear_mission(mock_conn, mission_type=0)
        
        # Verify clear command sent
        mock_conn.mav.mission_clear_all_send.assert_called_once_with(1, 1, 0)
    
    def test_verify_round_trip_success(self, mock_conn):
        """Test successful round-trip verification."""
        # Create expected items
        expected = [
            MissionItem(seq=0, frame=5, command=16, x=450000000, y=-1220000000),
            MissionItem(seq=1, frame=5, command=16, x=450010000, y=-1220010000),
        ]
        
        # Mock download to return matching items
        count_msg = Mock()
        count_msg.mission_type = 0
        count_msg.count = 2
        
        item_msg_1 = Mock()
        item_msg_1.seq = 0
        item_msg_1.mission_type = 0
        item_msg_1.frame = 5
        item_msg_1.command = 16
        item_msg_1.param1 = 0.0
        item_msg_1.param2 = 0.0
        item_msg_1.param3 = 0.0
        item_msg_1.param4 = 0.0
        item_msg_1.x = 450000000
        item_msg_1.y = -1220000000
        item_msg_1.z = 0.0
        item_msg_1.autocontinue = 1
        item_msg_1.current = 0
        
        item_msg_2 = Mock()
        item_msg_2.seq = 1
        item_msg_2.mission_type = 0
        item_msg_2.frame = 5
        item_msg_2.command = 16
        item_msg_2.param1 = 0.0
        item_msg_2.param2 = 0.0
        item_msg_2.param3 = 0.0
        item_msg_2.param4 = 0.0
        item_msg_2.x = 450010000
        item_msg_2.y = -1220010000
        item_msg_2.z = 0.0
        item_msg_2.autocontinue = 1
        item_msg_2.current = 0
        
        mock_conn.recv_match.side_effect = [count_msg, item_msg_1, item_msg_2]
        
        result = verify_round_trip(mock_conn, expected, mission_type=0)
        
        assert result is True
    
    def test_verify_round_trip_mismatch(self, mock_conn):
        """Test round-trip verification with mismatch."""
        # Create expected items
        expected = [
            MissionItem(seq=0, frame=5, command=16, x=450000000, y=-1220000000),
        ]
        
        # Mock download to return different item
        count_msg = Mock()
        count_msg.mission_type = 0
        count_msg.count = 1
        
        item_msg = Mock()
        item_msg.seq = 0
        item_msg.mission_type = 0
        item_msg.frame = 5
        item_msg.command = 17  # Different command!
        item_msg.param1 = 0.0
        item_msg.param2 = 0.0
        item_msg.param3 = 0.0
        item_msg.param4 = 0.0
        item_msg.x = 450000000
        item_msg.y = -1220000000
        item_msg.z = 0.0
        item_msg.autocontinue = 1
        item_msg.current = 0
        
        mock_conn.recv_match.side_effect = [count_msg, item_msg]
        
        result = verify_round_trip(mock_conn, expected, mission_type=0)
        
        assert result is False