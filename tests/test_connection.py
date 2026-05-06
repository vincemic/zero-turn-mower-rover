"""Tests for mower_rover.mavlink.connection — open_link shutdown_event support."""

from __future__ import annotations

import threading

import pytest

from mower_rover.mavlink.connection import ConnectionConfig, open_link


class TestOpenLinkShutdownEvent:
    def test_raises_immediately_when_event_already_set(self) -> None:
        """open_link() should raise ConnectionError without waiting for heartbeat."""
        event = threading.Event()
        event.set()

        config = ConnectionConfig(
            endpoint="udp:127.0.0.1:19999",
            heartbeat_timeout_s=30.0,
            retry_attempts=5,
        )

        with pytest.raises(ConnectionError, match="shutdown"):
            with open_link(config, shutdown_event=event):
                pass  # should never reach here

    def test_raises_during_retry_backoff(self) -> None:
        """open_link() should abort during retry sleep when event is set."""
        event = threading.Event()

        config = ConnectionConfig(
            endpoint="udp:127.0.0.1:19999",
            heartbeat_timeout_s=0.1,
            retry_attempts=3,
            retry_backoff_s=10.0,  # long backoff — event should interrupt it
        )

        # Set the event after a short delay to interrupt during backoff
        timer = threading.Timer(0.3, event.set)
        timer.start()

        try:
            with pytest.raises(ConnectionError, match="shutdown"):
                with open_link(config, shutdown_event=event):
                    pass
        finally:
            timer.cancel()
