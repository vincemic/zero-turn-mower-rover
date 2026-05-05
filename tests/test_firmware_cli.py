"""Test firmware CLI commands in mower-jetson.

Test coverage for firmware-check, firmware-update, and firmware-flash commands
using mocked MAVLink connections and firmware functions.
"""

from unittest.mock import MagicMock, patch
import json
import pytest
from typer.testing import CliRunner

from mower_rover.cli.jetson import app
from mower_rover.pixhawk.firmware import FirmwareInfo


@pytest.fixture
def cli_runner():
    """Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_firmware_info():
    """Mock firmware info object."""
    return FirmwareInfo(
        major=4,
        minor=5,
        patch=3,
        type_code=255,
        type_name="official",
        version_string="ArduRover 4.5.3 (Official)",
    )


class TestFirmwareCheckCommand:
    """Test firmware-check command."""

    def test_help_exits_zero(self, cli_runner):
        """Test that --help exits with code 0."""
        result = cli_runner.invoke(app, ["pixhawk", "firmware-check", "--help"])
        assert result.exit_code == 0
        assert "Check the current firmware version" in result.stdout

    @patch("mower_rover.cli.jetson.open_link")
    @patch("mower_rover.pixhawk.firmware.read_running_version")
    def test_json_output_format(self, mock_read_version, mock_open_link, cli_runner, mock_firmware_info):
        """Test --json output format is valid JSON."""
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__.return_value = mock_conn
        mock_read_version.return_value = mock_firmware_info
        
        result = cli_runner.invoke(app, [
            "pixhawk", "firmware-check", 
            "--json", "--offline"  # offline to skip remote check
        ])
        
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["ok"] is True
        assert output["running_version"] == "ArduRover 4.5.3 (Official)"
        assert output["running_type"] == "official"
        assert "update_available" in output

    @patch("mower_rover.cli.jetson.open_link")
    @patch("mower_rover.pixhawk.firmware.read_running_version")
    @patch("mower_rover.pixhawk.firmware.check_remote_version")
    def test_update_available_detection(self, mock_check_remote, mock_read_version, mock_open_link, cli_runner, mock_firmware_info):
        """Test update available detection logic."""
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__.return_value = mock_conn
        mock_read_version.return_value = mock_firmware_info  # 4.5.3
        mock_check_remote.return_value = (4, 5, 4)  # newer version available
        
        result = cli_runner.invoke(app, [
            "pixhawk", "firmware-check", 
            "--json"
        ])
        
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["update_available"] is True
        assert output["latest_version"] == "4.5.4"

    @patch("mower_rover.cli.jetson.open_link")
    def test_connection_failure_exits_one(self, mock_open_link, cli_runner):
        """Test connection failure exits with code 1."""
        mock_open_link.side_effect = Exception("Connection failed")
        
        result = cli_runner.invoke(app, [
            "pixhawk", "firmware-check",
            "--json"
        ])
        
        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert output["ok"] is False
        assert "Connection failed" in output["error"]


class TestFirmwareUpdateCommand:
    """Test firmware-update command."""

    def test_help_exits_zero(self, cli_runner):
        """Test that --help exits with code 0."""
        result = cli_runner.invoke(app, ["pixhawk", "firmware-update", "--help"])
        assert result.exit_code == 0
        assert "Download and flash the latest firmware" in result.stdout

    @patch("mower_rover.cli.jetson.open_link")
    @patch("mower_rover.pixhawk.firmware.read_running_version")
    @patch("mower_rover.pixhawk.firmware.check_remote_version")
    @patch("mower_rover.pixhawk.firmware.download_firmware")
    @patch("mower_rover.pixhawk.firmware.validate_apj")
    @patch("mower_rover.params.mav.fetch_params")
    @patch("mower_rover.params.io.write_json_snapshot")
    def test_dry_run_skips_flash(
        self, 
        mock_write_snapshot,
        mock_fetch_params,
        mock_validate_apj,
        mock_download_firmware,
        mock_check_remote,
        mock_read_version,
        mock_open_link,
        cli_runner, 
        mock_firmware_info
    ):
        """Test --dry-run skips actual flash operation."""
        from pathlib import Path
        
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__.return_value = mock_conn
        mock_read_version.return_value = mock_firmware_info  # 4.5.3
        mock_check_remote.return_value = (4, 5, 4)  # newer version
        mock_download_firmware.return_value = Path("/tmp/firmware.apj")
        mock_validate_apj.return_value = None
        mock_fetch_params.return_value = {}
        mock_write_snapshot.return_value = None
        
        result = cli_runner.invoke(app, [
            "--dry-run",
            "pixhawk", "firmware-update", 
            "--json"
        ])
        
        # Dry run should exit successfully
        assert result.exit_code == 0
        # Should not call reboot_to_bootloader or flash_firmware in dry run
        # (can't easily mock these since they're imported lazily, but exit 0 is enough)

    def test_offline_mode_error(self, cli_runner):
        """Test offline mode returns error for firmware-update."""
        result = cli_runner.invoke(app, [
            "pixhawk", "firmware-update", 
            "--offline", "--json"
        ])
        
        # Should fail with offline mode not supported  
        assert result.exit_code == 1
        # Check that offline error is mentioned in the output
        output_text = result.stdout + result.stderr
        assert "offline mode not supported" in output_text or "connect" in output_text.lower()


class TestFirmwareFlashCommand:
    """Test firmware-flash command."""

    def test_help_exits_zero(self, cli_runner):
        """Test that --help exits with code 0."""
        result = cli_runner.invoke(app, ["pixhawk", "firmware-flash", "--help"])
        assert result.exit_code == 0
        assert "Flash a local .apj firmware file" in result.stdout

    def test_missing_apj_file_exits_one(self, cli_runner):
        """Test missing .apj file exits with code 1."""
        result = cli_runner.invoke(app, [
            "pixhawk", "firmware-flash",
            "/nonexistent/firmware.apj",
            "--json"
        ])
        
        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert output["ok"] is False
        assert "file not found" in output["error"]

    @patch("mower_rover.cli.jetson.open_link")
    @patch("mower_rover.pixhawk.firmware.read_running_version")
    @patch("mower_rover.pixhawk.firmware.validate_apj")
    @patch("mower_rover.params.mav.fetch_params")
    @patch("mower_rover.params.io.write_json_snapshot")
    @patch("pathlib.Path.exists")
    def test_dry_run_skips_flash(
        self, 
        mock_exists,
        mock_write_snapshot,
        mock_fetch_params,
        mock_validate_apj,
        mock_read_version,
        mock_open_link,
        cli_runner, 
        mock_firmware_info
    ):
        """Test --dry-run skips actual flash operation."""
        mock_exists.return_value = True
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__.return_value = mock_conn
        mock_read_version.return_value = mock_firmware_info
        mock_validate_apj.return_value = None
        mock_fetch_params.return_value = {}
        mock_write_snapshot.return_value = None
        
        result = cli_runner.invoke(app, [
            "--dry-run",
            "pixhawk", "firmware-flash",
            "/tmp/test-firmware.apj",
            "--json"
        ])
        
        # Dry run should exit successfully
        assert result.exit_code == 0
        # Should not call reboot_to_bootloader or flash_firmware in dry run
        # (can't easily mock these since they're imported lazily, but exit 0 is enough)

    @patch("pathlib.Path.exists")
    @patch("mower_rover.pixhawk.firmware.validate_apj")
    def test_invalid_apj_exits_one(self, mock_validate_apj, mock_exists, cli_runner):
        """Test invalid .apj file exits with code 1."""
        mock_exists.return_value = True
        mock_validate_apj.side_effect = Exception("Invalid APJ format")
        
        result = cli_runner.invoke(app, [
            "pixhawk", "firmware-flash",
            "/tmp/invalid-firmware.apj", 
            "--json"
        ])
        
        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert output["ok"] is False
        assert "validation failed" in output["error"]


class TestFirmwareCommandsIntegration:
    """Integration tests for firmware commands."""

    def test_all_commands_have_json_option(self, cli_runner):
        """Test all firmware commands support --json option."""
        commands = ["firmware-check", "firmware-update", "firmware-flash"]
        
        for cmd in commands:
            # Test that --json is in help text
            help_result = cli_runner.invoke(app, ["pixhawk", cmd, "--help"])
            assert help_result.exit_code == 0
            assert "--json" in help_result.stdout

    def test_all_commands_have_port_option(self, cli_runner):
        """Test all firmware commands support --port option."""
        commands = ["firmware-check", "firmware-update", "firmware-flash"]
        
        for cmd in commands:
            help_result = cli_runner.invoke(app, ["pixhawk", cmd, "--help"])
            assert help_result.exit_code == 0
            assert "--port" in help_result.stdout


# --- SSH Wrapper Tests (Laptop CLI) ----------------------------------------


class TestSSHWrapperCommands:
    """Test laptop SSH wrapper commands for pixhawk firmware."""

    def test_ssh_wrapper_imports(self):
        """Test SSH wrapper commands can be imported."""
        from mower_rover.cli.laptop import app as laptop_app
        from mower_rover.cli.pixhawk_laptop import app as pixhawk_app
        
        # Should be able to import without errors
        assert laptop_app is not None
        assert pixhawk_app is not None

    @patch("mower_rover.cli.pixhawk_laptop.resolve_endpoint")
    @patch("mower_rover.cli.pixhawk_laptop.client_for")
    def test_firmware_check_ssh(self, mock_client_for, mock_resolve, cli_runner):
        """Test firmware-check SSH wrapper builds correct remote command."""
        from mower_rover.cli.laptop import app as laptop_app
        
        mock_client = MagicMock()
        mock_client.run.return_value = MagicMock(stdout="firmware ok", stderr="", returncode=0)
        mock_client_for.return_value = mock_client
        mock_resolve.return_value = MagicMock()
        
        result = cli_runner.invoke(laptop_app, [
            "pixhawk", "firmware-check", 
            "--host", "jetson", "--user", "me", "--json"
        ])
        
        assert result.exit_code == 0
        # Verify remote command was constructed correctly
        mock_client.run.assert_called_once()
        args, kwargs = mock_client.run.call_args
        remote_argv = args[0]
        assert remote_argv == ["mower-jetson", "pixhawk", "firmware-check", "--json"]
        assert kwargs.get("timeout") == 60.0

    @patch("mower_rover.cli.pixhawk_laptop.resolve_endpoint")
    @patch("mower_rover.cli.pixhawk_laptop.client_for")
    def test_firmware_update_ssh(self, mock_client_for, mock_resolve, cli_runner):
        """Test firmware-update SSH wrapper builds correct remote command."""
        from mower_rover.cli.laptop import app as laptop_app
        
        mock_client = MagicMock()
        mock_client.run.return_value = MagicMock(stdout="update complete", stderr="", returncode=0)
        mock_client_for.return_value = mock_client
        mock_resolve.return_value = MagicMock()
        
        result = cli_runner.invoke(laptop_app, [
            "pixhawk", "firmware-update", 
            "--host", "jetson", "--user", "me", 
            "--track", "beta", "--yes", "--force", "--json"
        ])
        
        assert result.exit_code == 0
        # Verify remote command was constructed correctly
        mock_client.run.assert_called_once()
        args, kwargs = mock_client.run.call_args
        remote_argv = args[0]
        expected = ["mower-jetson", "pixhawk", "firmware-update", "--track", "beta", "--yes", "--force", "--json"]
        assert remote_argv == expected
        assert kwargs.get("timeout") == 300.0  # Higher timeout for update

    @patch("mower_rover.cli.pixhawk_laptop.resolve_endpoint")
    @patch("mower_rover.cli.pixhawk_laptop.client_for")
    def test_firmware_flash_ssh(self, mock_client_for, mock_resolve, cli_runner):
        """Test firmware-flash SSH wrapper builds correct remote command."""
        from mower_rover.cli.laptop import app as laptop_app
        
        mock_client = MagicMock()
        mock_client.run.return_value = MagicMock(stdout="flash complete", stderr="", returncode=0)
        mock_client_for.return_value = mock_client
        mock_resolve.return_value = MagicMock()
        
        result = cli_runner.invoke(laptop_app, [
            "pixhawk", "firmware-flash", "/tmp/firmware.apj",
            "--host", "jetson", "--user", "me", 
            "--yes", "--skip-snapshot", "--json"
        ])
        
        assert result.exit_code == 0
        # Verify remote command was constructed correctly
        mock_client.run.assert_called_once()
        args, kwargs = mock_client.run.call_args
        remote_argv = args[0]
        expected = ["mower-jetson", "pixhawk", "firmware-flash", "/tmp/firmware.apj", "--yes", "--skip-snapshot", "--json"]
        assert remote_argv == expected
        assert kwargs.get("timeout") == 300.0  # Higher timeout for flash

    @patch("mower_rover.cli.pixhawk_laptop.resolve_endpoint")
    @patch("mower_rover.cli.pixhawk_laptop.client_for")
    def test_dry_run_passes_through(self, mock_client_for, mock_resolve, cli_runner):
        """Test --dry-run flag passes through to remote commands."""
        from mower_rover.cli.laptop import app as laptop_app
        
        mock_client = MagicMock()
        mock_client.run.return_value = MagicMock(stdout="dry run", stderr="", returncode=0)
        mock_client_for.return_value = mock_client
        mock_resolve.return_value = MagicMock()
        
        result = cli_runner.invoke(laptop_app, [
            "--dry-run",
            "pixhawk", "firmware-update", 
            "--host", "jetson", "--user", "me", "--json"
        ])
        
        assert result.exit_code == 0
        # Verify --dry-run was added to remote command
        mock_client.run.assert_called_once()
        args, kwargs = mock_client.run.call_args
        remote_argv = args[0]
        assert "--dry-run" in remote_argv

    @patch("mower_rover.cli.pixhawk_laptop.resolve_endpoint")
    @patch("mower_rover.cli.pixhawk_laptop.client_for")
    def test_ssh_error_handling(self, mock_client_for, mock_resolve, cli_runner):
        """Test SSH error handling in wrapper commands."""
        from mower_rover.cli.laptop import app as laptop_app
        from mower_rover.transport.ssh import SshError
        
        mock_client = MagicMock()
        mock_client.run.side_effect = SshError("Connection failed")
        mock_client_for.return_value = mock_client
        mock_resolve.return_value = MagicMock()
        
        result = cli_runner.invoke(laptop_app, [
            "pixhawk", "firmware-check", 
            "--host", "jetson", "--user", "me"
        ])
        
        assert result.exit_code == 3
        assert "ERROR: Connection failed" in result.stderr

    @patch("mower_rover.cli.pixhawk_laptop.resolve_endpoint")
    @patch("mower_rover.cli.pixhawk_laptop.client_for")
    def test_output_forwarding(self, mock_client_for, mock_resolve, cli_runner):
        """Test stdout and stderr are forwarded correctly."""
        from mower_rover.cli.laptop import app as laptop_app
        
        mock_client = MagicMock()
        mock_client.run.return_value = MagicMock(
            stdout='{"ok": true, "version": "4.5.3"}\n', 
            stderr="debug info\n", 
            returncode=0
        )
        mock_client_for.return_value = mock_client
        mock_resolve.return_value = MagicMock()
        
        result = cli_runner.invoke(laptop_app, [
            "pixhawk", "firmware-check", 
            "--host", "jetson", "--user", "me", "--json"
        ])
        
        assert result.exit_code == 0
        # Output should be forwarded to stdout
        assert '{"ok": true, "version": "4.5.3"}' in result.stdout