---
id: "014"
type: plan
title: "OAK-D Bootstrap Detection Fix — Service-Enable, Runtime-Dir, and Probe Diagnostics"
status: ✅ Complete
created: "2026-05-02"
updated: "2026-05-02"
completed: "2026-05-02"
owner: pch-coder
version: v2.6
---

## Introduction

Implements the 14-item remediation list from research [016-oakd-bootstrap-detection-failure.md](../research/016-oakd-bootstrap-detection-failure.md). Restores end-to-end `mower jetson bringup` functionality on the post-2026-05-02 reflashed Jetson AGX Orin so the OAK-D Pro reaches its expected steady state (PID `03e7:f63b`, USB 3.x SuperSpeed, persistent `Device()` holder running) without manual intervention. Also closes 8 probe-stack diagnostic gaps so the next failure is operator-visible without reading dmesg.

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-02 | pch-planner | Initial skeleton from research 016 |
| v1.1 | 2026-05-02 | pch-planner | Decisions 1–7 logged; Q&A complete |
| v2.0 | 2026-05-02 | pch-planner | Holistic review, requirements, technical design, risks, 5 execution phases |
| v2.1 | 2026-05-02 | pch-plan-reviewer | Review Q1 resolved: explicit `sudo` from bringup + `--target-user` flag |
| v2.2 | 2026-05-02 | pch-plan-reviewer | Review Q2 resolved: single `oakd` check, rewritten in place |
| v2.3 | 2026-05-02 | pch-plan-reviewer | Review Q3 resolved: `_DEFERRED_CHECKS`/`_HW_DEPENDENT` promoted to module-level frozensets |
| v2.4 | 2026-05-02 | pch-plan-reviewer | Review Q4 resolved: cleanup separated from install; user-level test coverage explicit |
| v2.5 | 2026-05-02 | pch-plan-reviewer | Review Q5 resolved: manual rollback runbook in Phase 5 |
| v2.6 | 2026-05-02 | pch-plan-reviewer | Review Q6 resolved: `waveshare_hub` WARNING with explicit deviation note; complexity assessment, follow-ups, review summary added; status → Ready for Implementation |

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 6
**Last Updated:** 2026-05-02

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | `sudo` install + UID mismatch (C1, C2, M1): how to resolve target user and orchestrate elevation | correctness | **B** — Bringup invokes `sudo … install --target-user <user> --target-home <home>`; CLI install commands gain `--target-user`/`--target-home` flags defaulting to `getpass.getuser()` / `Path.home()`. Cleanup of stale user-level units runs as a separate non-elevated bringup sub-step *before* the sudo install (or via `sudo -u $TARGET_USER`). | Phase 1 steps updated; new step 1.2a (cleanup sub-step) and step 1.5 (target-user flags) |
| 2 | `oakd` vs `oakd_pid_state` naming | clarity | **B** — Single check, keep name `oakd`. Rewrite in place per Q6 state machine. All FR-4 / Phase 3 / new-test-file references corrected to `oakd`. Test file renamed `tests/test_oakd_state_machine.py`. | FR-4, Phase 2 step 2.7, Phase 3 steps 3.1/3.2, File Edit Inventory updated |
| 3 | `_DEFERRED_CHECKS` / `_HW_DEPENDENT` module-level promotion | clarity | **A** — Promote both to module-level `frozenset[str]` constants near `STEP_NAMES`. Both `_run_verify` and `_run_final_verify` reference the module-level constants. Phase 3 step 3.4 tests import them directly. | Phase 3 step 3.0 added (promotion); steps 3.1/3.2 reference module-level constants; 3.4 tests import directly |
| 4 | User-level test path preservation (M4) | completeness | **A** — `_cleanup_user_unit` lives only on the new `service cleanup-user-units` CLI subcommand. Install functions never call it. Bringup orchestrates `cleanup → install`. Dedicated user-level install test asserts file-on-disk + `--user enable`, never invokes cleanup. | Phase 1 step 1.2 clarified (helper not called from install); 1.3 / 1.4 simplified (no cleanup wiring); 1.7 acceptance criteria explicit |
| 5 | Rollback runbook for system-level migration (M5) | completeness | **A** — Documented manual rollback procedure only (no new CLI subcommand). New Phase 5 step 5.1a documents the stop/disable/rm sequence + `service_user_level: true` config edit + `mower jetson bringup --from-step service` re-run. | Phase 5 step 5.1a added |
| 6 | `waveshare_hub` severity deviation from research R-7 (Mn2) | correctness | **A** — Keep WARNING with explicit deviation note in the Probe Check Additions table. `oakd` (CRITICAL) already gates VSLAM operability; `waveshare_hub` provides discriminating diagnostic detail. | Probe Check Additions table updated with deviation rationale |
| 3 | `_DEFERRED_CHECKS`/`_HW_DEPENDENT` module-level promotion | clarity | ⏳ pending | — |
| 4 | User-level test path preservation (M4) | completeness | ⏳ pending | — |
| 5 | Rollback runbook (M5) | completeness | ⏳ pending | — |
| 6 | `waveshare_hub` severity deviation from research (Mn2) | correctness | ⏳ pending | — |

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Scope & phasing | D — Full remediation (R-1..R-14) + automated `--check-db` bringup step | Operator wants the comprehensive fix in one plan, including automation of corrupt-DB detection so manual `rm ~/.ros/rtabmap.db` never gates a re-bringup. |
| 2 | `/run/mower/` creation mechanism (R-2) | C — Promote VSLAM (and bridge) to system-level systemd units | Eliminates the `/run/user/1000/` vs `/run/` mismatch at the source. `RuntimeDirectory=mower` in a system unit natively creates `/run/mower/` with correct ownership. The C++ binary's hardcoded `/run/mower/vslam-pose.sock` path is a tell that system-level was always the intent. Larger blast radius accepted in exchange for architectural correctness. |
| 3 | Service-install API change surface | A — Hard-flip default to system-level; retain `--user` flag for tests/dev | Flip `JetsonConfig.service_user_level` default from `True` to `False`; cascade through existing `user_level` plumbing in `service/unit.py` and CLI. Step 18 invokes install over `sudo`. Tests that exercise `user_level=True` keep working. Step 3 (`enable-linger`) stays — cheap and harmless. |
| 4 | Corrupt-DB detection (Phase 4) | D — `sqlite3 PRAGMA integrity_check` + size sanity, quarantine on failure | Zero new dependencies (sqlite3 in Ubuntu base). Sub-second probe over SSH catches Memory.cpp:3443-class corruption and 0-byte files. Quarantine = rename to `~/.ros/rtabmap.db.corrupt-{ts}`, never delete; preserves operator forensics. |
| 5 | Migration of stale user-level units on live Jetson | A — Auto-cleanup in install functions (stop + disable + rm + daemon-reload) | Self-healing migration; ~6 lines per install function; idempotent (CalledProcessError swallowed). Avoids dual-unit footgun where user + system units fight over `/run/mower/vslam-pose.sock`. Fresh flashes never touch the cleanup path. |
| 6 | PID-aware OAK-D probe semantics (R-4) | B — Service-aware cross-reference, no DepthAI fallback in production | Once VSLAM is a system service, the DepthAI fallback competes for the device. Probe checks `is-active mower-vslam` first, then sysfs `idProduct`/`speed`. State table: active+f63b→PASS, active+2485→WARN crash-loop, active+absent→FAIL, inactive+2485→PASS idle, inactive+absent→WARN. Eliminates probe-induced cycling. |
| 7 | Test coverage strategy | B — Unit tests + sysroot fixtures (`tests/fixtures/oakd_sysroot/{2485,f63b,absent}`) | Probe stack already takes `sysroot: Path` to enable filesystem fixtures. Hermetic, runs in CI on Win+Linux, no live-hardware dep. Field validation continues via operator's pre-merge bringup runs. |

## Holistic Review

### Decision interactions

- **Q2 (system-level units) + Q3 (hard-flip default) + Q5 (auto-cleanup)** form one coherent migration: the `JetsonConfig.service_user_level` default flips to `False`, all install functions now write to `/etc/systemd/system/` and call `systemctl enable`, and they pre-emptively stop+disable+remove any user-level units they find. This fixes R-1 and R-2 simultaneously — system units get `RuntimeDirectory=mower` working natively, and `enable` is no longer optional.
- **Q6 (service-aware probe) + Q2 (system service)** are mutually reinforcing: the probe consults `is-active mower-vslam.service`, which is now a system unit queryable without `--user`. The previous DepthAI fallback (which booted then dropped the camera) is removed because the steady-state `Device()` holder is the running service.
- **Q4 (DB integrity) + Phase ordering**: the new `vslam-db-check` step must run **before** `vslam-services` (step 18) so the corrupt-DB quarantine happens before systemd attempts to start the service. New step inserted at position 17.5 (between `service` and `vslam-services`).
- **Q3 (`sudo`-elevated install) + Step 18 invocation**: bringup's `_run_vslam_services()` currently calls `~/.local/bin/mower-jetson vslam install --yes`. With system-level default, it must call `sudo ~/.local/bin/mower-jetson vslam install --yes` (or rely on the install function detecting effective UID and self-elevating). Plan: explicit `sudo` in the bringup invocation; the CLI command itself does not self-elevate (follows existing pattern).

### Trade-offs accepted

- **Linger no longer required for production VSLAM** but step 3 (`enable-linger`) is retained — it's idempotent, harmless, and supports any future user-level service.
- **`sudo` on the Jetson during install** — already used by other bringup steps (`pixhawk-udev`, `vslam-config`), so no new auth pattern.
- **Probe `is-active` SSH round-trip per check** adds ~50 ms per probe invocation. Acceptable; checks are not on a hot path.
- **Auto-cleanup of user units** is silent on success. We log a structured event when cleanup actually deletes something, so the migration is auditable in the JSON log.

### Risks acknowledged

- A future operator who manually installs user-level units (e.g., for testing) will have them silently removed on the next bringup. Mitigation: log the deletion at INFO level with the unit path; document in operator runbook.
- The system-level VSLAM unit reads `/etc/mower/vslam.yaml` as user `vincent` (per `User=vincent` in unit). File ownership/permissions on `/etc/mower/` already set by step 12 (`pixhawk-udev`). No change needed.
- `systemctl --user` invocations from the legacy CLI path (with `--user-level` explicit override) still work for tests and dev.

## Overview

**Problem (root cause):** The bringup orchestrator's step 18 (`vslam-services`) installs `mower-vslam.service`, `mower-vslam-bridge.service`, and `mower-health.service` and starts them — but never `enable`s them. After the step-19 reboot, no `default.target.wants/` symlinks exist → services don't auto-start → no persistent process holds `dai::Device` open → OAK-D firmware (RAM-volatile) is never uploaded → camera stays in bootloader (PID `2485`, USB 2.0) → probe reports failure.

**Second blocker:** `RuntimeDirectory=mower` in the user-level VSLAM unit creates `/run/user/1000/mower/`, but the C++ binary hardcodes `/run/mower/vslam-pose.sock`. Service crash-loops on `bind(): No such file or directory` until `/run/mower/` is manually created.

**Third (orthogonal):** Corrupt `~/.ros/rtabmap.db` triggers `Memory.cpp:3443` assertion, amplifying the cycling pattern.

**Hardware/kernel/udev/hub: confirmed healthy.** USB 3.0 SuperSpeed transiently negotiates to 5 Gbps during the bringup probe (dmesg-confirmed). The fix is entirely in software.

**Outcome:** After this plan lands, a fresh `mower jetson bringup` produces a Jetson where `mower-vslam.service` is `enabled` + `active` (system-level), the OAK-D is at `idProduct=f63b` / `speed=5000` continuously, the probe distinguishes ≥7 OAK-D / hub / kernel-param failure modes by name, and a corrupt RTAB-Map DB is detected and quarantined automatically before VSLAM starts.

## Requirements

### Functional Requirements

- **FR-1**: `mower jetson bringup` against a freshly reflashed Jetson produces a system where, 60 s after the final reboot, `systemctl status mower-vslam.service` reports `enabled` + `active (running)` without manual intervention.
- **FR-2**: 60 s after final reboot, OAK-D sysfs reports `idProduct=f63b` and `speed=5000` continuously (no transient drops to 2485 except during legitimate service restarts).
- **FR-3**: `mower jetson bringup` re-run on a Jetson with stale user-level units in `~/.config/systemd/user/` cleanly transitions to system-level units without operator action; cleanup is logged.
- **FR-4**: `mower-jetson probe --json` distinguishes the following OAK-D / hub / kernel-param states by check name and detail message: bootloader-idle (service stopped), booted-active, bootloader-with-active-service (crash-loop), camera absent, hub absent, kernel quirk missing, udev rule missing. The OAK-D state machine is implemented inside the existing `oakd` check (rewritten in place; no new check name registered).
- **FR-5**: A new bringup step `vslam-db-check` (inserted between `service` and `vslam-services`) runs `sqlite3 ~/.ros/rtabmap.db 'PRAGMA integrity_check'` and a size-sanity check; on failure the DB is renamed to `~/.ros/rtabmap.db.corrupt-{ISO8601}` and a structured warning is logged. Bringup continues (RTAB-Map will create a fresh DB on first run).
- **FR-6**: After the final-verify reboot, the orchestrator waits at least 30 s before its first probe poll, eliminating the false-negative race against still-starting VSLAM service.
- **FR-7**: `mower-jetson service install`, `vslam install`, and `vslam bridge-install` default to **system-level** install (`/etc/systemd/system/`); `--user-level` flag remains for tests/dev.
- **FR-8**: All three install functions call `systemctl enable {unit}` after writing the unit file.
- **FR-9**: Probe checks `oakd_usb_autosuspend` and `oakd_usbfs_memory` no longer depend on `oakd` and run independently (kernel params are checkable without the camera being present).
- **FR-10**: New probe checks: `usbcore_quirks` (R-6), `waveshare_hub` (R-7), `oakd_udev_rule` (R-8). (R-4 is a rewrite of the existing `oakd` check, not a new registration.)
- **FR-11**: Probe `oakd` (or its replacement) does **not** invoke `dai.Device()` when `mower-vslam.service` is active.
- **FR-12**: `_DEFERRED_CHECKS` and `_HW_DEPENDENT` sets in `bringup.py` include the new check names plus the existing `oakd` check, so a missing camera or hub yields a `Deferred`/`hardware-dependent` warning rather than a blocking failure.

### Non-Functional Requirements

- **NFR-1**: Cross-platform plumbing intact — all laptop-side code runs on Windows; Jetson-side code on aarch64 Linux. Path handling uses `pathlib`; subprocess uses `shell=False`-equivalent argument lists.
- **NFR-2**: Field-offline by default (NFR-2 from copilot-instructions). No new internet dependencies.
- **NFR-3**: Structured logging at INFO for every install/uninstall/migrate/quarantine action with correlation IDs.
- **NFR-4**: All actuator-touching paths (none in this plan, but services restart-affecting) follow the existing `@requires_confirmation` + `--dry-run` pattern.
- **NFR-5**: New tests run under existing CI matrix without flake. No live-Jetson dependency in unit tests.
- **NFR-6**: All edits idempotent: re-running bringup on a fully-converged Jetson produces zero state changes.

### Out of Scope

- Modifying ArduPilot firmware, kernel quirks, udev rules content, or `jetson-harden.sh` USB-param ordering (all confirmed correct).
- Replacing DepthAI v3 firmware-volatile architecture.
- Building a non-Jetson sysroot/stub for the probe stack beyond test fixtures.
- Promoting `mower-health.service` migration to system-level is **in scope** for symmetry (Q3) but its functional behaviour does not depend on `/run/mower/`.
- Adding a `--check-db` mode to `rtabmap_slam_node.cpp` (Phase 4 uses external `sqlite3`).
- Suppressing `mtp-probe` udev events on `03e7:*` (Phase 1 noted; harmless, deferred).
- Live-Jetson E2E pytest target (operator runs bringup manually pre-merge).

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: "Probe check registration"
    location: "src/mower_rover/probe/checks/*.py + registry.py"
    usage: "New checks use @register(name, severity, depends_on=...)"
  - pattern: "Systemd unit install via _systemctl()"
    location: "src/mower_rover/service/unit.py"
    usage: "All install_* functions call _systemctl(['daemon-reload'], user_level=...)"
  - pattern: "Idempotent harden_* functions"
    location: "scripts/jetson-harden.sh"
    usage: "Each function checks-before-write and sets STATUS[...]"
  - pattern: "Bringup step deferred-check sets"
    location: "src/mower_rover/cli/bringup.py — _DEFERRED_CHECKS, _HW_DEPENDENT"
    usage: "Step 15 verify and step 19 final-verify partition critical fails"
```

### Architecture Changes

**1. Service tier flip (Q2/Q3).** `JetsonConfig.service_user_level` default changes from `True` → `False` (`src/mower_rover/config/jetson.py:46`). All callers in `cli/jetson.py` (lines ~472, 493, 514, 533) continue to honor explicit `--user-level/--system-level` overrides. Production install paths now write to `/etc/systemd/system/`.

**2. Install function changes (`src/mower_rover/service/unit.py`).** Each of `install_service`, `install_vslam_service`, `install_vslam_bridge_service` gains:
   1. **Pre-install user-unit cleanup** (`_cleanup_user_unit(unit_name)`): `systemctl --user stop`, `disable`, `rm ~/.config/systemd/user/{unit}.service`, `systemctl --user daemon-reload`. All errors swallowed (idempotent migration). Logs INFO event when a deletion actually occurred.
   2. **`systemctl enable` after `daemon-reload`**: `_systemctl(["enable", f"{unit_name}.service"], user_level=user_level)`.

**3. New step 17.5 `vslam-db-check` (Phase 4).** Inserted into `BRINGUP_STEPS` between `service` and `vslam-services`. Runs over SSH:
   - `test -f ~/.ros/rtabmap.db` — if absent, PASS (fresh install).
   - `stat -c %s ~/.ros/rtabmap.db` — must be > 0 and < 10737418240 (10 GiB).
   - `sqlite3 ~/.ros/rtabmap.db 'PRAGMA integrity_check;'` — stdout must be `ok`.
   - On failure: `mv ~/.ros/rtabmap.db ~/.ros/rtabmap.db.corrupt-$(date -u +%Y%m%dT%H%M%SZ)`; log structured WARN; continue bringup.

**4. Step 18 (`_run_vslam_services`) `sudo` invocation.** Change `~/.local/bin/mower-jetson vslam install --yes` to `sudo ~/.local/bin/mower-jetson vslam install --yes` (and likewise for `bridge-install`). The trailing `systemctl --user start ...` becomes `sudo systemctl start mower-vslam.service mower-vslam-bridge.service`. Add post-install `is-enabled` verification (R-10/R-12).

**5. Probe-stack additions (`src/mower_rover/probe/checks/`):**
   - `oakd.py` — `check_oakd` rewritten per state table (Q6): SSH `is-active mower-vslam` → sysfs PID + speed cross-reference → PASS/WARN/FAIL with PID-discriminating message. `_depthai_usb_speed()` removed from production path; retained only behind `if not _vslam_service_active(): ...` guard for sysroot-mocked dev.
   - `usb_tuning.py` — `oakd_usb_autosuspend` and `oakd_usbfs_memory` change `depends_on=("oakd",)` → `depends_on=("jetpack_version",)` (R-9). New checks `usbcore_quirks` (R-6), `waveshare_hub` (R-7), `oakd_udev_rule` (R-8).

**6. Bringup orchestrator (`src/mower_rover/cli/bringup.py`):**
   - `STEP_NAMES` and `BRINGUP_STEPS` gain `vslam-db-check` between positions 16 (`service`) and 17 (`vslam-services`). New step count: 20.
   - `_DEFERRED_CHECKS` (line ~987) adds `oakd`, `oakd_pid_state`, `usbcore_quirks`, `waveshare_hub`, `oakd_udev_rule`, `oakd_usb_autosuspend`, `oakd_usbfs_memory`.
   - `_HW_DEPENDENT` (line ~1347) adds `oakd`, `oakd_pid_state`, `waveshare_hub`.
   - `_run_final_verify()` adds `time.sleep(30)` after SSH-up confirmation, before first probe poll.
   - `_vslam_services_active()` checks both `is-active` AND `is-enabled` (returns False if either fails) so step 18 re-runs when re-enable is needed.

### Data Contracts

No data entities in scope — data contracts not applicable.

### Probe Check Additions / Modifications

| Check Name | Status | Severity | Depends On | Behaviour |
|------------|--------|----------|------------|-----------|
| `oakd` | **modified** | CRITICAL | `jetpack_version` | Service-aware PID + speed state machine (Q6 table). Removes `_depthai_usb_speed()` production fallback. |
| `oakd_usb_autosuspend` | **modified** | WARNING | `jetpack_version` (was `oakd`) | Decoupled per R-9. |
| `oakd_usbfs_memory` | **modified** | WARNING | `jetpack_version` (was `oakd`) | Decoupled per R-9. |
| `usbcore_quirks` | **new** (R-6) | WARNING | `jetpack_version` | Reads `/sys/module/usbcore/parameters/quirks`, asserts `03e7:2485:gk` and `03e7:f63b:gk` both present. |
| `waveshare_hub` | **new** (R-7) | WARNING | `jetpack_version` | Scans sysfs for `2109:0817` AND `2109:2817`. Both / one / neither yield distinct messages. **Deviation from research R-7** (which specifies CRITICAL): kept WARNING because the `oakd` check (CRITICAL) already gates VSLAM operability — a missing hub manifests as a missing camera and emits a CRITICAL `oakd` failure; `waveshare_hub` provides discriminating diagnostic detail without doubling the CRITICAL count for one root cause. |
| `oakd_udev_rule` | **new** (R-8) | WARNING | `jetpack_version` | Asserts `/etc/udev/rules.d/80-oakd-usb.rules` exists and contains `03e7`. |

---

_Note: `waveshare_hub` severity is WARNING (not CRITICAL as research R-7 specifies) for the reasons documented in the table above. The other new checks are WARNING because they are diagnostic; the `oakd` check itself stays CRITICAL and remains the gate for VSLAM operability._

### Implementation Notes for Coder

- **Line-number references throughout this plan (e.g., `bringup.py#L987`) will shift after Phase 1's edits land.** Re-locate edit targets by symbol name (`_DEFERRED_CHECKS`, `_HW_DEPENDENT`, `_run_vslam_services`, `_vslam_services_active`, `_run_final_verify`, `install_service`, `install_vslam_service`, `install_vslam_bridge_service`) rather than line numbers as work progresses.
- All probe-check additions are registered via `@register(name, severity, depends_on=...)` — no manual registry edits needed.
- `frozenset` literals in Python 3.11+: write `frozenset({"a", "b"})` (no `frozenset({...})` -typed annotation needed for module-level constants when right-hand side is unambiguous).

### Follow-ups (deferred, not in this plan)

- Suppress `mtp-probe` udev events on `03e7:*` (research 016 noted; harmless, low priority).
- Future: automated re-test of the rollback runbook as part of CI (currently exercised only by user-level install unit tests).
- Future: a periodic operator script to prune `~/.ros/rtabmap.db.corrupt-*` files older than 30 days (FR-5 quarantine accumulation — minor risk per R9).

### Service Unit Changes

| Unit | Tier (before) | Tier (after) | Path | New behaviour |
|------|---------------|--------------|------|---------------|
| `mower-health.service` | user | **system** | `/etc/systemd/system/` | `enable` + auto-cleanup of stale user unit |
| `mower-vslam.service` | user | **system** | `/etc/systemd/system/` | `enable` + native `/run/mower/` via `RuntimeDirectory=mower` + auto-cleanup |
| `mower-vslam-bridge.service` | user | **system** | `/etc/systemd/system/` | `enable` + auto-cleanup |

Unit file content changes:
- `WantedBy=default.target` → `WantedBy=multi-user.target` (already present in `_GENERIC_SYSTEM_TEMPLATE` at `unit.py:50`).
- `User={user}` line is rendered for system units (already present in `_GENERIC_SYSTEM_TEMPLATE` line 41).
- `RuntimeDirectory=mower` now correctly creates `/run/mower/` owned by `User=` (no `tmpfiles.d` required).

### File Edit Inventory

| File | Change Type | Items |
|------|-------------|-------|
| `src/mower_rover/config/jetson.py` | modify | Default `service_user_level: bool = False` |
| `src/mower_rover/service/unit.py` | modify | `_cleanup_user_unit()` helper; `enable` calls in 3 install fns |
| `src/mower_rover/probe/checks/oakd.py` | rewrite | Service-aware state machine; remove production DepthAI fallback |
| `src/mower_rover/probe/checks/usb_tuning.py` | modify + add | Decouple deps; add 3 new checks |
| `src/mower_rover/cli/bringup.py` | modify | New step 17.5; deferred/HW sets; final-verify 30 s wait; `sudo` invocations |
| `tests/fixtures/oakd_sysroot/` | create | 3 sysroot trees: `2485-bootloader/`, `f63b-booted/`, `absent/` |
| `tests/test_service.py` (existing) | extend | New cases for `enable` + cleanup |
| `tests/test_probe.py` (existing) | extend | Parametrize new checks over fixture trees |
| `tests/test_bringup.py` (existing) | extend | New step ordering + final-verify wait |
| `tests/test_oakd_state_machine.py` | create | 5-state matrix per Q6 (targets the rewritten `oakd` check) |
| `tests/test_db_integrity.py` | create | Quarantine + integrity-check coverage |
| `README.md` | modify | Operator notes (linger no longer required for VSLAM; system-level units) |

## Dependencies

- Research 016 complete (✅).
- Jetson at `192.168.4.38` reachable, hardware in current state per `/memories/repo/hardware-state.md`.
- No upstream blocker; all changes self-contained in this repo.

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|-----------|
| R1 | `sudo` over SSH fails (no NOPASSWD) for `vincent` on the Jetson | Low | Bringup step 18 fails | Verified in current bringup pipeline — step 12 (`pixhawk-udev`) already uses `sudo` successfully; same auth path. If it ever fails, error message names the missing privilege. |
| R2 | Auto-cleanup of user units accidentally deletes a unit an operator hand-installed for testing | Low | Operator's test setup wiped | Cleanup logs INFO with full unit path; documented in operator runbook; only triggers on units named exactly `mower-health`, `mower-vslam`, `mower-vslam-bridge`. |
| R3 | System unit's `User=vincent` mismatches actual SSH user on a future deploy | Low | Service fails to start | Unit generation reads `getpass.getuser()` at install time on the Jetson (existing pattern); matches whichever user runs the install. |
| R4 | `sqlite3` not installed on Jetson | Very Low | DB-check step fails | `sqlite3` is in `apt` base on Ubuntu 22.04 (JetPack 6); add to install-build-deps step as belt-and-suspenders. |
| R5 | `PRAGMA integrity_check` returns `ok` on a DB that RTAB-Map still rejects | Medium | False-negative; service still crash-loops | Acceptable — the new `oakd` probe state `active+2485 → WARN crash-loop` will surface this within one probe cycle, naming the exact `journalctl` command to run. |
| R6 | The 30 s post-reboot wait (FR-6) lengthens bringup wall-clock | Certain | +30 s | Acceptable; existing final-verify already waits 180 s for SSH and polls for 120 s. The 30 s is inside the existing 120 s budget. |
| R7 | `_HW_DEPENDENT` set adds `oakd` — a real camera failure now yields WARN instead of FAIL at final-verify | Medium | Operator could miss a genuine OAK-D regression | The `oakd_pid_state` probe always runs and surfaces the discriminating detail (active+absent→FAIL state). Final-verify still prints the table and the warning is loud. |
| R8 | New `usbcore_quirks` probe false-positive on a future kernel where quirks are merged differently | Low | Spurious WARN | Probe regex matches both PIDs explicitly; future kernel changes would already break the camera, so the warning is desired. |
| R9 | Stale rtabmap.db quarantine fills disk over many runs | Very Low | Disk pressure | Filename includes ISO8601 timestamp; operator runbook notes periodic cleanup. Files are typically <100 MB each on this rig. |
| R10 | Migration from user-level units leaves `~/.config/systemd/user/default.target.wants/` symlinks dangling | Low | Cosmetic in `systemctl --user list-units` | `systemctl --user disable` removes the WantedBy symlink before the unit file is deleted. |

## Execution Plan

### Phase 1: System-level service migration + enable (P0 hotfix)

**Status:** ✅ Complete
**Completed:** 2026-05-02
**Size:** Medium
**Files to Modify:** 4
**Prerequisites:** Working tree clean; current 599 tests pass.
**Entry Point:** [src/mower_rover/service/unit.py](src/mower_rover/service/unit.py)
**Verification (post-phase):** Re-run bringup against 192.168.4.38; `ssh vincent@192.168.4.38 'systemctl is-enabled mower-vslam.service'` returns `enabled`; `systemctl is-active mower-vslam.service` returns `active`; `ls /run/mower/vslam-pose.sock` exists.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Flip `JetsonConfig.service_user_level` default `True` → `False` | [src/mower_rover/config/jetson.py](src/mower_rover/config/jetson.py#L46) | Default value is `False`; YAML round-trip test still passes; existing tests that pass `service_user_level: true` explicitly continue working. |
| 1.2 | Add `_cleanup_user_unit(unit_name: str)` helper in `service/unit.py`. **Helper is exposed only via the new `service cleanup-user-units` CLI subcommand (step 1.5a). It is NOT called from any `install_*` function** — install paths are symmetric across user/system tiers and free of side effects on the other tier. | [src/mower_rover/service/unit.py](src/mower_rover/service/unit.py) | Helper runs `systemctl --user stop`, `disable`, `rm -f`, `daemon-reload`; all errors swallowed; logs INFO `user_unit_migrated` event when file deleted; returns bool indicating whether cleanup happened. **Must be invokable as the unprivileged target user** — does not assume root context. No `install_*` function imports or calls this helper. |
| 1.2a | Add `--target-user` and `--target-home` flags to `mower-jetson service install`, `vslam install`, `vslam bridge-install`; default to `getpass.getuser()` / `str(Path.home())`. Plumb through to `install_service`/`install_vslam_service`/`install_vslam_bridge_service` (new kwargs `target_user: str \| None = None`, `target_home: str \| None = None`). When unset, behaviour is unchanged (back-compat for user-level dev/test). | [src/mower_rover/service/unit.py](src/mower_rover/service/unit.py), `src/mower_rover/cli/jetson.py` (or wherever the install Typer commands live) | Unit-template `User=` and `WorkingDirectory=` lines render the resolved target user/home, regardless of effective UID. New unit test: install function called under simulated `sudo` (monkeypatched `getpass.getuser` → `root`) with `target_user="vincent"` produces a unit with `User=vincent`, not `User=root`. |
| 1.3 | Wire `systemctl enable` into `install_service` | [src/mower_rover/service/unit.py](src/mower_rover/service/unit.py) | Call order: write unit → daemon-reload → enable. Idempotent. Unit test mocks `subprocess.run` and asserts enable in call sequence. **No call to `_cleanup_user_unit`.** |
| 1.4 | Same wiring in `install_vslam_service` and `install_vslam_bridge_service` | [src/mower_rover/service/unit.py](src/mower_rover/service/unit.py) | Both functions follow identical pattern. Unit tests mirror 1.3 for both. **No call to `_cleanup_user_unit`.** |
| 1.5 | Update bringup step 18 (`_run_vslam_services`) to invoke install with **explicit `sudo` and `--target-user`/`--target-home` flags** sourced from `client.endpoint.user` and the resolved remote home (`echo $HOME` over a non-elevated SSH call, or hard-derived as `/home/{user}`). Replace `systemctl --user start` with `sudo systemctl start`. | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py#L1223) | All three remote commands invoke `sudo ~/.local/bin/mower-jetson <cmd> --target-user {user} --target-home {home} --yes`. Mocked-client test asserts both `sudo` token and the two flags are present in the command string. |
| 1.5a | New bringup pre-step (or inline at the head of `_run_vslam_services` and `_run_service`): run `_cleanup_user_unit` for each migrating unit as a **non-elevated** SSH command — `~/.local/bin/mower-jetson service cleanup-user-units --unit mower-health --unit mower-vslam --unit mower-vslam-bridge`. Exposes a new CLI subcommand under `service` that calls `_cleanup_user_unit` for each `--unit` arg (idempotent, swallows errors, logs deletions). Runs **before** the `sudo` install so `systemctl --user` operates against the operator's own DBUS session. | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py#L1223), `src/mower_rover/cli/jetson.py` | New subcommand exists and is callable without sudo. Bringup runs cleanup before install. Mocked-client test asserts the cleanup command is issued without `sudo` and *before* the install command. |
| 1.6 | Update `_vslam_services_active()` and `_service_active()` to use system-level `systemctl is-active` (no `--user`), and additionally check `is-enabled` | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py#L1208) | Returns False if either active or enabled is missing. Re-running step 18 after partial state converges. **Audit and migrate every other `systemctl --user` callsite in `bringup.py` and the Jetson CLI** (Critical C1) — every production-path callsite drops `--user`; user-level paths gated behind explicit `service_user_level=True`. |
| 1.6a | Audit `mower-jetson service start`/`stop`/`status` (and `vslam` equivalents) in the Jetson CLI: each command must select `--user` vs system based on `JetsonConfig.service_user_level` (or an explicit `--user-level/--system-level` flag), not unconditionally `--user`. | `src/mower_rover/cli/jetson.py`, any helpers in `src/mower_rover/service/` | `grep -r "systemctl.*--user" src/mower_rover/` returns only test fixtures and back-compat-gated branches. Existing user-level tests still pass. |
| 1.7 | Run full pytest; verify 599+ tests still pass; update any tests that hardcoded `user_level=True` *production* expectations. **Add a dedicated user-level install test** for each of the three install functions: invoke with `user_level=True, target_user="alice", target_home="/home/alice"` (in a tmp_path-rooted fake home), assert (a) the unit file is written to `~/.config/systemd/user/<name>.service`, (b) `systemctl --user enable` is in the mocked subprocess call sequence, (c) `_cleanup_user_unit` is **never** invoked, (d) the unit's `User=` line matches the target user when present in the template. | tests/ | All tests green; user-level path coverage explicitly retained; assertions (a)–(d) above all hold. |

---

### Phase 2: PID-aware OAK-D probe + diagnostic checks (P1)

**Status:** ✅ Complete
**Completed:** 2026-05-02
**Size:** Medium
**Files to Modify:** 4
**Prerequisites:** Phase 1 complete and merged.
**Entry Point:** [src/mower_rover/probe/checks/oakd.py](src/mower_rover/probe/checks/oakd.py)
**Verification:** `ssh vincent@192.168.4.38 'mower-jetson probe --json'` distinguishes the 5 states from the Q6 table; new probes appear in output.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Create `tests/fixtures/oakd_sysroot/{2485-bootloader,f63b-booted,absent}/` | tests/fixtures/oakd_sysroot/ | Three directory trees with `sys/bus/usb/devices/<dev>/{idVendor,idProduct,speed}` files reflecting each state. |
| 2.2 | Rewrite `check_oakd` in `oakd.py` per Q6 state machine; add `_vslam_service_active()` helper that calls `systemctl is-active mower-vslam.service` (system-level) | [src/mower_rover/probe/checks/oakd.py](src/mower_rover/probe/checks/oakd.py#L48) | `check_oakd(sysroot)` accepts optional `_service_active_fn` for injection in tests. Production removes `_depthai_usb_speed()` call from main path. State table per Q6 implemented. |
| 2.3 | Decouple `oakd_usb_autosuspend` and `oakd_usbfs_memory` deps | [src/mower_rover/probe/checks/usb_tuning.py](src/mower_rover/probe/checks/usb_tuning.py#L13) | `depends_on=("jetpack_version",)` for both. Probe registry topo-sort still well-formed. |
| 2.4 | Add new check `usbcore_quirks` in `usb_tuning.py` (R-6) | [src/mower_rover/probe/checks/usb_tuning.py](src/mower_rover/probe/checks/usb_tuning.py) | Reads `/sys/module/usbcore/parameters/quirks`; passes if both `03e7:2485:gk` and `03e7:f63b:gk` present; otherwise WARN with the missing token names. |
| 2.5 | Add new check `waveshare_hub` in `usb_tuning.py` (R-7) | [src/mower_rover/probe/checks/usb_tuning.py](src/mower_rover/probe/checks/usb_tuning.py) | Scans sysfs for `2109:0817` AND `2109:2817`; both/one/neither yield distinct messages. |
| 2.6 | Add new check `oakd_udev_rule` in `usb_tuning.py` (R-8) | [src/mower_rover/probe/checks/usb_tuning.py](src/mower_rover/probe/checks/usb_tuning.py) | Asserts `/etc/udev/rules.d/80-oakd-usb.rules` exists and contains `03e7`. |
| 2.7 | Create `tests/test_oakd_state_machine.py` with parametrized 5-state matrix targeting the rewritten `oakd` check | tests/test_oakd_state_machine.py | All 5 cells of Q6 table covered; uses sysroot fixtures + monkeypatched service-state fn. |
| 2.8 | Extend `tests/test_probe.py` with new check parametrizations | tests/test_probe.py | New checks have positive + negative cases each. |

---

### Phase 3: Bringup orchestrator hardening (P1)

**Status:** ✅ Complete
**Completed:** 2026-05-02
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phase 2 complete.
**Entry Point:** [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py)
**Verification:** Final-verify step yields `Hardware-dependent: oakd` (yellow) when camera unplugged, not red abort. Post-reboot probe poll begins ≥30 s after SSH ready.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.0 | Promote `_DEFERRED_CHECKS` and `_HW_DEPENDENT` from function-local sets to module-level `frozenset[str]` constants near `STEP_NAMES`. Replace function-local declarations in `_run_verify` and `_run_final_verify` with references to the module-level constants. Fixes the redeclaration-per-poll-iteration in the final-verify loop. | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py#L48) | Both constants exist at module scope as `frozenset`s; original function-local declarations removed; `from mower_rover.cli.bringup import _DEFERRED_CHECKS, _HW_DEPENDENT` works in tests; behaviour of `_run_verify`/`_run_final_verify` unchanged. |
| 3.1 | Update module-level `_DEFERRED_CHECKS`: add `oakd`, `usbcore_quirks`, `waveshare_hub`, `oakd_udev_rule`, `oakd_usb_autosuspend`, `oakd_usbfs_memory` | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py) | Constant updated; comment explains rationale. Step 15 verify yields yellow not red when these fail. |
| 3.2 | Update module-level `_HW_DEPENDENT`: add `oakd`, `waveshare_hub` | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py) | Constant updated. Final-verify message includes the new names in hw-fails category. |
| 3.3 | Add `time.sleep(30)` in `_run_final_verify` after SSH-up confirmation, before first probe poll | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py#L1291) | 30 s elapsed; comment cites Phase 4 of research 016 (FW upload + service start budget). |
| 3.4 | Extend `tests/test_bringup.py` with assertions on the new sets and the wait. Tests import `_DEFERRED_CHECKS` and `_HW_DEPENDENT` directly from the module. | tests/test_bringup.py | Tests verify `oakd` is in both sets; mock-time test verifies the 30 s wait. |

---

### Phase 4: Automated DB-integrity check (new bringup step)

**Status:** ✅ Complete
**Completed:** 2026-05-02
**Size:** Small
**Files to Modify:** 3
**Prerequisites:** Phase 1 complete.
**Entry Point:** [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py)
**Verification:** Manually corrupt the Jetson's `~/.ros/rtabmap.db` (write garbage); re-run bringup; observe quarantine rename and continued bringup; service starts cleanly with fresh DB.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | Add `_db_check_done()` and `_run_db_check(client, bctx)` functions | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py) | `_db_check_done` returns `False` always (always runs; cheap). `_run_db_check` runs `test -f`, `stat -c %s`, `sqlite3 PRAGMA integrity_check` over SSH; on failure, runs `mv` to ISO8601-stamped quarantine name. Logs structured WARN. Never raises (continues bringup). |
| 4.2 | Insert step `vslam-db-check` in `STEP_NAMES` and `BRINGUP_STEPS` between `service` and `vslam-services` | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py) | `STEP_NAMES` becomes 20-tuple; module docstring updated to reflect 20 steps; `--step` and `--from-step` accept the new name. |
| 4.3 | Add `sqlite3` to install-build-deps apt package list (belt-and-suspenders) | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py) (`_run_install_build_deps`) | `apt install` line includes `sqlite3`. |
| 4.4 | Create `tests/test_db_integrity.py` | tests/test_db_integrity.py | Cases: (a) DB absent → PASS; (b) DB empty → quarantine; (c) DB > 10 GiB → quarantine; (d) `PRAGMA` returns non-`ok` → quarantine; (e) `PRAGMA` returns `ok` → PASS. Uses mocked `JetsonClient`. |
| 4.5 | Update bringup module docstring step list to 20 steps | [src/mower_rover/cli/bringup.py](src/mower_rover/cli/bringup.py#L3) | Docstring lists steps 1–20 in order. |

---

### Phase 5: Operator runbook + steady-state verification (P2)

**Status:** ✅ Complete
**Completed:** 2026-05-02
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phases 1–4 complete and field-validated against the Jetson.
**Entry Point:** [README.md](README.md)
**Verification:** Operator follows the new runbook section successfully on a fresh flash.

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Add operator-facing "VSLAM service architecture" subsection to README | [README.md](README.md) | Documents: system-level units, where to find unit files, `sudo systemctl status mower-vslam`, journalctl commands, expected steady-state (PID f63b, speed 5000), what `corrupt-{ts}` quarantine files mean, manual cleanup. |
| 5.1a | Add operator-facing "Rolling back to user-level units" subsection to README. Document the manual sequence: (1) `sudo systemctl stop mower-vslam-bridge.service mower-vslam.service mower-health.service`, (2) `sudo systemctl disable …` (same units), (3) `sudo rm /etc/systemd/system/mower-{health,vslam,vslam-bridge}.service`, (4) `sudo systemctl daemon-reload`, (5) on the laptop, set `service_user_level: true` in `~/.config/mower-rover/jetson.yaml` (or its Windows-AppData equivalent), (6) re-run `mower jetson bringup --from-step service`. Note that step 18's cleanup pre-step is a no-op in this direction (no user units exist) and the install path will write to `~/.config/systemd/user/`. | [README.md](README.md) | Section present; sequence is copy-pasteable; mentions that this rollback path is exercised by the user-level install tests in step 1.7. |
| 5.2 | Add R-14 steady-state verification block: `mower-jetson probe --json` 60 s after boot must show `oakd_pid_state=active+f63b`, no service restarts in last 60 s, `/run/mower/vslam-pose.sock` present | [README.md](README.md) | Documented as one-liner shell snippet operator can paste. |
| 5.3 | Update `/memories/repo/hardware-state.md` to reflect system-level unit migration | (memory tool) | "VSLAM Services (Jetson)" block notes both units are now system-level; `/run/mower/` created natively by `RuntimeDirectory`; user-level migration auto-handled. |

### Phase Summary

| Phase | Size | Tasks | Files | Outcome | Status |
|-------|------|-------|-------|---------|--------|
| 1 | M | 7 | 4 | Bringup restored; OAK-D reaches steady-state f63b after reboot | ✅ Complete |
| 2 | M | 8 | 4 + fixtures | Probe diagnostics by name | ✅ Complete |
| 3 | S | 4 | 2 | Race-free final-verify; deferred sets correct | ✅ Complete |
| 4 | S | 5 | 3 | Corrupt-DB self-heals | ✅ Complete |
| 5 | S | 3 | 2 | Operator-facing docs current | ✅ Complete |

### Plan Completion

**All phases completed:** 2026-05-02
**Total tasks completed:** 27 (7 + 8 + 4 + 5 + 3)
**Total files modified/created:** 14 (8 source + 4 test + README + repo memory)
**Test count:** 599 → 659 passed (+60), 15 skipped
**Post-implementation code review:** clean (0 findings)

## Standards

No organizational standards applicable (none queried; offline mode).

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 3 | Production: `config/jetson.py`, `service/unit.py`, `cli/bringup.py`, plus `cli/jetson.py` (CLI flag plumbing); 2 probe files; ~5 test files; 1 README. |
| New patterns introduced | 2 | `--target-user`/`--target-home` flag pattern on install commands; module-level `frozenset` constants for orchestrator deferred sets. Both are localised, not project-wide. |
| External dependencies | 1 | Adds `sqlite3` apt package (already in Ubuntu base). No new Python packages. |
| Migration complexity | 3 | One-way migration of 3 systemd units from user to system tier on existing field installs; mitigated by separate non-elevated cleanup sub-step. Reversible via documented manual rollback (Phase 5 step 5.1a). |
| Test coverage required | 3 | New: sysroot fixtures (3 trees), `test_oakd_state_machine.py`, `test_db_integrity.py`. Extended: `test_service.py`, `test_probe.py`, `test_bringup.py`. Hermetic; no live-Jetson dep. |
| **Overall Complexity** | **12 / 25** | **Medium** (11–17) |

Medium complexity reflects the multi-file blast radius of the service-tier migration and the new CLI flag surface, balanced by hermetic testability and a documented rollback path. No phase breakdown required.

## Review Summary

**Review Date:** 2026-05-02
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.6

### Review Metrics

- Issues Found: 12 (Critical: 2, Major: 5, Minor: 5)
- Clarifying Questions Asked: 6
- Sections Updated: Version History, Review Session Log (new), Functional Requirements (FR-4, FR-10), Technical Design (Probe Check Additions table, Implementation Notes, Follow-ups), Phase 1 (steps 1.2, 1.2a, 1.3, 1.4, 1.5, 1.5a, 1.6, 1.6a, 1.7), Phase 2 (step 2.7), Phase 3 (new step 3.0; steps 3.1, 3.2, 3.4), Phase 5 (new step 5.1a), Implementation Complexity (new), Standards (unchanged).

### Key Improvements Made

1. **Resolved C2 (sudo + UID mismatch):** Install commands gain `--target-user`/`--target-home` flags so the rendered unit's `User=` line is correct under sudo elevation. New step 1.2a plumbs flags through Typer commands and helper functions.
2. **Resolved C1 (incomplete migration):** New step 1.6a mandates a full audit of `systemctl --user` callsites across `bringup.py` and `cli/jetson.py`, with each gated on `service_user_level`.
3. **Resolved M1 (cleanup vs sudo):** `_cleanup_user_unit` is decoupled from `install_*` and runs only via the new `service cleanup-user-units` non-elevated subcommand (steps 1.2 + 1.5a).
4. **Resolved M2 (function-local sets):** Phase 3 step 3.0 promotes `_DEFERRED_CHECKS` and `_HW_DEPENDENT` to module-level `frozenset` constants, fixing the per-iteration redeclaration in `_run_final_verify`.
5. **Resolved M3 (`oakd` naming):** All `oakd_pid_state` references corrected to `oakd`; new test file renamed to `tests/test_oakd_state_machine.py`.
6. **Resolved M4 (user-level test coverage):** Step 1.7 mandates a dedicated user-level install test for each install function with four named assertions.
7. **Resolved M5 (rollback runbook):** Phase 5 step 5.1a documents the manual rollback sequence.
8. **Resolved Mn1 (duplicate Version History):** Consolidated.
9. **Resolved Mn2 (`waveshare_hub` severity):** Plan retains WARNING with explicit deviation note from research R-7.
10. **Resolved Mn4 (line numbers):** Implementation Notes section directs coder to navigate by symbol, not line.
11. **Resolved Mn5 (follow-ups visibility):** Dedicated Follow-ups subsection added.

### Remaining Considerations

- **Mn3 (DB-check idempotency)** intentionally left as-is per plan (sub-second probe; acceptable cost).
- Field validation per phase remains the operator's responsibility (no live-Jetson E2E pytest).
- Risk R5 (PRAGMA passes but RTAB-Map still rejects) explicitly accepted; the rewritten `oakd` check's `active+2485 → WARN crash-loop` state surfaces it.

### Sign-off

This plan has been reviewed and is **Ready for Implementation**.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-02 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-02 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/014-oakd-bootstrap-detection-fix.md |
