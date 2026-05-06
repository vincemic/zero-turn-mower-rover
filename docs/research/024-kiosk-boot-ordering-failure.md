---
id: "024"
type: research
title: "Kiosk Service Boot Ordering Failure — Systemd Dependency Cycle"
status: ✅ Complete
created: "2026-05-05"
current_phase: "1 of 1"
---

## Introduction

After reboot, the mower-kiosk (and mower-weston) services fail to auto-start despite being `enabled`. Both services start fine when manually triggered with `systemctl start`. This research documents the root cause: a systemd ordering dependency issue between the services and `multi-user.target`.

## Objectives

- Determine why enabled services don't start on boot
- Identify the specific systemd ordering problem
- Document the minimal fix

## Root Cause Analysis

### The Dependency Chain (As Deployed)

```
mower-weston.service:
  [Unit]
  After=multi-user.target systemd-modules-load.service
  [Install]
  WantedBy=multi-user.target

mower-kiosk.service:
  [Unit]
  After=mower-weston.service mower-health.service
  BindsTo=mower-weston.service
  [Install]
  WantedBy=multi-user.target
```

### The Cycle

When systemd processes the boot transaction for `multi-user.target`:

1. `WantedBy=multi-user.target` creates an implicit **pull** (multi-user.target Wants mower-weston)
2. `After=multi-user.target` says weston must start **after** multi-user.target is reached
3. But `multi-user.target` cannot be marked "reached" until all its `Before=` dependencies finish
4. `mower-kiosk.service` with `WantedBy=multi-user.target` gets an implicit `Before=multi-user.target`
5. Kiosk has `After=mower-weston.service` → kiosk waits for weston
6. Weston has `After=multi-user.target` → weston waits for multi-user.target
7. multi-user.target waits for kiosk (implicit Before) → **cycle**

Systemd silently breaks this ordering cycle. In practice, it delays weston until after multi-user.target is considered "reached" by other means — but by that point the boot transaction is already committed without weston in it. Weston ends up in a limbo where it's "enabled" but was never enqueued in the boot transaction.

### Evidence From This Boot (2026-05-05 21:04:55 EDT)

| Observation | Value |
|-------------|-------|
| System boot time | 21:04:55 |
| `multi-user.target` reached | 21:08:02 (3 min 7 s after boot) |
| `mower-weston.service` auto-started? | **No** — only started at 21:08:02 via manual `systemctl start` |
| `mower-kiosk.service` auto-started? | **No** — only started at 21:09:33 via manual `systemctl start` |
| `mower-health.service` (no After=multi-user.target) | Started at 21:05:00 ✅ |
| `seatd.service` | Active since 21:04:57 ✅ |
| `/dev/dri/card0` | Present immediately at boot ✅ |
| DRM permissions (vincent in video group) | Correct ✅ |
| Symlinks in `multi-user.target.wants/` | Present ✅ |
| Boot target | `graphical.target` |
| `systemctl is-enabled` | Both `enabled` |

### Why Manual Start Works

Once multi-user.target has been reached, manually starting weston has no ordering conflict — `After=multi-user.target` is immediately satisfied, and the service starts in <1 second.

### Critical-Chain Analysis

```
mower-weston.service +26ms
└─multi-user.target @3min 9.192s
  └─mower-mavproxy.service @27.159s +5.164s
    └─network.target @6.472s
```

This confirms weston waited 3+ minutes for multi-user.target before starting (and only because we started it manually at that point).

## Weston's Actual Dependencies

Weston needs:
1. **seatd** — for DRM master access (already running at 21:04:57)
2. **`/dev/dri/card0`** — the DRM device (ExecStartPre already polls for it with 30s timeout)
3. **`/run/user/1000`** — XDG_RUNTIME_DIR (created by `logind` + linger)
4. **`systemd-modules-load.service`** — kernel modules (completes in ~1s)

It does **not** need `multi-user.target`. The `After=multi-user.target` was overly conservative and introduces the boot cycle.

## Fix Required

### In `_WESTON_UNIT_TEMPLATE` ([src/mower_rover/service/unit.py](../../src/mower_rover/service/unit.py#L409))

```diff
 [Unit]
 Description=Weston kiosk compositor for mower display
-After=multi-user.target systemd-modules-load.service
+After=seatd.service systemd-modules-load.service
+Requires=seatd.service
 StartLimitIntervalSec=120
 StartLimitBurst=30
```

**Rationale:**
- `After=seatd.service` ensures the seat manager is ready before weston tries to open DRM
- `Requires=seatd.service` pulls seatd in if not already started
- Removing `After=multi-user.target` breaks the ordering cycle
- The ExecStartPre `/dev/dri/card0` poll is retained as a safety net for slow DRM probe
- `WantedBy=multi-user.target` is kept — this ensures weston is pulled into boot

### Additional: Weston Log Rotation

The weston log at `/var/log/mower-jetson/weston.log` accumulated 385 KB of old-boot content (including stale "repaint-flush failed: Permission denied" errors from a prior session). Consider truncating it on service start:

```ini
ExecStartPre=/bin/sh -c '> /var/log/mower-jetson/weston.log'
```

Or use `LogNamespace=` / systemd journal instead of a file log.

## Secondary Issues Observed

| Issue | Severity | Notes |
|-------|----------|-------|
| `mower-mavproxy.service` failed | Expected | Pixhawk not connected during bench test |
| `mower-pixhawk-sync.service` failed | Expected | Same — no Pixhawk |
| VSLAM pose socket missing (`/run/mower/vslam_pose.sock`) | Info | Kiosk logs warning every 2s; harmless |
| Telemetry no heartbeat | Info | Expected without Pixhawk connected |

## Test Impact

The unit test `tests/test_kiosk_units.py` will need updating to match the new `After=` line.

## Deployment

After code fix:
```
mower jetson bringup --from-step kiosk-services --yes --host 192.168.4.38 --user vincent
```

Then reboot the Jetson and verify both services start automatically.

## Key Findings

- **Root cause:** `After=multi-user.target` on weston creates an ordering cycle with `WantedBy=multi-user.target` + kiosk's `After=mower-weston.service`
- **Fix:** Replace with `After=seatd.service` + `Requires=seatd.service`
- **Validation:** Reboot and confirm both services active within seconds of boot
- Services are healthy once started — no runtime issues

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-05 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/024-kiosk-boot-ordering-failure.md |
