---
id: "003"
type: plan
title: "CI Lint & Type-Check Fixes (Ruff + Mypy)"
status: ✅ Complete
created: "2026-04-22"
updated: "2026-04-22"
completed: "2026-04-22"
owner: pch-planner
version: v3.0
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-22 | pch-planner | Initial plan creation |
| v2.0 | 2026-04-22 | pch-planner | Holistic review completed; plan finalized |
| v2.1 | 2026-04-22 | pch-plan-reviewer | Review fixes: corrected SIM105 block reference, file/line counts, Phase 4 verification, type-ignore rationale |
| v3.0 | 2026-04-22 | pch-coder | Implementation complete — all 4 phases executed, all checks passing |

## Introduction

CI is failing on `ruff check` and `mypy` steps while all 175 pytest tests pass. This plan covers fixing all **28 Ruff errors** (14 auto-fixable, 14 manual) and **5 Mypy errors** (all in one file) identified in [research 003](../research/003-ci-lint-typecheck-failures.md). No logic changes are required — only formatting, imports, type annotations, and config.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| — | — | — | — |

## Holistic Review

### Decision Interactions

No user decisions required — all fixes are deterministic and catalogued in research 003. The auto-fix step (Phase 1) and manual steps (Phases 2-4) are independent categories that don't interact.

### Architectural Considerations

- **No behavioral changes:** Every fix is formatting, imports, config, or type annotations. No function signatures, return values, or control flow change.
- **Auto-fix safety:** Ruff `--fix` on F401/I001/UP035/F541 only removes unused imports, re-sorts import blocks, moves a stdlib import path, and strips an empty f-prefix. Pytest run after confirms no breakage.
- **SIM105 rewrite:** The `try/except ValueError: pass` → `contextlib.suppress` change is semantically identical but note there are **two** such blocks in `power.py` (lines ~87 and ~92). Ruff flags only the **first** block (line 87: `count += int(hi) - int(lo) + 1`) — the second block (line 92: `int(part); count += 1`) has two statements in the try body, so Ruff does not flag it. The coder should apply SIM105 only to the block Ruff flags (line 87).

### Trade-offs Accepted

- Using `# type: ignore[union-attr, attr-defined]` keeps both error codes suppressed so the comment works whether or not `sdnotify` is installed. Note: with the `_notifier: object` annotation, the actual error is always `attr-defined`; `union-attr` is included defensively in case the annotation is later narrowed to a union type. This is the minimal-change approach vs. restructuring the notifier typing.

### Risks Acknowledged

- Minimal. All fixes are well-understood, deterministic, and verified by running the same CI commands locally.

## Overview

### Feature Summary

Fix all CI-blocking lint (Ruff) and type-check (Mypy) errors so the pipeline goes green. Zero logic changes. The research document catalogues every error with file, line, rule, and deterministic fix.

### Objectives

1. Resolve all 28 Ruff violations (14 auto-fix, 14 manual)
2. Resolve all 5 Mypy errors (sdnotify stubs + type-ignore comments)
3. Verify full CI pass: `ruff check . && mypy && pytest -m "not field and not sitl"`

## Requirements

### Functional

- All Ruff rules pass (`E`, `F`, `W`, `I`, `B`, `UP`, `SIM` selectors)
- All Mypy strict-mode checks pass for `src/`
- All 175 existing tests continue to pass (no regressions)

### Non-Functional

- No behavioral changes to any CLI command or library function
- Changes limited to: whitespace/formatting, import ordering, unused-import removal, `raise ... from` additions, `contextlib.suppress` rewrite, pyproject.toml config, type-ignore comment updates

### Out of Scope

- Adding new tests
- Refactoring code beyond what's needed to fix the violations
- Upgrading Ruff or Mypy versions

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: "Line length limit"
    location: "pyproject.toml [tool.ruff] line-length = 100"
    usage: All E501 fixes must stay ≤ 100 chars
  - pattern: "Ruff lint selectors"
    location: "pyproject.toml [tool.ruff.lint] select"
    usage: E, F, W, I, B, UP, SIM rules enforced
  - pattern: "Mypy strict + overrides"
    location: "pyproject.toml [tool.mypy] + [[tool.mypy.overrides]]"
    usage: Add sdnotify override in same pattern as existing pymavlink/pyubx2 overrides
  - pattern: "Optional sdnotify import"
    location: "src/mower_rover/service/daemon.py:24-31"
    usage: try/except ImportError with fallback _NoOpNotifier
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Approach

**Step 1 — Auto-fix (14 errors):** Run `ruff check --fix .` to resolve all F401, I001, UP035, and F541 violations in one shot.

**Step 2 — Manual Ruff fixes (14 errors):**
- **E501 (10 lines):** Break long lines across 5 files to stay ≤ 100 chars
- **B904 (3 occurrences):** Add `from None` to `raise typer.Exit(code=3)` in `setup.py` exception handlers
- **SIM105 (1 occurrence):** Replace `try/except ValueError: pass` with `contextlib.suppress(ValueError)` in `power.py`

**Step 3 — Mypy fixes (5 errors, 2 files):**
- Add `sdnotify` to Mypy `[[tool.mypy.overrides]]` in `pyproject.toml`
- Update type-ignore comments on lines 64 and 76 of `daemon.py`

**Step 4 — Verify:** Run full CI check suite locally.

## Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| Research 003 | Document | Authoritative error catalogue |
| Ruff ≥ 0.5 | Dev tool | Already in `[project.optional-dependencies].dev` |
| Mypy ≥ 1.10 | Dev tool | Already in `[project.optional-dependencies].dev` |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Auto-fix changes behavior | Very Low | Medium | Ruff `--fix` only touches imports + formatting; verify with pytest |
| Line-break changes readability | Low | Low | Follow existing style; keep logical grouping |
| type-ignore comment drift | Low | Low | Use specific error codes, not blanket ignores |

## Execution Plan

### Phase 1: Auto-fixable Ruff Errors

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 8
**Prerequisites:** None
**Entry Point:** Project root
**Verification:** `uv run ruff check .` error count drops from 28 to 14

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Run `uv run ruff check --fix .` to auto-fix F401, I001, UP035, F541 | `src/mower_rover/cli/jetson.py`, `src/mower_rover/cli/setup.py`, `src/mower_rover/probe/registry.py`, `tests/conftest.py`, `tests/test_health.py`, `tests/test_service.py`, `tests/test_setup.py`, `tests/test_probe.py` | ✅ Complete |
| 1.2 | Run `uv run pytest -m "not field and not sitl"` to verify no regressions | — | ✅ Complete |

### Phase 2: Manual Ruff Fixes — E501 Line Length

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 5
**Prerequisites:** Phase 1 complete
**Entry Point:** Research 003 manual-fix table
**Verification:** Phase 1 verification passed

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Break `typer.Typer(...)` call at line 57 across multiple lines | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 2.2 | Break f-string at line 364 using intermediate variable or line continuation | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 2.3 | Break shell command string at line 229 across lines | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 2.4 | Break shell command string at line 250 across lines | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 2.5 | Break `CheckResult(...)` call at line 257 | `tests/test_cli_jetson_smoke.py` | ✅ Complete |
| 2.6 | Break `CheckSpec(...)` calls at lines 67, 68, 75, 76 | `tests/test_probe.py` | ✅ Complete |
| 2.7 | Break method signature at line 75 | `tests/test_setup.py` | ✅ Complete |
| 2.8 | Run `uv run ruff check .` — confirm 0 E501 errors remain | — | ✅ Complete |

### Phase 3: Manual Ruff Fixes — B904 and SIM105

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 2 complete
**Entry Point:** `src/mower_rover/cli/setup.py` lines 237, 247, 258; `src/mower_rover/health/power.py` line 87
**Verification:** Phase 2 verification passed

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add `from None` to `raise typer.Exit(code=3)` at line ~237 (Windows TimeoutExpired handler) | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 3.2 | Add `from None` to `raise typer.Exit(code=3)` at line ~247 (ssh-copy-id TimeoutExpired handler) | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 3.3 | Add `from None` to `raise typer.Exit(code=3)` at line ~258 (cat fallback TimeoutExpired handler) | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 3.4 | Replace `try: count += int(hi) - int(lo) + 1 except ValueError: pass` (line ~87) with `contextlib.suppress(ValueError)` in `_count_cpus()` | `src/mower_rover/health/power.py` | ✅ Complete |
| 3.5 | Run `uv run ruff check .` — confirm 0 Ruff errors | — | ✅ Complete |

### Phase 4: Mypy Fixes

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 3 complete (all Ruff errors resolved)
**Entry Point:** `pyproject.toml`, `src/mower_rover/service/daemon.py`
**Verification:** `uv run mypy` returns 0 errors

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | Add `[[tool.mypy.overrides]]` for `sdnotify` with `ignore_missing_imports = true` | `pyproject.toml` | ✅ Complete |
| 4.2 | Update type-ignore to `# type: ignore[attr-defined]` | `src/mower_rover/service/daemon.py` | ✅ Complete |
| 4.3 | Update type-ignore to `# type: ignore[attr-defined]` | `src/mower_rover/service/daemon.py` | ✅ Complete |
| 4.4 | Run `uv run mypy` — confirm 0 errors | — | ✅ Complete |
| 4.5 | Run full verification: `uv run ruff check . && uv run mypy && uv run pytest -m "not field and not sitl"` | — | ✅ Complete |

## Standards

No organizational standards applicable to this plan.

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 0
**Last Updated:** 2026-04-22

No clarifying questions required — all fixes are deterministic.

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 10 files across src/ and tests/ (but changes are trivial) |
| New patterns introduced | 1 | None — all changes use existing patterns |
| External dependencies | 1 | None |
| Migration complexity | 1 | N/A |
| Test coverage required | 1 | Existing 175 tests serve as regression suite |
| **Overall Complexity** | **6/25** | **Low** |

## Review Summary

**Review Date:** 2026-04-22
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 5 (Critical: 0, Major: 1, Minor: 4)
- Clarifying Questions Asked: 0
- Sections Updated: Holistic Review, Approach, Phase 1 header, Phase 3 Step 3.4, Phase 4 header, Trade-offs Accepted

### Key Improvements Made
1. Corrected SIM105 block reference — Ruff flags the **first** try/except at line 87, not the second; step 3.4 and holistic review updated to match
2. Fixed file count in Phase 1 header (6 → 8 files)
3. Fixed E501 line count in Approach section (8 → 10 lines)
4. Corrected Phase 4 verification to reference Mypy, not Ruff
5. Clarified type-ignore rationale — `attr-defined` is the actual error code; `union-attr` is defensive

### Remaining Considerations
- After Phase 1 auto-fix, some line numbers in Phases 2–4 may shift by ±1 (e.g., `test_setup.py` line 75 may become 74 after `SetupStep` import removal). The coder should use `ruff check` output post-auto-fix for accurate line references rather than relying solely on the plan's pre-fix line numbers.

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-22 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-22 |
| Status | ✅ Complete |
| Implemented By | pch-coder |
| Implementation Date | 2026-04-22 |
| Plan Location | /docs/plans/003-ci-lint-typecheck-fixes.md |

## Implementation Notes

### Phase 1 — Auto-fixable Ruff Errors
**Completed:** 2026-04-22
**Files Modified:** `src/mower_rover/cli/jetson.py`, `src/mower_rover/cli/setup.py`, `src/mower_rover/probe/registry.py`, `tests/conftest.py`, `tests/test_health.py`, `tests/test_probe.py`, `tests/test_service.py`
**Notes:** `ruff check --fix` resolved 15 errors across 7 files (F401, I001, UP035, F541). `tests/test_setup.py` had no auto-fixable errors. 175 tests passed.

### Phase 2 — E501 Line Length
**Completed:** 2026-04-22
**Files Modified:** `src/mower_rover/cli/jetson.py`, `src/mower_rover/cli/setup.py`, `tests/test_cli_jetson_smoke.py`, `tests/test_probe.py`, `tests/test_setup.py`
**Notes:** All 10 E501 violations fixed. Techniques: multi-line kwargs, intermediate variables, implicit string concatenation.

### Phase 3 — B904 and SIM105
**Completed:** 2026-04-22
**Files Modified:** `src/mower_rover/cli/setup.py`, `src/mower_rover/health/power.py`
**Notes:** 3× `from None` added to `raise typer.Exit(code=3)`. SIM105 applied to first try/except block only (as planned). Added `import contextlib`.

### Phase 4 — Mypy Fixes
**Completed:** 2026-04-22
**Files Modified:** `pyproject.toml`, `src/mower_rover/service/daemon.py`
**Deviations:** Used `# type: ignore[attr-defined]` instead of `[union-attr, attr-defined]` — mypy's `warn_unused_ignores` flags the unused `union-attr` code since `_notifier` is typed as `object`, not a union.

### Plan Completion
**All phases completed:** 2026-04-22
**Total tasks completed:** 20
**Total files modified/created:** 10 files modified, 0 created
**Code review:** Clean — no issues found
