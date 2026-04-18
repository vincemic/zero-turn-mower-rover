---
id: "001"
type: vision
title: "Zero-Turn Mower Robotic Conversion — Configuration & Utilities"
status: ✅ Complete
created: "2026-04-17"
owner: pch-visionary
---

## Introduction

This vision captures a project to convert a zero-turn mower into an autonomous robotic lawn mower using a Pixhawk Cube Orange flight controller running ArduPilot, an ArduSimple simpleRTK2B+heading (dual-antenna moving-base GPS) for high-precision positioning and GPS-derived heading, dual servos driving the left/right steering arms, and an NVIDIA Jetson Orin companion computer with a depth camera for VSLAM. The scope of this vision is the **configuration tooling and utility scripts/programs** needed to set up, tune, and operate the robot — not the robot's physical build or the autopilot firmware itself.

## Problem Space

**Context:** Owner needs to mow a 4-acre lawn and wants to automate the job by converting an existing zero-turn mower into a robotic mower. This is a custom hardware/software integration (Pixhawk Cube Orange + ArduPilot Rover + ArduSimple simpleRTK2B+heading + dual steering servos + Jetson Orin + depth-camera VSLAM) for which no single off-the-shelf toolset exists. Existing tools (e.g., Mission Planner, QGroundControl, MAVProxy, ArduPilot parameter tools, Jetson/ROS utilities) cover parts of the workflow but leave gaps. Manual setup and tuning across these disparate tools is difficult and error-prone.

**Current State:** No purpose-built tooling exists for this custom platform. Setup, calibration, and tuning must be done by hand across multiple unrelated tools, which is slow, error-prone, and hard to repeat.

**Desired State:** A set of configuration and utility scripts/programs that fill the gaps between existing tools and streamline the end-to-end process of setting up, tuning, and operating this specific robot platform.

**Success Metrics:**

| Metric | Target | Method |
|--------|--------|--------|
| End-to-end autonomous mowing | 4-acre lawn mowed without human intervention | Field run; track interventions per run |
| Capability milestones (tooling) | Specific tooling capabilities exist and work end-to-end | Per-capability acceptance checks (defined in Stage 4/6) |
| Setup/tuning effort | Reduced and repeatable vs. fully manual workflow | Subjective owner assessment + reproducibility check (same config restorable on demand) |

## Stakeholders

| Role | Goals | Pain Points | Proficiency |
|------|-------|-------------|-------------|
| Owner / Builder / Operator (solo) | Build, tune, configure, and run the robot to mow a 4-acre lawn autonomously | Manual setup/tuning across disparate tools is difficult and error-prone; gaps between existing tools | technical (power user) |

## Goals

**Primary Goals:**
- **G-1:** Enable the operator to bring the robot from cold-boot to ready-to-mow with minimal manual steps and reproducible configuration. — Priority: must-have — Success: documented one-command (or near-one-command) bring-up procedure that succeeds repeatably.
- **G-2:** Enable the operator to tune the integrated platform (steering servos, ArduPilot params, RTK, VSLAM) using guided utilities that fill the gaps left by existing tools. — Priority: must-have — Success: each tuning workflow has a dedicated utility that the operator can run end-to-end without ad-hoc manual steps.
- **G-3:** Enable end-to-end autonomous mowing of a 4-acre lawn by providing the operational scripts/utilities needed to run, monitor, and recover a mowing mission. — Priority: must-have — Success: full 4-acre lawn mowed in one session without manual intervention.
- **G-4:** Enable the operator to capture, version, and restore the full robot configuration (Pixhawk params + Jetson config) as a single artifact. — Priority: should-have — Success: snapshot of full robot config can be exported, committed, and restored on demand.

**Non-Goals:**
- **NG-1:** Building or modifying the physical robot (mechanical conversion, wiring, mounting).
- **NG-2:** Modifying or forking ArduPilot firmware or writing a custom autopilot.
- **NG-3:** Writing a custom VSLAM algorithm; we will integrate an existing VSLAM stack.
- **NG-4:** Replacing Mission Planner / QGroundControl as a general-purpose GCS; we fill gaps only.
- **NG-5:** Abstracting over other people's hardware variations (different flight controllers, GPS units, or mower platforms).
- **NG-6:** Mowing-blade control logic and safety certification beyond what ArduPilot/the hardware provide natively; tooling only orchestrates mission start/stop.
- **NG-7:** Production-grade multi-user, cloud, or fleet management features.

## Requirements

**Functional Requirements:**

| ID | Requirement | Priority | Goal | Phase |
|----|-------------|----------|------|-------|
| FR-1 | Detect, enumerate, and verify connected hardware (Pixhawk, RTK GPS, servos via Pixhawk, Jetson, depth camera) and report status. | must-have | G-1 | R1 / Phase 2 |
| FR-2 | Apply a known-good baseline ArduPilot parameter set to the Pixhawk in one operation. | must-have | G-1, G-4 | R1 / Phase 4 |
| FR-3 | Configure and verify the ArduSimple simpleRTK2B+heading for position + GPS-derived heading (base/rover setup, message rates, fix quality, heading quality). | must-have | G-1, G-2 | R1 / Phase 5 |
| FR-4 | Guided servo calibration utility for the left/right steering arms (endpoints, neutral, deadband, mixing for skid-steer). | must-have | G-2 | R1 / Phase 6 |
| FR-5 | Guided ArduPilot Rover tuning workflow (steering/throttle PIDs, turn rate, navigation tuning) using log-driven feedback. | must-have | G-2 | R1 / Phase 7 |
| FR-6 | Set up, launch, and verify the VSLAM stack on the Jetson with the depth camera. | should-have | G-1, G-2 | R3 / Phase 12 |
| FR-7 | Bridge VSLAM/Jetson telemetry into ArduPilot (e.g., vision position source) and verify bridge health. | should-have | G-2, G-3 | R3 / Phase 13 |
| FR-8 | Plan and upload a mowing mission (boundary, exclusion zones, coverage pattern, line spacing) to the autopilot. | must-have | G-3 | R1 / Phase 8 |
| FR-9 | Pre-flight check: single command validates ready-to-mow (hardware, RTK fix, params, mission, VSLAM). | must-have | G-1, G-3 | R1 / Phase 9 |
| FR-10 | Live mission monitoring (state, position, fix quality, coverage progress, alerts) during a run. | should-have | G-3 | R2 / Phase 10 |
| FR-11 | Post-run log collection and summary (Pixhawk DataFlash + Jetson logs + run metadata) into a single archive. | should-have | G-2, G-3 | R2 / Phase 11 |
| FR-12 | Snapshot full robot configuration (Pixhawk params + Jetson config + tooling config) to a versionable artifact; restore from snapshot. | must-have | G-4 | R1 / Phase 4 |
| FR-13 | Safe-stop / recovery utility (E-stop trigger, return-to-launch, clean shutdown of Jetson stack). | must-have | G-3 | R1 / Phase 9 |

**Non-Functional Requirements:**

| ID | Requirement | Priority | Type |
|----|-------------|----------|------|
| NFR-1 | Tools must fail gracefully and never leave the robot in a half-configured or unsafe state; pre-flight, snapshot/restore, and safe-stop paths must be reliable. | must-have | reliability |
| NFR-2 | Tooling is usable in the field from a laptop near the mower, supports both interactive and headless/scripted modes, and provides clear status output even on limited network. | must-have | operability |
| NFR-3 | E-stop is always reachable and fast; tooling never commands actuators without an explicit confirmation path and never undermines hardware-level safety. | must-have | safety |
| NFR-4 | Every tooling operation produces structured logs of inputs, robot responses, and outcomes; post-run logs are easy to inspect; tuning decisions are explainable. | must-have | observability |
| NFR-5 | Same input config + same hardware produces the same robot state; configuration snapshots are exact and restorable. | should-have | reproducibility |

**Constraints:**

| ID | Type | Constraint | Impact |
|----|------|------------|--------|
| C-1 | technical | Tooling interoperates with ArduPilot Rover on Pixhawk Cube Orange via MAVLink. | Drives MAVLink as the primary autopilot interface (likely pymavlink / MAVSDK). |
| C-2 | technical | RTK GPS hardware is ArduSimple **simpleRTK2B+heading** (dual-antenna ZED-F9P + ZED-F9H moving-base), providing position and GPS-derived heading from a single integrated module. | Tooling configures the integrated module's moving-base setup; yaw source is GPS, not magnetometer; single USB/UART interface to Pixhawk simplifies wiring. |
| C-3 | technical | Companion computer is NVIDIA Jetson Orin Nano Super (8GB) running Linux (JetPack/Ubuntu). | Jetson-side tooling targets aarch64 Linux; VSLAM and bridge processes share limited compute (~67 TOPS, 8GB). |
| C-4 | technical | Depth camera is Luxonis OAK-D Pro (USB), with onboard depth and IMU via the DepthAI SDK. | Depth computed on-camera; VSLAM stack must accept DepthAI input or use OAK-D Pro through a compatible driver. |
| C-5 | technical | VSLAM stack must run on the Jetson Orin Nano Super; specific stack is undetermined and is a research topic. | Tooling for FR-6/FR-7 cannot be designed in detail until stack is selected. |
| C-6 | technical | Operator workstation is a Windows laptop; tooling is split — laptop side (planning, snapshots, monitoring) and Jetson side (VSLAM bring-up, log collection). | Cross-platform tooling required: Python (or similar) on Windows + Linux; clear split of responsibilities between sides. |
| C-7 | technical | Steering uses two servos driving the left/right hydrostatic steering arms, controlled via Pixhawk PWM/AUX outputs. | Skid-steer mixing handled by ArduPilot; calibration utility must drive both servos and capture endpoint/neutral/deadband per side. |
| C-7a | technical | Mower platform is a Husqvarna Z254 (54" residential zero-turn, hydrostatic transmission, twin-lever steering). | Confirms dual-servo steering-arm assumption; sets physical envelope (cutting width, turn behavior) for mission-planning utilities. |
| C-8 | resource | Single developer, hobby budget, evenings/weekends cadence. | Favor small, composable utilities and existing libraries over large custom systems. |
| C-9 | regulatory | No formal regulatory regime for personal-use robotic mower on private property in operator's jurisdiction. | No compliance gates; safety is owner-driven (NFR-3). |
| C-10 | operational | Field environment is outdoors with possible sun glare and limited or no internet on the operator's laptop. | Tooling must work fully offline; status output must be readable on a laptop screen in sunlight (high contrast, terminal-first). |
| C-11 | technical | Two SiK telemetry radios on the rover: (a) one paired to the simpleRTK2B+heading for RTCM corrections from a base-station SiK radio; (b) one paired to a PC running Mission Planner for MAVLink telemetry/command. | RTK corrections are delivered over a dedicated SiK radio link (not NTRIP/internet); MAVLink reaches the laptop over a separate SiK link. Tooling on the laptop talks MAVLink via the SiK serial port; tooling does not need to bridge RTCM. |

## Architecture Vision

**Style:** CLI suite — small, composable command-line utilities (one tool per capability) running on the operator's Windows laptop and on the Jetson Orin Nano Super, sharing common libraries for MAVLink, config, snapshots, and logging. Complementary to Mission Planner / QGroundControl (NG-4); does not replace them.

**Rationale:** Best fit for a solo-operator, field-used, gap-filling toolset (C-6, C-8, C-10, NFR-1..NFR-5). Defers GUI investment until proven necessary.

**Known components (from initial brief):**

| Area | Choice | Rationale |
|------|--------|-----------|
| Flight Controller | Pixhawk Cube Orange | User-specified |
| Autopilot Firmware | ArduPilot Rover | User-specified |
| Positioning | ArduSimple simpleRTK2B+heading (dual-antenna ZED-F9P + ZED-F9H moving-base; position + GPS heading) | User-specified |
| Steering Actuation | Two servos driving left/right hydrostatic steering arms (Pixhawk PWM/AUX) | User-specified |
| Companion Computer | NVIDIA Jetson Orin Nano Super (8GB) | User-specified |
| Perception | Luxonis OAK-D Pro depth camera over USB → VSLAM on Jetson | User-specified |

**Tooling Technology Decisions:**

| Area | Choice | Rationale |
|------|--------|-----------|
| Implementation language | Python 3 | Best ecosystem fit (pymavlink, DepthAI, ArduPilot tooling); cross-platform Windows + Linux. |
| CLI framework | Typer | Type-hint based, low boilerplate, easy subcommand growth. |
| MAVLink library | pymavlink (primary); MAVSDK-Python optional for higher-level mission/offboard helpers. | Canonical Python ArduPilot interface. |
| Config format | YAML for human-edited config; JSON for machine-generated artifacts (snapshots, run metadata). | Human-friendly tuning + unambiguous round-trippable artifacts. |
| Snapshot/versioning | Git-tracked plain files (no custom versioning DB). | Matches NFR-5 reproducibility with minimal infra. |
| Logging | structlog (structured JSON) + human-readable console output. | Satisfies NFR-4 observability. |
| Packaging | uv + pyproject.toml; pipx for per-tool install. | Fast, cross-platform. |
| Testing | pytest + ArduPilot SITL for hardware-in-loop tests. | Lets most tooling be tested without the real robot. |
| VSLAM ↔ ArduPilot bridge | ArduPilot VISION_POSITION_ESTIMATE / VISION_SPEED_ESTIMATE MAVLink messages (EKF vision source). | Standard ArduPilot integration point; transport details depend on VSLAM stack. |

**Research Topics (architecture-related):**
- VSLAM stack selection (must run on Jetson Orin Nano Super, ingest OAK-D Pro). See C-5.
- ROS vs. no-ROS on the Jetson — defaults to no-ROS unless VSLAM stack requires it.
- RTK base station approach — ArduSimple base vs. NTRIP service vs. hybrid.
- VSLAM ↔ MAVLink transport (direct UDP MAVLink from Jetson process vs. ROS bridge).

**Integrations:**

| System | Type | Direction | Criticality |
|--------|------|-----------|-------------|
| Pixhawk / ArduPilot Rover | MAVLink over SiK telemetry radio (laptop-side serial COM port) | both | mvp |
| ArduSimple simpleRTK2B+heading | u-center config (USB during setup); RTCM stream from base over dedicated SiK radio (in operation) | both (config + corrections) | mvp |
| Base station (RTK) | SiK telemetry radio paired to rover's RTK SiK radio; streams RTCM from a base GPS receiver | write (RTCM out) | mvp |
| Steering servos | Pixhawk PWM/AUX outputs (controlled via MAVLink) | write | mvp |
| OAK-D Pro depth camera | DepthAI SDK over USB (on Jetson) | read | mvp |
| Jetson Orin Nano Super | SSH / file transfer / launchd-equivalent | both | mvp |
| Mission Planner / QGroundControl | Coexistence on the same MAVLink network | n/a | mvp |
| VSLAM stack on Jetson | TBD — feeds VISION_POSITION_ESTIMATE into ArduPilot | both | mvp |

**Security:**

| Concern | Approach |
|---------|----------|
| Authentication | Out of scope for v1 (LAN-only, single operator); rely on physical and Wi-Fi security. |
| Authorization | N/A (single user). |
| Data Sensitivity | None significant; mission boundaries and logs are not sensitive. |
| Actuator Safety | NFR-3: tooling never commands actuators without explicit confirmation; safe-stop (FR-13) always available. |

## Product Phasing

Organized into releases (MVP → final form). Each release contains dependency-ordered phases sized for individual handoff to pch-planner and pch-coder within a single context window. The pch-researcher processes one release at a time.

### Foundational Components

| Component | Type | What It Provides | Release |
|-----------|------|-------------------|---------|
| Python project skeleton | architecture | uv-managed pyproject, package layout, shared library, Typer CLI entry point | Release 1 (MVP) |
| MAVLink connection layer | shared infrastructure | Connection management, retry, message helpers around pymavlink | Release 1 (MVP) |
| Config & snapshot library | data foundation | YAML/JSON load/save, schema validation, Git-backed snapshot + restore primitives | Release 1 (MVP) |
| Structured logging | shared infrastructure | structlog setup, console + JSON-file sinks, per-operation correlation IDs | Release 1 (MVP) |
| SITL test harness | shared infrastructure | ArduPilot SITL launcher + pytest fixtures | Release 1 (MVP) |
| Jetson side base | architecture | Jetson Linux package layout, install script, systemd unit conventions, paired CLI | Release 1 (MVP) |
| Cross-side transport | shared infrastructure | SSH-based command execution + file transfer between laptop tools and Jetson tools | Release 1 (MVP) |
| Safety primitive | security pattern | Confirmation prompt + dry-run mode + central safe-stop trigger for every actuator command | Release 1 (MVP) |

### Release Overview

| Release | Theme | Phases | Features | Status | Research |
|---------|-------|--------|----------|--------|----------|
| Release 1 (MVP) | Bring-up + RTK-only autonomous mowing | 9 | 9 | ✅ Research Complete | [001-mvp-bringup-rtk-mowing.md](/docs/research/001-mvp-bringup-rtk-mowing.md) |
| Release 2 | Operations & iteration quality | 2 | 2 | ⏳ Not Started | — |
| Release 3 (Final) | VSLAM-augmented positioning | 2 | 2 | ⏳ Not Started | — |

---

### Release 1: MVP — Bring-up + RTK-only Autonomous Mowing

**Goal:** Robot autonomously mows the 4-acre lawn using RTK alone, with safe bring-up, calibration, tuning, mission planning, pre-flight, snapshot/restore, and safe-stop.

| Phase | Name | Category | Status | Depends On |
|-------|------|----------|--------|------------|
| 1 | Project foundation | infrastructure | ⏳ Not Started | — |
| 2 | MAVLink connection layer + hardware detection | infrastructure | ⏳ Not Started | 1 |
| 3 | Jetson side base + cross-side transport | infrastructure | ⏳ Not Started | 1 |
| 4 | ArduPilot baseline params + config snapshot | business-logic | ⏳ Not Started | 1, 2 |
| 5 | RTK GPS configure & verify | integration | ⏳ Not Started | 2, 4 |
| 6 | Servo calibration | business-logic | ⏳ Not Started | 2, 4 |
| 7 | Guided ArduPilot tuning | business-logic | ⏳ Not Started | 2, 4, 5, 6 |
| 8 | Mission planning & upload | interface | ⏳ Not Started | 2, 4 |
| 9 | Pre-flight check + safe-stop | interface | ⏳ Not Started | All prior |

#### Phase 1: Project foundation

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** infrastructure
**Foundational Components Delivered:** Python project skeleton, structured logging, config & snapshot library (primitives only), safety primitive, SITL test harness

**Scope:**
- uv-managed Python 3 project with pyproject.toml; shared library package + Typer CLI entry point
- structlog configured with console + JSON-file sinks; per-operation correlation IDs
- YAML/JSON config load/save with schema validation; Git-snapshot/restore primitives
- Safety primitive: confirmation prompt, dry-run mode, central safe-stop hook (placeholder; wired later)
- pytest setup with ArduPilot SITL launcher fixture

**Research Topics:**
- ArduPilot SITL fidelity for skid-steer Rover (medium)

**Done Criteria:**
- `mower --help` runs and lists subcommands (initially empty/placeholder)
- A trivial command exercises the safety primitive (confirm/dry-run)
- A trivial test launches SITL and connects via MAVLink loopback
- Snapshot of an empty config can be created and restored

#### Phase 2: MAVLink connection layer + hardware detection

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** infrastructure + data
**Foundational Components Delivered:** MAVLink connection layer
**Requirements:** FR-1 **Depends On:** Phase 1

**Scope:**
- pymavlink-based connection layer: open/retry, message helpers, common param read/write wrappers
- Hardware detection CLI: enumerate Pixhawk + RTK GPS receiver(s) + servos (via Pixhawk) + Jetson + OAK-D Pro
- Hardware status report; structured-log output

**Research Topics:**
- MAVLink-over-SiK field reliability (medium, cross-cutting)

**Done Criteria:**
- `mower hw-check` against SITL reports a healthy Pixhawk
- `mower hw-check` against real hardware enumerates all expected devices
- Connection layer retries gracefully on transient disconnect

#### Phase 3: Jetson side base + cross-side transport

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** infrastructure
**Foundational Components Delivered:** Jetson side base, cross-side transport
**Depends On:** Phase 1

**Scope:**
- Jetson-side package layout, install script, systemd unit conventions
- Paired Jetson CLI (`mower-jetson` or similar) using same shared library
- SSH-based command execution + file transfer from laptop to Jetson
- Optional small Jetson-side daemon stub for live status (placeholder for FR-10)

**Research Topics:** None

**Done Criteria:**
- Jetson tool installs cleanly on JetPack Ubuntu
- Laptop CLI can run a Jetson command remotely and stream output
- File pull from Jetson works (for later log archive)

#### Phase 4: ArduPilot baseline params + config snapshot

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** business-logic
**Requirements:** FR-2, FR-12 **Depends On:** Phases 1, 2

**Scope:**
- Apply a known-good baseline ArduPilot Rover param set in one operation
- Snapshot full robot config (Pixhawk params + Jetson config + tooling config) to a versionable artifact; restore from snapshot
- Dry-run + diff display before applying

**Research Topics:**
- ArduPilot Rover baseline param set for skid-steer with twin-servo steering arms (high)

**Done Criteria:**
- `mower params apply baseline.yaml` works against SITL with diff/confirm
- `mower snapshot create` produces a versionable artifact
- `mower snapshot restore <id>` round-trips a snapshot losslessly
- Snapshot includes Pixhawk params, Jetson config, tooling config

#### Phase 5: RTK GPS configure & verify

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** integration
**Requirements:** FR-3 **Depends On:** Phases 2, 4

**Scope:**
- Configure ArduSimple simpleRTK2B+heading rover for position + GPS-derived heading (message rates, integrated moving-base setup via u-center / configuration scripts)
- Verify fix quality, yaw quality; surface readable status
- RTK base station setup workflow (per research outcome)

**Research Topics:**
- RTK base station approach (high) — base GPS hardware choice (e.g., another simpleRTK2B configured as base, or simpleRTK2B+SBC running RTKLIB/u-center base mode), antenna survey-in vs. fixed coordinates, RTCM message set/rate sized for the SiK radio link bandwidth.

**Done Criteria:**
- `mower rtk configure` brings the rover GPS to expected message set
- `mower rtk verify` confirms RTK-fix and yaw-fix quality
- Documented base-station setup procedure

#### Phase 6: Servo calibration

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** business-logic + safety
**Requirements:** FR-4 **Depends On:** Phases 2, 4

**Scope:**
- Guided servo calibration for left/right steering arms: endpoints, neutral, deadband, per-side profile
- Apply calibration to Pixhawk servo output params
- Heavy use of safety primitive (each actuator command requires confirmation; dry-run mode for SITL)

**Research Topics:**
- Servo selection / specs validation (medium)

**Done Criteria:**
- `mower servo-cal` walks operator through left+right calibration interactively
- Resulting calibration profile is persisted and applied to Pixhawk
- All actuator commands gated by safety primitive

#### Phase 7: Guided ArduPilot tuning

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** business-logic
**Requirements:** FR-5 **Depends On:** Phases 2, 4, 5, 6

**Scope:**
- Guided tuning workflow: steering/throttle PIDs, turn rate, navigation tuning
- Log-driven feedback (read DataFlash logs, surface relevant traces)
- Iteration loop: propose change → operator reviews → apply → next test run

**Research Topics:** None new (depends on Phase 4 baseline research)

**Done Criteria:**
- Tuning utility runs an end-to-end iteration in SITL
- Tuning utility produces explainable proposals (NFR-4)
- Operator can accept/reject changes; rejected changes never applied

#### Phase 8: Mission planning & upload

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** interface
**Requirements:** FR-8 **Depends On:** Phases 2, 4

**Scope:**
- Mission definition: boundary, exclusion zones, coverage pattern, line spacing, home/launch
- Coverage-pattern generation appropriate for a 54" cutting deck (Z254)
- Upload mission to ArduPilot; round-trip verification

**Research Topics:**
- Mission file format choice (medium) — reuse Mission Planner `.waypoints` vs. custom YAML; coverage-pattern generation source

**Done Criteria:**
- `mower mission plan` produces a valid mission from a boundary + parameters
- `mower mission upload` round-trips to autopilot and reads back identically
- Coverage pattern visualizable (text/ASCII or simple plot)

#### Phase 9: Pre-flight check + safe-stop

**Release:** 1 (MVP) **Status:** ⏳ Not Started **Category:** interface + safety
**Requirements:** FR-9, FR-13 **Depends On:** All prior phases

**Scope:**
- Pre-flight: single command validates hardware OK, RTK fix, params match expected, mission loaded, (when present) VSLAM healthy
- Safe-stop: software-triggered RTL + clean Jetson shutdown; coordinates with hardware E-stop expectations
- Pre-flight failures produce actionable structured output

**Research Topics:**
- Pre-flight check inventory (low)
- Safe-stop mechanism design (high, cross-cutting) — physical E-stop + software RTL + Jetson shutdown interaction model

**Done Criteria:**
- `mower preflight` runs end-to-end with PASS/FAIL summary
- `mower safe-stop` triggers RTL and shuts down Jetson stack cleanly
- Pre-flight blocks downstream "go" commands when failing

---

### Release 2: Operations & Iteration Quality

**Goal:** Improve the operating experience after MVP — faster tuning iteration via auto log archive, standalone live monitoring without depending on Mission Planner.

| Phase | Name | Category | Status | Depends On |
|-------|------|----------|--------|------------|
| 10 | Live mission monitoring | interface | ⏳ Not Started | Release 1 |
| 11 | Post-run log archive & summary | data + interface | ⏳ Not Started | Release 1 |

#### Phase 10: Live mission monitoring

**Release:** 2 **Status:** ⏳ Not Started **Category:** interface
**Requirements:** FR-10 **Depends On:** Release 1 complete

**Scope:**
- Live MAVLink consumer: state, position, fix quality, coverage progress, alerts
- Terminal-friendly display (NFR-2 sun-readable)
- Alert thresholds configurable

**Research Topics:** None new

**Done Criteria:**
- `mower monitor` displays live state during a SITL or real run
- Alerts surface for fix degradation, mode changes, mission deviation

#### Phase 11: Post-run log archive & summary

**Release:** 2 **Status:** ⏳ Not Started **Category:** data + interface
**Requirements:** FR-11 **Depends On:** Release 1 complete (uses Phase 3 transport)

**Scope:**
- Pull Pixhawk DataFlash logs + Jetson logs + run metadata
- Bundle into single archive with manifest
- Generate summary report (duration, coverage, alerts, key params at run time)

**Research Topics:** None new

**Done Criteria:**
- `mower run-archive` collects all artifacts after a run
- Archive includes manifest and human-readable summary
- Archive is restorable / re-inspectable

---

### Release 3 (Final): VSLAM-Augmented Positioning

**Goal:** Add perception-based positioning robustness to the RTK-only MVP using the OAK-D Pro on the Jetson Orin Nano Super.

| Phase | Name | Category | Status | Depends On |
|-------|------|----------|--------|------------|
| 12 | VSLAM stack on Jetson | integration + business-logic | ⏳ Not Started | Release 1 |
| 13 | VSLAM ↔ ArduPilot bridge | integration | ⏳ Not Started | Phase 12 |

#### Phase 12: VSLAM stack on Jetson

**Release:** 3 **Status:** ⏳ Not Started **Category:** integration + business-logic
**Requirements:** FR-6 **Depends On:** Release 1 (Phase 3 Jetson base)

**Scope:**
- Select, install, and verify a VSLAM stack on Jetson Orin Nano Super, ingesting OAK-D Pro
- Tooling to launch/stop the stack and report health
- Calibrate camera extrinsics to robot frame

**Research Topics:**
- VSLAM stack selection (high)
- ROS-or-not on Jetson (high)
- OAK-D Pro extrinsic calibration to robot frame (medium)

**Done Criteria:**
- `mower vslam start` launches the stack on Jetson
- `mower vslam health` reports pose stream rate + quality
- Documented calibration procedure

#### Phase 13: VSLAM ↔ ArduPilot bridge

**Release:** 3 **Status:** ⏳ Not Started **Category:** integration
**Requirements:** FR-7 **Depends On:** Phase 12

**Scope:**
- Feed VISION_POSITION_ESTIMATE / VISION_SPEED_ESTIMATE MAVLink messages into ArduPilot
- Verify EKF accepts the vision source; tune EK3_SRC params
- Bridge health reporting; degraded-RTK fallback strategy

**Research Topics:**
- VSLAM ↔ MAVLink transport (high) — direct UDP vs. ROS bridge vs. mavros
- EKF3 vision source tuning (medium)

**Done Criteria:**
- VISION_POSITION_ESTIMATE flowing into ArduPilot at expected rate
- EKF accepts and uses vision source (verified in logs)
- `mower vslam bridge-health` reports end-to-end OK
- Documented degraded-RTK fallback behavior

---

### Deferred Items

| Item | Reason | Target Release |
|------|--------|----------------|
| Local web UI (mission map, live dashboard) | CLI-first decision; revisit only if a workflow is painful in CLI. | Post-R3 |
| Obstacle avoidance using OAK-D Pro depth | Separate workstream from positioning VSLAM. | Post-R3 |
| Multi-mower / fleet support | NG-7. | Never |
| Sharing / open-sourcing for other DIY builders | Solo-operator first; revisit if interest emerges. | Post-R3 |
| Magnetometer-based heading fusion fallback | RTK dual-antenna yaw is primary; revisit only if RTK yaw proves unreliable. | Conditional |
| Automated charging dock / autonomous recharge | Mowing run is operator-initiated. | Post-R3 |
| Weather-aware scheduling, calendar integration | Beyond MVP scope. | Post-R3 |

## Data Contracts Created

No data contracts authored at the vision stage. The tooling will produce/consume several persistent data artifacts whose schemas are tightly coupled to pending decisions (VSLAM stack, ArduPilot baseline params, mission file format). The planner should author contracts for these artifacts once those decisions are made:

| Planned artifact | Used by | Defer reason |
|------------------|---------|--------------|
| Robot config snapshot | FR-12, FR-2 | Shape depends on baseline ArduPilot param set + Jetson config layout. |
| Mission definition | FR-8 | Format choice (reuse Mission Planner `.waypoints` vs. custom YAML) is a planner decision. |
| Pre-flight check report | FR-9, FR-11 | Structure depends on which checks are actually implemented per phase. |
| Run archive manifest | FR-11 | Depends on what logs/artifacts the run produces. |
| Servo calibration profile | FR-4 | Depends on calibration utility design. |
| Hardware inventory | FR-1 | Depends on which devices the detector enumerates. |

## Research Topics

Cross-cutting topics not tied to a specific phase. Phase-specific research topics live inside each phase's section above.

| Topic | Priority | Questions | Applies To |
|-------|----------|-----------|------------|
| MAVLink-over-SiK field reliability | medium | Range, dropouts, recovery for the MAVLink SiK link across a 4-acre yard; impact on live monitoring (FR-10) and mission upload (FR-8). | Phases 2, 8, 9, 10 |
| RTCM-over-SiK link health | medium | RTCM bandwidth fit, link health monitoring, fix-degradation behavior when RTK link drops. | Phases 5, 9 |
| Safe-stop mechanism design | high | Physical E-stop + software-triggered RTL + Jetson clean shutdown — interaction model and authority. | Phases 6, 9, 13; NFR-3, FR-13 |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| RTK yaw (dual-antenna) doesn't deliver acceptable accuracy on a moving platform with vibration. | medium | high | Phase 5 verification gates; magnetometer-fusion fallback noted as deferred. |
| RTCM-over-SiK link drops in the field, causing RTK fix degradation mid-mission. | medium | high | Phase 5 monitors link health; pre-flight (FR-9) verifies RTCM is flowing; ArduPilot fail-safes on GPS quality loss. |
| ArduPilot SITL doesn't faithfully simulate twin-lever skid-steer dynamics; tuning utilities validate in SITL but fail on real hardware. | medium | medium | Treat SITL as smoke-test only; require field validation in Phase 7 done criteria. |
| Servo torque/speed insufficient to actuate Z254 hydrostatic levers reliably under load. | medium | high | Servo selection research (R1); fall back to higher-torque servos before Phase 6 if needed. |
| VSLAM stack selected for R3 doesn't run within Orin Nano Super 8GB compute/memory budget. | medium | medium | R3 is isolated; MVP works without VSLAM. Research evaluates resource fit before commit. |
| Safe-stop mechanism inadequate; software-triggered RTL alone is insufficient with a spinning blade. | low | critical | Cross-cutting research treats this as gate-condition for any field run; physical E-stop assumed mandatory. |
| Solo-developer cadence stalls before R1 completes; partial tooling unusable. | medium | medium | Phase ordering ensures each phase is independently demoable; snapshot/restore (Phase 4) protects intermediate progress. |
| ArduPilot baseline param research finds no clean community precedent for twin-servo steering arm setup. | medium | medium | Builds in time for first-principles tuning; SITL helps narrow before field. |

## Standards Applied

| Standard | Source | Relevance | Guidance |
|----------|--------|-----------|----------|
| (none queried) | n/a | Vision captured without organizational standards lookup. | n/a |

## Decisions Log

| Session | Date | Stage | Topic | Question | Answer | Impact |
|---------|------|-------|-------|----------|--------|--------|
| 1 | 2026-04-17 | 1 | Problem framing | What problem is this project solving? | Need to mow a 4-acre lawn; will use the robot to automate the job. | Establishes scale (4 acres) and primary use case (automated mowing of owner's lawn). |
| 2 | 2026-04-17 | 1 | Business context | Why custom tooling, what's the cost of not having it, why now? | Custom hardware/software integration with no dedicated tools; existing tools have gaps; manual tuning/setup is very difficult. | Scopes the project as gap-filling tooling that complements existing ecosystem tools rather than replacing them. |
| 3 | 2026-04-17 | 1 | Success definition | How will success be measured? | D — Combination of capability milestones (tooling) and a quantitative outcome (4 acres mowed autonomously). | Establishes mixed success model: feature-based milestones plus one real-world outcome metric. |
| 4 | 2026-04-17 | 2 | Primary user | Who will use this tooling? | A — Solo operator (owner = builder = operator). | CLI-first / power-user UX is acceptable; no need to abstract for other users or hardware variations in v1. |
| 5 | 2026-04-17 | 3 | Primary goals | What are the top goals? | A — Use proposed G-1..G-4 as-is. | Establishes four goals: bring-up, tuning, autonomous mowing, config snapshot/restore. |
| 6 | 2026-04-17 | 3 | Non-goals | What is explicitly out of scope? | A — Use proposed NG-1..NG-7 as-is. | Locks scope: tooling-only, no firmware/VSLAM authoring, no GCS replacement, no fleet/multi-user, no blade safety logic beyond mission orchestration. |
| 7 | 2026-04-17 | 4 | Functional requirements | What capabilities must the tooling provide? | A — Use proposed FR-1..FR-13 as-is. | Establishes 13 capabilities spanning bring-up, tuning, mission planning/execution, monitoring, post-run, snapshot/restore, and safe-stop. |
| 8 | 2026-04-17 | 4 | Non-functional requirements | Which quality attributes matter most? | Recommendation accepted: NFR must-haves = reliability, operability, safety, observability; reproducibility as should-have. | Locks NFR priorities; performance, maintainability, security treated as secondary. |
| 9 | 2026-04-17 | 4 | Constraints | Camera / Jetson variant / VSLAM / workstation OS, plus confirmation of inferred constraints. | OAK-D Pro depth camera; Jetson Orin Nano Super (8GB); VSLAM stack TBD (must run on Jetson); operator workstation = Windows laptop with mixed laptop/Jetson tooling split; C-1, C-2, C-3, C-7, C-8, C-9, C-10 confirmed as inferred. | Locks 10 constraints. VSLAM stack flagged as research topic. Cross-platform tooling (Windows + Linux) required. |
| 10 | 2026-04-17 | 5 | Solution style | What overall shape should the tooling take? | A — Suite of small, composable CLI utilities. | Establishes CLI-first architecture; complementary to Mission Planner/QGC; defers GUI investment. |
| 11 | 2026-04-17 | 5 | Technology decisions | Which tech choices to lock vs. defer? | A — Lock Python 3 / Typer / pymavlink (+ optional MAVSDK) / YAML+JSON / Git snapshots / structlog / uv+pipx / pytest+SITL / VISION_POSITION_ESTIMATE bridge. VSLAM stack, ROS-or-not, RTK base approach, and bridge transport deferred to research. | Locks core tooling stack; identifies four architecture-level research topics. |
| 12 | 2026-04-17 | 5 | Data contracts | Author contracts now or defer? | C — Defer to planner; record planned artifacts in vision. | Six planned artifacts noted; planner authors contracts once VSLAM stack and baseline params are settled. |
| 13 | 2026-04-17 | 4 | Constraints | Mower platform model. | Husqvarna Z254 (54" residential zero-turn, hydrostatic, twin-lever steering). | Adds C-7a; confirms dual-servo steering and sets physical envelope for mission planning. |
| 14 | 2026-04-17 | 6 | Foundational components | Are the proposed foundations the right set? | A — list confirmed (8 components, all in R1). | Locks foundation set; ensures cross-cutting concerns land in MVP. |
| 15 | 2026-04-17 | 6 | MVP definition | Which FRs are essential for Release 1? | A — proposed cut as-is. R1 = FR-1, 2, 3, 4, 5, 8, 9, 12, 13. R2 = FR-10, 11. R3 = FR-6, 7. | Locks MVP at RTK-only autonomous mowing; defers VSLAM and ops/iteration features. |
| 16 | 2026-04-17 | 6 | Release roadmap | How to group remaining FRs into releases? | A — three releases as proposed. | R1 = MVP, R2 = ops/iteration, R3 = VSLAM. Independently deployable; respects dependencies. |
| 17 | 2026-04-17 | 6 | R1 phase breakdown | Phase plan for Release 1? | A — 9 phases as proposed. | Bring-up sequence from foundation → MAVLink/HW → Jetson → params/snapshot → RTK → servo cal → tuning → mission → preflight/safe-stop. |
| 18 | 2026-04-17 | 6 | R2 phase breakdown | Phase plan for Release 2? | A — 2 phases (10 monitoring, 11 archive). | Small release; phases kept separate by category. |
| 19 | 2026-04-17 | 6 | R3 phase breakdown | Phase plan for Release 3? | A — 2 phases (12 stack, 13 bridge). | VSLAM stack first, then MAVLink bridge. Heavy research load deferred to research phase. |
| 20 | 2026-04-17 | 6 | Deferred capabilities | Items to capture as future possibilities? | A — list of 7 deferred items. | Local web UI, obstacle avoidance, fleet, sharing, magnetometer fallback, autorecharge, scheduling. |
| 21 | 2026-04-17 | 6 | Research topics | Final research topic list per release + cross-cutting? | A — 11 phase-specific + 2 cross-cutting topics. | Hands off detailed research plan to pch-researcher. |
| 22 | 2026-04-17 | 4 | Constraints | Specific RTK module model. | ArduSimple simpleRTK2B+heading (dual-antenna ZED-F9P + ZED-F9H moving-base; integrated module). | Refines C-2; updates Phase 5 scope and FR-3; clarifies that moving-base is integrated in one module rather than two boards. |
| 23 | 2026-04-17 | 4 | Constraints | Telemetry architecture. | Two SiK radios on the rover: one to the simpleRTK2B for RTCM corrections from a base-station SiK; one to the operator PC running Mission Planner for MAVLink. | Adds C-11; resolves much of the RTK base research (RTCM-over-SiK, not NTRIP); reframes MAVLink-over-Wi-Fi cross-cutting topic to MAVLink-over-SiK; adds RTCM-over-SiK link health as new cross-cutting research topic and a corresponding risk. |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-visionary |
| Created Date | 2026-04-17 |
| Status | ✅ Complete |
| Next Agent | pch-researcher (recommended — research per release) or pch-planner (per phase) |
| Path | /docs/vision/001-zero-turn-mower-rover.md |
