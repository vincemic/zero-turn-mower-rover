"""Tests for `mower jetson bringup` — automated Jetson provisioning."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from click.exceptions import Exit as ClickExit
from typer.testing import CliRunner

from mower_rover.cli.bringup import (
    STEP_NAMES,
    BringupContext,
    _archive_binaries_check,
    _build_depthai_check,
    _build_rtabmap_check,
    _build_slam_node_check,
    _check_ssh_ok,
    _clear_host_key_needed,
    _cli_installed,
    _final_verify_check,
    _harden_done,
    _linger_enabled,
    _pixhawk_udev_done,
    _reboot_check,
    _restore_binaries_check,
    _run_archive_binaries,
    _run_build_depthai,
    _run_build_rtabmap,
    _run_build_slam_node,
    _run_clear_host_key,
    _run_enable_linger,
    _run_final_verify,
    _run_harden,
    _run_install_cli,
    _run_pixhawk_udev,
    _run_reboot_and_wait,
    _run_restore_binaries,
    _run_vslam_config,
    _run_vslam_services,
    _service_active,
    _uv_installed,
    _verify_check,
    _vslam_config_exists,
    _vslam_services_active,
)
from mower_rover.cli.laptop import app as laptop_app
from mower_rover.config.laptop import JetsonEndpoint
from mower_rover.transport.ssh import JetsonClient, SshError, SshResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def endpoint() -> JetsonEndpoint:
    return JetsonEndpoint(host="10.0.0.42", user="mower", port=22, key_path=None)


@pytest.fixture
def mock_client(endpoint: JetsonEndpoint) -> JetsonClient:
    client = MagicMock(spec=JetsonClient)
    client.endpoint = endpoint
    return client


def _ssh_ok(stdout: str = "", stderr: str = "") -> SshResult:
    """Shorthand for a successful SshResult."""
    return SshResult(argv=["ssh"], returncode=0, stdout=stdout, stderr=stderr)


def _ssh_fail(returncode: int = 1, stdout: str = "", stderr: str = "") -> SshResult:
    """Shorthand for a failed SshResult."""
    return SshResult(argv=["ssh"], returncode=returncode, stdout=stdout, stderr=stderr)


def _bctx(tmp_path: Path, *, dry_run: bool = False, yes: bool = True) -> BringupContext:
    """Build a BringupContext for testing."""
    from rich.console import Console

    return BringupContext(
        project_root=tmp_path,
        dry_run=dry_run,
        yes=yes,
        correlation_id=None,
        console=Console(force_terminal=True),
    )


# ---------------------------------------------------------------------------
# 4.1 — CLI smoke tests
# ---------------------------------------------------------------------------


class TestBringupCLISmoke:
    """--help, --step validation, --dry-run."""

    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(laptop_app, ["jetson", "bringup", "--help"])
        assert result.exit_code == 0, result.output
        assert "bringup" in result.stdout.lower()
        # All step names mentioned in help text
        for name in STEP_NAMES:
            assert name in result.stdout

    def test_step_invalid_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )
        with patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe"):
            result = runner.invoke(
                laptop_app,
                ["jetson", "bringup", "--step", "bogus-step", "--config", str(cfg)],
            )
        assert result.exit_code == 2
        assert "Unknown step" in result.output or "bogus-step" in result.output

    def test_dry_run_prints_plan(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )
        with patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe"):
            result = runner.invoke(
                laptop_app,
                ["--dry-run", "jetson", "bringup", "--config", str(cfg)],
            )
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output


# ---------------------------------------------------------------------------
# 4.2 — Check functions (mocked JetsonClient)
# ---------------------------------------------------------------------------


class TestCheckSshOk:
    def test_returns_true_on_success(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="ok\n")
        assert _check_ssh_ok(mock_client) is True

    def test_returns_false_on_failure(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail()
        assert _check_ssh_ok(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("connection refused")
        assert _check_ssh_ok(mock_client) is False


# ---------------------------------------------------------------------------
# clear-host-key step
# ---------------------------------------------------------------------------


class TestClearHostKeyNeeded:
    def test_returns_true_when_ssh_succeeds(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="ok\n")
        assert _clear_host_key_needed(mock_client) is True

    def test_returns_false_on_host_key_changed_in_result(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail(
            returncode=255,
            stderr="@@@@@@@@@@@@@@@@@@@@@@@@@@@\nREMOTE HOST IDENTIFICATION HAS CHANGED\n",
        )
        assert _clear_host_key_needed(mock_client) is False

    def test_returns_false_on_host_key_verification_failed_in_result(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail(
            returncode=255,
            stderr="Host key verification failed.\n",
        )
        assert _clear_host_key_needed(mock_client) is False

    def test_returns_true_on_other_ssh_failure(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail(returncode=255, stderr="Connection refused")
        assert _clear_host_key_needed(mock_client) is True

    def test_returns_false_on_ssh_error_with_host_key_msg(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("Host key verification failed")
        assert _clear_host_key_needed(mock_client) is False

    def test_returns_true_on_ssh_error_without_host_key_msg(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("connection timed out")
        assert _clear_host_key_needed(mock_client) is True


class TestRunClearHostKey:
    def test_runs_ssh_keygen_locally(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        fake_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("mower_rover.cli.bringup.subprocess.run", return_value=fake_proc) as mock_run:
            _run_clear_host_key(mock_client, bctx)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["ssh-keygen", "-R", "10.0.0.42"]

    def test_exits_on_failure(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        fake_proc = MagicMock(returncode=1, stdout="", stderr="error")
        with (
            patch("mower_rover.cli.bringup.subprocess.run", return_value=fake_proc),
            pytest.raises(ClickExit),
        ):
            _run_clear_host_key(mock_client, bctx)

    def test_exits_on_ssh_keygen_not_found(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        with (
            patch("mower_rover.cli.bringup.subprocess.run", side_effect=FileNotFoundError("ssh-keygen")),
            pytest.raises(ClickExit),
        ):
            _run_clear_host_key(mock_client, bctx)


# ---------------------------------------------------------------------------
# enable-linger step
# ---------------------------------------------------------------------------


class TestLingerEnabled:
    def test_returns_true_when_linger_yes(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="yes\n")
        assert _linger_enabled(mock_client) is True

    def test_returns_false_when_linger_no(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="no\n")
        assert _linger_enabled(mock_client) is False

    def test_returns_false_on_command_failure(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail()
        assert _linger_enabled(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("timeout")
        assert _linger_enabled(mock_client) is False


class TestRunEnableLinger:
    def test_runs_loginctl_enable_linger(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run.return_value = _ssh_ok()
        _run_enable_linger(mock_client, bctx)
        mock_client.run.assert_called_once()
        call_args = mock_client.run.call_args[0][0]
        assert call_args == ["sudo", "loginctl", "enable-linger", "mower"]

    def test_exits_on_failure(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run.return_value = _ssh_fail(returncode=1, stderr="permission denied")
        with pytest.raises(ClickExit):
            _run_enable_linger(mock_client, bctx)

    def test_exits_on_ssh_error(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run.side_effect = SshError("disconnected")
        with pytest.raises(ClickExit):
            _run_enable_linger(mock_client, bctx)


# ---------------------------------------------------------------------------
# reboot-and-wait step
# ---------------------------------------------------------------------------


class TestRebootCheck:
    def test_returns_true_when_cmdline_has_usbcore(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(
            stdout="root=/dev/nvme0n1p1 usbcore.autosuspend=-1 usbcore.usbfs_memory_mb=1000\n"
        )
        assert _reboot_check(mock_client) is True

    def test_returns_false_when_cmdline_missing_usbcore(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="root=/dev/nvme0n1p1\n")
        assert _reboot_check(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("connection refused")
        assert _reboot_check(mock_client) is False


class TestRunRebootAndWait:
    def test_reboot_and_reconnect(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        # First call: sudo reboot (raises SshError — SSH disconnect expected)
        # Second call: echo ok (polling reconnect — succeeds)
        # Third call: cat /proc/cmdline (verification)
        call_count = 0

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SshError("Connection closed by remote host")
            if call_count == 2:
                return _ssh_ok(stdout="ok\n")
            if call_count == 3:
                return _ssh_ok(stdout="root=/dev/nvme0n1p1 usbcore.autosuspend=-1\n")
            return _ssh_ok()

        mock_client.run.side_effect = side_effect

        with patch("mower_rover.cli.bringup.time.sleep"):
            _run_reboot_and_wait(mock_client, bctx)

        assert call_count == 3

    def test_timeout_if_jetson_never_comes_back(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        call_count = 0

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SshError("Connection closed")
            raise SshError("Connection refused")

        mock_client.run.side_effect = side_effect

        with (
            patch("mower_rover.cli.bringup.time.sleep"),
            patch("mower_rover.cli.bringup.time.monotonic", side_effect=[0, 10, 20, 200]),
            pytest.raises(ClickExit),
        ):
            _run_reboot_and_wait(mock_client, bctx)

    def test_exits_if_cmdline_missing_usbcore(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        call_count = 0

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _ssh_ok()  # reboot (didn't raise — that's fine)
            if call_count == 2:
                return _ssh_ok(stdout="ok\n")  # polling
            # cmdline check — missing the param
            return _ssh_ok(stdout="root=/dev/nvme0n1p1\n")

        mock_client.run.side_effect = side_effect

        with (
            patch("mower_rover.cli.bringup.time.sleep"),
            pytest.raises(ClickExit),
        ):
            _run_reboot_and_wait(mock_client, bctx)


class TestHardenDone:
    def test_returns_true_when_both_conditions_met(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),  # test -f marker file
            _ssh_ok(stdout="multi-user.target\n"),  # systemctl get-default
        ]
        assert _harden_done(mock_client) is True

    def test_returns_false_when_marker_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_fail(),  # marker file not found
            _ssh_ok(stdout="multi-user.target\n"),
        ]
        assert _harden_done(mock_client) is False

    def test_returns_false_when_graphical_target(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),  # marker file exists
            _ssh_ok(stdout="graphical.target\n"),  # wrong target
        ]
        assert _harden_done(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("timeout")
        assert _harden_done(mock_client) is False


class TestUvInstalled:
    def test_returns_true_when_version_succeeds(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="uv 0.6.0\n")
        assert _uv_installed(mock_client) is True

    def test_returns_false_when_command_fails(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail(stderr="uv: not found")
        assert _uv_installed(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("connection lost")
        assert _uv_installed(mock_client) is False


class TestCliInstalled:
    def test_returns_true_when_version_succeeds(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="mower-jetson 0.1.0\n")
        assert _cli_installed(mock_client) is True

    def test_returns_false_when_command_fails(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail(stderr="mower-jetson: not found")
        assert _cli_installed(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("disconnected")
        assert _cli_installed(mock_client) is False


class TestVerifyCheck:
    def test_always_returns_false(self, mock_client: MagicMock) -> None:
        assert _verify_check(mock_client) is False


class TestServiceActive:
    def test_returns_true_when_active(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout="active\n")
        assert _service_active(mock_client) is True

    def test_returns_false_when_inactive(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail(returncode=3, stdout="inactive\n")
        assert _service_active(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("network unreachable")
        assert _service_active(mock_client) is False


# ---------------------------------------------------------------------------
# 4.3 — _run_install_cli (mocked subprocess + JetsonClient)
# ---------------------------------------------------------------------------


class TestRunInstallCli:
    def test_full_flow(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Wheel build → push → install → cleanup."""
        bctx = _bctx(tmp_path)

        # Fake uv build: create a .whl file in the output dir
        def fake_build(args, **kwargs):
            out_dir = Path(args[args.index("--out-dir") + 1])
            (out_dir / "mower_rover-0.1.0-py3-none-any.whl").write_bytes(b"fake")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_client.push.return_value = _ssh_ok()
        mock_client.run.return_value = _ssh_ok()  # uv tool install + rm cleanup

        with patch("mower_rover.cli.bringup.subprocess.run", side_effect=fake_build):
            from mower_rover.cli.bringup import _run_install_cli

            _run_install_cli(mock_client, bctx)

        # Push was called with the wheel
        mock_client.push.assert_called_once()
        push_args = mock_client.push.call_args
        local_path = push_args[0][0]
        remote_path = push_args[0][1]
        assert str(local_path).endswith(".whl")
        assert remote_path.startswith("~/")
        assert remote_path.endswith(".whl")

        # uv tool install was called
        install_call = mock_client.run.call_args_list[0]
        install_argv = install_call[0][0]
        assert "uv" in " ".join(install_argv)
        assert "tool" in " ".join(install_argv)
        assert "install" in " ".join(install_argv)

    def test_build_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        fake_proc = MagicMock(returncode=1, stdout="", stderr="build error")

        with (
            patch("mower_rover.cli.bringup.subprocess.run", return_value=fake_proc),
            pytest.raises(ClickExit),
        ):
            _run_install_cli(mock_client, bctx)

    def test_push_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        def fake_build(args, **kwargs):
            out_dir = Path(args[args.index("--out-dir") + 1])
            (out_dir / "mower_rover-0.1.0-py3-none-any.whl").write_bytes(b"fake")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_client.push.side_effect = SshError("push failed")

        with (
            patch("mower_rover.cli.bringup.subprocess.run", side_effect=fake_build),
            pytest.raises(ClickExit),
        ):
            _run_install_cli(mock_client, bctx)


# ---------------------------------------------------------------------------
# 4.4 — _run_harden (mocked push + run)
# ---------------------------------------------------------------------------


class TestRunHarden:
    def test_full_flow(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Script pushed, executed, cleaned up."""
        bctx = _bctx(tmp_path, yes=True)

        # Create the hardening script so the code finds it
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "jetson-harden.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")

        mock_client.push.return_value = _ssh_ok()
        mock_client.run.side_effect = [
            _ssh_ok(stdout="hardening complete\n"),  # sudo bash jetson-harden.sh
            _ssh_ok(),  # rm cleanup
        ]

        _run_harden(mock_client, bctx)

        # Script pushed to ~/jetson-harden.sh
        mock_client.push.assert_called_once()
        push_args = mock_client.push.call_args[0]
        assert Path(push_args[0]).name == "jetson-harden.sh"
        assert push_args[1] == "~/jetson-harden.sh"

        # Run with sudo bash --os-only
        run_call = mock_client.run.call_args_list[0]
        run_argv = run_call[0][0]
        assert "sudo" in run_argv
        assert "bash" in run_argv
        assert "--os-only" in run_argv

        # Temp file cleaned up
        cleanup_call = mock_client.run.call_args_list[1]
        cleanup_argv = cleanup_call[0][0]
        assert "rm" in cleanup_argv

    def test_script_not_found_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        # No scripts/ dir → script not found
        with pytest.raises(ClickExit):
            _run_harden(mock_client, bctx)

    def test_push_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "jetson-harden.sh").write_text("#!/bin/bash\n", encoding="utf-8")

        mock_client.push.side_effect = SshError("scp failed")

        with pytest.raises(ClickExit):
            _run_harden(mock_client, bctx)

    def test_harden_script_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "jetson-harden.sh").write_text("#!/bin/bash\n", encoding="utf-8")

        mock_client.push.return_value = _ssh_ok()
        mock_client.run.return_value = _ssh_fail(returncode=1, stderr="permission denied")

        with pytest.raises(ClickExit):
            _run_harden(mock_client, bctx)

    def test_skipped_when_not_confirmed(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=False)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "jetson-harden.sh").write_text("#!/bin/bash\n", encoding="utf-8")

        # Simulate declining the confirmation prompt
        with patch("mower_rover.cli.bringup.input", return_value="n"):
            _run_harden(mock_client, bctx)

        # Neither push nor run should have been called
        mock_client.push.assert_not_called()
        mock_client.run.assert_not_called()


# ---------------------------------------------------------------------------
# 4.5 — pixhawk-udev step
# ---------------------------------------------------------------------------


class TestPixhawkUdevDone:
    def test_returns_true_when_all_exist(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),  # test -f rules file
            _ssh_ok(),  # test -d /var/lib/mower
            _ssh_ok(),  # test -d /etc/mower
        ]
        assert _pixhawk_udev_done(mock_client) is True

    def test_returns_false_when_rules_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_fail(),  # rules file missing
            _ssh_ok(),
            _ssh_ok(),
        ]
        assert _pixhawk_udev_done(mock_client) is False

    def test_returns_false_when_var_lib_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),
            _ssh_fail(),  # /var/lib/mower missing
            _ssh_ok(),
        ]
        assert _pixhawk_udev_done(mock_client) is False

    def test_returns_false_when_etc_mower_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),
            _ssh_ok(),
            _ssh_fail(),  # /etc/mower missing
        ]
        assert _pixhawk_udev_done(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("timeout")
        assert _pixhawk_udev_done(mock_client) is False


class TestRunPixhawkUdev:
    def test_full_flow(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "90-pixhawk-usb.rules").write_text(
            'SUBSYSTEM=="tty"', encoding="utf-8",
        )

        mock_client.push.return_value = _ssh_ok()
        mock_client.run.side_effect = [
            _ssh_ok(),  # sudo cp
            _ssh_ok(),  # udevadm reload + trigger
            _ssh_ok(),  # mkdir + chown
            _ssh_ok(),  # rm cleanup
        ]

        _run_pixhawk_udev(mock_client, bctx)

        mock_client.push.assert_called_once()
        assert mock_client.run.call_count == 4
        # Verify udev reload command
        udev_cmd = mock_client.run.call_args_list[1][0][0]
        assert "udevadm" in " ".join(udev_cmd)
        # Verify mkdir command uses the endpoint username
        mkdir_cmd = mock_client.run.call_args_list[2][0][0]
        assert "mower" in " ".join(mkdir_cmd)

    def test_rules_file_not_found_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        # No scripts dir
        with pytest.raises(ClickExit):
            _run_pixhawk_udev(mock_client, bctx)

    def test_push_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "90-pixhawk-usb.rules").write_text("rule", encoding="utf-8")

        mock_client.push.side_effect = SshError("scp failed")

        with pytest.raises(ClickExit):
            _run_pixhawk_udev(mock_client, bctx)

    def test_skipped_when_not_confirmed(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=False)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "90-pixhawk-usb.rules").write_text("rule", encoding="utf-8")

        with patch("mower_rover.cli.bringup.input", return_value="n"):
            _run_pixhawk_udev(mock_client, bctx)

        mock_client.push.assert_not_called()
        mock_client.run.assert_not_called()


# ---------------------------------------------------------------------------
# 4.6 — vslam-config step
# ---------------------------------------------------------------------------


class TestVslamConfigExists:
    def test_returns_true_when_file_exists(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok()
        assert _vslam_config_exists(mock_client) is True

    def test_returns_false_when_file_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail()
        assert _vslam_config_exists(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("timeout")
        assert _vslam_config_exists(mock_client) is False


class TestRunVslamConfig:
    def test_full_flow(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        mock_client.push.return_value = _ssh_ok()
        mock_client.run.side_effect = [
            _ssh_ok(),  # sudo cp
            _ssh_ok(),  # rm cleanup
        ]

        _run_vslam_config(mock_client, bctx)

        mock_client.push.assert_called_once()
        push_args = mock_client.push.call_args[0]
        assert str(push_args[1]) == "~/vslam.yaml"
        # sudo cp was called
        cp_cmd = mock_client.run.call_args_list[0][0][0]
        assert "sudo" in " ".join(cp_cmd)
        assert "/etc/mower/vslam.yaml" in " ".join(cp_cmd)

    def test_push_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        mock_client.push.side_effect = SshError("scp failed")

        with pytest.raises(ClickExit):
            _run_vslam_config(mock_client, bctx)


# ---------------------------------------------------------------------------
# 4.7 — vslam-services step
# ---------------------------------------------------------------------------


class TestVslamServicesActive:
    def test_returns_true_when_both_active(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),  # mower-vslam active
            _ssh_ok(),  # mower-vslam-bridge active
        ]
        assert _vslam_services_active(mock_client) is True

    def test_returns_false_when_vslam_inactive(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_fail(returncode=3),  # mower-vslam inactive
            _ssh_ok(),
        ]
        assert _vslam_services_active(mock_client) is False

    def test_returns_false_when_bridge_inactive(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),
            _ssh_fail(returncode=3),  # bridge inactive
        ]
        assert _vslam_services_active(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("network unreachable")
        assert _vslam_services_active(mock_client) is False


class TestRunVslamServices:
    def test_full_flow(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)

        mock_client.run.side_effect = [
            _ssh_ok(),  # vslam install
            _ssh_ok(),  # bridge-install
            _ssh_ok(),  # systemctl start
        ]

        _run_vslam_services(mock_client, bctx)

        assert mock_client.run.call_count == 3
        # vslam install
        vslam_cmd = mock_client.run.call_args_list[0][0][0]
        assert "vslam install" in " ".join(vslam_cmd)
        # bridge-install
        bridge_cmd = mock_client.run.call_args_list[1][0][0]
        assert "bridge-install" in " ".join(bridge_cmd)
        # systemctl start
        start_cmd = mock_client.run.call_args_list[2][0][0]
        assert "systemctl" in " ".join(start_cmd)
        assert "mower-vslam" in " ".join(start_cmd)

    def test_vslam_install_failure_exits(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=True)
        mock_client.run.return_value = _ssh_fail(returncode=1, stderr="install error")

        with pytest.raises(ClickExit):
            _run_vslam_services(mock_client, bctx)

    def test_skipped_when_not_confirmed(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path, yes=False)

        with patch("mower_rover.cli.bringup.input", return_value="n"):
            _run_vslam_services(mock_client, bctx)

        mock_client.run.assert_not_called()


# ---------------------------------------------------------------------------
# 4.7b — Build steps (restore, rtabmap, depthai, slam-node, archive)
# ---------------------------------------------------------------------------


class TestRestoreBinariesCheck:
    def test_returns_true_when_all_markers_match(self, mock_client: MagicMock) -> None:
        import json

        mock_client.run.side_effect = [
            _ssh_ok(stdout=json.dumps({"version": "0.21.6"})),
            _ssh_ok(stdout=json.dumps({"version": "v3.5.0"})),
            _ssh_ok(stdout=json.dumps({"version": "1.0.0"})),
        ]
        assert _restore_binaries_check(mock_client) is True

    def test_returns_false_when_rtabmap_wrong_version(self, mock_client: MagicMock) -> None:
        import json

        mock_client.run.side_effect = [
            _ssh_ok(stdout=json.dumps({"version": "0.23.2"})),
            _ssh_ok(stdout=json.dumps({"version": "v3.5.0"})),
            _ssh_ok(stdout=json.dumps({"version": "1.0.0"})),
        ]
        assert _restore_binaries_check(mock_client) is False

    def test_returns_false_when_marker_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_fail(),  # rtabmap marker missing
            _ssh_ok(stdout='{"version": "v3.5.0"}'),
            _ssh_ok(stdout='{"version": "1.0.0"}'),
        ]
        assert _restore_binaries_check(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("connection refused")
        assert _restore_binaries_check(mock_client) is False


class TestRunRestoreBinaries:
    def test_restores_from_archive(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        # Create a fake backup dir with an archive
        backup_dir = tmp_path / ".local" / "share" / "mower" / "backups"
        backup_dir.mkdir(parents=True)
        archive = backup_dir / "mower-binaries-2026-04-26.tar.gz"
        archive.write_bytes(b"fake-tar")

        mock_client.push.return_value = _ssh_ok()
        mock_client.run.side_effect = [
            _ssh_ok(),  # tar extract
            _ssh_ok(),  # rm cleanup
        ]

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            _run_restore_binaries(mock_client, bctx)

        mock_client.push.assert_called_once()

    def test_skips_when_no_backup_dir(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        fake_dir = tmp_path / "nonexistent"

        with patch("mower_rover.cli.bringup._BACKUP_DIR", fake_dir):
            _run_restore_binaries(mock_client, bctx)

        mock_client.push.assert_not_called()

    def test_skips_when_no_archives(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            _run_restore_binaries(mock_client, bctx)

        mock_client.push.assert_not_called()


class TestBuildRtabmapCheck:
    def test_returns_true_when_version_matches(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout='{"version": "0.21.6"}')
        assert _build_rtabmap_check(mock_client) is True

    def test_returns_false_when_version_wrong(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout='{"version": "0.23.2"}')
        assert _build_rtabmap_check(mock_client) is False

    def test_returns_false_when_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail()
        assert _build_rtabmap_check(mock_client) is False


class TestRunBuildRtabmap:
    def test_calls_run_streaming(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run_streaming.return_value = _ssh_ok()

        _run_build_rtabmap(mock_client, bctx)

        mock_client.run_streaming.assert_called_once()
        call_kwargs = mock_client.run_streaming.call_args
        assert call_kwargs[1]["timeout"] == 3600

    def test_exits_on_failure(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run_streaming.return_value = _ssh_fail()

        with pytest.raises(ClickExit):
            _run_build_rtabmap(mock_client, bctx)

    def test_exits_on_ssh_error(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run_streaming.side_effect = SshError("timeout")

        with pytest.raises(ClickExit):
            _run_build_rtabmap(mock_client, bctx)


class TestBuildDepthaiCheck:
    def test_returns_true_when_version_matches(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout='{"version": "v3.5.0"}')
        assert _build_depthai_check(mock_client) is True

    def test_returns_false_when_version_wrong(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_ok(stdout='{"version": "v2.0.0"}')
        assert _build_depthai_check(mock_client) is False

    def test_returns_false_when_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail()
        assert _build_depthai_check(mock_client) is False


class TestRunBuildDepthai:
    def test_calls_run_streaming(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run_streaming.return_value = _ssh_ok()

        _run_build_depthai(mock_client, bctx)

        mock_client.run_streaming.assert_called_once()
        call_kwargs = mock_client.run_streaming.call_args
        assert call_kwargs[1]["timeout"] == 3600

    def test_exits_on_failure(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        mock_client.run_streaming.return_value = _ssh_fail()

        with pytest.raises(ClickExit):
            _run_build_depthai(mock_client, bctx)


class TestBuildSlamNodeCheck:
    def test_returns_true_when_binary_and_marker(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),  # test -f binary
            _ssh_ok(stdout='{"version": "1.0.0"}'),  # marker
        ]
        assert _build_slam_node_check(mock_client) is True

    def test_returns_false_when_binary_missing(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_fail(),  # binary not found
        ]
        assert _build_slam_node_check(mock_client) is False

    def test_returns_false_when_marker_wrong(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = [
            _ssh_ok(),  # binary exists
            _ssh_ok(stdout='{"version": "0.9.0"}'),  # wrong version
        ]
        assert _build_slam_node_check(mock_client) is False


class TestRunBuildSlamNode:
    def test_pushes_and_builds(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)

        # Create minimal contrib structure
        contrib = tmp_path / "contrib" / "rtabmap_slam_node"
        contrib.mkdir(parents=True)
        (contrib / "CMakeLists.txt").write_text("cmake_minimum_required()", encoding="utf-8")
        src = contrib / "src"
        src.mkdir()
        (src / "main.cpp").write_text("int main(){}", encoding="utf-8")

        mock_client.run.return_value = _ssh_ok()
        mock_client.push.return_value = _ssh_ok()
        mock_client.run_streaming.return_value = _ssh_ok()

        _run_build_slam_node(mock_client, bctx)

        # Should have pushed files
        assert mock_client.push.call_count >= 2  # CMakeLists.txt + main.cpp
        mock_client.run_streaming.assert_called_once()

    def test_exits_when_contrib_missing(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        # No contrib directory

        with pytest.raises(ClickExit):
            _run_build_slam_node(mock_client, bctx)


class TestArchiveBinariesCheck:
    def test_returns_true_when_archive_exists(self, mock_client: MagicMock, tmp_path: Path) -> None:
        import datetime

        today = datetime.date.today().isoformat()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / f"mower-binaries-{today}.tar.gz").write_bytes(b"fake")

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            assert _archive_binaries_check(mock_client) is True

    def test_returns_false_when_no_archive(self, mock_client: MagicMock, tmp_path: Path) -> None:
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            assert _archive_binaries_check(mock_client) is False


class TestRunArchiveBinaries:
    def test_creates_and_pulls_archive(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        backup_dir = tmp_path / "backups"

        mock_client.run.side_effect = [
            _ssh_ok(),  # tar
            _ssh_ok(),  # rm cleanup
        ]
        mock_client.pull.return_value = None

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            _run_archive_binaries(mock_client, bctx)

        mock_client.run.assert_called()
        mock_client.pull.assert_called_once()
        assert backup_dir.is_dir()

    def test_non_fatal_on_tar_failure(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        backup_dir = tmp_path / "backups"

        mock_client.run.return_value = _ssh_fail()

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            # Should not raise
            _run_archive_binaries(mock_client, bctx)

        mock_client.pull.assert_not_called()

    def test_non_fatal_on_pull_failure(self, mock_client: MagicMock, tmp_path: Path) -> None:
        bctx = _bctx(tmp_path)
        backup_dir = tmp_path / "backups"

        mock_client.run.return_value = _ssh_ok()
        mock_client.pull.side_effect = SshError("pull failed")

        with patch("mower_rover.cli.bringup._BACKUP_DIR", backup_dir):
            # Should not raise
            _run_archive_binaries(mock_client, bctx)


# ---------------------------------------------------------------------------
# 4.8 — Step ordering
# ---------------------------------------------------------------------------


class TestStepOrdering:
    def test_step_names_match_bringup_steps(self) -> None:
        from mower_rover.cli.bringup import BRINGUP_STEPS

        # BRINGUP_STEPS names are a subset of STEP_NAMES in the same order
        step_names = tuple(s.name for s in BRINGUP_STEPS)
        for name in step_names:
            assert name in STEP_NAMES, f"{name} not in STEP_NAMES"
        # Relative order preserved
        indices = [STEP_NAMES.index(n) for n in step_names]
        assert indices == sorted(indices), "BRINGUP_STEPS order doesn't match STEP_NAMES order"

    def test_first_five_steps_in_order(self) -> None:
        from mower_rover.cli.bringup import BRINGUP_STEPS

        names = [s.name for s in BRINGUP_STEPS]
        assert names[:5] == [
            "clear-host-key",
            "check-ssh",
            "enable-linger",
            "harden-os",
            "reboot-and-wait",
        ]

    def test_check_ssh_is_gate(self) -> None:
        from mower_rover.cli.bringup import BRINGUP_STEPS

        step_map = {s.name: s for s in BRINGUP_STEPS}
        assert step_map["check-ssh"].gate is True
        assert step_map["clear-host-key"].gate is False
        assert step_map["enable-linger"].gate is False
        assert step_map["harden-os"].gate is False
        assert step_map["reboot-and-wait"].gate is False

    def test_step_names_tuple(self) -> None:
        assert STEP_NAMES == (
            "clear-host-key",
            "check-ssh",
            "enable-linger",
            "harden-os",
            "reboot-and-wait",
            "restore-binaries",
            "build-rtabmap",
            "build-depthai",
            "build-slam-node",
            "archive-binaries",
            "pixhawk-udev",
            "install-uv",
            "install-cli",
            "verify",
            "vslam-config",
            "service",
            "vslam-services",
            "final-verify",
        )

    def test_all_18_steps_present(self) -> None:
        from mower_rover.cli.bringup import BRINGUP_STEPS

        assert len(BRINGUP_STEPS) == 18
        names = tuple(s.name for s in BRINGUP_STEPS)
        assert names == STEP_NAMES

    def test_final_verify_is_last(self) -> None:
        from mower_rover.cli.bringup import BRINGUP_STEPS

        assert BRINGUP_STEPS[-1].name == "final-verify"


# ---------------------------------------------------------------------------
# 5.3 — final-verify step
# ---------------------------------------------------------------------------


class TestFinalVerifyCheck:
    def test_always_returns_false(self, mock_client: MagicMock) -> None:
        assert _final_verify_check(mock_client) is False


class TestRunFinalVerify:
    def test_full_flow_all_pass(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Reboot → SSH poll → probe poll → all critical pass."""
        bctx = _bctx(tmp_path)
        import json

        probe_result = json.dumps([
            {"name": "python", "status": "pass", "severity": "critical", "detail": "ok"},
            {"name": "oakd", "status": "pass", "severity": "critical", "detail": "ok"},
        ])

        call_count = 0

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SshError("Connection closed")  # reboot
            if call_count == 2:
                return _ssh_ok(stdout="ok\n")  # SSH poll
            # probe --json
            return _ssh_ok(stdout=probe_result)

        mock_client.run.side_effect = side_effect

        with patch("mower_rover.cli.bringup.time.sleep"):
            _run_final_verify(mock_client, bctx)

        assert call_count == 3

    def test_timeout_ssh(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Exits if Jetson never comes back after reboot."""
        bctx = _bctx(tmp_path)

        call_count = 0

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SshError("Connection closed")
            raise SshError("Connection refused")

        mock_client.run.side_effect = side_effect

        with (
            patch("mower_rover.cli.bringup.time.sleep"),
            patch("mower_rover.cli.bringup.time.monotonic", side_effect=[0, 10, 20, 200]),
            pytest.raises(ClickExit),
        ):
            _run_final_verify(mock_client, bctx)

    def test_timeout_probe(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Exits if probe never returns valid JSON within deadline."""
        bctx = _bctx(tmp_path)

        call_count = 0
        # We need monotonic to expire the SSH loop quickly, then expire the probe loop
        monotonic_values = iter([
            0, 10,   # SSH loop: start, first poll
            0, 10, 200,  # probe loop: start, first poll attempt, expired
        ])

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SshError("Connection closed")  # reboot
            if call_count == 2:
                return _ssh_ok(stdout="ok\n")  # SSH poll → connected
            # probe attempts all fail
            raise SshError("timeout")

        mock_client.run.side_effect = side_effect

        with (
            patch("mower_rover.cli.bringup.time.sleep"),
            patch("mower_rover.cli.bringup.time.monotonic", side_effect=monotonic_values),
            pytest.raises(ClickExit),
        ):
            _run_final_verify(mock_client, bctx)

    def test_critical_failures_exit(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Exits with code 1 if critical checks still fail after probe deadline."""
        bctx = _bctx(tmp_path)
        import json

        probe_result = json.dumps([
            {"name": "python", "status": "pass", "severity": "critical", "detail": "ok"},
            {"name": "oakd", "status": "fail", "severity": "critical", "detail": "not found"},
        ])

        call_count = 0
        # SSH loop quick, probe loop expires with critical failure still present
        monotonic_values = iter([
            0, 10,          # SSH loop
            0, 10, 200,    # probe loop: start, attempt, expired
        ])

        def side_effect(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SshError("Connection closed")  # reboot
            if call_count == 2:
                return _ssh_ok(stdout="ok\n")  # SSH poll
            # probe returns with critical failure
            return _ssh_ok(stdout=probe_result)

        mock_client.run.side_effect = side_effect

        with (
            patch("mower_rover.cli.bringup.time.sleep"),
            patch("mower_rover.cli.bringup.time.monotonic", side_effect=monotonic_values),
            pytest.raises(ClickExit),
        ):
            _run_final_verify(mock_client, bctx)


# ---------------------------------------------------------------------------
# 5.6 — Integration tests (full 18-step pipeline)
# ---------------------------------------------------------------------------


class TestBringupIntegrationAllSkip:
    """All 18 check() functions return True → every step skips."""

    def test_all_steps_skip(self, runner: CliRunner, tmp_path: Path) -> None:
        import contextlib

        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )

        fake_client = MagicMock(spec=JetsonClient)
        fake_client.endpoint = JetsonEndpoint(
            host="10.0.0.42", user="mower", port=22, key_path=None,
        )
        fake_client.run.return_value = _ssh_ok(stdout="ok\n")

        patches = {
            "mower_rover.transport.ssh.shutil.which": "C:/fake/ssh.exe",
            "mower_rover.cli.bringup._clear_host_key_needed": True,
            "mower_rover.cli.bringup._check_ssh_ok": True,
            "mower_rover.cli.bringup._linger_enabled": True,
            "mower_rover.cli.bringup._harden_done": True,
            "mower_rover.cli.bringup._reboot_check": True,
            "mower_rover.cli.bringup._restore_binaries_check": True,
            "mower_rover.cli.bringup._build_rtabmap_check": True,
            "mower_rover.cli.bringup._build_depthai_check": True,
            "mower_rover.cli.bringup._build_slam_node_check": True,
            "mower_rover.cli.bringup._archive_binaries_check": True,
            "mower_rover.cli.bringup._pixhawk_udev_done": True,
            "mower_rover.cli.bringup._uv_installed": True,
            "mower_rover.cli.bringup._cli_installed": True,
            "mower_rover.cli.bringup._verify_check": True,
            "mower_rover.cli.bringup._vslam_config_exists": True,
            "mower_rover.cli.bringup._service_active": True,
            "mower_rover.cli.bringup._vslam_services_active": True,
            "mower_rover.cli.bringup._final_verify_check": True,
        }

        with contextlib.ExitStack() as stack:
            mock_ep = stack.enter_context(
                patch("mower_rover.cli.jetson_remote.resolve_endpoint")
            )
            mock_cf = stack.enter_context(
                patch("mower_rover.cli.jetson_remote.client_for")
            )
            for target, rv in patches.items():
                stack.enter_context(patch(target, return_value=rv))

            mock_ep.return_value = fake_client.endpoint
            mock_cf.return_value = fake_client

            result = runner.invoke(
                laptop_app,
                ["jetson", "bringup", "--config", str(cfg), "--yes"],
            )
        assert result.exit_code == 0, result.output
        assert "Bringup complete" in result.output
        assert result.output.count("Already satisfied") == 18


class TestBringupIntegrationFromStep:
    """--from-step skips steps before the target."""

    def test_from_step_skips_earlier(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )

        fake_client = MagicMock(spec=JetsonClient)
        fake_client.endpoint = JetsonEndpoint(
            host="10.0.0.42", user="mower", port=22, key_path=None,
        )

        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe"),
            patch("mower_rover.cli.jetson_remote.resolve_endpoint") as mock_ep,
            patch("mower_rover.cli.jetson_remote.client_for") as mock_cf,
            patch("mower_rover.cli.bringup._verify_check", return_value=True),
            patch("mower_rover.cli.bringup._vslam_config_exists", return_value=True),
            patch("mower_rover.cli.bringup._service_active", return_value=True),
            patch("mower_rover.cli.bringup._vslam_services_active", return_value=True),
            patch("mower_rover.cli.bringup._final_verify_check", return_value=True),
        ):
            mock_ep.return_value = fake_client.endpoint
            mock_cf.return_value = fake_client

            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "bringup",
                    "--from-step", "verify",
                    "--config", str(cfg),
                    "--yes",
                ],
            )
        assert result.exit_code == 0, result.output
        # Steps before "verify" should show "Skipping — before --from-step target"
        assert "before --from-step" in result.output
        assert "Bringup complete" in result.output


class TestBringupIntegrationContinueOnError:
    """--continue-on-error skips non-gate failures."""

    def test_continues_past_non_gate_failure(self, runner: CliRunner, tmp_path: Path) -> None:
        import contextlib

        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )

        fake_client = MagicMock(spec=JetsonClient)
        fake_client.endpoint = JetsonEndpoint(
            host="10.0.0.42", user="mower", port=22, key_path=None,
        )

        # All check functions return True except enable-linger
        check_patches = {
            "mower_rover.cli.bringup._clear_host_key_needed": True,
            "mower_rover.cli.bringup._check_ssh_ok": True,
            "mower_rover.cli.bringup._linger_enabled": False,  # NOT satisfied
            "mower_rover.cli.bringup._harden_done": True,
            "mower_rover.cli.bringup._reboot_check": True,
            "mower_rover.cli.bringup._restore_binaries_check": True,
            "mower_rover.cli.bringup._build_rtabmap_check": True,
            "mower_rover.cli.bringup._build_depthai_check": True,
            "mower_rover.cli.bringup._build_slam_node_check": True,
            "mower_rover.cli.bringup._archive_binaries_check": True,
            "mower_rover.cli.bringup._pixhawk_udev_done": True,
            "mower_rover.cli.bringup._uv_installed": True,
            "mower_rover.cli.bringup._cli_installed": True,
            "mower_rover.cli.bringup._verify_check": True,
            "mower_rover.cli.bringup._vslam_config_exists": True,
            "mower_rover.cli.bringup._service_active": True,
            "mower_rover.cli.bringup._vslam_services_active": True,
            "mower_rover.cli.bringup._final_verify_check": True,
        }

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe")
            )
            mock_ep = stack.enter_context(
                patch("mower_rover.cli.jetson_remote.resolve_endpoint")
            )
            mock_cf = stack.enter_context(
                patch("mower_rover.cli.jetson_remote.client_for")
            )
            # enable-linger execute → fail
            stack.enter_context(
                patch(
                    "mower_rover.cli.bringup._run_enable_linger",
                    side_effect=SshError("test failure"),
                )
            )
            for target, rv in check_patches.items():
                stack.enter_context(patch(target, return_value=rv))

            mock_ep.return_value = fake_client.endpoint
            mock_cf.return_value = fake_client

            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "bringup",
                    "--continue-on-error",
                    "--config", str(cfg),
                    "--yes",
                ],
            )
        # Should exit 1 (failures table) but not abort early
        assert result.exit_code == 1, result.output
        assert "Failed Steps" in result.output
        assert "enable-linger" in result.output


# ---------------------------------------------------------------------------
# 5.6b — Backup command tests
# ---------------------------------------------------------------------------


class TestBackupCommand:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(laptop_app, ["jetson", "backup", "--help"])
        assert result.exit_code == 0, result.output
        assert "backup" in result.stdout.lower()
        assert "--output-dir" in result.stdout
        assert "--include-binaries" in result.stdout

    def test_pulls_config_files(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )
        output = tmp_path / "backups"

        fake_client = MagicMock(spec=JetsonClient)
        fake_client.endpoint = JetsonEndpoint(
            host="10.0.0.42", user="mower", port=22, key_path=None,
        )
        fake_client.pull.return_value = _ssh_ok()

        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe"),
            patch("mower_rover.cli.jetson_remote.resolve_endpoint") as mock_ep,
            patch("mower_rover.cli.jetson_remote.client_for") as mock_cf,
        ):
            mock_ep.return_value = fake_client.endpoint
            mock_cf.return_value = fake_client

            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "backup",
                    "--config", str(cfg),
                    "--output-dir", str(output),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "5 pulled" in result.output
        assert fake_client.pull.call_count == 5

    def test_handles_pull_errors(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n",
            encoding="utf-8",
        )
        output = tmp_path / "backups"

        fake_client = MagicMock(spec=JetsonClient)
        fake_client.endpoint = JetsonEndpoint(
            host="10.0.0.42", user="mower", port=22, key_path=None,
        )
        # First pull succeeds, rest fail
        fake_client.pull.side_effect = [
            _ssh_ok(),
            SshError("not found"),
            SshError("not found"),
            SshError("not found"),
            SshError("not found"),
        ]

        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe"),
            patch("mower_rover.cli.jetson_remote.resolve_endpoint") as mock_ep,
            patch("mower_rover.cli.jetson_remote.client_for") as mock_cf,
        ):
            mock_ep.return_value = fake_client.endpoint
            mock_cf.return_value = fake_client

            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "backup",
                    "--config", str(cfg),
                    "--output-dir", str(output),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "1 pulled" in result.output
        assert "4 skipped" in result.output
