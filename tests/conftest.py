"""Shared pytest fixtures.

The `sitl_endpoint` fixture spawns ArduPilot SITL (rover-skid frame) with
`--instance` derived from `pytest-xdist` worker id for port isolation, waits
for a heartbeat, and yields the MAVLink endpoint string. Skips automatically
if `sim_vehicle.py` is not on PATH.

The `fake_sysroot` fixture creates a minimal Jetson-like filesystem tree under
``tmp_path`` for probe and health tests. Per-test fixtures in individual test
modules remain for edge cases; this fixture provides a standard happy-path layout.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared fake sysfs fixture — Jetson-like filesystem tree
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_sysroot(tmp_path: Path) -> Path:
    """Create a minimal Jetson-like sysfs tree under *tmp_path*.

    Provides happy-path files for probe checks and health readers.
    Works on Windows and Linux alike (everything under tmp_path).
    """
    # /etc/nv_tegra_release — JetPack / L4T version
    etc = tmp_path / "etc"
    etc.mkdir(parents=True)
    (etc / "nv_tegra_release").write_text(
        "# R36 (release), REVISION: 4.4, GCID: 36191598, BOARD: generic, EABI: aarch64\n",
        encoding="utf-8",
    )

    # Thermal zones
    thermal_base = tmp_path / "sys" / "class" / "thermal"
    zone0 = thermal_base / "thermal_zone0"
    zone0.mkdir(parents=True)
    (zone0 / "temp").write_text("45000\n", encoding="utf-8")
    (zone0 / "type").write_text("CPU-therm\n", encoding="utf-8")

    zone1 = thermal_base / "thermal_zone1"
    zone1.mkdir(parents=True)
    (zone1 / "temp").write_text("52500\n", encoding="utf-8")
    (zone1 / "type").write_text("GPU-therm\n", encoding="utf-8")

    # USB device — Luxonis/Movidius OAK-D (vendor 03e7)
    usb_dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-1"
    usb_dev.mkdir(parents=True)
    (usb_dev / "idVendor").write_text("03e7\n", encoding="utf-8")

    # /proc/mounts — NVMe root
    proc = tmp_path / "proc"
    proc.mkdir(parents=True)
    (proc / "mounts").write_text(
        "/dev/nvme0n1p1 / ext4 rw,relatime 0 0\n", encoding="utf-8"
    )

    # SSH hardening config
    sshd_conf_d = etc / "ssh" / "sshd_config.d"
    sshd_conf_d.mkdir(parents=True)
    (sshd_conf_d / "90-mower-hardening.conf").write_text(
        "PasswordAuthentication no\n", encoding="utf-8"
    )

    # CPU online range
    cpu_dir = tmp_path / "sys" / "devices" / "system" / "cpu"
    cpu_dir.mkdir(parents=True)
    (cpu_dir / "online").write_text("0-11\n", encoding="utf-8")

    # GPU frequency
    gpu_dir = tmp_path / "sys" / "devices" / "17000000.gpu" / "devfreq" / "17000000.gpu"
    gpu_dir.mkdir(parents=True)
    (gpu_dir / "cur_freq").write_text("1300500000\n", encoding="utf-8")

    return tmp_path


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
