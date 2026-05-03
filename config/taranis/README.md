# Taranis X9D+ Configuration

EdgeTX/OpenTX model and radio settings for the mower rover's FrSky Taranis X9D Plus transmitter.

## Source

Exported from OpenTX Companion as `mower.otx`, then converted to EdgeTX YAML
via EdgeTX Companion v2.10.5.

## Files

| File | Description |
|------|-------------|
| `RADIO/radio.yml` | Radio-level settings: calibration, switch config, battery alarms, trainer, stick mode |
| `MODELS/model00.yml` | Model **"mow2"** — active model (model ID 1) |
| `MODELS/model01.yml` | Model **"mow"** — original model (model ID 2) |

## Model Summary

Both models are nearly identical — 10-channel, XJT D16, with Yaapu v1.8.0
telemetry script (`yaapu9`) on the main screen.

### Channel Map

| CH  | Source | Switch Gate | Role |
|-----|--------|-------------|------|
| CH1 | Aileron stick | SF↓ (arm) | Left steering servo |
| CH2 | Rudder stick | SF↓ (arm) | Right steering servo |
| CH3 | Throttle stick | — | Throttle |
| CH4 | Elevator stick | — | Elevator |
| CH5 | SG (3-pos) | SF↓ (arm) | Flight mode |
| CH6 | SC (3-pos) | — | Aux |
| CH7 | SF (2-pos) | — | Arm / disarm |
| CH8 | SB (3-pos) | — | Aux |
| CH9 | SA (3-pos) | — | Aux (input gated by !SA2) |
| CH10 | SH (momentary) | — | Momentary action |

### Key Settings

- **Arm switch:** SF (2-position) — SF↓ enables CH1/CH2/CH5
- **Failsafe:** NOPULSES (receiver stops output on signal loss)
- **RSSI alarms:** warning 45, critical 42
- **Internal module:** XJT PXX1, D16 protocol, 16 channels
- **Telemetry screen:** Yaapu FrSky Telemetry Script (`yaapu9`)

### Differences Between Models

| Field | mow2 (model00) | mow (model01) |
|-------|-----------------|----------------|
| Rudder trim | 10 | 6 |
| Input 8 ("cut") | SD → CH9, gated by !SA2 | Not present |

## Radio Hardware

- **Board:** x9d+ (FrSky Taranis X9D Plus, original)
- **Stick mode:** 2 (throttle left)
- **Switches:** SA–SE (3-pos), SF (2-pos), SG (3-pos), SH (momentary toggle)
- **Pots:** P1, P2 (with detent), SL1, SL2 (sliders)
- **Units:** Imperial
- **Firmware origin:** OpenTX 2.3V0026

## ArduPilot Parameter Verification (2026-05-01)

Cross-referenced against actual Pixhawk param dump (`docs/config/mower.param`):

| Taranis Channel | Switch | ArduPilot Function | Param | Confirmed |
|-----------------|--------|--------------------|-------|-----------|
| CH1 | Aileron (SF-gated) | Throttle Left | `SERVO1_FUNCTION=73` | ✓ |
| CH2 | Rudder (SF-gated) | Throttle Right | `SERVO3_FUNCTION=74` | ✓ |
| CH7 | SF (2-pos) | Arm/Disarm | `RC7_OPTION=153` | ✓ |
| CH9 | SA (3-pos) | Flight Mode Select | `MODE_CH=9` | ✓ |
| CH3 | Throttle | — | `RC3_OPTION=0` | No function |
| CH5 | SG (SF-gated) | — | `RC5_OPTION=0` | No function |
| CH6 | SC (3-pos) | — | `RC6_OPTION=0` | No function |
| CH8 | SB (3-pos) | — | `RC8_OPTION=0` | No function |
| CH10 | SH (momentary) | — | `RC10_OPTION=0` | No function |

### Key Corrections from Params

- **Flight mode channel is CH9/SA, NOT CH5/SG.** The Taranis model labels CH5 as
  "Flight mode" — this is OpenTX's internal flight-mode concept (affects rates/expos
  on the transmitter), NOT ArduPilot's flight mode channel.
- **Mode mapping** (`MODE_CH=9`, SA 3-pos):
  - SA-up (982 µs) → MODE1/2 = **Manual**
  - SA-mid (1494 µs) → MODE3/4 = Manual/**Acro**
  - SA-down (2006 µs) → MODE5/6 = Manual/**Auto**
- **SBUS confirmed:** `RC_PROTOCOLS=1`
- **FrSky telemetry:** `SERIAL2_PROTOCOL=10` (S.Port passthrough) at 57600 baud
- **Skid-steer:** `FRAME_CLASS=1`, `SERVO3_REVERSED=1`
- **GPS yaw:** `EK3_SRC1_YAW=2`, `COMPASS_USE=0`, `COMPASS_ENABLE=0`

### Safety Observations

| Parameter | Current | Target | Issue |
|-----------|---------|--------|-------|
| `ARMING_CHECK` | 0 | Non-zero | All pre-arm checks disabled |
| `FENCE_ACTION` | 1 (RTL) | 2 (Hold) | RTL drives through obstacles |
| `FS_EKF_ACTION` | 1 (RTL) | 2 (Hold) | Same |
| `FENCE_ENABLE` | 0 | 1 | No geofence active |

### Servo/Relay Outputs (Current State)

| Output | Function | Passes Through | Taranis Switch | Likely Role |
|--------|----------|----------------|----------------|-------------|
| SERVO1 | 73 (ThrottleLeft) | — | — | Left steering |
| SERVO3 | 74 (ThrottleRight) | — | — | Right steering (reversed) |
| SERVO5 | 0 (Disabled) | — | — | Reserved for ignition kill relay |
| SERVO6 | 58 (RCIn8) | RC CH8 | SB (3-pos) | Starter relay (momentary) |
| SERVO7 | 56 (RCIn6) | RC CH6 | SC (3-pos) | Blade clutch relay |
| SERVO8 | 55 (RCIn5) | RC CH5 | SG (3-pos, SF-gated) | Ignition kill relay (armed-only) |

**Key insight:** SERVO6/7/8 use RC input passthrough — they directly mirror the
corresponding RC channel's PWM value to the servo output. This gives the operator
direct switch control over relays from the Taranis. SERVO8 (RCIn5) is gated by
SF (arm switch) at the transmitter level, meaning the relay only actuates when
the Taranis considers the vehicle armed.

**Note:** The "cut" input on SD in Taranis model mow2 routes to CH9, which ArduPilot
uses solely as `MODE_CH`. The Taranis-side "cut" concept does not map to an ArduPilot
relay function — actual relay control is via the RCPassThru outputs above.
