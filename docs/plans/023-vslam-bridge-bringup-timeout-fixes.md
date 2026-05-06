---
id: "023"
type: plan
title: "VSLAM Bridge Bringup Timeout & MAVProxy Service Ordering Fixes"
status: "✅ Complete"
created: "2026-05-06"
updated: "2026-05-06"
completed: "2026-05-06"
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-06 | pch-planner | Initial plan creation || v1.1 | 2026-05-06 | pch-planner | Scope decision: all 6 fixes |
| v1.2 | 2026-05-06 | pch-planner | SIGTERM handler approach: shutdown_event param |
| v1.3 | 2026-05-06 | pch-planner | Polling approach: single combined SSH call |
| v2.0 | 2026-05-06 | pch-planner | Holistic review + execution plan complete |
| v2.1 | 2026-05-06 | pch-plan-reviewer | Review pass: test placement decision, template/import clarifications |
## Introduction

This plan implements the remediation fixes identified in [research 026](../research/026-jetson-service-connection-kiosk-update-issues.md). The bringup process fails at the `vslam-services` step (step 19) due to a cascade failure: `install-cli` destroys the MAVProxy binary via `uv tool install --force`, the VSLAM bridge cannot connect to its MAVProxy dependency, and timeouts at multiple layers (SSH 60s, systemd 90s) cause the bringup to abort before `install-mavproxy` (step 21) can fix the venv. The minimum fix is three changes: reorder steps, add `TimeoutStartSec=120` to the bridge unit, and add `systemctl reset-failed` before start.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Scope of fixes | A — All 6 fixes in one plan | All fixes are closely related, single deployment verifies complete fix |
| 2 | SIGTERM handler placement | A — Pass `shutdown_event` parameter to `open_link()` | Clean, explicit, testable; backward-compatible optional param; `event.wait(timeout=backoff)` is drop-in replacement for `time.sleep()` |
| 3 | Polling implementation | D — Single SSH call with combined status query | `systemctl is-active svc1 svc2` outputs one line per unit; one SSH round-trip per iteration; follows existing combined-command pattern in bringup |

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 1  
**Last Updated:** 2026-05-06

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | Test file for `open_link()` shutdown behavior | Specificity | Option B: New `tests/test_connection.py` | Task 3.3 updated |

## Holistic Review

### Decision Interactions

- **Fix 1 (step reorder) + Fix 5 (Requires=):** These reinforce each other. Reordering ensures MAVProxy is installed before the bridge starts; `Requires=` prevents systemd from starting the bridge if MAVProxy subsequently fails. Both are needed — reorder handles the bringup path, Requires handles the boot/restart path.
- **Fix 4 (polling) + Fix 2 (TimeoutStartSec=120):** The polling budget (120s) matches the systemd timeout. This is intentional — if systemd kills the bridge at 120s, the polling loop will detect `failed` status on the next iteration rather than timing out simultaneously.
- **Fix 6 (shutdown_event) + Fix 2 (timeout):** With the shutdown event, the bridge exits promptly on SIGTERM during connection retries. This means systemd's TimeoutStartSec rarely needs to fire — SIGTERM alone handles graceful abort. The 120s timeout is a safety net.
- **Fix 3 (reset-failed) + Fix 1 (reorder):** reset-failed is still needed even after reordering, because a prior bringup attempt (or manual service restart) could have left the bridge in `start-limit-hit` state from a previous failure.

### Architectural Considerations

- **No regression for direct `/dev/pixhawk` users:** If `vslam.yaml` has `serial_device: /dev/pixhawk` (no MAVProxy), the `Requires=mower-mavproxy.service` on the bridge unit means the bridge won't start without MAVProxy. This is acceptable because `install-mavproxy` always rewrites the config to use UDP, and the Requires matches the runtime dependency. If someone manually changes the config back to direct serial, they'd also need to remove the Requires — but this is a supported-hardware-only project, not a general-purpose tool.
- **`open_link()` API change is backward-compatible:** The new `shutdown_event` parameter is keyword-only with default `None`. All existing callers (CLI commands, tests) continue to work unchanged.

### Trade-offs Accepted

- The polling loop adds 5s latency to detecting success (poll interval). This is acceptable for a bringup tool that already takes minutes.
- `Requires=` creates a hard dependency — if MAVProxy is removed, the bridge won't start. This correctly models the actual runtime dependency.

### Risks Acknowledged

- If the Pixhawk is powered off during bringup, MAVProxy will start but immediately enter a restart loop (can't open `/dev/pixhawk`). The bridge will then fail to get a heartbeat. The polling loop will eventually report failure. This is correct behavior — the operator should connect the Pixhawk before running bringup.
- The 120s polling budget assumes normal cold-start. If NVMe is degraded, RTAB-Map vocabulary loading could exceed 120s. This would require increasing the timeout — an operational concern, not a code bug.

## Overview

### Problem Statement

Bringup deploys (022–023) fail at step 19 (`vslam-services`) every time because:

1. Step 14 (`install-cli`) runs `uv tool install --force` which wipes the shared tool venv — including MAVProxy's binary and dependencies
2. The VSLAM bridge connects to `udp:127.0.0.1:14550` (MAVProxy output port), but MAVProxy is dead → no heartbeat → 150s+ connection timeout
3. SSH timeout (60s) < systemd `TimeoutStartSec` (90s default) — bringup gives up first
4. No `systemctl reset-failed` — prior failures block restarts within 300s window
5. Step 21 (`install-mavproxy`) that reinstalls the binary is never reached

### Objectives

- Unblock bringup by ensuring MAVProxy is installed and running before the bridge needs it
- Eliminate the SSH/systemd timeout race condition
- Harden service dependencies and shutdown behavior for production

### Scope

All six fixes from research 026:

| # | Fix | Severity |
|---|-----|----------|
| 1 | Move `install-mavproxy` before `vslam-services` in step order | Critical |
| 2 | Add `TimeoutStartSec=120` to bridge unit template | Critical |
| 3 | Add `systemctl reset-failed` before service start | Critical |
| 4 | Replace blocking `systemctl start` with `--no-block` + polling | Important |
| 5 | Add `Requires=mower-mavproxy.service` to bridge unit | Hardening |
| 6 | Add SIGTERM handler to bridge connection retry loop (via `shutdown_event` param on `open_link()`) | Hardening |

## Requirements

### Functional

- FR-1: Bringup step `install-mavproxy` executes before `vslam-services`
- FR-2: Bridge systemd unit includes `TimeoutStartSec=120`
- FR-3: `_run_vslam_services()` runs `systemctl reset-failed` before `systemctl start`
- FR-4: Service start uses `--no-block` with polling (up to 120s) instead of blocking `systemctl start`
- FR-5: Bridge unit declares `Requires=mower-mavproxy.service` as hard dependency
- FR-6: Bridge process exits cleanly on SIGTERM during connection retry phase

### Non-Functional

- NFR-1: All existing unit tests pass without modification (only new/updated assertions)
- NFR-2: No changes to the bridge's runtime behavior after `READY=1` is sent
- NFR-3: Bringup progress reporting gives operator visibility during polling wait

### Out of Scope

- Restructuring MAVProxy into a declared `pyproject.toml` dependency (separate effort)
- Switching bridge to `Type=simple` with watchdog-only signaling
- Adding `BindsTo=dev-pixhawk.device` to MAVProxy/bridge units (plan 009 item)

## Technical Design

### Architecture

No architectural changes. This fixes service ordering, timeout configuration, and startup robustness within the existing systemd + SSH bringup architecture.

### Fix 1: Reorder `install-mavproxy` Before `vslam-services`

**File:** `src/mower_rover/cli/bringup.py` (BRINGUP_STEPS list, ~line 2140)

Move the `BringupStep(name="install-mavproxy", ...)` entry from after `pixhawk-sync` to before `vslam-services`. The new step order around that area:

```
... (step 17) service
... (step 18) vslam-db-check
... (step 19) install-mavproxy   ← MOVED HERE (was step 21)
... (step 20) vslam-services     ← was step 19
... (step 21) pixhawk-sync       ← was step 20
... (step 22) kiosk-services
... (step 23) kiosk-probe
... (step 24) final-verify
```

**Dependency validation:** `install-mavproxy` requires:
- uv tool venv (from `install-cli`, step 14) ✓
- `/dev/pixhawk` symlink (from `pixhawk-udev`, step 12) ✓
- No dependency on `vslam-services` or `pixhawk-sync` ✓

### Fix 2: Add `TimeoutStartSec=120` to Bridge Unit

**File:** `src/mower_rover/service/unit.py` — `generate_vslam_bridge_unit_file()` (~line 380)

Add `timeout_start_sec=120` parameter to the `generate_service_unit()` call:

```python
def generate_vslam_bridge_unit_file(
    *,
    mower_jetson_path: str,
    user: str,
    home_dir: str,
    user_level: bool = True,
) -> str:
    exec_start = f"{mower_jetson_path} vslam bridge-run"
    return generate_service_unit(
        description="Mower Rover VSLAM MAVLink bridge daemon",
        exec_start=exec_start,
        user=user,
        home_dir=home_dir,
        user_level=user_level,
        after=f"network.target {VSLAM_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
        binds_to=None,
        watchdog_sec=30,
        runtime_directory=None,
        timeout_start_sec=120,  # ← NEW
    )
```

The `generate_service_unit()` function already supports `timeout_start_sec: int | None = None` and emits `TimeoutStartSec={value}\n` when set. No changes needed to the template logic.

### Fix 3: Add `systemctl reset-failed` Before Service Start

**File:** `src/mower_rover/cli/bringup.py` — `_run_vslam_services()` (~line 1480)

Insert a `reset-failed` call before the `systemctl start` command:

```python
# Clear any prior failure state (start-limit-hit, etc.)
bctx.console.print("  Resetting failed state…")
with contextlib.suppress(SshError):
    client.run(
        ["sudo systemctl reset-failed mower-vslam.service mower-vslam-bridge.service"],
        timeout=10,
    )
```

Uses `contextlib.suppress(SshError)` because `reset-failed` on a never-started service returns non-zero — this is not an error condition.

### Fix 4: `--no-block` + Polling for Service Start

**File:** `src/mower_rover/cli/bringup.py` — `_run_vslam_services()` (~line 1480)

Replace the blocking `systemctl start` call with:

1. **Non-blocking start:**
```python
client.run(
    ["sudo systemctl start --no-block mower-vslam.service mower-vslam-bridge.service"],
    timeout=15,
)
```

2. **Polling loop** (single SSH call per iteration, 5s interval, 120s budget):
```python
import time as _time

deadline = _time.time() + 120
while _time.time() < deadline:
    _time.sleep(5)
    try:
        result = client.run(
            ["systemctl is-active mower-vslam.service mower-vslam-bridge.service"],
            timeout=10,
        )
    except SshError as exc:
        bctx.console.print(f"  [yellow]Poll SSH error:[/yellow] {exc}")
        continue

    lines = (result.stdout or "").strip().splitlines()
    statuses = [l.strip() for l in lines]

    if all(s == "active" for s in statuses):
        bctx.console.print("  [green]Both VSLAM services active.[/green]")
        return

    if any(s == "failed" for s in statuses):
        # Fetch diagnostics
        diag = client.run(
            ["sudo systemctl status mower-vslam-bridge.service --no-pager -l"],
            timeout=10,
        )
        bctx.console.print(f"  [red]Service failed:[/red]")
        if diag.stdout:
            bctx.console.print(diag.stdout[:500], style="dim", highlight=False)
        raise typer.Exit(code=3)

    vslam_s = statuses[0] if len(statuses) > 0 else "?"
    bridge_s = statuses[1] if len(statuses) > 1 else "?"
    bctx.console.print(f"  Waiting… (vslam={vslam_s}, bridge={bridge_s})")

bctx.console.print("  [red]VSLAM services did not become active within 120s.[/red]")
raise typer.Exit(code=3)
```

### Fix 5: Add `Requires=mower-mavproxy.service` to Bridge Unit

**File:** `src/mower_rover/service/unit.py`

Two changes needed:

**5a.** Add `requires` parameter to `generate_service_unit()` (~line 88):

```python
def generate_service_unit(
    *,
    description: str,
    exec_start: str,
    user: str,
    home_dir: str,
    user_level: bool = True,
    after: str = "network.target",
    requires: str | None = None,       # ← NEW
    binds_to: str | None = None,
    watchdog_sec: int = 30,
    timeout_start_sec: int | None = None,
    runtime_directory: str | None = None,
    service_type: str = "notify",
    extra_environment: dict[str, str] | None = None,
) -> str:
```

Add formatting logic:
```python
requires_line = f"Requires={requires}\n" if requires else ""
```

Insert `{requires}` into both `_GENERIC_SYSTEM_TEMPLATE` and `_GENERIC_USER_TEMPLATE` in the `[Unit]` section, after `{binds_to}`:
```ini
[Unit]
Description={description}
After={after}
StartLimitIntervalSec=300
StartLimitBurst=5
{binds_to}{requires}
```

**5b.** Add `requires` to `generate_vslam_bridge_unit_file()`:

```python
return generate_service_unit(
    ...
    after=f"network.target {VSLAM_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
    requires=f"{MAVPROXY_UNIT_NAME}.service",  # ← NEW
    binds_to=None,
    ...
)
```

### Fix 6: Pass `shutdown_event` to `open_link()`

**File:** `src/mower_rover/mavlink/connection.py`

**6a.** Add optional parameter to `open_link()`:

```python
@contextmanager
def open_link(
    config: ConnectionConfig,
    *,
    shutdown_event: threading.Event | None = None,
) -> Iterator[Any]:
```

Add `import threading` at the top of the file.

**6b.** Check shutdown between retries (replace `time.sleep` with event wait):

```python
if attempt < config.retry_attempts:
    if shutdown_event is not None:
        if shutdown_event.wait(timeout=config.retry_backoff_s * attempt):
            raise ConnectionError("shutdown requested during connection retry")
    else:
        time.sleep(config.retry_backoff_s * attempt)
```

**6c.** Check shutdown before each attempt:

```python
for attempt in range(1, config.retry_attempts + 1):
    if shutdown_event is not None and shutdown_event.is_set():
        raise ConnectionError("shutdown requested before connection attempt")
    log.info("connect_attempt", attempt=attempt, of=config.retry_attempts)
    ...
```

**File:** `src/mower_rover/vslam/bridge.py` — `run_bridge()` (~line 205)

Pass the shutdown event to `open_link()`:

```python
with open_link(conn_cfg, shutdown_event=shutdown) as conn:
```

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: BringupStep list ordering
    location: "src/mower_rover/cli/bringup.py:2040+"
    usage: Reorder steps by moving install-mavproxy entry
  - pattern: generate_service_unit() with timeout_start_sec parameter
    location: "src/mower_rover/service/unit.py:88"
    usage: Add timeout_start_sec=120 to bridge unit generation
  - pattern: SshError suppression with contextlib.suppress
    location: "src/mower_rover/cli/bringup.py:1437"
    usage: reset-failed command uses same pattern
  - pattern: Signal handler in bridge.py
    location: "src/mower_rover/vslam/bridge.py:196-201"
    usage: Existing _handle_signal sets shutdown event — pass to open_link
  - pattern: Unit template placeholders
    location: "src/mower_rover/service/unit.py:40-55"
    usage: Add {requires} placeholder alongside {binds_to}
```

### Data Contracts

No data entities in scope — data contracts not applicable.

## Dependencies

- Research 026 (complete) — provides root cause analysis and fix specifications
- Existing `generate_service_unit()` already supports `timeout_start_sec` parameter
- Existing signal handler infrastructure in bridge.py

## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Step reordering introduces new dependency violation | High | Low | `install-mavproxy` only needs uv venv (step 14) + `/dev/pixhawk` (step 12) — both already complete |
| `Requires=` prevents bridge start when Pixhawk disconnected | Medium | Medium | MAVProxy uses `Restart=always`; if Pixhawk absent, MAVProxy restarts but doesn't crash — bridge still starts |
| Polling loop in bringup adds SSH overhead | Low | Low | 5s intervals × 24 max polls = minimal overhead |

## Execution Plan

### Phase 1: Unit Template & Connection Fixes (service layer)

**Status:** ✅ Complete  
**Size:** Small (5 tasks)  
**Files to Modify:** 3  
**Prerequisites:** None  
**Entry Point:** `src/mower_rover/service/unit.py`  
**Verification:** `pytest tests/test_service.py -x` passes — 67 passed, 1 skipped

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Add `requires` parameter to `generate_service_unit()` | `src/mower_rover/service/unit.py` | ✅ Complete |
| 1.2 | Add `{requires}` placeholder to both unit templates and pass in `.format()` | `src/mower_rover/service/unit.py` | ✅ Complete |
| 1.3 | Add `timeout_start_sec=120` and `requires=MAVPROXY_UNIT_NAME.service` to `generate_vslam_bridge_unit_file()` | `src/mower_rover/service/unit.py` | ✅ Complete |
| 1.4 | Add `shutdown_event` parameter to `open_link()` | `src/mower_rover/mavlink/connection.py` | ✅ Complete |
| 1.5 | Pass `shutdown` event from `run_bridge()` to `open_link()` | `src/mower_rover/vslam/bridge.py` | ✅ Complete |

### Phase 2: Bringup Step Reorder & Start Logic

**Status:** ✅ Complete  
**Size:** Small (5 tasks)  
**Files to Modify:** 1  
**Prerequisites:** Phase 1 complete (bridge unit template updated)  
**Entry Point:** `src/mower_rover/cli/bringup.py`  
**Verification:** `pytest tests/test_bringup.py -x` passes — 129 passed

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Move `install-mavproxy` BringupStep before `vslam-services` in `BRINGUP_STEPS` list | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 2.2 | Add `systemctl reset-failed` call before service start in `_run_vslam_services()` | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 2.3 | Replace blocking `systemctl start` with `--no-block` invocation | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 2.4 | Add polling loop after `--no-block` start | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 2.5 | Update `_vslam_services_active()` check function if needed | `src/mower_rover/cli/bringup.py` | ✅ Complete (no change needed) |

### Phase 3: Tests & Holistic Review

**Status:** ✅ Complete  
**Size:** Small (4 tasks)  
**Files to Modify:** 2–3  
**Prerequisites:** Phases 1 and 2 complete  
**Entry Point:** `tests/test_service.py`  
**Verification:** `pytest tests/ -k "not sitl and not field" --tb=short` — 837 passed, 2 skipped, 0 failures

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add test: bridge unit contains `TimeoutStartSec=120` | `tests/test_service.py` | ✅ Complete |
| 3.2 | Add test: bridge unit contains `Requires=mower-mavproxy.service` | `tests/test_service.py` | ✅ Complete |
| 3.3 | Add test: `open_link()` respects `shutdown_event` | `tests/test_connection.py` (new file) | ✅ Complete |
| 3.4 | Run full test suite, fix any regressions | all test files | ✅ Complete — 837 passed, 2 skipped, 0 failures |

## Implementation Notes for Coder

1. **`bringup.py` already imports `time`** (line 40) — use `time.time()` and `time.sleep()` directly; do NOT alias as `_time`.
2. **`open_link()` uses `@contextmanager`** — the decorator stays; only add the `shutdown_event` keyword-only parameter.
3. **Template `.format()` call** (line ~108 in unit.py) — add `requires=requires_line` alongside the existing `binds_to=binds_to_line` kwarg.
4. **Line numbers are approximate** — search by function name (`_run_vslam_services`, `generate_vslam_bridge_unit_file`, `open_link`) rather than relying on line numbers.

## Review Summary

**Review Date:** 2026-05-06  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 5 (Critical: 0, Major: 2, Minor: 3)
- Clarifying Questions Asked: 1
- Sections Updated: Phase 1 tasks 1.2/1.4, Phase 3 task 3.3, Implementation Notes added

### Key Improvements Made
1. Task 1.2 acceptance criteria now explicitly requires `requires=requires_line` in the `.format()` call
2. Task 1.4 clarifies `@contextmanager` decorator retention and `import threading` addition
3. Task 3.3 decisively placed in new `tests/test_connection.py` (user decision)
4. Added Implementation Notes section with import and line-number guidance for coder

### Remaining Considerations
- Line numbers in Technical Design are approximate (~10 lines off); coder should search by function name
- If test discovery needs updating in CI config, coder should verify `tests/test_connection.py` is picked up by existing `pytest tests/` glob

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Standards

No organizational standards applicable to this plan.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-06 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-06 |
| Status | ✅ Complete |
| Implemented By | pch-coder |
| Implementation Date | 2026-05-06 |
| Plan Location | /docs/plans/023-vslam-bridge-bringup-timeout-fixes.md |

## Implementation Notes

### Plan Completion

**All phases completed:** 2026-05-06
**Total tasks completed:** 14
**Total files modified/created:** 7

**Files Modified:**
- `src/mower_rover/service/unit.py` — added `requires` param + template placeholder + bridge unit config
- `src/mower_rover/mavlink/connection.py` — added `shutdown_event` to `open_link()`
- `src/mower_rover/vslam/bridge.py` — passed `shutdown` event to `open_link()`
- `src/mower_rover/cli/bringup.py` — reordered steps, added reset-failed + no-block + polling
- `tests/test_service.py` — added bridge unit assertion tests
- `tests/test_bringup.py` — updated mocks for new SSH call pattern

**Files Created:**
- `tests/test_connection.py` — shutdown_event tests for `open_link()`

**Deviations from Plan:** None

**Code Review:** 1 pre-existing finding (dead code in `_build_deps_check`, unrelated to this plan)
