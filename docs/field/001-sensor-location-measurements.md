# Sensor Location Measurements — Z254 Rover

All position measurements use the **ArduPilot body frame**: origin at the Pixhawk IMU, axes X = forward (+), Y = right (+), Z = down (+). Measure in **metres** to the nearest centimetre. A steel tape measure and a plumb bob (or laser level) are the minimum tools.

> **Tip — measure twice.** Take each measurement independently a second time. If the two readings differ by more than 1 cm, measure a third time and take the median.

---

## 0. Establish the Reference Point (Pixhawk IMU)

Before anything else, mark the Pixhawk Cube Orange mounting location. Every other measurement is relative to this point.

| Detail | Notes |
|---|---|
| **What to mark** | The centre of the Cube Orange carrier board (the IMU lives directly under the vibration-damped cube). |
| **How** | With the Cube mounted and fastened, drop a plumb line from its centre to the chassis rail below and mark both spots with a paint pen. This gives you a vertical reference you can tape-measure from later. |
| **Orientation** | Confirm the Cube's arrow-forward mark points toward the front of the mower. The baseline expects `AHRS_ORIENTATION: 0` (normal upright). If you mount it rotated, record the rotation and update `AHRS_ORIENTATION` before entering any offsets. |

---

## 1. Primary GNSS Antenna (Main) — `GPS1_POS_X / Y / Z`

The simpleRTK3B Heading board's **Main** antenna is the position-fix reference. ArduPilot needs its offset from the Pixhawk IMU.

| Axis | Measurement | How to Measure |
|---|---|---|
| **X** (forward +) | Horizontal distance forward from Pixhawk to the centre of the Main antenna ground plane. | Tape along the mower centreline. If the antenna is behind the Pixhawk, record a negative value. |
| **Y** (right +) | Horizontal lateral offset. | Tape perpendicular to the centreline. Left of centre = negative. If both Pixhawk and antenna are on the centreline, Y = 0. |
| **Z** (down +) | Vertical distance from Pixhawk to antenna phase centre. | Use a plumb line or level. The antenna is almost certainly above the Pixhawk (on the ROPS bar), so the value will be **negative** (up = negative Z in NED). Measure from the Pixhawk IMU centre to the antenna ground-plane surface, then add ~5 mm for the internal phase centre offset of a typical survey patch antenna. |

**Parameters to set:**
```
GPS1_POS_X  =  <measured X in metres>
GPS1_POS_Y  =  <measured Y in metres>
GPS1_POS_Z  =  <measured Z in metres>
```

**Tips:**
- Mount the antenna on a ground plane ≥ 10 cm diameter (the simpleANT2B Budget Survey has one built in).
- Keep the antenna level; any tilt degrades accuracy.
- Route the coax away from servo and ignition wiring.

---

## 2. Auxiliary GNSS Antenna (Aux) — Heading Baseline

The Aux antenna forms the heading baseline with the Main antenna. The mosaic-H computes heading internally (`EK3_SRC1_YAW: 2`), but it needs to know the baseline vector.

| Measurement | How to Measure |
|---|---|
| **Baseline length** | Tape the straight-line distance between the **phase centres** of Main and Aux antennas. Target ≥ 1.0 m (heading accuracy ≈ 0.15° at 1 m, ≈ 0.03° at 5 m). |
| **Baseline orientation** | Record which antenna is forward. The standard config is Main = forward, Aux = rear (both on the ROPS crossbar). If you mount them left-right instead, note the bearing offset. |
| **Cable length match** | Measure both coax cables. They **must be identical length** (Septentrio requirement for differential phase). If you must cut cable, trim both to the same length and re-terminate. |
| **Level match** | Both antennas should be at the same height. Measure the height of each above the ROPS bar surface — difference should be < 5 mm. |

**Where this goes:** The baseline vector is configured in the mosaic-H receiver (via the Septentrio web interface or SBF command), not directly in ArduPilot. Record Main→Aux as a vector in the receiver's antenna frame (typically: +X = forward, +Y = right, +Z = up — **opposite Z sign from ArduPilot NED**).

---

## 3. OAK-D Pro Camera — `VISO_POS_X / Y / Z`

The camera's position and orientation relative to the Pixhawk are needed for VSLAM → ArduPilot EKF fusion.

### 3a. Position

| Axis | Measurement | How to Measure |
|---|---|---|
| **X** (forward +) | Horizontal distance forward from Pixhawk to the camera lens centre. | Tape along the centreline. The camera will likely be mounted at the front of the mower, so this is positive. |
| **Y** (right +) | Lateral offset from centreline. | If centred on the mower, Y = 0. |
| **Z** (down +) | Vertical distance from Pixhawk to the camera lens centre. | Plumb line or level. If the camera is above the Pixhawk, Z is negative. If below (e.g., mounted lower on the frame), Z is positive. |

### 3b. Orientation (Camera Tilt)

| Angle | Measurement | How to Measure |
|---|---|---|
| **Pitch** (downward tilt) | Angle below horizontal that the camera optical axis points. Target 10–15° down. | Use a digital inclinometer or phone level app held against the camera housing's flat face. A bubble level on top of the housing reads 0° when level; the downward tilt is the reading when the camera is in its final mount position. |
| **Roll** | Rotation around the optical axis. Should be 0° (horizon level in image). | Check with a level across the camera housing. |
| **Yaw** | Rotation left/right of the mower centreline. Should be 0° (camera facing dead forward). | Sight along the camera's optical axis and compare to a string stretched along the mower centreline. |

**Parameters to set:**
```
VISO_TYPE    =  1        (MAVLink vision)
VISO_POS_X   =  <measured X>
VISO_POS_Y   =  <measured Y>
VISO_POS_Z   =  <measured Z>
VISO_ORIENT  =  0        (forward-facing)
```

**Tips:**
- The OAK-D Pro should be vibration-isolated (VHB tape or rubber grommets) — engine vibration blurs stereo depth.
- Mount height of 0.5–0.8 m above ground gives good obstacle-detection range.
- Ensure the USB cable has strain relief so vibration doesn't loosen the connector.

---

## 4. Wheel Encoder Roller Radius — `WENC_RADIUS / WENC2_RADIUS`

Each CALT GHW38 encoder has a 200 mm rubber roller that presses against a drive-wheel tyre. ArduPilot needs the **effective roller radius** to convert encoder counts to ground distance.

| Measurement | How to Measure |
|---|---|
| **Roller diameter** | Use callipers across the rubber roller at three spots (each end and centre). Average the readings. Divide by 2 for radius. The nominal value is 0.100 m but actual may differ. |
| **Contact pressure** | With the encoder pressed against the tyre at operating pressure, measure the roller diameter at the contact point — compression reduces the effective radius slightly. Use the unloaded radius as starting point; field-calibrate against GPS ground speed later. |

**Parameters:**
```
WENC_RADIUS   =  <left roller radius in metres>
WENC2_RADIUS  =  <right roller radius in metres>
```

---

## 5. Wheel Encoder Lateral Position (Optional but Recommended)

If encoders are not symmetrically placed, ArduPilot benefits from knowing their lateral offset for skid-steer odometry.

| Measurement | How to Measure |
|---|---|
| **Track width** | Tape the distance between the left and right encoder contact patches (centre of each roller on its tyre), measured perpendicular to the mower centreline. This feeds into `WP_PIVOT_RATE` and skid-steer turn calculations. |

---

## 6. Steering Servo Linkage Geometry

Not a sensor location per se, but the physical linkage dimensions determine servo calibration endpoints.

| Measurement | How to Measure |
|---|---|
| **Servo arm length** | Measure from the ASMC-04A output shaft centre to the clevis/ball-joint pin centre (the moment arm). |
| **Linkage rod length** | Measure the pushrod from servo clevis pin to the lap-bar bellcrank pin. |
| **Neutral position** | With the mower on a flat surface and hydrostatic levers in neutral (engine off, wheels locked), mark the servo arm angle. This is your TRIM reference. |
| **Full forward / full reverse** | Move each lever to its mechanical stop and mark the servo arm angle. These define MIN/MAX. **Left and right will differ** — measure each side independently. |

**Parameters (set via `mower servo-cal`):**
```
SERVO1_TRIM / SERVO3_TRIM   (neutral PWM)
SERVO1_MIN  / SERVO3_MIN    (one-end PWM)
SERVO1_MAX  / SERVO3_MAX    (other-end PWM)
SERVO1_REVERSED / SERVO3_REVERSED
```

---

## 7. RPM Sensor Pickup Location

| Measurement | How to Measure |
|---|---|
| **Pickup clamp position** | The inductive pickup clamps around the spark plug lead on the FR691V. No positional offset is needed in ArduPilot, but **document which cylinder's lead you're using** (front or rear) because the wasted-spark ignition fires both — pick whichever has the cleaner routing away from servo wires. |
| **Cable routing** | Measure the cable run from pickup to opto-isolator board, and from board to the Cube Orange AUX pin. Keep the pickup cable ≥ 15 cm from servo PWM wires and ≥ 30 cm from the ignition coil to reduce EMI coupling. |

**No positional ArduPilot parameters needed**, but record `RPM1_PIN` (the AUX pin number used) and plan to field-calibrate `RPM1_SCALING` against a handheld tachometer.

---

## 8. FrSky RC Receiver Antenna Placement

| Measurement | How to Measure |
|---|---|
| **Antenna separation** | FrSky receivers with diversity antennas need the two antenna tips ≥ 9 cm apart and oriented at 90° to each other for best signal. Measure tip-to-tip distance and the angle between them. |
| **Distance from Pixhawk** | Keep the receiver and its antennas ≥ 10 cm from the Pixhawk and GPS coax to avoid interference. Tape the distance. |

**No ArduPilot positional offset parameters needed** — this is for RF performance, not EKF fusion.

---

## 9. SiK Radio Antenna Placement

| Item | What to Record |
|---|---|
| **Radio A (RTCM)** | Antenna location and height above chassis. Keep ≥ 20 cm from GNSS antennas (different frequency, but minimize conducted coupling). |
| **Radio B (MAVLink)** | Same guidance. If both SiK antennas are whip-style, orient them vertically and ≥ 15 cm apart. |

---

## Measurement Recording Template

For each component, fill in and keep with the build log:

```
Component:       ____________________
Date measured:   ____________________
X (fwd, m):      ____________________
Y (right, m):    ____________________
Z (down, m):     ____________________
Roll (°):        ____________________
Pitch (°):       ____________________
Yaw (°):         ____________________
Notes:           ____________________
Photo ref:       ____________________
```

Take a photo of each measurement with the tape visible and store it alongside this record. When you enter these values into ArduPilot, snapshot the parameter file with `mower params snapshot` so the values are version-controlled.
