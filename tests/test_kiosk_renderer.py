"""Integration tests for kiosk data service socket behavior.

Tests validate the Unix socket server in run_kiosk():
- Client connects and receives length-prefixed JSON frames
- Client reconnects after server restart
- Server exits cleanly on shutdown signal within 2s
- Socket file is cleaned up on exit

Tests that exercise the Python data service directly run locally
(no Jetson required). Tests that require the LVGL renderer binary
running under Weston are marked @pytest.mark.jetson.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

from mower_rover.kiosk.app import run_kiosk
from mower_rover.kiosk.state import SharedState

# Skip entire module on Windows — AF_UNIX not available
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix domain sockets not available on Windows",
)


@pytest.fixture()
def sock_path(tmp_path: Path) -> str:
    """Return a temporary Unix socket path."""
    return str(tmp_path / "kiosk-test.sock")


def _read_frame(client: socket.socket) -> dict:
    """Read one length-prefixed JSON frame from the socket."""
    # Read 4-byte little-endian length prefix
    header = b""
    while len(header) < 4:
        chunk = client.recv(4 - len(header))
        if not chunk:
            raise ConnectionError("Socket closed before header received")
        header += chunk
    length = struct.unpack("<I", header)[0]
    # Read payload
    payload = b""
    while len(payload) < length:
        chunk = client.recv(length - len(payload))
        if not chunk:
            raise ConnectionError("Socket closed before payload received")
        payload += chunk
    return json.loads(payload)


class TestDataServiceSocket:
    """Tests for the kiosk data service Unix socket server."""

    def test_data_service_accepts_connection_and_sends_frames(
        self, sock_path: str
    ) -> None:
        """Data service starts, accepts a client, and pushes JSON frames."""
        shutdown = threading.Event()
        state = SharedState()
        state.update_mav(armed=True, mode="AUTO", groundspeed_ms=2.5)

        server_thread = threading.Thread(
            target=run_kiosk,
            kwargs={
                "_shutdown_event": shutdown,
                "_state": state,
                "_socket_path": sock_path,
            },
            daemon=True,
        )
        server_thread.start()

        # Wait for socket to appear
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)
        else:
            shutdown.set()
            pytest.fail("Socket file never appeared")

        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(5.0)
            client.connect(sock_path)

            # Read at least one frame
            frame = _read_frame(client)
            assert "mav" in frame
            assert frame["mav"]["armed"] is True
            assert frame["mav"]["mode"] == "AUTO"
            client.close()
        finally:
            shutdown.set()
            server_thread.join(timeout=5.0)

    def test_renderer_survives_data_restart(self, sock_path: str) -> None:
        """Client can reconnect after the data service restarts."""
        shutdown1 = threading.Event()
        state1 = SharedState()
        state1.update_mav(mode="MANUAL")

        # Start first server instance
        t1 = threading.Thread(
            target=run_kiosk,
            kwargs={
                "_shutdown_event": shutdown1,
                "_state": state1,
                "_socket_path": sock_path,
            },
            daemon=True,
        )
        t1.start()

        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        # Connect and read a frame
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5.0)
        client.connect(sock_path)
        frame1 = _read_frame(client)
        assert frame1["mav"]["mode"] == "MANUAL"
        client.close()

        # Shutdown first server
        shutdown1.set()
        t1.join(timeout=5.0)

        # Start second server instance with new state
        shutdown2 = threading.Event()
        state2 = SharedState()
        state2.update_mav(mode="AUTO")

        t2 = threading.Thread(
            target=run_kiosk,
            kwargs={
                "_shutdown_event": shutdown2,
                "_state": state2,
                "_socket_path": sock_path,
            },
            daemon=True,
        )
        t2.start()

        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        try:
            # Reconnect and verify new data
            client2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client2.settimeout(5.0)
            client2.connect(sock_path)
            frame2 = _read_frame(client2)
            assert frame2["mav"]["mode"] == "AUTO"
            client2.close()
        finally:
            shutdown2.set()
            t2.join(timeout=5.0)

    def test_data_service_clean_shutdown(self, sock_path: str) -> None:
        """Data service exits cleanly within 2s of shutdown signal; socket removed."""
        shutdown = threading.Event()
        state = SharedState()

        server_thread = threading.Thread(
            target=run_kiosk,
            kwargs={
                "_shutdown_event": shutdown,
                "_state": state,
                "_socket_path": sock_path,
            },
            daemon=True,
        )
        server_thread.start()

        # Wait for socket
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)
        else:
            shutdown.set()
            pytest.fail("Socket file never appeared")

        # Signal shutdown
        shutdown.set()
        server_thread.join(timeout=2.0)

        assert not server_thread.is_alive(), "Server did not exit within 2s"
        assert not os.path.exists(sock_path), "Socket file not cleaned up"


@pytest.mark.jetson
class TestKioskRendererOnDevice:
    """Integration tests requiring Jetson + Weston + LVGL renderer binary.

    These tests validate that the compiled LVGL renderer binary connects
    to the data service socket and displays data. They require:
    - Weston compositor running
    - mower-kiosk-renderer binary installed
    - mower-kiosk-data.service available
    """

    def test_renderer_connects_to_data_service(self) -> None:
        """LVGL renderer binary connects and stays alive with data service."""
        pytest.skip("Requires Jetson hardware with Weston and renderer binary")

    def test_renderer_survives_data_service_restart(self) -> None:
        """LVGL renderer reconnects after data service is restarted."""
        pytest.skip("Requires Jetson hardware with Weston and renderer binary")

    def test_renderer_clean_shutdown_on_sigterm(self) -> None:
        """Renderer exits 0 within 2s of SIGTERM."""
        pytest.skip("Requires Jetson hardware with Weston and renderer binary")
