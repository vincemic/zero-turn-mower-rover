---
id: "005"
type: research
title: "Jetson AGX Orin — JetPack 5 → JetPack 6 Reflash"
status: ✅ Complete
created: "2026-04-23"
current_phase: "✅ Complete"
---

## Introduction

The Jetson AGX Orin currently runs JetPack 5 (L4T R35.4.1). The `jetpack_version` probe check expects L4T R36.x (JetPack 6), and all downstream probe checks (CUDA, OAK-D, power_mode, python_ver, thermal) are skipped due to this dependency failure. This research documents the complete process for reflashing the AGX Orin to JetPack 6, including host setup, pre-flash backup, the flash itself, and post-flash re-bringup — all from the perspective of a Windows-primary operator with no dedicated Linux workstation.

## Objectives

- Determine the exact JetPack 6.x release to target (6.0 GA, 6.1, or latest)
- Document the SDK Manager flash process for AGX Orin step-by-step
- Identify what must be backed up before reflash and how
- Determine the simplest way to get a Linux host environment from Windows (live USB, VM, WSL2)
- Document post-flash steps to re-run `mower jetson bringup` and verify all probe checks pass
- Identify risks, failure modes, and recovery procedures

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | JetPack 6 Release Selection | ✅ Complete | Identify latest stable JetPack 6.x for AGX Orin; compare 6.0 GA vs 6.1+; confirm L4T version, CUDA version, Ubuntu version; check DepthAI/OAK-D compatibility | 2026-04-23 |
| 2 | Linux Host Environment Options | ✅ Complete | Evaluate live Ubuntu USB vs VM vs WSL2 for running SDK Manager on a Windows laptop; USB passthrough requirements; disk space; which Ubuntu version SDK Manager needs | 2026-04-23 |
| 3 | Pre-Flash Backup & Preparation | ✅ Complete | What to back up from current Jetson (configs, SSH keys, installed packages); Force Recovery Mode procedure for AGX Orin; USB-C port identification; hardware prep checklist | 2026-04-23 |
| 4 | SDK Manager Flash Procedure | ✅ Complete | Step-by-step SDK Manager installation and flash; NVMe vs eMMC boot target; network vs offline install; expected duration; common failure modes and recovery | 2026-04-23 |
| 5 | Post-Flash Re-Bringup | ✅ Complete | Initial Jetson setup (user account, network); re-running `mower jetson bringup`; verifying all probe checks pass; any JetPack 6-specific configuration changes needed in probe checks or hardening script | 2026-04-23 |

## Phase 1: JetPack 6 Release Selection

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Updated Recommendation: JetPack 6.2.2 (L4T 36.5.0)

The prior research (002-jetson-agx-orin-bringup.md) recommended **JetPack 6.2.1 (L4T 36.4.4)**. Since that research was completed, NVIDIA has released **JetPack 6.2.2 (L4T 36.5.0)**, which is now the latest stable production release for the Jetson Orin family.

**Updated recommendation: JetPack 6.2.2 (L4T 36.5.0)** — the latest production release, a bug-fix and security-hardening update over 6.2.1 with an identical compute stack.

### Complete JetPack 6.x Release Comparison

| Version | L4T | CUDA | TensorRT | cuDNN | Ubuntu | AGX Orin Support | Notes |
|---------|-----|------|----------|-------|--------|-----------------|-------|
| JetPack 7.1 | 38.4 | 13.0 | — | — | 24.04 | ❌ Thor only | NOT for AGX Orin |
| JetPack 7.0 | 38.2 | 13.0 | — | — | 24.04 | ❌ Thor only | NOT for AGX Orin |
| **JetPack 6.2.2** | **36.5.0** | **12.6.10** | **10.3.0** | **9.3.0** | **22.04** | ✅ **RECOMMENDED** | Bug/security fixes over 6.2.1; HSM boot signing |
| JetPack 6.2.1 | 36.4.4 | 12.6.10 | 10.3.0 | 9.3.0 | 22.04 | ✅ | Superseded by 6.2.2 |
| JetPack 6.2 | 36.4.3 | 12.6 | 10.3 | 9.3 | 22.04 | ✅ | Superseded |
| JetPack 6.1 | 36.4 | 12.6 | 10.3 | 9.3 | 22.04 | ✅ | Superseded |
| JetPack 6.0 GA | 36.3 | 12.x | — | — | 22.04 | ✅ | Initial GA; fewer features |
| **JetPack 5.1.2** | **35.4.1** | 11.4 | — | — | 20.04 | ✅ | **CURRENT on our Jetson** |

### Why JetPack 6.2.2 over 6.2.1

1. **Identical compute stack** — CUDA 12.6.10, TensorRT 10.3.0, cuDNN 9.3.0, VPI 3.2, DLA 3.14 unchanged
2. **Bug fixes and security patches** — Jetson Linux 36.5 fixes known issues and security vulnerabilities from 36.4.x
3. **HSM support** — Hardware Security Module boot image signing (nice-to-have)
4. **Same platform support** — All Jetson Orin series (AGX Orin, Orin NX, Orin Nano)

There is **no reason to prefer 6.2.1 over 6.2.2** — strictly better.

### Why Not Earlier 6.x Releases

| Release | Key Limitation |
|---------|----------------|
| 6.0 GA (L4T 36.3) | Initial release; fewer bug fixes |
| 6.0 DP (L4T 36.2) | Developer Preview — not for production |
| 6.1 (L4T 36.4) | Superseded by 6.2.x |
| 6.2 (L4T 36.4.3) | Superseded; Super Mode only for Nano/NX |
| 6.2.1 (L4T 36.4.4) | Superseded by 6.2.2; fewer security fixes |

### Probe Check Compatibility

| Probe Check | Check Logic | JetPack 6.2.2 Value | Compatible? |
|-------------|-------------|---------------------|-------------|
| `jetpack_version` | `"R36" in first_line` of `/etc/nv_tegra_release` | `# R36 (release), REVISION: 5.0, ...` | ✅ |
| `cuda` | `"release 12." in line.lower()` from `nvcc --version` | `release 12.6, V12.6.x` | ✅ |
| `python_ver` | Checks for Python 3.11+ | Ships 3.10; bringup installs 3.11 | ✅ (after bringup) |
| `oakd` | USB vendor ID `03e7` | No JetPack dependency | ✅ |
| `thermal` | Reads thermal zone sysfs | Same interface | ✅ |
| `power_mode` | Reads nvpmodel state | Supported | ✅ |
| `disk` | Checks disk space | No JetPack dependency | ✅ |

All existing probe checks work without code changes on JetPack 6.2.2.

### DepthAI / OAK-D Pro Compatibility

**DepthAI 3.5.0** is fully compatible with JetPack 6.2.2:

- **No CUDA dependency** — OAK-D Pro runs inference on its onboard Myriad X VPU, not the Jetson's CUDA
- **Ubuntu 22.04 aarch64 support** — Prebuilt wheels on PyPI
- **USB driver compatible** — Standard libusb; kernel 5.15 includes full USB 3.2 Gen2 support
- **Luxonis provides Jetson-specific deployment docs** covering apt dependencies, swap, venv, and `OPENBLAS_CORETYPE=ARMV8`

### Known Issues

1. **JetPack 7.x is Thor-only** — SDK Manager will not offer it for AGX Orin
2. **Windows SDK Manager first-flash USBIPD failure** — May need power cycle and re-enter recovery mode
3. **WSL `.wslconfig` modification** — SDK Manager backs up to `.wslconfig.bak`
4. **APX Driver required on Windows** — Must install before SDK Manager can detect Jetson
5. **Clean flash mandatory for 5.x → 6.x** — OTA upgrade not supported
6. **apt-mark hold for L4T packages** — Project's `jetson-harden.sh` already handles this

**Key Discoveries:**
- JetPack 6.2.2 (L4T 36.5.0) supersedes 6.2.1 as the recommended target
- All probe checks compatible without code changes
- DepthAI has zero CUDA dependency — no version conflicts
- Clean flash via recovery mode is mandatory (no OTA from JP5 to JP6)
- SDK Manager supports direct flash to 6.2.2

| File | Relevance |
|------|-----------|
| `src/mower_rover/probe/checks/jetpack.py` | Checks for "R36" — compatible with L4T 36.5.0 |
| `src/mower_rover/probe/checks/cuda.py` | Checks for "release 12." — compatible with CUDA 12.6.10 |
| `src/mower_rover/probe/checks/oakd.py` | USB vendor ID check — no JetPack dependency |
| `scripts/jetson-harden.sh` | Already holds correct nvidia-l4t-* packages |

**External Sources:**
- [JetPack 6.2.2 product page](https://developer.nvidia.com/embedded/jetpack-sdk-622)
- [JetPack archive](https://developer.nvidia.com/embedded/jetpack-archive)
- [Luxonis Jetson deployment guide](https://docs.luxonis.com/hardware/platform/deploy/to-jetson/)
- [DepthAI 3.5.0 on PyPI](https://pypi.org/project/depthai/)

**Gaps:** Jetson Linux 36.5 detailed release notes PDF not fetched — high-level description is "fixes for known issues and security vulnerabilities."  
**Assumptions:** SDK Manager's 6.2.2 flash procedure is identical to 6.2.1 (same BSP architecture, minor version increment).

## Phase 2: Linux Host Environment Options

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Host Environment Options for Flashing from Windows

#### Option A: SDK Manager Native Windows Install (RECOMMENDED)

**Official support:** ✅ Fully supported since SDK Manager 2.4.0

This is the **officially recommended path** for Windows users. SDK Manager runs natively on Windows and automates the entire WSL2 backend setup.

**What SDK Manager does automatically:**
1. Enables WSL2 and installs a compatible Ubuntu WSL instance
2. Installs a **customized WSL kernel** (needed for USB flashing)
3. Installs **USBIPD-Win** for USB passthrough from Windows to WSL2
4. Modifies `C:\Users\<user>\.wslconfig` (backs up to `.wslconfig.bak`)
5. Handles USB bind/attach to WSL for the Jetson in recovery mode
6. Runs the actual flash tooling inside WSL transparently

**Prerequisites:**
- Windows 10 or 11 (x86_64)
- 8 GB RAM minimum
- **45 GB free disk space** (~500 MB SDK Manager + ~2 GB WSL + ~27 GB downloads + ~16 GB image)
- USB-C to USB-A cable (included with dev kit)
- Internet connection
- NVIDIA Developer account (free)
- **APX Driver** — required to detect Jetson in Force Recovery Mode; SDK Manager prompts with install link

**Known Gotchas:**
1. **First flash USBIPD failure** — First attempt may fail due to USBIPD binding timing. Fix: power off Jetson, re-enter recovery mode, retry
2. **`.wslconfig` overwrite** — If you have custom WSL settings, SDK Manager replaces `.wslconfig` with its custom kernel reference (original backed up to `.wslconfig.bak`)
3. **Custom WSL kernel** — Replaces the default WSL kernel system-wide; stored at `C:\ProgramData\NVIDIA Corporation\SDKs\JetPack_<version>_Linux\`
4. **APX Driver must be installed first** — Without it, SDK Manager cannot see the Jetson at all

**Verdict:** Simplest and most reliable. Zero Linux knowledge required. NVMe flash is supported. NVIDIA designed it specifically for Windows users.

#### Option B: Manual WSL2 + SDK Manager CLI

**Official support:** ✅ Documented at NVIDIA SDK Manager WSL docs

If the operator already has WSL2, they can install SDK Manager directly inside WSL2. However:

**⚠️ CRITICAL LIMITATION: NVMe flashing is NOT supported from the manual WSL path** (per NVIDIA known issues). Since this project targets NVMe boot, **Option B is not viable as the primary path.**

Setup requires: Ubuntu 22.04 WSL, manual USBIPD-Win 4.3.0+ install, 20+ system packages in WSL, manual `usbipd bind/attach` commands from PowerShell.

**Verdict:** Not recommended. NVMe limitation is a blocker. More complex than Option A with no benefit.

#### Option C: Live Ubuntu 22.04 USB Boot (FALLBACK)

**Official support:** ✅ Ubuntu 22.04 x86_64 is a fully supported SDK Manager host

Booting the laptop from a live Ubuntu USB gives a native Linux environment with **direct hardware USB access — no passthrough layer.**

**Setup:**
1. Download Ubuntu 22.04 Desktop ISO
2. Create bootable USB using Rufus (Windows)
3. Reboot laptop → boot from USB → "Try Ubuntu"
4. Download and install SDK Manager `.deb`
5. Connect Jetson in recovery mode — auto-detected via native USB

**Advantages:**
- **Most reliable USB connection** — native hardware, no passthrough
- Full NVMe flash support
- Eliminates all USBIPD/WSL2 issues

**Disadvantages:**
- Requires laptop reboot (can't use Windows during flash)
- 43 GB download cache needs external storage (RAM disk too small for live session)
- Wi-Fi drivers may not work on some laptops (use Ethernet)
- No session persistence by default

**Verdict:** Best fallback if Option A fails. Prepare this in advance alongside Option A.

#### Option D: Virtual Machine (VirtualBox / VMware / Hyper-V)

**Official support:** ❌ Not supported by NVIDIA

**Not recommended.** USB passthrough in VMs is unreliable during flash operations — the Jetson changes USB identity mid-flash (APX → flashed device), breaking USB filters. Hyper-V has no USB passthrough at all. Multiple community reports of flash failures.

#### Option E: Docker Desktop for Windows

**Official support:** ❌ Docker flash images are Linux-host-only for USB access

**Not viable on Windows.** Docker Desktop uses WSL2 backend, adding an unnecessary layer. NVMe flash has known limitations even on Linux Docker. CLI mode only.

### Comparison Matrix

| Criterion | A: Native Windows | B: Manual WSL2 | C: Live USB | D: VM | E: Docker |
|-----------|:-:|:-:|:-:|:-:|:-:|
| **NVIDIA official** | ✅ | ✅ | ✅ | ❌ | ❌ (Win) |
| **Ease of setup** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ |
| **USB reliability** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ |
| **NVMe flash** | ✅ | ❌ | ✅ | Untested | ❌ |
| **Disk space** | ~45 GB | ~45 GB | 43 GB + ext. | ~55 GB | N/A |
| **Requires reboot** | No | No | Yes | No | No |
| **Risk of failure** | Low | Medium | Very low | High | N/A |

### Recommendation

**Primary: Option A — SDK Manager native Windows.** Simplest, GUI-guided, NVMe supported, NVIDIA-designed for Windows users.

**Fallback: Option C — Live Ubuntu 22.04 USB.** Prepare in advance. Native USB eliminates all passthrough issues. Use if Option A fails on first/second attempt.

**Prepare both before starting** — download SDK Manager `.exe` AND create a bootable Ubuntu 22.04 USB.

### USBIPD-Win Key Facts

- Version required: 4.3.0+
- SDK Manager installs it automatically in Option A
- Bridges USB devices from Windows to WSL2 via USB/IP protocol
- `--auto-attach` flag keeps re-attaching when device reconnects (useful during flash reboot)

**Key Discoveries:**
- SDK Manager native Windows install is the recommended path — automates WSL2, kernel, USBIPD entirely
- Manual WSL2 **cannot flash to NVMe** (NVIDIA known issue) — eliminates it for this project
- Live Ubuntu USB is the best fallback — native USB access, full NVMe support
- VMs and Docker on Windows are not viable for Jetson flashing
- APX Driver must be installed on Windows first
- Back up `.wslconfig` before running SDK Manager if custom WSL settings exist
- USBIPD-Win 4.3.0+ required; SDK Manager installs it automatically

| File | Relevance |
|------|-----------|
| `docs/research/002-jetson-agx-orin-bringup.md` | Prior research on SDK Manager Windows support |

**External Sources:**
- [NVIDIA SDK Manager WSL docs](https://docs.nvidia.com/sdk-manager/wsl-systems/index.html)
- [NVIDIA SDK Manager flash guide](https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html)
- [NVIDIA SDK Manager Docker docs](https://docs.nvidia.com/sdk-manager/docker-containers/index.html)
- [USBIPD-Win on GitHub](https://github.com/dorssel/usbipd-win)
- [Microsoft WSL USB guide](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)

**Gaps:** Exact APX Driver download URL is dynamic (provided by SDK Manager error dialog at runtime).  
**Assumptions:** Laptop has USB-A port for the included cable; laptop BIOS supports USB boot for fallback.

## Phase 3: Pre-Flash Backup & Preparation

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Backup Analysis: Reproducible vs Non-Reproducible

**Nearly everything is reproducible** by the project’s automation chain. A clean reflash followed by `mower jetson setup` + `mower jetson bringup` + `sudo bash jetson-harden.sh` regenerates the entire operational state.

**Regenerated by automation (no backup needed):**

| Config/Artifact | Regenerated By |
|-----------------|----------------|
| SSH hardening (90-mower-hardening.conf) | `jetson-harden.sh` §9 |
| Headless mode, disabled services | `jetson-harden.sh` §1-2 |
| Filesystem tuning (noatime, commit=60) | `jetson-harden.sh` §3 |
| Logrotate + journald limits | `jetson-harden.sh` §4 |
| OPENBLAS_CORETYPE, nvpmodel, watchdog | `jetson-harden.sh` §5-7 |
| apt-mark hold L4T packages | `jetson-harden.sh` §8 |
| uv + Python 3.11 | `bringup.py` step `install-uv` |
| mower-jetson CLI (wheel) | `bringup.py` step `install-cli` |
| mower-health.service | `bringup.py` step `service` |

**Requires manual re-creation (NOT automated):**

| Item | Re-creation Procedure |
|------|----------------------|
| **User account** (`vincent`) | SDK Manager Pre-Config with `username=vincent` |
| **Static IP** (`192.168.4.38/24`) | `sudo nmcli con add type ethernet con-name mower-bench ifname eth0 ipv4.addresses 192.168.4.38/24 ipv4.method manual` |
| **Hostname** | SDK Manager Pre-Config or `sudo hostnamectl set-hostname jetson-mower` |
| **SSH authorized_keys** | `mower jetson setup` (after network is up) |
| **Laptop `known_hosts`** entry | `ssh-keygen -R 192.168.4.38` (clear stale key after reflash) |
| **Passwordless sudo** | `echo "vincent ALL=(ALL) NOPASSWD:ALL" \| sudo tee /etc/sudoers.d/vincent` |

### Optional Safety-Net Backup (from Windows laptop)

```powershell
$backup = "$env:USERPROFILE\jetson-backup-$(Get-Date -Format 'yyyy-MM-dd')"
New-Item -ItemType Directory -Path $backup -Force

scp vincent@192.168.4.38:/etc/ssh/sshd_config.d/90-mower-hardening.conf "$backup\"
scp vincent@192.168.4.38:/etc/fstab "$backup\"
scp vincent@192.168.4.38:/etc/environment "$backup\"
scp vincent@192.168.4.38:/etc/NetworkManager/system-connections/* "$backup\" 2>$null
ssh vincent@192.168.4.38 "dpkg --get-selections" > "$backup\dpkg-selections.txt"
ssh vincent@192.168.4.38 "cat /etc/nv_tegra_release" > "$backup\nv_tegra_release.txt"
```

Full filesystem image backup is impractical (64 GB, 30+ min, not restorable across JP versions). Selective backup above is sufficient.

### Force Recovery Mode Procedure

#### Button Identification

Three tactile buttons near the USB-C / DC jack corner:

| Button | Label | Position |
|--------|-------|----------|
| **Power** | S1 | Leftmost (near white LED) |
| **Force Recovery** | S3 | **Middle** |
| **Reset** | S2 | Rightmost |

#### Procedure A — From Power-Off (preferred for reflash)

1. Ensure dev kit is **powered off**
2. Connect USB-C cable from laptop to **port 10 (J40)** — next to 40-pin header
3. Connect power supply (DC barrel jack or USB-C PD)
4. **Press and hold** Force Recovery button (middle)
5. While holding, **press then release** Power button (leftmost)
6. **Release** Force Recovery button
7. Jetson is now in Force Recovery Mode (no video output)

#### Procedure B — From Power-On

1. **Press and hold** Force Recovery (middle) + **Reset** (rightmost)
2. **Release both buttons**

#### Verifying Recovery Mode

- **Windows:** APX device appears in Device Manager (requires APX Driver)
- **Linux:** `lsusb | grep -i nvidia` → `ID 0955:7023 NVIDIA Corp.`
- **SDK Manager:** Shows Jetson as detected in status bar

### USB-C Port Identification

| Port | Board Ref | Location | Flashing? |
|------|-----------|----------|----------|
| Port 4 | J24 | Above DC power jack | **NO** — DFP only (host mode) |
| **Port 10** | **J40** | **Next to 40-pin header** | **YES** — UFP+DFP, required for flashing |

**⚠️ Use port 10 (J40) next to the 40-pin header. Port 4 (J24) above the DC jack CANNOT be used for flashing.**

### Hardware Prep Checklist

#### Physical Items at Workbench

- [ ] Jetson AGX Orin Dev Kit with power supply
- [ ] USB-C to USB-A cable (included with dev kit)
- [ ] Ethernet cable (laptop → Jetson direct connection)
- [ ] Windows laptop with power supply (flash takes 20–40 min)
- [ ] Optional: USB keyboard + DisplayPort monitor (not needed if using Pre-Config)

#### Windows Laptop Pre-Checks

| Check | Command | Expected |
|-------|---------|----------|
| Free disk space | `Get-PSDrive C \| Select Used,Free` | ≥ 45 GB free |
| WSL2 state | `wsl --status` | Note current state |
| Back up `.wslconfig` | `Copy-Item "$env:USERPROFILE\.wslconfig" "$env:USERPROFILE\.wslconfig.pre-sdkmgr"` | If file exists |
| SDK Manager | Check Start menu or download from NVIDIA | Installed |
| NVIDIA account | Log into developer.nvidia.com | Authenticated |
| Live Ubuntu USB | Bootable USB with Ubuntu 22.04 | Fallback ready |

#### Pre-Flash Sequence

1. Back up Jetson configs (optional — see commands above)
2. Shut down Jetson: `ssh vincent@192.168.4.38 "sudo shutdown -h now"`
3. Disconnect Ethernet from Jetson
4. Connect USB-C to **port 10 (J40)**
5. Enter Force Recovery Mode (Procedure A)
6. Verify recovery mode (Device Manager / SDK Manager)
7. Start SDK Manager → proceed to flash (Phase 4)

**Key Discoveries:**
- All Jetson configs are reproducible — no critical data at risk
- Only non-automated items: user account, static IP, hostname, passwordless sudo, known_hosts cleanup
- Flashing port is **port 10 (J40)** next to 40-pin header, NOT port 4 (J24)
- Force Recovery: Hold Recovery → Press+Release Power → Release Recovery
- `ssh-keygen -R 192.168.4.38` MUST be run after reflash (host key changes)

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | All 9 hardening steps regenerated by re-running |
| `src/mower_rover/cli/bringup.py` | Automated bringup chain |
| `src/mower_rover/cli/setup.py` | First-time SSH key + config setup |
| `src/mower_rover/transport/ssh.py` | SSH transport with `StrictHostKeyChecking=accept-new` |

**External Sources:**
- [NVIDIA L4T 36.5 Quick Start](https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/IN/QuickStart.html)
- [AGX Orin Dev Kit Hardware Layout](https://developer.nvidia.com/embedded/learn/jetson-agx-orin-devkit-user-guide/developer_kit_layout.html)
- [AGX Orin Dev Kit How-To](https://developer.nvidia.com/embedded/learn/jetson-agx-orin-devkit-user-guide/howto.html)

**Gaps:** None  
**Assumptions:** Standard P3701/P3737 dev kit carrier board; username `vincent` per SSH config.

## Phase 4: SDK Manager Flash Procedure

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Primary Path: SDK Manager on Windows

#### Step 0: Install SDK Manager (~5 min, one-time)

1. Download `.exe` from https://developer.nvidia.com/sdk-manager
2. Install → accept license → check “Launch SDK Manager” + “Add to PATH”

#### Step 1: STEP 01 — Development Environment (~2 min)

1. Log in with NVIDIA Developer account (browser OAuth)
2. Select:
   - **Product Category:** Jetson
   - **Target Hardware:** Jetson AGX Orin Dev Kit (auto-detected in recovery mode)
   - **SDK Version:** JetPack 6.2.2
   - **Additional SDKs:** Leave unchecked
3. Click **Continue**

**⚠️ APX Driver:** If first flash, SDK Manager may show “APX Driver Not Found.” Follow the linked guide to install, power cycle Jetson into recovery mode, click Refresh.

#### Step 2: STEP 02 — Review Components (~2 min)

1. Review components — leave Jetson Linux, CUDA, cuDNN, TensorRT selected
2. Check download path has ≥ 45 GB free
3. Accept license agreements
4. Click **Continue**

SDK Manager notifies it will set up WSL2, custom kernel, and USBIPD-Win automatically.

#### Step 3: STEP 03 — Installation (20–40 min)

**Sub-phase 3a: WSL2 Setup** (~5 min, Windows only)
- Installs/enables WSL2, Ubuntu instance, custom kernel, USBIPD-Win
- May prompt for UAC elevation

**Sub-phase 3b: Download & Build** (~10–20 min)
- Downloads ~15 GB of components
- Progress shown in UI; Terminal tab for detailed logs

**Sub-phase 3c: Flash Dialog (CRITICAL)**

Select **Manual Setup** → follow Force Recovery procedure from Phase 3.

**OEM Pre-Config (RECOMMENDED):**
- Username: `vincent`
- Password: (your choice)
- Hostname: `jetson-mower`
- Accept EULA: ✅

**Storage Selection:**
- Select **NVMe** (recommended) or EMMC
- Click **Flash**

**Sub-phase 3d: Flashing** (~10–15 min)
- USBIPD binds/attaches USB to WSL2
- Writes QSPI-NOR bootloader + rootfs to NVMe
- Jetson auto-reboots when complete

**⚠️ First-flash USBIPD failure:** Power off Jetson → re-enter recovery mode → Retry in SDK Manager.

**Sub-phase 3e: Post-Flash SDK Install** (~5–10 min)
- SDK Manager prompts for Jetson IP + credentials to install CUDA/cuDNN/TensorRT over SSH
- Enter IP `192.168.4.38` (after static IP configured), username `vincent`
- **If network not ready:** Skip and later run `sudo apt install nvidia-jetpack` on Jetson

#### Step 4: STEP 04 — Summary (~1 min)

Review results, export debug logs if needed, click **Finish**.

### What Gets Installed When

| Component | During Flash | Post-Flash (SSH) |
|-----------|:--:|:--:|
| L4T OS (Ubuntu 22.04) | ✅ | — |
| QSPI-NOR firmware/bootloader | ✅ | — |
| CUDA Toolkit 12.6 | — | ✅ |
| cuDNN 9.3.0 | — | ✅ |
| TensorRT 10.3.0 | — | ✅ |

The flash only writes the base OS. SDK components install separately over SSH. If skipped: `sudo apt install nvidia-jetpack`.

### NVMe vs eMMC

| Criterion | NVMe | eMMC |
|-----------|------|------|
| Speed | 2000+ MB/s | ~200 MB/s |
| Capacity | 256 GB–2 TB | 64 GB fixed |
| SDK Manager | Select “NVMe” | Select “EMMC” |
| CLI flash | `l4t_initrd_flash.sh ... external` | `flash.sh ... internal` |
| **Recommendation** | **✅ Use NVMe** | Only if no NVMe installed |

NVMe flash writes QSPI-NOR (bootloader) + rootfs to SSD. Boot sequence: QSPI-NOR → UEFI → NVMe rootfs.

### Expected Timing

| Step | Duration |
|------|----------|
| SDK Manager install | 5 min (one-time) |
| STEP 01–02 (config) | 4 min |
| WSL2 setup | 5 min (one-time) |
| Downloads | 10–20 min |
| Flash to NVMe | 10–15 min |
| Post-flash SDK install | 5–10 min |
| **Total** | **35–55 min** (first time) |

### Fallback: CLI Flash from Live Ubuntu USB

```bash
# Download L4T 36.5.0 (verify URLs at developer.nvidia.com/linux-tegra)
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/Jetson_Linux_R36.5.0_aarch64.tbz2
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/Tegra_Linux_Sample-Root-Filesystem_R36.5.0_aarch64.tbz2

tar xf Jetson_Linux_R36.5.0_aarch64.tbz2
sudo tar xpf Tegra_Linux_Sample-Root-Filesystem_R36.5.0_aarch64.tbz2 -C Linux_for_Tegra/rootfs/
cd Linux_for_Tegra/
sudo ./tools/l4t_flash_prerequisites.sh
sudo ./apply_binaries.sh

# Pre-configure user (skip oem-config)
sudo ./tools/l4t_create_default_user.sh -u vincent -p '<password>' -n jetson-mower --accept-license

# Verify recovery mode
lsusb | grep -i nvidia  # Expected: ID 0955:7023

# Flash to NVMe
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device nvme0n1p1 \
    -c tools/kernel_flash/flash_l4t_t234_nvme.xml \
    --showlogs --network usb0 \
    jetson-agx-orin-devkit external
```

Post-CLI-flash: `sudo apt install nvidia-jetpack` on Jetson for CUDA/cuDNN/TensorRT.

### Common Failure Modes & Recovery

| Failure | Recovery |
|---------|----------|
| USBIPD first-flash failure | Power off Jetson → re-enter recovery mode → retry |
| APX Driver not found | Install via SDK Manager’s linked guide → power cycle |
| Download failure | Retry Failed Items in STEP 03; or restart SDK Manager |
| USB disconnect mid-flash | Use direct cable (no hub); disable laptop sleep; retry |
| Post-flash SSH failure | Skip → set up network manually → `sudo apt install nvidia-jetpack` |
| Wrong storage target | UEFI menu (ESC during boot) → change boot order |
| Power loss mid-flash | **Not catastrophic** — re-enter recovery mode, reflash |
| Disk space exhaustion | Free space; clean `C:\Users\<user>\Downloads\nvidia\sdkm_downloads` |

**Key Discoveries:**
- Flash only writes base OS + bootloader; CUDA/cuDNN/TensorRT installed post-flash over SSH
- Select NVMe in SDK Manager storage dropdown for NVMe boot
- Use Pre-Config mode for headless setup (username=vincent, hostname=jetson-mower)
- Total time: 35–55 min first flash; ~20 min subsequent
- Power loss is recoverable — Force Recovery Mode is hardware-based
- CLI fallback uses `l4t_initrd_flash.sh` from live Ubuntu 22.04 USB

**External Sources:**
- [SDK Manager flash guide](https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html)
- [SDK Manager download](https://docs.nvidia.com/sdk-manager/download-run-sdkm/index.html)
- [L4T 36.5 Quick Start](https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/IN/QuickStart.html)
- [L4T Flashing Support](https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/SD/FlashingSupport.html)

**Gaps:** None  
**Assumptions:** SDK Manager 2.4.0+ used; NVMe SSD ≥ 64 GB installed; standard dev kit variant.

## Phase 5: Post-Flash Re-Bringup

**Status:** ✅ Complete  
**Session:** 2026-04-23

### Post-Flash State

After JetPack 6.2.2 flash with Pre-Config:
- ✅ Ubuntu 22.04 (L4T R36.5.0), user `vincent`, hostname `jetson-mower`
- ❌ Static IP, SSH keys, passwordless sudo, hardening, uv, Python 3.11, CLI, health service all need setup
- ❓ CUDA/cuDNN/TensorRT — installed only if SDK Manager STEP 03 completed

### Console vs Headless

Operator needs keyboard+monitor for **3 things only**:
1. Static IP configuration (SSH not available yet)
2. Passwordless sudo for `vincent`
3. CUDA install if SDK Manager post-flash failed

Everything else is headless from the laptop.

### Complete Runbook

#### Phase A: Manual Steps (Console)

**A1. Verify boot:**
```bash
cat /etc/nv_tegra_release
# Expected: # R36 (release), REVISION: 5.0, ...
```

**A2. Configure static IP:**
```bash
nmcli device status
sudo nmcli con mod "Wired connection 1" \
    ipv4.addresses 192.168.4.38/24 \
    ipv4.gateway 192.168.4.1 \
    ipv4.method manual
sudo nmcli con up "Wired connection 1"
```

**A3. Passwordless sudo:**
```bash
echo "vincent ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/vincent
sudo chmod 440 /etc/sudoers.d/vincent
```

**A4. If CUDA missing** (SDK Manager post-flash failed):
```bash
sudo apt update && sudo apt install -y nvidia-jetpack
nvcc --version  # Expected: release 12.6
```

**A5. On laptop — clear stale SSH host key:**
```powershell
ssh-keygen -R 192.168.4.38
```

#### Phase B: Semi-Automated (Laptop)

**B1. `mower jetson setup`** — deploys SSH key, writes laptop.yaml

#### Phase C: Fully Automated (Laptop)

**B2. `mower jetson bringup --host 192.168.4.38 --user vincent --yes`**

| Step | Name | Action | Skip If |
|------|------|--------|---------|
| 1 | check-ssh | SSH echo test | SSH works |
| 2 | harden | Push + run jetson-harden.sh | 90-mower-hardening.conf exists + multi-user.target |
| 3 | install-uv | Install uv + Python 3.11 | `~/.local/bin/uv --version` ok |
| 4 | install-cli | Build wheel, push, install | `mower-jetson --version` ok |
| 5 | verify | Run probe checks | Always runs |
| 6 | service | Install mower-health.service | Service active |

Bringup is fully idempotent — re-running after partial failure safely resumes.

### Probe Check Compatibility

All 9 probe checks are compatible with JetPack 6.2.2 without code changes:

| Check | Logic | JP 6.2.2 | OK? |
|-------|-------|----------|-----|
| `jetpack_version` | "R36" in nv_tegra_release | R36 (REVISION: 5.0) | ✅ |
| `cuda` | "release 12." in nvcc | release 12.6 | ✅ |
| `python_ver` | Python 3.11+ | 3.11 via uv | ✅ |
| `oakd` | USB vendor 03e7 | Hardware check | ✅ |
| `thermal` | sysfs thermal zones | Same interface | ✅ |
| `power_mode` | nvpmodel -q | Same CLI | ✅ |
| `disk_space` | /proc/mounts | Universal | ✅ |
| `ssh_hardening` | sshd_config.d scan | Same sshd | ✅ |

### Hardening Script Compatibility

All 9 sections of `jetson-harden.sh` are compatible with JetPack 6.2.2.

**⚠️ Cosmetic bug found:** Line 246 summary label says `"nvpmodel mode 2 (30W)"` but code (line 135–143) correctly sets mode 3 (50W). The code is correct; the label is wrong.

The `apt-mark hold` package names (`nvidia-l4t-kernel`, `nvidia-l4t-kernel-dtbs`, etc.) exist in L4T 36.x. Verify with `dpkg -l | grep nvidia-l4t` on actual hardware.

### JetPack 5 → 6 Differences

| Area | JP 5 (R35) | JP 6 (R36) | Impact |
|------|-----------|-----------|--------|
| nv_tegra_release | R35 | R36 | Probe already checks R36 ✅ |
| CUDA | 11.4 | 12.6 | Probe checks "release 12." ✅ |
| Ubuntu | 20.04 | 22.04 | System Python 3.8→3.10; we install 3.11 |
| Kernel | 5.10 | 5.15 | No sysfs changes |

**No JetPack 6-specific gotchas that break the tooling.**

### OAK-D Pro Verification

1. Plug OAK-D Pro into USB 3.0 port
2. `mower-jetson probe` → `oakd` check shows “OAK device found”
3. `lsusb | grep 03e7` confirms Luxonis device
4. OAK-D check is WARNING severity — bringup succeeds without camera

### CUDA Installation Note

If SDK Manager post-flash SSH failed, CUDA is not installed and the `cuda` probe check (CRITICAL severity) will fail, blocking bringup at the verify step. Run `sudo apt install nvidia-jetpack` on the Jetson before bringup.

**Key Discoveries:**
- All probe checks and hardening script compatible with JetPack 6.2.2 — no code changes needed
- Cosmetic bug in jetson-harden.sh: summary says "mode 2 (30W)" but code correctly sets mode 3 (50W)
- Bringup is fully idempotent — safe to re-run after partial failure
- Console access needed for only 3 things: static IP, sudo, optional CUDA install
- CUDA install is a prerequisite that may need manual intervention
- Codebase already targets JetPack 6 (test fixtures use R36, CUDA checks for "release 12.")

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/bringup.py` | Main bringup orchestration |
| `src/mower_rover/cli/setup.py` | SSH key + config setup |
| `scripts/jetson-harden.sh` | Hardening; has nvpmodel label bug |
| `src/mower_rover/probe/checks/*.py` | All probe checks analyzed |
| `tests/conftest.py` | Test fixtures already use R36 values |

**Follow-Up:**
- Fix nvpmodel summary label bug in jetson-harden.sh (line 246)
- Verify nvpmodel modes and apt-mark package names on actual hardware
- Capture actual bringup output after flash for documentation

**Gaps:** nvpmodel mode table and apt package names need on-device verification  
**Assumptions:** Mode 3 = 50W consistent between JP5 and JP6; L4T package names unchanged in 36.5.0

## Overview

Reflashing the Jetson AGX Orin from JetPack 5.1.2 to JetPack 6.2.2 (L4T 36.5.0) is a straightforward, low-risk operation when performed from a Windows laptop using NVIDIA’s SDK Manager 2.4.0 native Windows install. The entire process takes 35–55 minutes for a first flash and requires no Linux expertise — SDK Manager automates WSL2, USBIPD, and the custom flash kernel behind a GUI workflow.

The project’s existing probe checks, hardening script, and bringup automation are **fully compatible with JetPack 6.2.2 without any code changes**. All Jetson-side configuration is reproducible by the bringup automation chain (`mower jetson setup` → `mower jetson bringup` → `jetson-harden.sh`), meaning there is no critical data at risk during the reflash.

The recommended approach is:
1. **Primary:** SDK Manager native Windows install (handles everything automatically)
2. **Fallback:** Live Ubuntu 22.04 USB boot (native USB access, no passthrough issues)
3. **Always prepare both** before starting

The only manual steps after flash are: static IP via nmcli, passwordless sudo, and (if SDK Manager post-flash failed) `sudo apt install nvidia-jetpack` for CUDA. Everything else runs headless from the laptop.

One minor cosmetic bug was found in `jetson-harden.sh` — the summary label for nvpmodel says "mode 2 (30W)" but the code correctly sets mode 3 (50W).

## Key Findings

1. **JetPack 6.2.2 (L4T 36.5.0)** is the target — supersedes 6.2.1 with identical compute stack (CUDA 12.6.10, TensorRT 10.3.0, cuDNN 9.3.0) plus security/bug fixes
2. **SDK Manager native Windows** is the primary flash path — automates WSL2, USBIPD-Win, and custom kernel; zero Linux knowledge required
3. **Manual WSL2 cannot flash to NVMe** (NVIDIA known issue) — eliminates it as a primary option
4. **Live Ubuntu 22.04 USB** is the best fallback — native USB access, full NVMe support
5. **All probe checks and hardening compatible** with JetPack 6.2.2 without code changes
6. **All Jetson configs are reproducible** by automation — no critical data at risk
7. **Use USB-C port 10 (J40)** next to the 40-pin header for flashing — NOT port 4 (J24)
8. **Flash only writes base OS** — CUDA/cuDNN/TensorRT installed post-flash via SSH or `sudo apt install nvidia-jetpack`
9. **Known first-flash USBIPD failure** on Windows is recoverable — power cycle Jetson and retry
10. **Power loss mid-flash is not catastrophic** — Force Recovery Mode is hardware-based

## Actionable Conclusions

1. **Proceed with reflash** — no blockers identified; total time ~45 min including prep
2. **Download SDK Manager** from developer.nvidia.com and **create a bootable Ubuntu 22.04 USB** before starting
3. **Use Pre-Config** during SDK Manager flash: username=`vincent`, hostname=`jetson-mower`
4. **Select NVMe** as the storage target in SDK Manager
5. **Run `ssh-keygen -R 192.168.4.38`** on the laptop after flash before attempting SSH
6. **After manual steps** (static IP, sudo, optional CUDA), run `mower jetson setup` then `mower jetson bringup --yes`
7. **Fix the cosmetic nvpmodel label bug** in `jetson-harden.sh` line 246 (says "mode 2 (30W)", should say "mode 3 (50W)")
8. **Back up `.wslconfig`** on the laptop if custom WSL settings exist

## Open Questions

1. **nvpmodel modes on L4T 36.5.0** — Verify mode 3 = 50W on actual hardware with `nvpmodel -p --verbose` after flash
2. **apt-mark hold package names** — Verify `nvidia-l4t-*` package names in L4T 36.5.0 with `dpkg -l | grep nvidia-l4t` after flash
3. **Exact SDK Manager version for 6.2.2** — Confirm SDK Manager 2.4.0 or newer supports 6.2.2 (likely same as 6.2.x series)
4. **NVMe SSD installed?** — Confirm an NVMe SSD is installed in the dev kit’s M.2 slot before selecting NVMe as flash target

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-23 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/005-jetson-agx-orin-jetpack6-reflash.md |
