# Zero-Turn Mower Rover

CLI tooling suite for converting a Husqvarna Z254 zero-turn mower into an autonomous RTK-mowing robot.

This is **not** the autopilot firmware, **not** the physical build, and **not** a replacement for Mission Planner / QGroundControl. It fills the gaps between existing tools (ArduPilot, u-center, DepthAI, etc.) for a single operator working in a 4-acre yard.

## Hardware stack

| Component | Hardware |
|---|---|
| Flight controller | Pixhawk Cube Orange — ArduPilot Rover (skid-steer) |
| GNSS | ArduSimple simpleRTK3B Heading (Septentrio mosaic-H, dual-antenna GPS yaw) |
| Base station | simpleRTK2B Budget streaming RTCM3 over dedicated SiK radio |
| Steering | 2× ASMC-04A Robot Servo (12–24 V, back-driveable) |
| Companion computer | NVIDIA Jetson AGX Orin 64 GB (JetPack 6, 50 W mode) |
| Depth camera | Luxonis OAK-D Pro (USB, DepthAI v3) |
| Operator control | FrSky Taranis X9D Plus (OpenTX) transmitter (SBUS/FPort) + physical E-stop |

See [docs/vision/001-zero-turn-mower-rover.md](docs/vision/001-zero-turn-mower-rover.md) and [docs/research/001-mvp-bringup-rtk-mowing.md](docs/research/001-mvp-bringup-rtk-mowing.md) for full details.

## Install

Requires Python 3.11+. Recommended via [`pipx`](https://pipx.pypa.io/):

```
pipx install .
```

Or, for development with [`uv`](https://docs.astral.sh/uv/):

```
uv sync --extra dev
```

### Jetson install

On the rover's Jetson AGX Orin (JetPack 6 / Ubuntu, aarch64):

```
pipx install .[jetson]
```

This installs `mower-jetson` with Jetson-specific extras (`sdnotify`, `depthai`). Configure key-based SSH from the laptop to the Jetson user before using `mower jetson` from the laptop side (no password auth — `mower jetson` runs OpenSSH with `BatchMode=yes`).

## Commands

### Laptop (`mower`)

| Command | Description |
|---|---|
| `mower detect` | Read-only hardware enumeration over MAVLink (autopilot, GNSS, servos, radio, EKF) |
| `mower params snapshot OUT.json` | Fetch every autopilot param to a JSON snapshot |
| `mower params diff LEFT RIGHT` | Diff two param files (YAML / JSON snapshot / `.parm`); pass `baseline` for the shipped Z254 baseline |
| `mower params apply FILE` | Snapshot → diff → confirm → write params to autopilot. Honors `--dry-run` and `--yes` |
| `mower jetson setup` | Interactive first-time Jetson connectivity wizard |
| `mower jetson bringup` | Automated end-to-end Jetson provisioning |
| `mower jetson run -- CMD…` | Run `CMD` on the Jetson over SSH (key auth only) |
| `mower jetson pull REMOTE LOCAL` | Copy a file from the Jetson to the laptop; prompts on overwrite (`--yes` to bypass) |
| `mower jetson info` | Run `mower-jetson info --json` over SSH and print parsed result |
| `mower vslam health` | Display VSLAM bridge health received over MAVLink |
| `mower version` | Print the installed version |

Endpoint resolution for `mower jetson …`: `--host/--user/--port/--key` flags
→ `MOWER_JETSON_HOST` / `MOWER_JETSON_USER` / `MOWER_JETSON_PORT` / `MOWER_JETSON_KEY`
env vars → `~/.config/mower-rover/laptop.yaml` (Linux/macOS) or
`%APPDATA%\mower-rover\laptop.yaml` (Windows). Example:

```yaml
jetson:
  host: 10.0.0.42
  user: mower
  port: 22
  key_path: ~/.ssh/mower_id_ed25519
```

### Jetson (`mower-jetson`)

| Command | Description |
|---|---|
| `mower-jetson detect` | Detect connected hardware over local USB |
| `mower-jetson info` | Platform identity (hostname, kernel, JetPack release). `--json` for machine output |
| `mower-jetson config show` | Print resolved Jetson YAML config (`--config PATH` to override) |
| `mower-jetson probe` | Run pre-flight readiness checks (CUDA, OAK-D, USB tuning, thermal, disk, SSH, VSLAM…) |
| `mower-jetson thermal` | Live thermal zone monitor (`--watch` for continuous) |
| `mower-jetson power` | Power / performance state snapshot |
| `mower-jetson service install` | Install and enable the `mower-health` systemd service |
| `mower-jetson service uninstall` | Stop and remove the `mower-health` systemd service |
| `mower-jetson vslam install` | Install and enable VSLAM systemd services (`mower-vslam`, `mower-vslam-bridge`) |
| `mower-jetson vslam uninstall` | Stop and remove VSLAM systemd services |
| `mower-jetson version` | Print the installed version |

Default Jetson config path: `~/.config/mower-rover/jetson.yaml`.

## Architecture

```
┌─────────────────────────────┐       SSH / SCP       ┌──────────────────────────────────┐
│  Operator laptop (Windows)  │◄─────────────────────►│  Jetson AGX Orin (aarch64)       │
│                             │                        │                                  │
│  mower detect               │                        │  mower-jetson info / probe       │
│  mower params …             │   MAVLink (SiK radio)  │  mower-jetson thermal / power    │
│  mower jetson …             │◄─────────────────────►│                                  │
│  mower vslam health         │                        │  ┌──────────────────────────┐    │
│                             │                        │  │ mower-vslam.service      │    │
└─────────────────────────────┘                        │  │ (rtabmap_slam_node C++)  │    │
                                                       │  │ OAK-D Pro → RTAB-Map     │    │
        ┌──────────────────┐                           │  └──────────┬───────────────┘    │
        │  Cube Orange     │   MAVLink (serial)        │             │ Unix socket IPC    │
        │  ArduPilot Rover │◄─────────────────────────│  ┌──────────▼───────────────┐    │
        │  (skid-steer)    │   VISION_POSITION_EST     │  │ mower-vslam-bridge.svc   │    │
        └──────────────────┘   VISION_SPEED_EST        │  │ FLU→NED, MAVLink fwd    │    │
                                                       │  └──────────────────────────┘    │
                                                       │                                  │
                                                       │  mower-health.service            │
                                                       │  (disk, thermal, power watchdog) │
                                                       └──────────────────────────────────┘
```

### VSLAM pipeline

1. **`mower-vslam.service`** — C++ RTAB-Map SLAM node (`contrib/rtabmap_slam_node/`) reads stereo + IMU from the OAK-D Pro via DepthAI, runs visual odometry and loop closure, outputs 6-DOF poses over a Unix socket.
2. **`mower-vslam-bridge.service`** — Python bridge (`src/mower_rover/vslam/bridge.py`) reads poses from the Unix socket, converts FLU → NED, and forwards `VISION_POSITION_ESTIMATE` / `VISION_SPEED_ESTIMATE` to the Cube Orange over MAVLink.
3. **ArduPilot Lua script** (deployed via `mower-jetson vslam install` / `lua_deploy.py`) enables EKF source switching between GPS and visual odometry.

### Jetson systemd services

| Service | Type | Purpose |
|---|---|---|
| `mower-health.service` | `Type=notify` | Disk, thermal, and power health watchdog |
| `mower-vslam.service` | — | RTAB-Map SLAM node (C++ binary) |
| `mower-vslam-bridge.service` | — | VSLAM → MAVLink bridge (Python) |

### Health monitoring & pre-flight probes

The `mower-jetson probe` command runs dependency-ordered checks:

- **CUDA** — toolkit availability
- **OAK-D** — USB enumeration and device presence
- **USB tuning** — kernel params (`usbcore.autosuspend`, `usbfs_memory_mb`)
- **Disk** — free space and NVMe detection
- **Thermal** — zone accessibility
- **Power mode** — Jetson nvpmodel validation
- **Python version** — compatibility check
- **SSH hardening** — password auth disabled, root login disabled
- **JetPack** — release detection
- **VSLAM** — RTAB-Map and DepthAI readiness

### Safety

Every actuator-touching command goes through the safety primitive:

- **Confirmation prompt** — explicit operator approval before writes
- **`--dry-run` mode** — preview changes without applying
- **Central safe-stop hook** — registered cleanup on abort
- **Physical E-stop** — hardware relay has absolute authority (not software-bypassable)

## Configuration

Three YAML config files, resolved in order (flags → env vars → file):

| File | Platform | Default path |
|---|---|---|
| `laptop.yaml` | Windows / macOS / Linux | `%APPDATA%\mower-rover\laptop.yaml` or `~/.config/mower-rover/laptop.yaml` |
| `jetson.yaml` | Jetson (aarch64) | `~/.config/mower-rover/jetson.yaml` |
| `vslam.yaml` | Jetson (aarch64) | `~/.config/mower-rover/vslam.yaml` |

## Scripts

| Script | Purpose |
|---|---|
| `scripts/jetson-harden.sh` | Idempotent Jetson field-hardening (headless mode, USB tuning, udev rules, SSH hardening, RTAB-Map / DepthAI build, service setup) |
| `scripts/90-pixhawk-usb.rules` | udev rules for Pixhawk USB device permissions and symlink |

## Project layout

```
src/mower_rover/
├── cli/            # Typer CLI apps (laptop + jetson)
├── config/         # YAML config loading and validation
├── health/         # Disk, thermal, and power monitoring
├── logging_setup/  # structlog JSON + console, correlation IDs
├── mavlink/        # MAVLink connection with retry/reconnect
├── params/         # ArduPilot param snapshot / diff / apply
├── probe/          # Pre-flight check framework + individual checks
├── safety/         # Confirmation prompts, dry-run, safe-stop hooks
├── service/        # systemd unit generation and daemon framework
├── transport/      # SSH/SCP wrapper (laptop → Jetson)
└── vslam/          # VSLAM bridge, IPC, frame transforms, Lua deploy

contrib/rtabmap_slam_node/  # C++ RTAB-Map SLAM node (builds on Jetson)
scripts/                    # Hardening and udev rules
docs/                       # Vision, research, plans, procedures, field notes
```

## Test

```
pytest -m "not field and not sitl"        # fast unit tests, all platforms
pytest -m sitl                             # requires sim_vehicle.py on PATH (Linux/WSL2)
```

| Marker | Scope |
|---|---|
| *(unmarked)* | Unit tests — pure logic, mocked dependencies |
| `@pytest.mark.sitl` | Requires ArduPilot SITL (`rover-skid` frame) |
| `@pytest.mark.field` | Requires physical hardware (excluded from CI) |
| `@pytest.mark.jetson` | Requires a real Jetson device |

SITL is a **smoke-test harness** for MAVLink plumbing, param round-trips, mode transitions, and dry-run paths. It is **not** a tuning tool — the kinematic model has no mass, friction, or hydrostatics.

## License

MIT
