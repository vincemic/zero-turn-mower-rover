"""SITL-marked end-to-end tests for `mower params` snapshot/diff/apply."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mower_rover.cli.laptop import app
from mower_rover.params.io import load_json_snapshot


@pytest.mark.sitl
def test_params_snapshot_against_sitl(sitl_endpoint: str, tmp_path: Path) -> None:
    snap = tmp_path / "snap.json"
    result = CliRunner().invoke(
        app, ["params", "snapshot", str(snap), "--port", sitl_endpoint, "--timeout", "90"]
    )
    assert result.exit_code == 0, result.stdout
    params = load_json_snapshot(snap)
    # Rover SITL ships hundreds of params; require a sane lower bound.
    assert len(params) > 100
    assert "FRAME_CLASS" in params


@pytest.mark.sitl
def test_params_apply_baseline_round_trip(sitl_endpoint: str, tmp_path: Path) -> None:
    runner = CliRunner()
    # Apply with auto-confirm; verify the post-apply snapshot reflects baseline.
    result = runner.invoke(
        app,
        ["params", "apply", "baseline", "--port", sitl_endpoint, "--yes"],
    )
    assert result.exit_code == 0, result.stdout

    after = tmp_path / "after.json"
    result = runner.invoke(
        app,
        ["params", "snapshot", str(after), "--port", sitl_endpoint, "--timeout", "90"],
    )
    assert result.exit_code == 0, result.stdout

    loaded = load_json_snapshot(after)
    assert loaded["SERVO1_FUNCTION"] == 73
    assert loaded["SERVO3_FUNCTION"] == 74
    assert loaded["EK3_SRC1_YAW"] == 2
