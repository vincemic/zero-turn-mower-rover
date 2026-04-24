# Procedure 005 — End-to-End VSLAM Health Monitoring

**Objective:** Verify that `mower vslam health` on the operator laptop shows live VSLAM metrics received over the SiK MAVLink radio — without SSH to the Jetson.

**Related test:** `tests/test_vslam_field.py::test_field_health_monitoring_e2e`

## Equipment Needed

- Mower with full stack assembled and running (Pixhawk, Jetson, OAK-D Pro)
- VSLAM pipeline + bridge running on Jetson
- SiK radio pair: Radio B on Pixhawk TELEM1, Radio B ground-side on laptop USB
- Laptop with `mower` CLI installed
- Mowing area (lawn, field)

## Pre-Conditions

- SiK radio link established (MAVLink heartbeats flowing to laptop)
- VSLAM pipeline running on Jetson (`mower-vslam.service` active)
- Bridge running on Jetson (`mower-vslam-bridge.service` active)
- Bridge is sending `NAMED_VALUE_FLOAT` messages with `VSLAM_*` keys

## Steps

1. **Start health monitor on laptop:**
   ```bash
   mower vslam health --endpoint udp:127.0.0.1:14550
   ```
   (Adjust endpoint to match SiK radio ground station port.)

2. **Verify table appears** — The health table should populate within 2–3 s:
   ```
   VSLAM Health (live, 1 Hz refresh)
   ┌──────────────────┬────────────┐
   │ Metric           │ Value      │
   ├──────────────────┼────────────┤
   │ pose_rate_hz     │ 19.8       │
   │ confidence       │ 3          │
   │ tracking_status  │ OK         │
   │ covariance_norm  │ 0.042      │
   │ bridge_uptime_s  │ 342        │
   │ ekf_source       │ SRC1       │
   │ last_pose_age_ms │ 52         │
   └──────────────────┴────────────┘
   ```

3. **Check update rate** — Values should update at ~1 Hz. Watch `last_pose_age_ms` and `pose_rate_hz` for 30 s.

4. **Verify no SSH dependency:**
   - Confirm the laptop has **no** SSH session open to the Jetson.
   - All data arrives via MAVLink `NAMED_VALUE_FLOAT` over SiK radio.

5. **Obstruct camera briefly** (hand over lens for 3–5 s):
   - `confidence` should drop (to 1 or 0)
   - `tracking_status` should change to `DEGRADED` or `LOST`
   - Values should recover when camera is unobstructed.

6. **Walk the mower around** for 2 minutes, monitoring the health table. All values should remain updating.

## Pass / Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| Health table populates | Within 5 s of command start | No data after 10 s |
| No SSH required | All data via MAVLink/SiK radio | Requires SSH to Jetson |
| All VSLAM_* metrics present | All rows populated | Missing metrics |
| Update rate | ~1 Hz (values change every ~1 s) | Stale for > 5 s |
| Camera obstruction detected | Confidence drops, tracking degrades | No change |
| Recovery after obstruction | Values return to normal within 5 s | Stuck in degraded state |

## Data Recording

| Field | Value |
|-------|-------|
| Date | |
| Operator | |
| SiK radio link quality (%) | |
| Metrics visible (list) | |
| Update rate (approx Hz) | |
| Obstruction detection time (s) | |
| Recovery time (s) | |
| Pass / Fail | |
| Notes | |
