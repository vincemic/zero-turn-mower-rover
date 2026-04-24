---
id: "009"
type: plan
title: "Jetson MAVLink + VSLAM Deployment Gap Closure"
status: "✅ Complete"
created: "2026-04-23"
updated: "2026-04-24"
completed: "2026-04-24"
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-23 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-23 | pch-planner | Scope decision: all 10 gaps; Overview populated |
| v1.2 | 2026-04-23 | pch-planner | Bringup pipeline ordering: interleave at dependency points |
| v1.3 | 2026-04-23 | pch-planner | Logrotate fix: RotatingFileHandler in Python, drop logrotate for daemon logs |
| v1.4 | 2026-04-23 | pch-planner | Detect wiring: thin wrapper with Jetson defaults |
| v2.0 | 2026-04-23 | pch-planner | Technical design, execution plan, holistic review complete |
| v2.1 | 2026-04-23 | pch-plan-reviewer | Fix G10 probe signature (keyword-only → positional), depends_on list → tuple; fix G9 to follow config-driven user_level pattern; clarify Phase 1↔3 bridge-start dependency; fix G3 hardcoded username |

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 1  
**Last Updated:** 2026-04-24

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | `/run/mower` ephemeral on tmpfs — mkdir vs RuntimeDirectory | clarity | Option A: mkdir in bringup + RuntimeDirectory in units | G3 step 6 clarified; G8 + VSLAM unit templates updated; Phase 2 task 2.5 added |

## Introduction

This plan addresses the deployment and integration gaps identified in [Research 008](../research/008-jetson-mavlink-vision-integration-deploy.md). The Jetson bringup pipeline is ~90% complete; this plan closes the remaining gaps so the full MAVLink + VSLAM + bridge stack can be deployed and validated via a single `mower jetson bringup` invocation, with consistent device naming, proper log rotation, and on-device hardware detection.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | Scope — which gaps to include | C — All 10 gaps (Critical + High + Medium + Low) | Full gap closure in one plan so field testing can proceed without trailing fixups |
| 2 | Bringup pipeline ordering | C — Interleave at logical dependency points | `pixhawk-udev` after `harden` (infra before software); VSLAM config+services after `service` (respects systemd dep chain). Each step independently skippable via `--step`. Pipeline: check-ssh → harden → pixhawk-udev → install-uv → install-cli → verify → service → vslam-config → vslam-services |
| 3 | Logrotate fix strategy | B — Switch to `RotatingFileHandler` in Python | In-process rotation is install-path-agnostic, avoids SIGHUP complexity for user-level daemons. Remove daemon log path from logrotate config; keep logrotate for system-level targets only. 10 MB max, 5 backups. |
| 4 | Wiring `detect` to `mower-jetson` | B — Thin wrapper with Jetson-specific defaults | Jetson detect defaults to `--port /dev/pixhawk --baud 0` so `mower-jetson detect` just works on-device. Calls existing `_collect()` + `_render_human()` from `cli/detect.py`. No code duplication, no over-refactoring. |

## Holistic Review

### Decision Interactions

1. **Pipeline ordering (Q2) × `/dev/pixhawk` standardization (G7/G8):** Placing `pixhawk-udev` before `install-cli` ensures the udev symlink is already present when the CLI is installed and later when VSLAM services reference `/dev/pixhawk`. Consistent device naming across config (G7), service units (G8), and probe (G10) eliminates the class of bugs where one component uses `/dev/ttyACM0` and another uses `/dev/pixhawk`.

2. **`[jetson]` extras (G1) × VSLAM service deployment (G2):** The install command fix (G1) must land before VSLAM services are started (G2), because `mower-jetson vslam install` internally references modules that import from `depthai`. The pipeline ordering naturally satisfies this: `install-cli` (with `[jetson]` extras) precedes `vslam-services`.

3. **RotatingFileHandler (G5) × daemon lifetime:** The bridge and health daemons run indefinitely under systemd. Without rotation, a single JSONL file grows unbounded. With 10 MB × 5 backups = 50 MB max disk usage per daemon — acceptable on the Jetson's NVMe.

4. **Detect on Jetson (G6) × probe check (G10):** Both validate Pixhawk connectivity but serve different purposes. `detect` provides a rich hardware report for debugging; the probe check is a boolean pass/fail for automated pre-flight. They complement rather than overlap.

### Architectural Considerations

- **No new dependencies introduced.** All changes use existing stdlib (`logging.handlers`, `subprocess`, `pathlib`) and project libraries.
- **Backward compatibility:** The 3 new bringup steps are additive. Existing `--step check-ssh` through `--step service` behavior is unchanged.
- **`uv tool install` extras syntax risk** is the only field-validation item. Fallback path is documented.

### Trade-offs Accepted

- **G5 logrotate left as-is in `jetson-harden.sh`:** The existing logrotate stanza for `/var/log/mower-jetson/*.log` becomes a no-op (no files written there). Removing it would require modifying `jetson-harden.sh`, which is out of scope. Leaving a no-op stanza is harmless.
- **No automated rollback for VSLAM services in bringup:** If service install fails, the operator must manually debug. Automated rollback is deferred per Out of Scope.

### Risks Acknowledged

- `uv tool install` extras-from-wheel syntax needs field testing (documented fallback)
- `BindsTo=dev-pixhawk.device` needs field validation that systemd creates the device unit from the udev `TAG+="systemd"` rule

## Overview

Close all 10 deployment/integration gaps identified in Research 008 so the full MAVLink + VSLAM + bridge stack deploys end-to-end from a single `mower jetson bringup` invocation.

### Gaps In Scope

| # | Gap | Severity | Category |
|---|-----|----------|----------|
| G1 | `depthai` not in bringup install command (`--with sdnotify` → `[jetson]` extras) | Critical | Bringup pipeline |
| G2 | VSLAM + bridge services not in bringup pipeline | High | Bringup pipeline |
| G3 | `90-pixhawk-usb.rules` not auto-deployed | High | Bringup pipeline |
| G4 | Runtime dirs not auto-created (`/var/lib/mower/`, `/run/mower/`, `/etc/mower/`) | High | Bringup pipeline |
| G5 | Logrotate path mismatch (`/var/log/` vs `~/.local/share/`) | Medium | Field reliability |
| G6 | `detect` not wired to `mower-jetson` CLI | Medium | On-device tooling |
| G7 | `vslam_defaults.yaml` hardcodes `/dev/ttyACM0` instead of `/dev/pixhawk` | Low | Config consistency |
| G8 | Bridge `BindsTo=dev-ttyACM0.device` vs `/dev/pixhawk` mismatch | Low | Service unit |
| G9 | No `bridge-start` / `bridge-stop` convenience CLI commands | Low | Developer UX |
| G10 | No `/dev/pixhawk` symlink probe check | Low | Pre-flight |

### Objectives

1. Single `mower jetson bringup` deploys the full stack (health + VSLAM + bridge)
2. Consistent `/dev/pixhawk` symlink usage across config, service units, and probes
3. Daemon logs rotate correctly in the field
4. `mower-jetson detect` available for on-device hardware verification
5. Convenience CLI for bridge lifecycle management

## Requirements

### Functional

| ID | Requirement | Gap |
|----|-------------|-----|
| F1 | `mower jetson bringup` installs with `[jetson]` extras (includes `depthai`) | G1 |
| F2 | Bringup pipeline includes `pixhawk-udev` step: deploy `90-pixhawk-usb.rules`, create `/var/lib/mower/`, `/run/mower/`, `/etc/mower/` | G3, G4 |
| F3 | Bringup pipeline includes `vslam-config` step: push default `vslam.yaml` to `/etc/mower/` if absent | G4 |
| F4 | Bringup pipeline includes `vslam-services` step: install + start `mower-vslam` and `mower-vslam-bridge` services | G2 |
| F5 | Daemon logs rotate via `RotatingFileHandler` (10 MB, 5 backups) | G5 |
| F6 | `mower-jetson detect` command with default `--port /dev/pixhawk --baud 0` | G6 |
| F7 | `vslam_defaults.yaml` uses `/dev/pixhawk` for `serial_device` | G7 |
| F8 | Bridge service unit uses `BindsTo=dev-pixhawk.device` | G8 |
| F9 | `mower-jetson vslam bridge-start` and `bridge-stop` convenience commands | G9 |
| F10 | Probe check `pixhawk_symlink` validates `/dev/pixhawk` exists | G10 |

### Non-Functional

| ID | Requirement |
|----|-------------|
| NF1 | All new bringup steps are idempotent (safe to re-run) |
| NF2 | Each bringup step independently skippable via `--step <name>` |
| NF3 | No internet dependency in any new operational step (field-offline) |
| NF4 | All new CLI commands include structured logging with correlation IDs |
| NF5 | Cross-platform: bringup runs from Windows laptop via SSH |

### Out of Scope

- Package version tracking / rollback mechanism (future plan)
- Run-archive / log collection bundle
- VISION_SPEED_ESTIMATE covariance propagation
- Extrinsic calibration tooling
- Changes to `jetson-harden.sh` beyond logrotate path cleanup

## Technical Design

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Bringup Step
    location: "src/mower_rover/cli/bringup.py"
    usage: New pixhawk-udev, vslam-config, vslam-services steps follow BringupStep(name, description, check, execute, needs_confirm) dataclass pattern
  - pattern: Probe Check
    location: "src/mower_rover/probe/checks/*.py"
    usage: New pixhawk_symlink check follows @register decorator + sysroot parameter pattern
  - pattern: Systemd Service Management
    location: "src/mower_rover/service/unit.py"
    usage: Bridge BindsTo change uses existing generate_vslam_bridge_unit_file() template
  - pattern: CLI Command Registration
    location: "src/mower_rover/cli/jetson.py"
    usage: detect + bridge-start/stop follow existing vslam_app / service_app Typer sub-app pattern
  - pattern: Structured Logging
    location: "src/mower_rover/logging_setup/setup.py"
    usage: RotatingFileHandler replaces FileHandler; same formatter and structlog config
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### G1: Fix bringup install command (`[jetson]` extras)

**File:** `src/mower_rover/cli/bringup.py` — `_run_install_cli()` function (~line 299)

**Current:**
```python
f"~/.local/bin/uv tool install --python 3.11 --force"
f" --with sdnotify ~/{whl_name}",
```

**Target:**
```python
f"~/.local/bin/uv tool install --python 3.11 --force"
f" ~/{whl_name}[jetson]",
```

The `[jetson]` extras group in `pyproject.toml` already includes both `sdnotify>=0.3` and `depthai>=3.5.0`. The explicit `--with sdnotify` becomes redundant.

**Fallback:** If `uv tool install` doesn't support extras-from-local-wheel syntax, use `--with sdnotify --with 'depthai>=3.5.0'` instead. This needs field validation.

### G2: VSLAM + bridge services in bringup (new `vslam-services` step)

**File:** `src/mower_rover/cli/bringup.py`

New `BringupStep` at position 9 (after `service`):

```python
BringupStep(
    name="vslam-services",
    description="Install and start VSLAM + bridge systemd services",
    check=_vslam_services_active,
    execute=_run_vslam_services,
    needs_confirm=True,
)
```

- **`_vslam_services_active(client)`** — `systemctl --user is-active mower-vslam.service && systemctl --user is-active mower-vslam-bridge.service`
- **`_run_vslam_services(client, bctx)`** — Runs `mower-jetson vslam install --yes` then `mower-jetson vslam bridge-install --yes` then starts both services via direct `systemctl --user start` commands over SSH (not via the G9 `bridge-start` convenience command, which is implemented later in Phase 3). Confirmation required.

### G3: Pixhawk udev rules (new `pixhawk-udev` step)

**File:** `src/mower_rover/cli/bringup.py`

New `BringupStep` at position 3 (after `harden`):

```python
BringupStep(
    name="pixhawk-udev",
    description="Deploy Pixhawk udev rules and create runtime directories",
    check=_pixhawk_udev_done,
    execute=_run_pixhawk_udev,
    needs_confirm=True,
)
```

- **`_pixhawk_udev_done(client)`** — Check `/etc/udev/rules.d/90-pixhawk-usb.rules` exists AND `/var/lib/mower/` exists AND `/etc/mower/` exists
- **`_run_pixhawk_udev(client, bctx)`**:
  1. Push `scripts/90-pixhawk-usb.rules` to `~/90-pixhawk-usb.rules` via scp
  2. `sudo cp ~/90-pixhawk-usb.rules /etc/udev/rules.d/`
  3. `sudo udevadm control --reload-rules && sudo udevadm trigger`
  4. `sudo mkdir -p /var/lib/mower /etc/mower`
  5. `sudo chown $JETSON_USER:$JETSON_USER /var/lib/mower /etc/mower` (where `$JETSON_USER` is the SSH endpoint's configured username, not hardcoded)
  6. `mkdir -p /run/mower` (immediate availability for probe checks; `RuntimeDirectory=mower` in service units handles post-reboot lifecycle)
  7. Cleanup: `rm -f ~/90-pixhawk-usb.rules`

### G4: Runtime directories + VSLAM config (new `vslam-config` step)

**File:** `src/mower_rover/cli/bringup.py`

New `BringupStep` at position 8 (after `service`, before `vslam-services`):

```python
BringupStep(
    name="vslam-config",
    description="Push default VSLAM configuration to /etc/mower/",
    check=_vslam_config_exists,
    execute=_run_vslam_config,
    needs_confirm=False,
)
```

- **`_vslam_config_exists(client)`** — Check `/etc/mower/vslam.yaml` exists
- **`_run_vslam_config(client, bctx)`**:
  1. Extract `vslam_defaults.yaml` via `importlib.resources` from `mower_rover.config.data`
  2. Write to temp file, push via scp to `~/vslam.yaml`
  3. `sudo cp ~/vslam.yaml /etc/mower/vslam.yaml`
  4. Cleanup

### G5: RotatingFileHandler for daemon logs

**File:** `src/mower_rover/logging_setup/setup.py` — `configure_logging()` function

**Change:** Replace `logging.FileHandler` with `logging.handlers.RotatingFileHandler`:

```python
from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
```

**Log file naming change:** Current pattern creates a new file per invocation (`mower-{stamp}-{cid}.jsonl`). For daemons (long-running), this is fine — the RotatingFileHandler rotates that single file. For short CLI invocations, files are small and rotation doesn't trigger. No behavioral change for CLI commands.

**Logrotate cleanup:** Remove the `/var/log/mower-jetson/*.log` stanza from `jetson-harden.sh`'s `harden_logrotate()` or leave it as a no-op (no files will exist there). Recommend: leave the logrotate config but update the comment to note it's for future system-level log targets only.

### G6: `mower-jetson detect` command

**File:** `src/mower_rover/cli/jetson.py`

Add a new `detect` command on the Jetson app:

```python
from mower_rover.cli.detect import _collect, _render_human, DetectReport

@app.command("detect")
def detect_command(
    endpoint: str = typer.Option(
        "/dev/pixhawk",
        "--port", "--endpoint",
        help="MAVLink endpoint. Default: /dev/pixhawk (USB).",
    ),
    baud: int = typer.Option(0, help="Serial baud (0 for USB CDC)."),
    sample_seconds: float = typer.Option(3.0, help="How long to listen."),
    json: bool = typer.Option(False, "--json", help="JSON output."),
) -> None:
    """Detect connected hardware over local USB."""
    ...  # Same body as laptop detect_command but with Jetson defaults
```

### G7: `/dev/pixhawk` in VSLAM defaults

**File:** `src/mower_rover/config/data/vslam_defaults.yaml`

Change `bridge.serial_device` from `/dev/ttyACM0` to `/dev/pixhawk`.

### G8: Bridge `BindsTo` device name

**File:** `src/mower_rover/service/unit.py` — `generate_vslam_bridge_unit_file()`

Change `binds_to="dev-ttyACM0.device"` to `binds_to="dev-pixhawk.device"`. Also add `RuntimeDirectory=mower` to the bridge unit template so `/run/mower` is created automatically on every service start (survives reboots).

This requires the udev rule with `TAG+="systemd"` on the `/dev/pixhawk` symlink (already present in `90-pixhawk-usb.rules`: `SYMLINK+="pixhawk"` with `TAG+="systemd"`).

### G9: Bridge convenience CLI commands

**File:** `src/mower_rover/cli/jetson.py`

Add to existing `vslam_app` Typer sub-app:

```python
@vslam_app.command("bridge-start")
def bridge_start(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Start the VSLAM bridge service."""
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["start", f"{VSLAM_BRIDGE_UNIT_NAME}.service"])
    subprocess.run(cmd, check=True)
    typer.echo("VSLAM bridge service started.")

@vslam_app.command("bridge-stop")
def bridge_stop(
    ctx: typer.Context,
    user_level: bool | None = typer.Option(None, "--user-level/--system-level"),
) -> None:
    """Stop the VSLAM bridge service."""
    cfg = load_jetson_config()
    level = user_level if user_level is not None else cfg.service_user_level
    cmd = ["systemctl"]
    if level:
        cmd.append("--user")
    cmd.extend(["stop", f"{VSLAM_BRIDGE_UNIT_NAME}.service"])
    subprocess.run(cmd, check=True)
    typer.echo("VSLAM bridge service stopped.")
```

Follows the existing `vslam start`/`vslam stop` command pattern exactly (config-driven `user_level`, `VSLAM_BRIDGE_UNIT_NAME` constant).

### G10: Pixhawk symlink probe check

**File:** `src/mower_rover/probe/checks/vslam.py` (or new `pixhawk.py`)

```python
@register("pixhawk_symlink", severity=Severity.CRITICAL, depends_on=())
def check_pixhawk_symlink(sysroot: Path) -> tuple[bool, str]:
    """Check /dev/pixhawk symlink exists."""
    dev_pixhawk = sysroot / "dev" / "pixhawk"
    if dev_pixhawk.exists():
        return True, f"/dev/pixhawk -> {dev_pixhawk.resolve()}"
    return False, "/dev/pixhawk not found; deploy 90-pixhawk-usb.rules"
```

### Pipeline Summary (9 steps)

```
check-ssh → harden → pixhawk-udev → install-uv → install-cli → verify → service → vslam-config → vslam-services
```

`STEP_NAMES` tuple in `bringup.py` updated to include the 3 new step names.

## Dependencies

| Dependency | Type | Status | Notes |
|------------|------|--------|-------|
| Research 008 complete | Prerequisite | ✅ Complete | All 5 phases done; gap list is authoritative |
| Jetson provisioned at 192.168.4.38 | Infrastructure | ✅ Available | SSH key deployed, user `vincent` |
| Pixhawk connected via USB | Hardware | ✅ Available | `/dev/ttyACM0` confirmed |
| `uv` + Python 3.11 on Jetson | Toolchain | ✅ Installed | Via prior bringup runs |
| `rtabmap_slam_node` binary at `/usr/local/bin/` | Build artifact | ✅ Built | Via `jetson-harden.sh` step 15 |
| OAK-D Pro connected at USB 3.x | Hardware | Required for VSLAM | Not needed for MAVLink-only gaps |
| `depthai>=3.5.0` aarch64 wheel on PyPI | External | ✅ Confirmed | `manylinux_2_28_aarch64` in `uv.lock` |
| Internet on Jetson during initial install | Network | Required once | For `depthai` download; subsequent updates use cache |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `uv tool install` doesn't support `[jetson]` extras from local wheel | Medium | Critical | Fallback: use `--with sdnotify --with 'depthai>=3.5.0'` explicit flags. Test on Jetson before merging. |
| `/dev/pixhawk` symlink not created if Pixhawk not plugged in during udev deploy | Low | Medium | `pixhawk-udev` step is idempotent; udev rules persist and symlink appears on next plug. Probe check catches it. |
| `BindsTo=dev-pixhawk.device` requires systemd to track the symlink target device | Low | Medium | udev rule already has `TAG+="systemd"` on the `SUBSYSTEM=="tty"` match line which creates the device unit. Field-validate that `dev-pixhawk.device` resolves correctly. |
| `RotatingFileHandler` and structlog interaction | Low | Low | RotatingFileHandler is a drop-in for FileHandler in stdlib logging; structlog routes through stdlib. Covered by existing log tests. |
| VSLAM services fail to start if OAK-D not connected | Medium | Low | Expected behavior — systemd will retry per `Restart=on-failure`. Probe checks will report degraded. Bringup step check function tolerates services being inactive when hardware is absent. |

## Execution Plan

### Phase 1: Bringup Pipeline — Install Command Fix + New Steps

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2
**Prerequisites:** None
**Entry Point:** `src/mower_rover/cli/bringup.py`
**Verification:** `uv run pytest tests/test_bringup.py -v` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Fix `_run_install_cli()`: replace `--with sdnotify ~/{whl_name}` with `~/{whl_name}[jetson]` | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.2 | Add `_pixhawk_udev_done()` check function | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.3 | Add `_run_pixhawk_udev()` execute function | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.4 | Add `_vslam_config_exists()` check + `_run_vslam_config()` execute | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.5 | Add `_vslam_services_active()` check + `_run_vslam_services()` execute | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.6 | Update `STEP_NAMES` tuple with 3 new step names | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.7 | Update step list with 3 new `BringupStep` instances | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 1.8 | Add mock-based unit tests for 3 new steps | `tests/test_bringup.py` | ✅ Complete |

### Phase 2: Log Rotation + Config Consistency Fixes

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 4 (+ task 2.5 on existing `unit.py`)
**Prerequisites:** Phase 1 complete (for consistent `/dev/pixhawk` usage)
**Entry Point:** `src/mower_rover/logging_setup/setup.py`
**Verification:** `uv run pytest tests/test_logging.py tests/test_vslam_config.py -v` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Replace `logging.FileHandler` with `RotatingFileHandler(maxBytes=10*1024*1024, backupCount=5)` | `src/mower_rover/logging_setup/setup.py` | ✅ Complete |
| 2.2 | Update `vslam_defaults.yaml`: change `bridge.serial_device` to `/dev/pixhawk` | `src/mower_rover/config/data/vslam_defaults.yaml` | ✅ Complete |
| 2.3 | Update `generate_vslam_bridge_unit_file()`: `binds_to="dev-pixhawk.device"` | `src/mower_rover/service/unit.py` | ✅ Complete |
| 2.4 | Update unit tests for bridge service unit to expect `dev-pixhawk.device` | `tests/test_service.py` | ✅ Complete |
| 2.5 | Add `RuntimeDirectory=mower` to VSLAM and bridge unit templates | `src/mower_rover/service/unit.py` | ✅ Complete |

### Phase 3: Jetson CLI — Detect + Bridge Convenience + Probe

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 3-4
**Prerequisites:** Phase 2 complete (for `/dev/pixhawk` consistency)
**Entry Point:** `src/mower_rover/cli/jetson.py`
**Verification:** `uv run pytest tests/test_cli_jetson_smoke.py tests/test_probe.py -v` passes

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add `detect` command to `mower-jetson` app | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.2 | Add `bridge-start` command to `vslam_app` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.3 | Add `bridge-stop` command to `vslam_app` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.4 | Add `check_pixhawk_symlink` probe check | `src/mower_rover/probe/checks/vslam.py` | ✅ Complete |
| 3.5 | Add smoke tests for new commands and probe check | `tests/test_cli_jetson_smoke.py`, `tests/test_probe_vslam.py` | ✅ Complete |

## Standards

No organizational standards applicable to this plan. (pch-standards-space not available.)

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | ~7 files across bringup, service, logging, config, CLI, probe |
| New patterns introduced | 1 | All changes follow existing patterns (BringupStep, @register, Typer sub-app) |
| External dependencies | 1 | No new deps; `RotatingFileHandler` is stdlib |
| Migration complexity | 1 | No data migration; all changes are additive |
| Test coverage required | 2 | Unit tests only (mock SSH, fake sysroot); no integration/E2E |
| **Overall Complexity** | **7/25** | **Low** |

## Review Summary

**Review Date:** 2026-04-24  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.1  

### Review Metrics
- Issues Found: 6 (Critical: 1, Major: 3, Minor: 2)
- Clarifying Questions Asked: 1
- Sections Updated: G3, G8, G9, G10, Phase 1 (step 1.5), Phase 2 (tasks 2.3-2.5), Phase 3 (tasks 3.2-3.3)

### Key Improvements Made
1. Fixed G10 probe check signature from keyword-only (`*`) to positional — would have caused `TypeError` at runtime
2. Fixed G10 `depends_on=[]` to `depends_on=()` to match registry's `tuple[str, ...]` type
3. Fixed G9 bridge-start/stop to use config-driven `user_level` pattern matching existing `vslam start`/`stop` commands
4. Fixed G3 hardcoded `vincent` username to use dynamic SSH endpoint user
5. Clarified Phase 1 step 1.5 uses direct `systemctl` over SSH (not Phase 3's convenience CLI)
6. Added `RuntimeDirectory=mower` to VSLAM/bridge unit templates (Phase 2 task 2.5) for reboot-safe `/run/mower`

### Remaining Considerations
- `uv tool install` extras-from-wheel syntax needs field validation (fallback documented)
- `BindsTo=dev-pixhawk.device` needs field validation with `TAG+="systemd"` udev rule
- `RuntimeDirectory=mower` behavior when multiple services declare it (systemd deduplicates — safe)

### Sign-off
This plan has been reviewed and is **Ready for Implementation**

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-23 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-24 |
| Status | ✅ Complete |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/009-jetson-deploy-integration-gaps.md |

## Implementation Notes

### Phase 1 — Bringup Pipeline
**Completed:** 2026-04-24
**Files Modified:** `src/mower_rover/cli/bringup.py`, `tests/test_bringup.py`
**Deviations:** None

### Phase 2 — Log Rotation + Config
**Completed:** 2026-04-24
**Files Modified:** `src/mower_rover/logging_setup/setup.py`, `src/mower_rover/config/data/vslam_defaults.yaml`, `src/mower_rover/service/unit.py`, `tests/test_service.py`
**Deviations:** `runtime_directory` added as optional parameter to `generate_service_unit()` (cleaner than per-unit overrides)

### Phase 3 — Jetson CLI + Probe
**Completed:** 2026-04-24
**Files Modified:** `src/mower_rover/cli/jetson.py`, `src/mower_rover/probe/checks/vslam.py`, `tests/test_cli_jetson_smoke.py`, `tests/test_probe_vslam.py`
**Deviations:** None

### Plan Completion
**All phases completed:** 2026-04-24
**Total tasks completed:** 18
**Total files modified:** 10
**Code review:** No issues found
