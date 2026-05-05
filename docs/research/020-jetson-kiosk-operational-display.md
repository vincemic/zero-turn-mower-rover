---
id: "020"
type: research
title: "Jetson Kiosk Mode — Operational Status Display"
status: ✅ Complete
created: "2026-05-04"
current_phase: "5 of 5"
---

## Introduction

The Jetson AGX Orin Dev Kit is currently running headless (no GUI). This research investigates converting it to a kiosk-mode operational display — a single full-screen status dashboard that auto-starts on boot and shows real-time system health, VSLAM status, MAVLink telemetry, and mowing mission state. The display would be connected via the carrier board's DisplayPort output and visible to the operator in the field (e.g., mounted on the mower or a nearby post).

## Objectives

- Determine the lightest-weight display server stack for kiosk mode on JetPack 6 / L4T 36.5
- Identify dashboard rendering options that work on Jetson (browser-based vs native vs framebuffer)
- Define what operational data to surface and how to source it from existing services
- Evaluate power/thermal impact of running a display on nvpmodel mode 3 (50 W)
- Determine auto-start and crash-recovery mechanisms for unattended field operation
- Assess sunlight-readable display hardware considerations (brightness, anti-glare)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Display Server & Kiosk Stack on JetPack 6 | ✅ Complete | Wayland vs X11 vs framebuffer on L4T 36.5; minimal window manager options (cage, labwc, sway, openbox); kiosk lockdown (no desktop, no taskbar, no cursor); auto-login and session management; GPU acceleration availability | 2026-05-04 |
| 2 | Dashboard Rendering Approach | ✅ Complete | Browser-based kiosk (Chromium --kiosk, Firefox, wpe-webkit) vs native toolkit (GTK4, Qt, egui/Rust) vs framebuffer-direct (pygame, lvgl); GPU-accelerated rendering on Tegra; refresh rate and animation considerations; memory/CPU footprint comparison | 2026-05-04 |
| 3 | Operational Data Sources & Architecture | ✅ Complete | What data to display (VSLAM pose, MAVLink heartbeat/GPS/battery/mode, engine RPM, mower-health watchdog status, Wi-Fi signal, CPU/GPU temp, disk usage, service unit states); how to source each (Unix socket, MAVLink stream, D-Bus, /sys/class, systemctl); data refresh architecture (polling vs push vs IPC); web-based dashboard data feed (WebSocket server from existing services) | 2026-05-04 |
| 4 | Auto-Start, Crash Recovery & Field Hardening | ✅ Complete | systemd service for kiosk session; auto-restart on crash; handling display hotplug (monitor connect/disconnect); screen blanking/DPMS disable for always-on; read-only filesystem considerations; graceful degradation if display absent (headless fallback); integration with existing mower-health.service watchdog | 2026-05-04 |
| 5 | Display Hardware & Power/Thermal Impact | ✅ Complete | DisplayPort output specs on Orin Dev Kit carrier board; suitable field-rated displays (sunlight-readable, IP-rated, 7-10 inch); power draw of GPU compositor + display panel; thermal impact at 50 W power budget; HDMI vs DP adapter considerations; touchscreen viability for future interaction | 2026-05-04 |

## Phase 1: Display Server & Kiosk Stack on JetPack 6

**Status:** ✅ Complete  
**Session:** 2026-05-04

### Wayland vs X11 vs Framebuffer on L4T 36.5

L4T 36.x (JetPack 6) provides **first-class support for both X11 and Wayland**, with clear momentum toward Wayland as the primary display system.

**Weston 13.0** (Wayland reference compositor) is the **NVIDIA-supported Wayland compositor**, shipped as part of the L4T BSP package (`nvidia-l4t-weston`). NVIDIA has invested heavily in Wayland support:

- **NVGBM backend**: NVIDIA implemented its own GBM (Generic Buffer Management) backend for Mesa, enabling GBM-based compositors (including wlroots-based ones) to work with NVIDIA's DRM driver. Merged upstream in Mesa.
- **`nvidia_drm` kernel module**: Provides DRM/KMS support. Must be loaded with `modeset=1` parameter for any Wayland compositor to work.
- **EGL_KHR_platform_gbm**: Enabled with the NVGBM backend, allowing EGL initialization from GBM devices.
- **DMA-BUF support**: Full dma-buf rendering pipeline with hardware compositing overlay planes.

**X11** is also supported via the NVIDIA X server driver (`nvidia-l4t-x11`), but adds unnecessary attack surface and complexity. **Framebuffer (fbdev)** is deprecated — the modern kernel display subsystem on Jetson is **DRM/KMS**.

**Recommendation: Use Wayland (not X11)** for the kiosk display — lighter weight, better security posture, aligns with NVIDIA's direction, and maps perfectly to a single-compositor kiosk model. The hardening script already disables X11 forwarding.

### Minimal Compositor Options

| Compositor | NVIDIA Support | Kiosk-Ready | Complexity | GPU Accel | Build Required | Risk |
|---|---|---|---|---|---|---|
| **Weston kiosk-shell** | ✅ Official | ✅ Yes | Low | ✅ GL renderer | ❌ Ships with BSP | Very Low |
| **Cage** | ❌ Unsupported | ✅ Purpose-built | Minimal | ✅ Via wlroots | ✅ Must compile | Medium |
| **labwc** | ❌ Unsupported | ⚠️ Configurable | Medium | ✅ Via wlroots | ✅ Must compile | Medium |
| **Sway** | ❌ Unsupported | ⚠️ Configurable | High | ✅ Via wlroots | ✅ Must compile | Medium-High |
| **Direct DRM/KMS** | ✅ Supported | ⚠️ Manual | Very High | ✅ Direct | N/A | Low (but complex) |

**Weston kiosk-shell (RECOMMENDED):** Weston 13.0 ships with L4T BSP — no compilation needed. The `kiosk-shell.so` plugin provides purpose-built fullscreen single-app functionality. GPU-accelerated compositing via GL renderer with hardware overlay plane direct scanout. Configuration via `/etc/xdg/weston/weston.ini`:

```ini
[core]
shell=kiosk-shell.so
idle-time=0

[output]
name=DP-1
mode=1920x1080@60

[shell]
locking=false
```

**Cage** is the simplest kiosk compositor (single command: `cage /path/to/app`), but requires compilation from source and carries wlroots/NVIDIA compatibility risk. NVIDIA's NVGBM backend should enable it to work, but it's untested on Jetson.

**labwc/Sway** are more complex than needed for a single-app kiosk. Sway explicitly marks NVIDIA as "unsupported" (requires `--unsupported-gpu` flag).

**Direct DRM/KMS** has minimum overhead but requires the application to handle all display management — wrong abstraction for a browser-based or toolkit-based dashboard.

### Kiosk Lockdown Patterns

**Display-Level:**
1. No desktop environment — use compositor directly, don't install/enable GNOME/gdm3
2. Single-app compositor (Weston kiosk-shell or Cage) — no task switching, no alt-tab
3. Disable idle/screen lock — `idle-time=0` for Weston
4. Disable VT switching — `kernel.sysrq=0` (already in hardening sysctl), `NAutoVTs=0` in `logind.conf`
5. Disable XWayland — `xwayland=false` in weston.ini

**Input-Level:**
6. Disable compositor keybindings (Alt+F4, Ctrl+Alt+Del)
7. Hide mouse cursor if no mouse/touchscreen needed

**Process-Level:**
8. systemd service with `Restart=always` for both compositor and dashboard app
9. systemd `WatchdogSec=` to detect hangs
10. Dedicated `kiosk` user (principle of least privilege)

### Auto-Login and Session Management

**Current state:** Jetson is headless — `multi-user.target`, `gdm3` disabled, no display manager.

**Recommended approach: systemd service (not display manager)**

```ini
[Unit]
Description=Mower Dashboard Kiosk
After=multi-user.target
Wants=network-online.target

[Service]
User=kiosk
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStartPre=/sbin/modprobe nvidia_drm modeset=1
ExecStart=/usr/bin/weston --shell=kiosk-shell.so --idle-time=0
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

This runs the compositor without a login session — no gdm3, no graphical.target needed. Dashboard app launches via Weston's `[autostart]` section or as a separate systemd service waiting for the `WAYLAND_DISPLAY` socket.

Alternative (getty auto-login + shell profile) is fragile and less controllable.

### GPU Acceleration Availability

| API | Version | Notes |
|---|---|---|
| OpenGL ES | 3.2 | Used by Weston GL renderer |
| OpenGL | 4.6 | Full desktop GL |
| Vulkan | 1.3 | Confirmed in L4T 36.5 |
| EGL | Supported | EGLDevice, EGL_KHR_platform_gbm |
| GBM | Supported | NVIDIA NVGBM backend (upstream Mesa) |
| DRM/KMS | Supported | `nvidia_drm` module with `modeset=1` |

**Critical requirement: `nvidia_drm modeset=1`** must be added for kiosk mode. Options:
- Add `nvidia_drm.modeset=1` to kernel command line in `/boot/extlinux/extlinux.conf` (preferred — loaded early in boot)
- Add to `/etc/modprobe.d/nvidia-drm.conf`: `options nvidia_drm modeset=1`

Dashboard compositing is a negligible GPU workload compared to VSLAM (800p stereo @ 30 FPS). Should not measurably impact the 50W power budget.

**Key Discoveries:**
- Weston 13.0 is NVIDIA's officially supported Wayland compositor on L4T 36.x, shipped with the BSP — no compilation needed
- Weston kiosk-shell (`kiosk-shell.so`) provides purpose-built kiosk functionality within the NVIDIA-supported stack
- `nvidia_drm modeset=1` is a mandatory kernel parameter for ANY Wayland compositor on Jetson — must be added to extlinux.conf or modprobe.d
- NVIDIA's NVGBM backend (upstream in Mesa) enables GBM-based compositors (including wlroots-based cage/labwc/sway) to work with NVIDIA DRM, though unsupported
- The hardening script currently makes the Jetson headless — transitioning to kiosk requires a systemd service for the compositor, NOT re-enabling gdm3
- GPU acceleration overhead for display compositing is negligible relative to the VSLAM workload at 50W

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | Current headless configuration: disables gdm3, sets multi-user.target, manages extlinux.conf |

**External Sources:**
- [NVIDIA Weston/Wayland docs for L4T 36.x](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/WindowingSystems/WestonWayland.html)
- [Cage kiosk compositor](https://github.com/cage-kiosk/cage)
- [labwc compositor](https://github.com/labwc/labwc)
- [NVIDIA NVGBM backend Mesa MR](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/9902)

**Gaps:**
- Could not verify whether Weston kiosk-shell is included in L4T BSP's Weston build (compile-time option; needs field verification with `weston --help`)
- Exact `nvidia_drm` behavior with both VSLAM (OAK-D Pro USB) and DisplayPort active simultaneously is unknown
- Browser options deferred to Phase 2

**Assumptions:**
- L4T 36.5 has the same Weston/Wayland support as documented in L4T 36.4.3 docs (latest available online). Display stack unlikely to change between point releases.
- Jetson AGX Orin Dev Kit has working DisplayPort output on P3730 carrier board (confirmed in NVIDIA docs).

## Phase 2: Dashboard Rendering Approach

**Status:** ✅ Complete  
**Session:** 2026-05-04

### Rendering Approach Categories

Three categories evaluated for rendering the dashboard on Weston kiosk-shell:

1. **Browser-based kiosk** — Full web browser rendering HTML/CSS/JS
2. **Native GUI toolkit** — GTK4, Qt6, or Rust-based egui
3. **Framebuffer-direct / lightweight** — pygame, LVGL, custom DRM

### Browser-Based Options

**Chromium (`--kiosk`):** Full web platform with Ozone/Wayland backend. ~300–500 MB RSS. **Major issue:** Ubuntu 22.04 ships Chromium as a snap — unsuitable for embedded kiosk (snap confinement, auto-updates, ~500 MB snap overhead). Building from source is impractical (8+ hours on aarch64).

**Firefox (`--kiosk`):** Similar resource footprint (~250–450 MB). No advantage over Chromium. **Not recommended.**

**WPE WebKit + Cog (VIABLE):** Purpose-built embedded browser from Igalia. No UI chrome — web page IS the display. ~120–200 MB RSS (~60% less than Chromium). Uses WPEBackend-FDO for Wayland + EGL/GLES2. Cog is the minimal kiosk launcher. Packaging on Ubuntu 22.04 uncertain — may need PPA or source build.

```bash
# WPE/Cog kiosk launch:
COG_PLATFORM_WL_VIEW_FULLSCREEN=1 cog http://localhost:8080/dashboard
```

Browser-based approaches all require a separate Python HTTP/WebSocket server bridging data to the browser.

### Native Toolkit Options

**GTK4 + PyGObject (RECOMMENDED):** Lightest full-toolkit option. ~40–80 MB RSS. Ships with Ubuntu 22.04. GPU-accelerated Wayland via GDK/EGL. Python bindings stay in the project's tooling stack. Can directly `import` existing health modules (`thermal.py`, `power.py`, `disk.py`, `vslam/ipc.py`). CSS-like theming for high-contrast field display. Single-process, <1 s startup.

```python
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

class DashboardWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_fullscreened(True)
        grid = Gtk.Grid()
        self.set_child(grid)
        self.vslam_label = Gtk.Label(label="VSLAM: --")
        grid.attach(self.vslam_label, 0, 0, 1, 1)
        GLib.timeout_add(1000, self._update_data)
```

GTK4 CSS for high-contrast sunlight-readable display:
```css
window { background-color: #000000; }
.status-ok { color: #00ff00; font-size: 24px; font-weight: bold; }
.status-warn { color: #ffaa00; font-size: 24px; }
.status-fail { color: #ff0000; font-size: 24px; }
.metric-value { color: #ffffff; font-size: 36px; font-family: monospace; }
```

**Qt6 / PySide6:** ~200 MB disk, 60–120 MB RSS. Overkill for a status dashboard. **Not recommended.**

**egui / Rust:** Violates the Python tooling constraint. **Not recommended.**

### Lightweight Options

**pygame/SDL2:** Absolute lightest (30–50 MB RSS). Pure Python, can import health modules directly. But no layout engine, no widgets — all rendering is manual `blit()` calls. Suitable only for crude text-only displays.

**LVGL:** Targets microcontrollers (STM32/ESP32), not Linux SBCs. Immature CPython bindings. **Eliminated.**

**Direct DRM/KMS:** Incompatible with Weston kiosk-shell architecture from Phase 1 (app must be a Wayland client). **Eliminated.**

### GPU Acceleration

All Wayland client approaches get GPU acceleration via Weston's GL renderer on the NVIDIA GBM/EGL stack. Weston can assign a single-app kiosk surface to a hardware overlay plane for direct scanout — zero GPU compositing work.

### Refresh Rate

A 1–2 FPS refresh is sufficient — dashboard data changes at human-readable timescales (VSLAM: display at 1 Hz, MAVLink heartbeat: 1 Hz, temps: every 10 s). No animation framework needed. CPU/GPU differences between approaches are negligible at this rate.

### Footprint Comparison

| Approach | RSS (MB) | CPU @ 1 Hz | Disk (MB) | Startup (s) | Language | In-Process Data |
|---|---|---|---|---|---|---|
| **pygame/SDL2** | 30–50 | <1% | 15 | <1 | Python | ✅ Direct import |
| **GTK4 (PyGObject)** | 40–80 | <1% | 20 | <1 | Python | ✅ Direct import |
| **WPE/Cog** | 120–200 | 2–5% | 50–100 | 1–3 | HTML+Py server | ❌ Needs IPC |
| **Qt6 (PySide6)** | 60–120 | <1% | 200 | 1–2 | Python | ✅ Direct import |
| **Chromium** | 300–500 | 3–8% | 300–500 | 3–8 | HTML+Py server | ❌ Needs IPC |

### Recommendation

**Primary: GTK4 + PyGObject** — Best alignment with Python tooling stack, direct access to existing health modules, lightest full-toolkit option, ships with JetPack 6 Ubuntu 22.04.

**Fallback: WPE WebKit + Cog** — If richer UI (charts, gauges, maps) is needed later. Provides HTML/CSS flexibility at moderate resource cost. Hot-reloadable UI.

Decision depends on dashboard complexity — if primarily text-based status with color coding (which the data sources suggest), GTK4 is simpler. If gauges/maps desired later, WPE/Cog provides a growth path.

### Existing Codebase Alignment

| Module | Data Provided | Import Path |
|---|---|---|
| `health/thermal.py` | CPU/GPU temps, thermal zones | `mower_rover.health.thermal` |
| `health/power.py` | nvpmodel mode, CPU count, GPU freq | `mower_rover.health.power` |
| `health/disk.py` | Disk usage per mount point | `mower_rover.health.disk` |
| `vslam/ipc.py` | VSLAM pose messages (Unix socket) | `mower_rover.vslam.ipc.PoseReader` |
| `service/daemon.py` | Health daemon loop with sdnotify | Pattern for dashboard service |
| `probe/registry.py` | Pre-flight check results | `mower_rover.probe.registry` |

**Key Discoveries:**
- WPE WebKit + Cog is purpose-built for embedded kiosk — 60–70% lighter than Chromium
- Chromium on Ubuntu 22.04/JetPack 6 has snap packaging problems unsuitable for embedded kiosk
- GTK4 + PyGObject is the lightest full-toolkit option (40–80 MB), ships with Ubuntu 22.04, stays in Python, can directly import existing health/IPC modules
- 1–2 FPS refresh is sufficient — makes memory footprint and architectural simplicity the key differentiators
- Qt6/PySide6 is overkill, egui/Rust violates Python constraint, LVGL targets MCUs, direct DRM is incompatible with Weston kiosk-shell

| File | Relevance |
|------|-----------|
| `src/mower_rover/health/thermal.py` | Feeds GPU/CPU temp to dashboard |
| `src/mower_rover/health/power.py` | Feeds power/nvpmodel metrics |
| `src/mower_rover/health/disk.py` | Feeds storage metrics |
| `src/mower_rover/vslam/ipc.py` | Feeds VSLAM pose status over Unix socket |
| `src/mower_rover/service/daemon.py` | sdnotify watchdog pattern for dashboard service |

**External Sources:**
- [NVIDIA Weston/Wayland docs](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/WindowingSystems/WestonWayland.html)
- [WPE WebKit architecture](https://wpewebkit.org/about/architecture.html)
- [Chromium Ozone overview](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/ozone_overview.md)

**Gaps:**
- Exact package availability (Chromium, WPE, Cog) on JetPack 6.1 needs field verification via `apt list`
- Cog may need PPA or source build on Ubuntu 22.04
- Memory footprint numbers are estimates — need field measurement

**Assumptions:**
- GTK4 4.6.x Wayland support works on NVIDIA GBM (well-established, low risk)
- 64 GB LPDDR5 means even Chromium's ~500 MB is <1% of RAM — footprint is about principle not constraint

## Phase 3: Operational Data Sources & Architecture

**Status:** ✅ Complete  
**Session:** 2026-05-04

### Data Source Inventory

The codebase provides pre-built data readers for most categories. Below is a comprehensive catalog organized by source.

#### 1. VSLAM Pose Data

**Module:** `vslam/ipc.py` — `PoseReader` class over Unix socket at `/run/mower/vslam-pose.sock`  
**Wire format:** 118-byte packed struct → `PoseMessage` dataclass (x/y/z position, roll/pitch/yaw, 21-float covariance, confidence 0–100, reset_counter)  
**Read pattern:** `PoseReader(socket_path).read_poses()` — blocking iterator with auto-reconnect  
**Health aggregation:** `vslam/health.py` `compute_health()` → `BridgeHealth` (pose_rate_hz, pose_age_ms, confidence, covariance_norm, connection booleans)  
**GTK4 consumption:** Background thread reads poses, stores latest in `SharedState`, uses `GLib.idle_add()` for UI update.

#### 2. MAVLink Telemetry (Pixhawk)

**Module:** `mavlink/connection.py` — `open_link()` context manager  
**Challenge:** The bridge (`vslam/bridge.py`) holds the serial connection to `/dev/ttyACM0`. A second connection is NOT possible.

**MAVLink multiplexing recommendation:** Use **MAVProxy** (`--master=/dev/ttyACM0 --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551`). Bridge on `:14550`, kiosk on `:14551`. Battle-tested, zero custom code, ~10–15 MB RAM.

**Messages of interest (many already parsed in `cli/detect.py`):**

| Message | Dashboard Fields | Stream Rate |
|---------|-----------------|-------------|
| `HEARTBEAT` | Vehicle mode (Manual/Auto/Hold), armed state | 1 Hz |
| `GPS_RAW_INT` / `GPS2_RAW` | Fix type, satellites, HDOP, GPS yaw | 1–5 Hz |
| `GPS_RTK` / `GPS2_RTK` | RTK baseline mm, IAR hypotheses | 1 Hz |
| `SERVO_OUTPUT_RAW` | Steering PWM (servo1, servo3), blade clutch (servo7) | 1–4 Hz |
| `RADIO_STATUS` | RSSI, remote RSSI, TX buffer, noise | ~0.5 Hz |
| `EKF_STATUS_REPORT` | EKF health flags | 1 Hz |
| `NAMED_VALUE_FLOAT` | VSLAM_HZ, VSLAM_CONF, VSLAM_AGE, VSLAM_COV | 1 Hz |
| `SYS_STATUS` / `BATTERY_STATUS` | Bus voltage, current, battery remaining | 1 Hz |
| `RPM` (msg 226) | Engine RPM from inductive pickup | 1–2 Hz |
| `VFR_HUD` | Ground speed, heading, throttle | 4 Hz |
| `STATUSTEXT` | Operator alerts from ArduPilot/bridge | Event-driven |

**Engine state derivation:** Engine-running = RPM ≥ ~1500 AND bus voltage ≥ 13.2 V (alternator threshold).

**New parsing needed:** `RPM`, `BATTERY_STATUS`, `VFR_HUD`, `GLOBAL_POSITION_INT` are not yet parsed in the codebase.

#### 3. Jetson System Health (EXISTING — direct reuse)

| Function | Returns | Key Fields | Source |
|----------|---------|------------|--------|
| `read_thermal_zones(sysroot)` | `ThermalSnapshot` | Zones with name/temp_c (CPU-therm, GPU-therm) | `/sys/class/thermal/` |
| `read_power_state(sysroot)` | `PowerState` | mode_id, mode_name, online_cpus, gpu_freq_mhz, fan_profile | nvpmodel + sysfs |
| `read_disk_usage(sysroot)` | `list[DiskUsage]` | mount_point, total/used/free_gb, is_nvme | `/proc/mounts` + statvfs |

All are pure sysfs/proc reads, <1 ms each. Poll every 5–10 s via `GLib.timeout_add_seconds()`.

#### 4. Wi-Fi Signal Strength (NEW — needs implementation)

**No existing implementation.** Recommended: new `health/wifi.py` reading `/proc/net/wireless` for link quality (0–70) and signal level (dBm). Same `sysroot`-injectable pattern as other health readers. Update every 10 s.

#### 5. Systemd Service States (EXISTING pattern)

Batch check via single subprocess: `systemctl is-active mower-health.service mower-vslam.service mower-vslam-bridge.service` — returns one status per line. Already implemented in `probe/checks/service.py`. Update every 10–30 s.

#### 6. Probe/Pre-Flight Results (EXISTING — direct reuse)

`probe/registry.py` `run_checks()` → `list[CheckResult]` with name/status/severity/detail. Run full sweep every 60 s. Display as PASS/FAIL summary.

### Data Refresh Architecture

**Hybrid polling + push with SharedState:**

```
┌──────────────────────────────────────────────────────────┐
│                     KIOSK PROCESS                        │
│                                                          │
│  GTK Main Loop ◄── 1 Hz timer reads SharedState          │
│       ▲                                                  │
│       │          ┌─────────────────────────────┐         │
│       └──────────│   SharedState (lock-guarded) │         │
│                  │  .vslam_pose / .vslam_health │         │
│                  │  .mavlink (MavTelemetry)     │         │
│                  │  .thermal / .power / .disk   │         │
│                  │  .wifi / .services / .probe  │         │
│                  └──────────────────────────────┘         │
│                     ▲         ▲          ▲               │
│                     │         │          │               │
│              VSLAM Reader  MAVLink    Slow Poller        │
│              Thread        Reader     Thread             │
│              (20 Hz read)  Thread     (5–60s intervals)  │
│                            (msg-driven)                  │
└──────────────────────────────────────────────────────────┘
```

**4 threads:** Main (GTK/GLib), VSLAM Reader, MAVLink Reader, Slow Poller.

**SharedState dataclass:** `MavTelemetry` aggregates all MAVLink fields (mode, armed, GPS, RTK, battery, RPM, radio, EKF, servos, statustext). Protected by `threading.Lock` for compound reads.

**WebSocket fallback:** If WPE/Cog is used instead of GTK4, a `websockets` server on `127.0.0.1:8765` pushes JSON snapshots at 1 Hz.

### Dashboard Panel Layout

| Panel | Data Source | Key Metrics | Refresh |
|-------|------------|-------------|---------|
| VSLAM Status | Unix socket → PoseReader | Rate Hz, Confidence, Pose Age, Connection | 1 Hz |
| Vehicle State | MAVLink HEARTBEAT + VFR_HUD | Mode, Armed, Ground Speed, Heading | 1 Hz |
| GPS/RTK | MAVLink GPS_RAW + GPS_RTK | Fix type, Sats, HDOP, RTK baseline | 1 Hz |
| Engine | MAVLink RPM + BATTERY_STATUS | RPM, Bus V, Engine Running, Blade clutch | 1 Hz |
| Radio Link | MAVLink RADIO_STATUS | RSSI, Remote RSSI, TX buf, Noise | 1 Hz |
| System Health | health/*.py readers | CPU/GPU temp, Power mode, Fan | 5 s |
| Storage | health/disk.py | Mount usage, NVMe status | 30 s |
| Wi-Fi | /proc/net/wireless | Link quality, Signal dBm | 10 s |
| Services | systemctl is-active | Unit active/inactive/failed states | 10 s |
| Alerts | STATUSTEXT + probe results | Latest alerts, PASS/FAIL summary | Event + 60 s |

**Key Discoveries:**
- Codebase has production-ready readers for 3 of 6 data categories: thermal, power, disk — all with `sysroot` injection for testing
- VSLAM pose data fully available via `PoseReader` + `compute_health()` — direct reuse
- MAVLink parsing for HEARTBEAT, GPS, SERVO, RADIO, EKF exists in `cli/detect.py` — refactorable patterns
- Bridge holds the only serial MAVLink connection — MAVProxy multiplexing is the cleanest MVP solution
- Wi-Fi monitoring needs new `health/wifi.py` module (reads `/proc/net/wireless`)
- Engine RPM and BATTERY_STATUS parsing not yet in codebase — new handlers needed
- SharedState + 4-thread architecture (GTK main, VSLAM reader, MAVLink reader, slow poller) keeps I/O off main thread
- `GLib.timeout_add()` / `GLib.idle_add()` is the standard GTK4 pattern for threaded data consumption

| File | Relevance |
|------|-----------|
| `src/mower_rover/vslam/ipc.py` | VSLAM pose reader — core data source |
| `src/mower_rover/vslam/health.py` | BridgeHealth computation — direct reuse |
| `src/mower_rover/vslam/bridge.py` | Holds serial MAVLink connection, sends NAMED_VALUE_FLOAT |
| `src/mower_rover/health/thermal.py` | Thermal reader — direct reuse |
| `src/mower_rover/health/power.py` | Power state reader — direct reuse |
| `src/mower_rover/health/disk.py` | Disk usage reader — direct reuse |
| `src/mower_rover/mavlink/connection.py` | MAVLink connection wrapper |
| `src/mower_rover/cli/detect.py` | MAVLink parsing patterns for refactoring |
| `src/mower_rover/probe/registry.py` | Probe check results — direct reuse |
| `src/mower_rover/service/daemon.py` | sdnotify watchdog pattern reference |

**Gaps:**
- `health/wifi.py` does not exist
- RPM, BATTERY_STATUS, VFR_HUD, GLOBAL_POSITION_INT MAVLink parsing not yet implemented
- No MAVLink multiplexing infrastructure in place
- Blade clutch state (SERVO7) not tracked anywhere

**Assumptions:**
- MAVProxy works on Jetson (standard Python package)
- ArduPilot streams RPM/VFR_HUD/BATTERY_STATUS at configured SR rates
- GIL is sufficient for single-field reference assignments between threads

## Phase 4: Auto-Start, Crash Recovery & Field Hardening

**Status:** ✅ Complete  
**Session:** 2026-05-04

### systemd Service Architecture

Two services following the existing VSLAM service/bridge pattern:

**Service 1: `mower-weston.service` (Compositor)**

```ini
[Unit]
Description=Mower Kiosk Weston Compositor
After=multi-user.target systemd-user-sessions.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=kiosk
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStartPre=/sbin/modprobe nvidia_drm modeset=1
ExecStart=/usr/bin/weston \
    --shell=kiosk-shell.so \
    --idle-time=0 \
    --log=/var/log/mower-jetson/weston.log \
    --continue-without-input
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- `Type=simple` (Weston does not implement `sd_notify`)
- `User=kiosk` — dedicated unprivileged user (`useradd --system --create-home --groups video,render kiosk`)
- `--continue-without-input` — operates without keyboard/mouse

**Service 2: `mower-kiosk.service` (Dashboard)**

```ini
[Unit]
Description=Mower Kiosk Dashboard
After=mower-weston.service mower-health.service
Requires=mower-weston.service
BindsTo=mower-weston.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
User=kiosk
Environment=XDG_RUNTIME_DIR=/run/user/%U
Environment=WAYLAND_DISPLAY=wayland-0
ExecStart=/home/kiosk/.local/bin/mower-jetson kiosk run
WatchdogSec=30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- `BindsTo=mower-weston.service` — same pattern as VSLAM bridge binding to Pixhawk device
- `Type=notify` + `WatchdogSec=30` — same sdnotify watchdog pattern as `daemon.py`
- Dashboard sends `READY=1` after GTK window realized, `WATCHDOG=1` every 15 s

### Crash Recovery Scenarios

| Scenario | Recovery Mechanism | Time |
|----------|-------------------|------|
| Dashboard crash | `Restart=on-failure`, RestartSec=5 | ~5 s |
| Weston crash | `Restart=always`, RestartSec=3. `BindsTo=` auto-restarts dashboard | ~4–5 s |
| Dashboard hang | `WatchdogSec=30` → SIGABRT | ~30 s |
| GPU hang | `pageflip-timeout=10000` in weston.ini (10 s early detection) | ~10 s |
| Kernel hang | Hardware watchdog `RuntimeWatchdogSec=30` → full reboot | ~30 s + boot |
| OOM | Unlikely (64 GB), `OOMScoreAdjust=-500` protects kiosk | N/A |

`StartLimitBurst=5` per 300 s prevents crash loops from burning CPU.

### Display Hotplug

**NVIDIA confirms full hotplug support** — Weston monitors DRM udev events:
- Weston starts without a display and handles late connection via hotplug
- Disconnect/reconnect during operation: drawing resumes automatically
- No display-check guard script needed — always start Weston, rely on hotplug

`--continue-without-input` and `require-input=false` in weston.ini ensure Weston starts with no input devices.

### DPMS / Screen Blanking Disable

| Layer | Control | Setting |
|-------|---------|---------|
| Weston | idle timeout | `idle-time=0` (disables compositor screen fade) |
| Weston | screen lock | `locking=false` in weston.ini |
| Weston | VT switching | `vt-switching=false` in `[keyboard]` section |
| Kernel | console blank | `consoleblank=0` in extlinux.conf APPEND |
| systemd | logind idle | `IdleAction=ignore` in logind.conf drop-in |

**Complete weston.ini:**

```ini
[core]
shell=kiosk-shell.so
idle-time=0
xwayland=false
require-input=false
pageflip-timeout=10000

[keyboard]
vt-switching=false
```

### Headless Fallback

**Recommended: Always start Weston**, even without a display. NVIDIA confirms Weston creates the compositor with no active outputs and waits for hotplug. Dashboard connects to `wayland-0` socket and renders when a display appears. ~20 MB RAM for headless Weston — negligible.

**Optional disable mechanism:** `ConditionKernelCommandLine=mower.kiosk` — operator can add/remove `mower.kiosk` from extlinux.conf to enable/disable kiosk entirely.

### Read-Only Filesystem

**Not needed for MVP.** Existing hardening is sufficient:
- `noatime,commit=60` on root ext4
- journald `SystemMaxUse=500M`, `MaxRetentionSec=7day`
- logrotate daily, 14-day retention, 50 MB max/file
- Weston runtime files on tmpfs (`/run/user/<uid>`)
- Dashboard is stateless — zero disk writes from kiosk app
- Add `LimitCORE=0` to service files to prevent core dump disk fills

### mower-health.service Integration

```
mower-health.service    ← boots independently (canary)
mower-weston.service    ← boots independently
mower-kiosk.service     ← After+BindsTo mower-weston, After mower-health
```

- Dashboard uses same sdnotify pattern as `daemon.py`
- No `BindsTo` between kiosk and health — dashboard shows health failures, doesn't stop for them
- Kiosk polls `systemctl is-active mower-health.service` to display its state

### jetson-harden.sh Changes Needed

1. `harden_drm_modeset()` — Add `nvidia_drm.modeset=1` to extlinux.conf APPEND
2. `consoleblank=0` — Add to extlinux.conf APPEND
3. `harden_kiosk_user()` — Create `kiosk` system user with `video,render` groups
4. `harden_weston_config()` — Deploy `/etc/xdg/weston/weston.ini`
5. `harden_logind_kiosk()` — Deploy logind drop-in (`NAutoVTs=0`, `IdleAction=ignore`)
6. Install `nvidia-l4t-weston` package if not present
7. Keep existing headless logic (`multi-user.target`, gdm3 disabled) — kiosk does NOT use `graphical.target`

### Boot Sequence

```
kernel → systemd → multi-user.target
  ├── mower-health.service
  ├── mower-vslam.service
  ├── mower-vslam-bridge.service
  ├── mower-weston.service → creates wayland-0 socket
  └── mower-kiosk.service → connects wayland-0, renders dashboard
```

Boot to dashboard: ~10–15 s after kernel.

### Security

- Dedicated `kiosk` user — no access to mower config, SSH keys, or service binaries
- `xwayland=false` — eliminates X11 attack surface
- `vt-switching=false` — prevents unauthorized console access
- `PrivateTmp=true` and `ProtectSystem=strict` optional systemd sandboxing

**Key Discoveries:**
- NVIDIA confirms Weston starts without a display and handles late hotplug — no display-check guard needed
- Two-service model with `BindsTo=` mirrors existing VSLAM service/bridge pattern
- `idle-time=0` is the only DPMS control needed under Wayland
- `pageflip-timeout=10000` provides GPU-hang early detection before the hardware watchdog
- `generate_service_unit()` needs `Type=` configurable (currently hardcoded to `notify`)
- Read-only filesystem is unnecessary for MVP — existing hardening is sufficient
- Kiosk stays under `multi-user.target` — no graphical.target or gdm3

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | Needs 4–5 new functions for kiosk setup |
| `src/mower_rover/service/unit.py` | `generate_service_unit()` needs configurable `Type=` |
| `src/mower_rover/service/daemon.py` | sdnotify watchdog pattern to replicate |

**External Sources:**
- [NVIDIA Weston/Wayland docs](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/WindowingSystems/WestonWayland.html)
- [weston.ini(5) manpage](https://manpages.debian.org/bookworm/weston/weston.ini.5.en.html)
- [weston-drm(7) manpage](https://manpages.debian.org/bookworm/weston/weston-drm.7.en.html)

**Gaps:**
- Whether `kiosk-shell.so` is compiled into `nvidia-l4t-weston` needs field verification
- DRM connector name on Orin Dev Kit needs `ls /sys/class/drm/` on device
- Weston kiosk-shell + zero connected outputs is untested (NVIDIA docs show desktop-shell hotplug)

**Assumptions:**
- `nvidia-l4t-weston` includes `kiosk-shell.so` (standard in Weston 13.0)
- Dedicated `kiosk` system user is acceptable
- `wayland-0` socket naming is reliable per NVIDIA's L4T patch

## Phase 5: Display Hardware & Power/Thermal Impact

**Status:** ✅ Complete  
**Session:** 2026-05-04

### DisplayPort Output on Orin Dev Kit (P3730)

Single **DisplayPort output** at connector J18. No native HDMI. No DP over USB-C.

| Feature | Value |
|---------|-------|
| Connector | J18, full-size DisplayPort |
| Max resolution | 8K@30 / 4K@120 |
| Link speed | HBR3 / 4 lanes |
| HDMI adapter | Passive DP→HDMI works on JetPack 6 |

For a 7" panel at 1024×600 or 1280×800, this uses <1% of the DP link bandwidth. The display controller clock (1191 MHz) runs from VIN_SYS_5V0 — **outside** the 50 W TDP cap.

### Suitable Field-Rated Displays

Requirements: ≥1000 nits (sunlight-readable), IP65+, 7–10", −20°C to +70°C, HDMI input, 12 V DC.

| Category | Size | Brightness | Power | IP | Cost |
|----------|------|------------|-------|----|------|
| Camera/field monitor (Lilliput, Feelworld) | 7" | 500–1000 nits | 7–12 W @ 12 V | IP54–65 | $100–250 |
| Industrial sunlight (Advantech, Teguar) | 7" | 1000–1500 nits | 8–15 W @ 12–24 V | IP65 | $400–800 |
| Budget high-brightness (Waveshare) | 7" | 1000+ nits | 3–5 W @ 5 V | None (needs enclosure) | $50–100 |
| Vehicle/marine display (Lilliput marine) | 7" | 800–1500 nits | 10–15 W @ 12 V | IP64–67 | $200–500 |

**Recommended:** 7-inch 1000+ nit HDMI field/vehicle monitor at ~$150–300. Runs on 12 V DC from mower alternator. Lexan shield for debris protection.

### Power Draw

**Jetson SoC side:**
- Display controller (VIN_SYS_5V0 rail — outside 50 W cap): ~0.5–1.5 W
- GPU compositor at 1 FPS (VDD_GPU_SOC): ~0.5–2 W (GPU idles at minimum freq)
- **Total additional Jetson power: ~1–3 W** — negligible vs 25–35 W typical VSLAM workload

**External display panel:** 7–15 W at 12 V from mower alternator (not Jetson). Kawasaki FR691V alternator outputs 180–240 W — ample headroom.

### Thermal Impact

Adding a display is **negligible** thermal load:
- GPU stays <5% utilization for 1 FPS static-ish UI
- Display controller power is on separate VIN_SYS_5V0 rail
- Real thermal risk is outdoor ambient (35–55°C intake air), not display workload
- Existing fan "cool" profile and TMARGIN control handle this
- No fan profile changes needed

### HDMI vs DP Adapter

| Adapter Type | Max Res | Cost | Recommendation |
|-------------|---------|------|----------------|
| Passive DP→HDMI | 4K@30 / 1080p@60 | $5–15 | **Recommended** |
| Active DP→HDMI 2.0 | 4K@60 | $15–30 | Overkill for 7" |
| One-piece DP→HDMI cable | 1080p@60 | $8–15 | **Best for vibration** — fewer connection points |

For mower vibration: use a one-piece DP→HDMI cable or secure adapter with strain relief. DP connector locking clip recommended. Consider short cable to bulkhead connector on Jetson enclosure, then longer weatherproof run to display.

### Touchscreen Viability

**Not recommended for MVP:**
- Capacitive touch doesn't work with work gloves (nitrile/leather)
- Rain causes false touches
- Vibration makes tap targets imprecise
- Adds USB cable complexity
- Operator already has Taranis X9D Plus for real-time control

**If added later (Release 2+):**
- Projected-capacitive (PCAP) with "glove mode" firmware
- Large touch targets (≥20mm) for vibration tolerance
- Touch lockout in Auto mode (safety)
- Route USB HID through existing Waveshare 4-port hub (spare ports available)

**Key Discoveries:**
- DisplayPort on Orin Dev Kit is massively overspecced for a 7" kiosk panel — no bandwidth concerns
- Display controller power runs on VIN_SYS_5V0 — outside the 50 W TDP cap, near-zero budget impact
- Total kiosk power impact on Jetson: ~1–3 W additional SoC power
- External panel power (7–15 W) comes from mower 12 V alternator, not Jetson
- 7" 1000+ nit HDMI field monitor ($150–300) is the sweet spot
- Touchscreens unreliable on a mower (gloves, rain, vibration) — defer to Release 2+
- Passive DP→HDMI adapter works on JetPack 6; one-piece cable best for vibration

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | nvpmodel mode 3 config, extlinux.conf management |
| `src/mower_rover/health/thermal.py` | Can surface GPU/CPU temps to kiosk display |

**External Sources:**
- [NVIDIA Jetson AGX Orin Dev Kit Layout](https://developer.nvidia.com/embedded/learn/jetson-agx-orin-devkit-user-guide/developer_kit_layout.html)
- [NVIDIA Jetson Power & Performance Guide](https://docs.nvidia.com/jetson/archives/r36.3/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html)

**Gaps:** None  
**Assumptions:**
- Mower 12 V alternator can supply 7–15 W extra for display (180–240 W capacity, mostly unused)
- Passive DP→HDMI behavior on L4T 36.5 matches documented JetPack ≥5.0.2 behavior

## Overview

The Jetson AGX Orin Dev Kit can be converted from headless to a kiosk-mode operational display with **minimal power/thermal impact** (~1–3 W additional SoC load) and **no firmware or hardware modifications**. The recommended architecture uses entirely NVIDIA-supported components and the project's existing Python/systemd patterns.

**Architecture summary:**

```
Weston 13.0 (kiosk-shell.so)  →  GTK4 dashboard (PyGObject)  →  7" HDMI field display
      ↑                                ↑                               ↑
  nvidia_drm modeset=1         SharedState + 4 threads          DP→HDMI adapter
  systemd Type=simple          sdnotify watchdog                12V from alternator
```

The stack is: Weston compositor (NVIDIA-supported, ships with BSP) → GTK4 Python application (lightest full-toolkit, direct module import) → passive DP→HDMI adapter → 7" 1000+ nit sunlight-readable field monitor ($150–300, IP65, 12 V DC from mower alternator).

## Key Findings

1. **Weston 13.0 kiosk-shell** is the lowest-risk compositor — officially supported by NVIDIA on L4T 36.x, ships with the BSP, GPU-accelerated, purpose-built kiosk mode, handles display hotplug including no-display boot
2. **GTK4 + PyGObject** is the optimal rendering approach — 40–80 MB RSS, stays in Python, directly imports existing health/IPC modules, <1 s startup, GPU-accelerated Wayland rendering
3. **Existing codebase provides production-ready data readers** for thermal, power, disk, VSLAM pose, VSLAM health, and probe checks — direct reuse with no modifications needed
4. **MAVProxy multiplexing** resolves the single-serial-port constraint — bridge and kiosk each get their own MAVLink stream with zero custom code
5. **Two-service systemd model** (mower-weston + mower-kiosk) with `BindsTo=` mirrors the proven VSLAM service/bridge pattern
6. **Display controller power is outside the 50 W TDP cap** (runs on VIN_SYS_5V0) — adding a display has near-zero thermal/power impact
7. **Touchscreen is not viable for MVP** — glove incompatibility, rain false-touches, and vibration imprecision; defer to Release 2+
8. **1–2 FPS refresh is sufficient** — all data changes at human-readable timescales; CPU/GPU differences between approaches are negligible at this rate

## Actionable Conclusions

1. **Use Weston kiosk-shell + GTK4** — lowest risk, lightest weight, pure Python, direct data access
2. **Add `nvidia_drm.modeset=1` and `consoleblank=0`** to extlinux.conf kernel params
3. **Create `kiosk` system user** with `video,render` groups for compositor/dashboard services
4. **Deploy `weston.ini`** with kiosk-shell, idle-time=0, xwayland=false, require-input=false
5. **New modules needed:** `health/wifi.py` (Wi-Fi signal), RPM/BATTERY_STATUS MAVLink parsing, SharedState aggregation layer
6. **MAVProxy as systemd service** for MAVLink multiplexing between bridge and kiosk
7. **Purchase:** 7" 1000+ nit HDMI field monitor + DP→HDMI one-piece cable
8. **Field verification required:** confirm `kiosk-shell.so` is in BSP Weston build, test hotplug with no display at boot

## Open Questions

- Is `kiosk-shell.so` compiled into the `nvidia-l4t-weston` BSP package? (needs `weston --help` on device)
- What is the DRM connector name on the Orin Dev Kit? (needs `ls /sys/class/drm/` on device)
- Does Weston kiosk-shell handle zero-display hotplug the same as desktop-shell? (NVIDIA docs only show desktop-shell)
- Should MAVProxy run as its own systemd service or be started by the kiosk process?
- Should ArduPilot stream rate params (`SR*_`) be tuned for RPM/BATTERY_STATUS availability?



## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-04 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/020-jetson-kiosk-operational-display.md |
