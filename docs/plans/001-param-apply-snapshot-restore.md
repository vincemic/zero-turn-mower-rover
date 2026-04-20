---
id: "001"
type: implementation-plan
title: "Parameter Apply, Snapshot & Restore Workflow"
status: draft
created: 2026-04-19
updated: 2026-04-19
owner: pch-planner
version: v2.0
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-19 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-19 | pch-planner | Decision #1: restore command scope (option D) |
| v1.2 | 2026-04-19 | pch-planner | Decision #2: snapshot storage convention (option B) |
| v1.3 | 2026-04-19 | pch-planner | Decision #3: reboot-required param detection (option A) |
| v1.4 | 2026-04-19 | pch-planner | Decision #4: verification report format (option B) |
| v1.5 | 2026-04-19 | pch-planner | Decision #5: retrofit existing commands (option A) |
| v1.6 | 2026-04-19 | pch-planner | Decision #6: testing strategy (option A) |
| v2.0 | 2026-04-19 | pch-planner | Holistic review + full execution plan complete |

## Introduction

This plan covers completing the `mower params` CLI surface — specifically the `snapshot`, `apply`, and new `restore` subcommands — so that ArduPilot parameter management has a full round-trip workflow: capture current state, apply desired state with diff + confirmation, and restore from a previous snapshot. This is FR-2 (baseline param apply) and FR-12 (snapshot full config) from the vision document, plus NFR-5 (reproducibility: snapshots must round-trip-verify losslessly).

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|---------------|--------|-----------|
| 1 | Restore command scope | D — `restore` as alias + post-apply verification report | NFR-5 round-trip-verify contract; require JSON snapshot input for provenance; warn on reboot-needed params rather than forcing reboot |
| 2 | Snapshot storage convention | B — Default snapshot directory with auto-timestamped filenames | NFR-5 Git-tracked plain files; project-local `./snapshots/params/` is discoverable, Git-friendly, avoids manifest complexity |
| 3 | Reboot-required param detection | A — Hardcoded list maintained in this project | Small curated set for single vehicle; field-offline rules out runtime fetch; NFR-4 requires explainable guidance |
| 4 | Verification report format & destination | B — Auto-written JSON report file alongside snapshot directory | NFR-5 tangible proof artifact; co-located with snapshots in `./snapshots/params/`; Git-trackable; console still shows human summary |
| 5 | Retrofit existing snapshot/apply commands | A — Retrofit both to use default directory | Consistency across CLI; auto pre-apply snapshots align with NFR-1 safety; existing tests still work with explicit paths |
| 6 | Testing strategy | A — SITL for round-trip + unit tests with mocked MAVLink for logic | Follows existing split pattern; SITL = smoke-test harness; mocks give fast CI feedback on business logic |

## Holistic Review

### Decision Interactions

1. **Decisions #1 (restore as alias) + #4 (auto-written report)** reinforce each other: the restore command's primary value-add over `apply` is the verification report. The report file is the NFR-5 proof artifact. No conflict.

2. **Decision #2 (default snapshot dir) + #5 (retrofit both commands)** create a consistent storage convention. All three commands (`snapshot`, `apply`, `restore`) converge on `./snapshots/params/`. The `--snapshot-dir` override is available on all three for flexibility. No conflict.

3. **Decision #3 (hardcoded reboot list) + #1 (restore report)** interact cleanly: the reboot list feeds into the verification report's `reboot_required` field and the console warning. The list is also useful for `apply` in the future but is only wired into `restore` in this plan to keep scope tight.

4. **Decision #6 (testing split)** is compatible with all other decisions: mock-based tests cover the new I/O helpers, CLI flag parsing, report generation, and error paths. SITL tests cover the end-to-end MAVLink round-trip.

### Architectural Considerations

- **CWD-relative snapshot directory** (Risk R-4): The `./snapshots/params/` path is CWD-relative. If the user runs `mower` from a different directory, snapshots land elsewhere. This is acceptable for a single-operator project where the operator always works from the project root. The `--snapshot-dir` override exists for edge cases.

- **No `snapshot` subdir in `.gitignore`**: Snapshots are intentionally Git-tracked (NFR-5). The `./snapshots/` directory should NOT be gitignored. This is a documentation point for the operator, not a code change.

- **`apply` backward compatibility**: Changing `--snapshot-dir` default from `None` to `./snapshots/params/` means existing `mower params apply baseline` invocations will now auto-write a pre-apply snapshot. This is **desired behavior** (NFR-1 safety) but is a behavior change. The `--no-snapshot` escape hatch mitigates. Existing SITL tests pass explicit `--yes` but don't check for snapshot files, so they're unaffected.

- **Param name intersection in `apply` vs full set in `restore`**: The existing `apply` command diffs only the *intersection* of desired param names with autopilot params (so unrelated params don't show as "removed"). The `restore` command should use the same intersection approach — a snapshot captures the full autopilot state, but restore only applies the params that were in the snapshot. The post-apply verification also checks only the intersection. This is consistent.

### Trade-offs Accepted

- **Reboot-required list requires manual maintenance** — Accepted because the param set is small and stable for this single vehicle. The list is a `frozenset` literal, easy to update.
- **No manifest/index for snapshots** — Accepted because `ls snapshots/params/ | sort` is sufficient for a single operator. A manifest adds state management complexity for minimal benefit.
- **CWD-relative paths** — Accepted because the operator always works from the project root. A config-file-based path would be over-engineering.

### Risks Acknowledged

- **R-5 (superseded RC params)** is the most significant risk but is out of scope for this plan. The apply/restore machinery is param-value-agnostic — it works correctly regardless of what's in the baseline YAML. The RC re-research is a separate blocking item tracked in the vision doc.

## Overview

### What Already Exists

The codebase has a solid foundation for parameter management:

- **`ParamSet`** — ordered name→float container with normalization, I/O for YAML/JSON/.parm
- **`ParamDiff` / `diff_params()` / `render_diff()`** — structured diff with rich table rendering
- **`write_json_snapshot()` / `load_json_snapshot()`** — snapshot schema `mower-rover.params.snapshot.v1`
- **`fetch_params()`** — MAVLink `PARAM_REQUEST_LIST` with quiet-window collection
- **`apply_params()`** — MAVLink `param_set_send` with per-param verify + retry
- **`load_baseline()`** — shipped Z254 baseline from packaged YAML
- **CLI `mower params snapshot`** — fetches all params, writes JSON snapshot
- **CLI `mower params diff`** — diffs two param files (any format) or baseline
- **CLI `mower params apply`** — applies a param file with pre-snapshot, diff display, confirmation gate, dry-run support
- **Safety primitive** — `@requires_confirmation`, `SafetyContext`, `--dry-run` / `--yes`
- **SITL tests** — `test_params_snapshot_against_sitl`, `test_params_apply_baseline_round_trip`

### What This Plan Adds

1. **`mower params restore <snapshot.json>`** — dedicated restore command that:
   - Requires JSON snapshot input (not YAML/.parm) to preserve provenance metadata
   - Fetches current autopilot state as pre-apply baseline
   - Applies params from the snapshot via existing `apply_params()`
   - Performs post-apply verification fetch + diff
   - Emits a structured JSON verification report (pre-apply vs desired vs post-apply)
   - Warns if any applied params are known to require a reboot to take effect
   - Routes through `@requires_confirmation` safety gate
2. **Post-apply verification report** — JSON artifact proving NFR-5 round-trip losslessness
3. **Remaining gaps in existing commands** — to be identified via further questions

### Objectives

1. Complete the param management CLI with a full round-trip workflow: capture → apply → restore → verify
2. Enforce automatic pre-apply snapshots so the operator always has a rollback point (NFR-1)
3. Produce a tangible verification report proving round-trip losslessness (NFR-5)
4. Warn when applied params require a flight controller reboot (NFR-4 explainability)
5. Use a consistent, Git-trackable snapshot storage convention across all param commands

## Requirements

### Functional Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| FR-2 | Apply baseline ArduPilot params with diff + confirmation | Vision FR-2 |
| FR-12 | Snapshot full config (params), Git-versionable | Vision FR-12 |
| P-1 | `mower params snapshot` — default output to `./snapshots/params/params-<timestamp>.json`; explicit path optional | Decision #2, #5 |
| P-2 | `mower params apply` — auto pre-apply snapshot to default dir; `--no-snapshot` to skip | Decision #5 |
| P-3 | `mower params restore <snapshot.json>` — restore from JSON snapshot with verification report | Decision #1 |
| P-4 | Verification report auto-written to `./snapshots/params/verify-<timestamp>.json` | Decision #4 |
| P-5 | Reboot-required param warnings in console output and verification report | Decision #3 |
| P-6 | All actuator-touching commands route through `@requires_confirmation` + `--dry-run` | Vision NFR-3, copilot-instructions |

### Non-Functional Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| NFR-1 | Never leave robot in unsafe half-configured state — auto pre-apply snapshot | Vision NFR-1 |
| NFR-2 | Field-usable, offline, sunlit-readable output | Vision NFR-2 |
| NFR-4 | Structured JSON logs, every operation logged with correlation ID | Vision NFR-4 |
| NFR-5 | Snapshots round-trip-verifiable; verification report is the proof artifact | Vision NFR-5 |

### Out of Scope

- Mission snapshots (this plan covers params only; mission snapshot is a separate FR-8 concern)
- Jetson-side config snapshot (FR-12 includes Jetson config, but that's a separate plan)
- EEPROM-level param reset / factory defaults
- Automatic reboot after apply/restore (operator decides; command only warns)
- Param metadata from ArduPilot XML (we use a hardcoded reboot-required list)

## Technical Design

### Architecture

#### File Layout (new and modified files)

```
src/mower_rover/
  params/
    __init__.py              # MODIFY — add new public exports
    io.py                    # MODIFY — add default_snapshot_dir(), auto_snapshot_path()
    mav.py                   # NO CHANGE
    baseline.py              # NO CHANGE
    diff.py                  # NO CHANGE
    reboot.py                # NEW — REBOOT_REQUIRED_PARAMS set + check helper
    verify.py                # NEW — VerifyReport dataclass + write_verify_report()
    data/
      z254_baseline.yaml     # NO CHANGE
  cli/
    params.py                # MODIFY — retrofit snapshot/apply, add restore command
tests/
  test_params.py             # MODIFY — add unit tests for new I/O helpers
  test_params_restore.py     # NEW — unit tests for restore logic (mocked MAVLink)
  test_params_sitl.py        # MODIFY — add SITL restore round-trip test
```

#### Default Snapshot Directory

- Path: `./snapshots/params/` relative to CWD (the project root)
- Created on first write via `Path.mkdir(parents=True, exist_ok=True)`
- `.gitkeep` NOT created — the first snapshot itself populates the directory

#### Auto-Timestamped Naming

- Snapshot files: `params-<YYYYMMDD>T<HHMMSS>Z.json` (UTC)
- Pre-apply snapshots: `params-pre-apply-<YYYYMMDD>T<HHMMSS>Z.json`
- Verification reports: `verify-<YYYYMMDD>T<HHMMSS>Z.json`

#### New Module: `src/mower_rover/params/reboot.py`

```python
"""ArduPilot params known to require a flight controller reboot."""

# Curated for Rover 4.x on Cube Orange. Maintained manually.
# Source: ArduPilot parameter docs + field experience.
REBOOT_REQUIRED_PARAMS: frozenset[str] = frozenset({
    # Serial port configuration
    "SERIAL1_PROTOCOL", "SERIAL1_BAUD",
    "SERIAL2_PROTOCOL", "SERIAL2_BAUD",
    "SERIAL3_PROTOCOL", "SERIAL3_BAUD",
    "SERIAL4_PROTOCOL", "SERIAL4_BAUD",
    "SERIAL5_PROTOCOL", "SERIAL5_BAUD",
    "SERIAL6_PROTOCOL", "SERIAL6_BAUD",
    # Board config
    "BRD_SAFETY_DEFLT", "BRD_PWM_COUNT", "BRD_SAFETYOPTION",
    # CAN bus
    "CAN_D1_PROTOCOL", "CAN_D2_PROTOCOL", "CAN_P1_DRIVER", "CAN_P2_DRIVER",
    # GPS type
    "GPS1_TYPE", "GPS2_TYPE", "GPS_AUTO_CONFIG",
    # EKF
    "EK2_ENABLE", "EK3_ENABLE", "AHRS_EKF_TYPE",
    # Compass
    "COMPASS_TYPEMASK",
    # Frame
    "FRAME_CLASS",
})


def check_reboot_required(param_names: frozenset[str] | set[str]) -> list[str]:
    """Return sorted list of param names from `param_names` that need a reboot."""
    return sorted(param_names & REBOOT_REQUIRED_PARAMS)
```

#### New Module: `src/mower_rover/params/verify.py`

```python
"""Verification report for param restore round-trip (NFR-5)."""

@dataclass(frozen=True)
class VerifyReport:
    schema: str = "mower-rover.params.verify.v1"
    timestamp: str           # ISO 8601 UTC
    snapshot_source: str     # path to the snapshot that was restored
    pre_apply: dict[str, float]    # full autopilot state before apply
    desired: dict[str, float]      # params from the snapshot
    post_apply: dict[str, float]   # full autopilot state after apply
    mismatches: list[dict]   # [{name, desired, actual}] — should be empty on success
    reboot_required: list[str]     # params that need a reboot
    verdict: str             # "PASS" or "FAIL"

def write_verify_report(report: VerifyReport, path: Path) -> None:
    """Write the verification report as JSON."""
    ...

def build_verify_report(
    snapshot_source: str,
    pre_apply: ParamSet,
    desired: ParamSet,
    post_apply: ParamSet,
) -> VerifyReport:
    """Compare post-apply against desired; flag mismatches and reboot-required."""
    ...
```

#### CLI `restore` Command Signature

```python
@app.command("restore")
def restore_command(
    ctx: typer.Context,
    snapshot: Path = typer.Argument(..., help="JSON snapshot file to restore from."),
    endpoint: str = typer.Option("udp:127.0.0.1:14550", "--port", "--endpoint"),
    baud: int = typer.Option(57600),
    snapshot_dir: Path = typer.Option(None, "--snapshot-dir",
        help="Override default snapshot/report directory."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
```

**Flow:**
1. Validate input is a JSON snapshot (check schema field)
2. Resolve snapshot directory (explicit `--snapshot-dir` or default `./snapshots/params/`)
3. Connect to autopilot via `open_link()`
4. Fetch current autopilot params → `pre_apply` ParamSet
5. Write pre-apply snapshot to snapshot dir
6. Diff `pre_apply` vs `desired` (from snapshot); render to console
7. If diff is empty → print "Already matches", exit 0
8. Confirmation gate via `@requires_confirmation`
9. If `--dry-run` → print dry-run message, exit 0
10. Apply params via `apply_params()`
11. Fetch autopilot params again → `post_apply` ParamSet
12. Build `VerifyReport` comparing `desired` vs `post_apply`
13. Write verification report JSON to snapshot dir
14. Render human-readable summary to console (pass/fail, mismatch count, reboot warnings)
15. Exit 0 if PASS, exit 1 if FAIL

#### Retrofitted `snapshot` Command Signature

```python
@app.command("snapshot")
def snapshot_command(
    output: Path | None = typer.Argument(None, help="Output path (default: auto-named in ./snapshots/params/)."),
    endpoint: str = typer.Option("udp:127.0.0.1:14550", "--port", "--endpoint"),
    baud: int = typer.Option(57600),
    timeout: float = typer.Option(60.0),
) -> None:
```

Change: `output` becomes `Optional[Path]` (default `None`). If `None`, resolve to `./snapshots/params/params-<timestamp>.json`.

#### Retrofitted `apply` Command Changes

- Add `--no-snapshot` flag (default `False`)
- Change `--snapshot-dir` default from `None` to `./snapshots/params/` (when `--no-snapshot` is not set)
- Pre-apply snapshot is always written unless `--no-snapshot` is passed

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: CLI Subcommands via Typer
    location: "src/mower_rover/cli/params.py"
    usage: New restore command follows existing snapshot/diff/apply pattern
  - pattern: ParamSet I/O
    location: "src/mower_rover/params/io.py"
    usage: Snapshot read/write, format detection
  - pattern: MAVLink Param Protocol
    location: "src/mower_rover/params/mav.py"
    usage: fetch_params/apply_params for read/write cycles
  - pattern: Safety Confirmation
    location: "src/mower_rover/safety/confirm.py"
    usage: requires_confirmation decorator for actuator-touching commands
  - pattern: Structured Logging
    location: "src/mower_rover/logging_setup/setup.py"
    usage: get_logger() with operation binding and correlation IDs
  - pattern: Connection Context Manager
    location: "src/mower_rover/mavlink/connection.py"
    usage: open_link(ConnectionConfig) for all MAVLink interactions
```

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| `pymavlink` | Python package | Installed | Already in pyproject.toml; used by `mav.py` |
| `typer` + `rich` | Python packages | Installed | CLI framework + table rendering |
| `structlog` | Python package | Installed | Logging |
| `PyYAML` | Python package | Installed | YAML I/O |
| ArduPilot SITL | Test dependency | Available via WSL2 | For `@pytest.mark.sitl` tests only |
| Existing `ParamSet` / `ParamDiff` | Internal | Complete | Foundation this plan builds on |
| Existing `open_link()` | Internal | Complete | MAVLink connection context manager |
| Existing `SafetyContext` / `@requires_confirmation` | Internal | Complete | Safety primitive |

No new external dependencies are introduced.

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R-1 | Reboot-required list becomes stale with ArduPilot updates | Low | Low | List is small and curated for this single vehicle; review when upgrading ArduPilot firmware |
| R-2 | `snapshot` output path change breaks user muscle memory | Low | Low | Explicit path still accepted; auto-naming is additive |
| R-3 | Post-apply verification fails due to param echo timing | Medium | Medium | Existing `apply_params()` already has per-param retry + verify; post-apply fetch is a separate full read with quiet window |
| R-4 | CWD is not project root → default snapshot dir lands in unexpected location | Medium | Low | Document that `./snapshots/params/` is CWD-relative; add a `--snapshot-dir` override on every command |
| R-5 | ⚠️ Baseline YAML has superseded RC params (`FS_THR_ENABLE=0`, `RC_PROTOCOLS=0`) | Known | Medium | This plan does NOT touch the baseline YAML content; the apply/restore machinery works regardless of param values; RC re-research is a separate blocking item |

## Execution Plan

### Phase 1: New Library Modules (reboot + verify)

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 4
**Prerequisites:** None — builds on existing `ParamSet`/`ParamDiff`
**Entry Point:** `src/mower_rover/params/reboot.py` (new file)
**Verification:** `uv run pytest -m "not field and not sitl"` passes; `uv run mypy` clean

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Create `reboot.py` with `REBOOT_REQUIRED_PARAMS` frozenset and `check_reboot_required()` function | `src/mower_rover/params/reboot.py` | Module imports cleanly; `check_reboot_required({"GPS1_TYPE", "SERVO1_FUNCTION"})` returns `["GPS1_TYPE"]`; `check_reboot_required({"SERVO1_FUNCTION"})` returns `[]` |
| 1.2 | Create `verify.py` with `VerifyReport` dataclass, `build_verify_report()`, and `write_verify_report()` | `src/mower_rover/params/verify.py` | `VerifyReport` has fields: `schema`, `timestamp`, `snapshot_source`, `pre_apply`, `desired`, `post_apply`, `mismatches`, `reboot_required`, `verdict`; `build_verify_report()` returns `PASS` when post matches desired, `FAIL` when mismatches exist; `write_verify_report()` writes valid JSON with schema `mower-rover.params.verify.v1` |
| 1.3 | Add `default_snapshot_dir()` and `auto_snapshot_path(prefix)` helpers to `io.py` | `src/mower_rover/params/io.py` | `default_snapshot_dir()` returns `Path("./snapshots/params")`; `auto_snapshot_path("params")` returns `Path("./snapshots/params/params-<timestamp>.json")` with UTC ISO timestamp; `auto_snapshot_path("verify")` uses `verify-` prefix; `auto_snapshot_path("params-pre-apply")` uses that prefix |
| 1.4 | Update `__init__.py` to export new public symbols | `src/mower_rover/params/__init__.py` | `from mower_rover.params import check_reboot_required, VerifyReport, build_verify_report, write_verify_report, default_snapshot_dir, auto_snapshot_path` all resolve |
| 1.5 | Add unit tests for `reboot.py`, `verify.py`, and new `io.py` helpers | `tests/test_params.py` | Tests: `test_check_reboot_required_returns_matching`, `test_check_reboot_required_empty_when_none_match`, `test_verify_report_pass`, `test_verify_report_fail_with_mismatches`, `test_verify_report_includes_reboot_required`, `test_write_verify_report_json_schema`, `test_default_snapshot_dir`, `test_auto_snapshot_path_format`; all pass with `uv run pytest -m "not field and not sitl"` |

### Phase 2: Retrofit `snapshot` Command

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 1 complete (needs `default_snapshot_dir()`, `auto_snapshot_path()`)
**Entry Point:** `src/mower_rover/cli/params.py` — `snapshot_command()`
**Verification:** `uv run pytest -m "not field and not sitl"` passes; `mower params snapshot --help` shows optional output arg

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Change `output` argument from required `Path` to optional `Path \| None` with default `None` | `src/mower_rover/cli/params.py` | `mower params snapshot --help` shows `[OUTPUT]` (optional); calling with no arg doesn't crash (requires MAVLink, but the signature change is testable via `--help`) |
| 2.2 | When `output is None`, resolve to `auto_snapshot_path("params")` and create the directory | `src/mower_rover/cli/params.py` | When output is omitted, the file is written to `./snapshots/params/params-<timestamp>.json`; directory is created if absent; console prints the resolved path |
| 2.3 | Add unit test for default snapshot path resolution (mocked MAVLink) | `tests/test_params_restore.py` | Test `test_snapshot_default_path` uses `monkeypatch` to mock `fetch_params` + `open_link`; invokes `snapshot_command` via `CliRunner` with no output arg; asserts file is written to `./snapshots/params/params-*.json` pattern in `tmp_path` |
| 2.4 | Verify existing SITL test still passes with explicit output path | `tests/test_params_sitl.py` | `test_params_snapshot_against_sitl` unchanged and green |

### Phase 3: Retrofit `apply` Command

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 1 complete (needs `auto_snapshot_path()`)
**Entry Point:** `src/mower_rover/cli/params.py` — `apply_command()`
**Verification:** `uv run pytest -m "not field and not sitl"` passes; `mower params apply --help` shows `--no-snapshot` flag

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add `--no-snapshot` boolean flag (default `False`) to `apply_command` | `src/mower_rover/cli/params.py` | `mower params apply --help` shows `--no-snapshot` option |
| 3.2 | Change `--snapshot-dir` default: when `--no-snapshot` is `False` and `--snapshot-dir` is not given, default to `default_snapshot_dir()` | `src/mower_rover/cli/params.py` | When `--no-snapshot` not set and `--snapshot-dir` not given, pre-apply snapshot is auto-written to `./snapshots/params/params-pre-apply-<timestamp>.json` |
| 3.3 | When `--no-snapshot` is `True`, skip pre-apply snapshot entirely (even if `--snapshot-dir` is given) | `src/mower_rover/cli/params.py` | `--no-snapshot` prevents any snapshot file creation |
| 3.4 | Add unit tests for the new apply flags (mocked MAVLink) | `tests/test_params_restore.py` | Test `test_apply_auto_snapshot_default_dir` verifies pre-apply snapshot is written to default dir; test `test_apply_no_snapshot_skips` verifies `--no-snapshot` suppresses it |
| 3.5 | Verify existing SITL `apply` test still passes | `tests/test_params_sitl.py` | `test_params_apply_baseline_round_trip` unchanged and green |

### Phase 4: New `restore` Command

**Status:** ⏳ Not Started
**Size:** Medium
**Files to Modify:** 3
**Prerequisites:** Phase 1 complete (needs `verify.py`, `reboot.py`, `auto_snapshot_path()`); Phase 3 complete (needs `apply` retrofit for consistency)
**Entry Point:** `src/mower_rover/cli/params.py` — new `restore_command()`
**Verification:** `uv run pytest -m "not field and not sitl"` passes; `mower params restore --help` shows correct signature

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | Add `restore_command()` to `cli/params.py` with full signature: `snapshot` (required Path), `--port`/`--endpoint`, `--baud`, `--snapshot-dir`, `--yes` | `src/mower_rover/cli/params.py` | `mower params restore --help` displays all options; `snapshot` is a required positional arg |
| 4.2 | Implement input validation: reject non-JSON files and files missing the `mower-rover.params.snapshot.v1` schema field | `src/mower_rover/cli/params.py` | `mower params restore some.yaml` exits with error "restore requires a JSON snapshot"; a JSON file without the schema field exits with error "not a mower-rover param snapshot" |
| 4.3 | Implement the full restore flow: connect → fetch pre_apply → write pre-apply snapshot → diff → confirm → apply → fetch post_apply → build VerifyReport → write report → render summary | `src/mower_rover/cli/params.py` | Full flow runs (tested via mocked MAVLink in step 4.6); each step logs via structlog with `op="restore"` |
| 4.4 | Add `_confirm_restore()` function with `@requires_confirmation("Restore parameters from snapshot (this changes flight behaviour)")` | `src/mower_rover/cli/params.py` | Confirmation prompt shown; `--yes` skips it; `--dry-run` skips it and prints dry-run message |
| 4.5 | Render human-readable verification summary: param count, mismatches (if any), reboot-required warnings, overall PASS/FAIL verdict | `src/mower_rover/cli/params.py` | Console output shows: "Verified N/N params — PASS" or "FAIL: M mismatches"; reboot warnings listed if any |
| 4.6 | Add unit tests for `restore` (mocked MAVLink) | `tests/test_params_restore.py` | Tests: `test_restore_rejects_yaml_input`, `test_restore_rejects_non_snapshot_json`, `test_restore_dry_run`, `test_restore_full_flow_pass` (mock fetch→apply→fetch; verify report PASS), `test_restore_full_flow_fail` (mock post-apply with mismatch; verify report FAIL, exit code 1), `test_restore_shows_reboot_warnings`, `test_restore_already_matches` (diff empty → exit 0 with no apply) |
| 4.7 | Wire `restore` command into the params Typer app | `src/mower_rover/cli/params.py` | `mower params restore` appears in `mower params --help` output |

### Phase 5: SITL Integration Tests

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 1
**Prerequisites:** Phase 2, 3, 4 complete
**Entry Point:** `tests/test_params_sitl.py`
**Verification:** `uv run pytest -m sitl` passes (requires SITL available)

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Add `test_params_snapshot_default_dir_against_sitl` — invoke snapshot with no output arg, verify file written to default dir | `tests/test_params_sitl.py` | Snapshot file exists at `./snapshots/params/params-*.json`; contains >100 params |
| 5.2 | Add `test_params_apply_auto_snapshot_against_sitl` — invoke apply with baseline, verify pre-apply snapshot auto-written | `tests/test_params_sitl.py` | Pre-apply snapshot exists at `./snapshots/params/params-pre-apply-*.json` |
| 5.3 | Add `test_params_restore_round_trip_against_sitl` — full cycle: snapshot → apply different values → restore from snapshot → verify report PASS | `tests/test_params_sitl.py` | Verification report exists at `./snapshots/params/verify-*.json`; JSON `verdict` field is `"PASS"`; post-apply params match original snapshot values for the modified params |
| 5.4 | Add `test_params_restore_dry_run_against_sitl` — `restore --dry-run` connects and shows diff but writes nothing | `tests/test_params_sitl.py` | Exit code 0; no params changed on SITL (re-snapshot matches pre state); console output contains "dry-run" |

## Standards

No organizational standards applicable to this plan.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-19 |
| Status | ⏳ Pending Review |
| Next Agent | pch-plan-reviewer |
| Plan Location | /docs/plans/001-param-apply-snapshot-restore.md |
