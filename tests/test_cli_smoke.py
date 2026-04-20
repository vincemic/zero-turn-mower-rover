from __future__ import annotations

from typer.testing import CliRunner

from mower_rover import __version__
from mower_rover.cli.jetson import app as jetson_app
from mower_rover.cli.laptop import app as laptop_app


def test_laptop_help() -> None:
    result = CliRunner().invoke(laptop_app, ["--help"])
    assert result.exit_code == 0
    assert "detect" in result.stdout


def test_laptop_version() -> None:
    result = CliRunner().invoke(laptop_app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_jetson_help() -> None:
    result = CliRunner().invoke(jetson_app, ["--help"])
    assert result.exit_code == 0
