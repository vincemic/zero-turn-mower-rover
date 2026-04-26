"""Tests for VSLAM probe checks — service status, config, Lua script, confidence.

All checks are tested using fake sysfs trees under ``tmp_path`` and
monkeypatched subprocess calls.  Runs on Windows and Linux alike.
"""

from __future__ import annotations

import socket
import struct
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

import mower_rover.probe.checks  # noqa: F401 — trigger registration
from mower_rover.probe.registry import (
    _REGISTRY,
    Status,
    run_checks,
)

# ------------------------------------------------------------------
# Registration tests
# ------------------------------------------------------------------


class TestVslamChecksRegistered:
    """Verify all VSLAM probe checks appear in the global registry."""

    EXPECTED_CHECKS = {
        "oakd_vslam_config",
        "pixhawk_symlink",
        "vslam_process",
        "vslam_bridge",
        "vslam_socket_active",
        "vslam_pose_rate",
        "vslam_params",
        "vslam_lua_script",
        "vslam_confidence",
    }

    def test_all_vslam_checks_registered(self) -> None:
        assert self.EXPECTED_CHECKS.issubset(set(_REGISTRY.keys()))

    def test_dependency_chain_oakd_to_process(self) -> None:
        assert "oakd" in _REGISTRY["vslam_process"].depends_on

    def test_dependency_chain_process_to_bridge(self) -> None:
        assert "vslam_process" in _REGISTRY["vslam_bridge"].depends_on

    def test_dependency_chain_bridge_to_pose_rate(self) -> None:
        assert "vslam_bridge" in _REGISTRY["vslam_pose_rate"].depends_on

    def test_vslam_socket_active_depends_on_bridge(self) -> None:
        assert "vslam_bridge" in _REGISTRY["vslam_socket_active"].depends_on

    def test_vslam_params_depends_on_oakd(self) -> None:
        assert "oakd" in _REGISTRY["vslam_params"].depends_on

    def test_vslam_lua_script_depends_on_oakd(self) -> None:
        assert "oakd" in _REGISTRY["vslam_lua_script"].depends_on

    def test_vslam_confidence_depends_on_bridge(self) -> None:
        assert "vslam_bridge" in _REGISTRY["vslam_confidence"].depends_on

    def test_oakd_vslam_config_depends_on_oakd(self) -> None:
        assert "oakd" in _REGISTRY["oakd_vslam_config"].depends_on

    def test_pixhawk_symlink_has_no_deps(self) -> None:
        assert _REGISTRY["pixhawk_symlink"].depends_on == ()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_DEFAULT_VSLAM_YAML = {
    "vslam": {
        "odometry_strategy": "f2m",
        "stereo_resolution": "400p",
        "stereo_fps": 30,
        "imu_rate_hz": 200,
        "pose_output_rate_hz": 20,
        "memory_threshold_mb": 6000,
        "loop_closure": True,
        "database_path": "/var/lib/mower/rtabmap.db",
        "socket_path": "/run/mower/vslam-pose.sock",
        "extrinsics": {
            "pos_x": 0.30,
            "pos_y": 0.00,
            "pos_z": -0.20,
            "roll": 0.0,
            "pitch": -15.0,
            "yaw": 0.0,
        },
    },
    "bridge": {
        "serial_device": "/dev/ttyACM0",
        "source_system": 1,
        "source_component": 197,
    },
}


def _write_vslam_config(sysroot: Path, overrides: dict | None = None) -> Path:
    """Write a VSLAM config YAML under the sysroot."""
    cfg = _DEFAULT_VSLAM_YAML.copy()
    if overrides:
        for key, val in overrides.items():
            if isinstance(val, dict) and key in cfg:
                cfg[key] = {**cfg[key], **val}
            else:
                cfg[key] = val
    cfg_dir = sysroot / "etc" / "mower"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "vslam.yaml"
    cfg_path.write_text(yaml.dump(cfg, default_flow_style=False), encoding="utf-8")
    return cfg_path


def _create_socket(sysroot: Path) -> Path:
    """Create a fake socket file marker under the sysroot."""
    sock = sysroot / "run" / "mower" / "vslam-pose.sock"
    sock.parent.mkdir(parents=True, exist_ok=True)
    sock.write_text("", encoding="utf-8")  # placeholder
    return sock


def _mock_systemctl_active(*_services: str):
    """Return a mock subprocess.run that reports services as active."""
    active_set = set(_services)

    def _run(cmd, **kwargs):
        if cmd[0] == "systemctl" and cmd[1] == "is-active":
            service = cmd[3] if len(cmd) > 3 else cmd[2]
            rc = 0 if service in active_set else 3
            return subprocess.CompletedProcess(cmd, rc)
        return subprocess.CompletedProcess(cmd, 1)

    return _run


def _mock_systemctl_inactive():
    """Return a mock subprocess.run that reports all services inactive."""
    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 3)
    return _run


def _mock_systemctl_missing():
    """Return a mock subprocess.run that simulates missing systemctl."""
    def _run(cmd, **kwargs):
        raise FileNotFoundError("systemctl")
    return _run


# ------------------------------------------------------------------
# oakd_vslam_config check
# ------------------------------------------------------------------


class TestOakdVslamConfig:
    def test_pass_config_present(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path)
        fn = _REGISTRY["oakd_vslam_config"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "present" in detail.lower()

    def test_fail_config_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["oakd_vslam_config"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "missing" in detail.lower()


# ------------------------------------------------------------------
# vslam_process check
# ------------------------------------------------------------------


class TestVslamProcess:
    def test_pass_service_active(self, tmp_path: Path) -> None:
        mock = _mock_systemctl_active("mower-vslam.service")
        with patch("mower_rover.probe.checks.vslam.subprocess.run", side_effect=mock):
            fn = _REGISTRY["vslam_process"].fn
            passed, detail = fn(tmp_path)
            assert passed is True
            assert "active" in detail.lower()

    def test_fail_service_inactive(self, tmp_path: Path) -> None:
        mock = _mock_systemctl_inactive()
        with patch("mower_rover.probe.checks.vslam.subprocess.run", side_effect=mock):
            fn = _REGISTRY["vslam_process"].fn
            passed, detail = fn(tmp_path)
            assert passed is False

    def test_fail_no_systemctl(self, tmp_path: Path) -> None:
        mock = _mock_systemctl_missing()
        with patch("mower_rover.probe.checks.vslam.subprocess.run", side_effect=mock):
            fn = _REGISTRY["vslam_process"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "not found" in detail.lower()


# ------------------------------------------------------------------
# vslam_bridge check
# ------------------------------------------------------------------


class TestVslamBridge:
    def test_pass_service_active_and_socket(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        mock = _mock_systemctl_active("mower-vslam-bridge.service")
        with patch("mower_rover.probe.checks.vslam.subprocess.run", side_effect=mock):
            fn = _REGISTRY["vslam_bridge"].fn
            passed, detail = fn(tmp_path)
            assert passed is True
            assert "active" in detail.lower()

    def test_fail_service_active_no_socket(self, tmp_path: Path) -> None:
        mock = _mock_systemctl_active("mower-vslam-bridge.service")
        with patch("mower_rover.probe.checks.vslam.subprocess.run", side_effect=mock):
            fn = _REGISTRY["vslam_bridge"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "socket missing" in detail.lower()

    def test_fail_service_inactive(self, tmp_path: Path) -> None:
        mock = _mock_systemctl_inactive()
        with patch("mower_rover.probe.checks.vslam.subprocess.run", side_effect=mock):
            fn = _REGISTRY["vslam_bridge"].fn
            passed, detail = fn(tmp_path)
            assert passed is False


# ------------------------------------------------------------------
# vslam_pose_rate check
# ------------------------------------------------------------------


class TestVslamPoseRate:
    def test_pass_rate_sufficient(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path)
        fn = _REGISTRY["vslam_pose_rate"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "20" in detail

    def test_pass_rate_at_minimum(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path, {"vslam": {"pose_output_rate_hz": 5}})
        fn = _REGISTRY["vslam_pose_rate"].fn
        passed, detail = fn(tmp_path)
        assert passed is True

    def test_fail_rate_too_low(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path, {"vslam": {"pose_output_rate_hz": 3}})
        fn = _REGISTRY["vslam_pose_rate"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "3" in detail

    def test_fail_config_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["vslam_pose_rate"].fn
        passed, detail = fn(tmp_path)
        assert passed is False


# ------------------------------------------------------------------
# vslam_params check
# ------------------------------------------------------------------


class TestVslamParams:
    def test_pass_with_ardupilot_params_section(self, tmp_path: Path) -> None:
        cfg = {
            **_DEFAULT_VSLAM_YAML,
            "ardupilot_params": {
                "VISO_TYPE": 1,
                "SCR_ENABLE": 1,
                "EK3_SRC2_POSXY": 6,
                "EK3_SRC2_VELXY": 6,
                "EK3_SRC2_YAW": 6,
            },
        }
        cfg_dir = tmp_path / "etc" / "mower"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "vslam.yaml").write_text(
            yaml.dump(cfg, default_flow_style=False), encoding="utf-8"
        )
        fn = _REGISTRY["vslam_params"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "configured" in detail.lower()

    def test_fail_missing_ardupilot_params(self, tmp_path: Path) -> None:
        cfg = {
            **_DEFAULT_VSLAM_YAML,
            "ardupilot_params": {
                "VISO_TYPE": 0,  # wrong
                "SCR_ENABLE": 1,
            },
        }
        cfg_dir = tmp_path / "etc" / "mower"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "vslam.yaml").write_text(
            yaml.dump(cfg, default_flow_style=False), encoding="utf-8"
        )
        fn = _REGISTRY["vslam_params"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "VISO_TYPE" in detail

    def test_pass_fallback_vslam_section_only(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path)
        fn = _REGISTRY["vslam_params"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "not yet added" in detail.lower()

    def test_fail_config_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["vslam_params"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "missing" in detail.lower()

    def test_fail_empty_config(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "etc" / "mower"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "vslam.yaml").write_text("", encoding="utf-8")
        fn = _REGISTRY["vslam_params"].fn
        passed, detail = fn(tmp_path)
        assert passed is False


# ------------------------------------------------------------------
# vslam_lua_script check
# ------------------------------------------------------------------


class TestVslamLuaScript:
    def test_pass_bundled_script_exists(self, tmp_path: Path) -> None:
        fn = _REGISTRY["vslam_lua_script"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "bundled" in detail.lower()

    def test_fail_script_not_found(self, tmp_path: Path) -> None:
        fn = _REGISTRY["vslam_lua_script"].fn
        with patch(
            "importlib.resources.files",
            side_effect=FileNotFoundError("no package"),
        ):
            passed, detail = fn(tmp_path)
            assert passed is False


# ------------------------------------------------------------------
# vslam_confidence check
# ------------------------------------------------------------------


class TestVslamConfidence:
    def test_pass_loop_closure_enabled(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path)
        fn = _REGISTRY["vslam_confidence"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "enabled" in detail.lower()

    def test_fail_loop_closure_disabled(self, tmp_path: Path) -> None:
        _write_vslam_config(tmp_path, {"vslam": {"loop_closure": False}})
        fn = _REGISTRY["vslam_confidence"].fn
        passed, detail = fn(tmp_path)
        assert passed is False

    def test_fail_config_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["vslam_confidence"].fn
        passed, detail = fn(tmp_path)
        assert passed is False


# ------------------------------------------------------------------
# pixhawk_symlink check
# ------------------------------------------------------------------


class TestPixhawkSymlink:
    def test_pass_symlink_present(self, tmp_path: Path) -> None:
        dev_pixhawk = tmp_path / "dev" / "pixhawk"
        dev_pixhawk.parent.mkdir(parents=True, exist_ok=True)
        dev_pixhawk.write_text("", encoding="utf-8")  # placeholder
        fn = _REGISTRY["pixhawk_symlink"].fn
        passed, detail = fn(tmp_path)
        assert passed is True
        assert "/dev/pixhawk" in detail

    def test_fail_symlink_missing(self, tmp_path: Path) -> None:
        fn = _REGISTRY["pixhawk_symlink"].fn
        passed, detail = fn(tmp_path)
        assert passed is False
        assert "90-pixhawk-usb.rules" in detail


# ------------------------------------------------------------------
# vslam_socket_active check
# ------------------------------------------------------------------


class TestVslamSocketActive:
    _MSG_SIZE = struct.calcsize("<Q27fBB")  # 118 bytes
    _VSLAM_SOCKET_MOD = "mower_rover.probe.checks.vslam.socket"

    def _make_fake_frame(self, confidence: int = 3) -> bytes:
        """Build a minimal pose frame with the given confidence byte."""
        parts = struct.pack("<Q", 1234567890)
        parts += struct.pack("<27f", *(0.0 for _ in range(27)))
        parts += struct.pack("BB", confidence, 0)
        return parts

    def _mock_socket_module(self, mock_sock: MagicMock | None = None) -> MagicMock:
        """Create a mock socket module with AF_UNIX and SOCK_STREAM."""
        mod = MagicMock()
        mod.AF_UNIX = 1
        mod.SOCK_STREAM = 1
        mod.timeout = socket.timeout
        if mock_sock is not None:
            mod.socket.return_value = mock_sock
        return mod

    def test_pass_pose_received(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        frame = self._make_fake_frame(confidence=3)
        mock_sock = MagicMock()
        mock_sock.recv.return_value = frame
        mock_mod = self._mock_socket_module(mock_sock)

        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is True
            assert "confidence=3" in detail

    def test_fail_socket_not_found(self, tmp_path: Path) -> None:
        mock_mod = self._mock_socket_module()
        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "not found" in detail.lower()

    def test_fail_no_af_unix(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        mock_mod = MagicMock(spec=[])  # empty spec → hasattr(mock_mod, 'AF_UNIX') is False
        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "af_unix" in detail.lower()

    def test_fail_short_read(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"\x00" * 10
        mock_mod = self._mock_socket_module(mock_sock)

        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "short read" in detail.lower()

    def test_fail_timeout(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = socket.timeout("timed out")
        mock_mod = self._mock_socket_module(mock_sock)

        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "timed out" in detail.lower()

    def test_fail_connection_refused(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError("refused")
        mock_mod = self._mock_socket_module(mock_sock)

        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "refused" in detail.lower()

    def test_fail_os_error(self, tmp_path: Path) -> None:
        _create_socket(tmp_path)
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("broken pipe")
        mock_mod = self._mock_socket_module(mock_sock)

        with patch(self._VSLAM_SOCKET_MOD, mock_mod):
            fn = _REGISTRY["vslam_socket_active"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "socket error" in detail.lower()


# ------------------------------------------------------------------
# Dependency skip logic (integration)
# ------------------------------------------------------------------


class TestDependencySkip:
    """When oakd fails, all dependent VSLAM checks should be skipped."""

    def test_oakd_failure_skips_vslam_process(self, tmp_path: Path) -> None:
        # oakd will fail (no USB device in fake sysroot) → vslam_process skipped
        # Note: oakd itself depends on jetpack_version, so oakd may be SKIP or FAIL
        results = run_checks(
            sysroot=tmp_path, only=frozenset({"vslam_process"})
        )
        names = {r.name: r for r in results}
        assert "vslam_process" in names
        assert names["vslam_process"].status == Status.SKIP

    def test_oakd_failure_cascades_to_bridge(self, tmp_path: Path) -> None:
        results = run_checks(
            sysroot=tmp_path, only=frozenset({"vslam_bridge"})
        )
        names = {r.name: r for r in results}
        assert names["vslam_bridge"].status == Status.SKIP
