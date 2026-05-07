---
id: "027"
type: plan
title: "Remaining Jetson Service-Stack Instabilities — Fixes"
status: ✅ Complete
created: "2026-05-06"
updated: "2026-05-06"
completed: "2026-05-06"
owner: pch-planner
version: v2.8
research: "docs/research/030-remaining-jetson-instabilities.md"
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-06 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-05-06 | pch-planner | Decision 1: apply_params() returns ApplyResult dataclass |
| v1.2 | 2026-05-06 | pch-planner | Decision 2: Remove FS_GCS_TIMEOUT, add commented-out FS_TIMEOUT suggestion |
| v1.3 | 2026-05-06 | pch-planner | Decision 3: Add seatd socket polling ExecStartPre to Weston unit |
| v1.4 | 2026-05-06 | pch-planner | Decision 4: Always-run for five service-install bringup steps |
| v2.0 | 2026-05-06 | pch-planner | Holistic review completed; execution plan finalized (5 phases, 22 tasks) |
| v2.1 | 2026-05-06 | pch-planner | Decision 5: Add minimal `_test` zone to Phase 4 for DB isolation |
| v2.2 | 2026-05-06 | pch-plan-reviewer | Review Q1: Add Step 1.6 for cli/params.py caller; correct test file refs in Step 1.5 |
| v2.3 | 2026-05-06 | pch-plan-reviewer | Review Q2: Parameterize StartLimitBurst in generate_service_unit(); update Step 3.2 |
| v2.4 | 2026-05-06 | pch-plan-reviewer | Review Q3: Define PIXHAWK_SYNC_UNIT_NAME in service/unit.py; update Step 2.2 |
| v2.5 | 2026-05-06 | pch-plan-reviewer | Review Q4: Fix ParamSet.from_dict() → from_mapping() in Architecture #8 |
| v2.6 | 2026-05-06 | pch-plan-reviewer | Review Q5: Remove Step 2.3 (no tests mock bridge Lua deploy) |
| v2.7 | 2026-05-06 | pch-plan-reviewer | Review Q6: Expand Step 1.4 to cascade FS_GCS_TIMEOUT removal to test_params.py + baseline |
| v2.8 | 2026-05-06 | pch-plan-reviewer | Review Q7-Q8: Fix Step 3.4 test file refs; rewrite Step 4.4 as new zone-aware DB tests |
| v3.0 | 2026-05-06 | pch-coder | Implementation complete — all 5 phases, 22 tasks |

## Introduction

This plan addresses the five remaining Jetson service-stack instabilities identified in research 030. After Plan 026 (Jetson Startup Sequence & Pixhawk Reinitialization Fixes) deployment, seven of eight services run stably. This plan covers: (1) pixhawk-sync restart loop from `FS_GCS_TIMEOUT` on Rover 4.6.3, (2) concurrent MAVLink FTP session conflict between vslam-bridge and pixhawk-sync, (3) Weston cold-boot seatd socket race, (4) 221 GB RTAB-Map database from dead `MemoryThr` code, and (5) bringup stale-unit-file skip logic.

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 8  
**Last Updated:** 2026-05-06

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | Missing cli/params.py caller update for ApplyResult | correctness | Option A: Add Step 1.6 for cli/params.py + correct test refs | Phase 1: Step 1.5 test refs corrected, Step 1.6 added |
| 2 | StartLimitBurst not parameterized in generic templates | correctness | Option A: Add `start_limit_burst` param to `generate_service_unit()` | Step 3.2 updated with implementation details |
| 3 | PIXHAWK_SYNC_UNIT_NAME constant location for bridge ordering | specificity | Option B: Define constant in `service/unit.py` alongside others | Step 2.2 updated with constant location |
| 4 | Architecture #8 uses non-existent `ParamSet.from_dict()` | specificity | Option A: Correct to `from_mapping()` | Architecture #8 code snippet updated |
| 5 | Step 2.3 references wrong test files; no tests mock bridge Lua deploy | specificity | Option A: Remove Step 2.3 entirely | Step 2.3 removed from Phase 2 |
| 6 | FS_GCS_TIMEOUT removal cascades to test_params.py + baseline YAML | correctness | Option A: Expand Step 1.4 to include all cascades | Step 1.4 expanded with 3 additional files |
| 7 | Step 3.4 references wrong test files (test_kiosk_services.py, test_kiosk_renderer.py) | specificity | Option A: Correct to test_kiosk_units.py + test_service.py | Step 3.4 files + Phase 3 verification corrected |
| 8 | Step 4.4 references non-existent DB tests to "update" | specificity | Option A: Rewrite as new zone-aware DB path tests | Step 4.4 rewritten; Phase 4 verification updated |

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | `apply_params()` error handling strategy | A — Return a result dataclass with `applied` and `failures` lists | Explicit contract; callers decide severity; small caller count makes migration low-cost; safer for safety-critical system |
| 2 | `FS_GCS_TIMEOUT` removal strategy | C — Remove and add commented-out `FS_TIMEOUT: 5` suggestion | Unblocks pixhawk-sync immediately; documents 4.6.3 workaround; defers safety-relevant shared-timeout change to field validation |
| 3 | Weston seatd readiness check mechanism | A — Add seatd socket polling `ExecStartPre` | Directly addresses root cause; <1s typical delay; prevents unnecessary BindsTo cascade; documents seatd dependency |
| 4 | Bringup service-install skip logic | A — `check=lambda c: False` for all five steps + internal pip-present early-exit | Unit file deploy is ~2s and idempotent; no benefit to skipping; only MAVProxy pip install needs internal short-circuit |
| 5 | Testing/NOP zone scope | C — Minimal `_test` zone in bringup flow (plan 027) | Just DB isolation; bringup activates `_test` zone by default if no zone configured; full NOP zone design deferred |

## Holistic Review

### Decision Interactions

1. **Decisions 1 + 2 (ApplyResult + FS_GCS_TIMEOUT removal):** These are complementary — removing `FS_GCS_TIMEOUT` is the immediate unblock, while `ApplyResult` dataclass prevents future restart loops from any unknown param. Decision 1 alone would still require Decision 2 because the "added" param skip logic (Decision 1's `sync_params` change) depends on `diff.added` detection which correctly identifies `FS_GCS_TIMEOUT` as "added" — but `apply_params()` would still try to apply it and fail. Both fixes together create defense-in-depth.

2. **Bridge FTP removal + pixhawk-sync ordering (Architecture #4):** Removing `check_and_deploy_lua()` from the bridge eliminates the FTP race. Adding `After=mower-pixhawk-sync.service` to the bridge unit ensures Lua is deployed before pose streaming begins. These are independently sufficient but together provide belt-and-suspenders: even if the FTP removal is accidentally reverted, the ordering prevents the race.

3. **Bringup always-run (Decision 4) + all unit template changes (Decisions 3, Architecture #4):** The always-run fix ensures that unit template changes (seatd poll, bridge ordering, kiosk-renderer StartLimitBurst) are actually deployed on the next bringup run. Without Decision 4, these template fixes would be silently skipped if services were already active. This is the exact problem that caused research 030's Phase 5 finding.

4. **RTAB-Map MemoryThr fix (Architecture #5) + DB path fix (Architecture #6):** The MemoryThr fix prevents future DB bloat; the DB path fix ensures the bringup integrity check actually monitors the correct file. The `zone activate` command (`cli/jetson.py` line ~910) sets `database_path` to `/var/lib/mower/zones/{zone_id}/rtabmap.db`, so the bringup check must be zone-aware — reading the active path from the deployed config and also scanning per-zone DBs. The existing 221 GB DB must be manually deleted on the Jetson before the SLAM node restarts — this is an operational step, not a code change.

### Architectural Considerations

- **`ApplyResult` return type is a breaking change** to `apply_params()` — all callers and tests that catch `RuntimeError` must be updated. The caller count is small (sync_params + tests), so risk is low.
- **Removing bridge FTP removes the bridge's self-healing capability** — if pixhawk-sync fails and Lua is not deployed, the bridge will not attempt deployment. Mitigated by the `After=` ordering (bridge won't start until pixhawk-sync completes) and by pixhawk-sync's `Restart=on-failure` (it will retry).
- **C++ SLAM node change requires rebuilding on the Jetson** — this is deployed via the `build-slam-node` bringup step, not the Python wheel. The bringup sequence must include `--from-step build-slam-node` to pick up this fix.

### Trade-offs Accepted

- Bringup runs ~10s slower when all services are already current (5 steps × ~2s each) — acceptable for deployment reliability.
- `FS_TIMEOUT` remains at 1.5s (more aggressive than intended 5s) until field validation — accepted per copilot-instructions guidance on open questions.
- `memory_threshold_mb` naming mismatch (MB vs node count) is deferred — config value 6000 is reasonable as a node count for outdoor mowing.

### Risks Acknowledged

- The 221 GB RTAB-Map DB must be manually deleted before restarting VSLAM. If forgotten, the SLAM node will re-open the bloated DB and performance will remain degraded until `MemoryThr` transfers excess nodes to LTM (which could take hours at 293k nodes).
- Stale deployed Weston unit on Jetson (with `After=multi-user.target`) must be overwritten by running bringup `--from-step kiosk-services`. The always-run fix (Decision 4) ensures this happens.

## Overview

### Feature Summary

Fix five interrelated instabilities in the Jetson service stack that prevent stable autonomous operation:

1. **Pixhawk-sync restart loop** — `FS_GCS_TIMEOUT` does not exist on Rover 4.6.3; `apply_params()` is all-or-nothing
2. **MAVLink FTP race** — vslam-bridge and pixhawk-sync both deploy the same Lua script, racing on ArduPilot's single-session FTP server
3. **Weston cold-boot race** — seatd socket not ready on first boot; kiosk-renderer `StartLimitBurst` too low for `BindsTo` cascade
4. **RTAB-Map DB bloat** — `MemoryThr` param never inserted in C++ SLAM node; bringup DB check uses wrong path
5. **Bringup stale units** — skip-when-active ignores unit file content; five service-install steps skip unit deployment when services are already running

### Objectives

- Unblock pixhawk-sync from permanent restart loop
- Eliminate concurrent FTP failures between vslam-bridge and pixhawk-sync
- Reduce Weston cold-boot failures and kiosk-renderer cascade restarts
- Fix RTAB-Map memory management and DB integrity checking
- Ensure bringup always deploys current unit files regardless of service state

## Requirements

### Functional

- FR-1: `safety-defaults.yaml` must not contain params absent from Rover 4.6.3
- FR-2: `apply_params()` must report per-param success/failure without aborting on first failure
- FR-3: `sync_params()` must skip params not present on firmware with a warning
- FR-4: `sync_params()` must pass only drifted params to `apply_params()`, not the full desired set
- FR-5: vslam-bridge must not attempt Lua FTP deploy (pixhawk-sync is the designated deployer)
- FR-6: vslam-bridge unit must order after pixhawk-sync
- FR-7: Weston unit must wait for seatd socket readiness before starting
- FR-8: kiosk-renderer `StartLimitBurst` must tolerate `BindsTo` cascade restarts
- FR-9: RTAB-Map SLAM node must insert `MemoryThr` param into the params map
- FR-10: Bringup DB check must use the correct DB path from vslam config
- FR-11: Bringup service-install steps must always deploy unit files, regardless of service state
- FR-12: `install-mavproxy` must skip pip install if MAVProxy already present but always deploy unit

### Non-Functional

- NFR-1: All Python changes must pass existing `pytest` suite (837+ tests)
- NFR-2: C++ SLAM node change must compile on aarch64 with existing CMake toolchain
- NFR-3: No new external dependencies
- NFR-4: All changes must be deployable via `mower jetson bringup --from-step <step>`

### Out of Scope

- RTAB-Map DB rotation (fresh-DB-per-session) — future plan
- Renaming `memory_threshold_mb` config field to `max_wm_nodes` — future plan
- `gpu-egl-ready` ExecCondition integration — separate follow-up
- `FS_TIMEOUT` value change (1.5s → 5s) — requires field validation
- `Mem/BinDataKept`, `RGBD/MaxLoopClosureDistance` tuning — requires field validation

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Param apply/verify
    location: "src/mower_rover/params/mav.py"
    usage: Modify apply_params() to return results instead of raising
  - pattern: Param diff
    location: "src/mower_rover/params/diff.py"
    usage: Reference for how "added" params are detected
  - pattern: Param sync orchestration
    location: "src/mower_rover/pixhawk/sync.py"
    usage: Modify sync_params() to filter drifted-only and skip missing params
  - pattern: Lua FTP deploy
    location: "src/mower_rover/vslam/lua_deploy.py"
    usage: Remove call from bridge.py; keep in sync.py
  - pattern: Systemd unit generation
    location: "src/mower_rover/service/unit.py"
    usage: Modify Weston template and kiosk-renderer generation
  - pattern: Bringup step orchestration
    location: "src/mower_rover/cli/bringup.py"
    usage: Modify check functions and install-mavproxy logic
  - pattern: RTAB-Map SLAM node
    location: "contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp"
    usage: Insert MemoryThr param into params map
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Architecture Changes

#### 1. `apply_params()` → Returns `ApplyResult` Dataclass

**File:** `src/mower_rover/params/mav.py`

**Current:** Raises `RuntimeError` listing all failures — any single param failure aborts the entire operation.

**New:** Returns an `ApplyResult` dataclass:

```python
@dataclass
class ApplyResult:
    """Result of applying a set of params to the autopilot."""
    applied: dict[str, float]       # name → verified value
    failures: list[tuple[str, float, str]]  # (name, requested_value, error_reason)

    @property
    def ok(self) -> bool:
        return len(self.failures) == 0

    @property
    def partial(self) -> bool:
        return len(self.applied) > 0 and len(self.failures) > 0
```

**Caller changes:**
- `sync_params()` in `sync.py`: Check `result.ok` / `result.partial`; log failures as warnings for "added" params, errors for "changed" params
- Tests in `test_params.py` / `test_params_sitl.py`: Update assertions from `pytest.raises(RuntimeError)` to checking `result.failures`

#### 2. `safety-defaults.yaml` — Remove `FS_GCS_TIMEOUT`, Add Commented Suggestion

**File:** `src/mower_rover/params/data/safety-defaults.yaml`

**Current:**
```yaml
FS_GCS_ENABLE: 1
FS_GCS_TIMEOUT: 5             # seconds without heartbeat before action
```

**New:**
```yaml
FS_GCS_ENABLE: 1              # Hold if MAVLink heartbeat lost (decision Q3)
# FS_TIMEOUT: 5               # On Rover 4.6.3, GCS timeout is FS_TIMEOUT (shared with RC).
#                              # Default 1.5s. Set to 5 after field validation — changing
#                              # this also affects RC failsafe timing.
#                              # Rover 4.7+ has dedicated FS_GCS_TIMEOUT instead.
```

**Rationale:** `FS_GCS_TIMEOUT` is a Rover 4.7+ param (g2 index 56). On 4.6.3, ArduPilot silently ignores PARAM_SET for unknown names, causing `_await_param_echo()` to time out → permanent restart loop. The commented suggestion preserves intent and documents the 4.6.3 workaround path.

#### 3. Weston Unit Template — seatd Socket Polling + kiosk-renderer StartLimitBurst

**File:** `src/mower_rover/service/unit.py` (`_WESTON_UNIT_TEMPLATE`)

**Current ExecStartPre sequence:**
```ini
ExecStartPre=/bin/mkdir -p /var/log/mower-jetson
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /dev/dri/card0 ] && exit 0; sleep 1; done; echo "DRM device not found"; exit 1'
```

**New ExecStartPre sequence** (insert seatd poll before DRM poll):
```ini
ExecStartPre=/bin/mkdir -p /var/log/mower-jetson
ExecStartPre=/bin/sh -c 'for i in $(seq 1 10); do [ -S /run/seatd.sock ] && exit 0; sleep 0.5; done; echo "seatd not ready"; exit 1'
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /dev/dri/card0 ] && exit 0; sleep 1; done; echo "DRM device not found"; exit 1'
```

**kiosk-renderer `StartLimitBurst`:** Increase from default (5) to 15 in `generate_kiosk_renderer_unit_file()` to tolerate `BindsTo` cascade restarts when Weston fails and recovers on first boot.

**Stale repo-root `weston.service`:** Update to match the codebase template (add `After=seatd.service`, `Requires=seatd.service`, seatd poll ExecStartPre) to eliminate confusion.

#### 4. Remove Lua Deploy from vslam-bridge + Add Ordering

**File:** `src/mower_rover/vslam/bridge.py` (line ~207)

**Current:**
```python
with open_link(conn_cfg, shutdown_event=shutdown) as conn:
    check_and_deploy_lua(conn)
    _notifier.notify("READY=1")
```

**New:** Remove the `check_and_deploy_lua(conn)` call entirely. pixhawk-sync is the designated single FTP client for Lua deploy.

**File:** `src/mower_rover/service/unit.py` or `src/mower_rover/vslam/bridge.py` unit generation

Add `After=mower-pixhawk-sync.service` to the vslam-bridge unit template. This ensures params and Lua are applied before bridge sends `VISION_POSITION_ESTIMATE`, and eliminates FTP race even if bridge FTP code is not removed.

#### 5. RTAB-Map `MemoryThr` One-Line Fix

**File:** `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` (line ~339)

**Current:**
```cpp
/* Memory management. */
char mem_str[32];
snprintf(mem_str, sizeof(mem_str), "%d", cfg.memory_threshold_mb);

/* Loop closure. */
```

**New:** Insert the missing `params.insert()` call:
```cpp
/* Memory management. */
char mem_str[32];
snprintf(mem_str, sizeof(mem_str), "%d", cfg.memory_threshold_mb);
params.insert(rtabmap::ParametersPair(
    rtabmap::Parameters::kRtabmapMemoryThr(), mem_str));

/* Loop closure. */
```

#### 6. Bringup DB Path Fix — Zone-Aware

**File:** `src/mower_rover/cli/bringup.py` (line ~1376)

**Current:**
```python
db_path = "~/.ros/rtabmap.db"
```

**Problem:** The DB path is not a single hardcoded location. The `zone activate` command (in `cli/jetson.py`, line ~910) sets `database_path` to `/var/lib/mower/zones/{zone_id}/rtabmap.db`. The default path (no zone active) is `/var/lib/mower/rtabmap.db` per `vslam_defaults.yaml`.

**New:** Read the currently-configured DB path from `/etc/mower/vslam.yaml` on the Jetson via SSH, falling back to the default if the config file doesn't exist:
```python
# Read active DB path from deployed vslam config
try:
    result = client.run(
        ["python3", "-c",
         "import yaml; c=yaml.safe_load(open('/etc/mower/vslam.yaml'));"
         "print(c.get('vslam',{}).get('database_path','/var/lib/mower/rtabmap.db'))"],
        timeout=15,
    )
    db_path = result.stdout.strip() if result.ok else "/var/lib/mower/rtabmap.db"
except SshError:
    db_path = "/var/lib/mower/rtabmap.db"
```

Additionally, scan `/var/lib/mower/zones/*/rtabmap.db` for any per-zone DBs that also exceed the size threshold:
```python
# Also check per-zone DBs
try:
    result = client.run(
        ["find", "/var/lib/mower/zones", "-name", "rtabmap.db", "-type", "f"],
        timeout=15,
    )
    if result.ok:
        for zone_db in result.stdout.strip().splitlines():
            # ... same size/integrity check as primary DB ...
except SshError:
    pass  # Zones may not exist yet
```

This ensures the bringup integrity check covers both the active DB and any per-zone DBs.

#### 6a. Default `_test` Zone in Bringup

**File:** `src/mower_rover/cli/bringup.py` (in the `vslam-config` step execution function)

**Current:** The `vslam-config` step deploys `/etc/mower/vslam.yaml` with the default `database_path: /var/lib/mower/rtabmap.db` — a single shared DB that grows unbounded during bench testing.

**New:** After deploying the config, check if the `database_path` is still the bare default. If so, activate a `_test` zone:
```python
# If no zone is configured, default to _test zone for DB isolation
if vslam_db_path == "/var/lib/mower/rtabmap.db":
    test_zone_dir = "/var/lib/mower/zones/_test"
    client.run(["mkdir", "-p", test_zone_dir], timeout=10)
    # Update deployed config to use _test zone DB
    client.run([
        "sed", "-i",
        "s|database_path: /var/lib/mower/rtabmap.db|"
        "database_path: /var/lib/mower/zones/_test/rtabmap.db|",
        "/etc/mower/vslam.yaml",
    ], timeout=10)
    bctx.console.print("  Activated default '_test' zone for DB isolation.")
```

This prevents the bare-default DB from accumulating data during bench testing. Operators activate real zones via `mower-jetson zone activate <name>`, which overrides the `_test` default.

#### 7. Bringup Always-Run for Service-Install Steps

**File:** `src/mower_rover/cli/bringup.py`

**Five steps to change:**

| Step Name | Current Check | New Check |
|-----------|--------------|-----------|
| `service` | `_service_active()` | `lambda c: False` |
| `install-mavproxy` | `_mavproxy_active()` | `lambda c: False` |
| `vslam-services` | `_vslam_services_active()` | `lambda c: False` |
| `pixhawk-sync` | `_pixhawk_sync_done()` | `lambda c: False` |
| `kiosk-services` | `_kiosk_services_active()` | `lambda c: False` |

**`install-mavproxy` internal pip-present check:** Add early-exit inside `_run_install_mavproxy()`:
```python
# Check if MAVProxy is already installed — skip 300s pip install
result = client.run(["mavproxy.py", "--version"], timeout=15)
if result.ok:
    bctx.console.print(f"  MAVProxy already installed: {result.stdout.strip()}")
else:
    # ... existing pip install logic ...
```
Unit file deployment always runs regardless of pip check result.

#### 8. `sync_params()` — Pass Only Drifted Params + Skip Missing

**File:** `src/mower_rover/pixhawk/sync.py`

**Current (line ~122):**
```python
apply_params(conn, desired)  # all 7 params
```

**New:**
```python
# Build set of params that actually need changing
to_apply = ParamSet.from_mapping({
    c.name: c.new for c in diff.changed
})

# Warn about params in desired but not on firmware
for c in diff.added:
    log.warning("sync_param_not_on_firmware", name=c.name, value=c.new,
                hint="param may require firmware upgrade")

if to_apply:
    result = apply_params(conn, to_apply)
    # Handle result.failures as errors (these are known-to-exist params that failed)
```

This passes only changed params (not added/removed), and warns about params that don't exist on the firmware.

## Dependencies

- Research 030 (✅ Complete) — root cause analysis for all five instabilities
- Plan 026 (✅ Deployed) — prior startup sequence fixes
- ArduPilot Rover 4.6.3 — firmware version constraint (no `FS_GCS_TIMEOUT`)
- pymavlink MAVFTP — FTP session semantics

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `apply_params()` return-type change breaks callers | Medium | Medium | Search all callers; update signatures |
| Removing bridge Lua deploy breaks AHRS source switching if pixhawk-sync fails | Low | High | Add `After=mower-pixhawk-sync.service` ordering |
| Weston seatd polling ExecStartPre adds boot latency | Low | Low | 5s max polling; seatd typically ready in <1s |
| Bringup always-run increases deploy time | Low | Low | Unit file write is ~2s; pip skip check is fast |

## Execution Plan

### Phase 1: Param Apply Resilience & Safety Defaults Fix

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 7
**Prerequisites:** None
**Entry Point:** `src/mower_rover/params/mav.py`
**Verification:** `pytest tests/test_params.py tests/test_params_sitl.py tests/test_pixhawk_sync.py -v` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Define `ApplyResult` dataclass in `mav.py` | `src/mower_rover/params/mav.py` | ✅ Complete |
| 1.2 | Refactor `apply_params()` to return `ApplyResult` | `src/mower_rover/params/mav.py` | ✅ Complete |
| 1.3 | Update `sync_params()` to use `ApplyResult` | `src/mower_rover/pixhawk/sync.py` | ✅ Complete |
| 1.4 | Remove `FS_GCS_TIMEOUT` from safety-defaults + baseline + tests | `safety-defaults.yaml`, `z254_baseline.yaml`, `tests/test_params.py` | ✅ Complete |
| 1.5 | Update sync test assertions for `ApplyResult` | `tests/test_pixhawk_sync.py` | ✅ Complete |
| 1.6 | Update `cli/params.py` caller for `ApplyResult` | `src/mower_rover/cli/params.py` | ✅ Complete |

### Phase 2: MAVLink FTP Race Elimination & Bridge Ordering

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 1 complete (sync_params changes)
**Entry Point:** `src/mower_rover/vslam/bridge.py`
**Verification:** `pytest tests/test_probe_vslam.py tests/test_vslam_health.py tests/test_service.py -v` passes; grep confirms no `check_and_deploy_lua` in bridge.py

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Remove `check_and_deploy_lua` from bridge.py | `src/mower_rover/vslam/bridge.py` | ✅ Complete |
| 2.2 | Add `PIXHAWK_SYNC_UNIT_NAME` + bridge `After=` ordering | `src/mower_rover/service/unit.py` | ✅ Complete |

### Phase 3: Weston Cold-Boot & Kiosk-Renderer Resilience

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 3
**Prerequisites:** None (independent of Phases 1–2)
**Entry Point:** `src/mower_rover/service/unit.py`
**Verification:** `pytest tests/test_kiosk_units.py tests/test_service.py -v` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add seatd socket polling ExecStartPre to Weston template | `src/mower_rover/service/unit.py` | ✅ Complete |
| 3.2 | Parameterize `StartLimitBurst`, kiosk-renderer=15 | `src/mower_rover/service/unit.py` | ✅ Complete |
| 3.3 | Update repo-root `weston.service` | `weston.service` | ✅ Complete |
| 3.4 | Update Weston/kiosk-renderer tests | `tests/test_kiosk_units.py`, `tests/test_service.py` | ✅ Complete |

### Phase 4: RTAB-Map MemoryThr Fix & DB Path Correction

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** None (independent of Phases 1–3)
**Entry Point:** `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`
**Verification:** C++ compiles on Jetson via `build-slam-node` bringup step; `pytest tests/test_bringup.py -v -k "db_path or zone_db"` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | Insert `MemoryThr` params.insert in C++ SLAM node | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 4.2 | Zone-aware DB path resolution in bringup | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 4.3 | Default `_test` zone activation in vslam-config step | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 4.4 | Add zone-aware DB path tests | `tests/test_bringup.py` | ✅ Complete |

### Phase 5: Bringup Always-Run for Service-Install Steps

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 1
**Prerequisites:** Phases 1–4 complete (all unit template changes landed)
**Entry Point:** `src/mower_rover/cli/bringup.py`
**Verification:** `pytest tests/test_bringup.py -v` passes; manual verify that `--from-step service` does not print "Already satisfied — skipping" for any of the five service steps

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Always-run for `service` step | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 5.2 | Always-run for `install-mavproxy` step | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 5.3 | Internal MAVProxy pip-present check | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 5.4 | Always-run for `vslam-services` step | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 5.5 | Always-run for `pixhawk-sync` step | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 5.6 | Always-run for `kiosk-services` step | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 5.7 | Update bringup tests for always-run behavior | `tests/test_bringup.py` | ✅ Complete |

## Standards

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 3 | ~12 files across params, sync, bridge, service, bringup, C++ SLAM node, tests |
| New patterns introduced | 1 | `ApplyResult` dataclass follows existing `SyncResult` pattern |
| External dependencies | 1 | No new deps; all changes use existing pymavlink/structlog/systemd |
| Migration complexity | 2 | `apply_params()` return-type change affects 3 callers + tests; reversible |
| Test coverage required | 3 | Unit tests for ApplyResult, sync_params filtering, bringup DB path; SITL for param apply |
| **Overall Complexity** | **10/25** | **Low** — well-scoped fixes with clear acceptance criteria |

## Review Summary

**Review Date:** 2026-05-06
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.1
**Reviewed Plan Version:** v2.8

### Review Metrics
- Issues Found: 8 (Critical: 1, Major: 5, Minor: 2)
- Clarifying Questions Asked: 8
- Sections Updated: Phase 1 (Steps 1.4–1.6, verification, file count), Phase 2 (Step 2.2–2.3, file count), Phase 3 (Step 3.2, Step 3.4, verification), Phase 4 (Step 4.4, verification), Architecture #8

### Key Improvements Made
1. **Critical:** Added Step 1.6 for `cli/params.py` caller — prevented silent swallowing of param apply failures in safety-critical CLI command
2. **Critical:** Expanded Step 1.4 to cascade `FS_GCS_TIMEOUT` removal to `z254_baseline.yaml`, `SAFETY_KEYS`, and `test_load_profile_safety_defaults_has_seven_keys` — prevented 3 guaranteed test failures
3. **Major:** Fixed Step 3.2 — `StartLimitBurst` is hardcoded in generic templates, not parameterized; plan now specifies adding `start_limit_burst` parameter to `generate_service_unit()`
4. **Major:** Fixed Step 2.2 — specified `PIXHAWK_SYNC_UNIT_NAME` constant location in `service/unit.py` alongside existing constants
5. **Minor:** Fixed Architecture #8 — `ParamSet.from_dict()` does not exist; corrected to `from_mapping()`
6. **Minor:** Removed Step 2.3 — no tests mock bridge's `check_and_deploy_lua` call; step had no implementation work
7. Corrected Step 1.5 test file references from `test_params.py`/`test_params_sitl.py` to `test_pixhawk_sync.py`
8. Updated Phase 1 verification command to include `tests/test_pixhawk_sync.py`
9. **Major:** Corrected Step 3.4 test file references from `test_kiosk_services.py`/`test_kiosk_renderer.py` to `test_kiosk_units.py`/`test_service.py` — the original files contain zero unit file content assertions
10. **Major:** Rewrote Step 4.4 from "update existing DB tests" (none exist) to "add three new zone-aware DB path tests" with explicit code paths to cover

### Remaining Considerations
- The 221 GB RTAB-Map DB on the Jetson must be manually deleted before restarting VSLAM (operational step, not code)
- `FS_TIMEOUT` value change (1.5s → 5s) deferred to field validation — this is correct per copilot-instructions
- `test_load_profile_safety_defaults_has_seven_keys` should be renamed to `..._has_six_keys` for clarity (coder discretion)
- `ApplyResult` should be added to `params/__init__.py` `__all__` exports (coder should handle during Step 1.1)
- Phase 2 depends on Phase 1 (sync_params changes), but Phases 3 and 4 are independent and can be parallelized

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Implementation Notes

### Plan Completion

**All phases completed:** 2026-05-06
**Total tasks completed:** 22/22
**Total files modified:** 14
**Execution mode:** Automatic (Subagent Orchestration)
**Test results:** 357 passed, 1 skipped (Windows SIGTERM — expected)

**Files Modified:**
- `src/mower_rover/params/mav.py` — `ApplyResult` dataclass, `apply_params()` return type
- `src/mower_rover/params/__init__.py` — `ApplyResult` export
- `src/mower_rover/pixhawk/sync.py` — drifted-only apply, skip-missing warnings, `exc_info=True`
- `src/mower_rover/params/data/safety-defaults.yaml` — removed `FS_GCS_TIMEOUT`
- `src/mower_rover/params/data/z254_baseline.yaml` — removed `FS_GCS_TIMEOUT`
- `src/mower_rover/cli/params.py` — `ApplyResult` failure reporting
- `src/mower_rover/vslam/bridge.py` — removed `check_and_deploy_lua` import + call
- `src/mower_rover/service/unit.py` — seatd poll, `start_limit_burst` param, `PIXHAWK_SYNC_UNIT_NAME`, bridge ordering
- `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` — `MemoryThr` params.insert
- `src/mower_rover/cli/bringup.py` — zone-aware DB path, `_test` zone, always-run steps, MAVProxy pip check, dead code cleanup
- `weston.service` — seatd poll + ordering
- `tests/test_params.py` — `SAFETY_KEYS` 6 entries, renamed test
- `tests/test_pixhawk_sync.py` — `ApplyResult` assertions, unknown-param test
- `tests/test_kiosk_units.py` — seatd poll + StartLimitBurst=15 tests
- `tests/test_bringup.py` — zone-aware DB tests, always-run integration tests

**Code Review:** 3 findings — all fixed (bare expression removed, unused import removed, `exc_info=True` added)

**Deviations from Plan:** None

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-06 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-06 |
| Status | ✅ Complete |
| Next Agent | — |
| Plan Location | docs/plans/027-remaining-jetson-instabilities-fixes.md |
