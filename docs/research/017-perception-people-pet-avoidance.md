---
id: "017"
type: research
title: "Perception-Based Obstacle Avoidance — People & Pet Avoidance First"
status: ✅ Complete
created: "2026-05-02"
current_phase: "✅ Complete"
---

## Introduction

Investigates how to add perception-based obstacle avoidance to the rover, building on the existing OAK-D Pro + Jetson AGX Orin + RTAB-Map VSLAM stack (research 007–009) and the MAVLink bridge to ArduPilot Rover (research 008). The first deliverable is a **people and pet avoidance** safety layer: any time a person or pet enters a configurable danger envelope around the mower, the blade clutch (`SERVO7`) disengages and the rover transitions to Hold — independent of mission state and of the operator's RC inputs.

Subsequent phases extend the same perception pipeline into static obstacle avoidance via ArduPilot's built-in object-avoidance planner (Bendy Ruler / Dijkstra), driven by `OBSTACLE_DISTANCE` messages synthesized from OAK-D stereo depth. Tall-grass false positives, negative obstacles (drop-offs), and the back-driveable hydrostatic stop-distance problem are explicitly called out as field-validation concerns; this research will not propose tuning workflows that can only be validated in SITL.

## Objectives

- Determine the **minimum viable detector** (model, framerate, classes) that runs on the OAK-D Pro Myriad X without taxing the Orin's VSLAM workload.
- Define the **danger envelope** geometry (distance, lateral half-width, time-to-contact) for people vs. pets, and how it composes with mower speed and stop distance.
- Specify the **safety integration** — how a detection event reaches the blade clutch and the ArduPilot mode controller without violating the "physical E-stop has absolute authority" rule (NG: do not bypass the E-stop chain) and without forking ArduPilot (NG-2).
- Decide the **MAVLink message shape** for both the people/pet stop signal (Phase 1) and the per-sector obstacle distances (Phase 4) — `OBSTACLE_DISTANCE`, `OBSTACLE_DISTANCE_3D`, custom `STATUSTEXT`, or a dedicated companion-side service.
- Identify which detection/avoidance behaviors can be validated in SITL (mode transitions, MAVLink plumbing, blade-disengage interlock) and which **must** be field-validated (stop distance, grass-height filter thresholds, detector recall on real targets).
- Catalogue the **failure modes specific to a mower** (tall grass, dappled sunlight, water sprinkler, low/thin obstacles like hoses and cables) and document which are addressable with the current sensor stack vs. which need geofencing or operator procedure.

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | People & Pet Detection on OAK-D | ✅ Complete | Detector model selection (MobileNet-SSD vs. YOLO-Nano on Myriad X); class set (person, dog, cat — confirm COCO mapping); achievable FPS at 800p alongside VSLAM; latency budget end-to-end (frame → MAVLink); confidence thresholds and hysteresis to suppress flicker; behavior in dappled sun / backlight | 2026-05-02 |
| 2 | Danger Envelope & Stop-Distance Model | ✅ Complete | Envelope geometry (range, lateral half-width, vertical band); composition with current ground speed and a conservative hydrostatic stop-distance estimate; pet-vs-person thresholds; interaction with the planned mowing speed envelope from research 014; what's tunable via YAML vs. baked in | 2026-05-02 |
| 3 | Safety Chain & Blade Interlock | ✅ Complete | Where the stop decision lives (Jetson companion vs. Pixhawk Lua vs. ArduPilot param-driven failsafe); how it triggers blade disengage on `SERVO7` ahead of the Hold transition; ordering relative to E-stop, RC SF arm, and EKF/fence failsafes; round-trip latency budget; behavior on detector loss (heartbeat, watchdog) | 2026-05-02 |
| 4 | ArduPilot OA Integration for Static Obstacles | ✅ Complete | `OBSTACLE_DISTANCE` vs. `OBSTACLE_DISTANCE_3D` shape and rate; `OA_TYPE`, `PRX_*`, `AVOID_*` parameter set for Rover skid-steer; Bendy Ruler vs. Dijkstra trade-off on a 4-acre yard with pre-planned zones (research 014); how OA composes with mission re-planning vs. simple Hold; param-snapshot impact | 2026-05-02 |
| 5 | Mower-Specific False Positive & Negative-Obstacle Handling | ✅ Complete | Tall-grass filter using VSLAM ground plane / IMU-projected ground; mulch/leaf returns; sprinkler water and rain on lens; low/thin obstacles (hose, extension cord, sprinkler head); negative obstacles (drop-offs, retaining walls, pond) and why stereo can't see them — geofence backstop strategy from research 014 zones | 2026-05-02 |
| 6 | CLI Surface, Logging, Validation Plan | ✅ Complete | New `mower` / `mower-jetson` subcommands (e.g., `mower perception status`, `mower perception sim-detection` for dry-run); structured log schema for detection events (per-event correlation ID per NFR-4); SITL-validatable test list (`@pytest.mark.sitl`) vs. field-required tests (`@pytest.mark.field`); operator pre-flight check addition; dataset / labeled-clip strategy given NG-7 (no cloud / fleet) | 2026-05-02 |

## Phase 1: People & Pet Detection on OAK-D

**Status:** ✅ Complete
**Session:** 2026-05-02

### 1. Detector Model Options on Myriad X (RVC2)

#### RVC2 Hardware Context

The OAK-D Pro's Myriad X (RVC2) provides:
- **4 TOPS total** (1.4 TOPS dedicated to AI / NN inference)
- **2 NCEs** (Neural Compute Engines) — dedicated HW for supported NN layers
- **16 SHAVEs** — vector processors for layers NCEs don't handle, plus ISP
- **20 CMX slices** (128 KB each) — fast SRAM for intermediate computation
- **Dedicated HW stereo engine** — stereo depth does NOT consume SHAVEs
- **HW warp engines** for stereo rectification — also not SHAVEs

#### Benchmarked Models (Luxonis official, 8 SHAVEs, USB 3.x)

| Model | Input | FPS | Latency (ms) | COCO mAP | Notes |
|-------|-------|-----|--------------|----------|-------|
| **YOLOv6n R2** | 416×416 | **65.5** | 29.3 | ~35.0 | Best FPS/accuracy ratio for safety |
| YOLOv6n R2 | 640×640 | 29.3 | 66.4 | ~37.5 | Higher accuracy, slower |
| YOLOv8n | 416×416 | 31.3 | 56.9 | ~37.3 | Better mAP but half the FPS |
| YOLOv8n | 640×640 | 14.3 | 123.6 | ~37.3 | Too slow for safety-critical |
| YOLO11n | 416×416 | 28.1 | 35.6 | ~39.5 | Newest, comparable to YOLOv8n |
| YOLOv10n | 416×416 | 27.1 | 37.0 | ~38.5 | NMS-free; end-to-end slightly faster |

**MobileNet-SSD v2 (300×300):** Classic DepthAI model-zoo model. ~40–50 FPS at 6 SHAVEs. Lower mAP (~22). 20 COCO classes including person, cat, dog. Available via `blobconverter`.

**person-detection-retail-0013 (OpenVINO):** Person-only, 320×544, ~25–30 FPS. No pet classes.

**SCRFD Person Detection (Luxonis Model Zoo):** Person-only, ~30 FPS. No dog/cat.

#### COCO Class Mapping (Confirmed)

| Target | COCO ID | Model Output Index | Approx mAP |
|--------|---------|---------------------|------------|
| **person** | 1 | **0** | ~52 |
| **cat** | 17 | **15** | ~35 |
| **dog** | 18 | **16** | ~38 |

Filter accepts indices `{0, 15, 16}`; all other classes discarded host-side.

#### Recommended Primary Model: **YOLOv6n @ 416×416**

2× FPS headroom over YOLOv8n leaves room for concurrent stereo. Marginal mAP loss is irrelevant when the safety strategy biases toward recall.

---

### 2. Concurrent Load: NN + VSLAM Stereo Pipeline

#### Resource Budget with 800p @ 30 FPS Stereo Active

| Resource | Used By | Consumption |
|----------|---------|-------------|
| HW Stereo Engine | StereoDepth | 0 SHAVEs (HW-dedicated) |
| Warp Engines | Rectification | 0 SHAVEs (HW-dedicated) |
| ISP | CAM_B + CAM_C | ~3 SHAVEs |
| IMU | BNO086 @ 200 Hz | 0 SHAVEs (Leon CSS) |
| USB Transfer | depth + L + R + IMU | ~180 of ~350 MB/s practical |
| **Available for NN** | — | **~13 SHAVEs** |

DepthAI's own resource warning confirms: `"Network compiled for 8 shaves, maximum available 13"` when stereo + ISP are running.

**Practical FPS with 6 SHAVEs allocated to NN (conservative):** ~40–50 FPS for YOLOv6n@416. Worst case at 4 SHAVEs: ~30 FPS.

#### CRITICAL ARCHITECTURAL CONSTRAINT — One Pipeline per Device

DepthAI supports **one pipeline per device**. The existing C++ SLAM node (`mower-vslam.service`) holds exclusive OAK-D access. Three options:

| Approach | Complexity | Latency | Recommendation |
|----------|-----------|---------|----------------|
| **A) Extend C++ SLAM node** with NeuralNetwork + SpatialDetectionNetwork nodes | Medium (C++ changes) | Lowest (~30 ms) | ✅ Viable |
| **B) Jetson GPU inference** — SLAM node IPC-shares frames to Python detection service | Low–Medium | Low (~35 ms) | ✅ Best alternative — much simpler, more capable |
| **C) Replace SLAM node** with Python unified pipeline | Very High | Medium | ❌ Not viable |

**Approach B detail:** Jetson Orin's 275 TOPS runs YOLOv8n FP16 at >100 FPS via TensorRT, with no Myriad X contention. Frames already on host; an IPC channel (shared memory or Unix socket) to a Python service is straightforward.

#### DepthAI v3 SpatialDetectionNetwork

```cpp
auto sdn = pipeline.create<dai::node::SpatialDetectionNetwork>();
sdn->build(camRgb, stereo, modelDescription, fps);
sdn->setConfidenceThreshold(0.4f);
sdn->setDepthLowerThreshold(300);    // 0.3 m
sdn->setDepthUpperThreshold(10000);  // 10 m
```

Outputs `SpatialImgDetections` with bbox + XYZ in camera frame (RDF).

---

### 3. Latency Budget

**On-Device (Approach A, Myriad X):**

| Stage | Latency |
|-------|---------|
| Frame capture (sensor→ISP) | 1–2 ms |
| ISP + resize (800p→416) | 3–5 ms |
| NN inference (YOLOv6n@416, 6 SHAVEs) | 25–35 ms |
| Spatial calc (depth lookup) | 2–3 ms |
| XLink USB to host | 1–3 ms |
| Host parse + decision | 1–2 ms |
| MAVLink serial to Pixhawk (115200) | 5–10 ms |
| **Total** | **~38–60 ms** |

**Jetson GPU (Approach B):**

| Stage | Latency |
|-------|---------|
| Frame already on host (from SLAM) | ~0 ms |
| IPC to detection service | 1–2 ms |
| GPU inference (YOLOv8n FP16, TensorRT) | 3–5 ms |
| Post-processing + decision | 1–2 ms |
| MAVLink serial | 5–10 ms |
| **Total** | **~10–20 ms** |

**Worst case at 30 FPS** (one frame interval = 33 ms wait):
- On-device: ~78 ms
- Jetson GPU: ~48 ms

Both well under 200 ms — the rough threshold for a 1.5 m/s mower to cover 30 cm.

---

### 4. Confidence Thresholds & Hysteresis

| Context | Threshold | Rationale |
|---------|-----------|-----------|
| **Person** (safety) | **0.35** | Bias toward recall |
| **Dog/cat** (safety) | **0.30** | Smaller targets → lower model confidence |
| All classes (diagnostics) | 0.50 | Standard |

`SpatialDetectionNetwork.setConfidenceThreshold()` is global; per-class thresholds applied host-side.

**Asymmetric N-of-M consensus — fast stop, slow resume:**

| Transition | Strategy | Latency Impact |
|------------|----------|----------------|
| Clear → STOP | 2-of-3 frames (or 1-of-1 for person) | 0–66 ms at 30 FPS |
| STOP → Resume | **10 consecutive clear frames** | 333 ms at 30 FPS |

**Recommended YAML defaults (configurable):**

```yaml
perception:
  detection:
    model: yolov6-nano
    input_size: [416, 416]
    shaves: 6
    confidence_person: 0.35
    confidence_pet: 0.30
    stop_trigger_frames: 2
    clear_frames_required: 10
    detection_fps: 15  # NN can run slower than stereo
```

NN at 10–15 FPS is sufficient for safety and halves SHAVE contention vs. matching the 30 FPS stereo rate.

---

### 5. Outdoor / Mower-Specific Concerns

| Concern | Severity | Status | Mitigation |
|---------|----------|--------|------------|
| Dappled sunlight | Medium | Known DepthAI depth issue | NN runs on intensity/color — tolerant; use median spatial calc |
| Backlight (person vs sky) | Medium | Known CV challenge | Silhouette detection works; mount sun-hood |
| Motion blur @ 1.5 m/s | Low | Known/calculable | 50 mm/frame; sub-pixel at >2 m |
| IR projector contamination | Low | Known | Color cam has IR-cut filter; no impact on NN |
| Rain/water on lens | High | Known failure mode | Hardware only — lens hood + hydrophobic coating; "detector degraded" watchdog |
| Tall grass / vegetation | Low (for NN) | Phase 5 concern | NN on COCO doesn't false-positive on grass |
| Small/distant targets | Medium | Known model limitation | Drives min detection range |
| IR flood in daylight | None | Known | Sunlight overwhelms 200 mA flood |
| Engine vibration | Low–Med | Mitigated | VHB tape / rubber grommets per sensor docs |

#### Detection Range vs. Target Pixel Size (416×416 input, 73° HFOV)

| Target | Height | 3 m | 5 m | 8 m | 10 m |
|--------|--------|-----|-----|-----|------|
| Adult standing | 1.7 m | ~180 px | ~110 px | ~68 px | ~55 px |
| Child standing | 1.0 m | ~106 px | ~64 px | ~40 px | ~32 px |
| Large dog | 0.6 m | ~64 px | ~38 px | ~24 px | ~19 px |
| Cat | 0.3 m | ~32 px | ~19 px | ~12 px | ~10 px |

COCO "small object" threshold = 32×32 px; recall drops sharply below.

**Practical reliable detection range:**
- Adult: **3–10 m**
- Child: **3–7 m**
- Large dog: **2–5 m**
- Cat: **2–3 m** (marginal)

A mower at 1.5 m/s with 1–2 s reaction covers 1.5–3 m → envelope needs ≥4–5 m detection. Achievable for people/dogs, marginal for cats.

#### IR Projector / NN Interaction

If dots OFF (recommended for VSLAM feature quality per research 006): zero interaction. If ON: IR-cut filter on color cam blocks them. **No NN/IR concern either way.**

---

### Key Discoveries

- **YOLOv6n@416×416** is optimal: 65.5 FPS standalone, ~40–50 FPS with concurrent stereo, 29 ms inference — 2× faster than YOLOv8n with marginal mAP loss
- **Stereo engine is HW-dedicated** (0 SHAVEs); ~13 SHAVEs remain for NN alongside 800p@30 FPS VSLAM
- **DepthAI `SpatialDetectionNetwork`** integrates detection + 3D depth in one on-device node
- **One pipeline per device constraint** forces an architectural choice: extend C++ SLAM node (Approach A) or run on Jetson GPU (Approach B)
- **Latency budget** is 40–60 ms on-device or 10–20 ms on Jetson GPU — both well under the 200 ms safety threshold
- **COCO indices** for filter: person=0, cat=15, dog=16
- **Detection range** is pixel-size limited: people 3–10 m, dogs 2–5 m, cats 2–3 m at 416×416
- **Asymmetric hysteresis** (fast stop, slow resume) is the right pattern: 2-of-3 stop, 10-consecutive-clear resume
- **Outdoor concerns are manageable**; rain on lens is the only high-severity issue and requires hardware mitigation
- **NN at 10–15 FPS** is sufficient for safety and reduces SHAVE contention
- **Jetson GPU path (Approach B)** is arguably better — 275 TOPS vs Myriad X 1.4 TOPS, simpler, doesn't modify proven SLAM node

### Files Analyzed

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | Existing C++ SLAM pipeline owns OAK-D; modification target for Approach A |
| `src/mower_rover/config/data/vslam_defaults.yaml` | Current VSLAM config; detection config would be added here |
| `docs/research/006-oakd-pro-usb-slam-readiness.md` | Prior SHAVE budget, USB headroom, stereo HW independence |
| `docs/research/008-jetson-mavlink-vision-integration-deploy.md` | VSLAM 3-process architecture; detection adds 4th process |
| `src/mower_rover/probe/checks/oakd.py` | OAK-D probe; needs extension for detection-node health |
| `docs/field/001-sensor-location-measurements.md` | Camera mount (0.5–0.8 m, 15° down) — affects detection FoV geometry |

### External Sources

- [Luxonis RVC2 Hardware](https://docs.luxonis.com/hardware/platform/rvc/rvc2/) — NN benchmarks, SHAVE/NCE/CMX architecture
- [DepthAI v3 Inference](https://docs.luxonis.com/software-v3/ai-inference/inference/) — pipeline API, ParsingNeuralNetwork
- [SpatialDetectionNetwork Node](https://docs.luxonis.com/software-v3/depthai/depthai-components/nodes/spatial_detection_network/) — 3D detection with depth fusion
- [NeuralNetwork Node](https://docs.luxonis.com/software-v3/depthai/depthai-components/nodes/neural_network/) — SHAVE/NCE config
- [Luxonis Model Zoo](https://models.luxonis.com/) — YOLOv6 Nano, SCRFD, etc.

### Gaps

- Exact FPS of YOLOv6n at 6 SHAVEs with concurrent stereo not empirically measured — needs field test
- Cat/dog mAP at small target sizes (32–64 px) not published separately — must field-test recall
- Thermal throttling of Myriad X under sustained NN+stereo+IR load in 30–40 °C ambient not documented
- Whether `SpatialDetectionNetwork` can share an existing `StereoDepth` node already used by SLAM, or requires its own — needs API testing

### Assumptions

- 6-SHAVE NN delivers ~75–80% of 8-SHAVE benchmark FPS (sub-linear scaling per Luxonis)
- Color camera (CAM_A) is unused in current pipeline — confirmed by reading SLAM node source (only CAM_B/CAM_C used)
- MAVLink serial latency 5–10 ms at 115200 baud for ~50-byte safety messages (research 008 timings)
- COCO weights only — no fine-tuning on outdoor/mowing imagery

## Phase 2: Danger Envelope & Stop-Distance Model

**Status:** ✅ Complete
**Session:** 2026-05-02

### 1. Hydrostatic Stop-Distance Model

#### 1.1 Stop Mechanism in Hold Mode

ArduPilot Hold sets `SERVO1`/`SERVO3` to their `SERVOx_TRIM` (1500 µs neutral). Sequence:

1. ArduPilot transitions to Hold (~1 ms)
2. Servo PWM updates to TRIM (~1–5 ms at 50 Hz)
3. ASMC-04A back-driveable servos drive levers to neutral (~50–100 ms)
4. EZT pump displacement → 0
5. Mower **coasts** on hydraulic internal drag + rolling resistance
6. ⚠️ **NO mechanical friction brake exists** on the Z254 with Hydro-Gear EZT transaxles

#### 1.2 Conservative Stop-Distance Estimates

> **All values are engineering estimates and MUST be field-calibrated before autonomous operation.**

Estimated effective deceleration on level ground: **0.4–1.0 m/s²**. Use **0.4 m/s² (worst case)** for safety calculations.

| Speed | Stopping Time | Stop Distance (conservative) |
|-------|--------------|------------------------------|
| 0.8 m/s (NW turn) | 2.0 s | **0.8 m** |
| 1.0 m/s (NE turn) | 2.5 s | **1.25 m** |
| 1.4 m/s (WP_SPEED) | 3.5 s | **2.45 m** |
| 1.5 m/s (NW mow) | 3.75 s | **2.8 m** |
| 2.0 m/s (NE mow / CRUISE) | 5.0 s | **5.0 m** |
| 2.5 m/s (South mow) | 6.25 s | **7.8 m** |

Formula: `d = v² / (2 × 0.4)`. Field-measured deceleration is likely 0.6–0.8 m/s² → real distances ~30–50% shorter, but use conservative until calibrated.

#### 1.3 Slope Impact

On grade θ, gravitational accel component = `g × sin(θ)`:

- 5° (~8.7%): +0.85 m/s² — exceeds hydraulic drag → mower may creep downhill at neutral
- 10° (~17.6%): +1.7 m/s² — **mower accelerates downhill** at neutral

**Mitigation on slopes:** reduced speed (NW already 1.5 m/s), envelope ≥2× larger, **E-stop is the only true brake** (kills ignition). Field calibration on actual NW slope is **mandatory**.

#### 1.4 Active Deceleration Note

ArduPilot's `ATC_DECEL_MAX=5` provides active deceleration **only inside autonomous modes** (e.g., Auto approaching waypoint), via reverse pump displacement. **Hold mode bypasses this** — it sets servos directly to TRIM. A pre-Hold speed override (Phase 3 architectural choice) could improve effective stopping. Phase 2 assumes worst case: instantaneous Hold + passive coast.

#### 1.5 Field Calibration Protocol (Required)

1. Instrumented coast-down at each speed (RTK GPS 10 Hz + wheel encoders) until v=0
2. Repeat on level + each zone slope
3. Cold-start vs. warm-oil
4. Measure servo-to-neutral mechanical latency
5. Build lookup table `f(speed, slope) → stop_distance`
6. Apply 1.5× safety factor → configured envelope

---

### 2. Danger Envelope Geometry

#### 2.1 Sensor Frame

OAK-D Pro mounted (per `docs/field/001-sensor-location-measurements.md`): height 0.5–0.8 m, pitch 10–15° down, yaw 0°. Color cam HFOV 73°, VFOV ~56°.

#### 2.2 Envelope Formula

```
R(v) = d_stop(v) + v × t_reaction + margin_fixed
```

**System reaction time budget `t_reaction`:**

| Stage | Latency |
|-------|---------|
| Detection (1–2 frame intervals @ 15 FPS) | 33–66 ms |
| N-of-M consensus (2-of-3) | 33–66 ms |
| Host decision + MAVLink send | 5–15 ms |
| MAVLink transit + parse | 5–15 ms |
| PWM update | 0–20 ms |
| Servo mechanical transit | 50–100 ms |
| **Total — use 300 ms conservative** | **130–280 ms** |

#### 2.3 Computed Range vs. Phase 1 Detection Capability

Using `R = 1.25v² + 0.3v + max(1.0, 0.5v)`:

| Speed | d_stop | v × t_react | Margin | **Required R** | Person 3–10 m | Dog 2–5 m | Cat 2–3 m |
|-------|--------|-------------|--------|---------------|--------------|-----------|-----------|
| 0.8 m/s | 0.8 | 0.24 | 1.0 | **2.0 m** | ✅ | ✅ | ✅ |
| 1.0 m/s | 1.25 | 0.30 | 1.0 | **2.6 m** | ✅ | ✅ | ⚠️ |
| 1.5 m/s | 2.8 | 0.45 | 1.0 | **4.3 m** | ✅ | ⚠️ | ❌ |
| 2.0 m/s | 5.0 | 0.60 | 1.0 | **6.6 m** | ✅ | ❌ | ❌ |
| 2.5 m/s | 7.8 | 0.75 | 1.25 | **9.6 m** | ⚠️ | ❌ | ❌ |

#### 2.4 Lateral Half-Width

Use the full 73° HFOV (±36.5°). At range R lateral coverage = `R × tan(36.5°) ≈ 0.74R`. The 54" deck (1.37 m) is much narrower than camera coverage at any usable range — but the entire 700 lb vehicle is dangerous, so the full FOV is appropriate.

#### 2.5 Vertical Band

- Camera frustum: ~+13° to −43° (with 15° downward tilt, 56° VFOV)
- Valid detection band (relative to ground):
  - **H_min = 0.1 m** (excludes ground clutter)
  - **H_max = 2.5 m** (excludes birds, tree canopy)
- Depth filter on-device: 0.3–10.0 m via `setDepthLowerThreshold/UpperThreshold`
- Vertical filter host-side via `spatialCoordinates.y`

#### 2.6 Heading-Relative, NOT Predictive

The envelope is **purely camera-bore-sight forward**. Skid-steer can pivot instantly; predicting future position 2–5 s ahead is unreliable. The ±36.5° lateral coverage absorbs reasonable trajectories.

During pivot turns (rotation up to ~90°/s, speed already ≤1.2 m/s), 15 FPS NN captures a 6° arc per frame — adequate overlap.

#### 2.7 Pet-vs-Person: Closing-Speed Trigger

Dogs sprint at 6–12 m/s. A second trigger at extended range catches approaching threats:

| Trigger | Range | Condition | Action |
|---------|-------|-----------|--------|
| **Primary (in-zone)** | ≤ R(v) | Any detection in envelope | Hold + blade off |
| **Extended (closing)** | R < d ≤ 2R | Δd/Δt > threshold | Speed reduction to `WP_SPEED_MIN` |

Closing speed estimated by Δ-distance across consecutive frames (15 FPS → 67 ms Δt).

Recommended thresholds (configurable):
- `closing_speed_threshold`: 3.0 m/s
- `extended_range_multiplier`: 2.0
- Action: speed-reduce, do **not** full-stop (avoids excessive stops from parallax noise)

#### 2.8 Side & Rear Blind Spots — NOT Addressable by MVP Camera

| Scenario | Risk | Perception Addressable? |
|----------|------|------------------------|
| Pet at turn-point (was visible on approach) | High | Partially |
| Pet approaching from 90° side | Medium | ❌ |
| Pet darting from behind shrubbery | High | ❌ |
| Person behind moving-away mower | Low | ❌ |

**MVP decision:** Side/rear blind spots are **operator/geofence/SOP problems**:
1. Geofence exclusion zones around pet hideouts
2. Pre-scan turn zones (camera sweeps during pivot)
3. Reduced turn speed (already 0.8–1.2 m/s)
4. **Operator SOP**: pets indoors/fenced during mowing
5. Future: rear/side cameras (post-MVP)

---

### 3. Composition with Mowing Speed Envelope (Research 014)

#### 3.1 Zone Speeds

| Zone | Mow | Turn | Terrain | Required R |
|------|-----|------|---------|------------|
| NE | 2.0 m/s | 1.0 m/s | Flat | 6.6 m |
| NW | 1.5 m/s | 0.8 m/s | Sloped | 4.3 m + slope penalty |
| South | 2.5 m/s | 1.2 m/s | Flat | 9.6 m |

ArduPilot configured: `CRUISE_SPEED=2`, `WP_SPEED=1.4`, `WP_SPEED_MIN=1`.

#### 3.2 Maximum Safe Speed by Detection Target

Solving `R(v) ≤ detection_range`:

| Target | Reliable Range | Max Safe Speed |
|--------|---------------|----------------|
| Person | 10 m | **~2.6 m/s** |
| Dog | 5 m | **~1.7 m/s** |
| Cat | 3 m | **~1.1 m/s** |

#### 3.3 Three-Tier Safety Model

| Tier | Speed Range | Detection Guarantee | Use Case |
|------|-------------|---------------------|----------|
| **Full** | 0–1.5 m/s | Person + dog + cat (marginal) | NW; pet-prone areas |
| **Person + Large Dog** | 1.5–2.0 m/s | Person reliable, dog marginal | NE standard mowing |
| **Person Only** | 2.0–2.5 m/s | Person reliable | South, confirmed pet-free |

Zone YAML declares the tier. The system **refuses to run** at a speed inconsistent with the tier's detection capability.

#### 3.4 Slope Penalty (NW Zone)

`R_slope(v, θ) = R_level(v) × (1 + sin(θ) × g / a_decel)`

At 5° / 0.4 m/s²: factor ≈ 3.13× — confirms NW's reduced speed is necessary, and that uphill mowing direction is preferred where possible.

---

### 4. Tunable Surface — YAML vs. Hardcoded Floors

#### 4.1 Hardcoded Safety Floors (cannot be reduced by YAML)

| Constant | Value | Rationale |
|----------|-------|-----------|
| `MIN_STOP_TRIGGER_FRAMES` | 1 | Single high-confidence person detection MUST stop |
| `MIN_CLEAR_FRAMES_REQUIRED` | 5 | ≥333 ms before resume |
| `MIN_ENVELOPE_RANGE_M` | 2.0 | Envelope ≥ 2 m always |
| `MIN_CONFIDENCE_PERSON` | 0.20 | Floor on person threshold |
| `MIN_CONFIDENCE_PET` | 0.15 | Floor on pet threshold |
| `MAX_RESUME_SPEED_MPS` | 0.5 | Cap initial resume speed |
| `BLADE_DISENGAGE_ON_STOP` | true | Always disengages — not toggleable |
| `MIN_DETECTION_FPS` | 5 | Below → detector degraded → Hold |
| `MAX_SPEED_NO_DETECTION` | 0.0 | Detector offline → cannot move |
| `HEARTBEAT_TIMEOUT_MS` | 2000 | No heartbeat 2 s → Hold |

#### 4.2 YAML Configuration (`/etc/mower/perception.yaml`)

```yaml
perception:
  detection:
    confidence_person: 0.35         # floor 0.20, max 0.95
    confidence_pet: 0.30            # floor 0.15, max 0.95
    stop_trigger_frames: 2          # floor 1, max 5
    clear_frames_required: 10       # floor 5, max 60
    detection_fps: 15               # floor 5, max 30
  envelope:
    reaction_time_s: 0.3            # floor 0.1, max 1.0
    margin_fixed_m: 1.0             # floor 0.5, max 5.0
    margin_speed_factor: 0.5        # floor 0.0, max 2.0
    min_range_m: 3.0                # floor 2.0, max 15.0
    extended_range_multiplier: 2.0  # floor 1.5, max 3.0
    closing_speed_threshold_mps: 3.0  # floor 1.0, max 10.0
  stop_distance:
    calibration_source: "pre-calibration"  # or "field-YYYY-MM-DD"
    level_ground:
      - [0.0, 0.0]
      - [0.5, 0.2]
      - [1.0, 1.25]
      - [1.5, 2.8]
      - [2.0, 5.0]
      - [2.5, 7.8]
    slope_factor: 1.5               # floor 1.0, max 5.0
  safety_tier: "full"               # full | person_and_dog | person_only
  resume:
    initial_speed_mps: 0.5
    ramp_rate_mps2: 0.3
    cooldown_s: 2.0
```

#### 4.3 Per-Zone Overrides (in zone YAML)

```yaml
# zones/nw.yaml
perception:
  safety_tier: full
  stop_distance:
    slope_factor: 2.0
  envelope:
    min_range_m: 5.0
```

#### 4.4 Pre-Flight Validation

At startup, validate:
1. All YAML values within `[floor, max]` bounds
2. `safety_tier` consistent with configured `mow_speed_mps`
3. Calibration not expired (warn if >30 days)
4. Zone overrides do not weaken safety below global floors

Failure → CRITICAL pre-flight → mower refuses to arm.

---

### Key Discoveries

- Hold mode sets servos to TRIM; **no active braking** — mower coasts on hydraulic drag (~0.4–1.0 m/s²)
- Z254 has **no friction brakes**; E-stop (ignition kill) is the only true brake
- On slopes >5°, gravity may exceed hydraulic drag → mower creeps/accelerates downhill at neutral
- Required envelope at 2.0 m/s = 6.6 m (within person range 3–10 m, at limit for dogs 2–5 m)
- Max safe autonomous speeds by target: person ~2.6 m/s, dog ~1.7 m/s, cat ~1.1 m/s
- Three-tier safety model (Full / Person+Dog / Person-only) enforces speed/detection consistency per zone
- Extended-range closing-speed trigger (2×R) catches sprinting dogs without excess false stops
- Side/rear blind spots are operator/geofence/SOP problems — not addressable with single forward camera in MVP
- All stop-distance numbers are engineering estimates requiring field calibration; pre-calibration uses conservative `d = v² / 0.8`
- Safety floors are hardcoded; YAML provides bounded tuning; per-zone YAML overrides are allowed but cannot weaken floors

### Files Analyzed

| File | Relevance |
|------|-----------|
| `docs/research/014-multi-zone-lawn-management.md` | Zone speed structure |
| `docs/research/001-mvp-bringup-rtk-mowing.md` | Hydrostatic safety chain, ASMC-04A back-driveable, Hold architecture |
| `docs/config/mower.param` | ATC_DECEL_MAX=5, ATC_BRAKE=1, CRUISE_SPEED=2, WP_SPEED=1.4 |
| `docs/field/001-sensor-location-measurements.md` | Camera mount (0.5–0.8 m, 10–15° pitch) |
| `zones/ne.yaml` / `zones/nw.yaml` / `zones/south.yaml` | Per-zone speeds and terrain |

### External Sources

- [ArduPilot Hold Mode](https://ardupilot.org/rover/docs/hold-mode.html) — confirms servo output = SERVOx_TRIM in Hold

### Gaps

- Actual stop-distance numbers are unknown — field calibration required
- NW zone slope grade is undocumented (assumed ~5°)
- Warm-oil vs. cold-oil deceleration not quantified
- ATC_DECEL_MAX interaction with perception pre-Hold speed override is a Phase 3 architectural question
- Blade inertia after clutch disengage (PTO coast-down time) not accounted for in envelope

### Assumptions

- 0.4 m/s² conservative deceleration (KE analysis of 318 kg + ~125 N total drag)
- 300 ms conservative `t_reaction` (envelope of Phase 1 measured 40–60 ms + consensus + serial + mechanical)
- Camera VFOV ~56° (4:3 at 800p)
- NW slope ~5° (typical residential, needs measurement)
- Vehicle mass ~350 kg operational

## Phase 3: Safety Chain & Blade Interlock

**Status:** ✅ Complete
**Session:** 2026-05-02

### 1. Decision-Point Location

Three options evaluated against constraints (no fork, E-stop authority, existing 3-process architecture).

#### Option A: Companion (Jetson) → MAVLink → Pixhawk
| Criterion | Assessment |
|-----------|------------|
| Latency | ✅ Lowest (~5–15 ms detection → command) |
| Companion failure | ❌ No commands AND no heartbeat without Pixhawk-side watchdog |
| Debuggability | ✅ Excellent (structlog, correlation IDs) |
| RC interaction | ⚠️ `MAV_CMD_DO_SET_MODE` ignored in Manual; `MAV_CMD_DO_SET_SERVO` ignored unless function changed |
| No-fork | ✅ Standard MAVLink |

**Critical:** `MAV_CMD_DO_SET_SERVO` only works on `SERVOx_FUNCTION=0` or 51–66 with special handling. Currently `SERVO7_FUNCTION=56` blocks this.

#### Option B: Lua Script on Pixhawk
| Criterion | Assessment |
|-----------|------------|
| Latency | Medium (+15–30 ms vs Option A) |
| Companion failure | ✅✅ Lua detects heartbeat loss independently |
| Debuggability | ⚠️ Only STATUSTEXT; harder to correlate |
| RC interaction | ✅ `SRV_Channels:set_output_pwm_chan_timeout()` overrides ANY function including RC passthrough |
| No-fork | ✅ Lua is the intended extension mechanism |

#### Option C: ArduPilot OA — `OBSTACLE_DISTANCE` at 0 m
**❌ Rejected** for people/pet safety: OA path-plans around obstacles (not guaranteed Hold), and does not disengage blade. OA is correct for static obstacles (Phase 4) but wrong here.

#### ✅ Selected: Hybrid A+B

- **Primary (low latency):** Companion sends `NAMED_VALUE_INT(PCEP_STOP, 1)` + `MAV_CMD_DO_SET_MODE(Hold)`.
- **Secondary fail-safe:** Lua `perception-safety.lua` watches `PCEP_HB` heartbeat; on timeout (2 s) or `PCEP_STOP`, forces Hold + blade off via `set_output_pwm_chan_timeout()`.

Companion has intelligence + logging; Lua has hardware authority + survives companion crash.

---

### 2. Blade Clutch Override

#### Current State
- `SERVO7_FUNCTION=56` (RCIn6 passthrough; SC switch on Taranis)
- Relay is **fail-safe OFF** (no PWM = blade disengaged)
- Disengage PWM = SERVO7_MIN (1100 µs) — needs bench verification

#### Mechanisms Compared
| Mechanism | Works with Func=56? | Time-bounded? | Priority vs RC | Verdict |
|-----------|---------------------|---------------|----------------|---------|
| `MAV_CMD_DO_SET_SERVO(7,pwm)` | ❌ | No | Below RC | ❌ |
| Change `SERVO7_FUNCTION` at runtime | Yes but breaks RC blade ctrl | N/A | N/A | ❌ |
| **Lua `set_output_pwm_chan_timeout(6, pwm, ms)`** | ✅ | ✅ Auto-revert | ✅ Overrides RC | ✅ **SELECTED** |
| Hardware interlock relay (additional SERVO5) | Always | Hardware | Absolute | Reserve as defense-in-depth |

#### Selected: `SRV_Channels:set_output_pwm_chan_timeout(6, 1100, 30000)`

```lua
local BLADE_CHANNEL = 6     -- 0-indexed: SERVO7
local BLADE_OFF_PWM = 1100
SRV_Channels:set_output_pwm_chan_timeout(BLADE_CHANNEL, BLADE_OFF_PWM, 30000)
```

**Critical safety property:** the timeout is a dead-man — Lua must re-assert. Use **30 s** while perception stop is active so a Lua crash mid-stop keeps blade off long enough for operator intervention. `SERVO7_FUNCTION=56` does NOT need to change — `set_output_pwm_chan_timeout()` overrides regardless.

---

### 3. Order of Operations on Detection Event

```
T=0:    Detection consensus met
        ├── (a) NAMED_VALUE_INT(PCEP_STOP,1)    → Lua blade off
        ├── (b) MAV_CMD_DO_CHANGE_SPEED(0)      → active decel
        └── (c) MAV_CMD_DO_SET_MODE(Hold)       → servos to TRIM, coast
T+20ms: Lua loop sees PCEP_STOP
        ├── set_output_pwm_chan_timeout(6,1100,30000)
        └── vehicle:set_mode(4)  -- belt+suspenders
T+50–100ms:   PWM updates reach physical servos
T+100–500ms:  Servos at neutral, coasting begins
```

**Why blade first:** spinning blade is the lethal hazard; vehicle motion is secondary.

#### Dropped Message Handling
| Dropped | Consequence | Mitigation |
|---------|-------------|------------|
| `PCEP_STOP` | Blade engaged, no Hold | Companion retransmits 3× @100 ms; Lua heartbeat watchdog at 2 s |
| `DO_CHANGE_SPEED` | No active decel; coast only | Hold's TRIM handles passive coast |
| `DO_SET_MODE` | Stays in Auto at 0 speed | Lua redundantly calls `set_mode(4)` |

#### Behavior in Manual Mode
- `DO_SET_MODE` rejected when in Manual ✅ (operator override sacred)
- `DO_CHANGE_SPEED` no effect in Manual ✅
- **`set_output_pwm_chan_timeout()` STILL overrides blade** in Manual ✅

**Recommendation: Disengage blade in Manual on detection; do NOT fight RC for motion.** Blade is lethal; mower-bump survivable.

```yaml
perception:
  manual_mode_policy: blade_only  # blade_only | full_stop | disabled
```

#### Latch + Resume
- Blade override re-asserted every Lua cycle while STOPPED state holds
- Resume requires 10 consecutive clear frames (Phase 2 `clear_frames_required`)
- On clear consensus: companion sends `PCEP_CLR`, Lua releases override, mode → Auto, speed ramps from 0.5 m/s
- **Blade re-engagement requires explicit operator action** (RC SC switch or `mower blade on`); never automatic

---

### 4. Heartbeat / Watchdog

#### Companion → Pixhawk Heartbeat
| Field | Value |
|-------|-------|
| Message | `NAMED_VALUE_INT` |
| Name | `PCEP_HB` (10-char limit) |
| Value | Monotonic counter |
| Rate | 2 Hz |
| Timeout | 2000 ms (Phase 2 floor) |

#### Lua Watchdog
```lua
if perception_active and (millis() - last_heartbeat_ms > 2000) then
  gcs:send_text(2, "PERCEPTION OFFLINE - blade off, Hold")
  SRV_Channels:set_output_pwm_chan_timeout(6, 1100, 30000)
  vehicle:set_mode(4)
end
```

#### Why NOT `FS_GCS_ENABLE`
Acts on ALL heartbeat sources — would also fire on laptop GCS disconnect (which is normal during mowing). Lua watchdog is perception-specific.

#### Companion Self-Health
Detection service self-declares DEGRADED (NN rate < 5 Hz) or OFFLINE (no NN >2 s, OAK-D disconnect). On DEGRADED/OFFLINE: stops sending `PCEP_HB` → Lua watchdog triggers. **Dual-sided fail-safe.**

---

### 5. Failsafe Precedence

```
P0  Physical E-stop      (hardware, absolute — software CANNOT bypass)
P1  RC arm switch (SF)   (disarm → all servos safe)
P2  RC mode = Manual     (operator controls motion; blade override STILL ACTIVE)
P3  Perception STOP      (blade off + Hold + active decel; latched)
P4  RC throttle FS       (FS_THR_ENABLE=1, FS_THR_VALUE=910 → Hold)
P5  EKF/Fence FS         (FS_EKF_ACTION=2, FENCE_ACTION=2 → Hold)
P6  GCS / Mission        (lowest)
```

#### Should Perception STOP Disengage Blade in Manual? — YES (default)
- Blade is the lethal component
- False-positive cost: operator re-enables blade in 1 s
- False-negative cost: catastrophic
- Operator can opt out via `manual_mode_policy: disabled`
- Lua `set_output_pwm_chan_timeout()` operates below the mode system

---

### 6. Detector States & Pixhawk Action

| State | Definition | Vehicle | Blade | Speed Cap |
|-------|------------|---------|-------|-----------|
| **HEALTHY** | NN ≥5 Hz, heartbeat flowing | Normal Auto | Operator | Zone configured |
| **DEGRADED** | 2–5 Hz, transient hiccups | Reduce to `WP_SPEED_MIN` | Operator | 1.0 m/s |
| **OFFLINE** | >2 s no NN, OAK-D gone, HB timeout | **Hold** | **Disengage** | **0.0** (`MAX_SPEED_NO_DETECTION=0`) |

DEGRADED at 1.0 m/s requires only 2.6 m envelope (Phase 2) — achievable even at reduced FPS.

Recovery from OFFLINE: systemd restarts service → heartbeat resumes → Lua releases Hold; **blade re-engagement requires operator confirmation**.

---

### 7. SITL vs. Field Testability

| Test | SITL | Field |
|------|------|-------|
| `NAMED_VALUE_INT` plumbing | ✅ | — |
| Lua loading + execution | ✅ | — |
| `set_output_pwm_chan_timeout()` → SERVO_OUTPUT_RAW | ✅ | — |
| Mode transition Hold ← Auto | ✅ | — |
| Heartbeat timeout → Hold | ✅ | — |
| State machine (latch/clear/resume) | ✅ | — |
| Manual-mode blade override | ✅ | — |
| Multi-script coexistence (AHRS + safety) | ✅ | — |
| Actual blade clutch PTO disengage time | — | ✅ |
| Blade inertia coast-down | — | ✅ |
| Real serial latency under OAK-D + VSLAM load | — | ✅ |
| RC priority race during perception stop | — | ✅ |
| ASMC-04A servo-to-neutral latency | — | ✅ |
| E-stop interaction with Lua-held servo override | — | ✅ |

---

### 8. Required Parameter Changes

| Param | Current | Required | Reason |
|-------|---------|----------|--------|
| `SCR_ENABLE` | 0 | **1** | Gate for all Lua scripts |
| `FENCE_ACTION` | 1 (RTL) | **2** (Hold) | RTL drives through obstacles |
| `FS_EKF_ACTION` | 1 (RTL) | **2** (Hold) | Same |
| `FS_OPTIONS` | 0 | **1** | Failsafes respected even in Hold |
| `SCR_HEAP_SIZE` | default | **150000** | Two scripts (AHRS + safety) |
| `SERVO7_FUNCTION` | 56 | **56 (no change)** | `set_output_pwm_chan_timeout()` overrides regardless |

---

### 9. Lua Script Architecture

Two concurrent scripts in `APM/scripts/`:

| Script | Purpose | Rate | Status |
|--------|---------|------|--------|
| `ahrs-source-gps-vslam.lua` | EKF source switch (GPS↔VSLAM) | 10 Hz | ✅ Exists |
| `perception-safety.lua` | HB watchdog + STOP/CLR handler + blade override | 10–20 Hz | ❌ New |

**`perception-safety.lua` state machine:**
```
IDLE → (first PCEP_HB) → MONITORING
MONITORING → (PCEP_STOP OR HB timeout) → STOPPED
STOPPED → (PCEP_CLR + HB healthy) → RESUMING
RESUMING → (speed ramp complete) → MONITORING
```

Receives `NAMED_VALUE_INT` (msg_id 252) via `mavlink:receive_chan()` (ArduPilot 4.4+). Filter on name field: `PCEP_HB`, `PCEP_STOP`, `PCEP_CLR`.

---

### Key Discoveries

- **`SRV_Channels:set_output_pwm_chan_timeout(channel, pwm, ms)`** is the linchpin — overrides ANY servo function including RC passthrough, with auto-revert timeout
- **Hybrid A+B** (companion decides + Lua fail-safe) is optimal: companion has intelligence/logging, Lua survives companion crash
- **Option C (`OBSTACLE_DISTANCE` at 0)** rejected — OA path-plans rather than guaranteed Hold, doesn't address blade
- **Manual mode: blade still disengages** (Lua override below mode system); vehicle motion stays operator-controlled
- **`SCR_ENABLE=1` mandatory** (currently 0); also gates the existing AHRS source script
- **Blade re-engagement after perception stop: operator-only**, never automatic
- **30 s Lua timeout** keeps blade off even if Lua crashes mid-stop
- **`FS_GCS_ENABLE` is too coarse** — fires on laptop disconnect; Lua watchdog is perception-specific
- **`SERVO7_FUNCTION=56` stays unchanged** — the override mechanism is independent
- **SITL covers ~80%** of safety chain (plumbing, state machine, servos, timeouts); field-only is mechanical timing + RC priority races
- Required params: `SCR_ENABLE=1`, `FENCE_ACTION=2`, `FS_EKF_ACTION=2`, `FS_OPTIONS=1`, `SCR_HEAP_SIZE=150000`

### Files Analyzed

| File | Relevance |
|------|-----------|
| `docs/config/mower.param` | SCR_ENABLE=0, SERVO7_FUNCTION=56, FENCE/EKF action = RTL |
| `src/mower_rover/params/data/ahrs-source-gps-vslam.lua` | Existing Lua pattern: 10 Hz, gcs:send_text, ahrs:set_posvelyaw_source_set |
| `src/mower_rover/vslam/bridge.py` | MAVLink bridge component 197, 1 Hz heartbeat — perception service follows same pattern |
| `docs/research/001-mvp-bringup-rtk-mowing.md` | Phase 7 safe-stop, blade relay fail-safe-OFF, E-stop precedence |
| `docs/research/008-jetson-mavlink-vision-integration-deploy.md` | 3-process VSLAM, NAMED_VALUE_FLOAT health pattern |

### External Sources

- [ArduPilot Lua Scripts](https://ardupilot.org/rover/docs/common-lua-scripts.html) — `set_output_pwm_chan_timeout`, `vehicle:set_mode`, `gcs:send_text`
- [MAVLink MAV_CMD reference](https://ardupilot.org/rover/docs/common-mavlink-mission-command-messages-mav_cmd.html) — DO_SET_SERVO, DO_CHANGE_SPEED, DO_SET_MODE

### Gaps

- `mavlink:receive_chan()` Lua binding availability on Cube Orange firmware needs verification — fallback: `SCR_USER4`/`SCR_USER5` params written via `PARAM_SET`
- Exact blade disengage PWM (1100 vs 1500 µs) needs bench verification
- `set_output_pwm_chan_timeout()` channel index 0- vs 1-based — needs SITL verification
- Blade inertia coast-down time (residual hazard window)
- Two Lua scripts touching `SRV_Channels` simultaneously — thread safety in Lua sandbox

### Assumptions

- Channel param is 0-indexed (SERVO7 = ch 6)
- ArduPilot 4.5+ on Cube Orange has `mavlink:receive_chan()`
- Disengage PWM = SERVO7_MIN (1100 µs) per fail-safe-OFF design
- `SCR_HEAP_SIZE=150000` sufficient for two small scripts on H7 (1 MB RAM)
- `vehicle:set_mode(4)` = Hold for ArduPilot Rover

## Phase 4: ArduPilot OA Integration for Static Obstacles

**Status:** ✅ Complete
**Session:** 2026-05-02

### 1. `OBSTACLE_DISTANCE` Message — Format & Rover Support

#### Message Structure (MAVLink common #330)

| Field | Type | Usage for OAK-D |
|-------|------|-----------------|
| `sensor_type` | uint8 | `MAV_DISTANCE_SENSOR_LASER` (0) — closest match for stereo |
| `distances[72]` | uint16[72] | Distances in **cm**; `UINT16_MAX` or `max_distance` = no obstacle |
| `min_distance` | uint16 | **30** cm (stereo min) |
| `max_distance` | uint16 | **800** cm (stereo useful max) |
| `increment_f` | float | Sector angular width — **preferred** over `increment` |
| `angle_offset` | float | First sector angle relative to vehicle forward |
| `frame` | uint8 | `MAV_FRAME_BODY_FRD` (12) |

#### Rover Support
- **`OBSTACLE_DISTANCE` is consumed by Rover** via `AP_Proximity_MAV` when `PRX1_TYPE=2`
- Feeds both **Simple Avoidance** (stop) and **Bendy Ruler** (path deviation)
- Rate: **10–15 Hz** recommended

#### `OBSTACLE_DISTANCE_3D` — Rejected
- NOT consumed by Bendy Ruler or Dijkstra path planners
- Only used by Simple Avoidance (stop/backup)
- Less efficient for our planar use case
- **Use `OBSTACLE_DISTANCE` (72 sectors)** — feeds both Simple Avoidance AND Bendy Ruler

---

### 2. OAK-D Depth → 72 Sector Translation

Strategy mirrors ArduPilot's `d4xx_to_mavlink.py` (RealSense integration):

```
HFOV = 73°
N_SECTORS = 72
increment_f = 73 / 72 ≈ 1.014°
angle_offset = -36.5°
```

#### Algorithm (on Jetson)

```python
for sector in range(72):
    angle = ANGLE_OFFSET + sector * INCREMENT + INCREMENT/2
    col = int((angle / (HFOV/2) + 1) * width / 2)
    strip = depth_image[:, col-2:col+3]
    # height-filter each pixel: keep 0.1 m ≤ h ≤ 2.5 m above ground
    # take MIN distance among valid pixels
    distances[sector] = min_valid(strip, camera_height, pitch_rad)
```

#### Critical: Height Filter (0.1–2.5 m above ground)
Without it: tall grass at 0.5 m appears as obstacle wall. Filter:
1. Compute world-frame height per depth pixel using camera intrinsics + pitch (from ArduPilot `ATTITUDE`)
2. Reject ground returns (h < 0.1 m) and tree canopy/birds (h > 2.5 m)
3. Same constants as Phase 2 vertical band

#### Data Source
- Depth frames already on Jetson host from VSLAM pipeline (no extra OAK-D pipeline)
- IPC subscriber on Unix socket / shared memory
- Cost: ~1–2 ms/frame on Orin
- Publish at **10 Hz** (subsampled from 30 FPS stereo)
- Pitch compensation from ArduPilot `ATTITUDE` (already available via bridge)

---

### 3. `OA_TYPE` Choice — Bendy Ruler vs. Dijkstra

#### CRITICAL FINDING: Dijkstra Cannot Use Proximity Sensors

> **"Dijkstra's does not support avoiding objects sensed with lidar or proximity sensors"** — ArduPilot docs

Dijkstra ONLY plans around fence polygons + stay-out zones. **It cannot consume `OBSTACLE_DISTANCE`.**

#### Comparison

| Criterion | Bendy Ruler (1) | Dijkstra (2) | Combined (3) |
|-----------|-----------------|--------------|--------------|
| `OBSTACLE_DISTANCE` consumed | ✅ | ❌ | ✅ via BR |
| Fence/exclusion zones | ❌ direct | ✅ | ✅ via Dijkstra |
| Reactive to unknown obstacles | ✅ | ❌ | ✅ |
| CPU cost | Low | Medium | Medium |
| Skid-steer pivot suits | ✅ Excellent | ✅ | ✅ |
| Spline waypoints | ✅ | ❌ | ⚠️ |

#### ✅ Recommendation: **OA_TYPE=1 (Bendy Ruler) for MVP**

Reasons:
1. Dijkstra literally cannot see depth-camera obstacles
2. Bendy Ruler handles residential yard well (garbage can mid-row → probe → resume)
3. Skid-steer pivot makes Bendy Ruler's directional probing highly effective
4. Lower CPU on Cube Orange (already running Lua + EKF3 + RTK)
5. `OA_BR_LOOKAHEAD=5 m` matches stereo effective range

#### Future: OA_TYPE=3
When zone exclusion polygons are mature, upgrade to combined mode — Dijkstra plans globally around known exclusions, Bendy Ruler handles dynamic surprises. Param + fence change only; no companion code change.

---

### 4. Required Parameter Set

#### Current State
| Param | Current | Notes |
|-------|---------|-------|
| `OA_TYPE` | 0 | Disabled |
| `PRX1_TYPE` | 0 | Disabled |
| `AVOID_ENABLE` | 3 | Fence+Proximity (proximity ON but no source) |
| `FENCE_ENABLE` | 0 | Disabled |
| `FENCE_ACTION` | 1 (RTL) | **WRONG** — must be 2 (Hold) |

#### Required Changes (14 total)

| Param | Required | Rationale |
|-------|----------|-----------|
| `PRX1_TYPE` | **2** (MAVLink) | Companion sends `OBSTACLE_DISTANCE` |
| `OA_TYPE` | **1** (Bendy Ruler) | Reactive deviation around detected obstacles |
| `OA_BR_LOOKAHEAD` | **5** m | Matches stereo useful range |
| `OA_MARGIN_MAX` | **1.5** m | Body clearance (deck = 1.37 m) |
| `OA_DB_SIZE` | **100** | Yard tree/post/etc. count |
| `OA_DB_EXPIRE` | **10** s | Object disappears from DB after 10 s out of view |
| `OA_DB_QUEUE_SIZE` | **80** | Default usually fine |
| `OA_DB_OUTPUT` | **1** | GCS visualization |
| `AVOID_ENABLE` | **7** (all) | Fence + Proximity + GCS |
| `AVOID_MARGIN` | 2 m (no change) | |
| `AVOID_BACKUP_SPD` | **0** | **Disable backup** — no rear sensor |
| `AVOID_ACCEL_MAX` | **2** m/s² | Smoother stop on 350 kg vehicle |
| `FENCE_ENABLE` | **1** | Zone polygon as inclusion fence |
| `FENCE_ACTION` | **2** (Hold) | Phase 3 already requires this |

**Reboot required for:** `PRX1_TYPE`, `OA_TYPE` — add to plan 001's `reboot_required_params` frozenset.

#### Rover-Specific
- Rover **always STOPS** in Simple Avoidance (no slide; `AVOID_BEHAVE` is Copter-only)
- Simple Avoidance works in all modes **except Manual** — last-resort backup if Bendy Ruler fails
- `WP_RADIUS=2`, `WP_SPEED=1.4`, `CRUISE_SPEED=2.0` — OA may take vehicle outside `WP_RADIUS` during deviation; mission re-acquires next WP after

---

### 5. Composition: Deviate vs. Hold

#### Normal — Garbage Can Mid-Row
Bendy Ruler probes ±90° in increments around destination bearing, follows first clear path with progress, resumes direct path past obstacle. **Correct for static obstacles** — unlike Phase 3 STOP which must halt.

#### Boxed In — No Clear Path
- Vehicle stops in place (speed → 0), stays in Auto (not explicit Hold)
- Continuously re-checks for clear path
- **Mower concern:** blade stays engaged while stuck

**Recommendation:** Add **OA-stall watchdog** to `perception-safety.lua`:
- If speed=0 AND mode=Auto AND duration > 30 s → disengage blade + STATUSTEXT
- Operator resumes by re-engaging blade + GCS confirm

#### Moving Obstacle Coexistence with Phase 3

| Scenario | Handler | Behavior |
|----------|---------|----------|
| Person at 5 m | Phase 3 perception STOP | Hold + blade off + latch |
| Tree at 3 m | Phase 4 OA | Bendy Ruler deviates |
| Dog at 8 m closing 5 m/s | Phase 2 extended trigger → Phase 3 (if enters) | Speed reduce → STOP |
| Garbage can at 4 m | Phase 4 OA | Deviate |
| Person + tree | Phase 3 wins | Hold (OA inactive in Hold) |

**Architectural fact:** OA only operates in AUTO/GUIDED/RTL. The moment Phase 3 triggers Hold, **OA loses authority automatically**. No race condition, no config needed.

---

### 6. Param-Snapshot Impact

OA params are standard ArduPilot params — flow through standard `PARAM_SET`/`PARAM_VALUE` MAVLink. Plan 001's snapshot/restore handles them transparently.

| Concern | Action |
|---------|--------|
| Params dynamically appear when `OA_TYPE`≠0 | After enabling OA, re-snapshot |
| Baseline YAML | Add OA_*, PRX1_*, AVOID_*, FENCE_* to `desired_params.yaml` |
| Reboot required | Add `PRX1_TYPE` and `OA_TYPE` to `reboot_required_params` frozenset |
| Diff-and-confirm | Standard workflow (~14 changes shown) |

**No architectural changes needed.**

---

### 7. Fence Composition

Bendy Ruler **respects fences** ("avoids obstacles AND fences"):
- **Inclusion fence** (zone boundary) prevents off-lawn deviation
- **Exclusion polygons** (flower beds, deck, AC unit) respected
- **`OBSTACLE_DISTANCE` obstacles** (depth-detected) also respected

#### Zone Reuse (research 014)

```
Zone activation:
1. Upload mission (coverage)
2. Upload fence (inclusion + exclusion)   ← Bendy Ruler uses
3. Upload rally point
4. Start Auto
5. OBSTACLE_DISTANCE stream live          ← Bendy Ruler also uses
```

Triple defense: fence boundary + exclusion polygons + runtime depth detection.

---

### 8. Final Priority Model (with OA Added)

```
P0   Physical E-stop          (hardware, absolute)
P1   RC arm switch (SF)
P2   RC mode = Manual         (blade override still active)
P3   Perception STOP          (person/pet → Hold + blade off)
P4   RC throttle FS           (FS_THR → Hold)
P5   EKF/Fence FS             (FS_EKF/FENCE_ACTION → Hold)
P6a  Simple Avoidance STOP    (proximity → decel to 0)
P6b  OA path deviation        (Bendy Ruler in AUTO)
P7   GCS / Mission            (lowest)
```

**Key rules:**
1. **P3 > P6a/P6b**: Hold deactivates OA — no conflict
2. **P5 > P6b**: Fence breach → Hold
3. **P6a + P6b complementary**: Bendy Ruler re-routes; Simple Avoidance stops if obstacle within `AVOID_MARGIN` despite re-route
4. **OA does NOT affect blade** — tree doesn't threaten people; blade stays engaged during deviation
5. **OA stall watchdog (Lua)** disengages blade after 30 s stuck

---

### Key Discoveries

- **Dijkstra cannot use proximity sensor data** — explicitly documented; eliminated as primary OA
- **Bendy Ruler (OA_TYPE=1)** is the only viable MVP choice for depth-detected obstacles
- **`OBSTACLE_DISTANCE` 72 sectors at ~1°** maximizes angular resolution across OAK-D 73° HFOV
- **Simple Avoidance for Rover = STOP only** (no slide; `AVOID_BEHAVE` is Copter-only)
- **No conflict between Phase 3 STOP and OA** — Hold deactivates OA architecturally
- **Fence polygons compose with Bendy Ruler** — inclusion fence + exclusion zones + depth obstacles all respected
- **`AVOID_BACKUP_SPD=0`** for mower (no rear sensor → backing is dangerous)
- **`PRX1_TYPE` requires reboot** — add to plan 001's frozenset
- **14 param changes** total, all compatible with existing snapshot/restore
- **OA_TYPE=3 future upgrade** is param + fence only — no companion code change
- **`d4xx_to_mavlink.py` (ArduPilot RealSense)** is the implementation template
- **OA-stall watchdog** needed in `perception-safety.lua` (not built into ArduPilot): blade off after 30 s stuck
- **10 Hz `OBSTACLE_DISTANCE`** subsampled from 30 FPS stereo is sufficient
- **Height filter (0.1–2.5 m)** is critical to prevent grass / canopy false positives in OA sectors

### Files Analyzed

| File | Relevance |
|------|-----------|
| `docs/config/mower.param` | Current OA/PRX/AVOID/FENCE state |
| `docs/research/014-multi-zone-lawn-management.md` | Zone polygons → fence; mission upload protocol |
| `docs/plans/001-param-apply-snapshot-restore.md` | Snapshot/restore + reboot-required params |
| `src/mower_rover/vslam/bridge.py` | MAVLink bridge — extension point for OBSTACLE_DISTANCE publisher |
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | SLAM node owns OAK-D depth; IPC source for obstacle computation |

### External Sources

- [Bendy Ruler OA](https://ardupilot.org/rover/docs/common-oa-bendyruler.html)
- [Dijkstra OA](https://ardupilot.org/rover/docs/common-oa-dijkstras.html) — confirms no proximity sensor support
- [Simple Object Avoidance](https://ardupilot.org/rover/docs/common-simple-object-avoidance.html)
- [Proximity Sensors](https://ardupilot.org/rover/docs/common-proximity-landingpage.html)
- [Intel RealSense Depth Camera](https://ardupilot.org/rover/docs/common-realsense-depth-camera.html) — `d4xx_to_mavlink.py` template
- [OA Landing Page](https://ardupilot.org/rover/docs/common-object-avoidance-landing-page.html)

### Gaps

- `OBSTACLE_DISTANCE_3D` interaction with Bendy Ruler in Rover 4.5+ not definitively documented
- Bendy Ruler behavior crossing boustrophedon rows during deviation needs SITL test
- Min navigable gap (2×OA_MARGIN_MAX = 3 m) may be too wide for some tree gaps
- `OA_DB_EXPIRE=10` appropriateness for slow mower (5+ s out-of-view during turns) — field tunable
- Interaction with `DO_SET_RESUME_REPEAT_DIST` (mission rewind) — unverified

### Assumptions

- Rover 4.5+ on Cube Orange supports Bendy Ruler with MAVLink proximity (confirmed by docs, not field-tested on this build)
- `increment_f` (float) supersedes `increment` (uint8)
- `AVOID_BACKUP_SPD=0` disables backing per docs ("setting to zero would disable backing up")
- OA_DB memory on H7 sufficient for 100 obstacles (typical)
- 10 Hz `OBSTACLE_DISTANCE` achievable with ~1 ms/frame on Orin (trivial vs. 275 TOPS)

## Phase 5: Mower-Specific False Positive & Negative-Obstacle Handling

**Status:** ✅ Complete
**Session:** 2026-05-02

### 1. Tall Grass / Vegetation False Positives

#### Why Stereo Sees Tall Grass
SGM matching produces dense returns on textured 0.3–0.5 m grass at 2–4 m → "obstacle wall" in lower frame. Distance-dependent:
- < 2 m: dense, noisy individual blade returns
- 2–4 m: solid textured surface
- > 5 m: sub-pixel → mostly missed

#### Height Filter Mitigates This (per Phase 4)
World-frame height: `h = camera_height − d × sin(θ_pixel + θ_pitch)`. Pixels with `h < 0.1 m` rejected from `OBSTACLE_DISTANCE` sectors.

#### Ground-Plane Source — Tiered

| Tier | Source | Accuracy | When |
|------|--------|----------|------|
| **MVP** | IMU pitch from ArduPilot `ATTITUDE` (already on bridge) + VSLAM pose pitch | ±1–2° steady; ~2 cm height error at 0.6 m | Flat / gentle terrain |
| Future | RANSAC plane fit on lowest depth returns | Local slope independent | NW slope, terrain transitions |

RANSAC cost ~0.5–1 ms/frame on Orin — affordable when needed.

#### Irreducible Trade-off
| Floor | Grass FP | Missed real obstacles |
|-------|----------|----------------------|
| 0.0 m | Maximum | None |
| **0.1 m (selected)** | Uncut grass still triggers | Very low risk |
| 0.2 m | Reduced | Misses small toys, flat sprinkler heads |

**Resolution:** mow border passes first (headland) → interior sees only stubble < 0.15 m.

#### NN Detector Immune to Grass
YOLO trained on COCO with abundant grass backgrounds. **Zero false-positive risk on the NN path.** Grass is a depth-pipeline-only concern.

---

### 2. Mulch, Leaves, Dappled Sunlight

#### Cluster-Size Threshold (sparse noise rejection)

```python
MIN_PIXELS_PER_SECTOR = 10
for sector in range(72):
    valid = filter_height_band(column_pixels[sector])
    if len(valid) >= MIN_PIXELS_PER_SECTOR:
        distances[sector] = percentile(valid, 10)  # 10th, not min
    else:
        distances[sector] = MAX_DISTANCE
```

10th percentile (not absolute min) further rejects single-pixel mismatches.

#### Temporal Median (dappled-sun flicker suppression)

```python
TEMPORAL_WINDOW = 5  # 5 frames @ 10 Hz = 500 ms
sector_history[sector].append(current_distance)
if len(sector_history[sector]) > TEMPORAL_WINDOW:
    sector_history[sector].pop(0)
distances[sector] = median(sector_history[sector])
```

500 ms latency × 1.5 m/s = 0.75 m — acceptable because:
- Phase 3 perception STOP runs on **NN path**, not depth → no safety latency impact
- Bendy Ruler needs only 2–3 consistent frames before deviating
- Envelope already includes 1.0 m fixed margin

#### Combined Effect

| Source | Raw | + Cluster | + Temporal Median |
|--------|-----|-----------|-------------------|
| Mulch bed @ 3 m | 3–5 scattered pixels | Filtered out | N/A |
| Leaf pile @ 2 m | Dense fluctuating | Reports obstacle | Stable median |
| Dappled zone | Oscillates ±50% | May trigger | Smoothed/cleared |

---

### 3. Sprinkler Water & Rain

#### Mid-Air Droplets (Active Sprinkler)
Sparse, transient, non-repeating. Cluster threshold + temporal median handle it. **Operational SOP:** sprinkler schedule must not overlap mowing.

#### Rain on Lens — HARDWARE FAILURE MODE

Cannot be software-fixed. Mitigations:
| Mitigation | Type |
|------------|------|
| Lens hood / rain shield | Hardware (3D-printed) |
| Hydrophobic coating (RainX) | Hardware |
| Avoid mowing in rain | Operational SOP |
| Image-quality watchdog | Software detector (below) |

#### Image-Quality Watchdog (Lens Health)

```python
laplacian_var = cv2.Laplacian(gray_frame, cv2.CV_64F).var()
mean_lum = gray_frame.mean()

# Outdoor scene baseline: 200–500
FOCUS_DEGRADED = 50.0
FOCUS_OFFLINE  = 20.0
LUM_LOW = 20; LUM_HIGH = 240
```

State transitions:
- HEALTHY → DEGRADED: `laplacian < 50` for 10 consecutive frames
- DEGRADED → OFFLINE: `laplacian < 20` for 30 frames
- DEGRADED: speed cap `WP_SPEED_MIN=1.0 m/s`, log WARNING
- OFFLINE: Hold + blade off (same as Phase 3 heartbeat loss)

Cost: ~0.3 ms/frame on Orin. Negligible.

---

### 4. Low / Thin Obstacles (Hose, Cord, Sprinkler Head, Stakes)

#### Stereo Spatial Resolution Limit
At 800p / 73° HFOV: `0.057°/pixel`. Stereo correlation needs ≥6–8 px wide objects.

| Object | 2 m | 3 m | 4 m | 5 m |
|--------|-----|-----|-----|-----|
| Garden hose 25 mm | 9 px | 6 px | 4 px | 3 px |
| Extension cord 15 mm | 5 px | 3 px | 2 px | 2 px |
| Sprinkler head 50 mm | 18 px | 12 px | 9 px | 7 px |
| Edging stake 10 mm | 4 px | 2 px | 2 px | 1 px |
| Garden gnome 300 mm | ✅ | ✅ | ✅ | ✅ |

**Stereo cannot reliably see hose/cord/stakes beyond 2–3 m.** None are COCO classes either.

#### Mitigation Strategy
1. **Fixed installations** (sprinkler heads, edging, fittings) → exclusion zones in zone YAML with `buffer_m`
2. **Movable items** (hose, cord, toys) → **operator pre-mow walkaround SOP**
3. **Pop-up sprinklers** → operational schedule control

**Residual risk accepted:** A coiled hose in path will be driven over (350 kg vehicle + 54" deck → hose damaged, mower fine).

---

### 5. Negative Obstacles (Drop-offs, Ponds, Retaining Walls)

#### Stereo Fundamental Limit — "No Return" ≠ "Danger"

| Surface | Stereo result | OBSTACLE_DISTANCE |
|---------|---------------|-------------------|
| Air beyond cliff edge | No return | UINT16_MAX = "clear" |
| Pond/water | Specular, no match | "Clear" or distant |
| Dark void/ditch | Absorbs IR | "Clear" |

**ArduPilot interprets this as "drive ahead."** Mower will drive off cliffs, into ponds, over walls without other protection.

#### Primary Defense: Geofence Inclusion Polygon

Zone `boundary` in zone YAML → uploaded as `MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION`. With `FENCE_ENABLE=1` + `FENCE_ACTION=2` (Hold), mower physically cannot cross.

**Required margin:**
```
fence_margin = stop_distance(speed) + GPS_accuracy + AVOID_MARGIN
             ≥ 2.8 m + 0.02 m + 2.0 m
             ≥ 5 m from any cliff edge at 1.5 m/s
```

#### Exclusion Zones for Interior Hazards
```yaml
exclusion_zones:
  - name: "pond_edge"
    buffer_m: 5.0
    polygon: [...]
```
Bendy Ruler respects exclusion zones (Phase 4 §7).

#### Safety-Critical Implications
- Zone boundary survey requires RTK precision (±2 cm)
- Pre-flight MUST verify fence uploaded + `FENCE_ENABLE=1`
- **`FENCE_ACTION=2` and `FS_EKF_ACTION=2` (Phase 3) are not "good practice" — they are safety-critical** for negative obstacles
- E-stop is the only backstop if fence fails (GPS glitch, EKF reset)

#### Future (NOT MVP): IMU Pitch-Jump Detection
Reactive — `|pitch_rate| > 15°/s sustained 200 ms` → emergency Hold. Detects "we just drove off" — too late to prevent, limits further travel. Document as accepted residual risk.

---

### 6. Reflective / Textureless Surfaces

| Surface | Stereo Behavior | Defense |
|---------|----------------|---------|
| Wet patio concrete | Sparse/no returns | Exclusion zone |
| Standing water puddle | Specular/false | Operational SOP |
| Glass door/window | Sees through | Exclusion zone (house perimeter) |
| Smooth metal (AC unit) | Edge returns only | Exclusion zone + buffer |
| Fresh waxed car | Specular | Exclusion zone |

Same defense as negative obstacles: **geofence**. Standing water puddles < 50 mm: drive through safely. Image-quality watchdog catches active rain.

---

### 7. System-Level Mitigation Summary

| Mitigation | Layer | Addresses | Config |
|------------|-------|-----------|--------|
| Height filter (0.1–2.5 m) | Depth→sector | Grass, ground clutter, canopy | Hardcoded floor + YAML range |
| Cluster threshold (≥10 px) | Depth→sector | Single-pixel noise, mulch, sprinkler | YAML |
| Temporal median (5 frames) | Sector→MAVLink | Dappled flicker | YAML |
| 10th percentile (not min) | Depth→sector | Isolated mismatches | Hardcoded |
| Image-quality watchdog | Detection service | Rain, fog, occlusion | YAML |
| Detector heartbeat (Phase 3) | Lua + companion | NN failure | Phase 3 `PCEP_HB` |
| Geofence inclusion polygon | ArduPilot fence | **Negative obstacles, reflective** | Zone YAML `boundary` |
| Exclusion zones | ArduPilot fence | Fixed hazards, stereo-invisible | Zone YAML `exclusion_zones` |
| Per-zone speed override | Zone YAML | Difficult terrain | Zone YAML |
| Operator pre-mow SOP | Operational | Movable thin objects | Documented procedure |

#### Proposed `perception.yaml` Phase 5 Extensions

```yaml
perception:
  obstacle_distance:
    publish_rate_hz: 10
    temporal_window_frames: 5
    min_pixels_per_sector: 10
    percentile: 10
    height_min_m: 0.1
    height_max_m: 2.5
    ground_plane_source: imu_pitch  # imu_pitch (MVP) | ransac (future)
  image_quality:
    enable: true
    laplacian_degraded_threshold: 50.0
    laplacian_offline_threshold: 20.0
    luminance_low: 20
    luminance_high: 240
    degraded_frames_required: 10
    offline_frames_required: 30
```

#### Pre-Mow Walkaround SOP (Operator Checklist)
1. Walk zone boundary — confirm no new edge obstacles
2. Remove/relocate: hoses, cords, toys, loose items
3. Verify sprinkler schedule clear
4. Check for standing water (post-rain)
5. Confirm exclusion zones still accurate
6. Wipe OAK-D Pro lens

---

### 8. SITL vs. Field Testability

#### SITL-Testable (`@pytest.mark.sitl`)
- Height filter math, pixel→world height
- Cluster threshold, temporal median, percentile
- Sector calculation (72 × 1.014°)
- `OBSTACLE_DISTANCE` message construction
- Bendy Ruler response to synthetic obstacles
- Fence inclusion + exclusion zone enforcement
- Image-quality watchdog state transitions
- Config bounds validation

#### Field-Required (`@pytest.mark.field`)
- Grass height filter on actual zones
- Real low-obstacle detection at 2–3 m
- Dappled sun flicker suppression
- Mulch bed false-positive suppression
- Sprinkler transient filtering
- Rain-on-lens watchdog activation
- Negative obstacle test (drive toward edge with fence active) — **safety-critical**
- Hose-in-path residual risk confirmation
- IMU pitch accuracy on NW slope
- OA stall watchdog under real boxed-in conditions
- Stereo range characterization full sun vs. overcast

---

### 9. Failure-Mode Coverage Matrix

| Failure Mode | NN Detector | Depth→OA | Geofence | Operator SOP |
|---|---|---|---|---|
| Person/pet | ✅ PRIMARY | Supplementary | — | Pets indoors |
| Static obstacle | — | ✅ PRIMARY | If fixed | Walkaround |
| Tall grass FP | Immune | ⚠️ Height filter | — | Mow borders first |
| Dappled sun FP | Immune | ⚠️ Temporal median | — | — |
| **Drop-off / pond** | — | ❌ CANNOT | ✅ PRIMARY | Survey boundaries |
| **Hose / cord** | — | ❌ CANNOT | If fixed | ✅ PRIMARY |
| Rain on lens | ⚠️ Degrades | ⚠️ Degrades | Still works | Don't mow in rain |
| Reflective surface | — | ❌ CANNOT | ✅ PRIMARY | Exclusion zone |

---

### 10. Residual Risk Register

| ID | Hazard | Prob | Sev | Mitigation | Status |
|----|--------|------|-----|------------|--------|
| R5-1 | Unexpected hole/trench (no fence) | Very Low | High | None automated; E-stop | **Accepted** |
| R5-2 | Garden hose in path | Medium | Low | Operator SOP | **Accepted** |
| R5-3 | Extension cord in path | Low | Med | Operator SOP | **Accepted** |
| R5-4 | GPS glitch near cliff | Very Low | Critical | FS_EKF=2, RTK | **Accepted** (E-stop backstop) |
| R5-5 | Rain mid-mow | Medium | Low | Watchdog → DEGRADED → Hold | **Mitigated** |
| R5-6 | Tall grass false stops | High initially | None | Height filter + border-first | **Accepted** (operational) |
| R5-7 | Sprinkler activates mid-mow | Low | Low | Temporal filter + SOP | **Mitigated** |

---

### Key Discoveries

- **Stereo fundamentally cannot detect negative obstacles** — geofence inclusion polygon is the sole automated defense; **fence accuracy is safety-critical**
- Height filter (0.1–2.5 m) eliminates most grass FPs; uncut grass > 0.1 m still triggers (irreducible trade-off; resolved by border-first mowing)
- **IMU pitch from `ATTITUDE` is sufficient for MVP** ground-plane estimation; RANSAC is future enhancement for slopes
- Three-layer FP defense: height filter + cluster threshold (≥10 px) + 5-frame temporal median
- Thin/low obstacles (hose, cord, stakes) are below stereo resolution at any useful range — operator SOP is the only practical defense
- **Image-quality watchdog** (Laplacian variance + luminance, ~0.3 ms/frame) catches rain/fog/occlusion → DEGRADED/Hold
- **Rain on lens is purely a hardware problem** — lens hood + hydrophobic coating + SOP
- 10th percentile (not min) per sector is more robust than raw minimum
- Fence boundary inset must be ≥5 m from cliffs at 1.5 m/s (stop distance + GPS + AVOID_MARGIN)
- **NN detector is immune** to environmental FPs that affect stereo (grass, dappled sun, rain background, reflections) — COCO covers these
- **`FENCE_ACTION=2` and `FS_EKF_ACTION=2` are not just "good practice"** — they are **safety-critical for negative obstacles**

### Files Analyzed

| File | Relevance |
|------|-----------|
| `src/mower_rover/config/data/vslam_defaults.yaml` | Camera pitch −15°, 800p@30FPS, extrinsics for height filter |
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | SLAM owns OAK-D depth; IPC to obstacle service |
| `contrib/rtabmap_slam_node/include/vslam_pose_msg.h` | Pose msg includes pitch — available via IPC |
| `src/mower_rover/vslam/bridge.py` | Bridge already consumes ATTITUDE (pitch source) |
| `src/mower_rover/vslam/ipc.py` | PoseReader includes pitch |
| `zones/{ne,nw,south}.yaml` | Confirms `exclusion_zones` with `buffer_m` polygon support |
| `docs/research/014-multi-zone-lawn-management.md` | Fence upload protocol, exclusion zone semantics |
| `docs/field/001-sensor-location-measurements.md` | Camera mount geometry |

### External Sources

- DepthAI StereoDepth confidence filtering (Luxonis docs)
- ArduPilot ATTITUDE message (10–50 Hz pitch source)
- OpenCV Laplacian variance for focus quality

### Gaps

- `MIN_PIXELS_PER_SECTOR` (10) is engineering estimate — needs field calibration
- Optimal `TEMPORAL_WINDOW` (5 frames) — field testing may show 3 is sufficient
- Laplacian variance thresholds (50.0, 20.0) need outdoor calibration
- NW slope grade undocumented — IMU-only pitch may need RANSAC sooner than expected
- Whether SLAM node exposes per-pixel DepthAI confidence for additional cluster-quality filtering
- Blade-over-hose damage assessment unquantified (assumed minor)

### Assumptions

- Camera height ~0.6 m (Pixhawk + extrinsic offset) — needs field measurement
- DepthAI stereo correlation window 5×5 or 7×7 (standard SGM)
- 10th percentile more robust than 5th for vibration environment (analogous ag robotics)
- Maintained yard grass 0.05–0.10 m; uncut transitions 0.3–0.5 m
- NW slope ~5° → IMU pitch gives ±2 cm height error (within 0.1 m floor)
- Fence inset ≥5 m from hazards is feasible on 4-acre property without losing usable area

## Phase 6: CLI Surface, Logging, Validation Plan

**Status:** ✅ Complete
**Session:** 2026-05-02

### 1. CLI Surface

#### Laptop: `mower perception <verb>`

| Subcommand | Purpose | Actuator? | `--yes` | Transport |
|------------|---------|-----------|---------|-----------|
| `status` | Detector state, NN FPS, lens quality, last event, Lua state | No | — | SSH + MAVLink param read |
| `envelope <speed> [--slope]` | Compute `R(v)` per Phase 2 formula | No | — | Local |
| `sim-detection [--class] [--distance]` | Synthesize `PCEP_STOP` → end-to-end safety chain test | **YES** | **Required** | MAVLink `NAMED_VALUE_INT` |
| `calibrate-stop [--speed] [--runs]` | Instrumented coast-down test; writes calibration YAML | **YES** | **Required** | MAVLink + SSH |
| `export-events [--since] [--clips]` | Pull JSONL events + optional clips from Jetson | No | — | SSH/SCP |

#### Jetson: `mower-jetson perception <verb>`

| Subcommand | Purpose | Actuator? |
|------------|---------|-----------|
| `start` / `stop` / `restart` | systemd wrappers | No (but `stop` triggers Lua HB watchdog → Hold in 2 s) |
| `health` | Lightweight probe (used by laptop `status`) | No |
| `tail-logs` | `journalctl -fu mower-perception.service` | No |
| `ring-buffer` | Disk usage, oldest/newest clip, budget | No |

Justification: only `sim-detection` and `calibrate-stop` change vehicle state directly. `stop` is a Linux service operation whose safety effect is the *fail-safe response* (correct), not a CLI command.

---

### 2. Pre-Flight Check Integration

New file `src/mower_rover/probe/checks/perception.py` — 9 checks via `@register()`:

| Check | Severity | Pass condition |
|-------|----------|----------------|
| `perception_service_active` | **CRITICAL** | `systemctl is-active mower-perception.service` (via SSH) |
| `perception_oakd_nn_loaded` | **CRITICAL** | NN FPS ≥ `MIN_DETECTION_FPS` (5) |
| `perception_lua_scripts` | **CRITICAL** | `SCR_ENABLE=1` AND `perception-safety.lua` in scripting dir |
| `perception_params_set` | **CRITICAL** | All 19 params (5 from Phase 3 + 14 from Phase 4) match expected |
| `perception_fence_uploaded` | **CRITICAL** | `FENCE_ENABLE=1` AND vertex count > 3 for current zone |
| `perception_calibration_age` | **WARN** | Calibration < 30 days old |
| `perception_tier_speed_match` | **CRITICAL** | `safety_tier` consistent with zone `mow_speed_mps` |
| `perception_image_quality` | **WARN** | Single-frame Laplacian variance > 50.0 |
| `perception_heartbeat_flowing` | **CRITICAL** | ≥1 `PCEP_HB` received within 3 s |

**Dependency chain:** service_active → {nn_loaded, heartbeat_flowing} → image_quality. Lua/params/fence/calibration/tier are independent.

---

### 3. Structured Log Schema

Per-event JSONL → `/var/log/mower/perception/YYYY-MM-DD.jsonl`

```json
{
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "event_type": "stop_triggered",
  "timestamp": "2026-05-03T14:23:07.123456Z",
  "correlation_id": "f8a91bc2e3d4",
  "target_class": "person",
  "confidence": 0.82,
  "distance_m": 4.7,
  "closing_speed_mps": 0.3,
  "bbox": {"x1":120,"y1":80,"x2":200,"y2":350},
  "spatial_xyz_m": [4.5, -0.3, 1.2],
  "envelope_range_m": 4.3,
  "vehicle_speed_mps": 1.5,
  "system_state": {
    "vehicle_mode": "Auto",
    "armed": true,
    "blade_engaged": true,
    "detector_state": "HEALTHY",
    "safety_tier": "full"
  },
  "mavlink_correlation": {"pcep_stop_seq": 12, "pcep_hb_seq": 4217}
}
```

#### Event Types
| Type | When |
|------|------|
| `detection` | Per-frame detection (high volume; throttle in HEALTHY) |
| `stop_triggered` | 2-of-3 consensus → PCEP_STOP sent |
| `clear_consensus` | 10 clear frames → PCEP_CLR sent |
| `resumed` | Vehicle returned to Auto, ramping |
| `degraded` / `offline` / `recovery` | Detector state changes |
| `oa_obstacle` | Sector reports < AVOID_MARGIN |
| `oa_stall` | OA stall watchdog fired (30 s at speed=0 in Auto) |

#### Correlation ID Propagation
```
CLI cid → SSH env → structlog binding → event_id → MAVLink (event_id[0:8] as int32) → Lua STATUSTEXT prefix → resume references stop event_id
```

#### Timestamp
Jetson `time.time_ns()` UTC, GPS PPS-synced via Pixhawk (research 008 already syncs offset). ±1–5 ms drift acceptable.

#### Rotation
Daily files; 90-day retention; 10 GB total cap. Estimate: 2–5 MB/day after throttling.

---

### 4. SITL Test List (`@pytest.mark.sitl`)

#### Phase 2 — Envelope & Bounds (10 tests)
`test_envelope_formula_known_speeds`, `test_envelope_slope_penalty`, `test_envelope_minimum_floor`, `test_yaml_bounds_validation_rejects_below_floor`, `test_yaml_bounds_validation_accepts_valid`, `test_hardcoded_floor_not_overridable`, `test_tier_speed_consistency_full`, `test_tier_speed_consistency_person_dog`, `test_tier_speed_consistency_person_only`, `test_extended_range_closing_speed_trigger`

#### Phase 3 — Safety Chain (14 tests)
`test_pcep_stop_triggers_hold_mode`, `test_pcep_hb_timeout_triggers_hold`, `test_pcep_clr_releases_hold`, `test_blade_disengage_on_stop`, `test_blade_timeout_revert`, `test_lua_state_idle_to_monitoring`, `test_lua_state_monitoring_to_stopped`, `test_lua_state_stopped_to_resuming`, `test_manual_mode_blade_override`, `test_manual_mode_no_mode_change`, `test_resume_speed_ramp`, `test_latch_requires_clear_consensus`, `test_multi_script_coexistence`, `test_dropped_pcep_stop_retransmit`

#### Phase 4 — OA (10 tests)
`test_obstacle_distance_msg_construction`, `test_sector_angle_calculation`, `test_bendy_ruler_deviates_around_obstacle`, `test_simple_avoidance_stops_at_margin`, `test_fence_inclusion_blocks_deviation`, `test_oa_stall_watchdog_blade_off`, `test_oa_inactive_in_hold`, `test_obstacle_distance_height_filter`, `test_prx1_type_requires_reboot`, `test_avoid_backup_disabled`

#### Phase 5 — FP Defense (9 tests)
`test_height_filter_rejects_ground`, `test_height_filter_rejects_canopy`, `test_cluster_threshold_filters_sparse`, `test_temporal_median_smooths_flicker`, `test_10th_percentile_vs_min`, `test_image_quality_healthy_to_degraded`, `test_image_quality_degraded_to_offline`, `test_image_quality_recovery`, `test_config_bounds_obstacle_distance`

#### CLI Smoke (7 tests)
`test_perception_status_help`, `test_perception_envelope_computes`, `test_perception_envelope_with_slope`, `test_perception_sim_detection_dry_run`, `test_perception_export_events_help`, `test_jetson_perception_health_help`, `test_jetson_perception_start_help`

#### Pre-Flight (5 tests)
`test_preflight_perception_checks_registered`, `test_preflight_perception_service_critical`, `test_preflight_tier_speed_mismatch_fails`, `test_preflight_calibration_stale_warns`, `test_preflight_all_params_checked`

**Total SITL: ~55 tests.**

---

### 5. Field Test List (`@pytest.mark.field`)

#### Phase 1 (7) — NN FPS with VSLAM, thermal stability, person/dog/cat recall at distances, dappled sun
#### Phase 2 (7) — Coast-down at level + slope speeds, NW grade, cold/warm oil, servo-to-neutral latency
#### Phase 3 (5) — Blade clutch disengage time, ASMC-04A latency, **E-stop overrides Lua override**, RC priority race, Manual blade behavior
#### Phase 4 (4) — Bendy Ruler around real obstacle, OA_DB_EXPIRE tuning, min navigable gap, OA in boustrophedon
#### Phase 5 (6) — Grass FP rate per zone, **rain-on-lens watchdog**, **negative-obstacle fence stop (CRITICAL)**, hose-in-path residual, sprinkler transient

**Cardboard-cutout proxies acceptable** for routine person/dog/cat recall regression; live humans/animals only for acceptance.

---

### 6. Operator Pre-Flight Policy

| Detector State | Result | Mowing | Action |
|----------------|--------|--------|--------|
| HEALTHY (no WARNs) | ✅ GO | Yes | Proceed |
| HEALTHY + WARN | ⚠️ GO WITH CAVEATS | Yes | Acknowledge warnings |
| DEGRADED | ⚠️ GO WITH CAVEATS | Yes (capped 1.0 m/s) | Investigate |
| OFFLINE / any CRITICAL fail | ❌ NO-GO | **No** | Fix before mow |

**Manual-only escape hatch:** `mower preflight --skip-perception` for sessions that never leave Manual mode.

---

### 7. Dataset / Labelled-Clip Strategy (NG-7 Compliant)

#### Ring Buffer
- **GStreamer + nvenc** rolling 30 s H.264 segments on NVMe (no RAM hit; HW encoder free on Orin)
- On STOP event: hard-link last N segments → `/var/log/mower/perception/clips/{EVENT_ID}/`
- 5 s post-event capture
- Files: `video.mp4` + `detections.jsonl` + `metadata.json`

#### Disk Budget (2 TB NVMe)
| Consumer | Estimate |
|----------|----------|
| RTAB-Map DBs | ~200 GB |
| VSLAM + system logs | 50 GB |
| Perception JSONL | ~2 GB/year |
| **Perception clips** | **~45 GB / 90 days @ 10/day** |
| Models + OS | ~30 GB |
| **Free** | **~1.7 TB** |

#### Operator Labeling Workflow (Local Only)
1. `mower perception export-events --clips` → SCP to laptop
2. Review with VLC + `labels.yaml`, or local LabelStudio (Docker), or `mower perception review` TUI
3. Labels stored as YAML sidecar per clip — **never uploaded**
4. Re-training (if ever): manual, offline, on operator's training machine

```yaml
perception:
  clip_capture:
    enable: true
    ring_buffer_seconds: 30
    post_event_seconds: 5
    resolution: [640, 480]
    codec: h264_nvenc
    clip_dir: /var/log/mower/perception/clips
    max_retention_days: 90
    max_total_gb: 50.0
```

---

### 8. Implementation File Layout

#### New Files
```
src/mower_rover/perception/        # NEW package
  __init__.py
  detector.py                      # DepthAI / TensorRT inference
  consensus.py                     # N-of-M hysteresis
  envelope.py                      # Phase 2 R(v)
  obstacle_distance.py             # Depth → 72-sector OBSTACLE_DISTANCE
  image_quality.py                 # Laplacian + luminance watchdog
  mavlink_signals.py               # PCEP_HB/STOP/CLR sender
  clip_capture.py                  # Ring buffer + persistence
  service.py                       # Main entry (asyncio + sdnotify)
  config.py                        # YAML load + bounds validation

src/mower_rover/cli/
  perception_laptop.py             # `mower perception` Typer
  perception_jetson.py             # `mower-jetson perception` Typer

src/mower_rover/params/data/
  perception-safety.lua            # Lua watchdog + STOP/CLR handler

src/mower_rover/config/data/
  perception_defaults.yaml         # Defaults + bounds

src/mower_rover/probe/checks/
  perception.py                    # 9 pre-flight checks

systemd/
  mower-perception.service         # New systemd unit

tests/
  test_perception_envelope.py
  test_perception_consensus.py
  test_perception_obstacle.py
  test_perception_image_quality.py
  test_perception_safety_chain.py  # SITL Lua + MAVLink
  test_perception_oa_sitl.py
  test_perception_cli.py
  test_perception_preflight.py
  test_perception_config.py
  test_perception_field.py         # @pytest.mark.field stubs
```

#### Modified Files
- `src/mower_rover/cli/laptop.py` — `add_typer(perception_app, name="perception")`
- `src/mower_rover/cli/jetson.py` — same
- `pyproject.toml` — add `opencv-python>=4.8`, `numpy>=1.24` to `[jetson]` extras
- `src/mower_rover/probe/checks/__init__.py` — import perception module
- `scripts/jetson-harden.sh` — create `/var/log/mower/perception/` + permissions

#### systemd Unit
```ini
[Unit]
Description=Mower Perception Detection Service
After=network.target mower-vslam.service
Requires=mower-vslam.service

[Service]
Type=notify
ExecStart=/usr/local/bin/mower-jetson perception-daemon
Restart=on-failure
RestartSec=3
WatchdogSec=10
Environment=PYTHONUNBUFFERED=1
Environment=MOWER_LOG_DIR=/var/log/mower/perception

[Install]
WantedBy=multi-user.target
```

---

### Key Discoveries

- 11 total CLI commands (5 laptop + 6 Jetson); only 2 actuator-touching (`sim-detection`, `calibrate-stop`)
- 9 new pre-flight checks (7 CRITICAL, 2 WARN); OFFLINE blocks arming; DEGRADED is warn + 1.0 m/s speed cap
- Per-event UUID correlation propagates from CLI → SSH → structlog → MAVLink → Lua → resume
- ~55 SITL tests + ~29 field tests fully cover the architecture
- GStreamer + nvenc rolling segments avoid RAM hit; 50 GB clip budget on 2 TB NVMe = ~90 days at 10 events/day
- Dataset labeling is 100% local — no cloud, no fleet (NG-7 compliant)
- Implementation: ~12 new files in `src/mower_rover/perception/` + 2 CLI + 1 Lua + 1 systemd + 10 test files
- Existing patterns mirrored exactly (Typer add_typer, @register() probe checks, structlog correlation, SafetyContext)
- **Manual-only escape hatch** (`--skip-perception`) preserves operator's right to mow without perception

### Files Analyzed

| File | Pattern Used |
|------|-------------|
| `src/mower_rover/cli/laptop.py` | `add_typer()` registration |
| `src/mower_rover/cli/jetson.py` | Sub-typer composition |
| `src/mower_rover/cli/zone_laptop.py` | `requires_confirmation`, `SafetyContext` for actuator commands |
| `src/mower_rover/probe/checks/service.py` | `@register()` + Severity |
| `src/mower_rover/logging_setup/setup.py` | structlog JSON sink + correlation IDs |
| `src/mower_rover/safety/confirm.py` | SafetyContext wrapper |
| `tests/test_safety.py` / `test_cli_smoke.py` / `test_zone_cli.py` / `test_probe_service.py` / `test_health.py` | Test patterns |
| `pyproject.toml` | Entry points + extras |

### Gaps

- GStreamer + nvenc availability on JetPack 6 needs verification (likely present via DeepStream)
- IPC mechanism between SLAM node and perception service (Unix socket vs POSIX shm vs ZeroMQ) — planner decision
- Whether `perception-daemon` is a `[project.scripts]` entrypoint or `python -m mower_rover.perception.service`
- `PCEP_STOP` int32 value encoding event_id[0:8] — 4 bytes; collision risk acceptable but needs formal spec

### Assumptions

- GStreamer + nvenc available on JetPack 6 (standard DeepStream)
- Existing `JetsonClient` SSH transport reusable for pre-flight checks
- 640×480 for clip capture (sufficient for review; lower bandwidth than 800p)
- `perception-daemon` invoked by systemd only; not a public CLI entry point
- `structlog` JSONL sink works on Jetson without modification

## Overview

People-and-pet avoidance is implementable on the existing hardware (OAK-D Pro + Jetson AGX Orin + Pixhawk Cube Orange + ASMC-04A servos + electric blade clutch on `SERVO7`) **without** firmware forks, custom VSLAM, or cloud dependencies — but the system is fundamentally constrained by physics and the ArduPilot Rover navigation stack, and those constraints shape every architectural decision.

**The detector** is a YOLOv6n@416 SpatialDetectionNetwork running on-device on the OAK-D's Myriad X (Approach A, recommended for Release 1) at 30–60 ms latency. The OAK-D **cannot run a stereo+spatial-detection pipeline simultaneously with VSLAM stereo on the same device** — this is a hard hardware constraint that forced the architecture: VSLAM continues to use stereo on the OAK-D while perception runs detection on the same pipeline's spatial output, sharing depth via shared memory IPC. Approach B (depth on Jetson GPU/TensorRT) is reserved for Release 2 if FPS or thermal headroom proves insufficient.

**The danger envelope** is dictated by the Husqvarna Z254's hydrostatic transaxles having **no friction brakes** — the vehicle coasts to a stop at ≈0.4 m/s² when servos return to neutral. The formula `R(v) = 1.25v² + 0.3v + max(1.0, 0.5v)` is derived from physics + an added safety margin. Field calibration of the coast-down constant is **mandatory** before any autonomous operation. The 3-tier safety model (`full ≤1.5 m/s` / `person_and_dog ≤2.0 m/s` / `person_only ≤2.5 m/s`) maps detector confidence at distance to allowable mowing speed.

**The safety chain** is **hybrid: companion intelligence + Lua fail-safe**. The Jetson detection service sends `NAMED_VALUE_INT` messages (`PCEP_HB` heartbeat at 2 Hz, `PCEP_STOP` and `PCEP_CLR` events) to a new ArduPilot Lua script (`perception-safety.lua`). The Lua script enforces Hold + blade disengage on STOP, latches until consensus CLR, and **fails safe to Hold + blade off if the heartbeat stops for 2 s**. The linchpin is `SRV_Channels:set_output_pwm_chan_timeout(6, 1100, 30000)` — a Lua-only API that overrides RC passthrough on `SERVO7` with a 30 s expiring assertion, forcing the blade clutch off. **The physical E-stop retains absolute authority over both the companion and the Lua override.**

**Static-obstacle avoidance** uses **Bendy Ruler** (`OA_TYPE=1`) with depth → 72-sector `OBSTACLE_DISTANCE` messages at 10 Hz. Dijkstra was rejected because it ignores proximity sensors. 14 ArduPilot params change (proximity, OA, fence, avoid). An OA-stall watchdog (30 s at speed=0 in Auto) disengages the blade. Crucially, OA is **inactive in Hold mode**, so it does not conflict with the Phase 3 perception stop.

**False positives and negative obstacles** are addressed by a three-layer defense (height filter 0.1–2.5 m + cluster ≥10 px + 5-frame temporal median) plus an image-quality watchdog (Laplacian variance + luminance). **Negative obstacles (drop-offs, garden beds, ponds) cannot be reliably detected by stereo at this height/baseline** — the geofence (`FENCE_ENABLE=1`, `FENCE_ACTION=2`) is the **sole defense**. This is a non-negotiable architectural conclusion: the operator MUST survey and fence drop-offs before any autonomous mowing. Two ArduPilot defaults must be corrected in the field config: `FENCE_ACTION=2` (Hold, not RTL) and `FS_EKF_ACTION=2` (Hold, not RTL).

**The CLI surface** adds 11 new commands (5 laptop, 6 Jetson) following existing Typer + safety-primitive patterns. Only `mower perception sim-detection` and `mower perception calibrate-stop` are actuator-touching. Pre-flight gains 9 new checks (7 CRITICAL, 2 WARN); perception OFFLINE blocks arming, DEGRADED warns and caps speed to 1.0 m/s. Detection events log as JSONL to `/var/log/mower/perception/` with per-event UUIDs that propagate from CLI through MAVLink into the Lua state machine. A GStreamer + nvenc rolling 30 s ring buffer captures clips on STOP events for offline operator review (LabelStudio Docker or VLC + YAML sidecar). **All labeling is local; zero cloud dependency** (NG-7 satisfied).

The architecture totals: ~12 new Python files in `src/mower_rover/perception/`, 2 new CLI files, 1 new Lua script, 1 new systemd unit, 10 new test files, 19 new/changed ArduPilot params, ~55 SITL tests (`@pytest.mark.sitl`), and ~29 field-required tests (`@pytest.mark.field`). Implementation should proceed in the dependency order Phase 2 → 3 → 4 → 1 → 5 → 6 (formula and safety chain before detector integration; FP defense and CLI last).

## Key Findings

1. **OAK-D pipeline constraint dictates architecture.** Only one DepthAI pipeline per device; VSLAM and perception must share depth via IPC, not run as separate pipelines. Approach A (on-device detection) is recommended for Release 1; Approach B (Jetson GPU) is the Release 2 fallback.
2. **No friction brakes → coast-only deceleration.** Stop distance is governed by `R(v) = 1.25v² + 0.3v + max(1.0, 0.5v)`; field calibration of the 0.4 m/s² coast constant is mandatory before autonomous operation.
3. **Hybrid safety chain is correct.** Companion provides perception intelligence; Lua provides fail-safe behavior on heartbeat loss. Neither alone is sufficient; together they cover both detection failure and link failure.
4. **`SRV_Channels:set_output_pwm_chan_timeout` is the linchpin** for autonomous blade override on `SERVO7`. Without this Lua API, blade clutch could not be safely overridden against RC passthrough.
5. **`NAMED_VALUE_INT` is the right transport** for PCEP signals — lightweight, reliable, correlatable, no MAVLink dialect changes.
6. **Bendy Ruler is the only viable OA path planner** because Dijkstra ignores proximity sensors. 72-sector `OBSTACLE_DISTANCE` at 10 Hz is the integration contract.
7. **Geofence is the sole defense for negative obstacles.** Stereo cannot reliably detect drop-offs at this baseline/height. `FENCE_ACTION=2` and `FS_EKF_ACTION=2` are safety-critical and must be corrected from the current `=1` (RTL) defaults.
8. **Three-layer FP defense is necessary and sufficient** for grass and dappled-light conditions; rain-on-lens requires hardware mitigation (lens hood / hydrophobic coating) plus the image-quality watchdog.
9. **Manual mode requires explicit policy decision** for blade behavior on PCEP_STOP — research recommends "blade always disengages, mode change suppressed" (configurable).
10. **OA inactive in Hold means no conflict** between Phase 3 perception stop and Phase 4 OA — the two systems are mutually exclusive by design.
11. **Per-event correlation IDs propagate end-to-end** (CLI → SSH → structlog → MAVLink → Lua → resume), enabling forensic reconstruction of every safety event from a single log query.
12. **Local-only labeling fully satisfies NG-7.** GStreamer + nvenc clip capture, SCP export, VLC/LabelStudio review — no network dependency at any step.

## Actionable Conclusions

1. **Correct the failsafes immediately.** Set `FENCE_ACTION=2`, `FS_EKF_ACTION=2`, `FS_OPTIONS=1` before any autonomous mowing — these are independent of perception and currently wrong (RTL through obstacles).
2. **Implement the field calibration utility (`mower perception calibrate-stop`) early.** Without measured coast-down data, the envelope formula's safety margin is unverified. This is gating for any other field work.
3. **Build the Lua + heartbeat infrastructure before the detector.** The safety chain is the foundation; the detector is one possible source. SITL-validate the entire chain (PCEP_HB/STOP/CLR, blade override, latch, heartbeat timeout) before powering the OAK-D detection pipeline.
4. **Survey and fence all drop-offs.** Document the perimeter of every garden bed, pond, retaining wall, and steep slope on the property. Upload as inclusion fence with `FENCE_ENABLE=1`. This is operator SOP, not a coding task — but the planner must include it as a documented prerequisite.
5. **Choose Approach A for Release 1.** On-device YOLOv6n@416. Plan Approach B (Jetson GPU TensorRT) as a contingency if measured FPS or thermal data require it.
6. **Adopt the 3-tier safety model with hardcoded floors.** Permit operator-tunable parameters within validated bounds; reject configurations below safety floors at config load time (raise ValidationError).
7. **Add the 9 pre-flight checks before first autonomous run.** Without these, the operator has no observable assurance that the safety chain is alive.
8. **Implement clip capture from day one.** Operator review of stop events is the only feedback loop for tuning consensus parameters and identifying systematic FPs/FNs.

## Open Questions

These require **field validation** or **operator decision** — not further desk research:

1. **Actual coast-down constant** on level ground vs. NW slope vs. cold/warm transaxle oil — must be measured per Phase 2 protocol.
2. **Actual NN FPS** with concurrent VSLAM at 50 W power mode — measure before locking in Approach A vs. B.
3. **Manual-mode blade policy** — should `PCEP_STOP` disengage the blade in Manual? Research recommends YES; operator must confirm.
4. **GStreamer + nvenc availability** on JetPack 6 production image — likely yes via DeepStream, but unverified.
5. **IPC mechanism choice** between VSLAM node and perception service — Unix socket / POSIX shm / ZeroMQ — planner-level architectural decision.
6. **OA_DB_EXPIRE tuning** — how long should the OA database remember a transient obstacle (a person who walked through)? Field-tune.
7. **Min navigable gap** between obstacles for Bendy Ruler — depends on `OA_BR_LOOKAHEAD` and vehicle width; field-measure.
8. **Cat detection recall at distance** — YOLOv6n COCO data may be insufficient for small cats at 3+ m; field-test and consider supplementary training data if recall is too low.
9. **Image quality thresholds** — Laplacian variance threshold of 50.0 is a reasonable starting point; tune to actual zone conditions.

## Standards Applied

| Standard | Relevance | Guidance Used |
|----------|-----------|--------------|
| Project copilot-instructions.md | Hardware stack, tooling stack, conventions | All architectural choices conform: Python 3 + Typer + pymavlink + structlog + pytest; cross-platform; field-offline; structured output; safety primitive on actuator commands |
| NFR-2 / C-10 (field-offline) | All operational paths | Zero internet dependency; SSH + SCP only; local labeling only |
| NFR-4 (structured logging) | Detection event schema | Per-event JSONL + correlation IDs propagating end-to-end |
| NG-2 (no ArduPilot fork) | Safety chain implementation | Used existing Lua scripting + `NAMED_VALUE_INT` + standard servo override APIs |
| NG-3 (no custom VSLAM) | Detector pipeline | Used DepthAI SpatialDetectionNetwork with stock YOLOv6n |
| NG-4 (no general-purpose GCS) | CLI design | 11 narrowly-scoped subcommands; no mission editing, no map view |
| NG-7 (no cloud / fleet / multi-user) | Dataset strategy | Local-only ring buffer + manual offline labeling |
| ArduPilot Rover failsafe defaults | Phase 5 conclusions | `FENCE_ACTION=2`, `FS_EKF_ACTION=2` (Hold not RTL) per project rule |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-02 |
| Completed Date | 2026-05-02 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete (6 of 6) |
| Path | /docs/research/017-perception-people-pet-avoidance.md |
| Recommended Next Agent | `@pch-planner` |
| Implementation Order | Phase 2 (envelope) → Phase 3 (safety chain + Lua) → Phase 4 (OA) → Phase 1 (detector) → Phase 5 (FP defense) → Phase 6 (CLI + tests) |
