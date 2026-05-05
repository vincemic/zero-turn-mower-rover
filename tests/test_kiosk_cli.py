"""Smoke tests for the kiosk CLI sub-app."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mower_rover.cli.jetson import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_kiosk_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "--help"])
    assert result.exit_code == 0, result.output
    assert "kiosk" in result.output.lower()
    assert "operational display" in result.output.lower()


def test_kiosk_run_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "run", "--help"])
    assert result.exit_code == 0, result.output
    assert "--endpoint" in result.output
    assert "--config" in result.output


def test_kiosk_status_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "status", "--help"])
    assert result.exit_code == 0, result.output
    assert "--config" in result.output


def test_kiosk_enable_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "enable", "--help"])
    assert result.exit_code == 0, result.output
    assert "enable" in result.output.lower() or "start" in result.output.lower()


def test_kiosk_disable_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "disable", "--help"])
    assert result.exit_code == 0, result.output
    assert "disable" in result.output.lower() or "stop" in result.output.lower()


def test_kiosk_install_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "install", "--help"])
    assert result.exit_code == 0, result.output
    assert "--yes" in result.output
    assert "--target-user" in result.output
    assert "--target-home" in result.output


def test_kiosk_uninstall_help(runner: CliRunner) -> None:
    result = runner.invoke(app, ["kiosk", "uninstall", "--help"])
    assert result.exit_code == 0, result.output
    assert "--yes" in result.output


def test_kiosk_status_runs(runner: CliRunner) -> None:
    """status command runs without crashing (systemctl may not exist on Windows)."""
    result = runner.invoke(app, ["kiosk", "status"])
    # On Windows, systemctl won't exist, but the command should still render
    # a table with "unknown" states rather than crashing.
    assert result.exit_code == 0, result.output
    assert "Kiosk Service Status" in result.output
