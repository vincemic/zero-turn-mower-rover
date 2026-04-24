---
id: "007"
type: research
title: "Zero-Turn Mower Robotic Conversion — Release 3: VSLAM-Augmented Positioning"
status: ✅ Complete
created: "2026-04-23"
current_phase: "2 of 2"
vision_source: /docs/vision/001-zero-turn-mower-rover.md
target_release: 3
---

## Introduction

This research investigates how a Visual SLAM (VSLAM) stack running on the Jetson AGX Orin with an OAK-D Pro depth camera will integrate with ArduPilot Rover and the existing RTK GPS + dual-antenna heading system on the zero-turn mower rover. The mower's MVP (Release 1) operates with RTK-only positioning (Septentrio mosaic-H, GPS-derived yaw via `EK3_SRC1_YAW=2`). Release 3 adds a vision-based position source to improve robustness — particularly when RTK fix degrades (e.g., near trees, structures) or as a secondary EKF source for cross-validation. The research covers VSLAM stack selection, the ROS-or-not decision, how VSLAM pose estimates feed into ArduPilot's EKF3 via `VISION_POSITION_ESTIMATE` / `VISION_SPEED_ESTIMATE` MAVLink messages, transport options, EKF source configuration for fusing vision with RTK+GPS-yaw, and the degraded-RTK fallback strategy.

Prior research [006-oakd-pro-usb-slam-readiness.md](/docs/research/006-oakd-pro-usb-slam-readiness.md) confirmed OAK-D Pro USB connectivity, DepthAI SDK installation, stream configuration for SLAM workloads, and Linux USB tuning on JetPack 6 — that work is assumed as a foundation here.

**Hardware constraint:** The Jetson AGX Orin is the **only** companion computer for the Pixhawk Cube Orange. A direct serial (UART) connection between the Jetson and the Pixhawk must be established for MAVLink communication. This serial link carries all companion-computer MAVLink traffic, including the VSLAM bridge's `VISION_POSITION_ESTIMATE` / `VISION_SPEED_ESTIMATE` messages. The laptop connects to the Pixhawk separately via SiK radio (SERIAL1); the Jetson uses SERIAL2 (TELEM2).

> **⚠️ Superseded by Plan 008:** The SERIAL2/UART recommendation above (and the `SERIAL2_BAUD=921`, `SERIAL2_OPTIONS=1024`, `/dev/ttyTHS1` references throughout this document) has been replaced with a **USB connection (SERIAL0 / `/dev/ttyACM0`)** in [/docs/plans/008-vslam-ardupilot-integration.md](/docs/plans/008-vslam-ardupilot-integration.md). USB eliminates UART wiring, pin identification, and baud-rate configuration. SERIAL2 (TELEM2) remains free. All SERIAL2-specific parameters and device paths in this research doc should be read as historical context, not implementation guidance.

## Objectives

- Evaluate candidate VSLAM stacks that run on the Jetson AGX Orin and ingest OAK-D Pro stereo depth + IMU, ranking by maturity, resource fit, ArduPilot integration ease, and outdoor suitability
- Determine whether ROS 2 is required on the Jetson or if a ROS-free architecture is viable for the selected VSLAM stack
- Define the OAK-D Pro extrinsic calibration procedure (camera → robot body frame transform) needed to produce world-frame pose estimates
- Identify the optimal transport for feeding VSLAM poses into ArduPilot (direct UDP MAVLink from a Jetson process, mavros bridge, or ROS 2 → MAVLink bridge)
- Document the ArduPilot EKF3 source configuration for fusing vision position/velocity with RTK position and GPS-derived yaw, including `EK3_SRC` parameter values and any interaction with the existing `EK3_SRC1_YAW=2` / `COMPASS_USE=0` setup
- Define the degraded-RTK fallback strategy: how the system behaves when RTK fix is lost but VSLAM is healthy, and vice versa

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | VSLAM Stack Selection, ROS Decision & Extrinsic Calibration | ✅ Complete | Evaluate VSLAM candidates (RTAB-Map, ORB-SLAM3, Isaac Visual SLAM, Stella-VSLAM, etc.) against Jetson AGX Orin compute/memory budget and OAK-D Pro input; determine ROS 2 requirement; document camera-to-body extrinsic calibration approach | 2026-04-23 |
| 2 | VSLAM ↔ ArduPilot Bridge, EKF3 Fusion & Degraded-RTK Fallback | ✅ Complete | Transport options (direct pymavlink UDP, mavros, custom ROS 2 node); VISION_POSITION_ESTIMATE / VISION_SPEED_ESTIMATE message format and rate; EK3_SRC parameter configuration for dual-source (RTK + vision) fusion with GPS yaw; degraded-RTK and degraded-VSLAM fallback behavior; bridge health monitoring | 2026-04-23 |

## Phase 1: VSLAM Stack Selection, ROS Decision & Extrinsic Calibration

**Status:** ✅ Complete
**Session:** 2026-04-23

_Corresponds to vision Phase 12: VSLAM stack on Jetson_

### Scope

**VSLAM stack selection (high):**
- Candidate stacks: RTAB-Map, ORB-SLAM3, NVIDIA Isaac Visual SLAM (cuVSLAM), Stella-VSLAM (OpenVSLAM fork), any other viable options
- Evaluation criteria: runs on aarch64 / JetPack 6, ingests OAK-D Pro stereo depth + IMU via DepthAI, outdoor suitability (texture-poor grass, changing lighting, sun glare), CPU/GPU/memory footprint on AGX Orin (must coexist with TTS daemon from R2), pose output format and rate, maturity / maintenance status, licensing (Apache/MIT/BSD preferred), loop closure capability, relocalization after tracking loss
- Resource budget: AGX Orin has 12-core Arm Cortex-A78AE + 2048-core Ampere GPU + 64 GB unified memory; VSLAM should use ≤30% GPU and ≤8 GB memory to leave headroom
- Outdoor-specific challenges: grass is texture-poor (stereo depth helps), lighting changes across a 4-acre yard, sun glare, no fixed indoor features — how does each candidate handle these?

**ROS-or-not decision (high):**
- Project default is no-ROS unless the VSLAM stack requires it (vision doc architecture)
- For each candidate: does it require ROS 2? Can it run standalone?
- If ROS 2 is needed: what is the minimal ROS 2 footprint (base + perception packages only)?
- Impact on Jetson bringup tooling (`mower-jetson`), systemd service management, and overall complexity

**OAK-D Pro extrinsic calibration (medium):**
- Camera mounting position on the mower (forward-facing, height, tilt)
- Camera-to-body-frame transform (rotation + translation) needed by VSLAM and by ArduPilot's vision integration
- Calibration procedure: manual measurement vs. automated calibration tools
- How the transform is communicated to the VSLAM stack and/or to ArduPilot (`VISO_POS_X/Y/Z` parameters)

### VSLAM Stack Candidate Evaluation

Four candidates were evaluated against the project's criteria: aarch64/JetPack 6 compatibility, OAK-D Pro stereo depth + IMU ingestion via DepthAI, outdoor suitability, CPU/GPU/memory footprint on AGX Orin (≤30% GPU, ≤8 GB), pose output format and rate, maturity, licensing, loop closure, and relocalization.

#### 1. NVIDIA Isaac ROS Visual SLAM (cuVSLAM)

GPU-accelerated VSLAM using the proprietary cuVSLAM library, wrapped as a ROS 2 package. Best-in-class accuracy on KITTI benchmarks (0.94% translation error, 0.0019 deg/m rotation error). Supports stereo + IMU (SVIO), handles feature-poor scenes by falling back to IMU integration, and includes loop closure.

**Critical Platform Issue:** As of Isaac ROS 4.3.0 (March 2026), the supported platform table lists only **Jetson Thor (T5000/T4000) with JetPack 7.1**, x86_64 with Ampere+ GPU, and DGX Spark. The Jetson AGX Orin running JetPack 6 (L4T 36.x) is **no longer in the official test matrix**. Pinning to an older Isaac ROS 3.x release would work but means using stale packages with no forward support.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| ROS 2 required | **YES** — hard requirement | Core library (cuVSLAM) is closed-source; only accessible via ROS 2 node |
| JetPack 6 / AGX Orin | **⚠️ Not officially supported in 4.x** | Would need Isaac ROS 3.x (EOL) |
| GPU acceleration | **Excellent** | Full GPU pipeline for feature extraction, matching, optimization |
| License | Apache-2.0 (wrapper) | cuVSLAM library itself is proprietary/closed-source |
| Outdoor suitability | **Excellent** | IMU fallback, designed for ground robots and drones |
| Loop closure | **Yes** | Efficient statistical approach |
| OAK-D Pro input | Needs ROS 2 camera driver bridge | Not direct DepthAI ingestion |
| Maturity | High (1.3k stars, 6 contributors, NVIDIA-backed) | Active development |
| Memory footprint | ~2-4 GB GPU + ~1-2 GB host | Within budget |

**Verdict:** Eliminated due to (1) ROS 2 hard requirement violates project default, (2) AGX Orin / JetPack 6 no longer in official test matrix for current release, and (3) cuVSLAM core is closed-source. However, cuVSLAM can be used as an odometry strategy *within* RTAB-Map (see below).

#### 2. RTAB-Map (Real-Time Appearance-Based Mapping)

Mature, full-featured SLAM system supporting monocular, stereo, RGBD, and LiDAR input. Both a standalone C++ library (`librtabmap`) and a standalone GUI application (`rtabmap`), plus ROS 1/ROS 2 wrappers. BSD-3-Clause license. Actively maintained (3.7k stars, 914 forks, 62 contributors, commits within the past week). Latest release: v0.23.1 (October 2025).

**Key Architectural Feature — Standalone C++ API (no ROS required):** RTAB-Map's core is a C++ library that can be used programmatically. The `rtabmap::Rtabmap` class handles SLAM, and `rtabmap::OdometryF2F` / `rtabmap::OdometryF2M` classes handle visual odometry — all without ROS.

**Multiple Odometry Front-Ends:** RTAB-Map supports pluggable odometry strategies:
- Frame-to-Frame (F2F) — lightweight, visual odometry
- Frame-to-Map (F2M) — more robust, uses local map
- **CuVSLAM** — integrated as an odometry strategy via `cmake_modules/FindCuVSLAM.cmake`. If the cuVSLAM shared library is available on JetPack 6, RTAB-Map can use GPU-accelerated visual odometry without the full Isaac ROS stack.
- ORB-SLAM3 — can use ORB-SLAM3 as odometry source
- VINS-Fusion — visual-inertial odometry
- LIO-SAM — recently added as odometry strategy

**GPU Acceleration:** Uses OpenCV CUDA for feature extraction when available (JetPack 6 ships CUDA-accelerated OpenCV). The optional CuVSLAM integration adds full GPU VIO.

**Memory Management:** RTAB-Map's signature feature is its memory management — it transfers old data from Working Memory to Long-Term Memory and can bound RAM usage. Critical for long mowing sessions (a 4-acre boustrophedon pattern could run 30-60+ minutes).

| Criterion | Rating | Notes |
|-----------|--------|-------|
| ROS 2 required | **NO** — fully standalone | C++ library + app work without ROS |
| JetPack 6 / AGX Orin | **✅ Supported** | Builds on aarch64; available as ROS 2 binary or from source |
| GPU acceleration | **Good** | OpenCV CUDA + optional CuVSLAM odometry |
| License | **BSD-3-Clause** | Permissive — meets project requirement |
| Outdoor suitability | **Good** | Widely used outdoors; stereo depth helps with texture-poor areas |
| Loop closure | **Excellent** | RTAB-Map's core strength — bag-of-words appearance-based loop closure |
| OAK-D Pro input | **Direct** via DepthAI C++ or Python bridge | Standalone mode accepts stereo/depth frames programmatically |
| Maturity | **Very high** | 3.7k stars, 10+ years of development, academic and industry use |
| Memory footprint | ~2-6 GB (configurable) | Memory management bounds RAM; well within 8 GB budget |
| IMU integration | **Yes** | Supports IMU fusion in VIO modes |
| Relocalization | **Yes** | Can reload saved maps and relocalize |

**Verdict: Strong recommendation.** Only candidate meeting ALL criteria: standalone (no ROS), permissive license, GPU features, IMU support, outdoor-proven, aarch64-compatible, actively maintained, memory-bounded for long sessions.

#### 3. ORB-SLAM3

Academic VSLAM library supporting monocular, stereo, RGB-D, and visual-inertial modes. The most accurate open-source VSLAM in publications. Standalone C++ library with optional ROS wrapper.

**Critical Issues:**
1. **License: GPLv3** — copyleft license incompatible with project's stated preference for Apache/MIT/BSD
2. **Unmaintained:** Last commit December 2021 (4+ years ago, only 4 contributors). No responses to 538 open issues.
3. **No GPU acceleration:** CPU-only. On AGX Orin this wastes the available GPU.
4. **Build challenges on aarch64:** Not officially tested; community reports require patching for modern compilers.
5. **No DepthAI integration:** Would need custom camera adapter code.

**Verdict:** Eliminated due to GPLv3 license and abandonment. RTAB-Map can optionally use ORB-SLAM3 as an odometry strategy, but the GPL would taint the build.

#### 4. Stella-VSLAM (OpenVSLAM fork)

Community fork of OpenVSLAM after the original was taken down. Supports monocular, stereo, and RGBD. BSD-2-Clause license (versions ≥ 0.3). Moderately active (1.2k stars, 55 contributors, last commit 2 months ago).

**Critical Issue — No IMU Support:** The README's "Currently working on" list includes "IMU integration" — meaning IMU is **not yet implemented**. Without IMU fusion, the system relies purely on visual tracking, which will fail in feature-poor grass areas, fast zero-turn rotation, and temporary camera obscuration.

**Verdict:** Eliminated due to missing IMU integration (critical for outdoor robustness).

#### Candidate Comparison Summary

| Criterion | RTAB-Map | Isaac cuVSLAM | ORB-SLAM3 | Stella-VSLAM |
|-----------|----------|---------------|-----------|--------------|
| **Standalone (no ROS)** | ✅ | ❌ ROS 2 required | ✅ | ✅ |
| **JetPack 6 / AGX Orin** | ✅ | ⚠️ Not in 4.x matrix | ⚠️ Untested | ✅ |
| **License** | BSD-3 ✅ | Apache-2 (wrapper) | GPL-3 ❌ | BSD-2 ✅ |
| **GPU acceleration** | ✅ OpenCV CUDA + cuVSLAM | ✅ Full GPU | ❌ CPU only | ⚠️ Experimental |
| **IMU fusion** | ✅ | ✅ | ✅ | ❌ Not implemented |
| **Loop closure** | ✅ Excellent | ✅ Good | ✅ Good | ✅ |
| **Outdoor proven** | ✅ Widely | ✅ NVIDIA demos | ✅ Academic | ⚠️ Limited |
| **Memory management** | ✅ Built-in | ✅ Fixed map size | ❌ Unbounded | ⚠️ Basic |
| **OAK-D Pro input** | ✅ Programmatic | Needs ROS driver | Needs adapter | Needs adapter |
| **Active maintenance** | ✅ Weekly commits | ✅ NVIDIA-backed | ❌ Abandoned | ⚠️ Intermittent |
| **Stars / Community** | 3.7k / large | 1.3k / NVIDIA | 8.5k / dead | 1.2k / small |

### Recommendation: RTAB-Map (standalone, without ROS)

RTAB-Map is the clear winner on every dimension that matters:
1. **Standalone operation** — aligns with project's no-ROS default
2. **BSD-3 license** — permissive, meets project requirement
3. **Proven outdoor use** — widely deployed on ground robots
4. **Memory management** — critical for 30-60 minute mowing sessions
5. **GPU-enhanced** — can use OpenCV CUDA and optionally cuVSLAM for odometry
6. **Active and mature** — 10+ years of development, responsive maintainer
7. **Flexible architecture** — can switch odometry strategies without changing the SLAM back-end

### ROS-or-Not Decision

**Decision: No ROS required.**

RTAB-Map's standalone C++ library provides everything needed without ROS:

| Component | Without ROS | With ROS 2 |
|-----------|-------------|------------|
| SLAM engine | `librtabmap` C++ library | Same, via ROS wrapper |
| Camera input | DepthAI C++ API → RTAB-Map API | `depthai_ros_driver` → topics |
| Pose output | Direct C++ API call → Python bridge via IPC | ROS 2 `nav_msgs/Odometry` topic |
| MAVLink bridge | Python process reads poses, sends via pymavlink | mavros or custom node |
| Service management | systemd unit (existing pattern) | systemd + ROS 2 launch |
| Health monitoring | `mower-jetson vslam health` queries process stats | Same + ROS diagnostics |

**Architecture without ROS:**

```
┌────────────────────────────────────────────────┐
│  Jetson AGX Orin                               │
│                                                │
│  ┌──────────┐    ┌─────────────┐               │
│  │ OAK-D Pro│───►│ RTAB-Map    │               │
│  │ (DepthAI)│    │ standalone  │               │
│  │ stereo + │    │ C++ process │               │
│  │ IMU      │    │ (systemd)   │               │
│  └──────────┘    └──────┬──────┘               │
│                         │ SE3 pose @ 10-30 Hz  │
│                         │ (shared mem / socket) │
│                         ▼                      │
│                  ┌──────────────┐               │
│                  │ VSLAM Bridge │               │
│                  │ (Python/     │               │
│                  │  pymavlink)  │──► UDP MAVLink│
│                  │ (systemd)    │    to ArduPilot│
│                  └──────────────┘               │
└────────────────────────────────────────────────┘
```

**Why avoid ROS 2:**
1. **Complexity**: ROS 2 on JetPack 6 requires specific Humble/Jazzy packages; adds ~1-2 GB of dependencies
2. **Bringup tooling**: Would need to extend `mower-jetson` bringup to handle ROS 2 workspace, colcon builds, environment setup
3. **Service management**: ROS 2 nodes require launch files + daemon supervisor; conflicts with existing systemd-centric approach
4. **Field debugging**: ROS 2 adds DDS middleware, topic introspection tools, logging layers — all extra failure surfaces in a field-offline environment
5. **Resource overhead**: DDS discovery, parameter server, logging — additional CPU/memory for no functional benefit

**Minimal ROS 2 fallback if ever needed:** `ros-humble-ros-base` + `ros-humble-rtabmap-ros` + `ros-humble-depthai-ros-driver` (~800 MB installed). Can be revisited post-R3 if needed.

### OAK-D Pro Extrinsic Calibration

#### Camera Mounting on the Mower

The OAK-D Pro should be mounted **forward-facing** on the mower body:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Height** | 0.5–0.8 m above ground | Low enough to see ground texture; high enough for obstacle horizon |
| **Tilt** | 10–15° downward from horizontal | Captures ground features (grass, dirt boundaries) while seeing ahead |
| **Position** | Center-front of mower body | Minimizes lever arm to center of rotation; symmetric FOV |
| **Orientation** | Lens facing forward, USB port up or to the side | Aligns with standard camera conventions |

**Vibration isolation:** The Z254 mower deck generates significant vibration. Use thick double-sided VHB tape or a vibration-dampening mount (rubber grommets, silicone pads) between the camera bracket and the mower frame. IMU data in RTAB-Map helps compensate for vibration-induced motion blur, but mechanical isolation is the first defense.

#### Camera-to-Body Frame Transform

The transform from camera optical frame to the vehicle body frame (centered at the Pixhawk IMU) is needed in two places:

1. **RTAB-Map pipeline** — to convert camera-frame poses to body-frame poses
2. **ArduPilot** — `VISO_POS_X/Y/Z` parameters describe the camera offset from the autopilot

**Coordinate Frames:**

| Frame | Convention | Origin |
|-------|-----------|--------|
| ArduPilot body (NED) | X=forward, Y=right, Z=down | Pixhawk IMU |
| Camera optical (ROS/OpenCV) | X=right, Y=down, Z=forward | Camera lens center |
| RTAB-Map base_frame | Configurable; typically X=forward, Y=left, Z=up | Vehicle center |

**Example for forward-facing camera with 15° downward tilt, mounted 30 cm forward, centered, 20 cm above the Pixhawk:**

```yaml
# In mower config YAML:
vslam:
  extrinsics:
    # Camera position relative to Pixhawk in body frame (NED)
    pos_x: 0.30   # 30 cm forward of Pixhawk
    pos_y: 0.00   # centered (no lateral offset)
    pos_z: -0.20  # 20 cm above Pixhawk (negative = up in NED)
    # Camera orientation relative to body frame
    roll: 0.0
    pitch: -15.0   # 15° downward tilt
    yaw: 0.0
```

**ArduPilot VISO parameters:**

| Parameter | Value | Description |
|-----------|-------|-------------|
| `VISO_POS_X` | 0.30 | Forward offset from Pixhawk (meters) |
| `VISO_POS_Y` | 0.00 | Right offset from Pixhawk (meters) |
| `VISO_POS_Z` | -0.20 | Down offset from Pixhawk (meters, negative = above) |
| `VISO_ORIENT` | 0 | Camera orientation: 0 = forward |

#### Calibration Procedure

**Phase A: Physical Measurement (field procedure)**
1. Mark the Pixhawk IMU location on the mower frame
2. Mount the OAK-D Pro in the chosen position with vibration isolation
3. Measure the offset from Pixhawk to camera lens center using a tape measure (forward/back, left/right, up/down)
4. Measure camera tilt angle with a digital inclinometer or smartphone level app
5. Record measurements in the VSLAM config YAML

**Phase B: OAK-D Pro Intrinsic Calibration**

The OAK-D Pro ships factory-calibrated (stereo rectification + intrinsics stored on-device EEPROM). DepthAI reads these automatically:

```python
import depthai as dai

with dai.Device() as device:
    calibData = device.readCalibration()
    intrinsics_left = calibData.getCameraIntrinsics(dai.CameraBoardSocket.CAM_B)
    intrinsics_right = calibData.getCameraIntrinsics(dai.CameraBoardSocket.CAM_C)
    baseline = calibData.getBaselineDistance(
        dai.CameraBoardSocket.CAM_B, dai.CameraBoardSocket.CAM_C
    )
```

Factory calibration is sufficient for SLAM; re-calibration only needed if the camera housing is physically damaged.

**Phase C: Validation (field validation)**
1. Place the mower on flat ground with RTK fix
2. Start RTAB-Map and the MAVLink bridge
3. Drive a known pattern (e.g., 10 m straight line, 90° turn, return)
4. Compare VSLAM trajectory to RTK GPS trajectory
5. If systematic offset exists, adjust the extrinsic translation values
6. If heading drift exists, verify camera tilt angle and orientation

This validation procedure is a field exercise (not SITL-validatable) and should be marked `@pytest.mark.field`.

#### Integration with Existing Probe System

The existing `oakd.py` probe check verifies OAK-D presence and USB speed. For R3, this should be extended with VSLAM-readiness checks:

- Factory calibration readable from EEPROM
- Stereo depth stream achievable at target resolution/FPS
- IMU stream available at 200+ Hz
- Extrinsic config file present and parseable

### Key Discoveries

- **RTAB-Map is the recommended VSLAM stack** — standalone (no ROS), BSD-3 license, GPU-enhanced, outdoor-proven, active maintenance, memory-managed for long sessions, flexible odometry strategies (including optional cuVSLAM GPU acceleration)
- **ROS 2 is NOT required** — RTAB-Map standalone C++ library provides full SLAM capability without ROS middleware
- **Isaac ROS Visual SLAM (cuVSLAM) 4.x has dropped AGX Orin / JetPack 6 from its supported platform matrix** (now requires Jetson Thor / JetPack 7.1) — eliminates it as standalone primary choice, but cuVSLAM can potentially be used as an odometry strategy within RTAB-Map
- **ORB-SLAM3 eliminated** — GPLv3 license and 4+ years without maintenance
- **Stella-VSLAM eliminated** — missing IMU integration (critical for outdoor robustness on texture-poor grass)
- **OAK-D Pro extrinsic calibration** is a manual-measurement + field-validation procedure; ArduPilot's `VISO_POS_X/Y/Z` and `VISO_ORIENT` parameters carry the camera offset
- **Factory stereo calibration from OAK-D Pro EEPROM is sufficient** — no custom stereo calibration needed
- **RTAB-Map standalone architecture** (C++ SLAM process → IPC → Python pymavlink bridge) aligns with the project's existing systemd service pattern
- **RTAB-Map memory management** (Working Memory → Long-Term Memory transfer) is critical for 30-60 minute mowing sessions

| File | Relevance |
|------|-----------|
| `src/mower_rover/probe/checks/oakd.py` | Existing OAK-D presence/speed check; will need R3 extension for VSLAM readiness |
| `scripts/jetson-harden.sh` | Sets nvpmodel to mode 3 (50W) for OAK-D + SLAM workloads; holds XUSB firmware |
| `docs/research/006-oakd-pro-usb-slam-readiness.md` | Prior research confirming USB topology, DepthAI install, stream config for SLAM |
| `src/mower_rover/service/daemon.py` | Existing systemd daemon pattern that RTAB-Map service will follow |
| `src/mower_rover/service/unit.py` | Systemd unit file generation; RTAB-Map process will use this pattern |

**External Sources:**
- [RTAB-Map core library](https://github.com/introlab/rtabmap) — BSD-3, 3.7k stars, standalone + ROS
- [RTAB-Map wiki — standalone C++ tutorials](https://github.com/introlab/rtabmap/wiki)
- [Isaac ROS Visual SLAM](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam) — cuVSLAM, Apache-2.0, ROS 2 required
- [Isaac ROS Visual SLAM docs — JetPack 7.1/Thor requirement](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/index.html)
- [cuVSLAM architecture and coordinate frames](https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/index.html)
- [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) — GPLv3, 8.5k stars, unmaintained since Dec 2021
- [Stella-VSLAM](https://github.com/stella-cv/stella_vslam) — BSD-2, 1.2k stars, no IMU support
- [ArduPilot VIO setup (T265)](https://ardupilot.org/copter/docs/common-vio-tracking-camera.html) — EKF3 + VISO params
- [ArduPilot OAK-D VIO setup](https://ardupilot.org/copter/docs/common-vio-oak-d.html) — VINS-Fusion based, VISO_TYPE and EK3_SRC params
- [ArduPilot ROS VIO setup](https://ardupilot.org/dev/docs/ros-vio-tracking-camera.html) — VISION_POSITION_ESTIMATE flow

**Gaps:**
- cuVSLAM shared library availability on JetPack 6 without Isaac ROS: unclear whether the `.so` can be extracted/installed standalone for RTAB-Map's cuVSLAM odometry strategy on AGX Orin. RTAB-Map's own F2M odometry with OpenCV CUDA is the reliable fallback.
- RTAB-Map standalone C++ process to Python bridge IPC mechanism: the exact IPC pattern (shared memory, Unix socket, named pipe, or lightweight ZMQ) for passing SE3 poses from C++ to Python needs to be decided during planning.
- RTAB-Map version compatibility with JetPack 6's system OpenCV: need to verify that RTAB-Map 0.23.x builds against the OpenCV 4.x + CUDA shipped with JetPack 6.

**Assumptions:**
- RTAB-Map 0.23.x builds successfully on aarch64 / JetPack 6 with CMake, as it supports Linux/aarch64 and lower-spec ARM platforms
- OAK-D Pro factory stereo calibration is sufficiently accurate for SLAM (standard assumption for Luxonis cameras)
- RTAB-Map standalone C++ process can achieve 10-30 Hz pose output on AGX Orin with stereo depth + IMU at 400P/30fps

## Phase 2: VSLAM ↔ ArduPilot Bridge, EKF3 Fusion & Degraded-RTK Fallback

**Status:** ✅ Complete
**Session:** 2026-04-23

_Corresponds to vision Phase 13: VSLAM ↔ ArduPilot bridge_

### Scope

**VSLAM ↔ MAVLink transport (high):**
- Option A: Direct pymavlink UDP — a Python process on the Jetson consumes VSLAM poses and sends `VISION_POSITION_ESTIMATE` / `VISION_SPEED_ESTIMATE` over UDP to ArduPilot's companion computer MAVLink port
- Option B: mavros — ROS 2 mavros node bridges VSLAM topic to MAVLink automatically
- Option C: Custom ROS 2 → MAVLink bridge node (if VSLAM uses ROS but mavros is too heavy)
- Evaluation: latency, reliability, complexity, dependency footprint, alignment with ROS-or-not decision from Phase 1
- MAVLink message details: `VISION_POSITION_ESTIMATE` fields (usec, x, y, z, roll, pitch, yaw, covariance), `VISION_SPEED_ESTIMATE` fields, coordinate frame (NED vs. ENU conversion), required message rate (typ. 10–30 Hz)

**EKF3 vision source configuration (medium):**
- Current EKF config: `EK3_SRC1_YAW=2` (GPS yaw), `COMPASS_USE=0` (no magnetometer)
- Adding vision as a position/velocity source: `EK3_SRC1_POSXY`, `EK3_SRC1_VELXY`, `EK3_SRC1_POSZ`, `EK3_SRC1_VELZ` options for vision vs. GPS
- Multi-source EKF: can EKF3 use GPS for primary position AND vision as a secondary/fallback? Or does ArduPilot's `EK3_SRC_OPTIONS` / lane switching handle this?
- EKF lane switching: `EK3_SRC2_*` as a second source set, with automatic or manual switching between RTK-primary and vision-primary lanes
- Interaction with GPS yaw: does adding vision position affect `EK3_SRC1_YAW=2`? Can vision provide yaw as well?
- Key parameters: `VISO_TYPE`, `VISO_POS_X/Y/Z`, `VISO_ORIENT`, `EK3_SRC*` family, `EK3_SRC_OPTIONS`
- Required pose quality / covariance values for EKF acceptance

**Degraded-RTK fallback strategy:**
- Scenario 1: RTK fix degrades to float or single — VSLAM becomes primary position source
- Scenario 2: VSLAM tracking lost (e.g., camera obscured, featureless area) — RTK remains sole source
- Scenario 3: Both degrade simultaneously — trigger Hold (project convention: Hold, not RTL)
- How ArduPilot EKF3 lane switching enables automatic fallback
- `mower vslam bridge-health` reporting: what metrics indicate healthy fusion?
- Pre-flight check additions for VSLAM readiness (extending FR-9)

**Bridge health monitoring:**
- Metrics: pose rate, pose age, covariance magnitude, EKF innovation, EKF lane in use
- Surface in `mower vslam bridge-health` CLI command
- Integration with live monitoring (R2 Phase 10) and pre-flight (R1 Phase 9)

### VSLAM ↔ MAVLink Transport

#### Transport Option Evaluation

Given Phase 1's decision (RTAB-Map standalone, no ROS), only **Option A (Direct pymavlink serial)** is viable:

| Option | Description | Verdict |
|--------|-------------|---------|
| **A: Direct pymavlink** | Python bridge on Jetson reads RTAB-Map poses via IPC, sends `VISION_POSITION_ESTIMATE` via pymavlink over serial to Cube Orange | **✅ Recommended** |
| B: mavros | ROS 2 mavros node bridges VSLAM topics to MAVLink | ❌ Requires ROS 2 (eliminated Phase 1) |
| C: Custom ROS 2 → MAVLink node | Custom ROS 2 node for MAVLink bridge | ❌ Requires ROS 2 (eliminated Phase 1) |

Option A has the lowest dependency footprint (only `pymavlink`, already in `pyproject.toml`), aligns with the existing MAVLink connection pattern in `connection.py`, and fits the systemd service management pattern.

#### Physical Transport Path

The Jetson AGX Orin connects to the Cube Orange via a **direct serial/UART link** on `SERIAL2` (TELEM2 port), configured as MAVLink2 at 921600 baud. This is a **separate physical link** from the laptop's SiK Radio B:

```
┌──────────────────┐                    ┌──────────────────┐
│  Jetson AGX Orin │                    │  Cube Orange     │
│                  │   UART/USB-serial  │                  │
│  VSLAM Bridge    │──────────────────► │  SERIAL2 (TELEM2)│
│  (pymavlink)     │   921600 baud      │  MAVLink2        │
└──────────────────┘                    └──────────────────┘
                                        │
┌──────────────────┐   SiK Radio B     │
│  Laptop          │◄─────────────────►│  SERIAL1 (TELEM1)│
│  (mower CLI)     │   57600 baud      │  MAVLink2        │
└──────────────────┘                    └──────────────────┘
```

**ArduPilot serial port configuration for companion computer:**

| Parameter | Value | Description |
|-----------|-------|-------------|
| `SERIAL2_PROTOCOL` | 2 | MAVLink2 |
| `SERIAL2_BAUD` | 921 | 921600 baud (high rate for 10-30 Hz vision data) |
| `SERIAL2_OPTIONS` | 1024 | (Optional) Don't forward MAVLink to/from — prevents VSLAM data flooding GCS link |

#### MAVLink Message Details

**`VISION_POSITION_ESTIMATE` (msg #102):**

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `usec` | uint64_t | µs | Timestamp (UNIX epoch or boot time) |
| `x` | float | m | X position in NED frame (North) |
| `y` | float | m | Y position in NED frame (East) |
| `z` | float | m | Z position in NED frame (Down) |
| `roll` | float | rad | Roll angle |
| `pitch` | float | rad | Pitch angle |
| `yaw` | float | rad | Yaw angle |
| `covariance` | float[21] | | Row-major upper triangle of 6×6 pose cross-covariance |
| `reset_counter` | uint8_t | | Increment on SLAM relocalization/loop closure |

**`VISION_SPEED_ESTIMATE` (msg #103):**

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `usec` | uint64_t | µs | Timestamp |
| `x` | float | m/s | Velocity X (NED, North) |
| `y` | float | m/s | Velocity Y (NED, East) |
| `z` | float | m/s | Velocity Z (NED, Down) |
| `covariance` | float[9] | | Row-major 3×3 velocity cross-covariance |
| `reset_counter` | uint8_t | | Increment on SLAM relocalization |

**Coordinate Frame Conversion (Critical):**

RTAB-Map default output uses FLU (Forward-Left-Up). ArduPilot expects NED:

```
FLU → NED conversion:
  x_ned =  x_flu     (forward → north relative to body)
  y_ned = -y_flu     (right = -left)
  z_ned = -z_flu     (down = -up)
  roll_ned  =  roll_flu
  pitch_ned = -pitch_flu
  yaw_ned   = -yaw_flu
```

RTAB-Map's `base_frame_id` parameter can be configured to output FRD directly, which would eliminate bridge-side conversion (planner decision).

**Required Message Rate:** 15–20 Hz is sufficient for a ground rover at ≤2 m/s mowing speed. Reduces serial bandwidth vs. the 30 Hz used in drone applications.

#### Bridge pymavlink Code Pattern

Follows the existing codebase pattern from `connection.py`:

```python
from pymavlink import mavutil
import time

# Connect to ArduPilot's companion computer port
conn = mavutil.mavlink_connection(
    '/dev/ttyTHS1',           # Jetson UART to Cube Orange SERIAL2
    baud=921600,
    source_system=1,          # Same system as autopilot
    source_component=197,     # MAV_COMP_ID_VISUAL_INERTIAL_ODOMETRY
)
conn.wait_heartbeat(timeout=10)

def send_vision_pose(x, y, z, roll, pitch, yaw, covariance, reset_count):
    conn.mav.vision_position_estimate_send(
        usec=int(time.time() * 1e6),
        x=x, y=y, z=z,
        roll=roll, pitch=pitch, yaw=yaw,
        covariance=covariance,    # 21-element list or [0]*21
        reset_counter=reset_count,
    )

def send_vision_velocity(vx, vy, vz, covariance, reset_count):
    conn.mav.vision_speed_estimate_send(
        usec=int(time.time() * 1e6),
        x=vx, y=vy, z=vz,
        covariance=covariance,    # 9-element list or [0]*9
        reset_counter=reset_count,
    )
```

**Design notes:**
- `source_component=197` (`MAV_COMP_ID_VISUAL_INERTIAL_ODOMETRY`) — standard for companion computer VIO
- Bridge must also send periodic heartbeats (`MAV_TYPE_ONBOARD_CONTROLLER`) to keep the connection alive
- `reset_counter` must be incremented on RTAB-Map loop closure / relocalization so the EKF handles discontinuities
- Covariance should be populated from RTAB-Map's uncertainty output; if not available, use zeros (ArduPilot uses `VISO_DELAY_MS` defaults)

### EKF3 Vision Source Configuration

#### Current Baseline (Release 1, RTK-Only)

From `z254_baseline.yaml`:

```yaml
EK3_SRC1_POSXY: 1   # GPS
EK3_SRC1_VELXY: 1   # GPS
EK3_SRC1_POSZ:  1   # Baro
EK3_SRC1_VELZ:  1   # GPS
EK3_SRC1_YAW:   2   # GPS dual-antenna yaw
COMPASS_USE:    0    # No magnetometer
```

#### Release 3 Dual-Source Configuration (RTK + Vision)

ArduPilot EKF3 supports three source sets (`EK3_SRC1_*`, `EK3_SRC2_*`, `EK3_SRC3_*`) switchable at runtime. **Source Set 1 = RTK (primary), Source Set 2 = VSLAM (fallback):**

```yaml
# --- Source Set 1: RTK Primary (normal operation) ---
EK3_SRC1_POSXY: 1   # GPS (RTK)
EK3_SRC1_VELXY: 1   # GPS
EK3_SRC1_POSZ:  1   # Baro
EK3_SRC1_VELZ:  1   # GPS
EK3_SRC1_YAW:   2   # GPS dual-antenna yaw

# --- Source Set 2: VSLAM Fallback (degraded RTK) ---
EK3_SRC2_POSXY: 6   # ExternalNav (VSLAM)
EK3_SRC2_VELXY: 6   # ExternalNav (VSLAM)
EK3_SRC2_POSZ:  1   # Baro (safer — VSLAM Z is less reliable outdoors)
EK3_SRC2_VELZ:  6   # ExternalNav (VSLAM)
EK3_SRC2_YAW:   2   # GPS dual-antenna yaw (KEEP — see below)

# --- Visual Odometry Config ---
VISO_TYPE:      1    # MAVLink (receives VISION_POSITION_ESTIMATE)
VISO_DELAY_MS:  50   # Compensate for VSLAM processing latency (ms)
VISO_POS_X:     0.30 # Camera offset forward from Pixhawk (m) — field measured
VISO_POS_Y:     0.00 # Camera offset right (m)
VISO_POS_Z:    -0.20 # Camera offset down (m, negative=above)
VISO_ORIENT:    0    # Camera facing forward

# --- Source Options ---
EK3_SRC_OPTIONS: 0   # Do NOT fuse all velocities (keep sources independent)

# --- Companion Computer Serial Port ---
SERIAL2_PROTOCOL: 2  # MAVLink2
SERIAL2_BAUD:   921  # 921600 baud

# --- Lua Scripting ---
SCR_ENABLE:     1    # Enable Lua scripts
SCR_USER2:      0.3  # GPS speed accuracy threshold
SCR_USER3:      0.3  # ExternalNav innovation threshold
```

#### GPS Yaw Independence (Critical Advantage)

**The dual-antenna GPS yaw (`EK3_SRC1_YAW=2`) is independent of the position source.** This is a major advantage of this hardware stack:

- GPS yaw comes from phase difference between two antennas — works even with degraded position fix (float or single)
- Both Source Set 1 and Source Set 2 keep `YAW=2`, so heading always comes from GPS dual-antenna
- VSLAM does NOT need to provide yaw to ArduPilot — the bridge sends position/velocity only
- Eliminates the complexity of fusing VSLAM yaw with compass yaw (which other setups require)
- Only exception: if GPS signals are completely blocked (e.g., inside a barn) — not a scenario for outdoor mowing

#### EKF3 Uses One Source Set at a Time (Not Simultaneous)

**EKF3 uses one source set at a time, not both simultaneously.** The switching mechanism:

1. Only one source set is active at any moment (`EK3_SRC1_*` or `EK3_SRC2_*` or `EK3_SRC3_*`)
2. Switching triggered by RC switch (`RCx_OPTION=90`), MAVLink command (`MAV_CMD_SET_EKF_SOURCE_SET`), or Lua script
3. `EK3_SRC_OPTIONS` bit 0 (`FuseAllVelocities`) can merge velocity from multiple sources — **not recommended** for GPS+vision (different reference frames risk)
4. `EK3_AFFINITY` / lane switching is about **IMU core selection**, not position source switching

**Key property:** When Source Set 1 (GPS) is active, VISION_POSITION_ESTIMATE data is still received and cached — the ExternalNav position is **continuously updated to match the GPS position**. This means GPS→VSLAM switching is **seamless** (no position jump), while VSLAM→GPS switching may cause a jump if they've drifted.

#### Source Switching Mechanism

| Mechanism | How | Pros | Cons |
|-----------|-----|------|------|
| **RC switch** | `RCx_OPTION=90` (3-pos: low=SRC1, mid=SRC2, high=SRC3) | Instant pilot override | Manual only |
| **MAVLink command** | `MAV_CMD_SET_EKF_SOURCE_SET` from Jetson bridge | Bridge can automate | Depends on bridge alive |
| **Lua script** | Runs on Pixhawk at 10 Hz, uses GPS accuracy + EKF innovations | Runs in autopilot (no external dependency), proven approach | Requires Lua scripting support |

**Recommendation: Lua script (primary) + RC switch (manual override)**

ArduPilot's `ahrs-source.lua` reference script provides a production-tested template. Key logic:

```lua
-- GPS accuracy check
local gps_speed_accuracy = gps:speed_accuracy(gps:primary_sensor())
local gps_over_threshold = (gps_speed_accuracy == nil) or
    (gps_speed_accuracy > gps_speedaccuracy_thresh)

-- ExternalNav (VSLAM) innovation check
local extnav_innov = ahrs:get_vel_innovations_and_variances_for_source(6)
local extnav_over_threshold = (extnav_innov == nil) or
    (extnav_innov:z() == 0.0) or
    (math.abs(extnav_innov:z()) > extnav_innov_thresh)

-- Vote-based switching (2-second stabilization window)
if gps_over_threshold and not extnav_over_threshold then
    -- Vote for VSLAM (Source Set 2)
elseif not gps_over_threshold then
    -- Vote for GPS (Source Set 1)
end

ahrs:set_posvelyaw_source_set(auto_source)
```

A simplified 2-source variant (GPS vs VSLAM only, no optical flow) is needed for this project. The Lua script goes on the Pixhawk SD card at `/APM/scripts/ahrs-source-gps-vslam.lua`.

**Switching parameters:**

| Parameter | Value | Description |
|-----------|-------|-------------|
| `SCR_USER2` | 0.3 | GPS speed accuracy threshold (m/s) |
| `SCR_USER3` | 0.3 | ExternalNav velocity innovation threshold |
| `RCx_OPTION` | 90 | EKF Source Set switch (manual override on FrSky transmitter) |
| `RCx_OPTION` | 300 | Scripting1 — enable/disable automatic switching |
| `SCR_ENABLE` | 1 | Enable Lua scripting |

### Degraded-RTK Fallback Strategy

#### Scenario Matrix

| # | Condition | GPS Yaw | Position Source | Action | Mechanism |
|---|-----------|---------|-----------------|--------|-----------|
| 1 | RTK fix → float/single, VSLAM healthy | ✅ Available | Switch to VSLAM (SRC2) | Lua script detects GPS accuracy degradation, switches to SRC2 | Automatic |
| 2 | VSLAM tracking lost, RTK healthy | ✅ Available | Stay on GPS (SRC1) | Lua script detects ExternalNav innovation spike, stays on SRC1 | Automatic |
| 3 | RTK degraded AND VSLAM lost | ⚠️ May degrade | EKF failure → Hold | `FS_EKF_ACTION=2` triggers Hold; bridge triggers safe-stop | Automatic + failsafe |
| 4 | Both healthy | ✅ Available | GPS primary (SRC1) | Normal; VSLAM data cached for seamless handoff | Normal |
| 5 | GPS completely blocked (barn entry) | ❌ No yaw | VSLAM (SRC2) with `YAW=6` | Out of scope for outdoor mowing | Manual |

**Scenario 1 — RTK Degrades → VSLAM Primary:**
1. Lua script vote counter accumulates votes for VSLAM (over ~2 seconds)
2. When threshold reached, script calls `ahrs:set_posvelyaw_source_set(1)` → Source Set 2
3. GPS dual-antenna yaw remains active (SRC2_YAW=2)
4. Mission continues with VSLAM-derived position
5. When RTK recovers, script votes back to Source Set 1

GPS→VSLAM switching is **seamless** because ArduPilot continuously aligns ExternalNav with GPS when GPS is primary.

**Scenario 2 — VSLAM Lost → GPS Remains:**
1. If on SRC1 (GPS): no action needed — VSLAM data simply not used
2. If on SRC2 (VSLAM): Lua script detects ExternalNav degradation, votes to switch back to SRC1
3. Risk: position jump on VSLAM→GPS switch (drift accumulated); vote-based 2-second stabilization mitigates

**Scenario 3 — Both Degrade → Hold:**
1. ArduPilot's built-in `FS_EKF_ACTION=2` → triggers Hold mode (project convention)
2. Lua script cannot find a usable source — no switching occurs
3. Bridge health monitor triggers safe-stop via central safe-stop hook
4. Operator notification via FrSky telemetry (mode change on handset)
5. Existing failsafe config (`FS_EKF_ACTION=2`, `FS_ACTION=2`, `FENCE_ACTION=2`) handles this — no new failsafe needed

### Bridge Health Monitoring

#### Health Metrics

| Metric | Source | Healthy | Warning | Critical |
|--------|--------|---------|---------|----------|
| VSLAM pose rate | Bridge counter | 10-30 Hz | <10 Hz | <5 Hz or 0 |
| VSLAM pose age | `now - last_pose_ts` | <100 ms | >200 ms | >500 ms |
| VSLAM confidence | RTAB-Map tracking | High/Medium | Low | Lost |
| Covariance magnitude | Frobenius norm of 6×6 | <1.0 | >2.0 | >5.0 |
| EKF active source | `XKFS` dataflash / MAVLink | 0 (SRC1) or 1 (SRC2) | — | — |
| EKF ExternalNav innovation | `ahrs:get_vel_innovations...` | <0.3 | >0.3 | >1.0 |
| GPS fix type | `GPS_RAW_INT.fix_type` | 6 (RTK Fixed) | 5 (Float) | ≤3 |
| GPS speed accuracy | `gps:speed_accuracy()` | <0.3 m/s | >0.3 | >1.0 |
| Bridge msg rate | VISION_POSITION_ESTIMATE/sec | 15-20 Hz | <10 Hz | 0 Hz |
| Bridge connection | ArduPilot heartbeat | Present | >5s stale | Lost |

#### `mower vslam bridge-health` CLI Command

High-contrast terminal output per NFR-4:

```
VSLAM Bridge Health — 2026-04-23T14:32:01Z
────────────────────────────────────────────
  VSLAM Pose Rate:       18.2 Hz          ✓
  VSLAM Pose Age:        54 ms            ✓
  VSLAM Confidence:      HIGH             ✓
  Covariance Norm:       0.42             ✓
  EKF Active Source:     SRC1 (GPS)       ✓
  EKF ExtNav Innovation: 0.12            ✓
  GPS Fix Type:          RTK Fixed (6)    ✓
  GPS Speed Accuracy:    0.08 m/s         ✓
  Bridge Msg Rate:       18.2 Hz          ✓
  Bridge Connection:     OK               ✓
────────────────────────────────────────────
  Overall Status: HEALTHY
```

Bridge exposes metrics via Unix domain socket or shared memory file on the Jetson.

#### Pre-Flight Check Extensions (FR-9)

New VSLAM-readiness checks using the existing probe registry pattern:

| Check | Severity | Depends On | Validates |
|-------|----------|------------|-----------|
| `vslam_process` | CRITICAL | `oakd` | RTAB-Map systemd service active and producing poses |
| `vslam_bridge` | CRITICAL | `vslam_process` | Bridge service active, MAVLink connection established |
| `vslam_pose_rate` | CRITICAL | `vslam_bridge` | Pose rate ≥ 5 Hz (minimum usable) |
| `vslam_params` | WARNING | — | `VISO_TYPE=1`, `EK3_SRC2_*` configured, `SCR_ENABLE=1` |
| `vslam_lua_script` | WARNING | — | `ahrs-source-gps-vslam.lua` present on Pixhawk SD card |
| `vslam_confidence` | WARNING | `vslam_process` | RTAB-Map reporting Medium or High confidence |

### Key Discoveries

- **Direct pymavlink serial bridge is the only transport option** consistent with the Phase 1 no-ROS architecture. Aligns with existing `connection.py` and `mav.py` patterns.
- **EKF3 uses one source set at a time, NOT simultaneous fusion.** GPS (SRC1) and VSLAM (SRC2) are mutually exclusive; switching via Lua script, RC switch, or MAVLink command.
- **GPS dual-antenna yaw is independent of position source.** Both source sets keep `YAW=2` — heading always from GPS. VSLAM does not need to provide yaw.
- **ExternalNav position is continuously aligned to GPS when GPS is primary.** GPS→VSLAM switching is seamless (no position jump). VSLAM→GPS switching may cause a jump.
- **ArduPilot's `ahrs-source.lua` provides a production-tested template** for automatic source switching using vote-based GPS accuracy + ExternalNav innovations. A simplified 2-source variant is needed.
- **Lua script runs in the autopilot at 10 Hz** — no dependency on Jetson/bridge being alive for source switching. Critical safety property.
- **`VISO_TYPE=1` (MAVLink) is the correct visual odometry type.** Type 2 (IntelT265) has T265-specific handling.
- **Coordinate frame conversion FLU→NED required** in the bridge unless RTAB-Map configured to output FRD.
- **`reset_counter` must be incremented on RTAB-Map loop closure / relocalization** so EKF handles pose discontinuities.
- **Existing failsafe config (`FS_EKF_ACTION=2`) already handles dual-degrade** (both GPS and VSLAM lost) → Hold. No new failsafe needed.
- **Pre-flight checks for VSLAM fit the existing probe registry pattern** via `@register()` with dependency chain.
- **SERIAL2 at 921600 baud needed** for 15-20 Hz VISION_POSITION_ESTIMATE messages.

| File | Relevance |
|------|-----------|
| `src/mower_rover/mavlink/connection.py` | Existing MAVLink connection pattern; bridge follows this |
| `src/mower_rover/params/mav.py` | Param fetch/apply via MAVLink; bridge health may query EKF params |
| `src/mower_rover/params/data/z254_baseline.yaml` | R1 baseline params; R3 adds EK3_SRC2_*, VISO_*, SCR_* |
| `src/mower_rover/probe/registry.py` | Probe check registry with dependency ordering; new VSLAM checks use this |
| `src/mower_rover/probe/checks/oakd.py` | Existing OAK-D USB check; R3 extends with VSLAM readiness |
| `src/mower_rover/service/daemon.py` | Existing systemd daemon pattern; RTAB-Map and bridge follow this |
| `src/mower_rover/service/unit.py` | Systemd unit generation; new units for RTAB-Map + bridge |
| `src/mower_rover/health/thermal.py` | Health snapshot pattern; bridge health monitoring follows this style |

**External Sources:**
- [ArduPilot VIO setup (T265)](https://ardupilot.org/copter/docs/common-vio-tracking-camera.html) — VISO_TYPE, EK3_SRC, VISION_POSITION_ESTIMATE flow
- [ArduPilot OAK-D VIO setup](https://ardupilot.org/copter/docs/common-vio-oak-d.html) — VISO_TYPE=1, VISO_DELAY_MS=50, EKF3 source config for ExternalNav
- [ArduPilot EKF3 Source Selection](https://ardupilot.org/copter/docs/common-ekf-sources.html) — SRC1/SRC2/SRC3, switching via RC/MAVLink/Lua
- [ArduPilot GPS/Non-GPS Transitions](https://ardupilot.org/copter/docs/common-non-gps-to-gps.html) — dual-source setup, Lua scripts for switching
- [ArduPilot EKF3 Affinity](https://ardupilot.org/copter/docs/common-ek3-affinity-lane-switching.html) — lane switching is IMU-level, not source-level
- [ahrs-source.lua reference script](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/libraries/AP_Scripting/examples/ahrs-source.lua) — GPS + ExternalNav vote-based switching

**Gaps:**
- Lua scripting on Cube Orange Rover firmware: `ahrs-source.lua` is documented primarily for Copter. Need to verify `SCR_ENABLE`, `ahrs:set_posvelyaw_source_set()`, and `ahrs:get_vel_innovations_and_variances_for_source()` are available in Rover. Likely yes (shared scripting engine) but needs field verification.
- SERIAL2 physical connection: exact UART device name on AGX Orin for Cube Orange connection is hardware-dependent (`/dev/ttyTHS0`, `/dev/ttyTHS1`, or USB-serial adapter). Needs field measurement.
- Covariance mapping: exact mapping of RTAB-Map pose uncertainty to the 21-element upper-triangular covariance in VISION_POSITION_ESTIMATE needs verification against RTAB-Map API.
- Time synchronization: `usec` field should use same time base as ArduPilot. `VISO_DELAY_MS` compensates for latency, but NTP on the Jetson may be needed for accuracy.

**Assumptions:**
- ArduPilot Rover firmware on Cube Orange supports Lua scripting and the `ahrs:set_posvelyaw_source_set()` API (Rover shares scripting engine with Copter, and EKF3 source switching docs reference Rover explicitly)
- GPS dual-antenna yaw continues providing reliable heading even when position degrades to float (yaw requires only carrier phase between two close antennas, more robust than absolute position)
- 921600 baud achievable on SERIAL2 UART between Jetson and Cube Orange (standard for companion computer links)
- RTAB-Map can provide covariance alongside poses; if unavailable, zeros acceptable (ArduPilot uses `VISO_DELAY_MS` defaults)

## Overview

Release 3 adds VSLAM-augmented positioning to the RTK-only MVP using the OAK-D Pro depth camera on the Jetson AGX Orin. After evaluating four candidate VSLAM stacks and researching ArduPilot EKF3 integration patterns, the architecture is clear and well-supported by existing tooling and documentation.

**RTAB-Map** is the recommended VSLAM stack — it is the only candidate that meets all criteria simultaneously: standalone C++ operation (no ROS 2 dependency), permissive BSD-3 license, GPU acceleration via OpenCV CUDA and optional cuVSLAM odometry, proven outdoor use on ground robots, built-in memory management for long mowing sessions, active 10+ year maintenance, and IMU fusion for robustness on texture-poor grass terrain. Isaac ROS cuVSLAM was eliminated because its current release dropped AGX Orin/JetPack 6 support; ORB-SLAM3 was eliminated for GPLv3 licensing and abandonment; Stella-VSLAM was eliminated for lacking IMU integration.

The **no-ROS architecture** holds: RTAB-Map runs as a standalone C++ systemd process, feeding SE3 poses at 15-20 Hz via IPC to a Python pymavlink bridge process. The bridge sends `VISION_POSITION_ESTIMATE` and `VISION_SPEED_ESTIMATE` MAVLink messages over a direct UART link (SERIAL2 at 921600 baud) to the Cube Orange — completely separate from the laptop's SiK MAVLink link. This aligns with the project's existing systemd service management, MAVLink connection patterns, and avoids introducing ROS 2 complexity.

ArduPilot EKF3 **does not fuse GPS and vision simultaneously** — it uses one source set at a time. The recommended configuration uses Source Set 1 (GPS/RTK) as primary and Source Set 2 (ExternalNav/VSLAM) as fallback. A Lua script adapted from ArduPilot's `ahrs-source.lua` runs at 10 Hz on the Pixhawk itself (no Jetson dependency) and automatically switches between sources based on GPS accuracy and ExternalNav innovation metrics, with a vote-based 2-second stabilization window. An RC switch provides manual override. A critical advantage of this hardware stack is that **GPS dual-antenna yaw is independent of the position source** — heading is always available from the mosaic-H even when position degrades.

The degraded-RTK fallback strategy leverages existing failsafe configuration (`FS_EKF_ACTION=2` → Hold) and requires no new failsafe mechanisms. GPS→VSLAM switching is seamless because ArduPilot continuously aligns ExternalNav position with GPS when GPS is primary.

## Key Findings

1. **RTAB-Map is the recommended VSLAM stack** — standalone, BSD-3, GPU-enhanced, outdoor-proven, memory-managed, actively maintained. No other candidate meets all criteria.
2. **ROS 2 is not required** — RTAB-Map's C++ library provides full SLAM without ROS middleware, avoiding ~1-2 GB of dependencies and DDS complexity.
3. **Direct pymavlink serial bridge** from Jetson to Cube Orange SERIAL2 at 921600 baud is the simplest and only transport option consistent with the no-ROS architecture.
4. **EKF3 dual-source configuration** uses SRC1 (GPS) as primary and SRC2 (ExternalNav) as fallback, with Lua-based automatic switching at 10 Hz in the autopilot.
5. **GPS dual-antenna yaw is position-source-independent** — both source sets keep `YAW=2`, eliminating VSLAM yaw fusion complexity.
6. **GPS→VSLAM switching is seamless** (ExternalNav continuously aligned to GPS); VSLAM→GPS may cause a position jump.
7. **Existing failsafe config handles dual-degrade** — `FS_EKF_ACTION=2` (Hold) covers the scenario where both GPS and VSLAM are lost.
8. **OAK-D Pro factory calibration is sufficient** — no custom stereo calibration needed. Extrinsic calibration is manual measurement + field validation.
9. **RTAB-Map memory management** (Working Memory → Long-Term Memory) is critical for bounding RAM during 30-60 minute mowing sessions.
10. **Pre-flight VSLAM checks** fit the existing probe registry pattern with dependency chain: `oakd` → `vslam_process` → `vslam_bridge` → `vslam_pose_rate`.

## Actionable Conclusions

- **VSLAM stack: use RTAB-Map standalone C++ library** — build from source on JetPack 6, using Frame-to-Map (F2M) odometry with OpenCV CUDA acceleration as the default strategy
- **Bridge: implement as a Python pymavlink systemd service** on the Jetson, consuming RTAB-Map poses via IPC and sending `VISION_POSITION_ESTIMATE` at 15-20 Hz over SERIAL2
- **EKF3 params: add `EK3_SRC2_*` (ExternalNav), `VISO_TYPE=1`, `VISO_DELAY_MS=50`, `SCR_ENABLE=1`** to the R3 baseline delta; keep `VISO_POS_X/Y/Z` as field-measured values
- **Lua script: adapt `ahrs-source.lua` to a 2-source GPS/VSLAM variant** (`ahrs-source-gps-vslam.lua`), deploy to Pixhawk SD card; assign RC switch for manual override
- **Coordinate frame: configure RTAB-Map to output FRD or implement FLU→NED conversion** in the bridge (planner decision)
- **IPC mechanism: decide during planning** — shared memory, Unix socket, or ZMQ for C++ → Python pose transfer
- **Pre-flight: extend probe registry** with `vslam_process`, `vslam_bridge`, `vslam_pose_rate`, `vslam_params`, `vslam_lua_script`, `vslam_confidence` checks

## Open Questions

- Can the cuVSLAM shared library be installed standalone on JetPack 6 for RTAB-Map's GPU odometry strategy, without the full Isaac ROS stack?
- Does ArduPilot Rover firmware on Cube Orange support all Lua scripting APIs used in `ahrs-source.lua` (specifically `ahrs:set_posvelyaw_source_set()` and `ahrs:get_vel_innovations_and_variances_for_source()`)?
- What is the exact UART device name on AGX Orin for the Cube Orange SERIAL2 connection?
- What IPC mechanism (shared memory, Unix socket, ZMQ) provides the best latency/reliability trade-off for the RTAB-Map C++ → Python bridge?
- Does RTAB-Map 0.23.x build cleanly against JetPack 6's system OpenCV 4.x + CUDA?
- What covariance values should the bridge populate in `VISION_POSITION_ESTIMATE` — can RTAB-Map's uncertainty output be mapped directly to the 21-element format?

## Standards Applied

| Standard | Relevance | Guidance |
|----------|-----------|----------|
| No organizational standards applicable to this research. | — | — |

## References

### Phase 1 Sources
- [RTAB-Map core library](https://github.com/introlab/rtabmap) — BSD-3, 3.7k stars, standalone + ROS
- [RTAB-Map wiki — standalone C++ tutorials](https://github.com/introlab/rtabmap/wiki)
- [Isaac ROS Visual SLAM](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam) — cuVSLAM, Apache-2.0, ROS 2 required
- [Isaac ROS Visual SLAM docs — platform support](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/index.html)
- [cuVSLAM architecture and coordinate frames](https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/index.html)
- [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) — GPLv3, 8.5k stars, unmaintained since Dec 2021
- [Stella-VSLAM](https://github.com/stella-cv/stella_vslam) — BSD-2, 1.2k stars, no IMU support
- [ArduPilot VIO setup (T265)](https://ardupilot.org/copter/docs/common-vio-tracking-camera.html) — EKF3 + VISO params
- [ArduPilot OAK-D VIO setup](https://ardupilot.org/copter/docs/common-vio-oak-d.html) — VINS-Fusion based, VISO_TYPE and EK3_SRC params
- [ArduPilot ROS VIO setup](https://ardupilot.org/dev/docs/ros-vio-tracking-camera.html) — VISION_POSITION_ESTIMATE flow

### Phase 2 Sources
- [ArduPilot EKF3 Source Selection and Switching](https://ardupilot.org/copter/docs/common-ekf-sources.html) — SRC1/SRC2/SRC3, switching via RC/MAVLink/Lua
- [ArduPilot GPS/Non-GPS Transitions](https://ardupilot.org/copter/docs/common-non-gps-to-gps.html) — dual-source setup, Lua scripts
- [ArduPilot EKF3 Affinity / Lane Switching](https://ardupilot.org/copter/docs/common-ek3-affinity-lane-switching.html) — IMU-level lane switching
- [ahrs-source.lua reference script](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/libraries/AP_Scripting/examples/ahrs-source.lua) — GPS + ExternalNav vote-based switching

## Follow-Up Research

### From Phase 1
- Verify RTAB-Map 0.23.x builds against JetPack 6's system OpenCV 4.x + CUDA
- Investigate cuVSLAM shared library standalone availability on JetPack 6 (for RTAB-Map GPU odometry strategy)
- Determine optimal IPC mechanism for C++ RTAB-Map → Python pymavlink bridge (shared memory, Unix socket, or ZMQ)
- Field validation of RTAB-Map on grass/outdoor terrain with OAK-D Pro (mark `@pytest.mark.field`)

### From Phase 2
- Field verification of Lua scripting on Cube Orange Rover firmware (`SCR_ENABLE=1`, `ahrs:set_posvelyaw_source_set()`)
- Determine SERIAL2 UART device name on AGX Orin for Cube Orange connection (hardware-dependent)
- Verify RTAB-Map covariance output mapping to 21-element `VISION_POSITION_ESTIMATE` covariance field
- Investigate time synchronization between Jetson and Pixhawk for `usec` timestamp accuracy
- Design bridge systemd unit dependency chain: OAK-D USB → RTAB-Map → Bridge → MAVLink
- Develop Lua script deployment workflow (MAVLink FTP or part of param apply)

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-23 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/007-vslam-ardupilot-rtk-integration.md |
