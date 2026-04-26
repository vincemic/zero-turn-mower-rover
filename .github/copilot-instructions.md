# Copilot Instructions — Zero-Turn Mower Rover

## Project context

This repo will hold a **CLI tooling suite** for converting a Husqvarna Z254 zero-turn mower into an autonomous RTK-mowing robot. It is **not** the autopilot firmware, **not** the physical build, and **not** a replacement for Mission Planner / QGroundControl. It fills the gaps between existing tools (ArduPilot, u-center, DepthAI, etc.) for a single operator working in a 4-acre yard.

Authoritative project docs (read these before designing or coding anything new):

- Vision: [docs/vision/001-zero-turn-mower-rover.md](docs/vision/001-zero-turn-mower-rover.md)
- Release 1 (MVP) research: [docs/research/001-mvp-bringup-rtk-mowing.md](docs/research/001-mvp-bringup-rtk-mowing.md)

## Hardware stack (do not assume otherwise)

- Flight controller: **Pixhawk Cube Orange** running **ArduPilot Rover** (skid-steer, twin-servo steering arms on `SERVO1` / `SERVO3`, functions `73` / `74`).
- GNSS: **ArduSimple simpleRTK3B Heading** (Septentrio mosaic-H, SBF protocol, dual-antenna heading). The vision still says "simpleRTK2B+heading" — research superseded that; treat the mosaic-H as ground truth.
- Base station: **simpleRTK2B Budget** streaming RTCM3 over a dedicated SiK radio link (no NTRIP, no internet in the field).
- Telemetry: **two SiK radios on the rover** — Radio A = RTCM passthrough (`MAVLINK=0`), Radio B = MAVLink to laptop (`MAVLINK=1`).
- Manual control + on-handset telemetry: **FrSky RC receiver wired directly to the Cube Orange** (RCIN for SBUS, or a Pixhawk serial port for FPort), with **bidirectional FrSky telemetry** (S.Port / FPort) carried back to the operator's FrSky transmitter so flight state, mode, RTK fix, battery, etc. show on the handset display. The receiver is for **manual override and at-handset monitoring**, not for replacing GCS/MAVLink mission control. Autonomous mowing still runs from a saved mission via MAVLink; the operator can take manual control at any time via a mode switch on the FrSky transmitter.
- Steering: **2× ASMC-04A Robot Servo (12–24 V, PWM, back-driveable)** wired to Cube Orange MAIN `SERVO1` / `SERVO3`. Back-driveability is part of the safety chain — do not propose non-back-driveable alternatives.
- Engine/blade I/O: three existing PWM-driven relays on Cube Orange MAIN outputs (e.g. `SERVO5` ignition-kill (fail-safe), `SERVO6` starter (momentary), `SERVO7` blade clutch (fail-safe)). All AUX pins (`SERVO9`–`SERVO14`) remain free.
- Engine monitoring: **inductive RPM pickup** on Kawasaki FR691V spark plug lead (conditioned + opto-isolated to 3.3 V) on a Cube Orange AUX pin via ArduPilot `RPM1`, **plus** bus voltage from the existing power module (`BATTERY_STATUS`). Engine-running = RPM ≥ idle threshold AND voltage ≥ alternator threshold. Level-shifting / opto-isolation is **mandatory** (same 3.3 V AUX rule as encoders). Blade clutch (`SERVO7`) engagement is interlocked on confirmed engine-running.
- Wheel encoders: **2× CALT GHW38** (200 PPR quadrature, push-pull) on Cube Orange AUX pins; **level-shifting 5/12 V → 3.3 V is mandatory** — AUX pins are NOT 5 V or 12 V tolerant.
- Companion: **NVIDIA Jetson AGX Orin Developer Kit (64 GB LPDDR5, 2048 CUDA cores / 16 SMs, 64 Tensor Cores, 275 TOPS, 204.8 GB/s memory bandwidth, JetPack 6 / L4T 36.5, aarch64)** running at **nvpmodel mode 3 (50 W)** headless + **Luxonis OAK-D Pro** over USB via DepthAI. The OAK-D Pro boots in USB 2.0 mode (Movidius MyriadX bootloader at vendor `03e7`); DepthAI uploads firmware and the device re-enumerates at USB 3.x SuperSpeed — this is normal XLink behavior. **Required setup:** (1) udev rules for non-root access (`80-oakd-usb.rules`, `MODE="0666"` for vendor `03e7`), (2) kernel params `usbcore.autosuspend=-1` and `usbcore.usbfs_memory_mb=1000` in `extlinux.conf`, (3) `depthai>=3.5.0` (v3 API — `Device()` takes no pipeline arg, `getMxId()` deprecated in favor of `getDeviceId()`). All managed by `jetson-harden.sh` and `pyproject.toml` `[jetson]` extras.
- Storage: **Samsung 990 EVO Plus 2 TB NVMe SSD** (PCIe Gen 4, ~5 GB/s sequential read) in the Orin Dev Kit M.2 Key M 2280 slot. Provides fast mmap cold starts for LLM models, ample space for RTAB-Map databases, structured logs, and model files.
- Operator workstation: **Windows laptop** (cross-platform tooling required).
- Safety: **physical E-stop has absolute authority** (cuts ignition + servo power via hardware relay). Software cannot override it. Spring-return-to-neutral on the levers is the mechanical half of the safety chain.

## Tooling stack (use these — do not substitute)

| Concern | Choice |
|---|---|
| Language | Python 3 |
| CLI framework | Typer |
| MAVLink | `pymavlink` (primary); `MAVSDK-Python` only if a higher-level helper is clearly needed |
| GNSS config | `pyubx2` for u-blox base; SBF tooling for the mosaic-H rover |
| Coverage planning | Shapely + pyproj (custom boustrophedon). **Do not** pull in Fields2Cover for MVP. |
| Human config | YAML |
| Machine artifacts | JSON (snapshots, run metadata, pre-flight reports) |
| Snapshots | Plain files, Git-tracked. No custom versioning DB. |
| Logging | `structlog` — JSON sink + human console, per-operation correlation IDs |
| Packaging | `uv` + `pyproject.toml`; install with `pipx` |
| Testing | `pytest` + ArduPilot SITL (`rover-skid` frame) via fixtures |
| Cross-side transport | SSH (laptop → Jetson), file pull for log archive |

## Conventions and constraints (must follow)

- **CLI surface** is `mower <subcommand>` on the laptop and `mower-jetson <subcommand>` on the Jetson. Both share one library package.
- **Every actuator-touching command** goes through the safety primitive: explicit confirmation prompt + `--dry-run` mode + central safe-stop hook. No exceptions.
- **RC is present for manual override and on-handset telemetry**, not as the primary control path. ArduPilot's RC stack is **enabled** (`RC_PROTOCOLS` set to the FrSky protocol in use, e.g. SBUS or FPort), an **RC failsafe is configured** so loss of the FrSky link triggers the same Hold-mode safe stop as a GCS failsafe, and a **FrSky telemetry serial port is configured** (`SERIALn_PROTOCOL=4` for FrSky D, `=10` for FrSky SPort, or `=23` for FPort, depending on the receiver). The autonomous mowing mission still runs from MAVLink/GCS; the FrSky transmitter is for the operator to (a) take manual control from any range the handset can reach and (b) read live status without needing the laptop. **The physical E-stop still has absolute authority over both RC and GCS.** Specific RC/failsafe parameter values are pending re-research — the prior `FS_THR_ENABLE=0` / `RC_PROTOCOLS=0` baseline is **superseded** by this hardware change and should not be treated as authoritative.
- **Default mower failsafe = Hold, not RTL.** RTL drives in a straight line through obstacles. Use `FENCE_ACTION=2`, `FS_EKF_ACTION=2`.
- **Per-side calibration is mandatory.** Left and right hydrostatic levers are not symmetric. `mower servo-cal` produces independent `SERVO1` and `SERVO3` profiles (TRIM, MIN, MAX, REVERSED, forward/reverse deadband).
- **GPS yaw, not magnetometer.** `EK3_SRC1_YAW=2`, `COMPASS_USE=0`. Do not propose magnetometer calibration utilities.
- **Snapshot + diff before apply.** Param/mission/calibration changes show a diff and require confirmation; restore must be lossless and round-trip-verifiable.
- **Structured output everywhere** (NFR-4): every operation logs inputs, robot responses, and outcome; pre-flight and snapshots emit JSON. CLI output must be readable on a sunlit laptop screen (high-contrast terminal-first).
- **Field-offline by default** (NFR-2, C-10): no internet dependency in any operational command path.
- **Cross-platform:** all laptop-side code must run on Windows; all Jetson-side code on aarch64 Linux. Path handling, line endings, and process spawning must be portable.

## SITL is a smoke-test harness, not a tuning tool

ArduPilot's `rover-skid` SITL is **purely kinematic** (hard-coded `max_speed=4`, `max_accel=14`, `skid_turn_rate=140`; no mass, friction, hydrostatics, or servo model). Use SITL to validate:

- MAVLink connection, retry, and message handling
- Param apply / snapshot / restore round-trips
- Mission upload / readback
- Mode transitions and failsafe trigger logic
- CLI dry-run paths and pre-flight check plumbing

**Never** propose tuning workflows, PID values, `CRUISE_*`, servo endpoints, or RTK behavior validated only in SITL. Mark field-required tests with `@pytest.mark.field` and SITL-validatable tests with `@pytest.mark.sitl`. Use `--instance=N` for port isolation under `pytest-xdist`.

On Windows, run SITL via **WSL2** (preferred) or Docker. Cygwin is deprecated.

## Working with the docs

- The vision is the contract for *what* and *why*. The research is the contract for *how* (with concrete parameter values, library choices, and confirmed hardware).
- Where vision and research disagree, **research wins** (notably: GNSS receiver, ignition relay, wheel encoders, and the corrections to `FS_THR_ENABLE` / `RC_PROTOCOLS` / `FS_OPTIONS`). **Exception:** the FrSky RC receiver addition (decided 2026-04-19, after the original research) supersedes the prior "no RC" guidance — RC parameters and the RC failsafe behavior need a follow-up research pass before the baseline is re-locked.
- Phases are dependency-ordered. Do not propose work that skips a dependency without calling it out.
- Open Questions in the research doc are **not** invitations to invent answers — flag them as needing field validation or operator input.

## Things to avoid

- Forking or modifying ArduPilot firmware (NG-2).
- Writing a custom VSLAM algorithm (NG-3).
- Building a general-purpose GCS (NG-4).
- Abstracting over other people's hardware (NG-5) — this tooling is for **this** specific stack only.
- Multi-user, cloud, fleet, or auth features (NG-7).
- Adding dependencies, abstractions, or "nice-to-have" features that aren't tied to a vision FR/NFR.
