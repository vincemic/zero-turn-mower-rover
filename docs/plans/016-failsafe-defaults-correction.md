---
id: "016"
type: implementation-plan
title: "Failsafe Defaults Correction (FENCE/EKF/GCS/Arming)"
status: ✅ Complete (Phases 1–5); Phase 6 operator-scheduled
created: 2026-05-04
updated: 2026-05-04
owner: pch-coder
version: v3.0
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-04 | pch-planner | Initial skeleton |
| v1.1 | 2026-05-04 | pch-planner | Q1 — profile strategy (option C) |
| v1.2 | 2026-05-04 | pch-planner | Q2 — ARMING_CHECK bitmask 13816 (option B) |
| v1.3 | 2026-05-04 | pch-planner | Q3 — FS_GCS_ENABLE=1 / 5 s timeout (option A) |
| v1.4 | 2026-05-04 | pch-planner | Q4 — PROFILES dict resolver (option B) |
| v1.5 | 2026-05-04 | pch-planner | Q5 — SITL: round-trip + fence + GCS triggers (option E) |
| v1.6 | 2026-05-04 | pch-planner | Q6 — procedure-doc + operator-scheduled live apply (hybrid A+C) |
| v2.0 | 2026-05-04 | pch-planner | Holistic review + full execution plan complete |
| v2.1 | 2026-05-04 | pch-plan-reviewer | Review Q1 — `sitl_connection` fixture (option B); added Review Session Log |
| v2.2 | 2026-05-04 | pch-plan-reviewer | Review Q2 — dropped "verification report" language (option A); rely on existing `--snapshot-dir` + Phase 5 runbook for verification |
| v2.3 | 2026-05-04 | pch-plan-reviewer | Review Q3 — FR-3 magic-string only (option A); added Complexity Assessment + Review Summary; status → Ready for Implementation |
| v3.0 | 2026-05-04 | pch-coder | Phases 1–5 implemented; all unit and CLI tests passing; Phase 6 (live apply) remains operator-scheduled |

## Introduction

Implements **Phase 1 of [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md)** — correcting four ArduPilot failsafe parameters that are currently misconfigured for a zero-turn mower (`FENCE_ACTION`, `FS_EKF_ACTION`, `FENCE_ENABLE`, `ARMING_CHECK`, and a decision on `FS_GCS_ENABLE`). RTL on a skid-steer mower drives in a straight line through obstacles; Hold is the only safe failsafe action. This plan delivers a curated `safety-defaults` parameter profile, a SITL verification test, an applied-and-snapshotted `docs/config/mower.param` re-dump, and a small CLI ergonomics addition (`mower params apply --profile`) so the operator does not have to remember a path.

This plan **does not** introduce new tooling — it uses the existing `mower params apply` machinery from [Plan 001](001-param-apply-snapshot-restore.md).

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 3  
**Last Updated:** 2026-05-04

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | SITL fixture pattern (Critical-1): plan referenced nonexistent `sitl_rover_skid` | correctness | Option B — add `sitl_connection` fixture in `tests/conftest.py` that yields an open `pymavlink` link via `open_link(ConnectionConfig(...))` consumed from `sitl_endpoint` | Tech Design SITL Test Module + Phase 3 steps 3.1, 3.2, 3.3, 3.4, 3.5 updated; new step 3.0 added for the fixture |
| 2 | Verification report artifact (Major-1): FR-4 / step 2.2 referenced a nonexistent report | correctness | Option A — drop the artifact; use existing `--snapshot-dir` pre-apply snapshot + Phase 5 runbook's post-apply snapshot+diff for verification | FR-4 reworded; step 2.2 reworded to log `source` and rely on existing structured-log line |
| 3 | FR-3 diff-command surface ambiguity (Major-2) | clarity | Option A — magic-string only; `_load_any` extended to accept any `PROFILES` key; no `--profile` flag on `diff` | FR-3 reworded to one mechanism |

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Profile strategy & naming | C — Ship `safety-defaults.yaml` now; add follow-up task to sync the same keys into `z254_baseline.yaml` | Smallest-blast-radius live apply (only the corrected keys are diffed/applied), while explicitly preventing silent drift between the two yamls. The baseline yaml retains its `⚠️ SUPERSEDED` RC block until separate re-research lands. |
| 2 | `ARMING_CHECK` bitmask | B — `13816` = GPS(8) + INS(16) + Params(32) + RC(64) + BoardV(128) + Batt(256) + Logging(1024) + GPSConfig(4096) + System(8192) | Asserts research-019-mandated minimums plus parameter integrity, GPS config sanity, board health, and logging. Compass and Safety-switch bits omitted (hardware-incompatible). VisualOdom bit omitted (VSLAM is soft-real-time per Phase 3). Mission bit omitted (would block Manual-mode shakedowns). |
| 3 | `FS_GCS_ENABLE` decision | A — Enable with 5 s timeout (`FS_GCS_ENABLE=1`, `FS_GCS_TIMEOUT=5`); also assert `FS_ACTION=2` on the live Pixhawk during execution | Asymmetric cost: spurious Hold is recoverable in seconds; too-long timeout leaves a moving 600+ lb mower autonomous after real link loss. 5 s already matches `z254_baseline.yaml`, simplifying the Q1 sync follow-up. Loosen later via single-param apply if field evidence shows spurious trips. |
| 4 | `--profile` resolver | B — Hardcoded `PROFILES = {"baseline": ..., "safety-defaults": ...}` dict in `params/baseline.py`; new `--profile` Typer option mutually exclusive with `params_file` | Smallest change that retires "operator must know a path" friction. Curated single-vehicle toolkit per copilot-instructions — auto-discovery is wrong. `pipx`-install-safe via existing `Path(__file__).parent` pattern. Adding profiles later = 1-line dict edit. |
| 5 | SITL test scope | E — Round-trip param assertion + fence-breach → Hold + heartbeat-dropout → Hold (skip EKF-failsafe simulation) | Round-trip alone proves params landed but not that the autopilot acts on them — the entire point of this plan is "Hold, not RTL." Fence-breach is well-trodden in ArduPilot SITL; heartbeat-dropout is trivial (stop sending HEARTBEAT, wait 5 s). EKF simulation is brittle in SITL — defer to field. All marked `@pytest.mark.sitl`; plumbing-validation, not tuning. |
| 6 | Live-apply & re-snapshot | A+C hybrid — Plan delivers code + procedure doc as a closeable PR; live apply tracked as an explicit follow-up item (not a gate on plan completion) | Code-PR is reviewable on its own merits (profile YAML, `--profile` resolver, SITL tests, procedure runbook). Live apply requires hardware access and is the operator's call to schedule. Follow-up item is recorded in this plan's Execution Plan as a separate phase marked "🟡 operator-scheduled" so it does not get lost, and research 019 Phase 1 status update is part of that follow-up. Avoids B's permanent CLI surface for a one-shot action and avoids D's review/merge dependency on hardware availability. |

## Holistic Review

### Decision Interactions

- **Q1 + Q3 + Q4** form a coherent low-friction story: operator runs `mower params apply --profile safety-defaults`, only the corrected keys hit the live Pixhawk, and the chosen `FS_GCS_TIMEOUT=5` matches the existing `z254_baseline.yaml`, simplifying the Q1-mandated baseline-sync follow-up to a no-value-conflict edit.
- **Q2 + Q5** require the SITL fixture to provide a synthetic GPS lock so the rover can arm in Auto (with `ARMING_CHECK=13816` including bit `8`) before the fence-breach test drives it. The existing `tests/test_params_sitl.py` pattern already arranges this — verify in the test fixture, not a new requirement.
- **Q3 + Q5** the heartbeat-dropout SITL case directly validates Q3's decision (`FS_GCS_ENABLE=1`, 5 s timeout → `HOLD`).
- **Q6 + research 019 Phase 1**: research doc is the source of truth for hardware state; this plan is the source of truth for tooling state. The follow-up live-apply task closes both — research 019 Phase 1 status moves to "✅ Complete (applied YYYY-MM-DD)" only after the operator runs the procedure.

### Architectural Considerations

- **No new abstractions, no new dependencies.** Reuses Plan 001 machinery (`apply_params`, `fetch_params`, snapshot/diff, `requires_confirmation`).
- **Profile resolution stays in the package** — `Path(__file__).parent / "data"` works identically under editable install, `pipx`, and `uv tool install` because YAML files are bundled via `pyproject.toml`'s package-data config (already correct for `z254_baseline.yaml`).
- **The procedure runbook is the only operator-facing surface besides the `--profile` flag.** No CLI macro, no one-shot wrapper. Implementation discipline preserved.
- **VSLAM is intentionally NOT in the arming check** (bit `262144` off). Per research 019 Phase 3, VSLAM must be allowed to degrade without disarming or RTLing — this plan's failsafe-Hold defaults are precisely what makes that safe.

### Trade-offs Accepted

- **Two yamls temporarily diverge** on `FENCE_ENABLE` and `ARMING_CHECK` until the Q1 baseline-sync follow-up task lands. Mitigated by tracking it as a named task in this plan's execution section.
- **Live apply is not gated on this plan merging.** Mitigated by the explicit follow-up phase (operator-scheduled). The code-PR is fully reviewable without it.
- **EKF-failsafe behavior validated only by param presence**, not end-to-end SITL trigger. Mitigated by field validation discipline; flagged in Open Questions for the field-test session.

### Risks Acknowledged

See Risks section below. Most significant: **operator misapplies on the wrong endpoint** (e.g., still pointed at SITL UDP) — mitigated by the procedure doc's pre-flight checklist explicitly listing the live-Pixhawk endpoint and by the existing diff-then-confirm flow surfacing the unexpected param values from a SITL instance vs. the live dump.

## Overview

### Problem Statement

The 2026-05-01 param dump ([docs/config/mower.param](../config/mower.param)) shows the live Pixhawk has:

| Param | Live | Required | Why wrong |
|-------|------|----------|-----------|
| `FENCE_ACTION` | `1` (RTL) | `2` (Hold) | RTL on skid-steer = straight-line through obstacles |
| `FS_EKF_ACTION` | `1` (RTL) | `2` (Hold) | EKF failure correlates with GNSS loss — RTL is exactly when not to trust position |
| `FENCE_ENABLE` | `0` | `1` | Geofence is the primary backstop against runaway |
| `ARMING_CHECK` | `0` (all disabled) | curated bitmask | Currently nothing blocks arming — GPS-less, RC-less arming is permitted |
| `FS_GCS_ENABLE` | `0` | _operator decision (this plan)_ | GCS link loss currently silent |

The `mower params apply` snapshot/diff tooling exists. This is its use case.

### Objectives

1. Author a curated `safety-defaults` profile under `src/mower_rover/params/data/`.
2. Add a `--profile <name>` resolver to `mower params apply` so profiles ship with the wheel and don't depend on cwd.
3. Add SITL test(s) verifying the post-conditions (and failsafe behaviour where tractable in SITL).
4. Apply on the live Pixhawk and re-dump `docs/config/mower.param`.
5. Update [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md) Phase 1 status to "✅ Complete (applied 2026-05-XX)".

## Requirements

### Functional

- **FR-1** A new YAML profile `safety-defaults.yaml` exists under `src/mower_rover/params/data/` containing exactly the keys: `FENCE_ENABLE`, `FENCE_ACTION`, `FS_EKF_ACTION`, `FS_ACTION`, `FS_GCS_ENABLE`, `FS_GCS_TIMEOUT`, `ARMING_CHECK`. Each line is annotated with a comment giving rationale and a reference to research 019.
- **FR-2** `mower params apply` accepts a new `--profile <name>` option that resolves against a `PROFILES` dict in `mower_rover.params.baseline`. `--profile` and the positional `params_file` argument are mutually exclusive; supplying neither or both raises a `typer.BadParameter`.
- **FR-3** `mower params diff` accepts any key from `PROFILES` as a positional argument (mirroring the existing `baseline` magic-string), e.g. `mower params diff safety-defaults snapshot.json`. No new `--profile` flag is added to `diff` — the magic-string approach is the single supported mechanism. The `--profile` flag remains exclusive to `apply`, where its single-argument semantics are unambiguous.
- **FR-4** `mower params apply --profile safety-defaults` applies the seven keys. When `--snapshot-dir` is supplied, the existing pre-apply JSON snapshot path from Plan 001 is written. No new "verification report" artifact is introduced — post-apply verification is handled by the Phase 5 procedure runbook (separate post-apply snapshot + `mower params diff`) and by the Phase 3 SITL round-trip test (FR-5).
- **FR-5** Running `mower params apply --profile safety-defaults` against a SITL rover-skid instance results in all seven values being readable back via `fetch_params` with bit-exact equality.
- **FR-6** With `safety-defaults` applied in SITL, breaching a small test geofence in Auto mode causes the vehicle to enter `HOLD`, not `RTL`.
- **FR-7** With `safety-defaults` applied in SITL, ceasing MAVLink heartbeats for `FS_GCS_TIMEOUT + 1` seconds causes the vehicle to enter `HOLD`.
- **FR-8** A procedure runbook at `docs/procedures/006-apply-safety-defaults.md` documents the live-Pixhawk apply, including pre-flight checklist, exact CLI invocation, expected diff summary, snapshot location, and rollback command.

### Non-Functional

- NFR-1 Safety: actuator-touching command path; must use existing safety primitive (confirmation + dry-run + safe-stop).
- NFR-4 Structured logging: profile resolution, diff, and apply emit JSON log lines with correlation IDs.
- NFR-5 Snapshots: pre-apply snapshot mandatory; round-trip-verifiable.
- C-10 Field-offline: no network dependency.

### Out of Scope

- Phase 2 (RPM1 + Lua blade-clutch interlock) — separate plan.
- Phase 3 (VSLAM covariance gate) — depends on this plan but is a separate plan.
- Re-research of the `z254_baseline.yaml` superseded RC params — tracked separately.
- Tuning (PIDs, `CRUISE_*`, servo endpoints) — field-only per copilot-instructions.

## Technical Design

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Param profile YAML
    location: "src/mower_rover/params/data/z254_baseline.yaml"
    usage: New safety-defaults.yaml will follow this format (top-of-file comment header, KEY: value lines, inline `# comment` annotations)
  - pattern: Apply CLI command
    location: "src/mower_rover/cli/params.py::apply_command"
    usage: Extend with `--profile` option that resolves to packaged data dir
  - pattern: Baseline loader
    location: "src/mower_rover/params/baseline.py::BASELINE_PATH, load_baseline"
    usage: Generalize to `load_named_profile(name)` or add a parallel resolver
  - pattern: SITL test fixtures
    location: "tests/test_params_sitl.py"
    usage: New test file follows the same fixture pattern (rover-skid frame, --instance for xdist isolation)
  - pattern: Safety confirmation
    location: "src/mower_rover/safety/confirm.py"
    usage: Reused as-is via @requires_confirmation
```

### Profile Contents

New file [src/mower_rover/params/data/safety-defaults.yaml](src/mower_rover/params/data/safety-defaults.yaml):

```yaml
# safety-defaults.yaml — Failsafe corrections per docs/research/019.
#
# Targeted, minimal-blast-radius profile. Apply to the live Pixhawk via:
#   mower params apply --profile safety-defaults
#
# Each value is independently justified; do not edit without re-reading
# docs/research/019-current-architecture-fragility.md Phase 1 and the
# Planning Session Log of docs/plans/016-failsafe-defaults-correction.md.

# --- Geofence ---------------------------------------------------------------
FENCE_ENABLE: 1               # Geofence on; primary backstop against runaway
FENCE_ACTION: 2               # Hold on breach (NOT RTL — RTL = straight line through obstacles)

# --- EKF failsafe -----------------------------------------------------------
FS_EKF_ACTION: 2              # Hold on EKF failure (RTL = exactly when not to trust position)

# --- General failsafe action -----------------------------------------------
FS_ACTION: 2                  # Hold for any failsafe (asserted explicitly per Q3)

# --- GCS heartbeat failsafe ------------------------------------------------
FS_GCS_ENABLE: 1              # Hold if MAVLink heartbeat lost (decision Q3)
FS_GCS_TIMEOUT: 5             # seconds without heartbeat before action

# --- Arming checks ---------------------------------------------------------
# Bitmask 13816 = GPS(8) + INS(16) + Params(32) + RC(64) + BoardV(128)
#                + Batt(256) + Logging(1024) + GPSConfig(4096) + System(8192)
# Compass and Safety-switch bits omitted (hardware-incompatible).
# VisualOdom bit omitted (VSLAM is soft-real-time per research 019 Phase 3).
# Mission bit omitted (would block Manual-mode shakedowns).
ARMING_CHECK: 13816
```

### Code Changes

**[src/mower_rover/params/baseline.py](src/mower_rover/params/baseline.py)** — extend with a `PROFILES` registry and a resolver:

```python
_SAFETY_DEFAULTS_FILENAME = "safety-defaults.yaml"

def _resolve_data_path(filename: str) -> Path:
    with resources.as_file(resources.files(_PACKAGE).joinpath(filename)) as p:
        return Path(p)

SAFETY_DEFAULTS_PATH: Path = _resolve_data_path(_SAFETY_DEFAULTS_FILENAME)

PROFILES: dict[str, Path] = {
    "baseline": BASELINE_PATH,
    "safety-defaults": SAFETY_DEFAULTS_PATH,
}

def load_profile(name: str) -> ParamSet:
    """Load a named profile. Raises KeyError with a helpful message if unknown."""
    try:
        path = PROFILES[name]
    except KeyError as e:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown profile {name!r}; known: {known}") from e
    return load_param_file(path)

__all__ = ["BASELINE_PATH", "SAFETY_DEFAULTS_PATH", "PROFILES",
           "load_baseline", "load_profile"]
```

Refactor `_resolve_baseline_path` to call `_resolve_data_path("z254_baseline.yaml")` for DRY.

**[src/mower_rover/cli/params.py](src/mower_rover/cli/params.py)** — add `--profile` to `apply_command` and `diff_command`:

```python
# In apply_command signature, add:
profile: str | None = typer.Option(
    None, "--profile",
    help="Named profile (e.g. 'safety-defaults', 'baseline'). Mutually exclusive with PARAMS_FILE.",
),

# Make params_file optional (Argument(None, ...)).
# Validate at start of body:
if (params_file is None) == (profile is None):
    raise typer.BadParameter(
        "exactly one of PARAMS_FILE or --profile must be supplied"
    )
desired = load_profile(profile) if profile else _load_any(params_file)
source_label = f"profile:{profile}" if profile else str(params_file)
```

`diff_command` gets the same treatment OR the existing magic-string handling in `_load_any` is extended to accept any `PROFILES` key. Simpler: extend `_load_any` to consult `PROFILES` before treating the input as a path:

```python
def _load_any(path: Path) -> ParamSet:
    s = str(path)
    if s in PROFILES:
        return load_profile(s)
    # ... existing logic unchanged
```

This makes `mower params diff safety-defaults snapshot.json` work with no new flag — consistent with existing `baseline` behaviour. The `--profile` flag on `apply` remains the discoverable, documented surface.

**Help text**: `apply` and `diff` `--help` should list known profiles via `PROFILES.keys()`. Implement by setting `help=...` with a callable or by enumerating in a Typer callback.

### SITL Test Module

**Fixture model (per Review Q1):** existing `sitl_endpoint` fixture (session-scoped, yields a `udp:127.0.0.1:<port>` string) is consumed by a new `sitl_connection` fixture in `tests/conftest.py` that opens a `pymavlink` link and yields it for the duration of a test:

```python
# tests/conftest.py — new fixture
@pytest.fixture()
def sitl_connection(sitl_endpoint: str) -> Iterator["mavutil.mavfile"]:
    from mower_rover.mavlink.connection import ConnectionConfig, open_link
    with open_link(ConnectionConfig(endpoint=sitl_endpoint, baud=57600)) as conn:
        yield conn
```

New file `tests/test_failsafe_defaults_sitl.py`:

```python
import pytest
from typer.testing import CliRunner

from mower_rover.cli.laptop import app
from mower_rover.params.baseline import load_profile
from mower_rover.params.mav import apply_params, fetch_params

pytestmark = pytest.mark.sitl

SAFETY_KEYS = ("FENCE_ENABLE", "FENCE_ACTION", "FS_EKF_ACTION",
               "FS_ACTION", "FS_GCS_ENABLE", "FS_GCS_TIMEOUT", "ARMING_CHECK")

def test_safety_defaults_round_trip(sitl_endpoint, sitl_connection):
    """FR-5: apply via CLI; fetch back via direct link; bit-exact match."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["params", "apply", "--profile", "safety-defaults",
         "--port", sitl_endpoint, "--yes"],
    )
    assert result.exit_code == 0, result.stdout
    after = fetch_params(sitl_connection)
    desired = load_profile("safety-defaults")
    for k in SAFETY_KEYS:
        assert after[k] == desired[k], f"{k}: {after[k]!r} != {desired[k]!r}"

def test_fence_breach_enters_hold(sitl_endpoint, sitl_connection):
    """FR-6: with safety-defaults applied, fence breach in Auto -> HOLD."""
    # Apply profile via CLI for parity with operator path; then use
    # `sitl_connection` to upload a small fence around home, arm in
    # Auto, command guided velocity outward, poll HEARTBEAT.custom_mode
    # until == ROVER_MODE_HOLD or 10 s timeout.
    ...

def test_gcs_heartbeat_loss_enters_hold(sitl_endpoint, sitl_connection):
    """FR-7: stop heartbeats for FS_GCS_TIMEOUT+1s -> HOLD."""
    # Apply profile via CLI; arm via `sitl_connection`; stop the
    # heartbeat thread on the connection; wait FS_GCS_TIMEOUT + 1 s;
    # poll mode and assert HOLD.
    ...
```

The two trigger tests need helpers (fence upload, heartbeat-control) — design as small additions to `tests/conftest.py` if not already present, not a new fixture module.

### Procedure Runbook

New file `docs/procedures/006-apply-safety-defaults.md` — sections:

1. **Purpose** — one paragraph; reference research 019 Phase 1 and this plan.
2. **Pre-flight checklist** — mower on stand OR ignition off, USB tether present, no autonomous mission armed, laptop on a stable power source, current `docs/config/mower.param` committed.
3. **Step 1: Snapshot current state** — `mower params snapshot snapshots/params/pre-safety-defaults-$(date +%Y%m%dT%H%M%SZ).json --port <live-pixhawk-endpoint>`.
4. **Step 2: Dry-run apply** — `mower params apply --profile safety-defaults --port <endpoint> --dry-run`. Operator visually confirms the diff matches the expected 7-key change.
5. **Step 3: Live apply** — same command without `--dry-run`. Confirmation prompt.
6. **Step 4: Verify** — `mower params snapshot snapshots/params/post-safety-defaults-<stamp>.json` and re-`diff` to assert post-state matches the profile.
7. **Step 5: Re-dump `docs/config/mower.param`** — exact command (.parm format) and `git diff` expectation.
8. **Step 6: Update research 019 Phase 1 status** — change to `✅ Complete (applied YYYY-MM-DD)`.
9. **Rollback** — `mower params apply <pre-snapshot.json>` (Plan 001 supports JSON snapshots as input).
10. **Known gotchas** — endpoint must point at the live Pixhawk, not SITL; the diff-then-confirm flow will catch a wrong endpoint by surfacing wildly-different params.

## Dependencies

### Internal (must already exist — verified)

- `mower_rover.params.io` — `ParamSet`, `load_param_file`, `write_json_snapshot`, `load_json_snapshot` ✅
- `mower_rover.params.mav` — `apply_params`, `fetch_params` ✅
- `mower_rover.params.diff` — `diff_params`, `render_diff` ✅
- `mower_rover.params.baseline` — `BASELINE_PATH`, `load_baseline` ✅
- `mower_rover.safety.confirm` — `requires_confirmation`, `SafetyContext`, `ConfirmationAborted` ✅
- `mower_rover.mavlink.connection` — `open_link`, `ConnectionConfig` ✅
- Plan 001 (Param Apply, Snapshot & Restore Workflow) — implemented ✅

### External

- ArduPilot SITL (`rover-skid` frame) — already in CI per `tests/test_params_sitl.py`.
- No new Python packages.

### Hardware (only required for the operator-scheduled follow-up phase)

- Live Pixhawk Cube Orange on USB tether to laptop, ArduPilot Rover firmware running.
- Mower physically secured (on stand or ignition off).

## Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|------------|--------|------------|
| R-1 | Operator applies the profile against SITL endpoint instead of live Pixhawk (or vice versa) | Medium | Low (no harm; just wrong target) | Procedure runbook explicitly lists endpoint; existing diff-then-confirm flow surfaces wildly-different params before write |
| R-2 | `ARMING_CHECK=13816` blocks arming on live hardware due to a check we didn't anticipate (e.g. battery monitor edge case) | Low–Medium | Low (operator can disarm-check via single-param apply) | Procedure includes a step to attempt arming after apply; if it fails, the snapshot rollback path is documented |
| R-3 | Two yamls (`safety-defaults.yaml`, `z254_baseline.yaml`) drift on the seven keys before the Q1 follow-up sync lands | Medium | Low | Tracked as a named task (Phase 4) in the execution plan; SITL test asserts profile values, not baseline |
| R-4 | SITL fence-breach test is flaky due to timing of mode transition vs. fence evaluation rate | Medium | Low (test only) | Use polling loop with timeout (e.g. 10 s) and clear failure message; mark test `@pytest.mark.sitl` so it's not a CI gate for unrelated changes |
| R-5 | `FS_GCS_TIMEOUT=5` proves too aggressive in the field, causing spurious Holds during marginal Wi-Fi | Medium | Medium (operational nuisance, not safety) | Documented as a one-param `mower params apply` adjustment; not a code change |
| R-6 | Operator forgets to update research 019 Phase 1 status after applying | High | Low | Step 6 of the procedure runbook explicitly calls it out; PR template (if any) should mention it |

## Execution Plan

### Phase 1: Profile + Resolver

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2 (1 new, 1 edit)
**Prerequisites:** None
**Entry Point:** `src/mower_rover/params/data/safety-defaults.yaml` (new)
**Verification:** `python -c "from mower_rover.params.baseline import load_profile; print(load_profile('safety-defaults'))"` lists 7 keys with the values from the Profile Contents block above.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 ✅ | Create `safety-defaults.yaml` with the exact 7-key contents | [src/mower_rover/params/data/safety-defaults.yaml](../../src/mower_rover/params/data/safety-defaults.yaml) | File parses via `load_param_file`; produces a `ParamSet` with exactly 7 entries |
| 1.2 ✅ | Add `_resolve_data_path`, `SAFETY_DEFAULTS_PATH`, `PROFILES`, `load_profile` | [src/mower_rover/params/baseline.py](../../src/mower_rover/params/baseline.py) | `load_profile("nonexistent")` raises `KeyError` mentioning known profiles |
| 1.3 ✅ | Update `__all__` in `baseline.py` | [src/mower_rover/params/baseline.py](../../src/mower_rover/params/baseline.py) | New symbols exported |
| 1.4 ✅ | Add unit tests for `load_profile` (success + KeyError) | [tests/test_params.py](../../tests/test_params.py) | 5 new tests pass |

### Phase 2: CLI `--profile` Surface

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 1 complete (PROFILES dict exists)
**Entry Point:** [src/mower_rover/cli/params.py](src/mower_rover/cli/params.py)
**Verification:** `mower params apply --profile safety-defaults --port udp:127.0.0.1:14550 --dry-run` (against running SITL) shows the expected diff and exits cleanly.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Add `--profile` Typer Option to `apply_command`; make `params_file` Argument optional; validate exactly-one-of at start of body | [src/mower_rover/cli/params.py](src/mower_rover/cli/params.py) | Supplying both raises `typer.BadParameter`; supplying neither raises same; supplying just `--profile` succeeds |
| 2.2 | Wire `load_profile(profile)` into `apply_command` body when `--profile` is set; ensure structured log line on apply contains `source="profile:<name>"` | [src/mower_rover/cli/params.py](src/mower_rover/cli/params.py) | `log.bind(source="profile:safety-defaults")` (or equivalent) emits a JSON log entry on apply identifying the named profile; no new artifact files introduced beyond the existing `--snapshot-dir` pre-apply snapshot |
| 2.3 | Extend `_load_any` to consult `PROFILES` before treating input as a path (so `mower params diff safety-defaults snapshot.json` works without a new flag) | [src/mower_rover/cli/params.py](src/mower_rover/cli/params.py) | `mower params diff safety-defaults baseline` runs and produces a diff |
| 2.4 | Add CLI smoke tests asserting flag behaviour (mutual exclusion, profile resolution) using Typer's `CliRunner` | [tests/test_cli_smoke.py](tests/test_cli_smoke.py) (extend) | Tests pass; no MAVLink connection required (mock or test the validation path that exits before connect) |

### Phase 3: SITL Verification

**Status:** ✅ Complete (test module authored; SITL execution requires `sim_vehicle.py` on PATH)
**Size:** Medium
**Files to Modify:** 1 new test module + small `conftest.py` helper additions
**Prerequisites:** Phases 1–2 complete; SITL fixture (`sitl_rover_skid` or equivalent) functional from existing `tests/test_params_sitl.py`
**Entry Point:** `tests/test_failsafe_defaults_sitl.py` (new)
**Verification:** `pytest tests/test_failsafe_defaults_sitl.py -m sitl` — all three tests pass.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.0 | Add `sitl_connection` function-scoped fixture in `tests/conftest.py` that consumes `sitl_endpoint`, opens a `pymavlink` link via `open_link(ConnectionConfig(endpoint=sitl_endpoint, baud=57600))`, and yields the connection (closing on teardown) | [tests/conftest.py](tests/conftest.py) | `from mower_rover.mavlink.connection import ConnectionConfig, open_link`; fixture yields a `mavutil.mavfile`-compatible object; existing `@pytest.mark.sitl` tests in `tests/test_params_sitl.py` continue to pass unchanged |
| 3.1 | Create `tests/test_failsafe_defaults_sitl.py` with `pytestmark = pytest.mark.sitl` | tests/test_failsafe_defaults_sitl.py (new) | File exists; pytest collects it under the `sitl` marker |
| 3.2 | Implement `test_safety_defaults_round_trip` (FR-5): invoke `mower params apply --profile safety-defaults --port {sitl_endpoint} --yes` via `CliRunner`, then call `fetch_params(sitl_connection)` and assert bit-exact match for all 7 keys | tests/test_failsafe_defaults_sitl.py | Test passes against fresh SITL instance; each of 7 keys asserted individually with descriptive failure message |
| 3.3 | Add `upload_test_fence(conn, radius_m)` helper in `tests/conftest.py` (or a sibling test-helpers module) | [tests/conftest.py](tests/conftest.py) | Helper uploads a circular fence centered on home; readable back via `MISSION_REQUEST_LIST` for fence type |
| 3.4 | Implement `test_fence_breach_enters_hold` (FR-6): apply profile via CLI, then use `sitl_connection` to upload small fence, arm Auto, command guided velocity outward, poll mode until `HOLD` or 10 s timeout | tests/test_failsafe_defaults_sitl.py | Test passes deterministically over 10 consecutive runs; fails fast with clear message if mode does not become `HOLD` |
| 3.5 | Implement `test_gcs_heartbeat_loss_enters_hold` (FR-7): apply profile via CLI, arm via `sitl_connection`, stop heartbeat thread, wait `FS_GCS_TIMEOUT + 1` s, assert mode == `HOLD` | tests/test_failsafe_defaults_sitl.py | Test passes; uses configurable timeout to remain robust to slow CI |
| 3.6 | Run full SITL suite to confirm no regression in existing param-apply tests | tests/test_params_sitl.py | `pytest tests/ -m sitl` exit code 0 |

### Phase 4: Baseline Sync (Q1 Follow-Up)

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 1
**Prerequisites:** Phase 1 complete (profile values are now the canonical reference)
**Entry Point:** [src/mower_rover/params/data/z254_baseline.yaml](src/mower_rover/params/data/z254_baseline.yaml)
**Verification:** Diff `safety-defaults.yaml` and the relevant section of `z254_baseline.yaml`: the 7 keys agree exactly.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | In `z254_baseline.yaml`, add `FENCE_ENABLE: 1` under the `# --- Geofence ---` section | src/mower_rover/params/data/z254_baseline.yaml | Key present with value `1`; comment notes "added per plan 016 / research 019 Phase 1" |
| 4.2 | Replace the (currently absent) `ARMING_CHECK` line with `ARMING_CHECK: 13816` in the `# --- Arming ---` section, with a comment block summarising the bitmask | src/mower_rover/params/data/z254_baseline.yaml | Key present with value `13816`; comment lists the contributing bits |
| 4.3 | Verify the other five safety keys in `z254_baseline.yaml` (`FENCE_ACTION`, `FS_EKF_ACTION`, `FS_ACTION`, `FS_GCS_ENABLE`, `FS_GCS_TIMEOUT`) match `safety-defaults.yaml` | src/mower_rover/params/data/z254_baseline.yaml | All five values bit-exact match; if any differ, treat as a regression bug and reconcile in favor of the `safety-defaults` values (this plan is the authority) |
| 4.4 | Add a unit test asserting `load_baseline()` and `load_profile("safety-defaults")` agree on the 7 keys | [tests/test_params.py](tests/test_params.py) (extend) | Test passes; will fail loudly if either yaml drifts in future |

### Phase 5: Procedure Runbook

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 1 new
**Prerequisites:** Phases 1–3 complete (the runbook references the `--profile` flag and verification flow)
**Entry Point:** `docs/procedures/006-apply-safety-defaults.md` (new)
**Verification:** Operator reads the runbook end-to-end and confirms each step is executable as written without external lookups.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Author `006-apply-safety-defaults.md` following the section outline in the Technical Design | docs/procedures/006-apply-safety-defaults.md (new) | All 10 sections present (Purpose, Pre-flight, Steps 1–6, Rollback, Gotchas); commands are copy-pasteable |
| 5.2 | Cross-link from [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md) Phase 1 "Recommended Mitigations" to the new procedure | docs/research/019-current-architecture-fragility.md | Link present and resolves; research 019 status remains "🟢 Recommended" until live apply is performed |
| 5.3 | Cross-link from this plan's Handoff section to the procedure | docs/plans/016-failsafe-defaults-correction.md | Link present |

### Phase 6: Live Apply (Operator-Scheduled Follow-Up)

**Status:** ⏳ Not Started — operator-scheduled, NOT a gate on plan PR merge
**Size:** Small (procedure execution)
**Files to Modify:** 2 (snapshot files + status update)
**Prerequisites:** Phases 1–5 merged; mower physically accessible; current `docs/config/mower.param` is up to date
**Entry Point:** `docs/procedures/006-apply-safety-defaults.md`
**Verification:** Post-apply `docs/config/mower.param` shows the 7 corrected keys; `git diff` is limited to the expected lines.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 6.1 | Execute `docs/procedures/006-apply-safety-defaults.md` Steps 1–5 against the live Pixhawk | snapshots/params/*.json (new) | Pre-apply and post-apply snapshots exist under `snapshots/params/`; diff between them limited to the 7 keys |
| 6.2 | Re-dump `docs/config/mower.param` per Step 5 of the procedure | [docs/config/mower.param](../config/mower.param) | `git diff docs/config/mower.param` shows changes only on `FENCE_ENABLE`, `FENCE_ACTION`, `FS_EKF_ACTION`, `FS_ACTION`, `FS_GCS_ENABLE`, `FS_GCS_TIMEOUT`, `ARMING_CHECK` |
| 6.3 | Update [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md) Phase 1 status to `✅ Complete (applied YYYY-MM-DD)` | docs/research/019-current-architecture-fragility.md | Status row updated; date matches the snapshot timestamp |
| 6.4 | Commit snapshots + updated mower.param + updated research 019 in a single commit referencing this plan | git | Commit message: `safety: apply safety-defaults profile (plan 016 / research 019 phase 1)` |

| Related Plan | docs/plans/001-param-apply-snapshot-restore.md (reused machinery) |

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 6 files across 1 package: 2 new YAML, 2 new docs, 2 new tests, 3 edits (`baseline.py`, `cli/params.py`, `z254_baseline.yaml`, `tests/conftest.py`, `tests/test_params.py`, `tests/test_cli_smoke.py`) — all small |
| New patterns introduced | 1 | `PROFILES` registry + `load_profile(name)` resolver; mirrors existing `BASELINE_PATH` / `load_baseline` pattern |
| External dependencies | 1 | ArduPilot SITL (already in CI); no new Python packages |
| Migration complexity | 2 | Live param apply is reversible via pre-apply snapshot + Plan 001 restore; operator-scheduled (Phase 6) |
| Test coverage required | 3 | Unit (Phase 1.4, 4.4), CLI smoke (Phase 2.4), SITL (Phase 3, 3 tests including 2 trigger-based); no E2E hardware test in this plan |
| **Overall Complexity** | **9 / 25** | **Low** (≤ 10) — small, well-bounded, reuses existing machinery |

## Review Summary

**Review Date:** 2026-05-04  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.3

### Review Metrics

- Issues Found: 5 (Critical: 1, Major: 2, Minor: 2)
- Critical/Major Resolved: 3/3
- Minor: 2 (acknowledged, not blocking — see Remaining Considerations)
- Clarifying Questions Asked: 3
- Sections Updated: Tech Design (SITL Test Module), FR-3, FR-4, Phase 2 (step 2.2), Phase 3 (new step 3.0; steps 3.1–3.5)

### Codebase Verification Performed

| Claim | Result |
|-------|--------|
| `params/baseline.py` API surface (`BASELINE_PATH`, `load_baseline`, `_resolve_baseline_path`, `__all__`) | ✅ Verified |
| `cli/params.py` API surface (`apply_command`, `diff_command`, `_load_any` with `"baseline"` magic-string) | ✅ Verified |
| Live Pixhawk dump matches plan's claimed wrong values | ✅ Verified ([mower.param](../config/mower.param)) |
| `z254_baseline.yaml` already correct on 5 of 7 safety keys; missing `FENCE_ENABLE` and `ARMING_CHECK` | ✅ Verified — Phase 4 reduces to 2 deterministic edits |
| SITL fixture is `sitl_endpoint: str` (not `sitl_rover_skid`) and tests use `CliRunner` | ✅ Verified — fixed via Q1 |
| `ARMING_CHECK = 13816` bitmask arithmetic (8+16+32+64+128+256+1024+4096+8192) | ✅ Verified |

### Key Improvements Made

1. **Q1 (Critical):** Replaced fictitious `sitl_rover_skid.connect()` pattern with a real, additive `sitl_connection` fixture aligned with the existing `sitl_endpoint`-based suite.
2. **Q2 (Major):** Removed undefined "verification report file" artifact from FR-4 and step 2.2; verification now flows through existing `--snapshot-dir` pre-apply snapshot, Phase 5 runbook's post-apply snapshot+diff, and Phase 3 SITL round-trip test.
3. **Q3 (Major):** Tightened FR-3 to single mechanism (magic-string), eliminating implementation ambiguity for `pch-coder`.

### Remaining Considerations (Minor, non-blocking)

- **Minor-1:** Phase 4 step 4.3 phrasing implies discovery work that's already complete. `z254_baseline.yaml` was verified during this review to match `safety-defaults.yaml` on `FENCE_ACTION`, `FS_EKF_ACTION`, `FS_ACTION`, `FS_GCS_ENABLE`, `FS_GCS_TIMEOUT`. Only `FENCE_ENABLE` (add) and `ARMING_CHECK` (add) need edits. pch-coder can treat step 4.3 as a no-op assertion.
- **Minor-2:** Phase 5 step 5.2 conflates research-doc "complete" status with implementation-applied status. pch-coder should add an "Implementation status" line to research 019 Phase 1 rather than mutating its top-level `✅ Complete` status. Phase 6 step 6.3 already does the right thing.

### Open Questions Carried Forward (for field validation)

- `FS_GCS_TIMEOUT=5` may prove too aggressive in marginal Wi-Fi (R-5).
- `ARMING_CHECK=13816` may surface a hardware-specific check failure on first arm attempt (R-2) — procedure runbook covers rollback.
- EKF-failsafe end-to-end behaviour validated only by param presence; field test required.

### Sign-off

This plan has been reviewed and is **✅ Ready for Implementation**.

## Standards

| Standard | Relevance | Guidance Applied |
|----------|-----------|------------------|
| `.github/copilot-instructions.md` | All sections | Failsafe default = Hold; per-side calibration unchanged; SITL = smoke harness only; safety primitive on actuator-touching commands; structured output everywhere |
| [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md) Phase 1 | Direct parent | Four mandatory params + Q3 GCS-failsafe decision implemented per the recommended mitigations |
| [docs/plans/001-param-apply-snapshot-restore.md](001-param-apply-snapshot-restore.md) | Reused tooling | Apply / snapshot / diff / verification-report flow inherited unchanged |

## Implementation Notes

### Phases 1–5
**Completed:** 2026-05-04
**Execution Mode:** Direct (single coder session — small, well-bounded plan)

**Files Created:**

- `src/mower_rover/params/data/safety-defaults.yaml` — 7-key failsafe profile
- `tests/test_failsafe_defaults_sitl.py` — FR-5/6/7 SITL tests
- `docs/procedures/006-apply-safety-defaults.md` — operator runbook

**Files Modified:**

- `src/mower_rover/params/baseline.py` — added `_resolve_data_path`, `SAFETY_DEFAULTS_PATH`, `PROFILES`, `load_profile`; refactored `_resolve_baseline_path`
- `src/mower_rover/cli/params.py` — `--profile` flag on `apply` (mutually exclusive with `params_file`); `_load_any` now consults `PROFILES` so profile names work as positional args on `diff`; structured-log `source` field is `profile:<name>` when applied via `--profile`
- `src/mower_rover/params/data/z254_baseline.yaml` — added `FENCE_ENABLE: 1` and `ARMING_CHECK: 13816` (the only 2 of the 7 safety keys missing or different; other 5 already matched)
- `tests/test_params.py` — 5 new tests covering profile registry, safety-defaults values, baseline-vs-profile drift guard
- `tests/test_cli_smoke.py` — 4 new tests covering `--profile` flag validation and diff magic-string resolution
- `tests/conftest.py` — new `sitl_connection` fixture (function-scoped, opens pymavlink link via `open_link`)
- `docs/research/019-current-architecture-fragility.md` — Phase 1 cross-link to procedure 006 added

**Deviations from Plan:** None.

**Verification:**

- `python -m pytest tests/ -k "not sitl and not field"` → 667 passed, 1 skipped, 31 deselected
- `python -m ruff check` on changed files → All checks passed
- `python -m mypy` on `src/mower_rover/params` and `src/mower_rover/cli/params.py` → no issues
- SITL tests (`tests/test_failsafe_defaults_sitl.py`) authored and importable; live SITL execution deferred to a CI environment with `sim_vehicle.py` available

### Phase 6 — Outstanding (Operator-Scheduled)

Execute [docs/procedures/006-apply-safety-defaults.md](../procedures/006-apply-safety-defaults.md) against the live Pixhawk when next physically accessible. Then update research 019 Phase 1 with the applied date.

---

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-04 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-04 |
| Status | ✅ Complete (Phases 1–5); Phase 6 operator-scheduled |
| Next Agent | Operator (run procedure 006); then any pch-* for the next plan |
| Plan Location | docs/plans/016-failsafe-defaults-correction.md |
| Procedure Location (created in Phase 5) | docs/procedures/006-apply-safety-defaults.md |
| Related Research | docs/research/019-current-architecture-fragility.md (Phase 1) |
| Related Plan | docs/plans/001-param-apply-snapshot-restore.md (reused machinery) |
