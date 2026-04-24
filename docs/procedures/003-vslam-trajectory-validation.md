# Procedure 003 — VSLAM Trajectory vs. RTK GPS Validation

**Objective:** Drive a known geometric pattern and compare the RTAB-Map VSLAM trajectory against the RTK GPS track to verify positional accuracy and identify any systematic offset requiring extrinsic adjustment.

**Related test:** `tests/test_vslam_field.py::test_field_vslam_trajectory_vs_rtk`

## Equipment Needed

- Mower with Pixhawk, OAK-D Pro, and Jetson fully assembled and powered
- RTK base station streaming RTCM3 corrections (RTK Fix confirmed)
- Laptop with Mission Planner or QGroundControl for log download
- Tape measure or ground markers for the driving pattern
- Ground stakes or cones for waypoints

## Pre-Conditions

- RTK Fix established (3D Fix Type = 6 in GCS)
- VSLAM pipeline running (`mower-vslam.service` active on Jetson)
- Bridge running (`mower-vslam-bridge.service` active)
- Extrinsic calibration completed (Procedure 002)
- ArduPilot logging enabled: `LOG_BITMASK` includes `IMU`, `GPS`, `VISO`, `EKF3`

## Driving Pattern

```
Start ──── 10m straight ────► Turn 90° right
                                    │
                                   10m
                                    │
                              Turn 90° right
                                    │
                              ◄──── 10m straight ──── Turn 90° right
                                                            │
                                                           10m
                                                            │
                                                        End (≈ Start)
```

Drive a 10m × 10m rectangle at walking speed (~1 m/s), returning to the start point.

## Steps

1. **Mark the pattern** — Place ground stakes at 4 corners of a 10 m square on flat, open ground with good GPS sky view and moderate visual texture.
2. **Start logging** — Begin ArduPilot `.bin` log recording. Note the log number.
3. **Drive the rectangle** in Manual mode at ~1 m/s, pausing briefly at each corner.
4. **Return to start** and stop. End the log.
5. **Download the log** via GCS or USB.
6. **Extract GPS track** — Plot `GPS.Lat`, `GPS.Lng` (or `POS.Lat`, `POS.Lng`).
7. **Extract VSLAM track** — Plot `VISO.PX`, `VISO.PY` (vision position estimate, NED).
8. **Compare trajectories:**
   - Overlay GPS and VSLAM tracks in a common NED frame.
   - Measure lateral offset on each straight segment.
   - Measure corner alignment.
9. **Evaluate:**
   - If straight-segment offset > 0.5 m, revisit extrinsic calibration (Procedure 002).
   - If heading drift > 5° over the rectangle, check IMU fusion parameters.

## Pass / Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| VSLAM trajectory recorded | `VISO` messages in log | No VISO data |
| Straight-segment accuracy | Offset ≤ 0.5 m from GPS | Offset > 0.5 m |
| Corner alignment | Turns within 1 m of GPS | > 1 m divergence at corners |
| Loop closure | Return-to-start error ≤ 1 m | > 1 m between start and end |
| No tracking loss | Continuous VSLAM poses throughout | Gaps > 2 s in VISO stream |

## Data Recording

| Field | Value |
|-------|-------|
| Date | |
| Operator | |
| RTK fix type at start | |
| Log file number | |
| Straight-seg offset (N, m) | |
| Straight-seg offset (E, m) | |
| Straight-seg offset (S, m) | |
| Straight-seg offset (W, m) | |
| Loop closure error (m) | |
| Max VISO gap (s) | |
| Extrinsic adjustment needed | Yes / No |
| Pass / Fail | |
| Notes | |
