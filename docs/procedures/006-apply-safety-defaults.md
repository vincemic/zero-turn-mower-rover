# Procedure 006 — Apply `safety-defaults` Profile to the Live Pixhawk

**Plan:** [docs/plans/016-failsafe-defaults-correction.md](../plans/016-failsafe-defaults-correction.md)
**Research:** [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md) Phase 1
**Profile:** `src/mower_rover/params/data/safety-defaults.yaml`

## 1. Purpose

This procedure applies the `safety-defaults` parameter profile to the live
Pixhawk Cube Orange. The profile corrects four failsafe parameters that the
2026-05-01 dump showed as misconfigured for a zero-turn mower: `FENCE_ACTION`
and `FS_EKF_ACTION` were set to RTL (which on a skid-steer drives in a straight
line through obstacles), `FENCE_ENABLE` was off, and `ARMING_CHECK` was 0
(allowing arming with no GPS, no RC, no logging). It also asserts the GCS
heartbeat-failsafe trio (`FS_GCS_ENABLE=1`, `FS_GCS_TIMEOUT=5`, `FS_ACTION=2`).

After this procedure, all five failsafe categories produce **Hold**, never RTL.

## 2. Pre-flight Checklist

- [ ] Mower is on a service stand **OR** ignition is off and blade clutch is
      disengaged. Software cannot move the wheels in this state, but a wrong
      param value in a different profile could; do not skip this.
- [ ] USB tether between laptop and Pixhawk is connected and stable.
- [ ] No autonomous mission is armed; mode switch on the Taranis is in **Manual**.
- [ ] Laptop is on stable mains power (a mid-apply USB disconnect leaves a
      partial param set on the autopilot).
- [ ] The current `docs/config/mower.param` is committed; this procedure will
      regenerate it.
- [ ] Identify the live-Pixhawk MAVLink endpoint (NOT a SITL UDP port):
      typically `COM<n>` on Windows or `/dev/ttyACM0` on Linux at 115200 baud.

## 3. Step 1 — Snapshot Current State

From the repo root:

```powershell
$stamp = Get-Date -Format "yyyyMMddTHHmmssZ" -AsUTC
mower params snapshot "snapshots/params/pre-safety-defaults-$stamp.json" `
    --port COM5 --baud 115200
```

(Adjust `--port` to your live endpoint. On Linux: `/dev/ttyACM0`.)

Confirm the snapshot file exists and the log line `snapshot_written` reports
the expected param count (~1000+ for ArduPilot Rover).

## 4. Step 2 — Dry-run Apply

```powershell
mower params apply --profile safety-defaults --port COM5 --baud 115200 --dry-run
```

Visually confirm the diff lists **exactly seven** keys:
`FENCE_ENABLE`, `FENCE_ACTION`, `FS_EKF_ACTION`, `FS_ACTION`,
`FS_GCS_ENABLE`, `FS_GCS_TIMEOUT`, `ARMING_CHECK`. If the diff shows wildly
different keys, **stop** — the endpoint is probably wrong (e.g. pointed at
SITL).

## 5. Step 3 — Live Apply

```powershell
mower params apply --profile safety-defaults `
    --port COM5 --baud 115200 `
    --snapshot-dir snapshots/params/
```

You will be prompted to confirm. Type `yes` to apply. The CLI will:

1. Write a pre-apply JSON snapshot under `snapshots/params/`.
2. Show the diff (same as the dry-run).
3. Write the seven values via `PARAM_SET` and verify each via `PARAM_VALUE`.

Successful completion ends with `Applied 7 params.`

## 6. Step 4 — Verify

Take a post-apply snapshot and diff against the profile:

```powershell
$stamp = Get-Date -Format "yyyyMMddTHHmmssZ" -AsUTC
mower params snapshot "snapshots/params/post-safety-defaults-$stamp.json" `
    --port COM5 --baud 115200
mower params diff safety-defaults "snapshots/params/post-safety-defaults-$stamp.json"
```

The diff must report **no changes** for all seven keys. Any difference is a
write failure — re-run Step 3.

## 7. Step 5 — Re-dump `docs/config/mower.param`

```powershell
mower params snapshot docs/config/mower.param --port COM5 --baud 115200
git diff docs/config/mower.param
```

The git diff should be limited to lines for `FENCE_ENABLE`, `FENCE_ACTION`,
`FS_EKF_ACTION`, `FS_ACTION`, `FS_GCS_ENABLE`, `FS_GCS_TIMEOUT`, and
`ARMING_CHECK`. Anything else is unexpected drift; investigate before
committing.

## 8. Step 6 — Update Research 019 Phase 1 Status

Edit [docs/research/019-current-architecture-fragility.md](../research/019-current-architecture-fragility.md):
add an "Implementation status" line to Phase 1 noting:

```markdown
**Implementation status:** ✅ Applied YYYY-MM-DD via `mower params apply --profile safety-defaults`
  (pre-snapshot: `snapshots/params/pre-safety-defaults-<stamp>.json`).
```

Use today's date.

## 9. Rollback

If the mower behaves unexpectedly after the apply, restore the pre-apply
snapshot:

```powershell
mower params apply "snapshots/params/pre-safety-defaults-<stamp>.json" `
    --port COM5 --baud 115200
```

The diff-then-confirm flow surfaces exactly which params will revert. Plan 001
guarantees lossless round-trip restore for snapshots produced by `params snapshot`.

## 10. Known Gotchas

- **Wrong endpoint**: pointing `--port` at SITL (`udp:127.0.0.1:14550`) and
  not the live Pixhawk wastes a snapshot but is otherwise harmless. The
  diff-then-confirm flow will surface unrelated SITL defaults if you do this.
- **Arming fails after apply**: `ARMING_CHECK=13816` adds GPS-fix, RC,
  battery-monitor, and logging requirements. If the mower won't arm, run
  `mower params snapshot` and check which check is failing in the autopilot's
  status text before rolling back. Per-bit relaxation is a one-key
  `mower params apply <override.yaml>`.
- **`FS_GCS_TIMEOUT=5` too aggressive in marginal Wi-Fi**: Documented risk
  R-5 in plan 016. If field testing reveals spurious Holds, raise the timeout
  via a single-key apply; do not edit the profile yaml.
- **`--snapshot-dir` is per-apply**: each apply writes a new snapshot file;
  the directory accumulates. Periodically prune or archive.
