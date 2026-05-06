---
id: "021"
type: plan
title: "Kiosk Boot Ordering Fix — Remove Systemd Dependency Cycle"
status: ✅ Ready for Implementation
created: "2026-05-05"
updated: "2026-05-05"
owner: pch-planner
version: v1.0
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-05 | pch-planner | Initial plan creation |
| v1.0.1 | 2026-05-05 | pch-plan-reviewer | Reviewed — no corrections needed; added review summary |

## Introduction

After reboot the Jetson, `mower-weston.service` and `mower-kiosk.service` fail to auto-start due to a systemd ordering cycle. The `After=multi-user.target` directive on weston conflicts with `WantedBy=multi-user.target` + kiosk's `After=mower-weston.service`, causing systemd to silently break the ordering and never enqueue weston in the boot transaction. The fix replaces `After=multi-user.target` with `After=seatd.service` + `Requires=seatd.service`.

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 0  
**Last Updated:** 2026-05-05

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| — | No issues requiring user input | — | — | — |

## Holistic Review

**Decision interactions:** This is a single-concern fix with no cross-cutting decisions. The only interaction is with Plan 020 (weston cold-boot EGL fix) which previously modified the same template — this plan builds directly on that state.

**Architectural considerations:** Replacing `After=multi-user.target` with `After=seatd.service` is semantically correct because weston's only real boot dependency is seatd (for DRM master access). The `/dev/dri/card0` poll in `ExecStartPre` remains as a safety net for slow DRM probe. No other services in the stack depend on weston starting relative to `multi-user.target`.

**Trade-offs:** None — this is strictly a bug fix with no alternative approaches.

**Risks acknowledged:** If `seatd.service` were ever removed from the system, weston would fail to start. This is mitigated by `Requires=seatd.service` which makes the dependency explicit and ensures seatd is pulled in.

## Overview

**Feature:** Fix systemd boot ordering so weston and kiosk services start automatically on reboot without manual `systemctl start`.

**Objectives:**
1. Remove the dependency cycle by replacing `After=multi-user.target` with `After=seatd.service`
2. Add `Requires=seatd.service` to ensure seatd is pulled in
3. Optionally truncate stale weston log on service start
4. Update any tests that assert on the `After=` line
5. Deploy via bringup `--from-step kiosk-services` and verify on reboot

**Research basis:** [docs/research/024-kiosk-boot-ordering-failure.md](../research/024-kiosk-boot-ordering-failure.md)

## Requirements

### Functional

- FR-1: `mower-weston.service` starts within 10 seconds of `seatd.service` being active on boot
- FR-2: `mower-kiosk.service` starts within 5 seconds of `mower-weston.service` being active
- FR-3: No systemd ordering cycle warnings in journal
- FR-4: `WantedBy=multi-user.target` is preserved (services are still pulled into boot)

### Non-Functional

- NFR-1: No runtime behaviour change — services behave identically once started
- NFR-2: All existing unit tests pass with updated assertions

### Out of Scope

- Weston runtime issues (none observed)
- Log rotation strategy (secondary, optional enhancement only)

## Technical Design

### Current State

```ini
[Unit]
Description=Weston kiosk compositor for mower display
After=multi-user.target systemd-modules-load.service
StartLimitIntervalSec=120
StartLimitBurst=30
```

### Target State

```ini
[Unit]
Description=Weston kiosk compositor for mower display
After=seatd.service systemd-modules-load.service
Requires=seatd.service
StartLimitIntervalSec=120
StartLimitBurst=30
```

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Unit Template Strings
    location: "src/mower_rover/service/unit.py"
    usage: _WESTON_UNIT_TEMPLATE is the single source of truth for the Weston systemd unit
  - pattern: Unit Generation Tests
    location: "tests/test_kiosk_units.py"
    usage: TestGenerateWestonUnit class validates template output
  - pattern: Bringup Deployment
    location: "src/mower_rover/bringup/"
    usage: "kiosk-services" step deploys the updated unit file to Jetson
```

### Data Contracts

No data entities in scope — data contracts not applicable.

## Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Research 024 complete | ✅ | Root cause confirmed |
| `seatd.service` on Jetson | ✅ | Active since boot (21:04:57 in research) |
| Plan 020 (weston cold-boot EGL fix) | ✅ Complete | Template was modified in that plan; this builds on top |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| seatd not available at boot | Very Low | Weston won't start | `Requires=` ensures seatd is started; it's a core system service |
| Other services depend on weston ordering vs multi-user.target | Very Low | None | Kiosk uses explicit `After=mower-weston.service`; no other service references weston's boot position |

## Execution Plan

### Phase 1: Fix Unit Template and Tests

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** None
**Entry Point:** `src/mower_rover/service/unit.py`
**Verification:** `pytest tests/test_kiosk_units.py` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | In `_WESTON_UNIT_TEMPLATE` (~line 409), change `After=multi-user.target systemd-modules-load.service` to `After=seatd.service systemd-modules-load.service` | `src/mower_rover/service/unit.py` | ✅ Complete |
| 1.2 | Add `Requires=seatd.service` line immediately after the new `After=` line (before `StartLimitIntervalSec`) | `src/mower_rover/service/unit.py` | ✅ Complete |
| 1.3 | Add a test `test_after_seatd` to `TestGenerateWestonUnit` that asserts `After=seatd.service systemd-modules-load.service` is in the output | `tests/test_kiosk_units.py` | ✅ Complete |
| 1.4 | Add a test `test_requires_seatd` to `TestGenerateWestonUnit` that asserts `Requires=seatd.service` is in the output | `tests/test_kiosk_units.py` | ✅ Complete |
| 1.5 | Add a test `test_no_after_multi_user_target` to `TestGenerateWestonUnit` that asserts `After=multi-user.target` is NOT in the output | `tests/test_kiosk_units.py` | ✅ Complete |
| 1.6 | Run full test suite: `pytest tests/ -k "not sitl and not field" --tb=short` | — | ✅ Complete — 816 passed |

### Phase 2: Deploy and Validate

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 0 (deployment only)
**Prerequisites:** Phase 1 complete, Jetson powered on and reachable
**Entry Point:** Terminal
**Verification:** After reboot, both services active without manual intervention

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Deploy via `mower jetson bringup --from-step kiosk-services --yes --host 192.168.4.38 --user vincent` | — | Bringup completes successfully |
| 2.2 | Reboot Jetson: `ssh vincent@192.168.4.38 "sudo reboot"` | — | System reboots |
| 2.3 | After reboot, verify: `systemctl is-active mower-weston.service` returns `active` | — | Output is `active` |
| 2.4 | Verify: `systemctl is-active mower-kiosk.service` returns `active` | — | Output is `active` |
| 2.5 | Verify no ordering cycle: `journalctl -b --grep="ordering cycle"` returns nothing | — | No cycle warnings |

## Standards

No organizational standards applicable to this plan.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-05 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-05 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/021-kiosk-boot-ordering-fix.md |

## Review Summary

**Review Date:** 2026-05-05
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v1.0
**Reviewed Plan Version:** v1.0.1

### Review Metrics
- Issues Found: 2 (Critical: 0, Major: 0, Minor: 2)
- Clarifying Questions Asked: 0
- Sections Updated: Handoff, Review Session Log, Review Summary added

### Key Improvements Made
1. No corrections needed — plan accurately references codebase state
2. Verified all file paths, line numbers, and pattern claims against live code

### Remaining Considerations
- The existing `test_multi_user_target` test in `TestGenerateWestonUnit` only asserts `WantedBy=multi-user.target` (not `After=`), so it won't break. The plan's new `test_no_after_multi_user_target` guards against regression on the `After=` line.
- Phase 2 (deploy + reboot validation) requires the Jetson to be powered on and reachable.

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 1 | 2 files (unit.py, test_kiosk_units.py) |
| New patterns introduced | 1 | None — follows existing template/test patterns |
| External dependencies | 1 | seatd (already present on Jetson) |
| Migration complexity | 1 | Fully reversible, no data |
| Test coverage required | 1 | 3 new unit tests |
| **Overall Complexity** | 5/25 | Low |

### Sign-off
This plan has been reviewed and is **Ready for Implementation**
