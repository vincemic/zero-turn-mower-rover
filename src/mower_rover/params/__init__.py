"""Parameter snapshot, diff, and apply for ArduPilot Rover (Phase 3).

Public surface:
- `ParamSet`        — name → float dict with stable ordering and YAML/JSON I/O.
- `load_baseline()` — return the shipped Z254 baseline as a `ParamSet`.
- `fetch_params()`  — read every param from a live autopilot via MAVLink.
- `apply_params()`  — write a `ParamSet` to a live autopilot, with verify.
- `diff_params()`   — structured diff between two `ParamSet`s.
"""

from __future__ import annotations

from mower_rover.params.baseline import BASELINE_PATH, load_baseline
from mower_rover.params.diff import ParamDiff, diff_params, render_diff
from mower_rover.params.io import ParamSet, load_param_file, write_json_snapshot
from mower_rover.params.mav import apply_params, fetch_params

__all__ = [
    "BASELINE_PATH",
    "ParamDiff",
    "ParamSet",
    "apply_params",
    "diff_params",
    "fetch_params",
    "load_baseline",
    "load_param_file",
    "render_diff",
    "write_json_snapshot",
]
