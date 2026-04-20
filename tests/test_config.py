from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mower_rover.config.jetson import (
    JetsonConfig,
    JetsonConfigError,
    load_jetson_config,
    save_jetson_config,
)
from mower_rover.config.laptop import (
    JetsonEndpoint,
    LaptopConfig,
    LaptopConfigError,
    load_laptop_config,
    save_laptop_config,
)


def test_jetson_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_jetson_config(tmp_path / "nope.yaml")
    assert cfg == JetsonConfig()


def test_jetson_config_round_trip(tmp_path: Path) -> None:
    src = JetsonConfig(log_dir=Path("/var/log/mower"), oakd_required=True)
    target = tmp_path / "jetson.yaml"
    save_jetson_config(src, target)
    assert target.exists()
    back = load_jetson_config(target)
    assert back.log_dir == Path("/var/log/mower")
    assert back.oakd_required is True


def test_jetson_config_preserves_unknown_keys(tmp_path: Path) -> None:
    target = tmp_path / "jetson.yaml"
    target.write_text(
        yaml.safe_dump({"oakd_required": False, "future_field": 42}), encoding="utf-8"
    )
    cfg = load_jetson_config(target)
    assert cfg.extra == {"future_field": 42}


def test_jetson_config_rejects_bad_types(tmp_path: Path) -> None:
    target = tmp_path / "jetson.yaml"
    target.write_text(yaml.safe_dump({"oakd_required": "yes"}), encoding="utf-8")
    with pytest.raises(JetsonConfigError):
        load_jetson_config(target)


def test_jetson_config_rejects_non_mapping(tmp_path: Path) -> None:
    target = tmp_path / "jetson.yaml"
    target.write_text(yaml.safe_dump([1, 2, 3]), encoding="utf-8")
    with pytest.raises(JetsonConfigError):
        load_jetson_config(target)


def test_laptop_config_missing_file_returns_empty(tmp_path: Path) -> None:
    cfg = load_laptop_config(tmp_path / "nope.yaml")
    assert cfg == LaptopConfig()


def test_laptop_config_round_trip(tmp_path: Path) -> None:
    endpoint = JetsonEndpoint(host="10.0.0.42", user="mower", port=2222, key_path=Path("/k/id"))
    target = tmp_path / "laptop.yaml"
    save_laptop_config(LaptopConfig(jetson=endpoint), target)
    back = load_laptop_config(target).jetson
    assert back is not None
    assert back.host == "10.0.0.42"
    assert back.user == "mower"
    assert back.port == 2222
    assert back.key_path == Path("/k/id")


def test_laptop_config_requires_host_and_user(tmp_path: Path) -> None:
    target = tmp_path / "laptop.yaml"
    target.write_text(yaml.safe_dump({"jetson": {"host": "h"}}), encoding="utf-8")
    with pytest.raises(LaptopConfigError):
        load_laptop_config(target)


def test_laptop_config_rejects_bad_port(tmp_path: Path) -> None:
    target = tmp_path / "laptop.yaml"
    target.write_text(
        yaml.safe_dump({"jetson": {"host": "h", "user": "u", "port": 99999}}),
        encoding="utf-8",
    )
    with pytest.raises(LaptopConfigError):
        load_laptop_config(target)
