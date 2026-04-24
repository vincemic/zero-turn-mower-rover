# Procedure 004 — Lua EKF Source Switching Validation

**Objective:** Verify that the ArduPilot Lua script automatically switches the EKF3 position source from GPS (SRC1) to VSLAM (SRC2) when RTK degrades, and switches back when RTK recovers.

**Related test:** `tests/test_vslam_field.py::test_field_lua_source_switching`

## Equipment Needed

- Mower with full stack assembled (Pixhawk, Jetson, OAK-D Pro, RTK, SiK radios)
- RTK base station streaming RTCM3 corrections
- FrSky transmitter (for mode monitoring)
- Laptop running Mission Planner or QGroundControl (for STATUSTEXT messages)
- Dense tree cover nearby (natural GPS degradation)
- Stopwatch

## Pre-Conditions

- RTK Fix established in open sky
- VSLAM pipeline + bridge running on Jetson
- Lua script `vslam_switch.lua` deployed to Pixhawk APM/scripts/
- EKF3 dual-source configured: `EK3_SRC1_POSZ=1` (GPS), `EK3_SRC2_POSZ=6` (ExternalNav)
- ArduPilot logging enabled with `SCR` and `EKF3` log types

## Steps

1. **Establish baseline** — Confirm RTK Fix in open sky:
   ```
   GCS: GPS Status = RTK Fixed (Type 6)
   FrSky handset: GPS fix indicator shows RTK
   ```
2. **Verify SRC1 active** — Check GCS messages or `mower vslam health`:
   ```
   EKF3 source: SRC1 (GPS)
   ```
3. **Degrade GPS — walk/drive under dense tree cover:**
   - Start stopwatch when entering tree cover.
   - Monitor GCS for `STATUSTEXT` messages from the Lua script.
   - Expected: within ~2 s of GPS degradation (fix type drops below RTK Float):
     ```
     STATUSTEXT: "EKF3 source -> SRC2 (VSLAM)"
     ```
4. **Verify SRC2 active:**
   - `mower vslam health` should show `ekf_source: SRC2`
   - FrSky handset should display updated source info (if telemetry configured)
   - ArduPilot should continue navigating using VSLAM poses
5. **Recover GPS — return to open sky:**
   - Start stopwatch when exiting tree cover.
   - Wait for RTK Fix to re-establish.
   - Expected: Lua script switches back:
     ```
     STATUSTEXT: "EKF3 source -> SRC1 (GPS)"
     ```
6. **Record switching latencies** (both directions).
7. **Repeat 2–3 times** for consistency.

## Pass / Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| GPS→VSLAM switch | Occurs within ~2 s of GPS degradation | No switch or > 5 s latency |
| VSLAM→GPS switch | Occurs after RTK Fix re-established | Doesn't switch back |
| STATUSTEXT messages | Visible on GCS/laptop | Missing or garbled |
| No mode change | Vehicle stays in current mode during switch | Unexpected mode change |
| FrSky telemetry | Source change visible on handset | Not reflected |
| Repeatable | Consistent across 3 trials | Inconsistent switching |

## Data Recording

| Trial | GPS→VSLAM Latency (s) | VSLAM→GPS Latency (s) | STATUSTEXT Received | Mode Preserved | Pass/Fail |
|-------|------------------------|------------------------|---------------------|----------------|-----------|
| 1 | | | Yes / No | Yes / No | |
| 2 | | | Yes / No | Yes / No | |
| 3 | | | Yes / No | Yes / No | |

| Field | Value |
|-------|-------|
| Date | |
| Operator | |
| Location description | |
| Tree cover density | |
| RTK baseline distance (m) | |
| Log file number | |
| Pass / Fail (overall) | |
| Notes | |
