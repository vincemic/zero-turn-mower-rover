# Procedure 002 — Extrinsic Calibration (Camera-to-Pixhawk Offset)

**Objective:** Physically measure the OAK-D Pro camera position relative to the Pixhawk Cube Orange IMU origin, record values in `vslam.yaml`, and apply the corresponding `VISO_POS_X/Y/Z` ArduPilot parameters.

**Related test:** `tests/test_vslam_field.py::test_field_extrinsic_calibration`

## Equipment Needed

- Tape measure (metric, mm precision)
- Plumb line or laser level (optional, for vertical offset)
- Laptop with `mower` CLI connected to Pixhawk via SiK radio
- Access to Jetson (SSH or local terminal) to edit `vslam.yaml`

## Reference Frame

ArduPilot NED body frame (origin at Pixhawk IMU):
- **X** = forward (toward front of mower)
- **Y** = right (toward right side of mower)
- **Z** = down

The OAK-D Pro reference point is the centre of the stereo baseline (midpoint between left and right cameras).

## Steps

1. **Identify Pixhawk IMU location** — the Cube Orange IMU is at the geometric centre of the carrier board, marked on the case.
2. **Measure forward offset (X):**
   - Measure the horizontal distance from the Pixhawk IMU centre to the OAK-D Pro midpoint, along the mower's forward axis.
   - Positive = camera is forward of Pixhawk.
3. **Measure lateral offset (Y):**
   - Measure the horizontal distance perpendicular to the forward axis.
   - Positive = camera is to the right of Pixhawk.
4. **Measure vertical offset (Z):**
   - Measure the vertical distance.
   - Positive = camera is below Pixhawk (NED convention: Z-down).
5. **Record measurements** in the data section below.
6. **Update `vslam.yaml`** on the Jetson:
   ```yaml
   extrinsics:
     pos_x: <measured X in metres>
     pos_y: <measured Y in metres>
     pos_z: <measured Z in metres>
     # roll/pitch/yaw: adjust only if camera is not level with Pixhawk
   ```
7. **Apply ArduPilot parameters** from the laptop:
   ```bash
   mower params apply --param VISO_POS_X=<X> --param VISO_POS_Y=<Y> --param VISO_POS_Z=<Z>
   ```
8. **Verify params applied:**
   ```bash
   mower params snapshot | grep VISO_POS
   ```
   - Values must match the physical measurements (±0.01 m).

## Pass / Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| X/Y/Z measured to ±1 cm | Measurements recorded | Measurements missing or >5 cm uncertainty |
| `vslam.yaml` updated | Values match measurements | Default values unchanged |
| `VISO_POS_*` params applied | Params match `vslam.yaml` | Params differ or not set |
| Param snapshot round-trip | Snapshot shows applied values | Values don't survive reboot |

## Data Recording

| Field | Value |
|-------|-------|
| Date | |
| Operator | |
| Pixhawk mounting location | |
| Camera mounting location | |
| X (forward, m) | |
| Y (right, m) | |
| Z (down, m) | |
| Roll offset (°) | |
| Pitch offset (°) | |
| Yaw offset (°) | |
| Pass / Fail | |
| Notes | |
