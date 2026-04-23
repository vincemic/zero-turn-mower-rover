"""Tests for mower_rover.health readers (thermal, power, disk).

All tests use fake sysfs trees under ``tmp_path`` — no real Linux sysfs needed.
These run on Windows and Linux alike.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from mower_rover.health.disk import read_disk_usage
from mower_rover.health.power import PowerState, read_power_state
from mower_rover.health.thermal import ThermalSnapshot, read_thermal_zones

# ---------------------------------------------------------------------------
# Fixtures — fake sysfs trees
# ---------------------------------------------------------------------------


@pytest.fixture()
def thermal_sysroot(tmp_path: Path) -> Path:
    """Create a fake sysroot with two thermal zones."""
    base = tmp_path / "sys" / "class" / "thermal"

    zone0 = base / "thermal_zone0"
    zone0.mkdir(parents=True)
    (zone0 / "temp").write_text("45000\n", encoding="utf-8")
    (zone0 / "type").write_text("CPU-therm\n", encoding="utf-8")

    zone1 = base / "thermal_zone1"
    zone1.mkdir(parents=True)
    (zone1 / "temp").write_text("52500\n", encoding="utf-8")
    (zone1 / "type").write_text("GPU-therm\n", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def power_sysroot(tmp_path: Path) -> Path:
    """Create a fake sysroot with CPU online range and GPU freq."""
    cpu_dir = tmp_path / "sys" / "devices" / "system" / "cpu"
    cpu_dir.mkdir(parents=True)
    (cpu_dir / "online").write_text("0-11\n", encoding="utf-8")

    gpu_dir = tmp_path / "sys" / "devices" / "17000000.gpu" / "devfreq" / "17000000.gpu"
    gpu_dir.mkdir(parents=True)
    (gpu_dir / "cur_freq").write_text("1300000000\n", encoding="utf-8")  # 1300 MHz

    fan_dir = tmp_path / "sys" / "devices" / "pwm-fan"
    fan_dir.mkdir(parents=True)
    (fan_dir / "cur_pwm_profile").write_text("quiet\n", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def disk_sysroot(tmp_path: Path) -> Path:
    """Create a fake /proc/mounts with an NVMe root."""
    proc = tmp_path / "proc"
    proc.mkdir(parents=True)
    (proc / "mounts").write_text(
        "/dev/nvme0n1p1 / ext4 rw,relatime 0 0\n"
        "/dev/nvme0n1p2 /home ext4 rw,relatime 0 0\n"
        "tmpfs /tmp tmpfs rw 0 0\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Thermal tests
# ---------------------------------------------------------------------------


class TestReadThermalZones:
    def test_two_zones(self, thermal_sysroot: Path) -> None:
        snap = read_thermal_zones(sysroot=thermal_sysroot)
        assert isinstance(snap, ThermalSnapshot)
        assert len(snap.zones) == 2

        z0 = snap.zones[0]
        assert z0.index == 0
        assert z0.name == "CPU-therm"
        assert z0.temp_c == pytest.approx(45.0)

        z1 = snap.zones[1]
        assert z1.index == 1
        assert z1.name == "GPU-therm"
        assert z1.temp_c == pytest.approx(52.5)

    def test_empty_when_no_zones(self, tmp_path: Path) -> None:
        snap = read_thermal_zones(sysroot=tmp_path)
        assert snap.zones == []

    def test_skips_unreadable_temp(self, tmp_path: Path) -> None:
        zone = tmp_path / "sys" / "class" / "thermal" / "thermal_zone0"
        zone.mkdir(parents=True)
        (zone / "temp").write_text("not_a_number\n", encoding="utf-8")
        (zone / "type").write_text("bad-zone\n", encoding="utf-8")

        snap = read_thermal_zones(sysroot=tmp_path)
        assert snap.zones == []

    def test_missing_type_file(self, tmp_path: Path) -> None:
        zone = tmp_path / "sys" / "class" / "thermal" / "thermal_zone0"
        zone.mkdir(parents=True)
        (zone / "temp").write_text("50000\n", encoding="utf-8")
        # No type file.

        snap = read_thermal_zones(sysroot=tmp_path)
        assert len(snap.zones) == 1
        assert snap.zones[0].temp_c == pytest.approx(50.0)
        # Name should be empty string (no type file).
        assert snap.zones[0].name == ""

    def test_timestamp_present(self, thermal_sysroot: Path) -> None:
        snap = read_thermal_zones(sysroot=thermal_sysroot)
        assert snap.timestamp  # non-empty ISO string

    def test_frozen_dataclass(self, thermal_sysroot: Path) -> None:
        snap = read_thermal_zones(sysroot=thermal_sysroot)
        with pytest.raises(AttributeError):
            snap.timestamp = "tampered"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            snap.zones[0].temp_c = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Power tests
# ---------------------------------------------------------------------------

_NVPMODEL_OUTPUT = """\
NV Power Mode: MAXN
0
"""


class TestReadPowerState:
    def test_full_state(self, power_sysroot: Path) -> None:
        fake_result = subprocess.CompletedProcess(
            args=["nvpmodel", "-q"],
            returncode=0,
            stdout=_NVPMODEL_OUTPUT,
            stderr="",
        )
        with patch("mower_rover.health.power.subprocess.run", return_value=fake_result):
            state = read_power_state(sysroot=power_sysroot)

        assert isinstance(state, PowerState)
        assert state.mode_id == 0
        assert state.mode_name == "MAXN"
        assert state.online_cpus == 12
        assert state.gpu_freq_mhz == 1300
        assert state.fan_profile == "quiet"
        assert state.timestamp

    def test_nvpmodel_missing(self, power_sysroot: Path) -> None:
        with patch(
            "mower_rover.health.power.subprocess.run",
            side_effect=FileNotFoundError("nvpmodel"),
        ):
            state = read_power_state(sysroot=power_sysroot)

        assert state.mode_id is None
        assert state.mode_name is None
        # sysfs fields should still be populated.
        assert state.online_cpus == 12
        assert state.gpu_freq_mhz == 1300

    def test_all_none_on_empty_sysroot(self, tmp_path: Path) -> None:
        with patch(
            "mower_rover.health.power.subprocess.run",
            side_effect=FileNotFoundError("nvpmodel"),
        ):
            state = read_power_state(sysroot=tmp_path)

        assert state.mode_id is None
        assert state.mode_name is None
        assert state.online_cpus is None
        assert state.gpu_freq_mhz is None
        assert state.fan_profile is None

    def test_cpu_range_comma_separated(self, tmp_path: Path) -> None:
        cpu_dir = tmp_path / "sys" / "devices" / "system" / "cpu"
        cpu_dir.mkdir(parents=True)
        (cpu_dir / "online").write_text("0-3,6-7\n", encoding="utf-8")

        with patch(
            "mower_rover.health.power.subprocess.run",
            side_effect=FileNotFoundError("nvpmodel"),
        ):
            state = read_power_state(sysroot=tmp_path)

        assert state.online_cpus == 6  # 0-3 = 4, 6-7 = 2

    def test_frozen_dataclass(self, power_sysroot: Path) -> None:
        with patch(
            "mower_rover.health.power.subprocess.run",
            side_effect=FileNotFoundError("nvpmodel"),
        ):
            state = read_power_state(sysroot=power_sysroot)
        with pytest.raises(AttributeError):
            state.mode_id = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Disk tests
# ---------------------------------------------------------------------------


class TestReadDiskUsage:
    def test_nvme_root(self, disk_sysroot: Path) -> None:
        results = read_disk_usage(sysroot=disk_sysroot)
        # /proc/mounts has / and /home (both interesting), tmpfs /tmp is skipped.
        assert len(results) == 2
        root = next(r for r in results if r.mount_point == "/")
        assert root.is_nvme is True
        assert root.device == "/dev/nvme0n1p1"
        home = next(r for r in results if r.mount_point == "/home")
        assert home.is_nvme is True

    def test_non_nvme_device(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        proc.mkdir(parents=True)
        (proc / "mounts").write_text(
            "/dev/sda1 / ext4 rw,relatime 0 0\n",
            encoding="utf-8",
        )
        results = read_disk_usage(sysroot=tmp_path)
        assert len(results) == 1
        assert results[0].is_nvme is False

    def test_empty_when_no_proc_mounts(self, tmp_path: Path) -> None:
        results = read_disk_usage(sysroot=tmp_path)
        assert results == []

    def test_empty_mounts_file(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        proc.mkdir(parents=True)
        (proc / "mounts").write_text("", encoding="utf-8")
        results = read_disk_usage(sysroot=tmp_path)
        assert results == []

    def test_uninteresting_mounts_skipped(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        proc.mkdir(parents=True)
        (proc / "mounts").write_text(
            "tmpfs /tmp tmpfs rw 0 0\n"
            "devtmpfs /dev devtmpfs rw 0 0\n",
            encoding="utf-8",
        )
        results = read_disk_usage(sysroot=tmp_path)
        assert results == []

    def test_frozen_dataclass(self, disk_sysroot: Path) -> None:
        results = read_disk_usage(sysroot=disk_sysroot)
        assert len(results) > 0
        with pytest.raises(AttributeError):
            results[0].mount_point = "/tampered"  # type: ignore[misc]
