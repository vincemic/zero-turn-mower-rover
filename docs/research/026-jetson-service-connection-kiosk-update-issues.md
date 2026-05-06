---
id: "026"
type: research
title: "Jetson Service Connection & Kiosk Data Update Issues — Remaining Gaps"
status: ✅ Complete
created: "2026-05-05"
current_phase: "4 of 4"
---

## Introduction

Despite completing plan 022 (kiosk data delivery gap fixes), deployed bringup attempts (deploy-022 through deploy-023) still fail at the `vslam-services` step. The VSLAM bridge service times out on `systemctl start` (exceeds both systemd's own timeout and the 60s SSH timeout in bringup), MAVProxy is reported as not-active during probes, and consequently the kiosk dashboard never receives live VSLAM or vehicle-state data. This research investigates root causes of these service startup failures and proposes actionable resolutions.

## Objectives

- Determine why `mower-vslam-bridge.service` times out on start (systemd timeout exceeded + SSH 60s timeout in bringup)
- Determine why `mavproxy_active` probe reports "not active" during bringup — is this a boot ordering issue, a dependency on a missing device, or a unit file bug?
- Investigate whether the VSLAM node itself (`mower-vslam.service`) starts correctly and whether the bridge's dependency on it is correctly expressed
- For each issue, propose minimal, actionable fixes (unit file changes, bringup step adjustments, timeout tuning, or architectural corrections)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | VSLAM Bridge Service Timeout Root Cause | ✅ Complete | Analyze `mower-vslam-bridge.service` unit template, its ExecStart command, dependencies (After=/Requires=), and determine why `systemctl start` hangs — is it waiting on a socket, a device, or the VSLAM node to produce output? Check if the bridge's start is blocked by OAK-D enumeration delays or VSLAM node readiness. Examine Jetson journal logs from prior boots for clues. | 2026-05-05 |
| 2 | MAVProxy Service Startup & Probe Timing | ✅ Complete | Investigate why `mower-mavproxy.service` is not active at probe time: check unit template, device dependency on `/dev/pixhawk`, udev rule interaction, boot ordering vs. when bringup probes run. Determine if the Pixhawk USB device is absent during bringup (powered off or not connected) vs. a genuine service failure. | 2026-05-05 |
| 3 | Bringup SSH Timeout Architecture | ✅ Complete | The bringup step `vslam-services` calls `sudo systemctl start mower-vslam.service mower-vslam-bridge.service` over SSH with a 60s timeout. If the service startup legitimately takes >60s (OAK-D firmware upload + VSLAM initialization), the bringup will always fail. Research: what is the expected cold-start time for the full VSLAM pipeline? Should bringup use `--no-block` or poll with `is-active` instead? What timeout is appropriate? | 2026-05-05 |
| 4 | Remediation Design | ✅ Complete | For each confirmed root cause (phases 1–3), propose the minimal fix: unit file dependency adjustments, bringup step timeout or polling changes, service readiness signaling (sd_notify / Type=notify), or splitting the start from the verify. Produce an actionable fix summary suitable for handoff to `pch-planner`. | 2026-05-05 |

## Phase 1: VSLAM Bridge Service Timeout Root Cause

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Root Cause: `Type=notify` Timeout Mismatch

The `mower-vslam-bridge.service` is generated as `Type=notify` but has **no explicit `TimeoutStartSec`**, defaulting to systemd's 90s. However, the bridge's startup path (`run_bridge()`) must complete several blocking operations before it can send `READY=1`:

### Critical Path Before `sd_notify("READY=1")`

```python
# bridge.py — run_bridge() startup sequence:
cfg = load_vslam_config(...)              # Fast — read YAML
reader = PoseReader(cfg.socket_path)       # Fast — store path only
with open_link(conn_cfg) as conn:          # ← BLOCKING: MAVLink connection
    check_and_deploy_lua(conn)             # ← BLOCKING: FTP to Pixhawk
    _notifier.notify("READY=1")           # ← Only AFTER both above complete
```

### `open_link()` Worst-Case Timing

The bridge's `ConnectionConfig` is:
```python
ConnectionConfig(
    endpoint="/dev/pixhawk",      # USB serial via udev symlink
    heartbeat_timeout_s=30.0,     # 30s per attempt
    retry_attempts=5,             # 5 retries
    retry_backoff_s=2.0,          # backoff × attempt_number
)
```

`open_link()` retry loop (from `connection.py`):
- Each attempt: `mavutil.mavlink_connection(...)` + `wait_heartbeat(timeout=30s)`
- On failure: `time.sleep(retry_backoff_s * attempt)` = 2s, 4s, 6s, 8s
- **Worst case: 5×30 + (2+4+6+8) = 170s** before raising `ConnectionError`
- **Best case (Pixhawk responds on first attempt):** ~1-5s

If the Pixhawk USB device is present but slow to produce a heartbeat (just powered on, still initializing), the bridge could spend 30-60s on the first attempt alone.

### `check_and_deploy_lua()` Additional Time

After `open_link` succeeds, the bridge performs MAVLink FTP operations:
1. `ftp.list_directory("/APM/scripts/")` — list SD card
2. `ftp.read_file(remote_path)` — download existing Lua script
3. Compare versions
4. Potentially upload new script

MAVLink FTP over USB is relatively fast (~1-5s total), but adds to the pre-READY budget.

### Unit Template Analysis

From `generate_vslam_bridge_unit_file()` in `service/unit.py`:
```python
def generate_vslam_bridge_unit_file(...) -> str:
    exec_start = f"{mower_jetson_path} vslam bridge-run"
    return generate_service_unit(
        description="Mower Rover VSLAM MAVLink bridge daemon",
        exec_start=exec_start,
        after=f"network.target {VSLAM_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
        binds_to=None,              # ← No BindsTo on device or VSLAM
        watchdog_sec=30,
        runtime_directory=None,
        # timeout_start_sec NOT SET → defaults to None → omitted from unit
    )
```

**Generated unit file (system-level):**
```ini
[Unit]
Description=Mower Rover VSLAM MAVLink bridge daemon
After=network.target mower-vslam.service mower-mavproxy.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
ExecStart=/home/vincent/.local/bin/mower-jetson vslam bridge-run
Environment=MOWER_CORRELATION_ID=daemon
User=vincent
WorkingDirectory=/home/vincent
WatchdogSec=30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Missing:**
- `TimeoutStartSec=` — defaults to systemd's 90s
- `BindsTo=dev-pixhawk.device` — bridge won't auto-stop if Pixhawk disconnects
- `Requires=mower-vslam.service` — only `After=`, no hard dependency

### Contrast with VSLAM Unit

The VSLAM service (rtabmap_slam_node) has `timeout_start_sec=300` explicitly — acknowledging that the OAK-D firmware upload + RTAB-Map initialization is slow. The bridge has the same class of problem (MAVLink connection takes time) but lacks the equivalent timeout.

### Deploy Log Evidence

**deploy-022.log (first attempt):**
- `systemctl start` at 02:39:56.811 → returned at 02:39:57.896 (1.08s)
- Error: "Job for mower-vslam-bridge.service failed because a timeout was exceeded"
- **Interpretation:** The bridge had already failed from a **prior boot/start** and was in `start-limit-hit` state. systemd returned the cached failure immediately.

**deploy-023.log (second attempt, ~10 min later):**
- `systemctl start` at 02:49:13 → SSH timed out after 60s
- Error: "ssh timed out after 60s: sudo systemctl start mower-vslam.service mower-vslam-bridge.service"
- **Interpretation:** After the `StartLimitIntervalSec=300` expired, systemd allowed a fresh start attempt. The bridge was legitimately trying to connect but couldn't send `READY=1` within 60s (the SSH timeout, not systemd's timeout). The bringup SSH layer killed the connection before systemd's 90s limit.

### Secondary Issue: No `systemctl reset-failed` Before Start

The bringup function `_run_vslam_services()` does:
1. Cleanup stale user-level units ✓
2. Install VSLAM service (writes unit, daemon-reload, enable) ✓
3. Install bridge service (writes unit, daemon-reload, enable) ✓
4. `sudo systemctl start mower-vslam.service mower-vslam-bridge.service` — **without reset-failed**

If the bridge is in `failed` state from a prior attempt with start-limit-hit active, the start will immediately fail without retrying.

### Pixhawk/Device Availability During Bringup

From deploy-022 probes:
- `pixhawk_symlink` → PASS: `/dev/pixhawk -> /dev/ttyACM0`
- `vslam_process` → PASS: `mower-vslam.service is active`

Both prerequisites are met. The bridge failure is NOT due to missing hardware — it's a timing/timeout configuration issue.

**Key Discoveries:**
- The `mower-vslam-bridge.service` uses `Type=notify` but has NO `TimeoutStartSec` set — defaulting to systemd's 90s — while the bridge's startup requires up to 170s worst case to connect to the Pixhawk and send `READY=1`
- The `open_link()` connection to `/dev/pixhawk` uses 5 retries × 30s heartbeat timeout + exponential backoff = up to 170s before the sd_notify can fire
- The bringup SSH timeout is 60s (even less than systemd's 90s), creating a double-timeout trap: SSH gives up before systemd does
- The bringup does NOT run `systemctl reset-failed` before starting, so a previously-failed bridge (start-limit-hit) cannot be restarted within the 300s StartLimitIntervalSec window
- Deploy-022 failed immediately (1s) due to start-limit-hit from a prior failed start; deploy-023 timed out at SSH layer (60s) during a fresh start attempt
- Both the Pixhawk device AND the VSLAM node were confirmed available — hardware is not the issue
- The bridge has `After=mower-vslam.service mower-mavproxy.service` (ordering) but no `Requires=` or `BindsTo=` (hard dependency)
- Plan 009 proposed adding `BindsTo=dev-pixhawk.device` but this was never implemented

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | Unit template generator; `generate_vslam_bridge_unit_file()` omits `timeout_start_sec` and `binds_to` |
| `src/mower_rover/vslam/bridge.py` | Bridge daemon; `run_bridge()` shows blocking startup path before sd_notify |
| `src/mower_rover/mavlink/connection.py` | `open_link()` retry logic; worst-case 170s before yielding connection |
| `src/mower_rover/vslam/ipc.py` | `PoseReader` with reconnect loop; not blocking at startup |
| `src/mower_rover/vslam/lua_deploy.py` | `check_and_deploy_lua()` adds FTP time after connection |
| `src/mower_rover/config/data/vslam_defaults.yaml` | Bridge config: `serial_device: /dev/pixhawk` |
| `src/mower_rover/cli/bringup.py` | `_run_vslam_services()` starts with 60s SSH timeout, no reset-failed |

**Gaps:** None identified  
**Assumptions:** systemd default `TimeoutStartSec` for `Type=notify` is 90s (standard for systemd ≥230; JetPack 6 runs systemd 249+)

## Phase 2: MAVProxy Service Startup & Probe Timing

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Root Cause: `install-cli` Destroys MAVProxy Binary

The `mower-mavproxy.service` reports "not active" during the bringup probe (step 15) because the **`install-cli` step (step 14) destructively wipes the shared uv tool venv**, removing MAVProxy which was pip-installed into that same venv by a prior `install-mavproxy` run (step 21).

### Confirmed Timeline (from Jetson journal, this boot)

```
22:44:21 EDT  MAVProxy service starts at boot (already enabled from prior deploy)
22:44:21 EDT  FAILS: "Failed to locate executable .../mavproxy.py: No such file or directory"
              (binary was removed by install-cli's `uv tool install --force`)
22:44:21-47   5× restart attempts → all fail EXEC (binary missing) → start-limit-hit
22:50:48 EDT  StartLimitIntervalSec expired → retries
22:50:48 EDT  FAILS: "ModuleNotFoundError: No module named 'future'"
              (binary restored but dependencies incomplete)
22:51:38 EDT  SUCCESS — MAVProxy finally starts (after `future` module installed)
```

### Why the Probe Reports "not active" at Step 15

The bringup step order reveals a **destructive interaction between steps**:

| Step | Name | Effect on MAVProxy |
|------|------|--------------------|
| 14 | `install-cli` | `uv tool install --python 3.11 --force ~/wheel[jetson]` — **wipes entire tool venv**, removing `mavproxy.py` and all pip-installed packages |
| 15 | `verify` (probe) | Runs `mower-jetson probe --json` → `mavproxy_active` check → **reports "not active"** (correctly — binary is gone) |
| 16-18 | vslam-config, service, vslam-db-check | No effect on MAVProxy |
| 19 | `vslam-services` | **ABORTS HERE** (bridge timeout — Phase 1 issue) |
| 20 | `pixhawk-sync` | Never reached |
| 21 | `install-mavproxy` | Would reinstall MAVProxy + `future` + `setuptools` — **never reached** |

### The Shared Venv Problem

MAVProxy is installed via `uv pip install --python ~/.local/share/uv/tools/mower-rover/bin/python MAVProxy future setuptools` — this adds packages to the **same venv** that `uv tool install --force mower-rover` manages. The `--force` flag destroys the venv contents and recreates it with only `mower-rover[jetson]` dependencies.

**This means every time `install-cli` runs, MAVProxy's binary and dependencies are deleted.** The MAVProxy service (already enabled from a prior deploy) immediately enters a failure loop.

### Unit File Analysis (Confirmed via SSH)

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

**Missing from unit:**
- `BindsTo=dev-pixhawk.device` — service won't auto-stop if Pixhawk disconnected
- `After=dev-pixhawk.device` — no ordering guarantee for device availability
- `ExecStartPre=` check for binary existence — would give clearer failure message

**However:** The Pixhawk device IS present and NOT the cause of failure. Confirmed:
- `/dev/pixhawk -> ttyACM0` (symlink present)
- USB device `2dae:1011` enumerated on Bus 001
- udev rule `90-pixhawk-usb.rules` working correctly with `TAG+="systemd"`

### Why It Eventually Self-Heals

The service has `Restart=always` and `StartLimitIntervalSec=300`. After the `install-mavproxy` step reinstalls the binary + dependencies, the next systemd restart attempt succeeds. In today's case:
- 22:44 → start-limit-hit (binary missing)
- 22:50 → retry (binary back but `future` missing)
- 22:51 → success (all deps installed)

### The Probe Severity Is Only WARNING

The `mavproxy_active` check in `probe/checks/kiosk.py` is registered as `severity=Severity.WARNING`, meaning the verify step (step 15) does NOT abort bringup. It correctly reports the warning and continues. **The probe failure is cosmetic/informational at this stage** — it's not blocking the deploy.

### True Blocker

The bringup fails at step 19 (VSLAM bridge timeout, Phase 1), which means step 21 (`install-mavproxy`) is **never reached**. If the Phase 1 bridge timeout issue is fixed, MAVProxy installation will complete normally and the service will be active for subsequent probes.

**Key Discoveries:**
- `install-cli` (step 14) runs `uv tool install --force` which wipes the shared venv, destroying MAVProxy's binary and dependencies installed by a prior `install-mavproxy` step
- The probe at step 15 correctly reports "not active" — MAVProxy's binary literally doesn't exist at that point
- The `install-mavproxy` step (step 21) that would fix this is never reached because bringup aborts at step 19 (bridge timeout)
- This is NOT a device/hardware issue — Pixhawk is present (`/dev/pixhawk -> ttyACM0`)
- The probe severity is WARNING (non-blocking), so the "not active" report doesn't abort bringup
- The unit lacks `BindsTo=dev-pixhawk.device` (proposed in plan 009, never implemented) but this isn't the current failure cause
- MAVProxy self-heals after `StartLimitIntervalSec` expires, but only if the binary exists by then
- The fundamental issue is **two steps sharing a single venv with destructive install semantics**

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/bringup.py` line 980 | `uv tool install --force` wipes shared venv |
| `src/mower_rover/cli/bringup.py` line 1600 | `uv pip install ... MAVProxy future setuptools` into same venv |
| `src/mower_rover/service/unit.py` line 429 | `_MAVPROXY_UNIT_TEMPLATE` — Type=simple, no device deps |
| `src/mower_rover/probe/checks/kiosk.py` line 51 | `mavproxy_active` check — WARNING severity |
| `scripts/90-pixhawk-usb.rules` | udev rule creating `/dev/pixhawk` symlink with `TAG+="systemd"` |
| `/etc/systemd/system/mower-mavproxy.service` (on Jetson) | Deployed unit — confirmed no device deps |

**Gaps:** None — confirmed all findings via live SSH to Jetson  
**Assumptions:** None — all verified on running system

## Phase 3: Bringup SSH Timeout Architecture

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Three-Layer Timeout Stack

The service start command passes through **three independent timeout mechanisms**, creating a race condition:

| Layer | Timeout | Behavior on Expiry |
|-------|---------|-------------------|
| **Bringup SSH** | 60s (`client.run(..., timeout=60)`) | Python kills local SSH process; bringup raises `typer.Exit(3)` |
| **systemd TimeoutStartSec** | 90s (default, bridge has no override) | systemd sends SIGTERM to bridge process |
| **systemd TimeoutStopSec** | 90s (default) | systemd sends SIGKILL after SIGTERM ignored |

**Result:** The SSH layer gives up first (60s), bringup aborts, but `systemctl start` **continues running on the Jetson** because killing the SSH client doesn't kill the remote process. The bridge keeps retrying until systemd kills it at 180s total.

### Confirmed Cold-Start Timelines (from Jetson journal)

**VSLAM node (rtabmap_slam_node) — Type=notify:**
```
22:44:21  systemd starts service
22:44:22  Config loaded, socket listening (/run/mower/vslam-pose.sock)
22:44:27  OAK-D device opened + pipeline started (firmware upload ~5s)
22:44:27  IR projector + flood LED configured
22:44:33  First SLAM frame processed (RTAB-Map vocabulary loaded)
~22:44:33 sd_notify("READY=1") sent (after create_slam_engine completes)
```
**VSLAM node total startup: ~12s** (socket at 1s, OAK-D at 6s, RTAB-Map ready at 12s)

The `sd_notify("READY=1")` is sent after: DepthAI pipeline creation + RTAB-Map engine initialization. This takes ~12s on cold start (dominated by RTAB-Map vocabulary/database loading from NVMe).

**VSLAM bridge — Type=notify, depends on MAVProxy:**
```
22:44:33  Bridge starts, endpoint=udp:127.0.0.1:14550
22:44:34  Attempt 1 starts
22:45:18  Attempt 1 fails (30s heartbeat timeout — MAVProxy dead)
22:45:20  Attempt 2 starts (2s backoff)
22:45:50  Attempt 2 fails
22:45:54  Attempt 3 starts (4s backoff)
22:46:03  *** systemd TimeoutStartSec (90s) fires → SIGTERM ***
22:46:24  Attempt 3 still running (bridge ignores SIGTERM!)
22:47:33  *** systemd SIGKILL (90s after SIGTERM) ***
```

**Bridge with healthy MAVProxy:**
If MAVProxy is running and forwarding heartbeats from Pixhawk:
- Attempt 1 connects in 1-5s
- `check_and_deploy_lua()`: 1-5s (MAVLink FTP)
- `sd_notify("READY=1")`: fires at 5-10s total
- **Expected: 5-15s**

**Bridge with slow MAVProxy (just started):**
- Attempt 1 might timeout (30s — MAVProxy still connecting to Pixhawk)
- Attempt 2 succeeds after 2s backoff + 1-5s connection
- **Expected: 35-40s**

**Bridge with dead MAVProxy (current situation):**
- All 5 attempts timeout: 5×30 + (2+4+6+8) = 170s
- **Guaranteed timeout — exceeds ALL three timeout layers**

### Why the Bridge Depends on MAVProxy

The `install-mavproxy` step (step 21) rewrites `/etc/mower/vslam.yaml` to use:
```yaml
bridge:
  serial_device: udp:127.0.0.1:14550
```

This means the bridge connects to MAVProxy's UDP output port instead of directly to `/dev/pixhawk`. The architectural dependency is:

```
Pixhawk (/dev/pixhawk)
    ↓ serial
MAVProxy (--master=/dev/pixhawk --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551)
    ↓ udp:14550
VSLAM Bridge (mower-jetson vslam bridge-run)
    ↓ udp:14551
Kiosk / other consumers
```

But systemd only has `After=mower-mavproxy.service` (ordering) — no `Requires=` or `BindsTo=`. If MAVProxy failed to start (binary missing), systemd still starts the bridge.

### SSH Timeout Behavior (subprocess.run)

The `client.run()` method in `transport/ssh.py` uses:
```python
proc = subprocess.run(argv, timeout=timeout, ...)
```

When `TimeoutExpired` is raised:
- Python **kills the local SSH process** (`proc.kill()` internally)
- The **remote `systemctl start` continues running** on the Jetson
- The SSH session drops, but `systemctl` is a direct child of systemd — it doesn't die with SSH
- This is a **fire-and-forget** situation: bringup reports failure, but the Jetson service may eventually start successfully

### Signal Handling Deficiency in Bridge

The journal shows the bridge **ignores SIGTERM** during the connection retry loop:
```
22:46:03  systemd sends SIGTERM
22:46:24  Bridge still retrying (attempt 3 in progress)
22:47:33  systemd sends SIGKILL (90s later)
```

The bridge doesn't exit cleanly on SIGTERM while inside `open_link()`. This makes the stop-sigterm → SIGKILL escalation take the full 90s additional seconds.

### The Cascade Failure (Complete Picture)

Combining findings from all three phases:

```
Step 14: install-cli
    → uv tool install --force → MAVProxy binary deleted
    → MAVProxy service crashes → start-limit-hit (within 30s)

Step 15: verify probe
    → mavproxy_active: "not active" (WARNING, non-blocking)

Step 19: vslam-services
    → systemctl start mower-vslam.service mower-vslam-bridge.service
    → VSLAM node starts OK (~12s to READY=1)
    → Bridge starts, connects to udp:14550 → no heartbeat (MAVProxy dead)
    → SSH timeout at 60s → bringup ABORTS
    → Bridge continues retrying on Jetson → systemd kills at 180s

Step 21: install-mavproxy (NEVER REACHED)
    → Would have reinstalled MAVProxy + started it
    → Would have enabled bridge to connect successfully
```

### Appropriate Timeout Values

| Service | Expected Startup (healthy) | Worst Case (degraded) | Recommended TimeoutStartSec |
|---------|---------------------------|----------------------|---------------------------|
| VSLAM node | 12s | 30s (slow NVMe/large DB) | 300s (already set) |
| VSLAM bridge | 5-15s | 35-40s (slow Pixhawk) | 120s |
| SSH for `systemctl start` (both) | 15-20s | 50-60s | Not applicable — see below |

### Should Bringup Use `--no-block` + Poll?

**Yes.** The correct pattern for long-startup services is:

1. `sudo systemctl start --no-block mower-vslam.service mower-vslam-bridge.service` — returns immediately
2. Poll `systemctl is-active` every 5s with a total budget of 120-180s
3. Report progress to operator during polling
4. If still not active after budget, check `systemctl status` for error details

This decouples the SSH session timeout from the service startup timeout and gives the operator feedback during the wait.

**Key Discoveries:**
- The bringup SSH timeout (60s) is shorter than systemd's timeout (90s), creating a layered failure where bringup gives up first
- The remote `systemctl start` continues running on the Jetson after SSH drops — it's fire-and-forget
- VSLAM node cold-start takes ~12s (confirmed from journal: config→OAK-D→RTAB-Map→READY=1)
- VSLAM bridge cold-start takes 5-15s with healthy MAVProxy, but **infinitely times out** if MAVProxy is dead
- The bridge ignores SIGTERM during connection retries — doesn't exit cleanly until SIGKILL (90s later)
- The cascade failure is: `install-cli` kills MAVProxy → bridge can't connect → timeout → bringup aborts before `install-mavproxy` can fix it
- The `udp:127.0.0.1:14550` endpoint creates an undeclared runtime dependency on MAVProxy
- `--no-block` + polling is the correct pattern for the bringup start command

| File | Relevance |
|------|-----------|
| `src/mower_rover/transport/ssh.py` line 139-161 | SSH `run()` method — 60s default timeout, kills local process only |
| `src/mower_rover/cli/bringup.py` line 1484 | `client.run(["sudo systemctl start ..."], timeout=60)` |
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` line 848 | `sd_notify("READY=1")` after pipeline + RTAB-Map init |
| `src/mower_rover/vslam/bridge.py` | Bridge lacks SIGTERM handler during `open_link()` |
| Jetson journal (`journalctl -b -u mower-vslam-bridge.service`) | Confirms 90s timeout + SIGTERM ignored + SIGKILL |

**Gaps:** None  
**Assumptions:** None — all confirmed via live Jetson journal

## Phase 4: Remediation Design

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Fix Priority Order

The fixes below are ordered by impact. Fix 1 alone unblocks bringup; Fixes 2-5 harden the system for production.

---

### Fix 1 (Critical): Move `install-mavproxy` Before `vslam-services`

**Problem:** `install-cli` (step 14) destroys the MAVProxy binary. `install-mavproxy` (step 21) reinstalls it, but bringup aborts at step 19 before reaching step 21. The bridge depends on MAVProxy via `udp:127.0.0.1:14550`.

**Fix:** Reorder `BRINGUP_STEPS` to place `install-mavproxy` immediately before `vslam-services`:

```python
# Current order (broken):
# 14: install-cli          ← wipes MAVProxy
# 15: verify
# ...
# 19: vslam-services       ← bridge needs MAVProxy → FAILS
# ...
# 21: install-mavproxy     ← too late

# Fixed order:
# 14: install-cli
# 15: verify
# 16: vslam-config
# 17: service (health)
# 18: vslam-db-check
# 19: install-mavproxy     ← moved here (MAVProxy available before bridge)
# 20: vslam-services       ← bridge can now connect to udp:14550
# 21: pixhawk-sync
# 22: kiosk-services
# 23: kiosk-probe
# 24: final-verify
```

**Files to change:** `src/mower_rover/cli/bringup.py` — reorder `BringupStep` entries in the `BRINGUP_STEPS` list.

**Risk:** Low. The `install-mavproxy` step has no dependencies on steps 19-20 (it only needs the uv venv from step 14 and `/dev/pixhawk` from step 12).

---

### Fix 2 (Critical): Add `TimeoutStartSec=120` to Bridge Unit

**Problem:** Bridge has `Type=notify` with no `TimeoutStartSec`, defaulting to 90s. With a slow Pixhawk heartbeat, legitimate startup can take 35-40s. With MAVProxy just starting, it can take 60-70s.

**Fix:** Add `timeout_start_sec=120` to `generate_vslam_bridge_unit_file()`:

```python
def generate_vslam_bridge_unit_file(...) -> str:
    exec_start = f"{mower_jetson_path} vslam bridge-run"
    return generate_service_unit(
        description="Mower Rover VSLAM MAVLink bridge daemon",
        exec_start=exec_start,
        after=f"network.target {VSLAM_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
        binds_to=None,
        watchdog_sec=30,
        runtime_directory=None,
        timeout_start_sec=120,  # ← ADD THIS
    )
```

**Files to change:** `src/mower_rover/service/unit.py` — `generate_vslam_bridge_unit_file()`

---

### Fix 3 (Critical): Add `systemctl reset-failed` Before Start

**Problem:** If the bridge previously failed and hit `start-limit-hit` (within the 300s `StartLimitIntervalSec`), `systemctl start` returns immediately with a cached failure. The bringup doesn't clear this state.

**Fix:** In `_run_vslam_services()`, add `reset-failed` before the start command:

```python
# Before starting, clear any prior failure state
bctx.console.print("  Resetting failed state…")
with contextlib.suppress(SshError):
    client.run(
        ["sudo systemctl reset-failed mower-vslam.service mower-vslam-bridge.service"],
        timeout=10,
    )

bctx.console.print("  Starting VSLAM services…")
# ... existing start code
```

**Files to change:** `src/mower_rover/cli/bringup.py` — `_run_vslam_services()`

---

### Fix 4 (Important): Use `--no-block` + Polling for Service Start

**Problem:** `systemctl start` with `Type=notify` blocks until `READY=1`. The 60s SSH timeout is shorter than the bridge's startup time, creating a race. The SSH timeout kills the local process but the remote `systemctl` keeps running.

**Fix:** Replace the single blocking `systemctl start` call with:

```python
# 1. Start services without waiting
client.run(
    ["sudo systemctl start --no-block mower-vslam.service mower-vslam-bridge.service"],
    timeout=15,
)

# 2. Poll for readiness with progress reporting
import time
deadline = time.time() + 120  # 2 minute budget
while time.time() < deadline:
    time.sleep(5)
    r_vslam = client.run(["systemctl", "is-active", "mower-vslam.service"], timeout=10)
    r_bridge = client.run(["systemctl", "is-active", "mower-vslam-bridge.service"], timeout=10)
    
    if r_vslam.ok and r_bridge.ok:
        bctx.console.print("  [green]Both services active.[/green]")
        return
    
    # Check for hard failure (not just "activating")
    if "failed" in (r_bridge.stdout or ""):
        # Get status for diagnostics
        status = client.run(
            ["systemctl", "status", "mower-vslam-bridge.service", "--no-pager"],
            timeout=10,
        )
        bctx.console.print(f"  [red]Bridge failed:[/red] {status.stdout[:200]}")
        raise typer.Exit(code=3)
    
    bctx.console.print(f"  Waiting… (vslam={'✓' if r_vslam.ok else '…'}, bridge={'✓' if r_bridge.ok else '…'})")

bctx.console.print("  [red]Services did not become active within 120s.[/red]")
raise typer.Exit(code=3)
```

**Files to change:** `src/mower_rover/cli/bringup.py` — `_run_vslam_services()`

---

### Fix 5 (Hardening): Add `Requires=mower-mavproxy.service` to Bridge Unit

**Problem:** The bridge unit only has `After=mower-mavproxy.service` (ordering) but no hard dependency. If MAVProxy fails, systemd still starts the bridge — which will then fail to connect.

**Fix:** Add `requires` parameter to the bridge unit generation:

```python
return generate_service_unit(
    description="Mower Rover VSLAM MAVLink bridge daemon",
    exec_start=exec_start,
    after=f"network.target {VSLAM_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service",
    requires=f"{MAVPROXY_UNIT_NAME}.service",  # ← ADD: hard dependency
    binds_to=None,
    watchdog_sec=30,
    timeout_start_sec=120,
)
```

This ensures systemd won't start the bridge if MAVProxy failed. Note: `generate_service_unit()` may need a new `requires` parameter.

**Files to change:**
- `src/mower_rover/service/unit.py` — add `requires` parameter to `generate_service_unit()` and to `generate_vslam_bridge_unit_file()`
- `tests/test_kiosk_units.py` — update unit file assertions

---

### Fix 6 (Hardening): Add SIGTERM Handler to Bridge

**Problem:** The bridge ignores SIGTERM during `open_link()` retries. systemd sends SIGTERM at TimeoutStartSec, but the bridge continues for 90 more seconds until SIGKILL.

**Fix:** Register a signal handler in `run_bridge()` that sets a shutdown flag, and check it in the connection retry loop:

```python
import signal
import threading

_shutdown_event = threading.Event()

def _sigterm_handler(signum, frame):
    _shutdown_event.set()

signal.signal(signal.SIGTERM, _sigterm_handler)
```

Then in `open_link()` or `ConnectionConfig`, check `_shutdown_event.is_set()` between retries.

**Files to change:** `src/mower_rover/vslam/bridge.py` and/or `src/mower_rover/mavlink/connection.py`

---

### Fix Summary Table

| # | Fix | Root Cause | Severity | Files |
|---|-----|-----------|----------|-------|
| 1 | Move `install-mavproxy` before `vslam-services` | Step ordering — MAVProxy not installed when bridge needs it | Critical | `cli/bringup.py` |
| 2 | Add `timeout_start_sec=120` to bridge unit | Default 90s too short for connection retries | Critical | `service/unit.py` |
| 3 | Add `reset-failed` before service start | Prior failures block restart within 300s window | Critical | `cli/bringup.py` |
| 4 | Use `--no-block` + poll instead of blocking start | SSH timeout (60s) < systemd timeout — race condition | Important | `cli/bringup.py` |
| 5 | Add `Requires=mower-mavproxy.service` to bridge | No hard dependency — bridge starts even if MAVProxy failed | Hardening | `service/unit.py`, tests |
| 6 | Add SIGTERM handler to bridge process | Bridge ignores SIGTERM, delays shutdown by 90s | Hardening | `vslam/bridge.py`, `mavlink/connection.py` |

### Minimum Viable Fix (Unblocks Bringup)

Fixes 1 + 2 + 3 together are sufficient to unblock bringup:
- **Fix 1** ensures MAVProxy is running before the bridge needs it
- **Fix 2** gives the bridge enough time to connect even if Pixhawk is slow
- **Fix 3** clears stale failures from prior attempts

Fix 4 is strongly recommended to eliminate the timeout race entirely.

### Test Plan

- **Unit tests:** Update `test_kiosk_units.py` to assert `TimeoutStartSec=120` in bridge unit output
- **SITL (smoke):** Verify bringup step ordering — `install-mavproxy` executes before `vslam-services`
- **Integration (field):** Full bringup from `install-cli` should complete all 24 steps without timeout

**Key Discoveries:**
- The minimum fix is 3 changes: reorder steps, add timeout, add reset-failed
- The cascade failure is fully explained by step ordering + shared venv destruction
- Fix 4 (--no-block + poll) eliminates the SSH timeout race entirely
- Fix 5 (Requires=) prevents the bridge from starting when MAVProxy is known-dead
- Fix 6 (SIGTERM handler) improves shutdown behavior but isn't the root cause

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/bringup.py` | Step ordering, reset-failed, start command |
| `src/mower_rover/service/unit.py` | Bridge unit template — timeout + requires |
| `src/mower_rover/vslam/bridge.py` | SIGTERM handler |
| `src/mower_rover/mavlink/connection.py` | Shutdown flag check in retry loop |
| `tests/test_kiosk_units.py` | Unit test assertions for generated units |

**Gaps:** None  
**Assumptions:** None — all fixes are based on confirmed root causes from Phases 1-3

## Overview

The bringup failure at the `vslam-services` step is a **cascade failure** caused by a combination of step ordering, shared venv destruction, and missing timeout configuration. The root cause chain is:

1. **`install-cli` (step 14)** runs `uv tool install --force`, which destroys the entire tool venv — including MAVProxy's binary and dependencies that were pip-installed into the same venv by a prior `install-mavproxy` run.

2. **MAVProxy crashes immediately** (binary missing) and enters `start-limit-hit` within 30 seconds.

3. **The VSLAM bridge** (step 19) connects to `udp:127.0.0.1:14550` (MAVProxy's output), but since MAVProxy is dead, it never receives a heartbeat. It retries 5 times × 30s = 150s+ before giving up.

4. **Three timeout layers fire in sequence:** The bringup SSH timeout (60s) kills the SSH session first. systemd's TimeoutStartSec (90s default) sends SIGTERM second. SIGKILL arrives at 180s. The bridge ignores SIGTERM and runs until killed.

5. **Bringup aborts at step 19**, never reaching `install-mavproxy` (step 21) which would have fixed the venv.

### Key Findings Summary

1. The bridge unit has `Type=notify` but no `TimeoutStartSec` — defaults to 90s while worst-case startup is 170s
2. `install-cli` and `install-mavproxy` share a venv with destructive install semantics — `--force` wipes everything
3. Step ordering puts MAVProxy installation (step 21) AFTER the bridge that depends on it (step 19)
4. No `systemctl reset-failed` before start — prior failures permanently block restarts within a 5-minute window
5. The SSH timeout (60s) is shorter than systemd's timeout (90s), creating a race where bringup gives up before systemd does
6. The bridge ignores SIGTERM during connection retries

### Actionable Conclusions

The **minimum fix** to unblock bringup requires three changes:
1. **Reorder** `install-mavproxy` before `vslam-services` in the step list
2. **Add** `timeout_start_sec=120` to the bridge unit template
3. **Add** `systemctl reset-failed` before the start command

For production hardening, also implement:
4. Replace blocking `systemctl start` with `--no-block` + polling
5. Add `Requires=mower-mavproxy.service` to the bridge unit
6. Add SIGTERM handler to the bridge process

### Open Questions

- Should the bridge be restructured to send `READY=1` before MAVLink connection (making it `Type=simple` effectively), then use watchdog for ongoing health? This would eliminate the startup timeout issue entirely but changes the readiness semantics.
- Should MAVProxy be a declared dependency of the mower-rover uv tool (in `pyproject.toml`) rather than a pip-installed add-on? This would prevent `uv tool install --force` from removing it.

## References

- Jetson journal (`journalctl -b -u mower-vslam-bridge.service`) — confirmed timeout + SIGTERM + SIGKILL sequence
- Jetson journal (`journalctl -b -u mower-mavproxy.service`) — confirmed binary-missing failure loop
- deploy-022.log, deploy-023.log — confirmed start-limit-hit and SSH timeout in production deploys
- Plan 009 (`docs/plans/009-jetson-deploy-integration-gaps.md`) — previously proposed `BindsTo=dev-pixhawk.device` (never implemented)

## Follow-Up Research

- Consider whether MAVProxy should be a declared dependency in `pyproject.toml` extras rather than a separate pip install
- Evaluate switching bridge to `Type=simple` with watchdog-only health signaling (eliminates startup timeout entirely)
- Investigate whether `BindsTo=dev-pixhawk.device` (from plan 009) should be added to both MAVProxy and bridge units for disconnect detection

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-05 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/026-jetson-service-connection-kiosk-update-issues.md |
