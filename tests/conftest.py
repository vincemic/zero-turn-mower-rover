"""Shared pytest fixtures.

The `sitl_endpoint` fixture spawns ArduPilot SITL (rover-skid frame) with
`--instance` derived from `pytest-xdist` worker id for port isolation, waits
for a heartbeat, and yields the MAVLink endpoint string. Skips automatically
if `sim_vehicle.py` is not on PATH.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator

import pytest


def _instance_for_worker() -> int:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    digits = "".join(c for c in worker if c.isdigit())
    return int(digits) if digits else 0


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def sitl_endpoint() -> Iterator[str]:
    sim = shutil.which("sim_vehicle.py")
    if sim is None:
        pytest.skip(
            "sim_vehicle.py not on PATH; install ArduPilot SITL to run @pytest.mark.sitl tests"
        )

    instance = _instance_for_worker()
    # ArduPilot SITL UDP base port: 14550 + 10*instance for ground stations.
    port = 14550 + 10 * instance

    proc = subprocess.Popen(
        [
            sim,
            "--vehicle", "Rover",
            "--frame", "rover-skid",
            "--instance", str(instance),
            "--no-mavproxy",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    endpoint = f"udp:127.0.0.1:{port}"
    deadline = time.monotonic() + 60.0
    try:
        # We can't easily probe UDP for liveness; wait briefly for SITL to come up.
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"sim_vehicle.py exited early with code {proc.returncode}")
            time.sleep(1.0)
            # Cheap proxy: SITL also opens a TCP port at 5760 + 10*instance.
            if _port_open("127.0.0.1", 5760 + 10 * instance):
                break
        else:
            pytest.fail("SITL did not start within 60 s")

        yield endpoint
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
