---
id: "026"
type: plan
title: "Jetson Startup Sequence & Pixhawk Reinitialization Fixes"
status: ✅ Complete
created: "2026-05-06"
updated: "2026-05-06"
completed: "2026-05-06"
owner: pch-planner
version: v3.0
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-06 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-05-06 | pch-planner | Added watchdog staleness threshold decision |
| v1.2 | 2026-05-06 | pch-planner | Added kiosk-data independence decision |
| v2.0 | 2026-05-06 | pch-planner | Holistic review completed, execution plan finalized |
| v2.1 | 2026-05-06 | pch-plan-reviewer | Review: watchdog heartbeat access uses snapshot() for thread safety |
| v2.2 | 2026-05-06 | pch-plan-reviewer | Review: add _coerce_kiosk() parsing for heartbeat_staleness_s |
| v2.3 | 2026-05-06 | pch-plan-reviewer | Review: dedicated port 14552 for pixhawk-sync to avoid vslam-bridge contention |
| v3.0 | 2026-05-06 | pch-coder | Implementation complete — all 4 phases done, 869 tests pass |

## Introduction

This plan implements the 11 concrete improvements identified in research [029-jetson-startup-pixhawk-reinit.md](/docs/research/029-jetson-startup-pixhawk-reinit.md) to make the Jetson ↔ Pixhawk systemd service stack robust across cold boot, USB disconnect/reconnect, and service crash scenarios. The root cause is MAVProxy starting before the Pixhawk USB device enumerates, crashing silently as a zombie process, and no automated recovery mechanism existing. All fixes use existing systemd primitives and require changes to only 6 source files.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|---------------|--------|-----------|
| 1 | Kiosk watchdog staleness threshold | D — Configurable via `jetson.yaml` (`kiosk.heartbeat_staleness_s`, default 60s) | Optimal threshold depends on real-world USB timing; configurable avoids premature commitment; follows existing `load_jetson_config()` pattern |
| 2 | Cold boot without Pixhawk — kiosk behavior | B — Kiosk-data runs independently of MAVProxy (`After=` only, no `Requires=`) | Kiosk already handles MAVLink absence gracefully (infinite heartbeat retry, safe defaults). Health metrics (thermal, disk, Wi-Fi) are valuable for diagnosing why the Pixhawk isn't connected. |

## Holistic Review

### Decision Interactions

1. **D1 (configurable staleness) + D2 (kiosk independent of MAVProxy):** These are complementary. Because kiosk-data runs without MAVProxy, it will always start with `last_heartbeat_epoch=0.0`. The watchdog gate must handle this initial state correctly — suppressing watchdog from the very first iteration would cause an immediate restart loop. **Resolution:** The watchdog should only suppress when `last_heartbeat_epoch > 0` AND the heartbeat is stale. When `last_heartbeat_epoch == 0.0` (never received), the watchdog should still fire — the service is healthy, it just hasn't received telemetry yet. This is distinct from "had telemetry and lost it." Thread-safe access is achieved by moving the `snapshot()` call before the watchdog check and reading `snap["mav"]["last_heartbeat_epoch"]`.

2. **R1 (MAVProxy BindsTo device) + R3 (pixhawk-sync via UDP):** R3 depends on R1. With pixhawk-sync routed through MAVProxy UDP, pixhawk-sync now has an indirect device dependency (MAVProxy → device). If MAVProxy is stopped due to USB disconnect, pixhawk-sync's `Requires=mower-mavproxy` causes it to stop too. This is correct behavior — no point syncing params if the Pixhawk is gone.

3. **R2 (drop --daemon) + R1 (BindsTo):** Together these provide a complete recovery cycle: USB disconnect → BindsTo stops MAVProxy → USB reconnect → device reappears → Restart=always + After=device → MAVProxy restarts cleanly in main thread → downstream services recover.

### Architectural Considerations

- **No circular dependencies:** The proposed dependency graph is a DAG. MAVProxy depends on device. pixhawk-sync and vslam-bridge depend on MAVProxy. kiosk-data depends on Weston (hard) and MAVProxy (ordering only). kiosk-renderer depends on Weston (hard) and kiosk-data (ordering only).
- **Watchdog semantic change:** The kiosk-data watchdog changes from "process is alive" to "process is alive AND has had telemetry recently (or never connected yet)." This is a more useful health signal but introduces a subtlety: the first heartbeat loss after a period of good telemetry triggers eventual restart, while never having had telemetry does not. Thread-safe access is achieved by moving the `snapshot()` call before the watchdog check and reading `snap["mav"]["last_heartbeat_epoch"]`.
- **MAVProxy UDP port allocation:** After R3, three consumers have dedicated MAVProxy UDP outputs: vslam-bridge (14550), kiosk-data (14551), and pixhawk-sync (14552). Each consumer has its own port — no contention. pixhawk-sync is oneshot and exits after completion, so it doesn't hold the port long-term.

### Trade-offs Accepted

- **Pixhawk-absent boot:** With R1, MAVProxy never starts if Pixhawk isn't plugged in. This is accepted — the system is not operational without the flight controller. Kiosk-data (per D2) still shows system health.
- **Configurable threshold complexity:** Adding one config key (D1) adds minor complexity but avoids field-iteration friction when tuning staleness detection.

### Risks Acknowledged

- **MAVProxy without `--daemon` behavior untested:** The assumption that MAVProxy exits cleanly on SerialException in the main thread should be verified in SITL. If it hangs instead, a `TimeoutStopSec=10` may be needed. Mitigation: test in Phase 1 before deploying.
- **MAVLink FTP over UDP:** pixhawk-sync uses MAVLink FTP for Lua script deployment. vslam-bridge already uses this same pattern successfully, so risk is low.

## Overview

### Problem Statement

The Jetson AGX Orin's 8-service systemd stack has a fundamental reliability gap centered on MAVProxy — the single hub for all Pixhawk telemetry. On every boot, MAVProxy starts ~248ms before the Pixhawk USB device enumerates, its `main_loop` thread crashes with a `SerialException`, but the process stays alive as a zombie. systemd's `Restart=always` never triggers because the PID is still running. Every downstream service (VSLAM bridge, kiosk telemetry, pixhawk param sync) is broken, and no automated recovery exists. Observed: 43+ minutes of silent degraded operation.

### Objectives

1. Eliminate the MAVProxy zombie failure mode
2. Gate MAVProxy startup on Pixhawk USB device availability
3. Eliminate serial port contention between MAVProxy and pixhawk-sync
4. Fix cascading failure propagation (missing `Requires=`/`BindsTo=` dependencies)
5. Make silent data blackouts detectable and auto-recoverable
6. Fix the vslam-bridge infinite restart loop
7. Fix minor bugs (health unit concatenation, udev autosuspend warnings)

### Source Research

[docs/research/029-jetson-startup-pixhawk-reinit.md](/docs/research/029-jetson-startup-pixhawk-reinit.md)

## Requirements

### Functional

- FR-1: MAVProxy must wait for `/dev/pixhawk` before starting
- FR-2: MAVProxy must exit (not zombie) when its serial connection fails
- FR-3: MAVProxy must stop when Pixhawk USB disconnects and restart when it reconnects
- FR-4: pixhawk-sync must connect via MAVProxy UDP, not direct serial
- FR-5: vslam-bridge must require both MAVProxy and VSLAM services
- FR-6: kiosk-data must detect total MAVLink data blackout and allow watchdog restart
- FR-7: pixhawk-sync must retry on failure instead of failing permanently
- FR-8: kiosk-data must have correct dependency ordering on MAVProxy and Weston
- FR-9: kiosk-renderer must wait for kiosk-data to start
- FR-10: vslam-bridge restart loop must eventually hit the burst limit

### Non-Functional

- NFR-1: All fixes use existing systemd primitives — no new services, wrapper scripts, or external tools
- NFR-2: Changes confined to 6 source files + 1 udev rule
- NFR-3: No breaking changes to CLI interface or bringup step sequence
- NFR-4: All changes testable in existing pytest suite (unit tests for generated unit file content)

### Out of Scope

- Full-stack recovery CLI command (`mower-jetson stack restart`) — deferred to Tier 4 (R13)
- MAVLink heartbeat monitoring in mower-health — deferred to Tier 4 (R14)
- MAVProxy replacement or custom reconnection wrapper

## Technical Design

### Architecture

No architectural changes. All fixes modify systemd unit file generation templates and one application-level watchdog gate. The service topology remains identical; only the dependency edges and restart behaviors change.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Generic unit template
    location: "src/mower_rover/service/unit.py → generate_service_unit()"
    usage: Most services use this; MAVProxy and Weston bypass it with standalone templates
  - pattern: Standalone unit template
    location: "src/mower_rover/service/unit.py → _MAVPROXY_UNIT_TEMPLATE"
    usage: MAVProxy unit — will be modified to add device dependency
  - pattern: Pixhawk-sync oneshot template
    location: "src/mower_rover/pixhawk/unit.py → generate_pixhawk_sync_unit_file()"
    usage: Inline template — will change BindsTo target and add Restart policy
  - pattern: sdnotify watchdog
    location: "src/mower_rover/kiosk/app.py → run_kiosk()"
    usage: WATCHDOG=1 sent every loop iteration — will be gated on heartbeat freshness
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Changes by File

#### 1. `src/mower_rover/service/unit.py`

**R2: Drop `--daemon` from MAVProxy ExecStart**
- In `generate_mavproxy_unit_file()` (line ~497): remove `--daemon` from the `exec_start` string
- Without `--daemon`, `main_loop()` runs in the main thread; `SerialException` → process exit → `Restart=always` triggers

**R1: Add device dependency to MAVProxy unit template**
- In `_MAVPROXY_UNIT_TEMPLATE` (line ~464): add `After=network.target dev-pixhawk.device` and `BindsTo=dev-pixhawk.device`
- Delays start until `/dev/pixhawk` exists; stops service on USB disconnect

**R4: Add `Requires=mower-vslam.service` to vslam-bridge**
- In `generate_vslam_bridge_unit_file()` (line ~401): change `requires=` from `mower-mavproxy.service` to `mower-mavproxy.service mower-vslam.service`

**R5: Add `start_limit_interval_sec` parameter to `generate_service_unit()`**
- Add optional `start_limit_interval_sec: int = 300` parameter
- Replace hard-coded `StartLimitIntervalSec=300` in both templates with `{start_limit_interval_sec}`
- Pass `start_limit_interval_sec=900` from `generate_vslam_bridge_unit_file()`

**R8: Fix kiosk-data dependencies**
- In `generate_kiosk_data_unit_file()` (line ~537): add `requires=f"{WESTON_UNIT_NAME}.service"` and change `after=` to include `{WESTON_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service`
- Do NOT add `Requires=mower-mavproxy.service` — kiosk-data must start even without Pixhawk so it can display system health metrics. `After=` ordering is sufficient; telemetry appears automatically when MAVProxy becomes available.

**R9: Add kiosk-renderer ordering on kiosk-data**
- In `generate_kiosk_renderer_unit_file()` (line ~560): change `after=` to include `{KIOSK_DATA_UNIT_NAME}.service`

**R10: Fix health unit ExecStart/Environment concatenation bug**
- *Needs investigation during implementation — the research flagged this but exact root cause in template formatting TBD*

#### 2. `src/mower_rover/pixhawk/unit.py`

**R3: Change pixhawk-sync to connect via MAVProxy UDP**
- In `generate_pixhawk_sync_unit_file()`: change `After=` from `dev-pixhawk.device` to `mower-mavproxy.service`
- Change `BindsTo=` from `dev-pixhawk.device` to `Requires=mower-mavproxy.service`
- Change ExecStart to include `--port udp:127.0.0.1:14552`

**R7: Change pixhawk-sync `Restart=no` to `Restart=on-failure`**
- In the inline unit template: add `Restart=on-failure`, `RestartSec=30`
- Change `StartLimitIntervalSec` to 300 (if not already)

#### 3. `src/mower_rover/cli/jetson.py`

**R3: Change default endpoint for pixhawk sync**
- In `pixhawk_sync_command()` (line ~1054): change default `endpoint` from `"/dev/pixhawk"` to `"udp:127.0.0.1:14552"`

#### 4. `src/mower_rover/kiosk/app.py`

**R6: Gate watchdog on heartbeat freshness**
- Add `heartbeat_staleness_s: float = 60.0` to kiosk config dataclass in `src/mower_rover/config/jetson.py`
- In `run_kiosk()` at the watchdog line (line ~293): load `cfg.kiosk.heartbeat_staleness_s`, only send `WATCHDOG=1` if `state.last_heartbeat_epoch` is non-zero AND `time.time() - state.last_heartbeat_epoch < heartbeat_staleness_s`
- If stale → watchdog suppressed → `WatchdogSec=30` fires → systemd restarts
- Operator can tune via `/etc/mower/jetson.yaml` → `kiosk.heartbeat_staleness_s`

#### 5. `scripts/90-pixhawk-usb.rules`

**R11: Add `DEVTYPE=="usb_device"` to autosuspend rule**
- Add `DEVTYPE=="usb_device"` to the second rule to prevent firing on USB interface nodes

## Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Research 029 complete | Prerequisite | ✅ Done |
| ArduPilot SITL | Test infra | For validating MAVLink connection behavior |
| Live Jetson | Verification | For end-to-end boot sequence validation |

## Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| MAVProxy without `--daemon` behaves differently than expected | Low | High | Test in SITL first; verify process exit on serial error |
| MAVLink FTP over UDP doesn't work for Lua deploy | Low | High | Already used by vslam-bridge for its Lua deploy — same pattern |
| BindsTo=dev-pixhawk.device causes MAVProxy to wait indefinitely if Pixhawk not plugged in | Low | Medium | Expected behavior — kiosk shows "Pixhawk not connected"; operator plugs in |
| Kiosk watchdog gating causes unexpected restarts during brief telemetry gaps | Medium | Low | 60s staleness threshold is generous; normal gaps are <1s |
| Existing tests break due to changed unit file content | Medium | Low | Update assertion strings in test files |

## Execution Plan

### Phase 1: MAVProxy Zombie Fix & Device Dependency (R1, R2)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 2  
**Prerequisites:** None  
**Entry Point:** `src/mower_rover/service/unit.py`  
**Verification:** N/A — first phase

These are the two highest-impact fixes. R2 (drop `--daemon`) eliminates the zombie failure mode. R1 (`BindsTo=dev-pixhawk.device`) gates startup on USB device availability and provides native USB disconnect/reconnect recovery.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | **Remove `--daemon` from MAVProxy ExecStart** — In `generate_mavproxy_unit_file()`, remove `--daemon` from the `exec_start` string. Keep `--non-interactive`. Without `--daemon`, `main_loop()` runs in the main thread; `SerialException` causes process exit; `Restart=always` triggers. | `src/mower_rover/service/unit.py` (~line 497) | Generated unit file contains `--non-interactive` but NOT `--daemon`. `exec_start` ends with `{out_args} --non-interactive`. |
| 1.2 | **Add `BindsTo=dev-pixhawk.device` and `After=dev-pixhawk.device` to MAVProxy template** — In `_MAVPROXY_UNIT_TEMPLATE` (~line 464), change `After=network.target` to `After=network.target dev-pixhawk.device` and add `BindsTo=dev-pixhawk.device` line after `After=`. | `src/mower_rover/service/unit.py` (~line 464) | Generated unit file contains `After=network.target dev-pixhawk.device` and `BindsTo=dev-pixhawk.device`. |
| 1.3 | **Update test `test_daemon_non_interactive`** — In `TestGenerateMavproxyUnit.test_daemon_non_interactive` (~line 207 in `test_kiosk_units.py`), change assertion from `assert "--daemon --non-interactive" in content` to `assert "--non-interactive" in content` and add `assert "--daemon" not in content`. | `tests/test_kiosk_units.py` (~line 207) | Test passes; asserts `--non-interactive` present and `--daemon` absent. |
| 1.4 | **Add test for device dependency** — In `TestGenerateMavproxyUnit`, add `test_binds_to_pixhawk_device` asserting `"BindsTo=dev-pixhawk.device" in content` and `test_after_includes_pixhawk_device` asserting `"After=network.target dev-pixhawk.device" in content`. | `tests/test_kiosk_units.py` | New tests pass. |
| 1.5 | **Run full test suite** — `pytest tests/` to verify no regressions. | — | All tests pass (except pre-existing skips). |

### Phase 2: Pixhawk-Sync via MAVProxy UDP (R3, R7)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 4  
**Prerequisites:** Phase 1 complete (MAVProxy has device dependency and restarts properly)  
**Entry Point:** `src/mower_rover/config/jetson.py`  
**Verification:** Phase 1 tests pass; `generate_mavproxy_unit_file()` contains `BindsTo=dev-pixhawk.device`

Eliminates serial port contention by routing pixhawk-sync through MAVProxy UDP instead of direct serial access. Uses a dedicated port (14552) to avoid contention with vslam-bridge (14550). Also adds `Restart=on-failure` so pixhawk-sync retries on failure.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | **Change pixhawk-sync unit to depend on MAVProxy instead of device** — In `generate_pixhawk_sync_unit_file()`, change `after = "network.target dev-pixhawk.device"` to `after = "network.target mower-mavproxy.service"`. Change `binds_to = "BindsTo=dev-pixhawk.device\n"` to `requires = "Requires=mower-mavproxy.service\n"` (use `Requires=` instead of `BindsTo=` — pixhawk-sync is oneshot, not long-running). | `src/mower_rover/pixhawk/unit.py` (~line 20-60) | Generated unit has `After=network.target mower-mavproxy.service`, `Requires=mower-mavproxy.service`, and does NOT contain `dev-pixhawk.device`. |
| 2.1a | **Add port 14552 to MAVProxy default outputs** — In `_default_mavproxy_outputs()`, add `"udp:127.0.0.1:14552"` as a third output. This gives pixhawk-sync a dedicated port that doesn't contend with vslam-bridge (14550) or kiosk-data (14551). | `src/mower_rover/config/jetson.py` (~line 53) | `_default_mavproxy_outputs()` returns `["udp:127.0.0.1:14550", "udp:127.0.0.1:14551", "udp:127.0.0.1:14552"]`. |
| 2.2 | **Add `--port udp:127.0.0.1:14552` to pixhawk-sync ExecStart** — In `generate_pixhawk_sync_unit_file()`, change `exec_start` from `f"{mower_jetson_path} pixhawk sync"` to `f"{mower_jetson_path} pixhawk sync --port udp:127.0.0.1:14552"`. | `src/mower_rover/pixhawk/unit.py` (~line 28) | Generated unit ExecStart contains `--port udp:127.0.0.1:14552`. |
| 2.3 | **Add `Restart=on-failure` and `RestartSec=30` to pixhawk-sync unit** — In both user-level and system-level inline templates, add `Restart=on-failure` and `RestartSec=30` after `RemainAfterExit=yes`. | `src/mower_rover/pixhawk/unit.py` (~lines 30-60) | Generated unit contains `Restart=on-failure` and `RestartSec=30`. |
| 2.4 | **Change CLI default endpoint** — In `pixhawk_sync_command()`, change the `endpoint` default from `"/dev/pixhawk"` to `"udp:127.0.0.1:14552"`. Update help text to: `"MAVLink endpoint. Default: udp:127.0.0.1:14552 (via MAVProxy)."` | `src/mower_rover/cli/jetson.py` (~line 1055) | CLI `--port` default is `udp:127.0.0.1:14552`. |
| 2.5 | **Update pixhawk-sync unit tests** — In `TestPixhawkSyncUnit.test_user_level_unit` and `test_system_level_unit`, update assertions: replace `"dev-pixhawk.device" in content` with `"mower-mavproxy.service" in content`; add `assert "Restart=on-failure" in content`; add `assert "--port udp:127.0.0.1:14552" in content`. | `tests/test_pixhawk_sync.py` (~lines 196-223) | Tests pass with new assertions. |
| 2.6 | **Update CLI help test** — In `test_cli_jetson_smoke.py`, if `test_jetson_detect_help` asserts `"/dev/pixhawk"` in stdout, update to assert `"udp:127.0.0.1:14552"` or remove the specific default assertion. | `tests/test_cli_jetson_smoke.py` (~line 29) | Test passes. |
| 2.7 | **Run full test suite** | — | All tests pass. |

### Phase 3: Service Dependency Graph Fixes (R4, R5, R8, R9)

**Status:** ✅ Complete  
**Size:** Medium  
**Files to Modify:** 1  
**Prerequisites:** Phase 2 complete  
**Entry Point:** `src/mower_rover/service/unit.py`  
**Verification:** Phase 2 tests pass

Fixes missing `Requires=` dependencies, adds `start_limit_interval_sec` parameter, and corrects kiosk ordering.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | **Add `start_limit_interval_sec` parameter to `generate_service_unit()`** — Add `start_limit_interval_sec: int = 300` parameter. Replace hard-coded `StartLimitIntervalSec=300` in both `_GENERIC_SYSTEM_TEMPLATE` and `_GENERIC_USER_TEMPLATE` with `StartLimitIntervalSec={start_limit_interval_sec}`. Pass through in the `.format()` call. | `src/mower_rover/service/unit.py` (~lines 34-135) | `generate_service_unit(start_limit_interval_sec=900)` produces `StartLimitIntervalSec=900`. Default (300) unchanged for existing callers. |
| 3.2 | **Add `Requires=mower-vslam.service` to vslam-bridge (R4)** — In `generate_vslam_bridge_unit_file()`, change `requires=` from `f"{MAVPROXY_UNIT_NAME}.service"` to `f"{MAVPROXY_UNIT_NAME}.service {VSLAM_UNIT_NAME}.service"`. | `src/mower_rover/service/unit.py` (~line 401) | Generated bridge unit contains `Requires=mower-mavproxy.service mower-vslam.service`. |
| 3.3 | **Set vslam-bridge `StartLimitIntervalSec=900` (R5)** — In `generate_vslam_bridge_unit_file()`, add `start_limit_interval_sec=900` to the `generate_service_unit()` call. | `src/mower_rover/service/unit.py` (~line 401) | Generated bridge unit contains `StartLimitIntervalSec=900`. |
| 3.4 | **Fix kiosk-data dependencies (R8)** — In `generate_kiosk_data_unit_file()`, change `after=` to `f"{WESTON_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service"` and add `requires=f"{WESTON_UNIT_NAME}.service"`. Do NOT add `Requires=mower-mavproxy` (per decision #2). | `src/mower_rover/service/unit.py` (~line 537) | Generated kiosk-data unit has `After=mower-weston.service mower-mavproxy.service` and `Requires=mower-weston.service`. No `Requires=mower-mavproxy`. |
| 3.5 | **Fix kiosk-renderer ordering (R9)** — In `generate_kiosk_renderer_unit_file()`, change `after=` to include `{KIOSK_DATA_UNIT_NAME}.service` after `{WESTON_UNIT_NAME}.service`. | `src/mower_rover/service/unit.py` (~line 560) | Generated kiosk-renderer unit has `After=mower-weston.service mower-kiosk-data.service`. |
| 3.6 | **Update vslam-bridge tests** — In `TestGenerateVslamBridgeUnitFile`: update `test_requires_mavproxy_service` to assert `"Requires=mower-mavproxy.service mower-vslam.service"`. Add `test_start_limit_interval_sec_900` asserting `"StartLimitIntervalSec=900"`. | `tests/test_service.py` (~lines 491-497) | Tests pass with updated assertions. |
| 3.7 | **Add kiosk-data unit tests** — Add `TestGenerateKioskDataUnitFile` class with tests for: `After=` includes both Weston and MAVProxy, `Requires=` includes Weston only, no `Requires=mower-mavproxy`. | `tests/test_service.py` or `tests/test_kiosk_units.py` | New tests pass. |
| 3.8 | **Add kiosk-renderer ordering test** — Add test asserting `After=` includes `mower-kiosk-data.service`. | `tests/test_service.py` or `tests/test_kiosk_units.py` | New test passes. |
| 3.9 | **Update `test_contains_start_limit`** — In `TestGenerateUnitFile.test_contains_start_limit`, verify assertion still passes (default 300 unchanged). | `tests/test_service.py` (~line 64) | Existing test passes unchanged. |
| 3.10 | **Run full test suite** | — | All tests pass. |

### Phase 4: Kiosk Watchdog Gating & Minor Fixes (R6, R10, R11)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 3  
**Prerequisites:** Phase 3 complete  
**Entry Point:** `src/mower_rover/config/jetson.py`  
**Verification:** Phase 3 tests pass

Gates kiosk-data watchdog on heartbeat freshness, fixes health unit formatting bug, and fixes udev autosuspend rule.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | **Add `heartbeat_staleness_s` to `KioskConfig`** — In `KioskConfig` dataclass, add `heartbeat_staleness_s: float = 60.0`. | `src/mower_rover/config/jetson.py` (~line 67) | `KioskConfig()` has `.heartbeat_staleness_s == 60.0`. Configurable via `jetson.yaml` → `kiosk.heartbeat_staleness_s`. |
| 4.1a | **Add `heartbeat_staleness_s` parsing to `_coerce_kiosk()`** — In `_coerce_kiosk()`, add a block (following the `refresh_hz` pattern) that reads `heartbeat_staleness_s` from the raw dict, validates it is a positive `int` or `float`, and passes it to `KioskConfig(**kwargs)`. Raise `JetsonConfigError` if the value is not numeric or is ≤ 0. | `src/mower_rover/config/jetson.py` (~line 130) | `load_jetson_config()` with `kiosk.heartbeat_staleness_s: 30` in YAML produces `cfg.kiosk.heartbeat_staleness_s == 30.0`. Invalid values raise `JetsonConfigError`. |
| 4.2 | **Gate watchdog on heartbeat freshness (R6)** — In `run_kiosk()`, move the `snap = state.snapshot()` call **before** the watchdog line (~line 289). Load the staleness threshold from config (cached once before the loop). Use `snap["mav"]["last_heartbeat_epoch"]` for thread-safe access. Only send `WATCHDOG=1` if `last_hb > 0` AND `time.time() - last_hb < staleness_threshold`. When `last_hb == 0.0` (never connected), always send `WATCHDOG=1` — the service is healthy, just waiting. Log a warning when watchdog is suppressed due to staleness (once per transition, not every iteration). | `src/mower_rover/kiosk/app.py` (~line 289) | Watchdog suppressed only when heartbeat was previously received AND is now stale beyond threshold. Always fires when never connected (`last_heartbeat_epoch == 0.0`). systemd restarts service after `WatchdogSec=30` of suppression. |
| 4.3 | **Investigate and fix health unit ExecStart/Environment bug (R10)** — In `generate_unit_file()` or `generate_service_unit()`, inspect the template formatting that produces the concatenated `--health-interval 60Environment=` line on the live Jetson. Fix the missing newline. | `src/mower_rover/service/unit.py` | Generated health unit has `ExecStart=` and `Environment=` on separate lines. |
| 4.4 | **Fix udev autosuspend rule (R11)** — In `scripts/90-pixhawk-usb.rules`, add `DEVTYPE=="usb_device",` to the second rule (autosuspend line) between `SUBSYSTEM=="usb",` and `ATTRS{idVendor}==`. | `scripts/90-pixhawk-usb.rules` | Autosuspend rule only fires on USB device nodes, not interface nodes. No "Failed to write ATTR" errors. |
| 4.5 | **Add watchdog gating tests** — (a) Test that `WATCHDOG=1` IS sent when `last_heartbeat_epoch == 0.0` (never connected — service is healthy, just waiting). (b) Test that `WATCHDOG=1` IS sent when heartbeat is fresh (within staleness threshold). (c) Test that `WATCHDOG=1` is NOT sent when heartbeat was previously received but is now stale beyond threshold. | `tests/test_kiosk_services.py` or `tests/test_service.py` | All three test cases pass. |
| 4.6 | **Add config tests** — (a) Test that `KioskConfig` defaults include `heartbeat_staleness_s=60.0`. (b) Test that `_coerce_kiosk({"heartbeat_staleness_s": 30})` produces `KioskConfig(heartbeat_staleness_s=30.0)`. (c) Test that `_coerce_kiosk({"heartbeat_staleness_s": -5})` raises `JetsonConfigError`. (d) Test that `_coerce_kiosk({"heartbeat_staleness_s": "bad"})` raises `JetsonConfigError`. | `tests/test_config.py` | All four test cases pass. |
| 4.7 | **Run full test suite** | — | All tests pass. |

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 4  
**Last Updated:** 2026-05-06

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | Watchdog heartbeat access thread safety | correctness | Option B: Use `snapshot()` before watchdog check | Step 4.2 updated |
| 2 | Missing `_coerce_kiosk` update for new config field | completeness | Option A: Add explicit validation in `_coerce_kiosk()` | Steps 4.1a, 4.6 updated |
| 3 | Watchdog semantic: never-connected vs lost-connection | correctness | Resolved by step 4.2 update (fires when `last_hb==0`, suppresses only when stale) | Steps 4.2, 4.5 updated |
| 4 | UDP port 14550 contention: pixhawk-sync vs vslam-bridge | correctness | Option A: Dedicated port 14552 for pixhawk-sync | Steps 2.1a, 2.2, 2.4, 2.5 updated |

## Standards

No organizational standards applicable to this plan.

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 6 source files + 1 udev rule across 4 packages |
| New patterns introduced | 1 | No new patterns — extends existing unit templates and config |
| External dependencies | 1 | No new dependencies |
| Migration complexity | 1 | No data migration; services regenerated on next bringup |
| Test coverage required | 2 | Unit tests for generated unit content + watchdog gating |
| **Overall Complexity** | **7/25** | **Low** (≤10) |

## Review Summary

**Review Date:** 2026-05-06  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.3  

### Review Metrics
- Issues Found: 4 (Critical: 0, Major: 3, Minor: 1)
- Clarifying Questions Asked: 3
- Sections Updated: Phase 2, Phase 4, Holistic Review, Introduction, NFR-2, Technical Design

### Key Improvements Made
1. **Thread safety for watchdog gate (Major):** Step 4.2 now uses `snapshot()` for lock-protected heartbeat access instead of racy direct attribute access
2. **Config parsing completeness (Major):** Added step 4.1a to update `_coerce_kiosk()` for `heartbeat_staleness_s`, preventing silent config ignoring
3. **Port contention elimination (Major):** Allocated dedicated port 14552 for pixhawk-sync, added step 2.1a for `_default_mavproxy_outputs()` update, preventing address-in-use failures on `Restart=on-failure` retries
4. **Watchdog test coverage (Minor):** Expanded step 4.5 to three test cases covering never-connected, fresh, and stale heartbeat states

### Remaining Considerations
- R10 (health unit ExecStart/Environment concatenation bug) is marked "investigate during implementation" — the root cause isn't reproducible from template inspection alone. The implementer should check the live Jetson's current unit file to confirm the symptom before fixing.
- MAVProxy `--daemon` removal should be verified in SITL early in Phase 1 — if MAVProxy hangs instead of exiting on SerialException, add `TimeoutStopSec=10` to the unit.

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-06 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-06 |
| Status | ✅ Complete |
| Implemented By | pch-coder |
| Plan Location | /docs/plans/026-jetson-startup-pixhawk-reinit.md |

## Implementation Notes

### Phase 1 — MAVProxy Zombie Fix & Device Dependency
**Completed:** 2026-05-06

**Files Modified:** `src/mower_rover/service/unit.py`, `tests/test_kiosk_units.py`

**Changes:** Removed `--daemon` from MAVProxy ExecStart. Added `BindsTo=dev-pixhawk.device` and `After=network.target dev-pixhawk.device` to MAVProxy template. Updated and added unit tests.

### Phase 2 — Pixhawk-Sync via MAVProxy UDP
**Completed:** 2026-05-06

**Files Modified:** `src/mower_rover/pixhawk/unit.py`, `src/mower_rover/config/jetson.py`, `src/mower_rover/cli/jetson.py`, `tests/test_pixhawk_sync.py`

**Changes:** Changed pixhawk-sync to depend on `mower-mavproxy.service` (Requires+After) instead of `dev-pixhawk.device`. Added dedicated port `udp:127.0.0.1:14552` for pixhawk-sync. Added `Restart=on-failure` + `RestartSec=30`. Updated CLI default endpoint.

### Phase 3 — Service Dependency Graph Fixes
**Completed:** 2026-05-06

**Files Modified:** `src/mower_rover/service/unit.py`, `tests/test_service.py`, `tests/test_kiosk_units.py`

**Changes:** Added `start_limit_interval_sec` parameter to `generate_service_unit()`. Added `Requires=mower-vslam.service` to vslam-bridge. Set vslam-bridge `StartLimitIntervalSec=900`. Fixed kiosk-data dependencies (Weston required, MAVProxy ordering only). Fixed kiosk-renderer ordering on kiosk-data.

### Phase 4 — Kiosk Watchdog Gating & Minor Fixes
**Completed:** 2026-05-06

**Files Modified:** `src/mower_rover/config/jetson.py`, `src/mower_rover/kiosk/app.py`, `src/mower_rover/service/unit.py`, `scripts/90-pixhawk-usb.rules`, `tests/test_kiosk_services.py`, `tests/test_config.py`

**Changes:** Added `heartbeat_staleness_s` config field with `_coerce_kiosk()` validation. Gated watchdog on heartbeat freshness via `_should_notify_watchdog()` helper. Added defensive newline guard for ExecStart/Environment (R10 — no active bug found, preventive fix). Added `DEVTYPE=="usb_device"` to udev autosuspend rule.

**Deviations:**
- R10: No active concatenation bug found in templates — added defensive guard only
- Extracted `_should_notify_watchdog()` helper for testability

### Plan Completion
**All phases completed:** 2026-05-06
**Total tasks completed:** 30
**Total files modified/created:** 11
**Test results:** 869 passed, 27 skipped (up from 857 — 12 new tests added)
**Code review:** 1 minor finding (pre-existing redundant `import re`) — no action required
