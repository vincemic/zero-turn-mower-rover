"""Laptop-side YAML config schema.

For Phase 3 this carries the SSH endpoint pointing at the Jetson. Later
phases extend with mission/calibration paths, base-station radio port, etc.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _default_laptop_config_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "mower-rover" / "laptop.yaml"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "mower-rover" / "laptop.yaml"


DEFAULT_LAPTOP_CONFIG_PATH: Path = _default_laptop_config_path()


@dataclass
class JetsonEndpoint:
    """SSH coordinates for the rover's Jetson AGX Orin."""

    host: str
    user: str
    port: int = 22
    key_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "key_path": str(self.key_path) if self.key_path is not None else None,
        }


@dataclass
class LaptopConfig:
    jetson: JetsonEndpoint | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jetson": self.jetson.to_dict() if self.jetson else None}
        return d


class LaptopConfigError(ValueError):
    """Raised when a laptop YAML config is malformed."""


def _coerce_endpoint(raw: dict[str, Any]) -> JetsonEndpoint:
    if not isinstance(raw, dict):
        raise LaptopConfigError(
            f"`jetson` must be a mapping, got {type(raw).__name__}"
        )
    missing = {"host", "user"} - raw.keys()
    if missing:
        raise LaptopConfigError(f"`jetson` is missing required fields: {sorted(missing)}")
    host = raw["host"]
    user = raw["user"]
    if not isinstance(host, str) or not isinstance(user, str):
        raise LaptopConfigError("`jetson.host` and `jetson.user` must be strings")
    port_raw = raw.get("port", 22)
    if not isinstance(port_raw, int) or port_raw <= 0 or port_raw > 65535:
        raise LaptopConfigError(f"`jetson.port` must be 1..65535, got {port_raw!r}")
    key_raw = raw.get("key_path")
    key_path: Path | None
    if key_raw is None:
        key_path = None
    elif isinstance(key_raw, str):
        key_path = Path(key_raw).expanduser()
    else:
        raise LaptopConfigError(
            f"`jetson.key_path` must be a string, got {type(key_raw).__name__}"
        )
    return JetsonEndpoint(host=host, user=user, port=port_raw, key_path=key_path)


def load_laptop_config(path: Path | None = None) -> LaptopConfig:
    target = path or DEFAULT_LAPTOP_CONFIG_PATH
    if not target.exists():
        return LaptopConfig()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise LaptopConfigError(f"failed to parse {target}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LaptopConfigError(
            f"top-level YAML must be a mapping, got {type(raw).__name__}"
        )
    known = {"jetson"}
    extra = {k: v for k, v in raw.items() if k not in known}
    jetson_raw = raw.get("jetson")
    endpoint = _coerce_endpoint(jetson_raw) if jetson_raw else None
    return LaptopConfig(jetson=endpoint, extra=extra)


def save_laptop_config(config: LaptopConfig, path: Path | None = None) -> Path:
    target = path or DEFAULT_LAPTOP_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.to_dict()
    payload.update(config.extra)
    target.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return target
