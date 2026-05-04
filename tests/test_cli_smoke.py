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


# ---------------------------------------------------------------------------
# `mower params apply --profile` validation (plan 016 Phase 2)
# ---------------------------------------------------------------------------


def test_params_apply_requires_one_of_path_or_profile() -> None:
    """Supplying neither must fail before any MAVLink connect."""
    result = CliRunner().invoke(laptop_app, ["params", "apply", "--yes"])
    assert result.exit_code != 0
    assert "exactly one of" in result.output.lower()


def test_params_apply_rejects_both_path_and_profile(tmp_path: object) -> None:
    """Supplying both must fail before any MAVLink connect."""
    result = CliRunner().invoke(
        laptop_app,
        ["params", "apply", "baseline", "--profile", "safety-defaults", "--yes"],
    )
    assert result.exit_code != 0
    assert "exactly one of" in result.output.lower()


def test_params_apply_rejects_unknown_profile() -> None:
    result = CliRunner().invoke(
        laptop_app, ["params", "apply", "--profile", "nonexistent", "--yes"]
    )
    assert result.exit_code != 0
    assert "unknown profile" in result.output.lower()


def test_params_diff_resolves_safety_defaults_magic_string() -> None:
    """`mower params diff baseline safety-defaults` runs without files on disk."""
    result = CliRunner().invoke(
        laptop_app, ["params", "diff", "baseline", "safety-defaults", "--json"]
    )
    assert result.exit_code == 0, result.output
    # JSON output contains the changed-key set; just verify it parsed and ran.
    assert "FENCE_ENABLE" in result.output or "changed" in result.output
