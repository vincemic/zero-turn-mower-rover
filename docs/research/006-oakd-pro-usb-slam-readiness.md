---
id: "006"
type: research
title: "OAK-D Pro USB + SLAM Readiness on Jetson AGX Orin"
status: ✅ Complete
created: "2026-04-23"
current_phase: "✅ Complete"
---

## Introduction

This research investigates whether the **Luxonis OAK-D Pro** camera connected to the **NVIDIA Jetson AGX Orin** over USB is configured correctly and receives sufficient bandwidth for real-time SLAM workloads. The project's companion computer stack (vision document §Phase 11/12) depends on the OAK-D Pro providing stereo depth, IMU, and RGB streams through DepthAI — all over a single USB 3.x link. Misconfiguration of the USB controller, power delivery, DepthAI pipeline settings, or Linux kernel USB parameters can silently throttle bandwidth and cause frame drops that degrade SLAM. This research documents the full configuration surface, software dependencies, and concrete validation steps an operator must execute to confirm the camera is SLAM-ready before field deployment.

## Objectives

- Determine the USB 3.x controller topology on the Jetson AGX Orin and confirm which port(s) provide full SuperSpeed (5 Gbps+) bandwidth to the OAK-D Pro
- Document the DepthAI SDK / depthai-core installation procedure on JetPack 6 (L4T 36.x, aarch64) including version compatibility
- Identify the OAK-D Pro stream configuration (resolution, FPS, encoding) required to stay within USB 3.x bandwidth while meeting SLAM input needs
- Enumerate Linux kernel / udev / power-management settings that affect USB camera throughput on the Jetson
- Define a repeatable validation checklist (CLI commands + Python script) that confirms the camera is connected at USB 3.x speed, streams are running at target FPS without drops, and DepthAI reports no errors

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Jetson AGX Orin USB 3.x Topology & Hardware | ✅ Complete | USB controller layout; which physical ports are USB 3.2 Gen 1/2; OAK-D Pro USB requirements (power draw, bandwidth); how to confirm SuperSpeed negotiation; relevant device-tree / pinmux considerations on L4T 36.x | 2026-04-23 |
| 2 | DepthAI SDK Installation on JetPack 6 | ✅ Complete | depthai + depthai-sdk version matrix vs. JetPack 6 / L4T 36.x / Python 3.11+; pip vs. apt vs. source build; OpenCV and numpy compatibility; udev rules for non-root access; known issues on aarch64; XLink protocol basics | 2026-04-23 |
| 3 | OAK-D Pro Stream Configuration for SLAM | ✅ Complete | Stereo depth, mono left/right, RGB, and IMU stream parameters (resolution, FPS, encoding); bandwidth math per stream; typical SLAM pipeline input requirements (RTAB-Map, ORB-SLAM3, or Isaac VSLAM); recommended pipeline profile that balances quality vs. USB bandwidth; on-device (Myriad X) vs. host processing trade-offs | 2026-04-23 |
| 4 | Linux USB Power & Throughput Tuning | ✅ Complete | USB autosuspend disable; udev power rules for OAK-D; `usbcore.autosuspend=-1` kernel param; USB buffer sizes (`usbfs_memory_mb`); Jetson-specific USB quirks (XHCI driver, tegra-xudc); nvpmodel / jetson_clocks interaction with USB controller clocks; thermal throttling impact on USB throughput | 2026-04-23 |
| 5 | Validation Checklist & Scripted Checks | ✅ Complete | Step-by-step operator checklist: `lsusb -t` tree verification; `dmesg` SuperSpeed confirmation; DepthAI `device.getUsbSpeed()` API; FPS counter script (Python) confirming target rates; latency measurement; frame-drop detection; integration with existing `mower-jetson probe` oakd check; pre-flight check items for SLAM readiness | 2026-04-23 |

## Phase 1: Jetson AGX Orin USB 3.x Topology & Hardware

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Jetson AGX Orin Developer Kit USB Port Layout

The Jetson AGX Orin Developer Kit (P3737 carrier board + P3701 SOM) exposes **six USB ports** across four physical connector groups:

| Ref | Connector | Type | USB Spec | Location | Notes |
|-----|-----------|------|----------|----------|-------|
| J24 (port 4) | USB Type-C | DFP only | USB 3.2 Gen 2 (10 Gbps) | Above DC jack | Host-only Type-C |
| J33 (port 7) | 2× USB Type-A | Host | USB 3.2 Gen 2 (10 Gbps) | Next to Ethernet | Two stacked Type-A |
| J40 (port 10) | USB Type-C | UFP + DFP (OTG) | USB 3.2 Gen 2 (10 Gbps) | Next to 40-pin header | Also used for flashing |
| J33 (port 12) | 2× USB Type-A | Host | USB 3.2 Gen 1 (5 Gbps) | Next to 40-pin header | Two stacked Type-A |

**Recommendation for OAK-D Pro:** Connect to one of the **J33 Gen 2 Type-A ports (port 7, next to Ethernet)** using a USB-C to USB-A 3.x cable, or to the **J24 Type-C port** using a USB-C to USB-C cable. Both provide 10 Gbps SuperSpeed+ bandwidth. The Gen 1 ports (port 12) still provide 5 Gbps, which is sufficient for most SLAM stream configurations but leaves less headroom.

### UPHY Lane Architecture & USB 3.x Controller Topology

The Tegra234 SoC uses a **Universal Physical Layer (UPHY)** that multiplexes lanes among PCIe, UFS, and XUSB (USB SuperSpeed). There are three UPHY instances:

- **HSIO (UPHY0)** — 8 lanes, shared between USB 3.2 and PCIe C0/C1/C4
- **NVHS (UPHY1)** — 8 lanes, for PCIe C5
- **GBE (UPHY2)** — 8 lanes, shared between PCIe C7 and MGBE (10GbE)

The default Developer Kit configuration (`hsio-uphy-config-0`) allocates **3 UPHY lanes to USB SuperSpeed**:

| HSIO Lane | Assignment | USB3 Port | Physical Connector |
|-----------|-----------|-----------|-------------------|
| Lane 0 | USB 3.2 Port 0 | usb3-0 | J24 Type-C (DFP) — via `usb2-1` companion |
| Lane 1 | USB 3.2 Port 1 | usb3-1 | J40 Type-C (OTG) — via `usb2-0` companion |
| Lane 2 | USB 3.2 Port 2 | usb3-2 | J33 Gen 2 Type-A pair (via hub) — via `usb2-2` companion |

The **J33 Gen 1 Type-A ports (port 12)** use USB 2.0 UTMI pad 3 (`usb2-3`) but do **not** have a dedicated SuperSpeed lane — they operate at USB 3.2 Gen 1 (5 Gbps) through the carrier board's internal USB 3.x hub topology.

**Key controller nodes in the device tree:**

| Node | Address | Role |
|------|---------|------|
| `xusb_padctl` | `padctl@3520000` | USB pad controller (lane/port assignment) |
| xHCI (host) | `usb@3610000` | USB 3.2 host controller (SuperSpeed + HighSpeed) |
| xUDC (device) | `usb@3550000` | USB device controller (for OTG device mode) |

The xHCI controller `usb@3610000` handles **all** USB host traffic — both USB 2.0 (through UTMI pads) and USB 3.2 (through UPHY lanes). There is a single xHCI controller; all ports share it.

### Device Tree Port Configuration (L4T 36.x / JetPack 6)

From the NVIDIA platform adaptation docs, the default device tree for P3737+P3701 configures:

```
xusb_padctl: padctl@3520000 {
  pads {
    usb2 {
      lanes {
        usb2-0 { nvidia,function = "xusb"; };  // J40 (OTG Type-C)
        usb2-1 { nvidia,function = "xusb"; };  // J24 (Host Type-C)
        usb2-2 { nvidia,function = "xusb"; };  // J33 Gen 2 Type-A
        usb2-3 { nvidia,function = "xusb"; };  // J33 Gen 1 Type-A
      };
    };
    usb3 {
      lanes {
        usb3-0 { nvidia,function = "xusb"; };  // Lane 0 → J24
        usb3-1 { nvidia,function = "xusb"; };  // Lane 1 → J40
        usb3-2 { nvidia,function = "xusb"; };  // Lane 2 → J33 Gen 2
      };
    };
  };
  ports {
    usb2-0 { mode = "otg"; };
    usb2-1 { mode = "host"; };
    usb2-2 { mode = "host"; };
    usb2-3 { mode = "host"; };
    usb3-0 { nvidia,usb2-companion = <1>; };  // paired with usb2-1
    usb3-1 { nvidia,usb2-companion = <0>; };  // paired with usb2-0
    usb3-2 { nvidia,usb2-companion = <2>; };  // paired with usb2-2
  };
};
```

The Type-C ports use a **Cypress CYP4226 Type-C controller (U513)** and the `ucsi_ccg` driver for role switching and alt-mode. The XUSB firmware package (`nvidia-l4t-xusb-firmware`) provides the USB controller firmware — the project already holds this package in `jetson-harden.sh`.

**For the OAK-D Pro (a standard USB device), no device tree changes are required.** The default configuration provides full SuperSpeed on all three USB 3.2 port groups.

### OAK-D Pro USB Power Requirements

| Component | Power Draw |
|-----------|------------|
| Base (camera streaming) | 2.5–3.0 W |
| AI subsystem (VPU inference) | Up to 1.0 W |
| Stereo depth pipeline | Up to 0.5 W |
| Video encoder | Up to 0.5 W |
| IR dot projector (active stereo) | Up to 1.0 W |
| IR flood LED (night vision) | Up to 1.0 W |
| **Total max (all features active)** | **~7 W** |

USB 3.x spec provides **4.5 W (900 mA × 5 V)** from a standard Type-A port. The OAK-D Pro at full utilization (with IR projector + flood LED) can draw up to **7 W**, which exceeds the USB 3.x bus power budget.

**Implications for this project:**
- **Without IR features** (dot projector and flood LED disabled by default): typical draw is ~4–5 W — within USB 3.x bus power, but at the margin
- **With IR dot projector enabled** (recommended for active stereo in outdoor mowing): exceeds bus power; Luxonis recommends a **Y-adapter or external 5V power supply** rated at 15+ W
- The Jetson AGX Orin carrier board USB ports are rated for standard USB 3.x current (900 mA). Overdrawing can cause USB resets, frame drops, or device disconnects
- **Recommendation:** Use a **powered USB 3.x hub** or a **Luxonis Y-adapter cable** (USB-C with auxiliary power input) for field deployment, especially if the dot projector will be used for active stereo depth in low-texture environments (grass, pavement)

### OAK-D Pro USB Bandwidth Requirements

The OAK-D Pro uses the **XLink protocol** over USB for all data transfer between the Myriad X VPU and the host. XLink multiplexes multiple streams over a single USB connection.

The OAK-D Pro supports USB 3.2 Gen 2 (10 Gbps). By default, DepthAI negotiates USB 3.2 Gen 1 (5 Gbps / `SUPER` speed). To force 10 Gbps:

```python
with dai.Device(pipeline, maxUsbSpeed=dai.UsbSpeed.SUPER_PLUS) as device:
    ...
```

**Bandwidth per stream (unencoded):**

| Stream | Resolution | Bytes/px | 30 FPS BW | 60 FPS BW |
|--------|-----------|----------|-----------|----------|
| Color (NV12/YUV420) | 1080P | 1.5 | 747 Mbps | 1,494 Mbps |
| Color (NV12/YUV420) | 4K | 1.5 | 2,986 Mbps | N/A |
| Mono (grayscale) | 800P (1280×800) | 1 | 246 Mbps | 492 Mbps |
| Mono (grayscale) | 400P (640×400) | 1 | 62 Mbps | 123 Mbps |
| Depth (uint16) | 800P | 2 | 492 Mbps | 984 Mbps |
| Depth (uint16) | 400P | 2 | 123 Mbps | 246 Mbps |

**Typical SLAM stream set at USB 3.2 Gen 1 (5 Gbps effective ~3.2 Gbps after protocol overhead):**

| Stream | Config | BW |
|--------|--------|-----|
| Stereo depth | 400P @ 30fps | 123 Mbps |
| Left mono | 400P @ 30fps | 62 Mbps |
| Right mono | 400P @ 30fps | 62 Mbps |
| RGB (for mapping/viz) | 1080P @ 15fps | 374 Mbps |
| IMU | 200 Hz | ~0.1 Mbps |
| **Total** | | **~621 Mbps** |

This fits comfortably within USB 3.2 Gen 1 bandwidth. Encoding streams on-device (H.265/MJPEG) can reduce bandwidth dramatically if needed — Phase 3 will detail optimal stream profiles.

### Verifying SuperSpeed Negotiation on Linux

**Method 1: `lsusb -t` (tree view with speed)**

```bash
lsusb -t
```

Look for the OAK-D device (vendor `03e7`) and check the `speed` field:
- `5000M` = USB 3.2 Gen 1 (SuperSpeed)
- `10000M` = USB 3.2 Gen 2 (SuperSpeed+)
- `480M` = USB 2.0 (HighSpeed) — **problem: cable or port issue**

**Method 2: sysfs speed attribute**

```bash
for d in /sys/bus/usb/devices/*/; do
  if [ -f "$d/idVendor" ] && [ "$(cat "$d/idVendor")" = "03e7" ]; then
    echo "Device: $d"
    echo "Speed: $(cat "$d/speed") Mbps"
    echo "Version: $(cat "$d/version")"
  fi
done
```

The `speed` file returns: `480` (USB 2.0), `5000` (USB 3.2 Gen 1), or `10000` (USB 3.2 Gen 2).

**Method 3: dmesg kernel log**

```bash
dmesg | grep -i "new.*USB.*device\|SuperSpeed\|xhci"
```

Look for: `xhci-tegra 3610000.usb: new SuperSpeed Plus Gen 2 USB device number X using xhci-tegra`

**Method 4: DepthAI API**

```python
import depthai as dai

with dai.Device() as device:
    speed = device.getUsbSpeed()
    print(f"USB Speed: {speed.name}")
    # Expected: SUPER (5Gbps) or SUPER_PLUS (10Gbps)
    # Problem:  HIGH (480Mbps) or lower
```

### Pinmux / UPHY Considerations

The **default Developer Kit configuration requires no changes** for USB with the OAK-D Pro. Key points:

- The UPHY lane assignment is set at flash time via **ODMDATA** (`hsio-uphy-config-0` provides 3 USB 3.2 ports). If using a custom carrier board, verify ODMDATA includes USB lanes.
- The XUSB firmware (`nvidia-l4t-xusb-firmware`) must be present and matching the L4T version. The project's `jetson-harden.sh` already holds this package via `apt-mark hold`.
- The Tegra XHCI driver is `xhci-tegra` (kernel module), not the generic `xhci_hcd`. It handles USB 3.2 Gen 1 and Gen 2 on the Tegra234.
- USB pad voltage (3.3V tolerance) is configured in the pinmux BCT and should not be modified for standard USB operation.

**Key Discoveries:**
- Jetson AGX Orin Dev Kit has 6 USB ports across 4 connector groups; the 2× Type-A Gen 2 ports (J33, next to Ethernet) and J24 Type-C are the best choices for OAK-D Pro (all 10 Gbps capable)
- Three UPHY SuperSpeed lanes are available in the default configuration (hsio-uphy-config-0), mapped to usb3-0 (J24), usb3-1 (J40), and usb3-2 (J33 Gen 2)
- A single xHCI controller at `usb@3610000` (`xhci-tegra` driver) handles all USB host traffic
- OAK-D Pro can draw up to 7W at full utilization (with IR projector + flood LED), exceeding the 4.5W USB 3.x bus power spec — a powered hub or Y-adapter is recommended for field deployment with active stereo
- Without IR features, the OAK-D Pro draws ~4–5W, which is at the margin of bus power — thermal ambient and cable quality matter
- A typical SLAM stream set (400P depth + 400P mono pair + 1080P RGB @ 15fps + IMU) consumes ~621 Mbps — well within USB 3.2 Gen 1 effective throughput
- SuperSpeed negotiation can be verified via `lsusb -t`, `/sys/bus/usb/devices/*/speed`, `dmesg`, or DepthAI `device.getUsbSpeed()` API
- No device tree or pinmux changes are needed for the standard Dev Kit carrier board
- The XUSB firmware package is already held in the project's jetson-harden.sh

| File | Relevance |
|------|-----------|
| `src/mower_rover/probe/checks/oakd.py` | Existing OAK-D presence check (vendor ID only, no speed verification); will need enhancement in Phase 5 |
| `scripts/jetson-harden.sh` | Already holds `nvidia-l4t-xusb-firmware` package |

**Gaps:** Exact internal hub topology of J33 Gen 1 Type-A ports (port 12) not fully documented — they share bandwidth through an on-board hub, but the specific hub chip is not confirmed.  
**Assumptions:** Standard Jetson AGX Orin Developer Kit carrier board (P3737) with default ODMDATA (`hsio-uphy-config-0`). USB 3.2 Gen 1 effective throughput estimated at ~3.2 Gbps after protocol overhead.

## Phase 2: DepthAI SDK Installation on JetPack 6

**Status:** ✅ Complete  
**Session:** 2026-04-23

### DepthAI v2 vs v3 — Version Landscape

The DepthAI library exists in two major versions:

- **DepthAI v2 (depthai-python repo, `v2_stable` branch):** The mature, production-stable release. Python bindings live in the separate `luxonis/depthai-python` repository. Latest v2 release is on PyPI as `depthai`. Officially tested on Ubuntu 18.04–22.04, Raspbian 10, Windows 10/11, macOS 10.14–10.15.
- **DepthAI v3 (depthai-core repo, `main` branch):** The next-generation library with RVC4 support. Python bindings are integrated directly into `luxonis/depthai-core`. Adds support for RVC4 devices, new pipeline debugging, holistic record/replay, and auto-calibration. Requires C++17 and CMake ≥ 3.20.

**For this project (OAK-D Pro = RVC2 device):** Both v2 and v3 support RVC2. The latest PyPI release (`depthai 3.5.0`, released 2026-03-18) is from the v3 line. v2 is still available via the `v2_stable` branch. **Recommendation:** Use the v3 PyPI release (`depthai>=3.5.0`) as it is the actively maintained line and provides all RVC2 features needed for SLAM.

### Installation on JetPack 6 / L4T 36.x / aarch64

Luxonis provides **prebuilt wheels for Jetson on PyPI**. The official Jetson deployment guide confirms `pip install depthai` works on Jetson platforms.

**Recommended installation procedure:**

```bash
# 1. Install system dependencies
sudo wget -qO- https://docs.luxonis.com/install_dependencies.sh | bash
# This installs: python3, pip3, cmake, git, libudev-dev, libusb-1.0-0-dev, and udev rules

# 2. Create a virtual environment (project uses uv)
# On Jetson, within the project venv:
pip install depthai
# Or with extras from Luxonis snapshot repo:
pip install --extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/ depthai
```

**pip vs. apt vs. source build:**

| Method | Status on JetPack 6 aarch64 | Notes |
|--------|---------------------------|-------|
| `pip install depthai` | ✅ Recommended | Prebuilt aarch64 wheels available on PyPI |
| Luxonis snapshot repo | ✅ For pre-releases | `--extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/` |
| Source build (depthai-core) | ⚠️ Possible, complex | Requires CMake ≥ 3.20, C++17 compiler, libusb-1.0, libudev-dev. Build can OOM on Jetson — use `--parallel 2`. Need `git submodule update --init --recursive` first. |
| apt | ❌ Not available | No Debian package from Luxonis |

**Python version compatibility:**
- JetPack 6 (L4T 36.x, Ubuntu 22.04 base) ships Python 3.10 by default
- The project requires Python ≥ 3.11 (per `pyproject.toml`)
- DepthAI 3.5.0 supports Python 3.8+ — **compatible with 3.11+**
- If Python 3.11 is installed alongside 3.10 on the Jetson, ensure the venv targets 3.11

### OpenCV and NumPy Compatibility

**OpenCV on Jetson:** JetPack 6 ships with a CUDA-accelerated OpenCV 4.x built against the system Python. If using a Python 3.11 venv, this system OpenCV is not available — you need to `pip install opencv-python` or `opencv-python-headless` (headless is fine for this project since the Jetson runs headless).

**Known aarch64 issue — OpenBLAS illegal instruction:**
```bash
# If OpenCV/numpy crash with "illegal instruction" on aarch64:
echo "export OPENBLAS_CORETYPE=ARMV8" >> ~/.bashrc
source ~/.bashrc
```
This is documented by Luxonis as a required step on Jetson platforms. The `OPENBLAS_CORETYPE=ARMV8` environment variable should be set in the Jetson service environment or `.bashrc`.

**NumPy:** DepthAI v3 works with numpy 1.x and 2.x. JetPack 6 system numpy is 1.24.x. Installing via pip in a venv will pull the latest compatible numpy.

### udev Rules for Non-Root Access

Linux requires udev rules to allow non-root users to access the OAK-D USB device. Without these rules, DepthAI throws: `[warning] Insufficient permissions to communicate with X_LINK_BOOTED device having name "2.8". Make sure udev rules are set`

**Standard Luxonis udev rule:**

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

This sets the USB device permissions to `0666` (world read/write) for all devices with vendor ID `03e7` (Intel/Movidius/Luxonis). The Luxonis install dependencies script (`install_dependencies.sh`) automatically creates this rule.

**For the project's `jetson-harden.sh`:** The udev rule should be added to the hardening script as an idempotent step, ensuring it persists across re-flashes. Currently the script does not include this rule.

### XLink Protocol Basics

XLink is Luxonis's proprietary host-to-device communication protocol that runs over USB (or TCP/IP for PoE devices).

**Architecture:**
- **XLink** multiplexes multiple logical data streams over a single physical USB connection
- The host opens named **channels** (streams) to the Myriad X VPU — each DepthAI node output queue maps to an XLink channel
- Data flows are unidirectional per channel (host→device or device→host)
- The protocol handles chunking, flow control, and error recovery

**USB enumeration sequence:**
1. OAK-D Pro powers on → enumerates as USB2 device (`03e7:2485`, "Movidius MyriadX")
2. DepthAI uploads firmware + pipeline over USB2
3. Device reboots → re-enumerates as USB3 device (`03e7:f63b`, "Myriad VPU")
4. XLink channels open at SuperSpeed bandwidth

**Key implication:** The device **changes USB identity** during initialization. This is why:
- udev rules must match vendor ID `03e7` (which stays constant across both identities)
- dmesg will show two connection events (one USB2, one USB3)
- The existing `oakd.py` probe check (matching `03e7`) correctly catches both states

**Environment variables affecting XLink:**

| Variable | Effect |
|----------|--------|
| `XLINK_LEVEL` | XLink logging: `debug`, `info`, `warn`, `error`, `fatal`, `off` |
| `DEPTHAI_PROTOCOL` | Restrict to `usb`, `tcpip`, `tcpshd`, or `any` |
| `DEPTHAI_SEARCH_TIMEOUT` | Device search timeout (ms) |
| `DEPTHAI_CONNECT_TIMEOUT` | Connection establishment timeout (ms) |
| `DEPTHAI_WATCHDOG` | Device watchdog timeout; set `0` for debugging |
| `DEPTHAI_RECONNECT_TIMEOUT` | Reconnect timeout (ms); `0` disables reconnect |

### Known Issues on aarch64 / JetPack 6

1. **OpenBLAS illegal instruction** — solved with `OPENBLAS_CORETYPE=ARMV8` (see above)
2. **OOM during source build** — use `cmake --build build --parallel 2` (not default parallelism)
3. **System Python mismatch** — JetPack 6 default is Python 3.10; project needs 3.11+. Ensure `python3.11` is installed and the venv targets it
4. **USB device re-enumeration** — the OAK-D changes USB identity after firmware upload; some USB hubs handle this poorly. Direct connection to Jetson ports is preferred.
5. **USB cable quality** — cables >2m may cause `X_LINK_COMMUNICATION_NOT_OPEN` or `X_LINK_ERROR`. Use short, high-quality USB3 cables. For a moving robot, use a **screw-locking USB-C cable** to prevent disconnect.
6. **Power-related disconnects** — OAK-D Pro at full load can cause brownout on bus-powered USB. See Phase 1 findings on powered hub recommendation.

### Project Integration Notes

The project's `pyproject.toml` does **not** currently include `depthai` as a dependency. It should be added to `[project.optional-dependencies]` under a `jetson` or `vision` group:

```toml
[project.optional-dependencies]
jetson = [
    "sdnotify>=0.3",
    "depthai>=3.5.0",
]
```

This keeps depthai off the laptop-side install (where no OAK-D is connected) while making it available on the Jetson.

**Key Discoveries:**
- DepthAI 3.5.0 (v3 line) is the current PyPI release and supports RVC2 devices including OAK-D Pro
- Prebuilt aarch64 wheels are available — `pip install depthai` works on JetPack 6 without source build
- udev rule `SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"` is required for non-root access; not yet in `jetson-harden.sh`
- `OPENBLAS_CORETYPE=ARMV8` environment variable is mandatory on Jetson to avoid numpy/OpenCV illegal instruction crashes
- XLink protocol re-enumerates the USB device during init (USB2 → USB3); existing `oakd.py` vendor ID check handles both states correctly
- Project `pyproject.toml` does not yet list `depthai` as a dependency — should be added to `jetson` optional deps
- Screw-locking USB-C cable recommended for vibrating robot deployment to prevent XLink disconnects

| File | Relevance |
|------|-----------|
| `pyproject.toml` | Missing `depthai` dependency for Jetson |
| `src/mower_rover/probe/checks/oakd.py` | Existing vendor-ID check; works with XLink re-enumeration |
| `scripts/jetson-harden.sh` | Missing udev rule for OAK-D non-root access |

**External Sources:**
- [Luxonis Deploy to Jetson](https://docs.luxonis.com/hardware/platform/deploy/to-jetson/)
- [OAK USB Deployment Guide](https://docs.luxonis.com/hardware/platform/deploy/usb-deployment-guide/)
- [DepthAI Manual Install](https://docs.luxonis.com/software/depthai/manual-install/)
- [depthai-core v3 README](https://github.com/luxonis/depthai-core/blob/main/README.md)
- [depthai-python v2 README](https://github.com/luxonis/depthai-python/blob/main/README.md)
- [PyPI depthai 3.5.0](https://pypi.org/project/depthai/)

**Gaps:** Exact Python version matrix for prebuilt aarch64 wheels not confirmed — PyPI page doesn't list per-platform wheel availability per Python version. Field validation needed.  
**Assumptions:** JetPack 6 base is Ubuntu 22.04 with Python 3.10 default; Python 3.11 is installable via deadsnakes PPA or built from source.

## Phase 3: OAK-D Pro Stream Configuration for SLAM

**Status:** ✅ Complete  
**Session:** 2026-04-23

### SLAM Pipeline Input Requirements

Three SLAM solutions are viable on the Jetson AGX Orin with the OAK-D Pro:

**RTAB-Map:** Supports RGB-D and stereo modes. Natively supports OAK-D via `depthai-ros`. Requires rectified left/right mono, depth map (uint16 mm), IMU at 100–200 Hz. RGB optional (for map colorization). Works with 400P–800P at 15–30 FPS.

**ORB-SLAM3 (Stereo-Inertial):** Requires left+right mono grayscale, IMU at 200 Hz. Does NOT need a depth map — computes disparity internally. Works with 640×400 (400P) at 20 FPS (EuRoC benchmark standard). GPLv3 license.

**Isaac ROS Visual SLAM (cuVSLAM):** GPU-accelerated on Jetson. Supports multi-camera stereo, visual-inertial, and RGB-D modes. Requires raw (unencoded) left+right images + IMU at 200 Hz. Has ground vehicle constraint mode and map persistence (save/load across sessions). **Explicitly prohibits encoded images** and **IR dot patterns confuse feature tracking**.

| Requirement | RTAB-Map | ORB-SLAM3 | Isaac cuVSLAM |
|-------------|----------|-----------|---------------|
| Left mono (grayscale) | ✅ Required | ✅ Required | ✅ Required |
| Right mono (grayscale) | ✅ Required | ✅ Required | ✅ Required |
| Depth map (uint16) | ✅ Preferred | ❌ Not needed | Optional |
| RGB color | Optional | ❌ Not needed | ❌ Not needed |
| IMU | ✅ Recommended | ✅ Required | ✅ Required (VI mode) |
| Min resolution | ~400P | ~400P | Flexible |
| Recommended FPS | 15–30 | 20 | 15–30 |
| IMU rate | 100–200 Hz | 200 Hz | 200 Hz |
| Encoded images OK? | ❌ No | ❌ No | ❌ No (explicitly) |
| GPU acceleration | ❌ | ❌ | ✅ Jetson GPU |

**Critical finding:** All three SLAM solutions require **raw unencoded grayscale** images for feature extraction. On-device H.264/H.265/MJPEG encoding CANNOT be used for SLAM input streams. Encoding is only useful for the RGB stream (recording/visualization).

### OAK-D Pro Stream Configuration Parameters

**MonoCamera (2× OV9282):** Native 1280×800. Available: THE_400_P (640×400), THE_480_P, THE_720_P, THE_800_P. FPS 1–120. RAW8 grayscale only.

**ColorCamera (IMX378):** Up to 12MP. Common: THE_1080_P (1920×1080), THE_4_K. FPS 1–60 (1080P), 1–30 (4K). VideoEncoder requires NV12 input.

**StereoDepth node:** ROBOTICS preset (recommended for navigation) includes LR-check, 2× decimation, speckle filter, temporal filter. Outputs: `depth` (uint16 mm), `rectifiedLeft`/`rectifiedRight` (RAW8), `disparity`. FPS limits at 800P: ~50 FPS (LR, no sub), ~33 FPS (LR + subpixel 3-bit), ~16 FPS (LR + ext + sub).

**IMU (BNO086):** 9-axis. Accelerometer up to 500 Hz, gyroscope up to 400 Hz (raw). **For SLAM: 200 Hz accel + gyro** matches EuRoC/cuVSLAM standards.

**VideoEncoder:** H.264/H.265/MJPEG. HW encoder at 248 Mpix/sec (H.26x), 450 Mpix/sec (MJPEG). 4K@30fps, 1080P@60fps max. Encoded 1080P@15fps H.265 ≈ 2–4 Mbps.

### Bandwidth Math

**USB 3.2 Gen 1 effective:** ~3,200 Mbps | **Gen 2 effective:** ~7,200 Mbps

| Stream | Resolution | Bytes/px | FPS | Raw BW |
|--------|-----------|----------|-----|--------|
| Mono (each) | 640×400 | 1 | 30 | 61 Mbps |
| Mono (each) | 1280×800 | 1 | 30 | 246 Mbps |
| Depth | 640×400 | 2 | 30 | 123 Mbps |
| Depth | 1280×800 | 2 | 30 | 492 Mbps |
| RGB (NV12) | 1080P | 1.5 | 15 | 373 Mbps |
| RGB H.265 | 1080P | — | 15 | ~3 Mbps |
| IMU | 200 Hz | — | — | ~0.1 Mbps |

### Recommended Pipeline Profiles

**Profile A — "SLAM Minimal" (400P @ 15fps):** Rectified L+R + depth + IMU = **~123 Mbps** (96% headroom). For initial bringup or bandwidth-constrained scenarios.

**Profile B — "SLAM Standard" (400P @ 30fps + 1080P RGB encoded) — RECOMMENDED:**

| Stream | Config | BW |
|--------|--------|-----|
| Rectified left | 640×400 @ 30fps raw | 61 Mbps |
| Rectified right | 640×400 @ 30fps raw | 61 Mbps |
| Depth | 640×400 @ 30fps raw | 123 Mbps |
| RGB (H.265) | 1080P @ 15fps encoded | ~3 Mbps |
| IMU | 200 Hz | 0.1 Mbps |
| **Total** | | **~249 Mbps** (92% headroom) |

Room for obstacle detection NN or additional streams. Suitable for all three SLAM solutions.

**Profile C — "SLAM Full" (800P @ 30fps + 1080P RGB encoded):** Rectified L+R 800P + depth + RGB H.265 + IMU = **~986 Mbps** (69% headroom on Gen 1). For detailed mapping or when long-range depth accuracy matters. Stereo engine bottleneck at ~33 FPS with LR + subpixel.

### On-Device (Myriad X) vs Host (Jetson) Processing

**On the Myriad X VPU (OAK-D Pro):**
- Stereo depth computation — **dedicated HW stereo engine** (NOT SHAVEs)
- Stereo rectification — warp engines
- RGB encoding to H.265 — HW video encoder
- IMU data collection at 200 Hz
- (Optional) Feature tracking — HW Harris/Shi-Thomasi detector
- (Optional) Small obstacle NN (e.g., YOLOv8n) — uses SHAVEs

**On the Jetson AGX Orin:**
- SLAM algorithm (cuVSLAM on GPU, or RTAB-Map/ORB-SLAM3 on CPU)
- Path planning / obstacle avoidance
- H.265 decode + recording (if archiving)
- Large NN inference (Jetson GPU: 275 TOPS INT8)

**SHAVE budget:** With stereo depth on HW engine (0 SHAVEs) + ISP for 1080P color (~3 SHAVEs), 13 of 16 SHAVEs remain free for NN or encoding.

### Active Stereo (IR Dot Projector) for Outdoor Mowing

| Scenario | Dot Projector | Rationale |
|----------|---------------|-----------|
| Daytime, textured (grass) | ❌ OFF | Natural texture is sufficient; sunlight overwhelms IR |
| Daytime, smooth (pavement) | ⚠️ Optional | Sunlight typically washes out pattern |
| Dusk/dawn | ✅ ON | Low ambient IR lets pattern enhance smooth surfaces |
| Night / deep shade | ✅ ON + flood LED | Essential for both depth and mono images |

**IR dot projector MUST be OFF during cuVSLAM / ORB-SLAM3** — projected dots create spurious features that degrade visual tracking. For RTAB-Map RGB-D mode (depth pre-computed on-device), dot projector impact is less direct but still not recommended.

**Default for this project: Dot projector OFF, flood LED OFF.** Daylight outdoor mowing on grass provides rich natural texture.

**Key Discoveries:**
- All three SLAM solutions require **raw unencoded** stereo images — no on-device encoding for SLAM inputs
- Isaac cuVSLAM is the **best fit for Jetson** — GPU-accelerated, ground constraint mode, map persistence
- "SLAM Standard" profile (400P@30fps + 1080P RGB H.265 + IMU) uses only **249 Mbps** — 8% of USB 3.2 Gen 1
- StereoDepth ROBOTICS preset is purpose-built for navigation
- IR dot projector MUST be OFF during visual SLAM
- On-device stereo depth uses a **dedicated HW engine**, not SHAVEs — no competition with NN inference
- BNO086 IMU supports 200 Hz matching all SLAM solutions' expectations
- 400P is the sweet spot for SLAM FPS; 800P limits to ~33 FPS with LR+subpixel

| File | Relevance |
|------|-----------|
| `src/mower_rover/probe/checks/oakd.py` | Needs stream validation, not just vendor ID presence |
| `docs/vision/001-zero-turn-mower-rover.md` | Phase 11/12 companion computer SLAM integration |

**Gaps:** BNO086 IMU noise parameters (Allan variance) not published by Luxonis — needed for cuVSLAM tuning. SHAVE contention under simultaneous NN+stereo+encoding not benchmarked.  
**Assumptions:** Walking-pace mowing (~1.5 m/s) makes 15–30 FPS sufficient. SLAM integration via ROS 2 on Jetson. cuVSLAM as primary, RTAB-Map as fallback.

## Phase 4: Linux USB Power & Throughput Tuning

**Status:** ✅ Complete  
**Session:** 2026-04-23

### 4.1 USB Autosuspend — Why It Must Be Disabled

Linux USB autosuspend allows the kernel to put idle USB devices into a low-power suspended state after a configurable timeout. When the device needs to send data again, it must wake first, introducing latency spikes of 2–20 ms. For a continuously-streaming camera like the OAK-D Pro, autosuspend causes:

- **Frame drops** when the device is suspended between polling intervals
- **XLink reconnection storms** — the OAK-D re-enumerates USB during init (USB 2 → USB 3 transition); autosuspend during this window can cause enumeration failure
- **Stale depth maps** if stereo frames are delayed past the SLAM integrator's tolerance

Two complementary strategies exist to disable autosuspend:

#### Strategy A: Global Kernel Parameter (Recommended as Belt)

Add to the kernel command line (via `/boot/extlinux/extlinux.conf` on Jetson):

```
usbcore.autosuspend=-1
```

This globally sets the default autosuspend delay to -1 (disabled) for **all** USB devices at boot. The Jetson AGX Orin has no battery, so there is no power-savings benefit from USB autosuspend on an always-connected mower.

**Verification:**
```bash
cat /sys/module/usbcore/parameters/autosuspend
# Expected: -1
```

#### Strategy B: Per-Device udev Rule (Recommended as Suspenders)

Even with the global parameter, a per-device udev rule ensures the OAK-D specifically is never suspended, surviving kernel parameter resets or config drift:

```udev
# /etc/udev/rules.d/80-oakd-power.rules
# Disable autosuspend for OAK-D (Movidius/Luxonis vendor IDs)
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/autosuspend}="-1"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/control}="on"
```

The two attributes work together:
- `power/autosuspend=-1` — sets the suspend timeout to "never"
- `power/control=on` — forces the USB device into "always-on" power mode (overrides any runtime PM policy)

**Verification:**
```bash
# Find the OAK-D device path
OAKD_PATH=$(find /sys/bus/usb/devices -maxdepth 1 -name "[0-9]*" \
  -exec sh -c 'cat "$1/idVendor" 2>/dev/null | grep -q 03e7 && echo "$1"' _ {} \;)
cat "$OAKD_PATH/power/autosuspend"   # Expected: -1
cat "$OAKD_PATH/power/control"       # Expected: on
```

### 4.2 Comprehensive udev Rules for OAK-D Pro

The existing hardening script (`scripts/jetson-harden.sh`) currently has **no** udev rules for the OAK-D. Phase 2 documented the Luxonis standard permissions rule. The complete udev rule file should combine permissions, power management, and symlink creation:

```udev
# /etc/udev/rules.d/80-oakd-usb.rules
# 1. Grant non-root access to OAK-D (Movidius VPU vendor ID 03e7)
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"

# 2. Disable USB autosuspend for the device
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/autosuspend}="-1"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/control}="on"

# 3. Create a stable symlink for the OAK-D (optional, helps scripting)
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", SYMLINK+="oakd"
```

**Note on `ATTRS` vs `ATTR`:** Permissions rules that match parent device attributes use `ATTRS` (walks up the device tree). Power attribute writes that target the matched device directly use `ATTR` (no walk). Both are needed.

### 4.3 USB Buffer Sizing — `usbfs_memory_mb`

The Linux `usbfs` memory limit controls the maximum amount of DMA buffer memory that userspace applications can allocate for USB transfers. The default is **16 MB**, which is too low for high-bandwidth USB cameras.

**Impact on OAK-D Pro:** DepthAI's XLink protocol uses bulk USB transfers with large transfer buffers. When `usbfs_memory_mb` is too low, the kernel returns `-ENOMEM` errors on `USBDEVFS_SUBMITURB` ioctls, which DepthAI surfaces as:
- `RuntimeError: Failed to find device ...`
- XLink timeout errors
- Bandwidth throttling (the pipeline silently reduces FPS to fit within buffer constraints)

**Recommended setting:** 1000 MB (1 GB). This is the Luxonis-recommended value for robotics deployments and is well within the AGX Orin's 64 GB RAM.

**Three ways to set it:**

1. **Kernel parameter** (persistent across boots):
   ```
   # In /boot/extlinux/extlinux.conf, APPEND line:
   usbcore.usbfs_memory_mb=1000
   ```

2. **sysfs write** (immediate, lost on reboot):
   ```bash
   echo 1000 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb
   ```

3. **systemd tmpfile** (persistent, applies early in boot):
   ```
   # /etc/tmpfiles.d/usb-memory.conf
   w /sys/module/usbcore/parameters/usbfs_memory_mb - - - - 1000
   ```

**Verification:**
```bash
cat /sys/module/usbcore/parameters/usbfs_memory_mb
# Expected: 1000
```

**Hardening script integration:** The kernel parameter approach is preferred for the mower project because `extlinux.conf` is already managed and it takes effect before any userspace service starts.

### 4.4 Jetson-Specific USB Quirks — `xhci-tegra` Driver

The Jetson AGX Orin uses NVIDIA's custom `xhci-tegra` driver (not the upstream `xhci-hcd`) for its xHCI USB controller at `usb@3610000`. Key platform-specific behaviors:

#### 4.4.1 Device Re-Enumeration During OAK-D Init

The OAK-D Pro re-enumerates USB during initialization: it first connects as a USB 2.0 device (Movidius boot mode), then firmware is uploaded over USB, and the device reconnects at USB 3.x speed. The `xhci-tegra` driver handles this re-enumeration, but:

- **The transition generates `xhci-tegra` dmesg warnings** about port status changes — these are informational, not errors
- **If autosuspend is enabled**, the brief idle between USB 2 disconnect and USB 3 reconnect can trigger a suspend, causing enumeration failure
- **The XLink boot takes 3–5 seconds** — any monitoring script must wait for the final USB 3 enumeration, not the initial USB 2 appearance

#### 4.4.2 XUSB Firmware Hold

The hardening script correctly holds the `nvidia-l4t-xusb-firmware` package:

```bash
apt-mark hold nvidia-l4t-xusb-firmware
```

This is critical — the xHCI controller firmware is loaded from `/lib/firmware/nvidia/tegra234/xusb.bin` at boot, and an incompatible firmware update would break USB 3.x entirely. The hold ensures the firmware version stays matched to the L4T kernel version.

#### 4.4.3 Single xHCI Controller, Shared Bandwidth

All USB 3.x ports on the AGX Orin share a **single xHCI controller**. While total bandwidth is high (3 UPHY SuperSpeed lanes), connecting additional USB 3.x devices (e.g., a USB SSD for logging) on the same controller means they share the controller's scheduling slots. For the mower:

- OAK-D Pro at "SLAM Standard" profile uses ~249 Mbps (per Phase 3)
- A USB 3.0 SSD could consume 200+ Mbps during log writes
- **Recommendation:** If an external SSD is needed, use the NVMe slot instead; keep USB ports dedicated to the OAK-D

#### 4.4.4 `tegra-xudc` (Device Mode Controller)

The `tegra-xudc` driver manages the **USB device controller** (Type-C OTG port J40). This is used only for flashing mode and host-device communication. It is unrelated to the OAK-D host-mode connection. No tuning is needed for `tegra-xudc` in the SLAM use case.

### 4.5 `nvpmodel` and `jetson_clocks` Impact on USB

#### 4.5.1 nvpmodel Power Modes and USB

The hardening script sets **nvpmodel mode 3 (50W)** for the AGX Orin 64GB. Key characteristics from NVIDIA's power mode table:

| Parameter | Mode 3 (50W) | Mode 2 (30W) | Mode 1 (15W) |
|-----------|-------------|-------------|-------------|
| Online CPUs | 12 | 8 | 4 |
| CPU max freq | 1497.6 MHz | 1728 MHz | 1113.6 MHz |
| GPU TPC | 8 | 4 | 3 |
| GPU max freq | 816 MHz | 612 MHz | 408 MHz |
| Memory max freq | 3200 MHz | 3200 MHz | 2133 MHz |

**USB impact:** nvpmodel does NOT directly throttle USB controller clocks. The xHCI controller runs on fixed SoC clocks that are independent of the CPU/GPU frequency scaling. However, lower power modes (mode 1, 15W) reduce:
- **EMC frequency** to 2133 MHz (from 3200 MHz) — this reduces memory bandwidth available for USB DMA transfers
- **CPU frequency** — less headroom for the DepthAI host-side processing (XLink unpacking, IMU parsing, frame callbacks)
- **axi_cbb clock** stays at 408 MHz in all modes for AGX Orin 64GB — this is the AXI bus that serves the xHCI controller

**Conclusion:** Mode 3 (50W) is correct for the mower. The USB controller itself is not throttled by nvpmodel, but the downstream effects (lower EMC, fewer CPU cores) in lower modes could cause DepthAI frame processing bottlenecks.

#### 4.5.2 `jetson_clocks` and USB

`jetson_clocks` maximizes CPU, GPU, and EMC clocks to the nvpmodel-defined maximums. It sets all CPU governors to `performance` (maximum frequency) and locks EMC at maximum rate.

**USB-relevant effects:**
- EMC is locked at 3200 MHz → maximum DMA throughput for USB bulk transfers
- CPU cores run at maximum → consistent XLink/DepthAI host-side processing
- No direct USB clock control (USB clocks are SoC-fixed)

**Recommendation:** Run `jetson_clocks` before starting the SLAM pipeline. The hardening script does NOT currently call `jetson_clocks` — it only sets nvpmodel. Adding a `jetson_clocks` call (or a systemd service) would eliminate DVFS-related jitter during SLAM operation.

**Important caveat from NVIDIA docs:** "After running `jetson_clocks`, you cannot change the nvpmodel power mode. If the power mode has to be changed after running `jetson_clocks`, a system reboot is required." This is acceptable for the mower — power mode is set once during hardening and `jetson_clocks` is run at SLAM start.

**Proposed systemd integration:**
```ini
# /etc/systemd/system/jetson-clocks.service
[Unit]
Description=Lock Jetson clocks to nvpmodel maximums
After=nvpmodel.service

[Service]
Type=oneshot
ExecStart=/usr/bin/jetson_clocks
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

### 4.6 Thermal Throttling and USB Throughput

#### 4.6.1 Thermal Throttling Thresholds (AGX Orin)

From NVIDIA's thermal specifications, **all thermal zones** share these thresholds:

| Action | Temperature | TMARGIN from 105°C max |
|--------|-------------|------------------------|
| Software throttling begins | 99.0°C | 6°C margin |
| Hardware throttling (OC alarm) | 103.0°C | 2°C margin |
| Software shutdown | 104.5°C | 0.5°C margin |
| Hardware shutdown (thermtrip) | 105.0°C | 0°C |

Thermal zones monitored: `cpu-thermal`, `gpu-thermal`, `cv0-thermal`, `cv1-thermal`, `cv2-thermal`, `soc0-thermal`, `soc1-thermal`, `soc2-thermal`, `tj-thermal` (max of all).

#### 4.6.2 How Thermal Throttling Affects USB

Thermal throttling **does NOT directly reduce USB clock speeds**. The xHCI controller's clocks are not subject to DVFS thermal capping. However, thermal throttling indirectly impacts USB throughput:

1. **CPU frequency capping** — When `cpu-thermal` triggers software throttling at 99°C, the `cpufreq` governor's maximum is reduced. This slows DepthAI's host-side XLink processing, causing frame queue backup.

2. **EMC frequency capping** — If `soc0/1/2-thermal` trigger throttling, the memory controller frequency can be reduced via `devfreq_cooling`, reducing DMA bandwidth.

3. **GPU throttling** — If `gpu-thermal` triggers, the GPU's CUDA cores (used by cuVSLAM) are frequency-capped, which stalls the SLAM pipeline, causing upstream frame queues to fill and eventually drop frames.

4. **OC (Over-Current) hardware throttling** — At TDP mode 3 (50W), the AGX Orin 64GB's OC3 limit is 65W instantaneous. If total module power spikes above 65W (plausible with SLAM + CUDA + USB), hardware throttling reduces CPU and GPU to 50% — a severe SLAM performance hit.

#### 4.6.3 Thermal Management for the Mower

The mower operates **outdoors in summer heat** (ambient 35–40°C possible). The AGX Orin devkit's fan must be running in `cool` profile (default for AGX Orin series). Key recommendations:

- **Fan profile:** Keep default `cool` profile. Do NOT use `quiet` — it allows temperatures to rise higher before spinning up.
- **Fan speed verification:**
  ```bash
  sudo nvfancontrol -q
  # Expected: FAN1:FAN_PROFILE:cool
  ```
- **Thermal monitoring during operation:**
  ```bash
  # Quick thermal check (all zones)
  paste <(cat /sys/class/thermal/thermal_zone*/type) \
        <(cat /sys/class/thermal/thermal_zone*/temp) | \
    awk '{printf "%-15s %.1f°C\n", $1, $2/1000}'
  ```
- **Pre-flight thermal gate:** Do not start SLAM if `tj-thermal` (max of all zones) exceeds 85°C. This provides 14°C of headroom before software throttling begins at 99°C.

#### 4.6.4 OAK-D Pro Self-Heating

The OAK-D Pro draws up to 7W with IR projector enabled and up to 15W at peak (per Luxonis docs). The Myriad X VPU generates significant heat. In the SLAM pipeline with IR projector **off** (as recommended in Phase 3), the camera draws ~3–5W, but can still reach 60–70°C internally.

- The OAK-D reports its own temperature via `device.getChipTemperature()` in DepthAI
- **Critical:** If the OAK-D overheats (>105°C internal), it throttles its own processing or disconnects USB entirely
- **Recommendation:** Mount the OAK-D with adequate airflow, not in an enclosed housing. Consider a small heatsink on the VPU enclosure.

### 4.7 Practical Tuning Recommendations — Additions to `jetson-harden.sh`

The existing hardening script needs the following additions for USB/SLAM readiness. These should be implemented as new sections in the script's idempotent pattern:

| Item | Mechanism | When Applied | Restart Needed |
|------|-----------|--------------|----------------|
| Disable USB autosuspend globally | `usbcore.autosuspend=-1` in `extlinux.conf` APPEND line | Boot | Yes (one-time) |
| Set `usbfs_memory_mb=1000` | `usbcore.usbfs_memory_mb=1000` in `extlinux.conf` APPEND line | Boot | Yes (one-time) |
| OAK-D udev rules (permissions + power) | `/etc/udev/rules.d/80-oakd-usb.rules` | udev reload | No (udevadm trigger) |
| `jetson_clocks` at boot | systemd service after nvpmodel | Boot (service enable) | No |
| Fan profile verification | Assert `cool` profile is active | Script check | No |

**Kernel command line additions** for `/boot/extlinux/extlinux.conf`:

```
APPEND ${cbootargs} ... usbcore.autosuspend=-1 usbcore.usbfs_memory_mb=1000
```

**Verification commands** (for the script's status reporting):

```bash
# USB autosuspend
[ "$(cat /sys/module/usbcore/parameters/autosuspend)" = "-1" ] && echo "OK" || echo "FAIL"

# usbfs memory
[ "$(cat /sys/module/usbcore/parameters/usbfs_memory_mb)" -ge 1000 ] && echo "OK" || echo "FAIL"

# OAK-D udev rule exists
[ -f /etc/udev/rules.d/80-oakd-usb.rules ] && echo "OK" || echo "FAIL"

# Fan profile
sudo nvfancontrol -q 2>/dev/null | grep -q "cool" && echo "OK" || echo "WARN: not cool profile"
```

**Key Discoveries:**
- USB autosuspend must be disabled both globally (kernel param) and per-device (udev rule) for belt-and-suspenders reliability
- `usbfs_memory_mb` default of 16 MB is far too low for OAK-D SLAM streaming; 1000 MB is the standard robotics recommendation
- The `xhci-tegra` controller runs on fixed SoC clocks — nvpmodel does NOT throttle USB directly, but lower power modes reduce EMC bandwidth and CPU headroom needed for DepthAI host processing
- `jetson_clocks` eliminates DVFS jitter by locking all clocks at nvpmodel maximums; it should run before SLAM start
- Thermal throttling above 99°C reduces CPU/GPU/EMC frequencies which indirectly degrades SLAM throughput; the mower needs a pre-flight thermal gate
- The OAK-D Pro itself generates significant heat; it must be mounted with airflow, not enclosed
- The existing `jetson-harden.sh` script is missing: udev rules for OAK-D, USB autosuspend disable, `usbfs_memory_mb` tuning, and `jetson_clocks` service — all four should be added
- VIN_SYS_5V0 power rail feeds USB I/O; it can be monitored via INA3221 at I2C `0x40` channel 3 for power delivery health checks

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | Current hardening script; needs USB autosuspend, usbfs_memory_mb, udev rules, jetson_clocks additions |
| `/boot/extlinux/extlinux.conf` | Kernel command line where USB params must be added (on Jetson) |
| `/etc/udev/rules.d/80-oakd-usb.rules` | New file needed for OAK-D permissions + power management |
| `/etc/nvfancontrol.conf` | Fan profile config; should remain at `cool` default |
| `/etc/nvpmodel.conf` | Power mode config; mode 3 (50W) is correct for SLAM workload |

**External Sources:**
- [NVIDIA L4T r36.4 Platform Power & Performance](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html) — nvpmodel modes, thermal specs, jetson_clocks, fan profiles, power monitoring
- [Luxonis OAK USB Deployment Guide](https://docs.luxonis.com/hardware/platform/deploy/usb-deployment-guide/) — udev rules, USB cable requirements, power delivery, usbfs_memory_mb recommendation

**Gaps:** Exact `xhci-tegra` driver source on L4T 36.x not inspected — the USB controller clock tree specifics are inferred from NVIDIA's documentation that SoC I/O clocks are fixed, not from direct source code inspection. Field measurement of actual USB DMA throughput under thermal throttling conditions has not been performed.  
**Assumptions:** The AGX Orin 64GB variant is used (per hardware stack spec). nvpmodel mode 3 is set by the hardening script. The mower has no battery — USB autosuspend power savings are irrelevant.

## Phase 5: Validation Checklist & Scripted Checks

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Operator Pre-Flight Checklist

| # | Check | Command / Action | PASS Criterion | Severity |
|---|-------|-----------------|----------------|----------|
| 1 | Physical connection | Visual: OAK-D Pro LED solid white, cable fully seated | LED on | CRITICAL |
| 2 | USB device visible | `lsusb \| grep 03e7` | Shows `03e7:` | CRITICAL |
| 3 | USB SuperSpeed | `/sys/bus/usb/devices/*/speed` for vendor `03e7` | `5000` or `10000` (not `480`) | CRITICAL |
| 4 | dmesg SuperSpeed | `dmesg \| grep -i "xhci-tegra.*new SuperSpeed"` | At least one SuperSpeed line | WARNING |
| 5 | USB autosuspend | `cat /sys/module/usbcore/parameters/autosuspend` | `-1` | WARNING |
| 6 | usbfs buffer | `cat /sys/module/usbcore/parameters/usbfs_memory_mb` | `≥ 1000` | WARNING |
| 7 | Thermal gate | `tj-thermal` zone temperature | `< 85000` (85°C) | WARNING |
| 8 | Fan profile | `nvfancontrol -q` | Profile = `cool` | WARNING |
| 9 | `jetson_clocks` | `sudo jetson_clocks --show` | Clocks maximized | WARNING |
| 10 | DepthAI opens | `dai.Device(dai.Pipeline())` succeeds | No RuntimeError | CRITICAL |
| 11 | DepthAI USB speed | `device.getUsbSpeed()` | `SUPER` or `SUPER_PLUS` | CRITICAL |
| 12 | Chip temperature | `device.getChipTemperature().average` | `< 85.0°C` | WARNING |
| 13 | Calibration | `device.readCalibration2()` | No exception; ≥2 cameras | WARNING |
| 14 | Stream FPS | FPS counter script (30 s) | All ≥ 90% of target | CRITICAL |
| 15 | Frame drops | Sequence number gaps | `drops = 0` | WARNING |
| 16 | Frame latency | `dai.Clock.now() - frame.getTimestamp()` | `avg < 50 ms` | WARNING |

### `lsusb -t` Verification

Expected correct output at SuperSpeed:
```
/:  Bus 02.Port 1: Dev 1, Class=root_hub, Driver=xhci-tegra/4p, 10000M
    |__ Port 1: Dev 2, If 0, Class=Vendor Specific Class, Driver=, 5000M
```

| Speed Suffix | Meaning | SLAM OK? |
|-------------|---------|----------|
| `5000M` | USB 3.2 Gen 1 | ✅ Yes |
| `10000M` | USB 3.2 Gen 2 | ✅ Yes |
| `480M` | USB 2.0 (HighSpeed) | ❌ FAIL — cable/port issue |

If `480M`: check cable (must be USB 3.x with SuperSpeed wires), check port (use J33 Gen 2 or J24), check cable length (<2 m).

Alternative sysfs check:
```bash
OAK_DEV=$(grep -rl "03e7" /sys/bus/usb/devices/*/idVendor 2>/dev/null | head -1 | xargs dirname)
cat "$OAK_DEV/speed"  # Expected: 5000 or 10000
```

### `dmesg` SuperSpeed Confirmation

```bash
# Primary check
dmesg | grep -i "xhci-tegra.*new SuperSpeed"
# Expected: xhci-tegra 3610000.usb: new SuperSpeed USB device number N using xhci-tegra

# XLink boot shows TWO enumerations: USB 2.0 (firmware upload) then USB 3.x (running)
# The SECOND must be SuperSpeed. If only one event at 480M, XLink boot failed.
```

### DepthAI API Checks

```python
import depthai as dai

pipeline = dai.Pipeline()
with dai.Device(pipeline) as device:
    # USB speed
    usb_speed = device.getUsbSpeed()
    assert usb_speed in (dai.UsbSpeed.SUPER, dai.UsbSpeed.SUPER_PLUS)

    # Chip temperature
    temp = device.getChipTemperature()
    assert temp.average < 85.0

    # Calibration
    calib = device.readCalibration2()
    eeprom = calib.getEepromData()
    assert len(eeprom.cameraData) >= 2
```

### FPS Counter / Frame-Drop Detection Script Design

The key validation tool builds the "SLAM Standard" pipeline and measures actual throughput for 30 seconds:

**Pipeline:** Rectified L+R 400P@30fps (raw) + depth 400P@30fps (raw) + RGB 1080P@15fps (H.265) + IMU 200Hz

**Drop detection:** `ImgFrame.getSequenceNum()` provides monotonic per-stream sequence numbers. Gaps between consecutive frames = dropped frames.

**Latency:** `dai.Clock.now() - frame.getTimestamp()` — DepthAI auto-syncs device/host clocks (<200 µs accuracy on USB). Includes: MIPI readout + ISP + StereoDepth + XLink transfer + host deserialization.

**Expected latencies (USB 3.x, SLAM Standard):**

| Stream | Expected | Concern Threshold |
|--------|----------|-------------------|
| Rectified L/R | 8–15 ms | > 30 ms |
| Depth | 12–20 ms | > 40 ms |
| RGB H.265 | 30–50 ms | > 100 ms |

**Non-blocking queues** (`maxSize=4, blocking=False`) match real SLAM consumer behavior. **10% FPS tolerance** accommodates sensor timing jitter.

**CLI invocation:** `mower-jetson slam-preflight --duration 30 --json`

### Integration with Existing Probe System

**Current `oakd.py`** only checks vendor ID. Enhancement: also read `/sys/bus/usb/devices/*/speed` for the matched device.

**Enhanced check pseudocode:**
```python
@register("oakd", severity=Severity.CRITICAL, depends_on=("jetpack_version",))
def check_oakd(sysroot: Path) -> tuple[bool, str]:
    for vendor_file in glob.glob(str(sysroot / "sys/bus/usb/devices/*/idVendor")):
        vid = Path(vendor_file).read_text(encoding="utf-8").strip().lower()
        if vid == "03e7":
            speed_file = Path(vendor_file).parent / "speed"
            if speed_file.is_file():
                speed = speed_file.read_text(encoding="utf-8").strip()
                if speed in ("5000", "10000"):
                    return True, f"OAK device found at USB {speed} Mbps"
                return False, f"OAK device at USB {speed} Mbps (need ≥5000)"
            return True, "OAK device found (speed file missing)"
    return False, "No OAK device detected (vendor 03e7)"
```

**Proposed additional probe checks:**

| Check Name | Severity | Depends On | Verifies |
|-----------|----------|-----------|----------|
| `oakd` (enhanced) | CRITICAL | `jetpack_version` | Vendor ID + USB speed ≥ 5000 |
| `oakd_usb_autosuspend` | WARNING | — | autosuspend = `-1` |
| `oakd_usbfs_memory` | WARNING | — | usbfs_memory_mb ≥ 1000 |
| `oakd_thermal_gate` | WARNING | `thermal` | tj-thermal < 85°C |

### Pre-Flight JSON Report Structure

```json
{
  "report_type": "slam_preflight",
  "timestamp": "2026-04-23T14:30:00Z",
  "correlation_id": "abc-123-def",
  "device": {
    "mxid": "14442C108144F1D000",
    "usb_speed": "SUPER",
    "usb_speed_mbps": 5000,
    "chip_temp_avg_c": 42.5,
    "board_name": "OAK-D-PRO",
    "calibration_valid": true
  },
  "kernel_tuning": {
    "usb_autosuspend": -1,
    "usbfs_memory_mb": 1000,
    "jetson_clocks_active": true,
    "fan_profile": "cool"
  },
  "thermal": {
    "tj_thermal_c": 55.2,
    "gate_threshold_c": 85.0,
    "passed": true
  },
  "stream_validation": {
    "duration_s": 30,
    "streams": {
      "rectified_left": {"target_fps": 30, "actual_avg_fps": 29.8, "drop_count": 0, "avg_latency_ms": 11.2, "passed": true},
      "rectified_right": {"target_fps": 30, "actual_avg_fps": 29.7, "drop_count": 0, "avg_latency_ms": 11.5, "passed": true},
      "depth": {"target_fps": 30, "actual_avg_fps": 29.9, "drop_count": 0, "avg_latency_ms": 15.3, "passed": true},
      "rgb_h265": {"target_fps": 15, "actual_avg_fps": 14.9, "drop_count": 0, "avg_latency_ms": 38.1, "passed": true},
      "imu": {"target_hz": 200, "actual_avg_hz": 198.5, "passed": true}
    }
  },
  "slam_ready": true
}
```

**Key Discoveries:**
- `ImgFrame.getSequenceNum()` provides monotonic sequence numbers — gaps directly indicate dropped frames
- DepthAI auto-syncs device/host clocks (<200 µs for USB) enabling straightforward latency measurement
- The existing `oakd.py` check only reads `idVendor` but `speed` is in the same sysfs directory — minimal enhancement needed
- XLink boot re-enumeration is normal (USB2 → USB3); `dmesg` shows two events; the second must be "SuperSpeed"
- Non-blocking queues (`maxSize=4`) match SLAM consumer behavior; drops show as sequence gaps
- `DEPTHAI_LEVEL=trace` provides per-node timing for latency diagnosis
- IMU drop detection needs timestamp-based analysis (no `getSequenceNum()` on IMU packets)

| File | Relevance |
|------|-----------|
| `src/mower_rover/probe/checks/oakd.py` | Needs USB speed check enhancement |
| `src/mower_rover/probe/registry.py` | `@register` API for new checks |
| `src/mower_rover/probe/checks/thermal.py` | Pattern for sysfs-based thermal checks |
| `src/mower_rover/health/thermal.py` | Thermal zone reader |
| `src/mower_rover/cli/jetson.py` | CLI integration point for `slam-preflight` |
| `tests/test_probe.py` | Test pattern with fake sysfs trees |

**Gaps:** Exact `dmesg` output on L4T 36.x needs field validation. `readCalibration2()` API name may differ in depthai v3. IMU drop detection via timestamp gaps not fully designed.  
**Assumptions:** DepthAI v2-compatible API (method names from v2/3.5.0). 10% FPS tolerance acceptable for VIO/SLAM. SLAM validation runs standalone on Jetson (requires depthai bindings).

## Overview

The OAK-D Pro connects to the Jetson AGX Orin via a single xHCI controller (`xhci-tegra` at `3610000.usb`) with 3 UPHY SuperSpeed lanes. The recommended port is J33 Gen 2 Type-A (port 7, beside Ethernet) for guaranteed 10 Gbps capability, though any USB 3.x port provides sufficient bandwidth. The SLAM Standard pipeline — rectified stereo 400P@30fps + depth 400P@30fps + RGB 1080P@15fps H.265 + IMU 200Hz — consumes ~249 Mbps, only 8% of USB 3.2 Gen 1 capacity. The primary failure mode is USB 2.0 fallback (bad cable, wrong port, or XLink re-enumeration failure), which is detectable via sysfs `speed` file and DepthAI `getUsbSpeed()`.

DepthAI v3.5.0 provides prebuilt aarch64 wheels on PyPI. Installation requires only `python3 -m pip install depthai` plus a udev rule for permissions. The XLink protocol multiplexes all streams over a single USB connection, re-enumerating from USB 2.0 to USB 3.x during device initialization (normal behavior visible in `dmesg`).

For SLAM, Isaac cuVSLAM is the primary recommendation (GPU-accelerated, ground constraint mode, map persistence) with RTAB-Map as a CPU fallback. Both require raw unencoded grayscale stereo images — H.264/H.265 encoding on stereo streams is incompatible with SLAM.

Three kernel tunables are critical: `usbcore.autosuspend=-1` (prevent USB suspend), `usbfs_memory_mb=1000` (default 16 MB causes frame drops), and `jetson_clocks` (eliminate DVFS jitter). Thermal pre-flight gate at 85°C tj-thermal prevents throttling during operation.

The existing `oakd.py` probe check needs minimal enhancement (add `speed` file read alongside existing `idVendor` check). A standalone `slam-preflight` CLI command validates end-to-end stream throughput, frame drops (via sequence number gaps), and latency (via DepthAI clock sync).

## Key Findings

1. **Single USB controller, 3 SuperSpeed lanes** — All USB ports share one xHCI at `3610000.usb`. No dedicated bandwidth per port; other USB devices (keyboard, debug) share the same controller.
2. **249 Mbps pipeline on 5 Gbps link = 8% utilization** — USB bandwidth is not a bottleneck; the risk is USB 2.0 fallback, not saturation.
3. **DepthAI v3.5.0 has prebuilt aarch64 wheels** — No compilation needed on Jetson. `pip install depthai` works directly.
4. **XLink re-enumeration is normal** — OAK-D boots USB 2.0, uploads firmware, disconnects, reconnects at USB 3.x. Two `dmesg` events expected; second must be SuperSpeed.
5. **cuVSLAM requires raw unencoded stereo** — Cannot use H.264/H.265 on the mono camera streams fed to SLAM. Only RGB (for recording/display) should be encoded.
6. **`usbfs_memory_mb=16` (default) will cause frame drops** — Must set to ≥1000 via kernel cmdline or sysfs.
7. **`ImgFrame.getSequenceNum()` enables reliable drop detection** — Monotonic per-stream; gaps directly indicate dropped frames.
8. **DepthAI clock sync < 200 µs on USB** — `dai.Clock.now() - frame.getTimestamp()` gives capture-to-host latency without manual correlation.
9. **Existing `oakd.py` only checks vendor ID** — The `speed` sysfs file is in the same directory; enhancement is trivial.
10. **Thermal gate at 85°C, not 95°C** — Software throttle starts at 99°C; pre-flight gate at 85°C provides margin for sustained SLAM operation.

## Actionable Conclusions

1. **Enhance `oakd.py`** to read `speed` file (check ≥5000) alongside existing vendor ID check.
2. **Add probe checks**: `oakd_usb_autosuspend`, `oakd_usbfs_memory`, `oakd_thermal_gate` using existing `@register` pattern.
3. **Add to `jetson-harden.sh`**: udev rule `80-oakd-usb.rules`, `usbcore.autosuspend=-1` + `usbfs_memory_mb=1000` in kernel cmdline, `jetson_clocks` service.
4. **Add `depthai>=3.5.0`** to `pyproject.toml` `[project.optional-dependencies] jetson` group.
5. **Implement `mower-jetson slam-preflight`** CLI command: builds SLAM Standard pipeline, runs 30 s, reports FPS/drops/latency as JSON.
6. **Use J33 Gen 2 Type-A port** (port 7) for the OAK-D Pro. Document in operator setup guide.
7. **SLAM integration**: Start with cuVSLAM via Isaac ROS; fall back to RTAB-Map if GPU budget is exceeded.

## Open Questions

- Exact `dmesg` wording on L4T 36.x for XLink re-enumeration (needs field validation)
- `readCalibration2()` vs `readCalibration()` method name in depthai v3 API (verify against installed version)
- IMU packet drop detection (no `getSequenceNum()` on IMU packets — needs timestamp-gap approach)
- Whether J33 Gen 2 Type-A actually negotiates at 10 Gbps with OAK-D Pro (device is 5 Gbps capable, so it may cap at 5000M regardless of port)
- Power delivery on Type-A vs Type-C for the OAK-D Pro's 7W peak with IR (Type-A spec is 4.5W at 5V/0.9A)

## References

### Phase 1 Sources
- [Jetson AGX Orin Dev Kit Layout](https://developer.nvidia.com/embedded/learn/jetson-agx-orin-devkit-user-guide/developer_kit_layout.html) — Port specifications and connector locations
- [L4T 36.4 Platform Adaptation Guide](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonAgxOrinSeries.html) — USB porting, UPHY lane config, device tree structure
- [OAK-D Pro Product Page](https://docs.luxonis.com/hardware/products/OAK-D%20Pro) — Power consumption, IMU, sensors, IR features
- [DepthAI FPS & Latency Optimization](https://docs.luxonis.com/software/depthai/optimizing/) — Bandwidth tables, USB throughput data
- [DepthAI Device API](https://docs.luxonis.com/software/depthai-components/device/) — `getUsbSpeed()`, environment variables, queue settings

### Phase 2 Sources
- [Luxonis Deploy to Jetson](https://docs.luxonis.com/hardware/platform/deploy/to-jetson/) — Official Jetson installation procedure
- [OAK USB Deployment Guide](https://docs.luxonis.com/hardware/platform/deploy/usb-deployment-guide/) — udev rules, USB cable requirements, power delivery
- [DepthAI Manual Install](https://docs.luxonis.com/software/depthai/manual-install/) — Platform-specific dependencies and install scripts
- [depthai-core v3 README](https://github.com/luxonis/depthai-core/blob/main/README.md) — v3 library docs, env variables, XLink config
- [depthai-python v2 README](https://github.com/luxonis/depthai-python/blob/main/README.md) — v2 legacy library, wheel builds
- [PyPI depthai 3.5.0](https://pypi.org/project/depthai/) — Latest release (2026-03-18)

### Phase 3 Sources
- [DepthAI Optimizing FPS & Latency](https://docs.luxonis.com/software/depthai/optimizing/) — Bandwidth calculations, stereo depth FPS tables
- [Luxonis VIO and SLAM](https://docs.luxonis.com/software/ros/vio-slam/) — OAK-D SLAM integration overview
- [RVC2 Architecture](https://docs.luxonis.com/hardware/platform/rvc/rvc2/) — SHAVE/CMX/NCE details, HW stereo engine
- [Isaac ROS Visual SLAM](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/) — cuVSLAM tracking modes, IMU config, image requirements
- [RTAB-Map + OAK-D Launch](https://github.com/introlab/rtabmap_ros/blob/ros2/rtabmap_examples/launch/depthai.launch.py) — ROS 2 launch file
- [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) — Stereo-inertial config, EuRoC reference

### Phase 4 Sources
- [NVIDIA L4T r36.4 Platform Power & Performance](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html) — nvpmodel power modes, thermal specifications, jetson_clocks, fan profiles, power monitoring via INA3221
- [Luxonis OAK USB Deployment Guide](https://docs.luxonis.com/hardware/platform/deploy/usb-deployment-guide/) — udev rules, power delivery, usbfs_memory_mb, cable requirements
- [Linux USB autosuspend documentation](https://www.kernel.org/doc/html/latest/driver-api/usb/power-management.html) — Kernel USB power management, autosuspend controls

### Phase 5 Sources
- [DepthAI Device API](https://docs.luxonis.com/software/depthai-components/device/) — getUsbSpeed, UsbSpeed enum, clock syncing, queue management
- [DepthAI Optimizing Guide](https://docs.luxonis.com/software/depthai/optimizing/) — FPS/latency benchmarks, bandwidth calculations, latency measurement
- [DepthAI IMU Node](https://docs.luxonis.com/software/depthai-components/nodes/imu/) — IMU sensor frequencies (BNO086/BMI270), batch configuration

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-23 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/006-oakd-pro-usb-slam-readiness.md |
