from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mower_rover.cli.jetson import app as jetson_app
from mower_rover.cli.laptop import app as laptop_app
from mower_rover.health.power import PowerState
from mower_rover.health.thermal import ThermalSnapshot, ThermalZone
from mower_rover.probe.registry import CheckResult, Severity, Status


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# --- mower-jetson -----------------------------------------------------------


def test_jetson_info_text(runner: CliRunner) -> None:
    result = runner.invoke(jetson_app, ["info"])
    assert result.exit_code == 0, result.output
    assert "host" in result.stdout
    assert "python" in result.stdout
    assert "is_jetson" in result.stdout


def test_jetson_info_json(runner: CliRunner) -> None:
    result = runner.invoke(jetson_app, ["info", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["package_version"]
    assert "hostname" in payload
    assert "is_jetson" in payload


def test_jetson_config_show_defaults_on_missing(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "jetson.yaml"
    result = runner.invoke(jetson_app, ["config", "show", "--config", str(target), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["exists"] is False
    assert payload["config"]["oakd_required"] is False


def test_jetson_config_show_reports_invalid(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "jetson.yaml"
    target.write_text("oakd_required: not-a-bool\n", encoding="utf-8")
    result = runner.invoke(jetson_app, ["config", "show", "--config", str(target)])
    assert result.exit_code == 2
    assert "ERROR" in result.output


# --- mower jetson group -----------------------------------------------------


def test_laptop_jetson_group_in_help(runner: CliRunner) -> None:
    result = runner.invoke(laptop_app, ["jetson", "--help"])
    assert result.exit_code == 0, result.output
    for sub in ("run", "pull", "info"):
        assert sub in result.stdout


def test_laptop_jetson_run_dry_run(runner: CliRunner, tmp_path: Path) -> None:
    cfg = tmp_path / "laptop.yaml"
    cfg.write_text(
        "jetson:\n  host: 10.0.0.42\n  user: mower\n  port: 22\n", encoding="utf-8"
    )
    with patch("mower_rover.transport.ssh.shutil.which", return_value="C:/fake/ssh.exe"):
        result = runner.invoke(
            laptop_app,
            [
                "--dry-run",
                "jetson",
                "run",
                "--config",
                str(cfg),
                "--",
                "uname",
                "-a",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert "mower@10.0.0.42" in result.output


def test_laptop_jetson_run_requires_endpoint(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOWER_JETSON_HOST", raising=False)
    monkeypatch.delenv("MOWER_JETSON_USER", raising=False)
    cfg = tmp_path / "laptop.yaml"  # missing on purpose
    result = runner.invoke(
        laptop_app, ["jetson", "run", "--config", str(cfg), "--", "true"]
    )
    assert result.exit_code == 2
    assert "endpoint not configured" in result.output


def test_laptop_jetson_run_streams_output(runner: CliRunner, tmp_path: Path) -> None:
    cfg = tmp_path / "laptop.yaml"
    cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
    fake = MagicMock(returncode=0, stdout="hello\n", stderr="")
    with (
        patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
    ):
        result = runner.invoke(
            laptop_app, ["jetson", "run", "--config", str(cfg), "--", "echo", "hi"]
        )
    assert result.exit_code == 0, result.output
    assert "hello" in result.output


def test_laptop_jetson_info_parses_remote_json(runner: CliRunner, tmp_path: Path) -> None:
    cfg = tmp_path / "laptop.yaml"
    cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
    remote_payload = json.dumps({
        "package_version": "0.1.0",
        "hostname": "rover",
        "fqdn": "rover.lan",
        "system": "Linux",
        "release": "5.15",
        "machine": "aarch64",
        "python_version": "3.11.5",
        "jetpack_release": "R36 (release), REVISION: 2.0",
        "is_jetson": True,
        "warnings": [],
    })
    fake = MagicMock(returncode=0, stdout=remote_payload, stderr="")
    with (
        patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"),
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
    ):
        result = runner.invoke(laptop_app, ["jetson", "info", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "rover" in result.output
    assert "aarch64" in result.output
    assert "R36" in result.output


def test_laptop_jetson_pull_dry_run(runner: CliRunner, tmp_path: Path) -> None:
    cfg = tmp_path / "laptop.yaml"
    cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
    with patch("mower_rover.transport.ssh.shutil.which", return_value="scp"):
        result = runner.invoke(
            laptop_app,
            [
                "--dry-run",
                "jetson",
                "pull",
                "--config",
                str(cfg),
                "/var/log/foo.bin",
                str(tmp_path / "foo.bin"),
            ],
        )
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert "u@h:/var/log/foo.bin" in result.output


def test_laptop_jetson_pull_overwrite_aborts_without_yes(
    runner: CliRunner, tmp_path: Path
) -> None:
    cfg = tmp_path / "laptop.yaml"
    cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
    existing = tmp_path / "foo.bin"
    existing.write_bytes(b"old")
    fake = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("mower_rover.transport.ssh.shutil.which", return_value="scp"),
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
    ):
        result = runner.invoke(
            laptop_app,
            [
                "jetson",
                "pull",
                "--config",
                str(cfg),
                "/remote/foo.bin",
                str(existing),
            ],
            input="n\n",
        )
    assert result.exit_code == 1
    assert "Aborted" in result.output


def test_laptop_jetson_pull_overwrite_yes(runner: CliRunner, tmp_path: Path) -> None:
    cfg = tmp_path / "laptop.yaml"
    cfg.write_text("jetson:\n  host: h\n  user: u\n", encoding="utf-8")
    existing = tmp_path / "foo.bin"
    existing.write_bytes(b"old")
    fake = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("mower_rover.transport.ssh.shutil.which", return_value="scp"),
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
    ):
        result = runner.invoke(
            laptop_app,
            [
                "jetson",
                "pull",
                "--yes",
                "--config",
                str(cfg),
                "/remote/foo.bin",
                str(existing),
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Pulled" in result.output


def test_laptop_jetson_run_env_var_endpoint(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOWER_JETSON_HOST", "envhost")
    monkeypatch.setenv("MOWER_JETSON_USER", "envuser")
    cfg = tmp_path / "missing.yaml"
    with patch("mower_rover.transport.ssh.shutil.which", return_value="ssh"):
        result = runner.invoke(
            laptop_app,
            [
                "--dry-run",
                "jetson",
                "run",
                "--config",
                str(cfg),
                "--",
                "id",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "envuser@envhost" in result.output


# --- probe command -----------------------------------------------------------


def test_probe_help(runner: CliRunner) -> None:
    result = runner.invoke(jetson_app, ["probe", "--help"])
    assert result.exit_code == 0, result.output
    assert "probe" in result.stdout.lower()


def test_probe_json_with_monkeypatched_results(runner: CliRunner) -> None:
    canned = [
        CheckResult(name="python_ver", status=Status.PASS, severity=Severity.CRITICAL, detail="3.11.5"),
        CheckResult(name="disk", status=Status.FAIL, severity=Severity.WARNING, detail="disk low"),
    ]
    with patch("mower_rover.cli.jetson.run_checks", return_value=canned):
        result = runner.invoke(jetson_app, ["probe", "--json"])
    assert result.exit_code == 1  # WARNING severity → exit 1
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    assert payload[0]["name"] == "python_ver"
    assert payload[0]["status"] == "pass"
    assert payload[1]["status"] == "fail"


def test_probe_all_pass(runner: CliRunner) -> None:
    canned = [
        CheckResult(name="a", status=Status.PASS, severity=Severity.INFO, detail="ok"),
    ]
    with patch("mower_rover.cli.jetson.run_checks", return_value=canned):
        result = runner.invoke(jetson_app, ["probe"])
    assert result.exit_code == 0


def test_probe_check_filter(runner: CliRunner) -> None:
    canned = [
        CheckResult(name="disk", status=Status.PASS, severity=Severity.WARNING, detail="ok"),
    ]
    with patch("mower_rover.cli.jetson.run_checks", return_value=canned) as mock_run:
        result = runner.invoke(jetson_app, ["probe", "--check", "disk"])
    assert result.exit_code == 0
    mock_run.assert_called_once_with(sysroot=Path("/"), only=frozenset({"disk"}))


# --- thermal command ---------------------------------------------------------


def test_thermal_help(runner: CliRunner) -> None:
    result = runner.invoke(jetson_app, ["thermal", "--help"])
    assert result.exit_code == 0, result.output
    assert "thermal" in result.stdout.lower()


def test_thermal_json(runner: CliRunner) -> None:
    snapshot = ThermalSnapshot(
        zones=[
            ThermalZone(index=0, name="CPU-therm", temp_c=45.5),
            ThermalZone(index=1, name="GPU-therm", temp_c=72.0),
        ],
        timestamp="2026-04-22T00:00:00+00:00",
    )
    with patch("mower_rover.cli.jetson.read_thermal_zones", return_value=snapshot):
        result = runner.invoke(jetson_app, ["thermal", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["zones"]) == 2
    assert payload["zones"][0]["name"] == "CPU-therm"


def test_thermal_table(runner: CliRunner) -> None:
    snapshot = ThermalSnapshot(
        zones=[ThermalZone(index=0, name="CPU-therm", temp_c=50.0)],
        timestamp="2026-04-22T00:00:00+00:00",
    )
    with patch("mower_rover.cli.jetson.read_thermal_zones", return_value=snapshot):
        result = runner.invoke(jetson_app, ["thermal"])
    assert result.exit_code == 0, result.output
    assert "CPU-therm" in result.stdout


# --- power command -----------------------------------------------------------


def test_power_help(runner: CliRunner) -> None:
    result = runner.invoke(jetson_app, ["power", "--help"])
    assert result.exit_code == 0, result.output
    assert "power" in result.stdout.lower()


def test_power_json(runner: CliRunner) -> None:
    state = PowerState(
        mode_id=0,
        mode_name="MAXN",
        online_cpus=12,
        gpu_freq_mhz=1300,
        fan_profile="cool",
        timestamp="2026-04-22T00:00:00+00:00",
    )
    with patch("mower_rover.cli.jetson.read_power_state", return_value=state):
        result = runner.invoke(jetson_app, ["power", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode_name"] == "MAXN"
    assert payload["online_cpus"] == 12


def test_power_table(runner: CliRunner) -> None:
    state = PowerState(
        mode_id=0,
        mode_name="MAXN",
        online_cpus=12,
        gpu_freq_mhz=1300,
        fan_profile="cool",
        timestamp="2026-04-22T00:00:00+00:00",
    )
    with patch("mower_rover.cli.jetson.read_power_state", return_value=state):
        result = runner.invoke(jetson_app, ["power"])
    assert result.exit_code == 0, result.output
    assert "MAXN" in result.stdout


# --- info new fields ---------------------------------------------------------


def test_info_json_has_new_fields(runner: CliRunner) -> None:
    with (
        patch("mower_rover.cli.jetson.read_disk_usage", return_value=[]),
        patch(
            "mower_rover.cli.jetson.read_power_state",
            return_value=PowerState(
                mode_id=0, mode_name="MAXN", online_cpus=12,
                gpu_freq_mhz=1300, fan_profile="cool",
                timestamp="2026-04-22T00:00:00+00:00",
            ),
        ),
        patch("mower_rover.cli.jetson._read_cuda_version", return_value="12.2"),
        patch("mower_rover.cli.jetson._detect_oakd", return_value=False),
    ):
        result = runner.invoke(jetson_app, ["info", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "cuda_version" in payload
    assert payload["cuda_version"] == "12.2"
    assert "nvme_present" in payload
    assert "power_mode" in payload
    assert payload["power_mode"] == "MAXN"
    assert "oakd_detected" in payload
