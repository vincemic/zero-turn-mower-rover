---
id: "014"
type: research
title: "Multi-Zone Lawn Management — NE, NW, and South Lawns"
status: ✅ Complete
created: "2026-04-27"
current_phase: "✅ Complete"
---

## Introduction

The property has three distinct mowing areas — North East, North West, and South lawns — separated by the house, driveway, and/or other non-mowable terrain. This research investigates how to manage these three zones across both the SLAM system (RTAB-Map, OAK-D Pro VSLAM) and ArduPilot mission planning (boundaries, geofences, coverage patterns, mission files). The goal is a clean, operator-friendly workflow for defining, storing, switching between, and executing mowing missions on each zone independently, while maintaining correct SLAM map context per zone.

## Objectives

- How should RTAB-Map databases be organized per zone? One DB per zone, or a single shared DB with localization regions?
- How does the VSLAM coordinate frame and origin change when the mower transits between zones?
- What is the ArduPilot mission/geofence structure for three independent zones? One mission per zone, or a single multi-segment mission?
- How should the YAML mission definition format (from MVP research Phase 6) be extended to support named zones?
- What is the operator workflow for selecting a zone, loading the correct mission + SLAM map, and starting a mow?
- How does geofence management work across zones (separate polygon fences per zone, or dynamic fence switching)?
- What are the implications for mission resume, pre-flight checks, and safe-stop when operating in zone-aware mode?

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | RTAB-Map Multi-Zone Database Strategy | ✅ Complete | RTAB-Map DB-per-zone vs shared DB; localization vs mapping mode per zone; DB file naming/storage; cold-start and relocalization behavior when switching zones | 2026-04-27 |
| 2 | VSLAM Coordinate Frames Across Zones | ✅ Complete | VSLAM origin and coordinate frame handling when mower transits between zones; EKF origin reset or continuity; interaction with ArduPilot VISUAL_ODOMETRY; map-to-odom transform per zone | 2026-04-27 |
| 3 | ArduPilot Mission Structure for Multi-Zone | ✅ Complete | Single vs multi-mission approach; geofence polygon per zone; fence switching workflow; mission upload/download per zone; waypoint capacity across three zones; MAVLink mission management commands | 2026-04-27 |
| 4 | YAML Mission Format and Zone Configuration | ✅ Complete | Extending YAML mission definition for named zones; zone-level config (boundary, exclusions, coverage params); directory/file structure for zone definitions; `mower mission plan` CLI zone selection; zone metadata in GeoJSON exports | 2026-04-27 |
| 5 | Operator Workflow and Zone-Aware Tooling | ✅ Complete | End-to-end operator workflow for zone selection → load SLAM DB → upload mission → pre-flight → mow → zone switch; CLI UX for `mower zone` or `mower mission --zone`; SLAM DB auto-switching; pre-flight check zone awareness; mission resume within a zone; safe-stop behavior per zone; transit between zones (manual drive or autonomous?) | 2026-04-27 |

## Phase 1: RTAB-Map Multi-Zone Database Strategy

**Status:** ✅ Complete  
**Session:** 2026-04-27

### 1. RTAB-Map Database Switching: Init-Time Only, Not Runtime

RTAB-Map's `Rtabmap::init(params, databasePath)` binds the database at initialization. There is **no API to switch databases at runtime**. The only way to change the active database is:

```cpp
rtabmap->close(true);                    // save & close current DB
rtabmap->init(params, newDatabasePath);  // open new DB
```

This is confirmed by multiple patterns in the RTAB-Map source:

- **`Rtabmap::init()`** (Rtabmap.cpp:322–446): Sets `_databasePath`, creates a `Memory` object, calls `_memory->init(_databasePath, ...)` which opens the SQLite3 connection. If the DB file exists, loads graph into Working Memory.
- **`Rtabmap::close()`** (Rtabmap.cpp:486–548): Saves optimized poses, flushes statistics, closes the Memory (which closes the DB driver), then resets `_databasePath` to empty.
- **Android app pattern** (RTABMapApp.cpp:3287–3304): `rtabmap_->close(true, databasePath); rtabmap_->init(getRtabmapParameters(), databasePath);` — confirms close+reinit is the standard pattern for switching databases.

**Implication for multi-zone:** Zone switching requires stopping and restarting the SLAM engine with a different `database_path`. Since the SLAM node runs as a systemd service, this means a **service restart with updated config** — which is clean and reliable.

### 2. Recommendation: Separate DB Per Zone (Not Shared DB)

**Separate databases per zone is strongly recommended** over a single shared database. Reasons:

| Criterion | Separate DBs | Shared DB |
|-----------|-------------|-----------|
| Visual overlap between zones | None (separated by house/driveway) | Would create disconnected graph components |
| Loop closure | Works within each zone | Cannot close loops across zones with no shared features |
| DB file size | Smaller per zone (~100–500 MB) | Combined size, all loaded |
| Init/load time | Faster (smaller graph) | Slower (entire graph loaded) |
| Corruption risk | Isolated per zone | One corruption affects all zones |
| Backup/restore | Per-zone granularity | All-or-nothing |
| Map quality | Independent optimization per zone | Graph optimizer struggles with disconnected components |

RTAB-Map's graph optimization (g2o/GTSAM) works on connected graph components. Three disconnected subgraphs in one DB would be optimized independently anyway — there's zero benefit to sharing.

### 3. Localization Mode vs Mapping Mode

RTAB-Map has two modes controlled by `Mem/IncrementalMemory`:

- **Mapping mode** (`Mem/IncrementalMemory=true`, default): Full SLAM — creates new graph nodes, builds/extends the map, runs loop closure detection, manages Working Memory ↔ Long-Term Memory transfers. The DB grows over time.
- **Localization mode** (`Mem/IncrementalMemory=false`): The map is **frozen** — no new nodes added. The robot localizes against the existing map using appearance-based matching. Memory and processing time are bounded.

Additional relevant parameter: `Mem/LocalizationReadOnly=true` — opens the database in **read-only mode** during localization, preventing any writes.

**Recommended workflow per zone:**

1. **Initial mapping pass** (first mow): `Mem/IncrementalMemory=true` — drive the zone boundary and interior, building the visual map
2. **Subsequent mows**: `Mem/IncrementalMemory=false` + `Mem/LocalizationReadOnly=true` — localize against the saved map, no DB growth

### 4. Cold-Start and Relocalization Behavior

When RTAB-Map initializes with an **existing database** in localization mode:

1. **DB connection opened** — SQLite3 file opened
2. **Graph loaded into Working Memory** — All signatures, visual words, and links loaded from DB
3. **Visual features optionally pre-loaded** — When `Mem/LoadVisualLocalFeaturesOnInit=true` (default), all local visual features are loaded into RAM
4. **Optimized poses loaded** — The graph optimization from the last session is restored
5. **First frame processing** — RTAB-Map uses bag-of-words appearance matching to find the closest location → **relocalization**

**Expected timing on Orin + NVMe:**
- DB file open + graph load: 1–5 seconds (depends on node count; NVMe ~5 GB/s sequential read)
- Feature pre-loading: 2–10 seconds for a ~1 acre zone (dominated by decompression)
- First relocalization: ~0.5–2 seconds after first valid frame
- **Total cold-start to first localized pose: ~5–15 seconds**

RTK GPS provides position immediately; VSLAM relocalization is supplementary. The mower can begin operation on GPS alone and VSLAM locks on within seconds.

### 5. Expected DB File Size Per Zone

**Key parameters affecting DB size:**
- **Detection rate** (`Rtabmap/DetectionRate`): ~1 Hz from SLAM node's `process()` calls
- **Image compression**: Images stored as compressed PNG/JPEG (default)
- **Feature count**: `Vis/MinInliers=10`, `Odom/F2MMaxSize=3000` — bounded
- **Stereo resolution**: 800p (1280×800)

**Estimate for ~1 acre zone (30-minute mowing session):**
- At 1 Hz detection: ~1800 signatures per session
- Per signature: ~50–100 KB (compressed stereo pair + features + metadata)
- Graph overhead: ~10 KB per node
- **Total estimate: 100–300 MB per zone for initial mapping**
- In localization mode with `LocalizationReadOnly=true`: DB does not grow

With three zones at ~300 MB each, total VSLAM storage is ~1 GB — trivial for the 2 TB NVMe SSD.

### 6. DB File Naming and Filesystem Organization

**Recommended directory structure on Jetson:**

```
/var/lib/mower/
├── zones/
│   ├── ne/
│   │   └── rtabmap.db          # NE lawn SLAM database
│   ├── nw/
│   │   └── rtabmap.db          # NW lawn SLAM database
│   └── south/
│       └── rtabmap.db          # South lawn SLAM database
```

The hierarchical approach is preferred because:
- Each zone directory can hold additional zone-specific artifacts (boundary polygon, calibration data, mowing logs)
- The `database_path` in config is a clean path pattern: `/var/lib/mower/zones/{zone_id}/rtabmap.db`
- Zone IDs are short, CLI-friendly identifiers (e.g., `ne`, `nw`, `south`)

### 7. Required Changes to C++ SLAM Node and YAML Config

**Changes to `vslam_defaults.yaml`:**

```yaml
vslam:
  # ... existing params ...
  database_path: /var/lib/mower/zones/ne/rtabmap.db  # set by zone-select command
  slam_mode: mapping     # "mapping" or "localization"
```

The `mower-jetson zone select <id>` CLI command would:
1. Update `/etc/mower/vslam.yaml` with the correct `database_path` for the zone
2. Set `slam_mode` based on whether a DB exists (new zone → mapping, existing DB → localization)
3. Restart `mower-vslam.service`

**Changes to `rtabmap_slam_node.cpp`:**

1. **Add `slam_mode` config parameter** — Maps to `Mem/IncrementalMemory`:
```cpp
struct SlamConfig {
    // ... existing fields ...
    std::string slam_mode = "mapping";  // "mapping" or "localization"
};
```

2. **Set RTAB-Map params accordingly:**
```cpp
if (cfg.slam_mode == "localization") {
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kMemIncrementalMemory(), "false"));
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kMemLocalizationReadOnly(), "true"));
}
```

3. **No runtime zone switching needed** — Service restart handles it.

### 8. Memory Management and Zone Switching

RTAB-Map's memory architecture (Working Memory ↔ Long-Term Memory):

- **Working Memory (WM)**: Active signatures in RAM. Bounded by `memory_threshold_mb` (6000 MB).
- **Long-Term Memory (LTM)**: Older signatures moved to SQLite on disk. Retrieved when needed.
- **Short-Term Memory (STM)**: Most recent signatures (last N, default 10). Always in WM.

**Zone switching interaction:**
- `close()` flushes everything to disk for the current zone → clean state
- Service restart → fresh process, fresh memory allocation
- `init()` loads only the new zone's graph → no cross-contamination
- OdometryF2M is also recreated fresh (new process) → local feature map is zone-correct
- The `reset_counter` (sent to ArduPilot for EKF discontinuity handling) starts at 0 for each service restart

**RAM budget**: Each zone's WM fits easily within the 6 GB threshold. With ~1800 signatures at ~50 KB each in WM, that's ~90 MB — well under budget.

**Key Discoveries:**
- RTAB-Map database path is set at `init()` time only — no runtime switching; zone changes require `close()` + `init()` cycle (= service restart)
- Separate DB per zone is strongly recommended: zones share no visual overlap, so a shared DB would contain disconnected graph components with zero benefit
- Localization mode (`Mem/IncrementalMemory=false`) freezes the map for production mowing; `Mem/LocalizationReadOnly=true` prevents any DB writes
- Cold-start relocalization on Orin with NVMe SSD estimated at 5–15 seconds total; RTK GPS provides position immediately while VSLAM locks on
- DB size estimated at 100–300 MB per ~1 acre zone — trivial for 2 TB NVMe
- Current C++ SLAM node needs minimal changes: add `slam_mode` config parameter; zone switching handled by service restart with updated `database_path`
- OdometryF2M is automatically fresh on service restart — no cross-zone local map contamination

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | C++ SLAM node: `init(params, database_path)` and `close()` |
| `src/mower_rover/config/data/vslam_defaults.yaml` | Default config with single `database_path` needing zone-awareness |
| `src/mower_rover/config/vslam.py` | Python VslamConfig dataclass needing `slam_mode` field |
| `src/mower_rover/service/unit.py` | Systemd unit generation for VSLAM service |

**External Sources:**
- [RTAB-Map Multi-Session Tutorial](https://github.com/introlab/rtabmap/wiki/Multi-session)
- [RTAB-Map FAQ — Mapping vs Localization](https://github.com/introlab/rtabmap/wiki/FAQ)
- [RTAB-Map source — Rtabmap.h/cpp, Memory.h/cpp, Parameters.h](https://github.com/introlab/rtabmap)

**Gaps:**
- Exact relocalization timing needs field validation on Orin with real outdoor zone DB
- DB file size estimates based on typical behavior; actual outdoor grass/tree texture may affect feature density
- Interaction between RTAB-Map `reset_counter` and ArduPilot EKF on service restart needs field testing

**Assumptions:**
- RTAB-Map detection rate ~1 Hz; three zones each ~1 acre with 30-minute sessions
- Zone transitions happen via manual drive on driveway (not hot-switch during autonomous operation)

## Phase 2: VSLAM Coordinate Frames Across Zones

**Status:** ✅ Complete  
**Session:** 2026-04-27

### 1. VSLAM Coordinate Frame Origin on Zone Switch

When the VSLAM service restarts with a new zone DB, the RTAB-Map coordinate frame origin changes completely. The origin is defined by the first keyframe location in each zone's map database:

- **NE lawn RTAB-Map frame**: origin at first keyframe captured in the NE zone
- **NW lawn RTAB-Map frame**: completely different origin, at the NW zone's first keyframe
- **South lawn RTAB-Map frame**: again, different origin

The pose values `(x, y, z)` emitted via the Unix socket are in the current zone's RTAB-Map frame. After a zone switch and service restart, position `(0, 0, 0)` refers to a completely different physical location.

### 2. ArduPilot EKF3 Handling of Vision Position Discontinuity

**Most critical finding.** The mower uses `VISO_TYPE=1` (MAVLink), which maps to the `AP_VisualOdom_MAV` backend in ArduPilot:

- **`AP_VisualOdom_MAV` (VISO_TYPE=1 — our backend):** Does **NOT** use `reset_counter` to gate data consumption. Simply logs `reset_counter` but always passes pose data through. Calls `align_position_to_ahrs()` to offset ExternalNav position to match the AHRS/GPS position.
- **`AP_VisualOdom_IntelT265` (VISO_TYPE=2 — NOT our backend):** Uses `reset_counter` to ignore sensor data for 1000ms after a change.

**ArduPilot's position alignment mechanism** (`align_position_to_ahrs()`) is what handles the discontinuity. When GPS is primary, ExternalNav position is continuously aligned to GPS/AHRS position. This means GPS→VSLAM switching is seamless (no position jump).

**Zone transition safety chain:**
1. Mower is on GPS (SRC1) during transit between zones
2. VSLAM service is stopped — no `VISION_POSITION_ESTIMATE` messages sent
3. Lua script stays on GPS because ExternalNav innovations are invalid
4. VSLAM service restarts with new zone DB — new poses in new frame
5. ArduPilot receives new poses and aligns them to current GPS/AHRS position via `align_position_to_ahrs()`
6. ExternalNav is now aligned — GPS→VSLAM switch is seamless if GPS later degrades

**No position jump occurs** because the mower stays on GPS during the transition, and ArduPilot realigns ExternalNav automatically.

### 3. reset_counter Behavior Across Zone Transitions

On zone switch (service restart):
1. C++ node restarts → `reset_counter` starts at 0
2. Python bridge restarts → `bridge_reset_counter` starts at 0, `last_reset_counter` = -1
3. Since `AP_VisualOdom_MAV` backend does not use `reset_counter` for data gating, this is a diagnostic concern only

**Recommendation for future improvement:** Consider persisting `bridge_reset_counter` across restarts for monotonically increasing counter for diagnostics. However, this is **not required for correct operation**.

### 4. Bridge Restart Behavior Is Ideal for Zone Transitions

The bridge's stateless restart behavior (fresh process per zone) is ideal:
- `prev_msg = None` → no velocity sent for first pose (prevents velocity spike)
- All counters reset naturally
- No stale state from previous zone

### 5. VISION_POSITION_ESTIMATE vs VISION_POSITION_DELTA

**Recommendation: Keep VISION_POSITION_ESTIMATE.** Reasons:
1. ArduPilot's alignment mechanism already handles zone origin changes seamlessly
2. Absolute position is more robust for RTK/VSLAM fusion
3. Existing bridge is already implemented and tested
4. VISION_POSITION_DELTA is for simpler VIO systems without a global map

### 6. Map-to-Odom Transform in RTAB-Map

RTAB-Map maintains two frames:
- **"odom" frame**: Raw visual odometry output (accumulates drift)
- **"map" frame**: Loop-closure-corrected global frame

The map-to-odom transform is internal to RTAB-Map and per-database — different zone databases have independent transforms. No bridge-side handling needed.

### 7. Lua Source Switching and Zone Transitions

The Lua script operates purely on sensor health metrics. During zone transition:
1. VSLAM service stops → ExternalNav innovation becomes invalid
2. Lua script votes toward GPS — correct behavior
3. After VSLAM restarts, vote counter takes ~2 seconds to recover — natural stabilization window

**The Lua script needs NO zone awareness.**

### 8. ArduPilot Parameters — None Need Per-Zone Changes

| Parameter | Zone-Dependent? | Reason |
|-----------|-----------------|--------|
| `VISO_TYPE=1` | No | MAVLink backend, same for all zones |
| `VISO_POS_X/Y/Z` | No | Physical camera offset doesn't change |
| `EK3_SRC1_*` / `EK3_SRC2_*` | No | Source sets are zone-independent |

The only zone-dependent config is the RTAB-Map `database_path` in `vslam.yaml`.

**Key Discoveries:**
- ArduPilot's `AP_VisualOdom_MAV` (VISO_TYPE=1) does NOT use `reset_counter` for data gating — only logs it
- ArduPilot continuously aligns ExternalNav to GPS/AHRS when GPS is primary — zone-switch VSLAM frame origin changes are handled automatically
- Bridge's stateless restart behavior is ideal — no velocity spikes, no stale state
- Lua source switching script needs NO zone awareness — operates on sensor health only
- VISION_POSITION_ESTIMATE remains correct over VISION_POSITION_DELTA
- No ArduPilot parameters need per-zone changes
- Zone transition safety relies on: GPS primary during transit → VSLAM restart → ArduPilot realigns ExternalNav → Lua stays on GPS until VSLAM settles

| File | Relevance |
|------|-----------|
| `src/mower_rover/vslam/bridge.py` | VSLAM→MAVLink bridge; reset_counter tracking, FLU→NED conversion |
| `src/mower_rover/vslam/frames.py` | FLU↔NED coordinate conversion |
| `src/mower_rover/vslam/ipc.py` | PoseReader with auto-reconnect |
| `src/mower_rover/params/data/ahrs-source-gps-vslam.lua` | Lua EKF3 source switching (vote-based) |

**External Sources:**
- [ArduPilot GPS/Non-GPS Transitions](https://ardupilot.org/copter/docs/common-non-gps-to-gps.html)
- [ArduPilot EKF Source Selection](https://ardupilot.org/copter/docs/common-ekf-sources.html)
- [ArduPilot AP_VisualOdom source](https://github.com/ArduPilot/ardupilot)

**Gaps:** None — all 9 research questions answered with codebase and documentation evidence.  
**Assumptions:** Both SLAM node and bridge restart on zone switch; VISO_TYPE=1 is production config.

## Phase 3: ArduPilot Mission Structure for Multi-Zone

**Status:** ✅ Complete  
**Session:** 2026-04-27

### 1. One Mission Per Zone (Not Combined)

ArduPilot supports only **one active mission at a time**. A combined multi-zone mission would:
- Require transit waypoints between zones (transit is manual, not autonomous)
- Complicate mission resume (which waypoint in a 1500+ item mission?)
- Approach the Cube Orange's 700+ item limit
- Mix geofence concerns

**Per-zone mission workflow:**
1. Operator selects zone: `mower zone select ne`
2. CLI loads zone's YAML definition → generates waypoints → uploads via MAVLink
3. CLI uploads zone's geofence + rally point
4. CLI verifies round-trip (download + diff)
5. Operator runs pre-flight, arms, starts Auto mode
6. After zone complete → manually drive to next zone → repeat

### 2. Waypoint Capacity

Cube Orange supports **700+ mission items** (flash storage). Per-zone estimates:

| Zone | Estimated Area | WP (endpoints + DO cmds) | Within 700 limit? |
|------|---------------|--------------------------|-------------------|
| NE lawn | ~1.5 acres | ~200–250 | Yes |
| NW lawn | ~1 acre | ~140–180 | Yes |
| South lawn | ~1.5 acres | ~200–250 | Yes |
| **Combined** | **~4 acres** | **~550–680** | **Tight/Marginal** |

Individual zones are well within limits. Per-zone upload avoids capacity concerns entirely.

### 3. Geofence Per Zone — Separate Fences, Uploaded Per Zone

**Critical finding: ArduPilot enforces ALL active inclusion fences simultaneously (intersection by default).** Multiple non-overlapping inclusion fences cannot coexist — the mower would be confined to the intersection (empty).

**Recommendation: Upload one zone's geofence before mowing that zone, replacing the previous fence.**

Fences use `MISSION_TYPE_FENCE` in the MAVLink protocol — separate from main missions. Upload replaces the previous fence implicitly (no explicit clear needed).

Per-zone fence structure:
```
seq 0: MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION (vertex_count=N, lat, lon)
seq 1: MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION (vertex_count=N, lat, lon)
...
# Optional exclusion zones within the zone:
seq N:   MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION (vertex_count=M, lat, lon)
...
```

`FENCE_OPTIONS` bit 2 (union mode) does not solve multi-zone — transit between non-overlapping zones would still breach the fence.

### 4. Fence Switching Workflow

Since all inclusion fences are enforced simultaneously and zones don't overlap, the fence **must** be replaced on zone switch. Protocol:

```
GCS → FC:  MISSION_COUNT (count=V, mission_type=FENCE)
FC → GCS:  MISSION_REQUEST_INT (seq=0, mission_type=FENCE)
GCS → FC:  MISSION_ITEM_INT (seq=0, cmd=FENCE_POLYGON_VERTEX_INCLUSION, ...)
   ... repeat ...
FC → GCS:  MISSION_ACK (type=MAV_MISSION_ACCEPTED)
```

**Important:** Fence upload/download requires **MAVLink2** protocol. Verify SiK radio link configuration (`SERIAL2_PROTOCOL=2`).

### 5. Mission Upload/Download (Per Zone)

Standard MAVLink mission protocol:
- **Upload:** MISSION_COUNT → MISSION_REQUEST_INT/MISSION_ITEM_INT × N → MISSION_ACK
- **Download (verify):** MISSION_REQUEST_LIST → MISSION_COUNT → MISSION_REQUEST_INT × N → MISSION_ACK
- **Clear:** MISSION_CLEAR_ALL → MISSION_ACK

**Quirks:** Seq 0 = auto-populated home position; upload is not atomic (verify via round-trip); cannot clear during Auto mode.

### 6. Mission Resume Within a Zone

ArduPilot Rover supports robust mission resume:

- **MISSION_CURRENT** tracks the last active waypoint through Hold/Disarm
- **DO_SET_RESUME_REPEAT_DIST** (cmd 215): Insert at mission start for rewind-on-resume behavior
  - 7 waypoint history (~8.4 m at 1.2 m spacing) — adequate for track re-acquisition
  - Requires `MIS_RESTART=0`
- **MAV_CMD_MISSION_START** with `param1=current_wp` resumes from a specific waypoint

**Zone-specific resume:** CLI reads MISSION_CURRENT, logs zone_id + last_wp to run metadata (JSON), offers "Resume zone NE from waypoint N?" on restart.

### 7. DO_FENCE_ENABLE in Missions

`MAV_CMD_DO_FENCE_ENABLE` (cmd 207) can enable/disable fences within a mission:

- Include `DO_FENCE_ENABLE(param1=1)` as the first DO command in each zone mission
- Set `FENCE_ENABLE=1` globally + include mission item as safety belt
- Recommendation: `FENCE_ENABLE=1` globally, `DO_FENCE_ENABLE(1)` at mission start

### 8. Rally Points Per Zone

**One rally point per zone, uploaded alongside fence:**

Rally points use `mission_type=MAV_MISSION_TYPE_RALLY`. Per-zone rally point = zone's staging area (where mower enters from driveway).

- `RALLY_LIMIT_KM=0.5` prevents returning to a distant zone's rally point
- `RALLY_INCL_HOME=1` allows Home as fallback

**Zone switch sequence:**
1. Upload mission (MISSION_TYPE_MISSION)
2. Upload fence (MISSION_TYPE_FENCE)
3. Upload rally point (MISSION_TYPE_RALLY)
4. Verify all three via round-trip download

**Key Discoveries:**
- ArduPilot supports only one active mission; per-zone upload is the correct approach
- All active inclusion fences enforced simultaneously (intersection) — non-overlapping zone fences CANNOT coexist; must replace on zone switch
- Geofences, missions, and rally points use same MAVLink protocol with different `mission_type` values (MISSION, FENCE, RALLY)
- Individual zone missions (140–250 items each) well within Cube Orange 700+ item limit
- `DO_SET_RESUME_REPEAT_DIST` enables rewind-on-resume with 7 waypoint history
- Fence upload/download requires MAVLink2 protocol
- Zone switch = atomic operator action: upload mission + fence + rally point, verify, start Auto

| File | Relevance |
|------|-----------|
| `docs/research/001-mvp-bringup-rtk-mowing.md` | Phase 6 (mission format, MAVLink protocol) and Phase 7 (pre-flight, geofence) |

**External Sources:**
- [MAVLink Mission Protocol](https://mavlink.io/en/services/mission.html)
- [ArduPilot Polygon Fences](https://ardupilot.org/rover/docs/common-polygon_fence.html)
- [ArduPilot Rally Points](https://ardupilot.org/rover/docs/common-rally-points.html)
- [ArduPilot Mission Rewind](https://ardupilot.org/rover/docs/common-mission-rewind.html)

**Gaps:**
- Exact max mission items on Cube Orange needs field verification
- Rewind history survival after E-stop + full disarm needs field testing
- MAVLink2 default on SiK radio link needs verification

## Phase 4: YAML Mission Format and Zone Configuration

**Status:** ✅ Complete  
**Session:** 2026-04-27

### 1. Zone Configuration Structure: One YAML File Per Zone

**One YAML file per zone** (not a combined `zones.yaml`):

| Criterion | One file per zone | Single zones.yaml |
|-----------|-------------------|-------------------|
| Git diff clarity | Only changed zone in diff | All zones touched |
| CLI ergonomics | `mower mission plan zones/ne.yaml` | `--zone ne zones.yaml` |
| Snapshot/restore | Per-zone granularity | Parse sub-document |
| Extensibility | New zone = new file | Modify shared file |

Zone ID convention: short, lowercase, CLI-friendly identifiers (`ne`, `nw`, `south`). Validation: `^[a-z][a-z0-9_-]{0,31}$`.

### 2. Zone Metadata — What Belongs at Zone Level

| Field | Type | Purpose |
|-------|------|---------|
| `zone_id` | string | CLI-friendly identifier |
| `name` | string | Human-readable display name |
| `description` | string (optional) | Notes about the zone |
| `boundary` | polygon (lat/lon) | Mowing boundary = geofence inclusion polygon |
| `exclusion_zones` | list of named polygons | Obstacles (trees, rocks, flower beds) |
| `rally_point` | lat/lon | Zone staging area |
| `home` | lat/lon | ArduPilot home position |
| `coverage` | params block | Deck width, overlap, heading, speed, headland passes |
| `commands` | overrides | fence_enable, resume_dist, blade_engage |
| `slam` | overrides | slam_mode (mapping/localization) |

### 3. Full YAML Schema for a Zone Definition

```yaml
# Zone definition — NE lawn
schema: "mower-rover.zone.v1"

zone_id: ne
name: "North East Lawn"
description: "Flat ~1.5 acre area. Bordered by driveway (N), house (W), fence (E/S)."

home:
  lat: 38.89510
  lon: -77.03660

rally_point:
  lat: 38.89505
  lon: -77.03655
  description: "Driveway entrance to NE lawn"

boundary:
  - [38.89510, -77.03660]
  - [38.89510, -77.03400]
  - [38.89350, -77.03400]
  - [38.89350, -77.03660]

exclusion_zones:
  - name: "oak_tree_ne"
    buffer_m: 1.0
    polygon:
      - [38.89480, -77.03550]
      - [38.89480, -77.03520]
      - [38.89460, -77.03520]
      - [38.89460, -77.03550]

coverage:
  pattern: boustrophedon
  cutting_width_in: 54
  overlap_pct: 10
  angle_deg: auto
  headland_passes: 2
  mow_speed_mps: 2.0
  turn_speed_mps: 1.0

commands:
  fence_enable: true
  resume_dist_m: 2.5
  blade_engage: true

slam:
  mode: localization

output:
  waypoints_file: ne.waypoints
  geojson_file: ne.geojson
```

Schema versioning (`mower-rover.zone.v1`) follows the existing `write_json_snapshot()` pattern. Coordinate format: `[lat, lon]` pairs; GeoJSON output flips to `[lon, lat]` per RFC 7946.

### 4. Directory/File Structure on Laptop

```
project-root/
├── zones/
│   ├── ne.yaml              # Zone definitions (Git-tracked source of truth)
│   ├── nw.yaml
│   ├── south.yaml
│   └── generated/           # Generated .waypoints and .geojson
│       ├── ne.waypoints
│       ├── ne.geojson
│       └── ...
├── snapshots/
│   └── missions/
│       ├── ne/              # Per-zone mission upload snapshots (JSON)
│       ├── nw/
│       └── south/
```

Zone YAMLs are **Git-tracked** — consistent with "Snapshots: Plain files, Git-tracked" convention. `git diff` before committing boundary changes provides the "diff before apply" pattern.

### 5. Directory/File Structure on Jetson

```
/var/lib/mower/
├── zones/
│   ├── ne/
│   │   ├── rtabmap.db       # SLAM database
│   │   └── runs/            # Per-zone run logs
│   ├── nw/
│   └── south/
```

Active zone state is the `database_path` in `/etc/mower/vslam.yaml` — no separate `active_zone` file needed.

### 6. GeoJSON Export Format

Zone GeoJSON includes:
- **FeatureCollection-level properties**: `zone_id`, `zone_name`, generation timestamp, coverage summary stats
- **Per-feature properties**: `zone_id`, `feature_type` (boundary/exclusion/home/rally/coverage_pass) for QGIS filtering
- Coordinates in `[lon, lat]` per RFC 7946

Multi-zone property overview: `mower mission export-map zones/ --output property.geojson` — combines all zone boundaries for visualization.

### 7. CLI Zone Selection for `mower mission plan`

```bash
mower mission plan zones/ne.yaml                     # Plan single zone
mower mission plan zones/                             # Plan all zones
mower mission upload zones/generated/ne.waypoints     # Upload to autopilot
mower mission deploy zones/ne.yaml --port udp:...     # Plan + upload + verify
mower mission export-map zones/ --output property.geojson  # Multi-zone map
```

Zone YAML file path IS the zone selector — `zone_id` is read from the YAML file's `zone_id` field. No separate `--zone` flag needed.

### 8. Zone Config Validation Rules

**Schema validation (load time):**

| Rule | Severity |
|------|----------|
| `zone_id` format matches `^[a-z][a-z0-9_-]{0,31}$` | ERROR |
| `boundary` ≥ 3 vertices, valid Shapely polygon | ERROR |
| `exclusion_zones[*].polygon` valid polygons | ERROR |
| `coverage.cutting_width_in` > 0 | ERROR |
| `coverage.overlap_pct` 0–50% | ERROR |
| `rally_point` inside/at-edge of boundary | WARN |

**Cross-zone validation (plan time):**

| Rule | Severity |
|------|----------|
| Non-overlapping zone boundaries | WARN (not ERROR — one fence active at a time) |
| Exclusions inside boundary | WARN |
| Boundary area reasonable (100 m²–100,000 m²) | WARN |

### 9. Versioning/Snapshotting Interaction

| Artifact | Storage | Versioning |
|----------|---------|-----------|
| Zone YAML | `zones/{id}.yaml` (Git) | Git history |
| Generated .waypoints/.geojson | `zones/generated/` | Regenerated from YAML |
| Uploaded mission snapshot | `snapshots/missions/{id}/` (JSON, Git) | Auto on upload |
| SLAM database | `/var/lib/mower/zones/{id}/rtabmap.db` (Jetson) | `mower backup` |

Git IS the snapshot system for zone definitions. Mission upload creates JSON snapshots following `write_json_snapshot()` pattern.

**Key Discoveries:**
- One YAML file per zone — follows existing project patterns, clean Git diffs
- Zone YAML extends MVP Phase 6 mission format with `zone_id`, `name`, `rally_point`, `slam.mode`, `schema` version
- Zone files in `zones/` at project root (Git-tracked)
- `zone_id` is universal key across laptop (filename), Jetson (directory), CLI (argument), GeoJSON (property)
- Zone YAML file path IS the CLI zone selector — no separate `--zone` flag
- `database_path` in `vslam.yaml` is the active zone state on Jetson
- All needed dependencies (shapely, pyproj, pyyaml) already in `pyproject.toml`
- `buffer_m` on exclusion zones allows per-obstacle clearance tuning

| File | Relevance |
|------|-----------|
| `src/mower_rover/config/vslam.py` | VslamConfig dataclass pattern for ZoneConfig |
| `src/mower_rover/config/laptop.py` | LaptopConfig pattern (dataclass + coerce + load/save) |
| `src/mower_rover/params/io.py` | `write_json_snapshot()` pattern for mission snapshots |
| `src/mower_rover/safety/confirm.py` | Safety primitive for mission upload |

**Gaps:**
- Actual boundary coordinates need RTK GPS perimeter walk or Google Earth trace
- `angle_deg: auto` optimization algorithm untested on actual property geometry

## Phase 5: Operator Workflow and Zone-Aware Tooling

**Status:** ✅ Complete  
**Session:** 2026-04-27

### 1. End-to-End Operator Workflow: Full Session

```
SESSION START
│
├─ 1. Power up: Jetson boots, VSLAM + bridge services start (last active zone)
├─ 2. Laptop connects: $ mower jetson info  (verify Jetson reachable)
│
├─ ZONE 1 (NE)
│  ├─ 3. $ mower zone select zones/ne.yaml --port udp:...
│  │     → SSH to Jetson: activate NE zone (restart VSLAM with NE DB)
│  │     → Generate waypoints from zone YAML
│  │     → Upload mission + fence + rally → verify round-trip
│  │     → Save upload snapshot
│  ├─ 4. $ mower preflight --zone zones/ne.yaml --port udp:...
│  ├─ 5. Arm + Auto → autonomous mowing
│  ├─ 6. Zone complete → Hold mode
│
├─ TRANSIT (NE → NW)
│  ├─ 7. Manual mode (FrSky), drive on driveway to NW staging area, Hold
│
├─ ZONE 2 (NW)
│  ├─ 8. $ mower zone select zones/nw.yaml → repeat steps 3–6
│
├─ TRANSIT → ZONE 3 (South) → same pattern
│
├─ SESSION END
│  ├─ 10. $ mower zone status  (session summary)
```

Transit is **always manual** — operator drives on driveway. Autonomous transit would breach geofences and cross non-mowable terrain.

### 2. Zone Select Command — Laptop Side

```bash
mower zone select <zone.yaml> [--port udp:...] [--dry-run] [--skip-slam] [--slam-mode auto|mapping|localization]
```

**Steps (in order):**

| Step | Action | Safety |
|------|--------|--------|
| 1 | Load + validate zone YAML | Schema validation |
| 2 | Check FC not armed | Refuse if armed |
| 3 | SSH to Jetson: `mower-jetson zone activate {zone_id}` | `requires_confirmation` |
| 4 | Wait for VSLAM service ready (~15s) | Timeout + fallback |
| 5 | Generate waypoints from boundary + exclusions + coverage | Shapely + pyproj |
| 6 | Upload mission via MAVLink | `requires_confirmation` |
| 7 | Upload geofence via MAVLink | Same confirmation |
| 8 | Upload rally point | Same confirmation |
| 9 | Round-trip verify all three | Diff + abort on mismatch |
| 10 | Save upload snapshot | Git-trackable JSON |

**Flags:**
- `--dry-run`: Plans and validates but skips uploads and VSLAM restart
- `--skip-slam`: Skip SSH/VSLAM restart (for mission-only re-deployment)
- `--slam-mode auto` (default): DB exists → localization; no DB → mapping

### 3. Zone Activate Command — Jetson Side

```bash
mower-jetson zone activate <zone_id> [--slam-mode auto|mapping|localization] [--json]
```

Updates `/etc/mower/vslam.yaml` `database_path` to `/var/lib/mower/zones/{zone_id}/rtabmap.db`, sets `slam_mode`, restarts `mower-vslam.service` + `mower-vslam-bridge.service`.

### 4. Coordinated Zone Switch via SSH

The laptop orchestrates via SSH — one command does everything:

```python
client = JetsonClient(endpoint, correlation_id=cid)
result = client.run(
    ["mower-jetson", "zone", "activate", zone_id, "--slam-mode", slam_mode, "--json"],
    timeout=60,
)
```

Follows existing `JetsonClient` pattern. Fallback: if SSH fails, operator manually runs `mower-jetson zone activate ne` on Jetson, then `mower zone select --skip-slam` on laptop.

### 5. Pre-Flight Zone-Specific Checks

4 new zone-specific checks:

| # | Check | Level | Pass Criteria |
|---|-------|-------|---------------|
| PF-37 | Fence matches zone boundary | CRITICAL | Downloaded fence vertices match zone YAML boundary |
| PF-38 | Mission count matches zone | WARN | Count within ±5 of expected |
| PF-39 | VSLAM zone matches | WARN | `database_path` contains `zones/{zone_id}/` |
| PF-40 | VSLAM relocalized | WARN | Confidence ≥ 1 within timeout |

**PF-37 is CRITICAL** — mission/fence zone mismatch could drive the mower outside intended boundary. PF-39/40 are WARN because VSLAM is supplementary to RTK GPS.

### 6. Mission Resume Within a Zone

```bash
mower zone resume zones/ne.yaml --port udp:...
```

Reads `MISSION_CURRENT` from FC, displays "Resume NE from waypoint 142/217?", re-arms and Auto resumes. ArduPilot's `DO_SET_RESUME_REPEAT_DIST` provides rewind for clean track re-acquisition. **No zone re-selection needed** unless Jetson rebooted.

### 7. Safe-Stop: Zone-Agnostic

Safe-stop does NOT need zone awareness. Hold mode, blade kill, engine kill are all zone-independent. `zone_id` added to structlog bind context for traceability only.

### 8. Error Recovery: Zone Switch Failures

**Most dangerous failure: mission uploads but fence upload fails.** Mitigation:

1. Upload sequence: mission → fence → rally → verify ALL THREE
2. If ANY upload fails: **clear all three** (`MISSION_CLEAR_ALL` for each type)
3. CLI reports: "Zone switch FAILED. Mission cleared for safety. Retry: `mower zone select zones/ne.yaml`"
4. `mower zone select` checks FC not armed at start — zone switching while armed is forbidden

`mower zone select` is idempotent — safe to re-run on failure.

### 9. Zone Status Tracking

```bash
$ mower zone status --port udp:...
┌──────────────────────────────────────────────────────────┐
│ Zone Status — Session 2026-04-27T14:30:00                │
├──────┬───────────────┬──────────┬────────┬───────────────┤
│ Zone │ Name          │ Status   │ WPs    │ Duration      │
├──────┼───────────────┼──────────┼────────┼───────────────┤
│ ne   │ North East    │ ✓ Done   │ 217/217│ 35m 12s       │
│ nw   │ North West    │ ▶ Active │ 89/156 │ 18m 03s       │
│ south│ South         │ ○ Pending│ —      │ —             │
└──────┴───────────────┴──────────┴────────┴───────────────┘
```

Status derived from run metadata files (`snapshots/missions/{zone_id}/run-*.json`).

### 10. CLI Command Summary

**New laptop commands:**

| Command | Description |
|---------|-------------|
| `mower zone select <zone.yaml>` | Full zone switch (VSLAM + mission + fence + rally) |
| `mower zone resume <zone.yaml>` | Resume interrupted mowing |
| `mower zone status` | Session zone completion status |
| `mower zone list` | List available zone YAML files |

**New Jetson commands:**

| Command | Description |
|---------|-------------|
| `mower-jetson zone activate <zone_id>` | Update VSLAM config + restart services |
| `mower-jetson zone status` | Active zone, DB sizes, service health |

**Key Discoveries:**
- `mower zone select` is the single orchestrating command — coordinates laptop + Jetson from one invocation
- Transit between zones is always manual (operator drives, Manual mode, ~30s)
- Pre-flight gains 4 zone checks; PF-37 (fence/boundary match) is CRITICAL
- Safe-stop is zone-agnostic; zone_id is metadata only
- Mission resume works natively (MISSION_CURRENT + DO_SET_RESUME_REPEAT_DIST)
- Most dangerous failure = mission/fence mismatch → mitigated by clear-all on any partial failure
- All new commands follow existing patterns: Typer, SafetyContext, JetsonClient SSH, structlog

| File | Relevance |
|------|-----------|
| `src/mower_rover/cli/laptop.py` | Laptop CLI entry point; add `zone` subcommand |
| `src/mower_rover/cli/jetson.py` | Jetson CLI; add `zone activate/status` |
| `src/mower_rover/cli/jetson_remote.py` | JetsonClient SSH pattern |
| `src/mower_rover/safety/confirm.py` | SafetyContext for actuator commands |
| `src/mower_rover/transport/ssh.py` | SSH transport for Jetson orchestration |
| `src/mower_rover/probe/registry.py` | Pre-flight check registration |

**Gaps:**
- Exact MAVLink MISSION_CLEAR_ALL per mission_type behavior needs implementation verification
- Fence vertex comparison tolerance needs field validation
- Auto-detection of "zone complete" (final waypoint reached) vs manual marking

## Overview

Multi-zone lawn management for the three-zone property (NE, NW, South) is architecturally clean and requires minimal changes to the existing system. The core insight is that **zone switching is a deliberate operator action** — not a hot-swap during autonomous operation — which allows a simple, safe design: each zone gets its own RTAB-Map database, ArduPilot mission, geofence, and rally point. The operator selects a zone via a single CLI command (`mower zone select zones/ne.yaml`) that orchestrates both the Jetson VSLAM restart and the ArduPilot mission/fence upload.

The VSLAM system handles zone transitions gracefully because ArduPilot's `AP_VisualOdom_MAV` backend continuously aligns ExternalNav position to GPS/AHRS when GPS is primary. Zone transit (manual drive on driveway) naturally keeps the mower on GPS; after VSLAM restarts with the new zone's DB, ArduPilot realigns automatically — no position jump, no parameter changes.

The zone YAML format extends the MVP mission definition with `zone_id`, boundary, exclusions, rally point, coverage parameters, and SLAM mode. Zone files are Git-tracked (one file per zone in `zones/`), and the zone ID serves as the universal key across laptop filenames, Jetson directories, CLI arguments, and GeoJSON properties.

Safety is maintained through: (1) fence replacement on every zone switch (ArduPilot enforces all inclusion fences simultaneously — non-overlapping fences cannot coexist), (2) clear-all-on-failure if any upload step fails (prevents mission/fence mismatch), (3) a new CRITICAL pre-flight check that verifies the uploaded fence matches the zone boundary, and (4) refusing zone switches while the FC is armed.

## Key Findings

1. **Separate RTAB-Map DB per zone** — no visual overlap between zones means a shared DB has zero benefit; zone switch = service restart with new `database_path` (~5–15s cold-start relocalization, RTK GPS bridges the gap)
2. **ArduPilot handles VSLAM frame discontinuity automatically** — `align_position_to_ahrs()` realigns ExternalNav on every frame; no ArduPilot params change per zone; Lua script needs no zone awareness
3. **One mission + one fence + one rally per zone** — ArduPilot enforces all inclusion fences simultaneously (intersection), so non-overlapping zone fences cannot coexist; must replace all three on zone switch
4. **Per-zone mission items (140–250) well within Cube Orange 700+ limit** — combined would be marginal; per-zone avoids capacity concerns
5. **One YAML file per zone, Git-tracked** — extends MVP mission format with `zone_id`, `rally_point`, `slam.mode`; file path IS the CLI zone selector
6. **`mower zone select` is the single orchestrating command** — coordinates Jetson (VSLAM DB switch via SSH) and laptop (mission/fence/rally upload via MAVLink) in one invocation
7. **Mission/fence mismatch is the most dangerous failure mode** — mitigated by clear-all on any partial upload failure
8. **Safe-stop is zone-agnostic** — Hold mode, blade kill, engine kill are zone-independent
9. **Mission resume works natively** — `MISSION_CURRENT` + `DO_SET_RESUME_REPEAT_DIST` provide track re-acquisition without zone re-selection
10. **~100–300 MB per zone DB** — trivial for 2 TB NVMe; total VSLAM storage ~1 GB

## Actionable Conclusions

- **Add `slam_mode` field** to `VslamConfig` dataclass and `vslam_defaults.yaml`; plumb to RTAB-Map `Mem/IncrementalMemory` parameter in C++ SLAM node
- **Create `zones/` directory** at project root with one YAML file per zone (`ne.yaml`, `nw.yaml`, `south.yaml`) using `mower-rover.zone.v1` schema
- **Implement `mower zone select`** command (laptop-side) that orchestrates SSH zone activation + mission/fence/rally upload + round-trip verification
- **Implement `mower-jetson zone activate`** command (Jetson-side) that updates `vslam.yaml` `database_path` + restarts VSLAM services
- **Add 4 pre-flight checks** (PF-37 through PF-40): fence/boundary match (CRITICAL), mission count, VSLAM zone match, VSLAM relocalization
- **Implement clear-all-on-failure** safety guard in zone select: if any upload step fails, clear mission + fence + rally to prevent mismatch
- **Add armed-check guard** at zone select start: refuse to switch zones while FC is armed
- **Create `ZoneConfig` dataclass** following the existing `VslamConfig`/`LaptopConfig` pattern
- **Create zone run metadata** (`mower-rover.zone-run.v1` JSON) for session status tracking

## Open Questions

- **Actual zone boundary coordinates** — need RTK GPS perimeter walk or Google Earth trace for all three zones
- **RTAB-Map DB size in practice** — estimated 100–300 MB per zone; field measurement needed after initial mapping pass
- **Cold-start relocalization timing** — estimated 5–15 seconds; field measurement on Orin with production zone DB needed
- **ArduPilot EKF behavior on VSLAM service restart** — does `align_position_to_ahrs()` work seamlessly in practice? Field test during zone transit
- **Rewind history survival after E-stop** — does `DO_SET_RESUME_REPEAT_DIST` history survive full disarm cycle?
- **Fence vertex float precision** — MAVLink uses int32 lat/lon (1e-7 degree resolution); is this sufficient for fence comparison tolerance?
- **MAVLink2 on SiK radio** — fence upload requires MAVLink2; verify `SERIAL2_PROTOCOL=2` on SiK link
- **Auto-detection of "zone complete"** — can the FC signal when the final waypoint is reached, or must the operator mark done manually?
- **`slam_mode` and odometry strategy** — should localization mode also switch to F2F (lighter CPU) instead of F2M?

## Follow-Up Research

- Field measurement: RTAB-Map DB size after mapping each zone
- Field measurement: Cold-start relocalization timing on Orin with production zone DBs
- Field test: ArduPilot EKF behavior during zone transit (monitor XKFS + ExternalNav innovation)
- Field test: Full three-zone session workflow with actual mower
- Field test: Rewind-on-resume after E-stop with mowing waypoint spacing
- Implementation: Zone boundary coordinate collection (RTK perimeter walk procedure)
- Implementation: `mower zone select`, `mower-jetson zone activate`, `ZoneConfig` dataclass, zone pre-flight checks

## References

### Phase 1 Sources
- [RTAB-Map Multi-Session Tutorial](https://github.com/introlab/rtabmap/wiki/Multi-session)
- [RTAB-Map FAQ — Mapping vs Localization](https://github.com/introlab/rtabmap/wiki/FAQ)
- [RTAB-Map source — Rtabmap.h/cpp, Memory.h/cpp, Parameters.h](https://github.com/introlab/rtabmap)

### Phase 2 Sources
- [ArduPilot GPS/Non-GPS Transitions](https://ardupilot.org/copter/docs/common-non-gps-to-gps.html)
- [ArduPilot EKF Source Selection](https://ardupilot.org/copter/docs/common-ekf-sources.html)
- [ArduPilot AP_VisualOdom source](https://github.com/ArduPilot/ardupilot)

### Phase 3 Sources
- [MAVLink Mission Protocol](https://mavlink.io/en/services/mission.html)
- [ArduPilot Polygon Fences](https://ardupilot.org/rover/docs/common-polygon_fence.html)
- [ArduPilot Rally Points](https://ardupilot.org/rover/docs/common-rally-points.html)
- [ArduPilot Mission Rewind](https://ardupilot.org/rover/docs/common-mission-rewind.html)

### Phase 4 Sources
- [GeoJSON RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946)

### Phase 5 Sources
- [MAVLink MISSION_CURRENT](https://mavlink.io/en/services/mission.html)
- [ArduPilot Rover Mission Resume](https://ardupilot.org/rover/docs/common-mission-rewind.html)

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-27 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/014-multi-zone-lawn-management.md |
