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
