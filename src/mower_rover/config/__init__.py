"""Config schemas + load/save for laptop- and Jetson-side YAML files."""

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

__all__ = [
    "DEFAULT_JETSON_CONFIG_PATH",
    "DEFAULT_LAPTOP_CONFIG_PATH",
    "JetsonConfig",
    "JetsonEndpoint",
    "LaptopConfig",
    "load_jetson_config",
    "load_laptop_config",
    "save_jetson_config",
    "save_laptop_config",
]
