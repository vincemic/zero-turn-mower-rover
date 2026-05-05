---
id: "021"
type: research
title: "Jetson-Initiated Pixhawk Firmware Update (ArduPilot Rover)"
status: ✅ Complete
created: "2026-05-05"
current_phase: "4 of 4"
---

## Introduction

This research investigates how the Jetson AGX Orin can autonomously check for, download, and flash the latest ArduPilot Rover firmware onto the Pixhawk Cube Orange over their existing USB connection. The goal is a `mower-jetson firmware-update` command that safely handles the full update lifecycle — from version checking to bootloader flashing to post-flash verification — without requiring the laptop or any manual intervention beyond operator confirmation.

## Objectives

- Determine the exact protocol and tooling for flashing firmware to the Cube Orange via USB (PX4 bootloader protocol)
- Identify how to programmatically check the current firmware version and compare against available releases
- Document the ArduPilot firmware distribution structure (firmware.ardupilot.org) and how to fetch the correct `.apj` file
- Establish the safety requirements for firmware updates (E-stop state, pre/post-flight checks, parameter preservation)
- Define fallback/recovery procedures if a flash fails mid-way
- Determine whether the operation can work field-offline (pre-staged firmware) vs requiring internet

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | PX4 Bootloader Protocol & uploader.py | ✅ Complete | Analyze ArduPilot's `uploader.py` script; understand the STM32 bootloader protocol; identify USB device enumeration behavior on Linux (bootloader vs normal mode); document the exact sequence of operations | 2026-05-05 |
| 2 | Firmware Distribution & Version Detection | ✅ Complete | Map firmware.ardupilot.org directory structure for Rover/CubeOrange; determine how to detect current firmware version via MAVLink (`AUTOPILOT_VERSION`); identify metadata files (manifest.json) for programmatic version checking; offline/pre-staged firmware patterns | 2026-05-05 |
| 3 | Safety, Parameter Preservation & Recovery | ✅ Complete | Document parameter persistence across flashes; identify risks (power loss mid-flash, USB disconnect); research bootloader recovery procedures; define safety prerequisites (E-stop engaged, motors disarmed, param snapshot); research whether firmware downgrade is safe | 2026-05-05 |
| 4 | Integration Design for mower-jetson CLI | ✅ Complete | Define the CLI command surface (`mower-jetson firmware-update`); identify dependencies (pyserial, uploader.py vendoring vs download); determine how to handle the USB port change during bootloader reboot; map to existing safety primitives (confirmation prompt, dry-run); consider field-offline vs internet-connected modes | 2026-05-05 |

## Phase 1: PX4 Bootloader Protocol & uploader.py

**Status:** ✅ Complete  
**Session:** 2026-05-05

### ArduPilot's `uploader.py` — Architecture & Protocol

ArduPilot's firmware upload tool lives at `Tools/scripts/uploader.py` in the ArduPilot repository. It is a self-contained ~1200-line Python script licensed BSD-3-Clause (from the PX4 project). It implements the **PX4 bootloader serial protocol** — a simple binary command/response protocol over a serial (USB CDC ACM) connection at **115200 baud** (bootloader default).

#### Key Classes

1. **`firmware`** — Loads `.apj` firmware files. The `.apj` format is a JSON file containing:
   - `image`: base64-encoded zlib-compressed firmware binary
   - `image_size`: size in bytes
   - `board_id`: target board identifier (Cube Orange = **140**)
   - `board_revision`: informational
   - Optional `extf_image` for external flash

2. **`uploader`** — The main protocol handler. Opens a serial port via `pyserial` and executes the bootloader protocol.

#### Protocol Byte Constants

```python
# Sync/framing
INSYNC = b'\x12'     # Bootloader response prefix (every reply starts with this)
EOC    = b'\x20'     # End-of-command marker (every command ends with this)

# Response bytes (follow INSYNC)
OK              = b'\x10'     # Command succeeded
FAILED          = b'\x11'     # Command failed
INVALID         = b'\x13'     # Invalid operation (rev3+)
BAD_SILICON_REV = b'\x14'     # Bad silicon revision (rev5+)

# Command bytes
NOP             = b'\x00'     # Discarded by bootloader
GET_SYNC        = b'\x21'     # Sync check
GET_DEVICE      = b'\x22'     # Get device info (board_id, flash_size, etc.)
CHIP_ERASE      = b'\x23'     # Erase flash
CHIP_VERIFY     = b'\x24'     # Verify (rev2 only)
PROG_MULTI      = b'\x27'     # Program multiple bytes
READ_MULTI      = b'\x28'     # Read multiple bytes (rev2 only)
GET_CRC         = b'\x29'     # Get CRC of programmed flash (rev3+)
GET_OTP         = b'\x2a'     # Get OTP word (rev4+)
GET_SN          = b'\x2b'     # Get serial number (rev4+)
GET_CHIP        = b'\x2c'     # Get chip version (rev5+)
SET_BOOT_DELAY  = b'\x2d'     # Set boot delay (rev5+)
GET_CHIP_DES    = b'\x2e'     # Get chip description (rev5+)
REBOOT          = b'\x30'     # Reboot into firmware
SET_BAUD        = b'\x33'     # Change baud rate
CHIP_FULL_ERASE = b'\x40'     # Full erase (force)

# External flash commands
EXTF_ERASE      = b'\x34'
EXTF_PROG_MULTI = b'\x35'
EXTF_READ_MULTI = b'\x36'
EXTF_GET_CRC    = b'\x37'

# Info parameter IDs
INFO_BL_REV     = b'\x01'     # Bootloader protocol revision
INFO_BOARD_ID   = b'\x02'     # Board type (Cube Orange = 140)
INFO_BOARD_REV  = b'\x03'     # Board revision
INFO_FLASH_SIZE = b'\x04'     # Max firmware size in bytes
INFO_EXTF_SIZE  = b'\x06'     # External flash size

# Protocol limits
PROG_MULTI_MAX  = 252          # Max bytes per PROG_MULTI (must be multiple of 4)
BL_REV_MIN      = 2            # Minimum supported protocol rev
BL_REV_MAX      = 5            # Maximum supported protocol rev
```

#### Exact Flash Sequence

The complete firmware upload procedure executed by `uploader.upload()`:

```
1. CONNECT & SYNC
   ├── Open serial port at 115200 baud, 2s timeout
   ├── Send GET_SYNC + EOC
   └── Expect INSYNC + OK

2. IDENTIFY BOARD
   ├── GET_DEVICE(INFO_BL_REV)    → bootloader protocol version
   ├── GET_DEVICE(INFO_EXTF_SIZE) → external flash size (may fail on older BL)
   ├── GET_DEVICE(INFO_BOARD_ID)  → board type (must match firmware's board_id)
   ├── GET_DEVICE(INFO_BOARD_REV) → board revision
   └── GET_DEVICE(INFO_FLASH_SIZE)→ max firmware size

3. VALIDATE
   ├── Check board_id matches firmware file (or compatible_IDs)
   └── Check firmware image_size ≤ flash_size

4. OPTIONAL: SET_BAUD (negotiate faster baud for flash)

5. ERASE (external flash first if present)
   ├── EXTF_ERASE (if extf_image_size > 0)
   ├── CHIP_ERASE + EOC (or CHIP_FULL_ERASE if force_erase)
   └── Wait up to 20s for INSYNC+OK (erase takes ~9s on STM32H7)

6. PROGRAM (external flash first if present)
   ├── Split firmware image into 252-byte chunks
   ├── For each chunk: PROG_MULTI + length_byte + data + EOC
   └── Wait for INSYNC+OK after each chunk

7. VERIFY
   ├── Protocol rev2: READ_MULTI + byte-by-byte compare
   └── Protocol rev3+: GET_CRC + EOC → compare CRC32 against computed
       (CRC32 computed over image padded to fw_maxsize with 0xFF)

8. OPTIONAL: SET_BOOT_DELAY

9. REBOOT
   ├── REBOOT + EOC
   └── Close serial port
```

#### Reboot-to-Bootloader Mechanism

Before the upload sequence, the board must be IN bootloader mode. `uploader.py` handles this via `send_reboot()`:

1. **MAVLink reboot command** — Sends `MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN` with `param1=3` (stay in bootloader):
   ```python
   MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN (cmd 246)
   param1 = 3  # 3 = reboot and stay in bootloader
   ```
   The script sends pre-built MAVLink packets for both `target_system=1` and `target_system=0` to maximize chances.

2. **NSH fallback** — If MAVLink doesn't work, sends `\r\r\r` (NSH init) followed by `reboot -b\n` (reboot to bootloader) via the serial port.

3. After sending reboot, waits 250ms, then closes port, waits 300ms, then re-opens and attempts `identify()`.

### USB Device Enumeration — Cube Orange on Linux

#### USB VID/PID Mapping

| Mode | VID | PID | Device Path | Description |
|------|-----|-----|-------------|-------------|
| **Normal (MAVLink)** | `0x2DAE` | `0x1016` | `/dev/ttyACM0` → `/dev/pixhawk` | CubeOrange composite USB (MAVLink + SLCAN) |
| **Bootloader** | `0x2DAE` | `0x1011` | `/dev/ttyACM0` (new enumeration) | CubeOrange bootloader mode |

#### Enumeration Behavior During Flash

When the Pixhawk reboots into bootloader mode:
1. The USB device **disconnects** from the bus (existing `/dev/ttyACM0` disappears)
2. The Pixhawk re-enumerates with PID `0x1011` (bootloader)
3. A **new** `/dev/ttyACMx` device appears (may be ttyACM0 again or a different number)
4. The existing `/dev/pixhawk` symlink (from udev) matches on VID only — works for both modes

#### Timing Considerations

- USB re-enumeration typically takes 0.5–1.5 seconds on Linux
- `uploader.py` uses 250ms + 300ms waits between reboot and re-open
- The Waveshare USB 3.2 hub adds negligible latency to enumeration
- USB autosuspend is disabled (udev rule + kernel params) — prevents device unreachability during critical operations

### Dependencies

`uploader.py` requires:
- **`pyserial`** (≥3.5) — Already in project dependencies
- **`pymavlink`** — Only needed for generating the MAVLink reboot command (pre-built packets exist as fallback). Already in project dependencies.
- **Standard library**: `json`, `zlib`, `base64`, `struct`, `time`, `serial`, `glob`, `argparse`

### Can `uploader.py` Be Used as a Library?

**Partially.** The `uploader` and `firmware` classes are well-separated, but the script has limitations for library use:

1. **No public API** — Methods are prefixed with `__` (name-mangled), making subclassing awkward
2. **`print()` throughout** — Uses `print()` and `sys.stdout.write()` for progress instead of callbacks
3. **`sys.exit()` in `main()`** — Exits directly on errors
4. **Global state** — Some module-level code

**Recommended approach:** Vendor the `uploader` and `firmware` classes (BSD-3-Clause licensed), wrap them with:
- A callback/progress interface replacing `print()`
- Proper exception propagation instead of `sys.exit()`
- Integration with the project's `structlog` logging

Alternatively, invoke `uploader.py` as a subprocess: `python uploader.py --port /dev/pixhawk firmware.apj`

### Board ID Verification

The Cube Orange's APJ_BOARD_ID is **140** (`AP_HW_CUBEORANGE`). The CubeOrange+ is **1063** (`AP_HW_CUBEORANGEPLUS`). The firmware `.apj` file must have `board_id: 140` for this specific hardware.

### Baud Rate Notes

- **Bootloader default**: 115200 baud (hardcoded in the PX4 bootloader)
- **USB CDC ACM**: Baud rate is ignored (USB operates at native speed regardless of configured baud)
- **Flight stack detection**: `uploader.py` tries 57600 by default when sending the MAVLink reboot command
- Since the Jetson connects via USB (not true serial), baud rate settings are cosmetic

### CRC Verification

The bootloader CRC (rev3+) is computed over the full flash region padded with `0xFF` to `fw_maxsize`. The algorithm is CRC32 (same polynomial as `AP_Math/crc.cpp`). This provides reliable verification that the flash completed correctly.

### Safety Mechanisms in the Protocol

1. **Board ID check** — Firmware won't flash if `board_id` doesn't match (unless `--force`)
2. **Image size check** — Rejects firmware larger than flash capacity
3. **Mandatory GET_SYNC + GET_DEVICE before erase** — Bootloader requires identification before destructive operations
4. **Mandatory PROG_MULTI + GET_CRC before REBOOT** — Must program and verify before allowing reboot
5. **Erase timeout** — 20-second timeout for chip erase (STM32H7 is slower than F4)
6. **Post-program CRC verification** — Catches any programming errors before reboot

### Impact of Waveshare USB Hub

The Pixhawk connects through the Waveshare 4-Ch USB 3.2 Gen1 powered hub (VIA Labs `2109:0817`):

- **USB 2.0 Full Speed** (12 Mbps) — The Pixhawk is USB 2.0; the hub handles speed negotiation
- **Re-enumeration propagation** — When the Pixhawk reboots to bootloader, the hub propagates disconnect/reconnect
- **Power** — The hub is externally powered, so stable USB power during flash
- **Port persistence** — After re-enumeration, udev matches on VID so `/dev/pixhawk` will still be created

**Key Discoveries:**
- ArduPilot's `uploader.py` implements a simple binary serial protocol over USB CDC ACM at 115200 baud
- The Cube Orange uses VID `0x2DAE`, PID `0x1016` (normal) and PID `0x1011` (bootloader)
- Reboot-to-bootloader uses MAVLink `MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN` with `param1=3`
- The existing `/dev/pixhawk` udev rule matches on VID only — works for both modes
- pyserial is already a project dependency; no new packages needed
- The `.apj` format is JSON with base64+zlib-compressed binary image, board_id=140 for CubeOrange
- Protocol supports rev 2–5; requires sync→identify→erase→program→verify→reboot sequence
- Erase takes ~9s on STM32H7; total flash time for ~2MB image is ~30–60 seconds
- `uploader.py` is BSD-3-Clause and can be vendored, but private API requires wrapping
- USB re-enumeration during reboot-to-bootloader causes device path change that must be handled

| File | Relevance |
|------|-----------|
| `scripts/90-pixhawk-usb.rules` | Udev rule confirming VID/PID, /dev/pixhawk symlink |
| `src/mower_rover/cli/detect.py` | Existing AUTOPILOT_VERSION reading code |
| `src/mower_rover/mavlink/connection.py` | ConnectionConfig and open_link() for MAVLink |
| `pyproject.toml` | Confirms pyserial already a dependency |

**External Sources:**
- [ArduPilot uploader.py](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/scripts/uploader.py)
- [PX4 Bootloader README](https://github.com/PX4/PX4-Bootloader/blob/main/README.md)
- [ArduPilot board_types.txt](https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/AP_Bootloader/board_types.txt)
- [ArduPilot USB IDs](https://ardupilot.org/dev/docs/USB-IDs.html)
- [PX4 Bootloader Update](https://docs.px4.io/main/en/advanced_config/bootloader_update.html)

**Gaps:**
- The exact CubeOrange bootloader PID (`0x1011`) needs field verification with `lsusb` during actual bootloader reboot
- ArduPilot USB IDs page doesn't explicitly list a CubeOrange bootloader PID; may use shared/generic PID

**Assumptions:**
- Cube Orange bootloader PID is `0x1011` based on project's own udev rule (written from direct observation)
- Cube Orange uses bootloader protocol revision 5 (latest) since STM32H7 boards use current in-tree bootloader
- USB CDC ACM baud rate is cosmetic (standard behavior for USB serial devices)

## Phase 2: Firmware Distribution & Version Detection

**Status:** ✅ Complete  
**Session:** 2026-05-05

### 1. firmware.ardupilot.org Directory Structure

The ArduPilot firmware server uses a hierarchical structure:

```
firmware.ardupilot.org/
├── Rover/
│   ├── stable/           ← latest stable release
│   │   └── CubeOrange/
│   │       ├── ardurover.apj          ← THE FILE TO FLASH
│   │       ├── firmware-version.txt   ← "4.6.3-FIRMWARE_VERSION_TYPE_OFFICIAL"
│   │       └── git-version.txt        ← commit hash + APMVERSION string
│   ├── beta/             ← pre-release testing
│   │   └── CubeOrange/
│   ├── latest/           ← dev/nightly builds
│   │   └── CubeOrange/
│   ├── stable-4.6.3/    ← pinned version archive
│   └── stable-4.6.2/    ← pinned version archive
└── manifest.json.gz      ← master index (~300KB gzipped)
```

**URL patterns for CubeOrange Rover:**

| Track | URL |
|-------|-----|
| Stable (latest) | `https://firmware.ardupilot.org/Rover/stable/CubeOrange/ardurover.apj` |
| Beta | `https://firmware.ardupilot.org/Rover/beta/CubeOrange/ardurover.apj` |
| Latest (dev) | `https://firmware.ardupilot.org/Rover/latest/CubeOrange/ardurover.apj` |
| Pinned version | `https://firmware.ardupilot.org/Rover/stable-4.6.3/CubeOrange/ardurover.apj` |
| Version check | `https://firmware.ardupilot.org/Rover/stable/CubeOrange/firmware-version.txt` |

**Current versions observed (2026-05-05):**

| Track | Version |
|-------|---------|
| stable | 4.6.3-FIRMWARE_VERSION_TYPE_OFFICIAL |
| beta | 4.7.0-FIRMWARE_VERSION_TYPE_BETA |
| latest | 4.8.0-FIRMWARE_VERSION_TYPE_DEV |

### 2. firmware-version.txt Format

Plain text with format: `{major}.{minor}.{patch}-FIRMWARE_VERSION_TYPE_{TYPE}`

```python
import re
FW_VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"-FIRMWARE_VERSION_TYPE_(?P<type>\w+)\s*$"
)
```

### 3. AUTOPILOT_VERSION — Version Encoding

The `flight_sw_version` field is a 32-bit integer:

```
Byte 3 (MSB): major version
Byte 2:       minor version
Byte 1:       patch version
Byte 0 (LSB): firmware type enum
```

**Firmware type enum values:**
```python
class FirmwareVersionType:
    Dev = 0
    Alpha = 64
    Beta = 128
    RC = 192
    Official = 255
```

**Decoding:**
```python
def decode_flight_sw_version(raw: int) -> tuple[int, int, int, int]:
    """Decode AUTOPILOT_VERSION.flight_sw_version into (major, minor, patch, type)."""
    major = (raw >> 24) & 0xFF
    minor = (raw >> 16) & 0xFF
    patch = (raw >> 8) & 0xFF
    fw_type = raw & 0xFF
    return major, minor, patch, fw_type
```

**Additional useful AUTOPILOT_VERSION fields:**
- `board_version`: Upper 16 bits = APJ_BOARD_ID (140 for CubeOrange)
- `flight_custom_version[8]`: Git hash as 8-byte ASCII string
- `uid`: 64-bit unique chip ID

### 4. Existing Version Detection Code

`src/mower_rover/cli/detect.py` already requests AUTOPILOT_VERSION:

```python
conn.mav.command_long_send(
    conn.target_system, conn.target_component,
    mavutil.mavlink.MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES,
    0, 1, 0, 0, 0, 0, 0, 0,
)
# Stores raw hex: report.autopilot_version = f"0x{fw:08x}"
```

**Current limitation:** Stores raw hex (`"0x040600FF"`) but does NOT decode to semver. Trivial to add.

### 5. manifest.json Schema

```json
{
  "format-version": "1.0.0",
  "firmware": [
    {
      "vehicletype": "Rover",
      "platform": "CubeOrange",
      "mav-firmware-version": "4.6.3",
      "mav-firmware-version-type": "OFFICIAL",
      "url": "https://firmware.ardupilot.org/Rover/stable/CubeOrange/ardurover.apj",
      "format": "apj",
      "board_id": 140,
      "image_size": 1563633,
      "git-sha": "3fc7011a7d3dc047cbb17d8bd98ee94577d144c6"
    }
  ]
}
```

~7 MB uncompressed, ~300 KB gzipped. Filter by `vehicletype=="Rover"` + `platform=="CubeOrange"` + `format=="apj"`.

### 6. Version Comparison Logic

```python
def is_newer(available: str, running_raw: int) -> bool:
    """Check if available version string is newer than running firmware."""
    match = FW_VERSION_RE.match(available)
    avail_tuple = (int(match.group("major")), int(match.group("minor")), int(match.group("patch")))
    running_tuple = ((running_raw >> 24) & 0xFF, (running_raw >> 16) & 0xFF, (running_raw >> 8) & 0xFF)
    return avail_tuple > running_tuple
```

### 7. Firmware Tracks

| Track | Purpose | Safety | Recommendation |
|-------|---------|--------|----------------|
| `stable` | Production releases | Safest | **Default for this project** |
| `beta` | Pre-release | Medium risk | Only with explicit `--track beta` |
| `latest` | Nightly dev | High risk | Never for field use |
| `stable-X.Y.Z` | Pinned historical | Same as stable | For rollback/pinning |

### 8. Offline/Pre-Staged Firmware Pattern

```
~/.mower/firmware-cache/
└── Rover/
    └── CubeOrange/
        ├── ardurover.apj
        ├── firmware-version.txt
        └── git-version.txt
```

**Workflow:**
1. Online: `mower-jetson firmware-update --download-only` → caches files
2. Field: `mower-jetson firmware-update --offline` → uses cached files
3. Validate on download: `assert apj["board_id"] == 140`

### 9. .apj File Metadata

```json
{
    "board_id": 140,
    "magic": "APJFWv1",
    "image_size": 1563633,
    "git_identity": "3fc7011a7d3dc047cbb17d8bd98ee94577d144c6"
}
```

Note: The `version` field in `.apj` is always `"0.1"` (format version, NOT firmware version). Firmware version must come from `firmware-version.txt` or the manifest.

### 10. Practical Version Check Flow

```
1. Connect to Pixhawk → request AUTOPILOT_VERSION
2. Decode: 0x040603FF → 4.6.3 official
3. If online: GET firmware-version.txt (37 bytes)
   If offline: read from cache
4. Compare: available > running → "Update available: 4.7.0"
5. Display diff to operator for confirmation
```

**Key Discoveries:**
- firmware.ardupilot.org uses clean `/{Vehicle}/{Track}/{Board}/ardurover.apj` URL pattern
- `firmware-version.txt` (37 bytes) is the lightest way to check for updates
- `flight_sw_version` packed as `major<<24 | minor<<16 | patch<<8 | type` — type 255=official, 128=beta, 0=dev
- Existing `detect.py` already reads AUTOPILOT_VERSION — decoding to semver is trivial
- manifest.json.gz (~300KB) provides comprehensive index but is overkill for single-board updates
- Pinned archives (`stable-4.6.3/`) enable reproducible rollbacks
- `.apj` contains `board_id` validated by uploader.py — prevents wrong-board errors
- Pre-staging for offline use: cache .apj + firmware-version.txt, validate board_id on download

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/detect.py` | Existing AUTOPILOT_VERSION reading (lines 86-112) |
| `src/mower_rover/mavlink/connection.py` | MAVLink connection layer |
| `src/mower_rover/vslam/lua_deploy.py` | Pattern for version check → compare → deploy workflow |

**External Sources:**
- [firmware.ardupilot.org/Rover/stable/CubeOrange/](https://firmware.ardupilot.org/Rover/stable/CubeOrange/)
- [firmware-version.txt](https://firmware.ardupilot.org/Rover/stable/CubeOrange/firmware-version.txt)
- ArduPilot `GCS_Common.cpp` (flight_sw_version encoding)
- ArduPilot `firmware_version_decoder.py` (FirmwareVersionType enum)
- ArduPilot `generate_manifest.py` (manifest.json schema)

**Gaps:** None  
**Assumptions:**
- manifest.json.gz schema reconstructed from generator source code (not directly parsed)
- CubeOrange board_id=140 confirmed in Phase 1 and manifest generator

## Phase 3: Safety, Parameter Preservation & Recovery

**Status:** ✅ Complete  
**Session:** 2026-05-05

### 1. Parameter Persistence Across Firmware Flashes

#### Cube Orange Storage Architecture

The Cube Orange uses **RAMTRON FRAM** (Ferroelectric RAM) for parameter storage (`HAL_WITH_RAMTRON 1` in hwdef.inc):

- **FRAM is a separate physical chip** from the STM32H743's internal flash
- **Firmware flashing erases only the STM32H7 internal flash** (application area) — does NOT touch FRAM
- **Parameters ALWAYS survive firmware flashes** — stored on FRAM, remain intact

```
Flash Layout (STM32H743, 2 MB):
┌────────────────────┐ 0x08000000
│  Bootloader        │ 128 KB (protected, never erased)
├────────────────────┤ 0x08020000
│  Application       │ ~1920 KB (erased during flash)
│  (ArduPilot Rover) │
└────────────────────┘ 0x08200000

FRAM (16 KB, external chip):
┌────────────────────┐
│  Parameters        │ (survives any flash operation)
│  Waypoints         │
│  Rally/Fence pts   │
└────────────────────┘
```

#### Parameter Conversion During Upgrades

ArduPilot includes a conversion mechanism for renamed/moved parameters:
- Within the same major version (4.5→4.6, 4.6.2→4.6.3): all params preserved, conversions automatic
- Each version includes `ConversionInfo` tables mapping old keys to new
- Conversion runs once per boot after upgrade (checks `configured_in_storage()`)

### 2. Firmware Downgrade Safety

**Partially safe, with caveats:**

1. Parameters added in newer version → orphaned in FRAM (ignored, no harm)
2. Parameters renamed in newer version → older firmware can't find them, uses defaults
3. `FORMAT_VERSION` mismatch between versions may trigger full param reset

**Recommendation:** Always snapshot before upgrading. Downgrade + restore from pre-upgrade snapshot is the safe path.

### 3. Risks and Failure Modes

| Failure Point | Consequence | Recovery |
|---------------|-------------|----------|
| Power loss during **erase** | Partially erased flash; no valid firmware | **Bootloader survives** — re-flash |
| Power loss during **program** | Partially written firmware | **Bootloader survives** — re-flash |
| Power loss during **verify** | Firmware likely fine but unverified | Re-flash if uncertain |
| USB disconnect mid-flash | Bootloader times out, stays in BL mode | Re-plug, re-flash |
| Wrong board_id firmware | Rejected by uploader.py before erase | No damage |
| Wrong vehicle type (Copter on Rover) | Parameters reset (FORMAT_VERSION mismatch) | Restore from snapshot |

**Critical safety fact:** The bootloader resides in the first 128 KB (`FLASH_RESERVE_START_KB 128`). `CHIP_ERASE` only erases the application region. The **bootloader cannot be corrupted** by normal firmware flashing.

### 4. Bootloader Recovery Procedures

1. **Firmware fails to boot:** Bootloader runs first on every power cycle. Catch the bootloader window by initiating flash immediately after power-on.
2. **Firmware corrupted:** Power-cycle → bootloader auto-starts → re-flash
3. **Bootloader corrupted (extremely rare):** Requires DFU mode (BOOT0 pin held during reset). Not caused by normal flashing. Our tool will NEVER touch the bootloader.
4. **Parameters corrupted:** Reset via `FORMAT_VERSION=0` + reboot, or restore from JSON snapshot

### 5. Existing Project Safety Infrastructure

#### Safety Primitive (`src/mower_rover/safety/confirm.py`)

```python
@dataclass
class SafetyContext:
    dry_run: bool = False
    assume_yes: bool = False
    safe_stop_hooks: list[Callable[[], None]] = field(default_factory=list)
```

- `@requires_confirmation` decorator — forces operator approval
- `--dry-run` mode — previews without executing
- `safe_stop_hooks` — registered cleanup handlers on abort

#### Parameter Snapshot System (`src/mower_rover/params/`)

- `write_json_snapshot()` — schema `mower-rover.params.snapshot.v1`
- `load_json_snapshot()` — reads back for restore
- `fetch_params()` — MAVLink `PARAM_REQUEST_LIST`
- `apply_params()` — `PARAM_SET` with per-param verify + retry

#### Arming Check Pattern (`src/mower_rover/cli/zone_laptop.py`)

```python
def _check_not_armed(conn) -> None:
    hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    if hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
        raise typer.BadParameter("FC is armed — cannot proceed. Disarm first.")
```

### 6. Recommended Safety Prerequisites for Firmware Flash

| Pre-condition | Check Method | Rationale |
|---------------|-------------|-----------|
| FC disarmed | HEARTBEAT `base_mode` bit check | Armed FC could be in motion |
| E-stop engaged | Operator confirmation | Physical safety |
| No mission active | Mode check (Manual/Hold) | Prevent resume after reboot |
| USB stable | Serial port open + HEARTBEAT | Avoid mid-flash disconnect |
| Param snapshot taken | Auto-snapshot before flash | Rollback safety net |
| Current FW version known | AUTOPILOT_VERSION | Log previous version |
| Target board_id=140 | Parse .apj JSON | Prevent wrong-board flash |
| Target vehicle=Rover | Check .apj metadata | Prevent vehicle-type reset |

### 7. Recommended Flash Workflow

```
1. Confirmation: "Flash firmware X.Y.Z onto Cube Orange?
   Current: A.B.C. Params preserved. Ensure E-stop engaged."
2. Auto-snapshot: write_json_snapshot(pre-flash-<timestamp>.json)
3. Validate .apj: board_id=140, image_size, vehicle=Rover
4. Flash: reboot-to-BL → sync → erase → program → verify → reboot
5. Post-flash verify:
   - Wait for USB re-enumeration
   - Connect MAVLink → read AUTOPILOT_VERSION → confirm new version
   - Fetch all params → diff against pre-flash snapshot
   - Report params that changed (indicate conversion)
6. On failure: bootloader always accessible → re-attempt or restore
```

**Key Discoveries:**
- Cube Orange uses external RAMTRON FRAM for parameters — completely separate from MCU flash. Parameters ALWAYS survive firmware flashing.
- Bootloader is in protected first 128 KB. Erase command only touches application region. Bootloader cannot be corrupted by normal flashing.
- Power loss or USB disconnect mid-flash → board stays in bootloader mode → always recoverable by re-flashing.
- ArduPilot has `convert_old_parameter()` for transparent param migration between versions.
- Downgrade possible but may orphan params or trigger FORMAT_VERSION reset. Pre-upgrade snapshot is the safe rollback strategy.
- Project already has all building blocks: `SafetyContext`, `@requires_confirmation`, `_check_not_armed()`, `write_json_snapshot()`, `fetch_params()`, `apply_params()`.

| File | Relevance |
|------|-----------|
| `src/mower_rover/safety/confirm.py` | SafetyContext, requires_confirmation, safe_stop_hooks |
| `src/mower_rover/params/io.py` | write_json_snapshot, load_json_snapshot |
| `src/mower_rover/params/mav.py` | fetch_params, apply_params |
| `src/mower_rover/cli/params.py` | CLI: snapshot, diff, apply with pre-apply snapshot |
| `src/mower_rover/cli/zone_laptop.py` | _check_not_armed() pattern |
| `docs/procedures/006-apply-safety-defaults.md` | Safety procedure template |

**External Sources:**
- [ArduPilot Parameter Reset](https://ardupilot.org/copter/docs/common-parameter-reset.html)
- [ArduPilot Bootloader Architecture](https://ardupilot.org/dev/docs/bootloader.html)
- [ArduPilot Storage/EEPROM Management](https://ardupilot.org/dev/docs/learning-ardupilot-storage-and-eeprom-management.html)
- [CubeOrange hwdef.inc](https://github.com/ArduPilot/ardupilot/blob/master/libraries/AP_HAL_ChibiOS/hwdef/CubeOrange/hwdef.inc)

**Gaps:** None  
**Assumptions:**
- Cube Orange RAMTRON FRAM is functioning correctly (validated by 1000+ params currently readable)
- ArduPilot Rover 4.5.x–4.7.x maintains backward-compatible parameter conversion tables

## Phase 4: Integration Design for mower-jetson CLI

**Status:** ✅ Complete  
**Session:** 2026-05-05

### 1. Existing CLI Structure & Patterns

The `mower-jetson` CLI is defined in `src/mower_rover/cli/jetson.py`:
- Main `app = typer.Typer(name="mower-jetson")`
- Sub-apps: `config`, `service`, `vslam`, `zone`, `pixhawk`, `kiosk`
- Root callback handles `--dry-run` and `--verbose`, configures structlog, stores state in `ctx.obj`
- Entry point in `pyproject.toml`: `mower-jetson = "mower_rover.cli.jetson:app"`

**Consistent option patterns:**
- `--port/--endpoint` for MAVLink (default: `/dev/pixhawk`)
- `--baud` for serial (default: `0` for USB CDC)
- `--json` for machine-readable output
- `--yes/-y` to skip confirmation
- `--dry-run` inherited from root callback

### 2. Recommended Command Surface

Commands live under the existing `pixhawk_app` Typer sub-app:

```
mower-jetson pixhawk firmware-check   -- query running version + check for updates
mower-jetson pixhawk firmware-update  -- full lifecycle (download + flash)
mower-jetson pixhawk firmware-flash   -- flash a local .apj file (offline path)
```

#### `pixhawk firmware-check`
```python
@pixhawk_app.command("firmware-check")
def firmware_check_command(
    ctx: typer.Context,
    endpoint: str = typer.Option("/dev/pixhawk", "--port", "--endpoint"),
    baud: int = typer.Option(0),
    track: str = typer.Option("stable", "--track"),
    offline: bool = typer.Option(False, "--offline"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
```

#### `pixhawk firmware-update`
```python
@pixhawk_app.command("firmware-update")
def firmware_update_command(
    ctx: typer.Context,
    endpoint: str = typer.Option("/dev/pixhawk", "--port", "--endpoint"),
    baud: int = typer.Option(0),
    track: str = typer.Option("stable", "--track"),
    version: str | None = typer.Option(None, "--version"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    force: bool = typer.Option(False, "--force"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
```

#### `pixhawk firmware-flash`
```python
@pixhawk_app.command("firmware-flash")
def firmware_flash_command(
    ctx: typer.Context,
    apj_file: Path = typer.Argument(..., help="Path to .apj firmware file"),
    endpoint: str = typer.Option("/dev/pixhawk", "--port", "--endpoint"),
    baud: int = typer.Option(0),
    yes: bool = typer.Option(False, "--yes", "-y"),
    skip_snapshot: bool = typer.Option(False, "--skip-snapshot"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
```

### 3. uploader.py Integration: Vendor as Internal Module

**Recommendation:** Vendor at `src/mower_rover/pixhawk/_uploader.py`

**Rationale:**
- `src/mower_rover/pixhawk/` already exists (sync.py, unit.py)
- No `_vendor/` or `contrib/` pattern for Python exists in the project
- BSD-3-Clause permits vendoring; ~1200 lines as a single file
- Subprocess invocation loses library-level error handling
- Reimplementation is unnecessary — community-tested code

**Module layout:**
```
src/mower_rover/pixhawk/
├── __init__.py              # existing
├── sync.py                  # existing
├── unit.py                  # existing
├── firmware.py              # NEW: firmware operations API
└── _uploader.py             # NEW: vendored uploader.py (BSD-3-Clause)
```

**Thin wrapper API** (`firmware.py`):
```python
@dataclass
class FirmwareInfo:
    board_id: int
    version_raw: int
    version_str: str

@dataclass  
class FlashResult:
    success: bool
    elapsed_s: float
    board_id: int
    error: str | None = None

def read_running_version(conn) -> FirmwareInfo: ...
def check_remote_version(track: str = "stable") -> str | None: ...
def download_firmware(track: str, version: str | None, cache_dir: Path) -> Path: ...
def flash_firmware(port: str, apj_path: Path, *, progress_cb=None) -> FlashResult: ...
def wait_for_bootloader(timeout_s: float = 30.0) -> str: ...
def reboot_to_bootloader(conn) -> None: ...
```

### 4. USB Port Re-enumeration Handling

**Key insight:** The udev rule (`scripts/90-pixhawk-usb.rules`) matches on **vendor ID only** — `/dev/pixhawk` exists in BOTH normal and bootloader modes. No instability.

**Approach: Poll `/dev/pixhawk` with PX4 bootloader sync probe:**

```python
def wait_for_bootloader(timeout_s: float = 30.0) -> str:
    import serial, time
    deadline = time.monotonic() + timeout_s
    port = "/dev/pixhawk"
    time.sleep(1.0)  # allow USB disconnect/reconnect
    while time.monotonic() < deadline:
        try:
            with serial.Serial(port, 115200, timeout=0.5) as ser:
                ser.write(b'\x21\x20')  # GET_SYNC + EOC
                resp = ser.read(2)
                if resp == b'\x12\x10':  # INSYNC + OK
                    return port
        except (serial.SerialException, OSError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Bootloader not detected on {port} within {timeout_s}s")
```

**No new dependencies needed** — pyserial already in project.

### 5. Safety Primitives Integration

Firmware-update is an actuator-touching command (writes to FC flash):

1. **`@requires_confirmation`** — before flashing
2. **`--dry-run`** — shows plan without executing
3. **Pre-flash armed check** — `_check_not_armed()` pattern
4. **Safe-stop hook** — informational (bootloader is always recoverable)
5. **Pre-flash param snapshot** — auto via `write_json_snapshot()`

```python
@requires_confirmation(
    "Flash firmware to Pixhawk (always recoverable via bootloader)"
)
def _do_flash(*, ctx: SafetyContext, apj_path: Path, port: str) -> FlashResult:
    if ctx.dry_run:
        return FlashResult(success=True, elapsed_s=0, board_id=140)
    ...
```

### 6. Online vs Offline Mode

```
firmware-update (full lifecycle):
  1. Read running version (local, always)
  2. Check available version (online: GET firmware-version.txt; offline: check cache)
  3. Download .apj (online; skip if cached or --offline)
  4. Flash from local file (always local)

firmware-flash (offline-only path):
  - User provides .apj path directly
  - No internet at any point
```

**Pre-cache workflow (workshop):**
```bash
mower-jetson pixhawk firmware-update --track stable  # downloads + caches + flashes
# Or download only via firmware-check (just checks, reports)
```

**Field use (offline):**
```bash
mower-jetson pixhawk firmware-flash /var/cache/mower/firmware/ardurover-stable-4.6.3.apj
```

### 7. Firmware Cache Directory

```
/var/cache/mower/firmware/
├── ardurover-stable-4.6.3.apj
├── ardurover-stable-4.6.3.version.txt
└── ardurover-beta-4.7.0.apj
```

Consistent with `/var/cache/mower/` already used for zone probe data. Created lazily or by bringup pixhawk-udev step.

### 8. Full Update Lifecycle Sequence

```
1. log.info("firmware_update_start", track=track)
2. Open MAVLink → read AUTOPILOT_VERSION → decode flight_sw_version
3. If not --offline: HTTP GET firmware-version.txt (37 bytes)
4. Compare → if current and not --force: "Already up to date" + exit 0
5. Download .apj to /var/cache/mower/firmware/ (if not cached)
6. Validate .apj: board_id==140, image_size within limits
7. Pre-flash param snapshot → /var/lib/mower/snapshots/
8. @requires_confirmation("Flash ArduPilot Rover {ver} to Pixhawk...")
9. _check_not_armed(conn)
10. MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN(param1=3)
11. Close MAVLink
12. wait_for_bootloader() — poll for PX4 sync response
13. Flash: sync → identify → erase → program → verify → reboot
14. Wait for normal re-enumeration
15. Re-open MAVLink → verify AUTOPILOT_VERSION
16. log.info("firmware_update_complete", version=new_ver)
17. Print success summary (or JSON)
```

### 9. Dependencies Summary

| Dependency | Status | Purpose |
|-----------|--------|---------|
| pyserial | Already in project | Port access, bootloader sync |
| pymavlink | Already in project | MAVLink commands (reboot, version) |
| urllib.request (stdlib) | Always available | Download .apj + firmware-version.txt |
| structlog | Already in project | Logging |
| typer | Already in project | CLI framework |

**No new dependencies needed.**

**Key Discoveries:**
- `/dev/pixhawk` udev symlink covers both normal and bootloader PIDs — no USB instability
- `pixhawk_app` Typer sub-app already exists and is the natural home for firmware commands
- No new dependencies needed — pyserial, pymavlink, urllib.request all available
- Project has no vendored Python yet; `_uploader.py` would be the first (BSD-3-Clause)
- `/var/cache/mower/` already used for cached data; firmware cache fits naturally
- All safety/logging/CLI infrastructure already in place
- `firmware-flash` as separate command enables field-offline workflow naturally
- Step-by-step console.print (Rich) is the progress convention — no progress bars

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/jetson.py` | Main Jetson CLI, pixhawk_app group |
| `src/mower_rover/safety/confirm.py` | SafetyContext, @requires_confirmation |
| `src/mower_rover/pixhawk/sync.py` | Existing pixhawk module pattern |
| `src/mower_rover/mavlink/connection.py` | ConnectionConfig, open_link |
| `src/mower_rover/params/io.py` | write_json_snapshot |
| `src/mower_rover/cli/zone_laptop.py` | _check_not_armed pattern |
| `scripts/90-pixhawk-usb.rules` | udev rule (VID-only match) |

**Gaps:** None  
**Assumptions:**
- PX4 bootloader sync probe is reliable for detecting readiness on Cube Orange
- `urllib.request` sufficient for downloading firmware (no httpx needed)
- `/var/cache/mower/firmware/` created lazily or by bringup step

**Follow-up:**
- Field validation: confirm USB re-enumeration timing on actual hardware (1s sleep + 30s poll timeout)
- Consider whether firmware-update should also be exposed on laptop side via SSH tunnel

## Overview

This research conclusively demonstrates that Jetson-initiated Pixhawk firmware updates are feasible, safe, and straightforward to implement using existing project infrastructure. The Cube Orange's architecture (separate RAMTRON FRAM for parameters, protected bootloader in first 128 KB of flash) makes firmware flashing an inherently safe operation — the board is always recoverable even after power loss or USB disconnect mid-flash.

The implementation path is unusually clean: **no new dependencies** are required (pyserial, pymavlink, urllib.request are all already available), the udev rule already handles USB re-enumeration across modes, the safety/confirmation/snapshot primitives are all in place, and ArduPilot's `uploader.py` (BSD-3-Clause) can be vendored as a single file with a thin wrapper.

### Key Findings Summary

1. **Protocol is simple and well-understood** — PX4 bootloader protocol is a binary command/response over USB CDC ACM (115200 baud). Sequence: sync → identify → erase (~9s) → program (252B chunks) → CRC verify → reboot. Total ~30-60s for 2MB firmware.

2. **Zero new dependencies** — pyserial (flash protocol), pymavlink (reboot command, version detection), and urllib.request (firmware download) are all present in the project.

3. **Parameters always survive** — Cube Orange stores params in external RAMTRON FRAM, physically separate from the MCU flash that gets erased. ArduPilot's conversion mechanism handles param migrations between versions transparently.

4. **Bootloader cannot be corrupted** — Protected first 128 KB. Normal firmware flash only touches the application region. Even a catastrophic mid-flash failure leaves the board bootable into bootloader mode.

5. **USB re-enumeration is a non-issue** — The existing udev rule matches on vendor ID only, creating `/dev/pixhawk` for both normal (PID 0x1016) and bootloader (PID 0x1011) modes.

6. **firmware.ardupilot.org has a clean programmatic API** — `/{Vehicle}/{Track}/{Board}/firmware-version.txt` (37 bytes) for cheap update checks, `ardurover.apj` for the flashable file, pinned archives for rollback.

7. **Field-offline pattern is natural** — Cache .apj files locally; `firmware-flash` command takes a local path directly. The `firmware-update` command supports both online (download + flash) and offline (cache-only) modes.

### Cross-Cutting Patterns

- **Offline-first design** aligns perfectly with NFR-2 (field-offline by default). The three-command split (`firmware-check`, `firmware-update`, `firmware-flash`) naturally separates online and offline operations.
- **Safety-by-composition** — The existing `SafetyContext`, `@requires_confirmation`, `_check_not_armed()`, and `write_json_snapshot()` primitives compose directly into the firmware update flow without modification.
- **The `pixhawk_app` Typer group** in `jetson.py` is the natural home, following the same pattern as existing `pixhawk sync` commands.

### Actionable Conclusions

- **Vendor `uploader.py`** at `src/mower_rover/pixhawk/_uploader.py` with BSD-3-Clause header noting source commit
- **Create `firmware.py`** wrapper module providing `read_running_version()`, `check_remote_version()`, `download_firmware()`, `flash_firmware()`, `wait_for_bootloader()`, `reboot_to_bootloader()`
- **Add three CLI commands** under `pixhawk_app`: `firmware-check`, `firmware-update`, `firmware-flash`
- **Use `/var/cache/mower/firmware/`** for cached .apj files
- **Default to `stable` track** with `--track` override for beta/pinned versions
- **Auto-snapshot params** before every flash (existing `write_json_snapshot`)
- **Post-flash verify** by re-reading AUTOPILOT_VERSION after reboot

### Open Questions

- The exact CubeOrange bootloader PID (`0x1011`) needs field verification via `lsusb` during an actual bootloader reboot
- USB re-enumeration timing (1s delay + 30s poll) may need tuning on actual hardware
- Whether `firmware-update` should also be available on the laptop side (SSH-tunneled) or remain Jetson-only

## Key Findings

1. PX4 bootloader protocol is a simple binary serial protocol (sync/erase/program/verify/reboot) over USB CDC ACM — ArduPilot's `uploader.py` (BSD-3-Clause, ~1200 lines) is the reference implementation
2. Cube Orange uses VID `0x2DAE`, PID `0x1016` (normal) / `0x1011` (bootloader); existing udev rule handles both
3. Parameters stored in external RAMTRON FRAM — always survive firmware flashing regardless of outcome
4. Bootloader resides in protected first 128 KB — cannot be corrupted by normal firmware operations
5. firmware.ardupilot.org provides `firmware-version.txt` (37 bytes) for cheap version checks and `.apj` files for flashing
6. AUTOPILOT_VERSION.flight_sw_version encodes version as `major<<24 | minor<<16 | patch<<8 | type`
7. No new dependencies required — pyserial, pymavlink, urllib.request all already available
8. All safety primitives (SafetyContext, param snapshot, armed check, confirmation) already exist in the codebase

## Actionable Conclusions

1. Vendor `uploader.py` at `src/mower_rover/pixhawk/_uploader.py` with license header
2. Create `src/mower_rover/pixhawk/firmware.py` wrapper module (version decode, download, flash, wait-for-bootloader)
3. Add CLI commands: `pixhawk firmware-check`, `pixhawk firmware-update`, `pixhawk firmware-flash`
4. Use `/var/cache/mower/firmware/` for offline firmware cache
5. Default to `stable` track; support `--track` override and `--version` pinning
6. Auto-snapshot params before every flash; auto-verify version after reboot
7. The `firmware-flash` command provides the field-offline path (takes a local .apj path directly)

## Open Questions

- Verify CubeOrange bootloader PID (`0x1011`) with `lsusb` during actual bootloader reboot
- Tune USB re-enumeration timing (1s delay + 30s poll) on actual hardware
- Decide whether `firmware-update` should also be available laptop-side (SSH-tunneled)

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-05 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/021-jetson-pixhawk-firmware-update.md |
