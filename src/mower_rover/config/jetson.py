"""Jetson-side YAML config schema.

Minimal for Phase 3: just the fields we know we need to surface from
`mower-jetson config show`. New fields land as later phases need them.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _default_jetson_config_path() -> Path:
    """Per-user config path on the Jetson (XDG); falls back on Windows for laptop dev."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "mower-rover" / "jetson.yaml"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "mower-rover" / "jetson.yaml"


DEFAULT_JETSON_CONFIG_PATH: Path = _default_jetson_config_path()


def _default_kiosk_service_units() -> list[str]:
    return [
        "mower-health.service",
        "mower-vslam.service",
        "mower-vslam-bridge.service",
        "mower-weston.service",
        "mower-mavproxy.service",
    ]


def _default_mavproxy_outputs() -> list[str]:
    return [
        "udp:127.0.0.1:14550",
        "udp:127.0.0.1:14551",
        "udp:127.0.0.1:14552",
    ]


@dataclass
class KioskConfig:
    """Configuration for the kiosk operational display."""

    mavproxy_endpoint: str = "udp:127.0.0.1:14551"
    mavproxy_master: str = "/dev/ttyACM0"
    mavproxy_outputs: list[str] = field(default_factory=_default_mavproxy_outputs)
    vslam_socket: str = "/run/mower/vslam-pose.sock"
    refresh_hz: int = 1
    heartbeat_staleness_s: float = 60.0
    service_check_units: list[str] = field(default_factory=_default_kiosk_service_units)


@dataclass
class JetsonConfig:
    """Jetson-side runtime config.

    Attributes:
        log_dir: Where the Jetson-side CLI writes its structlog JSONL files.
            `None` means "use the default per-user log directory".
        oakd_required: If True, future hardware probes treat a missing OAK-D
            as an error rather than a warning. Phase 12 consumes this.
    """

    log_dir: Path | None = None
    oakd_required: bool = False
    health_interval_s: int = 60
    service_user_level: bool = False
    kiosk: KioskConfig = field(default_factory=KioskConfig)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["log_dir"] = str(self.log_dir) if self.log_dir is not None else None
        return d


class JetsonConfigError(ValueError):
    """Raised when a Jetson YAML config is malformed."""


def _coerce_kiosk(raw: Any) -> KioskConfig:
    """Parse and validate the optional ``kiosk:`` section."""
    if raw is None:
        return KioskConfig()
    if not isinstance(raw, dict):
        raise JetsonConfigError(f"kiosk section must be a mapping, got {type(raw).__name__}")
    kwargs: dict[str, Any] = {}
    if "mavproxy_endpoint" in raw:
        v = raw["mavproxy_endpoint"]
        if not isinstance(v, str):
            raise JetsonConfigError(f"kiosk.mavproxy_endpoint must be str, got {type(v).__name__}")
        kwargs["mavproxy_endpoint"] = v
    if "mavproxy_master" in raw:
        v = raw["mavproxy_master"]
        if not isinstance(v, str):
            raise JetsonConfigError(f"kiosk.mavproxy_master must be str, got {type(v).__name__}")
        kwargs["mavproxy_master"] = v
    if "mavproxy_outputs" in raw:
        v = raw["mavproxy_outputs"]
        if not isinstance(v, list) or not all(isinstance(i, str) for i in v):
            raise JetsonConfigError("kiosk.mavproxy_outputs must be a list of strings")
        kwargs["mavproxy_outputs"] = v
    if "vslam_socket" in raw:
        v = raw["vslam_socket"]
        if not isinstance(v, str):
            raise JetsonConfigError(f"kiosk.vslam_socket must be str, got {type(v).__name__}")
        kwargs["vslam_socket"] = v
    if "refresh_hz" in raw:
        v = raw["refresh_hz"]
        if not isinstance(v, int) or v <= 0:
            raise JetsonConfigError(f"kiosk.refresh_hz must be a positive integer, got {v!r}")
        kwargs["refresh_hz"] = v
    if "heartbeat_staleness_s" in raw:
        v = raw["heartbeat_staleness_s"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise JetsonConfigError(
                f"kiosk.heartbeat_staleness_s must be a positive number, got {v!r}"
            )
        kwargs["heartbeat_staleness_s"] = float(v)
    if "service_check_units" in raw:
        v = raw["service_check_units"]
        if not isinstance(v, list) or not all(isinstance(i, str) for i in v):
            raise JetsonConfigError("kiosk.service_check_units must be a list of strings")
        kwargs["service_check_units"] = v
    return KioskConfig(**kwargs)


def _coerce(raw: dict[str, Any]) -> JetsonConfig:
    if not isinstance(raw, dict):
        raise JetsonConfigError(f"top-level YAML must be a mapping, got {type(raw).__name__}")
    known = {"log_dir", "oakd_required", "health_interval_s", "service_user_level", "kiosk"}
    extra = {k: v for k, v in raw.items() if k not in known}
    log_dir_raw = raw.get("log_dir")
    log_dir: Path | None
    if log_dir_raw is None:
        log_dir = None
    elif isinstance(log_dir_raw, str):
        log_dir = Path(log_dir_raw)
    else:
        raise JetsonConfigError(f"log_dir must be a string path, got {type(log_dir_raw).__name__}")
    oakd_required = raw.get("oakd_required", False)
    if not isinstance(oakd_required, bool):
        raise JetsonConfigError(
            f"oakd_required must be bool, got {type(oakd_required).__name__}"
        )
    health_interval_s = raw.get("health_interval_s", 60)
    if not isinstance(health_interval_s, int) or health_interval_s <= 0:
        raise JetsonConfigError(
            f"health_interval_s must be a positive integer, got {health_interval_s!r}"
        )
    service_user_level = raw.get("service_user_level", False)
    if not isinstance(service_user_level, bool):
        raise JetsonConfigError(
            f"service_user_level must be bool, got {type(service_user_level).__name__}"
        )
    kiosk = _coerce_kiosk(raw.get("kiosk"))
    return JetsonConfig(
        log_dir=log_dir,
        oakd_required=oakd_required,
        health_interval_s=health_interval_s,
        service_user_level=service_user_level,
        kiosk=kiosk,
        extra=extra,
    )


def load_jetson_config(path: Path | None = None) -> JetsonConfig:
    """Load Jetson config from `path` (default: `DEFAULT_JETSON_CONFIG_PATH`).

    Returns defaults if the file does not exist.
    """
    target = path or DEFAULT_JETSON_CONFIG_PATH
    if not target.exists():
        return JetsonConfig()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise JetsonConfigError(f"failed to parse {target}: {exc}") from exc
    return _coerce(raw)


def save_jetson_config(config: JetsonConfig, path: Path | None = None) -> Path:
    target = path or DEFAULT_JETSON_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.to_dict()
    payload.update(config.extra)
    payload.pop("extra", None)
    target.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return target
