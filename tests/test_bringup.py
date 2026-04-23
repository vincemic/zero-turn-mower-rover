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
    _check_ssh_ok,
    _cli_installed,
    _harden_done,
    _run_harden,
    _run_install_cli,
    _service_active,
    _uv_installed,
    _verify_check,
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
        mock_client.run.return_value = _ssh_ok()
        assert _check_ssh_ok(mock_client) is True

    def test_returns_false_on_failure(self, mock_client: MagicMock) -> None:
        mock_client.run.return_value = _ssh_fail()
        assert _check_ssh_ok(mock_client) is False

    def test_returns_false_on_ssh_error(self, mock_client: MagicMock) -> None:
        mock_client.run.side_effect = SshError("connection refused")
        assert _check_ssh_ok(mock_client) is False


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

        # Run with sudo bash
        run_call = mock_client.run.call_args_list[0]
        run_argv = run_call[0][0]
        assert "sudo" in run_argv
        assert "bash" in run_argv

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
