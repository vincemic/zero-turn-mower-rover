---
id: "010"
type: plan
title: "Full Jetson Deployment Automation — Flash to Mower-Ready"
status: ✅ Complete
created: "2026-04-26"
updated: "2026-04-26"
completed: "2026-04-26"
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-26 | pch-planner | Initial plan skeleton |
| v2.0 | 2026-04-26 | pch-planner | Complete plan with all sections, holistic review |
| v2.1 | 2026-04-26 | pch-plan-reviewer | Fixed RTAB-Map version (0.21.6), --from-step/--step mutual exclusivity, clear-host-key check logic, build delegation clarification, vslam_socket_active socket details, BringupContext.parallel_builds field |
## Introduction

This plan implements the deployment automation designed in [research 011](/docs/research/011-full-jetson-deployment-automation.md). It extends the existing 9-step `mower jetson bringup` CLI to an 18-step pipeline that closes 11 identified gaps, adds build acceleration (binary archive, ccache, parallel builds), fixes 3 critical bugs (RTAB-Map tag, depthai-core pinning, `loginctl enable-linger`), adds 3 new probe checks, and introduces streaming SSH transport for long-running C++ builds. Target: ~640 LOC across 2 new files and 5 modified files.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Scope: full pipeline vs critical-fixes-first | C — Pipeline expansion absorbs fixes | Bug fixes (RTAB-Map tag, depthai pin, enable-linger) are naturally absorbed into the new decomposed steps; no throwaway intermediate code |
| 2 | Orchestration approach | A — Extended CLI (from research 011) | Zero new deps, BringupStep pattern 70% built, Windows-proven, Fabric/Ansible rejected |

## Holistic Review

### Decision Interactions

1. **Pipeline expansion absorbs bug fixes** — The decomposed build steps (7-9) use correct version tags from the start. The old monolithic `harden` step is replaced by `harden-os` (OS-only) + separate build steps. No intermediate state where old bugs exist in new code. **Build steps in bringup.py run remote shell commands directly via `run_streaming()`** — they do NOT call `harden_rtabmap()` / `harden_depthai_core()` from `jetson-harden.sh`. Those bash functions remain in the script for standalone/manual use but are skipped by `--os-only`. The Python build steps replicate the cmake/make logic (with correct version pins, ccache, and version markers) so all orchestration, timeout, and progress feedback lives in Python.

2. **Streaming SSH enables build steps** — `run_streaming()` (Phase 1) is a prerequisite for build steps (Phase 3) to provide real-time feedback. Without it, 30+ min builds would appear hung. The `on_line` callback pattern integrates cleanly with `rich.Live`.

3. **Binary archive creates fast-path skip** — `restore-binaries` (step 6) + version marker checks means steps 7-9 skip via idempotency when archive matches. This interacts correctly with `--from-step`: even if you `--from-step build-rtabmap`, the check sees markers from restore and skips.

4. **Parallel builds interact with `--continue-on-error`** — If one parallel build fails and the other succeeds, `--continue-on-error` allows the pipeline to continue to `build-slam-node` which will fail because it needs both dependencies. The failure summary correctly reports both the original build failure and the dependent failure.

### Architectural Considerations

- **Thread safety**: `run_streaming()` is called from threads during parallel builds. Each thread has its own `Popen` process — no shared state. The `on_line` callbacks write to separate `rich.Live` contexts or are serialized by the Rich console lock.
- **SSH connection reuse**: Each step creates its own SSH subprocess — no connection pooling, no multiplexing. This is intentional (matches existing pattern) and avoids complexity for a single-device tool.
- **Reboot steps break SSH state**: Steps 5 and 18 trigger reboots. The polling loop creates fresh SSH connections each attempt. No stale connection cleanup needed because each `client.run()` spawns a new subprocess.

### Trade-offs Accepted

- **No `nohup`/`tmux` wrapper for builds**: Research suggested SSH-surviving builds but this adds complexity. `ServerAliveInterval=30` + streaming keeps the connection alive. If SSH drops, `--from-step build-<component>` resumes via idempotency. Accepted risk.
- **No cross-compilation**: Native builds take ~65-75 min (fresh) but binary archive reduces repeat deploys to ~15 min. Accepted trade-off for single-device project.
- **`jq` dependency on Jetson**: Required for version marker reads. Installed in OS harden step. Fall back to file-existence check if `jq` unavailable.

### Risks Acknowledged

- SLAM cold-start time (120s timeout) is an estimate — needs field measurement. Mitigated by making timeout configurable.
- `Popen` streaming on Windows OpenSSH for >30 min — needs early prototyping in Phase 1 to validate. Fallback: periodic progress dots via `run()` with shorter timeouts.

## Overview

Extend `mower jetson bringup` from 9 steps to 18 steps, closing all 11 gaps identified in research 011. The expanded pipeline decomposes the monolithic `harden` step (which currently runs OS hardening + three C++ builds in a single 1200s-timeout SSH call) into discrete steps with individual timeouts, idempotency checks, and retry capability. New capabilities include: binary archive save/restore for instant same-JetPack re-deployment, parallel C++ builds (opt-in), streaming SSH output for long-running builds, `loginctl enable-linger` for user-service persistence, post-deploy reboot-and-verify loop, and 3 new runtime probe checks.

**Objectives:**
1. Close all 11 deployment gaps (G1–G11) from research 011 Phase 2
2. Reduce repeat-deployment time from ~80 min to ~15 min via binary archive restore
3. Add `--from-step`, `--continue-on-error`, `--parallel-builds` CLI flags
4. Add `run_streaming()` SSH transport method for real-time build output
5. Add 3 new probe checks: `health_service`, `loginctl_linger`, `vslam_socket_active`
6. Add `mower jetson backup` and `mower jetson clear-host-key` CLI commands
7. Fix RTAB-Map tag (0.23.2→0.21.6 to match field-proven install), pin depthai-core to v3.5.0
8. Add `--os-only` flag to `jetson-harden.sh` for decomposed pipeline

## Requirements

### Functional

1. **FR-1: 18-step bringup pipeline** — `mower jetson bringup` executes 18 ordered steps (clear-host-key → final-verify), each with idempotent `check()` and `execute()` methods following the existing `BringupStep` pattern.
2. **FR-2: Decomposed C++ builds** — RTAB-Map (v0.21.6), depthai-core (v3.5.0), and SLAM node each get their own step with individual timeouts (3600s, 3600s, 600s respectively) and version-marker-based idempotency.
3. **FR-3: Binary archive save/restore** — `archive-binaries` step creates a tar.gz of build outputs (~40-60 MB); `restore-binaries` step restores from archive when version markers match, skipping all C++ compilation.
4. **FR-4: `--from-step NAME`** — Run all steps starting from a named step; steps before it still run but skip via idempotency checks. **Mutually exclusive with existing `--step`** — `--step` runs exactly one step (existing behavior), `--from-step` runs from a step onward. If both are given, emit error and exit.
5. **FR-5: `--continue-on-error`** — Non-gate steps can fail without aborting the pipeline; gate steps (`check-ssh`) remain fatal. Report all failures at end.
6. **FR-6: `--parallel-builds`** — Opt-in flag to build RTAB-Map and depthai-core simultaneously (6 cores each).
7. **FR-7: Streaming SSH** — `JetsonClient.run_streaming()` via `subprocess.Popen` for real-time build output during 30+ min operations.
8. **FR-8: Reboot-and-wait** — `reboot-and-wait` step triggers `sudo reboot`, polls SSH every 10s, verifies `/proc/cmdline` has expected kernel params.
9. **FR-9: `enable-linger`** — New step runs `sudo loginctl enable-linger <user>` so user-level systemd services survive SSH logout and reboot.
10. **FR-10: 3 new probe checks** — `health_service` (CRITICAL), `loginctl_linger` (WARNING), `vslam_socket_active` (CRITICAL with 10s timeout).
11. **FR-11: `mower jetson backup`** — SCP config files + binary archive from Jetson to laptop before reflash.
12. **FR-12: `mower jetson clear-host-key`** — Run `ssh-keygen -R <host>` to remove stale SSH host key after reflash.
13. **FR-13: `--os-only` flag for jetson-harden.sh** — Run only OS hardening steps (1-12), skipping C++ builds (13-15), for the decomposed pipeline.
14. **FR-14: Version markers** — JSON files in `/usr/local/share/mower-build/` recording component version, git commit, cmake flags, build date, JetPack version.
15. **FR-15: ccache integration** — Install ccache, configure `CMAKE_*_COMPILER_LAUNCHER=ccache` in build steps, 5 GB cache on NVMe.
16. **FR-16: Final verification** — `final-verify` step reboots, polls for SLAM cold-start (10s intervals, 120s timeout), runs full probe suite.

### Non-Functional

1. **NFR-1: Windows compatibility** — All laptop-side code runs on Windows with system `ssh`/`scp` binaries (no paramiko).
2. **NFR-2: Field-offline** — No internet dependency in operational commands. Internet required only for bench-time builds (apt, git clone).
3. **NFR-3: Structured logging** — All step outcomes logged via `structlog` with correlation IDs.
4. **NFR-4: Idempotency** — Every step safe to re-run; check-then-execute pattern with end-state verification.
5. **NFR-5: Reproducibility** — All C++ builds pinned to specific tags/versions; version markers enable precise skip-build decisions.
6. **NFR-6: Progress feedback** — Rich progress display with step name + elapsed time; streaming last-line display for builds.

### Out of Scope

1. Cross-compilation from x86 host (research 011 rejected this)
2. nvpmodel switching for builds (marginal ~4-8 min gain, not worth complexity)
3. First-boot automation via rootfs injection (requires CLI flash from Linux, not SDK Manager Windows GUI)
4. Custom partitioning of 2 TB NVMe (default single APP partition is sufficient)
5. NTRIP or internet-dependent corrections paths
6. Automated SDK Manager flash (remains manual GUI operation)

## Technical Design

### Architecture

The deployment pipeline is a linear sequence of 18 `BringupStep` instances orchestrated by `bringup_command()` in `bringup.py`. Each step has:
- `check(client) → bool`: idempotency guard — returns `True` if step is already satisfied
- `execute(client, bctx) → None`: performs the work; raises `typer.Exit(code=3)` on failure
- `gate: bool`: new field — if `True`, failure aborts the entire pipeline regardless of `--continue-on-error`
- `needs_confirm: bool`: requires operator confirmation unless `--yes`

**Step Pipeline (18 steps):**

```
 1. clear-host-key    — ssh-keygen -R <host> (post-reflash)
 2. check-ssh         — Gate: SSH echo test
 3. enable-linger     — loginctl enable-linger for user services
 4. harden-os         — jetson-harden.sh --os-only (steps 1-12)
 5. reboot-and-wait   — Reboot for kernel params, poll SSH
 6. restore-binaries  — Restore from binary archive (fast path)
 7. build-rtabmap     — RTAB-Map 0.21.6 source build
 8. build-depthai     — depthai-core v3.5.0 source build
 9. build-slam-node   — Custom SLAM node binary
10. archive-binaries  — Save binary archive for future restores
11. pixhawk-udev      — Pixhawk udev rules + runtime dirs
12. install-uv        — uv + Python 3.11
13. install-cli       — mower-jetson CLI wheel
14. verify            — Remote probe (existing)
15. vslam-config      — VSLAM configuration
16. service           — mower-health.service
17. vslam-services    — VSLAM + bridge services
18. final-verify      — Reboot → poll (10s/120s) → full probe
```

**Key behaviors:**
- Steps 7+8 can run in parallel with `--parallel-builds` (via `threading.Thread`, `-j6` each)
- Step 6 (`restore-binaries`) — if archive matches version markers, steps 7-9 skip via idempotency
- Step 10 (`archive-binaries`) is non-fatal
- Step 5 (`reboot-and-wait`) polls SSH every 10s for up to 180s
- Step 18 (`final-verify`) polls probe every 10s for up to 120s (SLAM cold-start)

**CLI surface:**

```
mower jetson bringup [--from-step NAME] [--yes] [--continue-on-error] [--parallel-builds]
mower jetson backup [--output-dir ./backups/]
mower jetson clear-host-key
```

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: BringupStep(check, execute)
    location: "src/mower_rover/cli/bringup.py"
    usage: All 9 new steps follow this existing dataclass pattern
  - pattern: JetsonClient SSH transport
    location: "src/mower_rover/transport/ssh.py"
    usage: New run_streaming() method extends existing subprocess-based transport
  - pattern: Probe check registry
    location: "src/mower_rover/probe/registry.py"
    usage: 3 new checks use @register decorator with severity + depends_on
  - pattern: Idempotent bash guard clauses
    location: "scripts/jetson-harden.sh"
    usage: Version markers, --os-only flag, ccache integration follow existing STATUS[] pattern
  - pattern: CLI router (Typer)
    location: "src/mower_rover/cli/"
    usage: New backup/clear-host-key subcommands registered on existing jetson group
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Streaming SSH Transport

New method `JetsonClient.run_streaming()` using `subprocess.Popen` instead of `subprocess.run`:

```python
def run_streaming(
    self,
    remote_argv: Sequence[str],
    *,
    timeout: float | None = 3600.0,
    on_line: Callable[[str], None] | None = None,
    extra_env: dict[str, str] | None = None,
) -> SshResult:
```

- Streams `stdout` line-by-line, calling `on_line(line)` for each
- `on_line` callback updates a `rich.Live` display showing last line + elapsed time
- Adds `ServerAliveInterval=30` to SSH options to prevent drops during long builds
- Returns `SshResult` with full captured output on completion
- Falls back to `run()` behavior if `on_line` is `None`

### Version Markers

JSON files written to `/usr/local/share/mower-build/` on successful build:

```json
{
  "component": "rtabmap",
  "version": "0.21.6",
  "git_commit": "<sha>",
  "cmake_flags": "-DCMAKE_BUILD_TYPE=Release ...",
  "build_date": "2026-04-26T12:00:00Z",
  "jetpack": "6.2.2"
}
```

Check functions read markers with `jq` to decide whether to skip builds.

### Binary Archive Format

Contents (~40-60 MB compressed):
- `/usr/local/lib/librtabmap*`, `/usr/local/lib/libdepthai*`
- `/usr/local/lib/cmake/RTABMap*/`, `/usr/local/lib/cmake/depthai*/`
- `/usr/local/include/rtabmap/`, `/usr/local/include/depthai/`
- `/usr/local/bin/rtabmap*`, `/usr/local/bin/rtabmap_slam_node`
- `/usr/local/share/mower-build/*.json` (version markers)

Archive path: `/var/lib/mower/backups/native-builds-jp622-{date}.tar.gz`
Laptop backup path: `~/.local/share/mower/backups/`

### New Probe Checks

| Check Name | Severity | Depends On | Implementation |
|---|---|---|---|
| `health_service` | CRITICAL | — | `systemctl --user is-active mower-health.service` |
| `loginctl_linger` | WARNING | — | `loginctl show-user $USER -p Linger` → `Linger=yes` |
| `vslam_socket_active` | CRITICAL | `vslam_bridge` | Connect to Unix socket at `sysroot / "run/mower/vslam-pose.sock"` with `socket.settimeout(10)`, read ≥1 118-byte pose message. Returns `(True, "pose received, confidence=X")` or `(False, "timeout/no data")`. Uses `socket.AF_UNIX` + `socket.SOCK_STREAM`. |

### jetson-harden.sh Changes

1. **`--os-only` flag**: New CLI argument parsed in `main()`; when set, exit after step 12 (before C++ builds)
2. **RTAB-Map tag fix**: `local tag="0.23.2"` → `local tag="0.21.6"` in `harden_rtabmap()` (matches field-proven install; version check grep updated to `0\.21`)
3. **depthai-core version pin**: Add `local tag="v3.5.0"` and `--branch "$tag"` to `git clone` in `harden_depthai_core()`
4. **ccache integration**: `apt-get install -y ccache`, add `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CUDA_COMPILER_LAUNCHER=ccache` to cmake invocations, set `CCACHE_DIR=/var/lib/mower/ccache`, `ccache -M 5G`
5. **Version marker writes**: After each successful build, write JSON marker to `/usr/local/share/mower-build/{component}.json`
6. **Version-marker-based skip**: Replace binary-existence checks with `jq -e --arg t "$tag" '.version == $t' "$marker"`

### Modified Files Summary

| File | Changes | Est. LOC |
|------|---------|----------|
| `src/mower_rover/cli/bringup.py` | 9 new steps, `--from-step`, `--continue-on-error`, `--parallel-builds`, `BringupStep.gate` field, parallel build threading | ~300 |
| `src/mower_rover/transport/ssh.py` | `run_streaming()` method | ~60 |
| `scripts/jetson-harden.sh` | `--os-only`, tag fixes, ccache, version markers | ~80 |
| `src/mower_rover/probe/checks/vslam.py` | `vslam_socket_active` check | ~30 |
| `src/mower_rover/cli/__init__.py` (or router) | Register `backup`, `clear-host-key` commands | ~10 |

### New Files

| File | Purpose | Est. LOC |
|------|---------|----------|
| `src/mower_rover/probe/checks/service.py` | `health_service` + `loginctl_linger` checks | ~50 |
| `src/mower_rover/cli/backup.py` | `mower jetson backup` command | ~120 |

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `rich` | Existing Python dep | Used for `Live` display in streaming builds |
| `typer` | Existing Python dep | CLI framework |
| `structlog` | Existing Python dep | Logging |
| `threading` | Python stdlib | Parallel builds |
| `subprocess` | Python stdlib | `Popen` for streaming |
| `jq` | Remote (Jetson) | Version marker reads — install via `apt` in harden |
| `ccache` | Remote (Jetson) | Build acceleration — install via `apt` in harden |
| System `ssh`/`scp` | Laptop | Already required by existing transport |
| Research 011 | Research doc | Design authority for this plan |
| Plans 002, 005 | Prior plans | Existing bringup infrastructure this plan extends |

## Risks

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| RTAB-Map 0.21.6 API differs from future 0.23.x | SLAM node source needs changes on upgrade | Low | Version pinned to field-proven 0.21.6; future 0.23.x upgrade is separate task |
| SSH drops during 30+ min builds | Build restart required | Medium | `ServerAliveInterval=30` in streaming SSH; `nohup` wrapper if needed |
| Binary archive ABI breaks across JetPack minor versions | Silent runtime failures | Low | Version markers include JetPack version; restore checks JetPack match |
| SLAM cold-start exceeds 120s polling timeout | False failure in final-verify | Medium | Make timeout configurable; log warning but don't fail if services are running |
| Parallel builds exceed memory (64 GB) | OOM during build | Very Low | 16-18 GB peak for parallel builds — well within 64 GB |
| `Popen` streaming on Windows OpenSSH for >30 min | Unknown behavior | Medium | Prototype early; fall back to `run()` with periodic progress dots |
| `jq` not available on fresh flash | Version marker check fails | Low | Install `jq` in OS harden step; fall back to file-existence check |

## Execution Plan

### Phase 1: Transport Layer + BringupStep Refactor

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2
**Prerequisites:** None
**Entry Point:** `src/mower_rover/transport/ssh.py`
**Verification:** `pytest tests/test_transport_ssh.py` passes; `run_streaming()` available on `JetsonClient`

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| Step | Task | Status | Files | Acceptance Criteria |
|------|------|--------|-------|---------------------|
| 1.1 | Add `run_streaming()` method to `JetsonClient` | ✅ Complete | `src/mower_rover/transport/ssh.py` | Method exists with signature `run_streaming(remote_argv, *, timeout, on_line, extra_env) -> SshResult`. Uses `subprocess.Popen` with line-by-line stdout reading. Adds `ServerAliveInterval=30` to SSH options. Returns `SshResult` with full captured output. Falls back to buffered read if `on_line` is `None`. |
| 1.2 | Add `gate: bool = False` field to `BringupStep` dataclass | ✅ Complete | `src/mower_rover/cli/bringup.py` | `BringupStep` has `gate` field defaulting to `False`. |
| 1.3 | Add `--from-step` option to `bringup_command()` | ✅ Complete | `src/mower_rover/cli/bringup.py` | New `--from-step` typer Option. **Mutually exclusive with existing `--step`**: if both given, emit error and `typer.Exit(code=2)`. When `--from-step` is set, the `steps` list includes all steps from the named step onward; steps before it still run but skip via their `check()`. Validation: unknown step name → `typer.Exit(code=2)`. |
| 1.4 | Add `--continue-on-error` option to `bringup_command()` | ✅ Complete | `src/mower_rover/cli/bringup.py` | New flag. Non-gate step failures are collected in a list; gate step failures still abort immediately. After all steps, if failures exist, print summary table and exit code 1. |
| 1.5 | Add `--parallel-builds` option to `bringup_command()` | ✅ Complete | `src/mower_rover/cli/bringup.py` | New flag stored in `BringupContext` (add `parallel_builds: bool` field to dataclass). Actual parallel execution implemented in Phase 3. |
| 1.6 | Update `STEP_NAMES` tuple to include all 18 step names | ✅ Complete | `src/mower_rover/cli/bringup.py` | `STEP_NAMES` contains all 18 names in order. |
| 1.7 | Update `bringup_command()` main loop for `gate` + `--continue-on-error` + `--from-step` | ✅ Complete | `src/mower_rover/cli/bringup.py` | Main loop respects gate flag, collects non-gate errors, starts from `--from-step` position, prints failure summary table at end. |
| 1.8 | Add unit tests for `run_streaming()` | ✅ Complete | `tests/test_transport_ssh.py` | Test with mock `Popen` that streaming produces correct `SshResult`; test `on_line` callback is invoked per line; test timeout behavior. |

#### Phase 1 Implementation Notes

**Completed:** 2026-04-26
**Execution Mode:** Automatic (Subagent)

**Files Modified:**
- `src/mower_rover/transport/ssh.py`
- `src/mower_rover/cli/bringup.py`
- `tests/test_transport_ssh.py`
- `tests/test_bringup.py`

**Deviations from Plan:**
- Renamed existing `harden` step entry to `harden-os` in BRINGUP_STEPS to match new STEP_NAMES
- Reordered BRINGUP_STEPS to put `vslam-config` before `service` matching STEP_NAMES order
- Updated `test_step_names_match_bringup_steps` to check subset+order rather than exact equality (BRINGUP_STEPS has 9 of 18 until later phases)
- Updated `test_step_names_tuple` to match new 18-name STEP_NAMES

**Notes:**
- `run_streaming()` uses `subprocess.Popen` with line-by-line stdout iteration
- `ServerAliveInterval=30` injected after ssh binary in argv
- Timeout applied at `proc.wait()` after stdout EOF
- `--from-step` skips steps before the target index
- `--continue-on-error` wraps `execute()` in try/except, collecting non-gate failures in a list displayed as Rich table
- `parallel_builds` field added to `BringupContext` with default `False`

### Phase 2: New Bringup Steps (clear-host-key through reboot-and-wait)

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2
**Prerequisites:** Phase 1 complete (BringupStep.gate, STEP_NAMES updated)
**Entry Point:** `src/mower_rover/cli/bringup.py`
**Verification:** `pytest tests/test_bringup.py` passes; steps 1-5 registered in `BRINGUP_STEPS`

| Step | Task | Status | Files | Acceptance Criteria |
|------|------|--------|-------|---------------------|
| 2.1 | Implement `clear-host-key` step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: Attempts SSH connection; returns `True` if SSH succeeds (no host-key issue). If SSH fails, inspects stderr for `REMOTE HOST IDENTIFICATION HAS CHANGED` or `Host key verification failed` — returns `False` only on host-key errors (other SSH failures return `True` to skip this step and let `check-ssh` gate handle them). `execute()`: runs `ssh-keygen -R <host>` locally via `subprocess.run`. Not a gate step. |
| 2.2 | Implement `enable-linger` step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: `loginctl show-user <user> -p Linger --value` returns `yes`. `execute()`: `sudo loginctl enable-linger <user>`. |
| 2.3 | Implement `harden-os` step (replaces old `harden`) | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: same as old `_harden_done()`. `execute()`: pushes `jetson-harden.sh`, runs `sudo bash jetson-harden.sh --os-only`, timeout 300s. Replaces the old `harden` step entry in `BRINGUP_STEPS`. |
| 2.4 | Implement `reboot-and-wait` step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: SSH connects AND `/proc/cmdline` contains `usbcore.autosuspend=-1`. `execute()`: `sudo reboot` (ignore SSH disconnect error), then poll SSH every 10s for up to 180s. On success, verify cmdline. |
| 2.5 | Implement `mower jetson clear-host-key` standalone CLI command | ✅ Complete | `src/mower_rover/cli/jetson_remote.py` | Typer command that resolves endpoint and runs `ssh-keygen -R <host>`. Registered on the `jetson` command group. |
| 2.6 | Update `BRINGUP_STEPS` list with steps 1-5 | ✅ Complete | `src/mower_rover/cli/bringup.py` | Steps `clear-host-key`, `check-ssh` (gate=True), `enable-linger`, `harden-os`, `reboot-and-wait` are in correct order at positions 1-5. Old `harden` step removed. |
| 2.7 | Add/update tests for new steps | ✅ Complete | `tests/test_bringup.py` | Tests for `clear-host-key`, `enable-linger`, `harden-os`, `reboot-and-wait` check/execute with mocked `JetsonClient`. |

#### Phase 2 Implementation Notes

**Completed:** 2026-04-26
**Execution Mode:** Automatic (Subagent)

**Files Modified:**
- `src/mower_rover/cli/bringup.py`
- `src/mower_rover/cli/jetson_remote.py`
- `tests/test_bringup.py`

**Deviations from Plan:** None

**Notes:**
- `_clear_host_key_needed()` inspects both `SshResult.stderr` and `SshError` message for host-key error strings
- `_linger_enabled()` uses `loginctl show-user <user> -p Linger --value`
- `_run_harden()` updated to pass `--os-only` flag, timeout reduced 1200s → 300s
- `_run_reboot_and_wait()` polls SSH every 10s for 180s, verifies `usbcore.autosuspend=-1` in `/proc/cmdline`
- `clear_host_key_command()` registered as `@app.command("clear-host-key")` in jetson_remote.py
- 13 new test cases added, 75 total tests pass

### Phase 3: C++ Build Steps + Binary Archive

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2
**Prerequisites:** Phase 2 complete; Phase 1 `run_streaming()` available
**Entry Point:** `src/mower_rover/cli/bringup.py`, `scripts/jetson-harden.sh`
**Verification:** Steps 6-10 registered; `jetson-harden.sh --os-only` exits after step 12

| Step | Task | Status | Files | Acceptance Criteria |
|------|------|--------|-------|---------------------|
| 3.1 | Add `--os-only` flag to `jetson-harden.sh` | ✅ Complete | `scripts/jetson-harden.sh` | `main()` parses `$1` for `--os-only`; when set, skips `harden_rtabmap`, `harden_depthai_core`, `harden_slam_node`. Summary still prints OS-only steps. Step count label adjusts ("12/12" vs "15/15"). |
| 3.2 | Fix RTAB-Map tag: `0.23.2` → `0.21.6` | ✅ Complete | `scripts/jetson-harden.sh` | `harden_rtabmap()` uses `local tag="0.21.6"`. Version check grep updated to match `0\.21`. |
| 3.3 | Pin depthai-core to `v3.5.0` | ✅ Complete | `scripts/jetson-harden.sh` | `harden_depthai_core()` adds `local tag="v3.5.0"` and `git clone --branch "$tag"`. |
| 3.4 | Add ccache install + cmake integration | ✅ Complete | `scripts/jetson-harden.sh` | `apt-get install -y ccache` in build deps. `cmake` invocations add `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache -DCMAKE_C_COMPILER_LAUNCHER=ccache`. RTAB-Map also gets `-DCMAKE_CUDA_COMPILER_LAUNCHER=ccache`. Set `CCACHE_DIR=/var/lib/mower/ccache` and `ccache -M 5G`. |
| 3.5 | Add version marker writes to harden.sh | ✅ Complete | `scripts/jetson-harden.sh` | After each successful build, write JSON to `/usr/local/share/mower-build/{component}.json`. Install `jq` in build deps. Replace binary-existence idempotency checks with version-marker checks. |
| 3.6 | Implement `restore-binaries` bringup step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: all 3 version markers match expected versions. `execute()`: SCP archive from laptop → Jetson, `sudo tar -xzf ... -C /`, `sudo ldconfig`. Non-fatal if no archive exists. |
| 3.7 | Implement `build-rtabmap` bringup step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: version marker `rtabmap.json` has `version=0.21.6`. `execute()`: runs remote build commands via `run_streaming()` with 3600s timeout. |
| 3.8 | Implement `build-depthai` bringup step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: version marker `depthai.json` has `version=v3.5.0`. `execute()`: same pattern, clones `--branch v3.5.0 --recursive`. |
| 3.9 | Implement `build-slam-node` bringup step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: `/usr/local/bin/rtabmap_slam_node` exists AND version marker matches. `execute()`: pushes `contrib/rtabmap_slam_node/`, runs cmake + make. |
| 3.10 | Implement `archive-binaries` bringup step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: archive file exists for today's date. `execute()`: `tar -czf` of all build outputs + version markers. |
| 3.11 | Implement parallel build support | ✅ Complete | `src/mower_rover/cli/bringup.py` | When `--parallel-builds` is set, steps 7+8 run simultaneously via `threading.Thread` with `-j6`. |
| 3.12 | Add tests for build steps | ✅ Complete | `tests/test_bringup.py` | Mocked tests for all 5 new steps' check/execute. |

#### Phase 3 Implementation Notes

**Completed:** 2026-04-26
**Execution Mode:** Automatic (Subagent)

**Files Modified:**
- `scripts/jetson-harden.sh`
- `src/mower_rover/cli/bringup.py`
- `tests/test_bringup.py`

**Deviations from Plan:** None

**Notes:**
- jetson-harden.sh: `main()` parses `$1` for `--os-only`, uses dynamic `$total` (12 vs 15) for step labels
- All 3 build functions use version-marker JSON checks instead of binary-existence checks
- bringup.py: Added constants `RTABMAP_VERSION`, `DEPTHAI_VERSION`, `SLAM_NODE_VERSION`, `VERSION_MARKER_DIR`, `_BACKUP_DIR`
- Added `_read_version_marker()` helper for SSH + cat + JSON parse
- Parallel builds: when `bctx.parallel_builds` is True, `build-rtabmap` and `build-depthai` run in threads with `-j6`, `build-depthai` iteration is skipped
- 28 new tests, 103 total tests pass

### Phase 4: New Probe Checks

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2 (1 new, 1 modified)
**Prerequisites:** Phase 2 complete (services running after bringup)
**Entry Point:** `src/mower_rover/probe/checks/`
**Verification:** `pytest tests/test_probe.py tests/test_probe_vslam.py` passes; 3 new checks in registry

| Step | Task | Status | Files | Acceptance Criteria |
|------|------|--------|-------|---------------------|
| 4.1 | Create `service.py` with `health_service` check | ✅ Complete | `src/mower_rover/probe/checks/service.py` (NEW) | `@register("health_service", severity=Severity.CRITICAL)`. Runs `systemctl --user is-active mower-health.service`. Returns `(True, "active")` or `(False, "not active")`. Handles `FileNotFoundError` for non-systemd hosts. |
| 4.2 | Add `loginctl_linger` check to `service.py` | ✅ Complete | `src/mower_rover/probe/checks/service.py` | `@register("loginctl_linger", severity=Severity.WARNING)`. Runs `loginctl show-user $USER -p Linger --value`. Returns `(True, "Linger=yes")` or `(False, "Linger=no")`. |
| 4.3 | Add `vslam_socket_active` check to `vslam.py` | ✅ Complete | `src/mower_rover/probe/checks/vslam.py` | `@register("vslam_socket_active", severity=Severity.CRITICAL, depends_on=("vslam_bridge",))`. Opens AF_UNIX socket, reads 118-byte pose frame, parses confidence byte. |
| 4.4 | Import `service` module in probe checks `__init__.py` | ✅ Complete | `src/mower_rover/probe/checks/__init__.py` | `service` module imported so checks auto-register. |
| 4.5 | Add tests for new probe checks | ✅ Complete | `tests/test_probe_service.py` (NEW), `tests/test_probe_vslam.py` | Unit tests with mocked subprocess/socket for all 3 new checks. |

#### Phase 4 Implementation Notes

**Completed:** 2026-04-26
**Execution Mode:** Automatic (Subagent)

**Files Modified:**
- `src/mower_rover/probe/checks/__init__.py`
- `src/mower_rover/probe/checks/vslam.py`
- `tests/test_probe.py`
- `tests/test_probe_vslam.py`

**Files Created:**
- `src/mower_rover/probe/checks/service.py`
- `tests/test_probe_service.py`

**Deviations from Plan:**
- Added `hasattr(socket, "AF_UNIX")` guard in `vslam_socket_active` for Windows compatibility

**Notes:**
- `health_service` uses `systemctl --user is-active mower-health.service`
- `loginctl_linger` uses `os.environ.get("USER")` with `USERNAME` fallback for the loginctl command
- `vslam_socket_active` parses confidence byte at offset `msg_size - 2` from 118-byte frame
- 21 new tests added, 106 total tests pass

### Phase 5: Backup Command + Final Integration

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 3 (1 new, 2 modified)
**Prerequisites:** Phases 1-4 complete
**Entry Point:** `src/mower_rover/cli/`
**Verification:** Full `mower jetson bringup --help` shows all 18 steps + new flags; `mower jetson backup --help` works; all tests pass

| Step | Task | Status | Files | Acceptance Criteria |
|------|------|--------|-------|---------------------|
| 5.1 | Create `backup.py` with `mower jetson backup` command | ✅ Complete | `src/mower_rover/cli/backup.py` (NEW) | Typer command that pulls config files from Jetson, optionally includes binary archive. |
| 5.2 | Register `backup` and `clear-host-key` on jetson CLI group | ✅ Complete | `src/mower_rover/cli/jetson_remote.py` | Both commands accessible via `mower jetson backup` and `mower jetson clear-host-key`. |
| 5.3 | Implement `final-verify` bringup step | ✅ Complete | `src/mower_rover/cli/bringup.py` | `check()`: always returns False. `execute()`: reboot → SSH poll → probe poll → report table. |
| 5.4 | Wire all 18 steps into `BRINGUP_STEPS` in final order | ✅ Complete | `src/mower_rover/cli/bringup.py` | Complete ordered list of 18 BringupStep instances. `check-ssh` has `gate=True`. |
| 5.5 | Update module docstring and `--help` text | ✅ Complete | `src/mower_rover/cli/bringup.py` | Docstring reflects 18-step pipeline. |
| 5.6 | Integration tests | ✅ Complete | `tests/test_bringup.py` | End-to-end tests for all 18 steps, --from-step, --continue-on-error. |
| 5.7 | Verify all tests pass | ✅ Complete | All test files | 475 tests pass, 0 failures. |

#### Phase 5 Implementation Notes

**Completed:** 2026-04-26
**Execution Mode:** Automatic (Subagent)

**Files Modified:**
- `src/mower_rover/cli/bringup.py`
- `src/mower_rover/cli/jetson_remote.py`
- `tests/test_bringup.py`

**Files Created:**
- `src/mower_rover/cli/backup.py`

**Deviations from Plan:**
- Integration tests use `contextlib.ExitStack` to avoid Python 3.13 nested block compilation limit

**Notes:**
- backup.py pulls 5 config files + optional binary archive via `--include-binaries`
- `final-verify` reboots, polls SSH (10s/180s), polls probe --json (10s/120s), checks CRITICAL passes
- All 18 BringupStep entries in correct order, matching STEP_NAMES
- 475 total tests pass (116 in test_bringup.py)

### Plan Completion

**All phases completed:** 2026-04-26
**Total tasks completed:** 31
**Total files modified/created:** 12 (9 modified, 3 created)
**Code review:** 1 finding (fixed — SshError logging in backup.py)

## Standards

No organizational standards applicable to this plan.

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 6
**Last Updated:** 2026-04-26

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | RTAB-Map version: plan said 0.23.1 but 0.21.6 is field-proven | correctness | Pin to v0.21.6 (field-proven); 0.23.x upgrade is future work | All version refs updated: FR-2, Objectives, version marker example, harden.sh §3.2, build step §3.7, risk table |
| 2 | `--from-step` semantics conflict with existing `--step` | clarity | Mutually exclusive: `--step` = single step, `--from-step` = from step onward; error if both given | FR-4 updated, step 1.3 acceptance criteria updated |
| 3 | `clear-host-key` check() logic — how to detect host-key errors vs general SSH failures | correctness | Check SSH stderr for host-key-specific error messages; other failures return True (skip to check-ssh gate) | Step 2.1 acceptance criteria rewritten |
| 4 | Build steps duplicate harden.sh logic vs delegating | architecture | Build steps in bringup.py run remote commands directly via run_streaming(); harden.sh build functions remain for standalone use, skipped by --os-only | Holistic Review §1 expanded |
| 5 | `vslam_socket_active` probe — blocking socket read | correctness | Use `socket.settimeout(10)` with AF_UNIX/SOCK_STREAM; handle timeout, ConnectionRefused, FileNotFoundError | Probe check table + step 4.3 updated with socket details |
| 6 | `parallel_builds` field missing from BringupContext | specificity | Add `parallel_builds: bool` field to BringupContext dataclass | Step 1.5 updated, phase reference corrected to Phase 3 |

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 3 | 5 modified + 2 new across cli, transport, probe, scripts |
| New patterns introduced | 2 | Streaming SSH (Popen), parallel threading — both bounded |
| External dependencies | 1 | Only jq + ccache on Jetson (apt install) |
| Migration complexity | 1 | No data migration; additive changes to existing steps |
| Test coverage required | 3 | Unit tests for 9 new steps, streaming SSH, 3 probe checks |
| **Overall Complexity** | **10/25** | **Low-Medium** — mostly extends proven BringupStep pattern |

## Review Summary

**Review Date:** 2026-04-26
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 6 (Critical: 1, Major: 4, Minor: 1)
- Clarifying Questions Asked: 6 (all resolved autonomously based on codebase evidence)
- Sections Updated: Objectives, FR-2, FR-4, Holistic Review §1, Version Markers example, jetson-harden.sh Changes §3.2, Probe Checks table, Steps 1.3, 1.5, 2.1, 3.2, 3.6, 3.7, 4.3, Risk table

### Key Improvements Made
1. **RTAB-Map version corrected to v0.21.6** — terminal history proves this is the field-proven version; 0.23.x was never installed. Prevents build failure on non-existent tag.
2. **`--from-step` / `--step` mutual exclusivity specified** — prevents ambiguous behavior when both are given.
3. **`clear-host-key` check logic clarified** — now correctly distinguishes host-key errors from general SSH failures, avoiding false positives.
4. **Build delegation strategy documented** — build steps run remote commands directly via `run_streaming()`, not through harden.sh build functions. Eliminates confusion about code duplication.
5. **`vslam_socket_active` socket details specified** — `socket.settimeout(10)`, `AF_UNIX`/`SOCK_STREAM`, explicit error handling for timeout/connection/file-not-found.
6. **`BringupContext.parallel_builds` field added** — was referenced but not specified as a dataclass field change.

### Remaining Considerations
- SLAM cold-start polling timeout (120s) is an estimate — field measurement needed during Phase 5 implementation
- `Popen` streaming on Windows OpenSSH for >30 min sessions should be prototyped early in Phase 1 (step 1.1) before building Phase 3 steps that depend on it
- RTAB-Map 0.23.x upgrade should be tracked as a separate future work item
- The `jq` dependency for version markers should include a Python-side fallback (parse JSON via `json.loads` on laptop after `cat` over SSH) for robustness

### Sign-off
This plan has been reviewed and is **Ready for Implementation**

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-26 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-26 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/010-full-jetson-deployment-automation.md |
