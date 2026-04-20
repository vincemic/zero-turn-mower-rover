"""Shipped Z254 baseline parameter set (Phase 3, research §Consolidated Baseline)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from mower_rover.params.io import ParamSet, load_param_file

_PACKAGE = "mower_rover.params.data"
_FILENAME = "z254_baseline.yaml"


def _resolve_baseline_path() -> Path:
    # `as_file` is the cross-version-safe way to materialize a packaged resource.
    with resources.as_file(resources.files(_PACKAGE).joinpath(_FILENAME)) as p:
        return Path(p)


BASELINE_PATH: Path = _resolve_baseline_path()


def load_baseline() -> ParamSet:
    """Return the shipped Z254 baseline as a `ParamSet`."""
    return load_param_file(BASELINE_PATH)


__all__ = ["BASELINE_PATH", "load_baseline"]
