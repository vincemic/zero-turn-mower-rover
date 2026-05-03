---
id: "017"
type: research
title: "Perception-Based Obstacle Avoidance — People & Pet Avoidance First"
status: 🔄 In Progress
created: "2026-05-02"
current_phase: "2 of 6"
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
| 2 | Danger Envelope & Stop-Distance Model | 🔄 In Progress | Envelope geometry (range, lateral half-width, vertical band); composition with current ground speed and a conservative hydrostatic stop-distance estimate; pet-vs-person thresholds; interaction with the planned mowing speed envelope from research 014; what's tunable via YAML vs. baked in | — |
| 3 | Safety Chain & Blade Interlock | ⏳ Not Started | Where the stop decision lives (Jetson companion vs. Pixhawk Lua vs. ArduPilot param-driven failsafe); how it triggers blade disengage on `SERVO7` ahead of the Hold transition; ordering relative to E-stop, RC SF arm, and EKF/fence failsafes; round-trip latency budget; behavior on detector loss (heartbeat, watchdog) | — |
| 4 | ArduPilot OA Integration for Static Obstacles | ⏳ Not Started | `OBSTACLE_DISTANCE` vs. `OBSTACLE_DISTANCE_3D` shape and rate; `OA_TYPE`, `PRX_*`, `AVOID_*` parameter set for Rover skid-steer; Bendy Ruler vs. Dijkstra trade-off on a 4-acre yard with pre-planned zones (research 014); how OA composes with mission re-planning vs. simple Hold; param-snapshot impact | — |
| 5 | Mower-Specific False Positive & Negative-Obstacle Handling | ⏳ Not Started | Tall-grass filter using VSLAM ground plane / IMU-projected ground; mulch/leaf returns; sprinkler water and rain on lens; low/thin obstacles (hose, extension cord, sprinkler head); negative obstacles (drop-offs, retaining walls, pond) and why stereo can't see them — geofence backstop strategy from research 014 zones | — |
| 6 | CLI Surface, Logging, Validation Plan | ⏳ Not Started | New `mower` / `mower-jetson` subcommands (e.g., `mower perception status`, `mower perception sim-detection` for dry-run); structured log schema for detection events (per-event correlation ID per NFR-4); SITL-validatable test list (`@pytest.mark.sitl`) vs. field-required tests (`@pytest.mark.field`); operator pre-flight check addition; dataset / labeled-clip strategy given NG-7 (no cloud / fleet) | — |

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

**Status:** ⏳ Not Started
**Session:** —

_Awaiting research session._

## Phase 3: Safety Chain & Blade Interlock

**Status:** ⏳ Not Started
**Session:** —

_Awaiting research session._

## Phase 4: ArduPilot OA Integration for Static Obstacles

**Status:** ⏳ Not Started
**Session:** —

_Awaiting research session._

## Phase 5: Mower-Specific False Positive & Negative-Obstacle Handling

**Status:** ⏳ Not Started
**Session:** —

_Awaiting research session._

## Phase 6: CLI Surface, Logging, Validation Plan

**Status:** ⏳ Not Started
**Session:** —

_Awaiting research session._

## Overview

_To be synthesized after all phases complete._

## Key Findings

_To be populated._

## Actionable Conclusions

_To be populated._

## Open Questions

_To be populated._

## Standards Applied

_To be evaluated per phase._

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-02 |
| Status | 🔄 In Progress |
| Current Phase | 1 of 6 |
| Path | /docs/research/017-perception-people-pet-avoidance.md |
