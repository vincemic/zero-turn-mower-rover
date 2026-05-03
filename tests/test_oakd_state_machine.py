"""Tests for the rewritten OAK-D probe check — Q6 state machine.

Covers the 5-state cross-reference table:
  - active + f63b  → PASS (booted, USB 3.x)
  - active + 2485  → FAIL (crash-loop suspected)
  - active + absent → FAIL (service active but camera missing)
  - inactive + 2485 → PASS (idle in bootloader, service stopped)
  - inactive + absent → PASS (camera not present, service not running)

Uses sysroot fixtures under ``tests/fixtures/oakd_sysroot/`` and injectable
``_service_active_fn`` for hermetic testing on Windows and Linux.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mower_rover.probe.checks  # noqa: F401 — trigger registration
from mower_rover.probe.checks.oakd import check_oakd
from mower_rover.probe.registry import _REGISTRY, Severity

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures" / "oakd_sysroot"
_SYSROOT_F63B = _FIXTURES / "f63b-booted"
_SYSROOT_2485 = _FIXTURES / "2485-bootloader"
_SYSROOT_ABSENT = _FIXTURES / "absent"


# ---------------------------------------------------------------------------
# State machine parametrized matrix
# ---------------------------------------------------------------------------


class TestOakdStateMachine:
    """Q6 state table: 5 cells of (service_active, device_state) → outcome."""

    def test_active_f63b_pass(self) -> None:
        """active + f63b → PASS."""
        passed, detail = check_oakd(_SYSROOT_F63B, _service_active_fn=lambda: True)
        assert passed is True
        assert "f63b" in detail
        assert "active" in detail

    def test_active_2485_fail_crashloop(self) -> None:
        """active + 2485 → FAIL (crash-loop suspected)."""
        passed, detail = check_oakd(_SYSROOT_2485, _service_active_fn=lambda: True)
        assert passed is False
        assert "crash-loop" in detail.lower() or "Crash-loop" in detail
        assert "2485" in detail

    def test_active_absent_fail(self) -> None:
        """active + absent → FAIL (service active but camera missing)."""
        passed, detail = check_oakd(_SYSROOT_ABSENT, _service_active_fn=lambda: True)
        assert passed is False
        assert "active" in detail.lower()
        assert "no oak-d" in detail.lower() or "camera" in detail.lower()

    def test_inactive_2485_pass_idle(self) -> None:
        """inactive + 2485 → PASS (idle in bootloader, service stopped)."""
        passed, detail = check_oakd(_SYSROOT_2485, _service_active_fn=lambda: False)
        assert passed is True
        assert "bootloader" in detail.lower()
        assert "2485" in detail

    def test_inactive_absent_pass(self) -> None:
        """inactive + absent → PASS (camera not present, service not running)."""
        passed, detail = check_oakd(_SYSROOT_ABSENT, _service_active_fn=lambda: False)
        assert passed is True
        assert "not present" in detail.lower() or "not running" in detail.lower()


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestOakdEdgeCases:
    """Extra scenarios beyond the 5-state matrix."""

    def test_inactive_f63b_pass(self) -> None:
        """inactive + f63b → PASS (unusual but acceptable — service stopped mid-run)."""
        passed, detail = check_oakd(_SYSROOT_F63B, _service_active_fn=lambda: False)
        assert passed is True
        assert "f63b" in detail

    def test_check_severity_is_critical(self) -> None:
        spec = _REGISTRY["oakd"]
        assert spec.severity == Severity.CRITICAL

    def test_check_depends_on_jetpack(self) -> None:
        spec = _REGISTRY["oakd"]
        assert "jetpack_version" in spec.depends_on

    def test_speed_included_in_f63b_detail(self) -> None:
        """Verify speed (5000 Mbps) appears in the detail for booted state."""
        passed, detail = check_oakd(_SYSROOT_F63B, _service_active_fn=lambda: True)
        assert "5000" in detail

    def test_dynamic_sysroot_f63b(self, tmp_path: Path) -> None:
        """Build sysroot in tmp_path to verify glob pattern works."""
        dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-4.2"
        dev.mkdir(parents=True)
        (dev / "idVendor").write_text("03e7\n", encoding="utf-8")
        (dev / "idProduct").write_text("f63b\n", encoding="utf-8")
        (dev / "speed").write_text("5000\n", encoding="utf-8")
        passed, detail = check_oakd(tmp_path, _service_active_fn=lambda: True)
        assert passed is True
        assert "f63b" in detail

    def test_dynamic_sysroot_no_speed_file(self, tmp_path: Path) -> None:
        """idProduct present but speed file missing — still determines state by PID."""
        dev = tmp_path / "sys" / "bus" / "usb" / "devices" / "1-4.2"
        dev.mkdir(parents=True)
        (dev / "idVendor").write_text("03e7\n", encoding="utf-8")
        (dev / "idProduct").write_text("f63b\n", encoding="utf-8")
        passed, detail = check_oakd(tmp_path, _service_active_fn=lambda: True)
        assert passed is True
        assert "f63b" in detail
