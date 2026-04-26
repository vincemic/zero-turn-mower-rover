---
id: "009"
type: research
title: "OAK-D Pro Full Feature Set Configuration"
status: ✅ Complete
created: "2026-04-24"
current_phase: "✅ Complete"
---

## Introduction

The OAK-D Pro is currently configured in a conservative low-power mode
(400p stereo, USB 2.0, no IR illumination) to work around early Jetson
USB enumeration issues. Now that the VSLAM pipeline is proven end-to-end,
this research documents what needs to change to run the OAK-D Pro at its
full feature set: 800p stereo, USB 3.x SuperSpeed, IR dot projector, and
IR flood LED.

## Objectives

- Identify every file that constrains OAK-D Pro features
- Document the exact current values and their target replacements
- Assess power and bandwidth feasibility
- Identify risks and rollback strategy

## Overview

### Current vs. Target Configuration

| Setting | Current | Target | Rationale |
|---------|---------|--------|-----------|
| Stereo resolution | 400p (640×400) | 800p (1280×800) | Full native sensor resolution of OV9282 |
| USB speed | `dai::UsbSpeed::HIGH` (USB 2.0, 480 Mbps) | `dai::UsbSpeed::SUPER` (USB 3.x, 5 Gbps) | Required for 800p bandwidth; see bandwidth analysis |
| IR dot projector | Off (not wired into pipeline) | On, 750 mA default | Enables active stereo for textureless surfaces |
| IR flood LED | Off (not wired into pipeline) | On, 200 mA default | Uniform illumination for low-light / shadow areas |
| Stereo FPS | 30 | 30 (unchanged) | Sufficient for mower speeds |
| IMU rate | 200 Hz | 200 Hz (unchanged) | Already optimal |
| Stereo depth preset | DENSITY | DENSITY (unchanged) | Better for outdoor ground coverage |

### Power Budget

| Component | Current Draw | Notes |
|-----------|-------------|-------|
| Base + stereo cameras | ~5 W | Two OV9282 + MyriadX |
| Stereo depth processing | ~0.5 W | On-chip |
| IR dot projector @ 750 mA | ~1 W | Configurable 0–1200 mA |
| IR flood LED @ 200 mA | ~0.3 W | Configurable 0–1500 mA |
| USB 3.x link overhead | ~0.2 W | vs USB 2.0 |
| **Total estimated** | **~7 W** | Well within Jetson USB-C 15 W budget |

Peak (all IR maxed): ~12.5 W — still within budget.

### Bandwidth Analysis

| Config | Per-Frame Bytes | @30 FPS | USB Budget |
|--------|----------------|---------|------------|
| 400p mono×2 + depth | 640×400×2 + 640×400×2 = ~1.5 MB | ~45 MB/s | USB 2.0 practical ~35 MB/s (**tight**) |
| 800p mono×2 + depth | 1280×800×2 + 1280×800×2 = ~6 MB | ~180 MB/s | USB 3.x practical ~350 MB/s (**comfortable**) |

USB 3.x is **mandatory** at 800p. The current USB 2.0 constraint was a
workaround for a Jetson USB bus re-enumeration issue where the MyriadX
bootloader appeared on bus 1 (USB 2.0) and the booted device
re-enumerated on bus 2 (USB 3.x), causing XLink search to fail. This
must be addressed (see Risks below).

## Key Findings

### Files Requiring Changes

#### 1. C++ SLAM Node — `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`

**a) USB speed (lines ~174–179):**
```cpp
// CURRENT:
dai::DeviceBase::Config dev_cfg;
dev_cfg.board.usb.maxSpeed = dai::UsbSpeed::HIGH;

// TARGET:
dai::DeviceBase::Config dev_cfg;
dev_cfg.board.usb.maxSpeed = dai::UsbSpeed::SUPER;
```

**b) Default resolution (line 78):**
```cpp
// CURRENT:
std::string stereo_resolution = "400p";

// TARGET:
std::string stereo_resolution = "800p";
```

**c) IR control — new code needed after pipeline start (~line 255):**
The DepthAI v3 C++ API provides IR control via `Device` after the
pipeline is started. The SLAM node needs to read two new YAML keys
(`ir_dot_projector_ma`, `ir_flood_led_ma`) from the config and apply
them:
```cpp
// After pipeline->start():
if (cfg.ir_dot_projector_ma > 0) {
    result.device->setIrLaserDotProjectorIntensity(
        cfg.ir_dot_projector_ma / 1200.0f);
}
if (cfg.ir_flood_led_ma > 0) {
    result.device->setIrFloodLightIntensity(
        cfg.ir_flood_led_ma / 1500.0f);
}
```
Note: DepthAI v3 `setIrLaserDotProjectorIntensity()` and
`setIrFloodLightIntensity()` take a float 0.0–1.0 (fraction of max),
not milliamps directly. Max dot projector = 1200 mA, max flood = 1500 mA.

**d) SlamConfig struct (lines 77–88) — add two new fields:**
```cpp
int ir_dot_projector_ma = 750;
int ir_flood_led_ma = 200;
```

**e) load_config() — read new YAML keys:**
```cpp
if (vslam["ir_dot_projector_ma"])
    cfg.ir_dot_projector_ma = vslam["ir_dot_projector_ma"].as<int>();
if (vslam["ir_flood_led_ma"])
    cfg.ir_flood_led_ma = vslam["ir_flood_led_ma"].as<int>();
```

**f) USB 2.0 bandwidth comment block (lines ~170–180) — update/remove:**
The explanatory comment about forcing USB 2.0 should be updated to
explain the new USB 3.x default and when to fall back.

#### 2. Python Config Schema — `src/mower_rover/config/vslam.py`

**a) VslamConfig dataclass (lines 60–68) — change defaults, add fields:**
```python
# CURRENT:
stereo_resolution: str = "400p"

# TARGET:
stereo_resolution: str = "800p"

# NEW FIELDS:
ir_dot_projector_ma: int = 750
ir_flood_led_ma: int = 200
```

**b) _coerce() validation (around lines 170–190) — add validation:**
```python
ir_dot_projector_ma = vslam_raw.get("ir_dot_projector_ma", 750)
if not isinstance(ir_dot_projector_ma, int) or not (0 <= ir_dot_projector_ma <= 1200):
    raise VslamConfigError(
        f"ir_dot_projector_ma must be int 0–1200, got {ir_dot_projector_ma!r}"
    )

ir_flood_led_ma = vslam_raw.get("ir_flood_led_ma", 200)
if not isinstance(ir_flood_led_ma, int) or not (0 <= ir_flood_led_ma <= 1500):
    raise VslamConfigError(
        f"ir_flood_led_ma must be int 0–1500, got {ir_flood_led_ma!r}"
    )
```

**c) to_dict() — include new fields in serialized output.**

**d) _coerce() return — pass new fields to VslamConfig constructor.**

#### 3. YAML Defaults — `src/mower_rover/config/data/vslam_defaults.yaml`

Currently just a comment. Should be populated:
```yaml
vslam:
  stereo_resolution: "800p"
  stereo_fps: 30
  imu_rate_hz: 200
  ir_dot_projector_ma: 750
  ir_flood_led_ma: 200
  pose_output_rate_hz: 20
  memory_threshold_mb: 6000
  loop_closure: true
  database_path: /var/lib/mower/rtabmap.db
  socket_path: /run/mower/vslam-pose.sock
  extrinsics:
    pos_x: 0.30
    pos_y: 0.00
    pos_z: -0.20
    roll: 0.0
    pitch: -15.0
    yaw: 0.0
bridge:
  serial_device: /dev/ttyACM0
  source_system: 1
  source_component: 197
```

#### 4. Probe Check — `src/mower_rover/probe/checks/oakd.py`

**Line 17:** `_MIN_USB_SPEED_MBPS = 5000` — already expects USB 3.x
SuperSpeed. No change needed. The probe was always expecting 5 Gbps;
the C++ node was the one forcing USB 2.0.

#### 5. Tests — `tests/test_vslam_config.py`

Need updates for:
- New default values (800p instead of 400p)
- New `ir_dot_projector_ma` and `ir_flood_led_ma` fields
- Validation boundary tests for IR values (0 OK, 1200/1500 OK, above = error)

### Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **USB bus re-enumeration on Jetson** — MyriadX bootloader at USB 2.0 on bus 1, booted firmware at USB 3.x on bus 2, XLink search fails | HIGH | Test with the Coolgear screw-lock C-to-C cable on a known USB 3.x port. If re-enum still fails, add a YAML `usb_max_speed` field so the operator can fall back to `HIGH` without recompiling. |
| **IR dot projector thermal** — continuous operation on a mower in summer sun | MEDIUM | Default 750 mA (62.5% of 1200 mA max) is conservative. The OAK-D Pro has a passive heatsink. Monitor via DepthAI chip temperature API. |
| **RTAB-Map memory at 800p** — 4× more pixels per frame increases feature extraction cost and map size | MEDIUM | `memory_threshold_mb` is already set to 6000 MB (Orin has 64 GB RAM). Monitor with health bridge. If map bloat is an issue, reduce to 720p. |
| **Stereo matching quality at 800p** — more detail but also more noise at range | LOW | DENSITY preset + subpixel + LR check already handles this. Field validation needed. |

### USB Speed Fallback Recommendation

Add a `usb_max_speed` YAML key to allow runtime override without recompilation:

```cpp
// In SlamConfig:
std::string usb_max_speed = "SUPER";  // or "HIGH" for fallback

// In create_depthai_pipeline():
dai::UsbSpeed speed = dai::UsbSpeed::SUPER;
if (cfg.usb_max_speed == "HIGH") speed = dai::UsbSpeed::HIGH;
else if (cfg.usb_max_speed == "SUPER_PLUS") speed = dai::UsbSpeed::SUPER_PLUS;
dev_cfg.board.usb.maxSpeed = speed;
```

This should be added to both C++ and Python config schemas.

## Actionable Conclusions

1. **USB 3.x is the hard prerequisite** — everything else (resolution, IR) is just config values, but USB speed determines whether 800p is physically possible.
2. **Test USB 3.x first in isolation** — before changing resolution or IR, just flip `HIGH` → `SUPER` and verify XLink connects. If the bus re-enumeration bug resurfaces, the `usb_max_speed` YAML fallback provides a non-recompile escape hatch.
3. **IR values are conservative** — 750 mA dot / 200 mA flood is well below max. Can be tuned in the field via YAML.
4. **All changes are YAML-driveable** — the C++ node already reads config from `/etc/mower/vslam.yaml`. The planner just needs to wire up the new keys.
5. **Rebuild + redeploy required** — the C++ SLAM node must be recompiled on the Jetson after changes.

## Open Questions

- **USB bus re-enumeration**: Was this fixed in later JetPack 6 updates, or does it persist? Needs field test.
- **IR effectiveness outdoors**: Dot projector is designed for indoor structured-light use. Outdoor effectiveness at >2m range in sunlight is unknown — field validation needed.
- **Thermal limits**: What is the OAK-D Pro junction temperature during summer mowing? May need to throttle IR if chip temp exceeds ~85°C.

## Standards Applied

| Standard | Relevance | Guidance |
|----------|-----------|----------|
| No organizational standards applicable | — | — |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-24 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/009-oakd-pro-full-feature-config.md |
