"""Tests for VSLAM config loader — no Jetson hardware required."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mower_rover.config.vslam import (
    BridgeConfig,
    Extrinsics,
    VslamConfig,
    VslamConfigError,
    load_vslam_config,
    save_vslam_config,
)

# ------------------------------------------------------------------
# Defaults when file is missing
# ------------------------------------------------------------------


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_vslam_config(tmp_path / "nonexistent.yaml")
    assert cfg.odometry_strategy == "f2m"
    assert cfg.stereo_resolution == "800p"
    assert cfg.stereo_fps == 30
    assert cfg.imu_rate_hz == 200
    assert cfg.pose_output_rate_hz == 20
    assert cfg.memory_threshold_mb == 6000
    assert cfg.loop_closure is True
    assert cfg.database_path == "/var/lib/mower/rtabmap.db"
    assert cfg.socket_path == "/run/mower/vslam-pose.sock"
    assert cfg.usb_max_speed == "SUPER"
    assert cfg.ir_dot_projector_ma == 750
    assert cfg.ir_flood_led_ma == 200
    # extrinsics defaults
    assert cfg.extrinsics.pos_x == pytest.approx(0.30)
    assert cfg.extrinsics.pos_y == pytest.approx(0.00)
    assert cfg.extrinsics.pos_z == pytest.approx(-0.20)
    assert cfg.extrinsics.pitch == pytest.approx(-15.0)
    # bridge defaults
    assert cfg.bridge.serial_device == "/dev/ttyACM0"
    assert cfg.bridge.source_system == 1
    assert cfg.bridge.source_component == 197


# ------------------------------------------------------------------
# Valid config round-trip
# ------------------------------------------------------------------


def test_load_valid_config(tmp_path: Path) -> None:
    data = {
        "vslam": {
            "odometry_strategy": "f2f",
            "stereo_resolution": "720p",
            "stereo_fps": 15,
            "imu_rate_hz": 100,
            "pose_output_rate_hz": 10,
            "memory_threshold_mb": 4000,
            "loop_closure": False,
            "database_path": "/tmp/test.db",
            "socket_path": "/tmp/test.sock",
            "extrinsics": {
                "pos_x": 0.5,
                "pos_y": 0.1,
                "pos_z": -0.3,
                "roll": 1.0,
                "pitch": -10.0,
                "yaw": 5.0,
            },
        },
        "bridge": {
            "serial_device": "/dev/ttyUSB0",
            "source_system": 2,
            "source_component": 200,
        },
    }
    cfg_path = tmp_path / "vslam.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cfg = load_vslam_config(cfg_path)
    assert cfg.odometry_strategy == "f2f"
    assert cfg.stereo_resolution == "720p"
    assert cfg.stereo_fps == 15
    assert cfg.imu_rate_hz == 100
    assert cfg.pose_output_rate_hz == 10
    assert cfg.memory_threshold_mb == 4000
    assert cfg.loop_closure is False
    assert cfg.database_path == "/tmp/test.db"
    assert cfg.socket_path == "/tmp/test.sock"
    assert cfg.extrinsics.pos_x == pytest.approx(0.5)
    assert cfg.extrinsics.pitch == pytest.approx(-10.0)
    assert cfg.bridge.serial_device == "/dev/ttyUSB0"
    assert cfg.bridge.source_system == 2
    assert cfg.bridge.source_component == 200


def test_save_and_reload(tmp_path: Path) -> None:
    cfg = VslamConfig(
        odometry_strategy="f2m",
        memory_threshold_mb=8000,
        extrinsics=Extrinsics(pos_x=0.4),
        bridge=BridgeConfig(serial_device="/dev/ttyUSB1"),
    )
    out = save_vslam_config(cfg, tmp_path / "round.yaml")
    reloaded = load_vslam_config(out)
    assert reloaded.memory_threshold_mb == 8000
    assert reloaded.extrinsics.pos_x == pytest.approx(0.4)
    assert reloaded.bridge.serial_device == "/dev/ttyUSB1"


# ------------------------------------------------------------------
# Partial configs — missing sections use defaults
# ------------------------------------------------------------------


def test_partial_config_no_bridge(tmp_path: Path) -> None:
    data = {"vslam": {"odometry_strategy": "f2m"}}
    cfg_path = tmp_path / "vslam.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cfg = load_vslam_config(cfg_path)
    assert cfg.odometry_strategy == "f2m"
    assert cfg.bridge.serial_device == "/dev/ttyACM0"


def test_partial_config_no_extrinsics(tmp_path: Path) -> None:
    data = {"vslam": {"stereo_fps": 15}}
    cfg_path = tmp_path / "vslam.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cfg = load_vslam_config(cfg_path)
    assert cfg.stereo_fps == 15
    assert cfg.extrinsics.pos_x == pytest.approx(0.30)


def test_empty_yaml_returns_defaults(tmp_path: Path) -> None:
    cfg_path = tmp_path / "empty.yaml"
    cfg_path.write_text("", encoding="utf-8")
    cfg = load_vslam_config(cfg_path)
    assert cfg.odometry_strategy == "f2m"


# ------------------------------------------------------------------
# New fields: usb_max_speed, IR
# ------------------------------------------------------------------


def test_usb_max_speed_high(tmp_path: Path) -> None:
    data = {"vslam": {"usb_max_speed": "HIGH"}}
    cfg_path = tmp_path / "vslam.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    cfg = load_vslam_config(cfg_path)
    assert cfg.usb_max_speed == "HIGH"


def test_usb_max_speed_invalid(tmp_path: Path) -> None:
    data = {"vslam": {"usb_max_speed": "TURBO"}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(VslamConfigError, match="usb_max_speed"):
        load_vslam_config(cfg_path)


def test_ir_dot_projector_valid_range(tmp_path: Path) -> None:
    for val in (0, 600, 1200):
        data = {"vslam": {"ir_dot_projector_ma": val}}
        cfg_path = tmp_path / "vslam.yaml"
        cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        cfg = load_vslam_config(cfg_path)
        assert cfg.ir_dot_projector_ma == val


def test_ir_dot_projector_over_max(tmp_path: Path) -> None:
    data = {"vslam": {"ir_dot_projector_ma": 1201}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(VslamConfigError, match="ir_dot_projector_ma"):
        load_vslam_config(cfg_path)


def test_ir_flood_led_valid_range(tmp_path: Path) -> None:
    for val in (0, 750, 1500):
        data = {"vslam": {"ir_flood_led_ma": val}}
        cfg_path = tmp_path / "vslam.yaml"
        cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        cfg = load_vslam_config(cfg_path)
        assert cfg.ir_flood_led_ma == val


def test_ir_flood_led_over_max(tmp_path: Path) -> None:
    data = {"vslam": {"ir_flood_led_ma": 1501}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(VslamConfigError, match="ir_flood_led_ma"):
        load_vslam_config(cfg_path)


def test_ir_negative_rejected(tmp_path: Path) -> None:
    data = {"vslam": {"ir_dot_projector_ma": -1}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(VslamConfigError, match="ir_dot_projector_ma"):
        load_vslam_config(cfg_path)


# ------------------------------------------------------------------
# Invalid values
# ------------------------------------------------------------------


def test_invalid_odometry_strategy(tmp_path: Path) -> None:
    data = {"vslam": {"odometry_strategy": "invalid"}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="odometry_strategy"):
        load_vslam_config(cfg_path)


def test_invalid_stereo_resolution(tmp_path: Path) -> None:
    data = {"vslam": {"stereo_resolution": "1080p"}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="stereo_resolution"):
        load_vslam_config(cfg_path)


def test_invalid_stereo_fps_negative(tmp_path: Path) -> None:
    data = {"vslam": {"stereo_fps": -1}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="stereo_fps"):
        load_vslam_config(cfg_path)


def test_invalid_memory_threshold_zero(tmp_path: Path) -> None:
    data = {"vslam": {"memory_threshold_mb": 0}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="memory_threshold_mb"):
        load_vslam_config(cfg_path)


def test_invalid_loop_closure_not_bool(tmp_path: Path) -> None:
    data = {"vslam": {"loop_closure": "yes"}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="loop_closure"):
        load_vslam_config(cfg_path)


def test_invalid_extrinsics_type(tmp_path: Path) -> None:
    data = {"vslam": {"extrinsics": {"pos_x": "not_a_number"}}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="extrinsics.pos_x"):
        load_vslam_config(cfg_path)


def test_invalid_bridge_source_system(tmp_path: Path) -> None:
    data = {"vslam": {}, "bridge": {"source_system": -5}}
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VslamConfigError, match="source_system"):
        load_vslam_config(cfg_path)


def test_invalid_yaml_syntax(tmp_path: Path) -> None:
    cfg_path = tmp_path / "broken.yaml"
    cfg_path.write_text("vslam:\n  fps: [unclosed", encoding="utf-8")

    with pytest.raises(VslamConfigError, match="failed to parse"):
        load_vslam_config(cfg_path)


def test_top_level_not_a_mapping(tmp_path: Path) -> None:
    cfg_path = tmp_path / "list.yaml"
    cfg_path.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(VslamConfigError, match="top-level YAML must be a mapping"):
        load_vslam_config(cfg_path)
