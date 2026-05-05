"""Tests for mower_rover.health.wifi reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from mower_rover.health.wifi import WifiStatus, read_wifi_status


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROC_NET_WIRELESS_NORMAL = """\
Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   70.  -40.  -95.        0      0      0      0      0        0
"""

_PROC_NET_WIRELESS_EMPTY = """\
Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
"""


@pytest.fixture()
def wifi_sysroot(tmp_path: Path) -> Path:
    """Create a fake sysroot with a normal /proc/net/wireless."""
    proc_net = tmp_path / "proc" / "net"
    proc_net.mkdir(parents=True)
    (proc_net / "wireless").write_text(_PROC_NET_WIRELESS_NORMAL, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def wifi_sysroot_empty(tmp_path: Path) -> Path:
    """Create a fake sysroot with no wireless interfaces."""
    proc_net = tmp_path / "proc" / "net"
    proc_net.mkdir(parents=True)
    (proc_net / "wireless").write_text(_PROC_NET_WIRELESS_EMPTY, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReadWifiStatus:
    def test_normal_parse(self, wifi_sysroot: Path) -> None:
        """Parse a well-formed /proc/net/wireless with one interface."""
        result = read_wifi_status(sysroot=wifi_sysroot)
        assert result is not None
        assert isinstance(result, WifiStatus)
        assert result.interface == "wlan0"
        assert result.link_quality == 70.0
        assert result.signal_dbm == -40.0
        assert result.noise_dbm == -95.0

    def test_empty_wireless_file(self, wifi_sysroot_empty: Path) -> None:
        """Headers only, no interface lines → None."""
        result = read_wifi_status(sysroot=wifi_sysroot_empty)
        assert result is None

    def test_no_wireless_file(self, tmp_path: Path) -> None:
        """Missing /proc/net/wireless → None."""
        result = read_wifi_status(sysroot=tmp_path)
        assert result is None

    def test_non_linux_returns_none(self, tmp_path: Path) -> None:
        """On a system without /proc/net/wireless the result is None."""
        # tmp_path is empty — simulates non-Linux
        result = read_wifi_status(sysroot=tmp_path)
        assert result is None
