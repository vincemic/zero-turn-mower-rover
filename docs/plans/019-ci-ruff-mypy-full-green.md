---
id: "019"
type: plan
title: "CI Full Green — Ruff & Mypy Fix Execution"
status: ✅ Complete
created: "2026-05-05"
updated: "2026-05-05"
completed: "2026-05-05"
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-05 | pch-planner | Initial plan creation |
| v2.0 | 2026-05-05 | pch-planner | Holistic review completed; all sections populated || v2.1 | 2026-05-05 | pch-plan-reviewer | Review: fixed Step 3.7 (local var capture), added Step 2.6 (import cleanup) |
## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 2  
**Last Updated:** 2026-05-05

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | transport/ssh.py Step 3.7 fix is wrong — assert already exists; mypy lambda narrowing needs local variable | correctness | Option A: Local variable capture | Step 3.7 updated |
| 2 | Unused BOARD_ID_CUBE_ORANGE imports after flash_firmware fix | completeness | Option A: Add explicit import-removal step to Phase 2 | Step 2.6 added, old 2.6→2.7 |

## Introduction

Execute the fix strategy from [research 022](../research/022-ci-yml-failures-and-fixes.md) to resolve all 1195 ruff lint errors and 27 mypy type errors in CI. Tests already pass (826 passed). This plan is purely mechanical — applying auto-fixes, correcting real call-signature bugs, adding type annotations, and making config additions.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|---------------|--------|-----------|
| 1 | E501 line-too-long strategy | C — Per-file override for tests | Test files have long assertions/data that read better unwrapped; config ignores `tests/**` E501; manually wrap only ~43 production code violations |

## Holistic Review

### Decision Interactions

Only one decision was needed (E501 strategy). The per-file test ignore interacts positively with the auto-fix step — `ruff --fix` handles whitespace/import errors in tests, while E501 is simply not enforced there. No conflicts.

### Architectural Considerations

- The `download_firmware()` call-signature fix (Phase 2, Step 4) is a **real runtime bug** — if the firmware update path is exercised on the Jetson, it would fail with a type error. Fixing this is both a CI fix and a correctness fix.
- The `flash_firmware()` stale argument removal is also a real bug — `BOARD_ID_CUBE_ORANGE` was passed as a positional arg where `progress_cb` is expected.
- All other changes are cosmetic (whitespace, annotations, config).

### Trade-offs Accepted

- E501 not enforced in `tests/**` — long test lines are acceptable for readability
- `disallow_subclassing_any = false` for `kiosk.dashboard` — GTK4 has no type stubs, override is the standard solution
- `warn_unused_ignores = false` already exists for `vslam.ipc` — no new precedent

## Overview

### Objectives

1. Resolve all 1195 ruff lint errors (969 auto-fixable + 114 manual + 12 line-too-long exemptions)
2. Resolve all 27 mypy type errors
3. Fix the real runtime bug in `download_firmware()` call signature
4. Maintain all 826 tests passing
5. Achieve fully green CI on both `ubuntu-latest` and `windows-latest`

### Source Research

[docs/research/022-ci-yml-failures-and-fixes.md](../research/022-ci-yml-failures-and-fixes.md)

## Requirements

### Functional

- All `ruff check .` errors resolved (zero exit)
- All `mypy` errors resolved (zero exit)
- All `pytest -m "not field and not sitl"` tests continue to pass

### Non-Functional

- Minimal behavioral code changes — whitespace, imports, annotations, and config only (except the firmware call-signature bug which is a real fix)
- No new dependencies beyond `types-pyserial` in dev extras

### Out of Scope

- Adding new tests for the firmware call path (covered by plan 018)
- Refactoring any module beyond what is needed to fix the specific errors
- Changing ruff or mypy configuration to suppress errors (except the GTK4 kiosk override which is the correct fix)

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Mypy overrides for untyped third-party
    location: "pyproject.toml [[tool.mypy.overrides]]"
    usage: Add kiosk.dashboard override for GTK4 Any subclassing
  - pattern: Typer CLI error handling
    location: "src/mower_rover/cli/*.py"
    usage: Use `raise typer.Exit(code=1)` for unrecoverable errors
  - pattern: structlog logging
    location: "src/mower_rover/**/*.py"
    usage: All modules use get_logger() from logging_setup
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Key Technical Decisions

1. **E501 in tests suppressed via config** — `[tool.ruff.lint.per-file-ignores] "tests/**" = ["E501"]` in `pyproject.toml`
2. **GTK4 subclassing override** — `disallow_subclassing_any = false` for `mower_rover.kiosk.dashboard`
3. **Real bug fixes** — `download_firmware()` arg order and `flash_firmware()` stale `BOARD_ID` arg are runtime bugs, not just type noise
4. **`types-pyserial` added to dev deps** — provides serial port type stubs for mypy

## Dependencies

- Research 022 (complete) — provides the full error catalog and fix strategy
- `types-pyserial` package available on PyPI
- All 826 tests currently passing as baseline

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `ruff --fix` auto-fix breaks tests | Very Low | Medium | Run full test suite after auto-fix step |
| `download_firmware()` arg reorder introduces new bug | Low | High | Verify against function signature; code path untested locally anyway |
| E501 line wrapping changes semantics | Very Low | Low | Only wrap strings/calls, verify tests pass |

## Execution Plan

### Phase 1: Auto-fix & Config Changes

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 1 (pyproject.toml) + auto-fix touches many files  
**Prerequisites:** None  
**Entry Point:** `pyproject.toml`  
**Verification:** `uv run ruff check . --statistics` shows only manual-fix rules remaining

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Run `uv run ruff check . --fix` to auto-fix 969 whitespace/import errors | All `src/` and `tests/` files | Auto-fix completes without error; ~114 errors remain |
| 1.2 | Add `types-pyserial` to `[project.optional-dependencies] dev` | `pyproject.toml` | `"types-pyserial"` present in dev list |
| 1.3 | Add mypy override for `mower_rover.kiosk.dashboard` with `disallow_subclassing_any = false` | `pyproject.toml` | New `[[tool.mypy.overrides]]` block after existing overrides |
| 1.4 | Add `[tool.ruff.lint.per-file-ignores]` with `"tests/**" = ["E501"]` | `pyproject.toml` | E501 no longer reported for test files |
| 1.5 | Run `uv sync --extra dev` to install new stub package | N/A (environment) | `types-pyserial` installed in .venv |
| 1.6 | Verify: `uv run ruff check . --statistics` and `uv run mypy` | N/A | Ruff shows only manual-fix rules in `src/`; mypy errors reduced from 27 to ~23 |

**Commit:** `fix(ci): auto-fix lint, add types-pyserial, add mypy/ruff config overrides`

### Phase 2: Firmware Call-Signature Bug Fixes

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 1 (`src/mower_rover/cli/jetson.py`)  
**Prerequisites:** Phase 1 complete  
**Entry Point:** `src/mower_rover/cli/jetson.py`  
**Verification:** `uv run mypy src/mower_rover/cli/jetson.py` shows reduced errors

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Fix `download_firmware()` call at line ~1338: change `download_firmware(latest_tuple, cache_dir, track=track)` → `download_firmware(track, latest_tuple, cache_dir)` | `src/mower_rover/cli/jetson.py` | Positional args match signature `(track: str, version: tuple, cache_dir: Path)` |
| 2.2 | Fix first `flash_firmware()` call at line ~1437: remove `BOARD_ID_CUBE_ORANGE` third arg → `flash_firmware(bootloader_port, apj_path)` | `src/mower_rover/cli/jetson.py` | Call matches signature `(port, apj_path, progress_cb=None)` |
| 2.3 | Fix second `flash_firmware()` call at line ~1632: same removal of `BOARD_ID_CUBE_ORANGE` | `src/mower_rover/cli/jetson.py` | Call matches signature |
| 2.4 | Add `if apj_path is None: raise typer.Exit(code=1)` guard before `validate_apj(apj_path)` at line ~1349 | `src/mower_rover/cli/jetson.py` | mypy `[arg-type]` error for `Path \| None` resolved |
| 2.5 | Add same None guard before first `flash_firmware(bootloader_port, apj_path)` call if `apj_path` could be None at that point | `src/mower_rover/cli/jetson.py` | No `Path \| None` passed where `Path` expected |
| 2.6 | Remove `BOARD_ID_CUBE_ORANGE` from import blocks at lines ~1267 and ~1509 (now unused after Steps 2.2–2.3) | `src/mower_rover/cli/jetson.py` | No F401 unused-import for `BOARD_ID_CUBE_ORANGE`; ruff clean on this file |
| 2.7 | Verify: `uv run mypy src/mower_rover/cli/jetson.py` | N/A | All 8 firmware-related mypy errors resolved |

**Commit:** `fix(firmware): correct download_firmware/flash_firmware call signatures`

### Phase 3: Remaining Mypy Fixes

**Status:** ✅ Complete  
**Size:** Medium  
**Files to Modify:** 8  
**Prerequisites:** Phase 2 complete  
**Entry Point:** `src/mower_rover/cli/jetson.py` (remaining issues)  
**Verification:** `uv run mypy` exits 0

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | `jetson.py:983` — wrap float→int assignment with `int(...)` | `src/mower_rover/cli/jetson.py` | No `[assignment]` error on that line |
| 3.2 | `jetson.py:1139` — add type annotations to untyped function `_check_not_armed` | `src/mower_rover/cli/jetson.py` | No `[no-untyped-def]` error |
| 3.3 | `zone_laptop.py:49,58,88` — add parameter type annotations to `_check_not_armed`, `_upload_zone_atomically`, and `_write_zone_snapshot` | `src/mower_rover/cli/zone_laptop.py` | No `[no-untyped-def]` or `[no-untyped-call]` errors |
| 3.4 | `zone_laptop.py:143` — fix `typer.ClickException` → `typer.Exit` or proper import | `src/mower_rover/cli/zone_laptop.py` | No `[attr-defined]` error |
| 3.5 | `zone/config.py:378` — widen `check_latlng` param to accept `RallyPoint` (add protocol or union) | `src/mower_rover/zone/config.py` | No `[arg-type]` error |
| 3.6 | `vslam/lua_deploy.py:45` — narrow type from `object` to actual exception class; `:116` — fix `no-any-return` | `src/mower_rover/vslam/lua_deploy.py` | No `[attr-defined]` or `[no-any-return]` errors |
| 3.7 | `transport/ssh.py:226` — inside `_drain_stderr()`, assign `err = proc.stderr` after the existing assert and use `err.read(4096)` in the `iter(lambda:...)` call (mypy cannot narrow through closures/lambdas; the assert already exists at line 226 but doesn't help the lambda) | `src/mower_rover/transport/ssh.py` | No `[union-attr]` error |
| 3.8 | `mavlink/mission.py:89` — add type annotation `items_sent: set[int] = set()` | `src/mower_rover/mavlink/mission.py` | No `[var-annotated]` error |
| 3.9 | `zone/geojson.py:15,142` — change bare `dict` → `dict[str, Any]` | `src/mower_rover/zone/geojson.py` | No `[type-arg]` errors |
| 3.10 | `kiosk/app.py:291` — change `# type: ignore[assignment]` → `# type: ignore[method-assign]` | `src/mower_rover/kiosk/app.py` | No `[unused-ignore]` error |
| 3.11 | Verify: `uv run mypy` exits 0 | N/A | Zero mypy errors |

**Commit:** `fix(mypy): resolve all remaining type errors`

### Phase 4: Manual Ruff Fixes (Non-E501)

**Status:** ✅ Complete  
**Size:** Medium  
**Files to Modify:** ~10  
**Prerequisites:** Phase 1 complete (auto-fix applied)  
**Entry Point:** `src/mower_rover/cli/zone_laptop.py` (highest B904 count)  
**Verification:** `uv run ruff check . --statistics` shows only E501 in `src/` files

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | B904 (12): Add `from err` or `from None` to all `raise` statements inside except blocks | `src/mower_rover/cli/zone_laptop.py` (8), `src/mower_rover/cli/jetson.py` (2), `src/mower_rover/pixhawk/firmware.py` (2) | Zero B904 errors |
| 4.2 | SIM105 (8): Replace `try: ... except XError: pass` with `contextlib.suppress(XError)` | `src/mower_rover/cli/bringup.py` (4), `src/mower_rover/service/unit.py` (2), `tests/test_zone_sitl.py` (2) | Zero SIM105 errors |
| 4.3 | F841 (7): Remove or replace unused variable assignments with `_` | `src/mower_rover/cli/bringup.py` (2), `src/mower_rover/cli/jetson.py` (1), `tests/test_bringup.py` (1), `tests/test_firmware_sitl.py` (1), `tests/test_kiosk_state.py` (1), `tests/test_zone_planner.py` (1) | Zero F841 errors |
| 4.4 | B905 (9): Add `strict=True` or `strict=False` to `zip()` calls | `src/mower_rover/zone/planner.py` (3), `src/mower_rover/mavlink/mission.py` (1), `src/mower_rover/probe/checks/zone.py` (1), `tests/test_zone_planner.py` (2), `tests/test_zone_sitl.py` (2) | Zero B905 errors |
| 4.5 | SIM102 (3): Merge nested `if` statements into single `if x and y:` | `src/mower_rover/cli/jetson.py` (2), `src/mower_rover/kiosk/app.py` (1) | Zero SIM102 errors |
| 4.6 | B007 (1): Rename `pass_num` → `_` in bringup.py:1632 | `src/mower_rover/cli/bringup.py` | Zero B007 errors |
| 4.7 | B017 (1): Use more specific exception in `assertRaises` | `tests/test_zone_planner.py` | Zero B017 errors |
| 4.8 | Verify: `uv run ruff check . --statistics` shows only E501 in `src/` | N/A | Only E501 remains |

**Commit:** `fix(lint): resolve B904, SIM105, F841, B905, SIM102, B007, B017`

### Phase 5: E501 Line Wrapping (Production Code Only)

**Status:** ✅ Complete  
**Size:** Medium  
**Files to Modify:** ~10 production files  
**Prerequisites:** Phase 4 complete  
**Entry Point:** `src/mower_rover/cli/jetson.py` (23 occurrences — largest)  
**Verification:** `uv run ruff check .` exits 0

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Wrap long lines in `src/mower_rover/cli/jetson.py` (23 lines) — split f-strings, function calls, log messages | `src/mower_rover/cli/jetson.py` | Zero E501 in this file |
| 5.2 | Wrap long lines in `src/mower_rover/cli/bringup.py` (4 lines) | `src/mower_rover/cli/bringup.py` | Zero E501 in this file |
| 5.3 | Wrap long lines in `src/mower_rover/mavlink/mission.py` (2 lines) | `src/mower_rover/mavlink/mission.py` | Zero E501 in this file |
| 5.4 | Wrap long lines in `src/mower_rover/probe/checks/zone.py` (3 lines) | `src/mower_rover/probe/checks/zone.py` | Zero E501 in this file |
| 5.5 | Wrap long lines in remaining `src/` files (1-2 per file) | Various `src/` files | Zero E501 in any `src/` file |
| 5.6 | Final verification: `uv run ruff check .` exits 0 | N/A | Zero ruff errors anywhere |

**Commit:** `style: wrap long lines in production code (E501)`

### Phase 6: Final Verification & CI Commit

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 0 (verification only)  
**Prerequisites:** Phases 1–5 complete  
**Entry Point:** N/A  
**Verification:** All three CI steps pass locally

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 6.1 | Run `uv run ruff check .` — must exit 0 | N/A | Zero errors |
| 6.2 | Run `uv run mypy` — must exit 0 | N/A | Zero errors |
| 6.3 | Run `uv run pytest -m "not field and not sitl"` — all 826+ tests pass | N/A | All tests pass, exit 0 |
| 6.4 | Push to trigger CI; verify green on both `ubuntu-latest` and `windows-latest` | N/A | CI badge green |

**Commit:** Final push (all changes from Phases 1-5 may be squashed or kept as separate commits per implementor preference)

## Standards

No organizational standards applicable to this plan.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-05 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-05 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/019-ci-ruff-mypy-full-green.md |

## Review Summary

**Review Date:** 2026-05-05  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 4 (Critical: 0, Major: 2, Minor: 2)
- Clarifying Questions Asked: 2
- Sections Updated: Phase 2 (Step 2.6 added), Phase 3 (Step 3.7 rewritten)

### Key Improvements Made
1. **Step 3.7 corrected** — The assert already existed; real fix is local variable capture for mypy lambda narrowing
2. **Step 2.6 added** — Explicit removal of `BOARD_ID_CUBE_ORANGE` imports that become unused after call-signature fixes

### Minor Notes for Implementer
- Step 2.5 ("if `apj_path` could be None") — verify whether the None guard is actually needed at that point given Step 2.4 already narrows before `validate_apj`. If the code flow guarantees non-None by line 1437, skip this step.
- Step 3.6 (`lua_deploy.py:45`) — the parameter `ret: object` should be narrowed to the actual MAVLink FTP result class (likely `pymavlink.mavftp.FTPReply` or similar). Check `pymavlink.mavftp` for the correct type.

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.
