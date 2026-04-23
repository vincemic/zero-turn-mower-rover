---
id: "002"
type: research
title: "Jetson AGX Orin Developer Kit — Initial Bringup & Configuration"
status: ✅ Complete
created: "2026-04-22"
current_phase: "✅ Complete"
---

## Introduction

The NVIDIA Jetson AGX Orin developer kit has arrived and needs to be prepared for its role as the rover's companion computer. This research investigates the concrete steps, configuration choices, and potential pitfalls for flashing, networking, securing, and provisioning the Jetson so it is ready for the project's `mower-jetson` tooling, OAK-D Pro depth camera, and eventual VSLAM stack. The goal is a documented, repeatable bringup procedure that a single operator can execute at a workbench with a Windows laptop.

## Objectives

- Determine the correct JetPack / L4T version and flashing procedure for the AGX Orin dev kit
- Establish a reliable, field-offline network link between the Windows laptop and the Jetson (wired + mDNS/static IP)
- Configure SSH key-only auth that satisfies the project's transport layer (`BatchMode=yes`, no password)
- Identify the Python / pip / pipx / uv installation steps on JetPack Ubuntu (aarch64 constraints)
- Verify OAK-D Pro enumeration via DepthAI on JetPack (USB permissions, driver compatibility)
- Document any JetPack-specific gotchas (CUDA path, apt holds, kernel module quirks) that affect later phases

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | JetPack flashing & first boot | ✅ Complete | SDK Manager requirements; JetPack version selection; flash procedure; first-boot wizard; verification checks | 2026-04-22 |
| 2 | Networking & SSH configuration | ✅ Complete | Static IP vs mDNS; direct Ethernet bench setup; hostname; SSH hardening; key-only auth; Windows OpenSSH client interop | 2026-04-22 |
| 3 | Python toolchain & project install | ✅ Complete | System Python on JetPack; pip/pipx/uv on aarch64; venv strategy; `mower-jetson` install; dependency compatibility (numpy, PyYAML wheels) | 2026-04-22 |
| 4 | OAK-D Pro & DepthAI on JetPack | ✅ Complete | USB 3.0 port selection; DepthAI SDK install on aarch64/JetPack; udev rules; camera enumeration; known JetPack+DepthAI version conflicts | 2026-04-22 |
| 5 | Power, thermal & field-readiness | ✅ Complete | Power modes (MAXN vs others); nvpmodel/jetson_clocks; thermal management on the rover; headless operation; watchdog/auto-recovery; filesystem considerations (SD vs NVMe) | 2026-04-22 |

## Phase 1: JetPack flashing & first boot

**Status:** ✅ Complete
**Session:** 2026-04-22

### 1. JetPack Version Selection

**Recommended version: JetPack 6.2.1 (L4T 36.4.4)** — the latest stable release for Jetson AGX Orin as of April 2026.

| Version | L4T | Ubuntu | CUDA | Status for AGX Orin |
|---------|-----|--------|------|---------------------|
| JetPack 7.x | 38.x | 24.04 | 13.0 | **Jetson Thor ONLY — NOT compatible with AGX Orin** |
| JetPack 6.2.1 | 36.4.4 | 22.04 | 12.6.10 | **Latest stable — RECOMMENDED** |
| JetPack 6.1.x | 36.4.x | 22.04 | 12.6 | Superseded by 6.2.1 |
| JetPack 5.x | 35.x | 20.04 | 11.4 | Legacy; Ubuntu 20.04 EOL approaching |

**Key compute stack in JetPack 6.2.1:**
- CUDA 12.6.10
- TensorRT 10.3.0
- cuDNN 9.3.0
- VPI 3.2
- Python 3.10 (system)
- Ubuntu 22.04 LTS (Jammy)
- Linux kernel 5.15+

**Why NOT JetPack 5.x:** Ubuntu 20.04 is approaching end-of-life; CUDA 11.4 is significantly older; DepthAI and modern Python libraries increasingly target 22.04+ and CUDA 12.x.

**Why NOT JetPack 7.x:** JetPack 7 is exclusively for Jetson Thor. It is based on SBSA architecture and will NOT boot on AGX Orin hardware. The NVIDIA SDK Manager will not even offer JetPack 7 as an option for AGX Orin targets.

### 2. SDK Manager Requirements

#### Host Operating System Options

SDK Manager 2.4.0 supports flashing AGX Orin from:

| Host OS | Flash Support | Notes |
|---------|---------------|-------|
| Ubuntu 20.04 (x86_64) | ✅ Full | Traditional, most mature path |
| Ubuntu 22.04 (x86_64) | ✅ Full | Recommended Linux host |
| Ubuntu 24.04 (x86_64) | ✅ Flashing + target install only | No host SDK development |
| **Windows 10/11 (x86_64)** | ✅ **New in SDK Manager 2.4.0** | Uses WSL2 under the hood |
| Docker (Ubuntu images) | ✅ Full | For headless/CI flash workflows |

#### Windows Flashing (Relevant for This Project)

**SDK Manager 2.4.0 introduced Windows support for JetPack 6.2.x flashing.** This is directly relevant since the operator workstation is a Windows laptop.

When flashing from Windows, SDK Manager automatically:
1. Enables WSL2 and installs a compatible Ubuntu WSL instance
2. Installs a **customized WSL kernel** (for JetPack 6.x only)
3. Installs **USBIPD-Win** to manage USB device connectivity with WSL
4. Modifies `C:\Users\<user>\.wslconfig` (original backed up to `.wslconfig.bak`)

The WSL kernel and config files are stored at:
```
C:\ProgramData\NVIDIA Corporation\SDKs\JetPack_<version>_Linux\
```

**APX Driver requirement:** Windows requires an APX Driver for detecting the Jetson in Force Recovery Mode. If not found, SDK Manager shows an error dialog with a link to the APX Driver Installation Guide.

**Known Windows issue:** The first flash attempt may fail due to USBIPD binding. Power off the device and re-enter recovery mode to resolve.

#### Hardware Requirements

| Resource | Minimum |
|----------|---------|
| Host RAM | 8 GB |
| Host free disk | 27 GB (host components) + 16 GB (target image) = **43 GB total** |
| USB cable | USB Type-C to Type-A (included in AGX Orin dev kit box) |
| Internet | Required during SDK Manager download and flash (not required at field runtime) |
| NVIDIA account | Required — free NVIDIA Developer account for SDK Manager login |
| Screen resolution | 1440×900+ recommended for GUI mode |

### 3. Flash Procedure

#### Option A: SDK Manager GUI on Windows (Recommended for This Project)

**Pre-requisites:**
1. Download and install SDK Manager from https://developer.nvidia.com/sdk-manager
2. Create/log in to NVIDIA Developer account
3. Ensure ≥43 GB free disk space
4. Have the USB-C to USB-A cable ready (included in dev kit box)

**Step-by-step:**

1. **Enter Force Recovery Mode on AGX Orin Dev Kit:**
   - A. Ensure the developer kit is **powered off**
   - B. **Press and hold** the Force Recovery button (middle button on the button cluster)
   - C. **Press, then release** the Power button
   - D. **Release** the Force Recovery button
   - E. Connect USB-C cable (use the port next to the 40-pin header) to the Windows laptop

2. **Launch SDK Manager:**
   - Open SDK Manager on Windows
   - Log in with NVIDIA Developer account
   - SDK Manager should auto-detect the Jetson AGX Orin in recovery mode
   - If APX Driver is missing, follow the instruction guide linked in the error dialog

3. **STEP 01 — Development Environment:**
   - Product Category: **Jetson**
   - Target Hardware: **Jetson AGX Orin Developer Kit** (auto-detected)
   - SDK Version: **JetPack 6.2.1**
   - Additional SDKs: skip for initial flash

4. **STEP 02 — Review Components:**
   - Review selected components (Jetson Linux BSP, CUDA, cuDNN, TensorRT, etc.)
   - Accept license agreements
   - SDK Manager will set up WSL2 environment automatically (first time only)

5. **STEP 03 — Installation:**
   - SDK Manager downloads and begins flashing
   - Choose storage target: **NVMe** (recommended) or **eMMC**
   - OEM configuration choice:
     - **Pre-Config** (headless-friendly): provide username, password, hostname, locale upfront
     - **Runtime**: complete wizard interactively after flash
   - **Recommendation for this project: Pre-Config** with:
     - Username: `mower` (or operator's preferred username)
     - Hostname: `jetson-mower` (matches project SSH config expectations)
     - Locale/timezone: operator's local settings
   - Wait for flash to complete (15–45 minutes depending on USB speed and storage target)

6. **STEP 03 (continued) — Post-flash SDK Install:**
   - After flash, the Jetson reboots and runs first-boot setup
   - SDK Manager prompts for the Jetson's IP address and credentials
   - Enter the username/password from Pre-Config
   - SDK Manager installs remaining components (CUDA toolkit, cuDNN, TensorRT, etc.) over network
   - **This step requires the Jetson to have network access** (connect Ethernet before this step)

7. **STEP 04 — Finalize:**
   - Review summary for any errors
   - Export debug logs if needed
   - Click Finish

#### Option B: Command-Line Flash on Linux Host (Alternative)

If the operator has access to an Ubuntu 20.04/22.04 x86_64 machine (or WSL2 with USB passthrough already working), the flash can be done via CLI:

```bash
# Download L4T release package and sample rootfs
tar xf Jetson_Linux_R36.4.4_aarch64.tbz2
sudo tar xpf Tegra_Linux_Sample-Root-Filesystem_R36.4.4_aarch64.tbz2 \
  -C Linux_for_Tegra/rootfs/
cd Linux_for_Tegra/
sudo ./tools/l4t_flash_prerequisites.sh
sudo ./apply_binaries.sh

# Flash to eMMC:
sudo ./flash.sh jetson-agx-orin-devkit internal

# Or flash to NVMe SSD:
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
  --external-device nvme0n1p1 \
  -c tools/kernel_flash/flash_l4t_t234_nvme.xml \
  --showlogs --network usb0 jetson-agx-orin-devkit external
```

The `jetson-agx-orin-devkit` config name applies to both 32GB (P3701-0000, P3701-0004) and 64GB (P3701-0005) dev kit modules.

### 4. Storage Target: NVMe vs eMMC

| Factor | eMMC | NVMe SSD |
|--------|------|----------|
| Capacity | 32 or 64 GB (module-dependent) | 256 GB – 2 TB (user-supplied) |
| Speed | ~300 MB/s sequential | 2000+ MB/s sequential |
| Available on dev kit | Built into module | M.2 slot on carrier board |
| Flash command | `flash.sh ... internal` | `l4t_initrd_flash.sh ... external` |
| SDK Manager | Select "EMMC" | Select "NVMe" |

**Recommendation: Flash to NVMe** if an M.2 NVMe SSD is available. For the mower rover project, NVMe is strongly preferred:
- DepthAI frame logging, VSLAM maps, and structlog JSONL files consume disk rapidly
- eMMC is limited and has lower write endurance
- An NVMe SSD (even 256 GB) provides ample headroom

If NVMe is selected, the UEFI boot menu must be configured to boot from the NVMe drive.

### 5. First-Boot Wizard (oem-config)

When using **Runtime** mode (not Pre-Config), the first boot presents Ubuntu's `oem-config` wizard:

1. **Review and accept NVIDIA Jetson software EULA**
2. **Select system language** — English (US) recommended for consistency with project tooling
3. **Select keyboard layout**
4. **Select time zone** — operator's local timezone
5. **Create username and password** — this becomes the primary SSH user; choose a name that aligns with the `mower-jetson` config (e.g., `mower`)
6. **Set computer name (hostname)** — recommend `jetson-mower` to match project's SSH endpoint config
7. **Configure wireless networking** — optional at first boot; wired Ethernet preferred for reliability

**Headless first-boot alternative:** Connect via serial console (USB-C on the dev kit provides a serial debug interface) or connect a keyboard/monitor. Pre-Config mode in SDK Manager bypasses this entirely.

After oem-config completes, the system reboots to the Ubuntu desktop (or login prompt if no display is connected).

### 6. Verification Checks

After flash and first boot, run these checks to confirm a successful installation:

```bash
# 1. L4T / JetPack release (this is what mower-jetson info reads)
cat /etc/nv_tegra_release
# Expected: # R36 (release), REVISION: 4.4, ...

# 2. Hardware model
cat /proc/device-tree/model
# Expected: NVIDIA Jetson AGX Orin Developer Kit

# 3. Architecture
uname -m
# Expected: aarch64

# 4. Kernel version
uname -r
# Expected: 5.15.x-tegra

# 5. CUDA version
nvcc --version
# Expected: Cuda compilation tools, release 12.6, V12.6.x

# 6. JetPack metapackage
dpkg -l | grep nvidia-jetpack
# Expected: ii  nvidia-jetpack  6.2.1-...

# 7. System Python
python3 --version
# Expected: Python 3.10.x

# 8. GPU/memory monitoring
sudo tegrastats
# Expected: live GPU/CPU/memory stats (Ctrl+C to exit)

# 9. Disk layout (verify NVMe if used)
lsblk
# Expected: nvme0n1 with mounted rootfs if flashed to NVMe

# 10. CUDA sample smoke test
cd /usr/local/cuda/samples/1_Utilities/deviceQuery
sudo make
./deviceQuery
# Expected: "Result = PASS" with Orin GPU details
```

The existing codebase already reads `/etc/nv_tegra_release` in `src/mower_rover/cli/jetson.py` (`_read_jetpack_release()`) and uses it to set `is_jetson = True`. After a successful flash, `mower-jetson info` will report the JetPack release string and confirm it's running on a Jetson.

### 7. Gotchas and Pitfalls

1. **JetPack 7 is NOT for AGX Orin** — it's Thor-only. The SDK Manager landing page highlights JetPack 7 prominently, which could cause confusion.

2. **Windows first-flash USBIPD failure** — The first attempt to flash from Windows may fail due to USBIPD-Win USB binding timing. Power cycle the Jetson and re-enter recovery mode to resolve.

3. **WSL .wslconfig modification** — SDK Manager modifies the Windows user's `.wslconfig` for the custom WSL kernel. If the operator has existing WSL configurations, they should review the backup at `.wslconfig.bak`.

4. **APX Driver on Windows** — Must be installed before SDK Manager can detect the Jetson in recovery mode. The SDK Manager provides a link to the installation guide when the driver is missing.

5. **Post-flash SDK component install requires network** — The base flash writes the BSP (kernel + rootfs), but CUDA toolkit, cuDNN, TensorRT, etc. are installed over the network in a second pass. Ensure the Jetson has Ethernet connectivity for this step.

6. **Dev kit modules ship with old firmware** — New AGX Orin dev kits may ship with JetPack 5.0 firmware. SDK Manager handles the upgrade through recovery mode flash, but the operator should not try to do an OTA upgrade from 5.x to 6.x — always flash clean.

7. **NVMe boot requires UEFI menu selection** — If flashing to NVMe, the UEFI boot order must be set to boot from the NVMe drive. The flash process may not automatically set this.

8. **USB-C port selection** — For the AGX Orin dev kit, use the **USB-C port next to the 40-pin header** for the flashing connection, not the other USB-C ports.

9. **`apt-mark hold` on L4T packages** — After flash, NVIDIA's apt repositories pin certain L4T kernel/bootloader packages. Do not `apt upgrade` them without careful version control, as a broken kernel update can brick the device (requiring re-flash).

**Key Discoveries:**
- JetPack 6.2.1 (L4T 36.4.4) is the correct and latest version for AGX Orin; JetPack 7 is Jetson Thor only
- SDK Manager 2.4.0 now supports flashing from Windows via WSL2, directly relevant for this project's Windows-laptop operator
- Windows flashing requires APX Driver installation and may fail on first attempt due to USBIPD timing (power cycle resolves)
- NVMe flash is recommended over eMMC for the mower rover use case (disk I/O, capacity for VSLAM/logs)
- The AGX Orin force recovery mode: hold Force Recovery → press/release Power → release Force Recovery; use USB-C port next to 40-pin header
- SDK Manager's Pre-Config mode enables fully headless setup (username, hostname, locale specified upfront) — ideal for reproducible bringup
- Post-flash SDK install (CUDA, cuDNN, TensorRT) requires Jetson network connectivity and is a separate step from the base BSP flash
- The existing `mower-jetson info` code already reads `/etc/nv_tegra_release` which matches the L4T release string format
- System Python on JetPack 6.2.1 is Python 3.10 (Ubuntu 22.04 default)

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/jetson.py` | Existing `_read_jetpack_release()` reads `/etc/nv_tegra_release`; confirms verification approach is aligned |
| `src/mower_rover/config/laptop.py` | `JetsonEndpoint` dataclass defines SSH coordinates; hostname should match Pre-Config choice |
| `src/mower_rover/config/jetson.py` | Jetson-side config with XDG path defaults for aarch64 Linux |
| `docs/research/001-mvp-bringup-rtk-mowing.md` | Prior research Phase 2 Part C describes Jetson detection via SSH |

**Gaps:**
- Exact button physical layout diagram for AGX Orin dev kit (text procedure documented above)
- Whether current factory firmware ships with JetPack 5.x or 6.x (clean flash recommended regardless)
- NVMe SSD model recommendation for vibration/thermal on a mower (any standard M.2 2280 should work)

**Assumptions:**
- AGX Orin dev kit is standard P3701-0000 or P3701-0005 module on P3737-0000 carrier board
- Windows 10/11 laptop with WSL2 support available
- NVMe M.2 SSD available or will be procured

## Phase 2: Networking & SSH configuration

**Status:** ✅ Complete
**Session:** 2026-04-22

### 1. AGX Orin Dev Kit Ethernet Ports

The Jetson AGX Orin dev kit (P3737-0000 carrier board) exposes **one 10GbE RJ-45 Ethernet port**. JetPack 6.2.1 (Ubuntu 22.04) enumerates this as `eth0` (or `enpXsY` under predictable naming — JetPack 6.x typically uses `eth0` for the built-in NIC). A standard straight-through Ethernet cable works (auto MDI-X on both sides).

### 2. Static IP vs mDNS — Recommendation

**Recommendation: Static IP as primary, mDNS as convenience fallback.**

| Approach | Pros | Cons |
|----------|------|------|
| **Static IP** (`192.168.4.38` / `192.168.4.1`) | Zero external dependency; deterministic; aligns with existing codebase examples; instant on cable plug-in | Requires manual config on both sides |
| **mDNS** (`jetson-mower.local`) | Human-readable hostname; adapts to DHCP | Multicast dependency; Windows mDNS can be flaky on direct links; not strongest field-offline |

Use `192.168.4.38` for the Jetson and `192.168.4.1` for the laptop as canonical bench addressing. Avahi broadcasts `jetson-mower.local` automatically when avahi-daemon is running.

### 3. Jetson-Side Netplan Configuration

```yaml
# /etc/netplan/50-mower-bench.yaml
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      addresses:
        - 192.168.4.38/24
      # No gateway — direct point-to-point link
      # No DNS — field-offline
      nameservers:
        addresses: []
```

```bash
sudo netplan apply
```

**Alternative (nmcli):**
```bash
sudo nmcli con add type ethernet con-name mower-bench ifname eth0 \
  ipv4.addresses 192.168.4.38/24 ipv4.method manual
sudo nmcli con up mower-bench
```

### 4. Windows Laptop Static IP

```powershell
# Identify adapter
Get-NetAdapter | Where-Object { $_.MediaType -eq '802.3' }

# Set static IP (replace "Ethernet" with actual adapter name)
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.4.1 -PrefixLength 24
Set-NetIPInterface -InterfaceAlias "Ethernet" -Dhcp Disabled
```

### 5. Hostname Configuration

- Hostname `jetson-mower` set during Pre-Config (Phase 1)
- Avahi advertises `jetson-mower.local` automatically
- `laptop.yaml` should use the static IP (`192.168.4.38`) for reliability, not hostname
- Optional: add `192.168.4.38 jetson-mower` to Windows `hosts` file

### 6. SSH Key Generation and Deployment

**Generate Ed25519 key on Windows:**
```powershell
ssh-keygen -t ed25519 -C "mower-rover-laptop" -f "$env:USERPROFILE\.ssh\mower_id_ed25519"
```

**Deploy to Jetson (one-time, before disabling password auth):**
```powershell
type "$env:USERPROFILE\.ssh\mower_id_ed25519.pub" | ssh mower@192.168.4.38 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**Verify key auth:**
```powershell
ssh -i "$env:USERPROFILE\.ssh\mower_id_ed25519" -o BatchMode=yes mower@192.168.4.38 "echo ok"
```

### 7. SSH Hardening on the Jetson

Use a drop-in config file (survives `apt upgrade`):

```bash
# /etc/ssh/sshd_config.d/90-mower-hardening.conf
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers mower
X11Forwarding no
AllowTcpForwarding no
ClientAliveInterval 60
ClientAliveCountMax 5
AcceptEnv MOWER_CORRELATION_ID
```

```bash
sudo systemctl restart sshd
```

### 8. Alignment with Existing Transport Layer

The project's `JetsonClient._common_opts()` already sets:
- `BatchMode=yes` — never prompt for password
- `PasswordAuthentication=no` — explicit key-only
- `StrictHostKeyChecking=accept-new` — TOFU model
- `ConnectTimeout=10` — fail fast

**No code changes needed.** The bench config maps directly to `laptop.yaml`:
```yaml
jetson:
  host: 192.168.4.38
  user: mower
  port: 22
  key_path: ~/.ssh/mower_id_ed25519
```

`_resolve_endpoint()` priority (flags > env vars > YAML) naturally supports bench-to-field transitions.

### 9. Windows OpenSSH Specifics

- Windows 10/11 ships OpenSSH 8.x–9.x; Ed25519 fully supported
- `~/.ssh` resolves to `%USERPROFILE%\.ssh`; `Path.expanduser()` handles this
- Windows OpenSSH has **relaxed** file permission checks (no `chmod 600` needed)
- `ssh-copy-id` not available on Windows; use the `type ... | ssh` method above
- `ssh-agent` available as Windows service (`OpenSSH Authentication Agent`)
- Windows `known_hosts` at `%USERPROFILE%\.ssh\known_hosts`

### 10. Correlation ID Propagation

`AcceptEnv MOWER_CORRELATION_ID` in the Jetson SSH config prepares for future correlation ID propagation. The transport code sets `MOWER_CORRELATION_ID` locally but does not yet pass `-o SendEnv=MOWER_CORRELATION_ID` — acknowledged as a future enhancement.

### 11. Field Networking

- Same `192.168.4.38/24` ↔ `192.168.4.1/24` config works in bench and field with no changes
- USB-C Ethernet gadget (`l4tbr0` at `192.168.55.1`) is not recommended as primary link (USB-C port needed for OAK-D Pro, lower bandwidth)
- Host key regenerates on re-flash — operator must `ssh-keygen -R 192.168.4.38` after any re-flash

### 12. Complete Bench Bringup Networking Procedure

1. Generate SSH key on Windows (`ssh-keygen -t ed25519`)
2. Connect Ethernet cable (laptop ↔ Jetson RJ-45)
3. Configure Windows static IP (`192.168.4.1/24`)
4. Configure Jetson static IP via netplan (`192.168.4.38/24`)
5. Verify connectivity (`ping 192.168.4.38`)
6. Deploy SSH public key to Jetson
7. Verify key auth (`ssh -o BatchMode=yes`)
8. Deploy SSH hardening drop-in config
9. Verify hardening (password rejected, key works)
10. Configure `laptop.yaml` with endpoint details
11. Verify `mower jetson info` works over the link

**Key Discoveries:**
- Static IP (`192.168.4.38`/`192.168.4.1`) is correct primary addressing — aligns with codebase
- Existing SSH transport layer is perfectly aligned with key-only auth setup
- Ed25519 keys recommended; Windows OpenSSH fully interoperable
- SSH hardening via drop-in config (`sshd_config.d/`) survives apt upgrades
- `AcceptEnv MOWER_CORRELATION_ID` prepares for future correlation ID propagation
- Windows mDNS resolver built-in but flaky on direct links — static IP preferred
- `ssh-copy-id` unavailable on Windows; `type ... | ssh` is the equivalent

| File | Relevance |
|------|-----------|
| `src/mower_rover/transport/ssh.py` | SSH transport with `BatchMode=yes`, `PasswordAuthentication=no`, `StrictHostKeyChecking=accept-new` |
| `src/mower_rover/config/laptop.py` | `JetsonEndpoint` dataclass; `Path.expanduser()` handles `~` on Windows |
| `src/mower_rover/cli/jetson_remote.py` | `_resolve_endpoint()` priority chain (flags > env > YAML) |
| `tests/test_transport_ssh.py` | Verifies SSH options in argv |

**Gaps:**
- Exact Ethernet interface name on AGX Orin JetPack 6.2.1 (`eth0` vs predictable naming) needs field verification
- Whether JetPack 6.2.1 USB-C device mode (`l4tbr0`) is enabled by default — may be useful as bootstrap path
- Optimal `ClientAliveInterval`/`ClientAliveCountMax` for field conditions (vibration) may need tuning

**Assumptions:**
- AGX Orin dev kit has standard RJ-45 GbE port on P3737-0000 carrier board
- `192.168.4.0/24` subnet not in use elsewhere on operator's network
- Ed25519 supported by operator's Windows OpenSSH version (8.x+)

## Phase 3: Python toolchain & project install

**Status:** ✅ Complete
**Session:** 2026-04-22

### Critical Discovery: Python Version Mismatch

The project's `pyproject.toml` declares `requires-python = ">=3.11"`, and ruff/mypy target Python 3.11. However, JetPack 6.2.1 (Ubuntu 22.04) ships **Python 3.10.12** as the system interpreter. Direct `pip install` or `pipx install` using the system Python will **fail immediately** with a version compatibility error.

### Solution: uv-Managed Python 3.11

`uv` can install and manage its own Python interpreters from `python-build-standalone`. This is the cleanest path:
- Doesn't touch the system Python or apt-managed packages
- Works offline after initial download (field-offline constraint)
- Provides consistent tooling with the laptop side
- `uv` has **Tier 2 support** for `aarch64-unknown-linux-gnu` with prebuilt binaries

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

# Install Python 3.11
uv python install 3.11

# Verify
uv python list --only-installed
# cpython-3.11.x-linux-aarch64-gnu
```

uv stores managed Python in `~/.local/share/uv/python/` and adds `python3.11` to `~/.local/bin/`.

### uv on aarch64 Linux

- **Platform tier:** Tier 2 — prebuilt binaries published on every release
- **Binary:** `uv-aarch64-unknown-linux-gnu.tar.gz` (glibc 2.28+ required; Ubuntu 22.04 has glibc 2.35)
- **Install:** Standalone installer script (`curl ... | sh`) to `~/.local/bin/`

### pipx vs `uv tool install`

**Recommended: `uv tool install`** (replaces `pipx`):
```bash
uv tool install --python 3.11 ~/mower-rover/
```

This creates an isolated venv (in `~/.local/share/uv/tools/`), installs deps, and symlinks entry points to `~/.local/bin/`. Functionally identical to `pipx install` but eliminates a separate tool dependency.

**Alternative (strict compliance with copilot-instructions):**
```bash
sudo apt install pipx
pipx install --python "$(uv python find 3.11)" ~/mower-rover/
```

### venv Strategy: Full Isolation

The `mower-jetson` CLI has **no CUDA Python deps**. JetPack's system site-packages contain NVIDIA-specific packages (tensorrt, jetson-stats, etc.), but none are needed by the CLI. Full venv isolation (no `--system-site-packages`) is correct:
- Clean dependency resolution — no conflicts with NVIDIA's pinned packages
- Reproducible environment — identical deps on Jetson and laptop
- No risk of apt updates breaking the venv

### Dependency Compatibility on aarch64 / Python 3.11

| Dependency | Type | aarch64 Wheel | Notes |
|---|---|---|---|
| `typer>=0.12` | Pure Python | N/A | No platform issues |
| `rich>=13.7` | Pure Python | N/A | No platform issues |
| `structlog>=24.1` | Pure Python | N/A | No platform issues |
| `pymavlink>=2.4.40` | Source + wheels | ⚠️ Source dist | Needs `lxml`; requires `libxml2-dev`, `libxslt-dev` apt packages as insurance |
| `pyubx2>=1.2.45` | Pure Python | N/A | No platform issues |
| `shapely>=2.0` | C extension | ✅ `manylinux_2_17_aarch64` | Bundles GEOS in wheel |
| `pyproj>=3.6` | C extension | ✅ `manylinux_2_17_aarch64` | Bundles PROJ in wheel |
| `pyyaml>=6.0` | C extension (optional) | ✅ `manylinux_2_17_aarch64` | Falls back to pure Python if C ext unavailable |

**numpy (transitive via pymavlink):** numpy 2.4.x publishes `cp311-manylinux_2_28_aarch64` wheels. **No cp310 wheel exists** — another reason Python 3.11+ is required.

### pymavlink Build Dependencies

```bash
sudo apt install -y libxml2-dev libxslt-dev python3-dev
```

Needed by `lxml` (pymavlink's hard dependency). In practice, `lxml` publishes aarch64 manylinux wheels, so build deps may not be needed — but installing them is cheap insurance.

### JetPack-Specific Python Gotchas

1. **PEP 668 `EXTERNALLY-MANAGED` marker:** Ubuntu 22.04's system Python 3.10 may block `pip install` outside a venv. The uv-managed Python + isolated venv approach sidesteps this entirely.

2. **apt-held packages:** JetPack pins certain Python packages via apt (e.g., `python3-numpy` at CUDA-compatible version). Never modify these in system Python. Our isolated venv avoids this.

3. **CUDA Python path:** JetPack adds `/usr/lib/python3/dist-packages` for NVIDIA packages. A uv-managed Python 3.11 venv does **not** inherit these paths (by design).

4. **`/usr/bin/python3` symlink:** Points to Python 3.10. Do not modify. The uv-managed Python 3.11 lives in `~/.local/share/uv/python/`.

### Complete Installation Procedure

```bash
# === Prerequisites (requires internet — bench setup) ===

# 1. Build deps for pymavlink/lxml
sudo apt update
sudo apt install -y curl git libxml2-dev libxslt-dev

# 2. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

# 3. Install Python 3.11
uv python install 3.11
python3.11 --version  # Verify: 3.11.x

# === Project Installation ===

# 4. Get the project onto the Jetson
git clone <repo-url> ~/mower-rover
# Or: scp -r from laptop

# 5. Install mower-jetson CLI
uv tool install --python 3.11 ~/mower-rover/

# 6. Verify
mower-jetson --help
mower-jetson info
mower-jetson config show

# === Updates ===

# After code changes:
cd ~/mower-rover && git pull
uv tool install --python 3.11 ~/mower-rover/ --reinstall
```

### Entry Points

Both CLIs are exposed on install:
```toml
mower = "mower_rover.cli.laptop:app"        # Laptop-side
mower-jetson = "mower_rover.cli.jetson:app"  # Jetson-side
```

The `mower` command is also available on the Jetson but is primarily intended for the laptop. Both CLIs detect their platform context.

**Key Discoveries:**
- **CRITICAL:** Python 3.10 (JetPack) vs 3.11+ (project requirement) mismatch — `uv python install 3.11` is the solution
- `uv` has Tier 2 aarch64 support with prebuilt binaries; Ubuntu 22.04 glibc is compatible
- `uv tool install` replaces `pipx` — same isolation, no extra dependency
- Full venv isolation is correct (no `--system-site-packages` needed)
- All project deps have aarch64 wheels for Python 3.11+
- numpy dropped cp310 wheels, reinforcing the 3.11+ requirement
- Only build-time apt deps: `libxml2-dev libxslt-dev` for lxml (pymavlink)

| File | Relevance |
|------|-----------|
| `pyproject.toml` | `requires-python = ">=3.11"`, all deps, entry points, hatchling build |
| `src/mower_rover/cli/jetson.py` | `mower-jetson` CLI entry point |
| `src/mower_rover/config/jetson.py` | Jetson-side config (XDG paths for Linux) |

**Gaps:** None identified.

**Assumptions:**
- JetPack 6.2.1 ships Python 3.10.12 (standard for Ubuntu 22.04 Jammy)
- `python-build-standalone` CPython 3.11 available for aarch64 (well-established)
- pymavlink's lxml dep installs from pre-built wheel or builds from source with apt deps

## Phase 4: OAK-D Pro & DepthAI on JetPack

**Status:** ✅ Complete
**Session:** 2026-04-22

### 1. USB Port Selection on AGX Orin Dev Kit

The AGX Orin developer kit (P3737-0000 carrier board) has multiple USB ports:

| Port | Type | Speed | Location | Notes |
|------|------|-------|----------|-------|
| USB-C (flashing) | Type-C | USB 3.2 Gen2 (10 Gbps) | Next to 40-pin header | Used for flashing; also usable for OAK-D Pro |
| USB-A × 4 | Type-A | USB 3.2 Gen2 (10 Gbps) | Rear I/O panel | Standard host ports |
| USB-C (device mode) | Type-C | USB 2.0 | Near power jack | l4tbr0 device mode; NOT suitable for OAK-D Pro |

**Recommendation: Use a rear USB-A port** with a USB-C to USB-A adapter/cable for the OAK-D Pro. This keeps the USB-C flashing port free for future re-flashing or debugging. The rear USB-A ports provide full USB 3.2 Gen2 bandwidth (10 Gbps), which far exceeds the OAK-D Pro's requirements (~400 Mbps for stereo depth + color at full resolution).

**Do NOT use the USB-C device-mode port** (near power jack) — it is USB 2.0 and intended for host-to-Jetson connectivity, not device connections.

The OAK-D Pro ships with a USB-C to USB-C cable and a USB-C to USB-A cable. Use the USB-C to USB-A cable for the AGX Orin's rear ports.

### 2. DepthAI SDK Version and Installation

**Current version: DepthAI 3.5.0** (released March 2026). DepthAI v3 is the current API, supporting both OAK (RVC2, which includes OAK-D Pro) and OAK4 (RVC4) cameras. DepthAI v2 is legacy.

DepthAI is installable via `pip install depthai`. Luxonis provides **prebuilt wheels** on PyPI and their artifact repository. The OAK-D Pro uses the Myriad X VPU (RVC2 platform), which is fully supported by DepthAI v3.

**Installation on the Jetson (using the uv-managed Python 3.11 from Phase 3):**

```bash
# Option A: Install into a separate venv (recommended for isolation)
uv venv --python 3.11 ~/depthai-venv
source ~/depthai-venv/bin/activate
pip install depthai

# Option B: Install as additional dependency in the mower-jetson tool venv
# This requires adding depthai to pyproject.toml or installing it into the
# tool's venv directly (not recommended — see dependency strategy below)
```

**Luxonis also provides a dependency installer script:**
```bash
sudo wget -qO- https://docs.luxonis.com/install_dependencies.sh | bash
```
This installs system-level dependencies (libusb, libudev, cmake, etc.) and sets up udev rules. Running this script is recommended as a first step even if you install `depthai` via pip separately.

### 3. DepthAI on aarch64 / JetPack Compatibility

**Tested platforms (from Luxonis docs):** Ubuntu 18.04, 20.04, 22.04 are listed. Jetson deployment is documented for Nano and Xavier, but the underlying library works on any Linux aarch64 with USB support — AGX Orin is supported.

**Key compatibility notes:**
- DepthAI's Python bindings are compiled C++ extensions. PyPI publishes `manylinux` wheels for `aarch64` for common Python versions
- If no prebuilt wheel is available for the exact Python version, DepthAI can be built from source (requires `cmake`, `g++`, `libusb-1.0-0-dev`)
- The `OPENBLAS_CORETYPE=ARMV8` environment variable should be set in `.bashrc` to prevent OpenCV/numpy illegal instruction errors on ARM:
  ```bash
  echo "export OPENBLAS_CORETYPE=ARMV8" >> ~/.bashrc
  source ~/.bashrc
  ```

### 4. CUDA Usage by DepthAI

The OAK-D Pro runs neural inference and depth computation **entirely on the onboard Myriad X VPU**. DepthAI does NOT use the Jetson's CUDA for OAK-D Pro operations. The Myriad X is a standalone vision processing unit with its own compute pipeline.

The Jetson's GPU/CUDA is available for **host-side post-processing** (e.g., VSLAM, additional neural inference, point cloud processing) but is not used by the DepthAI SDK itself when communicating with RVC2-based cameras like the OAK-D Pro.

This means:
- No CUDA version dependency for DepthAI
- No JetPack CUDA conflicts
- The isolated venv approach (no system site-packages) works perfectly

### 5. udev Rules for Non-Root USB Access

The OAK-D Pro requires udev rules to allow non-root users to access the USB device. The Luxonis dependency installer script sets these up, but they can also be configured manually:

```bash
# Create udev rules for Luxonis/Movidius devices
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

The vendor ID `03e7` is Intel's Movidius division (used by all OAK cameras). The `MODE="0666"` allows any user to read/write the device.

**Important:** After creating the udev rule, **unplug and re-plug** the OAK-D Pro (or reboot) for the rule to take effect.

### 6. Camera Enumeration and Smoke Test

**Quick enumeration check:**
```bash
# List USB devices — should show Luxonis or Movidius device
lsusb | grep -i -E "movidius|luxonis|03e7"
# Expected: Bus XXX Device YYY: ID 03e7:2485 Intel Corp. Movidius MyriadX
```

**Python smoke test:**
```python
#!/usr/bin/env python3
"""OAK-D Pro enumeration smoke test."""
import depthai as dai

# List all connected OAK devices
devices = dai.Device.getAllAvailableDevices()
print(f"Found {len(devices)} OAK device(s):")
for d in devices:
    print(f"  - {d.getMxId()} state={d.state.name} protocol={d.protocol.name}")

if not devices:
    print("ERROR: No OAK devices found. Check USB connection and udev rules.")
    raise SystemExit(1)

# Open the first device and print info
with dai.Device() as device:
    print(f"\nDevice name: {device.getDeviceName()}")
    print(f"USB speed: {device.getUsbSpeed().name}")
    print(f"Connected cameras: {device.getConnectedCameraFeatures()}")
    print(f"IMU type: {device.getConnectedIMU()}")
    calib = device.readCalibration()
    print(f"Calibration valid: {calib is not None}")
    print("\nOAK-D Pro enumeration: PASS")
```

**Expected output for OAK-D Pro:**
- USB speed: `SUPER` (USB 3.x) or `SUPER_PLUS` (USB 3.2)
- Connected cameras: left mono (OV9282), right mono (OV9282), color (IMX378)
- Connected IMU: `BNO085` or `BNO086` (6-axis IMU on OAK-D Pro)
- Calibration data present from factory

**OAK Viewer (GUI tool):**
Luxonis provides `depthai-viewer` for a GUI-based camera preview. On the headless Jetson, this is less useful, but it can be run over SSH X11 forwarding for initial verification:
```bash
pip install depthai-viewer
depthai-viewer
```

### 7. Dependency Strategy: Separate from mower-jetson

**Recommendation: Keep DepthAI separate from `pyproject.toml` for now.**

Rationale:
- DepthAI is NOT needed by the `mower-jetson` CLI (which handles MAVLink, params, SSH transport)
- DepthAI is a Jetson-only dependency (not needed on the Windows laptop)
- DepthAI is a heavy package (~100 MB wheel with bundled libraries)
- The VSLAM/depth stack is a future phase (not MVP)
- Adding it to `pyproject.toml` would force installation on the laptop side (or require complex platform-conditional deps)

**When DepthAI IS needed:** When the project reaches the VSLAM/depth integration phase, create a separate optional dependency group:
```toml
[project.optional-dependencies]
depth = ["depthai>=3.5"]
```

Or create a separate Jetson-side package/venv for the depth pipeline. The `oakd_required` config flag in `JetsonConfig` already supports this split — when `oakd_required: true`, the Jetson probes will require OAK-D Pro presence.

### 8. Known Issues and Gotchas

1. **USB boot enumeration:** OAK devices go through a USB boot sequence when first connected. The device appears as `Movidius MyriadX` (USB2, boot mode), then re-enumerates as `Luxonis Device` (USB3, operational mode). Both device IDs use vendor `03e7`. The udev rule covers both.

2. **USB power delivery:** The OAK-D Pro draws ~1.5–2.5W over USB. The AGX Orin's USB-A ports can supply sufficient power. If stability issues occur (especially with multiple USB devices), use a powered USB hub or the Luxonis Y-adapter.

3. **OPENBLAS_CORETYPE:** Must be set to `ARMV8` on aarch64 to prevent illegal instruction errors from OpenBLAS (used by numpy/OpenCV). Add to `.bashrc` or the venv activation script.

4. **DepthAI v2 vs v3:** The Luxonis Jetson deployment docs still reference the v2 workflow. DepthAI v3 (3.5.0) is the current API and supports OAK-D Pro (RVC2). Install via `pip install depthai` (which now installs v3).

5. **Swap space on AGX Orin:** The Luxonis Jetson docs recommend increasing swap space. The AGX Orin dev kit has 32/64 GB RAM, so swap is less critical than on Nano/Xavier. However, if building DepthAI from source, additional swap may help. Disable ZRAM and create a swap file if needed.

6. **IR projector/flood light:** The OAK-D Pro's IR dot projector and flood illuminator can be controlled via the DepthAI API (`device.setIrLaserDotProjectorBrightness()`, `device.setIrFloodLightBrightness()`). These are useful for outdoor mowing in low-light conditions but should be used judiciously to avoid interfering with other sensors.

**Key Discoveries:**
- Use a rear USB-A port (USB 3.2 Gen2) on the AGX Orin for the OAK-D Pro; avoid the USB-C device-mode port (USB 2.0)
- DepthAI 3.5.0 (v3 API) is current; installed via `pip install depthai`; prebuilt wheels available
- OAK-D Pro runs entirely on Myriad X VPU — no Jetson CUDA dependency for DepthAI
- udev rule: `SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"` for non-root access
- Set `OPENBLAS_CORETYPE=ARMV8` in `.bashrc` to prevent illegal instruction errors on aarch64
- DepthAI should be kept separate from `pyproject.toml` for now — it's a future VSLAM phase dependency
- The `oakd_required` config flag in `JetsonConfig` already supports conditional OAK-D Pro probing
- OAK-D Pro power draw (~2.5W) is within AGX Orin USB-A port supply capability

| File | Relevance |
|------|-----------|
| `src/mower_rover/config/jetson.py` | `oakd_required: bool` field — controls whether OAK-D Pro is required during hardware probes |
| `tests/test_cli_jetson_smoke.py` | Tests `oakd_required` config parsing |
| `docs/vision/001-zero-turn-mower-rover.md` | C-4: "Depth camera is Luxonis OAK-D Pro (USB), with onboard depth and IMU via the DepthAI SDK" |

**Gaps:**
- Exact DepthAI Python wheel availability for `cp311-manylinux_aarch64` not confirmed on PyPI — may need to build from source or use Luxonis artifact repo
- DepthAI v3 behavior differences from v2 on RVC2 devices (OAK-D Pro) need field validation
- IR projector/flood light optimal settings for outdoor daylight mowing — requires field testing

**Assumptions:**
- AGX Orin dev kit has standard USB-A 3.2 Gen2 ports on rear panel
- DepthAI 3.5.0 supports Python 3.11 on aarch64 (likely given the broad platform support)
- OAK-D Pro ships with USB-C to USB-A cable included

## Phase 5: Power, thermal & field-readiness

**Status:** ✅ Complete
**Session:** 2026-04-22

### 1. Power Modes (nvpmodel)

The AGX Orin supports multiple power modes. Key modes for 32GB module:

| Mode ID | Name | Power Budget | Online CPUs | CPU Max (MHz) | GPU TPC | Memory Max (MHz) |
|---------|------|-------------|-------------|---------------|---------|-----------------|
| 0 | MAXN | Unconstrained | 8 | 2188.8 | 7 | 3200 |
| 1 | 15W | 15W | 4 | 1113.6 | 3 | 2133 |
| 2 | **30W** (default) | 30W | 8 | 1728 | 4 | 3200 |
| 3 | 40W | 40W | 8 | 1497.6 | 7 | 3200 |

**CRITICAL: MAXN is NOT the "max performance" mode.** It's an unconstrained experimental mode that triggers hardware throttling when TDP is exceeded.

**Recommendation: Mode 2 (30W, the default).** Provides 8 CPUs at 1728 MHz, 4 GPU TPCs, full memory bandwidth. Adequate for DepthAI + VSLAM + mower-jetson CLI. Stays within 12V mower power budget. Generates less heat than higher modes.

```bash
sudo nvpmodel -q       # Check current mode
sudo nvpmodel -m 2     # Set 30W (persists across reboots)
```

### 2. jetson_clocks

`jetson_clocks` locks CPU/GPU/EMC to maximum frequencies within the current power mode. **Do NOT enable by default.** Dynamic frequency scaling (`schedutil` governor) saves power during idle and responds within milliseconds when load increases.

If consistent performance is needed during active mowing:
```bash
sudo jetson_clocks --store   # Save current settings
sudo jetson_clocks            # Lock to max
# After mowing:
sudo jetson_clocks --restore  # Restore dynamic scaling
```

### 3. Thermal Management on the Mower

**Thermal limits:** SW throttling at 99°C, HW throttling at 103°C, HW shutdown at 105°C (die temperature). Dev kit ambient operating range: **5°C to 35°C** (standard variant).

**Fan profile:** "cool" (default for AGX Orin) — prioritizes cooling over noise. Fan noise is irrelevant on a mower.

**Mower-specific concerns:**
1. **Engine radiant heat:** Mount Jetson as far from engine as practical; use a heat shield
2. **Direct sunlight:** Sun shade or hood over the enclosure (solar radiation adds 20-30°C to surface temps)
3. **Enclosure ventilation:** Weatherproof enclosure MUST have ventilation for the fan — IP65-rated fan filters, intake/exhaust vents on opposite sides
4. **Summer ambient:** Can push to 35-45°C, at or above the dev kit's 35°C limit — thermal headroom is tight
5. **Vibration:** Verify heatsink/fan retention after initial mowing runs; use thread-locking compound

**Thermal monitoring:**
```bash
sudo tegrastats --interval 1000   # Live CPU@XX.XC GPU@XX.XC
cat /sys/class/thermal/thermal_zone*/temp  # Raw readings (millidegrees)
```

### 4. Headless Operation

Disable GUI desktop to save ~500 MB RAM and 2-5W:
```bash
sudo systemctl set-default multi-user.target
sudo systemctl disable gdm3
sudo reboot
```

**Disable unnecessary services:**
```bash
sudo systemctl disable cups cups-browsed    # Printing
sudo systemctl disable bluetooth            # No Bluetooth needed
sudo systemctl disable ModemManager         # No cellular
sudo systemctl disable whoopsie             # Error reporting (needs internet)
sudo systemctl disable unattended-upgrades  # Field-offline
```

**Keep enabled:** sshd, NetworkManager, nvfancontrol, nvpmodel, systemd-journald, avahi-daemon.

### 5. Watchdog / Auto-Recovery

| Failure Mode | Detection | Recovery |
|-------------|-----------|----------|
| Process crash | systemd `Restart=on-failure` | Auto-restart in 5s |
| Process hang | systemd `WatchdogSec=30` | Kill + restart |
| OS hang / kernel panic | Hardware watchdog (`RuntimeWatchdogSec`) | Hardware reboot |
| Power loss (E-stop) | None (power cut) | Boot on power restore (UEFI auto-power-on) |
| Thermal shutdown | BPMP thermal framework | Auto-reboot after cooldown |

**systemd service config (for future `mower-jetson service run`):**
```ini
[Service]
Type=notify
WatchdogSec=30
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=5
```

**System-level hardware watchdog:**
```bash
# /etc/systemd/system.conf
RuntimeWatchdogSec=30
```

**UEFI auto-power-on** must be enabled so Jetson boots when power is restored after E-stop.

### 6. Filesystem Considerations

**Filesystem: ext4** (recommended over f2fs) — more mature, excellent power-loss recovery, better tooling.

**Mount options:**
```
/dev/nvme0n1p1  /  ext4  defaults,noatime,commit=60  0  1
```
- `noatime`: Reduce writes
- `commit=60`: Journal commit interval (acceptable log data loss for fewer writes)

**Log rotation:**
```
# /etc/logrotate.d/mower-jetson
/home/mower/.local/share/mower-rover/logs/*.jsonl {
    daily
    rotate 14
    compress
    maxsize 50M
    copytruncate
}
```

**Journal limits:**
```ini
# /etc/systemd/journald.conf.d/mower.conf
[Journal]
SystemMaxUse=500M
MaxRetentionSec=7day
```

**Read-only rootfs: NOT recommended for MVP.** Adds excessive complexity; ext4 journaling provides sufficient power-loss protection.

**NVMe write endurance:** ~150 TBW for consumer SSDs vs ~730 GB/year worst case writes = 200+ year lifespan. Not a concern.

### 7. Power Supply Considerations

**AGX Orin dev kit input: 9–20V DC** (barrel jack, ships with 65W 19V adapter).

**DC-DC converter requirements:**

| Parameter | Requirement |
|-----------|------------|
| Input range | 9–32V DC (wide input, automotive) |
| Output | 19V DC |
| Output power | ≥75W (100W recommended) |
| Type | Boost or boost-buck (12V battery → 19V output) |
| Protection | OVP, OCP, reverse polarity, short circuit |
| Operating temp | -20°C to +70°C |

**Battery voltage range:** 12.0V (resting) → 14.4V (charging) → 9V (cranking dip). Converter must ride through cranking.

**E-stop power loss:** Causes ungraceful shutdown. ext4 journaling + NVMe internal capacitors make this acceptable for MVP. Post-MVP: supercapacitor UPS (10-30s hold-up) for graceful shutdown via GPIO signal.

```python
# Periodic sync in mower-jetson service loop
import os
os.sync()  # Flush all buffers to disk
```

**Key Discoveries:**
- 30W mode (default) is correct for the mower — adequate performance, within 12V power budget, less heat
- MAXN is NOT max performance — it's unconstrained and triggers hardware throttling
- `jetson_clocks` should be off by default; enable only during active mowing if needed
- Thermal limit: 35°C ambient for standard dev kit — tight for summer outdoor use
- Headless operation saves ~500 MB RAM and 2-5W
- Hardware watchdog + systemd watchdog provide layered auto-recovery
- ext4 with `noatime,commit=60` is the correct filesystem choice
- E-stop power loss is acceptable for MVP with ext4 journaling; supercapacitor UPS is post-MVP
- DC-DC converter must be automotive-grade boost type: 9-32V → 19V, ≥75W
- UEFI auto-power-on is essential for E-stop recovery

| File | Relevance |
|------|-----------|
| `src/mower_rover/config/jetson.py` | `log_dir` field relevant to log rotation path |
| `src/mower_rover/cli/jetson.py` | Future `thermal`, `power`, `service run` commands |
| `.github/copilot-instructions.md` | Hardware stack, E-stop authority, 12V system |

**Gaps:**
- Exact barrel jack spec (inner/outer diameter, polarity) for DC-DC connector selection
- UEFI auto-power-on configuration method (serial console vs nvbootctrl)
- Dev kit fan rating for outdoor conditions (dust/moisture) — may need IP-rated replacement
- Specific DC-DC converter part number recommendation
- Battery hold-up time after engine kill — needs field measurement
- Whether AGX Orin Industrial variant (-25°C to +80°C ambient) is worth the cost for summer outdoor use

**Assumptions:**
- Standard dev kit (not Industrial) — 5-35°C ambient, which is marginal for summer outdoor
- Mower's 15A alternator can supply sustained 75-100W for Jetson + DC-DC
- E-stop wiring cuts DC-DC converter input or output
- ext4 journaling is sufficient for power-loss protection at MVP

## Overview

This research documents a complete, repeatable bringup procedure for the NVIDIA Jetson AGX Orin developer kit as the mower rover's companion computer. The procedure is designed for a single operator working at a bench with a Windows laptop, producing a field-ready headless Jetson with SSH access, Python tooling, and OAK-D Pro camera support.

### Key Findings Summary

1. **JetPack 6.2.1** (L4T 36.4.4, Ubuntu 22.04, CUDA 12.6.10) is the correct and only viable version for AGX Orin. JetPack 7 is Jetson Thor only. SDK Manager 2.4.0 supports **flashing directly from Windows** via WSL2.

2. **Python version mismatch is the most critical bringup issue.** JetPack ships Python 3.10; the project requires ≥3.11. Solution: `uv python install 3.11` provides a managed interpreter independent of the system Python. `uv tool install` replaces `pipx` for CLI installation.

3. **Static IP (192.168.4.38/192.168.4.1) with key-only SSH** is the correct networking baseline — field-offline, deterministic, and already aligned with the existing transport layer code. No code changes needed.

4. **OAK-D Pro runs entirely on its Myriad X VPU** — no Jetson CUDA dependency for DepthAI. Install via `pip install depthai` in a separate venv. Keep DepthAI out of `pyproject.toml` until the VSLAM phase.

5. **30W power mode (default) is correct** for the mower — adequate performance for the workload, within 12V power budget, and generates less heat than higher modes. MAXN is an experimental mode, not a performance mode.

6. **Headless operation** (disable gdm3/GNOME) saves ~500 MB RAM and 2-5W. Combined with systemd + hardware watchdog, the Jetson auto-recovers from process crashes, hangs, and even OS-level hangs.

7. **E-stop power loss is the primary field reliability concern.** ext4 journaling + NVMe internal capacitors provide adequate protection for MVP. A supercapacitor UPS (10-30s hold-up) is the post-MVP solution for graceful shutdown.

### Complete Bringup Sequence

1. Flash JetPack 6.2.1 via SDK Manager on Windows (Pre-Config: user `mower`, hostname `jetson-mower`, NVMe storage)
2. Connect direct Ethernet; configure static IPs (Jetson 192.168.4.38, laptop 192.168.4.1)
3. Deploy Ed25519 SSH key; harden SSH via drop-in config (`sshd_config.d/90-mower-hardening.conf`)
4. Install uv; install Python 3.11 via `uv python install 3.11`
5. Clone project; install via `uv tool install --python 3.11 ~/mower-rover/`
6. Verify `mower-jetson info` works over SSH from the laptop
7. Install DepthAI dependencies and udev rules; plug OAK-D Pro into rear USB-A port
8. Disable GUI desktop; disable unnecessary services; set `multi-user.target`
9. Enable hardware watchdog (`RuntimeWatchdogSec=30`); configure UEFI auto-power-on
10. Configure log rotation; set ext4 mount options (`noatime,commit=60`)

### Cross-Cutting Patterns

- **Field-offline throughout:** Every step works without internet after the initial bench setup (flashing + pip downloads). uv, Python 3.11, and all wheels are cached locally.
- **Existing code alignment:** The SSH transport layer, endpoint config, and Jetson detection code are already compatible with this bringup procedure — no source changes needed.
- **Security-first:** Key-only SSH, disabled password auth, `AllowUsers mower`, no root login, no X11 forwarding.
- **Layered recovery:** Process crash → systemd restart → process hang → watchdog kill → OS hang → hardware watchdog reboot → power loss → UEFI auto-power-on.

### Actionable Conclusions

- The bringup procedure is ready to execute at the bench once the hardware is in hand
- The Python 3.10/3.11 mismatch must be addressed via `uv python install 3.11` — this is non-negotiable
- Consider updating copilot-instructions to recommend `uv tool install` over `pipx`
- An automotive DC-DC converter (9-32V → 19V, ≥75W) must be procured for field deployment
- Thermal enclosure design is the main open mechanical engineering task

### Open Questions

- Exact Ethernet interface name on JetPack 6.2.1 (`eth0` vs predictable naming) — verify on first boot
- UEFI auto-power-on configuration method — serial console or nvbootctrl?
- Summer ambient temperature vs 35°C dev kit limit — is the Industrial variant needed?
- DC-DC converter specific part number and connector compatibility
- NVMe SSD model recommendation for vibration/thermal tolerance on the mower

## References

### Phase 5 Sources
- [NVIDIA Jetson Linux R36.4 — Platform Power and Performance (Orin series)](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html) — nvpmodel modes, jetson_clocks, fan control, thermal specs
- [NVIDIA Power Estimator Tool](https://jetson-tools.nvidia.com/powerestimator/) — Power and custom nvpmodel config estimation

### Phase 4 Sources
- [Deploy with NVIDIA's Jetson](https://docs.luxonis.com/hardware/platform/deploy/to-jetson/) — Luxonis Jetson-specific install steps, power, SSH
- [Manual DepthAI installation](https://docs.luxonis.com/software/depthai/manual-install/) — Dependencies, udev, pip install, test procedure
- [DepthAI V3](https://docs.luxonis.com/software-v3/depthai/) — Current API, install via pip, v2 vs v3 differences
- [depthai on PyPI](https://pypi.org/project/depthai/) — Version 3.5.0, prebuilt wheels, Luxonis artifact repo
- [OAK USB Deployment Guide](https://docs.luxonis.com/hardware/platform/deploy/usb-deployment-guide/) — USB connection details, udev rules

### Phase 3 Sources
- [uv installation](https://docs.astral.sh/uv/getting-started/installation/) — Install methods
- [uv platform tiers](https://docs.astral.sh/uv/reference/policies/platforms/) — aarch64 = Tier 2
- [uv managed Pythons](https://docs.astral.sh/uv/concepts/python-versions/) — python-build-standalone
- [numpy PyPI](https://pypi.org/project/numpy/#files) — Wheel matrix (no cp310, has cp311 aarch64)
- [pymavlink PyPI](https://pypi.org/project/pymavlink/) — lxml dependency, optional numpy

### Phase 2 Sources
- [Jetson Linux quick start](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/IN/QuickStart.html) — Carrier board ports, networking
- Ubuntu 22.04 netplan documentation — Netplan with NetworkManager renderer
- OpenSSH sshd_config.d documentation — Drop-in config files, AcceptEnv
- Microsoft OpenSSH documentation — Windows OpenSSH client, ssh-agent service

### Phase 1 Sources
- [JetPack landing page](https://developer.nvidia.com/embedded/jetpack) — JetPack 7 is Thor-only, JetPack 6.x for Orin
- [JetPack 6.2.1 release notes](https://docs.nvidia.com/jetson/jetpack/release-notes/index.html) — L4T 36.4.4, CUDA 12.6.10, cuDNN 9.3.0, TensorRT 10.3.0
- [SDK Manager 2.4.0](https://developer.nvidia.com/sdk-manager) — Windows support, WSL2, USBIPD-Win, host OS compatibility
- [SDK Manager system requirements](https://docs.nvidia.com/sdk-manager/system-requirements/index.html) — 8GB RAM, 43GB disk
- [SDK Manager flash walkthrough](https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html) — 4 steps, Pre-Config vs Runtime, storage target
- [JetPack install methods](https://docs.nvidia.com/jetson/jetpack/install-setup/index.html) — SDK Manager, apt, SD card
- [Jetson Linux quick start](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/IN/QuickStart.html) — Force recovery mode, CLI flash, module configs
- [AGX Orin getting started](https://developer.nvidia.com/embedded/learn/get-started-jetson-agx-orin-devkit) — Box contents, oem-config, JetPack component install

## Follow-Up Research

### From Phase 5
- Field-test thermal behavior under load during summer conditions
- Measure actual power draw at 30W mode with DepthAI + VSLAM workload
- Select and procure automotive DC-DC converter (9-32V → 19V, ≥75W)
- Design Jetson enclosure with IP65-rated ventilation
- Test E-stop power-loss scenario: verify clean boot and filesystem integrity
- Verify UEFI auto-power-on setting on actual dev kit
- Add `sdnotify` package to project dependencies (for systemd watchdog heartbeat)
- Consider `mower-jetson thermal` and `mower-jetson power` commands
- Benchmark boot time in headless config — target <60s to service ready

### From Phase 4
- Confirm DepthAI `cp311-manylinux_aarch64` wheel exists on PyPI or build from source on first install
- Test OAK-D Pro enumeration on the actual AGX Orin hardware after flash
- Evaluate IR projector/flood light settings for outdoor mowing conditions
- When VSLAM phase begins, consider adding `depthai` as optional dependency in `pyproject.toml`

### From Phase 3
- Verify actual Python version on first boot of JetPack 6.2.1 (should be 3.10.12)
- Confirm `uv python install 3.11` succeeds on the Jetson
- Consider updating copilot-instructions to say "`uv tool install`" instead of "`pipx`"

### From Phase 2
- Phase 3 should verify that `mower-jetson` CLI works over the SSH link after Python toolchain installation
- The `MOWER_CORRELATION_ID` propagation via `SendEnv`/`AcceptEnv` is not yet in the transport code's argv builder — future enhancement
- Field testing should validate that the static IP bench config works unchanged when the Jetson is mounted on the rover

### From Phase 1
- Phase 2 should define the specific hostname (`jetson-mower` or similar) and user (`mower`) to use in Pre-Config, as these affect SSH endpoint configuration
- Phase 5 should evaluate NVMe SSD thermal behavior on the mower (vibration + heat) and recommend specific SSD models if needed
- The `mower-jetson info` verification command should be tested after flash to confirm the nv_tegra_release parsing works with the R36.4.4 format string

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-22 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/002-jetson-agx-orin-bringup.md |
