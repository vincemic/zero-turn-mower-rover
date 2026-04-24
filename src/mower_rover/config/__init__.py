"""Config schemas + load/save for laptop-, Jetson-, and VSLAM-side YAML files."""

from __future__ import annotations

from mower_rover.config.jetson import (
    DEFAULT_JETSON_CONFIG_PATH,
    JetsonConfig,
    load_jetson_config,
    save_jetson_config,
)
from mower_rover.config.laptop import (
    DEFAULT_LAPTOP_CONFIG_PATH,
    JetsonEndpoint,
    LaptopConfig,
    load_laptop_config,
    save_laptop_config,
)
from mower_rover.config.vslam import (
    DEFAULT_VSLAM_CONFIG_PATH,
    BridgeConfig,
    Extrinsics,
    VslamConfig,
    load_vslam_config,
    save_vslam_config,
)

__all__ = [
    "BridgeConfig",
    "DEFAULT_JETSON_CONFIG_PATH",
    "DEFAULT_LAPTOP_CONFIG_PATH",
    "DEFAULT_VSLAM_CONFIG_PATH",
    "Extrinsics",
    "JetsonConfig",
    "JetsonEndpoint",
    "LaptopConfig",
    "VslamConfig",
    "load_jetson_config",
    "load_laptop_config",
    "load_vslam_config",
    "save_jetson_config",
    "save_laptop_config",
    "save_vslam_config",
]
