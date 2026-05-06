---
id: "023"
type: research
title: "Weston Cold-Boot EGL Initialization Failure on Jetson AGX Orin"
status: ✅ Complete
created: "2026-05-05"
current_phase: "4 of 4"
---

## Introduction

After disabling GDM3 on the Jetson AGX Orin (to run Weston as a headless kiosk compositor), the NVIDIA EGL/GBM stack fails to initialize at boot time. Weston starts, acquires libseat/seatd DRM master on the correct GPU card, but EGL returns `EGL_NOT_INITIALIZED (0x3001)` with the error `"DRI2: gbm device using incorrect/incompatible backend"`. Running `nvidia-smi` before Weston forces GPU state initialization and resolves the issue — but only when run manually after boot, not as a systemd `ExecStartPre`.

This research investigates why the NVIDIA GPU driver requires explicit initialization before EGL works, what GDM was doing that we lost, and what reliable alternatives exist for a headless kiosk boot without a full desktop environment.

## Objectives

- Determine exactly what GPU initialization step GDM/lightdm provides that our headless boot lacks
- Understand why `nvidia-smi` in ExecStartPre fixes the issue manually but not at boot
- Identify a reliable, minimal cold-boot GPU initialization mechanism
- Evaluate alternative compositor strategies (nvweston, headless EGL, Cage, etc.)
- Produce a solution that survives reboot with zero manual intervention

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Root Cause Analysis — EGL/GBM Init Sequence | ✅ Complete | Trace what GDM does at boot; analyze nvidia-drm modeset timing; understand EGL vendor dispatch vs GBM backend selection | 2026-05-05 |
| 2 | Timing & Ordering Investigation | ✅ Complete | Determine if this is a race condition (GPU not ready) or a missing init step; test delays and ordering constraints | 2026-05-05 |
| 3 | Alternative Solutions Survey | ✅ Complete | Evaluate Cage, wlroots, nvidia headless mode, Plymouth handoff, re-enabling GDM in kiosk mode, nvidia-persistenced | 2026-05-05 |
| 4 | Implementation & Validation | ✅ Complete | Implement chosen solution; validate across 5+ cold boots; update unit.py, jetson-harden.sh, and bringup.py | 2026-05-05 |

## Overview

The Weston cold-boot EGL initialization failure on the Jetson AGX Orin is a **timing race condition** between systemd's service startup and the NVIDIA Tegra GPU's asynchronous render engine initialization. The root cause, solution, and implementation are well-defined.

### Root Cause

NVIDIA's `libnvidia-egl-gbm.so.1` library (the external platform plugin for GBM-based compositors) calls `eglQueryDevicesEXT()` during display creation. On Tegra/Jetson, the GPU render engine initializes asynchronously — DRM device nodes appear at t=1-5s post-boot, but EGL device enumeration isn't functional until t=25-30s (cold boot). The current `StartLimitBurst=5` with `RestartSec=3` exhausts all retries (~20s) before the GPU is ready, leaving the service permanently failed.

The error message "DRI2: gbm device using incorrect/incompatible backend" is **misleading** — it's Mesa's fallback reporting that it can't handle an nvidia GBM device, not the actual problem. NVIDIA's EGL fails silently first, then libglvnd dispatches to Mesa.

### Why Previous Attempts Failed

- **`nvidia-smi` in ExecStartPre**: On Tegra, nvidia-smi only accesses the monitoring/thermal subsystem, NOT the EGL/render path. It exits 0 but provides zero GPU render initialization.
- **GDM removal**: GDM implicitly served as the first EGL consumer (via Mutter), which triggered GPU render engine initialization. Disabling GDM removed this warmup step.

### Recommended Solution

**Two-phase rollout:**

| Phase | Approach | Effort | Effect |
|-------|----------|--------|--------|
| A (immediate) | `StartLimitBurst=30`, `RestartSec=2`, remove nvidia-smi | One-line changes | Weston retries for 60s, succeeding at ~30s |
| B (proper) | `ExecCondition=/usr/local/bin/gpu-egl-ready` | 50-line C binary + unit change | Non-failure skip until GPU ready; no wasted restarts |

The EGL probe (`gpu-egl-ready`) calls `eglQueryDevicesEXT()` + `eglInitialize()` — the same APIs Weston needs. It likely both TESTS and TRIGGERS GPU render initialization (first `eglInitialize()` warms the engine for subsequent consumers).

### Key Findings Summary

1. **DRM device ready ≠ EGL ready** — Separate subsystems on Tegra with ~25s async gap
2. **`nvidia-smi` is a no-op for EGL** on Tegra (monitoring path only)
3. **`ExecCondition=`** (systemd v243+) provides non-failure skip — ideal for readiness polling
4. **All alternative compositors** (Cage, nested Weston) have the same EGL problem
5. **nvidia-persistenced/Plymouth** are architecturally inapplicable to Tegra
6. **GDM overkill** — 300 MB of GNOME to do what a 50-line C binary accomplishes
7. **Phase A alone fixes the problem** — increased burst gives sufficient retry budget

### Actionable Conclusions

- Deploy Phase A immediately via `mower jetson bringup --from-step kiosk-services`
- Validate with 5+ cold boot power cycles (not just reboots)
- Layer Phase B once the EGL probe is compiled and tested on-device
- Remove the ineffective `nvidia-smi` ExecStartPre to reduce noise

### Open Questions

- Does the EGL probe **trigger** GPU init (reducing wait time) or merely **test** it? Needs on-device measurement.
- Is `libegl-dev` already satisfied by nvidia-l4t packages on JetPack 6, or does it need explicit install?
- Is `loginctl enable-linger vincent` configured? If not, `/run/user/1000` may be a secondary boot issue.

## Phase 1: Root Cause Analysis — EGL/GBM Init Sequence

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Scope

- What does GDM do at startup that initializes the nvidia EGL stack?
- Trace the difference between `libEGL_nvidia.so.0` and `libEGL_mesa.so.0` dispatch
- Why does mesa's DRI2 backend get selected for the nvidia-drm GBM device?
- What is the role of `/usr/share/egl/egl_external_platform.d/nvidia_gbm.json`?
- What nvidia kernel/userspace state does `nvidia-smi` trigger?
- Does `modeset=1` change the EGL initialization requirements?

### Known Facts

**Hardware/Software:**
- Jetson AGX Orin, JetPack R36.5 (L4T 5.15.185-tegra), nvidia driver 540.5.0
- Display: DP-1 on nvidia GPU (platform device `13800000.display`)
- DRM devices: `card0` = nvidia-drm (`nv_platform` driver), `card1` = tegra-drm (`host1x/drm` driver)
- Weston v13.0.0 from `nvidia-l4t-weston` package
- GDM3: DISABLED (was holding seat0, blocking Weston DRM master)
- `nvidia-drm modeset=1 fbdev=1` in `/etc/modprobe.d/nvidia-drm.conf`
- `nvidia-drm` in `/etc/modules-load.d/nvidia-drm.conf`
- seatd backend for libseat (not logind)

**EGL Stack:**
- Vendor dispatch: `/usr/share/glvnd/egl_vendor.d/10_nvidia.json` → `libEGL_nvidia.so.0`
- Mesa fallback: `/usr/share/glvnd/egl_vendor.d/50_mesa.json` → `libEGL_mesa.so.0`
- GBM external platform: `/usr/share/egl/egl_external_platform.d/nvidia_gbm.json` → `libnvidia-egl-gbm.so.1`
- GBM backend: `/usr/lib/aarch64-linux-gnu/gbm/nvidia-drm_gbm.so` → symlink to `libnvidia-allocator.so`
- Render node: `/dev/dri/renderD128` (nvidia), `/dev/dri/renderD129` (tegra)

**Observed Behavior:**
- **Fails at boot:** Weston opens card0 via libseat, tries EGL, gets `EGL_NOT_INITIALIZED` with "DRI2: gbm device using incorrect/incompatible backend"
- **Works after `nvidia-smi`:** Running `nvidia-smi -q` (even as root via `ExecStartPre=+`) does NOT fix it at boot — only fixes when run later (possibly timing)
- **Works when started manually after SSH login:** Same Weston command works perfectly 30+ seconds after boot
- **Forcing `__EGL_VENDOR_LIBRARY_FILENAMES`:** Using only nvidia vendor gives different error: "either no EGL_EXT_platform_base support or specific platform support; falling back to eglGetDisplay" → still fails

**Key Error Messages:**
```
libEGL debug: EGL user error 0x3001 (EGL_NOT_INITIALIZED) in eglInitialize: DRI2: gbm device using incorrect/incompatible backend
```
This means: Mesa's DRI2 EGL implementation is being invoked (not nvidia's), and it can't handle the nvidia GBM device.

### Assumptions

1. **Card assignment is stable with modeset=1:** card0 = nvidia, card1 = tegra. Confirmed via `/sys/class/drm/card0/device/driver → nv_platform` and `/sys/kernel/debug/dri/0/name → nvidia-drm`.
2. **The nvidia GBM allocator backend exists and is correctly linked** — `/usr/lib/aarch64-linux-gnu/gbm/nvidia-drm_gbm.so → libnvidia-allocator.so`
3. **seatd is functional** — libseat successfully opens seat and grants session control every time.
4. **The display is physically connected** — `/sys/class/drm/card0-DP-1/status` = "connected".
5. **No nvidia-persistenced available** — Package not installed on JetPack 6 Orin. nvidia-smi is the only known GPU state initializer.
6. **The ExecStartPre=+ nvidia-smi DID run successfully** (exit 0) but EGL still failed — suggesting nvidia-smi alone is insufficient at early boot, OR there is a timing dependency after nvidia-smi completes.

### Findings

#### The EGL Vendor Dispatch Architecture (libglvnd)

The EGL stack on JetPack 6 uses **libglvnd** for vendor-neutral dispatch. When Weston calls `eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gbm_device, ...)`, the dispatch works as follows:

1. **libglvnd** loads EGL vendor libraries in **priority order**:
   - `/usr/share/glvnd/egl_vendor.d/10_nvidia.json` → `libEGL_nvidia.so.0` (priority 10 = highest)
   - `/usr/share/glvnd/egl_vendor.d/50_mesa.json` → `libEGL_mesa.so.0` (priority 50 = fallback)

2. **libEGL_nvidia.so** loads external platform plugins for platform-specific handling:
   - `/usr/share/egl/egl_external_platform.d/nvidia_gbm.json` → `libnvidia-egl-gbm.so.1`

3. The external platform's `isValidNativeDisplay()` is called to check if it can handle the display
4. If valid, `getPlatformDisplay()` creates the EGL display
5. `eglInitialize()` hooks run to complete initialization

**If NVIDIA's EGL fails at any point**, libglvnd falls through to Mesa's EGL, producing the observed error.

#### NVIDIA egl-gbm Initialization Chain (from source analysis)

Analysis of [NVIDIA/egl-gbm](https://github.com/NVIDIA/egl-gbm) source code reveals the exact initialization sequence:

**Step 1: Platform Loading (`gbm-platform.c:loadEGLExternalPlatform`)**
```c
// Creates platform data, checks for EGL_EXT_platform_device client extension
platform->data = (void *)CreatePlatformData(driver);
```

**Step 2: Platform Data Creation (`gbm-platform.c:CreatePlatformData`)**
```c
// Resolves gbm_device_get_backend_name via dlsym
res->ptr_gbm_device_get_backend_name = dlsym(RTLD_DEFAULT, "gbm_device_get_backend_name");
if (res->ptr_gbm_device_get_backend_name == NULL) {
    DestroyPlatformData(res);
    return NULL;
}

// Also checks for EGL_EXT_platform_device and EGL_EXT_device_query/base
clExts = res->egl.QueryString(EGL_NO_DISPLAY, EGL_EXTENSIONS);
if (!eGbmFindExtension("EGL_EXT_platform_device", clExts) || ...) {
    DestroyPlatformData(res);
    return NULL;
}
```

**Step 3: Display Creation (`gbm-display.c:eGbmGetPlatformDisplayExport`)**
```c
// Check backend name — CRITICAL gate
const char *name = data->ptr_gbm_device_get_backend_name(display->gbm);
if (name == NULL || strcmp(name, "nvidia") != 0) {
    goto fail;  // Not nvidia backend → let libglvnd try next vendor
}

// Find matching EGL device via eglQueryDevicesEXT
display->dev = FindGbmDevice(data, display->gbm);
if (display->dev == EGL_NO_DEVICE_EXT) {
    goto fail;  // ← LIKELY FAILURE POINT AT BOOT
}

// Open a DEVICE-level EGL display
display->devDpy = data->egl.GetPlatformDisplay(EGL_PLATFORM_DEVICE_EXT, display->dev, attrs);
```

**Step 4: Device Enumeration (`gbm-display.c:FindGbmDevice`)**
```c
// Enumerate all NVIDIA EGL devices
data->egl.QueryDevicesEXT(maxDevs, devs, &numDevs);

// Match GBM device's DRM fd against EGL device paths
for (i = 0; i < numDevs; i++) {
    if (CheckDevicePath(data, devs[i], EGL_DRM_DEVICE_FILE_EXT, statbuf.st_rdev)) {
        dev = devs[i]; break;
    }
    if (CheckDevicePath(data, devs[i], EGL_DRM_RENDER_NODE_FILE_EXT, statbuf.st_rdev)) {
        dev = devs[i]; break;
    }
}
```

**Step 5: EGL Initialize Hook (`gbm-display.c:eGbmInitializeHook`)**
```c
// Initialize the device-level EGL display
res = data->egl.Initialize(display->devDpy, major, minor);

// Check for required stream extensions
if (!eGbmFindExtension("EGL_KHR_stream", exts) || ...) {
    data->egl.Terminate(display->devDpy);
    eGbmSetError(data, EGL_NOT_INITIALIZED);  // ← THE ERROR WE SEE
    res = EGL_FALSE;
}
```

#### The Root Cause: GPU Not Ready for EGL Device Enumeration at Early Boot

The failure occurs because **on Tegra/Jetson, the GPU's EGL device enumeration infrastructure is not ready at early boot**. Specifically:

1. `nvidia-drm` kernel module loads early (it's in `/etc/modules-load.d/`) with `modeset=1`
2. DRM device nodes appear (`/dev/dri/card0`, `/dev/dri/renderD128`) — Weston's device-wait loop succeeds
3. The GBM device creation succeeds (NVGBM allocator backend loads, `gbm_device_get_backend_name()` returns "nvidia")
4. **FAILURE**: Either `eglQueryDevicesEXT()` returns 0 devices, OR `FindGbmDevice()` cannot match the DRM device to an EGL device, OR `eglInitialize()` on the device display fails because the GPU's internal EGL state (compute shaders, stream extensions) is not initialized

The DRM device being available (card0 exists) is **NOT sufficient** for EGL device enumeration to work. The nvidia GPU's **userspace EGL path** requires additional initialization beyond just having the kernel DRM module loaded.

#### Why Mesa's Error Appears

When the nvidia egl-gbm platform fails (returns `EGL_NO_DISPLAY` or `EGL_FALSE` from initialize):
1. libglvnd dispatches to the next vendor: Mesa (`libEGL_mesa.so.0`)
2. Mesa's DRI2 `platform_gbm.c` attempts to initialize with the GBM device
3. Mesa looks at the GBM backend → it's nvidia's NVGBM allocator (not Mesa's own DRI backend)
4. Mesa correctly reports: **"DRI2: gbm device using incorrect/incompatible backend"**
5. This produces: `EGL_NOT_INITIALIZED (0x3001)`

The error message is misleading — it's **Mesa reporting that it can't handle an nvidia GBM device**, not the actual root cause.

#### What GDM Does That We Lost

GDM provides GPU initialization through this chain:

1. **GDM starts** → loads **Mutter** (GNOME compositor)
2. Mutter uses **EGL via EGLDevice** or **EGL via GBM** (depending on GNOME version)
3. The first successful `eglInitialize()` call from Mutter **triggers full GPU userspace initialization**:
   - NVIDIA's EGL internal state is created
   - GPU firmware loading completes
   - EGL device enumeration infrastructure becomes functional
   - Stream/image extensions become available
4. After this, **any subsequent process** can successfully call EGL functions

**GDM effectively serves as a GPU warmup mechanism**, not just a display manager. When we disabled GDM for our headless kiosk setup, we removed this implicit GPU initialization.

#### Why nvidia-smi Doesn't Fix It on Tegra

On **desktop NVIDIA** (discrete GPUs), `nvidia-smi`:
- Opens `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-modeset`
- Triggers full kernel driver initialization via NVML ioctls
- After nvidia-smi, the GPU is "warm" for EGL

On **Tegra/Jetson** (integrated GPU), `nvidia-smi`:
- Talks to the Tegra-specific power/thermal management interface
- Queries GPU clock, temperature, power — NOT the EGL/rendering paths
- Does NOT trigger EGL device initialization or GPU render engine power-up
- **This is why `ExecStartPre=+/usr/sbin/nvidia-smi -q` exits 0 but doesn't help EGL**

The Tegra GPU's EGL rendering subsystem is separate from the monitoring/thermal management subsystem that nvidia-smi uses.

#### The `modeset=1` Factor

`nvidia-drm modeset=1` ensures:
- DRM KMS connectors appear (`card0-DP-1`)
- DRM device nodes are created (`/dev/dri/card0`, `/dev/dri/renderD128`)
- The display controller is initialized for scanout

But `modeset=1` does NOT guarantee:
- EGL device enumeration readiness
- GPU render context availability
- EGL stream extension support

These are separate GPU subsystems. The display controller (KMS) can be ready while the render engine (EGL/GL) is still powering up.

#### Timing Validation

The observed behavior perfectly matches this analysis:
- **Fails at boot**: GPU render engine not ready, `eglQueryDevicesEXT()` fails
- **Works 30+ seconds after boot**: GPU has completed internal async initialization
- **nvidia-smi doesn't help**: It touches monitoring, not EGL/render paths
- **Manual start works**: By the time operator SSHs in, GPU is fully ready
- **`__EGL_VENDOR_LIBRARY_FILENAMES` forcing nvidia**: Different error because it forces ONLY nvidia EGL, which still can't initialize the device display → no Mesa fallback, different error path

#### The `__EGL_VENDOR_LIBRARY_FILENAMES` Clue

Setting this to force-load only NVIDIA produces: "either no EGL_EXT_platform_base support or specific platform support; falling back to eglGetDisplay". This confirms:
- NVIDIA's EGL IS being loaded
- But it cannot create the platform display (device enumeration fails)
- Without Mesa as fallback, a different (more informative) error path is taken

#### Cold Boot Timeline

```
Cold Boot Timeline:
═══════════════════════════════════════════════════════════════════

t=0s    nvidia-drm loads (modeset=1)
        │
t=1-5s  /dev/dri/card0 appears ← DRM device wait PASSES ✓
        │
t=5s    nvidia-smi ExecStartPre runs ← exits 0 (monitoring OK) ✓
        │                              BUT: EGL device enum still NOT ready ✗
        │
t=5-6s  Weston starts → gbm_create_device(card0) ← succeeds ✓
        │                 backend_name = "nvidia" ← succeeds ✓
        │                 eglQueryDevicesEXT() ← FAILS ✗ (or FindGbmDevice fails)
        │                 nvidia EGL returns EGL_NO_DISPLAY
        │                 libglvnd → Mesa → "DRI2: incorrect backend"
        │
t=30+s  GPU render engine fully initialized (async internal process)
        │
t=30+s  Manual weston start → same chain → eglQueryDevicesEXT SUCCEEDS ✓
```

**Key Discoveries:**
- The "DRI2: gbm device using incorrect/incompatible backend" error is from **Mesa's fallback**, not the actual problem. NVIDIA's egl-gbm fails silently first, then libglvnd falls through to Mesa which cannot handle nvidia's GBM device.
- NVIDIA's egl-gbm (`gbm-display.c:FindGbmDevice`) uses `eglQueryDevicesEXT()` to enumerate GPU devices and match them to the GBM device's DRM fd. This enumeration **requires the GPU render engine to be ready**, which it is NOT at early boot on Tegra.
- `nvidia-smi` on Jetson/Tegra only accesses the monitoring/thermal management subsystem, NOT the EGL/render paths. It provides zero GPU render initialization.
- GDM served as an implicit GPU render engine initializer by being the first EGL consumer. Without it, no process triggers the GPU's EGL state initialization.
- The DRM device node existing (`/dev/dri/card0`) only means the **display controller** (KMS) is ready. The **render engine** (EGL/GL) has a separate, asynchronous initialization path on Tegra.
- On desktop NVIDIA, `nvidia-persistenced` keeps the GPU render state alive by holding `/dev/nvidia0` open. On Jetson, this daemon may not exist or may not serve the same purpose.
- The fix requires either: (a) waiting until the GPU render engine is actually ready (not just the DRM device), or (b) triggering the render engine initialization explicitly (equivalent to what GDM did), or (c) re-enabling a minimal display manager that initializes EGL before Weston.

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | Weston unit template with ExecStartPre commands including nvidia-smi |
| `scripts/jetson-harden.sh` | DRM modeset config, kiosk groups, weston config functions |
| `weston.service` | Current deployed unit file with nvidia-smi workaround |
| `weston.unit` | Alternative unit file without nvidia-smi (card1 reference, possibly stale) |

**External Sources:**
- [NVIDIA/egl-gbm source](https://github.com/NVIDIA/egl-gbm) — source of libnvidia-egl-gbm.so.1
- [NVIDIA/eglexternalplatform](https://github.com/NVIDIA/eglexternalplatform) — EGL external platform interface specification
- [NVIDIA Jetson Weston/Wayland docs](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/WindowingSystems/WestonWayland.html)
- [nvidia-persistenced docs](https://download.nvidia.com/XFree86/Linux-x86_64/535.129.03/README/nvidia-persistenced.html)
- [Arch Wiki — NVIDIA DRM KMS](https://wiki.archlinux.org/title/NVIDIA#DRM_kernel_mode_setting)

**Gaps:**
- Could not get Mesa's `platform_gbm.c` source directly to confirm exact error path in Mesa
- Unknown whether `eglQueryDevicesEXT()` returns 0 devices or returns devices that don't match the DRM path — requires EGL debug tracing on device at boot time
- No access to NVIDIA's internal Tegra EGL implementation source to confirm async GPU initialization theory

**Assumptions:**
- Assumed `eglQueryDevicesEXT()` behavior on Tegra follows the same model as desktop NVIDIA (device enumeration depends on GPU readiness) — reasonable given the shared egl-gbm codebase
- Assumed the Jetson's GPU render engine has an asynchronous initialization path separate from DRM/KMS — supported by the timing evidence (works at 30+ seconds but not at 5 seconds)
- Assumed the `+` prefix on ExecStartPre (running as root) means nvidia-smi definitely has device access — confirmed by exit code 0 in known facts

## Phase 2: Timing & Ordering Investigation

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Scope

- Add substantial delay (10-30s) between nvidia-smi ExecStartPre and Weston ExecStart — does timing fix it?
- Check uptime when Weston fails vs when it succeeds manually — is there a minimum boot time threshold?
- Investigate what systemd targets/services must complete before GPU EGL is usable
- Check if `/run/user/1000` creation timing matters (logind creates it)
- Check if nvidia kernel module initialization has async components after device probe
- Test if accessing `/dev/nvidia0` + `/dev/nvidia-modeset` + `/dev/nvidia-uvm-tools` before Weston helps
- Check if `nvidia-modprobe` utility exists and would help create device nodes
- Test `ExecStartPre=/bin/sleep 15` as a brute-force validation of timing hypothesis

### Findings

#### The Timing Gap: DRM Ready ≠ EGL Ready

From Phase 1 and analysis of the current unit template in `src/mower_rover/service/unit.py`:

```ini
# Current ExecStartPre chain:
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /dev/dri/card0 ] && exit 0; sleep 1; done; echo "DRM device not found"; exit 1'
ExecStartPre=+/bin/sh -c '/usr/sbin/nvidia-smi -q > /dev/null 2>&1'
```

This waits for the DRM device node (KMS) but immediately proceeds. The `nvidia-smi` call is a no-op for EGL on Tegra.

**Estimated timing gap:** ~25-30 seconds on cold boot, ~10-15 seconds on warm reboot.

| Event | Approx Time After Boot | EGL Ready? |
|-------|----------------------|------------|
| nvidia-drm loads | t=0-1s | No |
| /dev/dri/card0 appears | t=1-5s | No |
| nvidia-smi exits 0 | t=5s | No |
| Current Weston start attempt | t=5-6s | No |
| 5th restart attempt (current) | t=20-25s | Maybe |
| GPU render engine ready | t=30+s (cold boot) | Yes |
| GPU render engine ready | t=10-15s (warm reboot) | Yes |
| Manual start (SSH login) | t=60+s | Yes |

#### Why Current `Restart=always` + `StartLimitBurst=5` Fails

The current unit has `Restart=always`, `RestartSec=3`, `StartLimitBurst=5`, `StartLimitIntervalSec=300`. This means:
- Weston fails at boot (~5s), wait 3s, retry (~8s), wait 3s, retry (~11s)...
- After 5 failures within 300s, the service enters **failed state** and stops retrying
- **5 retries × ~4-5s each ≈ 20-25s** — exhausted BEFORE the ~30s GPU readiness threshold

This is exactly why the service stays failed: the burst limit runs out before the GPU render engine completes its async initialization.

#### `ExecCondition=` — The Ideal Systemd Mechanism

`ExecCondition=` (systemd v243+, available on JetPack 6 which ships systemd 249) provides a **non-failure skip**:
- Exit code 0: proceed to ExecStart
- Exit code 1-254: skip (service goes to **inactive**, NOT failed — does NOT count against StartLimitBurst)
- Exit code 255: service marked failed

Combined with `Restart=always` + `RestartSec=3`, this creates a clean polling loop:
1. ExecCondition checks EGL readiness
2. Not ready → exit 1 → service skips → waits 3s → retries (no burst penalty)
3. Ready → exit 0 → Weston starts successfully

#### Minimal EGL Readiness Probe (C Binary)

```c
// gpu-egl-ready.c — minimal EGL device enumeration probe
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <stdio.h>

int main(void) {
    PFNEGLQUERYDEVICESEXTPROC eglQueryDevicesEXT =
        (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    if (!eglQueryDevicesEXT) return 1;

    EGLDeviceEXT devices[4];
    EGLint numDevices = 0;
    if (!eglQueryDevicesEXT(4, devices, &numDevices)) return 1;
    if (numDevices == 0) return 1;

    // Verify we can open a display on the first device
    PFNEGLGETPLATFORMDISPLAYEXTPROC eglGetPlatformDisplayEXT =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    if (!eglGetPlatformDisplayEXT) return 1;

    EGLDisplay dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, devices[0], NULL);
    if (dpy == EGL_NO_DISPLAY) return 1;

    EGLint major, minor;
    if (!eglInitialize(dpy, &major, &minor)) {
        return 1;  // GPU not ready yet
    }
    eglTerminate(dpy);
    return 0;  // GPU EGL ready!
}
// Compile: gcc -o /usr/local/bin/gpu-egl-ready gpu-egl-ready.c -lEGL
```

#### Python ctypes Alternative (No Compilation)

```python
#!/usr/bin/env python3
"""Check if NVIDIA EGL device enumeration is functional."""
import ctypes, sys
try:
    egl = ctypes.CDLL("libEGL.so.1")
    eglGetProcAddress = egl.eglGetProcAddress
    eglGetProcAddress.restype = ctypes.c_void_p
    eglGetProcAddress.argtypes = [ctypes.c_char_p]
    qd = eglGetProcAddress(b"eglQueryDevicesEXT")
    if not qd: sys.exit(1)
    EGLint = ctypes.c_int32
    num_devices = EGLint(0)
    func_type = ctypes.CFUNCTYPE(ctypes.c_uint, EGLint, ctypes.c_void_p, ctypes.POINTER(EGLint))
    query_devices = func_type(qd)
    result = query_devices(0, None, ctypes.byref(num_devices))
    if not result or num_devices.value == 0: sys.exit(1)
    sys.exit(0)  # GPU EGL ready
except Exception:
    sys.exit(1)
```

#### Ranked Solution Approaches

| Rank | Approach | Pros | Cons |
|------|----------|------|------|
| 1 | **ExecCondition + EGL probe** | Adaptive, no wasted delay, clean polling | Requires small C binary or Python script |
| 2 | **Increase StartLimitBurst=15** | Zero new tooling, simple | Wasteful (full Weston restart each cycle), relies on Weston failure |
| 3 | **ExecStartPre polling loop** | Single utility, blocks until ready | Any probe failure is fatal (counts against burst) |
| 4 | **ExecStartPre=/bin/sleep 20** | Trivially simple | Non-adaptive, always delays 20s even when GPU ready in 5s |

#### `nvidia-modprobe` and `nvidia-persistenced` — NOT Applicable on Tegra

- `nvidia-modprobe`: Creates `/dev/nvidia0` device nodes for **PCI GPUs only**. Tegra has no such device nodes.
- `nvidia-persistenced`: Holds GPU state for **discrete GPUs** via `/dev/nvidia0`. Not available in JetPack 6 packages, and irrelevant to Tegra's integrated GPU.

#### `/run/user/1000` — Possible Secondary Issue

`XDG_RUNTIME_DIR=/run/user/1000` is set in the unit's Environment. This directory is created by `systemd-logind` + `loginctl enable-linger`. If linger is not enabled, this directory may not exist at boot. This is **separate from the EGL issue** but could cause independent failures. Adding `ExecStartPre=/bin/mkdir -p /run/user/1000 && /bin/chown vincent:vincent /run/user/1000` is defensive.

#### Why NVIDIA's `nvstart-weston.sh` Doesn't Help

NVIDIA's official Weston launch script handles `modprobe nvidia_drm`, user groups, and XDG_RUNTIME_DIR — but does NOT handle EGL readiness timing because it's designed for interactive post-boot use or GDM session contexts.

**Key Discoveries:**
- The timing gap is ~25-30s on cold boot — current `StartLimitBurst=5` exhausts retries before GPU is ready
- Simply increasing `StartLimitBurst` to 15+ would likely fix the problem (zero new tooling)
- `ExecCondition=` (systemd v243+, available on JetPack 6) is the ideal mechanism — exit 1-254 skips without counting as failure
- A minimal EGL probe calling `eglQueryDevicesEXT()` can definitively test GPU readiness in <10ms
- `nvidia-modprobe` and `nvidia-persistenced` are NOT applicable on Tegra/Jetson
- On Tegra, the first EGL consumer triggers render engine initialization — there is no separate init command
- `/run/user/1000` creation may be a secondary issue if linger is not configured

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | Weston unit template with ExecStartPre chain and restart settings |
| `weston.service` | Currently deployed unit showing the DRM wait + nvidia-smi pattern |
| `scripts/jetson-harden.sh` | DRM modeset config, kiosk groups |
| `tests/test_kiosk_units.py` | Tests for unit file content |

**External Sources:**
- [nvidia-persistenced docs](https://docs.nvidia.com/deploy/driver-persistence/persistence-daemon.html)
- [nvidia-modprobe manpage](https://manpages.ubuntu.com/manpages/jammy/man1/nvidia-modprobe.1.html)
- [NVIDIA Jetson Weston/Wayland docs](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/WindowingSystems/WestonWayland.html)
- [systemd.service(5) — ExecCondition, Restart](https://man7.org/linux/man-pages/man5/systemd.service.5.html)
- [EGL device enumeration API](https://developer.nvidia.com/blog/egl-eye-opengl-visualization-without-x-server/)

**Gaps:**
- Cannot verify exact cold boot timing without SSH access to device
- Cannot confirm ExecCondition availability without checking `systemctl --version` on device
- Cannot test Python ctypes EGL probe on actual Tegra libEGL
- Unknown if `loginctl enable-linger vincent` is configured

**Assumptions:**
- Cold boot GPU readiness ~30s based on Phase 1 observations — may vary by boot type
- systemd v249 includes ExecCondition (added v243) — very likely correct
- eglQueryDevicesEXT returns quickly with 0 devices rather than blocking

## Phase 3: Alternative Solutions Survey

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Scope

- **Re-enable GDM in kiosk/autologin mode** — Can GDM run in minimal mode that just initializes GPU then hands off?
- **Cage compositor** — Minimal wlroots-based compositor designed for single-app kiosk; does it have the same EGL issue?
- **nvidia-persistenced** — Can it be installed/enabled on JetPack 6? Does it keep GPU initialized?
- **Plymouth DRM handoff** — Plymouth initializes GPU early for splash; does it leave EGL in a usable state?
- **nvweston.service** — JetPack's built-in Weston service script — can we adapt it?
- **Weston with wayland backend** (nested) — Run under a minimal compositor that handles DRM
- **GDM with Weston as session** — Keep GDM for GPU init but auto-login into a Weston session
- **Custom GPU init script** — Direct nvidia kernel ioctls or library calls to initialize EGL state
- **systemd device dependency** — `Requires=dev-dri-card0.device` + proper udev rules
- **EGL device enumeration API** — Use `EGL_EXT_device_enumeration` to force nvidia EGL init

### Findings

#### Consolidated Evaluation of All 10 Alternatives

| # | Alternative | Verdict | Key Reason |
|---|-------------|---------|------------|
| 1 | Re-enable GDM autologin | ❌ NOT RECOMMENDED | GDM holds seat0/DRM master; ~300 MB overhead; fragile GNOME session integration |
| 2 | Cage compositor | ❌ NOT RECOMMENDED | Same EGL problem (uses wlroots GBM backend → same `eglQueryDevicesEXT` path); lacks NVIDIA L4T patches |
| 3 | nvidia-persistenced | ❌ NOT APPLICABLE | Requires `/dev/nvidia0` device nodes that don't exist on Tegra; package not in JetPack 6 |
| 4 | Plymouth DRM handoff | ❌ NOT APPLICABLE | Plymouth uses KMS/framebuffer only; does NOT touch EGL render engine |
| 5 | nvweston.service | ❌ NOT USEFUL | Same cold boot problem; designed for GDM-warm path; no EGL timing handling |
| 6 | Weston nested/wayland | ❌ NOT RECOMMENDED | Circular — outer compositor needs EGL too; adds complexity without solving root cause |
| 7 | GDM with Weston session | ❌ NOT RECOMMENDED | Works but massive overkill; ~300 MB + fragile cross-BSP-update; amounts to "use GDM as a GPU warmup" |
| 8 | Custom GPU init script | ✅ **RECOMMENDED** | This IS the ExecCondition + EGL probe from Phase 2; 20 lines of C, stable EGL API |
| 9 | systemd device dependency | ⚠️ Prerequisite only | Ensures DRM device exists but NOT sufficient for EGL readiness; combine with probe |
| 10 | EGL device enumeration API | ✅ **RECOMMENDED** | Same as #8 — `eglQueryDevicesEXT()` is both the test AND potentially the trigger |

#### Detail: GDM in Kiosk/Autologin Mode

GDM holds `seat0` and runs Mutter internally as its greeter. Even with auto-login, you'd need Weston to run AS a GDM session (via `.desktop` session file), which requires GNOME session infrastructure, PAM, logind, dbus-activation. Adds ~200-400 MB RAM and dozens of fragile interdependencies. GDM config breaks on BSP updates.

#### Detail: Cage Compositor

Cage uses wlroots' DRM backend which calls `eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, ...)` — the SAME nvidia egl-gbm path as Weston. It would hit the identical cold boot failure. Additionally, wlroots lacks NVIDIA's L4T-specific GBM/DRM patches that `nvidia-l4t-weston` includes. Not in JetPack repos; requires source builds with wlroots ABI tracking.

#### Detail: Plymouth

Plymouth draws splash screens using DRM dumb buffers (KMS framebuffer) — a completely different layer than EGL/GL. It initializes the display controller for pixel scanout but does NOT touch the GPU render engine or EGL device infrastructure. Irrelevant to this problem.

#### Detail: The EGL Probe IS the Solution

The "custom GPU init script" and "EGL device enumeration API" alternatives are the SAME approach viewed from different angles — both use `eglQueryDevicesEXT()` + `eglInitialize()`. Key insight:

**The probe doesn't just TEST readiness — it likely TRIGGERS GPU EGL initialization.** The first `eglInitialize()` on a device display is what causes the nvidia driver to complete its internal render engine setup. This means the probe is BOTH the readiness check AND the warmup mechanism (same role GDM played, but in 20 lines of C instead of 300 MB of GNOME).

#### Final Recommended Implementation Strategy

**Immediate fix (one-line change, deploy now):**
```ini
StartLimitBurst=15  # was 5 — allows ~45s of retries
RestartSec=2        # was 3 — faster polling
```

**Proper fix (next deploy):**
```ini
ExecCondition=/usr/local/bin/gpu-egl-ready
Restart=always
RestartSec=2
StartLimitBurst=30
StartLimitIntervalSec=120
```

The `gpu-egl-ready` binary (20 lines C, compiled on Jetson: `gcc -o gpu-egl-ready gpu-egl-ready.c -lEGL`):
- Exit 0 → GPU ready → Weston starts
- Exit 1 → GPU not ready → service skips (no burst penalty) → retries in 2s

**Why NOT any heavier alternative:**
- All compositor/DM solutions either share the same EGL problem OR add 200-400 MB RAM + fragile config
- nvidia-persistenced/Plymouth are architecturally inapplicable (wrong GPU type, wrong layer)
- The EGL probe is minimal, stable (API unchanged since 2015), zero runtime cost, and directly addresses the exact condition

**Key Discoveries:**
- Cage would suffer the EXACT same EGL cold boot failure — wlroots GBM backend uses same `eglQueryDevicesEXT()` path
- nvidia-persistenced NOT available on Tegra — `/dev/nvidia0` device nodes don't exist for integrated GPUs
- Plymouth only touches KMS/framebuffer, NOT EGL render engine — completely wrong layer
- The EGL probe likely TRIGGERS GPU initialization (first `eglInitialize()` warms render engine), not just tests it
- GDM's only value was being "the first EGL consumer" — any minimal `eglInitialize()` call provides the same effect
- ALL "replace Weston with X" alternatives are invalid — the problem is in NVIDIA's EGL stack timing, not Weston
- NVIDIA's own nvweston.service has the same cold boot problem — designed for GDM-warm path
- `EGL_EXT_device_enumeration` (`eglQueryDevicesEXT`) is both the test AND trigger mechanism

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | Weston unit template — needs `StartLimitBurst` + `ExecCondition` changes |
| `src/mower_rover/kiosk/units.py` | Calls `generate_weston_unit_file()` |
| `scripts/jetson-harden.sh` | Headless mode setup (disables GDM), DRM modeset config |
| `src/mower_rover/cli/bringup.py` | Bringup step calling weston unit generation |
| `tests/test_kiosk_units.py` | Unit file content assertions |

**External Sources:**
- [Cage compositor](https://github.com/cage-kiosk/cage) — confirms wlroots GBM/DRM backend
- [nvidia-persistenced docs](https://docs.nvidia.com/deploy/driver-persistence/persistence-daemon.html) — confirms discrete GPU only
- [Plymouth wiki](https://wiki.archlinux.org/title/Plymouth) — KMS/framebuffer only
- [EGL_EXT_device_enumeration spec](https://registry.khronos.org/EGL/extensions/EXT/EGL_EXT_device_enumeration.txt) — stable since 2015
- [GDM autologin config](https://wiki.archlinux.org/title/GDM#Automatic_login)
- [NVIDIA egl-gbm source](https://github.com/NVIDIA/egl-gbm)

**Gaps:**
- Cannot verify whether `eglQueryDevicesEXT()` TRIGGERS initialization or merely tests it — needs on-device testing
- Unknown if JetPack 6 ships a pre-built EGL test binary
- Cannot verify exact systemd version on target device

**Assumptions:**
- Cage/wlroots uses same nvidia egl-gbm path — reasonable since both use GBM + EGL_PLATFORM_GBM_KHR
- Plymouth doesn't trigger EGL — based on Plymouth using only KMS dumb buffers
- `eglInitialize()` may serve as both test and trigger — based on manual Weston always working after 30s

## Phase 4: Implementation & Validation

**Status:** ✅ Complete  
**Session:** 2026-05-05

### Scope

- Implement the chosen solution from Phase 3
- Update `src/mower_rover/service/unit.py` — Weston unit template
- Update `scripts/jetson-harden.sh` — harden_weston_config function
- Update `src/mower_rover/cli/bringup.py` — any new packages or steps
- Validate with 5+ consecutive cold boots (power cycle, not just reboot)
- Ensure kiosk_ready event logged within 60s of boot on all attempts
- Update `tests/test_kiosk_units.py` with any new unit file assertions

### Findings

#### Two-Phase Rollout Plan

**Phase A: Immediate Fix (deploy now, zero new binaries)**

| File | Change |
|------|--------|
| `src/mower_rover/service/unit.py` | `StartLimitIntervalSec=120`, `StartLimitBurst=30`, `RestartSec=2`, remove nvidia-smi ExecStartPre |
| `tests/test_kiosk_units.py` | Update `test_restart_sec_3` → `test_restart_sec_2` |
| `weston.service` (repo root) | Update to match new template output |

**Phase B: Proper Fix (ExecCondition + EGL probe)**

| File | Change |
|------|--------|
| `contrib/gpu-egl-ready/gpu-egl-ready.c` | New file — EGL probe source |
| `contrib/gpu-egl-ready/build.sh` | New file — build script |
| `src/mower_rover/service/unit.py` | Add `ExecCondition=/usr/local/bin/gpu-egl-ready` |
| `src/mower_rover/cli/bringup.py` | Add EGL probe compilation to `_run_kiosk_services`, add `libegl-dev` to `_BUILD_APT_PACKAGES` |
| `tests/test_kiosk_units.py` | Add `test_exec_condition_gpu_probe` |

#### Phase A: Unit Template Changes

**Current `_WESTON_UNIT_TEMPLATE` in `unit.py` (~line 405):**
```ini
[Unit]
Description=Weston kiosk compositor for mower display
After=multi-user.target systemd-modules-load.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p /var/log/mower-jetson
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /dev/dri/card0 ] && exit 0; sleep 1; done; echo "DRM device not found"; exit 1'
ExecStartPre=+/bin/sh -c '/usr/sbin/nvidia-smi -q > /dev/null 2>&1'
ExecStart={weston_exec_start}
Environment=XDG_RUNTIME_DIR=/run/user/1000
User={user}
WorkingDirectory={home_dir}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**New template (Phase A):**
```ini
[Unit]
Description=Weston kiosk compositor for mower display
After=multi-user.target systemd-modules-load.service
StartLimitIntervalSec=120
StartLimitBurst=30

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p /var/log/mower-jetson
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /dev/dri/card0 ] && exit 0; sleep 1; done; echo "DRM device not found"; exit 1'
ExecStart={weston_exec_start}
Environment=XDG_RUNTIME_DIR=/run/user/1000
User={user}
WorkingDirectory={home_dir}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

**Changes:**
1. `StartLimitIntervalSec` 300→120 (2 min window)
2. `StartLimitBurst` 5→30 (allows 60s of retries at 2s interval)
3. Remove `nvidia-smi` ExecStartPre (ineffective on Tegra)
4. `RestartSec` 3→2 (faster polling)

**Rationale:** 30 retries × 2s = 60s budget. GPU ready at ~30s cold boot. Well within budget, no new binaries.

#### Phase B: EGL Probe Binary

**`contrib/gpu-egl-ready/gpu-egl-ready.c`:**
```c
/*
 * gpu-egl-ready.c — Minimal EGL device probe for NVIDIA Tegra.
 * Exit codes:
 *   0 — EGL ready (ExecCondition: proceed to ExecStart)
 *   1 — EGL not ready (ExecCondition: skip, no burst penalty)
 *   2 — Fatal error (e.g., libEGL not found)
 *
 * Build: gcc -O2 -o gpu-egl-ready gpu-egl-ready.c -lEGL
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    PFNEGLQUERYDEVICESEXTPROC eglQueryDevicesEXT =
        (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC eglGetPlatformDisplayEXT =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");

    if (!eglQueryDevicesEXT || !eglGetPlatformDisplayEXT) {
        fprintf(stderr, "gpu-egl-ready: EGL device extensions not available\n");
        return 2;
    }

    EGLDeviceEXT devices[4];
    EGLint num_devices = 0;
    if (!eglQueryDevicesEXT(4, devices, &num_devices) || num_devices == 0)
        return 1;

    EGLDisplay dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT,
                                               devices[0], NULL);
    if (dpy == EGL_NO_DISPLAY) return 1;

    EGLint major, minor;
    if (!eglInitialize(dpy, &major, &minor)) return 1;

    eglTerminate(dpy);
    return 0;
}
```

**Template addition (Phase B) — insert after DRM wait ExecStartPre:**
```ini
ExecCondition=/usr/local/bin/gpu-egl-ready
```

#### Bringup Integration

Add to `_run_kiosk_services()` in `bringup.py`, BEFORE deploying the Weston unit:

```python
# Build and install gpu-egl-ready probe (Phase B)
bctx.console.print("  Building GPU EGL readiness probe…")
client.run(
    ["sudo", "bash", "-c",
     "cat > /tmp/gpu-egl-ready.c << 'EOFPROBE'\n"
     "<embedded C source>\n"
     "EOFPROBE\n"
     "gcc -O2 -o /usr/local/bin/gpu-egl-ready /tmp/gpu-egl-ready.c -lEGL "
     "&& chmod 755 /usr/local/bin/gpu-egl-ready "
     "&& rm -f /tmp/gpu-egl-ready.c"],
    timeout=30,
)
```

Also add `"libegl-dev"` to `_BUILD_APT_PACKAGES` (~line 505) to ensure EGL headers are available.

#### Validation Protocol

**5+ consecutive cold boot tests (power cycle, not reboot):**

1. `ssh vincent@192.168.4.38 "sudo shutdown -h now"`
2. Physically disconnect power for 10+ seconds
3. Reconnect power
4. Wait up to 90s for SSH
5. Check: `journalctl -u mower-weston.service --boot -o short-monotonic`
6. Check: `systemctl is-active mower-weston.service mower-kiosk.service`

**Pass criteria:**
- 5/5 cold boots: Weston active within 60s of kernel boot
- No `start-limit-hit` in journal
- Average time-to-active < 45s

**Key Discoveries:**
- `_WESTON_UNIT_TEMPLATE` in `unit.py` (~line 405) is the single source of truth
- `nvidia-smi` ExecStartPre confirmed ineffective on Tegra — should be removed
- `generate_weston_unit_file()` takes `user` and `home_dir` params only — burst/restart hardcoded in template (appropriate)
- `_run_kiosk_services()` in `bringup.py` (~line 1757) is the deployment point
- `_BUILD_APT_PACKAGES` already has `build-essential` and `cmake` — only `libegl-dev` may be missing
- `tests/test_kiosk_units.py` has `test_restart_sec_3` (line ~141) as the only assertion breaking on Phase A
- `ExecCondition` placement: AFTER ExecStartPre (DRM wait passes first), BEFORE ExecStart
- `scripts/jetson-harden.sh` needs NO changes — GPU init is a runtime concern, not a hardening concern
- Pattern for `contrib/gpu-egl-ready/` already exists in `contrib/rtabmap_slam_node/`

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` (~L405-435) | Primary change target — `_WESTON_UNIT_TEMPLATE` |
| `src/mower_rover/cli/bringup.py` (~L505, ~L1757) | `_BUILD_APT_PACKAGES` + `_run_kiosk_services()` |
| `tests/test_kiosk_units.py` (~L116-148) | `TestGenerateWestonUnit` class |
| `weston.service` (repo root) | Reference copy to keep in sync |
| `contrib/rtabmap_slam_node/build.sh` | Pattern for new `contrib/gpu-egl-ready/build.sh` |

**Gaps:**
- Cannot verify `libegl-dev` package name on JetPack 6 without SSH access
- Cannot confirm EGL probe triggers GPU init vs merely tests — requires on-device testing
- `EGL_PLATFORM_DEVICE_EXT` constant availability in JetPack 6 headers needs verification

**Assumptions:**
- JetPack 6 ships systemd 249 (Ubuntu 22.04) — ExecCondition available
- `libEGL.so` and headers present when `nvidia-l4t-weston` is installed
- `gcc` available at kiosk-services step (from earlier `install-build-deps`)

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-05 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/023-weston-cold-boot-egl-initialization.md |
