"""Tests for service probe checks — health_service, loginctl_linger."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import mower_rover.probe.checks  # noqa: F401 — trigger registration
from mower_rover.probe.registry import (
    _REGISTRY,
    Severity,
)

# ------------------------------------------------------------------
# Registration tests
# ------------------------------------------------------------------


class TestServiceChecksRegistered:
    """Verify service probe checks appear in the global registry."""

    def test_health_service_registered(self) -> None:
        assert "health_service" in _REGISTRY

    def test_health_service_severity(self) -> None:
        assert _REGISTRY["health_service"].severity == Severity.CRITICAL

    def test_loginctl_linger_registered(self) -> None:
        assert "loginctl_linger" in _REGISTRY

    def test_loginctl_linger_severity(self) -> None:
        assert _REGISTRY["loginctl_linger"].severity == Severity.WARNING


# ------------------------------------------------------------------
# health_service check
# ------------------------------------------------------------------


class TestHealthService:
    def test_pass_service_active(self, tmp_path: Path) -> None:
        fake = subprocess.CompletedProcess(
            args=["systemctl", "--user", "is-active", "mower-health.service"],
            returncode=0,
        )
        with patch(
            "mower_rover.probe.checks.service.subprocess.run",
            return_value=fake,
        ):
            fn = _REGISTRY["health_service"].fn
            passed, detail = fn(tmp_path)
            assert passed is True
            assert detail == "active"

    def test_fail_service_inactive(self, tmp_path: Path) -> None:
        fake = subprocess.CompletedProcess(
            args=["systemctl", "--user", "is-active", "mower-health.service"],
            returncode=3,
        )
        with patch(
            "mower_rover.probe.checks.service.subprocess.run",
            return_value=fake,
        ):
            fn = _REGISTRY["health_service"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert detail == "not active"

    def test_fail_no_systemctl(self, tmp_path: Path) -> None:
        with patch(
            "mower_rover.probe.checks.service.subprocess.run",
            side_effect=FileNotFoundError("systemctl"),
        ):
            fn = _REGISTRY["health_service"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "not found" in detail.lower()

    def test_fail_timeout(self, tmp_path: Path) -> None:
        with patch(
            "mower_rover.probe.checks.service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=5),
        ):
            fn = _REGISTRY["health_service"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "timed out" in detail.lower()


# ------------------------------------------------------------------
# loginctl_linger check
# ------------------------------------------------------------------


class TestLoginctlLinger:
    def test_pass_linger_yes(self, tmp_path: Path) -> None:
        fake = subprocess.CompletedProcess(
            args=["loginctl", "show-user", "testuser", "-p", "Linger", "--value"],
            returncode=0,
            stdout="yes\n",
            stderr="",
        )
        with (
            patch(
                "mower_rover.probe.checks.service.subprocess.run",
                return_value=fake,
            ),
            patch.dict(
                "os.environ", {"USER": "testuser"}, clear=False,
            ),
        ):
            fn = _REGISTRY["loginctl_linger"].fn
            passed, detail = fn(tmp_path)
            assert passed is True
            assert detail == "Linger=yes"

    def test_fail_linger_no(self, tmp_path: Path) -> None:
        fake = subprocess.CompletedProcess(
            args=["loginctl", "show-user", "testuser", "-p", "Linger", "--value"],
            returncode=0,
            stdout="no\n",
            stderr="",
        )
        with (
            patch(
                "mower_rover.probe.checks.service.subprocess.run",
                return_value=fake,
            ),
            patch.dict(
                "os.environ", {"USER": "testuser"}, clear=False,
            ),
        ):
            fn = _REGISTRY["loginctl_linger"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "Linger=no" in detail

    def test_fail_no_loginctl(self, tmp_path: Path) -> None:
        with (
            patch(
                "mower_rover.probe.checks.service.subprocess.run",
                side_effect=FileNotFoundError("loginctl"),
            ),
            patch.dict(
                "os.environ", {"USER": "testuser"}, clear=False,
            ),
        ):
            fn = _REGISTRY["loginctl_linger"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "not found" in detail.lower()

    def test_fail_timeout(self, tmp_path: Path) -> None:
        with (
            patch(
                "mower_rover.probe.checks.service.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="loginctl", timeout=5),
            ),
            patch.dict(
                "os.environ", {"USER": "testuser"}, clear=False,
            ),
        ):
            fn = _REGISTRY["loginctl_linger"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "timed out" in detail.lower()

    def test_fail_no_user_env(self, tmp_path: Path) -> None:
        with patch.dict(
            "os.environ", {}, clear=True,
        ):
            fn = _REGISTRY["loginctl_linger"].fn
            passed, detail = fn(tmp_path)
            assert passed is False
            assert "cannot determine" in detail.lower()
