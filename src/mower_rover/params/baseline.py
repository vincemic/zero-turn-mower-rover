"""Shipped Z254 baseline parameter set (Phase 3, research §Consolidated Baseline)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from mower_rover.params.io import ParamSet, load_param_file

_PACKAGE = "mower_rover.params.data"
_BASELINE_FILENAME = "z254_baseline.yaml"
_SAFETY_DEFAULTS_FILENAME = "safety-defaults.yaml"


def _resolve_data_path(filename: str) -> Path:
    # `as_file` is the cross-version-safe way to materialize a packaged resource.
    with resources.as_file(resources.files(_PACKAGE).joinpath(filename)) as p:
        return Path(p)


BASELINE_PATH: Path = _resolve_data_path(_BASELINE_FILENAME)
SAFETY_DEFAULTS_PATH: Path = _resolve_data_path(_SAFETY_DEFAULTS_FILENAME)


PROFILES: dict[str, Path] = {
    "baseline": BASELINE_PATH,
    "safety-defaults": SAFETY_DEFAULTS_PATH,
}


def load_baseline() -> ParamSet:
    """Return the shipped Z254 baseline as a `ParamSet`."""
    return load_param_file(BASELINE_PATH)


def load_profile(name: str) -> ParamSet:
    """Load a named profile. Raises KeyError with a helpful message if unknown."""
    try:
        path = PROFILES[name]
    except KeyError as e:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown profile {name!r}; known: {known}") from e
    return load_param_file(path)


__all__ = [
    "BASELINE_PATH",
    "PROFILES",
    "SAFETY_DEFAULTS_PATH",
    "load_baseline",
    "load_profile",
]
