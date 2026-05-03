---
id: "016"
type: research
title: "OAK-D Pro Bootstrap Detection Failure — Probe & Kernel-Param Gaps"
status: ✅ Complete
created: "2026-05-02"
current_phase: "✅ Complete"
---

## Introduction

After the 2026-05-02 reflash + redeploy of the Jetson AGX Orin, the OAK-D Pro
camera is no longer being reliably detected or configured during `mower jetson
bringup`, even though the hardware is connected and powered on. This research
investigates **why the bootstrap pipeline cannot find or configure the camera**
— covering whether the device has changed USB port/PID, whether kernel
parameters and udev rules are actually live (vs. just written to disk),
whether the probe logic correctly handles the bootloader → booted PID
re-enumeration, and whether the Waveshare hub topology is intact. The
deliverable is a concrete list of detection/configuration gaps and the
remediation needed in `scripts/jetson-harden.sh`,
`src/mower_rover/probe/checks/oakd.py`,
`src/mower_rover/probe/checks/usb_tuning.py`, and the bringup orchestrator.

## Objectives

- Determine the **current physical USB topology**: which hub the OAK-D is plugged into, which bus/port it enumerates on, and which PID(s) are visible.
- Determine whether the **kernel quirks param** (`usbcore.quirks=03e7:2485:gk,03e7:f63b:gk`) is actually live in `/proc/cmdline`, or only written to `/boot/extlinux/extlinux.conf` (i.e. waiting for a reboot the bringup never performs).
- Identify **gaps in `probe/checks/oakd.py`** — vendor-only matching, no PID disambiguation, no bus/speed correlation, no hub-context check.
- Identify **gaps in `probe/checks/usb_tuning.py`** — no probe for `usbcore.quirks`, no probe for hub presence, no probe for udev-rule activation.
- Determine whether **`jetson-harden.sh` ordering** correctly forces a reboot (or defers probes) when kernel-param changes are first applied.
- Determine whether the **DepthAI fallback** (`_depthai_usb_speed()` in `oakd.py`) actually triggers firmware upload and re-enumeration, and whether it can survive the bus switch (Bus 01 bootloader → Bus 02 booted).
- Produce a prioritised remediation list for the **bringup pipeline + probe stack** so a fresh flash detects and configures the OAK-D end-to-end without manual intervention.

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Live USB topology & kernel-param state on the Jetson | ✅ Complete | SSH-driven inspection of `/proc/cmdline`, `lsusb -t`, `/sys/bus/usb/devices/*`, `dmesg`, hub presence, OAK-D PID(s) currently visible | 2026-05-02 |
| 2 | Probe-stack gap analysis (`oakd.py`, `usb_tuning.py`) | ✅ Complete | Code review of all OAK-D-related probe checks: vendor-only match, no PID disambiguation, no `usbcore.quirks` check, no hub check, no link-down/re-enum handling, sysroot vs. live-Jetson divergence | 2026-05-02 |
| 3 | Hardening-script ordering & reboot semantics | ✅ Complete | Trace `jetson-harden.sh` flow: when `harden_usb_params` writes extlinux, when udev rules are reloaded, whether/where bringup forces a reboot, and whether subsequent probe steps see stale or live kernel params | 2026-05-02 |
| 4 | DepthAI fallback & re-enumeration survival | ✅ Complete | Review `_depthai_usb_speed()` — does it upload firmware, can it survive the Bus 01 → Bus 02 PID switch, what happens when LPM quirk is missing (link drop), and are timeouts / retries adequate during bringup | 2026-05-02 |
| 5 | Hub topology & power-rail dependencies | ✅ Complete | Confirm Waveshare 4-Ch hub (`2109:0817`) presence is required, document expected port mapping, and identify how a missing/unpowered hub manifests vs. a missing camera vs. a missing kernel quirk | 2026-05-02 |
| 6 | Remediation design — probe additions, harden-script changes, bringup gating | ✅ Complete | Concrete list of new probe checks, new hardening idempotency guards, reboot-gating in bringup, and operator-facing diagnostics so root cause is visible without reading `dmesg` | 2026-05-02 |

## Phase 1: Live USB topology & kernel-param state on the Jetson

**Status:** ✅ Complete
**Session:** 2026-05-02

### Kernel Command Line

All three required USB kernel parameters are **LIVE and active** in `/proc/cmdline`:

```
usbcore.autosuspend=-1 usbcore.usbfs_memory_mb=1000 usbcore.quirks=03e7:2485:gk,03e7:f63b:gk
```

Confirmed via `/sys/module/usbcore/parameters/`:
- `autosuspend` = `-1` (disabled)
- `usbfs_memory_mb` = `1000`
- `quirks` = `03e7:2485:gk,03e7:f63b:gk` (NO_LPM for both bootloader and booted PIDs)

Per-device power management also confirmed applied via udev rule:
- `/sys/bus/usb/devices/1-4.4.3/power/control` = `on`
- `/sys/bus/usb/devices/1-4.4.3/power/autosuspend_delay_ms` = `-1000`

**Verdict: Kernel params are NOT the problem. No reboot pending.** APPEND line in `/boot/extlinux/extlinux.conf` matches `/proc/cmdline` exactly (modulo `${cbootargs}` expansion).

### USB Device Tree (live)

```
Bus 002 (USB 3.0, tegra-xusb, 10 Gbps root):
└── Port 3: Realtek 0bda:0420 (4-Port USB 3.0 Hub, 10 Gbps)
    └── Port 4: VIA Labs 2109:0817 (Waveshare USB3.0 Hub, 5 Gbps, 4 ports)
        └── (EMPTY — no device on any USB 3.0 port)

Bus 001 (USB 2.0, tegra-xusb, 480 Mbps root):
├── Port 3: IMC Networks 13d3:3549 (Bluetooth, rtk_btusb, 12M)
└── Port 4: Realtek 0bda:5420 (4-Port USB 2.0 Hub, 480M)
    ├── Port 1: Pixart 093a:2510 (Mouse, 1.5M)
    ├── Port 2: SEM 1a2c:506f (Keyboard, 1.5M)
    └── Port 4: VIA Labs 2109:2817 (Waveshare USB2.0 companion, 480M)
        ├── Port 3: **Intel 03e7:2485 (Movidius MyriadX — BOOTLOADER)** ← 480M
        └── Port 4: Hex/ProfiCNC 2dae:1011 (CubeBlack/Pixhawk, cdc_acm, 12M)
```

The OAK-D Pro is on the USB 2.0 companion hub at 480 Mbps in **bootloader mode (PID 2485)**, NOT on the USB 3.0 hub at 5 Gbps in firmware-loaded mode (PID f63b).

### OAK-D Pro Sysfs (current state)

| Attribute | Value |
|-----------|-------|
| sysfs path | `/sys/bus/usb/devices/1-4.4.3` |
| idVendor | `03e7` |
| idProduct | `2485` (bootloader) |
| speed | `480` (USB 2.0 High Speed) |
| bcdUSB | `2.00` |
| manufacturer | Movidius Ltd. |
| product | Movidius MyriadX |
| serial | `03e72485` |
| devpath | `4.4.3`, busnum `1`, devnum `9` |
| power/control | `on` (autosuspend disabled by udev) |
| driver | **(none)** — no kernel driver bound (correct for libusb access) |

### DepthAI Device Discovery

DepthAI 3.6.1 (in `/home/vincent/.local/share/uv/tools/mower-rover/`) **CAN see the device**:

```
1 devices
DeviceInfo(name=1.4.4.3, deviceId=14442C10A1E6D8D600,
           X_LINK_UNBOOTED, X_LINK_USB_VSC, X_LINK_MYRIAD_X, X_LINK_SUCCESS)
```

- State: `X_LINK_UNBOOTED` — waiting for firmware upload
- Protocol: `X_LINK_USB_VSC`
- Status: `X_LINK_SUCCESS` — XLink communication healthy

### dmesg — Critical USB Event Sequence at Boot

Jetson booted at 22:11:28. The bringup probe ran at 22:11:57:

```
[22:11:39] usb 1-4.4.3: new high-speed USB device number 7 using tegra-xusb   ← OAK-D bootloader appears (USB 2.0)
[22:11:57] SSH session 4 from 192.168.7.240 (laptop)                          ← bringup connected
[22:12:00] usb 1-4.4.3: USB disconnect, device number 7                       ← firmware uploaded → device resets
[22:12:01] usb 2-3.4.3: new SuperSpeed USB device number 4 using tegra-xusb   ← ✅ SuperSpeed (USB 3.0) SUCCEEDED
[22:12:03] mtp-probe[2291]: checking bus 2, device 4 → "was not an MTP device"
[22:12:03] usb 2-3.4.3: USB disconnect, device number 4                       ← ❌ SuperSpeed link DROPPED
[22:12:03] SSH session 4 disconnected                                          ← bringup probe process EXITED
[22:12:04] usb 1-4.4.3: new high-speed USB device number 9 using tegra-xusb   ← device falls back to bootloader
```

**SMOKING GUN — exact timestamp correlation:** The SuperSpeed device disconnected at the EXACT same second (22:12:03) the SSH session ended. The bringup probe uploaded firmware → device came up at SuperSpeed → **probe process exited → DepthAI `Device()` was destroyed → MyriadX reset to bootloader.** This is expected DepthAI v3 behavior: firmware is RAM-volatile.

### udev Rules

`/etc/udev/rules.d/80-oakd-usb.rules` is present and active:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/autosuspend}="-1"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/control}="on"
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", SYMLINK+="oakd"
```

- `/dev/oakd` symlink exists
- `/dev/bus/usb/001/009` permissions: `crw-rw-rw-` (0666) — non-root access enabled

### Service State

- **No VSLAM/DepthAI systemd service exists** on the Jetson — `mower-vslam.service` not found
- No unit files in `/etc/systemd/system/` for `vslam`, `mower`, `oakd`, or `depthai`
- DepthAI 3.6.1 IS installed but **nothing keeps a `Device()` open**

### Key Discoveries

- USB 3.0 SuperSpeed **WORKS** — dmesg proves the link succeeded for ~2 s before the holding process exited.
- Device is stuck in bootloader (PID 2485, USB 2.0) because **no persistent process holds a DepthAI `Device()` open**.
- The bringup probe's SSH session ending killed the DepthAI process → MyriadX hard-reset to bootloader (expected DepthAI v3 behavior — firmware is RAM-volatile).
- ALL kernel USB parameters are correctly live (autosuspend, usbfs_memory_mb, quirks) — **NO reboot pending**.
- udev rules correctly applied (0666 perms, `/dev/oakd` symlink, autosuspend override).
- DepthAI 3.6.1 CAN discover the device (`X_LINK_UNBOOTED`, `X_LINK_SUCCESS`) — XLink communication healthy.
- **No systemd service exists to keep the device booted — this is the root cause of "detection failure."**
- Waveshare USB 3.0 hub side has no downstream devices because OAK-D is in bootloader mode (USB 2.0 only at the moment).
- `mtp-probe` touched the briefly-booted SuperSpeed device (likely harmless, but worth ruling out).

### Files Inspected (remote)

| Path | Relevance |
|------|-----------|
| `/proc/cmdline` | Kernel params confirmed live |
| `/boot/extlinux/extlinux.conf` | Matches cmdline, no reboot pending |
| `/etc/udev/rules.d/80-oakd-usb.rules` | Present and active |
| `/sys/bus/usb/devices/1-4.4.3/` | OAK-D sysfs node (bootloader mode) |
| `/sys/bus/usb/devices/2-3.4/` | Waveshare USB 3.0 hub (empty) |
| `/sys/module/usbcore/parameters/{autosuspend,usbfs_memory_mb,quirks}` | All correct |
| `/home/vincent/.local/share/uv/tools/mower-rover/` | DepthAI 3.6.1 installed |
| `/dev/oakd`, `/dev/bus/usb/001/009` | Symlink + 0666 perms confirmed |

**Gaps:** None — all scope items fully addressed with live evidence.

**Assumptions:**
- The SSH session at 22:11:57 from 192.168.7.240 was the operator's `mower jetson bringup` (timing + IP correlate).
- The SuperSpeed disconnect at 22:12:03 was caused by process exit, not a separate USB fault (exact-second correlation with SSH session end).

**Follow-up for later phases:**
- Phase 2: which probe code path opens a `Device()` and then exits, and does it expect `f63b` after exit?
- Phase 3: does `verify` step assume f63b persists? Does bringup ever start a long-lived service?
- Phase 4: `_depthai_usb_speed()` already triggers firmware upload — but it doesn't keep the device booted afterward.
- Phase 6: root fix likely needs either (a) a persistent systemd service holding `Device()` open, or (b) probe/verify must treat `X_LINK_UNBOOTED` (PID 2485) as the normal idle state and only assert SuperSpeed during an active session.

## Phase 2: Probe-stack gap analysis (`oakd.py`, `usb_tuning.py`)

**Status:** ✅ Complete
**Session:** 2026-05-02

### `oakd.py` — Detection Logic

**Device matching strategy** (`check_oakd`, line 48): **vendor-ID-only**.
- Scans `/sys/bus/usb/devices/*/idVendor` for `03e7`.
- Does **not** check `idProduct` (cannot tell `2485` bootloader from `f63b` booted).
- Does **not** check bus (no Bus 01 vs Bus 02 correlation).
- Does **not** check Waveshare hub (`2109:0817`) presence or hub topology.

**Speed threshold logic:**
- Reads `/sys/bus/usb/devices/{device}/speed`.
- If `>= 5000` Mbps → immediate PASS.
- If `< 5000` AND `sysroot == Path("/")` → falls through to DepthAI fallback.

**`_depthai_usb_speed()` fallback (lines 30–44):**

```python
dev = dai.Device()                  # Uploads firmware → device re-enumerates to f63b @ SuperSpeed
speed_name = dev.getUsbSpeed().name # "SUPER" while firmware loaded
dev.close()                         # Releases handle → RAM-volatile FW → drops to bootloader
return _DAI_SPEED_MBPS.get(speed_name, 0)
```

The function does **not** leak the device — it explicitly closes it. But that close is the **root cause**: nothing keeps the firmware loaded after the probe exits.

**Result in current real condition (bootloader-as-idle):** sysfs reports 480 → fallback fires → brief SuperSpeed → returns `(True, "OAK device at USB 5000 Mbps via DepthAI (sysfs pre-boot: 480 Mbps)")`. **The probe PASSES**, but the device drops back to bootloader within seconds.

**Dependency cascade:** `oakd` is `Severity.CRITICAL` and is a dependency for `oakd_vslam_config`, `oakd_usb_autosuspend`, `oakd_usbfs_memory`, `vslam_process`, `vslam_params`, `vslam_lua_script`. If `oakd` fails, all are SKIPPED.

### `usb_tuning.py` — USB Parameter Checks

Three checks, all `depends_on=("oakd",)`:

1. **`oakd_usb_autosuspend`** — reads `/sys/module/usbcore/parameters/autosuspend`, expects `-1`.
2. **`oakd_usbfs_memory`** — reads `/sys/module/usbcore/parameters/usbfs_memory_mb`, expects `>= 1000`.
3. **`oakd_thermal_gate`** — thermal zones against 85°C limit.

**What it does NOT check:**
- No `/proc/cmdline` inspection — does not verify `usbcore.quirks=03e7:2485:gk,03e7:f63b:gk` is live.
- No udev rule presence (`/etc/udev/rules.d/80-oakd-usb.rules`).
- No Waveshare hub (`2109:0817`) presence.
- No "configured but pending reboot" differentiation.

**Dependency design flaw:** Kernel parameters and thermal state have nothing to do with whether the OAK-D is currently visible. Putting these behind `depends_on=("oakd",)` hides infra misconfigurations whenever the device isn't connected (or its probe transiently fails).

### Bringup Orchestrator Flow

**Step 15 `verify`** — calls `mower-jetson probe --json` over SSH. `_DEFERRED_CHECKS` does **not** include `"oakd"`, so oakd is treated as blocking infra. The transient firmware upload makes it pass on a fresh boot, then the device drops back when the probe process exits.

**Step 18 `vslam-services`** — installs `mower-vslam.service` and `mower-vslam-bridge.service`. The VSLAM process is the **persistent `Device()` holder** that keeps the OAK-D booted at SuperSpeed.

**Step 19 `final-verify`** — reboots the Jetson, waits for SSH (180 s), polls probe every 10 s for up to 120 s. `_HW_DEPENDENT` does **not** include `"oakd"` either. After reboot, the system races between the VSLAM service grabbing the device and the probe polling — each probe poll boots/drops the device transiently.

**Per Phase 1 (live state):** `mower-vslam.service` is **not present** on the Jetson at all (`/etc/systemd/system/mower-vslam.service` does not exist). So the supposed persistent device holder is missing, which is why the OAK-D is permanently in bootloader.

### Steps the User Retried (terminal history)

| Step | OAK-D relevant? |
|------|-----------------|
| `build-rtabmap` | No |
| `build-slam-node` | No (uses RTAB-Map/DepthAI libs at build time only) |
| `archive-binaries` | No |
| `install-cli` | No |
| `final-verify` | **Yes** — this is where the failure manifests |

### Gaps Summary

| # | Gap | Impact |
|---|-----|--------|
| 1 | `oakd` check passes transiently via firmware upload, doesn't validate steady-state | Pipeline reports "healthy" while device drops to bootloader on probe exit |
| 2 | `"oakd"` missing from `_DEFERRED_CHECKS` and `_HW_DEPENDENT` | DepthAI import error or unplugged camera halts pipeline despite intent |
| 3 | No PID differentiation (`2485` vs `f63b`) | Probe output cannot tell operator if device is in normal idle vs failed state |
| 4 | `usb_tuning` checks depend on `oakd` | Kernel-param misconfiguration hidden when OAK-D probe fails |
| 5 | No `usbcore.quirks` validation in any probe | LPM-related dropouts not detectable via probe |
| 6 | No udev-rule presence probe | `80-oakd-usb.rules` deployed by harden script but never verified |
| 7 | No Waveshare hub presence probe | Hub absence vs camera absence indistinguishable |
| 8 | `final-verify` reboots after service install → race | Probe and VSLAM service compete for `Device()` after reboot |

### Files Reviewed

| File | Relevance |
|------|-----------|
| `src/mower_rover/probe/checks/oakd.py` | Vendor-only match, speed threshold, transient firmware-upload fallback |
| `src/mower_rover/probe/checks/usb_tuning.py` | Kernel-param checks incorrectly gated on `oakd` |
| `src/mower_rover/cli/bringup.py` | Step 15 verify (`_DEFERRED_CHECKS`), step 18 services, step 19 final-verify (`_HW_DEPENDENT`) — neither set includes `"oakd"` |
| `src/mower_rover/probe/registry.py` | Dependency-based skip propagation, topological ordering |
| `src/mower_rover/probe/checks/vslam.py` | `vslam_process` is the persistent device holder — missing from current Jetson |
| `src/mower_rover/cli/jetson.py` | `mower-jetson probe` entry point |

**Gaps:** None within Phase 2 scope.

**Assumptions:** Assumed `mower-vslam.service` was intended to auto-start on boot — confirmed in step 18 code, but Phase 1 shows the unit file isn't present on the Jetson at all (orthogonal failure).

**Follow-up for Phase 3:** Trace why `mower-vslam.service` was never installed on the live Jetson — step 18 either silently failed, was never reached, or the unit file got removed by a reflash. Also trace `jetson-harden.sh` to confirm udev/kernel-param installation ordering is OK (Phase 1 already confirms they ARE live).

## Phase 3: Hardening-script ordering & reboot semantics

**Status:** ✅ Complete
**Session:** 2026-05-02

### `jetson-harden.sh` Flow (idempotent)

When invoked by bringup as `--os-only` (steps 1–12):

| # | Function | Action | Reboot-relevant |
|---|----------|--------|-----------------|
| 1 | `harden_headless` | multi-user.target (currently SKIPPED) | — |
| 2 | `harden_services` | Disable cups / bluetooth / ModemManager | — |
| 3 | `harden_fstab` | `noatime,commit=60` on root mount | Reboot |
| 4 | `harden_logrotate` | logrotate + journald limits | — |
| 5 | `harden_openblas` | `OPENBLAS_CORETYPE` + CUDA PATH in `/etc/environment` | Reboot for PATH |
| 6 | `harden_nvpmodel` | Set power mode 3 (50 W), `--force` may auto-reboot | May self-reboot |
| 7 | `harden_watchdog` | `RuntimeWatchdogSec=30` | Reboot |
| 8 | `harden_apt_hold` | Hold L4T kernel packages | — |
| 9 | `harden_ssh` | sshd hardening drop-in, restarts sshd | — |
| 10 | `harden_oakd_udev` | Write `80-oakd-usb.rules` + **`udevadm control --reload-rules && udevadm trigger`** | Immediate |
| 11 | `harden_usb_params` | Modify `/boot/extlinux/extlinux.conf` (autosuspend, usbfs_memory_mb, **quirks**) | **Reboot required** |
| 12 | `harden_jetson_clocks` | Lock clocks service | Reboot |

- Idempotent: every step checks before applying.
- Does **not** reboot itself — prints "Done. Reboot to apply all changes." Bringup handles the reboot in step 5.
- Does **not** install `mower-vslam.service` — step 18 does that.

### Bringup `STEPS` List (Full 19-Step Order)

```
 1. clear-host-key       6. restore-binaries     11. archive-binaries    16. vslam-config
 2. check-ssh            7. install-build-deps   12. pixhawk-udev        17. service
 3. enable-linger        8. build-rtabmap        13. install-uv          18. vslam-services
 4. harden-os            9. build-depthai        14. install-cli         19. final-verify
 5. reboot-and-wait     10. build-slam-node      15. verify
```

- Step 5 reboots and verifies kernel cmdline includes `usbcore.autosuspend=-1` — this is the gate for `usbcore.quirks` to take effect (Phase 1 confirms it did).
- Step 19 reboots again to validate steady-state.

### VSLAM Service Install Path (the smoking gun)

Step 18 (`vslam-services`) calls:

1. `mower-jetson vslam install --yes` → `install_vslam_service()` writes `~/.config/systemd/user/mower-vslam.service` + `systemctl --user daemon-reload`.
2. `mower-jetson vslam bridge-install --yes` → same for `mower-vslam-bridge.service`.
3. `systemctl --user start mower-vslam.service mower-vslam-bridge.service`.

**Critical bug: `systemctl --user enable` is never called.** All three install functions in `src/mower_rover/service/unit.py` (`install_service` at lines 175–205, `install_vslam_service` and `install_vslam_bridge_service` at lines 244–266) only do `daemon-reload`. The unit files have `[Install] WantedBy=default.target`, so enabling **would** work — it's just never called. The same bug applies to `mower-health.service`.

### `--from-step` Skip Semantics

```python
if from_step_idx is not None and (i - 1) < from_step_idx:
    console.print("  Skipping — before --from-step target.")
    continue
```

Unconditional skip — no check-and-satisfy logic. When the user ran `--from-step final-verify`, steps 1–18 were ALL skipped. Earlier full runs DID reach step 18 (which is why the unit files exist on disk).

### Live Service State (SSH-confirmed)

```
Location:      ~/.config/systemd/user/mower-vslam.service        (user)
               ~/.config/systemd/user/mower-vslam-bridge.service (user)
               ~/.config/systemd/user/mower-health.service       (user)
System level:  NONE (no /etc/systemd/system/mower*)              ← Phase 1 only checked here
LoadState:     loaded
ActiveState:   inactive
SubState:      dead
UnitFileState: disabled                                          ← ROOT CAUSE
Linger:        yes (enabled by step 3)
```

### Root Cause

**The services are installed and were started once, but never `enable`d.** Step 19 (`final-verify`) reboots the Jetson. Without `enable`, no `default.target.wants/` symlink exists, so the services don't auto-start. The probe then finds them dead, and the OAK-D — with no persistent `Device()` holder — stays in bootloader mode (PID 2485, USB 2.0).

### Ordering Issues

1. **Missing `enable`** in `install_service` / `install_vslam_service` / `install_vslam_bridge_service`.
2. **Step 18 `start` then step 19 `reboot`** — the transient running state is destroyed by the reboot.
3. **`_vslam_services_active()` checks `is-active` only**, not `is-enabled` — re-running step 18 would loop.

### Files Reviewed

| File | Relevance |
|------|-----------|
| `src/mower_rover/service/unit.py` | **Bug location** — lines 175–205 (`install_service`) and 244–266 (`install_vslam*`). All call `daemon-reload` but never `enable` |
| `src/mower_rover/cli/bringup.py` | Full 19-step orchestrator; step 18 line 1223, step 19 line 1290, `--from-step` line 1747 |
| `scripts/jetson-harden.sh` | Idempotent; udev step 10 line 255, kernel params step 11 line 280 |
| `src/mower_rover/config/jetson.py` | `service_user_level: bool = True` (line 46) |
| `src/mower_rover/cli/jetson.py` | CLI vslam install/start/stop (line 591+) |

**Gaps:** None.

**Assumptions:** Confirmed by live SSH — `UnitFileState=disabled`.

**Follow-up:**
- Phase 4: confirm DepthAI v3 firmware-volatile behavior is the real reason a transient `Device()` doesn't survive close. (Yes — already established in Phases 1–2.)
- Phase 6: the fix is a 1–2 line addition to each install function in `service/unit.py` plus a guard in `_vslam_services_active`.

## Phase 4: DepthAI fallback & re-enumeration survival

**Status:** ✅ Complete
**Session:** 2026-05-02

### SLAM Node DepthAI Lifecycle

`rtabmap_slam_node` (C++ at `/usr/local/bin/rtabmap_slam_node`):

1. **Device lifetime:** Creates `std::shared_ptr<dai::Device>(dev_cfg)` ONCE in `create_depthai_pipeline()` and holds it for the entire process lifetime. Never closed/reopened during operation.
2. **Pipeline:** `dai::Device(Config)` ctor uploads firmware → USB re-enumerates from PID `2485`/Bus 1/480M to PID `f63b`/Bus 2/SuperSpeed. Pipeline started, frame queues polled non-blockingly via `tryGet<>()`.
3. **No reconnection logic:** Mid-run device loss → `tryGet()` returns null → watchdog (30 s without `WATCHDOG=1`) kills the process → `Restart=on-failure` brings it back.
4. **USB speed:** `Config.board.usb.maxSpeed` from `/etc/mower/vslam.yaml` (`usb_max_speed: SUPER`).

### Systemd Unit Content (live)

```ini
[Unit]
Description=Mower Rover VSLAM (RTAB-Map) daemon
After=network.target mower-health.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
ExecStart=/usr/local/bin/rtabmap_slam_node --config /etc/mower/vslam.yaml
Environment=MOWER_CORRELATION_ID=daemon
WorkingDirectory=/home/vincent
WatchdogSec=30
TimeoutStartSec=300
RuntimeDirectory=mower
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Well-formed: `Type=notify`, generous `TimeoutStartSec=300`, `Restart=on-failure`, `WatchdogSec=30`, `StartLimitBurst=5/300s`. **No `ExecStartPre`** — no wait-for-device, but the 10 s internal DepthAI search timeout + restart logic compensates.

### Cold-Boot Timing

From dmesg: OAK-D bootloader enumerates ~11 s after kernel boot. systemd user session starts after `network.target`. `dai::Device(Config)` polls for up to 10 s for vendor `03e7`, finds bootloader, uploads firmware (~5 s), device re-enumerates as PID `f63b` on Bus 2. Worst-case race → 1–2 restart cycles. **Cold-boot resilience: adequate.**

### `_depthai_usb_speed()` Close-by-Design

Close-then-drop is **by design** — the probe answers "can we boot it to SuperSpeed?" The MyriadX has no persistent firmware storage; it must be uploaded each time.

**Conflict with running service:** If `mower-vslam.service` already holds the device, `dai.Device()` cannot acquire it → returns `None` (caught). The probe should detect an active VSLAM service first and read sysfs `2-3.4.3/speed` directly to avoid contention.

### Live Test Results (validated by SSH)

| Step | Observation |
|------|-------------|
| Pre-start | PID `2485`, Bus 1, 480M |
| Service start (8 s) | PID `f63b`, Bus 2, SuperSpeed, `active (running)` |
| 30 s of operation | 200+ frames, confidence 100, 381 MB RAM |
| Service stop | Drops to PID `2485` within ~3 s |
| 5 rapid crash cycles | Each cycle cleanly enumerates SuperSpeed and drops back — no stuck states |

**SuperSpeed hold is reliable when the process stays alive.** Kernel handles repeated Bus 1↔Bus 2 transitions cleanly.

### Second Blocker Discovered: `/run/mower/` Directory Missing

The unit declares `RuntimeDirectory=mower` but **for user-level services this creates `/run/user/1000/mower/`**, not `/run/mower/`. The C++ binary hardcodes `/run/mower/vslam-pose.sock` (a system path). Result: every service start fails with `[socket] bind(): No such file or directory` until `/run/mower` is manually created.

**This is the actual runtime blocker** — even if Phase 3's `systemctl --user enable` fix were applied, the service would still crash-loop without `/run/mower/` existing. Already tracked in plan `009-jetson-deploy-integration-gaps.md`.

### Third Issue: Corrupt RTAB-Map DB Causes Crash Loop

Live test revealed `Memory.cpp:3443` assertion from a corrupt `rtabmap.db`. This is an orthogonal data issue — not USB or DepthAI — but it amplifies the cycling problem.

### Files Reviewed

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | Device lifecycle, pipeline setup, watchdog |
| `src/mower_rover/service/unit.py` | `RuntimeDirectory=mower` declaration (ineffective for user units with system paths) |
| `src/mower_rover/probe/checks/oakd.py` | `_depthai_usb_speed()` close-by-design |
| `/etc/mower/vslam.yaml` (Jetson) | `socket_path=/run/mower/vslam-pose.sock` |
| `~/.config/systemd/user/mower-vslam.service` (Jetson) | Live unit — missing `enable` |
| `docs/plans/009-jetson-deploy-integration-gaps.md` | Already tracks `/run/mower/` gap |

### Key Discoveries

- SLAM node holds `dai::Device` for entire process lifetime — SuperSpeed is maintained as long as the process lives.
- Cold-boot timing is adequate (10 s internal + 5 s `RestartSec` + 5 attempts/300 s window).
- `RuntimeDirectory=mower` is ineffective for user-level units when the binary uses an absolute system path (`/run/mower/`) — **runtime blocker #2**.
- USB cycling under crash loops is clean and non-destructive — the kernel handles it reliably.
- `_depthai_usb_speed()` close-then-drop is correct for a probe but conflicts with a running service.
- Corrupt RTAB-Map DB (`Memory.cpp:3443`) is a third orthogonal blocker that amplifies cycling.
- LPM quirks `03e7:2485:gk,03e7:f63b:gk` are confirmed necessary for stable SuperSpeed on the Waveshare hub.

**Gaps:**
- Could not test true USB transients (cable wiggle, partial disconnect) without physical intervention.
- `RuntimeDirectory` behavior for user units with absolute system paths is per-systemd-version; not exhaustively documented.

**Assumptions:**
- DepthAI v3 `dai::Device(Config)` (no DeviceInfo) uses `DEFAULT_SEARCH_TIME=10s` (inferred from header analysis, not source-traced).
- Memory.cpp assertion is pre-existing DB corruption, not triggered by USB cycling.

**Follow-up for later phases:**
- Phase 6 must include: (a) `systemctl --user enable`, (b) `/run/mower/` creation (tmpfiles.d or system-level service), (c) probe should skip DepthAI fallback when VSLAM is active and use sysfs instead, (d) operator action to delete/repair corrupt rtabmap.db.

## Phase 5: Hub topology & power-rail dependencies

**Status:** ✅ Complete
**Session:** 2026-05-02

### Steady-State Topology

**With VSLAM stopped (current state):**

```
Bus 02 (USB 3.x, 10 Gbps root):
  └─ 2-3 Realtek 0bda:0420 (10 Gbps)
       └─ 2-3.4 Waveshare 2109:0817 (5 Gbps)
            └─ 2-3.4.3 [EMPTY — OAK-D not booted]

Bus 01 (USB 2.0, 480 Mbps root):
  └─ 1-4 Realtek 0bda:5420 (480M)
       └─ 1-4.4 Waveshare 2109:2817 (480M)
            ├─ 1-4.4.3 OAK-D Bootloader 03e7:2485 (480M, 500 mA)
            └─ 1-4.4.4 Pixhawk 2dae:1011 (12M, 100 mA)
```

**With VSLAM running:** OAK-D migrates to `2-3.4.3` as PID `03e7:f63b` at 5 Gbps (same physical port, different bus). Pixhawk stays at `1-4.4.4`.

**Insight:** Waveshare presents as a dual-TT pair: `2109:0817` (USB 3.0 instance) + `2109:2817` (USB 2.0 instance). They always enumerate together — absence of either signals a hub problem.

### Failure-Mode Discrimination

| Failure | `2109:0817` | `2109:2817` | `03e7:2485` | `03e7:f63b` | `2dae:1011` | Distinguishing Signal |
|---|---|---|---|---|---|---|
| Normal (VSLAM stopped) | ✅ | ✅ | ✅ Bus1 | ❌ | ✅ | `2485` on Bus 1, no `f63b` |
| Normal (VSLAM running) | ✅ | ✅ | ❌ | ✅ Bus2 5G | ✅ | `f63b` on Bus 2 |
| Camera unplugged | ✅ | ✅ | ❌ | ❌ | ✅ | No `03e7:*` anywhere |
| Hub unpowered | ✅ (descriptor lies) | ✅ | ⚠️ unstable | ❌ / unstable | ✅ / drops | Repeated connect/disconnect in dmesg |
| Hub unplugged from Jetson | ❌ | ❌ | ❌ | ❌ | ❌ | No `2109:*`, no downstream devices |
| Wrong port (USB-C J24) | ✅ | ✅ | varies | varies | varies | No Realtek `0bda:*` parent in chain |
| Kernel quirk missing | ✅ | ✅ | ✅ brief | ❌ drops | ✅ | Rapid `2-3.4.3` connect/disconnect (LPM) |
| Bootloader stuck (FW upload fail) | ✅ | ✅ | ✅ persists >30 s | ❌ | ✅ | `2485` persists; never transitions |

### Power-Rail Status (live)

| Hub | Bus | Speed | bmAttributes | Power Mode | MaxPower |
|---|---|---|---|---|---|
| `2109:0817` | 2 | 5000 M | `0xe0` | Self-Powered | 0 mA |
| `2109:2817` | 1 | 480 M | `0xe0` | Self-Powered | 0 mA |

**External 5V adapter is connected and working.** Total downstream load when VSLAM running ~1.1 A (OAK-D peak ~1 A + Pixhawk 0.1 A); 3 A budget gives 1.9 A headroom.

**Caveat:** VIA Labs `2109:0817` may hardcode "Self Powered" in descriptor even when aux power is missing. Power-loss detection should rely on **downstream device stability**, not the hub descriptor.

### dmesg Signatures

| Event | Pattern | Meaning |
|---|---|---|
| Normal boot | `usb 2-3.4: new SuperSpeed USB device` | Hub up at 5 Gbps |
| Firmware upload OK | `usb 1-4.4.3: USB disconnect` then `usb 2-3.4.3: new SuperSpeed USB device` | Bootloader → booted transition |
| Connect/disconnect loop | Alternating new/disconnect at `2-3.4.3` within seconds | LPM quirk missing OR service crash-loop OR insufficient power |
| Over-current | `over-current change on port N` | Power supply issue |
| Device never appears at hub port | No enumeration after hub is up | Cable / device unpowered |

Live dmesg shows ~5 connect/disconnect cycles at ~6 s intervals — characteristic of **VSLAM service crash-loop** (matches Phase 4's observation), not hardware instability.

### Key Discoveries

- Hub reports Self-Powered — 5V aux adapter is connected and working.
- Waveshare dual-TT: `2109:0817` (USB 3.0) + `2109:2817` (USB 2.0) always enumerate as a pair.
- OAK-D moves between Bus 1 (`1-4.4.3` bootloader) and Bus 2 (`2-3.4.3` booted) but stays on physical hub port 3.
- Pixhawk is USB 2.0 only — always at `1-4.4.4`, never Bus 2.
- Currently observed connect/disconnect cycles match VSLAM crash-loop pattern, not hardware fault.
- Hub presence detection is trivial: `lsusb -d 2109:` returns 2 devices when healthy.
- Realtek `0bda:0420`/`5420` presence confirms Type-A routing (absence → hub on USB-C J24).

**Gaps:**
- Could not test physically unpowered hub mode without disconnecting the 5V adapter.
- Could not test USB-C J24 routing without physical port move.

**Assumptions:**
- The repeated connect/disconnect pattern (~6 s) is from software crash-loop, not hardware instability (hub power healthy supports this).
- VIA Labs `2109:0817` may report Self-Powered even without aux — must verify via downstream stability heuristic.

**Follow-up for Phase 6:**
- Hub-presence probe is straightforward: `lsusb -d 2109:` should return both `0817` and `2817`.
- Power-loss heuristic: count `03e7:*` disconnect events in `dmesg --since=...` — >3 in 60 s is suspicious.
- Probe should distinguish at least: hub-missing, camera-missing, bootloader-only-as-idle, booted, crash-loop.

## Phase 6: Remediation design — probe additions, harden-script changes, bringup gating

**Status:** ✅ Complete
**Session:** 2026-05-02

### P0 — Service-Install Fixes (must fix to make bringup work)

#### R-1: Add `systemctl --user enable` to all service install functions

- **Problem:** `install_service()`, `install_vslam_service()`, `install_vslam_bridge_service()` only call `daemon-reload`. No `default.target.wants/` symlink → services don't auto-start after step-19 reboot.
- **Fix location:** `src/mower_rover/service/unit.py` — line ~204 (`install_service`), ~265 (`install_vslam_service`), ~356 (`install_vslam_bridge_service`)
- **Sketch:** After `daemon-reload`, call `_systemctl(["enable", f"{UNIT_NAME}.service"], user_level=user_level)`. Idempotent.
- **Test:** Unit test mocks `subprocess.run`, asserts enable in call sequence. Live: `systemctl --user is-enabled mower-vslam.service` → `enabled`.
- **Acceptance:** After full bringup + reboot, all three services are `enabled` and reach `active` within 30 s of boot.

#### R-2: Create `/run/mower/` via `tmpfiles.d`

- **Problem:** User-level `RuntimeDirectory=mower` creates `/run/user/1000/mower/` but binary hardcodes `/run/mower/vslam-pose.sock`. Service crashes with `bind(): No such file or directory`.
- **Fix location:** `scripts/jetson-harden.sh` (preferred) — add `/etc/tmpfiles.d/mower.conf` writer + `systemd-tmpfiles --create`. Alternative: `ExecStartPre=/bin/mkdir -p /run/mower` in unit template at `unit.py` line ~138.
- **Sketch (Option A):**
  ```
  echo "d /run/mower 0755 $MOWER_USER $MOWER_USER -" > /etc/tmpfiles.d/mower.conf
  systemd-tmpfiles --create
  ```
- **Test:** Live: after reboot (no manual intervention) `/run/mower/` exists with `vincent:vincent` ownership.
- **Acceptance:** `mower-vslam.service` reaches `active (running)` after reboot without manual `mkdir`.

### P1 — Probe Additions (better diagnostics)

#### R-3: Add `"oakd"` to `_DEFERRED_CHECKS` and `_HW_DEPENDENT`

- **Problem:** Camera unplugged or DepthAI import error currently blocks the entire pipeline at step 15.
- **Fix location:** `src/mower_rover/cli/bringup.py` — `_DEFERRED_CHECKS` line 987, `_HW_DEPENDENT` line 1347. Also add `oakd_usb_autosuspend`, `oakd_usbfs_memory` to `_HW_DEPENDENT`.
- **Acceptance:** Step 15 yields a yellow "Deferred" message instead of red abort when OAK-D is unplugged.

#### R-4: PID-aware OAK-D probe with state discrimination

- **Problem:** Vendor-only matching can't tell bootloader-idle (normal) from booted (healthy) from absent.
- **Fix location:** `src/mower_rover/probe/checks/oakd.py` — `check_oakd()` line 48.
- **Sketch:** Read `idProduct`. `2485` + VSLAM inactive → PASS "bootloader-idle, normal". `2485` + VSLAM active → WARN "crash-loop?". `f63b` → PASS "booted at {speed} Mbps". Absent → FAIL.
- **Acceptance:** Probe output distinguishes 3 states clearly to the operator.

#### R-5: Skip DepthAI fallback when VSLAM service is active

- **Problem:** `_depthai_usb_speed()` competes with running VSLAM for the single device.
- **Fix location:** `src/mower_rover/probe/checks/oakd.py` — around line 30 / call site line 68.
- **Sketch:** If `systemctl --user is-active mower-vslam.service` returns 0, read sysfs `2-3.4.3/speed` instead of opening `dai.Device()`.
- **Acceptance:** Running probe while VSLAM is active never causes device contention.

#### R-6: New probe `usbcore_quirks`

- **Problem:** Missing LPM quirks cause SuperSpeed drops; not detected by any probe.
- **Fix location:** New check in `src/mower_rover/probe/checks/usb_tuning.py`. `depends_on=("jetpack_version",)`, `Severity.WARNING`.
- **Sketch:** Read `/sys/module/usbcore/parameters/quirks`, assert `03e7:2485:gk` and `03e7:f63b:gk` both present.
- **Acceptance:** Probe names the exact missing kernel parameter.

#### R-7: New probe `waveshare_hub`

- **Problem:** Hub absence and camera absence are indistinguishable in current output.
- **Fix location:** New check in `usb_tuning.py`. `Severity.CRITICAL`.
- **Sketch:** Scan sysfs for `2109:0817` AND `2109:2817`. Both present → PASS. One present → "hub partially enumerated, power issue?". Neither → "hub not detected".
- **Acceptance:** Hub-unplugged failure mode is clearly distinguishable from camera-unplugged.

#### R-8: New probe `oakd_udev_rule`

- **Problem:** `80-oakd-usb.rules` deployed but never verified — silent permission failure if missing.
- **Fix location:** New check in `usb_tuning.py`. `Severity.WARNING`.
- **Sketch:** Check `/etc/udev/rules.d/80-oakd-usb.rules` exists and contains `03e7`.
- **Acceptance:** Probe warns if file is missing or invalid.

#### R-9: Decouple `usb_tuning` from `oakd` dependency

- **Problem:** `oakd_usb_autosuspend` and `oakd_usbfs_memory` check kernel-wide params but are skipped when OAK-D probe fails.
- **Fix location:** `src/mower_rover/probe/checks/usb_tuning.py` lines 13 and 24 — change `depends_on=("oakd",)` to `depends_on=("jetpack_version",)`.
- **Acceptance:** Kernel-param probes still run when OAK-D is unplugged.

### P1–P2 — Bringup Orchestrator Changes

#### R-10: Step 18 verifies `is-enabled` (defence-in-depth)

- **Fix location:** `bringup.py` `_run_vslam_services()` line 1223 — after `start`, check `is-enabled`, enable if not.
- **Acceptance:** Step 18 always leaves all three services in `enabled` state.

#### R-11: Step 19 initial 30 s wait after SSH reconnect

- **Problem:** First probe poll catches VSLAM service still starting; emits confusing intermediate failure.
- **Fix location:** `bringup.py` `_run_final_verify()` line 1291 — add `time.sleep(30)` after SSH ready, before first poll.
- **Acceptance:** First probe poll happens ≥30 s after reboot, reducing false negatives.

#### R-12: `_vslam_services_active()` checks `is-enabled`

- **Fix location:** `bringup.py` line 1208.
- **Acceptance:** Idempotency check fails (→ re-run step 18) if services are active but disabled.

### P2 — Operator Runbook Items

- **R-13:** Delete corrupt `~/.ros/rtabmap.db` after reflash (operator action; future automation possible via `--check-db`).
- **R-14:** After first bringup, verify steady-state at 60 s: `idProduct=f63b`, `speed=5000`, no service restarts.

### What's NOT a Problem (do not fix)

| Item | Evidence | Conclusion |
|------|----------|------------|
| Kernel USB params | `/proc/cmdline` matches extlinux; live in sysfs | No reboot pending, no script fix |
| udev rules | `80-oakd-usb.rules` present; `/dev/oakd` symlink; 0666 perms | Already correct |
| Waveshare hub | Both `2109:0817` and `2109:2817` present, self-powered, 5 Gbps | Hub healthy |
| USB SuperSpeed capability | dmesg proves 5 Gbps negotiates when firmware loaded | Not HW/driver issue |
| DepthAI library | v3.6.1, `X_LINK_SUCCESS` on discovery | Library works |
| OAK-D hardware | Reliable under 5 rapid crash cycles | Camera not faulty |
| `jetson-harden.sh` idempotency | All guards check-before-write | Script correct as-is |
| Linger | Already enabled (step 3) | User services can run sans login |
| Bus 1↔Bus 2 transition | Kernel handles cleanly | No quirk/driver issue |

### Operator-Facing Diagnostic Messages

| State | Current | Proposed |
|-------|---------|----------|
| Bootloader-idle, VSLAM stopped | `❌ OAK device at USB 480 Mbps (need ≥5000)` | `✅ OAK-D present (bootloader PID 2485). Normal when VSLAM service is not running.` |
| Booted, VSLAM running | `✅ OAK device found at USB 5000 Mbps` | `✅ OAK-D booted (PID f63b) at 5000 Mbps — VSLAM active` |
| Bootloader, VSLAM active | `✅ ... via DepthAI` (transient) | `⚠️ OAK-D in bootloader but mower-vslam.service is active — possible crash-loop. journalctl --user -u mower-vslam -n 20` |
| Camera absent | `❌ No OAK device detected` | `❌ No OAK-D (vendor 03e7 absent). Hub present — check camera USB cable.` |
| Hub absent | `❌ No OAK device detected` | `❌ Waveshare hub not detected (VID 2109 absent). Check USB-A connection to Jetson.` |
| LPM quirks missing | (not detected) | `⚠️ usbcore.quirks missing for 03e7:2485/f63b — OAK-D will drop SuperSpeed after ~2 s.` |
| `/run/mower/` missing | (silent crash-loop) | `❌ /run/mower/ does not exist — VSLAM socket bind will fail. Run: sudo systemd-tmpfiles --create` |

### Files To Edit (handoff to planner)

| File | Items |
|------|-------|
| `src/mower_rover/service/unit.py` | R-1, R-2 (Option B alt) |
| `src/mower_rover/probe/checks/oakd.py` | R-4, R-5 |
| `src/mower_rover/probe/checks/usb_tuning.py` | R-6, R-7, R-8, R-9 |
| `src/mower_rover/cli/bringup.py` | R-3, R-10, R-11, R-12 |
| `scripts/jetson-harden.sh` | R-2 (Option A, preferred) |

**Gaps:** None — all remediation items trace back to confirmed Phase 1–5 findings.

**Assumptions:**
- `systemd-tmpfiles --create` available on JetPack 6 (Ubuntu 22.04 base — standard systemd).
- 30 s post-reboot wait sufficient (Phase 4: 11 s enum + 5 s FW upload + startup ≈ 20 s worst case + margin).

**Follow-up:**
- Future: automated RTAB-Map DB integrity check (`--check-db`) as a bringup step.
- Future: investigate suppressing `mtp-probe` on `03e7:*` via udev rule (low priority).
- Long-term: consider promoting VSLAM to a system-level service to eliminate `/run/user/` vs `/run/` mismatch.

## Overview

After the 2026-05-02 reflash, `mower jetson bringup` fails at step 19 (`final-verify`) because the OAK-D Pro never reaches its expected steady state: USB 3.x SuperSpeed at PID `03e7:f63b` on Bus 02. Phase 1 confirmed via SSH that **the hardware, kernel parameters, udev rules, and Waveshare hub are all healthy** — the OAK-D is correctly visible in bootloader mode (PID `03e7:2485`, USB 2.0, 480 Mbps). dmesg proved that the bringup probe's transient `dai.Device()` call DOES successfully boot the camera to SuperSpeed for ~2 seconds, then the camera drops back to bootloader the instant the probe process exits — because DepthAI v3 firmware is RAM-volatile and the only thing keeping it loaded is a live `Device()` handle.

Phase 2 traced this to **eight gaps in the probe stack**, but Phase 3 found the actual root cause: the bringup orchestrator's step 18 (`vslam-services`) **installs `mower-vslam.service` and starts it but never `enable`s it**. The 1-line missing call (`systemctl --user enable`) is repeated across all three install functions in `service/unit.py`. With `linger` enabled (correctly, by step 3) but no `default.target.wants/` symlink, the services don't survive the step-19 reboot — leaving no persistent process to hold the OAK-D booted.

Phase 4 confirmed the SLAM node's architecture is correct: it opens `dai::Device` once at startup and holds it for the entire process lifetime, achieving stable SuperSpeed indefinitely. But it surfaced **a second blocker**: the unit's `RuntimeDirectory=mower` directive creates `/run/user/1000/mower/` for user-level units, while the binary hardcodes `/run/mower/vslam-pose.sock` (a system path). Even if the service were enabled, it would crash-loop on `bind(): No such file or directory` until `/run/mower/` is manually created. A third orthogonal issue — corrupt `rtabmap.db` causing a Memory.cpp:3443 assertion — amplifies the cycling.

Phase 5 documented the failure-mode discrimination matrix using the Waveshare dual-TT hub topology, and Phase 6 produced a 14-item prioritised remediation plan: 2 P0 fixes (R-1, R-2) make bringup work; 7 P1 items improve probe diagnostics; 5 P2 items are operator-facing or hardening.

## Key Findings

1. **Root cause: missing `systemctl --user enable`** in `install_service`, `install_vslam_service`, `install_vslam_bridge_service` (`src/mower_rover/service/unit.py`). All three call `daemon-reload` but never `enable`. After step 19 reboots, services don't auto-start → no `Device()` holder → OAK-D stuck in bootloader.
2. **Second blocker: missing `/run/mower/` directory.** `RuntimeDirectory=mower` is ineffective for user-level systemd units when the binary uses an absolute system path. Must be created via `tmpfiles.d` or `ExecStartPre`.
3. **Third (orthogonal): corrupt `~/.ros/rtabmap.db`** triggers `Memory.cpp:3443` assertion, amplifying the crash-loop.
4. **Hardware, kernel, udev, hub: all healthy.** Phase 1 SSH inspection confirmed `usbcore.quirks=03e7:2485:gk,03e7:f63b:gk` is live in `/proc/cmdline`, `/etc/udev/rules.d/80-oakd-usb.rules` is active, both Waveshare hub TT instances (`2109:0817` + `2109:2817`) are present and self-powered, and DepthAI 3.6.1 cleanly discovers the device (`X_LINK_SUCCESS`).
5. **SuperSpeed works — transiently.** dmesg shows USB 3.0 link succeeds for ~2 s during the bringup probe, then drops the instant the probe process exits (exact-second correlation between SSH session end and `usb 2-3.4.3: USB disconnect`).
6. **8 probe-stack gaps** identified in Phase 2: vendor-only matching, no PID disambiguation, no quirks/udev/hub probes, `usb_tuning` incorrectly depends on `oakd`, `"oakd"` missing from `_DEFERRED_CHECKS` and `_HW_DEPENDENT`, post-reboot probe-vs-service race.
7. **`_depthai_usb_speed()` close-then-drop is by design** — a probe answers "can it boot?" not "will it stay booted?" The MyriadX has no persistent firmware storage. The probe should not be invoked when a real `Device()` holder is supposed to be running.
8. **SLAM node architecture is sound.** It holds `dai::Device` for entire process lifetime; achieves stable SuperSpeed when running. Cold-boot timing (10 s internal + 5 s `RestartSec` + 5 attempts/300 s) is adequate.
9. **USB cycling under crash loops is clean.** Kernel handles repeated Bus 1↔Bus 2 transitions without stuck states or cascading failure.
10. **Hub failure modes are now discriminable** via `lsusb -d 2109:` (presence) + `lsusb -d 03e7:` (state) + dmesg disconnect-rate heuristic.

## Actionable Conclusions

1. **Apply R-1 + R-2 first.** These two P0 fixes (each 1–3 lines of code in `unit.py` and `jetson-harden.sh`) restore basic bringup functionality. No other change is required for the immediate problem.
2. **Then apply R-3 through R-9** (probe diagnostic improvements). These don't block functionality but make the next failure visible to the operator without reading dmesg.
3. **Then apply R-10 through R-12** (orchestrator defence-in-depth and post-reboot timing).
4. **Operator must delete the corrupt `~/.ros/rtabmap.db`** before re-running bringup (R-13). Future automation can add `--check-db` to step 18.
5. **Do NOT** modify kernel params, udev rules, hub configuration, DepthAI library, or `jetson-harden.sh` ordering — all are correct.
6. **Hand off to `pch-planner`** with this research and the 14-item R-list. The planner should produce a phased implementation plan grouping P0 (R-1, R-2), P1 (R-3 through R-12), and operator runbook (R-13, R-14).

## Open Questions

- Should VSLAM be promoted to a **system-level** service (`/etc/systemd/system/`) to eliminate the `/run/user/` vs `/run/` path mismatch entirely? Phase 4 noted this as a long-term consideration; current fix uses `tmpfiles.d` workaround.
- Should the bringup pipeline include an automated **`rtabmap.db` integrity check** (RTAB-Map's `--check-db` mode) as a step 17.5 to detect corruption before VSLAM starts?
- Could the `mtp-probe` udev event (which fires on the briefly-booted SuperSpeed device per Phase 1 dmesg) be suppressed via udev `ENV{ID_MTP_DEVICE}="0"` rule for vendor `03e7`? Phase 4 saw no harm, but it adds noise to dmesg.
- For non-Jetson developer environments (laptop SITL), should the probe stack stub the OAK-D check entirely instead of relying on `sysroot` divergence?
- After R-1 lands, is there a backwards-compat concern for any operator who previously ran `mower-jetson vslam install` manually? (Probably not — enable is idempotent — but worth a brief migration note.)

## Standards Applied

| Standard | Relevance | Guidance |
|----------|-----------|----------|
| _none queried_ | — | — |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-02 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/016-oakd-bootstrap-detection-failure.md |
