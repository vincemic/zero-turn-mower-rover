from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from mower_rover.params.baseline import BASELINE_PATH, load_baseline
from mower_rover.params.diff import diff_params
from mower_rover.params.io import (
    ParamSet,
    load_json_snapshot,
    load_param_file,
    write_json_snapshot,
)


def test_baseline_loads_and_has_required_skid_steer_pins() -> None:
    params = load_baseline()
    assert params["SERVO1_FUNCTION"] == 73
    assert params["SERVO3_FUNCTION"] == 74
    assert params["EK3_SRC1_YAW"] == 2
    assert params["COMPASS_USE"] == 0
    # Phase 7 corrections present.
    assert params["FS_THR_ENABLE"] == 0
    assert params["RC_PROTOCOLS"] == 0
    assert params["FS_OPTIONS"] == 1
    assert params["FENCE_ACTION"] == 2
    # Mosaic-H driver, single GPS.
    assert params["GPS1_TYPE"] == 10
    assert params["GPS2_TYPE"] == 0


def test_baseline_path_is_packaged_resource() -> None:
    assert BASELINE_PATH.exists()
    assert BASELINE_PATH.suffix == ".yaml"


def test_paramset_normalizes_names() -> None:
    p = ParamSet.from_pairs([("  foo_bar ", 1), ("BAZ", 2.5)])
    assert p["foo_bar"] == 1.0
    assert p["BAZ"] == 2.5
    assert "FOO_BAR" in p
    assert p.names() == ["BAZ", "FOO_BAR"]


def test_paramset_rejects_invalid_names() -> None:
    with pytest.raises(ValueError):
        ParamSet.from_pairs([("with space", 1)])
    with pytest.raises(ValueError):
        ParamSet.from_pairs([("", 1)])


def test_load_param_file_yaml(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("FOO: 1\nBAR: 2.5\n", encoding="utf-8")
    s = load_param_file(p)
    assert s["FOO"] == 1.0 and s["BAR"] == 2.5


def test_load_param_file_parm(tmp_path: Path) -> None:
    p = tmp_path / "x.parm"
    p.write_text(
        "# comment\nFOO,1\nBAR  2.5\n// another comment\nBAZ\t-3\n", encoding="utf-8"
    )
    s = load_param_file(p)
    assert s["FOO"] == 1.0
    assert s["BAR"] == 2.5
    assert s["BAZ"] == -3.0


def test_snapshot_roundtrip(tmp_path: Path) -> None:
    src = ParamSet.from_pairs([("A", 1), ("B", 2.5), ("C", -3)])
    snap = tmp_path / "snap.json"
    write_json_snapshot(src, snap, metadata={"endpoint": "udp:test"})
    loaded = load_json_snapshot(snap)
    assert loaded.as_sorted_dict() == src.as_sorted_dict()
    payload = json.loads(snap.read_text(encoding="utf-8"))
    assert payload["schema"] == "mower-rover.params.snapshot.v1"
    assert payload["metadata"]["endpoint"] == "udp:test"
    assert "captured_at" in payload


def test_diff_added_removed_changed_unchanged() -> None:
    old = ParamSet.from_pairs([("KEEP", 1), ("DROP", 2), ("MOVE", 3.0)])
    new = ParamSet.from_pairs([("KEEP", 1), ("MOVE", 3.5), ("ADD", 9)])
    d = diff_params(old, new)
    assert {c.name for c in d.added} == {"ADD"}
    assert {c.name for c in d.removed} == {"DROP"}
    assert {c.name for c in d.changed} == {"MOVE"}
    assert not d.is_empty


def test_diff_tolerance_treats_float32_noise_as_equal() -> None:
    old = ParamSet.from_pairs([("X", 0.20000000001)])
    new = ParamSet.from_pairs([("X", 0.20000000002)])
    assert diff_params(old, new).is_empty


def test_baseline_yaml_is_valid_yaml() -> None:
    data = yaml.safe_load(BASELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert all(isinstance(k, str) for k in data)
