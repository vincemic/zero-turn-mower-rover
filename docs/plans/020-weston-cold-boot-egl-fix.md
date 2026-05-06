---
id: "020"
type: plan
title: "Weston Cold-Boot EGL Initialization Fix"
status: "\u2705 Complete"
created: "2026-05-05"
updated: "2026-05-05"
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-05 | pch-planner | Initial plan skeleton |
| v2.0 | 2026-05-05 | pch-planner | All decisions captured, holistic review complete || v2.1 | 2026-05-05 | pch-plan-reviewer | Corrected ExecCondition placement (before ExecStartPre); fixed timing diagram; added test_exec_start fix to step 1.2 |
## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 2  
**Last Updated:** 2026-05-05

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | ExecCondition file placement vs execution order | Clarity | Option A: Place before ExecStartPre (match execution order) | Technical Design diagram + Phase B step 2.3 updated |
| 2 | Pre-existing test_exec_start failure | Correctness | Option A: Fix test assertion in Phase 1 step 1.2 | Step 1.2 updated to include `test_exec_start` fix |

## Introduction

Implement the two-phase fix for the Weston cold-boot EGL initialization failure on the Jetson AGX Orin, as specified in research doc 023. Phase A increases systemd restart budget so Weston survives the ~30s GPU render engine warmup. Phase B adds an `ExecCondition` EGL probe binary for clean, non-penalized polling.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Rollout strategy | B — Phase A + Phase B in one plan | Matches research 023's two-phase recommendation; Phase A unblocks cold boot immediately, Phase B layers proper EGL probe for clean polling |
| 2 | EGL probe deployment | B — `contrib/gpu-egl-ready/` with `build.sh` + source | Follows existing `contrib/rtabmap_slam_node/` pattern; version-controlled C source; on-device compilation trivial with gcc+libEGL already present |
| 3 | Bringup step placement | B — Inline within `_run_kiosk_services()` | EGL probe exclusively consumed by Weston unit; co-locating build ensures probe exists when unit deploys; --from-step kiosk-services rebuilds probe automatically |
| 4 | Root unit files | A — Update `weston.service`, delete `weston.unit` | Keeps human-readable reference in sync; removes stale card1 file that causes confusion |

## Holistic Review

### Decision Interactions

- Decisions 1+3 (both phases + inline in kiosk-services) create a clean deploy story: `--from-step kiosk-services` always produces the final state (Phase A + B together). No partial states.
- Decision 2 (contrib/ pattern) + Decision 3 (inline build) means the bringup step must `scp` or write the contrib directory to the Jetson then invoke `build.sh`. This matches how `build-slam-node` works (it uploads `contrib/rtabmap_slam_node/`).
- Decision 4 (update weston.service, delete weston.unit) means Phase 1 step 1.3 needs a `git rm weston.unit` and the reference file gets updated twice (once in Phase 1, again in Phase 3 after ExecCondition is added). This is fine — step 3.3 is the final sync.

### Architectural Considerations

- **No new runtime deps**: The probe links against `libEGL.so.1` already present on JetPack 6. The build-time dep `libegl-dev` provides headers only.
- **ExecCondition exit code semantics**: Exit 1-254 = skip (no burst penalty). Exit 255 = mark failed. The probe uses exit 1 (not ready) and exit 2 (fatal). Exit 2 < 255, so even fatal errors just skip — acceptable, since a missing libEGL means bigger problems.
- **Phase A is independently deployable**: If Phase B fails to compile on-device (e.g., missing headers), Phase A alone still fixes the cold-boot problem. The plan's phase ordering ensures this.

### Trade-offs Accepted

- Weston still crashes and restarts during the ~30s warmup (Phase A behavior) until Phase B's ExecCondition prevents the crash-restart cycle. Acceptable — crashes are clean and logged.
- The probe binary is aarch64-only (compiled on Jetson). Not testable on Windows CI. Only the source file and build script are version-controlled.

### Risks Acknowledged

- `libegl-dev` package name may differ on JetPack 6 — mitigated by checking `dpkg -l` output during bringup.
- Cannot field-validate until next cold boot power cycle — Phase A is safe to deploy speculatively.

## Overview

The Weston kiosk compositor fails on cold boot because NVIDIA's Tegra GPU render engine takes ~30s to become EGL-ready, but the current systemd unit exhausts its 5-retry budget in ~20s. The fix is two-phased:

- **Phase A (immediate):** Increase `StartLimitBurst=30`, reduce `RestartSec=2`, remove the ineffective `nvidia-smi` ExecStartPre. Weston retries for up to 60s — well past the ~30s GPU readiness threshold.
- **Phase B (proper):** Add a 30-line C binary (`gpu-egl-ready`) that calls `eglQueryDevicesEXT()` + `eglInitialize()`, deployed as `ExecCondition=`. Failed probes skip without burst penalty, producing clean logs and potentially triggering GPU init earlier.

**Objectives:**
1. Weston starts reliably on 100% of cold boots within 60s of kernel boot
2. No `start-limit-hit` failures in journal after power cycle
3. Zero new runtime dependencies (probe uses libEGL already present)
4. Maintain `--from-step kiosk-services` resume capability

## Requirements

### Functional

- FR-1: Weston service must survive GPU cold-boot delay (up to 45s) without entering `failed` state
- FR-2: `gpu-egl-ready` binary exits 0 when `eglQueryDevicesEXT()` returns ≥1 device AND `eglInitialize()` succeeds, exits 1 otherwise
- FR-3: `ExecCondition=/usr/local/bin/gpu-egl-ready` causes non-penalized skip when GPU not ready
- FR-4: `contrib/gpu-egl-ready/build.sh` compiles and installs binary to `/usr/local/bin/` idempotently
- FR-5: Bringup `kiosk-services` step builds and installs probe before deploying Weston unit

### Non-Functional

- NFR-1: Probe binary must complete in <100ms (no blocking/sleeping)
- NFR-2: No internet dependency — probe uses only local libEGL
- NFR-3: Phase A deployable independently (no Phase B dependency)
- NFR-4: All changes pass existing `test_kiosk_units.py` (updated assertions)

### Out of Scope

- Tuning GPU initialization timing (hardware-dependent)
- Verifying whether probe triggers vs merely tests GPU init (requires field measurement)
- `loginctl enable-linger` configuration (separate concern, noted in research)
- Alternative compositor evaluation (ruled out in research Phase 3)

## Technical Design

### Architecture

```
Cold Boot Sequence (after fix):
═══════════════════════════════════════════════════════════════

t=0s     nvidia-drm loads (modeset=1)
t=1s     systemd starts mower-weston attempt #1
         ExecCondition: gpu-egl-ready → exit 1 (skip, no burst penalty)
         (ExecStartPre never reached — unit skipped cleanly)
t=3s     Attempt #2: gpu-egl-ready → exit 1 (skip)
  ...    (retries every 2s, no burst count consumed)
t=30s    gpu-egl-ready → exit 0 (GPU ready!)
         ExecStartPre: mkdir -p /var/log/mower-jetson → OK
         ExecStartPre: DRM device wait → /dev/dri/card0 already present → OK
         ExecStart: Weston launches successfully
```

**Phase A only (no ExecCondition):** Same timeline but Weston itself crashes on each retry (noisier logs, consumes burst count — 30 burst budget still sufficient).

### Unit Template Changes (Phase A)

File: `src/mower_rover/service/unit.py` — `_WESTON_UNIT_TEMPLATE`

| Setting | Before | After | Reason |
|---------|--------|-------|--------|
| `StartLimitIntervalSec` | 300 | 120 | 2-min window (not 5 min) |
| `StartLimitBurst` | 5 | 30 | 60s retry budget at 2s interval |
| `RestartSec` | 3 | 2 | Faster polling |
| `ExecStartPre nvidia-smi` | present | **removed** | Ineffective on Tegra (monitoring path only) |

### Unit Template Changes (Phase B — additive)

| Setting | Value | Reason |
|---------|-------|--------|
| `ExecCondition` | `/usr/local/bin/gpu-egl-ready` | Non-penalized skip when GPU not ready |

Placement: BEFORE all ExecStartPre lines (matches systemd execution order: ExecCondition runs first, and only if it exits 0 do ExecStartPre lines execute).

### EGL Probe Binary

File: `contrib/gpu-egl-ready/gpu-egl-ready.c`

```c
/*
 * gpu-egl-ready.c — Minimal EGL device probe for NVIDIA Tegra.
 * Exit 0 = ready, Exit 1 = not ready, Exit 2 = fatal (missing libEGL).
 * Build: gcc -O2 -o gpu-egl-ready gpu-egl-ready.c -lEGL
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <stdio.h>

int main(void) {
    PFNEGLQUERYDEVICESEXTPROC eglQueryDevicesEXT =
        (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC eglGetPlatformDisplayEXT =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");

    if (!eglQueryDevicesEXT || !eglGetPlatformDisplayEXT) {
        fprintf(stderr, "gpu-egl-ready: EGL device extensions unavailable\n");
        return 2;
    }

    EGLDeviceEXT devices[4];
    EGLint num_devices = 0;
    if (!eglQueryDevicesEXT(4, devices, &num_devices) || num_devices == 0)
        return 1;

    EGLDisplay dpy = eglGetPlatformDisplayEXT(
        EGL_PLATFORM_DEVICE_EXT, devices[0], NULL);
    if (dpy == EGL_NO_DISPLAY) return 1;

    EGLint major, minor;
    if (!eglInitialize(dpy, &major, &minor)) return 1;

    eglTerminate(dpy);
    return 0;
}
```

File: `contrib/gpu-egl-ready/build.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="/usr/local/bin/gpu-egl-ready"

gcc -O2 -o "$BINARY" "$SCRIPT_DIR/gpu-egl-ready.c" -lEGL
chmod 755 "$BINARY"
echo "Installed: $BINARY"
```

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Unit Template Strings
    location: "src/mower_rover/service/unit.py"
    usage: _WESTON_UNIT_TEMPLATE is the single source of truth for the Weston systemd unit
  - pattern: Bringup Steps
    location: "src/mower_rover/cli/bringup.py"
    usage: _run_kiosk_services() deploys units via SSH
  - pattern: Contrib Build Scripts
    location: "contrib/rtabmap_slam_node/build.sh"
    usage: Pattern for new contrib/gpu-egl-ready/ with build.sh + source
  - pattern: Build Deps
    location: "src/mower_rover/cli/bringup.py"
    usage: _BUILD_APT_PACKAGES tuple for install-build-deps step
```

### Data Contracts

No data entities in scope — data contracts not applicable.

## Dependencies

| Dependency | Type | Required By | Notes |
|-----------|------|-------------|-------|
| `gcc` + `build-essential` | APT package | Phase B build | Already in `_BUILD_APT_PACKAGES` |
| `libegl-dev` | APT package | Phase B build | May already be satisfied by `nvidia-l4t-*`; add to `_BUILD_APT_PACKAGES` defensively |
| `libEGL.so.1` | Runtime library | Phase B probe | Present on all JetPack 6 installs |
| systemd ≥ v243 | System | Phase B `ExecCondition` | JetPack 6 ships systemd 249 (Ubuntu 22.04) |
| `install-build-deps` step | Bringup ordering | Phase B | Must run before `kiosk-services` to ensure gcc available |

## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| `libegl-dev` not available / different package name on JetPack 6 | Phase B build fails | Low | Check if `nvidia-l4t-weston` already provides headers; fall back to `libegl1-mesa-dev` |
| GPU takes >60s on some cold boots | Weston still fails (Phase A) | Very Low | Phase B with ExecCondition has no burst limit issue; increase StartLimitBurst further if needed |
| `EGL_PLATFORM_DEVICE_EXT` constant missing from JetPack headers | Probe won't compile | Low | Define manually: `#ifndef EGL_PLATFORM_DEVICE_EXT ... #define EGL_PLATFORM_DEVICE_EXT 0x313F` |
| Probe exits 2 (fatal) on missing libEGL | Service marked failed | Very Low | Only possible if libEGL removed; check at bringup time |
| Test `test_restart_sec_3` fails after Phase A | CI red | Certain | Update test assertion to `RestartSec=2` in same commit |

## Execution Plan

### Phase 1: Weston Unit Restart Budget (Phase A Fix)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 3  
**Prerequisites:** None  
**Entry Point:** `src/mower_rover/service/unit.py`  
**Verification:** `pytest tests/test_kiosk_units.py` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Update `_WESTON_UNIT_TEMPLATE`: change `StartLimitIntervalSec=300` → `120`, `StartLimitBurst=5` → `30`, `RestartSec=3` → `2`, remove the `ExecStartPre=+/bin/sh -c '/usr/sbin/nvidia-smi -q > /dev/null 2>&1'` line | `src/mower_rover/service/unit.py` (~L408-425) | Template string matches Phase A spec from Technical Design |
| 1.2 | Update `test_restart_sec_3` → `test_restart_sec_2` in `TestGenerateWestonUnit`; assert `RestartSec=2`; add `test_start_limit_burst_30` asserting `StartLimitBurst=30`; add `test_no_nvidia_smi` asserting `nvidia-smi` NOT in output; fix `test_exec_start` to include `--drm-device=card0` in expected string (pre-existing bug: template has it, test omits it) | `tests/test_kiosk_units.py` (~L121-148) | All kiosk unit tests pass (`pytest tests/test_kiosk_units.py` exit 0) |
| 1.3 | Update `weston.service` (repo root) to match new template output; delete `weston.unit` | `weston.service`, `weston.unit` | `weston.service` matches `generate_weston_unit_file()` output; `weston.unit` removed from repo |

### Phase 2: EGL Probe Binary (Phase B Fix)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 4 (2 new, 2 modified)  
**Prerequisites:** Phase 1 complete  
**Entry Point:** `contrib/gpu-egl-ready/`  
**Verification:** `gpu-egl-ready.c` compiles with `gcc -O2 -o gpu-egl-ready gpu-egl-ready.c -lEGL` on aarch64

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Create `contrib/gpu-egl-ready/gpu-egl-ready.c` with the EGL probe source from Technical Design | `contrib/gpu-egl-ready/gpu-egl-ready.c` (new) | File exists, compiles cleanly with `-Wall -Wextra` on aarch64 |
| 2.2 | Create `contrib/gpu-egl-ready/build.sh` following `contrib/rtabmap_slam_node/build.sh` pattern — compiles and installs to `/usr/local/bin/gpu-egl-ready` | `contrib/gpu-egl-ready/build.sh` (new) | Script is executable, idempotent, installs binary |
| 2.3 | Add `ExecCondition=/usr/local/bin/gpu-egl-ready` line to `_WESTON_UNIT_TEMPLATE` BEFORE all ExecStartPre lines (immediately after the `[Service]` / `Type=simple` lines) — matches systemd execution order | `src/mower_rover/service/unit.py` (~L413) | Template includes ExecCondition before ExecStartPre; systemd skips the entire activation attempt (including ExecStartPre) when ExecCondition exits non-zero |
| 2.4 | Add `test_exec_condition_gpu_probe` to `TestGenerateWestonUnit` asserting `ExecCondition=/usr/local/bin/gpu-egl-ready` present in output | `tests/test_kiosk_units.py` | Test passes |

### Phase 3: Bringup Integration + `libegl-dev` Dependency

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 2  
**Prerequisites:** Phase 2 complete  
**Entry Point:** `src/mower_rover/cli/bringup.py`  
**Verification:** `pytest tests/test_bringup.py` passes (if applicable); manual deploy via `--from-step kiosk-services`

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add `"libegl-dev"` to `_BUILD_APT_PACKAGES` tuple | `src/mower_rover/cli/bringup.py` (~L522) | Package in tuple; `_build_deps_check` includes it |
| 3.2 | In `_run_kiosk_services()`, before the "Deploy Weston unit" block: upload `contrib/gpu-egl-ready/` directory to Jetson (e.g., `/tmp/gpu-egl-ready/`), run `sudo bash /tmp/gpu-egl-ready/build.sh`, clean up temp files | `src/mower_rover/cli/bringup.py` (~L1780) | Probe build runs before Weston unit deploy; errors reported clearly; idempotent on re-run |
| 3.3 | Update `weston.service` (repo root) to include the `ExecCondition` line (final state after Phase B) | `weston.service` | File matches `generate_weston_unit_file()` output with ExecCondition |

## Standards

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 6 files across 3 phases (small, focused) |
| New patterns introduced | 1 | Follows existing contrib/ build pattern exactly |
| External dependencies | 1 | libEGL already present; libegl-dev for headers only |
| Migration complexity | 1 | No data migration; unit file replacement is atomic |
| Test coverage required | 2 | Unit tests only; field validation via cold boot |
| **Overall Complexity** | **7/25** | **Low** |

## Review Summary

**Review Date:** 2026-05-05  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.1  

### Review Metrics
- Issues Found: 4 (Critical: 0, Major: 2, Minor: 2)
- Clarifying Questions Asked: 2
- Sections Updated: Technical Design (timing diagram, ExecCondition placement), Execution Plan (step 1.2, step 2.3)

### Key Improvements Made
1. Corrected ExecCondition placement to before ExecStartPre (matches systemd execution semantics)
2. Updated timing diagram to accurately reflect ExecCondition → ExecStartPre → ExecStart order
3. Added pre-existing `test_exec_start` fix to Phase 1 (includes `--drm-device=card0`)
4. Minor line number corrections noted (off by ~15 lines — implementer should use anchor text, not line numbers)

### Remaining Considerations
- Line numbers in step references are approximate (~L408, ~L522, ~L1780) — use the function/variable names as anchors
- `test_exec_start` failure is pre-existing and unrelated to the cold-boot fix, but fixing it in the same commit keeps CI green
- Field validation requires actual cold-boot power cycle (not just `reboot`)

### Sign-off
This plan has been reviewed and is **Ready for Implementation**

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-05 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-05 |
| Status | ✅ Complete |
| Next Agent | — |
| Plan Location | /docs/plans/020-weston-cold-boot-egl-fix.md |

## Post-Implementation Update (2026-05-05)

### Outcome: Pivoted to Pixman Renderer

After deploying the plan as written (Phase A restart budget + Phase B EGL probe),
field testing on the Jetson with a display attached revealed a **deeper EGL
incompatibility** that the probe could not fix:

- On Tegra234 (Orin), the display controller lives on `card0` (`nv_platform`
  driver, `nvidia-drm` GBM backend).
- NVIDIA's EGL GBM external platform library (`libnvidia-egl-gbm.so`) only
  supports the `tegra` GBM backend which is on `card1`/`host1x`.
- `eglInitialize()` on a GBM device opened from `card0` **always** fails with
  `EGL_NOT_INITIALIZED (0x3001)` — this is architectural, not a timing issue.
- Even NVIDIA's own `nvstart-weston.sh` fails the same way.
- The `gpu-egl-ready` probe returned exit 0 (it uses device-level EGL, not GBM
  platform EGL), but Weston's `gl-renderer.so` still crashed.

### Final Fix

Switched to **`--renderer=pixman`** (CPU compositing). This bypasses EGL/GBM
entirely. For the kiosk use case (compositing a single fullscreen Chromium
window), CPU rendering is perfectly adequate — Chromium does its own GPU
acceleration internally.

### Changes from Original Plan

| Aspect | Plan | Actual |
|--------|------|--------|
| `ExecCondition` | Present (gpu-egl-ready) | **Removed** (not needed with pixman) |
| `--renderer` flag | Not specified (default=auto=gl) | **`--renderer=pixman`** |
| EGL probe binary | Built and deployed | **Removed from bringup** |
| `libegl-dev` dep | Added to _BUILD_APT_PACKAGES | **Removed** |
| Phase A restart budget | Deployed | **Retained** (still useful for DRM timing) |

### Verification

- Weston starts on cold boot within 2s (no EGL delay).
- `systemctl status mower-weston.service` shows `active (running)`.
- Display output confirmed on Samsung C27F591 via DP-1.
- All 813 tests pass.
