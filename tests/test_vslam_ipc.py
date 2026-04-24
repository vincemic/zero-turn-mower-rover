"""Tests for VSLAM IPC wire format and PoseReader — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mower_rover.vslam.ipc import (
    POSE_STRUCT_FMT,
    POSE_STRUCT_SIZE,
    PoseMessage,
    PoseReader,
)

# ------------------------------------------------------------------
# Wire format constants
# ------------------------------------------------------------------


def test_struct_size_is_118() -> None:
    assert POSE_STRUCT_SIZE == 118


def test_struct_format_matches_header() -> None:
    assert POSE_STRUCT_FMT == "<Q27fBB"


# ------------------------------------------------------------------
# PoseMessage.from_bytes / to_bytes round-trip
# ------------------------------------------------------------------


def _make_sample_msg() -> PoseMessage:
    return PoseMessage(
        timestamp_us=1_000_000,
        x=1.0,
        y=2.0,
        z=3.0,
        roll=0.1,
        pitch=0.2,
        yaw=0.3,
        covariance=tuple(float(i) for i in range(21)),
        confidence=85,
        reset_counter=2,
    )


class TestPoseMessageRoundTrip:
    def test_to_bytes_length(self) -> None:
        msg = _make_sample_msg()
        assert len(msg.to_bytes()) == 118

    def test_round_trip(self) -> None:
        original = _make_sample_msg()
        raw = original.to_bytes()
        restored = PoseMessage.from_bytes(raw)
        assert restored.timestamp_us == original.timestamp_us
        assert restored.x == pytest.approx(original.x)
        assert restored.y == pytest.approx(original.y)
        assert restored.z == pytest.approx(original.z)
        assert restored.roll == pytest.approx(original.roll)
        assert restored.pitch == pytest.approx(original.pitch)
        assert restored.yaw == pytest.approx(original.yaw)
        assert len(restored.covariance) == 21
        for i in range(21):
            assert restored.covariance[i] == pytest.approx(original.covariance[i])
        assert restored.confidence == original.confidence
        assert restored.reset_counter == original.reset_counter

    def test_from_bytes_wrong_length_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected 118"):
            PoseMessage.from_bytes(b"\x00" * 100)

    def test_zero_message(self) -> None:
        msg = PoseMessage(
            timestamp_us=0,
            x=0.0,
            y=0.0,
            z=0.0,
            roll=0.0,
            pitch=0.0,
            yaw=0.0,
            covariance=tuple(0.0 for _ in range(21)),
            confidence=0,
            reset_counter=0,
        )
        restored = PoseMessage.from_bytes(msg.to_bytes())
        assert restored.timestamp_us == 0
        assert restored.confidence == 0

    def test_max_confidence_and_reset(self) -> None:
        msg = PoseMessage(
            timestamp_us=2**63,
            x=0.0,
            y=0.0,
            z=0.0,
            roll=0.0,
            pitch=0.0,
            yaw=0.0,
            covariance=tuple(0.0 for _ in range(21)),
            confidence=255,
            reset_counter=255,
        )
        restored = PoseMessage.from_bytes(msg.to_bytes())
        assert restored.confidence == 255
        assert restored.reset_counter == 255


# ------------------------------------------------------------------
# PoseMessage field access
# ------------------------------------------------------------------


class TestPoseMessageFields:
    def test_covariance_length(self) -> None:
        msg = _make_sample_msg()
        assert len(msg.covariance) == 21

    def test_frozen(self) -> None:
        msg = _make_sample_msg()
        with pytest.raises(AttributeError):
            msg.x = 999.0  # type: ignore[misc]


# ------------------------------------------------------------------
# PoseReader with mock socket
# ------------------------------------------------------------------


class TestPoseReader:
    """Test PoseReader using mock sockets (works on Windows)."""

    def test_reads_one_message(self) -> None:
        sample = _make_sample_msg()
        raw = sample.to_bytes()

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [raw, b""]  # one full message, then EOF

        reader = PoseReader("/tmp/fake.sock")

        with patch.object(reader, "_connect", return_value=mock_sock):
            poses = []
            for msg in reader.read_poses():
                poses.append(msg)
                break  # stop after first message

            assert len(poses) == 1
            assert poses[0].timestamp_us == sample.timestamp_us
            assert poses[0].x == pytest.approx(sample.x)

    def test_reads_multiple_messages(self) -> None:
        msg1 = _make_sample_msg()
        msg2 = PoseMessage(
            timestamp_us=2_000_000,
            x=4.0,
            y=5.0,
            z=6.0,
            roll=0.4,
            pitch=0.5,
            yaw=0.6,
            covariance=tuple(float(i + 21) for i in range(21)),
            confidence=90,
            reset_counter=3,
        )

        mock_sock = MagicMock()
        # Deliver each message as a separate recv — mirrors real socket behavior
        # where recv(n) returns at most n bytes.
        mock_sock.recv.side_effect = [msg1.to_bytes(), msg2.to_bytes(), b""]

        reader = PoseReader("/tmp/fake.sock")
        with patch.object(reader, "_connect", return_value=mock_sock):
            poses = []
            for msg in reader.read_poses():
                poses.append(msg)
                if len(poses) >= 2:
                    break

            assert len(poses) == 2
            assert poses[0].timestamp_us == 1_000_000
            assert poses[1].timestamp_us == 2_000_000
            assert poses[1].x == pytest.approx(4.0)

    def test_handles_partial_recv(self) -> None:
        """Simulate receiving data in small chunks."""
        sample = _make_sample_msg()
        raw = sample.to_bytes()
        # Split into 10-byte chunks
        chunks = [raw[i : i + 10] for i in range(0, len(raw), 10)]

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = chunks + [b""]

        reader = PoseReader("/tmp/fake.sock")
        with patch.object(reader, "_connect", return_value=mock_sock):
            poses = []
            for msg in reader.read_poses():
                poses.append(msg)
                break

            assert len(poses) == 1
            assert poses[0].timestamp_us == sample.timestamp_us

    def test_reconnects_on_connection_error(self) -> None:
        """Verify reconnection after socket loss."""
        sample = _make_sample_msg()
        raw = sample.to_bytes()

        mock_sock_fail = MagicMock()
        mock_sock_fail.recv.side_effect = ConnectionError("broken pipe")

        mock_sock_ok = MagicMock()
        mock_sock_ok.recv.side_effect = [raw, b""]

        reader = PoseReader("/tmp/fake.sock", reconnect_delay_s=0.01)
        connect_count = 0

        def mock_connect() -> MagicMock:
            nonlocal connect_count
            connect_count += 1
            if connect_count == 1:
                return mock_sock_fail
            return mock_sock_ok

        with patch.object(reader, "_connect", side_effect=mock_connect):
            poses = []
            for msg in reader.read_poses():
                poses.append(msg)
                break

            assert connect_count >= 2
            assert len(poses) == 1

    def test_close(self) -> None:
        reader = PoseReader("/tmp/fake.sock")
        mock_sock = MagicMock()
        reader._sock = mock_sock
        reader.close()
        mock_sock.close.assert_called_once()
        assert reader._sock is None
