---
id: "008"
type: research
title: "Jetson MAVLink + Vision + Navigation Component Deployment & Integration Testing"
status: ✅ Complete
created: "2026-04-23"
current_phase: "5 of 5"
---

## Introduction

This research investigates the concrete steps required to deploy the mower_rover MAVLink, VSLAM, and navigation components to the Jetson AGX Orin and begin integration testing against the physical Pixhawk Cube Orange. The Jetson is already provisioned (IP 192.168.4.38, user vincent, SSH key deployed) and the Pixhawk is connected via USB at `/dev/ttyACM0`. The goal is to document what needs to be deployed, how to deploy it, what configuration is required on-device, and how to validate the integration end-to-end.

## Objectives

- Determine the minimal set of Python packages/modules that must be deployed to the Jetson for MAVLink + VSLAM + navigation integration
- Document the deployment mechanism (pip install from laptop via SSH, rsync, editable install, etc.)
- Identify Jetson-side configuration (serial ports, udev rules, DepthAI setup, service files) needed before components can run
- Define a phased integration test sequence: MAVLink heartbeat → VSLAM pipeline → bridge/IPC → health monitoring
- Document rollback and troubleshooting procedures for field use

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Deployment Packaging & Transfer | ✅ Complete | How to build and transfer the mower_rover package to the Jetson; pip/uv install on aarch64; dependency resolution (pymavlink, depthai, numpy, etc.); editable vs wheel install trade-offs | 2026-04-23 |
| 2 | Jetson-Side Prerequisites & Configuration | ✅ Complete | udev rules (Pixhawk USB, OAK-D Pro USB); kernel params (usbcore); serial port permissions; DepthAI v3 setup; pyproject.toml `[jetson]` extras; systemd service units if needed | 2026-04-23 |
| 3 | MAVLink Integration Testing | ✅ Complete | Validate MAVLink connection from Jetson to Pixhawk over USB; heartbeat exchange; param read/write round-trip; mode queries; connection retry logic; `mower-jetson` CLI commands that exercise the mavlink module | 2026-04-23 |
| 4 | VSLAM Pipeline & OAK-D Pro Integration | ✅ Complete | DepthAI device enumeration on Jetson; VSLAM pipeline startup (frames, bridge, IPC); OAK-D Pro USB 2→3 re-enumeration; health listener; Lua deploy for source switching; end-to-end pose output validation | 2026-04-23 |
| 5 | End-to-End Integration & Health Monitoring | ✅ Complete | Combined MAVLink + VSLAM integration path; health monitoring across both subsystems; log collection and structured output; failure modes and rollback; field test readiness checklist | 2026-04-23 |

## Phase 1: Deployment Packaging & Transfer

**Status:** ✅ Complete  
**Session:** 2026-04-23

### 1. Package Structure & Build System

The project uses **Hatchling** as the build backend with a `src` layout:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mower_rover"]
```

The single `mower_rover` package contains all modules for both laptop and Jetson CLIs. Two entry points are defined:

```toml
[project.scripts]
mower = "mower_rover.cli.laptop:app"
mower-jetson = "mower_rover.cli.jetson:app"
```

Both CLIs share the same library package — installing it anywhere makes both commands available.

### 2. Dependency Groups

**Core dependencies** (installed everywhere):

| Package | Type | aarch64 Status |
|---------|------|----------------|
| `typer>=0.12` | Pure Python | No issues |
| `rich>=13.7` | Pure Python | No issues |
| `structlog>=24.1` | Pure Python | No issues |
| `pymavlink>=2.4.40` | C ext (lxml) | May need `libxml2-dev libxslt-dev` for source build |
| `pyubx2>=1.2.45` | Pure Python | No issues |
| `shapely>=2.0` | C ext | `manylinux_2_17_aarch64` wheel bundles GEOS |
| `pyproj>=3.6` | C ext | `manylinux_2_17_aarch64` wheel bundles PROJ |
| `pyyaml>=6.0` | C ext (optional) | `manylinux_2_17_aarch64` wheel |

**Jetson extras** (`[project.optional-dependencies].jetson`):

| Package | Type | aarch64 Status |
|---------|------|----------------|
| `sdnotify>=0.3` | Pure Python | No issues |
| `depthai>=3.5.0` | C ext (~76 MB) | `manylinux_2_28_aarch64` wheel confirmed in `uv.lock` |

**Transitive dependencies of note:**
- **numpy** (via pymavlink and depthai): publishes `cp311-manylinux_2_28_aarch64` wheels. No cp310 wheel — Python 3.11+ is mandatory.
- **lxml** (via pymavlink): publishes aarch64 manylinux wheels, but `libxml2-dev libxslt-dev` apt packages provide insurance for source fallback.

### 3. Existing Deployment Mechanism: `mower jetson bringup`

The project already has a fully automated deployment pipeline in `src/mower_rover/cli/bringup.py` that runs from the laptop over SSH. The bringup sequence:

1. **check-ssh** — Verify SSH connectivity to the Jetson
2. **harden** — Push and execute `scripts/jetson-harden.sh` (udev rules, kernel params, etc.)
3. **install-uv** — Install `uv` on Jetson via `curl | sh`, then `uv python install 3.11`
4. **install-cli** — Build wheel locally, push via scp, install remotely via `uv tool install`
5. **verify** — Run `mower-jetson probe --json` remotely
6. **service** — Install and start `mower-health.service`

The **install-cli** step:

```python
# Step 1: Build wheel locally on laptop
subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_dir)],
               cwd=bctx.project_root, ...)

# Step 2: Push .whl to Jetson via scp
client.push(whl, f"~/{whl_name}")

# Step 3: Install on Jetson using uv tool install
client.run([
    f"~/.local/bin/uv tool install --python 3.11 --force"
    f" --with sdnotify ~/{whl_name}",
], timeout=300)

# Step 4: Cleanup
client.run(["rm", "-f", f"~/{whl_name}"], timeout=10)
```

### 4. Critical Gap: depthai Not Included in Current Deployment

The current bringup install-cli step uses `--with sdnotify` but does **NOT** include `--with depthai`. This means the currently deployed `mower-jetson` CLI does not have the `depthai` package available — VSLAM and OAK-D Pro modules will fail at runtime.

To deploy the full MAVLink + VSLAM + navigation stack, the install command should use the `[jetson]` extras group:

```bash
~/.local/bin/uv tool install --python 3.11 --force \
    '~/{whl_name}[jetson]'
```

The `[jetson]` extras group already includes both `sdnotify>=0.3` and `depthai>=3.5.0`, making the explicit `--with` flags redundant.

### 5. Wheel vs Editable Install Trade-offs

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **Wheel via `uv tool install`** (current) | Clean isolation; entry points symlinked; repeatable; no source needed on Jetson | Requires rebuild + push for every code change; ~76 MB depthai wheel transfer | **Use for production/field** |
| **Editable install** (`uv tool install -e`) | Code changes take effect without reinstall | Requires full source on Jetson; `uv tool install` doesn't support `-e` for tool installs | Not suitable for tool installs |
| **rsync + venv** | Fast incremental sync; only changed files transfer | Manual venv management; no entry point symlinks; not the project convention | Only for dev iteration |
| **git clone + `uv tool install` from source** | Source available for debugging; can `git pull` for updates | Larger footprint; requires git on Jetson; internet for `git clone` | Alternative for initial setup |

**Recommended approach:** Continue with the existing wheel-based `uv tool install` pattern, but add the `[jetson]` extras.

### 6. Transfer Mechanism Details

The SSH transport layer (`src/mower_rover/transport/ssh.py`) supports:
- **`push(local_path, remote_path)`** — scp laptop → Jetson (used for wheel transfer)
- **`pull(remote_path, local_path)`** — scp Jetson → laptop (used for log retrieval)
- **`run(remote_argv)`** — execute remote commands via ssh

These use the system `ssh`/`scp` binaries (no paramiko dependency). The Jetson endpoint is resolved from CLI flags → env vars → `laptop.yaml` config.

### 7. Wheel Size and Transfer Time

The `mower_rover` wheel itself is small (pure Python + bundled YAML/Lua data files). However, `depthai>=3.5.0` is ~76 MB. On the local network (GbE), this transfers in seconds. But `uv tool install` **downloads** depthai from PyPI on the Jetson side — so the Jetson needs **internet access during initial install**. Subsequent deploys only transfer the small mower_rover wheel (deps are cached by uv).

### 8. Update/Redeploy Procedure

```bash
# On laptop (builds and pushes wheel)
mower jetson bringup --step install-cli

# For the full VSLAM stack:
ssh vincent@192.168.4.38 '~/.local/bin/uv tool install --python 3.11 --force ~/mower_rover-0.1.0-py3-none-any.whl[jetson]'
```

### 9. Bundled Data Files

The wheel includes bundled data files via the `src/mower_rover` package structure:
- `config/data/vslam_defaults.yaml` — default VSLAM configuration
- `params/data/z254_baseline.yaml` — baseline parameter set
- `params/data/z254_r3_vslam_delta.yaml` — VSLAM delta parameters
- `params/data/ahrs-source-gps-vslam.lua` — Lua script deployed to Pixhawk SD card

These are accessed via `importlib.resources` at runtime and are correctly included in the wheel by Hatchling's `packages = ["src/mower_rover"]` directive.

**Key Discoveries:**
- The project already has a fully automated bringup pipeline (`mower jetson bringup`) that builds a wheel on the laptop, pushes it via scp, and installs via `uv tool install` on the Jetson
- **Critical gap:** The current install command uses `--with sdnotify` but NOT `--with depthai` — the VSLAM stack won't have depthai available at runtime
- The `[jetson]` extras group in pyproject.toml already bundles both `sdnotify` and `depthai>=3.5.0` — the bringup install command should use `[jetson]` extras instead of explicit `--with` flags
- DepthAI 3.5.0 has a confirmed prebuilt `manylinux_2_28_aarch64` wheel (~76 MB) in the uv.lock — no source compilation needed
- All core dependencies have aarch64 wheels for Python 3.11+; only pymavlink's lxml dependency might need `libxml2-dev libxslt-dev` as build insurance
- uv tool install creates an isolated venv in `~/.local/share/uv/tools/` with entry points symlinked to `~/.local/bin/`
- The Jetson needs internet during initial install (to download depthai from PyPI); subsequent updates only transfer the small mower_rover wheel
- Python 3.11+ is mandatory on the Jetson (JetPack ships 3.10; uv-managed 3.11 is already installed by the bringup pipeline)

| File | Relevance |
|------|-----------|
| `pyproject.toml` | Package definition, dependencies, entry points, jetson extras |
| `src/mower_rover/cli/bringup.py` | Automated bringup pipeline with wheel build + push + install |
| `src/mower_rover/cli/jetson.py` | Jetson-side CLI entry point |
| `src/mower_rover/cli/jetson_remote.py` | Laptop-side SSH commands |
| `src/mower_rover/transport/ssh.py` | SSH/SCP transport layer |
| `src/mower_rover/config/laptop.py` | JetsonEndpoint dataclass (host, user, port, key_path) |
| `src/mower_rover/config/jetson.py` | Jetson-side config (XDG paths, service settings) |
| `src/mower_rover/vslam/bridge.py` | VSLAM-to-MAVLink bridge daemon |
| `scripts/jetson-harden.sh` | Field hardening script |

**Gaps:**
- The `uv tool install` command's behavior with extras syntax (e.g., `~/wheel.whl[jetson]`) needs field validation
- Whether `uv tool install` with `--with depthai` resolves the exact same version as `[jetson]` extras group needs verification
- No automated rollback mechanism exists in the bringup pipeline

**Assumptions:**
- The Jetson at 192.168.4.38 already has uv and Python 3.11 installed (from prior bringup runs)
- Internet is available during bench setup for initial depthai download; field operations are offline-only

## Phase 2: Jetson-Side Prerequisites & Configuration

**Status:** ✅ Complete  
**Session:** 2026-04-23

### 1. Udev Rules — Pixhawk USB

The Pixhawk Cube Orange udev rule is defined in `scripts/90-pixhawk-usb.rules`:

```udev
# CubePilot vendor ID: 0x2dae
SUBSYSTEM=="tty", ATTRS{idVendor}=="2dae", SYMLINK+="pixhawk", MODE="0666", TAG+="systemd"
SUBSYSTEM=="usb", ATTRS{idVendor}=="2dae", ATTR{power/autosuspend}="-1"
```

- Creates `/dev/pixhawk` stable symlink (avoids reliance on `/dev/ttyACM0` ordering)
- Sets `MODE="0666"` — no `sudo` or `dialout` group required
- Tags device for systemd so `BindsTo=dev-pixhawk.device` can detect disconnect
- Disables USB autosuspend on the Pixhawk USB bus device

**Deployment gap:** The bringup pipeline does NOT deploy `90-pixhawk-usb.rules` to `/etc/udev/rules.d/`. The `harden` step runs `jetson-harden.sh`, which handles OAK-D udev rules (step 10) but NOT the Pixhawk rules. Must be deployed manually:

```bash
sudo cp 90-pixhawk-usb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2. Udev Rules — OAK-D Pro USB

Managed entirely by `jetson-harden.sh` step 10 (`harden_oakd_udev()`). Rules written inline to `/etc/udev/rules.d/80-oakd-usb.rules`:

```udev
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/autosuspend}="-1"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/control}="on"
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", SYMLINK+="oakd"
```

**Status:** Fully automated — deploying via `mower jetson bringup` (harden step) handles this.

### 3. Kernel Parameters (usbcore)

Managed by `jetson-harden.sh` step 11 (`harden_usb_params()`). Two parameters appended to kernel boot `APPEND` line in `/boot/extlinux/extlinux.conf`:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `usbcore.autosuspend` | `-1` | Global USB autosuspend disable |
| `usbcore.usbfs_memory_mb` | `1000` | Increases usbfs buffer from 16 MB to 1000 MB for OAK-D Pro high-bandwidth streams |

**Requires reboot** to take effect. Probe checks in `src/mower_rover/probe/checks/usb_tuning.py` verify at runtime via sysfs.

### 4. Serial Port Permissions

Both Pixhawk and OAK-D udev rules use `MODE="0666"` — no `dialout` group membership or `sudo` needed. The codebase does not reference group-based permission models anywhere.

VSLAM bridge config defaults to `serial_device: /dev/ttyACM0` in `vslam_defaults.yaml`. Using the `/dev/pixhawk` symlink would be more robust if other ACM devices are present.

### 5. DepthAI v3 Setup

Two separate DepthAI installations coexist:

**5a. Python `depthai` package (>= 3.5.0):** Defined in `[jetson]` extras. Currently the probe checks use raw sysfs inspection rather than `depthai` imports, so the Python package is forward-looking.

**5b. C++ `depthai-core` SDK (source build):** The RTAB-Map SLAM node (`contrib/rtabmap_slam_node/`) is a C++ binary linking against `depthai-core`. Built by `jetson-harden.sh` step 14:

```bash
git clone --depth 1 --recursive https://github.com/luxonis/depthai-core.git /opt/depthai-core-src
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_SHARED_LIBS=ON
make -j$(nproc) && make install
```

**Dependency chain:** `jetson-harden.sh` step 13 (RTAB-Map v0.23.1) → step 14 (depthai-core) → step 15 (rtabmap_slam_node binary). All from source, ~30-60 min build time, fully automated.

### 6. pyproject.toml `[jetson]` Extras

```toml
jetson = [
    "sdnotify>=0.3",
    "depthai>=3.5.0",
]
```

Both modules (`daemon.py`, `bridge.py`) have graceful `sdnotify` fallback via `_NoOpNotifier`. No additional Python packages are missing for the current architecture.

### 7. Systemd Service Units

Three units defined in `src/mower_rover/service/unit.py`, forming a dependency chain:

**`mower-health.service`** → **`mower-vslam.service`** → **`mower-vslam-bridge.service`**

| Service | Type | ExecStart | Key Features |
|---------|------|-----------|--------------|
| `mower-health` | `Type=notify` | `mower-jetson service run` | Health monitoring; WatchdogSec=30; already deployed by bringup |
| `mower-vslam` | `Type=notify` | `/usr/local/bin/rtabmap_slam_node` | C++ SLAM binary; After=mower-health |
| `mower-vslam-bridge` | `Type=notify` | `mower-jetson vslam bridge-run` | Python bridge; `BindsTo=dev-ttyACM0.device` for disconnect detection |

**Deployment gap:** Only `mower-health` is deployed by the automated bringup pipeline. VSLAM and bridge services must be deployed manually or via additional CLI commands not yet wired into bringup.

### 8. Runtime Directories

| Path | Purpose | Auto-Created? |
|------|---------|---------------|
| `/var/lib/mower/` | RTAB-Map database (`rtabmap.db`) | No — needs manual creation |
| `/run/mower/` | Unix socket for IPC (`vslam-pose.sock`) | No — service units lack `RuntimeDirectory=mower` |
| `/var/log/mower-jetson/` | Structured log files | Yes — logrotate config in `jetson-harden.sh` step 4 |
| `/etc/mower/` | VSLAM config file | No — needs manual creation |

### 9. Validation Probes

| Probe Check | What It Validates |
|-------------|-------------------|
| `oakd` | OAK-D present via USB vendor ID `03e7`; USB link speed ≥ 5000 Mbps |
| `oakd_vslam_config` | `/etc/mower/vslam.yaml` exists |
| `oakd_usb_autosuspend` | `usbcore.autosuspend=-1` via sysfs |
| `oakd_usbfs_memory` | `usbcore.usbfs_memory_mb >= 1000` via sysfs |
| `vslam_process` | `mower-vslam.service` is active |
| `vslam_bridge` | `mower-vslam-bridge.service` active + socket exists |
| `vslam_pose_rate` | Pose output rate ≥ 5 Hz |
| `vslam_params` | ArduPilot VISO_TYPE=1, SCR_ENABLE=1 |

**Gap:** No probe check for `/dev/pixhawk` symlink existence.

**Key Discoveries:**
- `90-pixhawk-usb.rules` is NOT deployed by `jetson-harden.sh` — requires manual deployment or a new bringup step
- All USB device permissions use `MODE="0666"` (world-accessible) — no group membership needed
- Three systemd services form a dependency chain but only `mower-health` is in the automated bringup pipeline
- Bridge uses `BindsTo=dev-ttyACM0.device` for Pixhawk disconnect detection (requires udev `TAG+="systemd"`)
- Two DepthAI installations coexist: C++ `depthai-core` (SLAM node) and Python `depthai>=3.5.0` (Python code)
- Kernel params require reboot after `jetson-harden.sh`
- Runtime directories `/var/lib/mower/`, `/run/mower/`, `/etc/mower/` not auto-created
- No probe for `/dev/pixhawk` symlink

| File | Relevance |
|------|-----------|
| `scripts/90-pixhawk-usb.rules` | Pixhawk udev rule (not auto-deployed) |
| `scripts/jetson-harden.sh` | 15-step hardening: OAK-D udev, kernel params, RTAB-Map, depthai-core |
| `src/mower_rover/service/unit.py` | Systemd unit templates for all three services |
| `src/mower_rover/service/daemon.py` | Health daemon with sd_notify |
| `src/mower_rover/vslam/bridge.py` | VSLAM→MAVLink bridge daemon |
| `src/mower_rover/probe/checks/oakd.py` | OAK-D USB detection probe |
| `src/mower_rover/probe/checks/usb_tuning.py` | USB tuning probes |
| `src/mower_rover/probe/checks/vslam.py` | VSLAM service/bridge probes |
| `src/mower_rover/config/data/vslam_defaults.yaml` | Default VSLAM config |
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | C++ SLAM node |

**Gaps:**
- No probe check for `/dev/pixhawk` symlink
- `90-pixhawk-usb.rules` not in automated deployment
- Service units lack `RuntimeDirectory=mower`
- VSLAM/bridge services not in bringup pipeline
- `/var/lib/mower/` and `/etc/mower/` creation not automated

**Assumptions:**
- Jetson already has `jetson-harden.sh` applied (per introduction stating provisioned at 192.168.4.38)
- User `vincent` relies on MODE=0666 permissions

## Phase 3: MAVLink Integration Testing

**Status:** ✅ Complete  
**Session:** 2026-04-23

### 1. MAVLink Connection Architecture

All MAVLink connections route through `src/mower_rover/mavlink/connection.py`:

- **`ConnectionConfig` dataclass** — endpoint, baud, source_system, source_component, timeouts, retry policy
- **`open_link()` context manager** — single entry point with retry-with-backoff

**Default config (CLI/laptop):**

```python
ConnectionConfig(
    endpoint="udp:127.0.0.1:14550",  # SITL default
    baud=57600,
    source_system=254,                # GCS identity
    source_component=0,
    heartbeat_timeout_s=10.0,
    retry_attempts=3,
    retry_backoff_s=1.0,
)
```

**Bridge config (Jetson → Pixhawk):**

```python
ConnectionConfig(
    endpoint="/dev/ttyACM0",          # USB CDC ACM
    baud=0,                           # USB CDC ignores baud
    source_system=1,                  # Same system as autopilot
    source_component=197,             # MAV_COMP_ID_VISUAL_INERTIAL_ODOMETRY
    heartbeat_timeout_s=30.0,         # Longer for USB enumeration
    retry_attempts=5,                 # More retries for field
    retry_backoff_s=2.0,              # Longer backoff
)
```

### 2. Connection Flow and Retry Logic

```
For attempt 1..retry_attempts:
  1. mavutil.mavlink_connection(endpoint, baud, source_system,
     source_component, autoreconnect=True)
  2. Wait for heartbeat with timeout=heartbeat_timeout_s
  3. If heartbeat received → yield connection
  4. If NOT received → ConnectionError("no heartbeat within timeout")
  5. On exception → log warning, sleep(retry_backoff_s × attempt)
  6. After all retries exhausted → raise ConnectionError
```

- `autoreconnect=True` — pymavlink handles reconnection transparently
- Linear backoff (1×, 2×, 3× `retry_backoff_s`)
- Connection closed in `finally` block
- All attempts logged via structlog

### 3. CLI Commands That Exercise MAVLink

**3a. `mower detect` (laptop CLI):**

```bash
mower detect --port /dev/pixhawk --json
```

Exercises: `open_link()` → HEARTBEAT recv → AUTOPILOT_VERSION → GPS_RAW_INT → GPS_RTK → SERVO_OUTPUT_RAW → RADIO_STATUS → EKF_STATUS_REPORT

**3b. `mower params snapshot` / `mower params apply`:**

```bash
mower params snapshot /tmp/params.json --port /dev/pixhawk
mower params apply baseline --port /dev/pixhawk --yes
```

Param apply uses a set-then-verify pattern: `param_set_send()` → wait for `PARAM_VALUE` echo → verify within 1e-4 tolerance → up to 3 retries per param.

**3c. `mower-jetson vslam bridge-run` (Jetson-side):**

The primary MAVLink consumer on the Jetson. Sends:
- 1 Hz component heartbeat (MAV_TYPE_ONBOARD_CONTROLLER)
- VISION_POSITION_ESTIMATE (msg_id 102) with FLU→NED conversion
- VISION_SPEED_ESTIMATE (msg_id 103)
- NAMED_VALUE_FLOAT for health metrics (VSLAM_HZ, VSLAM_CONF, VSLAM_AGE, VSLAM_COV)
- STATUSTEXT for confidence transitions
- Lua script deployment via MAVLink FTP on startup

### 4. Integration Test Sequence

**Step 1: Verify USB + Heartbeat**

```bash
ls -la /dev/pixhawk /dev/ttyACM0
python3 -c "
from pymavlink import mavutil
c = mavutil.mavlink_connection('/dev/pixhawk')
hb = c.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
print(f'Heartbeat: type={hb.type} ap={hb.autopilot}')
c.close()
"
```

Existing field test: `tests/test_vslam_field.py::TestUSBEnumeration::test_field_usb_enumeration`

**Step 2: Full Detection**

```bash
mower detect --port /dev/pixhawk --json
```

Expected: `vehicle_is_rover: true`, `vehicle_type: 11`, GNSS data, servo channels 1+3

**Step 3: Param Round-Trip**

```bash
mower params snapshot /tmp/params-pre.json --port /dev/pixhawk
mower params apply baseline --port /dev/pixhawk
mower params snapshot /tmp/params-post.json --port /dev/pixhawk
mower params diff /tmp/params-pre.json /tmp/params-post.json
```

**Step 4: Bridge MAVLink Connection**

```bash
mower-jetson vslam bridge-run
# Expected: heartbeat_received, bridge_started, heartbeat_sent (1 Hz)
```

### 5. ArduPilot Parameters Required

Per probe check `vslam_params`:
- `VISO_TYPE=1` — Visual odometry enabled
- `SCR_ENABLE=1` — Lua scripting enabled
- `EK3_SRC2_POSXY`, `EK3_SRC2_VELXY`, `EK3_SRC2_YAW` — EKF Source 2 for VSLAM

### 6. Existing SITL Tests

- `test_detect_sitl.py` — `mower detect --port <sitl> --json`, asserts rover + GNSS
- `test_params_sitl.py` — Snapshot (>100 params), apply baseline (SERVO1_FUNCTION=73, SERVO3_FUNCTION=74, EK3_SRC1_YAW=2)

Both use `sitl_endpoint` fixture from `conftest.py` with `--instance` port isolation.

**Key Discoveries:**
- All MAVLink connections route through single `open_link()` with configurable retry and linear backoff
- Bridge uses different MAVLink identity (system=1, component=197) vs laptop CLI (system=254, component=0)
- Bridge has longer timeouts (30s heartbeat, 5 retries) vs CLI defaults (10s, 3 retries)
- `detect` command is NOT wired to `mower-jetson` CLI — only available via `mower` laptop entry point
- USB CDC ACM uses baud=0 (pymavlink ignores baud for ACM devices)
- Param apply uses robust set-then-verify with 3 retries per param and 1e-4 tolerance
- Bridge sends heartbeat + VISION_POSITION_ESTIMATE + VISION_SPEED_ESTIMATE + health metrics + STATUSTEXT
- Lua script auto-deployed via MAVLink FTP on bridge startup
- Field test exists for USB enumeration + heartbeat but not for param round-trip or bridge messages
- `vslam_defaults.yaml` hardcodes `/dev/ttyACM0` — should be `/dev/pixhawk`
- Bridge systemd `BindsTo=dev-ttyACM0.device` should match udev symlink (`dev-pixhawk.device`)

| File | Relevance |
|------|-----------|
| `src/mower_rover/mavlink/connection.py` | Core connection wrapper, retry logic |
| `src/mower_rover/cli/detect.py` | Hardware detection over MAVLink |
| `src/mower_rover/cli/params.py` | Param snapshot/diff/apply with safety |
| `src/mower_rover/params/mav.py` | Low-level param fetch and apply |
| `src/mower_rover/vslam/bridge.py` | VSLAM→MAVLink bridge daemon |
| `src/mower_rover/vslam/lua_deploy.py` | MAVLink FTP Lua deployment |
| `src/mower_rover/safety/confirm.py` | Safety primitive |
| `tests/test_detect_sitl.py` | SITL detect test |
| `tests/test_params_sitl.py` | SITL param round-trip test |
| `tests/test_vslam_field.py` | Field USB + heartbeat test |

**Gaps:**
- `detect` not wired to `mower-jetson` CLI
- `vslam_defaults.yaml` hardcodes `/dev/ttyACM0` instead of `/dev/pixhawk`
- No field test for param round-trip over USB or bridge MAVLink messages
- Bridge `BindsTo=dev-ttyACM0.device` should match udev symlink `dev-pixhawk.device`

**Assumptions:**
- Both `mower` and `mower-jetson` entry points available after `uv tool install` (same package)
- USB CDC ACM baud=0 handled correctly by pymavlink on Jetson
- Bridge 30s heartbeat timeout sufficient for USB enumeration delay

## Phase 4: VSLAM Pipeline & OAK-D Pro Integration

**Status:** ✅ Complete  
**Session:** 2026-04-23

### 1. Full Pipeline Architecture

Three process layers communicate via Unix domain socket and MAVLink:

```
OAK-D Pro (USB) → [C++ rtabmap_slam_node] → Unix Socket → [Python bridge] → MAVLink USB → Pixhawk
                   mower-vslam.service       /run/mower/     mower-vslam-       /dev/ttyACM0
                                             vslam-pose.sock  bridge.service
```

**Process 1: C++ RTAB-Map SLAM Node** (`contrib/rtabmap_slam_node/`)
- Standalone binary (CMake, requires RTABMap, depthai-core, OpenCV, yaml-cpp, libsystemd)
- DepthAI pipeline: stereo MonoCamera pair (CAM_B/CAM_C), StereoDepth (high-density, LR check, subpixel), IMU (accel + gyro)
- RTAB-Map `OdometryF2M` (Frame-to-Map) + optional loop closure
- Rate-limited pose output (default 20 Hz) via 118-byte `vslam_pose_msg` structs over Unix socket
- systemd `Type=notify` with `WatchdogSec=30`
- On odometry loss: resets odometry, increments `reset_counter`

**Process 2: Python VSLAM Bridge** (`src/mower_rover/vslam/bridge.py`)
- `mower-jetson vslam bridge-run` → systemd daemon
- Reads `PoseMessage` from Unix socket via `PoseReader` (auto-reconnect)
- FLU → NED conversion (y and z sign flips, pitch and yaw negation)
- Sends VISION_POSITION_ESTIMATE (msg 102) with 21-float covariance + reset_counter
- Computes velocity via finite-differencing → VISION_SPEED_ESTIMATE (msg 103)
- 1 Hz heartbeat (MAV_TYPE_ONBOARD_CONTROLLER, component 197)
- NAMED_VALUE_FLOAT health metrics: VSLAM_HZ, VSLAM_CONF, VSLAM_AGE, VSLAM_COV
- STATUSTEXT on confidence transitions
- Deploys Lua script via MAVLink FTP on startup

**Process 3: Laptop Health Listener** (`src/mower_rover/vslam/health_listener.py`)
- Listens for NAMED_VALUE_FLOAT with `VSLAM_` prefix over MAVLink (SiK radio)
- Assembles `BridgeHealth` snapshot (pose_rate_hz, pose_age_ms, confidence, covariance_norm)
- `mower vslam health` displays Rich table — no SSH dependency

### 2. OAK-D Pro USB Enumeration

- Boots in USB 2.0 mode (Movidius MyriadX bootloader, vendor `03e7`)
- DepthAI uploads firmware via XLink → re-enumerates at USB 3.x SuperSpeed
- udev rule `80-oakd-usb.rules`: `MODE="0666"`, autosuspend disabled, `/dev/oakd` symlink
- Probe check: scans `/sys/bus/usb/devices/*/idVendor` for `03e7`, verifies link speed ≥ 5000 Mbps
- C++ node: `dai::Device(pipeline)` handles full boot→firmware→re-enum cycle

### 3. IPC: Unix Domain Socket

**Wire format:** `vslam_pose_msg` — 118 bytes, `__attribute__((packed))`:

| Field | Type | Size |
|-------|------|------|
| `timestamp_us` | uint64_t | 8 |
| `x, y, z` | float×3 | 12 |
| `roll, pitch, yaw` | float×3 | 12 |
| `covariance[21]` | float×21 | 84 |
| `confidence` | uint8_t | 1 |
| `reset_counter` | uint8_t | 1 |

Python struct format: `<Q27fBB` = 118 bytes. Size assertions on both C++ (static_assert) and Python (runtime assert) sides.

**Socket server (C++):** `AF_UNIX SOCK_STREAM` at `/run/mower/vslam-pose.sock`, `chmod 0660`, backlog=1, non-blocking via `select()`.

**Socket client (Python):** `PoseReader` with auto-reconnect, `_recv_exact()` for 118-byte reads, infinite `read_poses()` iterator.

### 4. Health Computation

`compute_health()` in `health.py`:
- Sliding window (deque maxlen=200) of `(PoseMessage, monotonic_time)` tuples
- `pose_rate_hz`: count within 2-second window
- `pose_age_ms`: wall-clock since latest pose
- `confidence`: latest pose's confidence (0–100, from odometry inliers)
- `covariance_norm`: Frobenius norm of 21-element upper-triangle

### 5. Lua EKF Source Switching

Script: `ahrs-source-gps-vslam.lua` (bundled in `mower_rover/params/data/`)
- Runs at 10 Hz on Pixhawk
- Vote-based switching with 2-second hysteresis (20 votes threshold)
- Thresholds from `SCR_USER2` (GPS speed accuracy) and `SCR_USER3` (ExternalNav innovation)
- Calls `ahrs:set_posvelyaw_source_set()` and sends STATUSTEXT on transitions
- Deployed via MAVLink FTP (`lua_deploy.py`): version-compared, non-blocking on failure

### 6. Pose Output Validation

**Procedure 003** (VSLAM vs RTK GPS):
- Drive 10m × 10m rectangle at ~1 m/s in Manual mode
- Compare VISO.PX/PY against GPS track in NED frame
- Pass: straight-segment offset ≤ 0.5m, corner ≤ 1m, loop closure ≤ 1m, no gaps > 2s

**Procedure 004** (Lua Source Switching):
- Transition open sky → tree cover → verify source switches SRC1→SRC2 within ~2s

**Procedure 005** (E2E Health Monitoring):
- `mower vslam health` on laptop over SiK radio — verify ~1 Hz updates, confidence drops on obstruction

### 7. VSLAM Configuration

`/etc/mower/vslam.yaml` defaults:
- `odometry_strategy: f2m`, `stereo_resolution: 400p`, `stereo_fps: 30`, `imu_rate_hz: 200`
- `pose_output_rate_hz: 20`, `memory_threshold_mb: 6000`, `loop_closure: true`
- `database_path: /var/lib/mower/rtabmap.db`, `socket_path: /run/mower/vslam-pose.sock`
- Extrinsics: pos_x=0.30, pos_y=0.00, pos_z=-0.20, roll=0, pitch=-15, yaw=0
- Bridge: serial_device=/dev/ttyACM0, source_system=1, source_component=197

### 8. CLI Surface

**Jetson** (`mower-jetson vslam`): install/uninstall/start/stop/status for SLAM node, bridge-install/uninstall/start/stop/status for bridge
**Laptop** (`mower vslam`): health — live Rich table of VSLAM metrics over MAVLink

**Key Discoveries:**
- Full pipeline is 3-process: C++ SLAM node → Unix socket IPC (118-byte packed) → Python bridge → MAVLink
- IPC has compile-time and runtime size assertions — zero ambiguity in wire format
- Bridge sends VISION_POSITION_ESTIMATE + VISION_SPEED_ESTIMATE (velocity from finite-differencing)
- Lua source switching uses vote-based 2-second hysteresis to prevent oscillation
- Health metrics flow over MAVLink via NAMED_VALUE_FLOAT — no SSH dependency for monitoring
- Pre-flight probes form validated dependency chain: oakd → vslam_process → vslam_bridge → vslam_pose_rate
- C++ SLAM node is standalone binary outside Python package, installed to /usr/local/bin
- Extrinsics declared in VSLAM config but unclear where transform is applied — possible gap

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | C++ SLAM node |
| `contrib/rtabmap_slam_node/include/vslam_pose_msg.h` | IPC wire format (118 bytes) |
| `src/mower_rover/vslam/bridge.py` | Python MAVLink bridge |
| `src/mower_rover/vslam/ipc.py` | PoseReader/PoseMessage Unix socket client |
| `src/mower_rover/vslam/frames.py` | FLU↔NED conversions |
| `src/mower_rover/vslam/health.py` | Health computation |
| `src/mower_rover/vslam/health_listener.py` | Laptop-side health listener |
| `src/mower_rover/vslam/lua_deploy.py` | MAVLink FTP Lua deployment |
| `src/mower_rover/params/data/ahrs-source-gps-vslam.lua` | Lua AHRS script |
| `src/mower_rover/config/data/vslam_defaults.yaml` | Default VSLAM config |
| `src/mower_rover/probe/checks/vslam.py` | VSLAM probe checks |
| `docs/procedures/003-vslam-trajectory-validation.md` | Trajectory validation procedure |

**Gaps:**
- Extrinsics declared in VSLAM config but unclear where camera-to-Pixhawk transform is applied (may be via ArduPilot VISO_POS_X/Y/Z params)
- VISION_SPEED_ESTIMATE covariance is hardcoded `[0.0]*9` — no velocity covariance propagation
- C++ SLAM node uses system_clock for timestamps — clock jumps could cause velocity spikes

**Assumptions:**
- build.sh and CMake only run on Jetson (aarch64, requires depthai-core + RTABMap + libsystemd)
- Extrinsic calibration consumed via ArduPilot VISO_POS_* params during param apply

## Phase 5: End-to-End Integration & Health Monitoring

**Status:** ✅ Complete  
**Session:** 2026-04-23

### 1. End-to-End Integration Path

Six sequential stages from deployment to operation:

| Stage | Action | Tool | Status |
|-------|--------|------|--------|
| 1 | SSH connectivity | `mower jetson setup` (6-step wizard) | Automated |
| 2 | Bringup | `mower jetson bringup` (6 steps: SSH→harden→uv→CLI→verify→health) | Automated |
| 3 | VSLAM service deploy | `mower-jetson vslam install` + `bridge-install` | Manual |
| 4 | Pre-flight validation | `mower-jetson probe --json` | Automated |
| 5 | Operational pipeline | 3 systemd services: health→vslam→bridge | Automated (systemd) |
| 6 | Laptop monitoring | `mower vslam health` over SiK radio | Automated |

**Gap:** Stage 3 (VSLAM services) is not part of the automated bringup pipeline — operator must install/start 2 additional services manually.

### 2. Health Monitoring Across Subsystems

**Jetson-side (mower-health.service):**
- Periodic thermal/power/disk checks (configurable interval, default 60s)
- sd_notify: READY=1 on startup, WATCHDOG=1 every 15s
- Error resilient: catches all exceptions, logs, continues loop

**VSLAM bridge health (mower-vslam-bridge.service):**
- Computes health from sliding deque of poses (maxlen=200, 2s window)
- NAMED_VALUE_FLOAT messages: VSLAM_HZ, VSLAM_CONF, VSLAM_AGE, VSLAM_COV
- STATUSTEXT on confidence transitions (tracking lost/recovered)

**Laptop-side (mower vslam health):**
- Listens for NAMED_VALUE_FLOAT with VSLAM_ prefix over SiK radio
- Rich table with color-coded thresholds — **no SSH required**

### 3. Logging Architecture

- **Format:** structlog → JSONL file + human console
- **File naming:** `mower-{timestamp}-{correlation_id}.jsonl`
- **Paths:** Jetson: `~/.local/share/mower-rover/logs/`, Windows: `%LOCALAPPDATA%\mower-rover\logs\`
- **Correlation ID:** UUID hex[:12], propagated via `MOWER_CORRELATION_ID` env var through SSH transport — enables cross-machine log stitching
- **Rotation:** System-level via `jetson-harden.sh` logrotate + journald limits

**Gap:** Logrotate targets `/var/log/mower-jetson/*.log` but structlog writes to `~/.local/share/mower-rover/logs/*.jsonl` — path mismatch means daemon logs won't be rotated. Also uses `FileHandler` not `RotatingFileHandler` — single JSONL file per daemon lifetime could grow large.

### 4. Failure Modes and Recovery

**Systemd recovery (all services):** `Restart=on-failure`, `RestartSec=5`, `StartLimitBurst=5/300s`, `WatchdogSec=30`

| Failure | Behavior | Recovery |
|---------|----------|----------|
| Health read exception | Logged, loop continues | Self-healing |
| SLAM socket loss | PoseReader reconnects (1s backoff) | Self-healing |
| Pixhawk USB disconnect | `BindsTo=dev-ttyACM0.device` stops bridge | Auto-restart on re-enumeration |
| MAVLink timeout | `autoreconnect=True` + retry in `open_link()` | Auto-reconnect |
| Tracking lost (conf→0) | STATUSTEXT sent, bridge continues | Self-healing when SLAM recovers |
| OAK-D disconnect | SLAM node crashes | systemd restart |
| 5 crashes in 5 min | Service enters `failed` | Manual: `systemctl --user reset-failed && start` |
| E-stop engaged | Hardware cuts power | Services keep running (no harm); manual re-engage |

**Cross-process:** SLAM death → bridge auto-reconnects IPC; Pixhawk disconnect → bridge stops, SLAM continues; health death → no impact on SLAM/bridge.

### 5. Rollback Procedures

| Target | Mechanism | Gap |
|--------|-----------|-----|
| CLI/Package | Rebuild old wheel + `uv tool install --force` | No version tracking, no auto-backup |
| Services | `uninstall --yes` (stop, disable, remove, reload) | Clean and idempotent |
| VSLAM config | Overwrite `/etc/mower/vslam.yaml` | No snapshot/restore (unlike ArduPilot params) |
| ArduPilot params | `mower params snapshot` + `mower params restore` | Well-implemented |
| Hardening | Idempotent (checks before applying) | No undo for hardening changes |

### 6. Field Test Readiness Checklist

**Pre-Deploy (Laptop):**
- [ ] SSH key pair exists
- [ ] `laptop.yaml` configured with Jetson host/user
- [ ] Wheel builds successfully (`uv build --wheel`)
- [ ] Pixhawk param snapshot taken as baseline

**Jetson Infrastructure:**
- [ ] SSH confirmed (`mower jetson bringup --step check-ssh`)
- [ ] Hardening applied, kernel params set
- [ ] uv + Python 3.11 installed
- [ ] `mower-jetson` CLI installed and working
- [ ] Runtime dirs exist: `/var/lib/mower/`, `/run/mower/`, `/etc/mower/`
- [ ] Pixhawk udev rules deployed (`/dev/pixhawk` symlink)
- [ ] OAK-D udev rules deployed

**VSLAM Configuration:**
- [ ] `/etc/mower/vslam.yaml` with correct extrinsics
- [ ] Extrinsic calibration completed (Procedure 002)
- [ ] `rtabmap_slam_node` binary at `/usr/local/bin/`

**Services:**
- [ ] `mower-health.service` active
- [ ] `mower-vslam.service` active
- [ ] `mower-vslam-bridge.service` active
- [ ] Socket `/run/mower/vslam-pose.sock` exists

**Hardware:**
- [ ] OAK-D Pro at USB 3.x SuperSpeed (≥5000 Mbps)
- [ ] Pixhawk USB at `/dev/ttyACM0`
- [ ] SiK radios connected (TELEM1 on Pixhawk, USB on laptop)
- [ ] RTK base station streaming RTCM3
- [ ] FrSky RC receiver bound

**ArduPilot Params:**
- [ ] `VISO_TYPE=1`, `SCR_ENABLE=1`
- [ ] `EK3_SRC1_YAW=2` (GPS yaw)
- [ ] EK3_SRC2_* set for VSLAM
- [ ] `FENCE_ACTION=2`, `FS_EKF_ACTION=2` (Hold, not RTL)
- [ ] Lua script on Pixhawk SD card

**Operational Validation:**
- [ ] `mower-jetson probe --json` — all critical checks pass
- [ ] `mower vslam health` on laptop shows metrics via SiK radio
- [ ] Pose rate ≥5 Hz, confidence ≥2, age <500 ms
- [ ] Camera obstruction → confidence drops; removal → recovery
- [ ] E-stop test: engage → mower stops; disengage → services still running

**Key Discoveries:**
- 6-stage deployment pipeline but VSLAM services not automated in bringup
- Cross-machine correlation ID propagation via MOWER_CORRELATION_ID env var through SSH
- PoseReader auto-reconnects on SLAM socket loss — bridge is self-healing
- Bridge BindsTo=dev-ttyACM0.device ensures auto-stop on Pixhawk disconnect
- Logrotate path mismatch — daemon logs won't be rotated
- No package version tracking or rollback mechanism
- No bridge-start/bridge-stop convenience CLI commands
- Run-archive (log collection bundle) not yet implemented

| File | Relevance |
|------|-----------|
| `src/mower_rover/logging_setup/setup.py` | Structured logging, correlation ID |
| `src/mower_rover/service/daemon.py` | Health daemon loop |
| `src/mower_rover/service/unit.py` | Systemd unit generation |
| `src/mower_rover/vslam/bridge.py` | VSLAM MAVLink bridge |
| `src/mower_rover/vslam/health.py` | BridgeHealth computation |
| `src/mower_rover/vslam/health_listener.py` | Laptop-side health listener |
| `src/mower_rover/cli/bringup.py` | Bringup pipeline |
| `src/mower_rover/cli/setup.py` | SSH setup wizard |
| `src/mower_rover/transport/ssh.py` | SSH transport with correlation ID |
| `scripts/jetson-harden.sh` | Logrotate (path mismatch) |

**Gaps:**
- Logrotate path mismatch (`/var/log/` vs `~/.local/share/`)
- No log rotation for long-running daemon JSONL files
- No package version tracking or rollback
- VSLAM service deployment not in bringup pipeline
- Runtime directories not auto-created
- No bridge-start/bridge-stop convenience CLI commands
- Run-archive not yet implemented
- VISION_SPEED_ESTIMATE covariance hardcoded zeros

## Overview

The Jetson AGX Orin deployment infrastructure for the mower_rover MAVLink + VSLAM + navigation stack is approximately **90% complete**. The automated bringup pipeline (`mower jetson bringup`) handles SSH setup, field hardening, uv/Python 3.11 installation, wheel deployment, and health service activation. The remaining 10% comprises VSLAM-specific service deployment, runtime directory creation, and fixing several configuration mismatches identified during this research.

### Key Findings Summary

1. **Deployment mechanism is sound** — Wheel-based `uv tool install` with the existing bringup pipeline covers 90% of the deployment. The critical fix is switching from `--with sdnotify` to `[jetson]` extras to include `depthai>=3.5.0`.

2. **VSLAM pipeline architecture is well-structured** — Three-process design (C++ SLAM → Unix socket IPC → Python bridge → MAVLink) with clear separation of concerns, compile-time/runtime size assertions on the 118-byte wire format, and self-healing reconnection in the bridge.

3. **Health monitoring works across subsystems without SSH** — Bridge health metrics flow as NAMED_VALUE_FLOAT messages over MAVLink/SiK radio, enabling laptop-side monitoring via `mower vslam health` without any SSH dependency.

4. **Cross-machine log correlation is implemented** — Correlation IDs propagate through SSH transport via MOWER_CORRELATION_ID env var, enabling log stitching across laptop and Jetson.

5. **Pre-flight probe system is comprehensive** — 12+ dependency-ordered checks validate the entire stack from JetPack version through VSLAM pose rate.

### Critical Gaps Requiring Implementation

| Gap | Impact | Severity |
|-----|--------|----------|
| `depthai` not in bringup install command | VSLAM modules fail at runtime | **Critical** |
| VSLAM/bridge services not in bringup pipeline | Manual install/start required for 2 services | **High** |
| `90-pixhawk-usb.rules` not auto-deployed | `/dev/pixhawk` symlink missing; bridge BindsTo may fail | **High** |
| Runtime dirs not auto-created | `/var/lib/mower/`, `/run/mower/`, `/etc/mower/` missing | **High** |
| Logrotate path mismatch | Daemon logs won't rotate in the field | **Medium** |
| `detect` not on Jetson CLI | No hardware detection from Jetson | **Medium** |
| `vslam_defaults.yaml` hardcodes `/dev/ttyACM0` | Less robust than `/dev/pixhawk` symlink | **Low** |
| Bridge `BindsTo=dev-ttyACM0.device` vs udev `/dev/pixhawk` | Device naming inconsistency | **Low** |
| No bridge-start/bridge-stop CLI commands | Must use raw systemctl | **Low** |
| No package version tracking/rollback | Can't roll back to previous deployment | **Low** |

### Cross-Cutting Patterns

- **Self-healing**: PoseReader auto-reconnects on socket loss; pymavlink autoreconnect on serial loss; systemd Restart=on-failure with watchdog
- **Safety chain**: Physical E-stop → hardware relay → software has no override. Bridge BindsTo stops on Pixhawk disconnect.
- **Offline-capable**: Initial deploy needs internet (depthai download); all operational commands work field-offline
- **Structured output**: Every operation logs inputs/responses/outcomes via structlog JSONL with correlation IDs

### Actionable Conclusions

1. **Immediate fix**: Update `bringup.py` install-cli step to use `[jetson]` extras instead of `--with sdnotify`
2. **Add bringup steps**: Deploy `90-pixhawk-usb.rules`, create runtime directories, install+start VSLAM/bridge services
3. **Fix logrotate path**: Update `jetson-harden.sh` to target actual structlog output directory, or add RotatingFileHandler
4. **Wire `detect` to Jetson CLI**: Enable `mower-jetson detect` for on-device hardware validation
5. **Standardize device naming**: Use `/dev/pixhawk` symlink consistently in defaults and service units

### Open Questions

- Where are camera-to-Pixhawk extrinsics actually applied? Config declares them but neither C++ node nor bridge transforms poses. Likely via ArduPilot VISO_POS_X/Y/Z — needs field validation.
- Does `uv tool install` support extras syntax from local wheel files (e.g., `~/wheel.whl[jetson]`)? Needs field testing.
- VISION_SPEED_ESTIMATE covariance is all zeros — does this degrade EKF3 fusion quality?

## References

### Key Source Files
- `pyproject.toml` — Package definition, `[jetson]` extras, entry points
- `src/mower_rover/cli/bringup.py` — Automated 6-step bringup pipeline
- `src/mower_rover/mavlink/connection.py` — MAVLink connection wrapper with retry
- `src/mower_rover/vslam/bridge.py` — VSLAM→MAVLink bridge daemon
- `src/mower_rover/vslam/ipc.py` — Unix socket IPC (PoseReader/PoseMessage)
- `src/mower_rover/service/unit.py` — Systemd unit templates
- `src/mower_rover/logging_setup/setup.py` — Structured logging with correlation IDs
- `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` — C++ SLAM node
- `scripts/jetson-harden.sh` — 15-step Jetson field hardening
- `scripts/90-pixhawk-usb.rules` — Pixhawk udev rule

### Prior Research
- `docs/research/002-jetson-agx-orin-bringup.md` — Python toolchain, uv, dependency compatibility
- `docs/research/006-oakd-pro-usb-slam-readiness.md` — OAK-D Pro readiness
- `docs/research/007-vslam-ardupilot-rtk-integration.md` — VSLAM-ArduPilot integration

### Field Procedures
- `docs/procedures/001-usb-enumeration.md` — Pixhawk USB verification
- `docs/procedures/002-extrinsic-calibration.md` — Camera-Pixhawk calibration
- `docs/procedures/003-vslam-trajectory-validation.md` — VSLAM vs RTK accuracy
- `docs/procedures/004-lua-source-switching.md` — Lua EKF source switching
- `docs/procedures/005-health-monitoring-e2e.md` — E2E health monitoring

## Follow-Up Research

### From Phase 1
- Validate `uv tool install` extras-from-wheel syntax on Jetson
- Add automated rollback mechanism to bringup pipeline

### From Phase 2
- Add `90-pixhawk-usb.rules` deployment to `jetson-harden.sh` or bringup
- Add `RuntimeDirectory=mower` to VSLAM bridge service unit
- Auto-create `/var/lib/mower/` and `/etc/mower/` in bringup
- Add probe check for `/dev/pixhawk` symlink

### From Phase 3
- Wire `detect` command into `mower-jetson` CLI
- Change `vslam_defaults.yaml` serial_device to `/dev/pixhawk`
- Resolve bridge `BindsTo=dev-ttyACM0.device` vs `/dev/pixhawk` mismatch
- Add field tests for param round-trip over USB and bridge MAVLink messages

### From Phase 4
- Verify where camera-to-Pixhawk extrinsics are applied (VISO_POS_* params?)
- Implement velocity covariance propagation in VISION_SPEED_ESTIMATE

### From Phase 5
- Fix logrotate path to match structlog output directory
- Add VSLAM+bridge service deployment to bringup pipeline
- Implement bridge-start/bridge-stop convenience CLI commands
- Add package version tracking to deployment
- Implement run-archive for post-session log collection

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-23 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/008-jetson-mavlink-vision-integration-deploy.md |
