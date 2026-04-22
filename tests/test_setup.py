"""Tests for the ``mower jetson setup`` and ``mower jetson health`` commands.

All tests run on Windows without a real Jetson — subprocess calls are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mower_rover.cli.laptop import app as laptop_app
from mower_rover.cli.setup import (
    SETUP_STEPS,
    SetupContext,
    SetupStep,
    _config_exists,
    _endpoint_configured,
    _key_auth_works,
    _key_exists,
    _ping_ok,
    _remote_probe_ok,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def sctx(tmp_path: Path) -> SetupContext:
    """A SetupContext pre-loaded with sensible test values."""
    return SetupContext(
        host="10.0.0.42",
        user="mower",
        key_path=tmp_path / ".ssh" / "mower_id_ed25519",
        config_path=tmp_path / "laptop.yaml",
        force=False,
    )


# ---------------------------------------------------------------------------
# Step check functions
# ---------------------------------------------------------------------------


class TestKeyExists:
    def test_returns_false_when_missing(self, sctx: SetupContext) -> None:
        assert _key_exists(sctx) is False

    def test_returns_true_when_present(self, sctx: SetupContext) -> None:
        sctx.key_path.parent.mkdir(parents=True, exist_ok=True)
        sctx.key_path.write_text("fake key")
        assert _key_exists(sctx) is True


class TestEndpointConfigured:
    def test_returns_true_when_flags_set(self, sctx: SetupContext) -> None:
        assert _endpoint_configured(sctx) is True

    def test_returns_true_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MOWER_JETSON_HOST", "envhost")
        monkeypatch.setenv("MOWER_JETSON_USER", "envuser")
        ctx = SetupContext(config_path=tmp_path / "nope.yaml")
        assert _endpoint_configured(ctx) is True
        assert ctx.host == "envhost"
        assert ctx.user == "envuser"

    def test_returns_true_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MOWER_JETSON_HOST", raising=False)
        monkeypatch.delenv("MOWER_JETSON_USER", raising=False)
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text("jetson:\n  host: cfghost\n  user: cfguser\n", encoding="utf-8")
        ctx = SetupContext(config_path=cfg)
        assert _endpoint_configured(ctx) is True
        assert ctx.host == "cfghost"

    def test_returns_false_when_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MOWER_JETSON_HOST", raising=False)
        monkeypatch.delenv("MOWER_JETSON_USER", raising=False)
        ctx = SetupContext(config_path=tmp_path / "nope.yaml")
        assert _endpoint_configured(ctx) is False


class TestPingOk:
    def test_returns_true_on_success(self, sctx: SetupContext) -> None:
        fake = MagicMock(returncode=0)
        with patch("mower_rover.cli.setup.subprocess.run", return_value=fake):
            assert _ping_ok(sctx) is True

    def test_returns_false_on_failure(self, sctx: SetupContext) -> None:
        fake = MagicMock(returncode=1)
        with patch("mower_rover.cli.setup.subprocess.run", return_value=fake):
            assert _ping_ok(sctx) is False

    def test_returns_false_on_timeout(self, sctx: SetupContext) -> None:
        import subprocess

        with patch(
            "mower_rover.cli.setup.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ping", 10),
        ):
            assert _ping_ok(sctx) is False


class TestKeyAuthWorks:
    def test_returns_true_on_success(self, sctx: SetupContext) -> None:
        fake = MagicMock(returncode=0)
        with (
            patch("mower_rover.cli.setup._find_ssh", return_value="ssh"),
            patch("mower_rover.cli.setup.subprocess.run", return_value=fake),
        ):
            assert _key_auth_works(sctx) is True

    def test_returns_false_when_ssh_missing(self, sctx: SetupContext) -> None:
        with patch("mower_rover.cli.setup._find_ssh", return_value=None):
            assert _key_auth_works(sctx) is False

    def test_returns_false_on_nonzero(self, sctx: SetupContext) -> None:
        fake = MagicMock(returncode=255)
        with (
            patch("mower_rover.cli.setup._find_ssh", return_value="ssh"),
            patch("mower_rover.cli.setup.subprocess.run", return_value=fake),
        ):
            assert _key_auth_works(sctx) is False


class TestConfigExists:
    def test_returns_false_when_no_file(self, sctx: SetupContext) -> None:
        assert _config_exists(sctx) is False

    def test_returns_true_when_matching(self, sctx: SetupContext) -> None:
        cfg_path = sctx.config_path
        assert cfg_path is not None
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            f"jetson:\n  host: {sctx.host}\n  user: {sctx.user}\n"
            f"  key_path: '{sctx.key_path}'\n",
            encoding="utf-8",
        )
        assert _config_exists(sctx) is True

    def test_returns_false_when_host_differs(self, sctx: SetupContext) -> None:
        cfg_path = sctx.config_path
        assert cfg_path is not None
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            "jetson:\n  host: other\n  user: mower\n", encoding="utf-8"
        )
        assert _config_exists(sctx) is False


class TestRemoteProbeOk:
    def test_returns_true_on_all_pass(self, sctx: SetupContext) -> None:
        payload = json.dumps([
            {"name": "a", "status": "pass", "severity": "critical", "detail": "ok"},
        ])
        fake_result = MagicMock(ok=True, returncode=0, stdout=payload, stderr="")
        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch("mower_rover.transport.ssh.subprocess.run", return_value=fake_result),
        ):
            assert _remote_probe_ok(sctx) is True

    def test_returns_false_on_critical_fail(self, sctx: SetupContext) -> None:
        payload = json.dumps([
            {"name": "a", "status": "fail", "severity": "critical", "detail": "bad"},
        ])
        fake_result = MagicMock(ok=True, returncode=2, stdout=payload, stderr="")
        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch("mower_rover.transport.ssh.subprocess.run", return_value=fake_result),
        ):
            assert _remote_probe_ok(sctx) is False

    def test_returns_false_on_ssh_error(self, sctx: SetupContext) -> None:
        from mower_rover.transport.ssh import SshError

        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch(
                "mower_rover.transport.ssh.subprocess.run",
                side_effect=FileNotFoundError("no ssh"),
            ),
        ):
            assert _remote_probe_ok(sctx) is False


# ---------------------------------------------------------------------------
# SETUP_STEPS structure
# ---------------------------------------------------------------------------


class TestSetupSteps:
    def test_six_steps(self) -> None:
        assert len(SETUP_STEPS) == 6

    def test_step_names(self) -> None:
        names = [s.name for s in SETUP_STEPS]
        assert names == ["ssh_key", "endpoint", "connectivity", "key_deployed", "config", "verify"]

    def test_all_steps_have_callables(self) -> None:
        for step in SETUP_STEPS:
            assert callable(step.check)
            assert callable(step.execute)


# ---------------------------------------------------------------------------
# CLI integration — setup command
# ---------------------------------------------------------------------------


class TestSetupCommandCli:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(laptop_app, ["jetson", "setup", "--help"])
        assert result.exit_code == 0, result.stdout
        assert "setup" in result.stdout.lower()

    def test_skips_when_all_checks_pass(self, runner: CliRunner, tmp_path: Path) -> None:
        """When every check returns True, no execute functions run."""
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text(
            "jetson:\n  host: 10.0.0.42\n  user: mower\n"
            f"  key_path: '{tmp_path / 'key'}'\n",
            encoding="utf-8",
        )
        key = tmp_path / "key"
        key.write_text("fake")

        with (
            patch("mower_rover.cli.setup._ping_ok", return_value=True),
            patch("mower_rover.cli.setup._key_auth_works", return_value=True),
            patch("mower_rover.cli.setup._remote_probe_ok", return_value=True),
        ):
            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "setup",
                    "--host", "10.0.0.42",
                    "--user", "mower",
                    "--key", str(key),
                    "--config", str(cfg),
                ],
            )
        assert result.exit_code == 0, result.stdout
        assert "Setup complete" in result.stdout

    def test_force_reruns_steps(self, runner: CliRunner, tmp_path: Path) -> None:
        """--force causes execute functions to run even when check passes."""
        key = tmp_path / "key"
        key.write_text("fake")
        pub = tmp_path / "key.pub"
        pub.write_text("fake pub")

        probe_payload = json.dumps([
            {"name": "a", "status": "pass", "severity": "info", "detail": "ok"},
        ])
        fake_ssh = MagicMock(returncode=0, stdout=probe_payload, stderr="")

        with (
            patch("mower_rover.cli.setup._ping_ok", return_value=True),
            patch("mower_rover.cli.setup._key_auth_works", return_value=True),
            patch("mower_rover.cli.setup.subprocess.run", return_value=MagicMock(returncode=0)),
            patch("mower_rover.cli.setup._find_ssh", return_value="ssh"),
            patch("mower_rover.cli.setup._find_binary", return_value=None),
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch("mower_rover.transport.ssh.subprocess.run", return_value=fake_ssh),
        ):
            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "setup",
                    "--host", "10.0.0.42",
                    "--user", "mower",
                    "--key", str(key),
                    "--config", str(tmp_path / "laptop.yaml"),
                    "--force",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Done" in result.output

    def test_connectivity_failure_exits(self, runner: CliRunner, tmp_path: Path) -> None:
        key = tmp_path / "key"
        key.write_text("fake")

        with patch("mower_rover.cli.setup._ping_ok", return_value=False):
            result = runner.invoke(
                laptop_app,
                [
                    "jetson", "setup",
                    "--host", "10.0.0.42",
                    "--user", "mower",
                    "--key", str(key),
                    "--config", str(tmp_path / "laptop.yaml"),
                ],
            )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI integration — health command
# ---------------------------------------------------------------------------


class TestHealthCommandCli:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(laptop_app, ["jetson", "health", "--help"])
        assert result.exit_code == 0, result.stdout
        assert "health" in result.stdout.lower()

    def test_dry_run(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
        with patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"):
            result = runner.invoke(
                laptop_app,
                ["--dry-run", "jetson", "health", "--config", str(cfg)],
            )
        assert result.exit_code == 0, result.stdout
        assert "DRY RUN" in result.stdout

    def test_renders_table(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
        payload = json.dumps([
            {"name": "python_ver", "status": "pass", "severity": "critical", "detail": "3.11"},
            {"name": "disk", "status": "fail", "severity": "warning", "detail": "low"},
        ])
        fake = MagicMock(returncode=1, stdout=payload, stderr="")
        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
        ):
            result = runner.invoke(
                laptop_app,
                ["jetson", "health", "--config", str(cfg)],
            )
        # exit code mirrors remote (1 for warning)
        assert result.exit_code == 1
        assert "python_ver" in result.stdout
        assert "disk" in result.stdout

    def test_json_passthrough(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
        payload = json.dumps([
            {"name": "a", "status": "pass", "severity": "info", "detail": "ok"},
        ])
        fake = MagicMock(returncode=0, stdout=payload, stderr="")
        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
        ):
            result = runner.invoke(
                laptop_app,
                ["jetson", "health", "--json", "--config", str(cfg)],
            )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed[0]["name"] == "a"

    def test_ssh_error(self, runner: CliRunner, tmp_path: Path) -> None:
        cfg = tmp_path / "laptop.yaml"
        cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
        with (
            patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
            patch(
                "mower_rover.transport.ssh.subprocess.run",
                side_effect=FileNotFoundError("gone"),
            ),
        ):
            result = runner.invoke(
                laptop_app,
                ["jetson", "health", "--config", str(cfg)],
            )
        assert result.exit_code != 0
        assert "ERROR" in result.output
