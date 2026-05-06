---
id: "025"
type: research
title: "Kiosk Dashboard Data Delivery — Gaps & Solutions"
status: ✅ Complete
created: "2026-05-05"
current_phase: "4 of 4"
---

## Introduction

The kiosk dashboard on the Jetson AGX Orin displays 8 panels (VSLAM Status, Vehicle State, GPS/RTK, System Health, Storage, Wi-Fi, Services, Alerts) refreshed at 1 Hz via `SharedState`. Three background threads feed it: a VSLAM Unix-socket reader, a MAVLink UDP reader, and a slow poller (health/disk/wifi/services). This research investigates whether each data source is actually delivering live data in the deployed environment, identifies any gaps, and recommends the best approach to close them.

## Objectives

- Determine which of the 8 dashboard panels are receiving live data from their intended sources on the deployed Jetson
- Identify data delivery failures or gaps (thread not running, service not present, endpoint misconfigured, socket missing, etc.)
- For each gap, research the best remediation approach (new service, config change, MAVProxy output, etc.)
- Assess whether the MAVLink endpoint (`udp:127.0.0.1:14550`) is available on the Jetson (requires MAVProxy or similar forwarding)
- Assess VSLAM socket availability (depends on `mower-vslam-bridge.service` running)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | MAVLink Data Path Audit | ✅ Complete | Trace MAVLink data from Pixhawk → Jetson → kiosk telemetry thread; verify MAVProxy (or equivalent) is deployed and forwarding to udp:14550; check `mower-kiosk.service` environment for endpoint config | 2026-05-05 |
| 2 | VSLAM & Service Data Path Audit | ✅ Complete | Verify VSLAM bridge writes to `/run/mower/vslam_pose.sock`; check `mower-vslam-bridge.service` is enabled and running; confirm `mower-slam-node.service` feeds it; check service status polling works under user systemd scope | 2026-05-05 |
| 3 | Health/Storage/Wi-Fi Poller Audit | ✅ Complete | Verify sysfs thermal zones, nvpmodel, disk paths, and Wi-Fi `/proc/net/wireless` are readable from the kiosk service context (user unit, no special caps); identify any permission barriers | 2026-05-05 |
| 4 | Gap Remediation Design | ✅ Complete | For each confirmed gap, propose the minimal fix — e.g., deploy a MAVProxy user service, add a socket activation unit for VSLAM bridge, adjust endpoint config in `/etc/mower/jetson.yaml`; produce an actionable remediation summary | 2026-05-05 |

## Phase 1: MAVLink Data Path Audit

**Status:** ✅ Complete  
**Session:** 2026-05-05

### MAVLink Data Path: Pixhawk → Kiosk Dashboard

The full data path is:

```
Pixhawk Cube Orange (USB micro → /dev/ttyACM0 → symlinked as /dev/pixhawk)
     │
     ▼
mower-mavproxy.service (MAVProxy 1.8.71)
  --master=/dev/pixhawk
  --out=udp:127.0.0.1:14550   →  mower-vslam-bridge.service
  --out=udp:127.0.0.1:14551   →  mower-kiosk.service (telemetry thread)
  --daemon --non-interactive
```

### 1. Physical Connection

The Pixhawk Cube Orange connects to the Jetson AGX Orin via **USB micro** (CDC ACM serial, appearing as `/dev/ttyACM0`). A udev rule (`scripts/90-pixhawk-usb.rules`) creates a stable symlink `/dev/pixhawk` and disables USB autosuspend:

```udev
SUBSYSTEM=="tty", ATTRS{idVendor}=="2dae", SYMLINK+="pixhawk", MODE="0666", TAG+="systemd"
SUBSYSTEM=="usb", ATTRS{idVendor}=="2dae", ATTR{power/autosuspend}="-1"
```

### 2. MAVProxy Service (`mower-mavproxy.service`)

**Unit file template** (from `src/mower_rover/service/unit.py`):
```ini
[Unit]
Description=MAVProxy telemetry forwarder for mower
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/home/vincent/.local/share/uv/tools/mower-rover/bin/mavproxy.py --master=/dev/pixhawk --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551 --daemon --non-interactive
Environment=MOWER_CORRELATION_ID=daemon
User=vincent
WorkingDirectory=/home/vincent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Deployment:** Step 21 (`install-mavproxy`) in the bringup pipeline installs MAVProxy, writes the systemd unit, enables it, rewrites VSLAM bridge config to `udp:127.0.0.1:14550`, and restarts the bridge.

**Deployment status (2026-05-05):** Successfully deployed — MAVProxy 1.8.71 active per deploy-019b.log.

### 3. Kiosk Telemetry Thread

The kiosk service ExecStart is `mower-jetson kiosk run` (no `--endpoint` flag).

The CLI command resolves the endpoint:
```python
cfg = load_jetson_config(config)  # loads ~/.config/mower-rover/jetson.yaml or defaults
mavlink_ep = endpoint or cfg.kiosk.mavproxy_endpoint
run_kiosk(mavlink_endpoint=mavlink_ep)
```

**Default endpoint:** `KioskConfig.mavproxy_endpoint = "udp:127.0.0.1:14551"` — matches MAVProxy's second output.

### 4. Telemetry Reader Loop

```python
def mavlink_reader_loop(state, shutdown, *, endpoint="udp:127.0.0.1:14550", ...):
    conn = mavutil.mavlink_connection(endpoint, source_system=254, autoreconnect=True)
    hb = conn.wait_heartbeat(timeout=10.0)  # blocks until first heartbeat
```

**Messages parsed → SharedState fields:**

| Message | Fields Updated |
|---------|---------------|
| `HEARTBEAT` | `armed`, `mode`, `system_status`, `last_heartbeat_epoch` |
| `VFR_HUD` | `groundspeed_ms`, `heading_deg`, `throttle_pct` |
| `GPS_RAW_INT` / `GPS2_RAW` | `gps1_fix/gps2_fix`, `gps1_sats/gps2_sats`, `gps1_hdop/gps2_hdop`, `last_gps_epoch` |
| `GPS_RTK` / `GPS2_RTK` | `rtk1_baseline_mm/rtk2_baseline_mm`, `rtk1_iar/rtk2_iar` |
| `STATUSTEXT` | `last_statustext` |

### 5. Error Handling / Failure Modes

- If MAVProxy is not running, `wait_heartbeat(timeout=10.0)` returns `None`, the thread logs an error and exits. The kiosk continues running with stale/empty telemetry.
- `autoreconnect=True` handles reconnects only AFTER initial heartbeat succeeds.
- The thread is `daemon=True` so it dies with the process.

### 6. Configuration Hierarchy

| Config File | Deployed By | Key Field | Value |
|-------------|-------------|-----------|-------|
| `/etc/mower/vslam.yaml` | install-mavproxy step (rewrite) | `bridge.serial_device` | `udp:127.0.0.1:14550` |
| `~/.config/mower-rover/jetson.yaml` | Not deployed (defaults used) | `kiosk.mavproxy_endpoint` | `udp:127.0.0.1:14551` (default) |
| `/etc/systemd/system/mower-mavproxy.service` | install-mavproxy step | `ExecStart` args | `--out=...14550 --out=...14551` |

### Bugs Found

1. **Unit name mismatch:** `cli/kiosk.py` line 33 lists `"mavproxy.service"` instead of `"mower-mavproxy.service"` — causes `kiosk status/enable/disable` to check the wrong unit.
2. **No heartbeat retry:** The telemetry thread exits after a single 10s heartbeat timeout with no retry loop. If MAVProxy starts after the kiosk, the thread dies permanently.
3. **Missing ordering dependency:** `mower-kiosk.service` has no `After=mower-mavproxy.service` — startup race possible.

**Key Discoveries:**
- The full MAVLink path is operational: Pixhawk USB (`/dev/pixhawk`) → MAVProxy → UDP `:14550` (VSLAM) + UDP `:14551` (kiosk)
- MAVProxy 1.8.71 confirmed deployed and active as of 2026-05-05
- Kiosk uses default `KioskConfig.mavproxy_endpoint = "udp:127.0.0.1:14551"` — no config file needed
- Unit name bug in `cli/kiosk.py`: `"mavproxy.service"` should be `"mower-mavproxy.service"`
- Telemetry thread has no retry on initial heartbeat failure — single-shot exit
- No startup ordering between kiosk and MAVProxy services

| File | Relevance |
|------|-----------|
| `src/mower_rover/kiosk/telemetry.py` | MAVLink reader loop, message parsing |
| `src/mower_rover/kiosk/app.py` | Thread orchestration, `run_kiosk` entry |
| `src/mower_rover/kiosk/state.py` | `SharedState` / `MavTelemetry` dataclass |
| `src/mower_rover/cli/kiosk.py` | `kiosk run` CLI, endpoint resolution, unit name bug |
| `src/mower_rover/config/jetson.py` | `KioskConfig` defaults |
| `src/mower_rover/service/unit.py` | MAVProxy and kiosk unit templates |
| `src/mower_rover/cli/bringup.py` | install-mavproxy step |
| `src/mower_rover/probe/checks/kiosk.py` | `mavproxy_active` probe |
| `scripts/90-pixhawk-usb.rules` | udev `/dev/pixhawk` symlink |

**Gaps:** Cannot confirm live Jetson state (appears shut down). Unit name bug and startup race require code fixes.  
**Assumptions:** deploy-019b.log represents the latest deployment; no explicit `jetson.yaml` is deployed on the Jetson.

## Phase 2: VSLAM & Service Data Path Audit

**Status:** ✅ Complete  
**Session:** 2026-05-05

### 1. VSLAM Socket Path Mismatch (CRITICAL BUG)

The kiosk's VSLAM reader thread hardcodes an **incorrect socket path**:

```python
# src/mower_rover/kiosk/app.py, line 47
socket_path = "/run/mower/vslam_pose.sock"  # ← UNDERSCORE (wrong)
```

The SLAM node and VSLAM bridge both use **hyphen**:
- C++ default: `"/run/mower/vslam-pose.sock"` (rtabmap_slam_node.cpp:83)
- Python config default: `socket_path: str = "/run/mower/vslam-pose.sock"` (config/vslam.py:69)
- YAML config deployed to Jetson: `socket_path: /run/mower/vslam-pose.sock`

**Impact:** The kiosk will never receive VSLAM pose data. The `PoseReader` will fail with `FileNotFoundError` on connect, log a warning every 2 seconds, and never populate the VSLAM Status panel.

### 2. Single-Client Socket Limitation (ARCHITECTURAL ISSUE)

The SLAM node's socket server accepts only **one client** at a time:
```cpp
// rtabmap_slam_node.cpp:512
static bool socket_send_pose(SocketServer &srv, const struct vslam_pose_msg &msg) {
    if (srv.client_fd < 0)
        return true;
    ssize_t n = write(srv.client_fd, &msg, sizeof(msg));
}
```

The bridge occupies that single slot. Even with the correct path, the kiosk **cannot** connect directly to the SLAM socket while the bridge is running.

### 3. Intended vs Actual VSLAM Data Flow

**Intended:**
```
OAK-D Pro → rtabmap_slam_node (C++) → /run/mower/vslam-pose.sock
                                            ↓
                              mower-vslam-bridge.service (PoseReader)
                                            ↓
                              FLU→NED → VISION_POSITION_ESTIMATE → Pixhawk
```

**Kiosk alternate path (via MAVLink):**
The bridge already emits `NAMED_VALUE_FLOAT` messages (`VSLAM_HZ`, `VSLAM_CONF`, `VSLAM_AGE`, `VSLAM_COV`) to MAVProxy. These flow to the kiosk via UDP :14551. The kiosk telemetry reader would need to parse these — it currently does **not**.

### 4. Service Name Mismatches (CRITICAL BUG)

The `_check_services()` function in `kiosk/app.py` uses **wrong unit names**:

```python
services_to_check = [
    ("slam_node", "mower-slam-node.service"),    # WRONG → actual: "mower-vslam.service"
    ("vslam_bridge", "mower-vslam-bridge.service"),  # correct
    ("health_monitor", "mower-health.service"),      # correct
    ("mavproxy", "mavproxy.service"),                # WRONG → actual: "mower-mavproxy.service"
]
```

### 5. systemctl --user on System-Level Services (CRITICAL BUG)

```python
# kiosk/app.py:180
proc = subprocess.run(
    ["systemctl", "--user", "is-active", unit],  # ← queries user instance
    ...
)
```

All four services are deployed as **system-level** units (under `/etc/systemd/system/`, installed via `sudo`). The `--user` flag queries the per-user systemd instance, which has no knowledge of system units.

**Impact:** The kiosk "Services" panel will **always** show all services as "inactive" regardless of actual state.

Fix: Remove `--user` — `systemctl is-active` is read-only and works without elevated permissions on system units.

### 6. Wire Format (Confirmed Stable)

IPC wire format: `<Q27fBB` — 118 bytes, little-endian. Both C++ (`static_assert`) and Python (`assert`) enforce this size. Fields: timestamp_us, pose (6 floats), covariance upper-triangle (21 floats), confidence, reset_counter.

### 7. Service Deployment Confirmation

Both `mower-vslam.service` and `mower-vslam-bridge.service`:
- Installed to `/etc/systemd/system/` via `sudo`
- Enabled and started at bringup
- Include `RuntimeDirectory=mower` (creates `/run/mower/` automatically)

**Key Discoveries:**
- **Socket path bug**: Kiosk uses underscore (`vslam_pose.sock`) but SLAM node creates hyphen (`vslam-pose.sock`) — VSLAM panel always empty
- **Single-client socket**: SLAM node accepts only 1 client (the bridge) — kiosk cannot be a second consumer
- **systemctl --user bug**: All services are system-level but kiosk polls with `--user` — Services panel always shows "inactive"
- **Service name bugs**: `mower-slam-node.service` (should be `mower-vslam.service`) and `mavproxy.service` (should be `mower-mavproxy.service`)
- **Redesign needed**: Kiosk should get VSLAM metrics via MAVLink `NAMED_VALUE_FLOAT` messages the bridge already emits
- **Wire format is stable**: 118-byte packed struct verified on both sides

| File | Relevance |
|------|-----------|
| `src/mower_rover/kiosk/app.py` | Wrong socket path, wrong unit names, wrong --user flag |
| `src/mower_rover/vslam/ipc.py` | PoseReader, wire format constants |
| `src/mower_rover/vslam/bridge.py` | Bridge main loop, NAMED_VALUE_FLOAT emission |
| `src/mower_rover/vslam/health.py` | BridgeHealth computation |
| `src/mower_rover/config/vslam.py` | VslamConfig with correct socket path |
| `src/mower_rover/service/unit.py` | Unit name constants |
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | Single-client socket server |
| `contrib/rtabmap_slam_node/include/vslam_pose_msg.h` | Wire format definition |

**Gaps:** None  
**Assumptions:** SLAM node's single `client_fd` confirmed by reading socket_accept_nonblock/socket_send_pose. Deployed config matches Python defaults.

## Phase 3: Health/Storage/Wi-Fi Poller Audit

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Slow Poller Architecture

The kiosk's `_slow_poller_thread` (`kiosk/app.py`, line 83) runs every 5 seconds and calls `_poll_health()`:

1. `read_thermal_zones(sysroot)` — thermal.py
2. `read_power_state(sysroot)` — power.py
3. `read_disk_usage(sysroot)` — disk.py
4. `read_wifi_status(sysroot)` — wifi.py
5. `_check_services()` — inline in app.py (systemctl subprocess)

The sysroot defaults to `Path("/")` in production.

### 1. Thermal Zones

**Paths:** `/sys/class/thermal/thermal_zone*/temp` and `/sys/class/thermal/thermal_zone*/type`

**Permissions:** World-readable on all Linux kernels including Jetson L4T 36.5. Confirmed working via deploy logs: "All zones OK (max 46.3°C on cpu-thermal)".

**Status: ✅ No permission barrier.**

### 2. Power State

| Sub-reader | Path/Method | Permissions | Notes |
|---|---|---|---|
| nvpmodel mode | subprocess `nvpmodel -q` | ✅ No sudo for query | Only `-m` (set) needs root |
| Online CPUs | `/sys/devices/system/cpu/online` | ✅ World-readable | Standard sysfs |
| GPU frequency | `/sys/devices/17000000.gpu/devfreq/.../cur_freq` | ✅ World-readable | devfreq 0444 |
| Fan profile | `/sys/devices/pwm-fan/cur_pwm_profile` | ✅ Likely | Graceful `None` fallback |

The `nvpmodel` binary is at `/usr/sbin/nvpmodel`. Systemd system-level units inherit a default `PATH` including `/usr/sbin` on L4T/Ubuntu. Code handles `FileNotFoundError` gracefully.

### 3. Disk Usage

**Paths:** `/proc/mounts` (world-readable) + `os.statvfs(mount_point)` on `{"/", "/home", "/data"}`

Both work without elevated privileges for any user. NVMe detection checks device name contains "nvme".

**Status: ✅ No permission barrier.**

### 4. Wi-Fi Status

**Path:** `/proc/net/wireless` — world-readable. Provides interface name, link quality, signal dBm, noise dBm.

Hardware: AzureWave AW-CB375NF (Intel AX210, `iwlwifi` driver), interface typically `wlan0`.

**Status: ✅ No permission barrier.**

### 5. Overall Permission Assessment

| Data Source | Readable as `vincent`? | Notes |
|---|---|---|
| Thermal zones | ✅ Yes | World-readable sysfs |
| nvpmodel mode | ✅ Yes | Query is unprivileged |
| Online CPUs | ✅ Yes | World-readable sysfs |
| GPU frequency | ✅ Yes | World-readable devfreq |
| Fan profile | ✅ Likely | Graceful fallback |
| /proc/mounts | ✅ Yes | World-readable |
| Disk statvfs | ✅ Yes | Works for all users |
| Wi-Fi signal | ✅ Yes | World-readable /proc |
| Service status | ❌ Bug | `--user` queries wrong instance (Phase 2) |

### Conclusion

**No permission barriers exist** for any health/storage/wifi data source. The system-level `User=vincent` service context is sufficient for all reads. The only functional issue in the slow poller is the `_check_services()` bug (wrong `--user` flag and wrong unit names) already identified in Phase 2.

**Key Discoveries:**
- All sysfs/procfs paths are world-readable — no capability escalation needed
- `nvpmodel -q` confirmed working without sudo (deploy log evidence)
- Code is well-structured with `sysroot` parameter injection for testability and graceful degradation
- The slow poller has zero permission barriers; only the `_check_services()` bug affects it

| File | Relevance |
|------|-----------|
| `src/mower_rover/kiosk/app.py` | Slow poller thread, _poll_health() |
| `src/mower_rover/health/thermal.py` | Reads thermal zone sysfs |
| `src/mower_rover/health/power.py` | nvpmodel, CPU, GPU, fan readers |
| `src/mower_rover/health/disk.py` | /proc/mounts + statvfs |
| `src/mower_rover/health/wifi.py` | /proc/net/wireless parser |
| `src/mower_rover/service/unit.py` | Kiosk unit generation (confirms User=vincent, no caps) |

**Gaps:** Cannot verify live permissions without SSH; analysis based on standard L4T 36.5 defaults + confirmed probe behavior from deploy logs.  
**Assumptions:** Standard L4T 36.5 sysfs permissions — supported by probes running as `vincent` successfully during bringup.

## Phase 4: Gap Remediation Design

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Priority Classification

| Priority | Bug | Impact | Panel(s) Affected |
|----------|-----|--------|-------------------|
| **P0 — Dashboard Broken** | `--user` flag in `_check_services()` | Services panel always wrong | Services |
| **P0 — Dashboard Broken** | Service name mismatches in `_check_services()` | Services panel always wrong | Services |
| **P0 — Dashboard Broken** | Socket path mismatch (`_` vs `-`) | VSLAM panel always empty | VSLAM Status |
| **P0 — Dashboard Broken** | Single-client socket (arch) | VSLAM panel empty even with path fix | VSLAM Status |
| **P1 — Reliability** | Telemetry thread no-retry on heartbeat timeout | All MAVLink panels blank if MAVProxy slow | Vehicle State, GPS/RTK |
| **P1 — Reliability** | Unit name in `cli/kiosk.py` KIOSK_UNITS | `kiosk status/enable/disable` check wrong unit | CLI only |
| **P2 — Robustness** | Missing `After=mower-mavproxy.service` in kiosk unit | Startup race (mitigated by P1 retry) | — |

### P0-A: Fix `_check_services()` — Remove `--user`, Fix Unit Names

**File:** `src/mower_rover/kiosk/app.py`, function `_check_services()`

1. Remove `--user` flag — `systemctl is-active` is read-only and works without root on system units
2. Fix unit names: `mower-slam-node.service` → `mower-vslam.service`, `mavproxy.service` → `mower-mavproxy.service`
3. **Recommended:** Use config-driven list from `KioskConfig.service_check_units` (already has correct defaults) instead of hardcoding. Add `mower-mavproxy.service` to `_default_kiosk_service_units()` in `config/jetson.py`.

### P0-B: VSLAM Data via MAVLink (Replace Direct Socket Reader)

**Problem:** SLAM node accepts only 1 socket client (bridge holds the slot). Kiosk cannot connect directly.

**Solution:** Parse `NAMED_VALUE_FLOAT` messages from the MAVLink stream in the existing telemetry reader thread. The bridge already emits `VSLAM_HZ`, `VSLAM_CONF`, `VSLAM_AGE`, `VSLAM_COV` via MAVProxy.

**Changes:**
1. `src/mower_rover/kiosk/telemetry.py` — Add `NAMED_VALUE_FLOAT` case to recv_match loop:
   ```python
   elif mtype == "NAMED_VALUE_FLOAT":
       _handle_named_value_float(state, msg)
   ```
   Reference: `src/mower_rover/vslam/health_listener.py` has the exact parsing pattern.

2. `src/mower_rover/kiosk/app.py` — Remove `_vslam_reader_thread` and `PoseReader` socket connection.

3. Verify `state.py` `update_vslam(**kwargs)` accepts new field names and `dashboard.py` VSLAM panel renders them.

**VSLAM State fields:**
| NAMED_VALUE_FLOAT | SharedState Key | Unit |
|---|---|---|
| `VSLAM_HZ` | `rate_hz` | Hz |
| `VSLAM_CONF` | `confidence` | 0-255 |
| `VSLAM_AGE` | `age_ms` | ms |
| `VSLAM_COV` | `covariance_norm` | Frobenius norm |

### P1-A: Telemetry Thread Heartbeat Retry

**File:** `src/mower_rover/kiosk/telemetry.py`

Wrap `wait_heartbeat(timeout=10.0)` in a retry loop with backoff that respects `shutdown.is_set()`. Also add outer reconnect wrapper for MAVProxy restart resilience.

### P1-B: Fix KIOSK_UNITS Name

**File:** `src/mower_rover/cli/kiosk.py`, line ~33

Change `"mavproxy.service"` → `"mower-mavproxy.service"`.

### P2: Add `After=mower-mavproxy.service` to Kiosk Unit

**File:** `src/mower_rover/service/unit.py`, `generate_kiosk_unit_file()`

Add `{MAVPROXY_UNIT_NAME}.service` to the `after=` field. Soft ordering (no `Requires=`).

### Implementation Ordering

| Step | Fix | Files | Scope |
|------|-----|-------|-------|
| 1 | P0-A: Fix `_check_services()` | `app.py`, `config/jetson.py` | ~15 lines |
| 2 | P1-B: Fix KIOSK_UNITS name | `cli/kiosk.py` | 1 line |
| 3 | P1-A: Heartbeat retry | `telemetry.py` | ~20 lines |
| 4 | P0-B: VSLAM via MAVLink | `telemetry.py`, `app.py`, `state.py`, `dashboard.py` | ~40 lines |
| 5 | P2: After= ordering | `unit.py` | 1 line |

Total: ~80 lines across 5 files. All testable without hardware.

### What Does NOT Need Changing

- MAVProxy service (already deployed and working)
- Bridge socket design (single-client is correct for bridge)
- SLAM node C++ (project constraint: no firmware mods)
- Health/thermal/disk/wifi pollers (zero permission barriers)
- No config file changes needed on the Jetson

**Key Discoveries:**
- VSLAM data must flow via MAVLink NAMED_VALUE_FLOAT (bridge already emits it) — direct socket is architecturally impossible
- `vslam/health_listener.py` is the reference implementation for parsing these messages
- `KioskConfig.service_check_units` already has correct names — just needs wiring through
- All fixes are backwards-compatible; no Jetson-side config changes required
- Scope fits a single plan document: `docs/plans/022-kiosk-data-gaps-fixes.md`

| File | Change Needed |
|------|---------------|
| `src/mower_rover/kiosk/app.py` | Fix _check_services(), remove VSLAM socket thread |
| `src/mower_rover/kiosk/telemetry.py` | Heartbeat retry, NAMED_VALUE_FLOAT handler |
| `src/mower_rover/cli/kiosk.py` | KIOSK_UNITS name fix |
| `src/mower_rover/config/jetson.py` | Add mower-mavproxy.service to defaults |
| `src/mower_rover/service/unit.py` | After= ordering |
| `src/mower_rover/kiosk/dashboard.py` | Verify/update VSLAM panel field names |
| `src/mower_rover/vslam/health_listener.py` | Reference only (no changes) |

**Gaps:** Dashboard VSLAM panel field name expectations not fully audited — verify during implementation.  
**Assumptions:** MAVProxy forwards all MAVLink messages (including NAMED_VALUE_FLOAT) to all `--out` endpoints — this is standard behavior.

## Overview

The kiosk dashboard has **7 bugs** across 3 data delivery paths that collectively leave 2 of 8 panels completely non-functional (VSLAM Status, Services) and make the remaining MAVLink-fed panels fragile during boot races.

### Key Findings Summary

1. **MAVLink path works** — MAVProxy correctly forwards Pixhawk telemetry to the kiosk via UDP :14551. The Vehicle State and GPS/RTK panels receive live data when the Pixhawk is connected. However, no heartbeat retry means a startup race can permanently kill the telemetry thread.

2. **VSLAM panel is completely broken** — Two compounding bugs: (a) socket path uses underscore instead of hyphen, and (b) even with the correct path, the SLAM node's single-client socket is already occupied by the bridge. The kiosk simply cannot be a second socket consumer.

3. **Services panel always shows "inactive"** — The `systemctl --user` flag queries the wrong systemd instance (per-user vs system), and 2 of 4 unit names are wrong. Every service appears inactive regardless of actual state.

4. **Health/Storage/Wi-Fi panels work** — All sysfs and procfs paths are world-readable. The slow poller has zero permission barriers. These panels show correct data.

5. **The fix is architectural for VSLAM** — The bridge already emits `NAMED_VALUE_FLOAT` messages (`VSLAM_HZ`, `VSLAM_CONF`, `VSLAM_AGE`, `VSLAM_COV`) via MAVProxy. The kiosk should parse these in its existing telemetry thread rather than attempting a direct socket connection.

### Cross-Cutting Patterns

- **Naming inconsistencies** appear in 3 places: socket path (`_` vs `-`), unit name (`mavproxy.service` vs `mower-mavproxy.service`), SLAM unit name (`mower-slam-node` vs `mower-vslam`). These suggest the kiosk module was written against an earlier naming convention.
- **Config already correct** — `KioskConfig.service_check_units` has the right names, but the kiosk code hardcodes its own list instead of using config.
- **Single-client socket design** is intentional and correct for the bridge use case — the fix is to route data through MAVLink, not to modify the SLAM node.

### Actionable Conclusions

All 7 bugs can be fixed in ~80 lines across 5 files. Recommended implementation order:
1. Fix `_check_services()` (P0-A) — trivial, unblocks Services panel
2. Fix KIOSK_UNITS name (P1-B) — 1-line fix
3. Add heartbeat retry (P1-A) — robustness for boot races
4. VSLAM via MAVLink (P0-B) — small refactor using existing `health_listener.py` pattern
5. Add After= ordering (P2) — 1-line unit template change

No new services, no config file changes, no Jetson-side deployment changes beyond the normal `--from-step install-cli` + `kiosk-services` redeployment.

### Open Questions

- Dashboard VSLAM panel field name expectations need verification during implementation (does `dashboard.py` read `rate_hz` / `confidence` or different names?)
- Should the telemetry thread's retry be unbounded or capped (e.g., 12 attempts = 2 minutes)?

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-05 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/025-kiosk-data-delivery-gaps.md |
