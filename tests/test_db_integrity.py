"""Tests for bringup vslam-db-check step — RTAB-Map DB integrity + quarantine."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from mower_rover.cli.bringup import (
    BringupContext,
    _db_check_done,
    _run_db_check,
)
from mower_rover.config.laptop import JetsonEndpoint
from mower_rover.transport.ssh import JetsonClient, SshError, SshResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def endpoint() -> JetsonEndpoint:
    return JetsonEndpoint(host="10.0.0.42", user="mower", port=22, key_path=None)


@pytest.fixture
def mock_client(endpoint: JetsonEndpoint) -> MagicMock:
    client = MagicMock(spec=JetsonClient)
    client.endpoint = endpoint
    return client


def _bctx(tmp_path: Path) -> BringupContext:
    from rich.console import Console

    return BringupContext(
        project_root=tmp_path,
        dry_run=False,
        yes=True,
        correlation_id=None,
        console=Console(force_terminal=True),
    )


def _ssh_ok(stdout: str = "", stderr: str = "") -> SshResult:
    return SshResult(argv=["ssh"], returncode=0, stdout=stdout, stderr=stderr)


def _ssh_fail(returncode: int = 1, stdout: str = "", stderr: str = "") -> SshResult:
    return SshResult(argv=["ssh"], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# _db_check_done always returns False
# ---------------------------------------------------------------------------


class TestDbCheckDone:
    def test_always_returns_false(self, mock_client: MagicMock) -> None:
        assert _db_check_done(mock_client) is False


# ---------------------------------------------------------------------------
# (a) DB absent → PASS
# ---------------------------------------------------------------------------


class TestDbAbsent:
    def test_db_not_found_passes(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """When `test -f` returns non-zero, DB is absent — step passes."""
        mock_client.run.return_value = _ssh_fail(returncode=1)
        bctx = _bctx(tmp_path)
        # Should not raise
        _run_db_check(mock_client, bctx)
        # Only one SSH call: test -f
        mock_client.run.assert_called_once()
        args = mock_client.run.call_args[0][0]
        assert "test" in args

    def test_db_check_ssh_error_passes(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """SSH error during existence check → treat as absent, pass."""
        mock_client.run.side_effect = SshError("connection lost")
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)


# ---------------------------------------------------------------------------
# (b) DB empty (0-byte) → quarantine
# ---------------------------------------------------------------------------


class TestDbEmpty:
    def test_zero_byte_db_quarantined(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """A 0-byte DB is quarantined via mv."""
        responses = [
            _ssh_ok(),        # test -f → exists
            _ssh_ok("0\n"),   # stat -c %s → 0 bytes
            _ssh_ok(),        # mv quarantine
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
        # The third call should be the quarantine mv
        assert mock_client.run.call_count == 3
        quarantine_call = mock_client.run.call_args_list[2]
        cmd = quarantine_call[0][0]
        assert "mv" in " ".join(cmd) if isinstance(cmd, list) else "mv" in cmd


# ---------------------------------------------------------------------------
# (c) DB > 10 GiB → quarantine
# ---------------------------------------------------------------------------


class TestDbTooLarge:
    def test_oversized_db_quarantined(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """A DB exceeding 10 GiB is quarantined."""
        too_large = str(10 * 1024 * 1024 * 1024 + 1)  # 10 GiB + 1 byte
        responses = [
            _ssh_ok(),             # test -f → exists
            _ssh_ok(f"{too_large}\n"),  # stat -c %s → too large
            _ssh_ok(),             # mv quarantine
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
        assert mock_client.run.call_count == 3
        quarantine_call = mock_client.run.call_args_list[2]
        cmd = quarantine_call[0][0]
        assert "mv" in " ".join(cmd) if isinstance(cmd, list) else "mv" in cmd


# ---------------------------------------------------------------------------
# (d) PRAGMA returns non-"ok" → quarantine
# ---------------------------------------------------------------------------


class TestDbCorrupt:
    def test_pragma_non_ok_quarantined(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """PRAGMA integrity_check returning anything other than 'ok' triggers quarantine."""
        valid_size = str(1024 * 1024)  # 1 MiB
        responses = [
            _ssh_ok(),                              # test -f → exists
            _ssh_ok(f"{valid_size}\n"),              # stat -c %s → valid size
            _ssh_ok("*** in database main ***\nPage 42: btree corrupt\n"),  # PRAGMA → corrupt
            _ssh_ok(),                              # mv quarantine
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
        assert mock_client.run.call_count == 4
        quarantine_call = mock_client.run.call_args_list[3]
        cmd = quarantine_call[0][0]
        assert "mv" in " ".join(cmd) if isinstance(cmd, list) else "mv" in cmd

    def test_pragma_ssh_error_quarantined(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """SSH error during PRAGMA → quarantine."""
        valid_size = str(1024 * 1024)
        mock_client.run.side_effect = [
            _ssh_ok(),                    # test -f → exists
            _ssh_ok(f"{valid_size}\n"),    # stat -c %s → valid
            SshError("timeout"),          # sqlite3 PRAGMA fails
            _ssh_ok(),                    # mv quarantine
        ]
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
        # After the SshError for PRAGMA, the quarantine mv is attempted
        assert mock_client.run.call_count == 4


# ---------------------------------------------------------------------------
# (e) PRAGMA returns "ok" → PASS
# ---------------------------------------------------------------------------


class TestDbHealthy:
    def test_pragma_ok_passes(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """A healthy DB with PRAGMA returning 'ok' passes without quarantine."""
        valid_size = str(50 * 1024 * 1024)  # 50 MiB
        responses = [
            _ssh_ok(),                    # test -f → exists
            _ssh_ok(f"{valid_size}\n"),    # stat -c %s → valid
            _ssh_ok("ok\n"),              # PRAGMA → ok
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
        # Only 3 calls — no quarantine mv
        assert mock_client.run.call_count == 3

    def test_pragma_ok_no_newline_passes(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """PRAGMA returning 'ok' without trailing newline still passes."""
        valid_size = str(50 * 1024 * 1024)
        responses = [
            _ssh_ok(),                    # test -f → exists
            _ssh_ok(f"{valid_size}\n"),    # stat -c %s → valid
            _ssh_ok("ok"),                # PRAGMA → ok (no trailing newline)
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
        assert mock_client.run.call_count == 3


# ---------------------------------------------------------------------------
# Edge cases: quarantine mv itself fails — bringup still continues
# ---------------------------------------------------------------------------


class TestQuarantineFailure:
    def test_quarantine_mv_fails_does_not_raise(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """If the quarantine mv fails, bringup still continues (no raise)."""
        responses = [
            _ssh_ok(),        # test -f → exists
            _ssh_ok("0\n"),   # stat -c %s → 0 bytes
            _ssh_fail(1),     # mv fails
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        # Must not raise
        _run_db_check(mock_client, bctx)

    def test_quarantine_ssh_error_does_not_raise(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """SSH error during quarantine mv does not raise."""
        responses = [
            _ssh_ok(),        # test -f → exists
            _ssh_ok("0\n"),   # stat -c %s → 0 bytes
            SshError("connection lost"),  # mv SSH error
        ]
        mock_client.run.side_effect = responses
        bctx = _bctx(tmp_path)
        _run_db_check(mock_client, bctx)
