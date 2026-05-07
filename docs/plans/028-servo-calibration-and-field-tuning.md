---
id: "028"
type: plan
title: "Servo Calibration (Jack-Stand Rough Cal) & Open-Field Tuning"
status: ✅ Ready for Implementation
created: "2026-05-07"
updated: "2026-05-07"
owner: pch-planner
version: v2.1
vision_source: /docs/vision/001-zero-turn-mower-rover.md
research_source: /docs/research/031-failsafe-fix-and-servo-calibration.md
target_release: 1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-07 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-05-07 | pch-planner | Scope decision: full pipeline (Stages 1-3) |
| v1.2 | 2026-05-07 | pch-planner | Input method: RC passthrough for Phases A/B |
| v1.3 | 2026-05-07 | pch-planner | Profile storage: dual config/ + /etc/mower/ |
| v1.4 | 2026-05-07 | pch-planner | Field-tune CLI: Jetson-only |
| v1.5 | 2026-05-07 | pch-planner | Record signal: RC8 + Enter dual |
| v2.0 | 2026-05-07 | pch-planner | Holistic review + full execution plan (7 phases) |
| v2.1 | 2026-05-07 | pch-plan-reviewer | Review: 7 issues resolved, all decisions documented |

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 7
**Last Updated:** 2026-05-07

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | `sync_params()` PROFILES dict guard blocks filesystem-based optional profiles | Correctness | Option B: Split loops — mandatory profiles use existing PROFILES guard, optional profiles use separate loop with `load_profile()` + `KeyError`/`FileNotFoundError` → warning | Step 3.2, pixhawk-sync Integration updated |
| 2 | Lua deploy standalone command doesn't exist | Correctness | Option A: Refactor `check_and_deploy_lua()` into generic `deploy_lua_script(conn, local_path, remote_path)` | Phase 7, Dependencies, Module Layout updated |
| 3 | `rover-quicktune.lua` source URL/version unspecified | Specificity | Option A: Pin to ArduPilot Rover-4.6.3 tag for API compatibility | Step 7.2 updated |
| 4 | `RecordSignal._input_waiter` spawns orphan daemon threads | Correctness | Option A: Single long-lived `input()` thread with `_listening` gate | RecordSignal pseudocode updated |
| 5 | Phase A "left stick" has no RC channel mapping reference | Clarity | Option C: Both mapping table AND live RC verification step; display on laptop CLI (Rich console) | Stand Calibration Flow updated |
| 6 | Field-tune data logging path unspecified | Completeness | Option A: `/var/log/mower/field-tune-YYYYMMDD-HHMMSS.json` | Steps 5.1, 5.5 updated |
| 7 | No `DO_SET_SERVO` helper in codebase | Completeness | Option A: Inline pymavlink call pattern in Technical Design, no new helper | Phase C, Step 1.5 updated |

## Introduction

This plan implements the `mower servo-cal` CLI command for rough servo calibration using jack stands (Phase C deadband uses manual observation since encoders are not yet wired), followed by open-field driving tests to validate and refine calibration values. It directly implements the design from research 031 — covering the safety-primitive-wrapped CLI wizard, profile generation, `pixhawk-sync` integration for optional profiles, and a field-tuning workflow for iterative refinement.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Scope: which stages to include | C — Full pipeline (Stages 1, 2, & 3) | Implement stand calibration, Jetson field-tune, AND QuikTune Lua deployment. Stage 3 is minimal custom code (deploy script + param setup) so inclusion cost is low. Provides complete end-to-end calibration from zero to tuned PID. |
| 2 | Interactive input for Phases A/B | B — RC passthrough (stick drives servo, CLI monitors + records) | Set `SERVOn_FUNCTION=51/53` (RC passthrough) for Phases A+B. Taranis stick drives servo directly with zero latency; CLI reads `SERVO_OUTPUT_RAW` and records on operator signal (RC8 switch or Enter key). Phase C (deadband) still uses `FUNCTION=0` + `DO_SET_SERVO` for ±5 µs precision. No new dependency. Natural UX — operator holds transmitter and watches arm move. |
| 3 | Calibration profile storage location | D — Dual: `config/` for git tracking + `/etc/mower/` on Jetson for pixhawk-sync | Write profiles to `config/servo-calibration.yaml` and `config/field-calibration.yaml` (git-trackable, visible in workspace). Bringup deploys to `/etc/mower/` on Jetson. `load_profile()` extended to check filesystem paths. Avoids `platformdirs` dependency. Matches `config/taranis/` pattern. |
| 4 | Field-tune CLI location | A — Jetson only (`mower-jetson servo-cal field-tune`) | Field-tune subscribes to 8+ MAVLink message types at up to 50 Hz — SiK radio bandwidth would saturate. Jetson connects via local UDP to MAVProxy with no bandwidth limit. Operator SSHes in; Rich Live display over SSH is proven. Stand cal stays on laptop (`mower servo-cal`); field-tune on Jetson (`mower-jetson servo-cal`). |
| 5 | Record signal for Phases A/B | C — Both: RC8 switch primary + Enter key fallback | RC8 switch toggle gives hands-free field UX (operator stays at mower with transmitter). Enter key fallback ensures CLI works in SITL and `--dry-run`. Background thread polls `RC_CHANNELS` for RC8 edge; main thread blocks on `input()`. Whichever fires first triggers recording. RC8 confirmed unassigned (`RC8_OPTION=0`). |

## Holistic Review

### Decision Interactions

1. **RC passthrough (Q2) + RC8 record signal (Q5):** These interact well. During Phases A/B, `SERVOn_FUNCTION=51/53` puts the channel in RC passthrough — the stick drives the servo AND `RC_CHANNELS` is available for RC8 monitoring. No conflict; both use the RC system simultaneously but for independent channels.

2. **RC passthrough (Q2) + Phase C deadband:** Phase C switches to `FUNCTION=0` + `DO_SET_SERVO` for ±5 µs precision. This is a clean phase boundary — passthrough for coarse positioning (A/B), programmatic for precision (C). The safe-stop hook must handle BOTH states: restore to `FUNCTION=73/74` regardless of whether the current phase was using `51/53` or `0`.

3. **Dual storage (Q3) + Jetson field-tune (Q4):** Field-tune writes directly to `/etc/mower/field-calibration.yaml` on the Jetson. The operator must `scp` or use `mower jetson` SSH transport to pull the file back to `config/` for git tracking. This is a manual step — document it clearly in the CLI output.

4. **Full pipeline (Q1) + QuikTune (Stage 3):** QuikTune reuses `RC8_OPTION` — but Stage 2 field-tune also uses RC8 for Learn Cruise (`RC8_OPTION=50`). These are sequential (not concurrent), so RC8 is reassigned between stages: `50` during field-tune → `300` for QuikTune. The field-tune CLI should set `RC8_OPTION=50` at start and document the Stage 3 reassignment.

### Architectural Considerations

- **Two `SERVO_FUNCTION` state transitions per calibration session:** `73→51` (passthrough, Phase A/B), then `51→0` (direct control, Phase C), then `0→73` (restore). Each transition needs verification that ArduPilot applies it without reboot. Research 031 flags this as an open question — mark as field-verification-required.
- **Thread safety in dual-signal recording:** Background RC8 polling thread and foreground `input()` thread both write to a shared "record triggered" flag. Use `threading.Event` — no lock contention, race-free.
- **SiK bandwidth for stand calibration:** Stand cal runs on the laptop via SiK radio. Message volume is low (only `SERVO_OUTPUT_RAW` at ~10 Hz + `RC_CHANNELS` at ~4 Hz during monitoring). Well within SiK capacity.

### Trade-offs Accepted

- **Manual `scp` for field-calibration profile:** Operator must pull the Jetson-generated profile to the laptop for git tracking. Automating this was considered unnecessary complexity for a one-time operation.
- **No encoder-assisted deadband:** Encoders not wired (`WENC_TYPE=0`). Phase C uses manual observation (operator watches wheel, presses Enter/RC8). Precision ±10–15 µs instead of ±5 µs. Acceptable for initial calibration; field-tune Stage 2 refines TRIM further.
- **`SERVO_FUNCTION` change without reboot:** Unverified assumption. If field testing shows a reboot is required, the calibration workflow becomes: set `FUNCTION=51` → reboot → Phase A/B → set `FUNCTION=0` → reboot → Phase C → restore → reboot. This would significantly slow calibration but is functional.

### Risks Acknowledged

- `PARAM_SET SERVOn_FUNCTION` may require reboot (field-verify before first use)
- RC8 switch physical location on Taranis X9D Plus unknown (operator must identify)
- `WHEEL_DISTANCE` index mapping unverified (not blocking — encoders not wired)
- Hydrostatic dwell time (400 ms) is estimated — may need field adjustment

## Overview

### Objectives

**Stage 1 — Jack-Stand Calibration (laptop-side):**
1. Implement `mower servo-cal run` CLI wizard — interactive, jack-stand-based, engine-on rough calibration (manual observation mode since `WENC_TYPE=0`)
2. Implement `mower servo-cal run --session engine-off|engine-on` — split-session support
3. Implement `mower servo-cal show` — display current calibration profile
4. Generate `servo-calibration.yaml` profile + `servo-calibration-meta.json` companion
5. Extend `PROFILES` / `pixhawk-sync` for optional user-generated profiles
6. Add `servo_calibration` probe check (WARNING severity)

**Stage 2 — Field Tuning (Jetson-side):**
7. Implement `mower-jetson servo-cal field-tune` — guided 12-maneuver sequence with real-time MAVLink sensor fusion
8. Real-time Rich Live console display over SSH showing telemetry + maneuver instructions
9. TRIM correction via Acro heading-hold servo output bias detection
10. ArduPilot Learn Cruise integration (`RC8_OPTION=50`)
11. Generate `field-calibration.yaml` profile + metadata JSON

**Stage 3 — QuikTune PID Auto-Tune:**
12. Deploy `rover-quicktune.lua` via `mower-jetson pixhawk lua-deploy`
13. Set `SCR_ENABLE=1`, `RTUN_ENABLE=1`, `RC8_OPTION=300` (Scripting1)
14. Document QuikTune usage procedure

**Cross-cutting:**
15. SITL smoke tests covering param round-trips, CLI dry-run, and profile I/O

### Non-Goals

- Encoder-automated deadband detection (encoders not wired; `WENC_TYPE=0`)
- Roller-stand fabrication (using existing jack stands)
- Full PID / navigation tuning (that's field-dependent, post-calibration)
- Modifying ArduPilot firmware

## Requirements

### Functional

- FR-1: `mower servo-cal run` — multi-phase interactive wizard (neutral, endpoints, deadband)
- FR-2: `mower servo-cal run --session engine-off` — phases A+B only (mechanical)
- FR-3: `mower servo-cal run --session engine-on` — phase C+D only (loads A+B from prior metadata)
- FR-4: `mower servo-cal show` — pretty-print current calibration profile
- FR-5: `mower servo-cal field-tune` — load profile, nudge values interactively, re-save
- FR-6: Profile persistence as `config/servo-calibration.yaml` + metadata JSON
- FR-7: Profile auto-sync via `pixhawk-sync` (conditional — skips if file absent)
- FR-8: `servo_calibration` probe check (file existence, WARNING)
- FR-9: `--dry-run` mode logs all commands without sending

### Non-Functional

- NFR-1: Safety primitive wraps all actuator commands
- NFR-2: Safe-stop hook restores `SERVOn_FUNCTION` on abort/crash/Ctrl+C
- NFR-3: Hard PWM clamp [MIN+50, MAX-50] µs during sweeps
- NFR-4: Rate limit ≤250 µs/sec slew during calibration
- NFR-5: Blade clutch interlock verified before engine-on phase
- NFR-6: Cross-platform (Windows laptop ↔ Jetson/MAVLink connection)
- NFR-7: Structured logging with correlation IDs

### Out of Scope

- Encoder-feedback automation (future, when CALT GHW38 wired)
- `readchar` keystroke dependency (not needed — RC passthrough for Phases A/B, `input()` for Phase C prompts)
- Roller stand design/fabrication
- PID tuning commands
- RTK-specific tuning

## Technical Design

### Architecture Overview

The calibration system spans two CLI surfaces with shared library code:

```
Laptop (mower servo-cal)          Jetson (mower-jetson servo-cal)
├── run (stand calibration)       ├── field-tune (sensor-fusion cal)
│   ├── Phase A: Find Neutral     │   ├── Guided 12-maneuver sequence
│   │   (RC passthrough + RC8)    │   ├── Real-time MAVLink monitoring
│   ├── Phase B: Endpoints        │   ├── Learn Cruise (RC8_OPTION=50)
│   │   (RC passthrough + RC8)    │   ├── TRIM correction (Acro mode)
│   ├── Phase C: Deadband         │   └── Profile generation
│   │   (DO_SET_SERVO + manual)   └── quicktune (Stage 3 setup)
│   └── Phase D: Output/Apply         ├── Deploy rover-quicktune.lua
└── show (display profile)             └── Set SCR_ENABLE, RTUN_ENABLE
```

### Module Layout

| Module | Location | Side |
|--------|----------|------|
| Stand calibration CLI | `src/mower_rover/cli/servo_cal.py` | Laptop |
| Stand calibration engine | `src/mower_rover/calibration/stand.py` | Shared |
| RC monitor (RC8 edge + SERVO_OUTPUT_RAW) | `src/mower_rover/calibration/rc_monitor.py` | Shared |
| Deadband sweep engine | `src/mower_rover/calibration/deadband.py` | Shared |
| Profile I/O (YAML + metadata JSON) | `src/mower_rover/calibration/profile.py` | Shared |
| Field-tune CLI | `src/mower_rover/cli/servo_cal_jetson.py` | Jetson |
| Field-tune data collector | `src/mower_rover/calibration/field_tune.py` | Jetson |
| Field-tune algorithms | `src/mower_rover/calibration/algorithms.py` | Jetson |
| QuikTune setup CLI | `src/mower_rover/cli/servo_cal_jetson.py` | Jetson |
| Generic Lua FTP deploy | `src/mower_rover/vslam/lua_deploy.py` (refactored) | Shared |
| Probe check | `src/mower_rover/probe/checks/servo_cal.py` | Jetson |

### Stand Calibration Flow (Phases A–D)

**Expected RC Channel → Stick Mapping (Taranis X9D Plus, config in `config/taranis/`):**

| RC Channel | Taranis Axis/Switch | ArduPilot Use | Passthrough Function |
|------------|---------------------|---------------|---------------------|
| RC1 | Right stick X (roll) | Steering | `SERVO1_FUNCTION=51` (RCPassThru1) → left lever |
| RC3 | Right stick Y (throttle) | Throttle | `SERVO3_FUNCTION=53` (RCPassThru3) → right lever |
| RC8 | SD switch (2-pos) | Record signal | `RC8_OPTION=0` (unassigned, used for recording) |

> **Verify from `config/taranis/RADIO/` export before implementation.** If the Taranis config uses a different channel assignment, update this table.

**Pre-Phase A — Stick Verification (laptop CLI, Rich console):**

Before recording begins, the CLI displays all 8 RC channels live (from `RC_CHANNELS` at ~4 Hz) on the laptop terminal. The operator moves each stick/switch to confirm which channel responds. This catches any Taranis reconfiguration. Display stays visible for ~10 seconds or until the operator presses Enter to proceed.

**Phase A — Find Neutral (RC Passthrough):**
1. `PARAM_SET SERVO1_FUNCTION=51` (RCPassThru1)
2. CLI monitors `SERVO_OUTPUT_RAW.servo1_raw` at ~10 Hz, displays live PWM on laptop terminal
3. Operator adjusts steering stick (RC1, see mapping above) on Taranis until lever is at mechanical center
4. Operator signals "record" via RC8 switch toggle or Enter key
5. CLI records `servo1_raw` as `SERVO1_TRIM` candidate
6. Repeat for SERVO3 (set `SERVO3_FUNCTION=53`)

**Phase B — Endpoint Detection (RC Passthrough):**
1. Same passthrough mode as Phase A
2. Operator pushes stick to full forward → record as `SERVOn_MAX`
3. Operator pushes stick to full reverse → record as `SERVOn_MIN`
4. Determine `SERVOn_REVERSED` from direction mapping (stick forward = lever forward)
5. Both sides sequentially

**Phase C — Deadband Detection (Engine-On, Programmatic):**
1. `PARAM_SET SERVOn_FUNCTION=0` (disable motor output)
2. `MAV_CMD_DO_SET_SERVO` sweeps from TRIM outward in 10 µs steps, 400 ms dwell. Inline pymavlink call pattern (no helper — single callsite in `deadband.py`):
   ```python
   from pymavlink import mavutil
   conn.mav.command_long_send(
       conn.target_system, conn.target_component,
       mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
       0,        # confirmation
       channel,  # param1: servo channel (1 or 3)
       pwm,      # param2: PWM µs
       0, 0, 0, 0, 0,  # params 3–7 unused
   )
   ```
3. Operator watches wheel, presses Enter/RC8 when rotation begins
4. Record PWM at onset → `forward_deadband_us`, `reverse_deadband_us`
5. Derive `MOT_THR_MIN = ceil(max(deadband_pct_left, deadband_pct_right))`

**Phase D — Output & Apply:**
1. Restore `SERVOn_FUNCTION` to 73/74
2. Generate `config/servo-calibration.yaml` (ArduPilot params)
3. Generate `config/servo-calibration-meta.json` (method, deadband details, timestamps)
4. Show diff vs. current Pixhawk values
5. Confirm → snapshot → apply → verify

### Safe-Stop Hook Design

```python
def _make_cal_restore_hook(
    conn, original_functions: dict[int, int]
) -> Callable[[], None]:
    """Return hook that restores SERVO functions on abort."""
    def _restore() -> None:
        for channel, func in original_functions.items():
            try:
                apply_params(
                    conn,
                    ParamSet.from_mapping(
                        {f"SERVO{channel}_FUNCTION": func}
                    ),
                )
            except Exception:
                pass  # best-effort on abort
    return _restore
```

Registered at calibration start: `ctx.register_safe_stop(_make_cal_restore_hook(conn, {1: 73, 3: 74}))`. The hook restores motor functions regardless of which phase was interrupted.

### RC8 Dual-Signal Recording

```python
class RecordSignal:
    """Waits for RC8 toggle OR Enter key, whichever comes first."""
    
    def __init__(self, conn):
        self._triggered = threading.Event()
        self._listening = False  # gate: ignore input/RC8 between recordings
        self._conn = conn
        self._rc8_thread: threading.Thread | None = None
        self._input_thread: threading.Thread | None = None
    
    def start_monitoring(self) -> None:
        """Start both long-lived daemon threads (call once at session start)."""
        self._rc8_thread = threading.Thread(
            target=self._poll_rc8, daemon=True
        )
        self._rc8_thread.start()
        self._input_thread = threading.Thread(
            target=self._input_loop, daemon=True
        )
        self._input_thread.start()
    
    def wait_for_record(self, prompt: str = "Press Enter or flip RC8") -> None:
        self._listening = True
        self._triggered.clear()
        self._triggered.wait()  # blocks until either source fires
        self._listening = False
    
    def _poll_rc8(self) -> None:
        prev_high = False
        while True:
            msg = self._conn.recv_match(
                type="RC_CHANNELS", blocking=True, timeout=0.5
            )
            if msg:
                high = msg.chan8_raw > 1500
                if high and not prev_high and self._listening:  # rising edge + listening
                    self._triggered.set()
                prev_high = high
    
    def _input_loop(self) -> None:
        """Single long-lived thread: loops on input(), gated by _listening."""
        while True:
            input()
            if self._listening:
                self._triggered.set()
```

### Field-Tune Data Collector

Subscribes to MAVLink messages via `conn.recv_match()` in a dedicated thread. Uses `threading.Lock`-protected circular buffer (last 300s of data). Key message types:

| Message | Rate | Fields Used |
|---------|------|-------------|
| `ATTITUDE` | 50 Hz | `yawspeed` |
| `GLOBAL_POSITION_INT` | 10 Hz | `vx`, `vy`, `lat`, `lon`, `hdg` |
| `GPS_RAW_INT` | 5 Hz | `vel`, `cog`, `eph`, `fix_type` |
| `SERVO_OUTPUT_RAW` | 10 Hz | `servo1_raw`, `servo3_raw` |
| `RC_CHANNELS` | 4 Hz | `chan1_raw`–`chan9_raw` |
| `VFR_HUD` | 4 Hz | `groundspeed`, `heading`, `throttle` |
| `HEARTBEAT` | 1 Hz | `base_mode`, `custom_mode` |
| `SYS_STATUS` | 1 Hz | `voltage_battery` |

### Field-Tune Algorithms

Per research 031 Phase 5, Section C:

- **MOT_THR_MIN:** Slow throttle ramp → detect GPS groundspeed > 0.15 m/s sustained 2s → record throttle %
- **CRUISE_SPEED/THROTTLE:** ArduPilot Learn Cruise (`RC8_OPTION=50`) in Manual mode
- **SERVO TRIM correction:** Measure servo output bias during Acro heading-hold straight driving (≥30s at ≥1 m/s)
- **ACRO_TURN_RATE:** Max `ATTITUDE.yawspeed` during sharp turns in Manual mode
- **ATC_STR_RAT_MAX:** Set equal to measured `ACRO_TURN_RATE`
- **ATC_ACCEL_MAX / ATC_DECEL_MAX:** GPS velocity derivative during accel/decel maneuvers

### QuikTune Setup (Stage 3)

1. Deploy `rover-quicktune.lua` to Pixhawk via existing `mower-jetson pixhawk lua-deploy`
2. `PARAM_SET SCR_ENABLE=1` (requires reboot)
3. `PARAM_SET RTUN_ENABLE=1`
4. `PARAM_SET RC8_OPTION=300` (Scripting1 — reassigned from Learn Cruise)
5. Document Circle-mode procedure for operator

### Profile Formats

**`config/servo-calibration.yaml`** (ArduPilot params, compatible with `load_param_file()`):
```yaml
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

**`config/servo-calibration-meta.json`** (companion, NOT loaded by param tooling):
```json
{
  "schema": "mower-rover.servo-calibration.v1",
  "created_at": "2026-05-10T14:30:00Z",
  "method": "manual-observation",
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

**`/etc/mower/field-calibration.yaml`** (Jetson-generated, pulled to `config/` for git):
```yaml
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

### pixhawk-sync Integration

```python
DEFAULT_SYNC_PROFILES: tuple[str, ...] = ("safety-defaults",)
OPTIONAL_SYNC_PROFILES: tuple[str, ...] = ("servo-calibration", "field-calibration")
```

`sync_params()` uses a **split-loop design** (per review decision Q1):

1. **First loop (mandatory):** Iterates `DEFAULT_SYNC_PROFILES` using the existing `PROFILES` dict guard (`if name not in PROFILES: error`). No changes to existing code.
2. **Second loop (optional):** Iterates `OPTIONAL_SYNC_PROFILES` after the mandatory loop. Calls `load_profile(name)` directly (which checks filesystem paths per Step 3.1). Catches `KeyError`/`FileNotFoundError` with a warning log + skip — missing optional profiles are not errors.
3. **Merge order:** Mandatory profiles first, then optional. Later profiles override earlier. Combined `desired` ParamSet continues through the existing diff → apply flow.

This preserves the existing validation for shipped mandatory profiles while cleanly adding optional filesystem-based profiles.

### `load_profile()` Extension

Extend `load_profile(name)` in `baseline.py` to check filesystem paths before `PROFILES` dict:

1. Check `/etc/mower/{name}.yaml` (Jetson)
2. Check `config/{name}.yaml` (laptop, relative to CWD)
3. Fall back to `PROFILES[name]` (package data)
4. Raise `KeyError` if none found

### Probe Check

```python
# src/mower_rover/probe/checks/servo_cal.py
@register(name="servo_calibration", severity=Severity.WARNING)
def _servo_calibration_probe(sysroot: Path) -> tuple[bool, str]:
    cal_path = sysroot / "etc" / "mower" / "servo-calibration.yaml"
    if cal_path.exists():
        return True, f"Servo calibration profile found: {cal_path}"
    return False, "No servo calibration profile — run 'mower servo-cal run'"
```

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Typer sub-app registration
    location: "src/mower_rover/cli/laptop.py"
    usage: Register servo_cal_app via add_typer()
  - pattern: Safety primitive (SafetyContext + @requires_confirmation)
    location: "src/mower_rover/safety/confirm.py"
    usage: Wrap all actuator-touching calibration commands
  - pattern: Params apply flow (snapshot → diff → confirm → apply)
    location: "src/mower_rover/cli/params.py"
    usage: Profile apply at end of calibration
  - pattern: MAVLink param fetch/set
    location: "src/mower_rover/params/mav.py"
    usage: SERVO_FUNCTION changes + DO_SET_SERVO commands
  - pattern: Profile loading
    location: "src/mower_rover/params/baseline.py"
    usage: Extend PROFILES dict for user-generated profile
  - pattern: Probe checks
    location: "src/mower_rover/probe/registry.py"
    usage: Add servo_calibration WARNING probe
  - pattern: SITL test fixtures
    location: "tests/conftest.py"
    usage: sitl_connection fixture for param round-trip tests
```

### Data Contracts

No data entities in scope — data contracts not applicable.

## Dependencies

| Dependency | Status | Blocking? |
|------------|--------|----------|
| Safety-defaults applied to Pixhawk (procedure 006) | ❌ Not yet applied | ⚠️ Recommended before field-tune (fences, failsafes) |
| MAVLink connection to Pixhawk (SiK radio or USB) | ✅ Working | Yes (stand cal) |
| MAVProxy on Jetson (`udp:127.0.0.1:14552`) | ✅ Working | Yes (field-tune) |
| `SafetyContext` + `@requires_confirmation` | ✅ Exists | Yes |
| `apply_params()` / `fetch_params()` / `ParamSet` | ✅ Exists | Yes |
| `load_param_file()` / `write_json_snapshot()` | ✅ Exists | Yes |
| `sync_params()` / `DEFAULT_SYNC_PROFILES` | ✅ Exists | Yes (needs extension) |
| Probe registry (`@register`) | ✅ Exists | Yes |
| `open_link()` + `ConnectionConfig` | ✅ Exists | Yes |
| SITL fixtures (`sitl_connection`) | ✅ Exists | Yes (tests) |
| Generic Lua FTP deploy (`deploy_lua_script()` refactored from `check_and_deploy_lua()`) | ⚠️ Needs refactor (Phase 7 creates generic function) | Yes (Stage 3) |
| Jack stands for mower | ❌ Operator provides | Yes (stand cal) |
| Encoders wired (`WENC_TYPE != 0`) | ❌ Not wired | No (manual fallback) |
| `rover-quicktune.lua` script | ❌ Must download from ArduPilot | Yes (Stage 3) |

## Risks

| # | Risk | Severity | Likelihood | Mitigation |
|---|------|----------|-----------|------------|
| R1 | `PARAM_SET SERVOn_FUNCTION` requires reboot | HIGH | MEDIUM | Field-verify before implementation. If reboot required, add reboot step between phases. Workflow becomes slower but functional. |
| R2 | `DO_SET_SERVO` brief PWM glitch on `FUNCTION` transition | MEDIUM | LOW | Transition with engine off. Phase C starts after engine-on confirmation. |
| R3 | Hydrostatic dwell time (400 ms) insufficient for deadband | LOW | MEDIUM | Make dwell configurable (`--dwell-ms`). Start conservative at 500 ms, reduce if field testing shows faster response. |
| R4 | RC8 physical switch inaccessible on Taranis | LOW | LOW | Enter key fallback always available. Operator identifies switch before starting. |
| R5 | SiK radio message drops during stand cal monitoring | LOW | LOW | `SERVO_OUTPUT_RAW` at 10 Hz is well within SiK bandwidth. Missed frames cause brief display gap, not data loss — recording happens on explicit trigger. |
| R6 | Field-tune GPS noise floor > 0.15 m/s at RTK Fix | MEDIUM | LOW | Threshold configurable. RTK Fix noise typically 0.02–0.05 m/s. Fall back to higher threshold if needed. |
| R7 | QuikTune Lua fails on skid-steer | MEDIUM | MEDIUM | QuikTune docs show general Rover. Test in SITL first. If it fails, Stage 3 becomes manual PID tuning with field-tune data as guide. |

## Execution Plan

### Phase 1: Calibration Core Library + Profile I/O

**Status:** ⏳ Not Started
**Size:** Medium
**Files to Modify:** 6
**Prerequisites:** None
**Entry Point:** `src/mower_rover/calibration/` (new package)
**Verification:** `pytest tests/test_servo_cal.py` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Create `src/mower_rover/calibration/__init__.py` package | `src/mower_rover/calibration/__init__.py` | Empty init; package importable |
| 1.2 | Implement `profile.py` — profile YAML write/read + metadata JSON write/read | `src/mower_rover/calibration/profile.py` | `write_servo_profile(path, params_dict)` writes YAML compatible with `load_param_file()`. `write_servo_metadata(path, metadata_dict)` writes JSON with `schema: mower-rover.servo-calibration.v1`. `read_servo_metadata(path)` loads and validates schema field. Round-trip test: write → `load_param_file()` → compare. |
| 1.3 | Implement `rc_monitor.py` — `RecordSignal` class (RC8 edge + Enter dual-trigger) | `src/mower_rover/calibration/rc_monitor.py` | `RecordSignal(conn)` with `start_monitoring()`, `wait_for_record()`, `stop()`. RC8 rising-edge detection from `RC_CHANNELS.chan8_raw > 1500`. `threading.Event` for cross-thread signaling. Enter key via daemon `input()` thread. Both sources trigger the same event. |
| 1.4 | Implement `stand.py` — calibration state machine (Phases A–D) | `src/mower_rover/calibration/stand.py` | `StandCalibrator(conn, safety_ctx)` with methods: `phase_a_neutral(channel)`, `phase_b_endpoints(channel)`, `phase_c_deadband(channel, trim)`, `phase_d_output(results)`. Each phase uses `apply_params()` for `SERVO_FUNCTION` changes. Phase A/B set `FUNCTION=51/53`; Phase C sets `FUNCTION=0` + `DO_SET_SERVO`. Rate limiting: 10 µs steps, 400 ms dwell for Phase C. Hard PWM clamp `[MIN+50, MAX-50]`. |
| 1.5 | Implement `deadband.py` — deadband sweep logic (extracted from stand.py) | `src/mower_rover/calibration/deadband.py` | `sweep_deadband(conn, channel, trim, direction, max_offset=200, step=10, dwell_s=0.4)` → returns `onset_pwm: int | None`. Uses inline `conn.mav.command_long_send(... MAV_CMD_DO_SET_SERVO ...)` (no helper — see Phase C pymavlink pattern in Technical Design). Displays current PWM + "watching for wheel motion" prompt. Returns `None` if no onset within `max_offset`. |
| 1.6 | Unit tests for profile I/O, RecordSignal (mocked conn), calibration state transitions | `tests/test_servo_cal.py` | Tests: profile YAML round-trip, metadata JSON schema validation, `RecordSignal` event triggering (mocked `RC_CHANNELS`), `StandCalibrator` state transitions with mocked `apply_params`. All pass without SITL. |

### Phase 2: Stand Calibration CLI + Safety Integration

**Status:** ⏳ Not Started
**Size:** Medium
**Files to Modify:** 5
**Prerequisites:** Phase 1 complete
**Entry Point:** `src/mower_rover/cli/servo_cal.py`
**Verification:** `mower servo-cal run --dry-run` completes; `mower servo-cal show` displays profile

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Create `src/mower_rover/cli/servo_cal.py` — Typer sub-app with `run` and `show` commands | `src/mower_rover/cli/servo_cal.py` | `app = typer.Typer(name="servo-cal")`. `run` command: options `--endpoint`, `--baud`, `--session engine-off\|engine-on\|full`, `--yes`, `--output` (default `config/servo-calibration.yaml`). `show` command: reads profile YAML + metadata JSON, renders Rich table. |
| 2.2 | Register servo-cal sub-app in `laptop.py` | `src/mower_rover/cli/laptop.py` | `app.add_typer(servo_cal_app, name="servo-cal")` added. `mower servo-cal --help` shows `run` and `show` subcommands. |
| 2.3 | Wire `run` command to `StandCalibrator` with full safety integration | `src/mower_rover/cli/servo_cal.py` | `SafetyContext` created from `ctx.obj["dry_run"]` + `--yes`. Safe-stop hook registered (restores `SERVO_FUNCTION`). `@requires_confirmation("This will take control of SERVO1 and SERVO3")` gate. Pre-calibration checklist prompts (blade disengaged, mower on stands, E-stop accessible). Phase orchestration: left side A→B, right side A→B, then left C, right C, then D. |
| 2.4 | Implement `--session` split-session support | `src/mower_rover/cli/servo_cal.py` | `--session engine-off`: runs Phases A+B for both sides, writes partial metadata JSON. `--session engine-on`: loads partial metadata, runs Phases C+D. `--session full` (default): all phases. |
| 2.5 | Implement `--dry-run` mode | `src/mower_rover/cli/servo_cal.py` | When `dry_run=True`: skip `SERVO_FUNCTION` changes, skip `DO_SET_SERVO`, use hardcoded example values, generate hypothetical profile to stdout. Log all commands that would be sent. |

### Phase 3: Profile Loading + pixhawk-sync Extension

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 4
**Prerequisites:** Phase 2 complete (profile files exist to load)
**Entry Point:** `src/mower_rover/params/baseline.py`
**Verification:** `mower params apply config/servo-calibration.yaml` works; `pixhawk-sync` skips missing optional profiles gracefully

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Extend `load_profile()` in `baseline.py` to check filesystem paths | `src/mower_rover/params/baseline.py` | `load_profile(name)` checks: (1) `/etc/mower/{name}.yaml`, (2) `config/{name}.yaml` relative to CWD, (3) `PROFILES[name]` package data. Returns first match. Raises `KeyError` with search paths listed if none found. |
| 3.2 | Add `OPTIONAL_SYNC_PROFILES` with split-loop in `sync.py` | `src/mower_rover/pixhawk/sync.py` | `OPTIONAL_SYNC_PROFILES = ("servo-calibration", "field-calibration")`. `sync_params()` gains a second loop after the existing mandatory-profile loop. Second loop iterates `OPTIONAL_SYNC_PROFILES`, calls `load_profile()` directly (bypasses `PROFILES` dict guard), catches `KeyError`/`FileNotFoundError` → warning log + skip. Mandatory loop unchanged. Profile merge order: `DEFAULT_SYNC_PROFILES` then `OPTIONAL_SYNC_PROFILES` (later overrides earlier). |
| 3.3 | Add `servo_calibration` probe check | `src/mower_rover/probe/checks/servo_cal.py` | `@register(name="servo_calibration", severity=Severity.WARNING)`. Checks `/etc/mower/servo-calibration.yaml` existence. Pass message includes path. Fail message says "run 'mower servo-cal run'". |
| 3.4 | Tests for profile loading fallback, sync with missing optional profiles, probe check | `tests/test_servo_cal.py` (append) | Test `load_profile("servo-calibration")` with filesystem path. Test `sync_params()` with missing optional profile (no error, warning logged). Test probe check pass/fail. |

### Phase 4: SITL Smoke Tests

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 2
**Prerequisites:** Phases 1–3 complete; SITL available
**Entry Point:** `tests/test_servo_cal_sitl.py`
**Verification:** `pytest tests/test_servo_cal_sitl.py -m sitl` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | SITL test: `SERVO_FUNCTION` param set + restore round-trip | `tests/test_servo_cal_sitl.py` | Set `SERVO1_FUNCTION=0`, verify via `fetch_params()`, restore to 73, verify. Marked `@pytest.mark.sitl`. |
| 4.2 | SITL test: `DO_SET_SERVO` send + `SERVO_OUTPUT_RAW` readback | `tests/test_servo_cal_sitl.py` | Set `SERVO1_FUNCTION=0`, send `DO_SET_SERVO(1, 1400)`, read `SERVO_OUTPUT_RAW`, verify `servo1_raw` ≈ 1400 (±20 µs tolerance for SITL jitter). |
| 4.3 | SITL test: full profile apply + snapshot round-trip | `tests/test_servo_cal_sitl.py` | Write servo-calibration.yaml to tmp dir, `load_param_file()`, `apply_params()`, `fetch_params()`, verify all 9 params match. |
| 4.4 | SITL test: CLI `--dry-run` end-to-end | `tests/test_servo_cal_sitl.py` | Invoke `mower servo-cal run --dry-run --endpoint <sitl> --yes` via `typer.testing.CliRunner`. Verify exit code 0, no `SERVO_FUNCTION` changes on SITL (fetch and compare). |
| 4.5 | SITL test: safe-stop hook restores FUNCTION on simulated abort | `tests/test_servo_cal_sitl.py` | Set `SERVO1_FUNCTION=0`, register safe-stop hook, call `ctx.safe_stop()`, verify `SERVO1_FUNCTION` restored to 73. |

### Phase 5: Field-Tune Data Collector + Algorithms (Jetson)

**Status:** ⏳ Not Started
**Size:** Large
**Files to Modify:** 5
**Prerequisites:** Phase 3 complete; MAVProxy running on Jetson
**Entry Point:** `src/mower_rover/calibration/field_tune.py`
**Verification:** Unit tests pass; `mower-jetson servo-cal field-tune --dry-run` completes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Implement `field_tune.py` — `FieldTuneCollector` with MAVLink message subscription + circular buffer | `src/mower_rover/calibration/field_tune.py` | `FieldTuneCollector(conn)` with `start()`, `stop()`, `get_data(msg_type, last_n_seconds)`, `save_session(path)`. Subscribes to 8 message types (ATTITUDE, GLOBAL_POSITION_INT, GPS_RAW_INT, SERVO_OUTPUT_RAW, RC_CHANNELS, VFR_HUD, HEARTBEAT, SYS_STATUS). Thread-safe via `threading.Lock`. 300s circular buffer. `save_session()` writes raw MAVLink data to `/var/log/mower/field-tune-YYYYMMDD-HHMMSS.json` for post-hoc analysis. Creates `/var/log/mower/` if absent. |
| 5.2 | Implement `algorithms.py` — field-tune computation functions | `src/mower_rover/calibration/algorithms.py` | Functions: `compute_mot_thr_min(data) -> int`, `compute_trim_correction(data, current_trims) -> TrimCorrection`, `compute_acro_turn_rate(data) -> float`, `compute_accel_decel_max(data) -> tuple[float, float]`. Each returns computed value + confidence (HIGH/MED/LOW) + sample count. Pure functions operating on recorded data arrays. |
| 5.3 | Implement guided maneuver state machine | `src/mower_rover/calibration/field_tune.py` | `ManeuverSequence` with 12 maneuvers (per research 031 §F). Each maneuver has: instruction text, required mode (Manual/Acro), minimum duration, validation criteria (speed range, yaw rate range). State machine: `IDLE → WAITING_FOR_ARM → BASELINE → MANEUVER_1..12 → COMPUTING → REVIEW`. |
| 5.4 | Implement maneuver validation | `src/mower_rover/calibration/field_tune.py` | Per-maneuver validation: straight runs require `mean(speed) > 0.5`, `max(|yawspeed|) < 10 deg/s`, ≥50 samples. Turns require `min(|yawspeed|) > 20 deg/s`, sustained ≥2s. Failed validation → "Please repeat" prompt. |
| 5.5 | Implement results presentation + profile generation | `src/mower_rover/calibration/field_tune.py` | Rich table showing `Parameter / Current → Computed / Confidence`. Options: Apply All, Apply High+Med Only, Review Details. Writes `/etc/mower/field-calibration.yaml` + metadata JSON. Raw session data saved to `/var/log/mower/field-tune-YYYYMMDD-HHMMSS.json` via `save_session()`. Shows diff, confirms, snapshots, applies. |
| 5.6 | Unit tests for algorithms (synthetic data) + collector (mocked conn) | `tests/test_field_tune.py` | Tests: `compute_mot_thr_min` with synthetic ramp data, `compute_trim_correction` with known servo bias, `compute_acro_turn_rate` with known yaw rates, maneuver validation pass/fail cases. All pure-function tests, no SITL. |

### Phase 6: Field-Tune CLI (Jetson)

**Status:** ⏳ Not Started
**Size:** Medium
**Files to Modify:** 3
**Prerequisites:** Phase 5 complete
**Entry Point:** `src/mower_rover/cli/servo_cal_jetson.py`
**Verification:** `mower-jetson servo-cal field-tune --help` shows options; `--dry-run` completes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 6.1 | Create `src/mower_rover/cli/servo_cal_jetson.py` — Typer sub-app with `field-tune` command | `src/mower_rover/cli/servo_cal_jetson.py` | `app = typer.Typer(name="servo-cal")`. `field-tune` command: options `--port` (default `udp:127.0.0.1:14552`), `--duration` (default 300s max), `--output` (default `/etc/mower/field-calibration.yaml`), `--yes`. |
| 6.2 | Register servo-cal sub-app in `jetson.py` | `src/mower_rover/cli/jetson.py` | `app.add_typer(servo_cal_jetson_app, name="servo-cal")`. `mower-jetson servo-cal --help` shows `field-tune` and `quicktune` subcommands. |
| 6.3 | Wire `field-tune` to collector + algorithms + Rich Live display | `src/mower_rover/cli/servo_cal_jetson.py` | Rich Live display showing: mode, armed state, speed, yaw rate, heading, SERVO1/3 PWM, throttle %, GPS fix quality. Current maneuver instruction + progress bar. Completed maneuver checklist. Updates at ~4 Hz via `Live.update()`. Pre-calibration gating: RTK Fixed (fix_type=6), ≥12 sats, engine running (voltage > 13.5V), armed. |
| 6.4 | Implement `RC8_OPTION=50` setup/teardown for Learn Cruise | `src/mower_rover/cli/servo_cal_jetson.py` | At field-tune start: `PARAM_SET RC8_OPTION=50`. On Learn Cruise maneuver: detect `STATUSTEXT` containing "Cruise Learned". At field-tune end: restore `RC8_OPTION=0`. Safe-stop hook includes RC8 restore. |

### Phase 7: QuikTune Setup (Stage 3) + Documentation

**Status:** ⏳ Not Started
**Size:** Small
**Files to Modify:** 4
**Prerequisites:** Phase 6 complete
**Entry Point:** `src/mower_rover/cli/servo_cal_jetson.py`
**Verification:** `mower-jetson servo-cal quicktune --dry-run` shows param changes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 7.1 | Refactor `check_and_deploy_lua()` → extract generic `deploy_lua_script(conn, local_path, remote_path)` | `src/mower_rover/vslam/lua_deploy.py` | Extract FTP upload logic into `deploy_lua_script(conn, local_path: Path, remote_path: str) -> bool`. `check_and_deploy_lua()` becomes a thin wrapper calling `deploy_lua_script()` with the AHRS script paths. Existing VSLAM deploy behavior unchanged (verified by existing tests). New function returns `True` if uploaded, `False` if already current. |
| 7.2 | Bundle `rover-quicktune.lua` in package data | `src/mower_rover/calibration/data/rover-quicktune.lua` | Download from ArduPilot GitHub at the **Rover-4.6.3 release tag** (`https://github.com/ArduPilot/ardupilot/blob/Rover-4.6.3/libraries/AP_Scripting/applets/rover-quicktune.lua`). Pin to this exact version for API compatibility with the mower's firmware. Add a header comment noting the source tag and download date. Include in `pyproject.toml` package data. |
| 7.3 | Add `quicktune` subcommand to `servo_cal_jetson.py` | `src/mower_rover/cli/servo_cal_jetson.py` | `quicktune` command: deploys `rover-quicktune.lua` via `deploy_lua_script()` to `/APM/scripts/rover-quicktune.lua`, sets `SCR_ENABLE=1`, `RTUN_ENABLE=1`, `RC8_OPTION=300`. Warns about required reboot for `SCR_ENABLE`. `--dry-run` logs all changes without sending. |
| 7.4 | Create QuikTune usage procedure doc | `docs/procedures/007-quicktune-pid-tuning.md` | Step-by-step: run `quicktune` command, reboot Pixhawk, switch to Circle mode, flip RC8, wait ~60s, verify STATUSTEXT results. Safety notes: open area, low speed, E-stop ready. |

## Standards

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 4 | ~15 files across calibration, CLI, params, pixhawk, probe |
| New patterns introduced | 2 | RC passthrough monitoring, dual-signal recording; builds on existing safety/param patterns |
| External dependencies | 1 | No new pip dependencies; `rover-quicktune.lua` bundled from ArduPilot |
| Migration complexity | 1 | No DB migrations; new files only; `sync.py` + `baseline.py` changes are additive |
| Test coverage required | 3 | Unit tests (profile I/O, algorithms), SITL smoke tests (param round-trips, DO_SET_SERVO), no encoder sim |
| **Overall Complexity** | **11/25** | **Medium** — Large feature surface but builds heavily on established patterns |

## Review Summary

**Review Date:** 2026-05-07
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 7 (Critical: 2, Major: 3, Minor: 2)
- Clarifying Questions Asked: 7
- Sections Updated: Stand Calibration Flow, RC8 Dual-Signal Recording, pixhawk-sync Integration, Phase 1 (Step 1.5), Phase 3 (Step 3.2), Phase 5 (Steps 5.1, 5.5), Phase 7 (Steps 7.1–7.4), Module Layout, Dependencies

### Key Improvements Made
1. **Split-loop sync_params** (Q1): Separated mandatory vs. optional profile loading to avoid `PROFILES` dict guard blocking filesystem-based profiles
2. **Lua deploy refactor** (Q2): Corrected non-existent `lua-deploy` standalone command; added Step 7.1 to extract generic `deploy_lua_script()` from existing FTP logic
3. **QuikTune version pinning** (Q3): Pinned `rover-quicktune.lua` to Rover-4.6.3 tag for firmware API compatibility
4. **RecordSignal thread lifecycle** (Q4): Replaced per-call orphan daemon threads with single long-lived `_input_loop` thread gated by `_listening` flag
5. **RC channel mapping** (Q5): Added channel → stick mapping table + pre-Phase A live RC verification step on laptop CLI
6. **Field-tune session logs** (Q6): Specified `/var/log/mower/` path for raw MAVLink session data, added `save_session()` to collector
7. **DO_SET_SERVO pattern** (Q7): Added inline pymavlink call pattern to Phase C, no new helper module

### Remaining Considerations
- R1 (`SERVO_FUNCTION` change without reboot) is still field-verify-required — if reboot needed, calibration workflow becomes slower but functional
- R7 (QuikTune on skid-steer) needs SITL validation before field use
- Taranis channel mapping should be verified against `config/taranis/RADIO/` export before implementation
- Operator must manually `scp` field-calibration profile from Jetson to `config/` for git tracking

### Sign-off
This plan has been reviewed and is **Ready for Implementation**

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-07 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-07 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/028-servo-calibration-and-field-tuning.md |
