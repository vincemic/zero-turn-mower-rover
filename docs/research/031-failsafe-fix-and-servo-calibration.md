---
id: "031"
type: research
title: "Failsafe Defaults Fix & Semi-Automated Servo Calibration"
status: ✅ Complete
created: "2026-05-06"
current_phase: "✅ Complete"
vision_source: /docs/vision/001-zero-turn-mower-rover.md
target_release: 1
---

## Introduction

This research addresses two blockers on the path to first autonomous mowing: (1) the Pixhawk still has incorrect failsafe defaults that would cause dangerous RTL behavior on fault, and (2) servo calibration (`mower servo-cal`) has not been implemented — the left/right hydrostatic levers are asymmetric and driving with symmetric defaults produces yaw drift. The user specifically wants to explore **automated or semi-automated servo calibration** with the mower on a stand (wheels free to spin but mower immobile), leveraging sensor feedback (wheel encoders, GPS, IMU) to reduce manual intervention.

## Objectives

- Determine the exact steps to apply and **verify** the failsafe corrections on the live Pixhawk (safety-defaults.yaml already has correct values; need to confirm pixhawk-sync applied them and the param dump matches)
- Determine whether fence polygon / fence radius need to be configured alongside `FENCE_ENABLE=1` to avoid immediate breach on arm
- Design a semi-automated servo calibration workflow that uses sensor feedback (wheel encoder RPM, GPS velocity, IMU yaw rate) to detect endpoints, neutral, and deadband without manual "press ENTER when wheel starts turning"
- Evaluate stand/lift options: jack stands, drive-wheel-off-ground jig, roller stand — what the mower needs to be safely elevated with wheels free
- Determine whether the ASMC-04A's programmable endpoint feature should be used vs. ArduPilot-side `SERVOn_MIN/MAX` only
- Produce a calibration profile format compatible with snapshot/restore and `mower params apply`

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Failsafe defaults — current state & fix verification | ✅ Complete | Verify pixhawk-sync result; fence polygon/radius requirements; apply + verify procedure; update mower.param dump | 2026-05-06 |
| 2 | Stand/lift safety requirements | ✅ Complete | Evaluate stand options for Z254 (weight, clearance, stability); safety constraints for engine-on calibration with wheels spinning; wheel encoder vs. no-encoder fallback | 2026-05-06 |
| 3 | Semi-automated servo calibration design | ✅ Complete | Sensor-feedback calibration algorithm (encoder RPM threshold, GPS velocity, IMU yaw); automation of Phase A–D from research 001 §5.6; ASMC-04A programmable endpoints vs. ArduPilot params; rate limiting & abort; profile format | 2026-05-06 |
| 4 | Integration with existing tooling | ✅ Complete | How `mower servo-cal` fits into CLI surface; safety primitive integration; SITL smoke-test path; persistence to snapshot; interaction with `mower params apply` and pixhawk-sync | 2026-05-06 |
| 5 | Field self-tuning via Acro mode + sensor fusion | ✅ Complete | Jack-stand rough calibration → field Acro-mode self-tuning using Pixhawk sensors (IMU yaw rate, RTK GPS velocity/heading, wheel encoders); Jetson calibration service architecture; RC-triggered workflow; auto-tune of MOT_THR_MIN, CRUISE_SPEED/THROTTLE, SERVO TRIM, ATC_STR_RAT_FF; parameter save on completion | 2026-05-07 |

## Phase 1: Failsafe defaults — current state & fix verification

**Status:** ✅ Complete  
**Session:** 2026-05-06

### 1. Current Pixhawk State vs. safety-defaults.yaml

The `docs/config/mower.param` dump (dated 2026-05-01) shows the following values for the six params in `safety-defaults.yaml`:

| Param | mower.param (current) | safety-defaults.yaml (target) | Match? |
|-------|----------------------|------------------------------|--------|
| `FENCE_ENABLE` | 0 | 1 | ❌ |
| `FENCE_ACTION` | 1 (RTL) | 2 (Hold) | ❌ |
| `FS_EKF_ACTION` | 1 (RTL) | 2 (Hold) | ❌ |
| `FS_ACTION` | 2 (Hold) | 2 (Hold) | ✅ |
| `FS_GCS_ENABLE` | 0 | 1 | ❌ |
| `ARMING_CHECK` | 0 | 13816 | ❌ |

**5 of 6 params need correction.** Only `FS_ACTION` already matches.

### 2. FS_GCS_TIMEOUT Fix Status — Already Resolved

Research 030 (Phase 1) identified that `FS_GCS_TIMEOUT` does not exist on Rover 4.6.3 (added for 4.7+). This caused `pixhawk-sync` to enter an infinite restart loop. Plan 027 (Phase 1, step 1.4) resolved this by:
- Removing `FS_GCS_TIMEOUT: 5` from `safety-defaults.yaml` — confirmed: current file has it only in a comment
- Removing `FS_GCS_TIMEOUT` from `z254_baseline.yaml`
- Refactoring `apply_params()` to return `ApplyResult` instead of raising — per-param success/failure reporting
- Updating `sync_params()` to skip "added" params (params in desired but not on firmware) with a warning

The safety-defaults profile now contains **6 active params** (not 7).

### 3. Pixhawk-Sync Service Status

The `mower-pixhawk-sync.service` (systemd oneshot, runs `mower-jetson pixhawk sync --port udp:127.0.0.1:14552` at boot) should now succeed on all 6 params. However, the **mower.param dump has NOT been updated** since 2026-05-01 — the safety-defaults have not yet been applied to the live Pixhawk. Procedure 006 has not been executed.

### 4. Fence Polygon/Radius Requirements with `FENCE_ENABLE=1`

Current fence params on the Pixhawk:

| Param | Current Value | Meaning |
|-------|---------------|---------|
| `FENCE_TYPE` | 6 | Bitmask: Circle(bit 1=2) + Polygon(bit 2=4) = 6 |
| `FENCE_RADIUS` | 300 | Circle fence radius = 300 m from HOME |
| `FENCE_MARGIN` | 2 | 2 m slowdown margin from boundary |
| `FENCE_TOTAL` | 0 | **No polygon fence uploaded** |
| `FENCE_ENABLE` | 0 | Fence disabled (will become 1) |

**Critical analysis:** `FENCE_TYPE=6` enables both Circle and Polygon. With `FENCE_ENABLE=1`:
- **Circle fence** (bit 1): Active — enforces 300 m radius from HOME. Easily covers a 4-acre lot (diagonal ~180 m).
- **Polygon fence** (bit 2): Enabled in bitmask, but `FENCE_TOTAL=0` means no polygon vertices loaded. ArduPilot does NOT breach on missing polygon — if no polygon items are uploaded, polygon fence is simply not enforced.

**Therefore: Enabling `FENCE_ENABLE=1` with current params will NOT cause an immediate breach.** The circle fence at 300 m is the sole containment boundary — safe for initial bring-up.

**For zone-based mowing:** `mower zone select <zone>` uploads polygon fence items via `upload_mission(conn, fence_items, mission_type=1)`. Each zone's boundary → `MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION`; exclusion zones → `MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION`. Polygon fence is populated dynamically per-zone.

**Safe sequence:**
1. Apply `safety-defaults` (sets `FENCE_ENABLE=1`, `FENCE_ACTION=2`)
2. Circle fence at 300 m is containment (safe for bring-up)
3. Before autonomous mowing, run `mower zone select <zone>` → uploads polygon fence
4. Pre-flight check PF-29 catches "no polygon loaded" before mission start

### 5. Apply + Verify Procedure — Accuracy

Procedure `docs/procedures/006-apply-safety-defaults.md` is comprehensive but has **staleness issues** from the `FS_GCS_TIMEOUT` removal:
- Step 2: says "exactly **seven** keys" including `FS_GCS_TIMEOUT` → should say **six**
- Step 3: says "Write the **seven** values" / "Applied **7** params" → should say **six**
- Step 4: says "no changes for all **seven** keys" → should say **six**

Core workflow remains correct: snapshot → dry-run → live apply → verify → re-dump.

### 6. Expected mower.param After Apply

```
ARMING_CHECK,13816      # was: 0
FENCE_ACTION,2          # was: 1
FENCE_ENABLE,1          # was: 0
FENCE_MARGIN,2          # unchanged
FENCE_RADIUS,300        # unchanged
FENCE_TOTAL,0           # unchanged
FENCE_TYPE,6            # unchanged
FS_ACTION,2             # unchanged (already correct)
FS_EKF_ACTION,2         # was: 1
FS_GCS_ENABLE,1         # was: 0
FS_TIMEOUT,1.5          # unchanged (not in safety-defaults)
```

Git diff of `docs/config/mower.param` should show changes to exactly 5 lines.

### 7. FS_TIMEOUT Considerations

On Rover 4.6.3, `FS_TIMEOUT` (currently 1.5s) is the shared timeout for both RC and GCS failsafe. The safety-defaults profile intentionally does NOT change it because increasing to 5s would make RC failsafe less responsive. Field validation is needed. Documented in safety-defaults.yaml comments.

**Key Discoveries:**
- **5 of 6 safety-defaults params need correction** on the live Pixhawk — only `FS_ACTION=2` already matches
- **`FS_GCS_TIMEOUT` already removed** from safety-defaults.yaml (plan 027) — `sync_params()` now skips unknown params
- **`FENCE_ENABLE=1` is safe to apply without a polygon fence** — circle fence at 300m is enforced; polygon is conditional on `FENCE_TOTAL>0`
- **Polygon fences uploaded dynamically per zone** via `mower zone select` — pre-flight PF-29 catches "no polygon loaded"
- **Procedure doc 006 is stale** — says "seven" keys, should say "six" after `FS_GCS_TIMEOUT` removal
- **`FS_TIMEOUT=1.5s` is the shared RC/GCS timeout on 4.6.3** — changing requires field validation

| File | Relevance |
|------|-----------|
| `src/mower_rover/params/data/safety-defaults.yaml` | The 6-param failsafe profile |
| `docs/config/mower.param` | Current param dump — 5/6 params need correction |
| `docs/procedures/006-apply-safety-defaults.md` | Apply procedure (stale: says "seven" keys) |
| `docs/research/030-remaining-jetson-instabilities.md` | FS_GCS_TIMEOUT root cause and fix |
| `docs/plans/027-remaining-jetson-instabilities-fixes.md` | Code fix steps for sync_params |
| `src/mower_rover/pixhawk/sync.py` | sync_params() skips unknown params |
| `src/mower_rover/cli/zone_laptop.py` | Zone select uploads polygon fence |
| `zones/ne.yaml` | Example zone config with fence_enable=true |

**External Sources:**
- [ArduPilot Fence Setup](https://ardupilot.org/rover/docs/common-geofencing-landing-page.html) — FENCE_TYPE bitmask, breach actions
- [ArduPilot Polygon Fence](https://ardupilot.org/rover/docs/common-polygon_fence.html) — Polygon enforcement only when uploaded

**Gaps:** None  
**Assumptions:** ArduPilot Rover 4.6.3 does not breach when polygon bit is set in FENCE_TYPE but no polygon is uploaded (FENCE_TOTAL=0). Based on ArduPilot docs: polygon fences "must also have been loaded via a fence list."

**Follow-up:**
- Update procedure doc 006: change "seven" to "six", remove `FS_GCS_TIMEOUT` from expected keys
- Consider whether `FENCE_TYPE` and `FENCE_RADIUS` should be added to `safety-defaults.yaml` or kept as zone-level config
- Field validation needed for `FS_TIMEOUT` value (1.5s vs 5s)

## Phase 2: Stand/lift safety requirements

**Status:** ✅ Complete  
**Session:** 2026-05-06

### 1. Z254 Weight and Physical Dimensions

| Spec | Value |
|------|-------|
| **Dry weight (no fuel, no operator)** | ~235 kg / ~518 lbs |
| **Weight with full fuel** | ~244 kg / ~538 lbs |
| **Cutting deck width** | 54 in / 137 cm |
| **Wheelbase** | ~48–52 in (estimated, needs physical measurement) |
| **Track width (rear drive wheels)** | ~42–46 in (needs measurement per `docs/field/001-sensor-location-measurements.md` §5) |
| **Ground clearance (frame rail)** | ~4–5 in |
| **Rear tire diameter** | ~20 in |
| **Engine** | Kawasaki FR691V, 726 cc V-twin, ~23 HP |

Safe lift points: main frame rails (front-to-rear) and rear cross member. NOT the deck, deck hangers, or ROPS.

### 2. Stand/Lift Options — Comparative Evaluation

| Rank | Option | Safety | Cost | Recommended? |
|------|--------|--------|------|-------------|
| **1** | **Roller stand (DIY)** | ⭐⭐⭐⭐⭐ | ~$50–100 | ✅ **Primary** — mower never leaves ground, no tip-over risk |
| **2** | Jack stands + chocks | ⭐⭐⭐⭐ | ~$40–80 | ✅ Good alternative |
| **3** | MoJack PRO (750 lb+) | ⭐⭐⭐ | ~$300 | ⚠️ Only if rated ≥750 lbs AND lifts rear |
| **4** | Floor jack + stands | ⭐⭐⭐ | ~$40–80 | ⚠️ Acceptable |
| **5** | Cinder blocks | ⭐⭐ | ~$10 | ⚠️ Emergency only |
| **6** | Drive-up ramps | ❌ | ~$50 | ❌ Reject — rear-heavy Z254 will tip backwards |

**Roller stand design:** Per-side cradle with 2× steel rollers (1.5 in OD, ~14 in long) on pillow-block bearings, ~12 in center-to-center. Wheel chocks front and rear. ~$60–100 BOM for both sides.

#### Roller Stand BOM — Sourced Parts (both cradles)

| Qty | Item | Spec | Source | Part # | Unit Price | Ext. |
|-----|------|------|--------|--------|-----------|------|
| 8 | Pillow-block bearing | 3/4" bore, set-screw, sealed, self-aligning | McMaster-Carr | [5913K63](https://www.mcmaster.com/5913K63) | $11.78 | $94.24 |
| 4 | Rotary shaft (axle) | 3/4" dia × 18" long, 1566 carbon steel, precision ground | McMaster-Carr | [1346K series](https://www.mcmaster.com/rotary-shafts/system-of-measurement~inch/diameter~3-4/length~18/) | ~$18 | ~$72 |
| 4 | Roller sleeve | 1-1/2" OD × 0.065" wall × 14" long, DOM steel tube (ID ≈ 1.370", slip-fit over 3/4" shaft with bushings or weld centering rings) | Local steel yard / Metals Depot | — | ~$8 | ~$32 |
| 2 | Frame angle | 2" × 2" × 1/8" steel angle, 18" long | Local steel yard / Home Depot | — | ~$8 | ~$16 |
| 2 | Frame angle (cross) | 2" × 2" × 1/8" steel angle, 14" long (connects pillows to frame) | Local steel yard / Home Depot | — | ~$6 | ~$12 |
| 4–6 | Wheel chocks | Rubber, heavy-duty, ≥6" wide | Any auto parts store | — | ~$8/pair | ~$16–24 |
| 16 | Mounting bolts | 3/8"-16 × 1" hex head + nut + flat washer (bearing mount) | McMaster-Carr / hardware store | — | ~$0.50 | ~$8 |

**Estimated total: ~$250–260** (McMaster bearings + shafts dominate cost)

**Cost-reduction alternatives:**
- **Amazon/eBay UCP204-012 bearings** — same spec as McMaster 5913K63 (3/4" bore pillow block, set screw, cast iron housing) at ~$5–8 each instead of $11.78. Search: "UCP204-12 pillow block bearing 3/4 inch bore". Saves ~$30–50.
- **Cut-to-length shaft from local steel supplier** — Cold-rolled 3/4" round bar (not precision-ground) is adequate for rollers (~$3–5/ft vs McMaster ~$1/inch). 6 ft of bar cuts into 4×18" pieces for ~$20 total.
- **Use 1-1/4" Sch 40 pipe** as roller sleeve (1.660" OD, 1.380" ID) — commonly stocked at Home Depot in 10 ft lengths (~$20, cuts into 8+ rollers).

**With budget alternatives (eBay bearings + local steel): ~$80–120 total.**

> **Note:** McMaster-Carr does not show prices without a logged-in account in some regions; prices confirmed 2025-07-15 via direct product page fetch. Shaft part number is approximate (exact depends on length availability — filter by 3/4" dia and 18" length in the rotary shafts category).

### 3. Engine-On vs. Engine-Off Calibration

The Z254 uses **Hydro-Gear EZT integrated transaxles** — one per side. The hydrostatic transmission is **engine-dependent**: without engine running, servo moves the lever but there is no hydraulic flow and wheels do not respond.

| Calibration Phase | Engine Required? | Why |
|-------------------|-----------------|-----|
| Phase A: Mechanical Neutral | ❌ No | Servo → lever → mechanical position only |
| Phase B: Endpoint Sweep | ❌ No | Servo → lever → mechanical stops only |
| Phase C: Deadband (wheel onset) | ✅ **Yes** | Needs hydraulic flow to detect wheel motion |
| Phase D: Output/save | ❌ No | Pure computation |

**Recommendation:** Split calibration into two sessions:
1. **Session 1 (engine-off):** Phases A + B — find neutral, sweep endpoints, mechanical limits
2. **Session 2 (engine-on, wheels on rollers):** Phase C — deadband with encoder feedback

### 4. Engine-On Hazards and Mitigations

| Hazard | Severity | Mitigation |
|--------|----------|------------|
| Spinning wheels | HIGH | Rate-limit servo sweep ≤50 µs/step; ±200 µs from TRIM max; roller stand |
| Blade engagement | CRITICAL | Software interlock: `SERVO7 ≤ 1100 µs`; PTO switch OFF; verify before start |
| Exhaust/CO | MEDIUM | Outdoors only |
| Noise (~95 dB) | MEDIUM | Hearing protection mandatory |
| Mower walking off stand | HIGH | Roller stand with chocks; front caster chocks |

### 5. Encoder Feedback vs. No-Encoder Fallback

**Current state: Encoders NOT yet wired** (`WENC_TYPE=0` in mower.param). Hardware selected (CALT GHW38 200 PPR quadrature) but level-shifter boards and wiring not done.

| Scenario | Mode | Precision |
|----------|------|-----------|
| **Encoders installed** | Semi-automated (threshold detection) | ±5 µs (1 step) |
| **Encoders not installed** | Interactive (operator visual + ENTER) | ±10–15 µs |
| **SITL / dry-run** | Simulated (log commands, no feedback) | N/A |

With encoders: 800 counts/rev (200 PPR × 4 quadrature). Can detect wheel onset within 1 PWM step via `WHEEL_DISTANCE` MAVLink message. Detection threshold: encoder delta > 3 counts over 200 ms.

Without encoders: Original research 001 §5.6 interactive design — operator watches wheel, presses ENTER when rotation observed. Less precise but functional.

**CLI should support both modes:** `--encoder-feedback` (default when `WENC_TYPE != 0`) and `--manual-feedback` (fallback).

### 6. Safety Protocol for Stand Calibration

**Pre-calibration checklist (software-enforced):**
1. Mower on roller stand or jack stands (operator confirms)
2. Front casters chocked (operator confirms)
3. E-stop accessible and tested (operator confirms)
4. Blade clutch DISENGAGED — `SERVO7 ≤ 1100 µs` (software check)
5. PTO switch OFF (operator confirms)
6. Engine running at idle (software check via RPM1, or operator confirms)
7. Hearing protection worn (operator confirms)
8. No persons/animals within 3 m (operator confirms)
9. Outdoors or well-ventilated (operator confirms)
10. Fire extinguisher within reach (operator confirms)

**Runtime safety constraints:**
- Hard PWM clamp: [SERVO_MIN + 50, SERVO_MAX - 50] µs
- Soft rate limit: 50 µs/step max, 5 steps/sec = 250 µs/sec max slew
- Deadband sweep limit: ±200 µs from TRIM (abort if no onset detected)
- Abort key: `q` or `Ctrl+C` → immediate return to TRIM
- Idle timeout: 30 sec → auto-abort
- E-stop hook via `SafetyContext.register_safe_stop()`
- Blade clutch interlock: verify `SERVO7` still disengaged before each sweep step

**Key Discoveries:**
- Z254 at ~518 lbs exceeds most consumer mower lift capacities — roller stand is safest
- Hydrostatic transmission is engine-dependent: no wheel response without engine
- Calibration should be split: engine-off (mechanical) + engine-on (deadband)
- Encoders not yet wired (`WENC_TYPE=0`); CLI must support manual fallback
- Hard PWM clamp of ±200 µs from TRIM limits wheel speed to very low RPM
- Blade clutch interlock is a critical pre-calibration software check

| File | Relevance |
|------|-----------|
| `docs/research/001-mvp-bringup-rtk-mowing.md` (§5.1–§5.7) | Servo calibration design, safety primitives |
| `docs/config/mower.param` | Confirms `WENC_TYPE=0`, `RPM1_TYPE=0` |
| `src/mower_rover/safety/confirm.py` | Safety primitive — `SafetyContext`, `register_safe_stop()` |
| `docs/field/001-sensor-location-measurements.md` | Physical measurement needs |

**Gaps:** Exact Z254 dimensions need physical measurement; bypass valve location needs field verification  
**Assumptions:** Hydro-Gear EZT behavior based on standard documentation; wheel RPM at ±200 µs from TRIM estimated <50 RPM

## Phase 3: Semi-automated servo calibration design

**Status:** ✅ Complete  
**Session:** 2026-05-06

### A. Servo Command Mechanism — Critical Design Decision

ArduPilot's `MAV_CMD_DO_SET_SERVO` (command 183) has a critical limitation: for channels with active motor functions (`SERVO1_FUNCTION=73`, `SERVO3_FUNCTION=74`), the motor output library **continuously overwrites** the PWM at ~50 Hz.

**Solution — temporarily disable motor function:**

1. **Before calibration:** `PARAM_SET SERVOn_FUNCTION=0` — removes channel from motor output loop
2. **During calibration:** `MAV_CMD_DO_SET_SERVO` freely — channel accepts and holds commanded PWM
3. **After calibration:** Restore `SERVOn_FUNCTION` to 73 or 74
4. **Safety hook:** `safe_stop_hook` restores original function on any abort/crash/Ctrl+C

### B. Calibration Algorithm — Per Phase

**Phase A — Find Neutral (Engine-Off, Semi-Automated):**
- Command servo to 1500 µs (default center)
- Operator adjusts with +/- keys in 5 µs increments until lever is at mechanical center
- Record as `SERVOn_TRIM`
- *Cannot be fully automated:* ASMC-04A has NO position feedback and NO current feedback

**Phase B — Endpoint Detection (Engine-Off):**
- Sweep from TRIM toward each extreme in 10 µs steps at 5 steps/sec, 200 ms dwell
- Operator presses ENTER when lever reaches physical stop
- Record as `SERVOn_MIN` / `SERVOn_MAX`; determine `REVERSED` from direction mapping
- *Cannot be fully automated:* no stall/current detection available

**Phase C — Deadband Detection (Engine-On, Key Innovation):**

With encoders (`WENC_TYPE != 0`), uses `WHEEL_DISTANCE` MAVLink message (ID 9000):

```python
def detect_deadband(conn, channel, trim, direction, max_offset=200):
    baseline = read_wheel_distance(conn, wheel_index)
    for offset in range(0, max_offset + 1, 5):  # 5 µs steps
        pwm = trim + (direction * offset)
        set_servo(conn, channel, pwm)
        time.sleep(0.4)  # 400 ms dwell for hydrostatic lag
        current = read_wheel_distance(conn, wheel_index)
        if abs(current - baseline) > 0.003:  # 3 mm threshold
            time.sleep(0.2)  # confirmation check
            confirm = read_wheel_distance(conn, wheel_index)
            if abs(confirm - current) > 0.001:  # still moving
                return pwm  # deadband boundary found
        verify_blade_disengaged(conn)
    return None  # no motion within ±200 µs — abort
```

- **Direction:** Always approach from TRIM outward (conservative/wider deadband)
- **Dwell:** 400 ms per step (hydrostatic response lag)
- **Precision:** ±5 µs with encoders (800 counts/rev from CALT GHW38)
- **Without encoders:** Manual fallback — operator watches wheel, presses ENTER. Precision ±10–15 µs.
- **CLI flag:** `--encoder-feedback` (default) vs `--manual-feedback`

**Phase D — Output:**
- Restore `SERVOn_FUNCTION` to 73/74
- Derive `MOT_THR_MIN = ceil(max(all_deadband_pct))` where `deadband_pct = deadband_us / half_range * 100`
- Write calibration profile YAML + metadata JSON
- Show diff, confirm, snapshot pre-apply, apply

### C. ASMC-04A Programmable Endpoints

**Finding: The ASMC-04A has NO programmable endpoints.** No serial interface, no learn button, no current feedback, no position feedback. It is a pure one-way PWM-to-position servo.

**Conclusion:** ArduPilot-side `SERVOn_MIN/MAX` is the **sole** endpoint limiting mechanism. This is simpler and safer — all limits centralized in ArduPilot params, included in snapshot/restore.

### D. Rate Limiting and Abort

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Step size (Phase A/B) | 10 µs | Adequate for visual detection |
| Step size (Phase C) | 5 µs | Precision deadband detection |
| Dwell (Phase A/B) | 200 ms | Mechanical settling only |
| Dwell (Phase C) | 400 ms | Hydrostatic response lag |
| Rate limit | 250 µs/sec max slew | Safety constraint from Phase 2 |
| Hard PWM clamp | [MIN+50, MAX-50] µs | Prevents full-speed wheel spin |
| Deadband sweep limit | ±200 µs from TRIM | Abort if no onset detected |

**Abort conditions:** operator abort (`q`/`Ctrl+C`), idle timeout (30s), blade clutch change, engine stop, encoder fault, MAVLink heartbeat loss, PWM bounds exceeded. All abort paths → immediate return to TRIM + restore `SERVOn_FUNCTION`.

**Laptop disconnect recovery:** With `SERVO_FUNCTION=0`, channel outputs TRIM (safe). On next `mower servo-cal` invocation, detect orphaned function=0 and offer to restore.

### E. Calibration Profile Format

**Profile YAML** (pure ArduPilot params, compatible with `load_param_file()` and `apply_params()`):

```yaml
# servo-calibration.yaml
SERVO1_TRIM: 1498
SERVO1_MIN: 1040
SERVO1_MAX: 1960
SERVO1_REVERSED: 0
SERVO3_TRIM: 1502
SERVO3_MIN: 1035
SERVO3_MAX: 1955
SERVO3_REVERSED: 0
MOT_THR_MIN: 9
```

**Metadata JSON** (companion, NOT loaded by param tooling):

```json
{
  "schema": "mower-rover.servo-calibration.v1",
  "method": "encoder-assisted",
  "left": {
    "channel": 1, "trim_us": 1498, "min_us": 1040, "max_us": 1960,
    "forward_deadband_us": 45, "reverse_deadband_us": 52, "deadband_pct": 8.6
  },
  "right": {
    "channel": 3, "trim_us": 1502, "min_us": 1035, "max_us": 1955,
    "forward_deadband_us": 38, "reverse_deadband_us": 41, "deadband_pct": 7.5
  },
  "derived": { "mot_thr_min": 9 }
}
```

Integrates into existing `PROFILES` dict in `baseline.py`. Enables `mower params apply --profile servo-calibration` and inclusion in `pixhawk-sync` boot enforcement.

### F. Calibration State Machine

```
IDLE → Phase A (Find Neutral, engine-off) → Phase B (Endpoints, engine-off)
     → [session boundary: start engine]
     → Phase C (Deadband, engine-on) → Phase D (Output & Apply)
```

Per-side: calibrate left (SERVO1) then right (SERVO3). Phases A+B for both sides, then Phase C for both sides.

Split-session support: `mower servo-cal --session engine-off` (A+B), `mower servo-cal --session engine-on` (C+D, loads A+B from metadata).

### G. Corrections to Research 001 §5.6

- `MOT_SVEL_LOW` / `MOT_SVEL_HIGH` do NOT exist in ArduPilot Rover — correct param is `MOT_THR_MIN`
- `DO_SET_SERVO` does not work on active motor channels — must use `SERVO_FUNCTION=0` technique

**Key Discoveries:**
- `DO_SET_SERVO` requires `SERVOn_FUNCTION=0` to work on motor channels — critical implementation detail
- ASMC-04A has NO feedback of any kind — only Phase C (deadband) benefits from encoder automation
- `WHEEL_DISTANCE` message enables ±5 µs deadband precision with CALT GHW38 encoders
- `MOT_SVEL_LOW/HIGH` don't exist in Rover — correct param is `MOT_THR_MIN`
- Profile format slots directly into existing `PROFILES` + `apply_params()` infrastructure
- Laptop disconnect is safe: `FUNCTION=0` defaults to TRIM; recovery logic needed on next invocation
- 400 ms dwell time needed per step for reliable hydrostatic onset detection

| File | Relevance |
|------|-----------|
| `src/mower_rover/params/mav.py` | `apply_params()` for PARAM_SET; used for FUNCTION changes |
| `src/mower_rover/params/baseline.py` | `PROFILES` dict; calibration profile registered here |
| `src/mower_rover/params/io.py` | `load_param_file()`, `write_json_snapshot()` |
| `src/mower_rover/safety/confirm.py` | Safety primitive for actuator commands |
| `src/mower_rover/mavlink/connection.py` | `open_link()` for MAVLink connection |
| `docs/research/001-mvp-bringup-rtk-mowing.md` (§5.6) | Original calibration design |

**External Sources:**
- [ArduPilot Wheel Encoder Setup](https://ardupilot.org/rover/docs/wheel-encoder.html) — WHEEL_DISTANCE message

**Gaps:** ASMC-04A detailed datasheet unavailable; WHEEL_DISTANCE behavior cannot be verified in SITL (no encoder sim)  
**Assumptions:** `SERVO_FUNCTION=0` change takes effect without reboot; WHEEL_DISTANCE index 0=left, 1=right; 400 ms dwell sufficient for hydrostatic onset

## Phase 4: Integration with existing tooling

**Status:** ✅ Complete  
**Session:** 2026-05-06

### A. CLI Surface Design

**Module location:** `src/mower_rover/cli/servo_cal.py`, registered in `laptop.py` as:
```python
from mower_rover.cli.servo_cal import app as servo_cal_app
app.add_typer(servo_cal_app, name="servo-cal")
```

**Subcommands:**
- `mower servo-cal run` — main calibration wizard (interactive)
- `mower servo-cal run --session engine-off|engine-on` — split-session support
- `mower servo-cal show` — display current calibration profile
- Standard options: `--port/--endpoint`, `--yes`, root `--dry-run`

**Interactive I/O:** No existing keystroke-by-keystroke pattern in codebase. Safety prompts use `input()`. For real-time PWM nudging (+/- keys), needs `readchar` library (cross-platform, MIT, lightweight) + Rich `Console.status()`/`Live` for display.

### B. Safety Primitive Integration

`SafetyContext.register_safe_stop()` takes `Callable[[], None]`. Servo-cal hook must:
1. Send neutral PWM (TRIM) to SERVO1 and SERVO3
2. Restore `SERVO1_FUNCTION=73` and `SERVO3_FUNCTION=74`

```python
def _make_servo_restore_hook(conn, original_functions):
    def _restore():
        for ch, func in original_functions.items():
            conn.mav.param_set_send(...)  # restore FUNCTION
            conn.mav.command_long_send(... DO_SET_SERVO, ch, 1500 ...)
    return _restore
ctx.register_safe_stop(_make_servo_restore_hook(conn, {1: 73, 3: 74}))
```

**`--dry-run`:** Log calibration plan and PWM commands without sending. Skip `SERVO_FUNCTION=0` and all `DO_SET_SERVO` calls. Optionally write a hypothetical profile to preview format.

**`@requires_confirmation`:** One confirmation at calibration start: "This will take control of SERVO1 and SERVO3 (steering arms will move)".

### C. SITL Smoke-Test Strategy

SITL's `rover-skid` has no encoder simulation — `WHEEL_DISTANCE` not available. Test matrix:

| Test | SITL? | Why |
|------|-------|-----|
| `SERVO_FUNCTION` set to 0 and restore | ✅ | Param round-trip |
| `MAV_CMD_DO_SET_SERVO` send/readback | ✅ | Command protocol |
| Profile YAML generation/loading | ✅ | Pure I/O |
| `params apply --profile servo-calibration` | ✅ | Standard apply flow |
| Safe-stop hook restoring FUNCTION | ✅ | Can verify param restored |
| CLI dry-run path | ✅ | No hardware needed |
| Deadband detection via WHEEL_DISTANCE | ❌ | No encoder sim |
| Physical endpoint detection | ❌ | No physical servo |

**Test structure:**
- `tests/test_servo_cal.py` — unit tests (no SITL)
- `tests/test_servo_cal_sitl.py` — SITL smoke tests (`@pytest.mark.sitl`)
- Encoder/physical tests marked `@pytest.mark.field`

**Mock strategy:** Abstract "wheel motion detector" dependency; inject mock for SITL tests.

### D. Persistence & Snapshot Interaction

**Profile storage options:**
1. Package data (`params/data/`) — read-only after install, won't work for generated profile
2. User data directory (`~/.config/mower-rover/`) — cross-platform via `platformdirs`
3. Project config directory (`config/servo-calibration.yaml`) — git-tracked, matches project philosophy

**Profile loading:** `PROFILES` dict in `baseline.py` uses `importlib.resources` for shipped files. User-generated profiles need either:
- Extended `PROFILES` with filesystem paths
- A `USER_PROFILES` dict alongside `PROFILES`
- Direct path via `mower params apply config/servo-calibration.yaml` (already works)

**Snapshot interaction:** No special handling needed — `fetch_params()` reads ALL params, so `write_json_snapshot()` automatically includes calibrated servo values.

**Metadata JSON:** Companion file alongside profile YAML; NOT loaded by `load_param_file()`. Stores deadband details, method, timestamps.

### E. pixhawk-sync Integration

Current: `DEFAULT_SYNC_PROFILES = ("safety-defaults",)`.

**Servo-calibration must be conditional** — profile may not exist before first calibration. Options:
1. **Graceful skip:** `sync_params()` catches `FileNotFoundError` for optional profiles
2. **Separate optional list:** `OPTIONAL_SYNC_PROFILES` that syncs only if file exists
3. **Auto-discovery:** Scan profiles directory

**Profile ordering:** Servo-calibration must come AFTER baseline (to override default SERVO values):
```python
DEFAULT_SYNC_PROFILES = ("safety-defaults", "servo-calibration")
```

### F. Pre-flight Check Integration

Probe system is **file-based** (`sysroot` Path), NOT MAVLink-based. Existing checks in `src/mower_rover/probe/checks/` all inspect local filesystem/sysfs.

**Recommended check:** `servo_calibration` probe verifying calibration profile file exists:
```python
@register(name="servo_calibration", severity=Severity.WARNING)
def _servo_calibration_probe(sysroot: Path) -> tuple[bool, str]:
    # Check profile file existence on disk
```

Severity `WARNING` (not `CRITICAL`) — can still operate with defaults, but yaw drift expected.

**Key Discoveries:**
- CLI follows existing `add_typer()` pattern; needs `readchar` for interactive keystroke input (new dependency)
- `SafetyContext` hook is zero-arg callable — straightforward for servo restore
- SITL tests cover param round-trips, CLI dry-run, profile generation — NOT encoder deadband
- `PROFILES` dict needs extension for user-generated profiles (currently package-data only)
- `pixhawk-sync` `DEFAULT_SYNC_PROFILES` needs conditional handling for optional profiles
- Probe system is file-based — servo calibration check verifies profile existence, not live params
- `mower params apply <path>` already works for filesystem paths — no code change for manual apply
- `z254_baseline.yaml` already has comments "VERIFY on vehicle (mower servo-cal)" on SERVO params

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/laptop.py` | Root CLI, `add_typer()` pattern |
| `src/mower_rover/cli/params.py` | Actuator-touching CLI pattern |
| `src/mower_rover/safety/confirm.py` | `SafetyContext`, `register_safe_stop()` |
| `src/mower_rover/params/baseline.py` | `PROFILES` dict, `load_profile()` |
| `src/mower_rover/params/io.py` | `load_param_file()`, `write_json_snapshot()` |
| `src/mower_rover/params/mav.py` | `apply_params()`, `fetch_params()` |
| `src/mower_rover/pixhawk/sync.py` | `sync_params()`, `DEFAULT_SYNC_PROFILES` |
| `src/mower_rover/probe/registry.py` | Probe check registration pattern |
| `tests/conftest.py` | SITL fixtures |
| `tests/test_params_sitl.py` | SITL param test pattern |
| `tests/test_safety.py` | Safety primitive tests |

**Gaps:** None  
**Assumptions:** `readchar` is acceptable new dependency; probe system stays file-based

## Phase 5: Field self-tuning via Acro mode + sensor fusion

**Status:** ✅ Complete  
**Session:** 2026-05-07

### A. ArduPilot Acro Mode for Skid-Steer Rover

In Acro mode, ArduPilot's motor mixer is NOT bypassed. The pilot's inputs are translated through two active control loops:

| Stick | Controls | Controller | Current Params |
|-------|----------|------------|----------------|
| Steering | Desired turn rate (deg/s) | ATC_STR_RAT PID+FF | `FF=0.3`, `P=0`, `I=0.9`, `D=0` |
| Throttle | Desired speed (m/s) | ATC_SPEED PID | `P=0.4`, `I=0.3`, `D=0`, `FF=0` |

- Steering stick deflection maps linearly from 0 to `ACRO_TURN_RATE` (currently **180 deg/s**). When the stick returns to neutral, the vehicle **holds heading** (compensating for external drift).
- Throttle stick maps speed via `CRUISE_THROTTLE` (50%) and `CRUISE_SPEED` (2 m/s) as baseline. The ATC_SPEED PID corrects for error between desired and actual speed.
- The motor mixer converts the combined throttle+steering outputs to per-side PWM: `SERVO1_PWM = TRIM1 + throttle_output - steering_output` (left), `SERVO3_PWM = TRIM3 + throttle_output + steering_output` (right), with REVERSED, MIN/MAX clamping, and MOT_THR_MIN deadband applied.

**Acro vs. Manual for calibration:**

| Mode | Speed Control | Steering Control | Best For |
|------|---------------|-------------------|----------|
| **Manual** | Direct RC→PWM passthrough (no PID) | Direct RC→PWM passthrough (no PID) | Learn Cruise (requires Manual), max turn rate measurement, accel/decel tests |
| **Acro** | Closed-loop speed via ATC_SPEED PID | Closed-loop turn rate via ATC_STR_RAT PID+FF | TRIM correction (heading-hold reveals bias), PID response observation |

**Conclusion: The field-tune workflow needs BOTH modes** — Manual for Learn Cruise and raw measurement, Acro for PID observation and TRIM correction.

**ArduPilot's built-in QuikTune (`rover-quicktune.lua`):**

ArduPilot Rover has **QuikTune**, a Lua script that auto-tunes:
1. `ATC_STR_RAT_FF`, then sets P and I as ratios of FF
2. `CRUISE_SPEED` and `CRUISE_THROTTLE`, then sets `ATC_SPEED_P` and I as ratios

QuikTune runs in **Circle mode**, records steering/throttle output and response for ≥10s, and computes gains. Requires: `SCR_ENABLE=1` (reboot), `RTUN_ENABLE=1`, `RCx_OPTION=300` (Scripting1). However, QuikTune does NOT tune: `MOT_THR_MIN`, SERVO TRIM correction, per-side asymmetry, `ACRO_TURN_RATE`, `ATC_STR_RAT_MAX`, or `ATC_ACCEL_MAX`/`ATC_DECEL_MAX`.

**Recommended three-stage calibration pipeline:**

| Stage | Tool | What It Tunes | Mode |
|-------|------|---------------|------|
| 1. Jack-stand calibration | `mower servo-cal run` | SERVO MIN/MAX/TRIM, rough MOT_THR_MIN | Engine-off + engine-on on stand |
| 2. Field tuning | `mower-jetson servo-cal field-tune` | MOT_THR_MIN (field verify), CRUISE_SPEED/THROTTLE, TRIM correction, ACRO_TURN_RATE, ATC_ACCEL_MAX/DECEL_MAX | Manual + Acro |
| 3. PID fine-tuning | QuikTune Lua script | ATC_STR_RAT_FF/P/I, ATC_SPEED_P/I | Circle |

### B. MAVLink Messages for Field Self-Tuning

| Message | ID | Key Fields | Rate | Calibration Use |
|---------|-----|------------|------|-----------------|
| **ATTITUDE** | #30 | `yawspeed` (rad/s) | 50 Hz | Turn rate measurement for ATC_STR_RAT_FF; yaw drift detection for TRIM |
| **GLOBAL_POSITION_INT** | #33 | `vx`, `vy` (cm/s), `lat`, `lon`, `hdg` (cdeg) | 10 Hz | Ground speed (`√(vx²+vy²)/100` m/s); heading; path straightness |
| **GPS_RAW_INT** | #24 | `vel` (cm/s), `cog` (cdeg), `yaw` (cdeg, dual-antenna) | 5 Hz | GPS speed; dual-antenna heading (more accurate than `hdg`); quality gating via `eph` |
| **SERVO_OUTPUT_RAW** | #36 | `servo1_raw`, `servo3_raw` (µs) | 10 Hz | Actual commanded PWM — critical for correlating input→output |
| **RC_CHANNELS** | #65 | `chan1_raw`..`chan18_raw` | 4 Hz | Operator stick inputs — separates operator intent from controller output |
| **VFR_HUD** | #74 | `groundspeed` (m/s), `heading` (deg), `throttle` (%) | 4 Hz | Quick speed/heading readout; `throttle` = controller's output % |
| **WHEEL_DISTANCE** | #9000 | `distance[N]` (meters) | 10 Hz | Per-wheel distance for asymmetry detection (when encoders installed) |
| **SYS_STATUS** | #1 | `voltage_battery` (mV) | 1 Hz | Engine-running detection via alternator voltage (≥13.5V) |
| **HEARTBEAT** | #0 | `base_mode`, `custom_mode` | 1 Hz | Armed state, current mode — safety gating |

**New subscriptions needed:** `ATTITUDE`, `GLOBAL_POSITION_INT`, `RC_CHANNELS`, `WHEEL_DISTANCE` are not currently parsed by any existing module.

### C. Self-Tuning Algorithms

#### C.1. MOT_THR_MIN — Field Deadband Verification

Operator slowly ramps throttle from zero. Service monitors GPS ground speed (`GLOBAL_POSITION_INT.vx/vy`). Detection threshold: groundspeed > 0.15 m/s sustained for 2s (above GPS noise floor ~0.05–0.1 m/s at RTK Fix). Records `VFR_HUD.throttle` at onset → `MOT_THR_MIN = ceil(onset_throttle_pct)`. Data requirement: ~30 seconds of slow ramp.

#### C.2. CRUISE_SPEED / CRUISE_THROTTLE

**Primary method — ArduPilot's built-in "Learn Cruise" (`RCx_OPTION=50`):**
- Assign `RC8_OPTION=50` (RC8 is currently unassigned)
- Operator drives in **Manual mode** at 50–80% throttle on flat terrain
- Flip RC8 switch high for ~5 seconds, then back to low
- ArduPilot auto-updates `CRUISE_SPEED` and `CRUISE_THROTTLE` and sends STATUSTEXT: "Cruise Learned: Thr:XX Speed:YY"
- Service monitors for this STATUSTEXT and logs the learned values

**Secondary method — Jetson-side multi-point mapping:**
Collect 3–5 steady-state segments at different speeds (each ≥5s). Fit linear model: `speed = a * throttle + b`. Total ~60–90 seconds of straight-line driving at varying speeds.

#### C.3. SERVO TRIM Correction — Yaw Drift Detection

**Key insight:** In Acro mode, heading-hold is active — ArduPilot automatically compensates for drift by biasing `SERVO1` vs `SERVO3` output. By measuring the steady-state servo output bias during straight-line driving, we directly observe the TRIM error.

```python
def detect_trim_correction(attitude_log, servo_log, duration_s=30):
    """Measure SERVO output bias during Acro heading-hold straight driving."""
    straight_segments = filter_segments(
        attitude_log, max_yawspeed=0.035,  # ~2 deg/s
        min_speed=1.0,  # must be moving
    )
    for seg in straight_segments:
        offset1 = mean(servo_log.servo1_at(seg)) - SERVO1_TRIM
        offset3 = mean(servo_log.servo3_at(seg)) - SERVO3_TRIM
        # Asymmetry = (offset1 - offset3) / 2 → split correction equally
        trim_correction = (offset1 - offset3) / 2
    return TrimCorrection(
        servo1_trim_delta=round(trim_correction),
        servo3_trim_delta=round(-trim_correction),
    )
```

Data requirement: ≥30 seconds straight-line driving at ≥1 m/s in Acro mode.

#### C.4. ATC_STR_RAT_FF — Steering Rate Feedforward

The Jetson can compute FF from turn response data (compare `ATTITUDE.yawspeed` vs `RC_CHANNELS` steering input × `ACRO_TURN_RATE`). However, **QuikTune does this more accurately** with direct access to internal PID state. Recommendation: Use QuikTune (Stage 3) for FF/PID tuning; the Jetson service validates and measures `ACRO_TURN_RATE` instead.

#### C.5. Left/Right Asymmetry Detection

**With encoders:** Compute per-side speed from `WHEEL_DISTANCE` during straight-line driving. Asymmetry % = `(left_speed - right_speed) / avg_speed * 100`.

**Without encoders:** Use GPS heading drift rate as proxy — detects net effect but cannot attribute to a specific side. The TRIM correction (C.3) corrects the net effect regardless.

#### C.6. Other Field-Tunable Parameters

| Parameter | Method | Data Source | Priority |
|-----------|--------|-------------|----------|
| `ACRO_TURN_RATE` | Max `ATTITUDE.yawspeed` during sharp turns in Manual mode | ATTITUDE 50 Hz | HIGH |
| `ATC_STR_RAT_MAX` | Set equal to `ACRO_TURN_RATE` (ArduPilot recommendation) | Derived | HIGH |
| `ATC_ACCEL_MAX` | Max forward accel from `GLOBAL_POSITION_INT.vx` derivative | GPS 10 Hz | MEDIUM |
| `ATC_DECEL_MAX` | Max deceleration from full speed to stop | GPS 10 Hz | MEDIUM |
| `WP_SPEED` | Set to 70–80% of measured max speed | Derived | LOW |
| `ATC_SPEED_FF` | Leave at 0 (ArduPilot docs: CRUISE baseline replaces FF need) | N/A | SKIP |

### D. Jetson Calibration Service Architecture

**Architecture: CLI command, not persistent service.** The field-tune session is operator-driven, interactive, and finite.

**CLI surface:**
```
mower-jetson servo-cal field-tune [--port UDP_ENDPOINT] [--duration SECONDS] [--output PATH]
```

Runs on the Jetson, connects via `udp:127.0.0.1:14552`. Operator triggers via SSH or laptop:
```bash
ssh vincent@192.168.4.38 "mower-jetson servo-cal field-tune"
```

**Data collection loop:**
```python
class FieldTuneCollector:
    SUBSCRIBED_MESSAGES = {
        "ATTITUDE", "GLOBAL_POSITION_INT", "GPS_RAW_INT",
        "SERVO_OUTPUT_RAW", "RC_CHANNELS", "VFR_HUD",
        "HEARTBEAT", "SYS_STATUS",
        # "WHEEL_DISTANCE" — auto-added when encoders detected
    }
    
    def collect_loop(self, shutdown: threading.Event):
        while not shutdown.is_set():
            msg = self.conn.recv_match(blocking=True, timeout=0.5)
            if msg and msg.get_type() in self.SUBSCRIBED_MESSAGES:
                self.buffer.append(timestamp=time.monotonic(), msg=msg)
```

**State machine:**
```
IDLE → WAITING_FOR_ARM → BASELINE → MANEUVER_SEQUENCE → COMPUTING → REVIEW → APPLYING
                                          ↓
                              DEADBAND_RAMP → LEARN_CRUISE → STRAIGHT_RUN_SLOW →
                              STRAIGHT_RUN_MED → STRAIGHT_RUN_FAST → TURN_LEFT →
                              TURN_RIGHT → FIGURE_EIGHT → ACCEL_TEST → DECEL_TEST
```

**Real-time console output** (Rich Live display via SSH):
```
┌─ Field Tune ──────────────────────────────────┐
│ Mode: ACRO  Armed: YES  Speed: 1.4 m/s       │
│ Yaw Rate: 12.3 deg/s  Heading: 142°          │
│ SERVO1: 1245 µs  SERVO3: 1310 µs             │
│ Throttle: 35%  GPS: RTK Fixed (18 sats)      │
│                                               │
│ Current: STRAIGHT_RUN_MED (2 of 3)            │
│ Instruction: Drive straight at ~2 m/s         │
│ Recording: 8.2s / 10.0s  ████████░░           │
│                                               │
│ Completed: BASELINE ✓, DEADBAND_RAMP ✓        │
│            STRAIGHT_RUN_SLOW ✓                 │
└───────────────────────────────────────────────┘
```

**Data logging:** All raw MAVLink data logged to timestamped JSON (`~/.config/mower-rover/field-tune-YYYYMMDD-HHMMSS.json`) for post-hoc analysis.

### E. RC-Triggered Workflow

**Recommended: Mode transitions + CLI lifecycle (no extra RC switch needed)**

1. Start field-tune CLI on Jetson (via SSH)
2. Arm mower via RC7 (SF switch, `RC7_OPTION=153`)
3. Switch to Manual (SA low) for Learn Cruise + raw measurements
4. Switch to Acro (SA mid) for PID observation + TRIM correction
5. Disarm or switch to Manual when done — CLI detects mode change and saves

**Mode detection via `HEARTBEAT.custom_mode`:**
```python
ROVER_MODE_MANUAL = 0   # MODE1 = SA low
ROVER_MODE_ACRO = 1     # MODE4 = SA mid
ROVER_MODE_AUTO = 10    # MODE6 = SA high
```

**Session lifecycle:**
```
CLI starts → waits for HEARTBEAT (armed=True)
           → begins data collection
           → prompts maneuvers via console
           → operator performs maneuvers (Manual ↔ Acro as guided)
           → operator disarms or CLI detects completion
           → computes results → shows diff → confirms → applies
```

**Optional RC switch enhancement:** `RC8_OPTION=50` (Learn Cruise) during Stage 2, then `RC8_OPTION=300` (Scripting1) for QuikTune in Stage 3. RC8 currently unassigned (`RC8_OPTION=0`).

**Safety on mode switch:**
- Away from Acro: service pauses data collection (not lost)
- E-stop: absolute authority — service detects heartbeat loss, saves partial data
- Switch to Auto during calibration: service warns and pauses

### F. Guided Maneuver Sequence

**Pre-calibration requirements:**
- Stage 1 (stand calibration) complete — SERVO MIN/MAX/TRIM set
- Safety defaults applied — `FENCE_ENABLE=1`, `FENCE_ACTION=2`
- GPS fix: RTK Fixed (fix_type=6) with ≥12 satellites
- Engine running (alternator voltage > 13.5V)
- Open area ≥30m × 30m flat mowed grass

| # | Maneuver | Mode | Duration | Purpose |
|---|----------|------|----------|---------|
| 1 | Stationary baseline | Acro | 10s | Sensor noise floor, IMU bias |
| 2 | Max turn rate | Manual | 15s | Measure ACRO_TURN_RATE |
| 3 | Slow throttle ramp | Acro | 30s | MOT_THR_MIN field verification |
| 4 | Learn Cruise | Manual | 15s | CRUISE_SPEED/THROTTLE via RC8 |
| 5 | Straight run — slow | Acro | 15s | Speed mapping + TRIM |
| 6 | Straight run — medium | Acro | 15s | Speed mapping + TRIM |
| 7 | Straight run — fast | Acro | 15s | Speed mapping + TRIM |
| 8 | Gentle left turns | Acro | 15s | Steering response left |
| 9 | Gentle right turns | Acro | 15s | Steering response right |
| 10 | Figure-8 | Acro | 30s | Asymmetry + turn response |
| 11 | Full throttle accel | Manual | 10s | ATC_ACCEL_MAX |
| 12 | Full brake decel | Manual | 10s | ATC_DECEL_MAX |

**Total estimated time: ~4–5 minutes** (including mode switches and settling).

**Maneuver validation criteria:**
- Straight runs: `mean(speed) > 0.5 m/s`, `std(speed) < 0.3`, `max(|yawspeed|) < 10 deg/s`, ≥50 samples
- Turns: `min(|yawspeed|) > 20 deg/s`, sustained ≥2 seconds
- If a maneuver fails validation: "Please repeat — insufficient data"

### G. Parameter Save and Apply

**Results presentation** (Rich table in terminal):
```
┌─ Field Tune Results ──────────────────────────────────────┐
│  Parameter           Current → Computed    Confidence     │
│  MOT_THR_MIN         0       → 8           HIGH (15 pts) │
│  CRUISE_SPEED        2.0     → 1.8         MED  (7 pts)  │
│  CRUISE_THROTTLE     50      → 45          MED  (7 pts)  │
│  SERVO1_TRIM         1180    → 1183        MED  (6 pts)  │
│  SERVO3_TRIM         1270    → 1268        MED  (6 pts)  │
│  ACRO_TURN_RATE      180     → 142         HIGH (12 pts) │
│  ATC_STR_RAT_MAX     41      → 142         HIGH (12 pts) │
│  ATC_ACCEL_MAX       0.8     → 1.2         LOW  (3 pts)  │
│  ATC_DECEL_MAX       5       → 3.5         LOW  (3 pts)  │
│                                                           │
│  [Apply All]  [Apply High+Medium Only]  [Review Details]  │
└───────────────────────────────────────────────────────────┘
```

**Profile YAML format** (extends Phase 3's servo-calibration.yaml):
```yaml
# field-calibration.yaml — Generated by mower-jetson servo-cal field-tune
MOT_THR_MIN: 8
CRUISE_SPEED: 1.8
CRUISE_THROTTLE: 45
SERVO1_TRIM: 1183
SERVO3_TRIM: 1268
ACRO_TURN_RATE: 142
ATC_STR_RAT_MAX: 142
ATC_ACCEL_MAX: 1.2
ATC_DECEL_MAX: 3.5
```

**Metadata JSON companion** includes per-parameter method, confidence, sample count, and session metadata (GPS quality, surface type, duration).

**Merge strategy with stand calibration:**
- Stand provides: SERVO MIN/MAX, REVERSED (mechanical limits)
- Field updates: SERVO TRIM (refined from observation), MOT_THR_MIN (field-verified)
- Field adds: CRUISE_SPEED/THROTTLE, ACRO_TURN_RATE, ATC_STR_RAT_MAX, ATC_ACCEL/DECEL_MAX
- No conflicts: stand params and field params don't overlap (except TRIM, where field overrides)

**pixhawk-sync integration:**
```python
DEFAULT_SYNC_PROFILES = ("safety-defaults", "servo-calibration", "field-calibration")
# Both calibration profiles optional — sync_params skips if file doesn't exist
```

**Snapshot workflow:** Pre-apply snapshot → diff display → confirm → apply → post-apply snapshot → verify.

### H. Encoder Fallback Analysis

| Algorithm | GPS+IMU Only | With Encoders | Precision Loss |
|-----------|-------------|---------------|----------------|
| MOT_THR_MIN (field) | ✅ GPS threshold 0.15 m/s | ✅ Encoder delta 0.003 m | Adequate — field is verification, not primary |
| CRUISE_SPEED/THROTTLE | ✅ GPS + Learn Cruise | ✅ Same + encoder speed | Negligible |
| SERVO TRIM correction | ✅ Servo output bias in Acro heading-hold | ✅ Same + per-wheel delta | Moderate — detects net drift, not per-side |
| ATC_STR_RAT_FF | ✅ IMU yawspeed (but QuikTune better) | ✅ Same | Negligible |
| Left/right asymmetry | ⚠️ Indirect (heading drift proxy) | ✅ Direct per-wheel comparison | Significant |
| ACRO_TURN_RATE | ✅ IMU yawspeed | ✅ Same | None |
| ATC_ACCEL/DECEL_MAX | ✅ GPS velocity derivative | ✅ Same + encoder | Minor |

**All algorithms work without encoders.** Primary loss: per-side asymmetry quantification (net effect detectable but not attributable). Service auto-detects encoder availability by checking for `WHEEL_DISTANCE` messages within 5 seconds of start.

**Key Discoveries:**
- **Acro mode uses closed-loop speed AND turn rate control** — not passthrough. Heading-hold on stick release reveals TRIM errors as servo output bias.
- **ArduPilot Rover has QuikTune** (`rover-quicktune.lua`) for PID/FF tuning in Circle mode — should be Stage 3 of a three-stage pipeline (stand → field → QuikTune)
- **Field-tune needs BOTH Manual and Acro modes** — Manual for Learn Cruise (`RCx_OPTION=50`) and raw measurements, Acro for PID observation and TRIM
- **RC8 is available** (`RC8_OPTION=0`) for Learn Cruise (option 50) in Stage 2, then reassigned to Scripting1 (option 300) for QuikTune in Stage 3
- **SERVO TRIM correction works by measuring servo output bias** during Acro heading-hold — the controller's compensation directly reveals asymmetry
- **`ATTITUDE.yawspeed` at 50 Hz is the primary turn rate measurement** — more reliable than GPS-derived rates
- **`ATC_SPEED_FF` should be left at 0** — CRUISE_SPEED/CRUISE_THROTTLE baseline replaces the need for speed feed-forward
- **All algorithms work without encoders** (GPS+IMU only) — per-side asymmetry quantification is the only significant loss
- **Total field calibration: ~4–5 minutes**, 12 guided maneuvers, ≥30m × 30m area
- **Field-tune is a CLI command** (`mower-jetson servo-cal field-tune`), not a persistent service

| File | Relevance |
|------|-----------|
| `src/mower_rover/mavlink/connection.py` | `open_link()` — field-tune service uses same pattern |
| `src/mower_rover/cli/detect.py` | `_collect()` — MAVLink message parsing pattern to extend |
| `src/mower_rover/kiosk/telemetry.py` | `mavlink_reader_loop()` — continuous message parsing model |
| `src/mower_rover/kiosk/state.py` | `SharedState` — thread-safe data buffer pattern |
| `src/mower_rover/cli/jetson.py` | Jetson CLI registration — field-tune registers here |
| `src/mower_rover/params/baseline.py` | `PROFILES` dict — add `field-calibration` profile |
| `src/mower_rover/params/mav.py` | `apply_params()`, `fetch_params()` — save/apply workflow |
| `src/mower_rover/safety/confirm.py` | `SafetyContext` — safety hooks for abort |
| `src/mower_rover/vslam/lua_deploy.py` | Lua deploy — needed for QuikTune installation |
| `docs/config/mower.param` | Current params: `ACRO_TURN_RATE=180`, `CRUISE_SPEED=2`, `RC8_OPTION=0` |

**External Sources:**
- [ArduPilot Acro Mode](https://ardupilot.org/rover/docs/acro-mode.html) — steering→turn rate, throttle→speed, heading hold
- [Steering Rate Tuning](https://ardupilot.org/rover/docs/rover-tuning-steering-rate.html) — ATC_STR_RAT PID, FF is primary param
- [Throttle/Speed Tuning](https://ardupilot.org/rover/docs/rover-tuning-throttle-and-speed.html) — CRUISE baseline, Learn Cruise aux, ATC_SPEED_FF=0
- [Rover Tuning Process](https://ardupilot.org/rover/docs/rover-tuning-process.html) — speed first → steering → QuikTune → pivot → navigation
- [QuikTune](https://ardupilot.org/rover/docs/quiktune.html) — Lua auto-tune for STR_RAT_FF/P/I and CRUISE, requires SCR_ENABLE=1
- [RC Auxiliary Functions](https://ardupilot.org/rover/docs/common-auxiliary-functions.html) — Learn Cruise=50, Scripting1=300

**Gaps:** `WHEEL_DISTANCE` index mapping (left=0, right=1?) needs field verification; QuikTune behavior on skid-steer not verified; whether `GCS_PID_MASK` streaming works over UDP to Jetson companion  
**Assumptions:** GPS noise floor ~0.05–0.1 m/s at RTK Fix; `ATTITUDE.yawspeed` 50 Hz sufficient; Learn Cruise works on Rover 4.6.3 skid-steer; RC8 physical switch exists and is accessible on Taranis X9D Plus

## Overview

This research resolved two blockers for the path to first autonomous mowing: failsafe defaults correction and servo calibration design, including a **three-stage calibration pipeline** from jack-stand rough values through field self-tuning to PID auto-tune.

**Failsafe defaults** (Phase 1): The live Pixhawk has 5 of 6 safety-defaults params misconfigured — `FENCE_ENABLE=0`, `FENCE_ACTION=1` (RTL), `FS_EKF_ACTION=1` (RTL), `FS_GCS_ENABLE=0`, and `ARMING_CHECK=0`. Only `FS_ACTION=2` already matches. The `FS_GCS_TIMEOUT` blocker from research 030 has already been resolved (removed from profile). Applying `safety-defaults` via procedure 006 is safe: the circle fence at 300 m will be the sole containment boundary until polygon fences are uploaded per-zone. Procedure 006 needs a minor doc update ("seven" → "six" keys).

**Stand/lift safety** (Phase 2): The Z254 at ~518 lbs exceeds most consumer mower lift capacities. Jack stands (~$40–80) are an acceptable and practical option for Stage 1 rough calibration. The hydrostatic transmission is engine-dependent: no wheel response without engine running. This drives a split-session stand calibration: engine-off for mechanical phases (neutral/endpoints), engine-on for deadband detection.

**Stand calibration algorithm** (Phase 3): Only Phase C (deadband detection) benefits from encoder automation. Phases A (neutral) and B (endpoints) remain operator-interactive because the ASMC-04A servo has no position or current feedback. The `WHEEL_DISTANCE` MAVLink message with CALT GHW38 encoders (800 counts/rev) enables ±5 µs deadband precision. A critical implementation detail: `MAV_CMD_DO_SET_SERVO` does not work on channels with active motor functions — must temporarily set `SERVOn_FUNCTION=0` during calibration.

**Tooling integration** (Phase 4): The calibration CLI slots cleanly into the existing Typer structure as `mower servo-cal`. The safety primitive (`SafetyContext`, `register_safe_stop`, `@requires_confirmation`) covers all abort/restore needs. SITL testing covers param round-trips, CLI dry-run, and profile generation but NOT encoder-based deadband.

**Field self-tuning** (Phase 5): After jack-stand rough values, the operator drives in the field using RC (Taranis X9D Plus) while a Jetson-side CLI command (`mower-jetson servo-cal field-tune`) monitors MAVLink sensor data in real-time. The workflow uses **both Manual and Acro modes**: Manual for ArduPilot's built-in Learn Cruise function and raw measurements, Acro for PID response observation and SERVO TRIM correction (Acro's heading-hold reveals left/right asymmetry as servo output bias). A guided sequence of 12 maneuvers (~4–5 minutes) tunes `MOT_THR_MIN`, `CRUISE_SPEED/THROTTLE`, `SERVO_TRIM`, `ACRO_TURN_RATE`, `ATC_STR_RAT_MAX`, and `ATC_ACCEL/DECEL_MAX`. All algorithms work without encoders (GPS+IMU only). ArduPilot's **QuikTune Lua script** (`rover-quicktune.lua`) handles Stage 3 PID fine-tuning (`ATC_STR_RAT_FF/P/I`, `ATC_SPEED_P/I`) in Circle mode — complementing, not replacing, the Jetson field-tune service.

## Key Findings

1. **5 of 6 safety-defaults params need correction** on the live Pixhawk — procedure 006 is ready to execute (update doc from "seven" to "six" keys first)
2. **`FENCE_ENABLE=1` is safe without polygon fence** — circle fence at 300 m is enforced; polygon is uploaded per-zone via `mower zone select`
3. **Three-stage calibration pipeline:** (1) jack-stand rough SERVO MIN/MAX/TRIM, (2) Jetson field-tune for CRUISE/TRIM/deadband/dynamics, (3) QuikTune Lua for PID/FF gains
4. **Hydrostatic transmission requires engine for wheel response** — stand calibration splits into engine-off (mechanical) and engine-on (deadband) sessions
5. **ASMC-04A has no feedback** — only deadband detection (Phase C) benefits from encoder automation on the stand
6. **`DO_SET_SERVO` requires `SERVO_FUNCTION=0`** — channels with active motor functions (73/74) are overwritten at 50 Hz
7. **`MOT_SVEL_LOW/HIGH` don't exist in Rover** — correct deadband param is `MOT_THR_MIN`
8. **Acro mode uses closed-loop speed AND turn rate control** — heading-hold on stick release reveals TRIM errors as servo output bias
9. **ArduPilot's QuikTune Lua script** tunes ATC_STR_RAT_FF/P/I and CRUISE values in Circle mode — complements but doesn't replace the Jetson field-tune service
10. **Field-tune needs BOTH Manual and Acro modes** — Manual for Learn Cruise (`RCx_OPTION=50`) and raw measurements, Acro for PID observation and TRIM
11. **All field-tune algorithms work without encoders** (GPS+IMU only) — per-side asymmetry quantification is the only significant loss
12. **Total field calibration: ~4–5 minutes** for 12 guided maneuvers in ≥30m × 30m area
13. **RC8 is available** for Learn Cruise (option 50) during field-tune, then reassignable to Scripting1 (option 300) for QuikTune
14. **Encoders not yet wired** (`WENC_TYPE=0`) — CLI must support both encoder-automated and GPS+IMU-only modes
15. **`FS_TIMEOUT=1.5s` is shared RC/GCS timeout** on 4.6.3 — changing requires field validation

## Actionable Conclusions

1. **Execute procedure 006** to apply safety-defaults to the live Pixhawk (after updating doc: "seven" → "six")
2. **Use jack stands** for Stage 1 stand calibration of SERVO MIN/MAX/TRIM + rough deadband
3. **Implement `mower servo-cal run`** (laptop) for jack-stand calibration with split-session support and dual encoder/manual modes
4. **Implement `mower-jetson servo-cal field-tune`** (Jetson) for field self-tuning with guided 12-maneuver sequence, real-time sensor fusion, and confidence-rated parameter computation
5. **Deploy QuikTune** as Stage 3: `rover-quicktune.lua` via `mower-jetson pixhawk lua-deploy` with `SCR_ENABLE=1`, `RTUN_ENABLE=1`, `RC8_OPTION=300`
6. **Assign `RC8_OPTION=50`** (Learn Cruise) for field-tune Stage 2; reassign to `RC8_OPTION=300` (Scripting1) for QuikTune Stage 3
7. **Add `readchar`** as a dependency for interactive stand-calibration keystroke input
8. **Extend `PROFILES` and `pixhawk-sync`** for optional `servo-calibration` and `field-calibration` profiles
9. **Use `SERVO_FUNCTION=0` technique** for direct servo control during stand calibration
10. **Add `servo_calibration` probe check** (WARNING severity) verifying profile file exists
11. **Mark field-dependent tests** with `@pytest.mark.field`; SITL tests cover param round-trips and dry-run only

## Open Questions

- Does `PARAM_SET SERVOn_FUNCTION=0` take effect without reboot on Cube Orange Rover 4.6.3? (needs field verification)
- Does changing `SERVO_FUNCTION` from 73→0 cause a brief PWM glitch? (if so, engine must be off during transition)
- What is the correct `FS_TIMEOUT` value? 1.5s default may be too aggressive for GCS failsafe but appropriate for RC (needs field testing)
- Should `FENCE_TYPE=7` (adding altitude bit) and `FENCE_RADIUS=200` be added to safety-defaults or kept as zone config?
- `WHEEL_DISTANCE` message wheel index mapping (0=left, 1=right) — needs field verification when encoders are installed
- Optimal hydrostatic dwell time for deadband detection — 400 ms is estimated, may need field tuning
- Which physical switch on the Taranis X9D Plus maps to RC channel 8? (need most ergonomic unassigned switch)
- Does QuikTune Lua work correctly on skid-steer vehicles? (docs show general Rover, skid-steer-specific quirks may exist)
- Does `GCS_PID_MASK` PID streaming work over UDP to the Jetson companion, or only to traditional GCS?
- GPS velocity noise floor at RTK Fix in the actual 4-acre yard — determines MOT_THR_MIN detection threshold accuracy
- Should QuikTune deployment be integrated into `mower-jetson pixhawk lua-deploy` or exposed as `mower servo-cal quicktune`?

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-06 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/031-failsafe-fix-and-servo-calibration.md |
