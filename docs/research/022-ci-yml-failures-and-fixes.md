---
id: "022"
type: research
title: "CI Workflow Failures — Ruff & Mypy Fix Strategy"
status: ✅ Complete
created: "2026-05-05"
current_phase: "3 of 3"
---

## Introduction

The GitHub Actions CI workflow (`.github/workflows/ci.yml`) is failing on both the `ruff` lint step and the `mypy` type-check step. Tests pass cleanly (826 passed). This research documents the exact failures, categorizes them by fix strategy, and provides actionable solutions for each category.

## Objectives

- Catalog all ruff errors by rule and identify safe auto-fix vs manual-fix categories
- Catalog all mypy errors and determine root causes
- Produce a prioritized fix plan that gets CI green with minimal code churn

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Ruff Error Analysis & Fix Strategy | ✅ Complete | Categorize 1195 ruff errors; determine which are auto-fixable; identify manual fixes needed | 2026-05-05 |
| 2 | Mypy Error Analysis & Fix Strategy | ✅ Complete | Analyze 27 mypy errors across 10 files; determine root causes and fixes | 2026-05-05 |
| 3 | Fix Execution Plan | ✅ Complete | Produce ordered fix commands and code changes to get CI green | 2026-05-05 |

## Phase 1: Ruff Error Analysis & Fix Strategy

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Current State

**Total errors:** 1195  
**Auto-fixable:** 969 (with `--fix`)  
**Hidden unsafe fixes:** 134 (with `--unsafe-fixes`)

### Error Breakdown by Rule

| Rule | Count | Fixable | Description |
|------|-------|---------|-------------|
| W293 | 869 | ✅ auto | Blank line contains whitespace |
| W291 | 99 | ✅ auto | Trailing whitespace |
| E501 | 73 | ❌ manual | Line too long (>100 chars) |
| F401 | 45 | ✅ auto | Unused import |
| I001 | 28 | ✅ auto | Unsorted imports |
| W292 | 20 | ✅ auto | Missing newline at end of file |
| B904 | 12 | ❌ manual | raise-without-from-inside-except |
| F811 | 12 | ✅ auto | Redefined while unused |
| B905 | 9 | ❌ manual | zip-without-explicit-strict |
| SIM105 | 8 | ❌ manual | Suppressible exception (try/except/pass) |
| F841 | 7 | ❌ manual | Unused variable |
| F541 | 4 | ✅ auto | f-string missing placeholders |
| SIM102 | 3 | ❌ manual | Collapsible if |
| UP015 | 2 | ✅ auto | Redundant open modes |
| UP035 | 2 | ✅ auto | Deprecated import |
| B007 | 1 | ❌ manual | Unused loop control variable |
| B017 | 1 | ❌ manual | assert-raises-exception |

### Ruff Configuration (pyproject.toml)

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["typer.Argument", "typer.Option"]
```

No per-file ignores configured. No rule exclusions.

### Fix Strategy — Ruff

**Step 1 — Safe auto-fix (resolves 969 of 1195):**
```bash
uv run ruff check . --fix
```
This resolves: W293 (869), W291 (99), F401 (45), I001 (28), W292 (20), F811 (12), F541 (4), UP015 (2), UP035 (2).

**Step 2 — Manual fixes for remaining ~114 errors:**

#### E501 (73 lines too long)

Files affected:
- `src/mower_rover/cli/jetson.py` — 23 occurrences (largest contributor)
- `tests/test_zone_sitl.py` — 9 occurrences
- `tests/test_zone_geojson.py` — 6 occurrences
- `src/mower_rover/cli/bringup.py` — 4 occurrences
- `tests/test_firmware.py` — 4 occurrences
- `tests/test_firmware_cli.py` — 4 occurrences
- `tests/test_zone_preflight.py` — 3 occurrences
- `tests/test_zone_planner.py` — 2 occurrences
- `src/mower_rover/mavlink/mission.py` — 2 occurrences
- `src/mower_rover/probe/checks/zone.py` — 3 occurrences
- Other files — 1-2 each

**Fix approach:** Line wrapping of long strings, f-strings, and function calls. Many will be format strings or log messages that can be split across multiple lines.

#### B904 (12 raise-without-from)

All in except blocks. Files:
- `src/mower_rover/cli/zone_laptop.py` — 8 occurrences (lines 85, 230, 314, 389, 397, 453, 464, 472)
- `src/mower_rover/cli/jetson.py` — 2 occurrences (lines 952, 1021)
- `src/mower_rover/pixhawk/firmware.py` — 2 occurrences (lines 355, 423)

**Fix:** Add `from err` or `from None` to each `raise` statement inside except clauses.

#### B905 (9 zip-without-explicit-strict)

- `src/mower_rover/zone/planner.py` — 3 (lines 90, 105, 114)
- `src/mower_rover/mavlink/mission.py` — 1 (line 385)
- `src/mower_rover/probe/checks/zone.py` — 1 (line 55)
- `tests/test_zone_planner.py` — 2 (lines 81, 449)
- `tests/test_zone_sitl.py` — 2 (lines 58, 95)

**Fix:** Add `strict=True` or `strict=False` parameter to each `zip()` call depending on whether lengths are guaranteed equal.

#### SIM105 (8 suppressible-exception)

- `src/mower_rover/cli/bringup.py` — 4 (lines 557, 1092, 1429, 1757) — suppress `SshError`
- `src/mower_rover/service/unit.py` — 2 (lines 191, 206) — suppress `CalledProcessError, FileNotFoundError, OSError`
- `tests/test_zone_sitl.py` — 2 (lines 106, 149) — suppress `Exception`

**Fix:** Replace `try: ... except XError: pass` with `with contextlib.suppress(XError):`. Import `contextlib` if not already present.

#### F841 (7 unused variables)

- `src/mower_rover/cli/bringup.py` lines 526, 1632 — `pkg_list`, `mavproxy_bin`
- `src/mower_rover/cli/jetson.py` line 1174 — `obj`
- `tests/test_bringup.py` line 1700 — `original_sleep`
- `tests/test_firmware_sitl.py` line 75 — `ack`
- `tests/test_kiosk_state.py` line 75 — `stop`
- `tests/test_zone_planner.py` line 165 — `exclusion_poly`

**Fix:** Remove unused assignment or replace with `_` if the call has side effects.

#### SIM102 (3 collapsible-if)

- `src/mower_rover/cli/jetson.py` lines 1388, 1583
- `src/mower_rover/kiosk/app.py` line 140

**Fix:** Merge nested `if` into single `if x and y:`.

#### B007 (1) + B017 (1)

- B007: `src/mower_rover/cli/bringup.py` line 1632 — rename `pass_num` to `_pass_num` or `_`
- B017: `tests/test_zone_planner.py` line 449 — use a more specific exception in `assertRaises`

### Key Discoveries

- 81% of all errors (969/1195) are trivially auto-fixable whitespace/import issues
- `jetson.py` is the single largest offender for both E501 and manual-fix rules
- No per-file ignores are configured — adding targeted ignores could be an alternative for test files

**Gaps:** None  
**Assumptions:** Auto-fix will not break tests (all tests currently pass)

## Phase 2: Mypy Error Analysis & Fix Strategy

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Current State

**Total errors:** 27 in 10 files  
**Mode:** `strict = true`

### Mypy Configuration (pyproject.toml)

```toml
[tool.mypy]
python_version = "3.11"
strict = true
files = ["src"]

[[tool.mypy.overrides]]
module = ["pymavlink.*", "pyubx2.*", "shapely.*", "pyproj.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["sdnotify.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["depthai.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["gi.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["mower_rover.vslam.ipc"]
warn_unused_ignores = false
```

### Error Catalog (All 27 Errors)

#### Category A: Missing type stubs (1 error)

| File | Line | Error | Fix |
|------|------|-------|-----|
| `pixhawk/firmware.py` | 11 | Library stubs not installed for "serial" [import-untyped] | Add `types-pyserial` to dev deps |

#### Category B: GTK4 "Any" base class (3 errors)

| File | Line | Error | Fix |
|------|------|-------|-----|
| `kiosk/dashboard.py` | 20 | Class cannot subclass "Frame" (has type "Any") [misc] | Add mypy override for this module |
| `kiosk/dashboard.py` | 100 | Class cannot subclass "ApplicationWindow" (has type "Any") [misc] | Same |
| `kiosk/dashboard.py` | 247 | Class cannot subclass "Application" (has type "Any") [misc] | Same |

**Root cause:** `gi.repository.Gtk4` has no type stubs. Classes imported from it have type `Any`, so subclassing triggers `[misc]`.  
**Best fix:** Add `[[tool.mypy.overrides]]` for `mower_rover.kiosk.dashboard` with `disallow_subclassing_any = false`.

#### Category C: firmware.py API call signature mismatches (8 errors)

| File | Line | Error | Fix |
|------|------|-------|-----|
| `cli/jetson.py` | 1338 | "download_firmware" gets multiple values for keyword argument "track" [misc] | Fix call order: `download_firmware(track, latest_tuple, cache_dir)` |
| `cli/jetson.py` | 1338 | Missing positional argument "cache_dir" in call to "download_firmware" [call-arg] | Same fix |
| `cli/jetson.py` | 1338 | Argument 1 has incompatible type "tuple[int,int,int]"; expected "str" [arg-type] | Same fix |
| `cli/jetson.py` | 1338 | Argument 2 has incompatible type "Path"; expected "tuple[int,int,int]" [arg-type] | Same fix |
| `cli/jetson.py` | 1349 | Argument 1 to "validate_apj" has incompatible type "Path \| None"; expected "Path" [arg-type] | Add `assert apj_path is not None` guard |
| `cli/jetson.py` | 1437 | Argument 2 to "flash_firmware" has incompatible type "Path \| None"; expected "Path" [arg-type] | Add `assert apj_path is not None` guard |
| `cli/jetson.py` | 1437 | Argument 3 has incompatible type "int"; expected "Callable[...] \| None" [arg-type] | Remove `BOARD_ID_CUBE_ORANGE` arg (not in signature) |
| `cli/jetson.py` | 1632 | Argument 3 to "flash_firmware" has incompatible type "int"; expected "Callable[...] \| None" [arg-type] | Same as above |

**Root cause:** `download_firmware(track, version, cache_dir)` is called as `download_firmware(latest_tuple, cache_dir, track=track)` — positional args are in wrong order. `flash_firmware(port, apj_path, progress_cb)` is called with `BOARD_ID_CUBE_ORANGE` as third arg (board ID validation was removed from the function signature but call sites not updated).

#### Category D: zone_laptop.py type annotations (5 errors)

| File | Line | Error | Fix |
|------|------|-------|-----|
| `cli/zone_laptop.py` | 49 | Function missing type annotation for params [no-untyped-def] | Add type annotations |
| `cli/zone_laptop.py` | 58 | Function missing type annotation [no-untyped-def] | Add type annotations |
| `cli/zone_laptop.py` | 88 | Function missing type annotation for params [no-untyped-def] | Add type annotations |
| `cli/zone_laptop.py` | 143 | Module has no attribute "ClickException" [attr-defined] | Fix import (likely `typer.Exit` not `click.ClickException`) |
| `cli/zone_laptop.py` | 270 | Call to untyped function "_upload_zone_atomically" [no-untyped-call] | Add type annotations to `_upload_zone_atomically` |

#### Category E: Miscellaneous type issues (10 errors)

| File | Line | Error | Fix |
|------|------|-------|-----|
| `zone/config.py` | 378 | Arg 1 to "check_latlng" incompatible type "RallyPoint"; expected "LatLon" [arg-type] | Add `LatLon` protocol or widen type |
| `vslam/lua_deploy.py` | 45 | "object" has no attribute "error_code" [attr-defined] | Narrow type from `object` to actual class |
| `vslam/lua_deploy.py` | 116 | Returning Any from function declared to return "bytes" [no-any-return] | Add cast or fix return type |
| `transport/ssh.py` | 227 | Item "None" of "IO[str] \| None" has no attribute "read" [union-attr] | Add `assert proc.stderr is not None` |
| `mavlink/mission.py` | 89 | Need type annotation for "items_sent" [var-annotated] | Add `items_sent: set[int] = set()` |
| `zone/geojson.py` | 15 | Missing type arguments for generic type "dict" [type-arg] | Add `dict[str, Any]` |
| `zone/geojson.py` | 142 | Missing type arguments for generic type "dict" [type-arg] | Same |
| `kiosk/app.py` | 291 | Unused "type: ignore" comment [unused-ignore] | Change `[assignment]` to `[method-assign]` |
| `cli/jetson.py` | 983 | Incompatible types: float assigned to int [assignment] | Use `int(...)` wrapper |
| `cli/jetson.py` | 1139 | Function missing type annotation [no-untyped-def] | Add type annotations |

### Fix Strategy — Mypy

**Quick wins (resolve 4 errors with config changes only):**
1. Add `types-pyserial` to `[project.optional-dependencies] dev` → fixes 1 error
2. Add mypy override for `mower_rover.kiosk.dashboard` → fixes 3 errors

**Call signature fixes (resolve 8 errors in jetson.py):**
3. Fix `download_firmware()` call at line 1338: swap argument order to `(track, latest_tuple, cache_dir)`
4. Remove `BOARD_ID_CUBE_ORANGE` from `flash_firmware()` calls at lines 1437 and 1632
5. Add `assert apj_path is not None` before `validate_apj(apj_path)` and `flash_firmware(...)` calls

**Type annotation additions (resolve remaining ~15):**
6. Add annotations to `zone_laptop.py` functions (lines 49, 58, 88)
7. Fix `ClickException` → `typer.Exit` at `zone_laptop.py:143`
8. Fix remaining issues one by one (all straightforward)

### Key Discoveries

- The largest cluster (8 errors) is a **runtime bug** in `jetson.py` — `download_firmware()` is called with args in the wrong order and `flash_firmware()` is called with a stale signature. These are real bugs, not just type noise.
- GTK4 type issues are environment-specific (no stubs available) — override is the correct fix.
- `types-pyserial` is a simple missing dev dependency.

**Gaps:** None  
**Assumptions:** The `download_firmware` call order bug may also be a runtime failure if that code path is exercised on the Jetson.

## Phase 3: Fix Execution Plan

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Ordered Fix Steps

Execute in this order to minimize churn and verify incrementally:

#### Step 1: Auto-fix whitespace/imports (resolves 969 errors)

```bash
uv run ruff check . --fix
uv run ruff check . --statistics  # verify ~114 remain
```

Commit: `style: auto-fix whitespace, imports, and trivial lint (ruff --fix)`

#### Step 2: Add `types-pyserial` to dev dependencies

In `pyproject.toml`, add `"types-pyserial"` to the `dev` extras list:

```toml
dev = [
    ...
    "types-pyserial",
]
```

Then: `uv sync --extra dev`

Commit: `fix(types): add types-pyserial for mypy serial stubs`

#### Step 3: Add mypy override for kiosk/dashboard.py

In `pyproject.toml`, add:

```toml
[[tool.mypy.overrides]]
module = ["mower_rover.kiosk.dashboard"]
disallow_subclassing_any = false
```

Commit: `fix(mypy): allow GTK4 Any subclassing in kiosk dashboard`

#### Step 4: Fix `download_firmware()` call signature in jetson.py

Line 1338: change from:
```python
apj_path = download_firmware(latest_tuple, cache_dir, track=track)
```
to:
```python
apj_path = download_firmware(track, latest_tuple, cache_dir)
```

This is a **real bug** — the function signature is `download_firmware(track, version, cache_dir)`.

#### Step 5: Fix `flash_firmware()` calls in jetson.py

Lines 1437 and 1632: remove the `BOARD_ID_CUBE_ORANGE` third argument:
```python
# Before:
flash_result = flash_firmware(bootloader_port, apj_path, BOARD_ID_CUBE_ORANGE)
# After:
flash_result = flash_firmware(bootloader_port, apj_path)
```

The function signature is `flash_firmware(port, apj_path, progress_cb=None)` — board ID is validated inside the function, not passed as an argument.

#### Step 6: Add None guards for `apj_path`

Before `validate_apj(apj_path)` at line ~1349 and before `flash_firmware(...)` calls, add:
```python
if apj_path is None:
    raise typer.Exit(code=1)
```

#### Step 7: Fix remaining mypy issues (15 errors)

| File | Fix |
|------|-----|
| `cli/jetson.py:983` | `int(value)` instead of bare assignment |
| `cli/jetson.py:1139` | Add parameter type annotations |
| `cli/zone_laptop.py:49,58,88` | Add parameter type annotations to 3 functions |
| `cli/zone_laptop.py:143` | Fix `ClickException` → `typer.Exit` |
| `zone/config.py:378` | Widen `check_latlng` param type or add protocol |
| `vslam/lua_deploy.py:45` | Narrow exception type or cast |
| `vslam/lua_deploy.py:116` | Add explicit return type or cast |
| `transport/ssh.py:227` | Add `assert proc.stderr is not None` |
| `mavlink/mission.py:89` | Add `items_sent: set[int] = set()` |
| `zone/geojson.py:15,142` | Change `dict` → `dict[str, Any]` |
| `kiosk/app.py:291` | Change `# type: ignore[assignment]` → `# type: ignore[method-assign]` |

#### Step 8: Fix remaining ruff manual errors (~114)

Order by easiest/most impactful:

1. **B904 (12):** Add `from err` / `from None` to raises in except blocks
2. **SIM105 (8):** Replace try/except/pass → `contextlib.suppress()`
3. **F841 (7):** Remove unused variable assignments
4. **B905 (9):** Add `strict=True` or `strict=False` to `zip()` calls
5. **SIM102 (3):** Merge nested `if` statements
6. **B007 (1):** Rename `pass_num` → `_`
7. **B017 (1):** Use specific exception in `assertRaises`
8. **E501 (73):** Line wrapping — do last as it's highest volume/lowest impact

#### Step 9: Verify CI locally

```bash
uv run ruff check .          # should be 0 errors
uv run mypy                  # should be 0 errors
uv run pytest -m "not field and not sitl"  # should pass
```

Commit: `fix(ci): resolve all ruff and mypy errors for green CI`

### Alternative: Pragmatic Quick-Fix (CI Green Faster)

If the goal is CI green ASAP with minimal code changes, a subset approach:

1. Run `ruff check . --fix` (auto-fix 969)
2. Add `types-pyserial` and kiosk dashboard mypy overrides
3. Fix the firmware call bugs (Steps 4-6) — these are real bugs anyway
4. For the remaining ~114 ruff + ~15 mypy: add targeted `# noqa` / `# type: ignore` comments

This would get CI green in ~30 minutes but leave tech debt. **Not recommended** — the full fix is ~2-3 hours of straightforward work.

### Key Discoveries

- The highest-priority fix is the `download_firmware()` call signature bug — this is broken at runtime, not just a type error
- 81% of lint errors are auto-fixable in one command
- The E501 (line too long) errors are the largest manual effort but lowest risk

**Gaps:** None  
**Assumptions:** Tests will continue to pass after all fixes (they don't test the firmware update code path locally)

## Overview

CI fails on two of three steps: **ruff** (1195 lint errors) and **mypy** (27 type errors). Tests pass cleanly (826 passed). The root causes are accumulated whitespace/import lint from rapid feature development, plus a real runtime bug in the firmware update call signatures.

### Key Findings

1. **81% of lint errors are auto-fixable** — a single `ruff check . --fix` resolves 969 of 1195 errors
2. **Real bug discovered** — `download_firmware()` in `jetson.py:1338` is called with arguments in the wrong order (would fail at runtime)
3. **`flash_firmware()` signature drift** — called with a `BOARD_ID` argument that was removed from the function signature
4. **GTK4 type stubs unavailable** — 3 mypy errors are environment artifacts requiring a config override
5. **Missing `types-pyserial` dependency** — simple addition to dev deps

### Recommended Fix Order

1. `ruff check . --fix` (auto-fix 969 errors in seconds)
2. Config changes: add `types-pyserial`, add mypy kiosk override
3. Fix firmware API call bugs (real runtime bugs)
4. Add type annotations and remaining manual lint fixes
5. Run full verification: `ruff check . && mypy && pytest -m "not field and not sitl"`

### Risk Assessment

| Fix Category | Risk | Impact |
|--------------|------|--------|
| Auto-fix whitespace/imports | Very Low | 969 errors resolved |
| Config changes (stubs, overrides) | None | 4 errors resolved |
| Firmware call signature fixes | **Medium** — real bug fix | 8 errors + runtime correctness |
| Type annotations | Low | 15 errors resolved |
| Line wrapping (E501) | Very Low | 73 errors resolved |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-05 |
| Status | 🔄 In Progress |
| Current Phase | 1 |
| Path | /docs/research/022-ci-yml-failures-and-fixes.md |
