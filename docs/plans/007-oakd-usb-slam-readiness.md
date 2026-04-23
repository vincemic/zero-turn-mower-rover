---
id: "007"
type: plan
title: "OAK-D Pro USB + SLAM Readiness Implementation"
status: ✅ Complete
created: "2026-04-23"
updated: "2026-04-23"
completed: "2026-04-23"
owner: pch-planner
version: v2.1
research: docs/research/006-oakd-pro-usb-slam-readiness.md
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-23 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-23 | pch-planner | Scope decision: items 1–6, slam-preflight deferred |
| v1.2 | 2026-04-23 | pch-planner | oakd check: promote to CRITICAL, inline speed verification |
| v1.3 | 2026-04-23 | pch-planner | Three separate new probe checks (autosuspend, usbfs, thermal gate) |
| v1.4 | 2026-04-23 | pch-planner | jetson_clocks: systemd oneshot service at boot |
| v2.0 | 2026-04-23 | pch-planner | Holistic review completed; execution plan finalized |
| v2.1 | 2026-04-23 | pch-plan-reviewer | Review passed — 0 Critical/Major, 4 Minor implementer notes |

## Introduction

This plan implements the actionable conclusions from [research 006](../research/006-oakd-pro-usb-slam-readiness.md): ensuring the OAK-D Pro camera on the Jetson AGX Orin is correctly configured for USB SuperSpeed operation and real-time SLAM streaming. The work spans four areas: (1) enhancing the existing `oakd` probe check to verify USB speed, (2) adding new probe checks for USB tuning and thermal gating, (3) updating `jetson-harden.sh` with USB/power tuning and udev rules, and (4) adding `depthai` to the project's optional Jetson dependencies.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Scope & Priority | D — Items 1–6 now, slam-preflight in follow-up | Items 1–6 are testable without physical OAK-D (fake sysfs). slam-preflight is complex enough for its own plan. |
| 2 | Enhanced oakd check severity | A — Promote to CRITICAL, add speed inline | Single check handles both vendor ID and USB speed; simplest change. |
| 3 | New probe checks granularity | A — Three separate checks (one per tunable) | Matches existing pattern (one check per concern). Maximum diagnostic clarity for operators. |
| 4 | jetson_clocks integration | A — Systemd oneshot service enabled at boot | Single workload, no battery, no reason for DVFS jitter. Natural extension of existing nvpmodel management. |

## Holistic Review

### Decision Interactions

1. **CRITICAL oakd + separate WARNING tunables:** Promoting `oakd` to CRITICAL while keeping USB tuning checks at WARNING is coherent — a missing/slow camera is a hard blocker, but misconfigured kernel params are fixable warnings. No conflict.

2. **Three separate checks + hardening script parity:** Each probe check (`oakd_usb_autosuspend`, `oakd_usbfs_memory`) has a corresponding hardening step that fixes what the check detects. The `oakd_thermal_gate` has no hardening fix (it's environmental) — this is correct; you can't script-fix ambient temperature.

3. **`jetson_clocks` service + nvpmodel interaction:** The service depends on `nvpmodel.service` via systemd ordering. The hardening script sets nvpmodel (step 6) before creating the `jetson_clocks` service (step 12). Both the runtime dependency (systemd) and the setup dependency (script order) are satisfied.

4. **`extlinux.conf` modification safety:** The `grep` guard before `sed` append prevents double-application. The script does NOT create a backup of `extlinux.conf` — this is acceptable because the modification is append-only to an existing line and the original params are preserved. However, the plan should note that a corrupted `extlinux.conf` would prevent boot; the Jetson can be recovered via USB flash mode.

### Architectural Considerations

- **No circular dependencies in probe registry:** `oakd` depends on `jetpack_version`. `oakd_thermal_gate` depends on `thermal` which depends on `jetpack_version`. `oakd_usb_autosuspend` and `oakd_usbfs_memory` have no dependencies. No cycles.
- **Test coverage:** All new code paths have corresponding test cases in `test_probe.py`. Hardening script changes are shell-only (not tested via pytest but verifiable via `shellcheck` and field execution).
- **No import-time side effects:** `usb_tuning.py` only registers checks via decorators at import time — same pattern as all other check modules.

### Trade-offs Accepted

- **oakd severity promotion to CRITICAL:** On a Jetson without an OAK-D connected (e.g., during initial network bringup), `mower-jetson probe` will now report a CRITICAL failure for `oakd`. This is acceptable because the OAK-D is required hardware for the SLAM workload; a CRITICAL failure correctly signals "this Jetson is not ready for field deployment."
- **`jetson_clocks` prevents nvpmodel changes without reboot:** Accepted — single-workload system.
- **No `extlinux.conf` backup:** Low risk — append-only modification, recoverable via USB flash.

### Gaps

- Hardening script is not tested via pytest (shell scripts). Mitigation: `shellcheck` + field validation.
- `depthai>=3.5.0` is added as a dependency but nothing imports it yet in this plan. The follow-up `slam-preflight` plan will use it.

## Overview

Implement the infrastructure and configuration changes identified in [research 006](../research/006-oakd-pro-usb-slam-readiness.md) to ensure the OAK-D Pro camera is SLAM-ready when connected to the Jetson AGX Orin. This covers four areas:

1. **Enhance the existing `oakd` probe check** — promote to CRITICAL, add USB speed verification via sysfs `speed` file alongside existing vendor ID check
2. **Add three new probe checks** — `oakd_usb_autosuspend` (WARNING), `oakd_usbfs_memory` (WARNING), `oakd_thermal_gate` (WARNING) for USB kernel tuning and pre-flight thermal gating
3. **Update `jetson-harden.sh`** — add OAK-D udev rules (`80-oakd-usb.rules`), USB kernel params (`autosuspend=-1`, `usbfs_memory_mb=1000` in `extlinux.conf`), and `jetson_clocks` systemd service
4. **Add `depthai` dependency** — add `depthai>=3.5.0` to `pyproject.toml` `jetson` optional-deps group

**Objectives:**
- An operator running `mower-jetson probe` gets clear pass/fail on OAK-D USB speed, kernel tuning, and thermal readiness
- A freshly re-flashed Jetson brought up with `jetson-harden.sh` has all USB/power settings correct for SLAM without manual intervention
- The `depthai` library is installable on the Jetson via `pip install .[jetson]`

## Requirements

### Functional

- **FR-1:** `oakd` probe check verifies vendor ID `03e7` AND sysfs `speed` file reads `5000` or `10000`; severity CRITICAL; reports speed in Mbps on pass, specific failure reason on fail
- **FR-2:** `oakd_usb_autosuspend` probe check reads `/sys/module/usbcore/parameters/autosuspend` and passes iff value is `-1`; severity WARNING; no dependencies
- **FR-3:** `oakd_usbfs_memory` probe check reads `/sys/module/usbcore/parameters/usbfs_memory_mb` and passes iff value ≥ `1000`; severity WARNING; no dependencies
- **FR-4:** `oakd_thermal_gate` probe check reads tj-thermal zone (or max of all zones) and passes iff temperature < 85°C; severity WARNING; depends on `thermal`
- **FR-5:** `jetson-harden.sh` creates `/etc/udev/rules.d/80-oakd-usb.rules` with permissions (`MODE=0666`), autosuspend disable, and symlink for vendor `03e7`
- **FR-6:** `jetson-harden.sh` appends `usbcore.autosuspend=-1 usbcore.usbfs_memory_mb=1000` to the `APPEND` line in `/boot/extlinux/extlinux.conf` (idempotent — skips if already present)
- **FR-7:** `jetson-harden.sh` creates and enables `jetson-clocks.service` (oneshot, `After=nvpmodel.service`)
- **FR-8:** `pyproject.toml` `[project.optional-dependencies] jetson` includes `depthai>=3.5.0`

### Non-Functional

- **NFR-1:** All probe checks testable on Windows via fake sysfs trees under `tmp_path` (no Jetson hardware required)
- **NFR-2:** All hardening script additions idempotent — safe to re-run after partial failure or re-flash
- **NFR-3:** Hardening script changes follow existing `STATUS` tracking pattern for summary output
- **NFR-4:** `extlinux.conf` modification is append-only to existing APPEND line; no destructive rewrite
- **NFR-5:** `depthai` import is Jetson-only; laptop-side code never imports it

### Out of Scope

- `mower-jetson slam-preflight` CLI command (DepthAI pipeline, FPS/drop/latency validation, JSON report) — deferred to follow-up plan
- SLAM algorithm integration (cuVSLAM / RTAB-Map) — Phase 11/12 of vision
- IR dot projector / flood LED configuration — not needed for daylight mowing
- Device tree or pinmux changes — default Dev Kit config is correct
- Custom carrier board support — project uses standard P3737 carrier

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Probe Check Registration
    location: "src/mower_rover/probe/checks/*.py"
    usage: New checks use @register decorator with Severity, depends_on; fn(sysroot) -> (bool, str)
  - pattern: sysfs-based Checks
    location: "src/mower_rover/probe/checks/oakd.py, thermal.py"
    usage: Read files from sysroot / sys / ... paths; testable via fake sysfs under tmp_path
  - pattern: Shell Hardening Script
    location: "scripts/jetson-harden.sh"
    usage: Idempotent functions with STATUS tracking; numbered steps in main()
  - pattern: Probe Test Pattern
    location: "tests/test_probe.py"
    usage: Create fake sysfs tree under tmp_path; call _REGISTRY["name"].fn(tmp_path)
  - pattern: Optional Dependencies
    location: "pyproject.toml [project.optional-dependencies]"
    usage: jetson group for Jetson-only packages
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Architecture

No new architectural patterns. Changes are additive within existing patterns:

- **Probe checks** — new `@register` decorated functions in `src/mower_rover/probe/checks/oakd.py` (enhanced) and a new `src/mower_rover/probe/checks/usb_tuning.py` (new file for `oakd_usb_autosuspend` + `oakd_usbfs_memory` + `oakd_thermal_gate`)
- **Hardening script** — new idempotent functions added to `scripts/jetson-harden.sh` following the existing `harden_*()` / `STATUS[]` pattern
- **Dependency** — one line addition to `pyproject.toml`

### Component Specifications

#### Enhanced `oakd` Probe Check

**File:** `src/mower_rover/probe/checks/oakd.py`

**Current behavior:** Finds vendor `03e7` in sysfs, returns `(True, "OAK device found")` or `(False, "No OAK device detected")`. Severity: WARNING.

**New behavior:** Same vendor ID scan, but also reads the `speed` file in the same sysfs device directory. Severity promoted to CRITICAL.

```python
@register("oakd", severity=Severity.CRITICAL, depends_on=("jetpack_version",))
def check_oakd(sysroot: Path) -> tuple[bool, str]:
    """Detect a Luxonis OAK device and verify USB SuperSpeed."""
    pattern = str(sysroot / "sys" / "bus" / "usb" / "devices" / "*" / "idVendor")
    for vendor_file in glob.glob(pattern):
        try:
            vid = Path(vendor_file).read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if vid == _OAK_VENDOR_ID:
            speed_file = Path(vendor_file).parent / "speed"
            if speed_file.is_file():
                try:
                    speed = speed_file.read_text(encoding="utf-8").strip()
                except OSError:
                    return True, f"OAK device found (vendor {_OAK_VENDOR_ID}, speed unknown)"
                if speed in ("5000", "10000"):
                    return True, f"OAK device found at USB {speed} Mbps"
                return False, f"OAK device at USB {speed} Mbps (need ≥5000)"
            return True, f"OAK device found (vendor {_OAK_VENDOR_ID}, speed file missing)"
    return False, f"No OAK device detected (vendor {_OAK_VENDOR_ID})"
```

**Key details:**
- `speed` file contains `480` (USB 2.0), `5000` (Gen 1), or `10000` (Gen 2) as plain text
- Missing `speed` file is a pass (graceful degradation for unusual sysfs layouts)
- `speed` present but `480` → FAIL with clear message
- Return values include Mbps for operator actionability

#### New Probe Check: `oakd_usb_autosuspend`

**File:** `src/mower_rover/probe/checks/usb_tuning.py` (new)

```python
_AUTOSUSPEND_PATH = Path("sys") / "module" / "usbcore" / "parameters" / "autosuspend"

@register("oakd_usb_autosuspend", severity=Severity.WARNING, depends_on=())
def check_usb_autosuspend(sysroot: Path) -> tuple[bool, str]:
    """Verify USB autosuspend is disabled (autosuspend == -1)."""
    param_file = sysroot / _AUTOSUSPEND_PATH
    if not param_file.is_file():
        return True, "autosuspend parameter not found (non-Linux or test env)"
    try:
        val = param_file.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "Could not read autosuspend parameter"
    if val == "-1":
        return True, "USB autosuspend disabled (autosuspend=-1)"
    return False, f"USB autosuspend={val} (expected -1; set usbcore.autosuspend=-1)"
```

#### New Probe Check: `oakd_usbfs_memory`

**File:** `src/mower_rover/probe/checks/usb_tuning.py`

```python
_USBFS_MEMORY_PATH = Path("sys") / "module" / "usbcore" / "parameters" / "usbfs_memory_mb"
_USBFS_MIN_MB = 1000

@register("oakd_usbfs_memory", severity=Severity.WARNING, depends_on=())
def check_usbfs_memory(sysroot: Path) -> tuple[bool, str]:
    """Verify usbfs_memory_mb >= 1000 for OAK-D streaming."""
    param_file = sysroot / _USBFS_MEMORY_PATH
    if not param_file.is_file():
        return True, "usbfs_memory_mb parameter not found (non-Linux or test env)"
    try:
        val = int(param_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False, "Could not read usbfs_memory_mb parameter"
    if val >= _USBFS_MIN_MB:
        return True, f"usbfs_memory_mb={val} (≥{_USBFS_MIN_MB})"
    return False, f"usbfs_memory_mb={val} (need ≥{_USBFS_MIN_MB}; set usbcore.usbfs_memory_mb=1000)"
```

#### New Probe Check: `oakd_thermal_gate`

**File:** `src/mower_rover/probe/checks/usb_tuning.py`

```python
_THERMAL_GATE_C = 85.0

@register("oakd_thermal_gate", severity=Severity.WARNING, depends_on=("thermal",))
def check_thermal_gate(sysroot: Path) -> tuple[bool, str]:
    """Verify thermal zones are below 85°C SLAM pre-flight gate."""
    snap = read_thermal_zones(sysroot=sysroot)
    if not snap.zones:
        return True, "No thermal zones found"
    max_zone = max(snap.zones, key=lambda z: z.temp_c)
    if max_zone.temp_c >= _THERMAL_GATE_C:
        return False, (
            f"{max_zone.name} at {max_zone.temp_c:.1f}°C "
            f"(SLAM gate {_THERMAL_GATE_C}°C; cool down before starting)"
        )
    return True, f"Thermal OK for SLAM (max {max_zone.temp_c:.1f}°C on {max_zone.name}, gate {_THERMAL_GATE_C}°C)"
```

**Import:** `from mower_rover.health.thermal import read_thermal_zones`

#### `checks/__init__.py` Update

Add `usb_tuning` to the import list:

```python
from mower_rover.probe.checks import (  # noqa: F401
    cuda,
    disk,
    jetpack,
    oakd,
    power_mode,
    python_ver,
    ssh_hardening,
    thermal,
    usb_tuning,
)
```

#### Hardening Script: OAK-D udev Rules (step 10)

**File:** `scripts/jetson-harden.sh` — new function `harden_oakd_udev`

```bash
harden_oakd_udev() {
    local udev_file="/etc/udev/rules.d/80-oakd-usb.rules"
    local desired
    desired=$(cat <<'UDEV'
# OAK-D Pro USB rules — managed by jetson-harden.sh
# 1. Grant non-root access (Movidius VPU vendor 03e7)
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"
# 2. Disable USB autosuspend for the device
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/autosuspend}="-1"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/control}="on"
# 3. Stable symlink
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", SYMLINK+="oakd"
UDEV
)

    if [[ -f "$udev_file" ]] && echo "$desired" | diff -q - "$udev_file" &>/dev/null; then
        STATUS[oakd_udev]="already"
    else
        echo "$desired" > "$udev_file"
        udevadm control --reload-rules && udevadm trigger
        STATUS[oakd_udev]="applied"
    fi
}
```

#### Hardening Script: USB Kernel Parameters (step 11)

**File:** `scripts/jetson-harden.sh` — new function `harden_usb_params`

```bash
harden_usb_params() {
    local extlinux="/boot/extlinux/extlinux.conf"
    if [[ ! -f "$extlinux" ]]; then
        STATUS[usb_params]="skip:no_extlinux"
        return
    fi

    local any_changed=false

    # Append usbcore.autosuspend=-1 if not present
    if ! grep -q 'usbcore.autosuspend=-1' "$extlinux"; then
        sed -i '/^\s*APPEND/ s/$/ usbcore.autosuspend=-1/' "$extlinux"
        any_changed=true
    fi

    # Append usbcore.usbfs_memory_mb=1000 if not present
    if ! grep -q 'usbcore.usbfs_memory_mb=' "$extlinux"; then
        sed -i '/^\s*APPEND/ s/$/ usbcore.usbfs_memory_mb=1000/' "$extlinux"
        any_changed=true
    fi

    if $any_changed; then
        STATUS[usb_params]="applied"
    else
        STATUS[usb_params]="already"
    fi
}
```

#### Hardening Script: `jetson_clocks` Service (step 12)

**File:** `scripts/jetson-harden.sh` — new function `harden_jetson_clocks`

```bash
harden_jetson_clocks() {
    local svc_file="/etc/systemd/system/jetson-clocks.service"
    local desired
    desired=$(cat <<'UNIT'
[Unit]
Description=Lock Jetson clocks to nvpmodel maximums
After=nvpmodel.service

[Service]
Type=oneshot
ExecStart=/usr/bin/jetson_clocks
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
)

    if [[ -f "$svc_file" ]] && echo "$desired" | diff -q - "$svc_file" &>/dev/null; then
        STATUS[jetson_clocks]="already"
    else
        echo "$desired" > "$svc_file"
        systemctl daemon-reload
        systemctl enable jetson-clocks.service
        STATUS[jetson_clocks]="applied"
    fi
}
```

#### Hardening Script: `main()` Updates

- Step count changes from `[N/9]` to `[N/12]`
- Three new calls at the end (before `print_summary`):
  - `[10/12] OAK-D udev rules...` → `harden_oakd_udev`
  - `[11/12] USB kernel parameters...` → `harden_usb_params`
  - `[12/12] jetson_clocks service...` → `harden_jetson_clocks`
- `print_summary` labels array gains three entries:
  - `"oakd_udev:OAK-D udev rules (80-oakd-usb.rules)"`
  - `"usb_params:USB kernel params (autosuspend, usbfs_memory_mb)"`
  - `"jetson_clocks:jetson_clocks service (lock clocks at boot)"`

#### `pyproject.toml` Change

```toml
jetson = [
    "sdnotify>=0.3",
    "depthai>=3.5.0",
]
```

Also add mypy override for depthai (no type stubs available):

```toml
[[tool.mypy.overrides]]
module = ["depthai.*"]
ignore_missing_imports = true
```

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| Research 006 complete | Knowledge | ✅ Complete | All 5 phases done |
| Existing probe registry + `@register` pattern | Code | ✅ Exists | `src/mower_rover/probe/registry.py` |
| Existing `oakd.py` check | Code | ✅ Exists | Vendor ID only; will be enhanced |
| Existing `health/thermal.py` reader | Code | ✅ Exists | Used by `oakd_thermal_gate` |
| `jetson-harden.sh` 9-step structure | Code | ✅ Exists | Extending to 12 steps |
| `pyproject.toml` `jetson` optional-deps | Code | ✅ Exists | Adding `depthai` |
| DepthAI 3.5.0 aarch64 wheel on PyPI | External | ✅ Available | Per research Phase 2 |
| JetPack 6 on Jetson AGX Orin | Hardware | ✅ Flashed | Per plan 006 |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `extlinux.conf` format varies across L4T versions | Low | High (broken boot) | Idempotent `grep` before `sed`; only appends to existing APPEND line; never rewrites the file |
| OAK-D Pro not yet physically connected during testing | Medium | Low | Probe checks use fake sysfs in tests; field validation with `@pytest.mark.jetson` |
| `depthai` aarch64 wheel unavailable for Python 3.11 specifically | Low | Medium | Research confirms 3.8+ support; fallback: source build with `cmake --parallel 2` |
| `jetson_clocks` prevents nvpmodel changes without reboot | Certain | Low | Accepted trade-off — power mode is set once during hardening |
| Existing tests for `oakd` check break after severity change | Certain | Low | Tests must be updated to expect CRITICAL instead of WARNING; included in execution plan |

## Execution Plan

### Phase 1: Probe Check Enhancements

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 5
**Prerequisites:** None
**Entry Point:** `src/mower_rover/probe/checks/oakd.py`
**Verification:** `uv run pytest tests/test_probe.py -v` passes on Windows

| Step | Task | Files | Status |
|------|------|-------|--------|
| 1.1 | Enhance `oakd` check: promote severity to CRITICAL, add `speed` file read after vendor ID match | `src/mower_rover/probe/checks/oakd.py` | ✅ Complete |
| 1.2 | Create `usb_tuning.py` with three new checks: `oakd_usb_autosuspend`, `oakd_usbfs_memory`, `oakd_thermal_gate` | `src/mower_rover/probe/checks/usb_tuning.py` (new) | ✅ Complete |
| 1.3 | Update `checks/__init__.py` to import `usb_tuning` | `src/mower_rover/probe/checks/__init__.py` | ✅ Complete |
| 1.4 | Update existing `oakd` tests for new severity + speed behavior; add tests for 3 new checks | `tests/test_probe.py` | ✅ Complete |
| 1.5 | Update `TestRegistry.test_all_checks_registered` expected set | `tests/test_probe.py` | ✅ Complete |

**Implementation notes:**
- Follow the exact patterns in existing `oakd.py` and `thermal.py` for sysfs path construction and error handling
- `usb_tuning.py` imports: `from pathlib import Path`, `from mower_rover.probe.registry import Severity, register`, `from mower_rover.health.thermal import read_thermal_zones`
- All test classes use `tmp_path` fixture with fake sysfs directories — no Jetson required

### Phase 2: Hardening Script & Dependency Updates

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2
**Prerequisites:** Phase 1 complete (probe checks define the verification criteria for hardening)
**Entry Point:** `scripts/jetson-harden.sh`
**Verification:** `shellcheck scripts/jetson-harden.sh` passes; `uv run pytest` still green; `uv sync --extra jetson` resolves `depthai`

| Step | Task | Files | Status |
|------|------|-------|--------|
| 2.1 | Add `harden_oakd_udev()` function | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.2 | Add `harden_usb_params()` function | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.3 | Add `harden_jetson_clocks()` function | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.4 | Update `main()` step count to 12, add new step calls | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.5 | Update `print_summary` labels array with 3 new entries | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.6 | Add `depthai>=3.5.0` to jetson deps + mypy override | `pyproject.toml` | ✅ Complete |

**Implementation notes:**
- `sed -i` on `extlinux.conf` APPEND line: use `s/$/ usbcore.autosuspend=-1/` to append to end of line. Guard with `grep -q` to avoid double-append.
- The udev rule uses `ATTRS{idVendor}` (with S, walks parent) for the permissions/symlink rules and `ATTR{idVendor}` (no S, direct) for the power attribute writes, per research Phase 4 §4.2.
- `jetson-clocks.service` uses `After=nvpmodel.service` to ensure power mode is set before clocks are locked.

## Standards

No organizational standards applicable to this plan.

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 0
**Last Updated:** 2026-04-23

No clarifying questions were required — all plan details are unambiguous and codebase-verified.

## Review Notes for Implementer

The following minor observations should be kept in mind during implementation. None require plan changes.

| # | Observation | Category | Severity | Notes |
|---|-------------|----------|----------|-------|
| 1 | `harden_usb_params()` grep inconsistency | Correctness | Minor | `autosuspend` grep checks exact value (`-q 'usbcore.autosuspend=-1'`), but `usbfs_memory_mb` grep checks key existence only (`-q 'usbcore.usbfs_memory_mb='`). If a prior value `!=1000` exists, it won't be corrected. Low risk — script targets fresh-flash Jetsons. Implementer may optionally align both greps to check exact value for consistency. |
| 2 | Existing `TestOakdCheck.test_pass_device_present` becomes speed-file-missing test | Clarity | Minor | After enhancement, this test has no `speed` file so it exercises the "speed file missing" path. Consider renaming to `test_pass_no_speed_file` and using the new `test_pass_superspeed` as the primary happy-path test. |
| 3 | `extlinux.conf` sed matches all APPEND lines | Specificity | Minor | `sed '/^\s*APPEND/ s/$/ .../'` modifies every APPEND line in the file. Standard JetPack 6 has one APPEND line; risk is negligible. Acknowledged in Risks table. |
| 4 | mypy override block style | Clarity | Minor | Plan adds a new `[[tool.mypy.overrides]]` block for `depthai.*`. Could alternatively merge into the existing `sdnotify.*` block (both Jetson-only, same `ignore_missing_imports = true`). Either approach is correct. |

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 5 files across 2 areas (probe checks + hardening/config) |
| New patterns introduced | 1 | No new patterns — all additive within existing `@register` + `harden_*` |
| External dependencies | 1 | `depthai` added but not imported in this plan |
| Migration complexity | 1 | No data migration; `extlinux.conf` is append-only |
| Test coverage required | 2 | Unit tests only; fake sysfs under `tmp_path` |
| **Overall Complexity** | **7/25** | **Low** |

## Review Summary

**Review Date:** 2026-04-23
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Codebase Verification

All technical claims verified against the codebase:

- ✅ `src/mower_rover/probe/checks/oakd.py` — exists, severity WARNING, vendor-only check
- ✅ `src/mower_rover/probe/registry.py` — `@register`, `Severity`, `_REGISTRY` all present
- ✅ `src/mower_rover/probe/checks/__init__.py` — imports 8 check modules (plan adds 9th)
- ✅ `src/mower_rover/health/thermal.py` — `read_thermal_zones(sysroot)` returns `ThermalSnapshot` with `zones: list[ThermalZone]`; `ThermalZone` has `temp_c` and `name`
- ✅ `scripts/jetson-harden.sh` — 9 steps, 11 STATUS labels, `harden_*()` + `diff -q` idempotency pattern
- ✅ `pyproject.toml` — `jetson` extras has `sdnotify>=0.3`; two existing mypy override blocks
- ✅ `tests/test_probe.py` — `TestOakdCheck` has 3 tests; `test_all_checks_registered` expects 9 checks
- ✅ No circular dependencies in probe registry with new checks added

### Review Metrics

- Issues Found: 4 (Critical: 0, Major: 0, Minor: 4)
- Clarifying Questions Asked: 0
- Sections Updated: Frontmatter, Version History, Handoff

### Key Observations

1. Plan is well-structured with clear phase ordering and testable acceptance criteria
2. All probe checks follow existing `@register` + sysfs patterns exactly
3. Hardening script additions follow established `harden_*()` + `STATUS[]` + `diff -q` pattern
4. Test coverage is comprehensive — all code paths (pass/fail/missing) specified with concrete assertions
5. Holistic Review section correctly identifies cross-cutting concerns and accepted trade-offs

### Remaining Considerations

- `depthai>=3.5.0` version availability should be verified during Phase 2 step 2.6 (`uv sync --extra jetson`)
- Shell script changes are not pytest-testable; verify with `shellcheck` + field execution on the Jetson
- After Phase 1, run `uv run pytest tests/test_probe.py -v` on Windows to confirm probe changes pass without Jetson hardware

### Sign-off

This plan has been reviewed and is **Ready for Implementation**.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-23 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-23 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/007-oakd-usb-slam-readiness.md |
