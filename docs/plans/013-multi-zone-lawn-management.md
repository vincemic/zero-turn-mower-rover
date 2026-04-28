---
id: "013"
type: plan
title: "Multi-Zone Lawn Management — NE, NW, and South Lawns"
status: ✅ Complete
created: "2026-04-27"
updated: "2026-04-28"
completed: "2026-04-28"
owner: pch-planner
version: v2.2
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-27 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-27 | pch-planner | Decisions 1-5 recorded; all sections populated |
| v2.0 | 2026-04-27 | pch-planner | Holistic review completed; 8-phase execution plan finalized |
| v2.1 | 2026-04-27 | pch-plan-reviewer | Review fixes: Severity.WARN→WARNING, probe path probe/checks/zone.py, depends_on vslam_process, _coerce naming |
| v2.2 | 2026-04-27 | pch-plan-reviewer | Decision: zone resume display-only (B). Complexity assessment + review summary added. Ready for implementation. |

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 1  
**Last Updated:** 2026-04-27

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | `zone resume` re-arm + mode-set safety semantics | correctness | Option B: Display-only resume — sets mission index via MISSION_SET_CURRENT, does NOT arm or set Auto. Operator arms via RC transmitter. | FR-6, CLI table, step 6.5 updated |

## Introduction

Implementation plan for multi-zone lawn management across the three-zone property (NE, NW, South lawns). Covers zone YAML configuration, `ZoneConfig` dataclass, VSLAM database-per-zone switching, ArduPilot mission/fence/rally per-zone upload, `mower zone` CLI commands (laptop), `mower-jetson zone` CLI commands (Jetson), zone-aware pre-flight checks, and the clear-all-on-failure safety guard. Based on [docs/research/014-multi-zone-lawn-management.md](docs/research/014-multi-zone-lawn-management.md).

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Implementation scope | A — Full implementation in one plan | All 5 research phases are tightly coupled; `mower zone select` orchestrates both Jetson VSLAM and MAVLink uploads; C++ change is minimal; execution phases provide session-sized granularity |
| 2 | MAVLink mission upload approach | B — Use existing param I/O patterns, extend for missions | Codebase has `open_link()` in `src/mower_rover/mavlink/connection.py`; new `src/mower_rover/mavlink/mission.py` reuses same connection pattern; avoids duplicating MAVLink setup; delivers fully testable upload/download/clear for mission/fence/rally |
| 3 | Coverage path planning | A — Include coverage path planner in this plan | Coverage planning is core value of zone select; zone YAML schema already defines all needed params; Shapely + pyproj already in pyproject.toml; boustrophedon for simple polygons is ~200–400 lines; deferring leaves zone YAML half-functional |
| 4 | Testing strategy | B — Unit tests + SITL integration for MAVLink | Unit tests for coverage planner (Shapely geometry) and ZoneConfig (YAML fixtures); SITL tests for mission/fence/rally upload→download→verify round-trip and armed-check guard; field tests marked `@pytest.mark.field` for actual waypoint execution |
| 5 | GeoJSON export / status tracking | B — GeoJSON export only, defer status tracking | GeoJSON export is a safety validation tool (visual boundary check in QGIS before first mow); zone status tracking is operational convenience that can follow after core workflow is proven |

## Holistic Review

### Decision Interactions

1. **Full-scope plan (D1) + coverage planner (D3)** — Including the planner makes Phase 2 the heaviest pure-algorithm phase. It has no MAVLink or hardware dependency, so it can be developed and tested independently. Phase 3 (MAVLink) depends on Phase 2 output format but not on the algorithm itself — the interface is `list[LatLon]`.

2. **MAVLink pattern reuse (D2) + SITL testing (D4)** — Using `open_link()` from `connection.py` means SITL tests can use the same connection manager as production code. The mission protocol functions get tested against real ArduPilot message handling, not just mocks.

3. **GeoJSON export (D5) + no status tracking** — GeoJSON export shares the planner's waypoint output. Since zone status tracking is deferred, there's no persistent session state to manage — the plan stays stateless between zone select invocations. This simplifies error recovery: each `mower zone select` is idempotent.

### Architectural Considerations

- **Phase ordering is dependency-safe**: Phases 1–2 are pure Python (no hardware). Phase 3 adds MAVLink protocol (testable with mocks). Phase 4 is a small config change. Phase 5 is Jetson-only. Phase 6 integrates everything. Phase 7 adds observability. Phase 8 validates against SITL.
- **No circular dependencies**: `zone/config.py` has no imports from other zone submodules. `zone/planner.py` imports only `zone/config.py`. `zone/mission_items.py` imports both. `mavlink/mission.py` is zone-agnostic.
- **C++ change is isolated**: The SLAM node change (Phase 4, steps 4.4–4.5) is ~10 lines and only affects the init path. No runtime behavior change for existing `mapping` mode.

### Trade-offs Accepted

- **`angle_deg: auto` not implemented** — Fixed angle requires operator to set heading manually in zone YAML. Auto-optimization (minimum-turns algorithm) deferred.
- **No zone status tracking** — Operator must manually track which zones are done during a session. Acceptable for early field sessions.
- **Pre-flight PF-39/PF-40 are SSH-based** — Requires Jetson reachable for these WARN-level checks. If SSH fails, checks are skipped (not CRITICAL).

### Risk Interactions

- **Mission/fence mismatch risk** is addressed at three layers: (1) atomic upload with clear-on-failure, (2) PF-37 CRITICAL pre-flight check, (3) ArduPilot's own fence enforcement. All three must fail simultaneously for a boundary breach.
- **MAVLink2 requirement for fence upload** — If the SiK radio doesn't support MAVLink2, fence upload will fail. This would be caught by the upload error and trigger clear-all. A pre-flight note should document verifying `SERIAL2_PROTOCOL=2`.

## Overview

The property has three distinct mowing areas — North East (NE), North West (NW), and South lawns — separated by the house, driveway, and non-mowable terrain. This plan implements multi-zone management: zone YAML definitions, boustrophedon coverage path planning, ArduPilot mission/fence/rally upload per zone, VSLAM database-per-zone switching via Jetson SSH orchestration, GeoJSON export for QGIS visualization, zone-specific pre-flight checks, and clear-all-on-failure safety guards.

**Objectives:**
- Single `mower zone select zones/ne.yaml` command orchestrates full zone switch (VSLAM restart + mission/fence/rally upload)
- Boustrophedon coverage planner generates mowing waypoints from zone boundary + exclusions
- GeoJSON export enables visual boundary verification before field deployment
- 4 new pre-flight checks ensure mission/fence/VSLAM zone consistency
- Clear-all-on-failure prevents mission/fence mismatch (most dangerous failure mode)

## Requirements

### Functional

- FR-1: `ZoneConfig` dataclass loads/validates zone YAML files (`mower-rover.zone.v1` schema)
- FR-2: `mower zone list` lists available zone YAML files from `zones/` directory
- FR-3: `mower mission plan zones/ne.yaml` generates boustrophedon waypoints + headland passes from boundary/exclusions/coverage params
- FR-4: `mower mission export-map zones/ --output property.geojson` exports zone boundaries, exclusions, and coverage passes as RFC 7946 GeoJSON
- FR-5: `mower zone select zones/ne.yaml` orchestrates full zone switch: SSH VSLAM activation + mission/fence/rally MAVLink upload + round-trip verification + snapshot
- FR-6: `mower zone resume zones/ne.yaml` displays resume point from `MISSION_CURRENT` and sets mission index via `MISSION_SET_CURRENT`; operator arms + switches to Auto via RC transmitter (CLI does NOT arm or set mode)
- FR-7: `mower-jetson zone activate <zone_id>` updates `vslam.yaml` `database_path` + `slam_mode`, restarts VSLAM services
- FR-8: `mower-jetson zone status` reports active zone, DB size, service health
- FR-9: MAVLink mission upload/download/clear for `MISSION_TYPE_MISSION`, `MISSION_TYPE_FENCE`, `MISSION_TYPE_RALLY`
- FR-10: Pre-flight checks PF-37 (fence/boundary match), PF-38 (mission count), PF-39 (VSLAM zone match), PF-40 (VSLAM relocalized)
- FR-11: Clear-all-on-failure: if any upload step fails, clear mission + fence + rally
- FR-12: Armed-check guard: refuse zone switch while FC is armed
- FR-13: Add `slam_mode` field to `VslamConfig` + C++ SLAM node; controls `Mem/IncrementalMemory` and `Mem/LocalizationReadOnly`

### Non-Functional

- NFR-1: Zone select completes in < 60s (SSH + VSLAM restart ~15s + MAVLink uploads ~10s + verification ~5s)
- NFR-2: Field-offline: no internet dependency in any zone management command
- NFR-3: Cross-platform: all laptop-side commands work on Windows; all Jetson-side on aarch64 Linux
- NFR-4: Structured output: zone operations log inputs, responses, outcomes via structlog with `zone_id` in bind context
- NFR-5: Coverage planner pure-geometry: no MAVLink or hardware dependency; testable with synthetic polygons

### Out of Scope

- Zone session status tracking (`mower zone status` dashboard with run metadata) — deferred to follow-up
- Autonomous transit between zones (always manual drive)
- Actual zone boundary coordinates (need RTK GPS perimeter walk)
- PID tuning or speed calibration per zone
- Multi-zone combined mission (one mission per zone, not combined)
- `angle_deg: auto` optimization algorithm (uses fixed angle for MVP)

## Technical Design

### Architecture

**Laptop-side flow:**
```
mower zone select zones/ne.yaml --port udp:...
  │
  ├─ 1. Load + validate zone YAML → ZoneConfig
  ├─ 2. Check FC not armed (MAVLink HEARTBEAT)
  ├─ 3. SSH: mower-jetson zone activate ne --slam-mode auto --json
  ├─ 4. Wait for VSLAM service ready (~15s)
  ├─ 5. Generate waypoints: boundary + exclusions → boustrophedon planner
  ├─ 6. Upload mission items (MAVLink MISSION_TYPE_MISSION)
  ├─ 7. Upload fence vertices (MAVLink MISSION_TYPE_FENCE)
  ├─ 8. Upload rally point (MAVLink MISSION_TYPE_RALLY)
  ├─ 9. Round-trip verify all three (download + diff)
  ├─ 10. Save upload snapshot (JSON)
  └─ ON ANY FAILURE at steps 6-9: clear all three mission types
```

**Jetson-side flow:**
```
mower-jetson zone activate ne --slam-mode auto
  │
  ├─ 1. Validate zone_id format
  ├─ 2. Determine slam_mode: DB exists → localization; no DB → mapping
  ├─ 3. Update /etc/mower/vslam.yaml: database_path + slam_mode
  ├─ 4. Restart mower-vslam.service + mower-vslam-bridge.service
  └─ 5. Report success JSON
```

**New module layout:**
```
src/mower_rover/
├── zone/                    # NEW: zone management module
│   ├── __init__.py
│   ├── config.py            # ZoneConfig dataclass + load/validate
│   ├── planner.py           # Boustrophedon coverage path planner
│   ├── geojson.py           # GeoJSON export (RFC 7946)
│   └── mission_items.py     # ZoneConfig → MAVLink mission items
├── mavlink/
│   ├── connection.py        # EXISTING
│   └── mission.py           # NEW: upload/download/clear for mission/fence/rally
├── cli/
│   ├── laptop.py            # MODIFIED: add zone sub-app
│   ├── jetson.py            # MODIFIED: add zone sub-app
│   └── zone_laptop.py       # NEW: laptop zone CLI commands
├── config/
│   └── vslam.py             # MODIFIED: add slam_mode field
├── probe/
│   └── checks/
│       └── zone.py           # NEW: PF-37..PF-40 zone-specific checks
zones/                        # NEW: Git-tracked zone definitions (project root)
├── ne.yaml
├── nw.yaml
├── south.yaml
└── generated/               # Generated .waypoints and .geojson files
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Typer CLI Sub-Apps
    location: "src/mower_rover/cli/laptop.py, src/mower_rover/cli/jetson.py"
    usage: New `zone` sub-app registered on both laptop and Jetson CLI apps
  - pattern: Config Dataclass + YAML Load/Save
    location: "src/mower_rover/config/vslam.py, src/mower_rover/config/laptop.py"
    usage: New ZoneConfig dataclass following VslamConfig pattern
  - pattern: Safety Primitives
    location: "src/mower_rover/safety/confirm.py"
    usage: SafetyContext + requires_confirmation on zone select (actuator-touching)
  - pattern: SSH Orchestration
    location: "src/mower_rover/transport/ssh.py, src/mower_rover/cli/jetson_remote.py"
    usage: JetsonClient.run() for remote zone activation
  - pattern: Probe Registry
    location: "src/mower_rover/probe/registry.py"
    usage: register() decorator for PF-37..PF-40 zone-specific checks
  - pattern: JSON Snapshots
    location: "src/mower_rover/params/io.py"
    usage: write_json_snapshot() pattern for mission upload snapshots
  - pattern: VSLAM Config + Defaults YAML
    location: "src/mower_rover/config/vslam.py, src/mower_rover/config/data/vslam_defaults.yaml"
    usage: Add slam_mode field to VslamConfig; zone select updates database_path + slam_mode
  - pattern: C++ SLAM Node Config
    location: "contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp"
    usage: Add slam_mode to SlamConfig struct and load_config()
  - pattern: Systemd Service Generation
    location: "src/mower_rover/service/unit.py"
    usage: Restart mower-vslam + mower-vslam-bridge services on zone switch
```

### Zone YAML Schema

Schema version: `mower-rover.zone.v1`. One file per zone in `zones/` at project root.

```yaml
schema: "mower-rover.zone.v1"

zone_id: ne                          # ^[a-z][a-z0-9_-]{0,31}$
name: "North East Lawn"
description: "Flat ~1.5 acre area."  # optional

home:
  lat: 38.89510
  lon: -77.03660

rally_point:
  lat: 38.89505
  lon: -77.03655
  description: "Driveway entrance to NE lawn"  # optional

boundary:                            # ≥ 3 vertices, [lat, lon] pairs
  - [38.89510, -77.03660]
  - [38.89510, -77.03400]
  - [38.89350, -77.03400]
  - [38.89350, -77.03660]

exclusion_zones:                     # optional list
  - name: "oak_tree_ne"
    buffer_m: 1.0                    # per-obstacle clearance
    polygon:
      - [38.89480, -77.03550]
      - [38.89480, -77.03520]
      - [38.89460, -77.03520]
      - [38.89460, -77.03550]

coverage:
  pattern: boustrophedon
  cutting_width_in: 54               # deck width in inches
  overlap_pct: 10                    # 0–50%
  angle_deg: 0                       # mowing heading (degrees from north)
  headland_passes: 2                 # perimeter passes before fill
  mow_speed_mps: 2.0
  turn_speed_mps: 1.0

commands:                            # optional mission command overrides
  fence_enable: true
  resume_dist_m: 2.5
  blade_engage: true

slam:                                # optional VSLAM overrides
  mode: localization                 # "mapping" or "localization"

output:                              # optional output file overrides
  waypoints_file: ne.waypoints
  geojson_file: ne.geojson
```

**Validation rules (load time):**

| Rule | Severity |
|------|----------|
| `zone_id` matches `^[a-z][a-z0-9_-]{0,31}$` | ERROR |
| `boundary` ≥ 3 vertices, valid Shapely polygon | ERROR |
| `exclusion_zones[*].polygon` valid polygons | ERROR |
| `coverage.cutting_width_in` > 0 | ERROR |
| `coverage.overlap_pct` 0–50 | ERROR |
| `coverage.mow_speed_mps` > 0, `turn_speed_mps` > 0 | ERROR |
| `home` and `rally_point` have valid lat/lon | ERROR |
| `rally_point` inside or at edge of boundary | WARN |
| Exclusion zones inside boundary | WARN |
| Boundary area 100 m²–100,000 m² | WARN |

### ZoneConfig Dataclass

File: `src/mower_rover/zone/config.py`. Follows `VslamConfig` pattern (dataclass + coerce + load).

```python
@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float

@dataclass(frozen=True)
class RallyPoint:
    lat: float
    lon: float
    description: str = ""

@dataclass(frozen=True)
class ExclusionZone:
    name: str
    buffer_m: float
    polygon: list[LatLon]

@dataclass(frozen=True)
class CoverageParams:
    pattern: str = "boustrophedon"       # only "boustrophedon" for MVP
    cutting_width_in: float = 54.0
    overlap_pct: float = 10.0
    angle_deg: float = 0.0
    headland_passes: int = 2
    mow_speed_mps: float = 2.0
    turn_speed_mps: float = 1.0

@dataclass(frozen=True)
class MissionCommands:
    fence_enable: bool = True
    resume_dist_m: float = 2.5
    blade_engage: bool = True

@dataclass(frozen=True)
class SlamOverrides:
    mode: str = "localization"           # "mapping" or "localization"

@dataclass(frozen=True)
class OutputConfig:
    waypoints_file: str = ""             # defaults to {zone_id}.waypoints
    geojson_file: str = ""               # defaults to {zone_id}.geojson

@dataclass(frozen=True)
class ZoneConfig:
    schema: str
    zone_id: str
    name: str
    home: LatLon
    rally_point: RallyPoint
    boundary: list[LatLon]
    description: str = ""
    exclusion_zones: list[ExclusionZone] = field(default_factory=list)
    coverage: CoverageParams = field(default_factory=CoverageParams)
    commands: MissionCommands = field(default_factory=MissionCommands)
    slam: SlamOverrides = field(default_factory=SlamOverrides)
    output: OutputConfig = field(default_factory=OutputConfig)

class ZoneConfigError(ValueError):
    """Raised when a zone YAML is malformed."""

def load_zone_config(path: Path) -> ZoneConfig: ...
def validate_zone_config(cfg: ZoneConfig) -> list[tuple[str, str]]: ...
    # Returns list of (severity, message) tuples
def load_all_zones(zones_dir: Path) -> list[ZoneConfig]: ...
```

`load_zone_config` reads YAML, coerces nested dicts into typed dataclasses, runs validation. `ZoneConfigError` raised on ERROR-severity failures. WARN-severity issues logged but not fatal.

### CLI Commands

**Laptop commands** (new `zone` sub-app in `src/mower_rover/cli/laptop.py`, implemented in `src/mower_rover/cli/zone_laptop.py`):

| Command | Signature | Safety |
|---------|-----------|--------|
| `mower zone list` | `list_(zones_dir: Path = "zones/")` | Read-only |
| `mower zone select` | `select(zone_yaml: Path, port: str, --dry-run, --skip-slam, --slam-mode auto\|mapping\|localization, --yes)` | `requires_confirmation` + armed check |
| `mower zone resume` | `resume(zone_yaml: Path, port: str, --yes)` | Read-only display + `MISSION_SET_CURRENT` (no arm/mode change) |
| `mower mission plan` | `plan(zone_yaml: Path, --output-dir zones/generated/)` | Read-only (generates files) |
| `mower mission export-map` | `export_map(zones_dir: Path, --output property.geojson)` | Read-only |

**Jetson commands** (new `zone` sub-app in `src/mower_rover/cli/jetson.py`):

| Command | Signature | Safety |
|---------|-----------|--------|
| `mower-jetson zone activate` | `activate(zone_id: str, --slam-mode auto\|mapping\|localization, --json)` | Restarts VSLAM services |
| `mower-jetson zone status` | `status(--json)` | Read-only |

**Registration pattern** (follows existing sub-app pattern):
```python
# In laptop.py
zone_app = typer.Typer(name="zone", help="Multi-zone lawn management.", no_args_is_help=True)
app.add_typer(zone_app)

# mission sub-app already exists or create new
mission_app = typer.Typer(name="mission", help="Coverage planning and mission management.", no_args_is_help=True)
app.add_typer(mission_app)
```

### VSLAM Config Changes

**Python side** — `src/mower_rover/config/vslam.py`:

Add `slam_mode` field to `VslamConfig`:
```python
@dataclass
class VslamConfig:
    # ... existing fields ...
    slam_mode: str = "mapping"  # "mapping" or "localization"
```

Add to `_coerce()` validation: `slam_mode` must be `"mapping"` or `"localization"`.

Add to `to_dict()`:
```python
"slam_mode": self.slam_mode,
```

**YAML defaults** — `src/mower_rover/config/data/vslam_defaults.yaml`:
```yaml
vslam:
  # ... existing fields ...
  slam_mode: mapping        # "mapping" or "localization" — set by zone activate
```

**Jetson zone activate** updates `database_path` and `slam_mode` in the live `/etc/mower/vslam.yaml` before restarting services. Pattern: load YAML → modify two keys → write back → `systemctl restart`.

### C++ SLAM Node Changes

File: `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`

**1. Add `slam_mode` to `SlamConfig` struct:**
```cpp
struct SlamConfig {
    // ... existing fields ...
    std::string slam_mode = "mapping";  // "mapping" or "localization"
};
```

**2. Add to `load_config()`:**
```cpp
if (vslam["slam_mode"])
    cfg.slam_mode = vslam["slam_mode"].as<std::string>();
```

**3. Set RTAB-Map parameters based on `slam_mode`** (in the RTAB-Map init section):
```cpp
if (cfg.slam_mode == "localization") {
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kMemIncrementalMemory(), "false"));
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kMemLocalizationReadOnly(), "true"));
}
// "mapping" mode uses defaults: IncrementalMemory=true, LocalizationReadOnly=false
```

This is a ~10 line change. No other C++ modifications needed — zone switching is handled by service restart.

### Pre-Flight Checks

File: `src/mower_rover/probe/checks/zone.py`. Uses existing `register()` decorator from `src/mower_rover/probe/registry.py`.

| Check | Name | Severity | Pass Criteria |
|-------|------|----------|---------------|
| PF-37 | `zone_fence_match` | CRITICAL | Downloaded fence vertices match zone YAML boundary within 1e-7 degree tolerance (MAVLink int32 resolution) |
| PF-38 | `zone_mission_count` | WARNING | Uploaded mission item count within ±5 of expected waypoint count from planner |
| PF-39 | `zone_vslam_match` | WARNING | VSLAM `database_path` contains `zones/{zone_id}/` (SSH query to Jetson) |
| PF-40 | `zone_vslam_relocalized` | WARNING | VSLAM confidence ≥ 1 within 30s timeout (SSH query to Jetson) |

**PF-37 is CRITICAL** — a mission/fence mismatch could drive the mower outside the intended zone boundary. PF-39/PF-40 are WARN because VSLAM is supplementary to RTK GPS.

**Registration signatures:**
```python
@register("zone_fence_match", severity=Severity.CRITICAL)
def check_zone_fence_match(sysroot: Path) -> tuple[bool, str]: ...

@register("zone_mission_count", severity=Severity.WARNING)
def check_zone_mission_count(sysroot: Path) -> tuple[bool, str]: ...

@register("zone_vslam_match", severity=Severity.WARNING, depends_on=("vslam_process",))
def check_zone_vslam_match(sysroot: Path) -> tuple[bool, str]: ...

@register("zone_vslam_relocalized", severity=Severity.WARNING, depends_on=("zone_vslam_match",))
def check_zone_vslam_relocalized(sysroot: Path) -> tuple[bool, str]: ...
```

### Safety Guards

**1. Armed-check guard** (in `mower zone select`, before any uploads):
```python
def _check_not_armed(conn) -> None:
    hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    if hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
        raise typer.BadParameter("FC is armed — cannot switch zones. Disarm first.")
```

**2. Clear-all-on-failure** (wraps the upload sequence):
```python
def _upload_zone_atomically(conn, mission_items, fence_items, rally_items):
    try:
        upload_mission(conn, mission_items, mission_type=MISSION)
        upload_mission(conn, fence_items, mission_type=FENCE)
        upload_mission(conn, rally_items, mission_type=RALLY)
        # Verify all three
        verify_round_trip(conn, mission_items, MISSION)
        verify_round_trip(conn, fence_items, FENCE)
        verify_round_trip(conn, rally_items, RALLY)
    except Exception:
        clear_mission(conn, MISSION)
        clear_mission(conn, FENCE)
        clear_mission(conn, RALLY)
        raise ZoneUploadError("Zone upload FAILED. All missions cleared for safety.")
```

**3. SafetyContext integration** — `mower zone select` uses `@requires_confirmation` decorator with message describing the zone switch action. `--dry-run` skips SSH and MAVLink uploads.

**4. Safe-stop is zone-agnostic** — existing Hold mode, blade kill, engine kill are zone-independent. `zone_id` is added to structlog bind context for traceability only.

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| `pymavlink` | Python package | Already in pyproject.toml | MAVLink mission protocol |
| `shapely` | Python package | Already in pyproject.toml | Polygon geometry for coverage planner |
| `pyproj` | Python package | Already in pyproject.toml | Geodetic → planar coordinate conversion |
| `pyyaml` | Python package | Already in pyproject.toml | Zone YAML loading |
| `structlog` | Python package | Already in pyproject.toml | Structured logging |
| `typer` | Python package | Already in pyproject.toml | CLI framework |
| `open_link()` | Internal module | `src/mower_rover/mavlink/connection.py` | MAVLink connection manager |
| `SafetyContext` | Internal module | `src/mower_rover/safety/confirm.py` | Safety primitives |
| `JetsonClient` | Internal module | `src/mower_rover/transport/ssh.py` | SSH orchestration |
| `VslamConfig` | Internal module | `src/mower_rover/config/vslam.py` | VSLAM config (add slam_mode) |
| `register()` | Internal module | `src/mower_rover/probe/registry.py` | Pre-flight check registration |
| ArduPilot SITL | External tool | WSL2 on Windows | `rover-skid` frame for MAVLink protocol tests |
| yaml-cpp | C++ library | Already in CMakeLists.txt | SLAM node config parsing |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Mission/fence mismatch after partial upload failure | Medium | **Critical** — mower exits zone boundary | Clear-all-on-failure guard; PF-37 CRITICAL pre-flight check |
| MAVLink mission protocol edge cases (timeout, retransmit) | Medium | Medium | Configurable timeouts; retry logic; SITL integration tests |
| Boustrophedon planner produces invalid waypoints for concave polygons | Low | Medium | Shapely polygon decomposition; unit tests with concave/L-shaped test polygons |
| Fence vertex float precision loss in MAVLink int32 encoding | Low | Low | 1e-7 degree tolerance (~1 cm) in PF-37 comparison; documented in pre-flight check |
| VSLAM service fails to restart on zone switch | Low | Medium | SSH command timeout + error reporting; `--skip-slam` flag as fallback; RTK GPS bridges VSLAM gap |
| Zone YAML boundary coordinates inaccurate (no RTK perimeter walk yet) | High | Medium | GeoJSON export for visual verification in QGIS before first field mow |
| MAVLink2 not enabled on SiK radio link | Low | High — fence upload fails | Pre-flight check for MAVLink2 capability; document `SERIAL2_PROTOCOL=2` requirement |

## Execution Plan

### Phase 1: Zone Config Foundation

**Status:** ✅ Complete
**Completed:** 2026-04-27
**Size:** Medium
**Files to Modify:** 6
**Prerequisites:** None
**Entry Point:** `src/mower_rover/zone/config.py` (new)
**Verification:** `uv run pytest tests/test_zone_config.py -v` passes — 19/19 tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 1.1 | Create `src/mower_rover/zone/__init__.py` | `src/mower_rover/zone/__init__.py` | ✅ Complete |
| 1.2 | Create `ZoneConfig` dataclass with all nested types | `src/mower_rover/zone/config.py` | ✅ Complete |
| 1.3 | Implement `load_zone_config(path: Path) -> ZoneConfig` with YAML coercion | `src/mower_rover/zone/config.py` | ✅ Complete |
| 1.4 | Implement `validate_zone_config(cfg: ZoneConfig)` with all validation rules | `src/mower_rover/zone/config.py` | ✅ Complete |
| 1.5 | Implement `load_all_zones(zones_dir: Path) -> list[ZoneConfig]` | `src/mower_rover/zone/config.py` | ✅ Complete |
| 1.6 | Create sample zone YAML fixtures for NE, NW, South | `zones/ne.yaml`, `zones/nw.yaml`, `zones/south.yaml` | ✅ Complete |
| 1.7 | Write unit tests | `tests/test_zone_config.py` | ✅ Complete |

**Implementation Notes:**
- All dataclasses frozen=True per plan
- Shapely polygon validation for boundaries and exclusion zones
- 19 unit tests covering valid/invalid YAML, validation warnings, load_all_zones
- Files created: `src/mower_rover/zone/__init__.py`, `src/mower_rover/zone/config.py`, `zones/ne.yaml`, `zones/nw.yaml`, `zones/south.yaml`, `tests/test_zone_config.py`

### Phase 2: Coverage Path Planner

**Status:** ✅ Complete
**Completed:** 2026-04-27
**Size:** Medium
**Files to Modify:** 3
**Prerequisites:** Phase 1 complete (ZoneConfig available) ✅
**Entry Point:** `src/mower_rover/zone/planner.py` (new)
**Verification:** `uv run pytest tests/test_zone_planner.py -v` passes — 19/19 tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 2.1 | Implement geodetic ↔ planar projection helpers using pyproj (UTM auto-zone from boundary centroid) | `src/mower_rover/zone/planner.py` | ✅ Complete |
| 2.2 | Implement headland pass generation with Shapely buffer and exclusion zone subtraction | `src/mower_rover/zone/planner.py` | ✅ Complete |
| 2.3 | Implement boustrophedon fill with alternating sweep lines and angle rotation | `src/mower_rover/zone/planner.py` | ✅ Complete |
| 2.4 | Implement `generate_waypoints(zone: ZoneConfig) -> list[LatLon]` combining headland + fill | `src/mower_rover/zone/planner.py` | ✅ Complete |
| 2.5 | Write unit tests for all polygon scenarios | `tests/test_zone_planner.py` | ✅ Complete |

**Implementation Notes:**
- UTM auto-detection from boundary centroid, round-trip within 1 cm tolerance
- Headland passes with proper exclusion zone handling (separate perimeter passes)
- Robust MultiLineString geometry handling in sweep line clipping
- Files created: `src/mower_rover/zone/planner.py`, `tests/test_zone_planner.py`

### Phase 3: MAVLink Mission Protocol + Mission Item Conversion

**Status:** ✅ Complete
**Completed:** 2026-04-27
**Size:** Medium
**Files to Modify:** 4
**Prerequisites:** Phase 1 complete (ZoneConfig), Phase 2 complete (planner waypoints) ✅
**Entry Point:** `src/mower_rover/mavlink/mission.py` (new)
**Verification:** `uv run pytest tests/test_zone_mission.py -v` passes — 15/15 tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 3.1 | Implement `MissionItem` dataclass | `src/mower_rover/mavlink/mission.py` | ✅ Complete |
| 3.2 | Implement `upload_mission()` protocol | `src/mower_rover/mavlink/mission.py` | ✅ Complete |
| 3.3 | Implement `download_mission()` protocol | `src/mower_rover/mavlink/mission.py` | ✅ Complete |
| 3.4 | Implement `clear_mission()` | `src/mower_rover/mavlink/mission.py` | ✅ Complete |
| 3.5 | Implement `verify_round_trip()` | `src/mower_rover/mavlink/mission.py` | ✅ Complete |
| 3.6 | Implement `zone_to_mission()` conversion | `src/mower_rover/zone/mission_items.py` | ✅ Complete |
| 3.7 | Implement `zone_to_fence()` conversion | `src/mower_rover/zone/mission_items.py` | ✅ Complete |
| 3.8 | Implement `zone_to_rally()` conversion | `src/mower_rover/zone/mission_items.py` | ✅ Complete |
| 3.9 | Write unit tests | `tests/test_zone_mission.py` | ✅ Complete |

**Implementation Notes:**
- Full MAVLink mission protocol with timeout/retry handling
- Lazy pymavlink imports for importability
- Int32 × 1e7 coordinate encoding per MAVLink spec
- Files created: `src/mower_rover/mavlink/mission.py`, `src/mower_rover/zone/mission_items.py`, `tests/test_zone_mission.py`

### Phase 4: VSLAM Config + C++ SLAM Node Changes

**Status:** ✅ Complete
**Completed:** 2026-04-27
**Size:** Small
**Files to Modify:** 4
**Prerequisites:** Phase 1 complete (ZoneConfig with `slam.mode`) ✅
**Entry Point:** `src/mower_rover/config/vslam.py`
**Verification:** `uv run pytest tests/test_vslam_config.py -v` passes (exit code 0); C++ builds with `build.sh`

| Step | Task | Files | Status |
|------|------|-------|--------|
| 4.1 | Add `slam_mode: str = "mapping"` field to `VslamConfig` dataclass | `src/mower_rover/config/vslam.py` | ✅ Complete |
| 4.2 | Add `slam_mode` validation to `_coerce()`: must be "mapping" or "localization" | `src/mower_rover/config/vslam.py` | ✅ Complete |
| 4.3 | Add `slam_mode: mapping` to YAML defaults file | `src/mower_rover/config/data/vslam_defaults.yaml` | ✅ Complete |
| 4.4 | Add `slam_mode` to C++ `SlamConfig` struct + `load_config()` | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 4.5 | Add RTAB-Map parameter mapping for localization mode | `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | ✅ Complete |
| 4.6 | Update existing `test_vslam_config.py` to cover `slam_mode` field | `tests/test_vslam_config.py` | ✅ Complete |

**Implementation Notes:**
- Added slam_mode field to VslamConfig with "mapping"/"localization" validation
- C++ SLAM node sets Mem/IncrementalMemory=false + Mem/LocalizationReadOnly=true in localization mode
- 6 new tests added to test_vslam_config.py (default, mapping, localization, invalid, to_dict, round-trip)
- Files modified: `src/mower_rover/config/vslam.py`, `src/mower_rover/config/data/vslam_defaults.yaml`, `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp`, `tests/test_vslam_config.py`

### Phase 5: Jetson-Side Zone Commands

**Status:** ✅ Complete
**Completed:** 2026-04-28
**Size:** Small
**Files to Modify:** 3
**Prerequisites:** Phase 4 complete (VslamConfig with slam_mode) ✅
**Entry Point:** `src/mower_rover/cli/jetson.py`
**Verification:** `uv run pytest tests/test_cli_jetson_smoke.py -v` passes — 36/36 tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 5.1 | Implement `mower-jetson zone activate <zone_id>` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 5.2 | Implement `mower-jetson zone status` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 5.3 | Write unit tests for zone activate and zone status | `tests/test_cli_jetson_smoke.py` | ✅ Complete |

**Implementation Notes:**
- zone_app Typer sub-app registered on jetson CLI
- Auto slam_mode: DB exists → localization, no DB → mapping
- Creates zone directory, updates vslam.yaml, restarts VSLAM services
- Status extracts zone_id from database_path, reports DB size, service health
- Files modified: `src/mower_rover/cli/jetson.py`, `tests/test_cli_jetson_smoke.py`

### Phase 6: Laptop-Side Zone CLI + Orchestration

**Status:** ✅ Complete
**Completed:** 2026-04-28
**Size:** Large
**Files to Modify:** 5
**Prerequisites:** Phase 1–3 complete, Phase 5 complete ✅
**Entry Point:** `src/mower_rover/cli/zone_laptop.py`
**Verification:** `uv run pytest tests/test_zone_cli.py -v` passes — 22/22 tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 6.1 | Create `zone_laptop.py` with `zone_app` and `mission_app` | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.2 | Implement `mower zone list` | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.3 | Implement `mower zone select` with full orchestration | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.4 | Implement `_upload_zone_atomically()` clear-on-failure | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.5 | Implement `mower zone resume` | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.6 | Implement `mower mission plan` | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.7 | Register zone_app and mission_app in laptop.py | `src/mower_rover/cli/laptop.py` | ✅ Complete |
| 6.8 | Implement zone upload snapshot | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 6.9 | Write unit tests | `tests/test_zone_cli.py` | ✅ Complete |

**Implementation Notes:**
- `select` uses `--yes`/`--dry-run` flags directly (not parent context)
- Confirmation via `@requires_confirmation` with SafetyContext
- `mission_app` has callback to prevent Typer single-command auto-promotion
- Lazy pymavlink import in `_check_not_armed`
- Files created: `src/mower_rover/cli/zone_laptop.py`, `tests/test_zone_cli.py`
- Files modified: `src/mower_rover/cli/laptop.py`

### Phase 7: GeoJSON Export + Pre-Flight Checks

**Status:** ✅ Complete
**Completed:** 2026-04-28
**Size:** Medium
**Files to Modify:** 4
**Prerequisites:** Phase 1, 2, 3 ✅
**Entry Point:** `src/mower_rover/zone/geojson.py`
**Verification:** `uv run pytest tests/test_zone_geojson.py tests/test_zone_preflight.py -v` passes — 24/24 tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 7.1 | Implement `export_zone_geojson()` | `src/mower_rover/zone/geojson.py` | ✅ Complete |
| 7.2 | Implement `export_multi_zone_geojson()` | `src/mower_rover/zone/geojson.py` | ✅ Complete |
| 7.3 | Implement `mower mission export-map` CLI | `src/mower_rover/cli/zone_laptop.py` | ✅ Complete |
| 7.4 | PF-37 `zone_fence_match` check | `src/mower_rover/probe/checks/zone.py` | ✅ Complete |
| 7.5 | PF-38 `zone_mission_count` check | `src/mower_rover/probe/checks/zone.py` | ✅ Complete |
| 7.6 | PF-39/PF-40 VSLAM checks | `src/mower_rover/probe/checks/zone.py` | ✅ Complete |
| 7.7 | Write unit tests | `tests/test_zone_geojson.py`, `tests/test_zone_preflight.py` | ✅ Complete |

**Implementation Notes:**
- GeoJSON uses RFC 7946 `[lon, lat]` coordinate ordering
- Pre-flight checks registered with probe registry; MAVLink-based checks use filesystem-cached state
- Files created: `src/mower_rover/zone/geojson.py`, `src/mower_rover/probe/checks/zone.py`, `tests/test_zone_geojson.py`, `tests/test_zone_preflight.py`
- Files modified: `src/mower_rover/cli/zone_laptop.py`

### Phase 8: SITL Integration Tests

**Status:** ✅ Complete
**Completed:** 2026-04-28
**Size:** Small
**Files to Modify:** 1
**Prerequisites:** Phase 3 complete ✅
**Entry Point:** `tests/test_zone_sitl.py`
**Verification:** `uv run pytest tests/test_zone_sitl.py --collect-only` — 6 tests collected; requires SITL to run

| Step | Task | Files | Status |
|------|------|-------|--------|
| 8.1 | Create SITL test fixture with sitl_conn | `tests/test_zone_sitl.py` | ✅ Complete |
| 8.2 | Mission upload/download round-trip | `tests/test_zone_sitl.py` | ✅ Complete |
| 8.3 | Fence upload/download round-trip | `tests/test_zone_sitl.py` | ✅ Complete |
| 8.4 | Rally upload/download round-trip | `tests/test_zone_sitl.py` | ✅ Complete |
| 8.5 | Clear mission (all types) | `tests/test_zone_sitl.py` | ✅ Complete |
| 8.6 | Armed-check guard | `tests/test_zone_sitl.py` | ✅ Complete |
| 8.7 | Coverage planner output accepted by SITL | `tests/test_zone_sitl.py` | ✅ Complete |

**Implementation Notes:**
- All tests marked `@pytest.mark.sitl`, skip gracefully without SITL
- Reuses `sitl_endpoint` fixture from conftest.py
- Fence/rally tests use pytest.skip fallback for unsupported SITL features
- Coordinate tolerance ±1e-6 for int32×1e7 round-trip
- Files created: `tests/test_zone_sitl.py`

## Standards

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 4 | ~15 new files across zone/, mavlink/, cli/, probe/ + 4 modified |
| New patterns introduced | 2 | MAVLink mission protocol is new; zone YAML schema is new but follows existing config pattern |
| External dependencies | 1 | All deps already in pyproject.toml (Shapely, pyproj, pymavlink) |
| Migration complexity | 1 | No migrations; additive-only changes |
| Test coverage required | 3 | Unit tests for planner + config, mock-based for MAVLink, SITL integration for round-trip |
| **Overall Complexity** | **11/25** | **Medium** — large surface area but each phase is self-contained and testable independently |

## Review Summary

**Review Date:** 2026-04-27
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.2

### Review Metrics
- Issues Found: 6 (Critical: 0, Major: 3, Minor: 3)
- Clarifying Questions Asked: 1
- Sections Updated: Version History, Review Session Log, FR-6, CLI Commands table, Pre-Flight Checks, Phase 6 step 6.5, Phase 7 steps 7.4–7.7, module layout diagram

### Key Improvements Made
1. Fixed `Severity.WARN` → `Severity.WARNING` to match actual enum in `probe/registry.py`
2. Moved probe check file from `probe/zone_checks.py` to `probe/checks/zone.py` to match existing `checks/` subdirectory convention
3. Corrected `depends_on=("vslam_service_active",)` to `depends_on=("vslam_process",)` — the referenced check name didn't exist
4. Fixed `_coerce_vslam()` → `_coerce()` to match actual function name
5. Changed `zone resume` from programmatic arm+Auto to display-only (MISSION_SET_CURRENT) — arming authority stays on RC transmitter per safety chain philosophy

### Remaining Considerations
- All codebase references verified: file paths, function signatures, patterns, dependencies all confirmed to exist
- C++ SLAM node change (~10 lines) is straightforward but must be tested on Jetson (no cross-compile CI)
- PF-37 (fence match) is the most safety-critical check — implementer should pay extra attention to the 1e-7 degree tolerance and int32 encoding edge cases
- Zone YAML placeholder coordinates are not real GPS positions — an RTK perimeter walk is needed before first field use

### Sign-off
This plan has been reviewed and is **Ready for Implementation**

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-27 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-27 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/013-multi-zone-lawn-management.md |
