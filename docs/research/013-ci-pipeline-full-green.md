---
id: "013"
type: research
title: "CI Pipeline Full Green — Diagnose & Fix All Remaining Failures"
status: ✅ Complete
created: "2026-04-26"
current_phase: "✅ Complete"
---

## Introduction

The GitHub Actions CI workflow (`.github/workflows/ci.yml`) has never been fully green on both platforms simultaneously, except for run #4 (commit `7705b5f`). After fixing the 28 ruff/mypy lint errors documented in research 012 (commit `3104ddc`), CI run #14 still fails with **two distinct platform-specific issues**: Mypy fails on ubuntu-latest, and Pytest fails on windows-latest. Ruff passes on both platforms. The root cause appears to be a combination of platform-specific type-checking differences and a Python version mismatch (CI pins Python 3.11 via `uv python install 3.11`, while local development uses Python 3.13). This research aims to identify every remaining CI blocker — including issues that pre-date recent changes — and document exact fixes to achieve a fully green pipeline on both platforms.

## Objectives

- Reproduce and catalogue the exact Mypy errors that appear on ubuntu-latest (Linux + Python 3.11) but not on Windows + Python 3.13
- Reproduce and catalogue the exact Pytest failures that appear on windows-latest (Python 3.11) but not locally (Python 3.13)
- Determine whether the Python version mismatch (3.11 in CI vs 3.13 local) is a contributing factor and recommend a resolution
- Identify any CI workflow configuration issues (action versions, caching, etc.) that contribute to failures
- Provide exact, tested remediation steps for every failure

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Reproduce CI failures locally | ✅ Complete | Install Python 3.11 via uv; run `ruff check .`, `mypy`, and `pytest -m "not field and not sitl"` on both Python 3.11 and 3.13; compare outputs; catalogue every error that appears under CI conditions but not locally | 2026-04-26 |
| 2 | Root-cause analysis & CI workflow audit | ✅ Complete | For each error from Phase 1: trace to the source code, identify why it's platform/version-specific; audit `ci.yml` for configuration issues (action deprecation warnings, cache failures, Python version strategy); check if `uv.lock` pins resolve the right dependency versions for 3.11 | 2026-04-26 |
| 3 | Remediation plan & verification | ✅ Complete | For each identified issue: provide exact fix (code change, CI config change, or both); determine fix order; verify fixes don't break the other platform; provide a single-pass remediation checklist; address the open questions from research 012 (pre-commit hooks, branch protection) | 2026-04-26 |

## Phase 1: Reproduce CI failures locally

**Status:** ✅ Complete  
**Session:** 2026-04-26

### CI Run Analysis

CI run #24965851734 (commit `3104ddc`, the plan-011 lint fix) was analyzed via `gh run view --log-failed`. The run has `fail-fast: false`, so both platform jobs ran to completion independently.

**Ubuntu-latest job:**
- Ruff: pass
- Mypy: **1 error** — `src/mower_rover/vslam/ipc.py:111: error: Unused "type: ignore" comment [unused-ignore]`
- Pytest: **skipped** — GitHub Actions stops subsequent steps when a prior step fails

**Windows-latest job:**
- Ruff: pass
- Mypy: pass
- Pytest: **4 failures, 471 passed, 1 skipped, 8 deselected**

### Issue 1: Cross-Platform Mypy — ipc.py:111 (Ubuntu only)

The file `src/mower_rover/vslam/ipc.py` line 111 uses:
```python
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined]  # AF_UNIX is Linux-only
```

- **On Windows:** `socket.AF_UNIX` does NOT exist — `# type: ignore[attr-defined]` is correct and suppresses the mypy error
- **On Linux (Ubuntu CI):** `socket.AF_UNIX` DOES exist — `# type: ignore[attr-defined]` is unnecessary — mypy `strict` mode (which enables `warn_unused_ignores`) flags it as `unused-ignore`

This is inherently a cross-platform mypy issue: the `type: ignore` is needed on one OS but flagged as unused on the other. The `pyproject.toml` sets `strict = true` for mypy, which enables `warn_unused_ignores`.

### Issue 2: Rich/Typer ANSI in CliRunner — GITHUB_ACTIONS=true (Windows CI, likely affects Ubuntu too)

4 pytest failures, all with the same root cause:

| # | Test | Failing assertion | Line |
|---|------|-------------------|------|
| 1 | `test_bringup.py::TestBackupCommand::test_help` | `assert "--output-dir" in result.stdout` | 1485 |
| 2 | `test_cli_jetson_smoke.py::test_jetson_detect_help` | `assert "--json" in result.stdout` | 30 |
| 3 | `test_cli_jetson_smoke.py::test_jetson_vslam_bridge_start_help` | `assert "--user-level" in result.stdout` | 37 |
| 4 | `test_cli_jetson_smoke.py::test_jetson_vslam_bridge_stop_help` | `assert "--user-level" in result.stdout` | 44 |

**Root cause:** When `GITHUB_ACTIONS=true` (set automatically by GitHub Actions), Rich's `Console` detects this and **forces ANSI terminal mode**, even though output is going to Typer's `CliRunner` in-memory buffer (not a real terminal). Rich then renders CLI option names with ANSI formatting that **splits the `--` prefix** across escape codes:

```
--json  →  \x1b[1;36m-\x1b[0m\x1b[1;36m-json\x1b[0m
```

The literal string `"--json"` does NOT appear in the captured stdout because the `--` is interrupted by ANSI escape codes (`-` + reset + bold + `-json`). The same splitting pattern affects all `--option-name` strings.

**Reproduction:** Setting `$env:GITHUB_ACTIONS = "true"` locally and running the tests reproduces the failure exactly.

**Why it passes locally:** Without `GITHUB_ACTIONS`, Rich detects that `CliRunner`'s output buffer is not a real TTY and disables ANSI formatting. The help text is rendered as plain text with literal `--option` strings.

**`NO_COLOR=1` does NOT fix it:** `NO_COLOR` removes color codes but Rich still outputs bold (`\x1b[1m`) and dim (`\x1b[2m`) ANSI sequences that split the `--` prefix.

**`TERM=dumb` DOES fix it:** Setting `TERM=dumb` causes Rich to disable ALL ANSI formatting (including bold/dim), producing plain text that matches the assertions. Confirmed locally.

### Other assertions NOT affected

Assertions checking for plain-text words (not prefixed with `--`) are NOT affected because Rich does not split regular words with ANSI codes:
- `assert "detect" in result.stdout.lower()` — passes (word not split)
- `assert "/dev/pixhawk" in result.stdout` — passes (not a CLI option)
- `assert "bridge" in result.stdout.lower()` — passes
- `assert "host" in result.stdout` — passes

Only assertions checking for `--option-name` patterns fail because Rich formats CLI options with ANSI around each `-`.

### Local Baseline (All Clean)

Running locally on Windows + Python 3.11.13 WITHOUT `GITHUB_ACTIONS`:
- `uv run ruff check .` — 0 errors
- `uv run mypy` — 0 errors (57 source files)
- `uv run pytest -m "not field and not sitl"` — 475 passed, 1 skipped, 8 deselected

The local environment is clean — all failures are CI-environment-specific.

### Python Version

CI and local both use Python 3.11. The `pyproject.toml` and CI workflow both target 3.11. No version mismatch — this was a non-issue.

**Key Discoveries:**
- Only 2 distinct CI issues remain after the 012 fixes: one mypy cross-platform issue and one Rich/ANSI test issue
- The mypy issue is a cross-platform `type: ignore` conflict — needed on Windows, flagged as unused on Linux
- The pytest issue is caused by `GITHUB_ACTIONS=true` making Rich force ANSI formatting in CliRunner
- `TERM=dumb` is a confirmed fix for the ANSI issue
- `NO_COLOR=1` is NOT sufficient — it removes color but not bold/dim formatting
- Ubuntu CI Pytest was skipped (not failed) because Mypy failed first — ANSI would likely affect it too since `GITHUB_ACTIONS=true` is set on both platforms
- Python version is 3.11 on both CI and local — no mismatch

| File | Relevance |
|------|-----------|
| `.github/workflows/ci.yml` | CI workflow — triggers, Python version, test commands |
| `src/mower_rover/vslam/ipc.py` | Contains the `socket.AF_UNIX` type: ignore that fails on Linux |
| `tests/test_cli_jetson_smoke.py` | 3 of 4 failing tests — CLI help assertions |
| `tests/test_bringup.py` | 1 of 4 failing tests — backup command help assertion |
| `pyproject.toml` | Mypy strict mode config, tool versions |

**Gaps:** Cannot confirm whether Ubuntu Pytest would also fail with ANSI issues (it was skipped due to prior mypy failure)
**Assumptions:** The ANSI issue would also affect Ubuntu Pytest since `GITHUB_ACTIONS=true` is set on both platforms

## Phase 2: Root-cause analysis & CI workflow audit

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Issue 1 Root Cause: ipc.py Cross-Platform type: ignore

**What:** `src/mower_rover/vslam/ipc.py:111` has `# type: ignore[attr-defined]` on `socket.AF_UNIX`. On Windows mypy needs it (AF_UNIX missing); on Linux mypy flags it as `unused-ignore` because `strict = true` enables `warn_unused_ignores`.

**Introduced:** Commit `3104ddc` (plan 011) — intentionally added as a platform guard per the remediation checklist in research 012 (step 6: "ipc.py:111 — add `# type: ignore[attr-defined]`"). The research noted `AF_UNIX` is Linux-only and this module runs on Jetson only, but the cross-platform mypy conflict on CI's Ubuntu runner was not anticipated.

**Existing codebase pattern:** `src/mower_rover/probe/checks/vslam.py:97-106` uses a runtime `hasattr(socket, "AF_UNIX")` guard instead of `type: ignore`. This avoids the mypy conflict entirely because `hasattr` returns a bool at runtime and mypy understands it as a type narrowing guard.

**Mypy overrides in pyproject.toml:** Three existing `[[tool.mypy.overrides]]` blocks exist, all using `ignore_missing_imports = true` for third-party modules. No existing pattern for per-file `warn_unused_ignores` override.

**Fix approaches (ordered by preference):**

1. **Per-file mypy override** — Add `[[tool.mypy.overrides]]` for `mower_rover.vslam.ipc` with `warn_unused_ignores = false`. Minimal code change, follows existing override pattern, but hides future legitimate unused-ignore warnings in that file.

2. **Platform-aware type: ignore** — Not supported by mypy. `# type: ignore` cannot be conditionally applied based on platform.

3. **Runtime hasattr guard** — Match the pattern in `vslam.py:97`. Replace direct `socket.AF_UNIX` with `if hasattr(socket, "AF_UNIX"):` + assign via `getattr`. Cleanest from a mypy perspective, but adds a runtime check for code that will only ever run on Linux.

### Issue 2 Root Cause: Rich ANSI Detection in GITHUB_ACTIONS

**What:** Rich's `Console` class detects the `GITHUB_ACTIONS` environment variable during initialization. When set, Rich forces ANSI terminal mode (`force_terminal=True`) because GitHub Actions log viewers support ANSI rendering. This override applies even when stdout is redirected to Typer's `CliRunner` in-memory buffer.

**Rich's detection order:**
1. Check `GITHUB_ACTIONS` env var → if truthy, force ANSI mode
2. Check `NO_COLOR` env var → if set, disable color (but NOT bold/dim/underline)
3. Check `TERM` env var → if `dumb`, disable ALL ANSI formatting
4. Check if stdout is a TTY → if not, disable ANSI (but overridden by step 1)

**Why `NO_COLOR` doesn't work:** `NO_COLOR` only removes color escape codes (e.g., `\x1b[1;36m` → `\x1b[1m`). Rich still outputs bold (`\x1b[1m`) and dim (`\x1b[2m`) sequences, which split the `--` prefix of CLI options.

**Why `TERM=dumb` works:** Rich treats `TERM=dumb` as "this terminal supports no ANSI at all" and disables ALL formatting — color, bold, dim, underline. The help text becomes plain ASCII.

**Typer CliRunner limitation:** Typer's `CliRunner` (inherited from Click) does not expose a `color` parameter. There is no Typer-native way to disable Rich formatting in tests. The fix must come from environment variables or Rich configuration.

**Note:** The test fixture in `test_bringup.py` line 90 explicitly creates `Console(force_terminal=True)` for `BringupContext` tests — but this is unrelated to the CliRunner/help-output issue.

### CI Workflow Audit

**Action versions:**

| Action | Current | Latest | Status |
|--------|---------|--------|--------|
| `actions/checkout` | v4 | v4 | Current |
| `astral-sh/setup-uv` | **v3** | **v5** | 2 versions behind |

Node.js 20 deprecation warnings are emitted by both actions. GitHub forces Node.js 24 on **June 2, 2026** (37 days away). Upgrading `setup-uv` to v5 resolves this.

**Workflow structure:** Steps run sequentially: checkout → setup-uv → python install → sync deps → ruff → mypy → pytest. If any step fails, subsequent steps are skipped (default GitHub Actions behavior). This means Ubuntu's Pytest was never run — it was skipped because Mypy failed.

**uv.lock:** Committed to git (previously listed in `.gitignore`, fixed in a prior plan). The `enable-cache: true` in `setup-uv` uses `**/uv.lock` as cache key — this now works correctly.

**Pre-commit:** `.pre-commit-config.yaml` exists with ruff check + ruff format hooks.

**Missing from CI:**
- No `TERM` or `NO_COLOR` environment variable set
- No `continue-on-error` on any step (Mypy failure blocks Pytest on Ubuntu)
- Steps lack `if: always()` — so we can't see if Ubuntu Pytest would also fail

**Key Discoveries:**
- The `type: ignore[attr-defined]` on ipc.py was an intentional fix from plan 011 that didn't account for cross-platform CI
- A working cross-platform pattern already exists in the same codebase: `hasattr(socket, "AF_UNIX")` in `probe/checks/vslam.py`
- Rich's GITHUB_ACTIONS detection is by design (for CI log rendering), but conflicts with CliRunner's in-memory capture
- `astral-sh/setup-uv` is 2 major versions behind (v3 → v5 needed)
- Node.js 20 deprecation has a hard deadline: June 2, 2026
- Pre-commit hooks exist but don't include mypy (only ruff)

| File | Relevance |
|------|-----------|
| `src/mower_rover/vslam/ipc.py` | Line 111 — the cross-platform type: ignore |
| `src/mower_rover/probe/checks/vslam.py` | Lines 97-106 — hasattr pattern that works cross-platform |
| `pyproject.toml` | Mypy strict mode and existing overrides |
| `.github/workflows/ci.yml` | CI workflow with outdated action versions |
| `.pre-commit-config.yaml` | Pre-commit hooks (ruff only, no mypy) |

**Gaps:** None
**Assumptions:** Rich's ANSI behavior is consistent across Rich versions pinned in uv.lock

## Phase 3: Remediation plan & verification

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Fix 1: ipc.py Cross-Platform Mypy (Ubuntu blocker)

**Recommended approach:** Add a per-file mypy override to disable `warn_unused_ignores` for `mower_rover.vslam.ipc`.

**Why this over hasattr:** The `ipc.py` module is Jetson-only production code. Adding a runtime `hasattr` guard + `getattr` for `AF_UNIX` would be dead code on the only target platform. The mypy override is more honest: "this file has a cross-platform type: ignore that we know about."

**Exact change in `pyproject.toml`:**

```toml
[[tool.mypy.overrides]]
module = ["mower_rover.vslam.ipc"]
warn_unused_ignores = false
```

Add this after the existing `depthai.*` override block. No source code changes needed.

**Verification:** Run `uv run mypy` on both Windows and Linux (via CI). Should produce 0 errors on both.

### Fix 2: Rich ANSI in CI Pytest (Windows blocker, likely Ubuntu too)

**Recommended approach:** Set `TERM: dumb` as an environment variable in the CI workflow for the Pytest step.

**Why `TERM=dumb` over other options:**
- `NO_COLOR=1` is insufficient (removes color but not bold/dim)
- Modifying test code to strip ANSI is fragile and adds maintenance burden
- `TERM=dumb` is a standard, well-understood terminal setting
- Setting it only on the Pytest step avoids affecting Ruff/Mypy output

**Exact change in `.github/workflows/ci.yml`:**

```yaml
      - name: Pytest (no field, no sitl)
        run: uv run pytest -m "not field and not sitl"
        env:
          TERM: dumb
```

**Alternative (broader):** Set `TERM: dumb` as a job-level `env` to apply to all steps. This would also prevent ANSI in Ruff and Mypy output, making CI logs slightly less colorful but ensuring no ANSI-related issues anywhere.

**Verification:** The fix was tested locally by setting `$env:GITHUB_ACTIONS = "true"; $env:TERM = "dumb"` — all 4 previously-failing tests pass.

### Fix 3: Upgrade `astral-sh/setup-uv` (maintenance)

**Exact change in `.github/workflows/ci.yml`:**

```yaml
      - uses: astral-sh/setup-uv@v5
```

Change `@v3` → `@v5`. This resolves the Node.js 20 deprecation warnings (hard deadline: June 2, 2026).

### Remediation Checklist (Single-Pass)

All 3 fixes are independent and can be applied in any order. Recommended order for minimal risk:

```
Step 1: Add mypy override for ipc.py in pyproject.toml
  Add [[tool.mypy.overrides]] for mower_rover.vslam.ipc
  Verify: uv run mypy → 0 errors

Step 2: Add TERM=dumb to CI Pytest step in ci.yml
  Add env: TERM: dumb to the Pytest step
  Verify: uv run pytest with GITHUB_ACTIONS=true and TERM=dumb → 475 passed

Step 3: Upgrade setup-uv action version in ci.yml
  Change astral-sh/setup-uv@v3 → @v5
  No local verification needed — action version bump

Step 4: Push and verify CI
  git add pyproject.toml .github/workflows/ci.yml
  git commit -m "fix: resolve CI failures (mypy cross-platform, Rich ANSI, setup-uv upgrade)"
  git push
  Verify: Both ubuntu-latest and windows-latest jobs green
```

### Addressing Open Questions from Research 012

**Q: Should `.pre-commit-config.yaml` be added?**
A: Already done — `.pre-commit-config.yaml` exists with ruff check + ruff format hooks (added in plan 011). Consider adding a mypy hook in the future, but mypy is slower and may be better left to CI only.

**Q: Should branch protection rules be configured for `main`?**
A: Recommended but outside the scope of this CI fix. Branch protection requires:
- Require pull request reviews before merge
- Require status checks to pass (select the `lint-test` jobs)
- This prevents direct pushes to `main` that bypass CI

This is a GitHub repository settings change, not a code change. Document as a follow-up task.

### Expected CI Outcome After Fixes

| Platform | Ruff | Mypy | Pytest | Overall |
|----------|------|------|--------|---------|
| ubuntu-latest | pass | pass (override suppresses unused-ignore) | pass (TERM=dumb prevents ANSI) | **GREEN** |
| windows-latest | pass | pass (type: ignore still valid) | pass (TERM=dumb prevents ANSI) | **GREEN** |

**Key Discoveries:**
- All 3 fixes are simple, independent, and low-risk
- The mypy fix is a 3-line `pyproject.toml` addition (no source code changes)
- The ANSI fix is a 2-line `ci.yml` addition
- The setup-uv fix is a single version string change
- Pre-commit hooks already exist (resolved from research 012)
- Branch protection is recommended as a follow-up but not a code change

| File | Relevance |
|------|-----------|
| `pyproject.toml` | Add mypy override for ipc.py |
| `.github/workflows/ci.yml` | Add TERM=dumb env, upgrade setup-uv |

**Gaps:** None
**Assumptions:** `astral-sh/setup-uv@v5` is backward-compatible with the existing workflow configuration

## Overview

After the 28 lint/type-check fixes in plan 011 (research 012), only **2 CI-blocking issues** remain — both environment-specific, invisible to local development. The ubuntu-latest job fails on a single mypy `unused-ignore` error caused by a cross-platform `type: ignore[attr-defined]` on `socket.AF_UNIX` in `ipc.py` — needed on Windows (where `AF_UNIX` doesn't exist) but flagged as unused on Linux (where it does). The windows-latest job fails 4 pytest tests because GitHub Actions sets `GITHUB_ACTIONS=true`, causing Rich to force ANSI terminal formatting in Typer's `CliRunner` buffer, which splits `--option` strings with escape codes and breaks literal string assertions.

Both fixes are simple, independent, and low-risk: a 3-line mypy per-file override in `pyproject.toml` and a 2-line `TERM: dumb` env addition to the CI workflow. An additional maintenance fix upgrades `astral-sh/setup-uv` from v3 to v5 to resolve Node.js 20 deprecation warnings before the June 2, 2026 hard deadline. All three changes can be applied in a single commit. Ruff is clean, all 475 tests pass locally, and Python 3.11 is consistent between CI and local — the version mismatch concern from the introduction was unfounded.

## Key Findings

1. **Only 2 CI blockers remain** — one mypy error (Ubuntu) and one Rich ANSI issue (Windows/both)
2. **Cross-platform mypy conflict:** `# type: ignore[attr-defined]` on `socket.AF_UNIX` is needed on Windows but flagged as `unused-ignore` on Linux under strict mode
3. **Rich forces ANSI when `GITHUB_ACTIONS=true`** — splits `--option` strings with escape codes, breaking 4 test assertions
4. **`TERM=dumb` disables all Rich ANSI formatting** — confirmed fix; `NO_COLOR=1` is insufficient
5. **Python 3.11 consistent** — no version mismatch between CI and local
6. **`astral-sh/setup-uv` is 2 versions behind** (v3 → v5) with Node.js 20 deprecation deadline June 2, 2026
7. **Pre-commit hooks already exist** (ruff check + ruff format) — open question from research 012 resolved

## Actionable Conclusions

1. Add `[[tool.mypy.overrides]]` for `mower_rover.vslam.ipc` with `warn_unused_ignores = false` in `pyproject.toml`
2. Add `env: TERM: dumb` to the Pytest step in `.github/workflows/ci.yml`
3. Upgrade `astral-sh/setup-uv@v3` → `@v5` in `ci.yml`
4. All 3 fixes in a single commit: `fix: resolve CI failures (mypy cross-platform, Rich ANSI, setup-uv upgrade)`
5. Follow-up: configure GitHub branch protection rules for `main` (require PR + passing CI)

## Open Questions

- Should `TERM=dumb` be set at the job level (affecting all steps) or only on the Pytest step?
- Should branch protection rules be configured for `main` now or deferred?
- Should a mypy pre-commit hook be added alongside the existing ruff hooks?

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-26 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/013-ci-pipeline-full-green.md |
