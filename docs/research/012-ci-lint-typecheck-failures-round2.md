---
id: "012"
type: research
title: "CI Lint & Type-Check Failures — Round 2 (Post Plans 007–010)"
status: ✅ Complete
created: "2026-04-26"
current_phase: "2 of 2"
---

## Introduction

The GitHub Actions CI workflow (`.github/workflows/ci.yml`) is failing on both the `ruff check` and `mypy` steps after feature commits for plans 007–010 (OAK-D USB/SLAM, VSLAM–ArduPilot integration, Jetson deploy gaps, full Jetson deployment automation). This is the second round of CI lint/type-check failures — the first round was fixed in commit `b272496` and documented in research 003. Pytest (476 tests) passes; only lint and type-check steps fail.

## Objectives

- Catalogue every Ruff and Mypy error with file, line, rule, and fix
- Classify fixes as auto-fixable (`ruff check --fix`) vs. manual
- Identify which recent commits introduced the regressions
- Provide exact remediation steps so the planner/coder can fix in one pass

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Reproduce & catalogue all errors | ✅ Complete | Run `ruff check .` and `mypy` locally; record every error with file, line, rule, fix classification; group by auto-fixable vs. manual | 2026-04-26 |
| 2 | Root-cause analysis & remediation plan | ✅ Complete | Trace each error to the commit that introduced it; determine fix strategy; check for pre-commit or CI-gate gaps that allowed regressions | 2026-04-26 |

## Phase 1: Reproduce & Catalogue All Errors

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Ruff Errors (20 total)

#### Group A: Auto-fixable with `ruff check --fix` (7 errors)

Safe-fixable with a single `uv run ruff check . --fix` command:

| # | File | Line | Rule | Description | Fix |
|---|------|------|------|-------------|-----|
| 1 | `src/mower_rover/cli/backup.py` | 10 | F401 | `JetsonClient` imported but unused | Remove unused import |
| 2 | `src/mower_rover/probe/checks/vslam.py` | 119 | UP041 | `socket.timeout` → `TimeoutError` | Replace aliased exception |
| 3 | `tests/test_bringup.py` | 3 | I001 | Import block is un-sorted/un-formatted | Re-sort imports |
| 4 | `tests/test_bringup.py` | 5 | F401 | `subprocess` imported but unused | Remove unused import |
| 5 | `tests/test_bringup.py` | 10 | F401 | `typer` imported but unused | Remove unused import |
| 6 | `tests/test_probe_service.py` | 3 | I001 | Import block is un-sorted/un-formatted | Remove extra blank line |
| 7 | `tests/test_probe_vslam.py` | 479 | UP041 | `socket.timeout` → `TimeoutError` | Replace aliased exception |

#### Group B: Auto-fixable with `ruff check --fix --unsafe-fixes` (2 additional errors)

Require the `--unsafe-fixes` flag. Both in `bringup.py`:

| # | File | Line | Rule | Description | Fix |
|---|------|------|------|-------------|-----|
| 8 | `src/mower_rover/cli/bringup.py` | 597 | SIM105 | `try/except SshError: pass` → `contextlib.suppress(SshError)` | Unsafe-fix: replace try/except/pass with suppress |
| 9 | `src/mower_rover/cli/bringup.py` | 1514 | F841 | Local variable `depthai_idx` assigned but never used | Unsafe-fix: remove assignment, rename loop var to `_j` |

**Note:** Both unsafe fixes are safe in context — SIM105 changes only the try-except-pass pattern (idiomatic for "reboot may disconnect SSH"), and F841 only removes the dead assignment.

#### Group C: Manual fixes required (11 errors)

| # | File | Line | Rule | Description | Manual Fix |
|---|------|------|------|-------------|------------|
| 10 | `src/mower_rover/cli/bringup.py` | 149 | SIM103 | Return negated condition directly | Refactor `if cond: return False; return True` → `return not (cond)` |
| 11 | `src/mower_rover/cli/bringup.py` | 157 | SIM103 | Return negated condition directly | Same pattern in the `except SshError` branch |
| 12 | `src/mower_rover/cli/bringup.py` | 317 | SIM105 | `try/except SshError: pass` → `contextlib.suppress` | Add `import contextlib`, rewrite as `with contextlib.suppress(SshError):` |
| 13 | `src/mower_rover/cli/bringup.py` | 483 | E501 | Line too long (112 > 100) | Break f-string into shorter segments or use intermediate variable |
| 14 | `src/mower_rover/cli/bringup.py` | 545 | E501 | Line too long (112 > 100) | Same pattern — long JSON echo in shell command string |
| 15 | `src/mower_rover/cli/bringup.py` | 624 | E501 | Line too long (128 > 100) | Same pattern — slam_node JSON echo |
| 16 | `src/mower_rover/cli/bringup.py` | 1181 | SIM105 | `try/except SshError: pass` → `contextlib.suppress` | Same as #12 |
| 17 | `src/mower_rover/cli/bringup.py` | 1538 | B023 | Function definition does not bind loop variable `errors` | Pass `errors` as a default argument: `def _run_in_thread(..., errors=errors):` |
| 18 | `tests/test_bringup.py` | 181 | E501 | Line too long (107 > 100) | Shorten test method name or wrap args |
| 19 | `tests/test_bringup.py` | 223 | E501 | Line too long (105 > 100) | Break the `patch(...)` call across lines |
| 20 | `tests/test_bringup.py` | 322 | E501 | Line too long (102 > 100) | Shorten test method name or wrap args |

**Why SIM105 at lines 317 and 1181 are not auto-fixed:** Ruff only auto-fixes one of the three SIM105 occurrences (line 597). The others may have different context that makes the fix non-trivial, or the safe-fix heuristic declined them. They share the identical pattern and can be manually converted to `with contextlib.suppress(SshError):`.

### Mypy Errors (8 total)

| # | File | Line | Code | Description | Fix |
|---|------|------|------|-------------|-----|
| 1 | `src/mower_rover/vslam/lua_deploy.py` | 55 | unused-ignore | Unused `# type: ignore[arg-type]` comment | Remove the `# type: ignore` comment |
| 2 | `src/mower_rover/vslam/ipc.py` | 111 | attr-defined | `socket` has no attribute `AF_UNIX` (Windows-only) | Guard with `if hasattr(socket, 'AF_UNIX')` or add `# type: ignore[attr-defined]` with Windows comment |
| 3 | `src/mower_rover/cli/bringup.py` | 366 | type-arg | Missing type arguments for generic `dict` | Change `dict` → `dict[str, Any]` in return annotation |
| 4 | `src/mower_rover/cli/bringup.py` | 372 | no-any-return | Returning `Any` from function declared to return `dict[Any, Any] \| None` | Fix the return type annotation (consequence of fixing #3) or add a cast |
| 5 | `src/mower_rover/probe/checks/oakd.py` | 36 | unused-ignore | Unused `# type: ignore[import-untyped]` comment | Remove the `# type: ignore` comment |
| 6 | `src/mower_rover/vslam/health_listener.py` | 60 | unused-ignore | Unused `# type: ignore[attr-defined]` on `msg.get_srcComponent()` | Remove the `# type: ignore` comment |
| 7 | `src/mower_rover/vslam/health_listener.py` | 66 | unused-ignore | Unused `# type: ignore[attr-defined]` on `msg.name` | Remove the `# type: ignore` comment |
| 8 | `src/mower_rover/vslam/health_listener.py` | 73 | unused-ignore | Unused `# type: ignore[attr-defined]` on `msg.value` | Remove the `# type: ignore` comment |

**Mypy error pattern:** 5 of 8 errors are "unused `type: ignore` comments" — someone added type-ignore annotations that are no longer necessary (likely because pymavlink stubs improved or mypy changed behavior). These are trivial to fix by deleting the comments.

### Pytest Status

**475 passed, 1 skipped, 8 deselected** — all tests pass. The 1 skip is `test_service.py:611` (SIGTERM not reliably catchable on Windows). The 8 deselected are `field`/`sitl` marker tests excluded by the filter.

### Fix Summary

| Category | Count | Command / Approach |
|----------|-------|--------------------|----|
| Ruff safe auto-fix | 7 | `uv run ruff check . --fix` |
| Ruff unsafe auto-fix | 2 | `uv run ruff check . --fix --unsafe-fixes` |
| Ruff manual fix | 11 | Hand-edit (SIM103 ×2, SIM105 ×2, E501 ×6, B023 ×1) |
| Mypy fix | 8 | Hand-edit (remove unused-ignore ×5, add type args ×2, guard AF_UNIX ×1) |
| **Total** | **28** | 9 auto-fixable + 19 manual |

### Error Concentration

| File | Ruff Errors | Mypy Errors | Total |
|------|-------------|-------------|-------|
| `src/mower_rover/cli/bringup.py` | 10 | 2 | **12** |
| `tests/test_bringup.py` | 6 | 0 | **6** |
| `src/mower_rover/vslam/health_listener.py` | 0 | 3 | **3** |
| `src/mower_rover/probe/checks/vslam.py` | 1 | 0 | **1** |
| `src/mower_rover/cli/backup.py` | 1 | 0 | **1** |
| `tests/test_probe_service.py` | 1 | 0 | **1** |
| `tests/test_probe_vslam.py` | 1 | 0 | **1** |
| `src/mower_rover/vslam/lua_deploy.py` | 0 | 1 | **1** |
| `src/mower_rover/vslam/ipc.py` | 0 | 1 | **1** |
| `src/mower_rover/probe/checks/oakd.py` | 0 | 1 | **1** |

`bringup.py` alone accounts for **12 of 28 errors** (43%).

**Key Discoveries:**
- 20 ruff errors and 8 mypy errors confirmed (28 total across 10 files)
- `bringup.py` is the dominant source: 10 ruff + 2 mypy = 12 errors (43% of total)
- 9 of 20 ruff errors are auto-fixable (7 safe + 2 unsafe), leaving 11 manual ruff fixes
- 5 of 8 mypy errors are trivial "unused type: ignore" comment removals
- The `AF_UNIX` mypy error (`ipc.py:111`) is a Windows-only issue — needs a platform guard or type: ignore
- All 3 E501 long-line errors in `bringup.py` share the same pattern: long f-strings embedding JSON echo shell commands
- All 3 SIM105 manual fixes share identical `try: reboot/mkdir; except SshError: pass` pattern
- Pytest passes cleanly (475/475) — only lint/type-check is broken

**Gaps:** None  
**Assumptions:** The 2 "unsafe-fix" ruff fixes (SIM105 at line 597, F841 at line 1514) are safe in context — the try-except-pass wraps an expected SSH disconnect on reboot, and the unused variable is genuinely dead code.

## Phase 2: Root-Cause Analysis & Remediation Plan

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Root-Cause: Commits by Error

All 28 errors (20 Ruff + 8 Mypy) trace to just **4 commits**, all post-plan-007:

| Commit | Subject | Ruff | Mypy | Total |
|--------|---------|------|------|-------|
| `3e2a2e5` | feat: full Jetson deployment automation (plan 010) | **15** | **2** | **17** |
| `40d9f4d` | feat: automated Jetson bringup via SSH (plan 005) | **5** | 0 | **5** |
| `b237ce7` | feat: VSLAM-ArduPilot EKF3 integration (plan 008) | 0 | **4** | **4** |
| `b6d71a4` | fix: migrate rtabmap_slam_node to DepthAI v3 API | 0 | **1** | **1** |
| **Unaccounted** | | 0 | **1** (ipc.py AF_UNIX) | **1** |

**Dominant offender:** Commit `3e2a2e5` (plan 010) accounts for **61%** of all errors. This is the most recent commit (`HEAD`) and introduced `bringup.py` (1500+ lines) plus its test file and `backup.py`.

### Why Regressions Slipped Through

1. **No pre-commit hooks** — `.git/hooks/` contains only `.sample` files. No `.pre-commit-config.yaml` exists. There is no automated local lint gate.

2. **CI runs on push, not pre-push** — `.github/workflows/ci.yml` triggers on `push` to `main` and on PRs. Since work was pushed directly to `main` (no PR branch), lint failures were only discovered **after** the push.

3. **No `--fix` in CI** — CI runs `uv run ruff check .` (fail-only, no auto-fix). This is correct behavior for CI (don't auto-fix in pipeline), but combined with no local linting, errors accumulate.

4. **Mypy `unused-ignore` from dependency config** — The `pyproject.toml` overrides for `pymavlink.*` and `depthai.*` set `ignore_missing_imports = true`, making those modules return `Any` types. This means `type: ignore[attr-defined]` and `type: ignore[import-untyped]` on those modules are unnecessary — mypy strict mode's `warn_unused_ignores` flags them.

### Auto-Fix Safety Assessment

**`ruff check . --fix` (7 safe fixes):** All are clean — removes unused imports, replaces `socket.timeout` → `TimeoutError`, re-sorts import blocks.

**`ruff check . --fix --unsafe-fixes` (2 additional):**
- Converts `try/except SshError: pass` → `contextlib.suppress(SshError)` at line 597 — SAFE (same semantics)
- Removes unused `depthai_idx` assignment at line 1514 — SAFE (variable never read)

### Manual Fix Details

#### SIM103 (lines 149, 157) — Return negated condition

**Current (lines 148-154):**
```python
        stderr_lower = result.stderr.lower()
        if (
            "remote host identification has changed" in stderr_lower
            or "host key verification failed" in stderr_lower
        ):
            return False
        return True
```

**Fix:**
```python
        stderr_lower = result.stderr.lower()
        return not (
            "remote host identification has changed" in stderr_lower
            or "host key verification failed" in stderr_lower
        )
```

Same pattern at lines 156-162 in the `except SshError` branch.

#### SIM105 (lines 317, 1181) — try/except/pass → contextlib.suppress

**Current:**
```python
    try:
        client.run(["sudo", "reboot"], timeout=10)
    except SshError:
        pass  # SSH disconnect on reboot is expected
```

**Fix:**
```python
    with contextlib.suppress(SshError):
        client.run(["sudo", "reboot"], timeout=10)
```

Note: `contextlib` is already imported in this file.

#### E501 (lines 483, 545, 624) — Long f-string shell commands

All three are long f-strings embedding JSON echo in shell commands. Fix by breaking the f-string across multiple lines with implicit string concatenation or extracting the JSON template to a variable.

#### B023 (line 1538) — Loop variable capture

**Current:**
```python
                def _run_in_thread(
                    name: str,
                    run_fn: Callable[[JetsonClient, BringupContext], None],
                ) -> None:
                    ...
                        errors.append((name, error_msg))
```

**Fix:** Add `errors` as a default argument:
```python
                def _run_in_thread(
                    name: str,
                    run_fn: Callable[[JetsonClient, BringupContext], None],
                    errors: list[tuple[str, str]] = errors,
                ) -> None:
```

#### E501 in test_bringup.py (lines 181, 223, 322)

- Line 181: Shorten method name or wrap parameter list
- Line 223: Break `patch(...)` call across lines
- Line 322: Wrap parameter list across lines

#### Mypy: Remove unused `type: ignore` (5 instances)

Simply delete `# type: ignore[...]` from:
- `src/mower_rover/vslam/lua_deploy.py:55` — `[arg-type]`
- `src/mower_rover/probe/checks/oakd.py:36` — `[import-untyped]`
- `src/mower_rover/vslam/health_listener.py:60,66,73` — `[attr-defined]` (3 instances)

#### Mypy: AF_UNIX platform guard (ipc.py:111)

Add `# type: ignore[attr-defined]` — `AF_UNIX` is Linux-only and this module runs on Jetson only.

#### Mypy: Type annotations (bringup.py:366,372)

Change `dict | None` → `dict[str, Any] | None` in `_read_version_marker()` return type. Wrap return with `dict(...)` or `cast()` to satisfy `no-any-return`.

### Remediation Checklist (Single-Pass)

```
Step 1: Auto-fix (safe)
  $ uv run ruff check . --fix
  Fixes 7 errors: F401×3, UP041×2, I001×2

Step 2: Auto-fix (unsafe)
  $ uv run ruff check . --fix --unsafe-fixes
  Fixes 2 more: SIM105 (line 597), F841 (line 1514)

Step 3: Manual Ruff fixes in src/mower_rover/cli/bringup.py
  a. Lines 149-154: SIM103 — collapse if/return to `return not (...)`
  b. Lines 157-162: SIM103 — same pattern
  c. Lines 317-320: SIM105 — try/except/pass → contextlib.suppress
  d. Line 483: E501 — break long f-string
  e. Line 545: E501 — break long f-string
  f. Line 624: E501 — break long f-string
  g. Lines 1181-1184: SIM105 — try/except/pass → contextlib.suppress
  h. Line 1538: B023 — add errors=errors default arg

Step 4: Manual Ruff fixes in tests/test_bringup.py
  a. Line 181: E501 — shorten method name or wrap
  b. Line 223: E501 — break patch(...) across lines
  c. Line 322: E501 — wrap parameter list

Step 5: Mypy — remove unused type: ignore (5 files)
  a. lua_deploy.py:55, oakd.py:36, health_listener.py:60,66,73

Step 6: Mypy — platform guard
  a. ipc.py:111 — add # type: ignore[attr-defined]

Step 7: Mypy — type annotations
  a. bringup.py:366 — dict | None → dict[str, Any] | None
  b. bringup.py:372 — ensure return type matches

Step 8: Verify
  $ uv run ruff check .                          # 0 errors
  $ uv run mypy src/mower_rover/                  # 0 errors
  $ uv run pytest -m "not field and not sitl"     # all pass
```

### Prevention Recommendations

1. **Add `.pre-commit-config.yaml`** with `ruff check --fix` and `ruff format` hooks
2. **Document developer workflow** — run `uv run ruff check . --fix` before committing
3. **Branch protection rules** — require PR + passing CI before merge to `main`

**Key Discoveries:**
- 61% of errors (17/28) from a single commit: `3e2a2e5` (plan 010)
- All errors trace to just 4 commits across plans 005, 008, and 010
- No pre-commit hooks and no `.pre-commit-config.yaml` exist
- CI only triggers post-push — direct pushes to `main` bypass any pre-merge gate
- 5 of 8 mypy errors are unnecessary `type: ignore` comments (pyproject.toml overrides make them redundant)
- B023 (loop variable capture) is a real concurrency bug risk in threading code

**Gaps:** None  
**Assumptions:** The `type: ignore[attr-defined]` fix for `ipc.py:111` is appropriate since the IPC module is Jetson-only (Linux).

## Overview

The CI pipeline has 28 lint/type-check failures (20 Ruff, 8 Mypy) across 10 source files, all introduced by 4 recent commits implementing plans 005, 008, and 010. A single commit (`3e2a2e5`, plan 010 — full Jetson deployment automation) accounts for 61% of errors. The root cause of regressions slipping through is the absence of any local lint gate — no pre-commit hooks exist, and direct pushes to `main` bypass CI's post-push-only lint checks. All errors are straightforward to fix: 9 are auto-fixable via `ruff check --fix --unsafe-fixes`, and the remaining 19 are well-characterized manual edits. Pytest (475 tests) passes cleanly; only lint/type-check steps fail.

## Key Findings

1. **28 total errors** (20 Ruff + 8 Mypy) across 10 files; `bringup.py` alone has 12 (43%)
2. **4 commits** account for all errors — `3e2a2e5` (plan 010) is the dominant offender at 61%
3. **9 auto-fixable** Ruff errors (7 safe + 2 unsafe); **11 manual** Ruff fixes; **8 manual** Mypy fixes
4. **5 of 8 Mypy errors** are trivial `unused-ignore` removals — `pyproject.toml` overrides make them redundant
5. **No pre-commit hooks** exist — zero local lint gates; CI triggers only post-push
6. **B023 (loop variable capture)** in `bringup.py:1538` is a real concurrency bug risk in the threading code
7. **AF_UNIX** Mypy error in `ipc.py:111` is a legitimate cross-platform issue (Linux-only attribute)

## Actionable Conclusions

1. Run `uv run ruff check . --fix --unsafe-fixes` to clear 9 errors instantly
2. Apply 11 manual Ruff fixes (SIM103 ×2, SIM105 ×2, E501 ×6, B023 ×1) and 8 Mypy fixes following the remediation checklist in Phase 2
3. Add `.pre-commit-config.yaml` with Ruff hooks to prevent future regressions
4. Consider branch protection rules requiring PR + passing CI before merge to `main`

## Open Questions

- Should `.pre-commit-config.yaml` be added as part of this fix or as a separate task?
- Should branch protection rules be configured for `main`?

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-26 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/012-ci-lint-typecheck-failures-round2.md |
