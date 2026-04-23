---
id: "006"
type: implementation-plan
title: "JetPack 5 → 6.2.2 Reflash & Re-Bringup"
status: ✅ Complete
created: 2026-04-23
updated: 2026-04-23
completed: 2026-04-23
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-23 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-23 | pch-planner | Decision #1: scope = code fix + operational runbook |
| v1.2 | 2026-04-23 | pch-planner | Decision #2: test approach = code review only |
| v1.3 | 2026-04-23 | pch-planner | Decision #3: runbook detail = inline commands + research refs |
| v2.0 | 2026-04-23 | pch-planner | Holistic review + full execution plan complete |
| v2.1 | 2026-04-23 | pch-plan-reviewer | Review: added missed line 295 fix; corrected line ref 136→135; added review summary |
| v2.2 | 2026-04-23 | pch-coder | Implementation complete: Phase 1 nvpmodel label fix applied; Phase 2 runbook ready for operator execution |

## Introduction

This plan covers the work required to reflash the Jetson AGX Orin from JetPack 5.1.2 (L4T R35.4.1) to JetPack 6.2.2 (L4T R36.5.0), fix a confirmed code bug, and verify the full bringup automation chain on the new OS. Based on research [005-jetson-agx-orin-jetpack6-reflash.md](/docs/research/005-jetson-agx-orin-jetpack6-reflash.md).

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|---------------|--------|-----------|
| 1 | Plan scope | B — Code fix + operational runbook | Research confirms all automation works on JP 6.2.2; no new CLI commands needed; value is a single actionable execution document with the nvpmodel label fix included |
| 2 | Test approach for nvpmodel fix | A — No automated test; code review only | Single-character cosmetic label fix in bash; existing tests mock script at SSH level; adding bash parsing tests is over-engineering for a one-off typo |
| 3 | Runbook detail level | B — Self-contained with key commands inline | Embed shell/PowerShell commands for bench execution; reference research 005 for SDK Manager GUI and hardware button procedures; balances usability vs maintenance cost |

## Holistic Review

### Decision Interactions

1. **Decisions #1 (scope B) + #3 (runbook detail B):** The plan has two distinct deliverables — a code fix and an embedded runbook. These are independent: the code fix (Phase 1) should be committed before the flash so the hardening script is correct when `mower jetson bringup` pushes it post-flash. The runbook (Phase 2) is a procedure document, not code.

2. **Decisions #2 (no automated test) + #1 (scope B):** No test risk here — the label fix has zero behavioral impact. The hardening script's `nvpmodel -m 3` call is unchanged. The plan reviewer will verify the string change.

### Architectural Considerations

- **No code architecture changes.** This plan modifies one string literal in a bash script. All Python source files are untouched.
- **Automation chain validated by research.** Research 005 confirmed all 8 probe checks, the hardening script, and the bringup sequence work on JetPack 6.2.2 without code changes.
- **Runbook is embedded in the plan, not a separate file.** This keeps it co-located with the decision history and avoids yet another document to maintain.

### Trade-offs Accepted

- **Runbook may drift from research 005** if research is updated later. Mitigation: runbook references research for GUI/hardware procedures rather than duplicating them; only shell commands are inline.
- **No automated pre-flash backup.** The backup is 6 scp commands — not worth a CLI command for a one-time operation. Inline PowerShell is sufficient.
- **Open questions from research 005** (nvpmodel mode table, apt-mark package names) require field verification after flash. These are noted in the Risks table and the verification checklist.

### Risk Assessment

No blocking risks identified. All risks have documented mitigations. The flash is recoverable (Force Recovery Mode is hardware-based). All Jetson configs are reproducible by the automation chain.

## Overview

Reflash the Jetson AGX Orin from JetPack 5.1.2 to JetPack 6.2.2 (L4T 36.5.0) and verify the full bringup chain. Scope includes:

1. **Code fix:** Correct the nvpmodel summary label bug in `scripts/jetson-harden.sh` (line 247 says "mode 2 (30W)" but code sets mode 3)
2. **Operational runbook:** Step-by-step execution checklist covering pre-flash backup, SDK Manager flash, post-flash manual setup, and automated re-bringup — synthesized from research 005 into a single go-to document
3. **Verification:** Confirm all 8 probe checks pass on JetPack 6.2.2 after bringup completes

## Requirements

### Functional

- **FR-1:** Fix nvpmodel summary label in `jetson-harden.sh` to say "mode 3 (50W)" instead of "mode 2 (30W)"
- **FR-2:** Add/update test coverage for the nvpmodel label fix
- **FR-3:** Operational runbook: pre-flash backup commands (PowerShell)
- **FR-4:** Operational runbook: SDK Manager flash procedure (Windows primary, live USB fallback)
- **FR-5:** Operational runbook: post-flash manual steps (static IP, sudo, CUDA, known_hosts)
- **FR-6:** Operational runbook: re-bringup command sequence (`mower jetson setup` → `mower jetson bringup`)
- **FR-7:** Verification checklist: all 8 probe checks pass on JetPack 6.2.2

### Non-Functional

- **NFR-1:** Runbook must be executable by a single operator from a Windows laptop
- **NFR-2:** No internet dependency in operational commands (bringup uses direct SSH)
- **NFR-3:** Runbook references research 005 for deep details rather than duplicating them

### Out of Scope

- New CLI commands (`mower jetson pre-backup`, `mower jetson post-flash`, etc.)
- Tightening probe check logic (e.g., checking specific L4T revision numbers)
- OTA upgrade path research (clean flash only)
- JetPack 7.x (Thor-only, not applicable to AGX Orin)
- Any changes to `bringup.py`, `setup.py`, or probe check source files

## Technical Design

### Code Change: nvpmodel Label Fixes

**File:** `scripts/jetson-harden.sh`

| Line | Current | Fixed |
|------|---------|-------|
| 246 | `"nvpmodel:nvpmodel mode 2 (30W)"` | `"nvpmodel:nvpmodel mode 3 (50W)"` |
| 295 | `echo "[6/9] nvpmodel (30W)..."` | `echo "[6/9] nvpmodel (50W)..."` |

The implementation code at lines 135–143 already correctly sets `nvpmodel -m 3`. Only the summary label (line 246) and progress echo (line 295) have the wrong wattage. The section comment (line 135) already correctly says "mode 3 (50W)".

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Hardening script sections
    location: "scripts/jetson-harden.sh"
    usage: Each section has a function + matching summary label in the labels array
  - pattern: Bringup orchestration
    location: "src/mower_rover/cli/bringup.py"
    usage: 6-step SSH-driven sequence; not modified by this plan
  - pattern: Probe checks
    location: "src/mower_rover/probe/checks/*.py"
    usage: Already target JetPack 6 (R36, CUDA 12.x); not modified by this plan
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Operational Runbook Structure

The runbook (Phase 2 of the Execution Plan) follows 5 stages:

| Stage | Type | Detail Source |
|-------|------|---------------|
| A. Pre-flash backup | Commands inline | PowerShell scp commands |
| B. SDK Manager flash | Reference | Research 005 Phase 4 |
| C. Post-flash manual setup | Commands inline | nmcli, sudoers, apt, ssh-keygen |
| D. Automated re-bringup | Commands inline | `mower jetson setup` + `mower jetson bringup` |
| E. Verification | Checklist inline | Probe check expected values |

## Dependencies

| Dependency | Type | Status | Notes |
|------------|------|--------|-------|
| Research 005 complete | Document | ✅ Done | Provides all flash procedures and compatibility analysis |
| Plan 005 (bringup automation) complete | Code | ✅ Done | `mower jetson setup` + `mower jetson bringup` implemented |
| SDK Manager installed on Windows laptop | Tool | ⏳ Operator | Download from developer.nvidia.com |
| Bootable Ubuntu 22.04 USB (fallback) | Tool | ⏳ Operator | Create with Rufus; needed only if SDK Manager fails |
| USB-C cable + power supply | Hardware | ✅ Available | Included with AGX Orin dev kit |
| NVMe SSD installed in AGX Orin | Hardware | ⏳ Verify | Confirm M.2 slot populated before selecting NVMe target |
| Network connectivity (laptop ↔ Jetson) | Network | ✅ Available | Direct Ethernet, static IP 192.168.4.38/24 |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| USBIPD first-flash failure on Windows | Medium | Low | Power cycle Jetson, re-enter recovery mode, retry. Known SDK Manager issue. |
| Power loss mid-flash | Low | Low | Force Recovery Mode is hardware-based; re-flash from scratch. Not catastrophic. |
| NVMe SSD not installed | Low | High | Verify before starting. If absent, flash to eMMC (64 GB, slower). |
| CUDA not installed post-flash (SDK Manager SSH step fails) | Medium | Low | Run `sudo apt install nvidia-jetpack` manually on Jetson console. |
| `.wslconfig` overwritten by SDK Manager | Medium | Low | Back up before flash; SDK Manager also creates `.wslconfig.bak`. |
| Static IP connection name differs on JP 6.2.2 | Low | Low | Use `nmcli device status` to find correct connection name before modifying. |
| apt-mark hold package names changed in L4T 36.5 | Low | Medium | Verify `dpkg -l \| grep nvidia-l4t` on device after flash; update `jetson-harden.sh` if needed. |
| nvpmodel mode 3 ≠ 50W on L4T 36.5 | Low | Low | Run `nvpmodel -p --verbose` after flash to verify. Open question in research 005. |

## Execution Plan

### Phase 1: nvpmodel Label Fix

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 1  
**Prerequisites:** None  
**Entry Point:** `scripts/jetson-harden.sh`  
**Verification:** `grep "nvpmodel" scripts/jetson-harden.sh` shows consistent mode 3 (50W) in both code and label

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Change summary label from `"nvpmodel:nvpmodel mode 2 (30W)"` to `"nvpmodel:nvpmodel mode 3 (50W)"` on line 246 | `scripts/jetson-harden.sh` | ✅ Complete |
| 1.2 | Change progress echo from `echo "[6/9] nvpmodel (30W)..."` to `echo "[6/9] nvpmodel (50W)..."` on line 295 | `scripts/jetson-harden.sh` | ✅ Complete |

### Phase 2: Operational Runbook

**Status:** ✅ Complete (runbook embedded; ready for operator execution)  
**Size:** Medium  
**Files to Modify:** 1 (this plan document — runbook is embedded here)  
**Prerequisites:** Phase 1 complete (label fix committed before flash)  
**Entry Point:** This section  
**Verification:** Operator has completed all stages A–E; all probe checks pass

#### Stage A: Pre-Flash Backup (from Windows laptop)

```powershell
# 1. Create backup directory
$backup = "$env:USERPROFILE\jetson-backup-$(Get-Date -Format 'yyyy-MM-dd')"
New-Item -ItemType Directory -Path $backup -Force

# 2. Pull config files (optional safety net — all are reproducible)
scp vincent@192.168.4.38:/etc/ssh/sshd_config.d/90-mower-hardening.conf "$backup\"
scp vincent@192.168.4.38:/etc/fstab "$backup\"
scp vincent@192.168.4.38:/etc/environment "$backup\"
scp vincent@192.168.4.38:/etc/NetworkManager/system-connections/* "$backup\" 2>$null

# 3. Record package state and L4T version
ssh vincent@192.168.4.38 "dpkg --get-selections" > "$backup\dpkg-selections.txt"
ssh vincent@192.168.4.38 "cat /etc/nv_tegra_release" > "$backup\nv_tegra_release.txt"

# 4. Back up .wslconfig if it exists (SDK Manager will overwrite it)
if (Test-Path "$env:USERPROFILE\.wslconfig") {
    Copy-Item "$env:USERPROFILE\.wslconfig" "$env:USERPROFILE\.wslconfig.pre-sdkmgr"
}
```

#### Stage B: SDK Manager Flash

**→ Follow [Research 005, Phase 4](/docs/research/005-jetson-agx-orin-jetpack6-reflash.md#phase-4-sdk-manager-flash-procedure) step-by-step.**

Key settings to select:
- **Target:** Jetson AGX Orin Dev Kit
- **SDK Version:** JetPack 6.2.2
- **Storage:** NVMe
- **Pre-Config:** username=`vincent`, hostname=`jetson-mower`

**Hardware prep:** Use USB-C port 10 (J40, next to 40-pin header). Force Recovery: Hold Recovery → Press+Release Power → Release Recovery. See [Research 005, Phase 3](/docs/research/005-jetson-agx-orin-jetpack6-reflash.md#phase-3-pre-flash-backup--preparation) for button layout.

**If SDK Manager fails:** Fall back to live Ubuntu 22.04 USB boot. See [Research 005, Phase 4 fallback](/docs/research/005-jetson-agx-orin-jetpack6-reflash.md#fallback-cli-flash-from-live-ubuntu-usb).

#### Stage C: Post-Flash Manual Setup (Jetson console)

```bash
# 1. Verify boot
cat /etc/nv_tegra_release
# Expected: # R36 (release), REVISION: 5.0, ...

# 2. Configure static IP
nmcli device status  # Note the connection name
sudo nmcli con mod "Wired connection 1" \
    ipv4.addresses 192.168.4.38/24 \
    ipv4.gateway 192.168.4.1 \
    ipv4.method manual
sudo nmcli con up "Wired connection 1"

# 3. Passwordless sudo
echo "vincent ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/vincent
sudo chmod 440 /etc/sudoers.d/vincent

# 4. If CUDA missing (SDK Manager post-flash SSH step failed):
sudo apt update && sudo apt install -y nvidia-jetpack
nvcc --version  # Expected: release 12.6
```

#### Stage D: Automated Re-Bringup (from Windows laptop)

```powershell
# 1. Clear stale SSH host key (MANDATORY — host key changed after reflash)
ssh-keygen -R 192.168.4.38

# 2. Verify connectivity
ping 192.168.4.38

# 3. Run first-time setup (deploys SSH key, writes laptop.yaml)
uv run mower jetson setup

# 4. Run full bringup (hardening, uv, CLI, probe, service)
uv run mower jetson bringup --host 192.168.4.38 --user vincent --yes
```

Bringup is idempotent — safe to re-run if any step fails partway through.

#### Stage E: Verification Checklist

After `mower jetson bringup` completes, all probe checks should pass:

| Probe Check | Expected Value | Severity |
|-------------|---------------|----------|
| `jetpack_version` | `# R36 (release), REVISION: 5.0, ...` | CRITICAL |
| `cuda` | `release 12.6, V12.6.x` | CRITICAL |
| `python_ver` | Python 3.11+ (installed by bringup) | CRITICAL |
| `oakd` | USB vendor 03e7 (if camera plugged in) | WARNING |
| `thermal` | Thermal zone readings | WARNING |
| `power_mode` | `POWER_MODEL ID=3` (50W, set by hardening) | WARNING |
| `disk_space` | Sufficient free space on NVMe | WARNING |
| `ssh_hardening` | 90-mower-hardening.conf present | WARNING |

**Additional manual verifications:**
```bash
# On Jetson — verify nvpmodel
nvpmodel -p --verbose  # Confirm mode 3 = 50W on L4T 36.5

# On Jetson — verify L4T package hold
dpkg -l | grep nvidia-l4t  # Confirm packages exist and are held

# On laptop — verify health monitoring
uv run mower jetson health --host 192.168.4.38 --user vincent
```

## Standards

No organizational standards applicable to this plan.

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 0  
**Last Updated:** 2026-04-23

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| — | No clarifying questions required | — | — | — |

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 1 | 1 file (`scripts/jetson-harden.sh`) |
| New patterns introduced | 1 | No new patterns |
| External dependencies | 1 | No external dependencies |
| Migration complexity | 1 | N/A — string literal fix |
| Test coverage required | 1 | Code review only (Planning Decision #2) |
| **Overall Complexity** | **5/25** | **Low** |

## Review Summary

**Review Date:** 2026-04-23  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 2 (Critical: 0, Major: 1, Minor: 1)
- Clarifying Questions Asked: 0
- Sections Updated: Technical Design, Execution Plan Phase 1, Version History

### Key Improvements Made
1. **Added missed line 295 fix** — progress echo `"[6/9] nvpmodel (30W)..."` also needs updating to `(50W)`. Added as Step 1.2 in Phase 1.
2. **Corrected line reference** — section comment is on line 135, not 136 as originally stated.

### Remaining Considerations
- Open questions from research 005 (nvpmodel mode table, apt-mark package names) still require field verification after flash — correctly documented in Risks table.
- Runbook Stage B depends on research 005 links — confirm anchor names still resolve if research doc is edited.

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Implementation Notes

### Phase 1 - nvpmodel Label Fix
**Completed:** 2026-04-23
**Execution Mode:** Automatic (Subagent)

**Files Modified:**
- `scripts/jetson-harden.sh`

**Deviations from Plan:** None

**Notes:**
- Line 246 summary label changed from "nvpmodel:nvpmodel mode 2 (30W)" to "nvpmodel:nvpmodel mode 3 (50W)"
- Line 295 progress echo changed from "[6/9] nvpmodel (30W)..." to "[6/9] nvpmodel (50W)..."
- All nvpmodel references now consistently show mode 3 (50W)

### Phase 2 - Operational Runbook
**Completed:** 2026-04-23
**Execution Mode:** N/A (runbook embedded in plan document during planning)

**Notes:**
- Runbook stages A–E are fully embedded in the Execution Plan section
- Ready for operator execution after Phase 1 code fix is committed

### Plan Completion
**All phases completed:** 2026-04-23
**Total tasks completed:** 2
**Total files modified:** 1 (`scripts/jetson-harden.sh`)
**Code review:** Clean — no issues found

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-23 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-23 |
| Status | ✅ Complete |
| Next Agent | Operator (execute runbook) |
| Plan Location | /docs/plans/006-jetpack6-reflash-and-rebringup.md |
