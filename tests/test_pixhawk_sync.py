"""Tests for the Pixhawk configuration sync module and CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mower_rover.params.baseline import load_profile
from mower_rover.pixhawk.sync import SyncResult, sync_params, sync_pixhawk


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# sync_params
# ---------------------------------------------------------------------------


class TestSyncParams:
    """Test sync_params with a mock MAVLink connection."""

    def _mock_conn(self, current: dict[str, float]) -> MagicMock:
        """Create a mock connection that returns *current* for fetch_params."""
        conn = MagicMock()
        return conn

    def test_already_in_sync(self) -> None:
        """When all profile values already match, no apply should happen."""
        profile = load_profile("safety-defaults")
        current = {k: profile[k] for k in profile}

        conn = self._mock_conn(current)
        with (
            patch("mower_rover.pixhawk.sync.fetch_params", return_value=current),
            patch("mower_rover.pixhawk.sync.apply_params") as mock_apply,
        ):
            result = sync_params(conn, profiles=("safety-defaults",))

        assert result.ok
        assert result.params_already_current
        assert result.params_applied == 0
        mock_apply.assert_not_called()

    def test_drift_detected_and_applied(self) -> None:
        """When a param is drifted, apply should be called."""
        profile = load_profile("safety-defaults")
        # Make one param differ from profile
        current = {k: profile[k] for k in profile}
        first_key = next(iter(current))
        current[first_key] = current[first_key] + 99.0

        conn = self._mock_conn(current)
        with (
            patch("mower_rover.pixhawk.sync.fetch_params", return_value=current),
            patch("mower_rover.pixhawk.sync.apply_params") as mock_apply,
        ):
            result = sync_params(conn, profiles=("safety-defaults",))

        assert result.ok
        assert not result.params_already_current
        assert result.params_applied >= 1
        mock_apply.assert_called_once()

    def test_drift_dry_run_no_apply(self) -> None:
        """In dry_run mode, apply should NOT be called even if drift detected."""
        profile = load_profile("safety-defaults")
        current = {k: profile[k] for k in profile}
        first_key = next(iter(current))
        current[first_key] = current[first_key] + 99.0

        conn = self._mock_conn(current)
        with (
            patch("mower_rover.pixhawk.sync.fetch_params", return_value=current),
            patch("mower_rover.pixhawk.sync.apply_params") as mock_apply,
        ):
            result = sync_params(conn, profiles=("safety-defaults",), dry_run=True)

        assert result.ok
        assert result.params_applied >= 1
        mock_apply.assert_not_called()

    def test_unknown_profile_errors(self) -> None:
        """An unknown profile name should produce an error."""
        conn = MagicMock()
        result = sync_params(conn, profiles=("nonexistent-profile",))

        assert not result.ok
        assert any("unknown" in e for e in result.errors)

    def test_fetch_failure_errors(self) -> None:
        """If fetch_params raises, error should be recorded."""
        conn = MagicMock()
        with patch(
            "mower_rover.pixhawk.sync.fetch_params",
            side_effect=RuntimeError("timeout"),
        ):
            result = sync_params(conn, profiles=("safety-defaults",))

        assert not result.ok
        assert any("fetch_params" in e for e in result.errors)

    def test_apply_failure_errors(self) -> None:
        """If apply_params raises, error should be recorded."""
        profile = load_profile("safety-defaults")
        current = {k: profile[k] for k in profile}
        first_key = next(iter(current))
        current[first_key] = current[first_key] + 99.0

        conn = MagicMock()
        with (
            patch("mower_rover.pixhawk.sync.fetch_params", return_value=current),
            patch(
                "mower_rover.pixhawk.sync.apply_params",
                side_effect=RuntimeError("write error"),
            ),
        ):
            result = sync_params(conn, profiles=("safety-defaults",))

        assert not result.ok
        assert any("apply_params" in e for e in result.errors)


# ---------------------------------------------------------------------------
# sync_pixhawk (integration of params + lua)
# ---------------------------------------------------------------------------


class TestSyncPixhawk:
    """Test the combined sync_pixhawk orchestrator."""

    def test_all_in_sync(self) -> None:
        """When params match and Lua is current, result is ok."""
        profile = load_profile("safety-defaults")
        current = {k: profile[k] for k in profile}

        conn = MagicMock()
        with (
            patch("mower_rover.pixhawk.sync.fetch_params", return_value=current),
            patch("mower_rover.pixhawk.sync.check_and_deploy_lua") as mock_lua,
        ):
            result = sync_pixhawk(conn)

        assert result.ok
        assert result.params_already_current
        assert result.lua_deployed
        mock_lua.assert_called_once()

    def test_lua_failure_recorded(self) -> None:
        """If Lua deploy fails, error is recorded but params still work."""
        profile = load_profile("safety-defaults")
        current = {k: profile[k] for k in profile}

        conn = MagicMock()
        with (
            patch("mower_rover.pixhawk.sync.fetch_params", return_value=current),
            patch(
                "mower_rover.pixhawk.sync.check_and_deploy_lua",
                side_effect=RuntimeError("no FTP"),
            ),
        ):
            result = sync_pixhawk(conn)

        assert not result.ok
        assert not result.lua_deployed
        assert any("lua" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# SyncResult dataclass
# ---------------------------------------------------------------------------


class TestSyncResult:
    """Test SyncResult.ok property."""

    def test_ok_when_no_errors(self) -> None:
        assert SyncResult().ok

    def test_not_ok_with_errors(self) -> None:
        assert not SyncResult(errors=["fail"]).ok


# ---------------------------------------------------------------------------
# Unit file generation
# ---------------------------------------------------------------------------


class TestPixhawkSyncUnit:
    """Test systemd unit file generation."""

    def test_user_level_unit(self) -> None:
        from mower_rover.pixhawk.unit import generate_pixhawk_sync_unit_file

        content = generate_pixhawk_sync_unit_file(
            mower_jetson_path="/home/mower/.local/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            user_level=True,
        )
        assert "Type=oneshot" in content
        assert "mower-jetson pixhawk sync" in content
        assert "WantedBy=default.target" in content
        assert "User=" not in content  # user-level units don't need User=
        assert "dev-pixhawk.device" in content
        assert "RemainAfterExit=yes" in content

    def test_system_level_unit(self) -> None:
        from mower_rover.pixhawk.unit import generate_pixhawk_sync_unit_file

        content = generate_pixhawk_sync_unit_file(
            mower_jetson_path="/home/mower/.local/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            user_level=False,
        )
        assert "Type=oneshot" in content
        assert "User=mower" in content
        assert "WantedBy=multi-user.target" in content


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


class TestPixhawkCLI:
    """CLI smoke tests for the pixhawk subcommands."""

    def test_pixhawk_help(self, runner: CliRunner) -> None:
        from mower_rover.cli.jetson import app as jetson_app

        result = runner.invoke(jetson_app, ["pixhawk", "--help"])
        assert result.exit_code == 0, result.output
        assert "sync" in result.output

    def test_pixhawk_sync_help(self, runner: CliRunner) -> None:
        from mower_rover.cli.jetson import app as jetson_app

        result = runner.invoke(jetson_app, ["pixhawk", "sync", "--help"])
        assert result.exit_code == 0, result.output
        assert "--port" in result.output
        assert "--json" in result.output

    def test_pixhawk_sync_install_help(self, runner: CliRunner) -> None:
        from mower_rover.cli.jetson import app as jetson_app

        result = runner.invoke(jetson_app, ["pixhawk", "sync-install", "--help"])
        assert result.exit_code == 0, result.output
        assert "--yes" in result.output
        assert "--target-user" in result.output

    def test_pixhawk_sync_uninstall_help(self, runner: CliRunner) -> None:
        from mower_rover.cli.jetson import app as jetson_app

        result = runner.invoke(jetson_app, ["pixhawk", "sync-uninstall", "--help"])
        assert result.exit_code == 0, result.output
        assert "--yes" in result.output
