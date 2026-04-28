"""VSLAM config schema and loader.

Configuration for RTAB-Map SLAM and the pymavlink bridge, read from
``/etc/mower/vslam.yaml`` on the Jetson.  Follows the same pattern as
``jetson.py`` (dataclass + coerce + load/save).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_VSLAM_CONFIG_PATH: Path = Path("/etc/mower/vslam.yaml")

_DEFAULTS_YAML = Path(__file__).resolve().parent / "data" / "vslam_defaults.yaml"


class VslamConfigError(ValueError):
    """Raised when a VSLAM YAML config is malformed."""


# ------------------------------------------------------------------
# Nested dataclasses
# ------------------------------------------------------------------


@dataclass
class Extrinsics:
    """Camera-to-Pixhawk extrinsic offsets (metres / degrees)."""

    pos_x: float = 0.30
    pos_y: float = 0.00
    pos_z: float = -0.20
    roll: float = 0.0
    pitch: float = -15.0
    yaw: float = 0.0


@dataclass
class BridgeConfig:
    """pymavlink bridge connection settings."""

    serial_device: str = "/dev/ttyACM0"
    source_system: int = 1
    source_component: int = 197


# ------------------------------------------------------------------
# Top-level config
# ------------------------------------------------------------------


@dataclass
class VslamConfig:
    """Full VSLAM runtime configuration."""

    odometry_strategy: str = "f2m"
    stereo_resolution: str = "800p"
    stereo_fps: int = 30
    imu_rate_hz: int = 200
    pose_output_rate_hz: int = 20
    memory_threshold_mb: int = 6000
    loop_closure: bool = True
    database_path: str = "/var/lib/mower/rtabmap.db"
    socket_path: str = "/run/mower/vslam-pose.sock"
    usb_max_speed: str = "SUPER"
    ir_dot_projector_ma: int = 750
    ir_flood_led_ma: int = 200
    extrinsics: Extrinsics = None  # type: ignore[assignment]
    bridge: BridgeConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extrinsics is None:
            self.extrinsics = Extrinsics()
        if self.bridge is None:
            self.bridge = BridgeConfig()

    def to_dict(self) -> dict[str, Any]:
        return {
            "vslam": {
                "odometry_strategy": self.odometry_strategy,
                "stereo_resolution": self.stereo_resolution,
                "stereo_fps": self.stereo_fps,
                "imu_rate_hz": self.imu_rate_hz,
                "pose_output_rate_hz": self.pose_output_rate_hz,
                "memory_threshold_mb": self.memory_threshold_mb,
                "loop_closure": self.loop_closure,
                "database_path": self.database_path,
                "socket_path": self.socket_path,
                "usb_max_speed": self.usb_max_speed,
                "ir_dot_projector_ma": self.ir_dot_projector_ma,
                "ir_flood_led_ma": self.ir_flood_led_ma,
                "extrinsics": asdict(self.extrinsics),
            },
            "bridge": asdict(self.bridge),
        }


# ------------------------------------------------------------------
# Coercion / validation
# ------------------------------------------------------------------

_VALID_ODOMETRY = {"f2m", "f2f", "fovis", "viso2", "orbslam2"}
_VALID_RESOLUTIONS = {"400p", "480p", "720p", "800p"}
_VALID_USB_SPEEDS = {"HIGH", "SUPER", "SUPER_PLUS"}


def _coerce_extrinsics(raw: Any) -> Extrinsics:
    if raw is None:
        return Extrinsics()
    if not isinstance(raw, dict):
        raise VslamConfigError(
            f"extrinsics must be a mapping, got {type(raw).__name__}"
        )
    kwargs: dict[str, float] = {}
    for key in ("pos_x", "pos_y", "pos_z", "roll", "pitch", "yaw"):
        val = raw.get(key)
        if val is not None:
            if not isinstance(val, (int, float)):
                raise VslamConfigError(
                    f"extrinsics.{key} must be a number, got {type(val).__name__}"
                )
            kwargs[key] = float(val)
    return Extrinsics(**kwargs)


def _coerce_bridge(raw: Any) -> BridgeConfig:
    if raw is None:
        return BridgeConfig()
    if not isinstance(raw, dict):
        raise VslamConfigError(
            f"bridge must be a mapping, got {type(raw).__name__}"
        )
    serial_device = raw.get("serial_device", "/dev/ttyACM0")
    if not isinstance(serial_device, str):
        raise VslamConfigError(
            f"bridge.serial_device must be a string, got {type(serial_device).__name__}"
        )
    source_system = raw.get("source_system", 1)
    if not isinstance(source_system, int) or source_system < 0:
        raise VslamConfigError(
            f"bridge.source_system must be a non-negative integer, got {source_system!r}"
        )
    source_component = raw.get("source_component", 197)
    if not isinstance(source_component, int) or source_component < 0:
        raise VslamConfigError(
            f"bridge.source_component must be a non-negative integer, got {source_component!r}"
        )
    return BridgeConfig(
        serial_device=serial_device,
        source_system=source_system,
        source_component=source_component,
    )


def _coerce(raw: dict[str, Any]) -> VslamConfig:
    """Validate and coerce a raw YAML dict into a ``VslamConfig``."""
    if not isinstance(raw, dict):
        raise VslamConfigError(
            f"top-level YAML must be a mapping, got {type(raw).__name__}"
        )

    vslam_raw = raw.get("vslam", {})
    if not isinstance(vslam_raw, dict):
        raise VslamConfigError(
            f"'vslam' must be a mapping, got {type(vslam_raw).__name__}"
        )

    odometry_strategy = vslam_raw.get("odometry_strategy", "f2m")
    if odometry_strategy not in _VALID_ODOMETRY:
        raise VslamConfigError(
            f"odometry_strategy must be one of {_VALID_ODOMETRY}, got {odometry_strategy!r}"
        )

    stereo_resolution = vslam_raw.get("stereo_resolution", "400p")
    if stereo_resolution not in _VALID_RESOLUTIONS:
        raise VslamConfigError(
            f"stereo_resolution must be one of {_VALID_RESOLUTIONS}, got {stereo_resolution!r}"
        )

    stereo_fps = vslam_raw.get("stereo_fps", 30)
    if not isinstance(stereo_fps, int) or stereo_fps <= 0:
        raise VslamConfigError(f"stereo_fps must be a positive integer, got {stereo_fps!r}")

    imu_rate_hz = vslam_raw.get("imu_rate_hz", 200)
    if not isinstance(imu_rate_hz, int) or imu_rate_hz <= 0:
        raise VslamConfigError(f"imu_rate_hz must be a positive integer, got {imu_rate_hz!r}")

    pose_output_rate_hz = vslam_raw.get("pose_output_rate_hz", 20)
    if not isinstance(pose_output_rate_hz, int) or pose_output_rate_hz <= 0:
        raise VslamConfigError(
            f"pose_output_rate_hz must be a positive integer, got {pose_output_rate_hz!r}"
        )

    memory_threshold_mb = vslam_raw.get("memory_threshold_mb", 6000)
    if not isinstance(memory_threshold_mb, int) or memory_threshold_mb <= 0:
        raise VslamConfigError(
            f"memory_threshold_mb must be a positive integer, got {memory_threshold_mb!r}"
        )

    loop_closure = vslam_raw.get("loop_closure", True)
    if not isinstance(loop_closure, bool):
        raise VslamConfigError(
            f"loop_closure must be bool, got {type(loop_closure).__name__}"
        )

    database_path = vslam_raw.get("database_path", "/var/lib/mower/rtabmap.db")
    if not isinstance(database_path, str):
        raise VslamConfigError(
            f"database_path must be a string, got {type(database_path).__name__}"
        )

    socket_path = vslam_raw.get("socket_path", "/run/mower/vslam-pose.sock")
    if not isinstance(socket_path, str):
        raise VslamConfigError(
            f"socket_path must be a string, got {type(socket_path).__name__}"
        )

    usb_max_speed = vslam_raw.get("usb_max_speed", "SUPER")
    if usb_max_speed not in _VALID_USB_SPEEDS:
        raise VslamConfigError(
            f"usb_max_speed must be one of {_VALID_USB_SPEEDS}, got {usb_max_speed!r}"
        )

    ir_dot_projector_ma = vslam_raw.get("ir_dot_projector_ma", 750)
    if not isinstance(ir_dot_projector_ma, int) or not (0 <= ir_dot_projector_ma <= 1200):
        raise VslamConfigError(
            f"ir_dot_projector_ma must be int 0\u20131200, got {ir_dot_projector_ma!r}"
        )

    ir_flood_led_ma = vslam_raw.get("ir_flood_led_ma", 200)
    if not isinstance(ir_flood_led_ma, int) or not (0 <= ir_flood_led_ma <= 1500):
        raise VslamConfigError(
            f"ir_flood_led_ma must be int 0\u20131500, got {ir_flood_led_ma!r}"
        )

    extrinsics = _coerce_extrinsics(vslam_raw.get("extrinsics"))
    bridge = _coerce_bridge(raw.get("bridge"))

    return VslamConfig(
        odometry_strategy=odometry_strategy,
        stereo_resolution=stereo_resolution,
        stereo_fps=stereo_fps,
        imu_rate_hz=imu_rate_hz,
        pose_output_rate_hz=pose_output_rate_hz,
        memory_threshold_mb=memory_threshold_mb,
        loop_closure=loop_closure,
        database_path=database_path,
        socket_path=socket_path,
        usb_max_speed=usb_max_speed,
        ir_dot_projector_ma=ir_dot_projector_ma,
        ir_flood_led_ma=ir_flood_led_ma,
        extrinsics=extrinsics,
        bridge=bridge,
    )


# ------------------------------------------------------------------
# Load / save
# ------------------------------------------------------------------


def _load_defaults() -> dict[str, Any]:
    """Load built-in default values from the bundled YAML."""
    if _DEFAULTS_YAML.exists():
        return yaml.safe_load(_DEFAULTS_YAML.read_text(encoding="utf-8")) or {}
    return {}


def load_vslam_config(path: Path | None = None) -> VslamConfig:
    """Load VSLAM config from *path* (default: ``/etc/mower/vslam.yaml``).

    Returns defaults if the file does not exist.
    """
    target = path or DEFAULT_VSLAM_CONFIG_PATH
    if not target.exists():
        return VslamConfig()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise VslamConfigError(f"failed to parse {target}: {exc}") from exc
    return _coerce(raw)


def save_vslam_config(config: VslamConfig, path: Path | None = None) -> Path:
    """Write *config* to *path* (default: ``/etc/mower/vslam.yaml``)."""
    target = path or DEFAULT_VSLAM_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.to_dict()
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target
