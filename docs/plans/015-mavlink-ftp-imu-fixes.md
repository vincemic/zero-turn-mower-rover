---
id: "015"
type: plan
title: "MAVLink FTP API Migration & RTAB-Map IMU Orientation Fix"
status: ✅ Complete
created: "2026-05-04"
updated: "2026-05-04"
completed: "2026-05-04"
owner: pch-planner
version: v2.1
research: docs/research/018-mavlink-ftp-imu-fixes.md
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-04 | pch-planner | Initial plan skeleton || v1.1 | 2026-05-04 | pch-planner | Added tempdir lifecycle decision |
| v1.2 | 2026-05-04 | pch-planner | Added IMU sensor config decision (YAML field) |
| v1.3 | 2026-05-04 | pch-planner | Added health monitoring scope + probe mechanism decisions |
| v2.0 | 2026-05-04 | pch-planner | Holistic review completed; full execution plan |
| v2.1 | 2026-05-04 | pch-plan-reviewer | Review: added cmd_put return guard; fixed IMU constructor terminology |
| v3.0 | 2026-05-04 | pch-coder | All 3 phases implemented and verified (658 tests pass) |
## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 1  
**Last Updated:** 2026-05-04

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | cmd_put return value not checked before process_ftp_reply (30s hang risk) | correctness | Option A: Add two-step guard | Component 1 write_file + Step 1.6 updated |

## Introduction

This plan addresses two unrelated faults in the VSLAM MAVLink bridge observed after the latest Jetson reboot: (1) the Lua auto-deploy fails because `_FTPSession` in `lua_deploy.py` uses a callback-based pymavlink MAVFTP API that no longer exists in pymavlink 2.4.49, and (2) RTAB-Map discards all IMU data because the DepthAI pipeline never requests a rotation-vector sensor from the BNO086. Both fixes are surgical, low-risk, and independent.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Tempdir lifecycle for MAVFTP.read() side-effect file | A — Leave uncleaned (process-scoped) | Single small file (~2 KB), bridge is long-running systemd service, /tmp cleaned on reboot; no need for cleanup machinery |
| 2 | IMU rotation sensor configurability | B — Expose as YAML config field | User prefers runtime configurability via VslamConfig dataclass and YAML, avoiding recompilation to switch sensor type |
| 3 | Health-monitoring follow-up scope | A — Include in this plan as a third phase | Add Lua SHA verify after deploy + RTAB-Map log scan for orientation warning as Phase 3 of this plan |
| 4 | RTAB-Map log scan mechanism | A — New probe check via subprocess journalctl | Follows existing probe pattern (registry-decorated, subprocess calls); on-demand only via `mower-jetson probe`; no C++ or IPC changes |

## Holistic Review

### Decision Interactions

- **Decisions 1 + 2 (tempdir + YAML config):** No conflict. The tempdir is Python-internal to the FTP session; the YAML config field flows through to C++ only. They touch entirely different code paths.
- **Decisions 2 + 3 (YAML config + health probe):** Synergy — the probe validates that the configured sensor is actually working (i.e., no "orientation set" warnings). If someone configures `rotation_vector` (9-DoF with mag) on this platform, the probe might still pass (data flows) but quality could be poor. This is acceptable — the probe checks for the failure mode, not optimal configuration.
- **Decisions 3 + 4 (health scope + journalctl):** The probe check is lightweight and on-demand, consistent with keeping health monitoring in Phase 3 rather than the daemon loop.

### Architectural Considerations

- **Phase independence:** Phase 1 (Python FTP) and Phase 2 (C++ IMU + Python config) are fully independent — they can be implemented in parallel or in either order. Phase 3 depends on Phase 2 only conceptually (the probe validates IMU orientation is working after the fix).
- **No cross-language coupling in Phase 1:** The FTP rewrite is entirely internal to Python; the C++ node doesn't use FTP.
- **Config field addition is backward-compatible:** The YAML field has a default; existing config files without `imu_rotation_sensor` continue working (both Python and C++ fall back to `"game_rotation_vector"`).
- **Probe check is platform-gated:** `journalctl` won't exist on Windows dev machines. The `FileNotFoundError` handler returns a non-blocking result, so `mower-jetson probe` only produces meaningful output on the Jetson.

### Trade-offs Accepted

- ~15s FTP latency at bridge startup (4 × 3.7s idle_detection_time) — acceptable for once-per-boot operation
- Temp file left on disk until reboot — single ~2 KB file in `/tmp`, no cleanup needed
- YAML config field exposes 3 sensor options but only 1 is correct for this platform — documented as operator guidance, not enforced by validation

### Risks Acknowledged

- The `MAVFTP.read()` return-None-on-failure behavior is documented but not field-tested with this specific Pixhawk firmware version — mitigated by try/except wrapper
- The post-upload SHA verify adds one extra FTP `read()` call (~3.7s) to every successful deploy — only runs when a new version is uploaded (rare), not on every bridge start

## Overview

Two independent bugs prevent the VSLAM MAVLink bridge from operating at full capability:

1. **Lua FTP deploy failure** — `_FTPSession` in `lua_deploy.py` uses a callback-based pymavlink MAVFTP API that was removed in pymavlink 2.4.49 (the version installed on the Jetson). Every FTP operation fails with `TypeError` or `AttributeError`, preventing the AHRS source-switching Lua script from being deployed to the Pixhawk.

2. **RTAB-Map IMU data discarded** — The DepthAI pipeline in `rtabmap_slam_node.cpp` only enables raw accelerometer and gyroscope, never requesting a rotation-vector sensor. The BNO086 IMU's orientation quaternion stays at zeros, causing RTAB-Map's odometry engine to discard all IMU packets. The system runs as visual-only odometry, fragile on a vibrating mower.

**Objectives:**
- Rewrite `_FTPSession` internals to use the synchronous pymavlink 2.4.49 MAVFTP API
- Add `GAME_ROTATION_VECTOR` sensor to the DepthAI pipeline and feed the quaternion to RTAB-Map
- Expose `imu_rotation_sensor` as a configurable YAML field in `VslamConfig`
- Add health-monitoring probes for both failure modes

## Requirements

### Functional

- FR-1: `_FTPSession.mkdir()` creates directories idempotently using synchronous `cmd_mkdir` API
- FR-2: `_FTPSession.list_directory()` returns filenames using synchronous `cmd_list` + `list_result` side-effect
- FR-3: `_FTPSession.read_file()` downloads files using `MAVFTP.read()` (internal pump loop)
- FR-4: `_FTPSession.write_file()` uploads files using `cmd_put(fh=BytesIO)` + `process_ftp_reply`
- FR-5: `rtabmap_slam_node` enables a configurable rotation-vector sensor (default: `GAME_ROTATION_VECTOR`)
- FR-6: `rtabmap_slam_node` reads the quaternion from `IMUPacket.rotationVector` and passes it to RTAB-Map's 7-arg `IMU` constructor
- FR-7: `VslamConfig` exposes `imu_rotation_sensor` field (string, validated, default `"game_rotation_vector"`)
- FR-8: C++ `SlamConfig` reads `imu_rotation_sensor` from YAML and maps to `dai::IMUSensor` enum
- FR-9: Probe check `vslam_imu_orientation` scans recent RTAB-Map journal for the "orientation set" warning
- FR-10: Lua deploy includes a post-upload read-back SHA verification with warning log on mismatch

### Non-Functional

- NFR-1: Public API of `_FTPSession` (`mkdir`, `list_directory`, `read_file`, `write_file`) unchanged — callers and all 12 existing tests pass without modification
- NFR-2: Total FTP latency budget ≤ 30s for full deploy cycle (4 ops × ~3.7s idle_detection_time + transfer)
- NFR-3: C++ changes compile cleanly with existing `CMakeLists.txt` (no new dependencies)
- NFR-4: New probe check works offline (journal is local) and runs in < 5s

### Out of Scope

- Tuning `idle_detection_time` for faster FTP ops (acceptable at default 3.7s)
- Making `_FTPSession` a context manager or adding cleanup
- Adding `ROTATION_VECTOR` (9-DoF with magnetometer) — unsuitable for this platform
- RTAB-Map loop closure tuning or database management
- Health daemon integration (probe is on-demand only)

## Technical Design

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: "_FTPSession internal class"
    location: "src/mower_rover/vslam/lua_deploy.py"
    usage: Rewrite internals; preserve public method signatures
  - pattern: "DepthAI IMU pipeline setup"
    location: "contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp (L247-255)"
    usage: Add configurable rotation-vector sensor enable
  - pattern: "RTAB-Map IMU data feeding"
    location: "contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp (L660-698)"
    usage: Read quaternion and use 7-arg IMU constructor
  - pattern: "Mock-at-class-boundary testing"
    location: "tests/test_vslam_lua_deploy.py"
    usage: Tests mock _FTPSession; no test changes needed
  - pattern: "VslamConfig dataclass with validation"
    location: "src/mower_rover/config/vslam.py"
    usage: Add imu_rotation_sensor field with allowed-set validation
  - pattern: "SlamConfig YAML loading (C++)"
    location: "contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp (L81-160)"
    usage: Read imu_rotation_sensor string, map to dai::IMUSensor enum
  - pattern: "Probe registry-decorated checks"
    location: "src/mower_rover/probe/checks/vslam.py"
    usage: Add vslam_imu_orientation probe (journalctl subprocess)
```

### Component 1: `_FTPSession` Rewrite (Python)

**File:** `src/mower_rover/vslam/lua_deploy.py`

**Deletions:**
- `self._result`, `self._error`, `self._listing`, `self._done` state fields (lines 57–60)
- `_list_cb`, `_read_cb`, `_write_cb`, `_generic_cb` methods (lines 104–133)
- `_pump` method (lines 135–142)
- Per-method state resets in each public method

**Additions:**
- `import os`, `import tempfile` and `from io import BytesIO` at module top
- `from pymavlink.mavftp import FtpError` inside methods (deferred import pattern)
- `self._tmpdir = tempfile.mkdtemp()` in `__init__`
- New `mkdir` implementation:
  ```python
  def mkdir(self, path: str) -> None:
      from pymavlink.mavftp import FtpError
      ret = self._ftp.cmd_mkdir([path])
      if ret.error_code not in (FtpError.Success, FtpError.FileExists):
          raise OSError(f"mkdir {path}: FTP error {ret.error_code}")
  ```
- New `list_directory` implementation:
  ```python
  def list_directory(self, path: str) -> list[str]:
      from pymavlink.mavftp import FtpError
      ret = self._ftp.cmd_list([path])
      if ret.error_code != FtpError.Success:
          raise OSError(f"list {path}: FTP error {ret.error_code}")
      return [entry.name for entry in self._ftp.list_result]
  ```
- New `read_file` implementation:
  ```python
  def read_file(self, path: str) -> bytes:
      self._ftp.filename = os.path.join(self._tmpdir, "mavftp_dl")
      data = self._ftp.read(path, 0x40000)
      if data is None:
          raise OSError(f"read {path}: FTP transfer failed")
      return data
  ```
- New `write_file` implementation:
  ```python
  def write_file(self, path: str, data: bytes) -> None:
      from io import BytesIO
      from pymavlink.mavftp import FtpError
      ret = self._ftp.cmd_put([path, path], fh=BytesIO(data))
      if ret.error_code != FtpError.Success:
          raise OSError(f"write {path}: FTP create error {ret.error_code}")
      ret = self._ftp.process_ftp_reply('CreateFile', timeout=30)
      if ret.error_code != FtpError.Success:
          raise OSError(f"write {path}: FTP transfer error {ret.error_code}")
  ```

**Post-upload SHA verify (in `check_and_deploy_lua`):**
After `ftp.write_file(_REMOTE_PATH, bundled)`, add:
```python
try:
    readback = ftp.read_file(_REMOTE_PATH)
    if readback != bundled:
        log.warning("lua_deploy_verify_mismatch", expected_len=len(bundled), got_len=len(readback))
except OSError as exc:
    log.warning("lua_deploy_verify_failed", error=str(exc))
```

### Component 2: IMU Orientation Fix (C++)

**File:** `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`

**Change 1 — `SlamConfig` struct (after line 89, add field):**
```cpp
std::string imu_rotation_sensor = "game_rotation_vector";
```

**Change 2 — `load_config` (after `slam_mode` reading, add):**
```cpp
if (vslam["imu_rotation_sensor"])
    cfg.imu_rotation_sensor = vslam["imu_rotation_sensor"].as<std::string>();
```

**Change 3 — Helper function (before pipeline creation):**
```cpp
static dai::IMUSensor parse_imu_rotation_sensor(const std::string &name) {
    if (name == "game_rotation_vector") return dai::IMUSensor::GAME_ROTATION_VECTOR;
    if (name == "rotation_vector") return dai::IMUSensor::ROTATION_VECTOR;
    if (name == "arvr_stabilized_game_rotation_vector")
        return dai::IMUSensor::ARVR_STABILIZED_GAME_ROTATION_VECTOR;
    std::cerr << "[config] Unknown imu_rotation_sensor '" << name
              << "'; defaulting to GAME_ROTATION_VECTOR" << std::endl;
    return dai::IMUSensor::GAME_ROTATION_VECTOR;
}
```

**Change 4 — Pipeline creation (after line 252, add sensor):**
```cpp
imu->enableIMUSensor(
    parse_imu_rotation_sensor(cfg.imu_rotation_sensor), cfg.imu_rate_hz);
```

**Change 5 — IMU drain loop (lines 663–675, add quaternion extraction):**
```cpp
// Zero quaternion = no orientation data yet; RTAB-Map will discard
// IMU until first valid rotation packet arrives (graceful startup).
cv::Vec4d orientation(0, 0, 0, 0);  // qx, qy, qz, qw
// Inside per-packet loop, after gyro extraction:
if (p.rotationVector.real != 0 || p.rotationVector.i != 0 ||
    p.rotationVector.j != 0 || p.rotationVector.k != 0) {
    orientation[0] = p.rotationVector.i;
    orientation[1] = p.rotationVector.j;
    orientation[2] = p.rotationVector.k;
    orientation[3] = p.rotationVector.real;
}
```

**Change 6 — Replace 5-arg IMU constructor with 7-arg (lines 688–691):**
```cpp
sensor_data.setIMU(rtabmap::IMU(
    orientation, cv::Mat::eye(3, 3, CV_64FC1),
    gyro,        cv::Mat::eye(3, 3, CV_64FC1),
    accel,       cv::Mat::eye(3, 3, CV_64FC1),
    imu_local_transform));
```

### Component 3: Python Config Extension

**File:** `src/mower_rover/config/vslam.py`

**Add to `VslamConfig` dataclass (after `imu_rate_hz` field):**
```python
imu_rotation_sensor: str = "game_rotation_vector"
```

**Add validation set:**
```python
_VALID_IMU_ROTATION_SENSORS = {"game_rotation_vector", "rotation_vector", "arvr_stabilized_game_rotation_vector"}
```

**Add to `_coerce()` function (after `imu_rate_hz` validation):**
```python
imu_rotation_sensor = vslam_raw.get("imu_rotation_sensor", "game_rotation_vector")
if imu_rotation_sensor not in _VALID_IMU_ROTATION_SENSORS:
    raise VslamConfigError(
        f"imu_rotation_sensor must be one of {_VALID_IMU_ROTATION_SENSORS}, got {imu_rotation_sensor!r}"
    )
```

**Add to `to_dict()` method and `VslamConfig(...)` constructor call in `_coerce()`.**

### Component 4: Probe Checks

**File:** `src/mower_rover/probe/checks/vslam.py`

**New check — `vslam_imu_orientation`:**
```python
@register("vslam_imu_orientation", severity=Severity.WARNING, depends_on=("vslam_process",))
def check_vslam_imu_orientation(sysroot: Path) -> tuple[bool, str]:
    """Scan recent RTAB-Map journal for IMU orientation warnings."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", _VSLAM_SERVICE, "--since", "5 min ago",
             "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Cannot read journal for mower-vslam.service"
    if "doesn't have orientation set" in result.stdout:
        return False, "RTAB-Map IMU orientation warning detected — IMU data being discarded"
    if result.stdout.strip():
        return True, "No IMU orientation warnings in last 5 min"
    return True, "No recent VSLAM journal output (service may not have run)"
```

## Dependencies

| Dependency | Type | Impact |
|-----------|------|--------|
| pymavlink 2.4.49 on Jetson | Runtime | FTP rewrite targets this specific API version |
| depthai-core with `GAME_ROTATION_VECTOR` support | Compile-time | OAK-D Pro BNO086 must support this sensor (confirmed in research) |
| RTAB-Map 7-arg `IMU` constructor | Compile-time | Available in rtabmap ≥ 0.21 (confirmed installed on Jetson) |
| yaml-cpp in C++ build | Compile-time | Already in `CMakeLists.txt` |
| systemd journal on Jetson | Runtime | Probe check reads `journalctl` output |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `MAVFTP.read()` raises instead of returning `None` on failure | Low | Medium | Wrap in try/except, re-raise as `OSError` |
| `process_ftp_reply('CreateFile', timeout=30)` returns before upload completes on slow SD cards | Low | Medium | 30s timeout is generous; can increase if field-testing shows issues |
| BNO086 doesn't support `GAME_ROTATION_VECTOR` at configured rate | Very Low | High | Datasheet confirms up to 400 Hz; our default is 200 Hz |
| `idle_detection_time` adds ~15s total to bridge startup (4 ops × 3.7s) | Certain | Low | Acceptable for once-per-boot; documented in research |
| Existing tests break from internal refactor | Very Low | Medium | Tests mock at class boundary; public API unchanged |
| Journal may not have 5 min of data if service just started | Low | Low | Probe returns "pass" with explanatory message when no output found |

## Execution Plan

### Phase 1: `_FTPSession` Rewrite + Lua SHA Verify

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 1 (`src/mower_rover/vslam/lua_deploy.py`)  
**Prerequisites:** None  
**Entry Point:** `src/mower_rover/vslam/lua_deploy.py`  
**Verification:** All 12 tests in `tests/test_vslam_lua_deploy.py` pass; `pytest tests/test_vslam_lua_deploy.py -v`

| Step | Task | Files | Status |
|------|------|-------|--------|
| 1.1 | Add `import os` and `import tempfile` at module top | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.2 | Rewrite `_FTPSession.__init__`: remove state flags; add `self._tmpdir = tempfile.mkdtemp()` | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.3 | Rewrite `mkdir()`: synchronous `cmd_mkdir` + `FtpError.Success`/`FileExists` check | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.4 | Rewrite `list_directory()`: synchronous `cmd_list` + read `self._ftp.list_result` | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.5 | Rewrite `read_file()`: set `self._ftp.filename` to tmpdir path, call `self._ftp.read(path, 0x40000)` | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.6 | Rewrite `write_file()`: check `cmd_put` return for early errors, then `process_ftp_reply('CreateFile', timeout=30)` | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.7 | Delete all `_*_cb` callback methods and `_pump` method | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.8 | Add post-upload SHA verify in `check_and_deploy_lua` | `src/mower_rover/vslam/lua_deploy.py` | ✅ Complete |
| 1.9 | Run `pytest tests/test_vslam_lua_deploy.py -v` — all 12 tests pass | — | ✅ Complete |
| 1.10 | Run `pytest tests/ -k "not sitl and not field" --tb=short` — no regressions | — | ✅ Complete |

### Phase 2: RTAB-Map IMU Orientation Fix + Python/C++ Config

**Status:** ✅ Complete  
**Size:** Medium  
**Files to Modify:** 3 (`contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`, `src/mower_rover/config/vslam.py`, `tests/test_vslam_config.py`)  
**Prerequisites:** None (independent of Phase 1)  
**Entry Point:** `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`  
**Verification:** C++ compiles (`cd contrib/rtabmap_slam_node && mkdir -p build && cd build && cmake .. && make`); Python tests pass (`pytest tests/test_vslam_config.py -v`)

| Step | Task | Files | Status |
|------|------|-------|--------|
| 2.1 | Add `imu_rotation_sensor` field to `SlamConfig` struct | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.2 | Add YAML loading for `imu_rotation_sensor` in `load_config()` | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.3 | Add `parse_imu_rotation_sensor()` helper function | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.4 | Enable rotation-vector sensor in DepthAI pipeline | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.5 | Add `cv::Vec4d orientation(0,0,0,0)` declaration before IMU drain loop | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.6 | Extract quaternion from `p.rotationVector` inside per-packet loop | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.7 | Replace 5-arg `rtabmap::IMU` constructor with 7-arg orientation-aware constructor | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 2.8 | Add `imu_rotation_sensor` field to Python `VslamConfig` dataclass | `src/mower_rover/config/vslam.py` | ✅ Complete |
| 2.9 | Add `_VALID_IMU_ROTATION_SENSORS` set and validation in `_coerce()` | `src/mower_rover/config/vslam.py` | ✅ Complete |
| 2.10 | Add `imu_rotation_sensor` to `to_dict()` and `VslamConfig(...)` constructor call | `src/mower_rover/config/vslam.py` | ✅ Complete |
| 2.11 | Add test for `imu_rotation_sensor` validation | `tests/test_vslam_config.py` | ✅ Complete |
| 2.12 | Run `pytest tests/test_vslam_config.py -v` — all tests pass | — | ✅ Complete |

### Phase 3: Health-Monitoring Probe Checks

**Status:** ✅ Complete  
**Size:** Small  
**Files to Modify:** 2 (`src/mower_rover/probe/checks/vslam.py`, `tests/test_probe_vslam.py`)  
**Prerequisites:** Phase 2 complete (probe depends on `vslam_process` being meaningful)  
**Entry Point:** `src/mower_rover/probe/checks/vslam.py`  
**Verification:** `pytest tests/test_probe_vslam.py -v`

| Step | Task | Files | Status |
|------|------|-------|--------|
| 3.1 | Add `vslam_imu_orientation` probe check: scan journal for "doesn't have orientation set" | `src/mower_rover/probe/checks/vslam.py` | ✅ Complete |
| 3.2 | Register with `severity=Severity.WARNING, depends_on=("vslam_process",)` | `src/mower_rover/probe/checks/vslam.py` | ✅ Complete |
| 3.3 | Handle `FileNotFoundError` and `TimeoutExpired` gracefully | `src/mower_rover/probe/checks/vslam.py` | ✅ Complete |
| 3.4 | Add unit tests for `vslam_imu_orientation` probe (3 scenarios) | `tests/test_probe_vslam.py` | ✅ Complete |
| 3.5 | Run `pytest tests/test_probe_vslam.py -v` — all tests pass | — | ✅ Complete |
| 3.6 | Run full test suite — no regressions | — | ✅ Complete |

## Standards

No organizational standards applicable to this plan.

## Review Summary

**Review Date:** 2026-05-04
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 4 (Critical: 0, Major: 2, Minor: 2)
- Clarifying Questions Asked: 1
- Sections Updated: Version History, Component 1 (write_file), Step 1.1, Step 1.6, Step 2.7, Change 5, Change 6

### Key Improvements Made
1. Added `cmd_put` return-value guard in `write_file` to avoid 30s hang on early-return errors (PutAlreadyInProgress, InvalidArguments)
2. Fixed "2-arg" → "5-arg" IMU constructor terminology to match actual RTAB-Map API (the existing constructor takes gyro, cov, accel, cov, transform)
3. Added startup-behavior comment on zero-quaternion (documents intentional graceful degradation during first frames)
4. Fixed `import os` — moved to module-top imports (Step 1.1) since it's stdlib and doesn't need deferred import treatment

### Remaining Considerations
- Phase 1 adds ~15s FTP latency at bridge startup (documented and accepted)
- The post-upload SHA verify (Step 1.8) adds ~3.7s to successful deploys only (rare event)
- Field validation required to confirm `MAVFTP.read()` returns `None` (vs raises) on actual Pixhawk firmware

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 4 files across 2 languages (Python + C++) |
| New patterns introduced | 1 | All changes follow existing patterns |
| External dependencies | 1 | No new deps; uses installed pymavlink + depthai |
| Migration complexity | 1 | No data migration; pure code replacement |
| Test coverage required | 2 | Unit tests only; field test for IMU deferred |
| **Overall Complexity** | 7/25 | Low |

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Implementation Notes

### Plan Completion

**All phases completed:** 2026-05-04
**Total tasks completed:** 28/28
**Total files modified/created:** 4

### Phase 1 — `_FTPSession` Rewrite + Lua SHA Verify

**Completed:** 2026-05-04

**Files Modified:**

- `src/mower_rover/vslam/lua_deploy.py`

**Deviations from Plan:** None

**Notes:** Synchronous MAVFTP API rewrite complete. All 12 existing tests pass unchanged (mock at class boundary). Post-upload SHA verify logs warning on mismatch, swallows read-back OSError.

### Phase 2 — RTAB-Map IMU Orientation Fix + Python/C++ Config

**Completed:** 2026-05-04

**Files Modified:**

- `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`
- `src/mower_rover/config/vslam.py`
- `tests/test_vslam_config.py`

**Deviations from Plan:** None

**Notes:** C++ `parse_imu_rotation_sensor()` helper added. 7-arg IMU constructor with orientation quaternion. Python `VslamConfig` has `imu_rotation_sensor` field with validation. 5 new config tests added (default, valid values, invalid, to_dict, round-trip).

### Phase 3 — Health-Monitoring Probe Checks

**Completed:** 2026-05-04

**Files Modified:**

- `src/mower_rover/probe/checks/vslam.py`
- `tests/test_probe_vslam.py`

**Deviations from Plan:** None

**Notes:** `vslam_imu_orientation` probe check registered with WARNING severity. Handles `FileNotFoundError` and `TimeoutExpired`. 5 test cases added (pass with output, fail with warning, journalctl not found, empty journal, registry check).

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-04 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-04 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | docs/plans/015-mavlink-ftp-imu-fixes.md |
