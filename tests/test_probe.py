"""Tests for mower_rover.probe — registry, checks, dependency ordering, exit codes.

All checks are tested using fake sysfs trees under ``tmp_path`` and
monkeypatched subprocess calls. These run on Windows and Linux alike.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — ensure check modules are imported so the registry is populated.
# ---------------------------------------------------------------------------
import mower_rover.probe.checks  # noqa: E402, F401
from mower_rover.probe.registry import (
    _REGISTRY,
    CheckResult,
    CheckSpec,
    Severity,
    Status,
    _resolve_order,
    derive_exit_code,
    register,
    run_checks,
)

# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_checks_registered(self) -> None:
        expected = {
            "jetpack_version",
            "cuda",
            "python_ver",
            "disk_space",
            "disk_nvme",
            "ssh_hardening",
            "oakd",
            "thermal",
            "power_mode",
            "oakd_usb_autosuspend",
            "oakd_usbfs_memory",
            "oakd_thermal_gate",
            "health_service",
            "loginctl_linger",
            "vslam_socket_active",
        }
        assert expected.issubset(set(_REGISTRY.keys()))

    def test_check_spec_fields(self) -> None:
        spec = _REGISTRY["cuda"]
        assert spec.severity == Severity.CRITICAL
        assert "jetpack_version" in spec.depends_on
        assert callable(spec.fn)

    def test_duplicate_registration_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate check name"):
            register("jetpack_version", severity=Severity.INFO)(lambda sysroot: (True, "dup"))

    def test_dependency_cycle_raises(self) -> None:
        specs = {
            "a": CheckSpec(
                name="a", severity=Severity.INFO,
                depends_on=("b",), fn=lambda s: (True, ""),
            ),
            "b": CheckSpec(
                name="b", severity=Severity.INFO,
                depends_on=("a",), fn=lambda s: (True, ""),
            ),
        }
        with pytest.raises(ValueError, match="cycle"):
            _resolve_order(specs)

    def test_resolve_order_respects_deps(self) -> None:
        specs = {
            "child": CheckSpec(
                name="child", severity=Severity.INFO,
                depends_on=("parent",), fn=lambda s: (True, ""),
            ),
            "parent": CheckSpec(
                name="parent", severity=Severity.INFO,
                depends_on=(), fn=lambda s: (True, ""),
            ),
        }
        order = _resolve_order(specs)
        assert order.index("parent") < order.index("child")


# ---------------------------------------------------------------------------
# Selective execution tests
# ---------------------------------------------------------------------------


class TestRunChecksSelective:
    def test_only_filters_checks(self, tmp_path: Path) -> None:
        # Set up a fake sysroot with proc/mounts for disk checks.
        proc = tmp_path / "proc"
        proc.mkdir(parents=True)
        (proc / "mounts").write_text(
            "/dev/nvme0n1p1 / ext4 rw,relatime 0 0\n",
            encoding="utf-8",
        )
        results = run_checks(sysroot=tmp_path, only=frozenset({"disk_nvme"}))
        names = [r.name for r in results]
        assert "disk_nvme" in names
        # Should NOT include unrelated checks.
        assert "cuda" not in names
        assert "ssh_hardening" not in names

    def test_only_pulls_in_deps(self, tmp_path: Path) -> None:
        # Requesting "cuda" should also run "jetpack_version" (its dep).
        results = run_checks(sysroot=tmp_path, only=frozenset({"cuda"}))
        names = [r.name for r in results]
        assert "jetpack_version" in names
        assert "cuda" in names

    def test_dep_failure_skips_dependent(self, tmp_path: Path) -> None:
        # jetpack_version will fail (no nv_tegra_release) → cuda should be skipped.
        results = run_checks(sysroot=tmp_path, only=frozenset({"cuda"}))
        jp = next(r for r in results if r.name == "jetpack_version")
        cuda_r = next(r for r in results if r.name == "cuda")
        assert jp.status == Status.FAIL
        assert cuda_r.status == Status.SKIP


# ---------------------------------------------------------------------------
# Exit code derivation tests
# ---------------------------------------------------------------------------


class TestDeriveExitCode:
    def test_all_pass_returns_zero(self) -> None:
        results = [
            CheckResult(name="a", status=Status.PASS, severity=Severity.CRITICAL, detail="ok"),
            CheckResult(name="b", status=Status.PASS, severity=Severity.WARNING, detail="ok"),
        ]
        assert derive_exit_code(results) == 0

    def test_warning_failure_returns_one(self) -> None:
        results = [
            CheckResult(name="a", status=Status.PASS, severity=Severity.CRITICAL, detail="ok"),
            CheckResult(name="b", status=Status.FAIL, severity=Severity.WARNING, detail="bad"),
        ]
        assert derive_exit_code(results) == 1

    def test_critical_failure_returns_two(self) -> None:
        results = [
            CheckResult(name="a", status=Status.FAIL, severity=Severity.CRITICAL, detail="bad"),
            CheckResult(name="b", status=Status.PASS, severity=Severity.WARNING, detail="ok"),
        ]
        assert derive_exit_code(results) == 2

    def test_critical_trumps_warning(self) -> None:
        results = [
            CheckResult(name="a", status=Status.FAIL, severity=Severity.CRITICAL, detail="bad"),
            CheckResult(name="b", status=Status.FAIL, severity=Severity.WARNING, detail="bad"),
        ]
        assert derive_exit_code(results) == 2

    def test_skip_counts_as_failure(self) -> None:
        results = [
            CheckResult(name="a", status=Status.SKIP, severity=Severity.CRITICAL, detail="skipped"),
        ]
        assert derive_exit_code(results) == 2

    def test_info_only_failure_returns_zero(self) -> None:
        results = [
            CheckResult(name="a", status=Status.FAIL, severity=Severity.INFO, detail="meh"),
        ]
        assert derive_exit_code(results) == 0

    def test_empty_results_returns_zero(self) -> None:
        assert derive_exit_code([]) == 0


# ---------------------------------------------------------------------------
# Individual check PASS/FAIL tests
# ---------------------------------------------------------------------------


class TestJetpackVersionCheck:
    def test_pass_r36(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir(parents=True)
        (etc / "nv_tegra_release").write_text(
            "# R36 (release), REVISION: 4.3\n", encoding="utf-8"
        )
        fn = _REGISTRY["jetpack_version"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "R36" in detail

    def test_fail_wrong_release(self, tmp_path: Path) -> None:
        etc = tmp_path / "etc"
        etc.mkdir(parents=True)
        (etc / "nv_tegra_release").write_text(
            "# R35 (release), REVISION: 3.1\n", encoding="utf-8"
        )
        fn = _REGISTRY["jetpack_version"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "Expected L4T R36.x" in detail

    def test_fail_file_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["jetpack_version"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "Not a Jetson" in detail


class TestCudaCheck:
    def test_pass_cuda_12(self, tmp_path: Path) -> None:
        fake_result = subprocess.CompletedProcess(
            args=["nvcc", "--version"],
            returncode=0,
            stdout=(
                "nvcc: NVIDIA (R) Cuda compiler driver\n"
                "Cuda compilation tools, release 12.2, V12.2.140\n"
            ),
            stderr="",
        )
        fn = _REGISTRY["cuda"].fn
        with patch("mower_rover.probe.checks.cuda.subprocess.run", return_value=fake_result):
            passed, detail = fn(tmp_path)
        assert passed is True
        assert "12.2" in detail

    def test_fail_cuda_11(self, tmp_path: Path) -> None:
        fake_result = subprocess.CompletedProcess(
            args=["nvcc", "--version"],
            returncode=0,
            stdout=(
                "nvcc: NVIDIA (R) Cuda compiler driver\n"
                "Cuda compilation tools, release 11.4, V11.4.100\n"
            ),
            stderr="",
        )
        fn = _REGISTRY["cuda"].fn
        with patch("mower_rover.probe.checks.cuda.subprocess.run", return_value=fake_result):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "Expected 12.x" in detail

    def test_fail_nvcc_not_found(self, tmp_path: Path) -> None:
        fn = _REGISTRY["cuda"].fn
        with patch(
            "mower_rover.probe.checks.cuda.subprocess.run",
            side_effect=FileNotFoundError("nvcc"),
        ):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "CUDA not found" in detail


class TestPythonVerCheck:
    def test_pass_python_311(self, tmp_path: Path) -> None:
        fake_result = subprocess.CompletedProcess(
            args=["python3.11", "--version"],
            returncode=0,
            stdout="Python 3.11.9\n",
            stderr="",
        )
        fn = _REGISTRY["python_ver"].fn
        with patch(
            "mower_rover.probe.checks.python_ver.subprocess.run",
            return_value=fake_result,
        ):
            passed, detail = fn(tmp_path)
        assert passed is True
        assert "3.11" in detail

    def test_pass_python3_312(self, tmp_path: Path) -> None:
        # python3.11 not found, but python3 is 3.12.
        call_count = 0

        def side_effect(args, **kwargs):
            nonlocal call_count
            call_count += 1
            if args[0] == "python3.11":
                raise FileNotFoundError("python3.11")
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="Python 3.12.1\n", stderr=""
            )

        fn = _REGISTRY["python_ver"].fn
        with patch(
            "mower_rover.probe.checks.python_ver.subprocess.run",
            side_effect=side_effect,
        ):
            passed, detail = fn(tmp_path)
        assert passed is True
        assert "3.12" in detail

    def test_fail_python_310(self, tmp_path: Path) -> None:
        fake_result = subprocess.CompletedProcess(
            args=["python3", "--version"],
            returncode=0,
            stdout="Python 3.10.6\n",
            stderr="",
        )
        fn = _REGISTRY["python_ver"].fn
        with patch(
            "mower_rover.probe.checks.python_ver.subprocess.run",
            return_value=fake_result,
        ):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "3.11+" in detail

    def test_fail_no_python(self, tmp_path: Path) -> None:
        fn = _REGISTRY["python_ver"].fn
        with patch(
            "mower_rover.probe.checks.python_ver.subprocess.run",
            side_effect=FileNotFoundError("python"),
        ):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "3.11+" in detail


class TestDiskSpaceCheck:
    def test_pass_enough_space(self, tmp_path: Path) -> None:
        from mower_rover.health.disk import DiskUsage

        fake = [DiskUsage(mount_point="/", device="/dev/nvme0n1p1",
                          total_gb=64.0, used_gb=10.0, free_gb=54.0, is_nvme=True)]
        fn = _REGISTRY["disk_space"].fn
        with patch("mower_rover.probe.checks.disk.read_disk_usage", return_value=fake):
            passed, detail = fn(tmp_path)
        assert passed is True
        assert "54.0 GB free" in detail

    def test_fail_low_space(self, tmp_path: Path) -> None:
        from mower_rover.health.disk import DiskUsage

        fake = [DiskUsage(mount_point="/", device="/dev/nvme0n1p1",
                          total_gb=64.0, used_gb=63.0, free_gb=1.0, is_nvme=True)]
        fn = _REGISTRY["disk_space"].fn
        with patch("mower_rover.probe.checks.disk.read_disk_usage", return_value=fake):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "below 2 GB" in detail

    def test_fail_no_root_mount(self, tmp_path: Path) -> None:
        fn = _REGISTRY["disk_space"].fn
        with patch("mower_rover.probe.checks.disk.read_disk_usage", return_value=[]):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "not found" in detail


class TestDiskNvmeCheck:
    def test_pass_nvme(self, tmp_path: Path) -> None:
        from mower_rover.health.disk import DiskUsage

        fake = [DiskUsage(mount_point="/", device="/dev/nvme0n1p1",
                          total_gb=64.0, used_gb=10.0, free_gb=54.0, is_nvme=True)]
        fn = _REGISTRY["disk_nvme"].fn
        with patch("mower_rover.probe.checks.disk.read_disk_usage", return_value=fake):
            passed, detail = fn(tmp_path)
        assert passed is True
        assert "NVMe" in detail

    def test_fail_non_nvme(self, tmp_path: Path) -> None:
        from mower_rover.health.disk import DiskUsage

        fake = [DiskUsage(mount_point="/", device="/dev/sda1",
                          total_gb=64.0, used_gb=10.0, free_gb=54.0, is_nvme=False)]
        fn = _REGISTRY["disk_nvme"].fn
        with patch("mower_rover.probe.checks.disk.read_disk_usage", return_value=fake):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "not on NVMe" in detail


class TestSshHardeningCheck:
    def test_pass_disabled(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / "etc" / "ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "sshd_config").write_text(
            "# Comment\nPasswordAuthentication no\n", encoding="utf-8"
        )
        fn = _REGISTRY["ssh_hardening"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "disabled" in detail

    def test_fail_enabled(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / "etc" / "ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "sshd_config").write_text(
            "PasswordAuthentication yes\n", encoding="utf-8"
        )
        fn = _REGISTRY["ssh_hardening"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "still enabled" in detail

    def test_fail_not_set(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / "etc" / "ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "sshd_config").write_text("# nothing relevant\n", encoding="utf-8")
        fn = _REGISTRY["ssh_hardening"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "still enabled" in detail

    def test_conf_d_override(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / "etc" / "ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "sshd_config").write_text(
            "PasswordAuthentication yes\n", encoding="utf-8"
        )
        conf_d = ssh_dir / "sshd_config.d"
        conf_d.mkdir()
        (conf_d / "99-hardening.conf").write_text(
            "PasswordAuthentication no\n", encoding="utf-8"
        )
        fn = _REGISTRY["ssh_hardening"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "disabled" in detail


class TestOakdCheck:
    def test_pass_superspeed(self, tmp_path: Path) -> None:
        usb_dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-2"
        usb_dev.mkdir(parents=True)
        (usb_dev / "idVendor").write_text("03e7\n", encoding="utf-8")
        (usb_dev / "speed").write_text("5000\n", encoding="utf-8")
        fn = _REGISTRY["oakd"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "USB 5000 Mbps" in detail

    def test_pass_superspeed_plus(self, tmp_path: Path) -> None:
        usb_dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-2"
        usb_dev.mkdir(parents=True)
        (usb_dev / "idVendor").write_text("03e7\n", encoding="utf-8")
        (usb_dev / "speed").write_text("10000\n", encoding="utf-8")
        fn = _REGISTRY["oakd"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "USB 10000 Mbps" in detail

    def test_fail_usb2(self, tmp_path: Path) -> None:
        usb_dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-2"
        usb_dev.mkdir(parents=True)
        (usb_dev / "idVendor").write_text("03e7\n", encoding="utf-8")
        (usb_dev / "speed").write_text("480\n", encoding="utf-8")
        fn = _REGISTRY["oakd"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "USB 480 Mbps" in detail
        assert "5000" in detail

    def test_pass_no_speed_file(self, tmp_path: Path) -> None:
        usb_dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-2"
        usb_dev.mkdir(parents=True)
        (usb_dev / "idVendor").write_text("03e7\n", encoding="utf-8")
        fn = _REGISTRY["oakd"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "speed unknown" in detail

    def test_fail_no_device(self, tmp_path: Path) -> None:
        fn = _REGISTRY["oakd"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "No OAK device" in detail

    def test_fail_wrong_vendor(self, tmp_path: Path) -> None:
        usb_dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-2"
        usb_dev.mkdir(parents=True)
        (usb_dev / "idVendor").write_text("8086\n", encoding="utf-8")
        fn = _REGISTRY["oakd"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "No OAK device" in detail

    def test_severity_is_critical(self) -> None:
        spec = _REGISTRY["oakd"]
        assert spec.severity == Severity.CRITICAL


class TestThermalCheck:
    def test_pass_all_cool(self, tmp_path: Path) -> None:
        base = tmp_path / "sys" / "class" / "thermal"
        zone0 = base / "thermal_zone0"
        zone0.mkdir(parents=True)
        (zone0 / "temp").write_text("45000\n", encoding="utf-8")
        (zone0 / "type").write_text("CPU-therm\n", encoding="utf-8")

        fn = _REGISTRY["thermal"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "45.0" in detail

    def test_fail_zone_hot(self, tmp_path: Path) -> None:
        base = tmp_path / "sys" / "class" / "thermal"
        zone0 = base / "thermal_zone0"
        zone0.mkdir(parents=True)
        (zone0 / "temp").write_text("96000\n", encoding="utf-8")
        (zone0 / "type").write_text("GPU-therm\n", encoding="utf-8")

        fn = _REGISTRY["thermal"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "throttle imminent" in detail

    def test_pass_no_zones(self, tmp_path: Path) -> None:
        fn = _REGISTRY["thermal"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "No thermal zones" in detail


class TestPowerModeCheck:
    def test_pass_mode_available(self, tmp_path: Path) -> None:
        fake_result = subprocess.CompletedProcess(
            args=["nvpmodel", "-q"],
            returncode=0,
            stdout="NV Power Mode: MAXN\n0\n",
            stderr="",
        )
        fn = _REGISTRY["power_mode"].fn
        with patch("mower_rover.health.power.subprocess.run", return_value=fake_result):
            passed, detail = fn(tmp_path)
        assert passed is True
        assert "MAXN" in detail

    def test_fail_nvpmodel_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["power_mode"].fn
        with patch(
            "mower_rover.health.power.subprocess.run",
            side_effect=FileNotFoundError("nvpmodel"),
        ):
            passed, detail = fn(tmp_path)
        assert passed is False
        assert "nvpmodel not found" in detail


# ---------------------------------------------------------------------------
# USB tuning check tests
# ---------------------------------------------------------------------------


class TestUsbAutosuspendCheck:
    def test_pass_disabled(self, tmp_path: Path) -> None:
        param = tmp_path / "sys" / "module" / "usbcore" / "parameters"
        param.mkdir(parents=True)
        (param / "autosuspend").write_text("-1\n", encoding="utf-8")
        fn = _REGISTRY["oakd_usb_autosuspend"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "-1" in detail

    def test_fail_enabled(self, tmp_path: Path) -> None:
        param = tmp_path / "sys" / "module" / "usbcore" / "parameters"
        param.mkdir(parents=True)
        (param / "autosuspend").write_text("2\n", encoding="utf-8")
        fn = _REGISTRY["oakd_usb_autosuspend"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "autosuspend=2" in detail

    def test_fail_missing_file(self, tmp_path: Path) -> None:
        fn = _REGISTRY["oakd_usb_autosuspend"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "missing sysfs" in detail


class TestUsbfsMemoryCheck:
    def test_pass_1000(self, tmp_path: Path) -> None:
        param = tmp_path / "sys" / "module" / "usbcore" / "parameters"
        param.mkdir(parents=True)
        (param / "usbfs_memory_mb").write_text("1000\n", encoding="utf-8")
        fn = _REGISTRY["oakd_usbfs_memory"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "1000" in detail

    def test_pass_2000(self, tmp_path: Path) -> None:
        param = tmp_path / "sys" / "module" / "usbcore" / "parameters"
        param.mkdir(parents=True)
        (param / "usbfs_memory_mb").write_text("2000\n", encoding="utf-8")
        fn = _REGISTRY["oakd_usbfs_memory"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "2000" in detail

    def test_fail_low(self, tmp_path: Path) -> None:
        param = tmp_path / "sys" / "module" / "usbcore" / "parameters"
        param.mkdir(parents=True)
        (param / "usbfs_memory_mb").write_text("16\n", encoding="utf-8")
        fn = _REGISTRY["oakd_usbfs_memory"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "16" in detail
        assert "1000" in detail

    def test_fail_missing_file(self, tmp_path: Path) -> None:
        fn = _REGISTRY["oakd_usbfs_memory"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "missing sysfs" in detail


class TestThermalGateCheck:
    def test_pass_cool(self, tmp_path: Path) -> None:
        base = tmp_path / "sys" / "class" / "thermal"
        zone0 = base / "thermal_zone0"
        zone0.mkdir(parents=True)
        (zone0 / "temp").write_text("60000\n", encoding="utf-8")
        (zone0 / "type").write_text("CPU-therm\n", encoding="utf-8")
        fn = _REGISTRY["oakd_thermal_gate"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "60.0" in detail

    def test_fail_hot(self, tmp_path: Path) -> None:
        base = tmp_path / "sys" / "class" / "thermal"
        zone0 = base / "thermal_zone0"
        zone0.mkdir(parents=True)
        (zone0 / "temp").write_text("86000\n", encoding="utf-8")
        (zone0 / "type").write_text("GPU-therm\n", encoding="utf-8")
        fn = _REGISTRY["oakd_thermal_gate"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "86" in detail
        assert "85" in detail

    def test_pass_no_zones(self, tmp_path: Path) -> None:
        fn = _REGISTRY["oakd_thermal_gate"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "No thermal zones" in detail
