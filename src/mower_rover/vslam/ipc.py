"""IPC reader for VSLAM pose messages over Unix domain socket.

The C++ RTAB-Map node sends fixed-size ``vslam_pose_msg`` structs (118
bytes each, see ``contrib/rtabmap_slam_node/include/vslam_pose_msg.h``)
on a stream-oriented Unix socket.  ``PoseReader`` connects, reads
complete messages, and yields ``PoseMessage`` dataclass instances.

On socket loss the reader backs off and reconnects automatically so the
bridge loop can keep running even if the SLAM node restarts.
"""

from __future__ import annotations

import contextlib
import socket
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass

from mower_rover.logging_setup.setup import get_logger

# Wire format: little-endian uint64 + 27 floats + 2 uint8
POSE_STRUCT_FMT = "<Q27fBB"
POSE_STRUCT_SIZE = struct.calcsize(POSE_STRUCT_FMT)  # 118 bytes

assert POSE_STRUCT_SIZE == 118, f"Expected 118, got {POSE_STRUCT_SIZE}"


@dataclass(frozen=True, slots=True)
class PoseMessage:
    """One pose sample from the SLAM node."""

    timestamp_us: int
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float
    covariance: tuple[float, ...]  # 21 upper-triangle floats
    confidence: int
    reset_counter: int

    @classmethod
    def from_bytes(cls, data: bytes) -> PoseMessage:
        """Unpack a 118-byte buffer into a ``PoseMessage``."""
        if len(data) != POSE_STRUCT_SIZE:
            raise ValueError(
                f"Expected {POSE_STRUCT_SIZE} bytes, got {len(data)}"
            )
        fields = struct.unpack(POSE_STRUCT_FMT, data)
        return cls(
            timestamp_us=fields[0],
            x=fields[1],
            y=fields[2],
            z=fields[3],
            roll=fields[4],
            pitch=fields[5],
            yaw=fields[6],
            covariance=tuple(fields[7:28]),
            confidence=fields[28],
            reset_counter=fields[29],
        )

    def to_bytes(self) -> bytes:
        """Pack back to the wire format (useful for tests)."""
        return struct.pack(
            POSE_STRUCT_FMT,
            self.timestamp_us,
            self.x,
            self.y,
            self.z,
            self.roll,
            self.pitch,
            self.yaw,
            *self.covariance,
            self.confidence,
            self.reset_counter,
        )


class PoseReader:
    """Connects to the SLAM node's Unix socket and yields ``PoseMessage`` objects.

    Parameters
    ----------
    socket_path:
        Filesystem path of the Unix domain socket.
    reconnect_delay_s:
        Seconds to wait before reconnecting after a socket error.
    """

    def __init__(
        self,
        socket_path: str,
        *,
        reconnect_delay_s: float = 1.0,
    ) -> None:
        self._socket_path = socket_path
        self._reconnect_delay_s = reconnect_delay_s
        self._sock: socket.socket | None = None
        self._log = get_logger("vslam.ipc").bind(socket_path=socket_path)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _connect(self) -> socket.socket:
        """Create and connect a new Unix stream socket."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self._log.info("socket_connected")
        return sock

    def _close(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        """Read exactly *n* bytes from the socket, raising on EOF."""
        buf = bytearray()
        assert self._sock is not None
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket EOF")
            buf.extend(chunk)
        return bytes(buf)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_poses(self) -> Iterator[PoseMessage]:
        """Yield pose messages forever, reconnecting on failure.

        This is a blocking infinite iterator.  The caller (bridge loop)
        should catch ``KeyboardInterrupt`` or use a shutdown event to
        break out.
        """
        while True:
            try:
                self._close()
                self._sock = self._connect()
                while True:
                    raw = self._recv_exact(POSE_STRUCT_SIZE)
                    yield PoseMessage.from_bytes(raw)
            except (OSError, ConnectionError) as exc:
                self._log.warning("socket_error", error=str(exc))
                self._close()
                time.sleep(self._reconnect_delay_s)

    def close(self) -> None:
        """Tear down the socket."""
        self._close()
