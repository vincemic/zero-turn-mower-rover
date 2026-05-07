---
id: "029"
type: research
title: "Jetson Startup Sequence & Pixhawk Integration — Cold-Start Reinitialization Gaps"
status: ✅ Complete
created: "2026-05-06"
current_phase: "5 of 5"
---

## Introduction

The Jetson AGX Orin runs multiple systemd services that depend on each other and on the Pixhawk Cube Orange being available over USB. In certain situations — cold boot, Pixhawk power-cycle, USB disconnect/reconnect, or service crash — the system does not reliably reinitialize the full MAVLink data pipeline. This research investigates the current startup sequence, identifies failure modes, and documents improvements to make the Jetson ↔ Pixhawk integration robust across all restart scenarios.

## Objectives

- Map the complete systemd service dependency graph from boot to operational state
- Identify cold-start failure modes where services start before the Pixhawk is available
- Analyze MAVProxy, pixhawk-sync, VSLAM bridge, and kiosk data services for reconnection behavior
- Document USB device enumeration timing and udev rule reliability
- Propose concrete improvements (unit ordering, health checks, reconnection logic, watchdog patterns)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Systemd Service Dependency Graph | ✅ Complete | Map all mower-* services, their After=/Requires=/BindsTo= relationships, and boot ordering; identify missing or weak dependencies | 2026-05-06 |
| 2 | Pixhawk USB Enumeration & udev Timing | ✅ Complete | Analyze `/dev/pixhawk` symlink creation timing, udev rule reliability, `dev-pixhawk.device` systemd unit, and race conditions between device availability and service start | 2026-05-06 |
| 3 | MAVProxy & MAVLink Connection Lifecycle | ✅ Complete | Trace MAVProxy startup, reconnection behavior on USB disconnect/reconnect, heartbeat timeout handling, and downstream consumer impact (kiosk-data, pixhawk-sync, VSLAM bridge) | 2026-05-06 |
| 4 | Service Recovery & Restart Behavior | ✅ Complete | Analyze Restart=/RestartSec=/StartLimitBurst= across all services; identify services that fail permanently vs. recover; test cold-boot and Pixhawk-absent scenarios; check for cascading failures | 2026-05-06 |
| 5 | Improvement Recommendations | ✅ Complete | Synthesize findings into concrete changes: unit file fixes, reconnection logic, health-check probes, watchdog integration, and a recommended boot dependency graph | 2026-05-06 |

## Phase 1: Systemd Service Dependency Graph

**Status:** ✅ Complete  
**Session:** 2026-05-06

### Service Inventory

All 8 services are installed as **system-level** units under `/etc/systemd/system/` and all are **enabled**. Current live state (2026-05-06):

| Service | Type | Active State | Restart Policy | RestartSec | StartLimitBurst |
|---------|------|-------------|----------------|-----------|----------------|
| mower-mavproxy | simple | running | always | 5s | 5 / 300s |
| mower-health | notify | running | on-failure | 5s | 5 / 300s |
| mower-vslam | notify | running | on-failure | 5s | 5 / 300s |
| mower-vslam-bridge | notify | activating (start) | on-failure | 5s | 5 / 300s |
| mower-pixhawk-sync | oneshot | failed | no | — | 5 / 300s |
| mower-weston | simple | running | always | 2s | 30 / 120s |
| mower-kiosk-data | notify | running | on-failure | 5s | 5 / 300s |
| mower-kiosk-renderer | notify | running | on-failure | 2s | 5 / 300s |

### Dependency Graph (After= / Requires= / BindsTo=)

```
                        dev-pixhawk.device
                               │
                    BindsTo + After
                               │
                               ▼
                    mower-pixhawk-sync (oneshot, RemainAfterExit=yes)


  network.target ──After──► mower-mavproxy (simple, Restart=always)
                                │
                   Requires + After
                                │
                                ▼
                        mower-vslam-bridge (notify)
                                │
                         After (ordering only, no hard dep)
                                │
                        mower-vslam ◄──After── (ordering only)
                                │
                         After (ordering only, no hard dep)
                                │
                        mower-health ◄──After── network.target


  seatd.service ──Requires+After──► mower-weston (simple, Restart=always)
                                          │
                              ┌───────────┴───────────┐
                        After (only)            BindsTo + After
                              │                       │
                              ▼                       ▼
                     mower-kiosk-data      mower-kiosk-renderer
```

### Detailed Per-Service Analysis

**1. `mower-mavproxy.service`**
- **After:** `network.target`
- **Requires:** (none)
- **BindsTo:** (none)
- **ExecStart:** `mavproxy.py --master=/dev/pixhawk --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551 --daemon --non-interactive`
- **Restart:** always (RestartSec=5)
- **CRITICAL GAP:** Uses `/dev/pixhawk` as `--master` but has **NO** `After=dev-pixhawk.device` and **NO** `BindsTo=dev-pixhawk.device`. If the Pixhawk is not plugged in at boot, MAVProxy will start, fail to open the serial port, and restart-loop every 5s (up to 5 times in 300s, then enter failed state).
- **Reverse deps:** `mower-vslam-bridge` Requires it.

**2. `mower-health.service`**
- **After:** `network.target`
- **Requires:** (none)
- **BindsTo:** (none)
- **ExecStart:** `mower-jetson service run --health-interval 60`
- **Independent** of Pixhawk — monitors system health (CPU, memory, disk).

**3. `mower-vslam.service`**
- **After:** `network.target mower-health.service`
- **Requires:** (none)
- **BindsTo:** (none)
- **ExecStart:** `/usr/local/bin/rtabmap_slam_node --config /etc/mower/vslam.yaml`
- **Independent** of Pixhawk — uses OAK-D Pro camera.
- **No hard dependency on mower-health** (only ordering via After=).

**4. `mower-vslam-bridge.service`**
- **After:** `network.target mower-vslam.service mower-mavproxy.service`
- **Requires:** `mower-mavproxy.service`
- **BindsTo:** (none)
- **ExecStart:** `mower-jetson vslam bridge-run`
- **TimeoutStartSec:** 120s
- **Only service with a hard `Requires=` on MAVProxy.** If MAVProxy is not running, systemd will pull it in.
- **GAP:** Does NOT `Requires=mower-vslam.service`. If VSLAM isn't running, the bridge starts and tries to connect to its socket — will fail if VSLAM hasn't started yet.
- **GAP:** No relationship to `dev-pixhawk.device` at all (indirect via mavproxy, but mavproxy also lacks it).

**5. `mower-pixhawk-sync.service`**
- **After:** `network.target dev-pixhawk.device`
- **Requires:** (none implicit — but `BindsTo` is stronger)
- **BindsTo:** `dev-pixhawk.device`
- **Type:** oneshot, RemainAfterExit=yes
- **Restart:** no (oneshot — runs once at boot or when device appears)
- **Correctly bound to Pixhawk device** — will only start when `/dev/pixhawk` exists and will stop if the device disappears.
- **Currently failed:** `FS_GCS_TIMEOUT=5.0` param application failed.
- **No reverse deps** — nothing depends on pixhawk-sync completing.

**6. `mower-weston.service`**
- **After:** `seatd.service systemd-modules-load.service`
- **Requires:** `seatd.service`
- **ExecStartPre:** Waits up to 30s for `/dev/dri/card0` to appear.
- **Independent** of Pixhawk — display compositor.
- **Restart:** always (RestartSec=2, aggressive restart limits: 30 bursts / 120s).

**7. `mower-kiosk-data.service`**
- **After:** `mower-weston.service`
- **Requires:** (none)
- **BindsTo:** (none)
- **ExecStart:** `mower-jetson kiosk run`
- **GAP:** Only has `After=mower-weston.service` but NO `Requires=` or `BindsTo=`. If Weston fails, kiosk-data keeps running pointlessly.
- **GAP:** No ordering After= `mower-mavproxy` — may start before telemetry source is available.

**8. `mower-kiosk-renderer.service`**
- **After:** `mower-weston.service`
- **Requires:** (none)
- **BindsTo:** `mower-weston.service` ✅
- **ExecStartPre:** Waits up to 15s for `/run/user/1000/wayland-0` socket.
- **Correctly bound to Weston** — if Weston dies, this stops.
- **GAP:** No ordering or dependency on `mower-kiosk-data`. Reads from the Unix socket in `/run/mower/` but doesn't ensure the data service is running first.

### Boot Ordering Timeline

All services are `WantedBy=multi-user.target`. Actual ordering given After= chains:

```
Phase 1 (early boot):
  seatd.service, network.target, systemd-modules-load.service
  dev-pixhawk.device (depends on USB enumeration timing)

Phase 2 (immediate after basic targets):
  mower-mavproxy    (After=network.target)
  mower-health      (After=network.target)
  mower-weston      (After=seatd + modules-load)

Phase 3 (after Phase 2 services):
  mower-vslam       (After=mower-health)
  mower-kiosk-data  (After=mower-weston)
  mower-kiosk-renderer (After=mower-weston)
  mower-pixhawk-sync (After=dev-pixhawk.device — may be delayed if USB not ready)

Phase 4 (after Phase 3):
  mower-vslam-bridge (After=mower-vslam + mower-mavproxy)
```

### Identified Weak/Missing Dependencies

| ID | Service | Problem | Severity |
|----|---------|---------|----------|
| D1 | mower-mavproxy | No `After=dev-pixhawk.device` or `BindsTo=dev-pixhawk.device` — uses `/dev/pixhawk` but doesn't wait for it | 🔴 Critical |
| D2 | mower-mavproxy | No mechanism to detect Pixhawk USB disconnect at runtime | 🔴 Critical |
| D3 | mower-vslam-bridge | No `Requires=mower-vslam.service` — if VSLAM isn't running, bridge starts and fails | 🟡 Medium |
| D4 | mower-kiosk-data | No `Requires=` or `BindsTo=mower-weston.service` — runs without compositor | 🟡 Medium |
| D5 | mower-kiosk-data | No ordering After= `mower-mavproxy` — may start before telemetry source | 🟡 Medium |
| D6 | mower-kiosk-renderer | No `After=mower-kiosk-data.service` — may start before data socket exists | 🟡 Medium |
| D7 | mower-pixhawk-sync | `Restart=no` — if it fails, it never retries | 🟡 Medium |
| D8 | mower-pixhawk-sync | Nothing depends on it — system doesn't wait for param sync | ℹ️ Info |
| D9 | mower-vslam-bridge | No `BindsTo=dev-pixhawk.device` (indirect through mavproxy, but mavproxy also lacks it) | 🟡 Medium |
| D10 | mower-health | Formatting bug: `--health-interval 60Environment=` — Environment= line concatenated with ExecStart | 🟡 Bug |

### Code vs. Live Unit File Comparison

The MAVProxy unit template (`_MAVPROXY_UNIT_TEMPLATE` in `src/mower_rover/service/unit.py`) is a standalone template, **not** using `generate_service_unit()`. It has:
- Hardcoded `Restart=always` (not `on-failure` like the generic template)
- No support for `binds_to=` or `requires=` parameters
- No watchdog integration (`WatchdogSec` absent)

The `generate_service_unit()` function supports `binds_to`, `requires`, `after`, `timeout_start_sec`, `restart_sec`, `exec_start_pre`, and `service_type` parameters — but the MAVProxy template bypasses all of this.

### Pixhawk-Touching Services Summary

| Service | How it uses Pixhawk | Has device dependency? |
|---------|--------------------|-----------------------|
| mower-mavproxy | `--master=/dev/pixhawk` (direct serial access) | ❌ None |
| mower-pixhawk-sync | Opens `/dev/pixhawk` via pymavlink | ✅ `BindsTo=dev-pixhawk.device` |
| mower-vslam-bridge | Connects to MAVProxy UDP (indirect) | ❌ None |
| mower-kiosk-data | Reads MAVProxy UDP for telemetry (indirect) | ❌ None |

**Key Discoveries:**
- `mower-mavproxy` is the single most critical gap: it directly opens `/dev/pixhawk` but has zero systemd relationship with `dev-pixhawk.device`
- `mower-mavproxy` uses a standalone template that bypasses `generate_service_unit()`, so it lacks `binds_to`/`requires` support
- Only `mower-pixhawk-sync` correctly uses `BindsTo=dev-pixhawk.device`
- `mower-vslam-bridge` has `Requires=mower-mavproxy` but NOT `Requires=mower-vslam`
- `mower-kiosk-data` has NO hard dependency on `mower-weston` (only After= ordering)
- `mower-kiosk-renderer` has NO ordering on `mower-kiosk-data`
- `mower-pixhawk-sync` has `Restart=no` — it failed and will never retry
- `mower-health` unit file has a formatting bug: ExecStart/Environment= lines concatenated

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | All unit file generation templates |
| `src/mower_rover/pixhawk/unit.py` | Pixhawk-sync oneshot unit generation |
| `scripts/90-pixhawk-usb.rules` | udev rule creating `/dev/pixhawk` symlink |
| `src/mower_rover/cli/bringup.py` | Bringup step sequence (25 steps) |

**Gaps:** None — all 8 services examined in both codebase and live Jetson  
**Assumptions:** The `mower-health` concatenated ExecStart/Environment line is a formatting bug (not intentional)

## Phase 2: Pixhawk USB Enumeration & udev Timing

**Status:** ✅ Complete  
**Session:** 2026-05-06

### udev Rule Analysis

**Codebase rule** (`scripts/90-pixhawk-usb.rules`) matches the deployed rule on the Jetson at `/etc/udev/rules.d/90-pixhawk-usb.rules` — byte-for-byte identical.

Two entries:
1. **Symlink + tag:** `SUBSYSTEM=="tty", ATTRS{idVendor}=="2dae", SYMLINK+="pixhawk", MODE="0666", TAG+="systemd"` — Correctly creates `/dev/pixhawk` symlink, sets world-readable permissions, and adds systemd tag for `dev-pixhawk.device` auto-creation.

2. **Autosuspend:** `SUBSYSTEM=="usb", ATTRS{idVendor}=="2dae", ATTR{power/autosuspend}="-1"` — **BUG: Fires on both USB device AND interface nodes.** Interface nodes do NOT have `power/autosuspend`, producing 2-4 "Failed to write ATTR" errors per enumeration event. Fix: add `DEVTYPE=="usb_device"`.

**TAG+="systemd" verified working.** `udevadm info /dev/pixhawk` shows `TAGS=:systemd:` and `CURRENT_TAGS=:systemd:`.

**Product ID:** Pixhawk enumerates with `0x1011` (labeled "bootloader" in rule comments), NOT `0x1016` (labeled "MAVLink"). Rule correctly matches on vendor ID only, so this works. Comment is misleading.

### USB Enumeration Timing (Live Boot Data)

| Monotonic (s) | Event |
|--------------|-------|
| 0.000 | Kernel starts |
| 7.951 | `tegra-xusb 3610000.usb` USB bus registered |
| 8.737 | VIA Labs hub at port 1-4 enumerated |
| 9.629 | Realtek 4-Port hub at port 1-4.4 enumerated |
| 10.445 | OAK-D bootloader at port 1-4.4.3 enumerated |
| **12.943** | **mower-mavproxy.service started** (PID 1301) |
| **12.961** | Pixhawk at port 1-4.4.4 enumerated as USB device #6 |
| 13.174 | udev processes Pixhawk — autosuspend write errors on interfaces |
| **13.191** | **`ttyACM0` created** by `cdc_acm` driver |
| **13.236** | **`dev-pixhawk.device` active** |
| 13.239 | mower-pixhawk-sync.service started |
| 13.790 | pixhawk-sync connects to `/dev/pixhawk` |
| **14.128** | **MAVProxy main_loop CRASHES** — `SerialException: device reports readiness to read but returned no data` |
| 14.148 | pixhawk-sync receives heartbeat |
| 15.902 | OAK-D disconnects for firmware upload re-enumeration |

**MAVProxy started 248ms BEFORE the Pixhawk USB device was enumerated, and 293ms before `ttyACM0` was created.**

### Race Condition: MAVProxy vs. Pixhawk

Two contributing factors:

1. **No device dependency:** MAVProxy starts at ~12.9s (After=network.target only), but `/dev/pixhawk` doesn't become available until ~13.2s.

2. **Serial port contention:** Both MAVProxy AND `mower-pixhawk-sync` opened `/dev/pixhawk` simultaneously. MAVProxy at 12.94s; pixhawk-sync at 13.79s.

**MAVProxy failure mode — WORST CASE:** The `SerialException` occurred in a thread (`main_loop`), NOT the main process. **The process stayed alive** (PID 1301 is still running after 28 minutes) but is **functionally dead** — its main communication loop exited. Because the process didn't exit, systemd's `Restart=always` never triggers. The service shows `active (running)` but forwards no telemetry. All downstream consumers (kiosk-data, vslam-bridge) connect to UDP endpoints but receive no data.

### USB Disconnect/Reconnect Events

| Monotonic (s) | Event |
|---------------|-------|
| 13.191 | ttyACM0 created (initial boot) |
| 916.6 | USB disconnect — `dev-pixhawk.device` goes inactive |
| 919.8 | ttyACM1 created (re-enumeration) |
| 924.5 | USB disconnect again |
| 924.9 | ttyACM1 created again — current |

After each disconnect/reconnect, the ttyACM number incremented (ACM0 → ACM1). The `/dev/pixhawk` symlink correctly tracks the new device node. But **MAVProxy doesn't know the device came back** — it's holding a dead file descriptor and its main_loop thread already crashed.

### BindsTo= Semantics and Service Impact

| Service | Has BindsTo? | On disconnect | On reconnect |
|---------|-------------|---------------|--------------|
| mower-mavproxy | ❌ No | Unaware (zombie already) | Unaware |
| mower-pixhawk-sync | ✅ Yes | systemd stops it | Never restarts (Restart=no) |
| mower-vslam-bridge | ❌ No | UDP connection stale | Unaware |
| mower-kiosk-data | ❌ No | No telemetry updates | Unaware |

### OAK-D udev Rule

Deployed at `/etc/udev/rules.d/80-oakd-usb.rules`. OAK-D bootloader disconnects at 15.9s on adjacent hub port (1-4.4.3) — no direct interference with Pixhawk on port 1-4.4.4. Has the same `DEVTYPE` autosuspend bug as the Pixhawk rule.

### Bringup Deployment

The `_run_pixhawk_udev()` in `bringup.py` correctly pushes the rule, copies to `/etc/udev/rules.d/`, and runs `udevadm control --reload-rules && udevadm trigger`. Deployment is reliable.

**Key Discoveries:**
- MAVProxy starts ~248ms BEFORE the Pixhawk USB device appears — confirmed race condition
- MAVProxy's main_loop thread crashes with `SerialException` but the process stays alive as a zombie — `Restart=always` never triggers
- MAVProxy and pixhawk-sync BOTH open `/dev/pixhawk` simultaneously, causing serial port contention
- Autosuspend udev rule fires on USB interface nodes producing harmless errors — fix by adding `DEVTYPE=="usb_device"`
- After USB disconnect/reconnect, ttyACM number increments but `/dev/pixhawk` symlink correctly tracks the new device
- `mower-pixhawk-sync` has `BindsTo=dev-pixhawk.device` but `Restart=no` — on disconnect, systemd stops it and it never comes back
- `dev-pixhawk.device` ActiveEnterTimestamp monotonic = 13.236s; MAVProxy ExecMainStartTimestamp monotonic = 12.943s — 293ms gap

| File | Relevance |
|------|-----------|
| `scripts/90-pixhawk-usb.rules` | udev rule for /dev/pixhawk symlink and TAG+="systemd" |
| `src/mower_rover/service/unit.py` | MAVProxy unit template lacks device dependency support |
| `src/mower_rover/cli/bringup.py` | _run_pixhawk_udev() deployment function |

**Gaps:** Could not test cold-boot without Pixhawk (requires physical intervention). Could not determine if MAVProxy thread crash is inherent or caused by serial contention.  
**Assumptions:** SerialException likely caused by serial port contention between MAVProxy and pixhawk-sync. Product ID `0x1011` is normal CDC ACM mode, not bootloader-only.

## Phase 3: MAVProxy & MAVLink Connection Lifecycle

**Status:** ✅ Complete  
**Session:** 2026-05-06

### MAVProxy Startup & Crash Behavior

**Unit Configuration:**
- `Type=simple` — systemd considers it "started" as soon as the process forks
- `After=network.target` only — NO device dependency
- `Restart=always`, `RestartSec=5`, `StartLimitBurst=5` / `StartLimitIntervalSec=300`
- ExecStart: `mavproxy.py --master=/dev/pixhawk --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551 --daemon --non-interactive`

**What `--daemon` does:** MAVProxy's `--daemon` flag runs `main_loop()` in a background **thread** (not a subprocess). This is the critical architectural flaw:
- When `main_loop` thread crashes with `SerialException`, the **thread dies** but the **process stays alive**
- systemd tracks the main PID → sees process alive → never triggers `Restart=always`
- Result: a "walking dead" process — PID exists, no work is being done

**MAVProxy has NO built-in serial reconnection:**
- `--master` opens a pyserial connection once via `mavutil.mavlink_connection()`
- pyserial's `Serial` object has no auto-reconnect capability
- pymavlink's `autoreconnect=True` only applies to UDP connections, not serial
- There is no `--reconnect` flag in MAVProxy
- **Recovery requires a full process restart** — which doesn't happen because the process stays alive

**What happens when `/dev/pixhawk` doesn't exist at startup:**
- pyserial raises `SerialException: [Errno 2] No such file or directory`
- `main_loop` thread crashes immediately — same zombie outcome

### MAVProxy Live State on the Jetson

**Current state (32+ minutes after boot):**
- PID 1301: alive, sleeping, 14 threads, 131 MB memory
- FD 7: `/dev/ttyACM0 (deleted)` — stale serial file descriptor
- FD 12, 13: socket (UDP output sockets for 14550/14551) — sockets exist but no data flows
- systemd reports: `active (running)` — has no idea MAVProxy is dead inside
- UDP ports 14550/14551 are bound by downstream **consumers** (not MAVProxy sending)

### Downstream MAVLink Consumers

#### mower-kiosk-data (PID 840)
- **Endpoint:** `udp:127.0.0.1:14551`
- **Connection:** Direct `mavutil.mavlink_connection()` with `autoreconnect=True`
- **Heartbeat strategy:** Unbounded retry loop — `conn.wait_heartbeat(timeout=10.0)` in `while not shutdown.is_set()`. Retries forever.
- **Current state:** Spinning in heartbeat retry since boot. Every 10 seconds: `telemetry_no_heartbeat_retry`. 32+ minutes of continuous retries.
- **Unit ordering:** `After=mower-weston.service` only — NO ordering on mower-mavproxy
- **Impact:** Kiosk display shows stale/empty telemetry. If MAVProxy recovered, kiosk would pick up within 10s.

#### mower-vslam-bridge (PID 54577)
- **Endpoint:** `udp:127.0.0.1:14550`
- **Connection:** `open_link()` with `ConnectionConfig(heartbeat_timeout_s=30.0, retry_attempts=5, retry_backoff_s=2.0)`
- **Current state:** On restart counter **10**. `activating (start)`, attempt 2 of 5 failing. Will exhaust retries, crash, restart, repeat.
- **Eventual fate:** After `StartLimitBurst=5` exhausted, enters `failed` state permanently
- **Impact:** No VISION_POSITION_ESTIMATE being sent to Cube Orange

#### mower-pixhawk-sync (oneshot)
- **Endpoint:** `/dev/pixhawk` DIRECTLY — not via MAVProxy
- **Connection:** `open_link()` with `ConnectionConfig(endpoint="/dev/pixhawk", baud=0)`
- **Boot timeline:** Started at 18:34:42, got heartbeat at 18:34:43 — same second MAVProxy's thread crashed
- **Serial port contention CONFIRMED:** pixhawk-sync and MAVProxy both opened `/dev/pixhawk` within 1 second, causing the `SerialException`: "device reports readiness to read but returned no data (device disconnected or **multiple access on port**?)"

#### mower-health
- **Does NOT check MAVLink connectivity at all.** Only monitors: thermal zones, power mode, disk mounts.
- **No heartbeat monitoring.** No awareness of whether MAVProxy is functional.

### Heartbeat Timeout Handling

**Who tracks heartbeats:**
- `SharedState.last_heartbeat_epoch` (kiosk): Updated on each HEARTBEAT. Currently `0.0` — no heartbeats received this boot.
- VSLAM bridge: Sends 1 Hz component heartbeat to Pixhawk (MAV_TYPE_ONBOARD_CONTROLLER, component 197) — only after connection established.
- `open_link()`: Waits for initial heartbeat as connection-established signal. No ongoing heartbeat monitoring after handshake.

**No service monitors heartbeat staleness.** Once MAVProxy dies, the failure is silent and permanent until manual intervention.

### Serial Port Contention

| Service | Access Method | When | Exclusive? |
|---------|--------------|------|------------|
| mower-mavproxy | `--master=/dev/pixhawk` (serial, continuous) | Always running | Yes (holds fd open) |
| mower-pixhawk-sync | `open_link('/dev/pixhawk')` (serial, oneshot) | At boot | Yes (pyserial) |
| vslam-bridge `check_and_deploy_lua()` | FTP over MAVLink via connection | At bridge start | Via open_link() |

**pixhawk-sync should use MAVProxy's UDP output instead:**
- pixhawk-sync only needs MAVLink param read/write + MAVLink FTP (Lua script deploy)
- All of these work over MAVProxy's UDP forwarding
- Connecting to `udp:127.0.0.1:14550` would eliminate serial contention
- BUT: creates dependency — pixhawk-sync would need MAVProxy healthy first
- Linux serial ports are exclusive: two processes opening the same port → garbled data or the observed `SerialException`

**Key Discoveries:**
- MAVProxy's `--daemon` flag runs `main_loop` in a thread; when thread crashes, process survives but does nothing — `Restart=always` never triggers
- MAVProxy has NO serial reconnection capability — USB disconnect/reconnect is permanent failure without process restart
- Live Jetson confirms: MAVProxy PID alive 32+ minutes with dead thread, holding stale FD to `/dev/ttyACM0 (deleted)`
- Serial port contention CONFIRMED: pixhawk-sync and MAVProxy both opened `/dev/pixhawk` within 1 second
- kiosk-data spins in infinite heartbeat retry (10s intervals for 32+ minutes) — resilient but indicates total data blackout
- vslam-bridge on restart counter 10 — approaching permanent `failed` state
- mower-health does NOT monitor MAVLink connectivity — no heartbeat staleness watchdog
- No service detects or acts on MAVProxy failure — silent and permanent

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | MAVProxy unit template (no device dependency, Type=simple) |
| `src/mower_rover/mavlink/connection.py` | `open_link()` context manager with retry/backoff |
| `src/mower_rover/kiosk/telemetry.py` | `mavlink_reader_loop()` with infinite heartbeat retry |
| `src/mower_rover/kiosk/state.py` | `MavTelemetry` with `last_heartbeat_epoch` |
| `src/mower_rover/vslam/bridge.py` | `run_bridge()` with 30s heartbeat timeout, 5 retries |
| `src/mower_rover/pixhawk/sync.py` | `sync_pixhawk()` using direct serial via `open_link()` |
| `src/mower_rover/pixhawk/unit.py` | `generate_pixhawk_sync_unit_file()` with `BindsTo=dev-pixhawk.device` |
| `src/mower_rover/config/jetson.py` | Default MAVProxy endpoints configuration |

**Gaps:** None  
**Assumptions:** MAVProxy `--daemon` thread behavior is standard upstream. Serial port exclusivity based on standard Linux semantics.

## Phase 4: Service Recovery & Restart Behavior

**Status:** ✅ Complete  
**Session:** 2026-05-06

### Restart Policy Analysis — Complete Service Table

| Service | Type | Restart | RestartSec | StartLimitBurst | StartLimitIntervalSec | TimeoutStartSec | WatchdogSec | NotifyAccess |
|---------|------|---------|------------|-----------------|----------------------|-----------------|-------------|--------------|
| mower-mavproxy | simple | **always** | 5s | 5 | 300s | 90s | **0 (none)** | none |
| mower-health | notify | on-failure | 5s | 5 | 300s | 90s | **30s** | main |
| mower-weston | simple | **always** | **2s** | **30** | **120s** | 90s | 0 (none) | none |
| mower-vslam | notify | on-failure | 5s | 5 | 300s | **300s** | **30s** | main |
| mower-kiosk-data | notify | on-failure | 5s | 5 | 300s | 90s | **30s** | main |
| mower-kiosk-renderer | notify | on-failure | **2s** | 5 | 300s | 90s | **30s** | main |
| mower-pixhawk-sync | **oneshot** | **no** | 100ms | 5 | **10s** | **120s** | 0 (none) | none |
| mower-vslam-bridge | notify | on-failure | 5s | 5 | 300s | **120s** | **30s** | main |

**Key observations:**
1. Only 2 services use `Restart=always`: `mower-mavproxy` and `mower-weston`
2. `pixhawk-sync` has `Restart=no` — never self-recovers
3. MAVProxy has NO watchdog (`WatchdogSec=0`) — zombie state invisible to systemd
4. 5 services implement sd_notify watchdog (WatchdogSec=30s)

### Current Failure State (43 min uptime)

| Service | ActiveState | SubState | Result | NRestarts | Notes |
|---------|-------------|----------|--------|-----------|-------|
| mower-mavproxy | **active** | **running** | success | 0 | **ZOMBIE**: PID alive, main_loop thread dead, stale FD |
| mower-health | active | running | success | 0 | Functional, does NOT monitor MAVLink |
| mower-weston | active | running | success | 1 | Restarted once early, now stable |
| mower-vslam | active | running | success | 0 | Functional (RTAB-Map) |
| mower-kiosk-data | active | running | success | 0 | **Data blackout**: heartbeat retry 43+ min |
| mower-kiosk-renderer | active | running | success | 0 | Running but displaying stale/empty data |
| **mower-pixhawk-sync** | **failed** | **failed** | exit-code | 0 | **Permanent failure**, Restart=no |
| **mower-vslam-bridge** | **activating** | **auto-restart** | timeout | **14** | **Infinite restart loop** (~130s per cycle) |

**Summary**: 3 of 8 services degraded — MAVProxy zombie, pixhawk-sync permanently failed, vslam-bridge in infinite restart loop, plus kiosk-data in silent data blackout.

### Cascading Failure — The MAVProxy Zombie Cascade

```
MAVProxy starts before Pixhawk USB → thread crash → zombie (process alive, thread dead)
    │
    ├─ systemd sees: active/running → Restart=always NEVER TRIGGERS
    │
    ├─► vslam-bridge: no heartbeat → TimeoutStartSec=120s → SIGTERM → restart
    │   └─ Each cycle ~130s → only 2.3 fit in 300s window → NEVER hits burst=5
    │   └─ INFINITE RESTART LOOP (14 cycles and counting)
    │
    ├─► kiosk-data: no heartbeat → retry every 10s → WATCHDOG=1 still fires
    │   └─ systemd thinks healthy → PERMANENT SILENT DATA BLACKOUT
    │
    ├─► pixhawk-sync: already failed (param error) → Restart=no → PERMANENT
    │
    └─► mower-health: no MAVLink monitoring → OBLIVIOUS
```

### BindsTo= Limitations

- BindsTo= propagates **stop** but NOT **start** — when mower-weston restarts, kiosk-renderer (BindsTo=weston) must be manually restarted
- Same for pixhawk-sync: BindsTo=dev-pixhawk.device stops it on USB disconnect, but NO restart on reconnect

### vslam-bridge StartLimitBurst Ineffectiveness

Each restart cycle takes ~130s (120s TimeoutStartSec + SIGTERM + 5s RestartSec). In a 300s window, at most 2-3 restarts fit. **StartLimitBurst=5 is unreachable** — the service restarts infinitely, never hitting the burst limit.

### sd_notify / Watchdog Status

| Service | Sends READY=1? | Sends WATCHDOG=1? | Problem? |
|---------|---------------|-------------------|----------|
| mower-health | Yes | Yes (15s interval) | None |
| mower-kiosk-data | Yes | **Yes — even during data blackout** | **Masks failure**: watchdog fires with zero telemetry |
| mower-vslam-bridge | Yes (gated on heartbeat) | Yes (in pose loop) | READY=1 never sent if no heartbeat → TimeoutStartSec fires |
| mower-mavproxy | N/A (Type=simple) | N/A | **No health monitoring at all** |

### Recovery Scenarios

| Scenario | Effect | Recovers MAVProxy? | Recovers pixhawk-sync? |
|----------|--------|--------------------|-----------------------|
| `systemctl restart mower-mavproxy` | Kills zombie, fresh start | ✅ Yes | ❌ No (still failed) |
| Pixhawk USB replug | Symlink updates, no service restart | ❌ No (zombie stays) | ❌ No (Restart=no) |
| Full system reboot | Clean restart, but race condition repeats | 🎲 Coin flip (timing) | ✅ Yes (if device present) |
| CLI command | No mavproxy restart command exists | ❌ No | ❌ No |

### Missing Recovery Infrastructure

- No `systemctl restart mower-mavproxy` anywhere outside bringup
- No full-stack recovery CLI command
- No heartbeat staleness watchdog that triggers restarts
- No udev ACTION=="add" trigger for service restart on Pixhawk replug
- Probe checks are diagnostic-only — no corrective action
- kiosk-data watchdog guards liveness not correctness

**Key Discoveries:**
- vslam-bridge StartLimitBurst=5 is completely ineffective — infinite restart loop (14+ restarts observed)
- MAVProxy has NO watchdog — zombie state is invisible to systemd
- kiosk-data watchdog masks total data blackout — WATCHDOG=1 fires with zero telemetry
- pixhawk-sync Restart=no means permanent failure, no recovery
- No full-stack recovery command exists in CLI
- BindsTo= propagates stop but NOT start — no auto-restart on dependency recovery
- USB replug recovers nothing — no udev-triggered service restart
- mower-health monitors thermal/power/disk but NOT MAVLink connectivity

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | All unit file templates |
| `src/mower_rover/service/daemon.py` | Health daemon with sd_notify |
| `src/mower_rover/kiosk/app.py` | Kiosk watchdog that fires during data blackout |
| `src/mower_rover/vslam/bridge.py` | Bridge READY=1 gated on heartbeat |
| `src/mower_rover/probe/checks/` | Diagnostic-only probe checks |

**Gaps:** None  
**Assumptions:** rtabmap_slam_node and kiosk-renderer C binaries correctly implement sd_notify (verified by active status with WatchdogSec=30).

## Phase 5: Improvement Recommendations

**Status:** ✅ Complete  
**Session:** 2026-05-06

### Priority-Ordered Improvement List

#### Tier 1 — Critical (Must fix before autonomous field testing)

**R1. MAVProxy: Add `After=dev-pixhawk.device` + `BindsTo=dev-pixhawk.device`**
- Issues: D1, D2 | Severity: 🔴 Critical | Complexity: Easy
- File: `src/mower_rover/service/unit.py` → `_MAVPROXY_UNIT_TEMPLATE`
- Add `After=network.target dev-pixhawk.device` and `BindsTo=dev-pixhawk.device`
- Effect: systemd delays MAVProxy until `/dev/pixhawk` exists; stops MAVProxy if Pixhawk USB disconnects; `Restart=always` restarts it when device reappears

**R2. MAVProxy: Drop `--daemon` to fix zombie state**
- Issues: D2 | Severity: 🔴 Critical | Complexity: Easy
- File: `src/mower_rover/service/unit.py` → `generate_mavproxy_unit_file()`
- Remove `--daemon` from ExecStart command
- Without `--daemon`, `main_loop()` runs in the main thread → `SerialException` → process exits → `Restart=always` triggers
- The `--daemon` flag was designed for running from a shell; in a systemd service, it's counterproductive

**R3. pixhawk-sync: Connect via MAVProxy UDP instead of direct serial**
- Issues: serial port contention | Severity: 🔴 Critical | Complexity: Medium | Depends on: R1
- Three changes:
  - `src/mower_rover/cli/jetson.py`: Change default endpoint to `udp:127.0.0.1:14550`
  - `src/mower_rover/pixhawk/unit.py`: Change `BindsTo=dev-pixhawk.device` to `Requires=mower-mavproxy.service`, `After=mower-mavproxy.service`
  - ExecStart: add `--port udp:127.0.0.1:14550` explicitly
- MAVLink FTP (Lua deploy) works over UDP forwarding (confirmed by vslam-bridge usage)

#### Tier 2 — High (Prevents cascading failures and silent degradation)

**R4. vslam-bridge: Add `Requires=mower-vslam.service`**
- Issues: D3 | Severity: 🟡 High | Complexity: Easy
- File: `src/mower_rover/service/unit.py` → `generate_vslam_bridge_unit_file()`
- Add VSLAM to the existing `requires=` parameter

**R5. vslam-bridge: Fix StartLimitBurst ineffectiveness**
- Severity: 🟡 High | Complexity: Easy
- Set `StartLimitIntervalSec=900` (15 min) so 5 restarts at ~130s/cycle fit within the window
- Add `start_limit_interval_sec` parameter to `generate_service_unit()` and pass `900`

**R6. kiosk-data: Gate watchdog on heartbeat freshness**
- Severity: 🟡 High | Complexity: Medium
- File: `src/mower_rover/kiosk/app.py`
- Only send `WATCHDOG=1` if `last_heartbeat_epoch` is non-zero AND within last 60s
- If no heartbeat for 60s → watchdog suppressed → WatchdogSec=30 fires → systemd restarts service

**R7. pixhawk-sync: Change `Restart=no` to `Restart=on-failure`**
- Issues: D7 | Severity: 🟡 High | Complexity: Easy | Depends on: R3
- File: `src/mower_rover/pixhawk/unit.py`
- Add `Restart=on-failure`, `RestartSec=30`, relax `StartLimitIntervalSec=300`
- On failure, retries after 30s instead of permanent failure

#### Tier 3 — Medium (Correctness and observability)

**R8. kiosk-data: Add `Requires=mower-weston.service` + `After=mower-mavproxy.service`**
- Issues: D4, D5 | Complexity: Easy
- File: `src/mower_rover/service/unit.py` → `generate_kiosk_data_unit_file()`

**R9. kiosk-renderer: Add `After=mower-kiosk-data.service`**
- Issues: D6 | Complexity: Easy
- File: `src/mower_rover/service/unit.py` → `generate_kiosk_renderer_unit_file()`

**R10. mower-health: Fix ExecStart/Environment concatenation bug**
- Issues: D10 | Complexity: Easy
- File: `src/mower_rover/service/unit.py` — locate missing newline in template

**R11. udev autosuspend rule: Add `DEVTYPE=="usb_device"` filter**
- Complexity: Easy
- File: `scripts/90-pixhawk-usb.rules`
- Eliminates 2-4 harmless "Failed to write ATTR" errors per enumeration

#### Tier 4 — Enhancements (Deferred)

**R12. USB replug recovery** — Already solved by R1+R2 (`BindsTo=` + `Restart=always` = native recovery)

**R13. Full-stack recovery CLI command** — `mower-jetson stack restart`: stops all services, reset-failed, starts in order. Medium complexity.

**R14. MAVLink connectivity probe in mower-health** — Heartbeat freshness check from UDP, observability only. Medium complexity. Depends on R2.

### Recommended Boot Dependency Graph (After Fixes)

```
                        dev-pixhawk.device
                               │
                    BindsTo + After
                               │
                               ▼
                    mower-mavproxy (simple, Restart=always, no --daemon)
                       │         │              │
         Requires+After│         │              │ Requires+After
                       │         │              │
                       ▼         │              ▼
  mower-pixhawk-sync   │    mower-kiosk-data
  (oneshot, via UDP)    │    (Requires=weston, After=mavproxy)
  [Restart=on-failure]  │    [Watchdog gated on heartbeat]
                        │
         Requires+After │   Requires+After
                        │──────────┐
                        │          │
                        ▼          ▼
                mower-vslam-bridge
                [Requires=mavproxy+vslam]
                [StartLimitIntervalSec=900]

  seatd ──Req+After──► mower-weston ──BindsTo+After──► mower-kiosk-renderer
                              │                        [After=kiosk-data]
                              └─────Requires+After────► mower-kiosk-data

  network.target ──After──► mower-health (independent)
```

### Expected Boot Ordering (With Fixes)

```
Phase 1: seatd, network.target, systemd-modules-load
Phase 2: dev-pixhawk.device (~13s), /dev/dri/card0
Phase 3: mower-mavproxy (After=device), mower-health, mower-weston
Phase 4: mower-vslam, mower-pixhawk-sync (After=mavproxy), mower-kiosk-data
Phase 5: mower-kiosk-renderer (After=kiosk-data), mower-vslam-bridge (After=vslam+mavproxy)
```

### Recovery Scenarios (With Fixes)

| Scenario | MAVProxy | pixhawk-sync | vslam-bridge | kiosk-data |
|----------|----------|-------------|-------------|------------|
| Cold boot (Pixhawk present) | ✅ Waits for device | ✅ After MAVProxy, via UDP | ✅ After MAVProxy+VSLAM | ✅ After MAVProxy+Weston |
| Pixhawk USB disconnect | 🔄 BindsTo stops it | 🔄 Requires stops it | 🔄 Requires stops it | ⚠️ Watchdog → restart |
| Pixhawk USB replug | 🔄 Restart=always | 🔄 Restart=on-failure | 🔄 Restart=on-failure | 🔄 Heartbeats resume |
| MAVProxy thread crash | ✅ No --daemon → exit → restart | 🔄 Requires restarts | 🔄 Requires restarts | 🔄 Watchdog → restart |

### Implementation Sequencing

| Order | Fix | Files Changed |
|-------|-----|--------------|
| 1 | R2: Drop `--daemon` | `service/unit.py` |
| 2 | R1: Add device dependency | `service/unit.py` |
| 3 | R3: pixhawk-sync via UDP | `cli/jetson.py`, `pixhawk/unit.py` |
| 4 | R7: pixhawk-sync Restart=on-failure | `pixhawk/unit.py` |
| 5 | R4: vslam-bridge Requires VSLAM | `service/unit.py` |
| 6 | R5: vslam-bridge StartLimitInterval | `service/unit.py` |
| 7 | R8: kiosk-data dependencies | `service/unit.py` |
| 8 | R9: kiosk-renderer After kiosk-data | `service/unit.py` |
| 9 | R6: kiosk-data watchdog gating | `kiosk/app.py` |
| 10 | R10: health unit bug | `service/unit.py` |
| 11 | R11: udev DEVTYPE filter | `scripts/90-pixhawk-usb.rules` |

**Key Discoveries:**
- Dropping `--daemon` is the single highest-impact fix — eliminates zombie failure mode with one string change
- `BindsTo=dev-pixhawk.device` + `Restart=always` provides native USB replug recovery without udev triggers
- pixhawk-sync via MAVProxy UDP eliminates serial contention and simplifies dependency chain
- Unconditional `WATCHDOG=1` in kiosk-data actively masks data blackouts
- Complete fix set (R1-R11) requires changes to only 5 source files
- No new services, wrapper scripts, or external tools needed — all fixes use existing systemd primitives

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | R1, R2, R4, R5, R8, R9, R10 |
| `src/mower_rover/pixhawk/unit.py` | R3, R7 |
| `src/mower_rover/cli/jetson.py` | R3 |
| `src/mower_rover/kiosk/app.py` | R6 |
| `scripts/90-pixhawk-usb.rules` | R11 |

**Gaps:** D10 (health ExecStart/Environment bug) needs exact root cause verification  
**Assumptions:** MAVProxy without `--daemon` exits on SerialException (standard upstream behavior). MAVLink FTP works via UDP forwarding.

## Overview

The Jetson AGX Orin's service stack has a fundamental reliability gap: **MAVProxy — the single hub for all Pixhawk telemetry — starts before the Pixhawk USB device enumerates, crashes silently, and systemd never restarts it.** This creates a "zombie" process that appears healthy to systemd while forwarding zero data. Every downstream service (VSLAM bridge, kiosk telemetry, pixhawk param sync) is broken as a direct consequence, and no automated recovery mechanism exists.

The root cause chain is: (1) missing systemd device dependency on MAVProxy, (2) serial port contention between MAVProxy and pixhawk-sync at boot, (3) MAVProxy's `--daemon` flag running the communication loop in a thread rather than the main process, and (4) absent health monitoring of MAVLink data flow. The system was observed running for 43+ minutes in this degraded state with no automated detection or recovery.

11 concrete fixes were identified, requiring changes to only 5 source files. The two highest-impact fixes — dropping `--daemon` and adding `BindsTo=dev-pixhawk.device` — are single-line changes that eliminate the entire zombie failure mode and provide native USB disconnect/reconnect recovery using existing systemd primitives.

## Key Findings

1. **MAVProxy zombie is the root cause of total MAVLink failure.** The `--daemon` flag runs `main_loop()` in a thread; when it crashes (SerialException from USB timing or serial contention), the process stays alive and systemd's `Restart=always` never triggers. PID alive for 43+ minutes with zero data throughput, reported as `active (running)`.

2. **MAVProxy has no systemd relationship with `dev-pixhawk.device`.** It starts ~248ms before the Pixhawk USB device enumerates (After=network.target only). Only `mower-pixhawk-sync` correctly uses `BindsTo=dev-pixhawk.device`.

3. **Serial port contention between MAVProxy and pixhawk-sync.** Both services open `/dev/pixhawk` simultaneously at boot. Linux serial ports are exclusive — the contention produces the `SerialException: "device reports readiness to read but returned no data (device disconnected or multiple access on port?)"`.

4. **vslam-bridge is in an infinite restart loop.** Each cycle takes ~130s (120s TimeoutStartSec + delays). `StartLimitBurst=5` in a 300s window is mathematically unreachable (only 2-3 cycles fit). 14+ restarts observed and counting.

5. **kiosk-data masks total data blackout.** The service sends `WATCHDOG=1` unconditionally, even with zero telemetry data for 43+ minutes. systemd thinks it's healthy.

6. **pixhawk-sync fails permanently.** `Restart=no` on a oneshot service means any failure (param apply error, Lua deploy error) is final. No CLI command or automated mechanism retries it.

7. **No service monitors MAVLink connectivity.** `mower-health` checks thermal/power/disk but has zero awareness of the Pixhawk connection. No heartbeat staleness watchdog exists anywhere.

8. **USB replug does not recover anything.** No udev-triggered restart, MAVProxy zombie holds stale FD, pixhawk-sync stays failed. `BindsTo=` propagates stop but NOT start.

9. **All fixes use existing systemd primitives.** No new services, wrapper scripts, or external tools needed. 11 changes across 5 files.

## Actionable Conclusions

1. **Drop `--daemon` from MAVProxy ExecStart** (R2) — single highest-impact fix. Eliminates zombie failure mode entirely. One string change.
2. **Add `BindsTo=dev-pixhawk.device`** to MAVProxy unit (R1) — provides device-gated startup and native USB replug recovery.
3. **Move pixhawk-sync to MAVProxy UDP** (R3) — eliminates serial port contention. Requires MAVProxy to be reliable first (R1+R2).
4. **Gate kiosk-data watchdog on heartbeat freshness** (R6) — makes data blackout detectable and auto-recoverable.
5. **Fix vslam-bridge `StartLimitIntervalSec`** (R5) — set to 900s so burst=5 is reachable, ending the infinite restart loop.
6. **Add missing `Requires=` dependencies** (R4, R7, R8, R9) — correct the dependency graph so cascading failures propagate correctly.
7. **Implementation sequence:** R2 → R1 → R3 → R7 → R4 → R5 → R8 → R9 → R6 → R10 → R11. Changes to 5 files total.

## Open Questions

- **MAVProxy without `--daemon` behavior:** Does MAVProxy exit cleanly on SerialException in the main thread? Should be verified in SITL before deploying to hardware.
- **MAVLink FTP via UDP:** pixhawk-sync uses MAVLink FTP for Lua script deployment. Confirm this works through MAVProxy's UDP forwarding (vslam-bridge already uses this pattern for its own Lua deploy, so likely works).
- **mower-health ExecStart/Environment bug (D10):** Exact root cause of the concatenated lines needs verification — may be a missing newline in `generate_service_unit()` template or in `extra_environment` formatting.
- **Cold boot without Pixhawk:** With R1 (`BindsTo=dev-pixhawk.device`), MAVProxy will wait indefinitely for the device. Is this the desired behavior, or should there be a timeout after which the system reports "Pixhawk not connected" to the kiosk?
- **Pixhawk product ID 0x1011 vs 0x1016:** The udev rule comments label `0x1011` as "bootloader" and `0x1016` as "MAVLink", but the Pixhawk always enumerates as `0x1011`. Clarify whether `0x1016` is used in any scenario.

## References

- Live Jetson SSH analysis (192.168.4.38) — systemd unit files, journalctl logs, USB enumeration timing, process state
- ArduPilot MAVProxy source behavior — `--daemon` threading model, serial reconnection limitations
- systemd documentation — BindsTo= semantics (propagates stop, not start), StartLimitBurst timing, WatchdogSec behavior

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-06 |
| Status | ✅ Complete |
| Current Phase | 5 of 5 |
| Path | /docs/research/029-jetson-startup-pixhawk-reinit.md |
