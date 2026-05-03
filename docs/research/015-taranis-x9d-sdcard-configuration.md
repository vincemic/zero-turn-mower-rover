---
id: "015"
type: research
title: "Taranis X9D Plus SD Card — Configuration Capture & Artifact Inventory"
status: ✅ Complete
created: "2026-04-28"
current_phase: "✅ Complete"
---

## Introduction

The operator's FrSky Taranis X9D Plus transmitter SD card (drive `D:\`) has been connected for inspection. This research catalogues the card's contents, identifies significant configuration artifacts (OpenTX version, firmware images, Yaapu telemetry configs, model definitions, Lua scripts, and logs), and determines what should be captured into the repo for reproducibility. The Taranis is the manual-override / at-handset-telemetry device per the project hardware stack; preserving its configuration supports disaster recovery and the RC failsafe research that is still pending.

## Objectives

- Inventory the full SD card directory structure and identify every non-stock / operator-modified artifact
- Determine the OpenTX firmware version and SD card content pack version in use
- Capture Yaapu telemetry script configuration (`mow.cfg`, `mow2.cfg`, sensor files) and understand the configured display layout
- Identify the model binary (`mow-2002-07-11.bin`) and determine what metadata can be extracted without OpenTX Companion
- Catalogue firmware images on the card (OpenTX `.bin`/`.dfu`, FrSky receiver `.frk`) and note version/region info
- Identify any telemetry logs and assess their content / value
- Recommend which artifacts to capture into the repo and in what format (verbatim copy vs parsed config)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | SD Card Structure & Version Inventory | ✅ Complete | Full directory tree; OpenTX version (`2.3V0026`); SD content pack version (`sdcard-taranis-x9-2.2-20180525`); firmware binaries inventory; stock vs custom file identification | 2026-04-28 |
| 2 | Yaapu Telemetry Configuration Deep-Dive | ✅ Complete | Parse `mow.cfg` / `mow2.cfg` key-value pairs; map config keys to Yaapu display features; analyse `yaapuprod_sensors.lua` custom sensor definitions; identify rover-specific vs example-only sensor files; determine Yaapu version from compiled `.luac` headers | 2026-04-28 |
| 3 | Model Binary & Log Analysis | ✅ Complete | Inspect `MODELS/mow-2002-07-11.bin` structure; determine if channel maps, switch assignments, or mixer config can be extracted without OpenTX Companion; inspect `LOGS/mow-20201126_130119.plog` for telemetry data format and content; check `EEPROMS/` and `EEPROM/` for backup data | 2026-04-28 |
| 4 | Artifact Capture Plan & Repo Integration | ✅ Complete | Decide which files to copy verbatim into `config/taranis/` (or similar); propose directory layout in the repo; identify files that need parsing/documentation vs raw copy; draft a manifest listing every captured artifact with provenance; note any files that should NOT be committed (large binaries, stock sound packs, BMP libraries) | 2026-04-28 |

## Phase 1: SD Card Structure & Version Inventory

**Status:** ✅ Complete  
**Session:** 2026-04-28

### SD Card Overview

| Metric | Value |
|--------|-------|
| Total files | 5,093 |
| Total size | 291.63 MB |
| SOUNDS (stock voice packs) | 2,538 files / 157.11 MB |
| BMP (stock model images) | 342 files / 0.38 MB |
| Stock backup (`sdcard-taranis-x9-2.2-20180525/`) | 2,066 files / 131.68 MB |
| Operator-significant artifacts | ~30 files / < 2 MB |

The card is dominated by stock sound packs (multi-language: cz, de, en, es, fr, it, pt, ru) and a complete copy of the **original 2.2 SD card content pack** that was retained when the card was upgraded to 2.3.

### OpenTX & SD Card Pack Versions

| Item | Value | Evidence |
|------|-------|----------|
| **OpenTX SD card version** | `2.3V0026` | `D:\opentx.sdcard.version` (9 bytes, dated 2020-05-07) |
| **Original SD card pack** | `2.2V0016` | `D:\sdcard-taranis-x9-2.2-20180525\opentx.sdcard.version` |
| **Original pack date** | 2018-05-25 | Directory name `sdcard-taranis-x9-2.2-20180525` |
| **Upgrade date** | ~2020-05-07 | Timestamps on 2.3 stock files all show `05/07/2020 14:14:52` |

The card was originally populated with the OpenTX 2.2 content pack from 2018-05-25, then upgraded to OpenTX 2.3 (V0026) on approximately 2020-05-07. The old 2.2 pack was preserved as-is in the `sdcard-taranis-x9-2.2-20180525/` directory.

### Top-Level Directory Structure

```
D:\
├── BMP/                          # Stock model bitmap images (342 files)
├── CROSSFIRE/                    # TBS Crossfire Lua scripts (stock)
├── EEPROM/                       # EEPROM backup directory (readme only)
├── EEPROMS/                      # Legacy EEPROM backup directory (empty)
├── FIRMWARE/                     # OpenTX + receiver firmware images
├── FIRMWARES/                    # Legacy firmware directory (duplicates)
├── IMAGES/                       # Model images (readme only)
├── LOGS/                         # Telemetry logs (1 plog file)
├── MODELS/                       # Model binaries + Yaapu configs
│   ├── mow-2002-07-11.bin        # <-- OPERATOR MODEL
│   ├── readme.txt
│   └── yaapu/                    # Yaapu per-model config & sensors
│       ├── mow.cfg               # <-- OPERATOR CONFIG
│       ├── mow2.cfg              # <-- OPERATOR CONFIG
│       ├── yaapuprod.cfg          # Empty (0 bytes)
│       ├── yaapuprod_sensors.lua  # Stock example (cell monitoring)
│       ├── cels_example_sensors.lua
│       └── kerojet_example_sensors.lua
├── SCREENSHOTS/                  # Screenshot directory (readme only)
├── SCRIPTS/                      # Lua scripts
│   ├── FUNCTIONS/                # Custom function scripts (readme only)
│   ├── GAMES/                    # snake.lua (stock 2014 vintage)
│   ├── MIXES/                    # Custom mixer scripts (readme only)
│   ├── MODEL01/                  # Per-model telemetry (stock examples)
│   ├── TELEMETRY/                # Telemetry screen scripts
│   │   ├── yaapu7.lua            # Yaapu 7-column (compiled .luac in .lua)
│   │   ├── yaapu7.luac           # Yaapu 7-column bytecode
│   │   ├── yaapu9.lua            # Yaapu 9-column (compiled .luac in .lua)
│   │   ├── yaapu9.luac           # Yaapu 9-column bytecode
│   │   └── yaapu/                # Yaapu sub-modules (all .luac)
│   ├── TEMPLATES/                # (empty)
│   ├── TOOLS/                    # Tool scripts (Yaapu Debug, FrSky, etc.)
│   └── WIZARD/                   # Model setup wizard (stock)
├── SOUNDS/                       # Voice packs (8 languages + Yaapu sounds)
│   ├── cz/ de/ en/ es/ fr/ it/ pt/ ru/  # Stock language packs
│   └── yaapu0/                   # Yaapu flight-mode voice alerts
│       ├── de/ en/ fr/ it/       # 4 languages
├── SxR/                          # FrSky SxR stabiliser scripts
├── SxR Calibrate/                # SxR calibration tool
├── sdcard-taranis-x9-2.2-20180525/  # FULL BACKUP of original 2.2 pack
└── opentx.sdcard.version         # "2.3V0026"
```

### Firmware Binary Inventory

**`D:\FIRMWARE\` (active firmware directory):**

| File | Size | Date | Description |
|------|------|------|-------------|
| `optx.bin` | 417,360 b | 2020-05-07 | OpenTX 2.3 transmitter firmware binary |
| `x9dpNonEU_mode2_20180525.bin` | 383,496 b | 2018-06-04 | OpenTX 2.2 transmitter firmware (NonEU/FCC, Mode 2) |
| `x9dpNonEU_mode2_20180525.dfu` | 383,805 b | 2018-06-04 | Same as above, DFU format for STM32 bootloader flashing |
| `X8R_FCC_180322.frk` | 67,584 b | 2019-06-25 | FrSky X8R receiver firmware, FCC region, dated 2018-03-22 |
| `X8R_ACCST_2.1.0_FCC.frk` | 63,488 b | 2022-05-13 | FrSky X8R receiver firmware, ACCST 2.1.0, FCC — **newest file on card** |

**`D:\FIRMWARES\` (legacy directory — duplicates):**

| File | Size | Date | Description |
|------|------|------|-------------|
| `new.bin` | 383,496 b | 2018-06-04 | Same size as `x9dpNonEU_mode2_20180525.bin` — likely a copy |
| `optx.bin` | 417,360 b | 2020-05-07 | Duplicate of `FIRMWARE\optx.bin` |

**Key observations:**
- The transmitter firmware filename (`x9dpNonEU_mode2_20180525`) confirms: **Taranis X9D Plus, Non-EU (FCC) region, Mode 2 (throttle left)**.
- `optx.bin` (417 KB) is the newer OpenTX 2.3 firmware; the 383 KB images are the original 2.2 firmware.
- Two X8R receiver firmware images present — the `ACCST_2.1.0_FCC` version (2022) is the most recent file on the entire SD card, indicating the operator last updated the X8R receiver firmware.
- The presence of X8R firmware confirms the operator has (or had) an **FrSky X8R receiver**, which is an 8-channel ACCST D16 Full-Range receiver with S.Port telemetry.

### Stock vs Operator-Modified File Classification

**Operator-created / modified files:**

| File | Evidence | Significance |
|------|----------|--------------|
| `MODELS/mow-2002-07-11.bin` | Named "mow", only model on card | **The mower model definition** — contains channel maps, mixes, switch assignments |
| `MODELS/yaapu/mow.cfg` | Named "mow", dated 2022-07-11 | Yaapu telemetry config for the mow model |
| `MODELS/yaapu/mow2.cfg` | Named "mow2", dated 2022-08-31 | Second Yaapu config (possibly for a different telemetry page or layout variant) |
| `LOGS/mow-20201126_130119.plog` | Yaapu passthrough telemetry log | Captured telemetry session from 2020-11-26 |
| `FIRMWARE/X8R_ACCST_2.1.0_FCC.frk` | Newest file (2022) | Operator downloaded this receiver firmware |
| `FIRMWARE/X8R_FCC_180322.frk` | Older X8R firmware | Operator-added |

**Stock files (from SD card content packs):**

| Category | Source |
|----------|--------|
| All SOUNDS/ wav files | OpenTX 2.3 V0026 content pack |
| All BMP/ images | OpenTX 2.3 V0026 content pack |
| SCRIPTS/WIZARD/, SCRIPTS/GAMES/ | OpenTX 2.3 V0026 content pack |
| SCRIPTS/TOOLS/ (FrSky *.lua) | OpenTX 2.3 V0026 content pack |
| CROSSFIRE/, SxR/, SxR Calibrate/ | OpenTX 2.3 V0026 content pack |
| readme.txt files | OpenTX 2.3 V0026 content pack |
| `opentx.sdcard.version` | OpenTX 2.3 V0026 content pack |
| `MODELS/yaapu/yaapuprod_sensors.lua` | Yaapu distribution (same as `cels_example_sensors.lua`) |
| `MODELS/yaapu/cels_example_sensors.lua` | Yaapu distribution example |
| `MODELS/yaapu/kerojet_example_sensors.lua` | Yaapu distribution example |
| `MODELS/yaapu/yaapuprod.cfg` | Empty, Yaapu distribution default |

**Yaapu telemetry script files (added during upgrade, not modified):**

| Category | Files |
|----------|-------|
| Yaapu main scripts | `SCRIPTS/TELEMETRY/yaapu7.lua`, `yaapu7.luac`, `yaapu9.lua`, `yaapu9.luac` |
| Yaapu sub-modules | `SCRIPTS/TELEMETRY/yaapu/*.luac` (15 files: view, draw, hud, menu, etc.) |
| Yaapu sounds | `SOUNDS/yaapu0/` (4 languages: de, en, fr, it) |
| Yaapu debug tool | `SCRIPTS/TOOLS/Yaapu Debug.lua`, `.luac` |

### Yaapu Telemetry Version

Extracted from compiled bytecode string table in `yaapu9.luac`:

> **Yaapu X9 telemetry script 1.8.0**

All Yaapu `.luac` files are dated `2020-05-07 13:55:28` — installed as part of the 2.3 upgrade session.

### Model Binary Header

The model binary `mow-2002-07-11.bin` (482 bytes) starts with magic bytes `6F 74 78 33` = ASCII **"otx3"**, confirming it is an **OpenTX v3 model format** (used by OpenTX 2.3.x). The file is very small (482 bytes), indicating a minimal model with few customizations. Full extraction requires OpenTX Companion (Phase 3 topic).

The filename date `2002-07-11` is an RTC artifact — the Taranis X9D Plus has no battery-backed RTC by default, so dates on files created by the radio itself are unreliable. The `LastWriteTime` shows `07/11/2002 17:10:56`, which is almost certainly a default/bogus date.

### Telemetry Log (plog)

`LOGS/mow-20201126_130119.plog` (4,497 bytes) is a Yaapu passthrough telemetry log in CSV format:

```
counter;f_time;data_id;value
20831;0;20486;897923
20831;0;20488;525463
...
```

The `data_id` values (0x5006 = 20486, 0x5008 = 20488, etc.) are ArduPilot passthrough telemetry packet IDs. This log was captured on 2020-11-26 and contains raw S.Port passthrough data. Full analysis in Phase 3.

**Key Discoveries:**
- OpenTX version is **2.3 V0026** (upgraded from 2.2 V0016 circa 2020-05-07)
- Yaapu telemetry script version is **1.8.0** (all compiled Lua bytecode, not source)
- Transmitter is confirmed **X9D Plus, FCC/Non-EU region, Mode 2**
- Receiver firmware on card is for **FrSky X8R** (ACCST D16), latest version ACCST 2.1.0 FCC
- Model binary uses **otx3** format (OpenTX 2.3 model format), only 482 bytes
- The card retains a **full backup** of the original 2.2 SD card pack (131 MB)
- Only ~6 files are genuinely operator-created: 1 model binary, 2 Yaapu configs, 1 telemetry log, 2 receiver firmware images
- `yaapuprod_sensors.lua` is identical to `cels_example_sensors.lua` — it's the **stock cell monitoring example**, not a rover-specific sensor file

| File | Relevance |
|------|-----------|
| `D:\opentx.sdcard.version` | Version identification — `2.3V0026` |
| `D:\sdcard-taranis-x9-2.2-20180525\opentx.sdcard.version` | Original version — `2.2V0016` |
| `D:\MODELS\mow-2002-07-11.bin` | Operator's mower model definition (otx3 format) |
| `D:\MODELS\yaapu\mow.cfg` | Yaapu config for the mow model |
| `D:\MODELS\yaapu\mow2.cfg` | Alternate Yaapu config |
| `D:\MODELS\yaapu\yaapuprod_sensors.lua` | Custom sensor definitions (stock example) |
| `D:\FIRMWARE\X8R_ACCST_2.1.0_FCC.frk` | Latest receiver firmware on card |
| `D:\LOGS\mow-20201126_130119.plog` | Passthrough telemetry log |
| `D:\SCRIPTS\TELEMETRY\yaapu9.luac` | Yaapu v1.8.0 main telemetry script |

**External Sources:**
- none (all findings from direct SD card inspection)

**Gaps:** None — full directory tree and all key files inspected.  
**Assumptions:** The RTC date on `mow-2002-07-11.bin` (2002-07-11) is a bogus date from a non-battery-backed RTC, not the actual creation date. The actual creation date is unknown but likely between 2020 and 2022 based on the Yaapu config file dates.

## Phase 2: Yaapu Telemetry Configuration Deep-Dive

**Status:** ✅ Complete  
**Session:** 2026-04-28

### Configuration File Format

The Yaapu telemetry script stores per-model configuration at `/MODELS/yaapu/<modelname>.cfg` on BW LCD radios (Taranis). The config filename is derived from the OpenTX model name by stripping all control characters, punctuation, spaces, and null bytes:

```lua
local function getConfigFilename()
  local info = model.getInfo()
  return "/MODELS/yaapu/" .. string.gsub(info.name, "[%c%p%s%z]", "")..".cfg"
end
```

This means the model is named **"mow"** in OpenTX (yielding `mow.cfg`). The `mow2.cfg` file suggests either a second model named "mow2" or a manually duplicated config for experimentation.

The config format is a single-line comma-separated list of `KEY:VALUE` pairs. Values are always integers. The parsing uses regex: `menuItems[i][2]..":([-%d]+)"`.

### Complete Config Key Mapping

Derived from the BW 212x64 `menu9.lua` source code — the exact variant used on the Taranis X9D Plus (212×64 BW LCD). Values from `mow.cfg` interpreted against the `menuItems` array:

| Config Key | Value | Menu Label | Interpretation |
|------------|-------|------------|----------------|
| `L1` | `1` | "voice language:" | **English** (1=en, 2=it, 3=fr, 4=de) |
| `V1` | `375` | "batt alert level 1:" | **3.75 V/cell** (PREC2: value/100, warning) |
| `V2` | `350` | "batt alert level 2:" | **3.50 V/cell** (PREC2: value/100, critical) |
| `B1` | `0` | "batt[1] capacity override:" | **Disabled** (use ArduPilot-reported capacity) |
| `B2` | `0` | "batt[2] capacity override:" | **Disabled** |
| `S1` | `1` | "disable all sounds:" | **No** — sounds ENABLED (1=no, 2=yes) |
| `S2` | `1` | "disable msg beep:" | **No** — message beep ENABLED (1=no, 2=info, 3=all) |
| `VIBR` | `1` | "enable haptic:" | **No** — haptic DISABLED (1=no, 2=yes) |
| `VS` | `1` | "default voltage source:" | **Auto** (1=auto, 2=FLVSS, 3=fc) |
| `BC` | `1` | "dual battery config:" | **Parallel** (1=par, 2=ser, 3=other-1, 4=other-2) |
| `CC` | `0` | "batt[1] cell count override:" | **Disabled** (auto-detect, range 0–16) |
| `CC2` | `0` | "batt[2] cell count override:" | **Disabled** |
| `T1` | `0` | "timer alert every:" | **Disabled** (no periodic timer vocal alert) |
| `A1` | `0` | "min altitude alert:" | **Disabled** |
| `A2` | `0` | "max altitude alert:" | **Disabled** |
| `D1` | `0` | "max distance alert:" | **Disabled** |
| `T2` | `10` | "repeat alerts every:" | **10 seconds** (alert repetition period) |
| `RM` | `0` | "rangefinder max:" | **Disabled** (rangefinder display off) |
| `HSPD` | `1` | "air/groundspeed unit:" | **m/s** (1=m/s, 2=km/h, 3=mph, 4=kn) |
| `VSPD` | `1` | "vertical speed unit:" | **m/s** (1=m/s, 2=ft/s, 3=ft/min) |
| `CPANE` | `1` | "center panel layout:" | **Default** (full HUD with artificial horizon) |
| `RPANE` | `1` | "right panel layout:" | **Default** (battery info) |
| `LPANE` | `1` | "left panel layout:" | **Default** (GPS/home info) |
| `AVIEW` | `1` | "alternate view layout:" | **Default** (custom sensors / GPS coords) |
| `PX4` | `1` | "enable px4 flightmodes:" | **No** — PX4 modes DISABLED (correct for ArduPilot) |

**Notable absent key:** `CRSF` — not present. Defaults to "no" (CRSF disabled), correct since the operator uses FrSky S.Port protocol.

### Display Layout Analysis

Based on the configuration, the Taranis X9D Plus displays:

- **Center Panel** (`hud9`): Full artificial horizon with roll, pitch, yaw. Numeric compass heading. VSI at bottom. Altitude on right side of HUD.
- **Right Panel** (`right9`): Battery voltage, current, capacity %. GPS status (fix type, HDop, sat count). Home distance.
- **Left Panel** (`left9`): Flight mode. Armed/disarmed status. RSSI. Transmitter voltage. Flight time (Timer 3).
- **Alternate View** (`alt9_view`): Accessible via short ENTER press — shows custom sensor values (if configured) and GPS coordinates.

All panels use **default** layouts — no customization was applied.

### PX4:1 Setting — Correct for ArduPilot Rover

`PX4:1` means PX4 flight modes are **DISABLED**. This is **correct** for ArduPilot Rover. When PX4 mode is enabled, the script loads PX4-specific flight mode decoders (for MavToPT/Teensy firmware). With PX4 disabled, the standard ArduPilot decoder correctly interprets Rover modes (Manual, Acro, Steering, Hold, Loiter, Follow, Simple, Auto, RTL, SmartRTL, Guided). **No action needed.**

### Sensor File Analysis

**Sensor file naming convention:** The script looks for `<modelname>_sensors.lua` matching the config file name.

**Critical finding: No `mow_sensors.lua` exists.** The custom sensors alternate view screen shows nothing for the "mow" model.

| File | Purpose | Active for "mow"? |
|------|---------|-------------------|
| `yaapuprod_sensors.lua` | Stock FLVSS cell monitoring example | ❌ Not linked to "mow" |
| `cels_example_sensors.lua` | Same as above (example copy) | ❌ Example only |
| `kerojet_example_sensors.lua` | Kerojet engine sensor example | ❌ Example only |

**`yaapuprod_sensors.lua` content:** Defines 6 sensors — all LiPo cell voltage monitoring from an FLVSS sensor (Celm, Celd, Cel1–Cel4). Identical to `cels_example_sensors.lua`. This was distributed with Yaapu 1.8.0 and **never customized** for the rover.

### Recommended Rover-Specific Sensors

To make the custom sensors display useful, a `mow_sensors.lua` file could be created with:

| Sensor # | Label | OpenTX Sensor | Rationale |
|----------|-------|---------------|-----------|
| 1 | GSpd | GSpd | Ground speed — critical for mowing |
| 2 | Hdg | Hdg | Heading — monitoring direction |
| 3 | Alt | Alt | Altitude — GPS quality validation |
| 4 | VSpd | VSpd | Vertical speed — terrain changes |
| 5 | VFAS | VFAS | Battery voltage (min tracking) |
| 6 | Fuel | Fuel | Battery remaining % |

Future additions once engine monitoring is operational: RPM from inductive pickup, engine status.

### Config File Duplication

Both `mow.cfg` and `mow2.cfg` are **byte-identical** (149 bytes, same content). They differ only in date:
- `mow.cfg`: 2022-07-11
- `mow2.cfg`: 2022-08-31

The operator likely created a second OpenTX model named "mow2" for testing different mixer/channel settings while keeping the same Yaapu display preferences.

**Key Discoveries:**
- All 25 config keys mapped to exact Yaapu display features with option values — config uses all defaults
- Both `mow.cfg` and `mow2.cfg` are byte-identical — same Yaapu settings for two OpenTX models
- PX4:1 = PX4 modes disabled — correct for ArduPilot Rover, no action needed
- **No `mow_sensors.lua` exists** — the custom sensors alternate view shows nothing for the "mow" model
- `yaapuprod_sensors.lua` is a stock FLVSS cell monitoring example — never customized for rover
- Battery alerts at 3.75V (warning) / 3.50V (critical) per cell — standard LiPo thresholds
- CRSF absent from config — confirms FrSky S.Port protocol (matches X8R hardware)
- Config path derived from model name confirms OpenTX model names are "mow" and "mow2"

| File | Relevance |
|------|-----------|
| `D:\MODELS\yaapu\mow.cfg` | Primary Yaapu config, 25 key-value pairs, all defaults |
| `D:\MODELS\yaapu\mow2.cfg` | Duplicate config (identical, different date) |
| `D:\MODELS\yaapu\yaapuprod_sensors.lua` | Stock FLVSS example, not linked to "mow" model |
| GitHub `menu9.lua` | Authoritative menu item definitions for BW 212x64 |

**External Sources:**
- [Yaapu FrSky Telemetry Script](https://github.com/yaapu/FrskyTelemetryScript) — main repo + wiki
- [Configuration menu wiki](https://github.com/yaapu/FrskyTelemetryScript/wiki/Configuration-menu)
- [Custom sensors wiki](https://github.com/yaapu/FrskyTelemetryScript/wiki/Support-for-user-selected-Frsky-sensors)

**Gaps:** None  
**Assumptions:** BW 212x64 variant (menu9.lua) matches X9D Plus hardware (212×64 pixel resolution). Config key indexing is consistent between 1.8.0 and current source.

## Phase 3: Model Binary & Log Analysis

**Status:** ✅ Complete  
**Session:** 2026-04-28

### Model Binary Analysis (`D:\MODELS\mow-2002-07-11.bin`)

#### File Format — Confirmed from OpenTX Source

The file uses the **OpenTX SD card model backup format** as defined in `radio/src/storage/sdcard_raw.cpp`:

| Offset | Size | Value | Meaning |
|--------|------|-------|---------|
| 0–3 | 4 bytes | `6F 74 78 33` ("otx3") | `OTX_FOURCC` — `0x3378746F` = Taranis X9D/X9D+ |
| 4 | 1 byte | `DA` (218) | `EEPROM_VER` — data format version 218 (OpenTX 2.2.x–2.3.x) |
| 5 | 1 byte | `4D` ('M') | Model file marker (vs 'G' for general settings) |
| 6–7 | 2 bytes LE | `DA 01` (474) | Model data size in bytes |
| 8–481 | 474 bytes | (raw struct) | Serialized `ModelData` struct |

**Total: 8-byte header + 474 bytes model data = 482 bytes** — matches exactly.

The board FOURCC byte (`33` = '3') uniquely identifies **Taranis X9D / X9D Plus**. Version 218 = OpenTX 2.2.x–2.3.x era format.

#### Model Name

Backup filename pattern: `{modelname}-{YYYY}{MM}{DD}.bin`. Model name = **"mow"**, backup date = 2002-07-11 (bogus RTC).

#### Extraction Without OpenTX Companion — Verdict

The 474-byte model data is a **tightly bit-packed serialized struct** with:
- **Bit-level packing** — Fields like `BoolField<1>`, `UnsignedField<3>`, `SwitchField<9>`
- **Board-conditional layout** — Field order/sizes differ between 20+ board types
- **Version-conditional layout** — Different serialization for versions 216–219+
- **Custom character encoding** — `ZCharField` uses a non-ASCII alphabet

**No standalone CLI tool or Python library exists** for parsing `.bin` model files. The canonical decoder is **OpenTX Companion** (or EdgeTX Companion), which has ~600 lines of conditional bit-field definitions in `companion/src/firmwares/opentx/opentxeeprom.cpp`.

**Recommendation:** Open `mow-2002-07-11.bin` in OpenTX Companion 2.3.x (select Taranis X9D Plus profile) to extract channel maps, switch assignments, and mixer config.

> **UPDATE (2026-04-28):** The model binary was successfully decoded. The operator's `mower.otx` (Companion export) was opened in **EdgeTX Companion v2.10.5**, which converted it to `.etx` format (ZIP of YAML files). The YAML models are fully human-readable and have been committed to `config/taranis/`. See the decoded channel map and switch assignments in the Overview section and `config/taranis/README.md`. OpenTX Companion is abandoned (last release 2.3.15, April 2022); EdgeTX Companion v2.10.x is the last version that can import `.otx` files (v2.12+ dropped `.otx` support).

#### Observable Patterns in Hex Dump

| Offset Range | Pattern | Likely Content |
|--------------|---------|----------------|
| 0x08–0x1F | Non-zero mixed data | Model header (name, IDs, bitmap, timers) |
| 0x48–0x5F | Solid `0x7F` fill | Unused/default slots |
| 0xF0–0x198 | Repeating `01 04` with `56 12`/`76 12` headers | Likely **8 default mixer definitions** (stick→channel passthrough) |

---

### Telemetry Log Analysis (`D:\LOGS\mow-20201126_130119.plog`)

#### File Format

Yaapu passthrough telemetry log, 194 data rows + 1 header. Format: `counter;f_time;data_id;value`

#### Session Characteristics

| Metric | Value |
|--------|-------|
| Counter range | 20831 – 21380 (Δ549 ticks) |
| Duration | **~2.75 seconds** (549 × 5ms) |
| Time since power-on | ~104 seconds |
| Total packets | 194 |
| Packet types present | 8 of 10 possible |

#### Packet Type Distribution

| data_id | Name | Count | % |
|---------|------|-------|---|
| 20486 (0x5006) | ATTITUDE | 110 | 56.7% |
| 20485 (0x5005) | VEL_YAW | 22 | 11.3% |
| 20481 (0x5001) | AP_STATUS | 12 | 6.2% |
| 20482 (0x5002) | GPS_STATUS | 11 | 5.7% |
| 20483 (0x5003) | BATT_1 | 11 | 5.7% |
| 20484 (0x5004) | HOME | 11 | 5.7% |
| 20488 (0x5008) | BATT_2 | 11 | 5.7% |
| 20487 (0x5007) | PARAM | 6 | 3.1% |
| 20480 (0x5000) | STATUS_TEXT | 0 | — |
| 20489 (0x5009) | WAYPOINT | 0 | — |

#### Decoded Vehicle State

**AP_STATUS (0x5001) = constant:**
- Flight mode: **LOITER** (Rover mode 5)
- Armed: **Yes**
- Battery failsafe: No
- Land complete (stationary): Yes

**PARAM (0x5007) — cycled parameter IDs:**

| param_id | Value | Interpretation |
|----------|-------|----------------|
| 1 | 10 | **MAV_TYPE_GROUND_ROVER** — confirms ArduPilot Rover |
| 4 | 6000 | Battery 1 capacity: **6000 mAh** |
| 5 | 3300 | Battery 2 capacity: **3300 mAh** |

**BATT_1 (0x5003):** ~15.2V, 1A draw, 70–80 mAh consumed  
**BATT_2 (0x5008):** ~15.1–15.2V, 1A draw, 40 mAh consumed  
Both batteries at ~15.2V → **4S LiPo** (nominal 14.8V, near-full charge)

**GPS_STATUS (0x5002):** **15 satellites**, 3D fix  
**HOME (0x5004):** Distance ≈ 0m (at home), heading ~164–180° (bearing drift)  
**VEL_YAW (0x5005):** Heading ~197–201° (SSW), near-zero ground speed  
**ATTITUDE (0x5006):** Constant (level ground, stationary)

#### Inferred Vehicle Scenario

A **2.75-second snapshot of an armed ArduPilot Rover in LOITER mode**, stationary with:
- Dual 4S LiPo batteries (6000 + 3300 mAh)
- Excellent GPS (15 satellites)
- Near-zero movement at home position
- Heading ~200° (south-southwest)
- Low power draw (~1A each battery)

Consistent with a **bench test or pre-mow idle** session on 2020-11-26.

---

### EEPROM Directories — Confirmed Empty

| Directory | Contents |
|-----------|----------|
| `D:\EEPROMS\` | Empty (0 files) |
| `D:\EEPROM\` | `readme.txt` only (factory placeholder) |

**No EEPROM backup data exists on this SD card.**

**Key Discoveries:**
- Model binary confirmed as Taranis X9D/X9D+ format (FOURCC `otx3`, version 218, model name "mow")
- 474-byte model data is tightly bit-packed — **cannot be decoded without OpenTX Companion** (no CLI/Python tool exists)
- Telemetry log confirms **ArduPilot Rover** (MAV_TYPE=10) with **dual 4S batteries** (6000 + 3300 mAh)
- Vehicle was **armed in LOITER mode** with 15 GPS satellites during the 2.75-second capture
- The plog proves this transmitter was previously used with an ArduPilot Rover — confirms operator's mower project history
- No STATUS_TEXT or WAYPOINT packets — no active mission running during capture
- EEPROM backup directories are factory-empty

| File | Relevance |
|------|-----------|
| `D:\MODELS\mow-2002-07-11.bin` | OpenTX model binary (482 bytes), X9D/X9D+ format v218 |
| `D:\LOGS\mow-20201126_130119.plog` | Yaapu passthrough telemetry log (194 packets, 2.75s) |
| `D:\EEPROMS\` | Empty directory |
| `D:\EEPROM\readme.txt` | Factory placeholder only |

**External Sources:**
- [OpenTX source](https://github.com/opentx/opentx) — `sdcard_raw.cpp`, `sdcard.h`, `opentxeeprom.cpp` analyzed

**Gaps:** Exact bit-level model data decoding not attempted — requires Companion. ArduPilot passthrough bit packing may vary slightly by firmware version.  
**Assumptions:** Standard ArduPilot passthrough encoding for param_id 1=FRAME_TYPE, 4=BATT1_CAPACITY, 5=BATT2_CAPACITY.

## Phase 4: Artifact Capture Plan & Repo Integration

**Status:** ✅ Complete  
**Session:** 2026-04-28

### Repo Directory Layout

**Committed (EdgeTX YAML export):**

```
config/
└── taranis/
    ├── README.md                          # Channel map, key settings, hardware summary
    ├── RADIO/
    │   └── radio.yml                      # Radio-level settings (calibration, switches, etc.)
    └── MODELS/
        ├── model00.yml                    # Model "mow2" (active, model ID 1)
        └── model01.yml                    # Model "mow" (original, model ID 2)
```

The `.etx` directory structure (RADIO/ + MODELS/) is preserved from the EdgeTX Companion export. All files are human-readable YAML, fully diffable.

**Still to commit (when SD card is next mounted):**

```
config/
└── taranis/
    ├── MODELS/
    │   ├── mow-2002-07-11.bin             # Original OpenTX model binary (verbatim)
    │   └── yaapu/
    │       ├── mow.cfg                    # Yaapu config for "mow" model
    │       └── mow2.cfg                   # Yaapu config for "mow2" model
    ├── LOGS/
    │   └── mow-20201126_130119.plog       # Passthrough telemetry log
    └── opentx.sdcard.version              # SD card version marker
```

Follows existing repo conventions (`zones/` for YAML configs, `scripts/` for deployment). `config/taranis/` is scoped to this transmitter.

### Artifact Classification

#### Verbatim Copy (commit to repo)

| SD Card Path | Repo Path | Size | Rationale |
|--------------|-----------|------|-----------|
| `D:\MODELS\mow-2002-07-11.bin` | `config/taranis/models/mow-2002-07-11.bin` | 482 B | **The** mower model definition — unique, irreplaceable |
| `D:\MODELS\yaapu\mow.cfg` | `config/taranis/models/yaapu/mow.cfg` | 149 B | Yaapu telemetry config (text, all defaults documented) |
| `D:\MODELS\yaapu\mow2.cfg` | `config/taranis/models/yaapu/mow2.cfg` | 149 B | Second Yaapu config (byte-identical to mow.cfg) |
| `D:\LOGS\mow-20201126_130119.plog` | `config/taranis/logs/mow-20201126_130119.plog` | 4,497 B | Only telemetry log — proves Rover + dual battery config |
| `D:\opentx.sdcard.version` | `config/taranis/opentx.sdcard.version` | 9 B | Version marker for disaster recovery |

**Total verbatim: 5 files, ~5.3 KB**

#### Document-Only (record in README, do NOT commit)

| Category | SD Card Path | Size | Reason |
|----------|--------------|------|--------|
| Stock sound packs | `D:\SOUNDS\{cz,de,en,es,fr,it,pt,ru}\` | 157.1 MB | From OpenTX 2.3V0026 content pack |
| Stock BMP images | `D:\BMP\` | 0.39 MB | From content pack |
| Old 2.2 backup | `D:\sdcard-taranis-x9-2.2-20180525\` | 131.7 MB | Superseded by 2.3 |
| OpenTX firmware | `D:\FIRMWARE\*.bin`, `*.dfu` | ~1.2 MB | Re-downloadable |
| FrSky X8R firmware | `D:\FIRMWARE\*.frk` | ~128 KB | Re-downloadable (document version: ACCST 2.1.0 FCC) |
| Compiled Yaapu scripts | `D:\SCRIPTS\TELEMETRY\yaapu*` | ~172 KB | Reinstall from Yaapu v1.8.0 release |
| Yaapu voice sounds | `D:\SOUNDS\yaapu0\` | (subset) | Part of Yaapu distribution |
| Legacy firmware dupes | `D:\FIRMWARES\` | ~782 KB | Duplicates of `D:\FIRMWARE\` |
| Stock scripts/tools | `D:\CROSSFIRE\`, `D:\SxR\*`, `D:\SCRIPTS\{WIZARD,GAMES,TOOLS}\` | (stock) | From content pack |
| Empty directories | `D:\EEPROM\`, `D:\EEPROMS\`, `D:\SCREENSHOTS\`, `D:\IMAGES\` | 0 | No data |
| Stock sensor examples | `D:\MODELS\yaapu\{yaapuprod,cels_example,kerojet_example}*` | ~11 KB | Yaapu examples, never customized |

**Total excluded: ~289 MB (99.8% of SD card content)**

#### Parse + Document (extract info into README, do not commit)

| SD Card Path | What to Extract |
|--------------|-----------------|
| `yaapuprod_sensors.lua` | Note as stock FLVSS cell monitoring example, not customized for rover |
| Yaapu `.luac` files | Document version (1.8.0) and file list |
| Firmware binaries | Document exact versions and download sources |

### Disaster Recovery Recipe

**To reconstruct the SD card from scratch:**

1. **Download OpenTX 2.3.x SD card content pack** from [OpenTX downloads](https://downloads.open-tx.org/2.3/release/sdcard/) — `sdcard-taranis-x9-2.3V0026.zip`
2. **Format SD card** as FAT32 (≥2 GB)
3. **Extract content pack** to SD card root
4. **Install Yaapu v1.8.0** from [Yaapu releases](https://github.com/yaapu/FrskyTelemetryScript/releases):
   - `yaapu7.lua`, `yaapu9.lua`, `*.luac` → `SCRIPTS/TELEMETRY/`
   - `yaapu/` submodules → `SCRIPTS/TELEMETRY/yaapu/`
   - Sounds → `SOUNDS/yaapu0/`
   - Debug tool → `SCRIPTS/TOOLS/`
5. **Restore operator files from repo:**
   - `config/taranis/models/mow-2002-07-11.bin` → `SD:\MODELS\`
   - `config/taranis/models/yaapu/mow.cfg` → `SD:\MODELS\yaapu\`
   - `config/taranis/models/yaapu/mow2.cfg` → `SD:\MODELS\yaapu\`
   - `config/taranis/opentx.sdcard.version` → `SD:\`
6. **Optionally restore telemetry log:** `config/taranis/logs/*.plog` → `SD:\LOGS\`
7. **Firmware (if needed):** Download from OpenTX/FrSky:
   - TX firmware: `optx.bin` from OpenTX 2.3.x → `FIRMWARE/`
   - X8R receiver: `X8R_ACCST_2.1.0_FCC.frk` from FrSky → `FIRMWARE/`

**Critical:** The model binary is the ONLY truly irreplaceable file. Everything else can be re-downloaded.

### README.md Content Outline

The `config/taranis/README.md` should contain:
1. Hardware summary (X9D Plus, FCC, Mode 2, OpenTX 2.3, Yaapu 1.8.0)
2. Artifact manifest (table of committed files with provenance)
3. Decoded `mow.cfg` configuration reference (from Phase 2)
4. Software versions (SD card content pack, Yaapu, firmware)
5. Stock files NOT committed (categories with download links)
6. Disaster recovery recipe (above)
7. Telemetry log summary (decoded session from Phase 3)
8. Model binary notes (format info, Companion required for full decode)

### .gitignore

No `.gitignore` changes needed — the committed set is explicit and small (5 files, 5.3 KB).

**Key Discoveries:**
- Only **5 files (5.3 KB)** warrant commit — 99.8% of the SD card is stock/re-downloadable
- `config/taranis/` is the right repo path, mirroring SD card hierarchy
- The model binary (482 bytes) is the **only truly irreplaceable artifact**
- Disaster recovery achievable from 3 download sources + 5 repo files
- `config/taranis/README.md` serves triple duty: manifest, config reference, recovery guide
- No `.gitignore` changes needed

| File | Relevance |
|------|-----------|
| `D:\MODELS\mow-2002-07-11.bin` | Only irreplaceable artifact (commit) |
| `D:\MODELS\yaapu\mow.cfg` | Config to commit (149 B) |
| `D:\MODELS\yaapu\mow2.cfg` | Config to commit (149 B) |
| `D:\LOGS\mow-20201126_130119.plog` | Historical log to commit (4.5 KB) |
| `D:\opentx.sdcard.version` | Version marker to commit (9 B) |

**External Sources:**
- [OpenTX SD card content packs](https://downloads.open-tx.org/2.3/release/sdcard/)
- [Yaapu telemetry script releases](https://github.com/yaapu/FrskyTelemetryScript/releases)
- [FrSky X8R receiver downloads](https://www.frsky-rc.com/product/x8r/)

**Gaps:** None  
**Assumptions:** `config/` as new top-level directory is acceptable. Operator prefers documentation-heavy approach over committing re-downloadable binaries.

## Overview

The operator's Taranis X9D Plus SD card (D:\) contains 5,093 files / 291 MB, of which **99.8% is stock content** from the OpenTX 2.3V0026 SD card content pack, Yaapu telemetry script v1.8.0, and a retained backup of the original OpenTX 2.2V0016 pack. Only **6 operator-created files** exist: one 482-byte model binary ("mow"), two byte-identical Yaapu config files (all defaults), one 2.75-second passthrough telemetry log confirming ArduPilot Rover operation, and two FrSky X8R receiver firmware images. The Yaapu custom sensors feature is unused — no `mow_sensors.lua` exists — and the `yaapuprod_sensors.lua` on the card is an unmodified stock example.

The telemetry log conclusively proves prior ArduPilot Rover use: MAV_TYPE=10, armed in LOITER mode with 15 GPS satellites, dual 4S LiPo batteries (6000 + 3300 mAh), and an FrSky X8R receiver providing S.Port passthrough telemetry.

The original model binary (otx3 format, bit-packed, version 218) was converted from `mower.otx` (OpenTX Companion export) to **EdgeTX YAML** via EdgeTX Companion v2.10.5 (`mower.etx`). The YAML models are now fully decoded and version-controlled. Both models ("mow" and "mow2") are 10-channel, XJT D16, with a clear safety architecture: **SF is the arm switch** (gates steering and mode channels), **SA is a safety interlock** on critical functions (input gated by `!SA2`), and model "mow2" has a dedicated **"cut" input on SD** for engine kill / blade disengage. Both models use the Yaapu v1.8.0 telemetry script (`yaapu9`) on the main screen.

For repo integration, the EdgeTX YAML exports (3 files: `radio.yml`, `model00.yml`, `model01.yml`) plus a README have been committed to `config/taranis/` — **4 files, 1,136 lines**, fully human-readable and diffable. The SD card can be fully reconstructed from 3 public download sources (OpenTX content pack, Yaapu release, FrSky firmware) plus the committed files.

## Key Findings

1. **OpenTX 2.3 V0026** on the card, upgraded from 2.2 V0016 circa 2020-05-07; **Yaapu 1.8.0** telemetry scripts installed as compiled bytecode
2. **Transmitter: X9D Plus, FCC/Non-EU region, Mode 2** — confirmed by firmware filename, FOURCC header, and EdgeTX radio.yml (`board: x9d+`)
3. **Receiver firmware: FrSky X8R, ACCST 2.1.0 FCC** — the newest file on the card (2022-05-13)
4. **Model binary fully decoded via EdgeTX Companion v2.10.5** — converted from `.otx` to `.etx` (YAML), channel maps and switch assignments now documented
5. **10-channel model with clear safety architecture:** SF (2-pos) = arm switch gating CH1/CH2/CH5; SA = safety interlock on critical inputs; "cut" input on SD in model mow2
6. **Channel map decoded:** CH1=left steer (Ail, SF-gated), CH2=right steer (Rud, SF-gated), CH3=throttle, CH4=elevator, CH5=flight mode (SG 3-pos, SF-gated), CH6=SC, CH7=SF, CH8=SB, CH9=SA, CH10=SH (momentary)
7. **Internal module: XJT PXX1, D16 protocol, 16 channels** — failsafe mode NOPULSES, RSSI alarms at 45/42
8. **Yaapu config uses all defaults** — English, m/s, default HUD panels, battery alerts at 3.75/3.50 V/cell, PX4 disabled (correct for ArduPilot)
9. **No custom sensor file exists** (`mow_sensors.lua` missing) — the alternate view custom sensors screen is unused
10. **Telemetry log proves ArduPilot Rover** — MAV_TYPE=10, dual 4S batteries (6000+3300 mAh), armed in LOITER, 15 sats
11. **ArduPilot config confirmed from Pixhawk params (2026-05-01):** skid-steer (`FRAME_CLASS=1`, `SERVO1_FUNCTION=73`, `SERVO3_FUNCTION=74`), `MODE_CH=9` (SA switch, NOT CH5/SG as inferred from Taranis model labeling), `RC7_OPTION=153` (arm/disarm confirmed), `RC_PROTOCOLS=1` (SBUS), `SERIAL2_PROTOCOL=10` (FrSky S.Port passthrough at 57600 baud)
12. **Two models confirmed:** "mow" (model01, ID 2) and "mow2" (model00, ID 1, active) — nearly identical, differ only in rudder trim (6 vs 10) and mow2's extra "cut" input
13. **EdgeTX YAML committed to repo** — `config/taranis/` with radio.yml + two model YAMLs + README (4 files, 1136 lines)

## Actionable Conclusions

- ✅ **DONE — EdgeTX YAML committed to `config/taranis/`**: radio.yml, model00.yml (mow2), model01.yml (mow), README.md — 4 files, 1136 lines, human-readable and diffable
- ✅ **DONE — Model binary decoded**: converted `.otx` → `.etx` via EdgeTX Companion v2.10.5; full channel maps, mixer config, and switch assignments now documented in YAML and README
- ✅ **DONE — `config/taranis/README.md` created** with channel map table, key settings, model differences, and hardware summary
- **Still needed — Commit SD card artifacts**: Yaapu configs (`mow.cfg`, `mow2.cfg`), telemetry log (`.plog`), version marker, and raw model binary when SD card is next mounted
- **Still needed — Create `mow_sensors.lua`** for rover-specific telemetry sensors (GSpd, Hdg, Alt, VSpd, VFAS, Fuel) once the FrSky telemetry link is operational
- ✅ **DONE — ArduPilot channel mapping verified** (2026-05-01 param dump): `MODE_CH=9` (SA 3-pos switch selects flight mode — NOT CH5/SG as the Taranis model label implied), `RC7_OPTION=153` (arm/disarm confirmed on SF), `RCMAP_ROLL=1, RCMAP_YAW=2, RCMAP_PITCH=3, RCMAP_THROTTLE=4` (standard). No `RCx_OPTION` set on CH6/CH8/CH9/CH10 — those channels have no ArduPilot auxiliary function assigned.
- **Do NOT commit** stock sound packs (157 MB), BMP images, old 2.2 backup (132 MB), firmware binaries, compiled Lua scripts, or stock tools
- **Consider EdgeTX migration** — OpenTX is abandoned (last release 2.3.15, April 2022); EdgeTX is the actively maintained successor, supports X9D+, and stores models in diffable YAML
- **Consider upgrading Yaapu** if a newer version adds rover-relevant features (current 1.8.0 is from 2020)

## Open Questions

- ~~What are the exact channel maps, mixer definitions, and switch assignments in the "mow" model?~~ **RESOLVED** — Fully decoded via EdgeTX Companion v2.10.5. See channel map in `config/taranis/README.md` and YAML models in `config/taranis/MODELS/`.
- ~~Is there a second model "mow2" defined in the transmitter EEPROM, or is `mow2.cfg` just a backup copy?~~ **RESOLVED** — Yes, both "mow" (model01, ID 2) and "mow2" (model00, ID 1) are distinct models in the transmitter. "mow2" is the active model (selected in radio settings). They are nearly identical — mow2 has an extra "cut" input (SD → CH9, gated by !SA2) and a different rudder trim value (10 vs 6).
- Should the Yaapu script be upgraded beyond 1.8.0, and if so, does a newer version add rover-specific features or break compatibility with OpenTX 2.3?
- ~~Are the battery capacity values from the telemetry log (6000 + 3300 mAh) still accurate for the current hardware configuration?~~ **PARTIALLY RESOLVED** — Pixhawk params show `BATT_CAPACITY=6300` (single battery configured, BATT2_MONITOR=0 disabled). The 2020 telemetry log showed dual batteries (6000+3300); the current config has only one battery monitored at 6300 mAh. Either the second battery was removed or just its monitoring was disabled.
- Should the transmitter be migrated from OpenTX 2.3 to EdgeTX? (OpenTX is abandoned since April 2022; EdgeTX is actively maintained, supports X9D+, and uses YAML model storage)
- ~~What ArduPilot `RC*_OPTION` values correspond to CH6 (SC), CH8 (SB), CH9 (SA/"cut"), and CH10 (SH)?~~ **RESOLVED** — Only `RC7_OPTION=153` (arm/disarm) is set. All other channels (`RC5_OPTION` through `RC10_OPTION` except RC7) = 0 (no function). CH9/SA is used as `MODE_CH=9` (flight mode selector) — it doesn't need an RCx_OPTION because ArduPilot reads it directly as the mode switch. CH6/SC, CH8/SB, CH10/SH have no assigned ArduPilot function.
- ~~Does the "cut" input on SD in model mow2 map to `SERVO5` (ignition kill) or `SERVO7` (blade clutch) on the ArduPilot side?~~ **RESOLVED** — Neither, currently. The Taranis mow2 model's "cut" input on SD routes to CH9, but ArduPilot uses CH9 solely as `MODE_CH` (flight mode). The "cut" function is not currently mapped to any ArduPilot relay/servo output. `SERVO5_FUNCTION=0` (disabled), `SERVO6_FUNCTION=58` (scripting1), `SERVO7_FUNCTION=56` (scripting3), `SERVO8_FUNCTION=55` (scripting2). Relay-based ignition/blade control is not yet configured.
- **NEW:** `ARMING_CHECK=0` — ALL arming pre-arm checks are disabled. This should be re-enabled before field testing (at minimum GPS lock, EKF, and battery checks).
- **NEW:** `FENCE_ACTION=1` (RTL) and `FS_EKF_ACTION=1` (RTL) need to be changed to `2` (Hold) per project safety docs — RTL drives straight through obstacles.
- **NEW:** Flight mode mapping via `MODE_CH=9` / SA switch: MODE1=Manual, MODE2=Manual, MODE3=Manual, MODE4=Acro, MODE5=Manual, MODE6=Auto. With a 3-pos switch (SA), effective modes are likely Manual (SA-up) / Acro (SA-mid) / Auto (SA-down). Consider adding Hold to one of the intermediate positions for safety.
- **NEW:** SERVO6/7/8 use **RCPassThru** functions (not scripting outputs as initially reported): `SERVO6_FUNCTION=58` (RCIn8 → SB), `SERVO7_FUNCTION=56` (RCIn6 → SC), `SERVO8_FUNCTION=55` (RCIn5 → SG, SF-gated). This gives the operator direct switch control over relay outputs from the Taranis — likely starter (SB), blade clutch (SC), and ignition kill (SG, only when armed).

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-28 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/015-taranis-x9d-sdcard-configuration.md |
