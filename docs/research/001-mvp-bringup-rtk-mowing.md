---
id: "001"
type: research
title: "Zero-Turn Mower Robotic Conversion — Release 1 (MVP): Bring-up + RTK-only Autonomous Mowing"
status: ✅ Complete
created: "2026-04-17"
current_phase: "Complete"
vision_source: /docs/vision/001-zero-turn-mower-rover.md
target_release: 1
---

## Introduction

This research investigates the open technical questions for **Release 1 (MVP)** of the zero-turn mower robotic conversion tooling project, as defined in vision document `001-zero-turn-mower-rover.md`. Release 1's goal is to deliver a CLI tooling suite that brings the robot from cold-boot to autonomous mowing of a 4-acre lawn using RTK-only positioning. The research covers SITL fidelity, MAVLink/RTK telemetry over SiK radios, ArduPilot baseline parameters for twin-servo skid-steer, RTK base station setup, servo selection, mission file formats, and safe-stop design — providing the planner with the answers needed to build detailed implementation plans for each MVP phase.

## Overview

All seven research phases for the Release 1 MVP are complete. The investigation confirms that the proposed architecture (Pixhawk Cube Orange + ArduPilot Rover + ArduSimple **simpleRTK3B Heading** (Septentrio mosaic-H) + dual back-driveable servos + dual SiK radios + Jetson Orin Nano) is technically sound for a residential 4-acre RTK-only autonomous mower, with no architectural changes required. The research surfaces concrete configuration values, library choices, hardware recommendations, and one important correction to the Phase 3 baseline.

> 🔄 **Hardware update (2026-04-17): two CALT GHW38 200 mm rubber-roller wheel encoders (200 PPR, push-pull quadrature output) will be added to the Cube Orange.** Mounting: each roller pressed against one drive-wheel tire → measures **true ground speed** (not just axle rotation), which enables wheel-slip detection (axle-driven hydrostatic torque vs. actual ground motion) and improves dead-reckoning when RTK degrades. **This supersedes the Phase 3 assumption "No wheel encoders for MVP (speed feedback from GPS only)."** Drives ArduPilot wheel-odometry params: `WENC_TYPE=1` / `WENC2_TYPE=1` (Quadrature), `WENC_CPR=800` and `WENC2_CPR=800` (200 PPR × 4 quadrature decode), `WENC_RADIUS=0.100` / `WENC2_RADIUS=0.100` (200 mm wheel → 0.100 m radius), `WENC_PINA/PINB` and `WENC2_PINA/PINB` set to free Cube Orange AUX pins (with `BRD_PWM_COUNT` reduced to free those AUX pins for GPIO), and `EK3_SRC1_VELXY=6` (use wheel encoders as primary horizontal-velocity source) once calibrated. **Electrical caveat:** GHW38 push-pull output level equals supply voltage — if powered at 12 V from the mower battery, the A/B signals must be level-shifted to 3.3 V before reaching the Cube Orange AUX inputs (recommended: bidirectional level shifter or simple resistor divider; Pixhawk AUX pins are NOT 12 V tolerant). Powering the encoders at 5 V is also viable but still exceeds 3.3 V — **level shifting is mandatory either way**. New Open Questions: AUX pin assignment for the 4 encoder lines (all 6 AUX pins are free since the three engine/blade relays use MAIN outputs `SERVO5/6/7`), encoder-to-tire pre-load force tuning, and `BRD_PWM_COUNT` value that converts the chosen AUX pins from PWM to GPIO for `WENC_PINA/PINB`.
>
> 🔄 **Hardware update (2026-04-17): An existing servo-signal-driven ignition cutoff relay is already installed on the mower, intended for emergency engine cutoff.** It accepts a standard 1000–2000 µs PWM control signal and is **fail-safe** (no signal / power loss = engine OFF, kill grounded). **Two additional servo-signal relays are also wired directly to Cube Orange MAIN servo outputs (not AUX): a starter motor relay (momentary — pulse-high to crank) and a blade clutch (PTO) relay (fail-safe OFF — no signal = blade disengaged).** Together these give the FC three independent engine/blade control outputs over standard PWM with no add-on hardware. This **supersedes the Bosch-style 30 A SPDT relay (~$10) BOM line** in the Overview and Phase 7 §3 — no add-on relay is required for the engine-kill path. Wire each relay's PWM input to a free Cube Orange MAIN `SERVOn` output (steering uses `SERVO1`/`SERVO3`, leaving `SERVO2`/`SERVO4`–`SERVO8` available; e.g. `SERVO5`=ignition-kill, `SERVO6`=starter, `SERVO7`=blade-clutch) configured with `SERVOn_FUNCTION=-1` (RCPassThru) or driven via `MAV_CMD_DO_SET_SERVO` from missions / `mower safe-stop` / `mower start-engine` / `mower blade`. **Because the relays use MAIN outputs, all 6 AUX pins (`SERVO9`–`SERVO14`) remain free — plenty for the 4 wheel-encoder inputs (A/B × 2) plus 2 spare AUX.** The physical E-stop button still grounds the ignition relay's signal line directly (or breaks its supply) so the cutoff is independent of the flight controller. The Phase 7 safe-stop architecture, defense-in-depth precedence, and spring-return-to-neutral chain are otherwise unchanged. **See the 🔄 callout at the top of Phase 7 §3 for details.**
>
> 🔄 **Hardware update (2026-04-17): GNSS receiver changed from simpleRTK2B+heading (dual u-blox ZED-F9P with moving-baseline RTK) to simpleRTK3B Heading (single Septentrio mosaic-H with internal dual-antenna attitude).** This is a major architectural change for Phase 3 §4 (GPS / RTK params): single GPS driver instead of two; SBF protocol instead of u-blox MB; heading computed inside the mosaic and exposed to ArduPilot via SBF `AttEuler`. The Phase 4 base-station design (simpleRTK2B Budget streaming RTCM3 over SiK) is unchanged — RTCM3 is interoperable; the rover chip swap does not affect base-station hardware. ✅ **ArduSimple publishes an official ArduPilot integration tutorial for this exact board** ([ardusimple.com/ardupilot-simplertk3b-heading-configuration](https://www.ardusimple.com/ardupilot-simplertk3b-heading-configuration/)), so integration risk is low. **See the 🔄 callout at the top of Phase 3 §4 for the superseded vs. new parameter table.** Older inline mentions of "simpleRTK2B+heading" and dual-F9P throughout phases 2–4 are retained for traceability of the original recommendation.

### Key Findings Summary

1. **SITL is a smoke-test harness, not a tuning tool.** ArduPilot's skid-steer Rover SITL uses a kinematic model (no hydrostatic dynamics, no engine vibration, no real servo response). Use SITL exclusively for tooling smoke-tests via pytest fixtures with `--instance=N` port isolation; all tuning must happen on real hardware. WSL2 or Docker on Windows.

2. **MAVLink-over-SiK is reliable across 4 acres** — at 200 m max range from operator, link margin is trivial. Use `pymavlink` with `autoreconnect=True`, `source_system=254`, and `RADIO_STATUS` (msg 109) monitoring for adaptive flow control. Hardware detection is straightforward: `GPS_RAW_INT.yaw` + `GPS2_RTK.iar_num_hypotheses==1` for heading verification; OAK-D Pro via DepthAI on Jetson via SSH.

3. **A complete Z254 ArduPilot baseline parameter set is identified** — `SERVO1_FUNCTION=73`, `SERVO3_FUNCTION=74` (ThrottleLeft/Right for skid-steer), `ATC_STR_RAT_FF=0.20`, `GPS1_TYPE=17`/`GPS2_TYPE=18` (moving-baseline), `EK3_SRC1_YAW=2` (GPS yaw), `COMPASS_USE=0` (no magnetometer). **Phase 7 corrects one Phase 3 value:** `FS_THR_ENABLE` must be **0** (not 1) for GCS-only operation, paired with `RC_PROTOCOLS=0`.

4. **RTK base = standalone simpleRTK2B Budget ($215)** — survey-in (1 h, 2.0 m) → switch to Fixed Mode workflow, RTCM3 message set sized to ~530 B/s (well within SiK 1.5 kB/s budget). `pyubx2` automates the u-center config; cold-start to RTK Fixed at the rover ≈ 35–60 s. Two SiK radios on the rover (constraint C-11): Radio A = RTCM passthrough (`MAVLINK=0`), Radio B = MAVLink to laptop.

5. **Selected servos: ASMC-04A Robot Servo High Torque 12–24 V** (×2, one per hydrostatic lever). The original research recommendation was Savox SB2290SG / Torxis i00600 (retained in Phase 5 §3 for traceability). **Control interface confirmed as standard 1000–2000 µs PWM** — wires directly to Cube Orange `SERVO1`/`SERVO3` outputs; no PWM-to-serial bridge needed. **Gear type confirmed as back-driveable** — the passive spring-return-to-neutral safety chain (Phase 7 §3) is intact. **One spec remains to verify before integration commit:** holding torque under engine vibration. **Gas dampers must be removed** from Z254 lap bars (standard ArduPilot ZTR community practice; reduces servo torque requirement ~40 %). The 12–24 V supply runs directly off the mower battery — no high-current 7.4 V BEC needed.

6. **Mission planning uses a dual-format approach** — YAML mission definition (source of truth, Git-versionable) → generated `.waypoints` (ArduPilot upload + Mission Planner QA) + GeoJSON (visualization). **Shapely + pyproj custom boustrophedon implementation is recommended for MVP** (fits uv/pipx packaging); Fields2Cover is the upgrade path for complex field shapes. **ArduPilot Rover has native pivot-turn support** (`WP_PIVOT_ANGLE=60`) — coverage planner emits straight-line pass endpoints only; no explicit headland-turn waypoints needed.

7. **Pre-flight is a 6-tier / 33-check inventory** with CRITICAL vs. WARN levels and structured JSON output. **Hold (not RTL) is the correct default failsafe for a mower** — RTL drives in a straight line potentially through obstacles. **Physical E-stop has absolute authority** — cuts ignition + servo power via hardware relay; ArduPilot cannot override. **`FS_OPTIONS=1` is critical** — without it, failsafes are silently ignored once the vehicle is already in Hold mode.

### Cross-Cutting Patterns

- **Defense in depth on safety:** Physical E-stop (absolute) → ArduPilot Hold/Disarm → Software RTL → Mission pause. Spring-return-to-neutral mechanical property links the E-stop electrical layer to the hydrostatic mechanical layer with no software in the loop.
- **GCS-only operation throughout:** No RC transmitter is held during autonomous mowing. This drives `FS_THR_ENABLE=0`, `RC_PROTOCOLS=0`, mandatory `FS_GCS_ENABLE=1`, and the structured pre-flight + safe-stop CLI commands.
- **Per-side calibration is mandatory:** Left and right hydrostatic transaxles will NOT be symmetric (manufacturing tolerances, linkage geometry, servo tolerances). The `mower servo-cal` utility produces independent profiles for SERVO1 and SERVO3 including TRIM, MIN, MAX, REVERSED, and forward/reverse deadband.
- **Snapshot + diff for state management:** Param snapshots (Phase 3), mission YAML (Phase 6), calibration profiles (Phase 5), pre-flight reports (Phase 7) — all human-readable, Git-versionable, and round-trip-verifiable. JSON for machine-readable outputs (snapshots, pre-flight reports); YAML for human-edited inputs (config, mission, calibration).
- **Jetson is operationally independent for MVP:** Jetson runs monitoring, log collection, and (Release 3) VSLAM — but it's not in the ArduPilot control loop for RTK-only mowing. Jetson crash does not affect mowing; ArduPilot disarm does not affect Jetson. Independence simplifies failure analysis.
- **Native ArduPilot features are leveraged, not duplicated:** native pivot-turn support (Phase 6), native mission resume via `MISSION_CURRENT` (Phase 7), built-in pre-arm checks surfaced via STATUSTEXT (Phase 7), native EKF + failsafe machinery.

### Actionable Conclusions

- **No architectural changes required.** The vision-defined hardware stack and software stack are sound. Proceed to planning.
- **Update Phase 3 baseline** before planning: `FS_THR_ENABLE=0`, `RC_PROTOCOLS=0`, add `FS_OPTIONS=1`, `FS_CRASH_CHECK=2`, `CRASH_ANGLE=30`, `FS_EKF_ACTION=2`.
- **Use Shapely + pyproj for coverage planning, not Fields2Cover** — fits the uv/pipx packaging constraint and runs natively on Windows. Keep Fields2Cover as a documented upgrade path.
- **Use a dual-format mission file** (YAML source → `.waypoints` + GeoJSON outputs).
- **Hardware bill of materials is firm enough to commit:** ArduSimple **simpleRTK3B Heading (Septentrio mosaic-H, ~$874 USD)** rover — single-board solution with two antenna inputs, replaces the originally-recommended dual-F9P simpleRTK2B+heading; simpleRTK2B Budget base ($215, unchanged — RTCM3 is interoperable); 2× **matched** multi-band L1/L2/E5b GNSS antennas with **identical cable lengths** (e.g. simpleANT2B Budget Survey ~$111 each, NOT included with the heading board); **ASMC-04A Robot Servo High Torque 12–24 V × 2 (SELECTED)** — PWM control + back-driveable gears confirmed; **CALT GHW38 200 mm rubber-roller wheel encoders × 2 (200 PPR, push-pull quadrature)** — pressed against drive-wheel tires for true ground-speed measurement; level shifter required (12 V or 5 V encoder output → 3.3 V FC AUX pins); Schneider XB4-BS8442 mushroom E-stop (~$20); ~~Bosch-style 30 A SPDT relay (~$10)~~ **superseded — existing PWM-driven ignition cutoff relay already on mower (fail-safe, 1000–2000 µs control); no add-on relay needed**; 2× SiK radios on rover (constraint C-11) + 1 paired on laptop + 1 paired on base.
- **Plan SITL test fixtures from the start** — every CLI command should have a SITL-mode dry-run path (especially `mower servo-cal` and `mower preflight`).
- **The Phase 1 SITL constraint flows everywhere:** SITL is for smoke-testing CLI behavior, not for tuning ArduPilot. The planner should not propose any tuning workflow that depends on SITL fidelity.

### Open Questions (for planning + field validation)

These are the residual gaps that the planner should plan around or that require field validation during MVP execution:

- **⚠️ ASMC-04A datasheet capture (non-blocking, integration-time):** control interface confirmed as standard 1000–2000 µs PWM (wires directly to Cube Orange `SERVO1`/`SERVO3`); gear type confirmed back-driveable (safe-stop chain intact). Still useful to capture for sizing/tuning: stall/continuous torque at 12 V and 24 V, no-load speed, travel range, current draw, position-feedback resolution, IP rating, connector pinout, inrush current, PWM pulse-width range / dead-band, and holding-torque behavior under engine vibration.
- **Z254-specific physical measurements:** lever force (spring-scale at handle, dampers removed), linkage geometry that achieves 78–98 mm servo throw covering full lever range (with ASMC-04A mounting + arm), Kawasaki FR691V ignition kill wire identification.
- **SITL verification needed:** `FENCE_ACTION=2` (Hold) on Rover (documented for Copter); `FS_THR_ENABLE=0` + `RC_PROTOCOLS=0` clean GCS-only arming with no false RC failsafe.
- **Field tuning (ground truth needed):** `CRUISE_THROTTLE` via "Learn Cruise" run, `ATC_STR_RAT_FF` refinement, `SERVO1/3_REVERSED` polarity, `MOT_THR_MIN` (hydrostatic deadband), `WP_PIVOT_RATE` for smooth-but-fast row-end turns, actual RTCM bandwidth at the user's location.
- **Boundary collection workflow:** RTK GPS perimeter walk vs. Google Earth trace — to be decided based on operator preference.
- **Mission item count ceiling on Cube Orange** with the deployed firmware version (estimated 700+; needs confirmation).
- **Hardware sourcing:** SiK radio pair purchase (separately or with ArduSimple kit), high-current servo BEC selection (2-4 A per Savox SB2290SG at 7.4 V).
- **Power budget verification:** servo BEC at 7.4 V or use Torxis at 12 V from mower battery. **Selected ASMC-04A is 12–24 V native off the mower battery — no high-current 7.4 V BEC needed; size inline fuse per ASMC-04A current spec.**

## Objectives

- Determine ArduPilot SITL fidelity for twin-lever skid-steer Rover and how the tooling should use SITL (smoke-test only vs. tuning-capable).
- Characterize MAVLink-over-SiK reliability (range, dropouts, recovery) for a 4-acre yard and its impact on mission upload, monitoring, and pre-flight.
- Identify a known-good ArduPilot Rover baseline parameter set for a Husqvarna Z254 with twin-servo steering arms.
- Decide the RTK base station approach (hardware, survey-in vs. fixed coords, RTCM message set sized for SiK link).
- Validate servo selection/specs for actuating Z254 hydrostatic levers under load.
- Choose a mission file format (Mission Planner `.waypoints` reuse vs. custom YAML) and a coverage-pattern generation source for a 54" deck.
- Design the pre-flight check inventory and the safe-stop mechanism (physical E-stop + software RTL + Jetson clean shutdown interaction model).
- Characterize RTCM-over-SiK link health (bandwidth fit, monitoring, fix-degradation behavior).

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | ArduPilot SITL fidelity for skid-steer Rover | ✅ Complete | SITL accuracy for twin-lever skid-steer dynamics; what tooling can validate in SITL vs. requires field; pytest fixture implications | 2026-04-17 |
| 2 | MAVLink-over-SiK reliability + hardware detection patterns | ✅ Complete | SiK MAVLink range/dropout behavior across 4 acres; recovery patterns; pymavlink connection retry idioms; hardware enumeration patterns for Pixhawk/RTK/servos/Jetson/OAK-D Pro | 2026-04-17 |
| 3 | ArduPilot Rover baseline params for Z254 twin-servo skid-steer | ✅ Complete | Community precedents for twin-servo steering-arm skid-steer Rover param sets; SERVOn_FUNCTION mapping; skid-steer mixing params; Pixhawk Cube Orange Rover defaults; param diff/snapshot conventions | 2026-04-17 |
| 4 | RTK base station approach + simpleRTK2B+heading configuration | ✅ Complete | Base hardware options (second simpleRTK2B vs. SBC+RTKLIB vs. hybrid); survey-in vs. fixed-coords; RTCM message set/rate sized for SiK bandwidth; RTCM-over-SiK link health monitoring; u-center config workflow for moving-base rover; fix-quality + yaw-quality verification | 2026-04-17 |
| 5 | Servo selection/specs for Z254 hydrostatic lever actuation | ✅ Complete | Torque/speed required to actuate Z254 levers under load; servo candidates; PWM range/endpoint conventions; calibration utility design (per-side endpoints, neutral, deadband); safety-primitive integration | 2026-04-17 |
| 6 | Mission file format + coverage pattern generation for 54" deck | ✅ Complete | Mission Planner `.waypoints` format vs. custom YAML; round-trip via MAVLink mission protocol; coverage-pattern generators (boustrophedon, exclusion zones); line spacing for 54" cutting width; visualization options | 2026-04-17 |
| 7 | Pre-flight check inventory + safe-stop mechanism design | ✅ Complete | Pre-flight check list (HW, RTK fix, params match, mission loaded); safe-stop interaction model (physical E-stop authority + software RTL + Jetson clean shutdown); ArduPilot fail-safe params relevant to RTK loss; structured failure output | 2026-04-17 |

## Phase 1: ArduPilot SITL fidelity for skid-steer Rover

**Status:** ✅ Complete
**Session:** 2026-04-17

### SITL Skid-Steer Physics Model — Source Code Analysis

The SITL Rover skid-steer model is defined in `libraries/SITL/SIM_Rover.cpp` and `SIM_Rover.h`. It is activated by including `"skid"` in the frame string (e.g., `rover-skid`).

**Frame initialization** (`SimRover` constructor):

```cpp
skid_steering = strstr(frame_str, "skid") != nullptr;
if (skid_steering) {
    printf("SKID Steering Rover Simulation Started\n");
    // these are taken from a 6V wild thumper with skid steering,
    // with a sabertooth controller
    max_accel = 14;   // m/s² (hard-coded)
    max_speed = 4;    // m/s  (hard-coded)
    return;
}
```

Additional hard-coded class members: `float skid_turn_rate = 140.0f;` (max turn rate in deg/sec).

**Core physics update** (skid-steering branch):

```cpp
// Servo inputs → steering + throttle via differential mixing
const float motor1 = input.servos[0] ? normalise_servo_input(input.servos[0]) : 0;
const float motor2 = input.servos[2] ? normalise_servo_input(input.servos[2]) : 0;
steering = motor1 - motor2;
throttle = 0.5*(motor1 + motor2);

// Yaw rate from steering input
float yaw_rate = calc_yaw_rate(steering, speed);

// Target speed — linear mapping from throttle
float target_speed = throttle * max_speed;

// Acceleration — crude first-order model toward target
float accel = max_accel * (target_speed - speed) / max_speed;
```

**Conclusion: This is a purely kinematic model.** It does NOT model: tire-ground friction/slip, vehicle mass/inertia/COG, hydrostatic transmission response, servo response time/deadband/endpoints, terrain (slopes, grass, soft ground), weight transfer, or asymmetric left/right motor response.

### Servo Channel Mapping in SITL

The SITL model reads `servos[0]` (channel 1) and `servos[2]` (channel 3). For ArduPilot Rover skid-steer, the firmware-side mapping uses:

| Servo Function | Value | Channel | Role |
|---|---|---|---|
| `SRV_Channel::k_throttleLeft` | 73 | SERVO1 | Left motor |
| `SRV_Channel::k_throttleRight` | 74 | SERVO3 | Right motor |

Skid-steer is **auto-detected** by `AP_MotorsUGV::have_skid_steering()` when both `SERVO1_FUNCTION=73` AND `SERVO3_FUNCTION=74` are assigned. **Rover does NOT use `FRAME_CLASS` for skid-steer selection** — no FRAME_CLASS or MOT_* frame parameter is required.

### Key Parameters for SITL Skid-Steer

| Parameter | Purpose | Notes |
|---|---|---|
| `SERVO1_FUNCTION = 73` | ThrottleLeft | Required for skid-steer |
| `SERVO3_FUNCTION = 74` | ThrottleRight | Required for skid-steer |
| `MOT_THR_MAX` / `MOT_THR_MIN` | Throttle bounds | Caps output to motors |
| `MOT_SLEWRATE` | Throttle slew rate limit | Smooths transitions |
| `ATC_STR_RAT_*` | Steering rate PID | Field-tune; SITL = smoke-test only |
| `ATC_SPEED_*` | Speed PID | Field-tune; SITL = smoke-test only |
| `CRUISE_SPEED` / `CRUISE_THROTTLE` | AUTO mode targets | Field-tune |

### Launching SITL as Skid-Steer Rover

```bash
sim_vehicle.py -v Rover -f rover-skid --console --map --no-mavproxy
```

Or run the binary directly:

```bash
./build/sitl/bin/ardurover --model rover-skid --home -35.362938,149.165085,585,270
```

The `--no-mavproxy` flag is critical for programmatic use — SITL listens on TCP port 5760 without launching MAVProxy.

### What Can Be Validated in SITL (high confidence)

| Capability | Notes |
|---|---|
| MAVLink connection layer | TCP `127.0.0.1:5760`; pymavlink connects identically |
| Hardware-detection logic | SITL reports HEARTBEAT with MAV_TYPE_GROUND_ROVER |
| Param apply/snapshot/restore | Full-fidelity round-trip |
| Mission upload/readback | MISSION_ITEM_INT protocol fully exercised |
| Pre-flight check logic | Checks run; RTK-specific checks won't see real RTK fix |
| Safe-stop / RTL behavior | Mode changes work identically |
| Tuning iteration mechanics | propose → apply → verify round-trip works |
| Mode transitions | MANUAL/GUIDED/AUTO/RTL/HOLD/STEERING all functional |
| Failsafe triggers | Throttle, GCS, battery (via SIM_* params) |
| Servo function assignment | Mixing logic runs on firmware side, identical to real HW |
| Fence / geofence | Fully functional |

### What MUST Be Validated on Real Hardware

| Capability | Why SITL fails |
|---|---|
| Final PID values | Kinematic model has no real dynamics |
| Servo endpoints/deadband | No servo model in SITL |
| `CRUISE_SPEED`/`CRUISE_THROTTLE` | SITL `max_speed=4` m/s hard-coded; Z254 differs |
| Turn behavior | SITL `turn_rate=140°/s` constant; real depends on friction, geometry |
| RTK fix quality, dual-antenna yaw | SITL GPS is synthetic; no RTK model |
| VSLAM | No camera simulation |
| MAVLink-over-SiK radio | SITL uses TCP/UDP loopback; no radio behavior |
| Mower dynamics under load | No terrain, mass, transmission model |
| Physical E-stop chain | Software RTL works; physical wiring must be tested |

### pytest Fixture Design

**Recommended architecture:**

```
conftest.py
├── sitl_binary()          — session-scoped: locate or build SITL binary
├── sitl_instance()        — function-scoped: launch SITL process (per worker)
├── mav_conn()             — function-scoped: pymavlink connection
└── with_skid_steer_params()  — function-scoped: seed baseline skid-steer params
```

**SITL launcher fixture (port-isolated for pytest-xdist):**

```python
import subprocess, time, pytest
from pymavlink import mavutil

@pytest.fixture(scope="function")
def sitl_instance(tmp_path, worker_id):
    instance = 0 if worker_id == "master" else int(worker_id.replace("gw", ""))
    tcp_port = 5760 + 10 * instance
    cmd = [
        "sim_vehicle.py", "-v", "Rover", "-f", "rover-skid",
        "--instance", str(instance),
        "--no-mavproxy", "--no-rebuild", "-w",
        "-S", "10",  # speedup
        "--home", "-35.362938,149.165085,585,270",
    ]
    proc = subprocess.Popen(cmd, cwd=tmp_path,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(5)  # crude; better: poll TCP port
    yield {"process": proc, "tcp_port": tcp_port, "instance": instance}
    proc.terminate()
    proc.wait(timeout=10)

@pytest.fixture
def mav_conn(sitl_instance):
    conn = mavutil.mavlink_connection(
        f"tcp:127.0.0.1:{sitl_instance['tcp_port']}",
        source_system=255, source_component=0,
    )
    conn.wait_heartbeat(timeout=30)
    yield conn
    conn.close()
```

**Parallel execution:** `--instance=N` shifts all SITL ports by `10*N`. Map xdist `worker_id` (`gw0`, `gw1`, …) to instance N to prevent collisions.

**Cleanup:** Always `proc.terminate()` + `proc.wait(timeout=10)`; use `tmp_path` for SITL working dir (logs, eeprom.bin) to avoid cross-test contamination; in CI, `pkill -f ardurover` as a safety net.

**Test categorization:** Use markers (`@pytest.mark.sitl`, `@pytest.mark.field`) to separate SITL-validatable tests from field-required tests.

### Windows-Host Considerations

ArduPilot officially recommends **WSL2** for Windows:

| Approach | Setup | CI compat | Notes |
|---|---|---|---|
| WSL2 (SITL + pytest both inside) | ★★★★ | ★★★ | Recommended for dev |
| WSL2 SITL + Windows pytest | ★★★ | ★★ | Cross-boundary networking via `localhost` |
| Docker (`ardupilot/ardupilot-dev-base`) | ★★★ | ★★★★★ | Best for CI |
| Cygwin | ★ | ★ | Deprecated by ArduPilot |

**CI:** GitHub Actions `ubuntu-latest`; install deps via `Tools/environment_install/install-prereqs-ubuntu.sh`; build with `./waf configure --board sitl && ./waf rover`. No pre-built SITL binaries on `firmware.ardupilot.org` (those are for real HW). Use `--speedup=10+` and generous fixture timeouts (5-15s startup).

### Risk Assessment — Vision Risk Confirmed

**Vision risk:** "ArduPilot SITL doesn't faithfully simulate twin-lever skid-steer dynamics; tuning utilities validate in SITL but fail on real hardware."

**Confirmed with source-code evidence:**

1. Kinematic only — no tire friction, mass, inertia, hydrostatic modeling
2. Hard-coded to a 6V Wild Thumper RC car (per source comments) — not a 700lb hydrostatic mower
3. Fixed compile-time params (`max_speed=4`, `max_accel=14`, `skid_turn_rate=140`) — not configurable

**Refined mitigation:**

- SITL is **excellent** for tooling smoke-tests (connection, params, mission protocol, modes, failsafes — all real ArduPilot code paths)
- SITL is **NOT useful** for tuning validation — any PID/speed values tuned against SITL will not transfer
- pytest fixtures should clearly separate SITL-validatable from field-required tests via markers
- Phase 7 (Guided Tuning) done criteria must explicitly require field validation (vision already calls this out)

**Key Discoveries:**

- The SITL `rover-skid` model is **purely kinematic** — no mass, friction, inertia, or transmission response. Based on a "6V Wild Thumper" RC car, not a full-size mower.
- Skid-steer is NOT activated by `FRAME_CLASS`; it is auto-detected when `SERVO1_FUNCTION=73` AND `SERVO3_FUNCTION=74` are assigned.
- SITL hard-coded constants (`max_speed=4`, `max_accel=14`, `skid_turn_rate=140`) are compile-time, not configurable via ArduPilot params.
- Servo input mapping: `servos[0]` (ch1=left), `servos[2]` (ch3=right); mixing is `steering = left - right`, `throttle = avg(left, right)`.
- ArduPilot's autotest (`Tools/autotest/rover.py`) is rich reference material but uses pexpect, not pytest — fixtures must be custom-built.
- **WSL2 is the officially recommended** Windows SITL environment; Cygwin is deprecated; Docker is good for CI.
- Port isolation via `--instance=N` (shifts ports by 10×N) is the key to parallel pytest-xdist.
- Vision risk **confirmed**: SITL is smoke-test only; field validation is mandatory for tuning, servo cal, and RTK.

| File / Path | Relevance |
|---|---|
| `ArduPilot/ardupilot/libraries/SITL/SIM_Rover.cpp` | Core SITL Rover physics (kinematic skid-steer update loop) |
| `ArduPilot/ardupilot/libraries/SITL/SIM_Rover.h` | SimRover class with hard-coded constants |
| `ArduPilot/ardupilot/libraries/AR_Motors/AP_MotorsUGV.cpp` | Firmware skid-steer mixing (`output_skid_steering`, `have_skid_steering`) |
| `ArduPilot/ardupilot/Tools/autotest/rover.py` | Autotest patterns for Rover (param setting, mode transitions) |
| `ArduPilot/ardupilot/Tools/autotest/pysim/util.py` | `start_SITL()` SITL launch patterns |
| `ArduPilot/ardupilot/Tools/autotest/sim_vehicle.py` | Frame selection, port config, `--instance` |
| `ArduPilot/ardupilot/Tools/autotest/vehicle_test_suite.py` | Base TestSuite class |
| `ArduPilot/ardupilot/libraries/SITL/examples/Morse/rover_skid.py` | Confirms `SERVO1=73`, `SERVO3=74` |

**External Sources:**

- [ArduPilot SITL usage guide](https://ardupilot.org/dev/docs/using-sitl-for-ardupilot-testing.html) — frame types, sim_vehicle.py options
- [SITL architecture overview](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html)
- [Building SITL on Windows 11 (WSL2)](https://ardupilot.org/dev/docs/building-setup-windows11.html) — recommended Windows path
- [SITL Native on Windows (Cygwin)](https://ardupilot.org/dev/docs/sitl-native-on-windows.html) — deprecated
- [pymavlink Python guide](https://mavlink.io/en/mavgen_python/) — connection strings, recv_match, param set/get

**Gaps:** None
**Assumptions:** Assumed WSL2 or Docker rather than native Windows SITL (consistent with ArduPilot recommendation and constraint C-6). Assumed pytest-xdist for parallel execution.

## Phase 2: MAVLink-over-SiK reliability + hardware detection patterns

**Status:** ✅ Complete
**Session:** 2026-04-17

### Part A — MAVLink-over-SiK Reliability (4-Acre Yard)

**Range assessment.** Standard SiK radios (Si1000-based: Holybro SiK v2, 3DR clones, ArduSimple modems): 20 dBm (100 mW) Tx, -121 dBm Rx sensitivity, 433 or 915 MHz with FHSS, demonstrated multi-km range with stock omni antennas. A 4-acre lawn diagonal is ~180 m — well within capability with 30+ dB fade margin. **No antenna or power upgrades required** for either Radio A (RTCM) or Radio B (MAVLink).

**Dropout/recovery behavior.** SiK uses synchronous adaptive TDM. Degradation is gradual, not cliff-edge:

1. RSSI drops with distance — `RADIO_STATUS` reports rssi, remrssi, noise, remnoise in real time
2. ECC (Golay 12/24) can correct up to 25% BER if enabled, at cost of half bandwidth
3. On full link loss, receiver sweeps frequencies while Tx hops normally; re-sync takes a few seconds at AIR_SPEED=64 / 50 channels
4. ArduPilot triggers GCS failsafe after `FS_GCS_TIMEOUT` (default 5s) of missed heartbeats
5. At 200m, dropouts should be extremely rare with stock hardware; common at-range issues are USB noise on the laptop and motor/ESC EMI on the vehicle, not propagation

**Air rate / baud / Tx power tradeoffs (recommended settings):**

| Setting | Default | Recommended |
|---------|---------|-------------|
| `AIR_SPEED` | 64 kbps | 64 kbps (ample for 200m) |
| `SERIAL_SPEED` | 57600 | 57600 (auto-throttled via `RADIO_STATUS.txbuf`) |
| `TXPOWER` | 20 dBm | 20 dBm (legal in US 915 MHz ISM) |
| `ECC` | 0 | 0 — at 200m, ECC unnecessary and halves bandwidth |
| `MAVLINK` | 1 | 1 for Radio B (telemetry); **0 for Radio A** (RTCM raw passthrough) |
| `NUM_CHANNELS` | 50 | 50 (FHSS compliance, good re-sync) |

ArduPilot auto-adapts telemetry rates downward using `RADIO_STATUS.txbuf` (transmit buffer fill %), so `SERIAL_SPEED` can safely exceed sustainable air throughput.

**Stream rates and bandwidth budget** (SR1_* on SERIAL1 for telemetry):

| Stream Group | Messages | Recommended Hz |
|---|---|---|
| `SR1_EXT_STAT` | SYS_STATUS, GPS_RAW_INT, GPS_RTK, GPS2_RAW, GPS2_RTK, MISSION_CURRENT | 2 |
| `SR1_POSITION` | GLOBAL_POSITION_INT, LOCAL_POSITION_NED | 2 |
| `SR1_RC_CHAN` | SERVO_OUTPUT_RAW, RC_CHANNELS | 2 |
| `SR1_EXTRA1` | ATTITUDE | 4 |
| `SR1_EXTRA3` | BATTERY_STATUS, VIBRATION, EKF_STATUS_REPORT | 2 |
| `SR1_RAW_SENS` | RAW_IMU, SCALED_PRESSURE | 1 |

Effective throughput at AIR_SPEED=64 / no ECC ≈ 7 KB/s. Estimated total telemetry traffic ≈ 600-800 B/s — comfortably under capacity.

**Mission upload over lossy links.** MAVLink mission protocol (MISSION_COUNT → per-item MISSION_REQUEST_INT / MISSION_ITEM_INT → MISSION_ACK) is inherently robust: each item is individually re-requested on loss. SiK's MAVLINK=1 framing discards corrupt packets at the radio, so the protocol's retry mechanism handles dropped frames cleanly.

**Heartbeat liveness.** Both ends send `HEARTBEAT` at 1 Hz. Ground-side tools should treat absence >3-5 s as link loss. Inspect `RADIO_STATUS` (msg 109) for live link quality (rssi, remrssi, txbuf, noise, remnoise, rxerrors, fixed counts).

### Part B — pymavlink Connection Retry Idioms

**Connection strings.** `mavutil.mavlink_connection()` selects transport by prefix:

```python
from pymavlink import mavutil

# Serial — Windows
conn = mavutil.mavlink_connection('COM3', baud=57600)
# Serial — Linux/Jetson
conn = mavutil.mavlink_connection('/dev/ttyUSB0', baud=57600)
# TCP client (SITL)
conn = mavutil.mavlink_connection('tcp:127.0.0.1:5760')
# UDP listen / send
conn = mavutil.mavlink_connection('udpin:0.0.0.0:14550')
conn = mavutil.mavlink_connection('udpout:192.168.1.10:14550')
```

For this project, the primary Windows-side connection to Radio B is:

```python
conn = mavutil.mavlink_connection('COM3', baud=57600,
                                  source_system=254, source_component=1)
```

**`wait_heartbeat` pattern.** Internally just `recv_match(type='HEARTBEAT', blocking, timeout)`. After the first heartbeat, pymavlink auto-sets `target_system` / `target_component`.

**Reconnection idiom.** pymavlink does NOT auto-reconnect by default. Two options:

```python
# Option 1 — built-in (mavserial only)
conn = mavutil.mavlink_connection('COM3', baud=57600,
                                  autoreconnect=True)

# Option 2 — explicit retry loop (recommended for tooling)
def connect_with_retry(device, baud, max_retries=5, retry_delay=2.0):
    for attempt in range(1, max_retries + 1):
        try:
            conn = mavutil.mavlink_connection(
                device, baud=baud,
                source_system=254, source_component=1,
                autoreconnect=True,
            )
            if conn.wait_heartbeat(timeout=10) is not None:
                return conn
        except Exception as e:
            logger.warning("connection_failed", attempt=attempt, error=str(e))
        time.sleep(retry_delay)
    raise ConnectionError(f"Failed to connect after {max_retries} attempts")
```

**Important:** Even with `autoreconnect=True`, the application must re-call `wait_heartbeat()` after a reconnect — pymavlink reopens the serial port but does not re-establish the MAVLink session.

**MAVLink 1 vs. 2.** ArduPilot 4.x and pymavlink default to MAVLink 2; auto-detected from received messages. MAVLink 2 is required for extension fields like `GPS_RAW_INT.yaw` (dual-antenna heading). Use MAVLink 2 — no special config needed.

**Multi-connection (sharing the link with Mission Planner).** Three options:

1. **MAVProxy multiplexer** (recommended for dev):
   ```
   mavproxy.py --master=COM3,57600 --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551
   ```
   Mission Planner → `udpin:127.0.0.1:14550`; mower CLI → `udpin:127.0.0.1:14551`.

2. **mavlink-router** (lightweight C++ daemon, better for production / unattended use)

3. **Direct serial with tool exclusivity** — close Mission Planner before running `mower hw-check`. Simplest for MVP.

**System/component ID conventions:**

| Entity | sysid | compid | Notes |
|---|---|---|---|
| Pixhawk autopilot | 1 | 1 (MAV_COMP_ID_AUTOPILOT1) | Standard |
| Mission Planner | 255 | 0 / 190 | Traditional GCS |
| MAVProxy | 255 | 0 | Shares with MP |
| **Mower tooling** | **254** | **1** | Avoids collision with MP |
| SiK Radio | 51 | 68 | Auto-injects RADIO_STATUS |

Use `source_system=254, source_component=1` for the mower CLI to avoid clashing with Mission Planner.

### Part C — Hardware Enumeration Patterns

#### 1. Pixhawk (via MAVLink)

```python
hb = conn.wait_heartbeat(timeout=10)
is_rover = (hb.type == mavutil.mavlink.MAV_TYPE_GROUND_ROVER)        # 10
is_ardupilot = (hb.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA)  # 3
is_armed = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
```

Request `AUTOPILOT_VERSION` (msg 148) for firmware/board info via `MAV_CMD_REQUEST_MESSAGE` (cmd 512):

```python
conn.mav.command_long_send(
    conn.target_system, conn.target_component,
    mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
    148, 0, 0, 0, 0, 0, 0)
av = conn.recv_match(type='AUTOPILOT_VERSION', blocking=True, timeout=5)
# Decode flight_sw_version: major.minor.patch.fw_type (4 bytes)
# av.board_version, av.uid (64-bit), av.capabilities (MAV_PROTOCOL_CAPABILITY bitmask)
```

`SYS_STATUS` provides sensor health bitmasks (`onboard_control_sensors_present/enabled/health`). Key bits from `MAV_SYS_STATUS_SENSOR`: GPS=0x20, gyro=0x01, accel=0x02, mag=0x04, baro=0x08, AHRS=0x200000, battery=0x2000000.

#### 2. simpleRTK2B+heading (via Pixhawk MAVLink)

The module attaches to a Pixhawk SERIAL port and presents as GPS1 (and GPS2 for the secondary heading receiver). Detect entirely through MAVLink GPS messages.

`GPS_RAW_INT` — primary fix and RTK status:

```python
FIX_NAMES = {0:'NO_GPS', 1:'NO_FIX', 2:'2D_FIX', 3:'3D_FIX',
             4:'DGPS', 5:'RTK_FLOAT', 6:'RTK_FIXED', 7:'STATIC', 8:'PPP'}
gps = conn.recv_match(type='GPS_RAW_INT', blocking=True, timeout=5)
has_rtk = gps.fix_type >= 5
has_fixed_rtk = gps.fix_type == 6
# Dual-antenna heading (MAVLink 2 extension field):
# yaw: 0 = not provided; UINT16_MAX (65535) = configured but unavailable; 36000 = north
has_heading = (gps.yaw not in (0, 65535))
heading_deg = gps.yaw / 100.0 if has_heading else None
```

`GPS2_RAW` for the secondary receiver, `GPS_RTK` / `GPS2_RTK` for baseline & RTK health. **`GPS2_RTK.iar_num_hypotheses == 1`** is the definitive indicator that the moving-base RTK ambiguity is resolved (heading solution valid). The baseline_a/b/c vector length should match the physical antenna separation.

ArduPilot params confirming dual-GPS config: `GPS_TYPE2=1`, `GPS_AUTO_CONFIG=1`.

#### 3. Servos (via Pixhawk)

No direct telemetry. Verify indirectly:

```python
# SERVO_OUTPUT_RAW shows live PWM output (port=0=MAIN, 1=AUX)
servo = conn.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=5)
# Param check: SERVO1_FUNCTION must be 73 (ThrottleLeft), SERVO3_FUNCTION = 74 (ThrottleRight)
conn.mav.param_request_read_send(conn.target_system, conn.target_component,
                                  b'SERVO1_FUNCTION', -1)
p = conn.recv_match(type='PARAM_VALUE', blocking=True, timeout=5)
```

#### 4. Jetson Orin Nano Super (SSH-based)

Detect via SSH from the Windows PC:

```python
def detect_jetson(host="jetson.local"):
    info = {}
    # Model: /proc/device-tree/model → "NVIDIA Jetson Orin Nano"
    # JetPack/L4T: /etc/nv_tegra_release → "# R36 (release), REVISION: 4.0, ..."
    # tegrastats availability: which tegrastats
    # Memory: free -h
    return info
```

#### 5. OAK-D Pro (on Jetson, via DepthAI SDK)

Runs on the Jetson (camera is plugged into Jetson USB), so the Windows-side `mower hw-check` invokes this over SSH:

```python
import depthai as dai
infos = dai.DeviceBootloader.getAllAvailableDevices()
for info in infos:
    state = str(info.state).split('X_LINK_')[1]  # 'UNBOOTED', 'BOOTED', etc.
    # info.name (USB path or PoE IP), info.mxid (unique chip ID)
# For details: boot the device, then device.getCameraSensorNames(),
# device.readCalibration().getEepromData() (productName, boardName), device.getUsbSpeed()
```

**Key Discoveries:**

- **4-acre range (~200 m) is trivially within stock SiK capability** (demonstrated several km). No antenna/power upgrades needed for either Radio A (RTCM) or Radio B (MAVLink).
- **`RADIO_STATUS` (msg 109)** is the critical link-quality message — SiK firmware injects it into the MAVLink stream when `MAVLINK=1`. Includes rssi, remrssi, txbuf, noise, remnoise, rxerrors, fixed.
- ArduPilot **auto-adapts telemetry rates** using `RADIO_STATUS.txbuf` percentage, so `SERIAL_SPEED` can safely exceed sustainable air throughput.
- **Default AIR_SPEED=64, MAVLINK=1, ECC=0** is the right baseline for Radio B; **MAVLINK=0** for Radio A (RTCM is raw, not MAVLink-framed).
- **pymavlink does NOT auto-reconnect by default**; `autoreconnect=True` must be explicitly set, and the app must re-call `wait_heartbeat()` after reconnect.
- **Use `source_system=254, source_component=1`** for the mower CLI to avoid clashing with Mission Planner's sysid=255. For multi-GCS scenarios, use **MAVProxy or mavlink-router** as a UDP multiplexer.
- **`GPS_RAW_INT.yaw` (MAVLink 2 extension)** is the canonical field for dual-antenna heading: `0`=not provided, `65535`=configured but unavailable, `36000`=north.
- **`GPS2_RTK.iar_num_hypotheses == 1`** is the definitive moving-base RTK ambiguity-resolved indicator.
- **OAK-D Pro detection requires DepthAI SDK and runs on the Jetson** (USB-attached there) — invoked by Windows-side `hw-check` via SSH.
- Servo outputs have **no direct telemetry**; verify via `SERVO_OUTPUT_RAW` PWM observation + param read of `SERVOx_FUNCTION` (73=ThrottleLeft, 74=ThrottleRight).
- **`MAV_CMD_REQUEST_MESSAGE` (cmd 512)** is the modern way to request a single message instance like `AUTOPILOT_VERSION` — preferred over deprecated `REQUEST_DATA_STREAM`.

| File / Path | Relevance |
|---|---|
| pymavlink `mavutil.py` | `mavlink_connection`, `mavserial`, `wait_heartbeat`, autoreconnect |
| pymavlink `examples/status_msg.py` | HEARTBEAT/banner connection pattern |
| pymavlink `examples/mavtester.py` | Minimal connect+heartbeat example |
| DepthAI `examples/host_side/device_information.py` | OAK device enumeration reference |

**External Sources:**

- [ArduPilot SiK Telemetry Radio overview](https://ardupilot.org/copter/docs/common-sik-telemetry-radio.html)
- [SiK Advanced Configuration](https://ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html) — air rate, ECC, MAVLink framing, power, TDM, RADIO_STATUS
- [ArduPilot — Requesting MAVLink Data](https://ardupilot.org/dev/docs/mavlink-requesting-data.html) — SRx params, SET_MESSAGE_INTERVAL, REQUEST_MESSAGE
- [MAVLink Common Message Set](https://mavlink.io/en/messages/common.html) — HEARTBEAT, SYS_STATUS, GPS_RAW_INT, GPS2_RAW, GPS_RTK, GPS2_RTK, SERVO_OUTPUT_RAW, AUTOPILOT_VERSION, RADIO_STATUS
- [Luxonis DepthAI device information example](https://docs.luxonis.com/software/depthai/examples/device_information/)
- [pymavlink GitHub](https://github.com/ArduPilot/pymavlink) — mavutil.py source

**Gaps:** None
**Assumptions:** Radio A is a SiK-compatible 915 MHz radio (typical of ArduSimple-paired modems). Pixhawk uses SERIAL1 for MAVLink telemetry (Cube Orange standard). Jetson uses standard JetPack paths.

## Phase 3: ArduPilot Rover baseline params for Z254 twin-servo skid-steer

**Status:** ✅ Complete
**Session:** 2026-04-17

### 1. Skid-Steer Servo Function Mapping (Definitive)

| Param | Value | Function | Source |
|---|---|---|---|
| `SERVO1_FUNCTION` | `73` | ThrottleLeft | wiki, `rover-skid.parm`, `SRV_Channel.h` (`k_throttleLeft = 73`) |
| `SERVO3_FUNCTION` | `74` | ThrottleRight | same |

Confirmed by ArduPilot Rover [Motor & Servo Configuration wiki](https://ardupilot.org/rover/docs/rover-motor-and-servo-configuration.html), the canonical SITL `Tools/autotest/default_params/rover-skid.parm`, and `SIM_Rover.cpp` (skid uses `servos[0]` = output 1 = left and `servos[2]` = output 3 = right).

When other values apply: `Steering=26` + `Throttle=70` are for **Ackermann** vehicles (separate steering servo + single drive). Z254 twin-lever hydrostatic is textbook skid-steer → use 73/74.

**Servo ranges:**

| Param | Value | Notes |
|---|---|---|
| `SERVOn_MIN` / `MAX` / `TRIM` | `1000` / `2000` / `1500` | Standard PWM, neutral=center |
| `SERVOn_REVERSED` | `0` (verify on vehicle) | Set during motor test if linkage inverted |

Internally, skid-steer left/right throttle uses `set_angle(±1000)` in `AP_MotorsUGV.cpp`.

### 2. Skid-Steer Mixing Parameters

| Param | Value | Rationale |
|---|---|---|
| `MOT_THR_MAX` | `100` | Default; full range |
| `MOT_THR_MIN` | `0` | **Tune on vehicle** — increase until hydrostatic deadband eliminated (often 5-15%) |
| `MOT_SLEWRATE` | `100` | %/sec; reduce to 40-60 if linkage is jerky |
| `MOT_PWM_TYPE` | `0` | Normal PWM |
| `MOT_SAFE_DISARM` | `0` | Output trim (neutral) when disarmed — keeps levers centered |
| `PILOT_STEER_TYPE` | `0` | Default mixing in Manual mode (1=Two Paddles, user preference) |
| `FRAME_CLASS` | `1` | Rover (not Boat=2, BalanceBot=3) |
| `RCMAP_ROLL` / `RCMAP_THROTTLE` | `1` / `3` | Defaults |

With `SERVO1_FUNCTION=73` + `SERVO3_FUNCTION=74` set, the firmware auto-detects skid-steer and performs the mixing internally from steering+throttle RC input.

### 3. Cube Orange Defaults & Relevant Params

| Param | Value | Rationale |
|---|---|---|
| `BRD_TYPE` | `3` (auto) | Auto-detected on Cube Orange |
| `BRD_SAFETY_DEFLT` | `0` | Disable safety switch req (Z254 has none); set to 1 if installed |
| `INS_ENABLE_MASK` | `7` | All 3 IMUs (Cube has 3) |

**Serial port mapping (Cube Orange standard):**

| Port | Physical | Default Protocol | Our Assignment |
|---|---|---|---|
| `SERIAL0` | USB | 1 (MAVLink1) | GCS via USB (debug) |
| `SERIAL1` | TELEM1 | 2 (MAVLink2) | SiK Radio B → GCS |
| `SERIAL2` | TELEM2 | 2 (MAVLink2) | Spare or disable (`-1`) |
| `SERIAL3` | GPS1 | 5 (GPS) | simpleRTK2B base F9P |
| `SERIAL4` | GPS2 | 5 (GPS) | simpleRTK2B rover F9P |

```yaml
SERIAL3_PROTOCOL: 5    # GPS
SERIAL4_PROTOCOL: 5    # GPS
SERIAL3_BAUD: 460      # 460800 (F9P UART1 default; auto-config handles if GPS_AUTO_CONFIG=1)
SERIAL4_BAUD: 460
```

**Battery (optional for MVP):**

| Param | Value | Notes |
|---|---|---|
| `BATT_MONITOR` | `4` (Analog V+I) | Or `0` to skip until power module wired |

**Compass strategy — critical for a zero-turn mower:**

The Z254 has massive magnetic interference (engine, solenoids, hydrostatic pump). The simpleRTK2B+heading provides far more reliable yaw than any compass.

| Param | Value | Rationale |
|---|---|---|
| `COMPASS_ENABLE` | `1` | Keep enabled for calibration/visibility |
| `COMPASS_USE` / `USE2` / `USE3` | `0` / `0` / `0` | **Do NOT use compass for heading** |
| `EK3_SRC1_YAW` | `2` (GPS) | Dual-antenna GPS yaw is primary heading |

`EK3_SRC1_YAW=3` (GPS+Compass fallback) is available but compass fallback may do more harm than good on a mower; start with `2`.

**AHRS / EKF:**

```yaml
AHRS_EKF_TYPE: 3       # EKF3 (required for GPS yaw)
AHRS_ORIENTATION: 0    # Normal upright
EK2_ENABLE: 0
EK3_ENABLE: 1
```

### 4. GPS / RTK Params for simpleRTK2B+heading

> 🔄 **HARDWARE SWAP (2026-04-17) — supersedes the dual-F9P configuration below.** The selected GNSS receiver is now the **ArduSimple simpleRTK3B Heading (Septentrio mosaic-H)** (SKU AS-RTK3B-MH-L1L2-NH-01, $873.75 USD) — a single-chip dual-antenna receiver, NOT two u-blox F9Ps doing moving-baseline RTK. The original F9P MB table is retained below for traceability; the mosaic-H configuration is in the new table that follows.
>
> ✅ **ArduSimple publishes an official tutorial: ["How to configure Septentrio RTK Heading and connect it to ArduPilot"](https://www.ardusimple.com/ardupilot-simplertk3b-heading-configuration/)** — written specifically for this exact board. Follow that tutorial as the authoritative integration guide; the table below summarizes the resulting ArduPilot parameter set.
>
> **Why the architecture is different:** the mosaic-H computes vehicle heading and pitch/roll *internally* from its two antenna inputs and outputs a single position+attitude stream over one UART/USB. The Cube Orange therefore consumes a *single* GPS driver (Septentrio SBF), not a paired GPS1/GPS2 moving-baseline configuration. ArduPilot's mosaic support is documented at <https://ardupilot.org/copter/docs/common-septentrio-gps.html>.
>
> **mosaic-H configuration (use these values; ignore the F9P MB table that follows):**
>
> | Param | Value | Meaning |
> |---|---|---|
> | `GPS1_TYPE` | `10` | **SBF (Septentrio Binary Format)** — single driver for the mosaic |
> | `GPS2_TYPE` | `0` | Disabled (no second GPS chip on the rover) |
> | `GPS_AUTO_CONFIG` | `0` | **Pre-configure the mosaic via Septentrio's Web UI** before deploying; ArduPilot does not auto-configure SBF receivers the way it does u-blox |
> | `GPS_AUTO_SWITCH` | `0` | Single GPS (no blending) |
> | `GPS_RATE_MS` | `200` | 5 Hz (mosaic-H supports up to 20 Hz RTK+attitude, i.e. 50 ms; up to 50 Hz standalone) |
> | `GPS1_POS_X/Y/Z` | measured | Position of the **primary (Main) antenna** relative to vehicle CG (m) |
> | `EK3_SRC1_YAW` | `2` | GPS-supplied yaw (works with mosaic SBF `AttEuler` block) |
>
> **Mosaic side (one-time, via Septentrio Web UI on the receiver's USB-Ethernet interface):**
> - Set the **Main→Aux antenna baseline** in the receiver itself (the mosaic, not ArduPilot, owns the antenna geometry).
> - Enable SBF output of `PVTGeodetic`, `AttEuler`, `AttCovEuler`, `AuxAntPositions`, `ReceiverStatus`, and `EndOfPVT` on the UART that connects to the Cube Orange.
> - Set UART baud to 230400 (or higher) to comfortably carry SBF at 5–10 Hz.
> - Enable RTCM3 *input* on the same UART (or a different one) for incoming base-station corrections delivered via Phase 4's SiK link.
> - Enable AIM+ anti-jamming/anti-spoofing (Septentrio default).
>
> **Antenna placement:** ≥1 m baseline strongly preferred for mosaic-H (datasheet quotes 0.15° heading at 1 m, improving to 0.03° at 5 m). Mount Main antenna forward, Aux antenna rear (or transverse if pitch/roll matters more than heading). Both antennas must be **multi-band L1/L2/E5b**, **identical part numbers**, and **wired with cables of identical length** (Septentrio requirement to keep the differential phase budget tight). ArduSimple recommends the [simpleANT2B Budget Survey dual-band antenna](https://www.ardusimple.com/product/survey-gnss-multiband-antenna/) (~$111 each) — NOT included with the heading board.
>
> **Wiring (single GPS UART):** mosaic UART → Cube Orange `GPS1` (TELEM-style JST). RTCM3 from Phase 4's base station SiK pair flows in on the same UART (mosaic auto-detects RTCM3 input).
>
> **What the F9P MB table below DOES NOT apply to:** `GPS1_TYPE=17`, `GPS2_TYPE=18`, `GPS1_MB_TYPE=1`, `GPS1_MB_OFS_*`, `GPS_DRV_OPTIONS=1` — all of these are u-blox-moving-baseline-specific and have **no equivalent** on the Septentrio driver. Do NOT set them.

**⚠️ Original recommendation (SUPERSEDED — retained for traceability):**

**Definitive setting from ArduPilot [GPS for Yaw wiki](https://ardupilot.org/rover/docs/common-gps-for-yaw.html)** for dual-serial F9P (which is what the simpleRTK2B+heading is):

| Param | Value | Meaning |
|---|---|---|
| `GPS1_TYPE` | `17` | **UBlox moving baseline base** (NOT UAVCAN — this value is MB-base specific) |
| `GPS2_TYPE` | `18` | UBlox moving baseline rover |
| `GPS_AUTO_CONFIG` | `1` | Let ArduPilot configure the F9Ps |
| `GPS_AUTO_SWITCH` | `1` | Use best (**NOT 2/Blend** — wiki explicitly warns) |
| `GPS_RATE_MS` | `200` | 5 Hz (set 100 for 10 Hz) |
| `GPS_DRV_OPTIONS` | `0` | Default; set `1` if cross-UART RTCM link is wired between the two F9Ps |

**EKF3 sources:**

```yaml
EK3_SRC1_POSXY: 1      # GPS
EK3_SRC1_VELXY: 1      # GPS
EK3_SRC1_POSZ:  1      # Baro
EK3_SRC1_VELZ:  1      # GPS
EK3_SRC1_YAW:   2      # GPS (dual-antenna yaw)
```

**Antenna offsets (must measure on vehicle):**

| Param | Notes |
|---|---|
| `GPS1_POS_X/Y/Z` | Master antenna offset from CG (m) |
| `GPS2_POS_X/Y/Z` | Rover antenna offset from CG (m) |
| `GPS1_MB_TYPE` = `1` | Enable moving-baseline offsets |
| `GPS1_MB_OFS_X/Y/Z` | Slave-to-master vector (m); Z=0 if same height |

**Antenna placement:** ≥30 cm separation; 50-80 cm ideal. Mount on a horizontal bar across the Z254 ROPS, master antenna forward.

### 5. Steering & Speed PIDs (Starting Points)

Canonical SITL `rover-skid.parm` overrides only **6 params** on top of `rover.parm`:

```
ATC_STR_RAT_FF  0.2
CRUISE_SPEED    3
CRUISE_THROTTLE 75
SERVO1_FUNCTION 73
SERVO3_FUNCTION 74
WP_SPEED        3
```

This confirms `ATC_STR_RAT_FF=0.2` (vs. Ackermann default 0.75) and `CRUISE_THROTTLE=75` (skid-steer needs more throttle due to mixing losses).

**Z254 starting baseline** (more conservative than SITL):

| Param | Value | Rationale |
|---|---|---|
| `ATC_STR_RAT_FF` | `0.20` | Primary tuning knob |
| `ATC_STR_RAT_P` | `0.04` | ~20% of FF |
| `ATC_STR_RAT_I` | `0.04` | Same as P |
| `ATC_STR_RAT_D` | `0.00` | Start at zero |
| `ATC_STR_RAT_MAX` | `90` | deg/s; conservative |
| `ACRO_TURN_RATE` | `90` | Match `STR_RAT_MAX` |
| `ATC_SPEED_P` | `0.10` | rover.parm default |
| `ATC_SPEED_I` | `0.05` | ~50% of P |
| `ATC_SPEED_D` / `FF` | `0.00` / `0.00` | Cruise pair provides FF baseline |
| `ATC_ACCEL_MAX` | `2.0` | m/s²; conservative for heavy mower |
| `ATC_DECEL_MAX` | `0.0` | = ACCEL_MAX |
| `ATC_TURN_MAX_G` | `0.30` | Lateral g limit |
| `CRUISE_SPEED` | `2.0` | ~4.5 mph mowing |
| `CRUISE_THROTTLE` | `50` | Starting guess; use "Learn Cruise" |
| `WP_SPEED` | `2.0` | Match cruise |
| `WP_RADIUS` | `1.0` | Tight (Z254 can pivot) |
| `WP_OVERSHOOT` | `1.0` | |
| `WP_PIVOT_ANGLE` | `60` | Trigger pivot turn at >60° |
| `WP_PIVOT_RATE` | `45` | deg/s pivot rate |

### 6. Failsafe Params for MVP

| Param | Value | Rationale |
|---|---|---|
| `FS_ACTION` | `2` (Hold) | **Stop in place** — RTL might drive through obstacles |
| `FS_TIMEOUT` | `1.5` | Default |
| `FS_THR_ENABLE` / `_VALUE` | `1` / `910` | RC failsafe |
| `FS_GCS_ENABLE` / `_TIMEOUT` | `1` / `5` | GCS failsafe (critical for autonomous mowing) |
| `FS_CRASH_CHECK` | `1` | Hold on crash |
| `FS_EKF_ACTION` / `_THRESH` | `2` (Hold) / `0.8` | Hold on EKF failure |
| `FS_OPTIONS` | `1` | Failsafe active even in Hold mode |
| `RTL_SPEED` | `0` | Use `WP_SPEED` |
| `ARMING_REQUIRE` | `1` | |
| `ARMING_SKIPCHK` | `0` | All checks enabled |
| `ARMING_NEED_LOC` | `1` | Require GPS fix before arming |

### 7. Community Precedents

- **Canonical SITL skid-steer** = `Tools/autotest/default_params/rover-skid.parm` (only 6 params layered on `rover.parm`)
- All Morse/Gazebo/follow-mode skid examples use the same SERVO1=73 / SERVO3=74 mapping
- **No Z254/Husqvarna/zero-turn-specific param files exist** in the ArduPilot community — baseline must be derived from generic skid-steer + Z254-specific tuning

### 8. Param File Format & Snapshot Conventions

| Format | Syntax | Use |
|---|---|---|
| Mission Planner `.parm` | `NAME,VALUE` | Most common; comma-separated, no header |
| MAVProxy / SITL `.parm` | `NAME    VALUE` | Space/tab separated; what `default_params/` uses |
| QGroundControl `.params` | tab-separated, header `# Vehicle-Id Component-Id Name Value Type` | Used by QGC |

**Tools:**
- `pymavlink.mavparm.MAVParmDict` — read/write/diff
- `Tools/scripts/extract_param_defaults.py` — extract defaults from .bin log; supports `--format missionplanner|mavproxy|qgcs`

**Recommended diff approach:** sort by name; compare against post-flash defaults snapshot; surface only changed params; store baseline as YAML for human editing, export to `.parm` for Mission Planner upload.

### Consolidated Baseline Parameter Set

```yaml
# Z254 Zero-Turn Mower — ArduPilot Rover Baseline
# Cube Orange + twin servos on hydrostatic levers + simpleRTK2B+heading

# --- Frame & Board ---
FRAME_CLASS: 1
BRD_SAFETY_DEFLT: 0

# --- Skid-steer servo functions ---
SERVO1_FUNCTION: 73          # ThrottleLeft
SERVO1_MIN: 1000
SERVO1_MAX: 2000
SERVO1_TRIM: 1500
SERVO1_REVERSED: 0           # VERIFY on vehicle
SERVO3_FUNCTION: 74          # ThrottleRight
SERVO3_MIN: 1000
SERVO3_MAX: 2000
SERVO3_TRIM: 1500
SERVO3_REVERSED: 0           # VERIFY on vehicle

# --- Motor / mixing ---
MOT_THR_MAX: 100
MOT_THR_MIN: 0               # TUNE for hydrostatic deadband
MOT_SLEWRATE: 100
MOT_PWM_TYPE: 0
MOT_SAFE_DISARM: 0
PILOT_STEER_TYPE: 0

# --- AHRS / EKF ---
AHRS_EKF_TYPE: 3
AHRS_ORIENTATION: 0
EK2_ENABLE: 0
EK3_ENABLE: 1

# --- GPS / RTK ---
GPS1_TYPE: 17                # UBlox moving baseline base
GPS2_TYPE: 18                # UBlox moving baseline rover
GPS_AUTO_CONFIG: 1
GPS_AUTO_SWITCH: 1           # NOT 2/Blend
GPS_RATE_MS: 200
GPS_DRV_OPTIONS: 0
SERIAL3_PROTOCOL: 5
SERIAL4_PROTOCOL: 5

# --- GPS antenna offsets (MEASURE ON VEHICLE) ---
GPS1_POS_X: 0.0
GPS1_POS_Y: 0.0
GPS1_POS_Z: 0.0
GPS2_POS_X: 0.0
GPS2_POS_Y: 0.0
GPS2_POS_Z: 0.0
GPS1_MB_TYPE: 1
GPS1_MB_OFS_X: 0.0           # MEASURE
GPS1_MB_OFS_Y: 0.0           # MEASURE
GPS1_MB_OFS_Z: 0.0

# --- EKF3 sources ---
EK3_SRC1_POSXY: 1
EK3_SRC1_VELXY: 1
EK3_SRC1_POSZ: 1
EK3_SRC1_VELZ: 1
EK3_SRC1_YAW: 2              # GPS dual-antenna yaw

# --- Compass (disabled for heading) ---
COMPASS_USE: 0
COMPASS_USE2: 0
COMPASS_USE3: 0

# --- Telemetry ---
SERIAL1_PROTOCOL: 2
SERIAL2_PROTOCOL: 2

# --- Steering PID ---
ATC_STR_RAT_FF: 0.20
ATC_STR_RAT_P: 0.04
ATC_STR_RAT_I: 0.04
ATC_STR_RAT_D: 0.00
ATC_STR_RAT_MAX: 90
ACRO_TURN_RATE: 90

# --- Speed PID ---
ATC_SPEED_P: 0.10
ATC_SPEED_I: 0.05
ATC_SPEED_D: 0.00
ATC_SPEED_FF: 0.00
ATC_ACCEL_MAX: 2.0
ATC_DECEL_MAX: 0.0
ATC_TURN_MAX_G: 0.30

# --- Cruise & navigation ---
CRUISE_SPEED: 2.0
CRUISE_THROTTLE: 50
WP_SPEED: 2.0
WP_RADIUS: 1.0
WP_OVERSHOOT: 1.0
WP_PIVOT_ANGLE: 60
WP_PIVOT_RATE: 45

# --- Failsafe ---
FS_ACTION: 2                 # Hold
FS_TIMEOUT: 1.5
FS_THR_ENABLE: 1
FS_THR_VALUE: 910
FS_GCS_ENABLE: 1
FS_GCS_TIMEOUT: 5
FS_CRASH_CHECK: 1
FS_EKF_ACTION: 2
FS_EKF_THRESH: 0.8
FS_OPTIONS: 1
RTL_SPEED: 0

# --- Arming ---
ARMING_REQUIRE: 1
ARMING_SKIPCHK: 0
ARMING_NEED_LOC: 1
```

**Key Discoveries:**

- **`SERVO1_FUNCTION=73` + `SERVO3_FUNCTION=74`** is THE canonical skid-steer convention — confirmed by wiki, SITL `rover-skid.parm`, source enums (`SRV_Channel.h`), and SITL physics (`SIM_Rover.cpp` reads `servos[0]`/`servos[2]`).
- The canonical `rover-skid.parm` overrides only **6 params**: `ATC_STR_RAT_FF=0.2`, `CRUISE_SPEED=3`, `CRUISE_THROTTLE=75`, `SERVO1_FUNCTION=73`, `SERVO3_FUNCTION=74`, `WP_SPEED=3`.
- **`ATC_STR_RAT_FF` must drop from 0.75 (Ackermann default) to 0.2 for skid-steer** — the single most important parameter change.
- For dual F9P moving-baseline: **`GPS1_TYPE=17`** (UBlox MB **base**, NOT UAVCAN), **`GPS2_TYPE=18`** (UBlox MB **rover**). NOT auto/UBlox (1).
- **`EK3_SRC1_YAW=2`** (GPS) is the definitive setting for dual-antenna yaw. Option 3 (GPS+Compass fallback) is available but inadvisable on a mower with heavy magnetic interference.
- **`GPS_AUTO_SWITCH` MUST NOT be `2`/Blend** with moving-baseline — wiki explicitly warns.
- **`COMPASS_USE=0`** disables compass for heading while keeping it enabled — critical on a zero-turn mower.
- **`CRUISE_THROTTLE` should start higher for skid-steer** (SITL uses 75) due to mixing losses; Z254 starting guess = 50 with "Learn Cruise" to refine.
- **No Husqvarna/zero-turn community param files exist** — baseline derived from generic skid-steer + vehicle-specific tuning.
- `.parm` (Mission Planner) = `NAME,VALUE`; SITL/MAVProxy = `NAME VALUE` (space/tab); QGC `.params` is tab-separated with header.

| File / Path | Relevance |
|---|---|
| `ArduPilot/ardupilot/Tools/autotest/default_params/rover-skid.parm` | Canonical SITL skid-steer overrides (6 params) |
| `ArduPilot/ardupilot/Tools/autotest/default_params/rover.parm` | Base Rover SITL defaults |
| `ArduPilot/ardupilot/Tools/autotest/pysim/vehicleinfo.py` | Frame → param-file mapping |
| `ArduPilot/ardupilot/libraries/SRV_Channel/SRV_Channel.h` | `k_throttleLeft=73`, `k_throttleRight=74` enum |
| `ArduPilot/ardupilot/libraries/AR_Motors/AP_MotorsUGV.cpp` | Skid-steer output impl, MOT_ params |
| `ArduPilot/ardupilot/Rover/Parameters.cpp` | All Rover parameter definitions |
| `ArduPilot/ardupilot/Tools/scripts/extract_param_defaults.py` | Extract defaults from .bin log |

**External Sources:**

- [Rover Motor & Servo Configuration](https://ardupilot.org/rover/docs/rover-motor-and-servo-configuration.html) — definitive skid-steer mapping
- [GPS for Yaw (Moving Baseline)](https://ardupilot.org/rover/docs/common-gps-for-yaw.html) — `GPS1_TYPE=17`/`GPS2_TYPE=18`/`EK3_SRC1_YAW=2`/antenna offsets/no Blend warning
- [EKF Source Selection](https://ardupilot.org/rover/docs/common-ekf-sources.html) — `EK3_SRC1_YAW` options
- [Rover Failsafes](https://ardupilot.org/rover/docs/rover-failsafes.html)
- [Arming Your Rover](https://ardupilot.org/rover/docs/arming-your-rover.html)
- [Rover Tuning — Throttle and Speed](https://ardupilot.org/rover/docs/rover-tuning-throttle-and-speed.html)
- [Rover Tuning — Steering Rate](https://ardupilot.org/rover/docs/rover-tuning-steering-rate.html)
- [SITL `rover-skid.parm` raw](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/autotest/default_params/rover-skid.parm)
- [SITL `rover.parm` raw](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/autotest/default_params/rover.parm)

**Gaps:**

- ArduSimple integration page (ardusimple.com/connecting-ardusimple-to-ardupilot/) returned 404 — physical wiring (which simpleRTK2B UART → which Cube Orange GPS port) should be verified from product docs or hands-on testing.
- No field-tested heavy zero-turn / Z254 community param sets exist — all values extrapolated from SITL defaults and general guidance.
- Antenna offsets (`GPS*_POS_*`, `GPS1_MB_OFS_*`) require physical measurement.
- `MOT_THR_MIN` (hydrostatic deadband) is vehicle-specific and must be determined experimentally.

**Assumptions:**

- Servos accept standard 1000-2000 µs PWM with neutral at 1500 µs.
- simpleRTK2B+heading connects its two F9Ps via UART (not DroneCAN) to Cube Orange GPS1/GPS2 — standard configuration.
- `CRUISE_THROTTLE=50` reasonable starting point; SITL uses 75 but Z254 hydrostatic response differs.
- Cube Orange mounted upright (`AHRS_ORIENTATION=0`).
- ~~No wheel encoders for MVP (speed feedback from GPS only).~~ **Superseded 2026-04-17:** two CALT GHW38 200 mm push-pull quadrature encoders (200 PPR) will be added, mounted as rollers pressed against the drive-wheel tires for true ground-speed measurement. See top-of-doc 🔄 callout for the param-set additions (`WENC_*`, `WENC2_*`, `EK3_SRC1_VELXY=6`) and the level-shifter electrical caveat.

**Follow-up needed:**

- Verify simpleRTK2B+heading → Cube Orange wiring from product docs.
- On-vehicle servo testing for `SERVOn_REVERSED` and `MOT_THR_MIN`.
- Field tuning for `CRUISE_THROTTLE` (Learn Cruise) and `ATC_STR_RAT_FF`.
- Verify `GPS_DRV_OPTIONS` setting based on whether internal RTCM cross-link exists in the simpleRTK2B+heading.
- Add `BATT_LOW_VOLT` / `BATT_FS_LOW_ACT` if battery monitoring is wired.
- **Wheel-encoder integration (added 2026-04-17):** assign two free Cube Orange AUX pins per encoder (4 AUX pins total for A/B × 2 encoders). All 6 AUX pins (`SERVO9`–`SERVO14`) are available — the three engine/blade relays use MAIN outputs (`SERVO5/6/7`), not AUX. Set `BRD_PWM_COUNT` accordingly to convert the chosen AUX pins from PWM to GPIO; populate `WENC_TYPE=1`, `WENC_CPR=800`, `WENC_RADIUS=0.100`, `WENC_PINA/PINB`, `WENC_POS_X/Y/Z` (left-wheel offset from CG); same for `WENC2_*` (right wheel); after on-ground odometry calibration, set `EK3_SRC1_VELXY=6` (wheel encoders) and `EK3_SRC2_VELXY=3` (GPS) for slip-tolerant velocity fusion. Bench-verify both encoder counts increment correctly with manual wheel rotation before powering the engine. Confirm push-pull → 3.3 V level shifter (6N137 opto module) is in place; do **not** connect a 12 V or 5 V push-pull output directly to a Cube Orange AUX pin.

## Phase 4: RTK base station approach + simpleRTK2B+heading configuration

**Status:** ✅ Complete
**Session:** 2026-04-17

> 🔄 **Hardware update (2026-04-17):** the rover-side receiver is now the **simpleRTK3B Heading (Septentrio mosaic-H)** instead of the dual-F9P simpleRTK2B+heading. **The base-station design in this phase is UNCHANGED** — a simpleRTK2B Budget (ZED-F9P) base streaming RTCM3 over SiK is fully interoperable with a Septentrio rover. RTCM3 message set, survey-in/fixed-coord workflow, bandwidth budget (~530 B/s), and ArduPilot ingest path all remain valid. Only consequence: the rover-side u-center procedures in this phase no longer apply (replaced by the Septentrio Web UI procedures called out in Phase 3 §4's 🔄 callout, and by the official ArduSimple tutorial linked there).

### 1. Base Station Hardware Options

| Option | Hardware | Approx Cost | SBC | Recommendation |
|---|---|---|---|---|
| **A:** Standalone simpleRTK2B Budget + L1/L2 antenna + SiK radio | ~$215 + ~$50 + ~$50 ≈ **$315** | No | ✅ **Recommended** |
| **B:** simpleRTK2B + Raspberry Pi running RTKLIB `str2str` | ~$375 | Yes | Adds complexity (SD corruption, boot, OS); no benefit for offline use |
| **C:** Hybrid (effectively same as A; u-center one-time config) | $315 | No (PC for setup only) | Same as A |

**Recommendation: Option A.** Configure a single simpleRTK2B Budget once via u-center, save settings to F9P flash, then deploy with a SiK radio wired to UART2. On power-up the F9P autonomously enters survey-in (or uses fixed coords) and streams RTCM. No SBC, no RTKLIB, no internet — fully consistent with constraint C-10.

**Bill of materials (additional to existing rover-side heading kit):**

| Item | Approx Cost |
|---|---|
| simpleRTK2B Budget (ZED-F9P) | $215 |
| L1/L2 multiband antenna (ArduSimple survey antenna) | $50–$80 |
| SiK 915 MHz radio (one unit, paired with rover Radio A) | $30–$50 |
| SMA extension cable (~10 m) | $15 |
| Tripod / fixed mount | $20–$40 |
| 5 V power (USB power bank or supply) | $20 |
| **Total** | **~$350–$420** |

### 2. Survey-In vs. Fixed Coordinates

- **Survey-In (TMODE3 mode 1):** F9P self-surveys; locks position when min duration AND accuracy threshold are both met.
- **Fixed (TMODE3 mode 2):** F9P uses given ECEF coords; immediate startup.

**Recommended workflow:**

1. **First-time setup (once per base location):**
   - Mount antenna on tripod over a permanently-marked ground point with clear sky.
   - Configure `CFG-TMODE-MODE = 1`, `CFG-TMODE-SVIN_MIN_DUR = 3600` (1 h), `CFG-TMODE-SVIN_ACC_LIMIT = 20000` (2.0 m, units are 0.1 mm).
   - Wait 1–3 h until `NAV-SVIN` reports "Valid".
   - Read mean ECEF X/Y/Z and **save these coordinates** to a config file.
2. **Subsequent sessions:**
   - Re-mount antenna on the same marked point.
   - Set `CFG-TMODE-MODE = 2`, `CFG-TMODE-ECEF_X/Y/Z` from saved coords, `CFG-TMODE-FIXED_POS_ACC = 10000` (1.0 m).
   - RTCM output begins immediately.

**Why this works:** Survey-in for 1 h gives ~0.5–1.0 m absolute accuracy. The mower needs ~2–3 cm **relative** accuracy, which RTK provides regardless of base absolute accuracy. Fixed mode eliminates the warm-up wait on every session.

### 3. RTCM Message Set + SiK Bandwidth Budget

**Recommended message set (matches ArduSimple's published base config + BeiDou):**

| Message | Content | Rate | ~Bytes/epoch | Bytes/s |
|---|---|---|---|---|
| 1005 | Stationary base ARP | 0.2 Hz | 25 | 5 |
| 1074 | GPS MSM4 | 1 Hz | 150 | 150 |
| 1084 | GLONASS MSM4 | 1 Hz | 120 | 120 |
| 1094 | Galileo MSM4 | 1 Hz | 130 | 130 |
| 1124 | BeiDou MSM4 | 1 Hz | 120 | 120 |
| 1230 | GLONASS code-phase biases | 0.2 Hz | 30 | 6 |
| **Total** | | | | **~531 B/s** |

**SiK Radio A capacity:** AIR_SPEED=64 ⇒ ~6,800–7,200 B/s effective with MAVLINK=0. **Utilization ≈ 7.6%** — comfortable. MSM7 (~1,200 B/s) only ~17% utilization but unnecessary for mowing accuracy.

**Note:** RTCM 4072.0/4072.1 (u-blox proprietary moving-baseline) are NOT needed on the base→rover link. Those handle the inter-F9P link inside the heading module, managed by ArduPilot's GPS driver.

### 4. RTCM-over-SiK Link Health Monitoring

**The challenge:** Radio A runs `MAVLINK=0` (raw RTCM passthrough), so it does NOT inject `RADIO_STATUS` messages into the Pixhawk's MAVLink stream. The Pixhawk has no direct visibility into Radio A's RSSI / packet loss.

**Indirect indicators (primary monitoring approach):**

| MAVLink message | Field | Healthy | Degraded |
|---|---|---|---|
| `GPS_RAW_INT` | `fix_type` | 6 (RTK Fixed) | 5 → 4 → 3 |
| `GPS_RAW_INT` | `h_acc` | <50 mm | rising |
| `GPS_RAW_INT` | `eph` | <50 | rising |
| `GPS_RTK` | `rtk_health` | non-zero | 0 |
| `GPS_RTK` | `rtk_rate` | >0 | 0 (no RTCM arriving) |
| `GPS_RTK` | `nsats` | >10 | decreasing |
| `GPS2_RTK` | `iar_num_hypotheses` | 1 | >1 (heading not resolved) |

**RTCM age → fix degradation timeline:**

| Age since last RTCM | Expected fix | Notes |
|---|---|---|
| 0–5 s | RTK Fixed | Normal |
| 5–10 s | RTK Fixed | F9P extrapolating |
| 10–30 s | → RTK Float | ~10–50 cm accuracy |
| 30–60 s | → DGPS | ~0.5–2 m accuracy |
| >60 s | → 3D Fix | ~2–5 m |

**Decision thresholds:** 5 s gap = continue; 10 s = warn (`pause` candidate); >30 s = abort/RTL.

**Direct query of Radio A:** Not possible while passing RTCM. Only via physical LED inspection or temporarily breaking the data path to enter AT-command mode (`ATI5`).

**Pre-flight RTK health check (sketch):**

```python
def check_rtk_link_health(mav, timeout_s=30):
    consecutive_good = 0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        gps = mav.recv_match(type='GPS_RAW_INT', blocking=True, timeout=2)
        if gps is None:
            continue
        if gps.fix_type == 6 and gps.h_acc < 50 and gps.yaw not in (0, 65535):
            consecutive_good += 1
            if consecutive_good >= 5:
                return True, f"RTK Fixed, h_acc={gps.h_acc}mm, yaw={gps.yaw/100.0}°"
        else:
            consecutive_good = 0
    return False, "RTK convergence timeout"
```

**Continuous in-mission monitor:** track time-since-last-RTK-Fixed; degrade → pause; lost → abort/RTL.

### 5. u-center Configuration Workflow

**Rover side (simpleRTK2B+heading on Pixhawk):** ArduPilot's `GPS_AUTO_CONFIG=1` handles ALL F9P configuration on boot — no u-center setup required for the heading module in normal use. (Phase 3 covered the rover-side params.)

**Base station side (the separate simpleRTK2B Budget):** NOT touched by ArduPilot. Requires manual u-center setup once, saved to F9P flash:

1. **Connect:** USB to PC; open u-center (F9 version); select COM port.
2. **Verify firmware:** `UBX > MON > VER` — confirm FWVER 1.13 or 1.32+.
3. **Load ArduSimple base config:** `Tools > Receiver Configuration` → "u-blox Generation 9" → load ArduSimple's downloadable base config (sets survey-in 2.5 m, UART2 = 115200, RTCM 1005/1074/1084/1094/1230 enabled).
4. **Add BeiDou:** `UBX > CFG > MSG` → enable RTCM 1124 on UART2 at rate 1.
5. **Adjust low-rate messages:** 1005 and 1230 every 5 s (rate 5 = once every 5 seconds in u-blox terms, or set Hz per project convention).
6. **UART2 baud:** `UBX > CFG > PRT` → UART2 → match SiK serial speed (57600 or 115200).
7. **Survey-in setup:** `UBX > CFG > TMODE3` → Mode 1, min duration 3600 s, accuracy 2.0 m.
8. **Save to flash:** `Receiver > Action > Save Config`.
9. **Verify:** Packet Console shows RTCM streaming after `NAV-SVIN` reports "Valid"; `NAV-PVT` fix type shows "TIME" (base mode active).
10. **Record ECEF:** Save the surveyed ECEF X/Y/Z for switching to Fixed Mode later.

**Useful UBX messages for monitoring:** `NAV-PVT`, `NAV-SVIN` (survey progress), `MON-VER`, `MON-COMMS` (port buffer stats).

**CLI automation opportunity:** Use **`pyubx2`** to send `UBX-CFG-VALSET` over USB and skip the u-center GUI:

```python
# Conceptual — programmatic base F9P config via pyubx2
from pyubx2 import UBXMessage
import serial

def configure_base_f9p(port, survey_in=True, ecef_coords=None):
    ser = serial.Serial(port, 38400)
    if survey_in:
        msg = UBXMessage.config_set(layers=1, transaction=0, cfgData=[
            ("CFG_TMODE_MODE", 1),
            ("CFG_TMODE_SVIN_MIN_DUR", 3600),
            ("CFG_TMODE_SVIN_ACC_LIMIT", 20000),
        ])
    else:
        msg = UBXMessage.config_set(layers=1, transaction=0, cfgData=[
            ("CFG_TMODE_MODE", 2),
            ("CFG_TMODE_ECEF_X", ecef_coords[0]),
            ("CFG_TMODE_ECEF_Y", ecef_coords[1]),
            ("CFG_TMODE_ECEF_Z", ecef_coords[2]),
        ])
    ser.write(msg.serialize())
    # ... enable RTCM messages, save to flash
```

This makes `mower rtk base-config` fully scripted, replacing all the u-center clicking.

### 6. Fix-Quality + Yaw-Quality Verification

**Programmatic verification thresholds:**

| Check | Field | Threshold | Meaning |
|---|---|---|---|
| RTK Fixed | `GPS_RAW_INT.fix_type` | == 6 | Best fix |
| Position accuracy | `GPS_RAW_INT.h_acc` | <50 mm | <5 cm — adequate for lane spacing |
| Heading available | `GPS_RAW_INT.yaw` | ∉ {0, 65535} | Valid yaw |
| Heading accuracy | `GPS_RAW_INT.hdg_acc` | <100 (1.0°) | Adequate for straight passes |
| MB ambiguity resolved | `GPS2_RTK.iar_num_hypotheses` | == 1 | Heading solution valid |
| RTCM flowing | `GPS_RTK.rtk_rate` | >0 | Corrections arriving |
| Sat count | `GPS_RAW_INT.satellites_visible` | ≥10 | Good geometry |

**ArduPilot's internal yaw validation** (auto-applied by GPS driver):

1. Rover GPS in fix type 6
2. Reported antenna baseline matches `GPS1_MB_OFS_X/Y/Z` within 20%
3. Reported height difference between GPS modules matches attitude within 20% of baseline length

If any check fails, ArduPilot ignores GPS yaw.

**Convergence times:**

| Event | Typical |
|---|---|
| Cold start → 3D fix | ~25 s |
| 3D fix → RTK Float | ~5–10 s |
| RTK Float → RTK Fixed | ~10–30 s |
| **Cold → RTK Fixed total** | **~35–60 s** |
| First heading lock | +60–120 s (after RTK Fixed on both F9Ps) |
| Hot start → RTK Fixed | 2–5 s |

**Pre-mission convergence state machine** (sketch):

```python
class ConvergenceState:
    WAITING_3D = "Waiting for 3D fix"
    WAITING_RTK_FLOAT = "Waiting for RTK Float"
    WAITING_RTK_FIXED = "Waiting for RTK Fixed"
    WAITING_HEADING = "Waiting for heading lock"
    READY = "Ready to arm"
    TIMEOUT = "Convergence timeout"

def wait_for_convergence(mav, timeout_s=180):
    start = time.time()
    rtk_fixed_since = None
    while time.time() - start < timeout_s:
        gps = mav.recv_match(type='GPS_RAW_INT', blocking=True, timeout=2)
        if gps is None: continue
        if gps.fix_type == 6:
            if rtk_fixed_since is None:
                rtk_fixed_since = time.time()
            heading_ok = gps.yaw not in (0, 65535)
            stable = (time.time() - rtk_fixed_since) > 5
            if heading_ok and stable and gps.h_acc < 50:
                return ConvergenceState.READY, {
                    "h_acc_mm": gps.h_acc, "yaw_cdeg": gps.yaw,
                    "sats": gps.satellites_visible,
                    "convergence_s": time.time() - start,
                }
        else:
            rtk_fixed_since = None
    return ConvergenceState.TIMEOUT, {}
```

**During convergence:** hold disarmed; display real-time fix/accuracy/sats/heading; allow user to skip with degraded warning if heading lock fails after ~3 min.

**Key Discoveries:**

- **Standalone simpleRTK2B Budget ($215) is the recommended base** — no SBC/Pi required. Configure once via u-center, save to F9P flash, autonomous on every power-up.
- **ArduSimple publishes pre-made base configuration files** (1005/1074/1084/1094/1230 enabled) — load as starting point, then customize for BeiDou.
- **Survey-in once (1 h, 2.0 m target), record ECEF, then Fixed Mode** for all subsequent sessions — eliminates warm-up.
- **Recommended RTCM message set ≈ 530 B/s, ≈ 7.6% of SiK link capacity** — ample headroom; MSM7 not needed.
- **RTCM 4072 messages NOT needed on base→rover link** — those are for the internal heading-module link, handled by ArduPilot.
- **Radio A (SiK, MAVLINK=0) has no remote query** — must use indirect monitoring via `GPS_RAW_INT.fix_type` and `GPS_RTK.*`.
- **RTCM age timeline:** RTK Fixed maintained ~5–10 s; degrades to Float by 10–30 s; to 3D fix by ~60 s.
- **`GPS_AUTO_CONFIG=1` handles ALL rover-side F9P configuration** — no u-center needed for the heading module on the mower.
- **Cold → RTK Fixed: ~35–60 s; first heading lock: +60–120 s.**
- **`pyubx2` enables programmatic base F9P configuration** via `UBX-CFG-VALSET` — `mower rtk base-config` can fully replace u-center clicking.

**External Sources:**

- [ArduPilot GPS for Yaw (Moving Baseline)](https://ardupilot.org/rover/docs/common-gps-for-yaw.html)
- [ArduPilot RTK GPS Correction (Fixed Baseline)](https://ardupilot.org/rover/docs/common-rtk-correction.html)
- [ArduSimple Configuration Files](https://www.ardusimple.com/configuration-files/) — base config with RTCM rationale
- [SparkFun Rover Base RTK Setup](https://learn.sparkfun.com/tutorials/setting-up-a-rover-base-rtk-system/all) — TMODE3 setup, RTCM selection
- [ArduSimple RTK Starter Kits](https://www.ardusimple.com/rtk-starter-kits/) — kit pricing
- [simpleRTK2B Budget product page](https://www.ardusimple.com/product/simplertk2b/)
- [ArduPilot SiK Telemetry Radio](https://ardupilot.org/rover/docs/common-sik-telemetry-radio.html)

**Gaps:**

- u-blox ZED-F9P integration manual PDF (404) — exact `CFG-TMODE-*` UBX key names for `pyubx2` need verification at implementation time.
- ArduSimple product pages are heavily JS-rendered; couldn't fetch the simpleRTK2B+heading product page directly.
- RTCM message byte sizes are estimates from community measurements; actual values vary with satellite geometry.

**Assumptions:**

- Radio A operates at AIR_SPEED=64, MAVLINK=0 (per project constraints) ⇒ ~7 KB/s effective.
- 915 MHz SiK radios (North America). 433 MHz variants for other regions.
- Base UART2 baud matches SiK serial speed (57600 default; can raise to 115200).
- simpleRTK2B+heading ships pre-configured for moving baseline between its internal F9Ps (verified by ArduPilot wiki noting ArduSimple modules work with `GPS_AUTO_CONFIG=1`).
- `pyubx2` supports the needed CFG-TMODE keys (verify in implementation).

**Follow-up needed:**

- **⚠️ Mosaic-H integration verification (non-blocking; ArduSimple has an official tutorial):** follow the [ArduSimple simpleRTK3B Heading + ArduPilot tutorial](https://www.ardusimple.com/ardupilot-simplertk3b-heading-configuration/) end-to-end. Confirm the resulting ArduPilot parameter set matches the Phase 3 §4 mosaic-H table; verify `AttEuler` heading is consumed by EKF3 with `EK3_SRC1_YAW=2`; verify required SBF block list and minimum baud (likely 230400); document the Septentrio Web UI antenna-baseline configuration steps. Decide between 5 Hz and 10 Hz (`GPS_RATE_MS=200` vs `100`) given SBF bandwidth.
- Verify exact `pyubx2` API for `CFG-TMODE-MODE`, `CFG-TMODE-SVIN_MIN_DUR`, `CFG-TMODE-SVIN_ACC_LIMIT`, `CFG-TMODE-ECEF_X/Y/Z`.
- Field-test actual RTCM bandwidth at the user's location (estimate 530 B/s may vary with constellation).
- Determine whether the SiK radio pair for the RTCM link is purchased separately or comes with an ArduSimple kit the user is already buying.
- Consider an optional ESP32 status-LED/BLE on the base station for at-a-glance health indication.

## Phase 5: Servo selection/specs for Z254 hydrostatic lever actuation

**Status:** ✅ Complete
**Session:** 2026-04-17

### 1. Force Required at the Z254 Lever

No published Husqvarna spec exists. Estimate is synthesized from ArduPilot ZTR-conversion community (Kevin Groba, Kenny Trussell, Max_G, BenBBB, marblecreek), Hydro-Gear EZT transaxle characteristics, and first-principles analysis. The Z254 uses Hydro-Gear EZT transaxles, one per side; lap-bar lever connects to swashplate input via a linkage.

| Component | Force at handle (lbs) | Notes |
|---|---|---|
| Pump return spring (swashplate centering) | 3–8 | Highest at endpoints, lowest near neutral |
| Gas damper resistance | 3–5 | Velocity-dependent |
| Linkage friction | 1–3 | Increases with age/dirt |
| **Total with dampers** | **8–16 lbs** | |
| **Total dampers removed** | **4–11 lbs** | Recommended config |

**Critical finding: Gas damper removal is standard practice in the ArduPilot ZTR community** (confirmed by Max_G: *"The gas dampeners are only connected to the handles… Most of us who automate these mowers remove the dampeners."*). Reduces force requirement ~40%; dampers can be unbolted without affecting hydrostatic function. **✅ Confirmed by user 2026-04-17: gas dampers have been removed from this Z254.**

**Force profile across travel:** sinusoidal-like — endpoint force ≈ 1.5–2× neutral-region force. Servo must be sized for the **endpoint force**.

**Lever travel geometry (Z254):** handle sweep ~6–10" (150–250 mm), angular travel ±15–25° from neutral, push rod typically attaches 100–200 mm from lever pivot.

**Design force (dampers removed): 10–15 lbs (45–67 N) at the lever attachment point.**

### 2. From Lever Force to Servo Torque

For a typical linkage:

$$\tau_{servo} = \tau_{lever} \times \frac{r_s}{r_L} \quad\text{where}\quad \tau_{lever} = F_{handle} \times r_{handle}$$

**Numeric example (conservative):** $F_{handle}=15$ lbs (67 N), $r_{handle}=300$ mm, $r_L=150$ mm, $r_s=40$ mm

$$\tau_{lever} = 67 \times 0.30 = 20.1\ \text{N·m} = 205\ \text{kg·cm}$$
$$F_{rod} = 20.1 / 0.15 = 134\ \text{N} = 30\ \text{lbs}$$
$$\tau_{servo,raw} = 134 \times 0.04 = 5.36\ \text{N·m} = 54.6\ \text{kg·cm}$$

**Safety factors:** endpoint angle loss ×1.4; vibration/stiction ×1.3; aging/wear ×1.2; combined **×2.2**.

| Geometry | Raw τ_servo | With ×2.2 |
|---|---|---|
| Conservative ($r_L$=150, $r_s$=40) | 54.6 kg·cm | 120 kg·cm |
| Favorable ($r_L$=200, $r_s$=50) | 50.3 kg·cm | 110 kg·cm |

**Practical target: 35–50 kg·cm (486–694 oz·in)** with optimized linkage geometry. Matches the working range observed in the ArduPilot ZTR community.

**Speed:** 0.5–2.0 sec for full range during normal mowing; 0.3–1.0 sec/60° during pivot turns; **e-stop snap-back is best handled by mechanical spring return, not servo speed**.

**Holding torque under vibration:** prefer **digital servos** (300+ Hz position refresh vs. ~50 Hz analog); brushless is best (no torque ripple).

### 3. Servo Candidates

#### Tier 1: High-torque hobby digital servos (recommended starting point)

| Servo | Torque @ 7.4 V | Speed (s/60°) | Travel | Motor | Waterproof | Price |
|---|---|---|---|---|---|---|
| **Savox SB2290SG** ★ | 694 oz·in (49.6 kg·cm) | 0.13 | 160° | Brushless | No | $164 |
| **Hitec D845WP** ★ | 694 oz·in (49.6 kg·cm) | 0.17 | 146° (202° reprog.) | Coreless | **Yes** | $135 |
| Hitec DB961WP | 763 oz·in (54.5 kg·cm) | 0.15 | 165° (260°) | Brushless | **Yes** | $200 |
| Hitec HS-7950TH | 486 oz·in (34.7 kg·cm) | 0.15 | 120° (198°) | Coreless | No | $113 |
| Savox SV1270TG | 486 oz·in (34.7 kg·cm) | 0.11 | 160° | Brushless | No | $117 |
| Savox SA1230SG | 500 oz·in (35.7 kg·cm) | 0.16 | 160° | Coreless | No | $103 |
| Hitec D956WP | 403 oz·in (28.8 kg·cm) | 0.12 | 150° (205°) | Coreless | **Yes** | $140 |

★ **Primary picks:** Savox SB2290SG (best torque/$, brushless) or Hitec D845WP (waterproof equivalent torque).

#### Tier 2: Industrial fallback

| Servo | Torque | Voltage | Notes | Price |
|---|---|---|---|---|
| **GearWurx Torxis i00600** | 1600 oz·in (115 kg·cm) cont., 3200 oz·in stall | 12 V | Embedded Jrk 21v3 USB controller; aluminum housing; manufacturer lists "unmanned ground vehicle controls" as application | $339 |
| GearWurx Torxis i00800 | 800 oz·in (57 kg·cm), faster | 12 V | Speed variant | ~$339 |

#### Tier 3: Linear actuators (community alternative)

| Actuator | Force | Speed | Stroke | Voltage | Price |
|---|---|---|---|---|---|
| **Actuonix L16-100-150-12-P** | 40 lbs (175 N) | ~8 mm/sec | 100 mm | 12 V (analog feedback; needs LAC board for PWM) | $80 |
| Actuonix L16-100-63-12-P | 22 lbs | ~20 mm/sec | 100 mm | 12 V | $80 |

Used by BenBBB and Max_G with `SERVO1_FUNCTION=73` / `SERVO3_FUNCTION=74`. Worm-gear actuators are **self-locking** (no back-drive) — good for holding but **incompatible with passive spring-return-to-neutral**.

#### Recommendation matrix

| Priority | Pick | Cost (pair) |
|---|---|---|
| **Best overall** | Savox SB2290SG | $328 |
| Best waterproof | Hitec D845WP | $270 |
| Industrial fallback | Torxis i00600 | $678 |
| Best budget | Savox SA1230SG | $206 |

#### 🔴 SELECTED SERVO (overrides recommendation matrix above)

> **Servos chosen for the build: ASMC-04A Robot Servo High Torque 12 V – 24 V** (×2, one per hydrostatic lever).
>
> The Tier 1/2/3 candidates above were the original research recommendations; they are retained for traceability. The actual hardware decision is the ASMC-04A.

**ASMC-04A — properties to verify before integration commit:**

The ASMC-04A is a Chinese-market industrial-style high-torque servo with 12–24 V supply. It is plausibly suitable for Z254 lever actuation at this voltage/torque class. **Control interface is confirmed as standard 1000–2000 µs PWM** — wires directly to Cube Orange `SERVO1`/`SERVO3` outputs (`SERVO1_FUNCTION=73`, `SERVO3_FUNCTION=74` per Phase 3 baseline); no PWM-to-serial bridge required. **Gear type is confirmed as back-driveable** — the passive spring-return-to-neutral safety chain established in §4 and Phase 7 §3 is intact. **One spec remains to verify before integration commit:**

| Spec | Why it matters | Action if confirmed | Action if denied |
|---|---|---|---|
| **Holding torque + position-hold under engine vibration** | Phase 5 §2 notes the Kawasaki FR691V vibrates significantly. Industrial servos with position feedback typically hold well, but unverified for the ASMC-04A. | Standard mounting + Sorbothane isolation suffices | Add accelerometer-based vibration monitoring; may require stiffer linkage |

**✅ Control interface (RESOLVED — confirmed by user 2026-04-17):** ASMC-04A accepts standard hobby PWM (1000–2000 µs, ~50 Hz). Wires directly from Cube Orange servo rail to the ASMC-04A signal pin; ground common between FC and servo power supply. No bridge MCU, no firmware translation layer.

**✅ Gear type (RESOLVED — confirmed by user 2026-04-17):** ASMC-04A gearbox is **back-driveable**. When servo power is cut by E-stop, the Hydro-Gear EZT pump centering springs return the lap-bar levers to neutral by back-driving the servo gear train — no software involvement required. Phase 5 §4 Approach A (rely on pump centering spring) is valid; Phase 7 §3 safe-stop architecture applies unchanged. **Verification on physical units:** with servo unpowered, the output horn should rotate freely by hand (some motor-cogging detent is normal; gears must NOT lock).

**Specs to capture from datasheet (and add to Phase 5 follow-ups):**

- Stall torque + continuous torque at 12 V and at 24 V
- No-load speed (sec/60° or RPM)
- Travel range (degrees) and whether reprogrammable (impacts servo-arm length → linear-throw calculation in §4)
- Current draw under load (sizes the inline fuse from mower battery)
- Position-feedback resolution (encoder/pot)
- IP rating (waterproofing for outdoor mower deck environment)
- Connector pinout (signal, power, ground) and PWM pulse-width range / dead-band

**Mechanical interface for the ASMC-04A:** the linkage geometry from §4 (40–50 mm servo arm, 78–98 mm push-rod throw, ball links at both ends) applies regardless of servo brand and remains the recommendation. The ASMC-04A's mounting hole pattern will dictate the bracket fabrication design.

**Power feed (12–24 V native is convenient):** the ASMC-04A runs from the mower battery directly (no high-current 7.4 V BEC needed). Phase 5 follow-up "BEC selection" partially obviated. Verify the inrush current spec to size an inline fuse.

**MVP recommendation status:** **Proceed with ASMC-04A.** With PWM control and back-driveable gears both confirmed, the Phase 3 baseline wiring, the Phase 5 §4 spring-return safety chain (Approach A + B), the Phase 5 §6 calibration utility, and the Phase 7 §3 safe-stop architecture all apply unchanged. The remaining holding-torque-under-vibration check is a tuning/integration item, not a design-blocking unknown.

### 4. Mechanical Interface

**Servo arm length vs. linear throw** (160° travel servo): linear throw $= 2 r_s \sin(\theta/2)$.

| Arm $r_s$ | Linear throw | Effective torque |
|---|---|---|
| 25 mm | 49 mm | High (short throw) |
| 40 mm | 78 mm | Medium (recommended) |
| 50 mm | 98 mm | Lower (recommended) |
| 60 mm | 118 mm | Marginal |

**Linkage rules to avoid binding:** push rod ≥ 3× $r_s$; both attachment points sweep ±40° or less from perpendicular; use **ball links** at both ends; never reach a collinear "dead point."

**🔴 Spring-return safety mechanism (most important mechanical decision):** if the servo loses power/signal/integrity, the lever MUST return to neutral.

| Approach | Pros | Cons |
|---|---|---|
| **A: Rely on Hydro-Gear EZT pump centering spring (recommended)** | Simple; uses existing spring; always works | Servo must overcome spring (already in torque budget) |
| **B: Add external return spring on linkage** | Redundant if pump spring fails | More complexity; raises servo torque needed |
| C: Linear actuator (worm-gear, self-locking) | Holds last position in power loss | **NO passive return to neutral** — needs disconnect mechanism |
| D: Servo with center detent | Simplest if available | Few hobby servos support |

**Recommendation: A + B (redundancy).** Use spur/helical-gear servos (back-driveable). **Savox SB2290SG and Hitec D845WP both use spur/helical gear trains → back-driveable → compatible with passive spring-return.**

> ✅ **ASMC-04A gear type confirmed back-driveable (user, 2026-04-17).** Approach A (rely on Hydro-Gear EZT pump centering spring through the servo) is valid. The Phase 7 §3 safe-stop chain applies as designed: E-stop cuts servo power → pump centering spring back-drives the servo gear train → levers return to neutral → wheels stop. No software involvement; pure mechanics.

**Mounting:** 1/8–3/16" aluminum bracket; rubber grommets or Sorbothane for vibration isolation; mount near existing lever pivot; short push rods. Conformal coating or ABS enclosure if not waterproof.

### 5. PWM Range / Endpoint Conventions

| Param | Standard | Extended |
|---|---|---|
| Pulse | 1000–2000 µs | 500–2500 µs |
| Neutral | 1500 µs | 1500 µs |
| Update rate | 50 Hz | 50–333 Hz (digital) |

ArduPilot params (per Phase 3 baseline): `SERVO1/3_MIN`, `MAX`, `TRIM`, `REVERSED`, `MOT_PWM_TYPE=0`, `MOT_THR_MIN` (deadband %).

**Per-side calibration is mandatory** — left/right transaxles will NOT match due to manufacturing tolerances, linkage geometry differences, servo tolerances, and wear.

**Hydrostatic deadband: typically 5–15% of full range** — must be empirically calibrated with engine running.

### 6. Calibration Utility Design (`mower servo-cal`)

```
Phase A: Mechanical Neutral (engine OFF)
  A1: Command TRIM (1500 µs) to both servos
  A2: Operator confirms levers at mechanical neutral
  A3: If not, operator adjusts linkage → re-confirm
  A4: Save SERVO1_TRIM, SERVO3_TRIM

Phase B: Endpoint Calibration (engine OFF)
  B1: Sweep LEFT toward MAX in 10 µs steps; ENTER at full-forward stop → SERVO1_MAX
  B2: Return to TRIM
  B3: Sweep LEFT toward MIN; ENTER at full-reverse stop → SERVO1_MIN
  B4: Repeat B1-B3 for RIGHT (SERVO3)
  B5: Direction verify; set SERVOn_REVERSED if needed

Phase C: Deadband Calibration (engine ON, wheels on blocks)
  C1: SAFETY CHECK — mower on blocks, wheels free
  C2: Command TRIM
  C3: LEFT — increment +5 µs from TRIM; ENTER when wheel begins to turn (forward deadband)
  C4: LEFT — decrement -5 µs from TRIM; ENTER when wheel begins to turn (reverse deadband)
  C5: Repeat C3-C4 for RIGHT
  C6: MOT_THR_MIN = ceil(max(deadband_pct_left, deadband_pct_right))

Phase D: Output
  - YAML/JSON profile + equivalent ArduPilot params
  - Summary display
```

**Profile output (YAML example):**

```yaml
calibration:
  left:
    servo_output: SERVO1
    function: 73
    trim_us: 1512
    max_us: 1945
    min_us: 1065
    reversed: false
    deadband_fwd_us: 1547
    deadband_rev_us: 1478
    deadband_pct: 7.0
  right:
    servo_output: SERVO3
    function: 74
    trim_us: 1498
    max_us: 1960
    min_us: 1040
    reversed: false
    deadband_fwd_us: 1538
    deadband_rev_us: 1462
    deadband_pct: 8.7
  mot_thr_min: 9
ardupilot_params:
  SERVO1_FUNCTION: 73
  SERVO1_MIN: 1065
  SERVO1_MAX: 1945
  SERVO1_TRIM: 1512
  SERVO1_REVERSED: 0
  SERVO3_FUNCTION: 74
  SERVO3_MIN: 1040
  SERVO3_MAX: 1960
  SERVO3_TRIM: 1498
  SERVO3_REVERSED: 0
  MOT_THR_MIN: 9
  MOT_PWM_TYPE: 0
```

### 7. Safety-Primitive Integration

| Mode | Context | PWM Behavior | Confirmation |
|---|---|---|---|
| **SITL / Dry-run** | Sim or bench without HW | Logged, no real PWM | None |
| Bench test | Real HW, engine OFF, on blocks | Real PWM | Per-step (grouped) |
| Live calibration | Engine ON, wheels on blocks | Real PWM | Per-step + extra warnings |
| Autonomous mowing | Full auto | PWM from FC | ArduPilot's own arming/geofence/failsafe |

**Calibration safety rules:**

1. Each phase transition (A→B→C→D) requires confirmation
2. Within a phase, incremental sweeps don't need per-step confirmation; ENTER stops the sweep
3. **Abort key (`q`) at all times** → immediately commands TRIM PWM to all servos (bypasses confirmation — safety override)
4. **Idle timeout 30 s** → auto-abort, return to neutral, retain saved progress
5. **Hard PWM bounds** (e.g., 900–2100 µs) even if servo physically allows wider range
6. **Rate limit ≤50 µs per step** to prevent sudden lever motion

```python
class ServoCal:
    def __init__(self, safety, dry_run):
        self.safety = safety
        self.dry_run = dry_run

    def command_servo(self, channel, pwm_us):
        if self.dry_run:
            log.info(f"[DRY-RUN] SERVO{channel} = {pwm_us} µs")
            return True
        if not self.safety.confirm_action(
            action=f"Command SERVO{channel} to {pwm_us} µs",
            category="actuator", reversible=True,
            undo_action=f"Return SERVO{channel} to TRIM"):
            return False
        mavlink.set_servo(channel, pwm_us)
        return True

    def abort(self):
        # Bypass confirmation (safety override)
        for ch, trim in self.trims.items():
            mavlink.set_servo(ch, trim)
        log.warning("ABORT: All servos returned to neutral")
```

**Integration with ArduPilot failsafe:** post-calibration `SERVOn_TRIM` becomes the failsafe position. RC/GCS loss → `FS_ACTION=2` (Hold) → servo outputs at TRIM → levers neutral → mower stops; reinforced by pump centering spring + optional external spring.

**Key Discoveries:**

- **Selected hardware: ASMC-04A Robot Servo High Torque 12 V – 24 V** (×2). **Control interface confirmed as standard 1000–2000 µs PWM** (wires directly to Cube Orange `SERVO1`/`SERVO3`). **Gear type confirmed as back-driveable** — the passive spring-return-to-neutral safety chain (Phase 5 §4 + Phase 7 §3) is intact. One spec remains to verify: holding torque under engine vibration (tuning/integration concern, not design-blocking). The original tier 1/2/3 candidates below are retained for traceability.
- ArduPilot Discourse has 37+ threads on ZTR conversions — community consistently uses `SERVO_FUNCTION 73/74` for skid-steer hydrostatic ZTR.
- **Gas dampers have been removed** from this Z254 (confirmed by user 2026-04-17; standard ArduPilot ZTR community practice; reduces force ~40%); dampers are only for operator hand comfort and don't affect hydrostatic function.
- The **Hydro-Gear EZT centering spring provides natural return-to-neutral** when servo power is lost — *if* the servo uses spur/helical gears (back-driveable). **Worm-gear actuators are self-locking and break this safety property.**
- **Savox SB2290SG (694 oz·in, $164)** is the recommended primary servo — adequate torque margin, brushless (vibration-resistant), back-driveable.
- **Torxis i00600 ($339)** is the identified industrial fallback — 1600 oz·in continuous, 12 V native, embedded Jrk 21v3 USB controller; manufacturer lists "unmanned ground vehicle controls."
- Linear actuators (Actuonix L16) are viable and used by BenBBB/Max_G but their slow speed (8 mm/s) limits e-stop response, and worm-gear self-locking eliminates passive spring-return.
- Hydrostatic deadband typically 5–15% of full PWM range — must be empirically calibrated **per-side** with engine running.
- Per-side calibration is **mandatory** — left/right transaxles will NOT be symmetric.
- Calibration must use a "sweep and stop" pattern (operator presses ENTER at mechanical limit) rather than blind PWM commands, because PWM-to-lever mapping depends on linkage geometry that varies per build.
- Standard hobby digital servos (300 Hz position refresh) hold position under engine vibration far better than analog servos (50 Hz).

**External Sources:**

- [ArduPilot Rover Motor & Servo Configuration](https://ardupilot.org/rover/docs/rover-motor-and-servo-configuration.html)
- [ArduPilot Rover Motor & Servo Connections](https://ardupilot.org/rover/docs/rover-motor-and-servo-connections.html)
- [ArduPilot Discourse — ZTR servo conversions](https://discuss.ardupilot.org/search?q=zero%20turn%20mower%20servo) — 37 threads (Kevin Groba, Kenny Trussell, Max_G, BenBBB, marblecreek)
- [ArduPilot Discourse — hydrostatic mower rover](https://discuss.ardupilot.org/search?q=hydrostatic%20mower%20rover)
- [ServoCity servo catalog](https://www.servocity.com/servos/) — verified torque/speed/price for Hitec, Savox
- [Pololu — GearWurx Torxis i00600](https://www.pololu.com/product/1390) — 1600 oz·in industrial servo, $339
- [Actuonix L16 series](https://www.actuonix.com/l16) — linear actuators 22-40 lbs

**Gaps:**

- No direct Z254 lever force measurement — 10-15 lbs is derived from community experience + analysis.
- Several ArduPilot Discourse thread bodies returned 404 on direct fetch (URL format mismatch); only titles/snippets were searchable.
- Savox SB2290SG detailed datasheet (Savox USA pages 404); voltage/current draw figures from general Savox specs.
- Actuonix L16 detailed force/speed curves didn't render; specs from product naming + FAQ.
- No Husqvarna service manual lever-force spec publicly available.

**Assumptions:**

- Gas dampers have been removed (confirmed by user 2026-04-17).
- Z254 uses Hydro-Gear EZT transaxles (standard for Husqvarna Z200-series residential ZTRs).
- Linkage geometry: 40-50 mm servo arm + push rod to 150-200 mm from lever pivot.
- Hobby servos powered at 7.4 V via high-current BEC; Torxis/actuators at 12 V from mower battery.
- Savox SB2290SG gear train is back-driveable (consistent with spur/helical hobby servo design).

**Follow-up needed:**

- **⚠️ ASMC-04A datasheet capture (non-blocking, integration-time):** control interface confirmed as standard 1000–2000 µs PWM (wires directly to Cube Orange `SERVO1`/`SERVO3`); gear type confirmed back-driveable (Phase 5 §4 Approach A + Phase 7 §3 safe-stop chain apply unchanged). Still useful to capture for sizing/tuning: stall/continuous torque at 12 V and 24 V, no-load speed, travel range, current draw, position-feedback resolution, IP rating, connector pinout, inrush current, PWM pulse-width range / dead-band, holding-torque behavior under engine vibration.
- **Physical lever-force measurement** on actual Z254 (spring scale at handle, dampers removed) — validates 10-15 lbs estimate and confirms ASMC-04A torque margin.
- **Linkage geometry prototype** (3D-print or fabricate) — verify 78-98 mm servo throw covers full Z254 lever range with the ASMC-04A's mounting hole pattern and servo arm.
- **Power-feed sizing** — ASMC-04A runs from 12-24 V directly off the mower battery (no high-current 7.4 V BEC needed); size the inline fuse from the ASMC-04A inrush + stall current spec.
- **Servo cable routing** — long PWM signal cables near engine/starter risk EMI; consider shielded cables and keep runs short.
- **Re-attempt deep dive** of Kenny Trussell's and Max_G's ArduPilot Discourse build logs (try alternate URL formats / Google cache).

## Phase 6: Mission file format + coverage pattern generation for 54" deck

**Status:** ✅ Complete
**Session:** 2026-04-17

### 1. Mission File Format Choice — Dual-Format Approach

Two viable options exist; the project should use **both**: a custom YAML "mission definition" as the human-editable source of truth, and the standard `.waypoints` format as the generated upload artifact.

#### Option A: Mission Planner `.waypoints` (QGC WPL 110)

The de facto standard plain-text mission format used by Mission Planner, QGroundControl, MAVProxy, and most ArduPilot tools.

```
QGC WPL 110
<INDEX>\t<CURRENT WP>\t<COORD FRAME>\t<COMMAND>\t<P1>\t<P2>\t<P3>\t<P4>\t<LAT>\t<LON>\t<ALT>\t<AUTOCONTINUE>
```

Example (mowing-relevant):

```
QGC WPL 110
0	1	0	16	0	0	0	0	38.89510000	-77.03660000	0	1
1	0	3	16	0	0	0	0	38.89520000	-77.03650000	0	1
2	0	3	178	2.0	0	0	0	0	0	0	1
3	0	3	16	0	0	0	0	38.89530000	-77.03640000	0	1
```

Where `16`=`MAV_CMD_NAV_WAYPOINT`, `178`=`MAV_CMD_DO_CHANGE_SPEED`, frame `3`=`MAV_FRAME_GLOBAL_RELATIVE_ALT`.

| Aspect | Assessment |
|---|---|
| Pros | Direct upload; loadable in Mission Planner for visual QA; round-trips through MAVLink mission protocol |
| Cons | No metadata (boundary polygon, exclusions, line spacing, overlap, pattern type); tab-separated, error-prone to hand-edit; no geofence in same file; numeric command IDs are opaque |
| ArduPilot quirk | Seq 0 is the home position, not a mission item — actual mission starts at seq 1 |

#### Option B: Custom YAML Mission Definition

```yaml
version: 1
name: "Front lawn — full coverage"
created: "2026-04-17T14:30:00"

home: { lat: 38.8951000, lon: -77.0366000 }

boundary:
  - [38.89510, -77.03660]
  - [38.89510, -77.03400]
  - [38.89350, -77.03400]
  - [38.89350, -77.03660]
  - [38.89510, -77.03660]

exclusion_zones:
  - name: "flower bed"
    polygon:
      - [38.89480, -77.03550]
      - [38.89480, -77.03520]
      - [38.89460, -77.03520]
      - [38.89460, -77.03550]
      - [38.89480, -77.03550]

coverage:
  pattern: boustrophedon         # boustrophedon | spiral | custom
  cutting_width_in: 54           # Z254 deck
  overlap_pct: 10
  angle_deg: auto                # auto = optimize, or fixed degrees from north
  headland_passes: 2
  mow_speed_mps: 2.0
  turn_speed_mps: 1.0

output:
  waypoints_file: "mission.waypoints"
  geojson_file: "mission.geojson"
```

| Aspect | Assessment |
|---|---|
| Pros | Human-readable; full intent capture; Git-versionable; regenerate `.waypoints` on demand; extensible |
| Cons | Extra tooling to parse + generate; not loadable directly in Mission Planner |

#### Recommendation: Dual format

```
mission.yaml  →  [mower mission plan]  →  mission.waypoints  (ArduPilot upload)
   (source)          (CLI tool)         →  mission.geojson    (visualization)
```

YAML is the source of truth; `.waypoints` is the generated upload artifact (and Mission Planner QA fallback); GeoJSON is the visualization export.

### 2. MAVLink Mission Protocol — Round-Trip

**Upload sequence:**

```
GCS → Drone:  MISSION_COUNT (count=N)
Drone → GCS:  MISSION_REQUEST_INT (seq=0)
GCS → Drone:  MISSION_ITEM_INT (seq=0, cmd=16, lat*1e7, lon*1e7, ...)
   ... repeat seq=1..N-1 ...
Drone → GCS:  MISSION_ACK (type=MAV_MISSION_ACCEPTED)
```

**Download sequence:**

```
GCS → Drone:  MISSION_REQUEST_LIST
Drone → GCS:  MISSION_COUNT (count=N)
GCS → Drone:  MISSION_REQUEST_INT (seq=0)
Drone → GCS:  MISSION_ITEM_INT (seq=0, ...)
   ... repeat ...
GCS → Drone:  MISSION_ACK (type=MAV_MISSION_ACCEPTED)
```

**pymavlink upload sketch:**

```python
def upload_mission(mav, items):
    mav.waypoint_clear_all_send()
    mav.recv_match(type='MISSION_ACK', blocking=True, timeout=5)
    mav.waypoint_count_send(len(items))
    for i, item in enumerate(items):
        req = mav.recv_match(type=['MISSION_REQUEST_INT', 'MISSION_REQUEST'],
                             blocking=True, timeout=5)
        if req is None:
            raise TimeoutError(f"No request for item {i}")
        mav.mav.mission_item_int_send(
            mav.target_system, mav.target_component,
            item['seq'], item['frame'], item['command'],
            1 if i == 0 else 0,           # current
            item.get('autocontinue', 1),
            item.get('param1', 0), item.get('param2', 0),
            item.get('param3', 0), item.get('param4', 0),
            item['x'],   # lat * 1e7
            item['y'],   # lon * 1e7
            item['z'],   # alt
            0,           # MAV_MISSION_TYPE_MISSION
        )
    ack = mav.recv_match(type='MISSION_ACK', blocking=True, timeout=10)
    if ack.type != mavutil.mavlink.MAV_MISSION_ACCEPTED:
        raise RuntimeError(f"Mission upload failed: {ack.type}")
```

**ArduPilot quirks:**

- **Seq 0 = home position** (auto-populated; not a mission item)
- **Upload is NOT atomic** — failed upload leaves a partial mission; always verify round-trip after upload
- **Float rounding** — `param1–4` stored with limited precision; compare with tolerance, not equality
- **Max mission size** — Cube Orange supports 700+ items; sufficient for 4 acres
- **Cannot clear during Auto mode** — must upload a new mission instead

### 3. ArduPilot Rover Mission Commands for Mowing

| Command | ID | Use |
|---|---|---|
| `MAV_CMD_NAV_WAYPOINT` | 16 | Each pass endpoint; `param1`=hold time (0=continuous) |
| `MAV_CMD_DO_CHANGE_SPEED` | 178 | Set mowing speed on straight passes; reduce for headland turns (`param2`=m/s) |
| `MAV_CMD_DO_SET_SERVO` | 183 | Optional: blade engagement relay/servo on a spare output (NOT for steering) |
| `MAV_CMD_NAV_RETURN_TO_LAUNCH` | 20 | Final item — return home after coverage |
| `MAV_CMD_DO_SET_RESUME_REPEAT_DIST` | 215 | Rewind distance on mission resume after pause |
| `MAV_CMD_NAV_LOITER_TIME` | 19 | Optional pause at a point |
| `MAV_CMD_DO_FENCE_ENABLE` | 207 | Enable geofence at mission start |
| `MAV_CMD_DO_JUMP` | 177 | Repeat sections (e.g., multiple coverage passes) |

Typical mowing mission outline:

```
seq 0:    HOME (auto-populated)
seq 1:    DO_CHANGE_SPEED (2.0 m/s)
seq 2..M: NAV_WAYPOINT × headland perimeter
seq M+1:  DO_CHANGE_SPEED (2.0 m/s)        — confirm pass speed
seq M+2..N: NAV_WAYPOINT × boustrophedon row endpoints
seq N+1:  NAV_RETURN_TO_LAUNCH
```

### 4. Coverage Pattern + Line Spacing for 54" Deck

**Line spacing formula:**

$$\text{line\_spacing} = \text{cutting\_width} \times \left(1 - \frac{\text{overlap\_pct}}{100}\right)$$

| Overlap % | Line spacing (in) | Line spacing (m) |
|---|---|---|
| 0 % | 54.0" | 1.372 m |
| 5 % | 51.3" | 1.303 m |
| **10 %** | **48.6"** | **1.234 m** |
| 15 % | 45.9" | 1.166 m |
| 20 % | 43.2" | 1.097 m |

**Recommendation: 10 % overlap (48.6" / 1.234 m).** Industry standard for GPS-guided mowing; provides margin over RTK position error (~2–3 cm) + tracking error (~5–10 cm) + minor boundary misalignment.

**4-acre coverage estimate** (16,187 m² at 1.234 m spacing, ~120 m average pass length): ~131 passes × 120 m ≈ 15.7 km path; at 2.0 m/s ≈ 2.2 h mowing time + headland turns ≈ **2.5–3.0 h total**. Waypoint count ~262 pass endpoints + ~262 turn anchors + DO commands ≈ **550–600 items** (well within Cube Orange capacity).

**Boustrophedon algorithm** (convex polygon):

1. Choose sweep angle (auto-optimize across 0–180° in 5° steps to minimize pass count)
2. Compute line spacing
3. Generate parallel lines across polygon at spacing
4. Clip each line to boundary
5. Order lines snake/zigzag (odd rows forward, even rows reverse)
6. Headland turns are handled natively by ArduPilot (see §5)

For concave / hole-bearing polygons: decompose into convex sub-cells (trapezoidal or boustrophedon decomposition), generate boustrophedon within each, connect with transit segments.

### 5. Headland Turns — ArduPilot Native Pivot Support

**Critical finding: ArduPilot Rover has built-in pivot turn support for skid-steer.** The mission does NOT need explicit pivot waypoints — ArduPilot handles 180° row-end turns natively.

| Parameter | Value | Effect |
|---|---|---|
| `WP_PIVOT_ANGLE` | 60 | Trigger pivot when heading error >60° (covers 180° row-end turns) |
| `WP_PIVOT_RATE` | 45 | deg/s max pivot rate — conservative for heavy mower |
| `ATC_STR_ANG_P` | 2.0 (default) | Heading error → turn rate gain during pivot |
| `ATC_STR_RAT_MAX` | 90 | Global max turn rate |
| `ATC_STR_ACC_MAX` | 60 (default) | Max rotational acceleration |
| `WP_RADIUS` | 1.0 | Waypoint acceptance radius |

How it works: when the rover reaches a waypoint and the heading to the next waypoint exceeds `WP_PIVOT_ANGLE`, it stops, pivots in place until heading is within ~10° of target, then resumes forward motion. At end-of-row in a boustrophedon pattern, heading delta is ~180° → ArduPilot pivots automatically.

**S-Curves (default, `WP_PIVOT_ANGLE=0`) are wrong for mowing** — they cut corners and leave uncut strips at row ends. Always set `WP_PIVOT_ANGLE > 0` for mowing.

**Implication for the planner:** the coverage planner just emits straight-line pass endpoints; ArduPilot handles turn geometry. No headland-turn waypoints needed in the mission file.

### 6. Open-Source Coverage Planning Libraries

#### Fields2Cover

| Property | Value |
|---|---|
| Repo | [Fields2Cover/Fields2Cover](https://github.com/Fields2Cover/Fields2Cover) |
| License | BSD-3-Clause |
| Language | C++17 + Python SWIG bindings |
| Status | Active, v2.0; 792 stars |
| Deps | GDAL, Eigen3, OR-tools (optional), tinyxml2, nlohmann-json, GEOS |
| Tested platforms | Ubuntu 18/20/22, ARM64 Dockerfile; **Windows untested** |
| Algorithms | Headland generation, trapezoidal/boustrophedon decomposition, swath generation (BruteForce angle optimization), snake-order route planning, OR-tools TSP, Dubins/Reeds-Shepp paths |

Pipeline (matches our needs):

```
Field boundary → Headland generation → Cell decomposition (if concave)
  → Swath generation (angle optimization) → Snake-order route → Path planning
```

```python
import fields2cover as f2c

boundary = f2c.F2CLinearRing()
for x, y in [(0,0), (120,0), (120,135), (0,135), (0,0)]:
    boundary.addPoint(f2c.F2CPoint(x, y))
cells = f2c.F2CCells(f2c.F2CCell(boundary))

robot = f2c.F2CRobot(2.0, 1.234)   # vehicle_width, coverage_width
robot.setMinRadius(0.01)            # near-zero turn radius (pivot)

const_hl = f2c.hg_ConstHL()
no_hl = const_hl.generateHeadlands(cells, 2.0 * robot.getWidth())

bf = f2c.sg_BruteForce()
swaths = bf.generateBestSwaths(f2c.obj_NSwath(),
                               robot.getCovWidth(),
                               no_hl.getGeometry(0))
swaths = f2c.rp_SnakeOrder().genSortedSwaths(swaths)
```

| Criterion | Rating | Notes |
|---|---|---|
| Concave polygon support | ✅ Excellent | v2.0 trapezoidal + boustrophedon decomposition |
| Exclusion zones | ✅ | v2.0 |
| Swath angle optimization | ✅ | BruteForce + NSwath cost |
| Snake/boustrophedon ordering | ✅ | Built-in |
| Python API | ✅ SWIG, but no `pip install` — must build from source |
| Offline | ✅ | Pure computation |
| Windows | ⚠️ Untested — likely needs WSL2/Docker |
| Dependency weight | ❌ Heavy — GDAL, OR-tools, GEOS, CMake build |
| Stability | ⚠️ "Early development" per README |

**Conflict with C-8:** Fields2Cover's heavy deps + CMake/SWIG build conflict with the project's "uv + pipx" packaging philosophy.

#### Shapely + custom implementation (RECOMMENDED for MVP)

| Property | Value |
|---|---|
| Libraries | Shapely + pyproj |
| License | BSD-3 (Shapely), MIT (pyproj) |
| Install | `pip install shapely pyproj` — pure-Python wheels, no build step |
| Windows | ✅ Native |
| Deps | GEOS (bundled in wheel), numpy |

```python
from shapely.geometry import Polygon, LineString, MultiLineString
from shapely import affinity

def generate_boustrophedon(boundary_coords, exclusion_polys,
                           cutting_width_m, overlap_pct, angle_deg=None):
    field = Polygon(boundary_coords)
    for exc in exclusion_polys:
        field = field.difference(exc)

    spacing = cutting_width_m * (1 - overlap_pct / 100)

    if angle_deg is None:
        best_angle, best_count = 0, float('inf')
        for a in range(0, 180, 5):
            n = _count_passes(field, spacing, a)
            if n < best_count:
                best_angle, best_count = a, n
        angle_deg = best_angle

    rotated = affinity.rotate(field, -angle_deg, origin='centroid')
    minx, miny, maxx, maxy = rotated.bounds

    passes, y, row_idx = [], miny + spacing/2, 0
    while y < maxy:
        line = LineString([(minx-10, y), (maxx+10, y)])
        clipped = rotated.intersection(line)
        geoms = [clipped] if isinstance(clipped, LineString) else (
            list(clipped.geoms) if isinstance(clipped, MultiLineString) else [])
        for g in geoms:
            coords = list(g.coords)
            if row_idx % 2 == 1:
                coords.reverse()
            passes.append(coords)
            row_idx += 1
        y += spacing

    return [list(affinity.rotate(LineString(p), angle_deg,
                                 origin=field.centroid).coords)
            for p in passes]
```

| Factor | Fields2Cover | Shapely custom |
|---|---|---|
| Algorithm quality | ✅ Research-grade + OR-tools | ⚠️ Basic but sufficient for residential lawns |
| Concave field handling | ✅ Decomposition | ⚠️ Suboptimal without manual decomposition |
| Install complexity | ❌ CMake + SWIG + GDAL + OR-tools | ✅ `pip install` |
| Windows | ❌ WSL2/Docker | ✅ Native |
| MVP fit (C-8) | ❌ Conflict | ✅ Fits |

**Recommendation for MVP: Shapely + pyproj custom implementation.** Sufficient for convex / simple-concave residential lawns. Keep Fields2Cover as an upgrade path for complex field shapes in a later release.

Other libraries considered: **CGAL** (overkill, no coverage-specific algos, GPL/LGPL), **boustrophedon_cellular_decomposition** (ROS-bound), various academic GitHub repos (not production quality).

### 7. Visualization

| Option | Format | Viewer | Effort |
|---|---|---|---|
| Terminal ASCII | Text | Terminal | Low |
| **GeoJSON** | `.geojson` | QGIS (offline), geojson.io, Google Earth | Trivial (`json.dumps`) |
| KML | `.kml` | Google Earth, QGIS | `simplekml` package |
| Mission Planner QA | `.waypoints` | Mission Planner | Already generated |

**Recommendation: GeoJSON as primary visualization export + `.waypoints` for Mission Planner QA.** GeoJSON is trivial to generate, viewable offline in QGIS, supports boundary + exclusions + path lines in a single FeatureCollection.

```python
def mission_to_geojson(boundary, exclusions, passes, output_path):
    features = [{
        "type": "Feature",
        "properties": {"name": "boundary", "type": "boundary"},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[lon, lat] for lat, lon in boundary]]},
    }]
    for i, exc in enumerate(exclusions):
        features.append({
            "type": "Feature",
            "properties": {"name": f"exclusion_{i}", "type": "exclusion"},
            "geometry": {"type": "Polygon",
                         "coordinates": [[[lon, lat] for lat, lon in exc]]},
        })
    for i, p in enumerate(passes):
        features.append({
            "type": "Feature",
            "properties": {"name": f"pass_{i}", "type": "coverage_pass", "index": i},
            "geometry": {"type": "LineString",
                         "coordinates": [[lon, lat] for lat, lon in p]},
        })
    with open(output_path, 'w') as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)
```

### 8. Coordinate Handling

Boundary + exclusion zones come in WGS84 lat/lon (RTK GPS survey or Google Earth trace). Coverage planning must use a local metric coordinate system (UTM or local tangent plane) for accurate distance work.

```
WGS84 lat/lon  →  pyproj UTM transform  →  Shapely ops in meters
              →  pyproj WGS84 back  →  MISSION_ITEM_INT (lat*1e7, lon*1e7)
```

```python
from pyproj import Transformer

def get_utm_transformer(lat, lon):
    zone = int((lon + 180) / 6) + 1
    epsg_utm = 32600 + zone if lat >= 0 else 32700 + zone
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg_utm}", always_xy=True)
    to_wgs = Transformer.from_crs(f"EPSG:{epsg_utm}", "EPSG:4326", always_xy=True)
    return to_utm, to_wgs
```

**Key Discoveries:**

- **Dual-format approach is optimal:** YAML mission definition (source of truth) → generated `.waypoints` (ArduPilot upload) + GeoJSON (visualization). Satisfies both the project's YAML config philosophy and Mission Planner interoperability.
- **ArduPilot Rover has native pivot-turn support** (`WP_PIVOT_ANGLE` + `WP_PIVOT_RATE`) — the mission does NOT need explicit pivot waypoints. `WP_PIVOT_ANGLE=60` triggers automatic 180° row-end pivots.
- **S-Curves (default, `WP_PIVOT_ANGLE=0`) are wrong for mowing** — they cut corners and leave uncut strips at row ends.
- **Fields2Cover** is the most mature open-source CPP library (BSD-3, Python bindings, decomposition support) but its dep weight (GDAL, OR-tools, GEOS, CMake build, Linux-only) conflicts with C-8 (uv/pipx packaging).
- **Shapely + pyproj custom implementation is recommended for MVP** — `pip install`, native Windows, fits uv/pipx; sufficient for convex / simple-concave residential lawns.
- **10 % overlap at 54" cutting width = 48.6" (1.234 m) line spacing** — industry standard for GPS-guided mowing.
- **4-acre mission ≈ 550–600 waypoints** — well within Cube Orange capacity (700+ items).
- **ArduPilot mission seq 0 = home position** (not a mission item); actual mission starts at seq 1.
- **MAVLink mission upload is NOT atomic** on ArduPilot — always verify round-trip after upload.
- **`MAV_CMD_DO_CHANGE_SPEED`** can vary speed between headland passes and straight passes.
- **GeoJSON is the simplest visualization export** — viewable in QGIS (offline) or geojson.io.

**External Sources:**

- [MAVLink Mission Protocol](https://mavlink.io/en/services/mission.html)
- [MAVLink File Formats — QGC WPL 110](https://mavlink.io/en/file_formats/)
- [ArduPilot Rover Mission Commands](https://ardupilot.org/rover/docs/common-mavlink-mission-command-messages-mav_cmd.html)
- [ArduPilot Rover — Tuning Pivot Turns](https://ardupilot.org/rover/docs/rover-tuning-pivot-turns.html)
- [ArduPilot Rover — Tuning Navigation (S-Curves)](https://ardupilot.org/rover/docs/rover-tuning-navigation.html)
- [Fields2Cover GitHub](https://github.com/Fields2Cover/Fields2Cover)
- [Fields2Cover Documentation](https://fields2cover.github.io/)
- [Fields2Cover Paper (IEEE RA-L 2023)](https://ieeexplore.ieee.org/document/10050562)
- [Shapely Documentation](https://shapely.readthedocs.io/)
- [pyproj Documentation](https://pyproj4.github.io/pyproj/)

**Gaps:** None — all Phase 6 vision research topics addressed.

**Assumptions:**

- 4-acre lawn is roughly convex / simple-concave (typical residential); simple boustrophedon sweep with Shapely suffices.
- Boundary coordinates obtained by walking the perimeter with an RTK GPS or tracing in Google Earth/QGIS.
- Operator defines exclusion zones as polygons in the YAML mission definition.
- `WP_PIVOT_ANGLE=60` (Phase 3 baseline) is appropriate for 180° row-end turns; may need field tuning.

**Follow-up needed:**

- Field-test pivot turn behavior at row ends with the actual Z254; tune `WP_PIVOT_RATE` and `ATC_STR_ANG_P` for smooth-but-fast pivots.
- Decide boundary collection workflow (RTK GPS perimeter walk vs. Google Earth trace).
- Evaluate Fields2Cover under WSL2 as an upgrade path for complex field shapes after MVP.
- Test maximum mission item count on Cube Orange with the deployed firmware.
- Consider `MAV_CMD_DO_SET_RESUME_REPEAT_DIST` to enable mid-pass resume.

## Phase 7: Pre-flight check inventory + safe-stop mechanism design

**Status:** ✅ Complete
**Session:** 2026-04-17

### 1. Pre-Flight Check Inventory (`mower preflight`)

Checks are organized in 6 tiers, executed in order. Within a tier, **CRITICAL** failures abort the tier; all tiers are still attempted to give a complete picture. **WARN**-level failures do not block arming.

```
mower preflight [--timeout 180] [--json] [--quick] [--skip TIER]

Tier 1: Hardware Connectivity     (~5 s)
Tier 2: Sensor Health             (~5 s)
Tier 3: RTK Convergence           (~60–180 s) — skipped by --quick if RTK already Fixed
Tier 4: Configuration Integrity   (~3 s)
Tier 5: Mission & Geofence        (~2 s)
Tier 6: Safety Systems            (~2 s)
```

#### Complete check table (33 checks)

| # | Check | Tier | Level | Source | Pass criteria | Fail action |
|---|---|---|---|---|---|---|
| PF-01 | Pixhawk heartbeat | 1 | CRITICAL | `HEARTBEAT` | Within 10 s; type=10 (GROUND_ROVER), autopilot=3 | Abort — no FC |
| PF-02 | Not armed | 1 | CRITICAL | `HEARTBEAT.base_mode` | `MAV_MODE_FLAG_SAFETY_ARMED` not set | Abort — already armed |
| PF-03 | Firmware version | 1 | WARN | `AUTOPILOT_VERSION` | `flight_sw_version` ≥ 4.5.0 | Warn |
| PF-04 | GPS1 detected | 1 | CRITICAL | `GPS_RAW_INT` | Received; `fix_type` ≥ 3 | Abort |
| PF-05 | GPS2 detected | 1 | CRITICAL | `GPS2_RAW` | Received | Abort |
| PF-06 | Servo outputs present | 1 | CRITICAL | `SERVO_OUTPUT_RAW` | Ch1 + Ch3 within ±50 µs of TRIM | Abort |
| PF-07 | SiK link quality | 1 | WARN | `RADIO_STATUS` | rssi>50, remrssi>50, rxerrors<10 | Warn |
| PF-08 | Jetson reachable | 1 | WARN | SSH probe | Connect within 5 s | Warn (non-blocking MVP) |
| PF-09 | OAK-D Pro detected | 1 | WARN | SSH→`depthai` | Device enumerated | Warn (non-blocking MVP) |
| PF-10 | IMU health | 2 | CRITICAL | `SYS_STATUS` | Gyro+Accel health bits set | Abort |
| PF-11 | AHRS ready | 2 | CRITICAL | `SYS_STATUS` | AHRS bit (0x200000) set | Abort |
| PF-12 | EKF status | 2 | CRITICAL | `EKF_STATUS_REPORT` | velocity+position OK, variances <1.0 | Abort |
| PF-13 | Battery voltage | 2 | WARN | `SYS_STATUS.voltage_battery` | > `BATT_ARM_VOLT` or > 11.0 V | Warn |
| PF-14 | Logging subsystem | 2 | WARN | `SYS_STATUS` | Logging bit set | Warn |
| PF-15 | RTK fix quality | 3 | CRITICAL | `GPS_RAW_INT` | `fix_type` == 6 for ≥5 consecutive samples over ≥5 s | Abort |
| PF-16 | Position accuracy | 3 | CRITICAL | `GPS_RAW_INT.h_acc` | < 50 mm | Abort |
| PF-17 | Dual-antenna heading | 3 | CRITICAL | `GPS_RAW_INT.yaw` | ∉ {0, 65535} | Abort |
| PF-18 | MB ambiguity resolved | 3 | CRITICAL | `GPS2_RTK.iar_num_hypotheses` | == 1 | Abort |
| PF-19 | RTCM flowing | 3 | CRITICAL | `GPS_RTK.rtk_rate` | > 0 | Abort |
| PF-20 | Heading accuracy | 3 | WARN | `GPS_RAW_INT.hdg_acc` | < 200 (2.0°) | Warn |
| PF-21 | Satellite count | 3 | WARN | `GPS_RAW_INT.satellites_visible` | ≥ 10 | Warn |
| PF-22 | Params match baseline | 4 | CRITICAL | Param batch read | Critical params match (table below) | Abort — config drift |
| PF-23 | Servo functions correct | 4 | CRITICAL | `SERVO1/3_FUNCTION` | == 73 / == 74 | Abort |
| PF-24 | GPS type correct | 4 | CRITICAL | `GPS1/2_TYPE` | == 17 / == 18 | Abort |
| PF-25 | EKF yaw source | 4 | CRITICAL | `EK3_SRC1_YAW` | == 2 (GPS) | Abort |
| PF-26 | Failsafe params set | 4 | CRITICAL | Batch read | `FS_ACTION≥1`, `FS_GCS_ENABLE≥1`, `FENCE_ENABLE==1` | Abort |
| PF-27 | Mission loaded | 5 | CRITICAL | `MISSION_COUNT` | count ≥ 2 | Abort |
| PF-28 | Mission round-trip OK | 5 | WARN | Download + compare | All items match last upload | Warn |
| PF-29 | Geofence loaded | 5 | CRITICAL | param check | `FENCE_ENABLE==1` AND polygon bit in `FENCE_TYPE` | Abort |
| PF-30 | Vehicle inside fence | 5 | CRITICAL | `FENCE_STATUS.breach_status` | == 0 | Abort |
| PF-31 | ArduPilot pre-arm clear | 6 | CRITICAL | Try arm + `STATUSTEXT` | No pre-arm failure messages | Abort — surface AP failures |
| PF-32 | E-stop circuit armed | 6 | WARN | Operator confirmation | Operator confirms | Warn |
| PF-33 | Servo neutral verified | 6 | WARN | `SERVO_OUTPUT_RAW` | Within ±20 µs of calibrated TRIM | Warn |

#### Critical parameter baseline comparison (PF-22)

| Parameter | Expected | Match | Why critical |
|---|---|---|---|
| `SERVO1_FUNCTION` | 73 | exact | Wrong = no steering |
| `SERVO3_FUNCTION` | 74 | exact | Wrong = no steering |
| `GPS1_TYPE` | 17 | exact | Wrong = no RTK heading |
| `GPS2_TYPE` | 18 | exact | Wrong = no RTK heading |
| `EK3_SRC1_YAW` | 2 | exact | Wrong yaw source = no heading |
| `FS_ACTION` | ≥1 | min | 0 = failsafe disabled |
| `FS_GCS_ENABLE` | ≥1 | min | 0 = GCS failsafe off |
| `FENCE_ENABLE` | 1 | exact | 0 = no geofence |
| `ARMING_REQUIRE` | 1 | exact | 0 = motors can spin unexpectedly |
| `MOT_SAFE_DISARM` | 0 | exact | 1 = no PWM on disarm (levers might not center) |
| `CRUISE_SPEED` | baseline | ±0.5 m/s | Drift = unexpected behavior |
| `WP_SPEED` | baseline | ±0.5 m/s | Drift = unexpected behavior |

### 2. Safe-Stop Architecture — Precedence

Three independent stop mechanisms form a defense-in-depth architecture. **Physical E-stop has absolute authority — no software can override it.**

```
┌─────────────────────────────────────────────────────────────┐
│  LEVEL 0: PHYSICAL E-STOP (highest authority)              │
│  ► Cuts ignition coil → engine dies (1-3 s coast-down)     │
│  ► Cuts servo power → springs return levers to neutral     │
│  ► ArduPilot CANNOT override — purely electrical           │
├─────────────────────────────────────────────────────────────┤
│  LEVEL 1: ARDUPILOT DISARM / HOLD                          │
│  ► FC sets servo outputs to TRIM → levers neutral          │
│  ► Engine continues running                                │
├─────────────────────────────────────────────────────────────┤
│  LEVEL 2: SOFTWARE RTL / SmartRTL                          │
│  ► FC navigates back to launch, then holds                 │
├─────────────────────────────────────────────────────────────┤
│  LEVEL 3: MISSION PAUSE (lowest)                           │
│  ► HOLD; resumes on command                                │
└─────────────────────────────────────────────────────────────┘
```

**State preserved by stop level:**

| State | E-stop | HOLD/Disarm | RTL | Pause |
|---|---|---|---|---|
| Mission progress | ❌ Lost (must re-arm) | ✅ | ❌ Aborted | ✅ |
| Vehicle position | ✅ | ✅ | ✅ | ✅ |
| SmartRTL breadcrumb | ✅ | ✅ | In use | ✅ |
| DataFlash log | ✅ | ✅ | ✅ | ✅ |

### 3. Physical E-Stop Design for the Z254

> 🔄 **Hardware update (2026-04-17): three existing PWM-driven engine/blade relays are already installed on the mower and wire directly to the Cube Orange.**
>
> | Relay | Purpose | Control signal | Fail state (no signal / power loss) | Suggested AP output |
> |---|---|---|---|---|
> | **Ignition cutoff** | Emergency engine kill (grounds Kawasaki FR691V kill wire) | 1000–2000 µs PWM | **Engine OFF** (kill grounded) | `SERVO5` (MAIN 5) |
> | **Starter motor** | Crank the engine (momentary — pulse-high to crank, release to stop) | 1000–2000 µs PWM | **Disengaged** (no crank) | `SERVO6` (MAIN 6) |
> | **Blade clutch (PTO)** | Engage / disengage cutting deck | 1000–2000 µs PWM | **Disengaged** (blade OFF) | `SERVO7` (MAIN 7) |
>
> **Wired to Cube Orange MAIN outputs, not AUX.** Steering servos occupy `SERVO1` (left) and `SERVO3` (right) on MAIN; the three relays sit on the remaining MAIN channels. This leaves all 6 AUX pins (`SERVO9`–`SERVO14`) free for the wheel encoders and other GPIO use.
>
> All three accept standard servo PWM and are **fail-safe OFF** — loss of FC, loss of servo rail power, or loss of signal defaults to engine-off / starter-disengaged / blade-disengaged. This matches the spring-return-to-neutral safety philosophy for the steering servos.
>
> **Implications for the wiring/BOM below:**
>
> - **The Bosch-style 30 A SPDT relay BOM line is superseded** for the *ignition kill* path. (A separate servo-rail power relay may still be desirable to break the steering-servo BEC supply on E-stop and force spring-return-to-neutral; that is a different relay than the one being superseded here. For MVP, cutting the FC's PWM signal to the existing ignition relay is sufficient because the relay itself is fail-safe-OFF.)
> - **The physical E-stop button** should break the ignition relay's PWM signal line (or its supply) so the cutoff is *independent* of the flight controller — preserving the "E-stop has absolute authority" property. Routing the same E-stop break through the blade-clutch relay's signal line is recommended (defense in depth: blade stops even if FC keeps commanding engage).
> - **ArduPilot integration:** assign each output to its MAIN channel as above, e.g. `SERVO5_FUNCTION=-1` (RCPassThru) or `SERVO5_FUNCTION=1` (Script1) and drive via Lua, or use `MAV_CMD_DO_SET_SERVO` from `mower safe-stop`, `mower start-engine`, `mower blade {on|off}`, and from mission `DO_SET_SERVO` items. The starter is **momentary** — the start-engine workflow must time-bound the crank pulse (e.g. 2–3 s max, abort if engine doesn't start) to avoid burning the starter motor.
> - **Boot-time PWM trim is critical for all three:** configure `SERVOn_TRIM` (and `SERVOn_MIN`/`MAX` orientation) so the boot-time PWM corresponds to the *fail-safe state* (ignition=kill-asserted, starter=disengaged, blade=disengaged). Only command the *active* PWM after pre-flight passes and the operator explicitly arms / starts / engages.
> - **Mission integration:** blade engage/disengage becomes a `MAV_CMD_DO_SET_SERVO` mission item at the start/end of mowing passes, replacing manual PTO control. (See Phase 6 mission table — the existing `MAV_CMD_DO_SET_SERVO` row for blade engagement now maps to a real, present-on-vehicle relay.)
> - **Kawasaki FR691V kill-wire identification (Open Question)** is *still required* — the existing ignition relay terminates somewhere in the ignition harness, but the wire identification is needed to verify the relay is wired to the magneto kill terminal. Bench-verify by commanding the kill-PWM with the engine running before any field operation. Likewise, bench-verify the starter and blade relays by commanding each PWM with the engine off and confirming the expected effect (starter cranks; blade clutch clicks).
> - **Spring-return-to-neutral chain is intact:** Phase 5's back-driveable ASMC-04A + Hydro-Gear EZT centering springs still provide the mechanical safe-stop on servo-power loss. The ignition cutoff, blade-clutch cutoff, and steering-servo-power cutoff remain *independent* failure paths.
>
> The wiring diagram, hardware table, and FR691V mechanism notes below are retained for traceability of the original recommendation; treat the "Servo BEC power relay" row as the only relay that may still need to be sourced, and treat the "Ignition kill", "Starter", and "Blade clutch" paths as **already implemented in mower hardware**.

#### Z254 stock safety switches

- **Operator Presence Switch (seat):** must be **bypassed** for autonomous operation (standard ArduPilot ZTR community practice).
- **PTO switch:** retained for manual blade engagement.

#### Recommended E-stop wiring

The E-stop must achieve TWO simultaneous effects:

1. **Kill the engine** — ground the Kawasaki FR691V kill wire (same path the key switch uses)
2. **Cut servo power** — de-energize the servo BEC input → servos lose holding torque → pump centering springs return levers to neutral

```
[BIG RED MUSHROOM BUTTON] (NC contacts, IP65, twist-release)
       │
       ├──► Ignition coil kill wire (grounds coil → engine stops)
       │
       └──► Servo BEC power relay (breaks 12 V input → servos lose power
                                   → pump centering springs → levers neutral)

ALSO WIRED:
► Pixhawk AUX GPIO input (logs E-stop event via RCx_OPTION=31 or Lua)

NOT cut by E-stop:
► Pixhawk power (independent BEC) — keeps logging
► Jetson power (independent supply) — keeps running
► SiK radios — keeps telemetry flowing
```

#### Hardware recommendations

| Component | Recommendation | Cost |
|---|---|---|
| Button | Schneider XB4-BS8442 mushroom-head, IP65, NC, twist-release | ~$20 |
| Servo power relay | Bosch-style automotive 30 A SPDT, 12 V coil, NC contact | ~$10 |
| Ignition kill | Direct ground of Kawasaki FR691V kill terminal (same as key switch OFF) | $0 |
| FC notification | NC contact → Pixhawk AUX GPIO; `RCx_OPTION=31` (Motor E-stop) | $0 |
| Mounting | Dashboard-accessible from operator standing position (3–5 ft reach) | — |

**Kawasaki FR691V kill mechanism:** magneto ignition with kill wire — grounding shorts coil primary to ground. Engine coasts to stop in 1–3 s; blades spin down in 3–5 s.

**Spring-return integration (from Phase 5):** Savox SB2290SG (recommended) uses spur/helical gears = back-driveable. When servo power is cut: servo loses torque → Hydro-Gear EZT centering spring pushes swashplate to neutral → wheels stop driving → vehicle coasts 1–3 ft. **Worm-gear actuators (Actuonix L16) would NOT provide this** — they self-lock.

### 4. ArduPilot Failsafe Parameters — Mower-Specific

**Hold (not RTL) is the correct default for a mower** — RTL drives in a straight line potentially through obstacles, garden beds, or people. A ground vehicle can safely stop where it is.

#### Comprehensive failsafe parameter table

| Parameter | Recommended | AP Default | Rationale |
|---|---|---|---|
| `FS_ACTION` | **2** (Hold) | 2 | Stop in place — safest for ground vehicle |
| `FS_TIMEOUT` | 1.5 | 1.5 | RC failsafe trigger time |
| **`FS_THR_ENABLE`** | **0** | 1 | **Critical correction.** GCS-only operation = no RC transmitter. Value 1 (Phase 3) would trigger immediate RC failsafe. Use 0 with `RC_PROTOCOLS=0`, OR use 2 (continue Auto on RC loss) if an RC backup is wired. |
| `FS_THR_VALUE` | 910 | 910 | Irrelevant when THR_ENABLE=0 |
| `FS_GCS_ENABLE` | **1** | 0 | **Must enable** for autonomous mowing — trigger FS_ACTION on GCS link loss |
| `FS_GCS_TIMEOUT` | 5 | 5 | Seconds without GCS heartbeat |
| `FS_CRASH_CHECK` | **2** (Hold + Disarm) | 0 | If demanded throttle but no movement for 2 s, hold + disarm. Critical for a mower that hits a stump. |
| `CRASH_ANGLE` | **30** | 0 (disabled) | Tilt > 30° triggers crash failsafe |
| `FS_EKF_ACTION` | **2** (Hold) | 0 | EKF unhealthy = position/heading unknown = unsafe to navigate |
| `FS_EKF_THRESH` | 0.8 | 0.8 | EKF variance threshold |
| **`FS_OPTIONS`** | **1** | 0 | **Critical.** Bit 0 = recognize failsafes even in Hold mode. Without this, GCS link drop while in Hold is silently ignored. |
| `FENCE_ENABLE` | 1 | 0 | Enable geofence |
| `FENCE_ACTION` | **2** (Hold) | 1 | On breach: Hold (not RTL — RTL might cross boundary further) |
| `FENCE_TYPE` | **7** (Circle + Polygon) | 7 | Polygon = mowing boundary + exclusions; Circle = gross safety net |
| `FENCE_RADIUS` | 200 | 100 | 200 m covers 4-acre lot diagonal (~180 m) with margin |
| `FENCE_MARGIN` | 2 | 2 | Slow-down margin from boundary |
| **`RC_PROTOCOLS`** | **0** | 1 | Disable RC protocol detection — prevents noise on unused RC input from triggering failsafe |

#### GCS-only operation config (no RC transmitter)

```yaml
FS_THR_ENABLE: 0       # Disable RC failsafe entirely
RC_PROTOCOLS: 0         # Prevent noise being detected as RC signal
FS_GCS_ENABLE: 1        # GCS failsafe: trigger FS_ACTION on link loss
FS_GCS_TIMEOUT: 5
FS_ACTION: 2            # Hold
FS_OPTIONS: 1           # Recognize failsafes in Hold mode
```

**Alternative if RC backup is wired:**

```yaml
FS_THR_ENABLE: 2        # Continue Auto mission if RC lost
RC_PROTOCOLS: 1
```

#### Failsafe response matrix

| Event | ArduPilot response | Vehicle behavior | Operator action |
|---|---|---|---|
| GCS link lost (SiK dropout) | FS_ACTION → Hold | Stops in place, engine running | Walk to mower or wait; re-take control via mode switch |
| RTK degrades to Float/3D | EKF variance rises → FS_EKF_ACTION → Hold | Stops in place | Wait for RTK re-lock; if persistent, E-stop |
| RTCM lost (Radio A down) | Fix degrades 6→5→4→3 over 10–60 s; eventually EKF failsafe | Gradual stop | Monitor; if `fix_type < 5` for >30 s, manual E-stop |
| Geofence breach | FENCE_ACTION → Hold | Stops at boundary | Switch to Manual, drive back inside, re-arm |
| Crash detected (stuck) | FS_CRASH_CHECK → Hold + Disarm | Servos to TRIM, levers neutral | Walk to mower, clear obstruction, re-arm |
| EKF failure | FS_EKF_ACTION → Hold | Stops in place | Wait for EKF recovery or E-stop |
| Operator presses E-stop | Engine dies, servos lose power | Springs return levers to neutral | Twist-release E-stop, follow recovery |
| `mower safe-stop` | Mode change → Hold + Disarm | Servos to TRIM, engine running | Follow recovery procedure |
| Tilt > 30° | CRASH_ANGLE → Hold + Disarm | Vehicle stopped (likely tipped) | E-stop; assess damage |

### 5. Software Safe-Stop Command (`mower safe-stop`)

```
mower safe-stop [--mode hold|rtl|smartrtl] [--disarm] [--jetson-shutdown]

Default: --mode hold --disarm
```

```python
def safe_stop(mav, mode="hold", disarm=True, jetson_shutdown=False):
    log.critical("safe_stop_initiated", mode=mode, disarm=disarm)

    mode_map = {
        "hold":     mavutil.mavlink.MAV_MODE_HOLD,
        "rtl":      mavutil.mavlink.MAV_MODE_RTL,
        "smartrtl": mavutil.mavlink.MAV_MODE_SMART_RTL,
    }
    mav.set_mode(mode_map[mode])
    hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=3)
    if not verify_mode(hb, mode):
        log.error("mode_change_failed", requested=mode)
        mav.set_mode(mavutil.mavlink.MAV_MODE_HOLD)  # fallback

    if disarm:
        mav.mav.command_long_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 0, 21196, 0, 0, 0, 0, 0)  # 0=disarm, 21196=force
        ack = mav.recv_match(type='COMMAND_ACK', blocking=True, timeout=5)

    if jetson_shutdown:
        try:
            ssh_exec("jetson.local", "sudo systemctl stop mower-jetson.service")
        except Exception as e:
            log.warning("jetson_shutdown_failed", error=str(e))

    log_vehicle_state(mav)
```

### 6. Jetson ↔ ArduPilot Interaction

**Independence principle (MVP):** Jetson and Pixhawk are operationally independent for Release 1.

| Question | Answer (MVP) | Rationale |
|---|---|---|
| Does Jetson shutdown affect mowing? | **No** | Jetson runs VSLAM (Release 3 only), monitoring, and log collection — not in the ArduPilot control loop for RTK-only mowing |
| Does ArduPilot disarm trigger Jetson shutdown? | **No** | `mower safe-stop --jetson-shutdown` is CLI-level orchestration, not an ArduPilot-triggered event |
| Does Jetson crash affect ArduPilot? | **No (MVP)** | No `VISION_POSITION_ESTIMATE` flow in Release 1 |
| Does E-stop affect Jetson? | **No** | Jetson has independent power supply |

**Release 3 change:** when VSLAM enters the EKF, Jetson crash → vision source lost → EKF falls back to GPS (or triggers EKF failsafe if vision is the primary source via `EK3_SRC1_POSXY=6`).

### 7. Structured Failure Output Schema

#### Pre-flight report JSON schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["version", "timestamp", "result", "checks", "summary"],
  "properties": {
    "version": { "const": "1.0" },
    "timestamp": { "type": "string", "format": "date-time" },
    "result": { "enum": ["PASS", "FAIL", "WARN"] },
    "duration_s": { "type": "number" },
    "checks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "tier", "level", "result"],
        "properties": {
          "id":       { "type": "string", "pattern": "^PF-\\d{2}$" },
          "name":     { "type": "string" },
          "tier":     { "type": "integer", "minimum": 1, "maximum": 6 },
          "level":    { "enum": ["CRITICAL", "WARN"] },
          "result":   { "enum": ["PASS", "FAIL", "SKIP", "TIMEOUT"] },
          "message":  { "type": "string" },
          "measured": {},
          "expected": {},
          "duration_ms": { "type": "integer" }
        }
      }
    },
    "summary": {
      "type": "object",
      "properties": {
        "total":    { "type": "integer" },
        "passed":   { "type": "integer" },
        "failed":   { "type": "integer" },
        "warnings": { "type": "integer" },
        "skipped":  { "type": "integer" },
        "critical_failures": { "type": "array", "items": { "type": "string" } }
      }
    },
    "vehicle_state": {
      "type": "object",
      "properties": {
        "armed": { "type": "boolean" }, "mode": { "type": "string" },
        "gps_fix": { "type": "integer" }, "gps_sats": { "type": "integer" },
        "rtk_h_acc_mm": { "type": "integer" }, "heading_deg": { "type": "number" },
        "battery_v": { "type": "number" }
      }
    }
  }
}
```

#### Exit codes

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | Passed with warnings — arming allowed |
| 2 | Critical check(s) failed — arming blocked |
| 3 | Connection failure — could not reach Pixhawk |
| 4 | Timeout — RTK convergence did not complete |

`mower preflight --json` writes the full JSON report to stdout (pipeable) and a summary to stderr; also archives to `~/.mower/preflight/YYYY-MM-DDTHH-MM-SS.json`.

### 8. Recovery Patterns

#### `mower preflight --quick`

For recovery after software stops where RTK is still locked:

```
Skips:  Tier 1 hardware detection (already connected)
        Tier 3 full RTK convergence (if fix_type still == 6)

Runs:   Tier 2 sensor health (quick)
        Tier 4 param verification
        Tier 5 mission + fence
        Tier 6 safety systems
        Single RTK quality snapshot

Time:   5-10 s (vs. 30-180 s for full preflight)
```

#### Recovery procedures

**After physical E-stop:**

```
1. Walk to mower, assess + clear hazard
2. Twist-release the mushroom button → servo power restored
3. Restart engine (key switch)
4. From laptop: mower preflight (full)
5. mower mission resume (or restart)
6. Arm via GCS, switch to Auto
```

**After software HOLD/Disarm:**

```
1. mower status — assess from laptop
2. mower preflight --quick
3. Arm via GCS
4. mower mission resume (ArduPilot resumes from current waypoint)
```

**After GCS failsafe (link loss → HOLD):**

```
1. Walk closer / check laptop SiK radio
2. Wait for heartbeat to resume
3. mower status — verify link stable
4. Switch mode back to Auto (operator action required even after link recovers)
```

**After crash detect:**

```
1. Walk to mower, clear obstruction, inspect
2. mower preflight (full — crash may have shifted GPS antennas)
3. Adjust exclusion zones if planning issue caused crash
4. Re-arm and resume
```

#### Mission resume

ArduPilot Rover supports native mission resume; `MISSION_CURRENT` tracks the current waypoint through HOLD/Disarm. After E-stop (re-arm cycle), the CLI must offer "resume from waypoint N" by reading the last-known waypoint from logged state.

```python
mav.mav.command_long_send(
    mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_CMD_MISSION_START, 0,
    current_wp, 0, 0, 0, 0, 0, 0)
```

### 9. Leveraging ArduPilot Built-In Pre-Arm Checks

ArduPilot's own pre-arm checks (`ARMING_SKIPCHK`) overlap with our list. Strategy: **leverage, don't duplicate.** Run `mower preflight` first (custom checks), then attempt ArduPilot arm; capture STATUSTEXT failure messages and include them in the report.

```python
def check_ardupilot_prearm(mav, timeout=10):
    while mav.recv_match(type='STATUSTEXT', blocking=False):
        pass  # flush
    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 0, 0, 0, 0, 0, 0)  # try to arm
    ack = mav.recv_match(type='COMMAND_ACK', blocking=True, timeout=timeout)
    if ack and ack.result == 0:
        # Armed — immediately disarm (we were just checking)
        mav.mav.command_long_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 0, 0, 0, 0, 0, 0, 0)
        return True, []
    failures = []
    while True:
        msg = mav.recv_match(type='STATUSTEXT', blocking=True, timeout=2)
        if msg is None:
            break
        if msg.severity <= 3:  # MAV_SEVERITY_ERROR or worse
            failures.append(msg.text)
    return False, failures
```

### 10. Updated Failsafe Baseline (corrects Phase 3)

Integrating Phase 7 with the Phase 3 baseline:

```yaml
# --- Failsafe (PHASE 7 corrections vs. Phase 3) ---
FS_ACTION: 2             # Hold — safest for ground vehicle
FS_TIMEOUT: 1.5
FS_THR_ENABLE: 0         # ⚠ CORRECTED from Phase 3 (was 1) — GCS-only, no RC
FS_THR_VALUE: 910        # (irrelevant with THR_ENABLE=0)
FS_GCS_ENABLE: 1         # CRITICAL for GCS-only operation
FS_GCS_TIMEOUT: 5
FS_CRASH_CHECK: 2        # Hold + Disarm on stuck-vehicle detect (NEW)
CRASH_ANGLE: 30          # Tilt > 30° = crash (NEW)
FS_EKF_ACTION: 2         # Hold on EKF failure (NEW)
FS_EKF_THRESH: 0.8
FS_OPTIONS: 1            # Recognize failsafes in Hold mode (CRITICAL, NEW)
RTL_SPEED: 0             # Use WP_SPEED for RTL
RC_PROTOCOLS: 0          # Disable RC detection (NEW, GCS-only)

# --- Geofence ---
FENCE_ENABLE: 1
FENCE_ACTION: 2          # Hold on breach
FENCE_TYPE: 7            # Circle + Polygon
FENCE_RADIUS: 200
FENCE_MARGIN: 2

# --- SmartRTL (manual use only) ---
SRTL_ACCURACY: 2
SRTL_POINTS: 300         # ≈ 3 km buffer

# --- Arming ---
ARMING_REQUIRE: 1
ARMING_SKIPCHK: 0
ARMING_NEED_LOC: 1
MOT_SAFE_DISARM: 0       # Output TRIM when disarmed
BRD_SAFETY_DEFLT: 0      # No safety switch (Z254 has none)
```

> ⚠️ **Phase 3 correction:** the Phase 3 baseline set `FS_THR_ENABLE=1`, which would trigger immediate RC failsafe under GCS-only operation (no RC transmitter). The correct value is **0** (with `RC_PROTOCOLS=0`).

**Key Discoveries:**

- **Physical E-stop has absolute authority** — cuts ignition + servo power via hardware relay; ArduPilot cannot override. Back-driveable servos (Phase 5) + pump centering springs provide passive mechanical return-to-neutral with NO software involvement.
- **Hold (not RTL) is the correct default failsafe for a mower** — RTL drives in a straight line potentially through obstacles or people. A ground vehicle can safely stop where it is.
- **`FS_THR_ENABLE` must be 0 for GCS-only operation** — Phase 3 had it at 1, which would cause immediate RC failsafe with no RC transmitter connected. Combined with `RC_PROTOCOLS=0`. *(This is a correction to the Phase 3 baseline.)*
- **`FS_OPTIONS=1` is critical** — without it, failsafes are silently IGNORED while in Hold mode, so a GCS link loss after entering Hold is invisible to the operator.
- **`FS_CRASH_CHECK=2` (Hold + Disarm) and `CRASH_ANGLE=30`** provide stuck-vehicle and tip-over protection for a heavy mower.
- Pre-flight is organized in **6 tiers / 33 checks** (CRITICAL vs. WARN levels) covering HW connectivity, sensor health, RTK convergence, config integrity, mission/geofence, and safety systems.
- **ArduPilot built-in pre-arm checks should be leveraged, not duplicated** — attempt arm, capture STATUSTEXT failure messages, surface alongside custom checks.
- **`mower preflight --quick`** enables 5-10 s recovery re-check after software stops by skipping hardware detection and RTK convergence wait.
- **Jetson and ArduPilot are operationally independent for MVP** — Jetson crash does not affect mowing; ArduPilot disarm does not affect Jetson. This changes in Release 3 when VSLAM enters the EKF.
- **SmartRTL is available as a manual safe-stop option** but its 300-point breadcrumb buffer (~3 km) may fill on long mowing missions — not suitable as default failsafe.
- **Mission resume is natively supported** via `MISSION_CURRENT` waypoint tracking through HOLD/Disarm cycles. After E-stop (re-arm cycle), CLI offers "resume from waypoint N" using last-logged state.
- **Geofence: `FENCE_TYPE=7` (Circle + Polygon)** — polygon = mowing boundary + exclusions; circle = gross safety net.
- Structured JSON failure output with **exit codes 0–4** enables scripted workflows and machine-readable archives.

**External Sources:**

- [ArduPilot Rover Failsafes](https://ardupilot.org/rover/docs/rover-failsafes.html) — FS_ACTION, FS_GCS_ENABLE, FS_CRASH_CHECK, FS_EKF_ACTION, FS_OPTIONS
- [ArduPilot Pre-Arm Safety Checks](https://ardupilot.org/rover/docs/common-prearm-safety-checks.html)
- [ArduPilot Arming / Disarming](https://ardupilot.org/rover/docs/arming-your-rover.html)
- [ArduPilot Geofencing](https://ardupilot.org/rover/docs/common-geofencing-landing-page.html)
- [ArduPilot GCS-Only Operation](https://ardupilot.org/rover/docs/common-gcs-only-operation.html)
- [ArduPilot SmartRTL Mode](https://ardupilot.org/rover/docs/smartrtl-mode.html)
- [ArduPilot RTL Mode](https://ardupilot.org/rover/docs/rtl-mode.html)

**Gaps:**

- Kawasaki FR691V ignition kill wire identification (color/pin/location) requires physical inspection or Z254 service manual.
- `FENCE_ACTION=2` (Hold) for **Rover** documented in the Copter table but the Rover-specific table only shows 0/1 — needs SITL verification.
- No tested wireless E-stop keyfob recommendation — wired E-stop only for MVP.

**Assumptions:**

- GCS-only operation during autonomous mowing (no RC transmitter in hand).
- Kawasaki FR691V uses standard magneto kill (ground kill wire = no spark).
- E-stop uses NC contacts (fail-safe: wire break = engine kill).
- Pixhawk and Jetson have independent power supplies not affected by E-stop servo relay.
- Operator can physically reach mower within ~30 s from laptop position.

**Follow-up needed:**

- SITL test: verify `FENCE_ACTION=2` (Hold) is supported in Rover.
- SITL test: verify `FS_THR_ENABLE=0` + `RC_PROTOCOLS=0` allows clean GCS-only arming with no RC failsafe false triggers.
- Identify the Kawasaki FR691V ignition kill wire (color, connector, location) from Z254 service manual.
- Source E-stop hardware: Schneider XB4-BS8442 mushroom button + 30 A SPDT relay.
- Design the E-stop wiring harness (relay + kill wire + GPIO notification to Pixhawk via `RCx_OPTION=31`).
- Consider `ARMING_MIS_ITEMS` to require an RTL item at mission end.
- Build a SITL-based preflight test fixture exercising all 33 checks (with simulated GPS fix, fence breach, etc.).

## Overview

_Synthesized summary across all phases. Will be written after all phases complete._

## Key Findings

_To be populated after all phases complete._

## Actionable Conclusions

_To be populated after all phases complete._

## Open Questions

_To be populated after all phases complete._

## Standards Applied

| Standard | Relevance | Guidance |
|----------|-----------|----------|
| (none yet) | — | — |

## References

### Phase 1 — SITL fidelity

- [ArduPilot SITL usage guide](https://ardupilot.org/dev/docs/using-sitl-for-ardupilot-testing.html)
- [SITL architecture overview](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html)
- [Building SITL on Windows 11 (WSL2)](https://ardupilot.org/dev/docs/building-setup-windows11.html)
- [SITL Native on Windows (Cygwin) — deprecated](https://ardupilot.org/dev/docs/sitl-native-on-windows.html)
- [pymavlink Python guide](https://mavlink.io/en/mavgen_python/)
- ArduPilot/ardupilot — `libraries/SITL/SIM_Rover.cpp`, `libraries/AR_Motors/AP_MotorsUGV.cpp`, `Tools/autotest/rover.py`, `Tools/autotest/sim_vehicle.py`

### Phase 2 — MAVLink-over-SiK + HW detection

- [ArduPilot SiK Telemetry Radio overview](https://ardupilot.org/copter/docs/common-sik-telemetry-radio.html)
- [SiK Advanced Configuration](https://ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html)
- [ArduPilot Requesting MAVLink Data](https://ardupilot.org/dev/docs/mavlink-requesting-data.html)
- [MAVLink Common Message Set](https://mavlink.io/en/messages/common.html)
- [Luxonis DepthAI device information example](https://docs.luxonis.com/software/depthai/examples/device_information/)
- [pymavlink GitHub](https://github.com/ArduPilot/pymavlink)

### Phase 3 — Z254 baseline params

- [Rover Motor & Servo Configuration](https://ardupilot.org/rover/docs/rover-motor-and-servo-configuration.html)
- [GPS for Yaw (Moving Baseline)](https://ardupilot.org/rover/docs/common-gps-for-yaw.html)
- [EKF Source Selection](https://ardupilot.org/rover/docs/common-ekf-sources.html)
- [Rover Failsafes](https://ardupilot.org/rover/docs/rover-failsafes.html)
- [Arming Your Rover](https://ardupilot.org/rover/docs/arming-your-rover.html)
- [Rover Tuning — Throttle and Speed](https://ardupilot.org/rover/docs/rover-tuning-throttle-and-speed.html)
- [Rover Tuning — Steering Rate](https://ardupilot.org/rover/docs/rover-tuning-steering-rate.html)
- [SITL `rover-skid.parm`](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/autotest/default_params/rover-skid.parm)
- [SITL `rover.parm`](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/autotest/default_params/rover.parm)

### Phase 4 — RTK base + simpleRTK3B Heading (mosaic-H)

- **[How to configure Septentrio RTK Heading and connect it to ArduPilot](https://www.ardusimple.com/ardupilot-simplertk3b-heading-configuration/) — official ArduSimple tutorial for this exact board**
- [ArduPilot Septentrio GPS](https://ardupilot.org/copter/docs/common-septentrio-gps.html) — SBF driver, mosaic configuration, attitude support
- [ArduSimple simpleRTK3B Heading product page](https://www.ardusimple.com/product/simplertk3b-heading/)
- [How to configure Septentrio mosaic-X5 / mosaic-H](https://www.ardusimple.com/how-to-configure-septentrio-mosaic-x5-and-mosaic-h/)
- [simpleANT2B Budget Survey multi-band antenna](https://www.ardusimple.com/product/survey-gnss-multiband-antenna/) — recommended matched pair for mosaic-H
- [ArduPilot RTK GPS Correction (Fixed Baseline)](https://ardupilot.org/rover/docs/common-rtk-correction.html)
- [ArduSimple Configuration Files](https://www.ardusimple.com/configuration-files/)
- [SparkFun Rover Base RTK Setup tutorial](https://learn.sparkfun.com/tutorials/setting-up-a-rover-base-rtk-system/all)
- [ArduSimple RTK Starter Kits](https://www.ardusimple.com/rtk-starter-kits/)
- [simpleRTK2B Budget product page](https://www.ardusimple.com/product/simplertk2b/) — base station only

### Phase 5 — Servo selection

- [ArduPilot Rover Motor & Servo Configuration](https://ardupilot.org/rover/docs/rover-motor-and-servo-configuration.html)
- [ArduPilot Rover Motor & Servo Connections](https://ardupilot.org/rover/docs/rover-motor-and-servo-connections.html)
- [ArduPilot Discourse — ZTR servo conversions](https://discuss.ardupilot.org/search?q=zero%20turn%20mower%20servo)
- [ArduPilot Discourse — hydrostatic mower rover](https://discuss.ardupilot.org/search?q=hydrostatic%20mower%20rover)
- [ServoCity servo catalog](https://www.servocity.com/servos/)
- [Pololu — GearWurx Torxis i00600 (1600 oz·in)](https://www.pololu.com/product/1390)
- [Actuonix L16 linear actuator series](https://www.actuonix.com/l16)

### Phase 6 — Mission file format + coverage

- [MAVLink Mission Protocol](https://mavlink.io/en/services/mission.html)
- [MAVLink File Formats — QGC WPL 110](https://mavlink.io/en/file_formats/)
- [ArduPilot Rover Mission Commands](https://ardupilot.org/rover/docs/common-mavlink-mission-command-messages-mav_cmd.html)
- [ArduPilot Rover — Tuning Pivot Turns](https://ardupilot.org/rover/docs/rover-tuning-pivot-turns.html)
- [ArduPilot Rover — Tuning Navigation (S-Curves)](https://ardupilot.org/rover/docs/rover-tuning-navigation.html)
- [Fields2Cover GitHub](https://github.com/Fields2Cover/Fields2Cover)
- [Fields2Cover Documentation](https://fields2cover.github.io/)
- [Fields2Cover paper (IEEE RA-L 2023)](https://ieeexplore.ieee.org/document/10050562)
- [Shapely Documentation](https://shapely.readthedocs.io/)
- [pyproj Documentation](https://pyproj4.github.io/pyproj/)

## Follow-Up Research

### From Phase 3
- Verify simpleRTK2B+heading → Cube Orange physical wiring from ArduSimple product docs (which F9P UART connects to which GPS port)
- On-vehicle servo testing to determine `SERVO1_REVERSED` / `SERVO3_REVERSED` and `MOT_THR_MIN` (hydrostatic deadband)
- Field tuning session: `CRUISE_THROTTLE` via "Learn Cruise" and `ATC_STR_RAT_FF` refinement
- Confirm whether the simpleRTK2B+heading has an internal RTCM cross-link between its two F9Ps; if so, set `GPS_DRV_OPTIONS=1`
- Consider `BATT_LOW_VOLT` / `BATT_FS_LOW_ACT` if battery monitoring is wired

### From Phase 4
- **⚠️ Mosaic-H integration verification (non-blocking; ArduSimple has an official tutorial):** follow [How to configure Septentrio RTK Heading and connect it to ArduPilot](https://www.ardusimple.com/ardupilot-simplertk3b-heading-configuration/) end-to-end and confirm `AttEuler` heading flows into EKF3 with `EK3_SRC1_YAW=2`; verify SBF block list and minimum baud; document Septentrio Web UI antenna-baseline configuration steps. Decide whether to run at 5 Hz or 10 Hz given SBF bandwidth.
- Verify exact `pyubx2` API for `CFG-TMODE-MODE`, `CFG-TMODE-SVIN_MIN_DUR`, `CFG-TMODE-SVIN_ACC_LIMIT`, `CFG-TMODE-ECEF_X/Y/Z`
- Field-test actual RTCM bandwidth at the user's location (estimate 530 B/s may vary with constellation/satellite count)
- Determine whether the SiK radio pair for the RTCM link is purchased separately or comes with an ArduSimple kit
- Consider optional ESP32 status-LED/BLE on the base station for at-a-glance health indication

### From Phase 5
- **⚠️ ASMC-04A datasheet capture (non-blocking, integration-time):** control interface confirmed as standard 1000–2000 µs PWM (wires directly to Cube Orange `SERVO1`/`SERVO3`; Phase 3 baseline applies unchanged); gear type confirmed back-driveable (Phase 5 §4 Approach A + Phase 7 §3 safe-stop chain apply unchanged). Still useful to capture for sizing/tuning: stall/continuous torque at 12 V and 24 V, no-load speed, travel range, current draw, position-feedback resolution, IP rating, connector pinout, inrush current, PWM pulse-width range / dead-band.
- **Physical lever-force measurement** on actual Z254 (spring scale at handle, dampers removed) to validate 10–15 lbs estimate and confirm ASMC-04A torque margin
- **Linkage geometry prototype** (3D-print or fabricate) to verify 78–98 mm servo throw covers full Z254 lever range with the ASMC-04A's mounting pattern and arm
- **Power-feed sizing** — ASMC-04A 12-24 V native runs directly off the mower battery (no high-current 7.4 V BEC needed); size the inline fuse from the ASMC-04A inrush + stall current spec
- **Servo cable routing** — long PWM signal cables near engine/starter risk EMI; consider shielded cables and keep runs short
- Re-attempt deep dive of Kenny Trussell's and Max_G's ArduPilot Discourse build logs (try alternate URL formats / Google cache)

### From Phase 6
- Field-test pivot turn behavior at Z254 row ends; tune `WP_PIVOT_RATE` and `ATC_STR_ANG_P` for smooth-but-fast pivots
- Decide boundary-collection workflow (RTK GPS perimeter walk vs. Google Earth trace)
- Evaluate Fields2Cover under WSL2/Docker as an upgrade path for complex field shapes (post-MVP)
- Test maximum mission item count on Cube Orange with the deployed firmware version
- Consider `MAV_CMD_DO_SET_RESUME_REPEAT_DIST` (cmd 215) to enable mid-pass mission resume after pause

### From Phase 7
- SITL test: verify `FENCE_ACTION=2` (Hold) is supported in ArduPilot Rover (documented for Copter; uncertain for Rover)
- SITL test: verify `FS_THR_ENABLE=0` + `RC_PROTOCOLS=0` allows clean GCS-only arming with no RC failsafe false triggers
- Identify the Kawasaki FR691V ignition kill wire (color, connector, location) from the Z254 service manual
- Source E-stop hardware: Schneider XB4-BS8442 mushroom button (IP65, NC, twist-release) + Bosch-style 30 A SPDT relay
- Design E-stop wiring harness (relay + kill wire + GPIO notification to Pixhawk via `RCx_OPTION=31`)
- Consider `ARMING_MIS_ITEMS` to require an RTL item at mission end
- Build a SITL-based preflight test fixture exercising all 33 checks

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-17 |
| Status | ✅ Complete |
| Current Phase | Complete |
| Path | /docs/research/001-mvp-bringup-rtk-mowing.md |
