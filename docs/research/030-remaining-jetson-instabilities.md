---
id: "030"
type: research
title: "Remaining Jetson Service-Stack Instabilities & Fixes"
status: ✅ Complete
created: "2026-05-07"
current_phase: "5 of 5"
---

## Introduction

After Plan 026 (Jetson Startup Sequence & Pixhawk Reinitialization Fixes) was deployed, 7 of 8 services run stably. However, live diagnostics (2026-05-07T00:34 UTC) reveal several remaining instabilities: pixhawk-sync is stuck in a restart loop due to a parameter-apply failure, MAVLink FTP operations fail on both vslam-bridge and pixhawk-sync, Weston and kiosk-renderer fail on first boot before self-recovering, the RTAB-Map database has grown to 221 GB with 293 k+ nodes causing 100% loop-closure rejection, and the bringup tool leaves stale unit files when services are already active. This research investigates root causes and documents actionable fixes for each instability.

## Objectives

- Determine why `FS_GCS_TIMEOUT` PARAM_VALUE echo is missing and how to fix the param-apply logic
- Understand MAVLink FTP target-mismatch errors (`wrong MAVLink target 254 component 0`) and `/APM/scripts` write failures
- Root-cause the Weston first-boot exit-code-1 failure and kiosk-renderer SIGTERM cascade
- Assess the impact of a 221 GB RTAB-Map database on VSLAM performance and propose a maintenance strategy
- Fix the bringup tool's skip-when-active logic so unit files are always updated

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Pixhawk-Sync Param Apply Failure | ✅ Complete | `FS_GCS_TIMEOUT` no-echo root cause; param_apply retry/timeout logic; ArduPilot param-set behaviour for read-only or range-restricted params | 2026-05-07 |
| 2 | MAVLink FTP Failures & Lua Deploy | ✅ Complete | FTP target-mismatch 254/0 warnings via MAVProxy; `/APM/scripts` list/write fail; MAVProxy FTP module vs pymavlink `mavftp`; component-ID routing through UDP outputs | 2026-05-07 |
| 3 | Weston & Kiosk-Renderer Cold-Boot Race | ✅ Complete | Weston exit-code-1 on first start (DRM/KMS init timing?); kiosk-renderer ExecStartPre SIGTERM when Weston absent; recovery path timing; possible systemd ordering fixes | 2026-05-07 |
| 4 | RTAB-Map Database Bloat & Loop-Closure Degradation | ✅ Complete | 221 GB DB, 293 k+ nodes; 0/10 inliers on every loop closure; DB pruning/rotation strategy; `Rtabmap/MemoryThr`, `Rtabmap/DbSqlite3InMemory`, WM size limits; fresh-DB-per-session vs incremental pruning | 2026-05-07 |
| 5 | Bringup Stale-Unit-File Skip Logic | ✅ Complete | Current `bringup.py` step-skip when service active; unit-file update should always run regardless of service state; force-update + restart strategy; idempotent unit deployment | 2026-05-07 |

## Phase 1: Pixhawk-Sync Param Apply Failure

**Status:** ✅ Complete  
**Session:** 2026-05-07

**Observed symptoms (2026-05-07):**
- `mower-pixhawk-sync` in `activating (auto-restart)` state — restart counter at 2+
- Applies 6/7 params successfully, fails on `FS_GCS_TIMEOUT=5.0`: `"no PARAM_VALUE echo"`
- Lua deploy also fails (`write /APM/scripts/ahrs-source-gps-vslam.lua: Fail`) — see Phase 2
- Service exits with code 1, restarts every 30s via `Restart=on-failure`

### Root Cause: `FS_GCS_TIMEOUT` Does Not Exist on ArduPilot Rover 4.6.3

`FS_GCS_TIMEOUT` is defined in ArduPilot's `ParametersG2` at index 56 — added to the master branch for **ArduPilot 4.7**. The Pixhawk is running **Rover 4.6.3**, which lacks both index-55 (`MANUAL_STR_EXPO`) and index-56 (`FS_GCS_TIMEOUT`). Neither appears in the `mower.param` dump (854 params). On 4.6.x, the GCS failsafe timeout is hardcoded via `FS_TIMEOUT` (default 1.5s), not a dedicated `FS_GCS_TIMEOUT`.

### Failure Chain (Step by Step)

1. `safety-defaults.yaml` lists 7 params including `FS_GCS_TIMEOUT: 5`
2. `sync_params()` builds `desired` (all 7) and fetches `current_full` — `FS_GCS_TIMEOUT` absent
3. `diff_params()` marks `FS_GCS_TIMEOUT` as **"added"** (in desired, not in current)
4. `sync_params` passes **ALL 7 params** to `apply_params()`, not just the 1 that drifted
5. Params 1–6 succeed — ArduPilot echoes PARAM_VALUE for each
6. Param 7 (`FS_GCS_TIMEOUT`): PARAM_SET sent; ArduPilot silently ignores unknown param names. `_await_param_echo()` times out after 2s × 3 retries = 6s
7. `apply_params()` raises `RuntimeError("Failed to apply/verify 1 param(s): FS_GCS_TIMEOUT=5.0 (no PARAM_VALUE echo)")`
8. `sync_params()` records error → `result.ok == False`
9. CLI handler raises `typer.Exit(code=1)`
10. systemd `Restart=on-failure`, `RestartSec=30` → restarts in 30s
11. On restart: 6 params already match, but `FS_GCS_TIMEOUT` is still "added" → same failure repeats indefinitely

### Code Design Issues

**Issue A: `apply_params()` is all-or-nothing** — Any single param failure raises RuntimeError killing the entire operation. 6 successfully-applied params are wasted.

```python
# src/mower_rover/params/mav.py:109-113
if failures:
    joined = ", ".join(f"{n}={v} ({e})" for n, v, e in failures[:10])
    raise RuntimeError(
        f"Failed to apply/verify {len(failures)} param(s): {joined}"
    )
```

**Issue B: `sync_params()` passes ALL desired params, not just drifted ones**

```python
# src/mower_rover/pixhawk/sync.py:122
apply_params(conn, desired)  # all 7 params, not just the 1 that drifted
```

**Issue C: No detection of "param doesn't exist on firmware"** — When a param is "added" (in desired but not in `current_full`), there's no check whether the autopilot can accept it. ArduPilot silently ignores PARAM_SET for unknown param names.

**Issue D: `_await_param_echo` discards non-matching PARAM_VALUE messages** — While not the primary cause, stale messages from `fetch_params()` or MAVProxy could delay matching.

### ArduPilot Param-Set Behavior

- `FS_GCS_ENABLE` is a top-level `GSCALAR` (always present in all Rover versions)
- `FS_GCS_TIMEOUT` is a `ParametersG2` `AP_GROUPINFO` at index 56 (master/4.7 only)
- ArduPilot's `AP_Param::set()` silently drops PARAM_SET for unknown param names
- `FS_GCS_TIMEOUT` range is 2–120s, fully writable, no reboot required — but only on 4.7+
- On 4.6.3, GCS failsafe uses `FS_TIMEOUT` (currently 1.5s in `mower.param`)

### MAVProxy Interaction Assessment

Connection goes through MAVProxy on `udp:127.0.0.1:14552`. MAVProxy correctly forwards PARAM_SET and PARAM_VALUE messages. It is **NOT** the cause — the issue is purely that ArduPilot 4.6.3 doesn't recognize `FS_GCS_TIMEOUT`.

### Impact of `FS_GCS_TIMEOUT` Absence

On 4.6.3, the GCS failsafe uses `FS_TIMEOUT` (currently 1.5s). The effective timeout is more aggressive than the intended 5s and could cause spurious Hold mode entries during brief network blips.

### Recommended Fixes

**Fix 1 (Immediate — unblock pixhawk-sync):** Remove `FS_GCS_TIMEOUT` from `safety-defaults.yaml`. On 4.6.3, the GCS timeout is `FS_TIMEOUT`. If 5s is desired, set `FS_TIMEOUT=5` (but this also affects RC failsafe timing).

**Fix 2 (Resilience):** In `sync_params()`, skip "added" params that don't exist in `current_full` with a warning:
```python
for c in diff.added:
    log.warning("sync_param_not_on_firmware", name=c.name, value=c.new,
                hint="param may require firmware upgrade")
```

**Fix 3 (Graceful degradation):** Change `apply_params()` to return both `applied` and `failures` instead of raising, letting the caller decide severity.

**Fix 4 (Efficiency):** Pass only drifted params to `apply_params()`, not the full desired set.

**Key Discoveries:**
- `FS_GCS_TIMEOUT` is a **Rover 4.7+ parameter** (g2 index 56); does NOT exist on installed **Rover 4.6.3**
- Permanent restart loop: param always "added" in diff → `apply_params()` raises → exit(1) → systemd restart → repeat
- On 4.6.3, GCS failsafe timeout is `FS_TIMEOUT` (1.5s), not a dedicated GCS timeout
- `sync_params()` passes ALL desired params, not just drifted ones
- `apply_params()` is all-or-nothing — single failure kills the entire sync

| File | Relevance |
|------|-----------|
| `src/mower_rover/params/mav.py` | `apply_params()` and `_await_param_echo()` — source of RuntimeError |
| `src/mower_rover/pixhawk/sync.py` | `sync_params()` — passes full desired set instead of diff-only |
| `src/mower_rover/params/data/safety-defaults.yaml` | Contains incompatible `FS_GCS_TIMEOUT: 5` |
| `src/mower_rover/params/diff.py` | `diff_params()` — how "added" params are detected |
| `src/mower_rover/pixhawk/unit.py` | Unit file template with `Restart=on-failure`, `RestartSec=30` |
| `src/mower_rover/mavlink/connection.py` | `open_link()` with source_system=254, source_component=0 |
| `src/mower_rover/cli/jetson.py` | CLI handler raises `typer.Exit(code=1)` on `not result.ok` |
| `docs/config/mower.param` | Param dump confirming absence of FS_GCS_TIMEOUT |

**External Sources:**
- [ArduPilot Rover/Parameters.cpp](https://github.com/ArduPilot/ardupilot/blob/master/Rover/Parameters.cpp)
- [ArduPilot rover-failsafes.html](https://ardupilot.org/rover/docs/rover-failsafes.html)

**Gaps:** None  
**Assumptions:** Param dump via `PARAM_REQUEST_LIST` returns all params including defaults (confirmed by 854 params). ArduPilot 4.6.3 lacks g2 indices 55-56 (inferred from param dump + ArduPilot master source).

## Phase 2: MAVLink FTP Failures & Lua Deploy

**Status:** ✅ Complete  
**Session:** 2026-05-07

**Observed symptoms (2026-05-07):**
- vslam-bridge log: `FTP: wrong MAVLink target 254 component 0. Will discard message` (2× on every boot)
- vslam-bridge log: `list /APM/scripts: Fail`
- pixhawk-sync log: `write /APM/scripts/ahrs-source-gps-vslam.lua: Fail`
- MAVProxy is forwarding to 3 UDP outputs (14550, 14551, 14552) — FTP responses may be routed to wrong consumer

### Root Cause: Concurrent FTP Session Conflict

ArduPilot implements a **single-session FTP server** (one active file session at a time). Both `vslam-bridge` and `pixhawk-sync` attempt the same Lua script deploy (`check_and_deploy_lua`) with no systemd ordering between them, racing to do FTP simultaneously.

#### The Two FTP Clients

| Service | Port | source_system | source_component | FTP Response Target |
|---------|------|---------------|-------------------|---------------------|
| **vslam-bridge** | `udp:127.0.0.1:14550` | 1 | 197 (VIO) | `target=1/197` |
| **pixhawk-sync** | `udp:127.0.0.1:14552` | 254 (GCS) | 0 | `target=254/0` |

#### The "wrong MAVLink target 254 component 0" Warning

This warning is **cosmetic and expected**. Chain:
1. pixhawk-sync (source=254/0 on port 14552) sends FTP request
2. ArduPilot responds with `FILE_TRANSFER_PROTOCOL(target_system=254, target_component=0)`
3. MAVProxy **broadcasts** response to ALL three UDP outputs
4. vslam-bridge (source=1/197 on port 14550) receives it
5. MAVFTP checks: `254 != 1` (mismatch) → discards with warning

#### The MAVFTP Constructor Race

Both services create `MAVFTP` → constructor sends `OP_ResetSessions`:
```python
# pymavlink/mavftp.py line 296-297
self.__send(FTP_OP(self.seq, self.session, OP_ResetSessions, 0, 0, 0, 0, None))
self.process_ftp_reply('ResetSessions')
```

When both run concurrently:
1. Service A sends `ResetSessions` → ArduPilot acknowledges
2. Service B sends `ResetSessions` → ArduPilot acknowledges, **kills A's session state**
3. Both proceed to `cmd_mkdir`, `cmd_list`, `cmd_put` — ArduPilot's FTP state machine is confused by interleaved requests from different sources

Result: both fail — `list /APM/scripts: Fail` (bridge), `write .../ahrs-source-gps-vslam.lua: Fail` (sync).

#### Response Cross-Talk and Timeouts

`process_ftp_reply()` consumes **any** `FILE_TRANSFER_PROTOCOL` message via `recv_match`. Wrong-target messages are discarded but consume pump iterations, potentially pushing the real response past the idle detection timeout (3.7s).

#### MAVProxy's FTP Module: Not a Factor

MAVProxy's `mavproxy_ftp.py` is idle under `--non-interactive` with no FTP commands issued. It does not interfere with message forwarding.

#### `target_component=0` Is Not a Rewrite

ArduPilot responds to FTP with `target_system`/`target_component` set to the requester's source values. pixhawk-sync uses `source_component=0` (from `ConnectionConfig` defaults), so ArduPilot correctly responds with `target_component=0`.

#### Redundant Lua Deploy

Both services deploy the **exact same** Lua script:
- `pixhawk-sync` (`sync.py:143`): Explicit purpose — sync params + Lua at boot
- `vslam-bridge` (`bridge.py:207`): Opportunistic deploy before pose loop

The bridge's FTP deploy is redundant and introduces the concurrent conflict.

### Recommended Fixes

**Fix A (primary): Remove Lua deploy from vslam-bridge** — Delete `check_and_deploy_lua(conn)` from `bridge.py:207`. pixhawk-sync is the designated single FTP client. Eliminates concurrent FTP conflict entirely.

**Fix B (complementary): Add systemd ordering** — Add `After=mower-pixhawk-sync.service` to vslam-bridge unit. Ensures params and Lua are applied before bridge sends VISION_POSITION_ESTIMATE.

**Fix C (robustness): FTP retry with backoff in pixhawk-sync** — Wrap FTP ops in retry loop (2–3 attempts, 5s backoff) for transient USB/serial failures.

**Fix D (minor): Suppress cosmetic FTP warnings** — Automatically resolved if Fix A is applied.

**Key Discoveries:**
- "FTP: wrong MAVLink target 254 component 0" is **not a bug** — vslam-bridge correctly discards FTP responses meant for pixhawk-sync
- Both services attempt the same Lua deploy — redundant and creates concurrent FTP session conflict
- No systemd ordering between the two services — both race after mavproxy starts
- MAVFTP constructor sends `OP_ResetSessions` on init, killing any other client's active session
- `target_component=0` is ArduPilot's correct response addressing, not a MAVProxy rewrite
- MAVProxy's FTP module is idle and does not interfere

| File | Relevance |
|------|-----------|
| `src/mower_rover/vslam/lua_deploy.py` | `_FTPSession` wrapper and `check_and_deploy_lua()` |
| `src/mower_rover/vslam/bridge.py` | Redundant `check_and_deploy_lua(conn)` call at line 207 |
| `src/mower_rover/pixhawk/sync.py` | `sync_lua()` — the designated Lua deployer |
| `src/mower_rover/mavlink/connection.py` | `ConnectionConfig` defaults: source_system=254, source_component=0 |
| `src/mower_rover/config/vslam.py` | `BridgeConfig` defaults: source_system=1, source_component=197 |
| `src/mower_rover/config/jetson.py` | MAVProxy outputs list: [14550, 14551, 14552] |
| `src/mower_rover/pixhawk/unit.py` | Pixhawk-sync unit template; no ordering against vslam-bridge |

**External Sources:**
- [MAVLink FTP spec](https://mavlink.io/en/services/ftp.html)
- [MAVProxy FTP module source](https://raw.githubusercontent.com/ArduPilot/MAVProxy/master/MAVProxy/modules/mavproxy_ftp.py)

**Gaps:** None  
**Assumptions:** ArduPilot Rover's FTP server is single-session (consistent with PX4 per spec and pymavlink's session=0 init pattern). The race condition is reliable (both services start within ~1–2s after mavproxy).

## Phase 3: Weston & Kiosk-Renderer Cold-Boot Race

**Status:** ✅ Complete  
**Session:** 2026-05-07

**Observed symptoms (2026-05-07):**
- `mower-weston.service` exits with status=1 on first boot attempt, restarts after ~2s, succeeds on second attempt
- `mower-kiosk-renderer.service` starts concurrently, ExecStartPre waits for `/run/user/1000/wayland-0`, gets SIGTERM (status=15) when its dependency (Weston) restarts
- After Weston stabilizes, kiosk-data starts, kiosk-renderer eventually starts ~3.5 min later (at 20:31:03 vs boot at 20:27:31)
- This is a regression-free repeat of the pattern documented in research 023 and 024

### Root Cause Analysis

#### 1. Deployed vs. Codebase Unit File Discrepancy

**Codebase template** (`_WESTON_UNIT_TEMPLATE` in `unit.py`) has been fixed:
```ini
After=seatd.service systemd-modules-load.service
Requires=seatd.service
StartLimitBurst=30
```

**Repo-root `weston.service` reference file is STALE** — still has:
```ini
After=multi-user.target systemd-modules-load.service
```

This is the exact ordering cycle that research 024 identified as causing `multi-user.target` to take 3m7s. If the deployed Jetson unit still has this old config, it explains the 3.5 minute delay precisely.

#### 2. Weston First-Boot Failure: seatd Socket Race

With `--renderer=pixman`, Weston bypasses EGL entirely for rendering. The first-boot failure (exit 1, succeeds on 2s restart) is likely a **seatd socket race**:
- Weston has `After=seatd.service` + `Requires=seatd.service`
- seatd is `Type=simple` — systemd considers it "started" as soon as the process forks
- But seatd needs time to create `/run/seatd.sock` and begin accepting connections
- Weston tries to connect via libseat immediately → `ECONNREFUSED` on first attempt
- 2s restart delay gives seatd time to initialize → second attempt succeeds

#### 3. BindsTo Cascade

kiosk-renderer has `BindsTo=mower-weston.service`. When Weston exits (even briefly):
1. systemd propagates stop to kiosk-renderer
2. If kiosk-renderer's ExecStartPre is polling for `wayland-0`, it gets SIGTERM (status=15)
3. This counts against `StartLimitBurst=5` — leaving little margin for recovery

#### 4. kiosk-data Is Not a Bottleneck

kiosk-data sends `sd_notify("READY=1")` immediately after socket bind/listen (no MAVLink dependency for readiness). The `After=mower-kiosk-data.service` ordering adds minimal delay.

### ExecCondition + gpu-egl-ready Status

Research 023 proposed:
- **Phase A (immediate):** `StartLimitBurst=30`, `RestartSec=2` — **IMPLEMENTED** in codebase ✅
- **Phase B (proper):** `ExecCondition=/usr/local/bin/gpu-egl-ready` — **NOT IMPLEMENTED** ❌

The `gpu-egl-ready` binary exists in `contrib/gpu-egl-ready/` and was deployed manually, but:
1. `_WESTON_UNIT_TEMPLATE` has **no `ExecCondition` line**
2. `bringup.py` has **no step to build/deploy gpu-egl-ready**

With pixman renderer, the EGL probe still has value as a proxy for nvidia GPU subsystem readiness (GBM allocator shares initialization paths) and as a GPU warmup mechanism.

### Systemd Patterns for Readiness Gating

**`ConditionPathExists=/dev/dri/card0`:** Redundant with existing ExecStartPre polling loop.

**`After=dev-dri-card0.device`:** Requires udev `TAG+="systemd"` rule. More robust than polling but doesn't solve the seatd race.

**seatd socket readiness polling:** Directly addresses the first-boot failure:
```ini
ExecStartPre=/bin/sh -c 'for i in $(seq 1 10); do [ -S /run/seatd.sock ] && exit 0; sleep 0.5; done; echo "seatd not ready"; exit 1'
```

**`ExecCondition=` (systemd v243+):** Available on JetPack 6 (systemd 249). Non-failure skip (exit 1-254 = skip without counting against StartLimitBurst). Ideal for readiness polling.

### Recommended Fixes

**Fix 1 (CRITICAL): Deploy research 024 fix to Jetson** — Run bringup `--from-step kiosk-services` to deploy the fixed `After=seatd.service` unit. Likely eliminates the 3.5 minute delay.

**Fix 2: Add seatd socket readiness check** — ExecStartPre polling for `/run/seatd.sock` before the DRM device wait. Prevents first-boot failure.

**Fix 3: Integrate gpu-egl-ready as ExecCondition** — Add to template and build step for defense-in-depth.

**Fix 4: Increase kiosk-renderer StartLimitBurst** — Current 5 is too low given BindsTo cascade. Use 15+.

**Fix 5: Update stale `weston.service` at repo root** — Eliminate confusion risk.

**Key Discoveries:**
- Repo-root `weston.service` STILL has `After=multi-user.target` while codebase template is fixed — Jetson deployment may have old config causing 3.5 min delay
- Research 023's Phase B fix (ExecCondition + gpu-egl-ready) NOT integrated into template or bringup despite probe existing in contrib/
- First-boot failure with pixman renderer is likely seatd socket race, not the ~30s EGL GPU init from research 023
- kiosk-renderer's `BindsTo` cascade consumes `StartLimitBurst` attempts (only 5 allowed)
- LVGL kiosk-renderer exits with status 1 if `lv_wayland_window_create()` returns NULL (Wayland not ready)

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` (~line 430) | `_WESTON_UNIT_TEMPLATE` — fixed template |
| `src/mower_rover/service/unit.py` (~line 565) | `generate_kiosk_renderer_unit_file()` — BindsTo, After, ExecStartPre |
| `weston.service` (repo root) | STALE reference with After=multi-user.target |
| `contrib/gpu-egl-ready/gpu-egl-ready.c` | EGL readiness probe, not integrated |
| `src/mower_rover/cli/bringup.py` | Kiosk-services deployment function |
| `contrib/lvgl_kiosk/src/main.c` | LVGL renderer with sd_notify |
| `docs/research/023-weston-cold-boot-egl-initialization.md` | Prior EGL init research |
| `docs/research/024-kiosk-boot-ordering-failure.md` | Prior ordering cycle research |

**Gaps:**
- Cannot verify deployed Weston unit on Jetson without SSH
- Cannot confirm seatd socket path on JetPack 6 without checking deployed config

**Assumptions:** 3.5 min delay is primarily `After=multi-user.target` cycle (matches research 024 exactly). First-boot failure with pixman is seatd race, not EGL GPU init.

## Phase 4: RTAB-Map Database Bloat & Loop-Closure Degradation

**Status:** ✅ Complete  
**Session:** 2026-05-07

**Observed symptoms (2026-05-07):**
- `/var/lib/mower/rtabmap.db` is **221 GB** — this is a single RTAB-Map database file
- Node IDs have reached 293 k+ (loop closure candidates range 293526–293554 in a single log burst)
- **100% loop-closure rejection**: every candidate shows `Not enough inliers 0/10 (matches=55-76)` — the feature matches exist but geometric verification fails completely
- System load average 3.24/1.94/0.87 at 6 min uptime — VSLAM + loop-closure scanning is CPU-heavy
- The mower is stationary indoors — the camera sees a static scene, so loop closures against a 293 k-node history are futile

### Critical Bug: `memory_threshold_mb` is Dead Code

In `rtabmap_slam_node.cpp` (line 338–339), `memory_threshold_mb` is loaded from config and formatted into `mem_str`, but **never inserted into the RTAB-Map parameters map**:

```cpp
/* Memory management. */
char mem_str[32];
snprintf(mem_str, sizeof(mem_str), "%d", cfg.memory_threshold_mb);

/* Loop closure. */   // ← proceeds directly, never inserts mem_str
if (!cfg.loop_closure) {
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kRGBDEnabled(), "false"));
}
```

Missing line:
```cpp
params.insert(rtabmap::ParametersPair(
    rtabmap::Parameters::kRtabmapMemoryThr(), mem_str));
```

**Impact:** `Rtabmap/MemoryThr` defaults to `0` (infinity). Working Memory grows without bound — no nodes ever transfer to Long-Term Memory. Every node stays in RAM and accumulates in the DB.

### DB Path Mismatch in Bringup Integrity Check

In `bringup.py` (line 1376), the vslam-db-check step uses a **hardcoded wrong path**:
```python
db_path = "~/.ros/rtabmap.db"   # ← WRONG: old path
```

Actual DB path from `vslam_defaults.yaml`:
```yaml
database_path: /var/lib/mower/rtabmap.db
```

The 10 GiB size check and PRAGMA integrity check never ran against the real DB. The 221 GB DB grew completely undetected.

### Why the DB Reached 221 GB

With `MemoryThr=0`, no WM→LTM transfer occurs. 293k nodes × ~750 KB/node ≈ 220 GB (matches observed 221 GB). Despite `RGBD/LinearUpdate=0.1m` and `AngularUpdate=0.1rad` defaults that should prevent node addition when stationary, OdometryF2M drift + IMU noise (BNO086 gyro drift) occasionally exceed these thresholds, adding ~1 node/sec over weeks of indoor testing.

### Loop Closure 0-Inlier Failure: Expected for Stationary Camera

`Not enough inliers 0/10 (matches=55-76)` means:
1. **Bag-of-words visual matching works** — 55–76 visual word correspondences found
2. **Geometric verification (RANSAC) fails completely** — with near-zero translation between current pose and candidate, the fundamental/essential matrix degenerates. Any small noise in feature positions causes all points to be classified as outliers

**This is NOT a camera calibration issue** — it's expected when loop closure is attempted between frames taken from the same position.

### RTAB-Map Memory Management Parameters

| Parameter | Default | Current SLAM Node | Effect |
|-----------|---------|-------------------|--------|
| `Rtabmap/MemoryThr` | 0 (∞) | **NOT SET** (bug) | Max WM nodes before WM→LTM |
| `Rtabmap/TimeThr` | 0 (∞) | NOT SET | Max processing time before WM→LTM |
| `RGBD/LinearUpdate` | 0.1 m | NOT SET (default) | Min displacement to add node |
| `RGBD/AngularUpdate` | 0.1 rad | NOT SET (default) | Min rotation to add node |
| `RGBD/MaxLoopClosureDistance` | 0 (no limit) | NOT SET | Max distance for loop closure |
| `Mem/BinDataKept` | true | NOT SET (stores full images) | Keep binary data in DB |

### `memory_threshold_mb` Naming Mismatch

Config field is named `memory_threshold_mb` (implying megabytes) with default `6000`. But RTAB-Map's `MemoryThr` is a **node count**, not memory size. A value of 6000 means "max 6000 nodes in WM" — reasonable for outdoor mowing, but the naming is misleading.

### Localization Mode Works Correctly

When `slam_mode: localization`, the node correctly sets `Mem/IncrementalMemory=false` and `Mem/LocalizationDataSaved=false`. DB growth is exclusively a `mapping` mode problem.

### DB Rotation & Management Strategies

**Option A (Recommended for MVP): Fresh DB per mapping session** — On service start in mapping mode, rename existing DB to `rtabmap.db.{ISO8601}` before `Rtabmap::init()`. Clean state, bounded session size.

**Option B: Set MemoryThr to bound WM** — Fix the bug first, then configured 6000 value limits WM to 6000 nodes. Excess nodes transfer to LTM (remain in DB but not in RAM). Prevents CPU overload from scanning 293k nodes.

**Option C: Set TimeThr=700ms** — Adaptive: transfers WM→LTM when processing exceeds 700ms. Self-regulating.

**Option D: ExecStartPre size guard** — Script in systemd unit checks file size and rotates if over threshold.

**Recommended combination:** A + fix MemoryThr bug (B) + D. Fresh start each session, WM bounded within a session, belt-and-suspenders size check.

### Impact on VSLAM Pose Quality and Bridge Latency

- `process()` searching 293k WM nodes is O(N) in WM size — CPU-intensive even on Orin
- 30 FPS stereo + 1 Hz detection rate = 1 in 30 frames goes to `process()`, so odometry unaffected
- But the `process()` call blocks the slam loop thread, delaying pose output
- Loop closure rejection wastes CPU: feature matching (55–76 matches) + RANSAC (which fails) on every candidate

**Key Discoveries:**
- **Critical bug:** `mem_str` computed but never inserted into RTAB-Map params — `MemoryThr` defaults to 0 (infinity), disabling all WM management
- **DB path mismatch:** Bringup checks `~/.ros/rtabmap.db` but actual DB is at `/var/lib/mower/rtabmap.db` — size/corruption checks never ran
- **221 GB = ~293k nodes × ~750 KB/node** — unbounded WM in mapping mode over weeks
- **Loop closure 0-inlier failure is expected** for stationary camera — RANSAC degenerates with zero translation
- **`memory_threshold_mb` naming mismatch** — config uses MB semantics but `MemoryThr` is a node count
- **Localization mode is unaffected** — bloat is exclusively mapping mode

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | Missing MemoryThr insert (line 338-339), SlamConfig, create_slam_engine() |
| `src/mower_rover/config/data/vslam_defaults.yaml` | Default config: memory_threshold_mb=6000, database_path |
| `src/mower_rover/config/vslam.py` | VslamConfig dataclass, validation logic |
| `src/mower_rover/cli/bringup.py` | Wrong DB path in vslam-db-check (line 1376) |
| `docs/research/014-multi-zone-lawn-management.md` | Prior RTAB-Map DB strategy research |

**External Sources:**
- [RTAB-Map Parameters.h](https://github.com/introlab/rtabmap/blob/master/corelib/include/rtabmap/core/Parameters.h)
- [RTAB-Map Rtabmap.cpp](https://github.com/introlab/rtabmap/blob/master/corelib/src/Rtabmap.cpp)
- [RTAB-Map FAQ](https://github.com/introlab/rtabmap/wiki/FAQ)

**Gaps:** Could not verify actual RTAB-Map version defaults (0.21.6-rolling) vs upstream master. Per-node storage estimate (~750 KB) is approximate.  
**Assumptions:** RTAB-Map 0.21.6-rolling has same parameter defaults as upstream master. 293k nodes accumulated over weeks/months of indoor testing.

## Phase 5: Bringup Stale-Unit-File Skip Logic

**Status:** ✅ Complete  
**Session:** 2026-05-07

**Observed symptoms (2026-05-07 deploy):**
- During Plan 026 deployment, bringup step 20 (`install-mavproxy`) was skipped because `mower-mavproxy.service` was already active
- All downstream unit files (kiosk-data, kiosk-renderer, pixhawk-sync, vslam-bridge) were also stale
- Required manual SCP of corrected unit files + `systemctl daemon-reload` + restarts
- Commit 29efa0a fixed the hardcoded MAVProxy output count, but the skip-when-active logic remains

### How the Skip Logic Works

The main loop in `bringup_command()` (line ~2583):
```python
if step is None and s.check(client):
    console.print("  [green]✔ Already satisfied — skipping.[/green]")
    log.info("step_skipped", step=s.name)
    continue
```

If `check(client)` returns `True`, the **entire step** is skipped — including unit file writes, `daemon-reload`, and service restart.

### Five Affected Steps

| Step # | Name | Check Function | What It Checks | Affected? |
|--------|------|----------------|----------------|----------|
| 18 | `service` | `_service_active()` | is-active AND is-enabled for `mower-health` | **YES** |
| 20 | `install-mavproxy` | `_mavproxy_active()` | is-active AND is-enabled for `mower-mavproxy` | **YES** |
| 21 | `vslam-services` | `_vslam_services_active()` | is-active AND is-enabled for vslam + bridge | **YES** |
| 22 | `pixhawk-sync` | `_pixhawk_sync_done()` | is-enabled only (oneshot) | **YES** |
| 23 | `kiosk-services` | `_kiosk_services_active()` | is-active for weston, kiosk-data, renderer | **YES** |

All check `is-active`/`is-enabled` but **ignore unit file content**. When a new wheel is deployed (step 15 `install-cli`) with updated unit templates, the check says "already satisfied" even though the on-disk unit files are stale.

### Check Function Pattern

All affected check functions follow the same pattern:
```python
def _service_active(client: JetsonClient) -> bool:
    try:
        r_active = client.run(["systemctl", "is-active", "mower-health.service"], timeout=10)
        r_enabled = client.run(["systemctl", "is-enabled", "mower-health.service"], timeout=10)
        return r_active.ok and r_enabled.ok
    except SshError:
        return False
```

### Two Deployment Patterns

**Pattern A — Remote CLI invocation (steps 18, 21, 22):** Calls `sudo mower-jetson <subcommand> install --yes` on the Jetson. The Jetson-side CLI always writes the file + daemon-reload + enable. Already idempotent internally, but **never called** when check says "active".

**Pattern B — Inline SSH deployment (steps 20, 23):** Generates unit content in `bringup.py`, writes via `sudo bash -c 'cat > /etc/systemd/system/...'`. Also idempotent when executed, but **never reached** when check says "active".

### Evaluation: `systemctl show -p NeedDaemonReload`

Not useful for this problem. `NeedDaemonReload` only detects changes *after* a file has been modified on disk. The stale-unit issue is that the file is **never written** because the step is skipped.

### Mixed-Concern Steps

`install-mavproxy` (step 20) bundles:
- pip install of MAVProxy (~300s) — expensive, should skip if present
- Unit file deployment (~2s) — cheap, must always run

The check skips **both** operations. Need internal early-exit for the expensive part.

### Recommended Fix: Always Run + Internal Idempotency

The simplest and most robust fix:

**Step 1:** Set `check=lambda c: False` for all five service-install steps:
```python
BringupStep(
    name="install-mavproxy",
    check=lambda c: False,  # Always run — ensures unit files are current
    execute=lambda c, b: _run_install_mavproxy(c, b),
)
```

**Step 2:** Add internal early-exit for expensive sub-operations (e.g., pip install) that are already satisfied:
```python
def _run_install_mavproxy(client, bctx):
    # 1. Always deploy unit file (~2s)
    unit_content = generate_mavproxy_unit_file(...)
    # ... write + daemon-reload ...
    
    # 2. Skip pip install if already present
    result = client.run(["mavproxy.py", "--version"], timeout=15)
    if result.ok:
        bctx.console.print(f"  MAVProxy installed: {result.stdout.strip()}")
    else:
        # ... pip install (~300s) ...
```

Unit file write + daemon-reload is cheap (~2s) and fully idempotent — no reason to skip it.

### Alternative Strategies Evaluated

**`--force-units` flag:** Quick fix but operators will forget to pass it. Doesn't solve the default case.

**Content comparison in check functions:** More elegant but requires expanding `BringupStep.check` signature to receive `BringupContext` for unit file generation — a more invasive change.

**Two-pass execution (reconcile-units step):** Cleanest architecture but larger refactor. A dedicated step generates all expected unit files, compares with on-disk, writes diffs, runs daemon-reload once, restarts changed services.

**Key Discoveries:**
- Five bringup steps skip unit file deployment when services are already active/enabled
- Check functions only inspect `is-active`/`is-enabled`, never unit file content
- Unit file deployment is cheap (~2s) and idempotent — no reason to skip it
- `NeedDaemonReload` is NOT useful for pre-write staleness detection
- Steps 18/21/22 delegate to remote CLI `install` commands that are already internally idempotent — the skip happens before they run
- `install-mavproxy` bundles 300s pip install with unit file deploy — needs internal pip-present check
- Recommended fix: `check=lambda c: False` for all five steps + internal early-exit for expensive ops

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/bringup.py` | Main bringup orchestration: check functions, execute functions, step table, main loop |
| `src/mower_rover/service/unit.py` | Unit file generation templates and install functions |
| `src/mower_rover/pixhawk/unit.py` | Pixhawk-sync unit file generation and install |
| `src/mower_rover/cli/jetson.py` | Jetson CLI: `vslam install`, `pixhawk sync-install`, etc. |

**Gaps:** None  
**Assumptions:** Unit file writes over SSH are reliable. `daemon-reload` is cheap enough to run unconditionally.

## Overview

All five remaining Jetson service-stack instabilities have clear, identified root causes with actionable fixes. Three are **code bugs** (dead `MemoryThr` variable, wrong DB path, redundant Lua FTP deploy), one is a **firmware version mismatch** (`FS_GCS_TIMEOUT` doesn't exist on Rover 4.6.3), and one is a **design flaw** in the bringup tool (skip-when-active ignores unit file content). The Weston cold-boot race is a known issue with a fix already in the codebase template but possibly not deployed to the Jetson.

The most critical fix is the RTAB-Map `MemoryThr` bug (Phase 4) — a one-line C++ addition that caused a 221 GB database. The pixhawk-sync restart loop (Phase 1) is the most operationally visible since it prevents the service from ever stabilizing. The bringup stale-unit issue (Phase 5) is a systemic problem that will cause repeated deployment failures.

## Key Findings

1. **`FS_GCS_TIMEOUT` does not exist on Rover 4.6.3** — it's a 4.7+ parameter. ArduPilot silently ignores PARAM_SET for unknown params, causing a permanent restart loop in pixhawk-sync.

2. **Concurrent FTP session conflict** between vslam-bridge and pixhawk-sync — both redundantly deploy the same Lua script, racing on ArduPilot's single-session FTP server. The "wrong MAVLink target" warning is cosmetic.

3. **Weston cold-boot failure** is likely a seatd socket race (not EGL init since pixman renderer bypasses EGL). The 3.5 min delay may be a stale deployed unit still using `After=multi-user.target` (research 024 fix in codebase but possibly not deployed).

4. **221 GB RTAB-Map database** caused by dead code: `mem_str` is computed from `memory_threshold_mb` but never inserted into RTAB-Map params. `MemoryThr` defaults to 0 (infinity), disabling all WM management. Additionally, the bringup DB integrity check uses the wrong path (`~/.ros/rtabmap.db` vs `/var/lib/mower/rtabmap.db`).

5. **Bringup skip logic** checks `is-active`/`is-enabled` but ignores unit file content. Five service-install steps (18, 20, 21, 22, 23) skip unit file deployment when services are already running, leaving stale unit files after wheel updates.

## Actionable Conclusions

### Immediate (unblock service stack)
- Remove `FS_GCS_TIMEOUT` from `safety-defaults.yaml` (or replace with `FS_TIMEOUT=5`)
- Remove `check_and_deploy_lua(conn)` from `vslam/bridge.py` (redundant with pixhawk-sync)
- Delete the 221 GB `rtabmap.db` on the Jetson and restart VSLAM

### One-line fixes (C++ and Python)
- Insert `mem_str` into RTAB-Map params map in `rtabmap_slam_node.cpp` (line 339)
- Fix bringup DB check path from `~/.ros/rtabmap.db` to `/var/lib/mower/rtabmap.db`

### Resilience improvements
- `apply_params()`: Return applied+failures instead of raising on any single failure
- `sync_params()`: Skip "added" params not in `current_full` with warning; pass only drifted params
- Add `After=mower-pixhawk-sync.service` to vslam-bridge unit (eliminates FTP race even without removing bridge FTP)
- Add seatd socket readiness ExecStartPre in Weston unit; increase kiosk-renderer `StartLimitBurst` to 15+
- Integrate `gpu-egl-ready` ExecCondition into Weston unit template + bringup step

### Bringup tool fix
- Set `check=lambda c: False` for all five service-install steps
- Add internal early-exit for expensive sub-operations (pip install check in `install-mavproxy`)
- Update stale `weston.service` reference at repo root

### DB management
- Implement fresh-DB-per-mapping-session rotation (rename to `rtabmap.db.{ISO8601}` on start)
- Add ExecStartPre size guard to mower-vslam.service unit
- Consider renaming `memory_threshold_mb` config to `max_wm_nodes` (semantics mismatch)

## Open Questions

- Should `FS_TIMEOUT` be changed from 1.5s to 5s on 4.6.3 to achieve the intended GCS failsafe timing? (Note: also affects RC failsafe timing)
- Is the deployed Weston unit on the Jetson still using `After=multi-user.target`? (Requires SSH verification)
- Should `Mem/BinDataKept=false` be used to reduce DB size, or does it impact localization quality for outdoor mowing?
- Should `RGBD/MaxLoopClosureDistance` be set (e.g., 50m) to limit loop closure search radius for the 4-acre yard?

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-07 |
| Status | ✅ Complete |
| Current Phase | 1 |
| Path | /docs/research/030-remaining-jetson-instabilities.md |
