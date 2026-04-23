---
id: "003"
type: research
title: "CI Lint & Type-Check Failures — Ruff + Mypy Fixes"
status: ✅ Complete
created: "2026-04-22"
current_phase: "✅ Complete"
---

## Overview

CI fails on both the `ruff check` and `mypy` steps. **Pytest passes** (175 passed, 4 skipped). The failures are exclusively lint and type-checking violations — no logic bugs. There are **28 Ruff errors** (14 auto-fixable) and **5 Mypy errors** (all in one file). Every error has a deterministic fix documented below.

### Root Cause

The Ruff and Mypy configurations were tightened or new code was added without a pre-push lint pass. The two categories are independent:

1. **Ruff** — unused imports, line-length violations, unsorted import blocks, a bare f-string, a `try/except/pass` that should use `contextlib.suppress`, and missing `from err`/`from None` on re-raised exceptions.
2. **Mypy** — `sdnotify` has no type stubs; the existing `type: ignore[union-attr]` comment doesn't cover the actual error code Mypy emits when the import itself is unresolved.

## Objectives

- Catalogue every CI-failing error with file, line, rule, and fix
- Classify fixes as auto-fixable vs. manual
- Provide exact remediation steps

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Reproduce & catalogue all errors | ✅ Complete | Run `ruff check .` and `mypy`; record every error | 2026-04-22 |

## Phase 1: Reproduce & Catalogue All Errors

**Status:** ✅ Complete  
**Session:** 2026-04-22

CI configuration: `.github/workflows/ci.yml` runs on `ubuntu-latest` + `windows-latest`, Python 3.11, with three check steps: `uv run ruff check .`, `uv run mypy`, `uv run pytest -m "not field and not sitl"`. Pytest passes; Ruff and Mypy fail.

---

### Ruff Errors (28 total)

#### Auto-fixable with `uv run ruff check --fix .` (14 errors)

These can all be resolved in one command:

| # | Rule | File | Line | Description |
|---|------|------|------|-------------|
| 1 | F401 | `src/mower_rover/cli/jetson.py` | 44 | `CheckResult` imported but unused |
| 2 | F401 | `src/mower_rover/cli/jetson.py` | 44 | `Severity` imported but unused |
| 3 | F401 | `src/mower_rover/probe/registry.py` | 13 | `dataclasses.field` imported but unused |
| 4 | F401 | `tests/test_health.py` | 15 | `DiskUsage` imported but unused |
| 5 | F401 | `tests/test_health.py` | 17 | `ThermalZone` imported but unused |
| 6 | F401 | `tests/test_service.py` | 11 | `unittest.mock.call` imported but unused |
| 7 | F401 | `tests/test_setup.py` | 19 | `SetupStep` imported but unused |
| 8 | F401 | `tests/test_setup.py` | 185 | `SshError` imported but unused |
| 9 | UP035 | `src/mower_rover/cli/setup.py` | 21 | Import `Callable` from `collections.abc` instead of `typing` |
| 10 | F541 | `src/mower_rover/cli/setup.py` | 457 | f-string without placeholders — remove `f` prefix |
| 11 | I001 | `tests/conftest.py` | 13 | Import block unsorted |
| 12 | I001 | `tests/test_health.py` | 7 | Import block unsorted |
| 13 | I001 | `tests/test_probe.py` | 7 | Import block unsorted |
| 14 | I001 | `tests/test_service.py` | 3 | Import block unsorted |

#### Manual fixes required (14 errors)

| # | Rule | File | Line | Description | Fix |
|---|------|------|------|-------------|-----|
| 1 | E501 | `src/mower_rover/cli/jetson.py` | 57 | Line too long (112 > 100) | Break the `typer.Typer(...)` call across lines |
| 2 | E501 | `src/mower_rover/cli/jetson.py` | 364 | Line too long (109 > 100) | Break the f-string or use a variable |
| 3 | E501 | `src/mower_rover/cli/setup.py` | 229 | Line too long (109 > 100) | Break the shell command string |
| 4 | E501 | `src/mower_rover/cli/setup.py` | 250 | Line too long (114 > 100) | Break the shell command string |
| 5 | B904 | `src/mower_rover/cli/setup.py` | 237 | `raise typer.Exit(code=3)` in except — missing `from` | Add `from None` |
| 6 | B904 | `src/mower_rover/cli/setup.py` | 247 | Same as above | Add `from None` |
| 7 | B904 | `src/mower_rover/cli/setup.py` | 258 | Same as above | Add `from None` |
| 8 | SIM105 | `src/mower_rover/health/power.py` | 87 | `try/except ValueError: pass` → use `contextlib.suppress` | Rewrite with `contextlib.suppress(ValueError)` |
| 9 | E501 | `tests/test_cli_jetson_smoke.py` | 257 | Line too long (104 > 100) | Break `CheckResult(...)` call |
| 10 | E501 | `tests/test_probe.py` | 67 | Line too long (105 > 100) | Break `CheckSpec(...)` call |
| 11 | E501 | `tests/test_probe.py` | 68 | Line too long (105 > 100) | Break `CheckSpec(...)` call |
| 12 | E501 | `tests/test_probe.py` | 75 | Line too long (118 > 100) | Break `CheckSpec(...)` call |
| 13 | E501 | `tests/test_probe.py` | 76 | Line too long (111 > 100) | Break `CheckSpec(...)` call |
| 14 | E501 | `tests/test_setup.py` | 75 | Line too long (101 > 100) | Break method signature |

---

### Mypy Errors (5 total, all in `src/mower_rover/service/daemon.py`)

| # | Line | Error Code | Description | Fix |
|---|------|------------|-------------|-----|
| 1 | 24 | `import-not-found` | Cannot find stubs for `sdnotify` | Add `sdnotify` to `mypy` `[[tool.mypy.overrides]]` with `ignore_missing_imports = true` |
| 2 | 64 | `unused-ignore` | `type: ignore[union-attr]` is unused (real error is `attr-defined`) | Change to `type: ignore[attr-defined]` |
| 3 | 64 | `attr-defined` | `object` has no attribute `notify` | Covered by updated ignore comment |
| 4 | 76 | `unused-ignore` | Same as #2 | Change to `type: ignore[attr-defined]` |
| 5 | 76 | `attr-defined` | Same as #3 | Covered by updated ignore comment |

**Explanation:** When `sdnotify` is unresolved (`import-not-found`), Mypy infers `_notifier` as `object`. The `.notify()` calls then fail with `attr-defined`, not `union-attr`. The existing `type: ignore[union-attr]` comments don't suppress the actual error and themselves become `unused-ignore` errors.

**Fix approach:**

1. In `pyproject.toml`, add a Mypy override for `sdnotify`:
   ```toml
   [[tool.mypy.overrides]]
   module = "sdnotify"
   ignore_missing_imports = true
   ```
2. In `daemon.py` lines 64 and 76, change `# type: ignore[union-attr]` to `# type: ignore[union-attr, attr-defined]` (covers both the case where sdnotify is installed and where it's not).

---

### Recommended Fix Sequence

1. **Run `uv run ruff check --fix .`** — auto-fixes 14 errors (unused imports, import sorting, UP035, F541)
2. **Manually fix E501 lines** — break long lines in 8 locations across 5 files
3. **Manually fix B904** — add `from None` to 3 `raise` statements in `setup.py`
4. **Manually fix SIM105** — rewrite `try/except/pass` in `power.py` with `contextlib.suppress`
5. **Fix Mypy overrides** — add `sdnotify` override in `pyproject.toml`
6. **Fix type-ignore comments** — update 2 lines in `daemon.py`
7. **Verify** — run `uv run ruff check . && uv run mypy && uv run pytest -m "not field and not sitl"`

**Key Discoveries:**

- All 175 tests pass; CI failure is lint/type-check only
- 14 of 28 Ruff errors are auto-fixable with `--fix`
- All 5 Mypy errors trace to one root cause: missing `sdnotify` stubs
- No code logic changes required — only formatting, imports, and type annotations

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-22 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/003-ci-lint-typecheck-failures.md |
