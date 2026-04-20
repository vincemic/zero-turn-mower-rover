"""SITL-marked end-to-end test for `mower detect`."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from mower_rover.cli.laptop import app


@pytest.mark.sitl
def test_detect_against_sitl(sitl_endpoint: str) -> None:
    result = CliRunner().invoke(
        app,
        ["detect", "--port", sitl_endpoint, "--sample-seconds", "5", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    # Output may include log lines on stderr; the command writes JSON to stdout.
    # Find the JSON payload in stdout.
    stdout = result.stdout.strip()
    # Locate the first `{` to skip any leading log noise.
    start = stdout.find("{")
    assert start != -1, f"no JSON in output: {stdout!r}"
    report = json.loads(stdout[start:])
    assert report["vehicle_is_rover"] is True
    assert report["gnss"], "expected at least one GNSS instance from SITL"
