---
id: "022"
type: plan
title: "Kiosk Dashboard Data Delivery Gap Fixes"
status: "\u2705 Complete"
created: "2026-05-05"
updated: "2026-05-05"
completed: "2026-05-05"
owner: pch-coder
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-05 | pch-planner | Initial plan creation |
| v2.0 | 2026-05-05 | pch-planner | Holistic review + execution plan complete |
| v2.1 | 2026-05-05 | pch-plan-reviewer | Review: fixed VSLAM_CONF scale (0–100 not 0–255); made step 1.3 mandatory; added complexity + review summary |

## Introduction

This plan addresses 7 bugs across 3 data delivery paths in the kiosk dashboard that leave 2 of 8 panels non-functional (VSLAM Status, Services) and make MAVLink-fed panels fragile during boot races. Based on research doc `docs/research/025-kiosk-data-delivery-gaps.md`.

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 2  
**Last Updated:** 2026-05-05

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | VSLAM_CONF range incorrect (0–255 vs actual 0–100); display format | correctness | Option A — Raw integer (0–100) | Architectural Considerations + Step 2.5 AC corrected |
| 2 | Step 1.3 "Optionally" ambiguity | clarity | Option B — Make mandatory; wire to KioskConfig | Step 1.3 reworded as mandatory |

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Heartbeat retry strategy | B — Unbounded retry until shutdown | Simple, guarantees eventual recovery, matches PoseReader pattern, clean exit via shutdown event |
| 2 | VSLAM panel metrics | A — Bridge health metrics (rate, confidence, age, covariance) | Direct 1:1 mapping to NAMED_VALUE_FLOAT messages, zero derivation logic, tells operator everything needed |

## Holistic Review

### Decision Interactions

- **Unbounded heartbeat retry + After= ordering** complement each other: the ordering reduces the window where retry is needed, while unbounded retry guarantees recovery even if MAVProxy restarts mid-session.
- **VSLAM via MAVLink + heartbeat retry** interact positively: since VSLAM data now flows through the same MAVLink connection, a single retry mechanism covers both Vehicle State and VSLAM panels.
- **Removing the VSLAM socket thread** simplifies the threading model (3 threads → 2 threads: telemetry + slow poller), reducing contention and failure modes.

### Architectural Considerations

- No new dependencies, no new IPC channels — data flows through the existing MAVProxy UDP path.
- The `update_vslam()` method accepts `**kwargs` so the field name change (from `x/y/confidence/reset_counter` to `rate_hz/confidence/age_ms/covariance_norm`) is transparent to `SharedState`.
- Dashboard VSLAM panel (Card 0) reads from `snap["vslam"]` dict — the field names in `set_metric()` calls need updating to match new keys.
- Status dot logic currently checks `vslam.get("confidence", 0) >= 2` — this remains valid since `VSLAM_CONF` is 0–100 quality metric (per `vslam_pose_msg.h`). Dashboard displays the raw integer (e.g., "Confidence: 80").

### Trade-offs Accepted

- Pose x/y/z data is no longer shown on the dashboard (not available via NAMED_VALUE_FLOAT). Acceptable because operational health (rate, age, covariance) is more useful for the operator than raw coordinates.
- Unbounded retry means the thread consumes a small amount of resources indefinitely when MAVProxy is truly absent. Acceptable because 10s timeout blocks in pymavlink have near-zero CPU cost.

### Risks Acknowledged

- If MAVProxy filters NAMED_VALUE_FLOAT (non-default), VSLAM panel stays blank. Mitigation: standard MAVProxy forwards all messages; confirmed by laptop-side `health_listener.py` already receiving them.
- `bytes` vs `str` for `msg.name` in pymavlink versions — mitigated by copying the `rstrip` pattern from `health_listener.py`.

## Overview

### Feature Summary

Fix all data delivery bugs in the kiosk dashboard so all 8 panels display live, correct data in the deployed Jetson environment. Scope: ~80 lines across 5–6 files, no new services, no Jetson-side config changes.

### Objectives

1. Services panel shows correct live status of all 4 system-level services
2. VSLAM Status panel receives live metrics via MAVLink NAMED_VALUE_FLOAT
3. MAVLink telemetry thread survives boot races (heartbeat retry)
4. CLI `kiosk status/enable/disable` operates on correct unit names
5. Kiosk unit has proper startup ordering relative to MAVProxy

## Requirements

### Functional

- FR-1: `_check_services()` queries system-level systemd (no `--user` flag)
- FR-2: `_check_services()` uses correct unit names (`mower-vslam.service`, `mower-mavproxy.service`)
- FR-3: VSLAM panel populated via `NAMED_VALUE_FLOAT` messages from telemetry thread
- FR-4: Telemetry thread retries heartbeat on initial connection failure
- FR-5: `KIOSK_UNITS` list in `cli/kiosk.py` uses `mower-mavproxy.service`
- FR-6: Kiosk systemd unit orders after `mower-mavproxy.service`

### Non-Functional

- NFR-1: All fixes testable without hardware (unit tests with mocked subprocess/MAVLink)
- NFR-2: No new dependencies introduced
- NFR-3: Backward-compatible — no Jetson-side config file changes needed

### Out of Scope

- Modifying the SLAM node C++ code (single-client socket is by design)
- Adding new systemd services
- Changing MAVProxy configuration or outputs
- VSLAM bridge changes

## Technical Design

### Architecture

The fix restructures the VSLAM data flow to use MAVLink instead of a direct Unix socket:

```
Before (broken):
  SLAM node → /run/mower/vslam-pose.sock → kiosk PoseReader (FAILS: wrong path + single-client)

After (fixed):
  SLAM node → /run/mower/vslam-pose.sock → bridge → NAMED_VALUE_FLOAT → MAVProxy
       → UDP :14551 → kiosk telemetry thread → SharedState.update_vslam()
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: NAMED_VALUE_FLOAT parsing
    location: "src/mower_rover/vslam/health_listener.py"
    usage: Reference for parsing VSLAM_HZ/VSLAM_CONF/VSLAM_AGE/VSLAM_COV in kiosk telemetry
  - pattern: SharedState update methods
    location: "src/mower_rover/kiosk/state.py"
    usage: update_vslam(**kwargs) already accepts arbitrary keyword updates
  - pattern: Unit name constants
    location: "src/mower_rover/service/unit.py"
    usage: MAVPROXY_UNIT_NAME, VSLAM_UNIT_NAME constants for correct names
  - pattern: generate_service_unit kwargs
    location: "src/mower_rover/service/unit.py"
    usage: after= parameter accepts space-separated unit list
  - pattern: KioskConfig defaults
    location: "src/mower_rover/config/jetson.py"
    usage: service_check_units already has correct names
```

## Dependencies

- Research: `docs/research/025-kiosk-data-delivery-gaps.md` (complete)
- MAVProxy deployed and active on Jetson (confirmed 2026-05-05)
- VSLAM bridge emitting NAMED_VALUE_FLOAT messages (confirmed in bridge.py)

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| NAMED_VALUE_FLOAT not forwarded by MAVProxy | Low | High | Standard MAVProxy behavior; confirmed in health_listener.py laptop-side |
| Dashboard field name mismatch after VSLAM refactor | Medium | Medium | Verify dashboard.py reads matching keys |
| systemctl without --user fails on non-Linux (test env) | Low | Low | Tests mock subprocess.run |

## Execution Plan

### Phase 1: Service Status and Unit Name Fixes (P0-A + P1-B)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 3  
**Prerequisites:** None  
**Entry Point:** `src/mower_rover/kiosk/app.py`  
**Verification:** `pytest tests/test_kiosk_dashboard.py tests/test_kiosk_cli.py -x` passes (if they exist; otherwise new test)

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Fix `_check_services()`: remove `--user` flag from `subprocess.run` call | `src/mower_rover/kiosk/app.py` | ✅ Complete |
| 1.2 | Fix `_check_services()`: correct unit names to `mower-vslam.service` and `mower-mavproxy.service` | `src/mower_rover/kiosk/app.py` | ✅ Complete |
| 1.3 | Wire `_check_services()` to accept a unit list parameter; caller passes `KioskConfig.service_check_units` from loaded config (single source of truth for service names) | `src/mower_rover/kiosk/app.py` | ✅ Complete |
| 1.4 | Add `mower-mavproxy.service` to `_default_kiosk_service_units()` in config | `src/mower_rover/config/jetson.py` | ✅ Complete |
| 1.5 | Fix `KIOSK_UNITS` in CLI: change `"mavproxy.service"` → `"mower-mavproxy.service"` | `src/mower_rover/cli/kiosk.py` | ✅ Complete |
| 1.6 | Add/update unit tests for `_check_services()` verifying correct subprocess call (no `--user`, correct unit names) | `tests/test_kiosk_services.py` (new) | ✅ Complete |

### Phase 2: Heartbeat Retry + VSLAM via MAVLink (P1-A + P0-B)

**Status:** ✅ Complete  
**Size:** Medium  
**Files to Modify:** 4  
**Prerequisites:** Phase 1 complete (not strictly required but cleaner to land together)  
**Entry Point:** `src/mower_rover/kiosk/telemetry.py`  
**Verification:** `pytest tests/test_kiosk_dashboard.py tests/test_kiosk_state.py -x` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Wrap `wait_heartbeat()` in unbounded retry loop | `src/mower_rover/kiosk/telemetry.py` | ✅ Complete |
| 2.2 | Add `NAMED_VALUE_FLOAT` handling to `mavlink_reader_loop()` | `src/mower_rover/kiosk/telemetry.py` | ✅ Complete |
| 2.3 | Implement `_handle_named_value_float(state, msg)` | `src/mower_rover/kiosk/telemetry.py` | ✅ Complete |
| 2.4 | Remove `_vslam_reader_thread()` and its thread launch | `src/mower_rover/kiosk/app.py` | ✅ Complete |
| 2.5 | Update dashboard VSLAM panel (Card 0) field names | `src/mower_rover/kiosk/dashboard.py` | ✅ Complete |
| 2.6 | Update VSLAM status dot logic with age_ms check | `src/mower_rover/kiosk/dashboard.py` | ✅ Complete |
| 2.7 | Add unit tests for `_handle_named_value_float()` | `tests/test_kiosk_state.py` | ✅ Complete |
| 2.8 | Add unit test for heartbeat retry | `tests/test_kiosk_state.py` | ✅ Complete |

### Phase 3: Systemd Unit Ordering (P2)

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 2  
**Prerequisites:** Phase 1 complete (MAVPROXY_UNIT_NAME constant used)  
**Entry Point:** `src/mower_rover/service/unit.py`  
**Verification:** `pytest tests/test_kiosk_units.py -x` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add `{MAVPROXY_UNIT_NAME}.service` to the `after=` parameter in `generate_kiosk_unit_file()` | `src/mower_rover/service/unit.py` | ✅ Complete |
| 3.2 | Update existing `test_kiosk_units.py` assertions to expect `mower-mavproxy.service` in After= line | `tests/test_kiosk_units.py` | ✅ Complete |

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 6 files: `app.py`, `telemetry.py`, `dashboard.py`, `cli/kiosk.py`, `config/jetson.py`, `service/unit.py` + 2 test files |
| New patterns introduced | 1 | Reuses existing NAMED_VALUE_FLOAT parsing pattern from `health_listener.py` |
| External dependencies | 1 | No new dependencies; pymavlink already in use |
| Migration complexity | 1 | No data migration; removes dead code (VSLAM socket thread) |
| Test coverage required | 2 | Unit tests with mocked subprocess and MAVLink messages |
| **Overall Complexity** | **7 / 25** | **Low** (≤ 10) — small, well-bounded bug fixes reusing existing patterns |

## Review Summary

**Review Date:** 2026-05-05
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Review Metrics

- Issues Found: 4 (Critical: 1, Major: 1, Minor: 2)
- Critical/Major Resolved: 2/2
- Minor: 2 (acknowledged, noted for implementer awareness)
- Clarifying Questions Asked: 2
- Sections Updated: Architectural Considerations, Step 1.3, Step 2.5

### Codebase Verification Performed

| Claim | Result |
|-------|--------|
| `_check_services()` uses `--user` flag | ✅ Verified (app.py line 183) |
| `_check_services()` has wrong unit names | ✅ Verified (`mavproxy.service`, `mower-slam-node.service`) |
| `KIOSK_UNITS` contains `"mavproxy.service"` | ✅ Verified (cli/kiosk.py line 33) |
| `_default_kiosk_service_units()` missing mavproxy | ✅ Verified |
| `generate_kiosk_unit_file()` After= lacks mavproxy | ✅ Verified (unit.py line 495) |
| telemetry.py has no NAMED_VALUE_FLOAT handling | ✅ Verified |
| `update_vslam(**kwargs)` signature | ✅ Verified (state.py line 102) |
| NAMED_VALUE_FLOAT parsing in `health_listener.py` lines 62–72 | ✅ Verified |
| Bridge sends `VSLAM_CONF` as `float(h.confidence)` | ✅ Verified (bridge.py line 83) |
| `VSLAM_CONF` is 0–255 byte | ❌ **Incorrect** — `vslam_pose_msg.h` defines confidence as `uint8_t, 0–100 quality metric` |
| `service_check_units` field exists in KioskConfig | ✅ Verified (config/jetson.py line 57) |
| `MAVPROXY_UNIT_NAME` constant exists | ✅ Verified (`"mower-mavproxy"`, unit.py line 27) |

### Key Improvements Made

1. **Q1 (Critical):** Corrected VSLAM_CONF scale from "0–255" to "0–100" in Architectural Considerations and Step 2.5. Dashboard displays raw integer.
2. **Q2 (Major):** Removed "Optionally" from Step 1.3; made config-driven service list mandatory. `_check_services()` now explicitly accepts a unit list from `KioskConfig.service_check_units`.

### Remaining Considerations (Minor, non-blocking)

- **Minor-1:** Architecture diagram uses `vslam-pose.sock` (hyphen) but actual code in `app.py` line 48 uses `vslam_pose.sock` (underscore). Implementer should reference the code, not the diagram.
- **Minor-2:** Step 2.6 `age_ms` thresholds (1000ms, 3000ms) have no cited source. These seem reasonable (1s = stale, 3s = dead) but implementer may want to make them configurable via `KioskConfig` or at minimum add a comment justifying the values.

### Sign-off

This plan has been reviewed and is **✅ Ready for Implementation**.

## Standards

No organizational standards applicable to this plan.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-05 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-05 |
| Status | ✅ Complete |
| Next Agent | pch-coder |
| Plan Location | docs/plans/022-kiosk-data-gaps-fixes.md |

## Implementation Notes

### Phase 1 — Service Status and Unit Name Fixes

**Completed:** 2026-05-05

**Files Modified:** `src/mower_rover/kiosk/app.py`, `src/mower_rover/config/jetson.py`, `src/mower_rover/cli/kiosk.py`
**Files Created:** `tests/test_kiosk_services.py`

**Deviations:** Tests placed in new `tests/test_kiosk_services.py` (not `test_kiosk_dashboard.py`) because the dashboard test file has a module-level `pytest.importorskip("gi")` that skips ALL tests on Windows/headless CI. Service key derivation uses `_unit_display_key()` helper instead of hardcoded mapping.

### Phase 2 — Heartbeat Retry + VSLAM via MAVLink

**Completed:** 2026-05-05

**Files Modified:** `src/mower_rover/kiosk/telemetry.py`, `src/mower_rover/kiosk/app.py`, `src/mower_rover/kiosk/dashboard.py`, `tests/test_kiosk_state.py`, `tests/test_kiosk_dashboard.py`

**Deviations:** Updated existing test `test_refresh_updates_from_snapshot` to use new VSLAM field names. Module docstring in `app.py` updated to remove stale "VSLAM" thread mention.

### Phase 3 — Systemd Unit Ordering

**Completed:** 2026-05-05

**Files Modified:** `src/mower_rover/service/unit.py`, `tests/test_kiosk_units.py`

**Deviations:** None.

### Code Review

**Completed:** 2026-05-05
**Findings:** 2 (both fixed)

1. `_slow_poller_thread` error log missing `exc_info=exc` — fixed.
2. Bare `threading.Event()` expression in `test_kiosk_state.py` — removed.

### Plan Completion

**All phases completed:** 2026-05-05
**Total tasks completed:** 16
**Total files modified/created:** 10
**Test results:** 833 passed, 2 skipped, 0 failures
