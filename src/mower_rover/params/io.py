"""Param set I/O — YAML (human-edited inputs) and JSON (machine snapshots).

A `ParamSet` is an order-preserving mapping of `name -> float`. Names are
normalized to upper-case ASCII; values are stored as Python floats so that
round-tripping through MAVLink (`MAV_PARAM_TYPE_REAL32`) is lossless within
single-precision. Integer-valued params keep an integer-looking repr in YAML.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def _normalize_name(name: str) -> str:
    n = name.strip().upper()
    if not n or any(c.isspace() for c in n):
        raise ValueError(f"invalid param name: {name!r}")
    return n


@dataclass(frozen=True)
class ParamSet:
    """Ordered, name-keyed param container."""

    values: dict[str, float]

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, float | int]]) -> ParamSet:
        out: dict[str, float] = {}
        for name, value in pairs:
            out[_normalize_name(name)] = float(value)
        return cls(values=out)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, float | int]) -> ParamSet:
        return cls.from_pairs(mapping.items())

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and _normalize_name(name) in self.values

    def __getitem__(self, name: str) -> float:
        return self.values[_normalize_name(name)]

    def get(self, name: str, default: float | None = None) -> float | None:
        return self.values.get(_normalize_name(name), default)

    def names(self) -> list[str]:
        return sorted(self.values)

    def as_sorted_dict(self) -> dict[str, float]:
        return {k: self.values[k] for k in sorted(self.values)}


def load_param_file(path: Path) -> ParamSet:
    """Load a `ParamSet` from a YAML file or an ArduPilot `.parm`/`.params` file.

    YAML format (preferred): top-level mapping of `NAME: value`.
    ArduPilot format: lines of `NAME,VALUE` or `NAME<whitespace>VALUE`;
    `#` and `//` start comments.
    """
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml", ".json"}:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected mapping at top level, got {type(data).__name__}")
        return ParamSet.from_mapping(data)
    return _parse_parm_text(text)


def _parse_parm_text(text: str) -> ParamSet:
    pairs: list[tuple[str, float]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split("//", 1)[0].strip()
        if not line:
            continue
        if "," in line:
            name, _, value = line.partition(",")
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise ValueError(f"unparseable param line: {raw!r}")
            name, value = parts
        pairs.append((name.strip(), float(value.strip())))
    return ParamSet.from_pairs(pairs)


def write_json_snapshot(
    params: ParamSet,
    path: Path,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Write a JSON snapshot file with metadata and sorted params.

    Schema:
        {
          "schema": "mower-rover.params.snapshot.v1",
          "captured_at": "<ISO 8601 UTC>",
          "metadata": {...},
          "params": { "NAME": value, ... }   # sorted
        }
    """
    payload: dict[str, Any] = {
        "schema": "mower-rover.params.snapshot.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "metadata": dict(metadata or {}),
        "params": params.as_sorted_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_json_snapshot(path: Path) -> ParamSet:
    """Read a JSON snapshot written by `write_json_snapshot`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "params" not in payload:
        raise ValueError(f"{path}: not a mower-rover param snapshot")
    return ParamSet.from_mapping(payload["params"])


__all__ = [
    "ParamSet",
    "load_json_snapshot",
    "load_param_file",
    "write_json_snapshot",
]
