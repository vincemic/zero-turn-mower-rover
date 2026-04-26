---
id: "011"
type: plan
title: "CI Lint & Type-Check Fixes — Round 2 + Pre-commit Gate"
status: ✅ Complete
created: "2026-04-26"
updated: "2026-04-26"
completed: "2026-04-26"
owner: pch-planner
version: v2.0
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-26 | pch-planner | Initial plan creation |
| v1.1 | 2026-04-26 | pch-plan-reviewer | Review fixes: corrected no-any-return fix (Step 2.5), preserved Callable type in B023 fix (Step 2.4), updated pre-commit rev to v0.15.11 (Step 4.2), clarified mypy verification scope (Step 4.3), disambiguated file paths (Step 1.1) |
| v2.0 | 2026-04-26 | pch-coder | Implementation complete — all 4 phases executed, all checks passing |

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 0
**Last Updated:** 2026-04-26

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | Step 2.5: `no-any-return` not fixed by type arg alone | correctness | Corrected: add typed intermediate variable | Step 2.5 rewritten |
| 2 | Step 2.4: B023 fix regressed Callable type safety | correctness | Corrected: preserve original Callable type | Step 2.4 rewritten |
| 3 | Step 4.2: pre-commit rev v0.5.0 stale (installed is v0.15.11) | specificity | Corrected: use v0.15.11 | Step 4.2 updated |
| 4 | Step 4.3: mypy verification scope ambiguous | clarity | Clarified: `uv run mypy` matches CI (`src/` only) | Step 4.3 updated |
| 5 | Step 1.1: ambiguous `vslam.py` file reference | clarity | Corrected: use `probe/checks/vslam.py` | Step 1.1 updated |

## Introduction

CI is failing on `ruff check` and `mypy` steps after feature commits for plans 005, 008, and 010. All 475 pytest tests pass; only lint and type-check steps fail. This plan fixes all 28 errors (20 Ruff + 8 Mypy) catalogued in [research 012](../research/012-ci-lint-typecheck-failures-round2.md) and adds a `.pre-commit-config.yaml` to prevent future regressions — the root cause identified by the research.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Include pre-commit hooks? | Yes — add `.pre-commit-config.yaml` with Ruff hooks | Prevents recurring CI lint failures; root cause was absence of local lint gates |

## Holistic Review

### Decision Interactions

All fixes are deterministic and non-interacting — formatting, imports, type annotations, and config only. The pre-commit addition is orthogonal to the error fixes.

### Architectural Considerations

- **No behavioral changes:** Every fix is formatting, imports, config, or type annotations. No function signatures, return values, or control flow change.
- **B023 fix (bringup.py:1538):** Binding `errors` as a default argument is the standard Python pattern for capturing loop variables in closures. This fixes a real concurrency bug risk.
- **AF_UNIX type ignore (ipc.py:111):** Appropriate since the IPC module is Jetson-only (Linux). Adding a comment explaining the platform constraint.

### Trade-offs Accepted

- Using `# type: ignore[attr-defined]` for `AF_UNIX` rather than a runtime `hasattr` guard, since the module is Linux-only and the guard would add dead code on the only target platform.

### Risks Acknowledged

- Minimal. All fixes are well-characterized in research 012 and verified by running the same CI commands locally.

## Overview

### Feature Summary

Fix all 28 CI-blocking lint (Ruff) and type-check (Mypy) errors and add a `.pre-commit-config.yaml` with Ruff hooks to prevent future regressions.

### Objectives

1. Zero Ruff errors on `uv run ruff check .`
2. Zero Mypy errors on `uv run mypy`
3. All 475 pytest tests continue to pass
4. `.pre-commit-config.yaml` gates `ruff check --fix` and `ruff format` locally

## Requirements

### Functional

- Fix all 20 Ruff errors (7 safe auto-fix, 2 unsafe auto-fix, 11 manual)
- Fix all 8 Mypy errors (5 unused-ignore removals, 1 type annotation, 1 return type, 1 platform guard)
- Add `.pre-commit-config.yaml` with Ruff check and format hooks

### Non-Functional

- No logic changes — only formatting, imports, type annotations, and config
- All existing tests must continue to pass

### Out of Scope

- Branch protection rules (infrastructure change, not code)
- CI workflow modifications (current CI config is correct)
- Adding `ruff format --check` to CI (no formatting issues were flagged)

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: "contextlib.suppress for expected exceptions"
    location: "src/mower_rover/cli/bringup.py:608"
    usage: "Already used in file; extend to lines 317, 1181"
  - pattern: "type: ignore with error code comments"
    location: "src/mower_rover/vslam/lua_deploy.py:56-58"
    usage: "Follow existing pattern for AF_UNIX ignore"
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Files Modified

| File | Ruff Fixes | Mypy Fixes | Total |
|------|------------|------------|-------|
| `src/mower_rover/cli/bringup.py` | 10 | 2 | 12 |
| `tests/test_bringup.py` | 6 | 0 | 6 |
| `src/mower_rover/vslam/health_listener.py` | 0 | 3 | 3 |
| `src/mower_rover/cli/backup.py` | 1 | 0 | 1 |
| `src/mower_rover/probe/checks/vslam.py` | 1 | 0 | 1 |
| `tests/test_probe_service.py` | 1 | 0 | 1 |
| `tests/test_probe_vslam.py` | 1 | 0 | 1 |
| `src/mower_rover/vslam/lua_deploy.py` | 0 | 1 | 1 |
| `src/mower_rover/vslam/ipc.py` | 0 | 1 | 1 |
| `src/mower_rover/probe/checks/oakd.py` | 0 | 1 | 1 |
| `.pre-commit-config.yaml` (new) | — | — | — |

## Dependencies

- Research 012 (complete) — provides the error catalogue and fix specifications
- `pre-commit` Python package — added to `[project.optional-dependencies] dev`

## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Auto-fix breaks test | Low | Very Low | Run pytest after auto-fix step |
| Unsafe-fix changes semantics | Low | Very Low | Both unsafe fixes verified safe in research 012 |

## Execution Plan

### Phase 1: Auto-fix Ruff Errors + Verify

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 6 (auto-touched by ruff)
**Prerequisites:** None
**Entry Point:** Repository root
**Verification:** `uv run ruff check .` shows fewer than 20 errors remaining

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Run `uv run ruff check . --fix` | Auto: `cli/backup.py`, `probe/checks/vslam.py`, `tests/test_bringup.py`, `tests/test_probe_service.py`, `tests/test_probe_vslam.py` | 7 safe-fix errors resolved (F401×3, UP041×2, I001×2) |
| 1.2 | Run `uv run ruff check . --fix --unsafe-fixes` | Auto: `bringup.py` | 2 additional errors resolved (SIM105 line 597, F841 line 1514) |
| 1.3 | Run `uv run pytest -m "not field and not sitl"` | — | All 475 tests pass |

### Phase 2: Manual Ruff Fixes in `bringup.py`

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 1
**Prerequisites:** Phase 1 complete
**Entry Point:** `src/mower_rover/cli/bringup.py`
**Verification:** Phase 1 auto-fixes applied; `uv run ruff check src/mower_rover/cli/bringup.py` shows only E501 and manual SIM fixes remaining

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | **SIM103 ×2 (lines 149, 157):** Collapse `if cond: return False; return True` → `return not (cond)` in `_clear_host_key_needed()`. Lines 148–154: replace the `if (...): return False; return True` block with `return not ("remote host identification has changed" in stderr_lower or "host key verification failed" in stderr_lower)`. Lines 155–161: same pattern in the `except SshError` branch — replace with `return not ("remote host identification has changed" in msg or "host key verification failed" in msg)`. | `src/mower_rover/cli/bringup.py` | `ruff check` reports no SIM103 errors |
| 2.2 | **SIM105 ×2 (lines 317, 1181):** Convert `try: client.run(["sudo", "reboot"], timeout=10); except SshError: pass` → `with contextlib.suppress(SshError): client.run(["sudo", "reboot"], timeout=10)`. `contextlib` is already imported in this file. Apply at both `_run_reboot_and_wait()` (line 317) and `_run_final_verify()` (line 1181). | `src/mower_rover/cli/bringup.py` | `ruff check` reports no SIM105 errors |
| 2.3 | **E501 ×3 (lines 483, 545, 624):** All three are long f-strings embedding JSON echo in shell commands. Extract the JSON template string to a local variable (e.g., `json_tpl = f'{{"component":"rtabmap","version":"{tag}",...}}'`) and reference it in the shell command string to keep lines ≤100 chars. Line 483: `rtabmap.json` echo. Line 545: `depthai.json` echo. Line 624: `slam_node.json` echo. | `src/mower_rover/cli/bringup.py` | `ruff check` reports no E501 errors in this file |
| 2.4 | **B023 (line 1538):** Add `errors` as a default argument to the nested `_run_in_thread()` function to bind the loop variable at definition time. Change the signature from `def _run_in_thread(name: str, run_fn: Callable[[JetsonClient, BringupContext], None]) -> None:` to `def _run_in_thread(name: str, run_fn: Callable[[JetsonClient, BringupContext], None], errors: list[tuple[str, str]] = errors) -> None:`. Preserve the original `Callable[[JetsonClient, BringupContext], None]` type annotation — do NOT change it to `Callable[..., None]`. | `src/mower_rover/cli/bringup.py` | `ruff check` reports no B023 errors |
| 2.5 | **Mypy: type annotation + no-any-return (lines 366, 372):** (a) Add `from typing import Any` to the imports (line 28 area). (b) Change the return type on line 366 from `dict \| None` → `dict[str, Any] \| None`. (c) Fix `no-any-return` at line 372: `json.loads()` returns `Any`, so assign to a typed intermediate variable before returning: `parsed: dict[str, Any] = _json.loads(result.stdout)` then `return parsed`. Without this, mypy strict's `no-any-return` still fires because `Any` is being returned from a non-`Any` return type. | `src/mower_rover/cli/bringup.py` | `mypy` reports no errors for this file |

### Phase 3: Manual Ruff Fixes in `test_bringup.py` + Mypy Fixes

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 5
**Prerequisites:** Phase 2 complete
**Entry Point:** `tests/test_bringup.py`
**Verification:** `uv run ruff check .` shows 0 errors; `uv run mypy` shows 0 errors

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | **E501 ×3 in test_bringup.py:** Line 181: wrap `test_returns_false_on_host_key_verification_failed_in_result` — shorten method name or wrap args across lines. Line 223: break `patch("mower_rover.cli.bringup.subprocess.run", side_effect=FileNotFoundError("ssh-keygen"))` across lines. Line 322: wrap `test_timeout_if_jetson_never_comes_back` method def or args. | `tests/test_bringup.py` | `ruff check tests/test_bringup.py` reports 0 errors |
| 3.2 | **Mypy: remove unused `type: ignore[arg-type]`** at line 55 of `lua_deploy.py`. Delete `# type: ignore[arg-type]` from the `mavftp.MAVFTP(conn, ...)` call — the `[attr-defined]` ignores on lines 56–57 remain. | `src/mower_rover/vslam/lua_deploy.py` | `mypy` reports no errors for this file |
| 3.3 | **Mypy: remove unused `type: ignore[import-untyped]`** at line 36 of `oakd.py`. Delete the `# type: ignore[import-untyped]` from `import depthai as dai` — `pyproject.toml` already has `ignore_missing_imports = true` for `depthai.*`. | `src/mower_rover/probe/checks/oakd.py` | `mypy` reports no errors for this file |
| 3.4 | **Mypy: remove 3× unused `type: ignore[attr-defined]`** in `health_listener.py` at lines 60, 66, 73. Delete `# type: ignore[attr-defined]` from `msg.get_srcComponent()`, `msg.name`, and `msg.value`. The `pymavlink.*` override in `pyproject.toml` makes these unnecessary. | `src/mower_rover/vslam/health_listener.py` | `mypy` reports no errors for this file |
| 3.5 | **Mypy: AF_UNIX platform guard** in `ipc.py` line 111. Add `# type: ignore[attr-defined]  # AF_UNIX is Linux-only; this module runs on Jetson` to the `socket.socket(socket.AF_UNIX, ...)` line. | `src/mower_rover/vslam/ipc.py` | `mypy` reports no errors for this file |

### Phase 4: Add Pre-commit + Final Verification

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2 (new `.pre-commit-config.yaml`, edit `pyproject.toml`)
**Prerequisites:** Phases 1–3 complete
**Entry Point:** Repository root
**Verification:** `uv run ruff check .` = 0 errors; `uv run mypy` = 0 errors; `uv run pytest -m "not field and not sitl"` = all pass

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | **Add `pre-commit` to dev dependencies** in `pyproject.toml` under `[project.optional-dependencies] dev`. Add `"pre-commit>=3.7"`. | `pyproject.toml` | `uv sync --extra dev` installs pre-commit |
| 4.2 | **Create `.pre-commit-config.yaml`** at repository root with Ruff mirror hooks for `ruff-check` (with `--fix`) and `ruff-format`. Use `rev: v0.15.11` matching the currently installed Ruff version. Config: `repos: [{repo: https://github.com/astral-sh/ruff-pre-commit, rev: v0.15.11, hooks: [{id: ruff, args: [--fix]}, {id: ruff-format}]}]` | `.pre-commit-config.yaml` (new) | File exists and is valid YAML |
| 4.3 | **Final verification:** Run `uv run ruff check .` (0 errors), `uv run mypy` (0 errors — this checks `src/` only per `pyproject.toml [tool.mypy] files = ["src"]`, matching CI), `uv run pytest -m "not field and not sitl"` (all 475 pass). Note: `uv run mypy .` (with `.` arg) will show additional test-file errors that are out of scope for CI. | — | All three commands pass cleanly |

## Standards

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 11 files, but all are small single-point edits |
| New patterns introduced | 1 | No new patterns; extends existing `contextlib.suppress` usage |
| External dependencies | 1 | `pre-commit` added to dev deps only |
| Migration complexity | 1 | No migrations; all reversible text edits |
| Test coverage required | 1 | Existing 475 tests cover all affected code; no new tests needed |
| **Overall Complexity** | **6/25** | **Low** |

## Review Summary

**Review Date:** 2026-04-26
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v1.0
**Reviewed Plan Version:** v1.1

### Review Metrics
- Issues Found: 5 (Critical: 1, Major: 2, Minor: 2)
- Clarifying Questions Asked: 0
- Sections Updated: Steps 1.1, 2.4, 2.5, 4.2, 4.3

### Key Improvements Made
1. **Fixed incorrect `no-any-return` resolution (Critical):** The original plan claimed changing `dict | None` → `dict[str, Any] | None` would resolve both `type-arg` and `no-any-return`. This is wrong — `json.loads()` returns `Any`, so a typed intermediate variable is needed. Step 2.5 rewritten with correct fix.
2. **Preserved `Callable` type safety in B023 fix (Major):** The original example changed `Callable[[JetsonClient, BringupContext], None]` to `Callable[..., None]`, losing type safety. Step 2.4 corrected to preserve the original type annotation.
3. **Updated pre-commit `rev` to match installed Ruff (Major):** Changed from stale `v0.5.0` to actual installed `v0.15.11` to prevent rule mismatches.
4. **Clarified mypy verification scope:** Documented that `uv run mypy` (no args) checks `src/` only per `pyproject.toml`, matching CI. `uv run mypy .` shows 22 additional test-file errors that are out of scope for CI.
5. **Disambiguated file paths:** Changed `vslam.py` to `probe/checks/vslam.py` to avoid confusion with other `vslam/` modules.

### Remaining Considerations
- 22 mypy errors exist in test files (`tests/`) but are not checked by CI (`uv run mypy` uses `files = ["src"]`). These could be addressed in a follow-up task if desired.
- The `pre-commit` hook requires a one-time `uv run pre-commit install` after cloning. Consider documenting this in `README.md` or a `CONTRIBUTING.md`.

### Codebase Verification
- All file paths confirmed to exist
- All line numbers verified against current `HEAD`
- Ruff output (20 errors) matches plan exactly
- Mypy output (8 errors in `src/`) matches plan exactly
- `contextlib` already imported in `bringup.py` (confirmed line 27)
- No `from typing import Any` in `bringup.py` imports (needs adding per Step 2.5)

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-26 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-26 |
| Status | ✅ Complete |
| Implemented By | pch-coder |
| Plan Location | /docs/plans/011-ci-lint-typecheck-fixes-round2.md |
