"""Tests for zone management CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from mower_rover.cli.zone_laptop import (
    ZoneUploadError,
    _check_not_armed,
    _upload_zone_atomically,
    _write_zone_snapshot,
    mission_app,
    zone_app,
)
from mower_rover.mavlink.mission import MissionItem
from mower_rover.zone.config import CoverageParams, LatLon, RallyPoint, ZoneConfig


@pytest.fixture
def sample_zone_config() -> ZoneConfig:
    return ZoneConfig(
        schema="mower-rover.zone.v1",
        zone_id="test_zone",
        name="Test Zone",
        home=LatLon(lat=40.7128, lon=-74.0060),
        rally_point=RallyPoint(lat=40.7130, lon=-74.0058, description="Test rally"),
        boundary=[
            LatLon(lat=40.7120, lon=-74.0070),
            LatLon(lat=40.7140, lon=-74.0070),
            LatLon(lat=40.7140, lon=-74.0050),
            LatLon(lat=40.7120, lon=-74.0050),
        ],
        coverage=CoverageParams(cutting_width_in=54.0, mow_speed_mps=2.0),
    )


@pytest.fixture
def sample_waypoints() -> list[LatLon]:
    return [
        LatLon(lat=40.7125, lon=-74.0065),
        LatLon(lat=40.7135, lon=-74.0065),
        LatLon(lat=40.7135, lon=-74.0055),
        LatLon(lat=40.7125, lon=-74.0055),
    ]


@pytest.fixture
def mock_mission_items() -> list[MissionItem]:
    return [
        MissionItem(seq=0, frame=5, command=16, current=1),
        MissionItem(seq=1, frame=5, command=16),
        MissionItem(seq=2, frame=5, command=16),
    ]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ------------------------------------------------------------------ zone list


class TestZoneList:
    @patch("mower_rover.cli.zone_laptop.load_all_zones")
    def test_list_zones_success(self, mock_load, runner, sample_zone_config):
        mock_load.return_value = [sample_zone_config]
        result = runner.invoke(zone_app, ["list"])
        assert result.exit_code == 0
        assert "test_zone" in result.output
        assert "Test Zone" in result.output
        assert "Total: 1 zones" in result.output

    @patch("mower_rover.cli.zone_laptop.load_all_zones")
    def test_list_zones_empty(self, mock_load, runner):
        mock_load.return_value = []
        result = runner.invoke(zone_app, ["list"])
        assert result.exit_code == 0
        assert "No valid zone files found" in result.output

    def test_list_zones_missing_directory(self, runner, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        result = runner.invoke(zone_app, ["list", "--zones-dir", str(nonexistent)])
        assert result.exit_code == 1
        assert "Zones directory not found" in result.output


# ------------------------------------------------------------------ zone select


class TestZoneSelect:
    @patch("mower_rover.cli.zone_laptop._write_zone_snapshot")
    @patch("mower_rover.cli.zone_laptop._upload_zone_atomically")
    @patch("mower_rover.cli.zone_laptop.zone_to_rally")
    @patch("mower_rover.cli.zone_laptop.zone_to_fence")
    @patch("mower_rover.cli.zone_laptop.zone_to_mission")
    @patch("mower_rover.cli.zone_laptop.generate_waypoints")
    @patch("mower_rover.cli.zone_laptop._check_not_armed")
    @patch("mower_rover.cli.zone_laptop.open_link")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_select_success(
        self,
        mock_load,
        mock_open_link,
        mock_check_armed,
        mock_gen_wp,
        mock_to_mission,
        mock_to_fence,
        mock_to_rally,
        mock_upload,
        mock_snapshot,
        runner,
        sample_zone_config,
        sample_waypoints,
        mock_mission_items,
    ):
        mock_load.return_value = sample_zone_config
        mock_gen_wp.return_value = sample_waypoints
        mock_to_mission.return_value = mock_mission_items
        mock_to_fence.return_value = [MissionItem(seq=0, frame=5, command=5001)]
        mock_to_rally.return_value = [MissionItem(seq=0, frame=5, command=5100)]
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_open_link.return_value.__exit__ = Mock(return_value=False)

        result = runner.invoke(
            zone_app,
            ["select", "test.yaml", "--yes", "--skip-slam"],
        )

        assert result.exit_code == 0, result.output
        mock_load.assert_called_once()
        mock_gen_wp.assert_called_once()
        mock_upload.assert_called_once()
        assert "selected successfully" in result.output

    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_select_invalid_config(self, mock_load, runner):
        mock_load.side_effect = ValueError("Invalid YAML")

        result = runner.invoke(
            zone_app, ["select", "invalid.yaml", "--yes"]
        )

        assert result.exit_code == 1
        assert "Failed to load zone config" in result.output

    @patch("mower_rover.cli.zone_laptop.generate_waypoints")
    @patch("mower_rover.cli.zone_laptop.zone_to_mission")
    @patch("mower_rover.cli.zone_laptop.zone_to_fence")
    @patch("mower_rover.cli.zone_laptop.zone_to_rally")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_select_dry_run(
        self,
        mock_load,
        mock_to_rally,
        mock_to_fence,
        mock_to_mission,
        mock_gen_wp,
        runner,
        sample_zone_config,
        sample_waypoints,
        mock_mission_items,
    ):
        mock_load.return_value = sample_zone_config
        mock_gen_wp.return_value = sample_waypoints
        mock_to_mission.return_value = mock_mission_items
        mock_to_fence.return_value = [MissionItem(seq=0, frame=5, command=5001)]
        mock_to_rally.return_value = [MissionItem(seq=0, frame=5, command=5100)]

        result = runner.invoke(
            zone_app, ["select", "test.yaml", "--dry-run"]
        )

        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output

    @patch("mower_rover.cli.zone_laptop._check_not_armed")
    @patch("mower_rover.cli.zone_laptop.open_link")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_select_armed_fc(
        self, mock_load, mock_open_link, mock_check, runner, sample_zone_config
    ):
        mock_load.return_value = sample_zone_config
        mock_check.side_effect = Exception("FC is armed")
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_open_link.return_value.__exit__ = Mock(return_value=False)

        result = runner.invoke(
            zone_app, ["select", "test.yaml", "--yes", "--skip-slam"]
        )
        assert result.exit_code == 1

    @patch("mower_rover.cli.zone_laptop.generate_waypoints")
    @patch("mower_rover.cli.zone_laptop._check_not_armed")
    @patch("mower_rover.cli.zone_laptop.open_link")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_select_no_waypoints(
        self, mock_load, mock_open_link, mock_check, mock_gen_wp,
        runner, sample_zone_config,
    ):
        mock_load.return_value = sample_zone_config
        mock_gen_wp.return_value = []
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_open_link.return_value.__exit__ = Mock(return_value=False)

        result = runner.invoke(
            zone_app, ["select", "test.yaml", "--yes", "--skip-slam"]
        )
        assert result.exit_code == 1
        assert "No waypoints generated" in result.output

    def test_zone_select_confirmation_declined(self, runner):
        """Select without --yes triggers confirmation which declines on EOF."""
        result = runner.invoke(zone_app, ["select", "test.yaml"])
        # Confirmation is declined (EOF → no)
        assert result.exit_code != 0


# ------------------------------------------------------------------ zone resume


class TestZoneResume:
    @patch("mower_rover.cli.zone_laptop.download_mission")
    @patch("mower_rover.cli.zone_laptop.open_link")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_resume_dry_run(
        self, mock_load, mock_open_link, mock_download,
        runner, sample_zone_config, mock_mission_items,
    ):
        mock_load.return_value = sample_zone_config
        mock_download.return_value = mock_mission_items
        mock_conn = MagicMock()
        mock_open_link.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_open_link.return_value.__exit__ = Mock(return_value=False)
        mock_conn.recv_match.return_value = Mock(seq=1)

        result = runner.invoke(zone_app, ["resume", "test.yaml", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Current waypoint: 1" in result.output
        assert "DRY RUN" in result.output

    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_zone_resume_invalid_config(self, mock_load, runner):
        mock_load.side_effect = ValueError("Invalid config")

        result = runner.invoke(zone_app, ["resume", "invalid.yaml"])
        assert result.exit_code == 1
        assert "Failed to load zone config" in result.output


# ------------------------------------------------------------------ mission plan


class TestMissionPlan:
    @patch("mower_rover.cli.zone_laptop.generate_waypoints")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_mission_plan_success(
        self, mock_load, mock_gen_wp, runner,
        sample_zone_config, sample_waypoints, tmp_path,
    ):
        mock_load.return_value = sample_zone_config
        mock_gen_wp.return_value = sample_waypoints
        output_dir = tmp_path / "output"

        result = runner.invoke(
            mission_app, ["plan", "test.yaml", "--output-dir", str(output_dir)]
        )

        assert result.exit_code == 0, result.output
        assert "Mission planned successfully" in result.output

        waypoints_file = output_dir / "test_zone.waypoints"
        assert waypoints_file.exists()
        content = waypoints_file.read_text()
        lines = content.strip().split("\n")
        assert lines[0] == "QGC WPL 110"
        # header + home + 4 waypoints
        assert len(lines) == 1 + 1 + len(sample_waypoints)

    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_mission_plan_invalid_config(self, mock_load, runner):
        mock_load.side_effect = ValueError("Invalid config")

        result = runner.invoke(mission_app, ["plan", "invalid.yaml"])
        assert result.exit_code == 1
        assert "Failed to load zone config" in result.output

    @patch("mower_rover.cli.zone_laptop.generate_waypoints")
    @patch("mower_rover.cli.zone_laptop.load_zone_config")
    def test_mission_plan_no_waypoints(
        self, mock_load, mock_gen_wp, runner, sample_zone_config,
    ):
        mock_load.return_value = sample_zone_config
        mock_gen_wp.return_value = []

        result = runner.invoke(mission_app, ["plan", "test.yaml"])
        assert result.exit_code == 1
        assert "No waypoints generated" in result.output


# ------------------------------------------------------------------ helpers


class TestHelperFunctions:
    def test_check_not_armed_disarmed(self):
        conn = MagicMock()
        conn.recv_match.return_value = Mock(base_mode=0)
        _check_not_armed(conn)  # should not raise

    def test_check_not_armed_armed(self):
        import typer as _typer

        conn = MagicMock()
        conn.recv_match.return_value = Mock(base_mode=128)  # SAFETY_ARMED
        with pytest.raises(_typer.BadParameter, match="FC is armed"):
            _check_not_armed(conn)

    @patch("mower_rover.cli.zone_laptop.verify_round_trip")
    @patch("mower_rover.cli.zone_laptop.upload_mission")
    def test_upload_zone_atomically_success(
        self, mock_upload, mock_verify, mock_mission_items,
    ):
        conn = MagicMock()
        fence = [MissionItem(seq=0, frame=5, command=5001)]
        rally = [MissionItem(seq=0, frame=5, command=5100)]

        _upload_zone_atomically(conn, mock_mission_items, fence, rally)

        assert mock_upload.call_count == 3
        assert mock_verify.call_count == 3

    @patch("mower_rover.cli.zone_laptop.clear_mission")
    @patch("mower_rover.cli.zone_laptop.upload_mission")
    def test_upload_zone_atomically_clears_on_failure(
        self, mock_upload, mock_clear, mock_mission_items,
    ):
        conn = MagicMock()
        fence = [MissionItem(seq=0, frame=5, command=5001)]
        rally = [MissionItem(seq=0, frame=5, command=5100)]
        mock_upload.side_effect = [None, RuntimeError("upload fail"), None]

        with pytest.raises(ZoneUploadError, match="All missions cleared for safety"):
            _upload_zone_atomically(conn, mock_mission_items, fence, rally)

        assert mock_clear.call_count == 3

    def test_write_zone_snapshot(self, tmp_path):
        rally = LatLon(lat=40.7130, lon=-74.0058)
        out = tmp_path / "snapshots" / "test" / "snap.json"

        _write_zone_snapshot("test_zone", 10, 4, rally, out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["schema"] == "mower-rover.zone-upload.v1"
        assert data["zone_id"] == "test_zone"
        assert data["waypoint_count"] == 10
        assert data["fence_vertex_count"] == 4
        assert data["rally_point"]["lat"] == 40.7130


# ------------------------------------------------------------------ integration


class TestIntegration:
    @patch("mower_rover.cli.zone_laptop.load_all_zones")
    def test_list_with_existing_dir(self, mock_load, runner, sample_zone_config):
        mock_load.return_value = [sample_zone_config]
        result = runner.invoke(zone_app, ["list", "--zones-dir", "zones"])
        assert result.exit_code == 0
        assert "test_zone" in result.output

    def test_zone_help(self, runner):
        result = runner.invoke(zone_app, ["--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "select" in result.output
        assert "resume" in result.output

    def test_mission_help(self, runner):
        result = runner.invoke(mission_app, ["--help"])
        assert result.exit_code == 0
        assert "plan" in result.output
