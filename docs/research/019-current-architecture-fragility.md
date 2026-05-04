---
id: "019"
type: research
title: "Current Architecture Fragility Inventory & Mitigations"
status: ✅ Complete
created: "2026-05-04"
current_phase: "✅ Complete"
---

## Introduction

This document inventories the **current, real fragilities** in the Zero-Turn Mower Rover stack as of 2026-05-04, and records concrete mitigations for each. It was prompted by a discussion of whether the system should move to an RTOS architecture; the conclusion was that the safety-critical RTOS is **already** present (ChibiOS on the Cube Orange) and the hardware E-stop sits above all software, so the real fragilities lie elsewhere — primarily in misconfigured ArduPilot failsafes, soft-real-time perception assumptions, and operational gaps in the Linux-side orchestration tier.

This is **not** a plan. It is a research-grade catalog so the planner agent can pick items off it in priority order. Items are tagged by severity:

- **🔴 Safety** — could lead to uncontrolled motion, blade engagement, or property damage if it fires before mitigation.
- **🟠 Operational** — degrades autonomy or forces manual recovery; not directly dangerous given the E-stop and spring-return levers.
- **🟡 Quality** — affects reliability, observability, or developer velocity but not field safety.

## Objectives

- Catalog every known fragility in the integrated stack as of 2026-05-04.
- Distinguish architectural fragilities (would require a redesign) from configuration/operational fragilities (one-line fixes or small CLI additions).
- For each, record the recommended mitigation, the constraint it must respect, and whether it is on an existing plan.
- Provide an honest "things we don't know yet" section so unknowns are not mistaken for known-safe.

## Architectural Decision: RTOS vs Current Split (Recap)

The current split is sound and should not change:

| Concern | Runs on | Real-time class |
|---|---|---|
| Servo PWM, RC failsafe, EKF, mode logic, fence/EKF failsafe → Hold | ChibiOS on Cube Orange (400 Hz) | Hard real-time (already RTOS) |
| E-stop | Hardware relay — cuts ignition + servo power | Bypasses all software |
| RTK corrections | SiK radio → Septentrio mosaic-H → Cube serial | No CPU in the path |
| VSLAM, perception, mission orchestration, logging, CLI | Jetson + Ubuntu (JetPack 6 / L4T 36.5) | Soft real-time (designed to degrade safely) |

Moving the Jetson to an RTOS would **lose** DepthAI, RTAB-Map, CUDA/cuDNN/TensorRT, pyubx2, pymavlink, MAVSDK, structlog, OpenCV — and **gain** nothing, because none of the hard-real-time loops are on Linux. The fragilities below are therefore tractable inside the existing architecture.

## Fragility Inventory

### Phase 1: ArduPilot Failsafe Misconfiguration (🔴 Safety)

**Status:** ✅ Complete

The 2026-05-01 param dump (`docs/config/mower.param`) shows three failsafe-related parameters that are wrong for a zero-turn mower with a 4-acre operating envelope. RTL on a skid-steer mower drives **in a straight line through whatever obstacles exist** — fences, trees, the operator. Hold is the only safe default.

| Param | Current | Required | Why |
|-------|---------|----------|-----|
| `FENCE_ACTION` | `1` (RTL) | `2` (Hold) | RTL ignores obstacles; Hold stops in place. |
| `FS_EKF_ACTION` | `1` (RTL) | `2` (Hold) | EKF failure usually correlates with GNSS degradation — RTL is exactly when you should NOT trust position. |
| `FENCE_ENABLE` | `0` | `1` | Geofence is the primary backstop against runaway. Must be on before any autonomous mission. |
| `ARMING_CHECK` | `0` (all disabled) | non-zero, scoped | All arming checks are disabled. At minimum, GPS lock + EKF healthy + RC link should block arming. |
| `FS_GCS_ENABLE` | `0` | TBD (likely `1` with Hold) | GCS link loss currently does nothing; if mission orchestration runs from the laptop, the rover should at minimum Hold when MAVLink drops. |

**Key Discoveries:**
- All four are single-param fixes — no firmware change, no architectural change.
- The `mower params apply` snapshot/diff tooling (Plan 001) is already built; this is exactly its use case.
- These should land **before** the next field test, not as part of a larger workstream.

**Recommended Mitigations:**
1. Author a `safety-defaults.yaml` profile under `config/params/` with the four corrections above plus an `ARMING_CHECK` bitmask that asserts GPS + EKF + RC + battery.
2. Apply via `mower params apply --profile safety-defaults --diff --confirm`.
3. Add a SITL test (`@pytest.mark.sitl`) that loads the dump, asserts the four post-conditions, and triggers each failsafe to confirm Hold (not RTL) is entered.
4. Re-snapshot to `docs/config/mower.param` after apply so the repo's authoritative dump matches reality.

**Implementation:** Tooling, profile, and SITL tests delivered by [docs/plans/016-failsafe-defaults-correction.md](../plans/016-failsafe-defaults-correction.md). Live apply is performed via [docs/procedures/006-apply-safety-defaults.md](../procedures/006-apply-safety-defaults.md). Update this section's status to `✅ Applied YYYY-MM-DD` after the operator runs the procedure.

**Files Analyzed:**

| File | Relevance |
|------|-----------|
| `docs/config/mower.param` lines 328, 329, 346, 348 | Confirms current wrong values |
| `docs/plans/001-param-apply-snapshot-restore.md` | Tooling already exists for the fix |
| `.github/copilot-instructions.md` | States the requirement explicitly: "Default mower failsafe = Hold, not RTL" |

**Gaps:** Whether `FS_GCS_ENABLE=1` is desirable depends on whether the mission is intended to survive a brief MAVLink dropout (long missions over 4 acres with a laptop on a tripod will see dropouts). Needs an operator decision.

---

### Phase 2: Blade Clutch Interlock Lives on the Wrong Side (🔴 Safety)

**Status:** ✅ Complete

The blade clutch (SERVO7, function `56` = RCIn6) is currently a pure RC passthrough. The vision says the clutch should be **interlocked on confirmed engine-running** (RPM ≥ idle threshold AND voltage ≥ alternator threshold). That interlock currently does not exist in firmware **or** in the Linux-side mission orchestrator. It exists only on the operator's transmitter (the operator chooses when to flick SC).

If the autonomous mission ever drives SERVO7 — or if RC fails safe and SERVO7 is held in its last commanded position — there is no hardware/firmware check that the engine is running. Engaging the clutch with a stalled engine is mechanically harmful and a vibration/noise indicator the operator would otherwise rely on for situational awareness.

**Recommended Mitigations (in priority order):**
1. **ArduPilot Lua script on the Cube Orange** — gate `SERVO7` output on `RPM1` ≥ idle threshold AND `BATTERY_STATUS` voltage ≥ alternator threshold. This keeps the interlock in the hard-real-time domain. Lua is supported on Cube Orange and does not require a firmware fork (respects NG-2).
2. **Wire RPM1**: per the vision and copilot-instructions, the inductive RPM pickup on the Kawasaki FR691V spark plug lead must be conditioned + opto-isolated to 3.3 V before reaching an AUX pin. AUX pins are NOT 5/12 V tolerant — same rule as the wheel encoders. Until RPM1 reads, the interlock has nothing to gate on.
3. **Linux-side belt-and-suspenders**: the mission orchestrator should refuse to issue clutch-engage commands unless the latest `RPM_VALUE` MAVLink message confirms engine-running. This is a soft check, but it prevents the orchestrator from issuing a command that the Lua script would reject — which would otherwise be a confusing failure mode in the field.

**Constraints:**
- Must respect NG-2 (no firmware fork) — hence Lua.
- Must respect the AUX pin 3.3 V rule — opto-isolation is non-negotiable.
- Spring-return-to-neutral on the levers and the hardware E-stop remain the ultimate authorities.

---

### Phase 3: VSLAM Pose Quality Has No Firm Failsafe Path (🟠 Operational, edges into 🔴)

**Status:** ✅ Complete

VSLAM is correctly designed as soft real-time — a dropped or late frame degrades pose quality but does not crash the EKF, because GNSS+IMU keep running. **However**, the current integration sends VSLAM pose into ArduPilot via the bridge with no published policy for what happens when:

- The OAK-D drops out (USB re-enumeration, thermal throttle, dust on the lens).
- RTAB-Map enters relocalization and pose covariance balloons.
- The bridge socket times out (the known "Socket read timed out" path noted in the bringup probe).

If ArduPilot's EKF is fusing a degraded VSLAM pose alongside good GNSS, the EKF can either reject it (best case) or absorb a position step (bad case). The existing `FS_EKF_ACTION=1` (RTL) makes this **worse** — see Phase 1.

**Recommended Mitigations:**
1. Land Phase 1 first — `FS_EKF_ACTION=2` (Hold) is the prerequisite that makes any VSLAM degradation safe.
2. Define and enforce a covariance gate in the bridge: if RTAB-Map pose covariance exceeds a threshold (TBD in field), the bridge stops publishing `VISION_POSITION_ESTIMATE` rather than publishing degraded data. Better to lose vision than to poison the EKF.
3. Add a heartbeat from the bridge → the bridge stops publishing if it hasn't received a fresh pose from rtabmap_slam_node within N ms.
4. Surface bridge state through the existing health monitor (`mower-health.service`) so the operator sees "VSLAM degraded" in telemetry rather than discovering it post-hoc in logs.

**Files Analyzed:**

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | Publishes pose + covariance over UDS |
| `src/mower_rover/jetson/vslam/bridge.py` (per repo memory) | Forwards to MAVLink VISION_POSITION_ESTIMATE |
| `docs/plans/008-vslam-ardupilot-integration.md` | Original integration design |

**Gaps:** Covariance threshold needs field calibration. Mark as `@pytest.mark.field`.

---

### Phase 4: USB Stack Fragility on the Jetson (🟠 Operational)

**Status:** ✅ Complete

The OAK-D Pro is on a powered Waveshare hub via the Realtek root hub, requires kernel quirks (`usbcore.quirks=03e7:2485:gk,03e7:f63b:gk`), and re-enumerates across USB 2/3 when DepthAI uploads firmware. The Pixhawk shares the same hub. Repo memory records this is "confirmed working" but every term in that sentence is a known fragility:

- A USB error storm on either device can knock out the other (shared root hub).
- A kernel update that touches `usbcore` can silently re-introduce LPM and break the OAK-D until quirks are re-applied.
- Hub power glitches re-enumerate **both** devices; the Pixhawk symlink (`/dev/pixhawk`) is stable but the device path changes.

**Recommended Mitigations:**
1. Pin the kernel package on the Jetson (`apt-mark hold linux-tegra` or equivalent), so security updates don't silently regress USB quirks.
2. Add a startup probe that asserts `usbcore.quirks` contains both PIDs and exits non-zero if not — wired into `mower-health.service`.
3. Move the Pixhawk to the **direct USB-C port (J24)** if a free path can be arranged. The Waveshare hub is needed for the OAK-D's power budget; the Pixhawk is not power-constrained and benefits from isolation.
4. Long-term: dedicate the Waveshare hub to the OAK-D only. (Documented as a future hardware change, not blocking.)

**Files Analyzed:**

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | Owns the quirks + udev rules |
| `docs/procedures/001-usb-enumeration.md` | Documents the bus-switch behavior |
| `/memories/repo/hardware-state.md` | Authoritative hardware record |

---

### Phase 5: Per-Side Calibration Not Yet Captured (🟠 Operational)

**Status:** ✅ Complete

The copilot-instructions explicitly require independent `SERVO1` / `SERVO3` profiles (TRIM, MIN, MAX, REVERSED, forward/reverse deadband) because the hydrostatic levers are not symmetric. The param dump shows symmetric defaults — meaning calibration has not been captured in the param file yet. Driving a zero-turn with symmetric servo trims under autonomy will produce yaw drift even on a perfectly flat surface, which the EKF will partially mask but the coverage planner will not.

**Recommended Mitigations:**
1. Implement / finalize `mower servo-cal` per the vision contract (independent forward/reverse deadband per side).
2. Run it in the field. This is `@pytest.mark.field` by definition.
3. Persist the profile into `config/params/servo-cal.yaml`, snapshot, and re-dump `docs/config/mower.param`.
4. Add a SITL pre-flight check that **warns** if `SERVO1` and `SERVO3` profiles are bit-symmetric — symmetry on a real hydrostatic mower is a smell, not a feature.

---

### Phase 6: Wheel Encoders & RPM Not Yet Wired (🟠 Operational)

**Status:** ✅ Complete

Param dump: `WENC_TYPE=0`, `RPM1_TYPE=0`. Both are part of the safety chain (encoders for odometry sanity vs GNSS, RPM for the blade clutch interlock in Phase 2). Hardware is selected (CALT GHW38 encoders, inductive pickup on the spark plug) but neither is plumbed.

**Recommended Mitigations:**
1. Build the level-shifter / opto-isolator board for the AUX pins (mandatory — AUX is 3.3 V).
2. Configure `WENC_TYPE` for quadrature, set PPR to 200, wire to AUX pins per the wiring map.
3. Configure `RPM1_TYPE` to the appropriate input mode for the conditioned spark-plug signal.
4. Add a SITL test that asserts encoder + RPM1 params are configured before any "field-ready" pre-flight passes.

This is a hardware task as much as a software task; document the wiring in `docs/field/` once done.

---

### Phase 7: Operator Workstation Is a Single Point of Failure (🟡 Quality)

**Status:** ✅ Complete

Mission orchestration runs from the Windows laptop via MAVLink. If the laptop hibernates, the Wi-Fi association drops, or the Python process dies mid-mission, the rover is left in whatever mode/mission state it was last commanded — with `FS_GCS_ENABLE=0` (currently!), nothing happens server-side.

**Recommended Mitigations:**
1. Land `FS_GCS_ENABLE=1` with Hold action (Phase 1 follow-up).
2. Document a "tripod laptop" SOP: power settings, Wi-Fi roaming disabled, screen-lock disabled, antenna positioning. This is `docs/procedures/`.
3. Consider whether mission orchestration should run on the Jetson (companion-side) for missions longer than the operator's attention span. The Jetson has the compute and is physically on the rover. This is a vision-level decision, **not** a casual refactor — flag for the visionary, not the planner.

---

### Phase 8: Logging & Observability Gaps (🟡 Quality)

**Status:** ✅ Complete

`structlog` is in use, JSON sink + human console exist, but the current bringup/deploy iteration cycle exposed gaps:

- Unicode encoding issues on Windows (`PYTHONIOENCODING=utf-8` had to be set manually for `mower jetson bringup` to render its own output — see recent terminal history). This means structured log lines with non-ASCII content can drop on the laptop.
- The bringup `--from-step` resume is a workaround for the lack of step-level idempotence. Most steps **are** idempotent; the ones that aren't should be.
- Field-side logs live on the Jetson (`journalctl -u mower-vslam-bridge.service`). There is no `mower jetson logs pull --since <time>` shortcut yet — operators SSH in manually.

**Recommended Mitigations:**
1. Force UTF-8 in the CLI entrypoint (`sys.stdout.reconfigure(encoding="utf-8")` at import time on Python ≥ 3.7) so the operator doesn't need env-var workarounds.
2. Audit each bringup step for idempotence; the ones that aren't should declare it explicitly.
3. Add `mower jetson logs pull --service <name> --since <time>` that uses the existing SSH transport to pull `journalctl -o cat` output and persist it under `logs/` with a correlation ID.

---

### Phase 9: SITL ≠ Reality (Architectural Acknowledgment, 🟡 Quality)

**Status:** ✅ Complete

Per the copilot-instructions: ArduPilot's `rover-skid` SITL is purely kinematic. Every SITL-validated test must be marked `@pytest.mark.sitl`; tuning, PIDs, `CRUISE_*`, RTK behavior, and any servo response curves are field-required. This is not a fragility per se — it is correctly understood — but the **fragility risk** is that someone (human or AI agent) writes a tuning test in SITL and assumes it's load-bearing.

**Recommended Mitigations:**
1. Add a CI check that fails if any test under `tests/test_*sitl*.py` references PID params, `CRUISE_*`, or servo endpoints.
2. Document the SITL-vs-field test boundary in `tests/conftest.py` with a docstring the agent must read.
3. Keep the existing `@pytest.mark.field` marker discipline.

---

## Things We Genuinely Don't Know Yet

These are flagged as Open Questions. **Do not invent answers.**

1. **VSLAM covariance threshold for the bridge gate (Phase 3)** — needs field measurement under representative lighting + grass conditions. Without this, the gate either trips constantly or never trips.
2. **`FS_GCS_ENABLE` correct value (Phase 1, 7)** — depends on operator preference for "Hold on link loss" vs "tolerate 30 s link loss." Operator decision.
3. **RPM idle threshold (Phase 2)** — depends on the actual idle RPM of this specific FR691V engine; the spec gives a range. Field measurement.
4. **Alternator voltage threshold (Phase 2)** — same. Read on a multimeter at idle, set with margin.
5. **Whether to relocate the Pixhawk off the Waveshare hub (Phase 4)** — depends on cable routing on the rover that hasn't been built yet.
6. **Whether mission orchestration should move to the Jetson (Phase 7)** — vision-level decision; the current MVP path is laptop-side and that should not change without explicit re-vision.

## Overview

### Prioritized Action List

In strict priority order — items earlier in this list **block** items later in the list:

1. 🔴 **Phase 1: Fix the four failsafe params.** One profile, one apply, one snapshot. Blocks all autonomous field testing.
2. 🔴 **Phase 2: Wire RPM1 + ship the Lua blade-clutch interlock.** Blocks any blade-engaging mission.
3. 🟠 **Phase 3: VSLAM covariance + heartbeat gate in the bridge.** Depends on Phase 1 (Hold failsafe) being in place first.
4. 🟠 **Phase 5: Per-side servo calibration in the field.** Independent of Phases 1–3; can run in parallel.
5. 🟠 **Phase 6: Wheel encoder wiring + WENC config.** Independent; can run in parallel.
6. 🟠 **Phase 4: USB hardening (kernel pin, startup probe).** Quality-of-life; not blocking.
7. 🟡 **Phase 8: UTF-8 + idempotent bringup steps + `logs pull` CLI.** Pure DX; do when frustration hits.
8. 🟡 **Phase 7: Operator workstation SOP + `FS_GCS_ENABLE` decision.** SOP can land now; the architectural question is for the visionary.
9. 🟡 **Phase 9: SITL/field test guard rails.** One CI check, low effort, high payoff against future drift.

### Cross-Cutting Patterns

- **The biggest risks are configuration, not architecture.** Five of the nine phases are param/config/wiring fixes. The architecture is sound.
- **The hardware E-stop and spring-return levers absorb a lot of sin.** That is by design and should not be relied on as an excuse to defer Phases 1 and 2.
- **Linux-side soft-real-time is the right tool for VSLAM and orchestration**, provided the Cube-side failsafes correctly demote VSLAM to "nice to have." Phase 1 is what makes that demotion safe.
- **The Lua scripting path on the Cube Orange is underused.** It is the right place for the blade-clutch interlock and would also be a good home for any future "engine-running" or "battery low" hard interlocks. Stays inside NG-2.

### Actionable Conclusions

- Do not move to a different OS architecture. Land Phase 1 this week.
- Treat Phase 2 (RPM1 + Lua clutch interlock) as a mandatory prerequisite to the first autonomous blade-engaging mission, not a "nice to have."
- Treat the SITL/field discipline (Phase 9) as cheap insurance against AI-agent-induced regression — write the CI check before the next major refactor.

## Standards Applied

| Standard | Relevance | Guidance Applied |
|----------|-----------|------------------|
| Project copilot-instructions | All sections | Failsafe = Hold; AUX pins 3.3 V; NG-2 (no fork); per-side calibration mandatory; SITL ≠ field |
| Vision doc 001 + Research doc 001 | All sections | Research wins where vision and research disagree (GNSS, ignition relay, encoders) |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-04 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/019-current-architecture-fragility.md |

**Next Steps:**
- Hand off to `@pch-planner` to plan **Phase 1 (failsafe params)** as the immediate next implementation. It is small, safe, fully covered by existing tooling (Plan 001), and unblocks autonomous field testing.
- Phase 2 (RPM1 + Lua interlock) requires a hardware step (signal conditioning) that should be scheduled with the operator before planning the software side.
- Phases 3, 5, 6 can be planned independently when their prerequisites (Phase 1 for Phase 3; hardware install for Phase 6) are met.
