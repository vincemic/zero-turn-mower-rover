---
id: "002"
type: implementation-plan
title: "Jetson AGX Orin Bringup Verification & Health Tooling"
status: ✅ Complete
completed: 2026-04-22
created: 2026-04-22
updated: 2026-04-22
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-22 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-22 | pch-planner | Decision #1: scope = D (maximum — probe + health + setup + service) |
| v1.2 | 2026-04-22 | pch-planner | Decision #2: probe checks = C (named registry + severity + gating) |
| v1.3 | 2026-04-22 | pch-planner | Decision #3: thermal/power = B (single-shot + optional continuous) |
| v1.4 | 2026-04-22 | pch-planner | Decision #4: setup assistant = C (idempotent + step detection) |
| v1.5 | 2026-04-22 | pch-planner | Decision #5: service management = C (shell + watchdog + health logging) |
| v1.6 | 2026-04-22 | pch-planner | Decision #6: testing = B (mocked interfaces + fake filesystem fixtures) |
| v2.0 | 2026-04-22 | pch-planner | Holistic review + full execution plan complete |
| v2.1 | 2026-04-22 | pch-plan-reviewer | Review: reordered phases (health before probe); split disk check; clarified subprocess testing, key_path sync, fixture coexistence |

## Introduction

This plan covers CLI tooling to verify, monitor, and assist the Jetson AGX Orin bringup documented in research 002. The existing codebase provides `mower-jetson info`, `mower-jetson config show`, and laptop-side `mower jetson run/pull/info` — this plan extends that foundation with health probing, thermal/power monitoring, setup assistance, and bringup verification commands so the operator can confirm each bringup step succeeded and monitor the Jetson's field-readiness.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|---------------|--------|-----------|
| 1 | Plan scope — which bringup capabilities to include | D — Verification + Health + Setup + Systemd Service Management (Maximum) | Operator wants full automation: repeatable probe, ongoing thermal/power monitoring, guided setup from laptop, and systemd service management for the future Jetson daemon |
| 2 | Probe check granularity | C — Named check registry with severity levels and gating | Iterative bringup needs selective checks; severity levels + dependency gating prevent cascading confusion; exit codes enable scripting; pre-flight integration (D) is premature for Phase 3 |
| 3 | Thermal & power command design | B — Single-shot with optional continuous mode | Single-shot for scripts/quick checks; `--watch` for field thermal monitoring during mowing; threshold alerts (C) add complexity for marginal value; collapsing into `health` group (D) prematurely constrains CLI |
| 4 | Setup assistant workflow | C — Idempotent single command with step detection | Re-runnable after fixing issues without manual step tracking; auto-skips completed steps; produces config file as side effect; avoids wizard re-run (A), fragmented subcommands (B), or config-before-setup (D) |
| 5 | Systemd service management scope | C — Service shell + watchdog heartbeat loop + basic health logging | Full service lifecycle tooling; proven systemd integration with sd_notify/WatchdogSec/graceful shutdown/os.sync(); periodic health logging (thermal, power, disk) gives operator visibility before Phase 10 daemon |
| 6 | Testing strategy | B — Unit tests with mocked interfaces + fixture-based fake filesystem | Fake sysfs in `tmp_path` catches path construction + parsing bugs; `sysroot: Path` param enables testability; `@pytest.mark.jetson` for future on-device tests; Docker (C) adds CI complexity for marginal benefit |

## Holistic Review

### Decision Interactions

1. **Decisions #1 (max scope) + #5 (service with health logging)** create an end-to-end lifecycle: the setup assistant provisions the Jetson, probe verifies bringup, and the daemon provides ongoing health visibility. The daemon's health logging (Decision #5) reuses the same health readers from Decision #3 — no duplication, shared code path.

2. **Decisions #2 (probe registry with severity) + #6 (fake filesystem testing)** reinforce each other: the `sysroot: Path` parameter needed for testing (Decision #6) is the same injection point that makes checks composable and testable in the registry (Decision #2). The dependency gating in the registry ensures fake filesystem tests can verify skip logic.

3. **Decisions #3 (single-shot + watch) + #5 (daemon health logging)** overlap in what they measure but serve different audiences: `thermal`/`power` are interactive operator tools; the daemon logs to structlog for post-incident review. Both call the same `read_thermal_zones()`/`read_power_state()` functions, avoiding duplication.

4. **Decision #4 (idempotent setup) + #1 (max scope)** means the setup assistant's final step runs `probe` remotely, which validates all of Phase 1's checks. This creates a natural "setup → verify → monitor" workflow.

### Architectural Considerations

- **Cross-platform split is clean:** The `sysroot` parameter defaults to `/` on Linux (Jetson) and is only meaningful there. Laptop-side commands (`setup`, `health`) delegate to the Jetson over SSH — no sysfs access on Windows. The setup assistant uses platform-detected commands (`ping -n` vs `ping -c`; `type ... | ssh` vs `ssh-copy-id`).

- **`sysroot` parameter in production:** On the real Jetson, `sysroot=Path("/")` is always used. The parameter exists solely for testability. It does NOT enable "remote sysfs" — the laptop never reads Jetson sysfs directly. This is a testing seam, not a configuration option.

- **Health reader reuse across probe and daemon:** Probe checks (`thermal`, `power_mode`, `disk`) and the daemon health loop both call health readers from `mower_rover.health`. The probe checks add pass/fail logic on top; the daemon just logs the raw readings. No circular dependency — `probe.checks.*` imports `health.*`, not vice versa.

- **`sdnotify` optional dependency:** Adding `sdnotify` to `[project.optional-dependencies] jetson` means the laptop install doesn't pull it in. The daemon code does a guarded `try: import sdnotify` with a no-op fallback. This is safe for unit tests on Windows and for running `mower-jetson` commands that aren't the daemon.

- **Setup assistant password prompt (Risk R-8):** The key deployment step (step 4) is the only operation in the entire codebase that uses password authentication. It runs a direct `subprocess.run` call with password interaction, bypassing `JetsonClient` (which enforces `BatchMode=yes`). This is intentional and clearly documented — it's a bootstrap step that enables all subsequent key-only operations.

### Trade-offs Accepted

- **Max scope increases plan size (6 phases, ~45 tasks)** — Accepted because the four capability groups are well-separated by phase and can be implemented independently. If time is short, Phases 4-5 can be deferred without breaking Phases 1-3.
- **`sdnotify` is a new external dependency** — Accepted because it's 2KB, pure Python, zero transitive deps, and optional. The alternative (reimplementing sd_notify over the Unix socket) is more code for the same result.
- **Daemon health logging overlaps with interactive commands** — Accepted as intentional: interactive for real-time operator visibility, daemon logs for post-incident forensics. Same readers, different output sinks.
- **Setup assistant's key deployment uses password auth** — Accepted as a necessary bootstrap. The operator does this once; all subsequent operations are key-only.

### Risks Acknowledged

- **R-5 (user-level systemd availability)** is the most significant risk. JetPack's default Ubuntu may not enable user-level lingering (`loginctl enable-linger`). The `service install` command should detect this and either enable it (with confirmation) or fall back to system-level. The `service_user_level` config flag gives the operator control.
- **R-6 (fake sysfs fidelity)** will be validated when hardware arrives. The `@pytest.mark.jetson` marker ensures real-device tests are easy to add later.

## Overview

This plan adds four capability groups to the Jetson tooling:

1. **Bringup Verification (`mower-jetson probe`)** — single-command validation that all bringup prerequisites from research 002 are met (JetPack version, CUDA, Python, disk, SSH hardening, OAK-D Pro, thermal, power mode)
2. **Health Monitoring (`mower-jetson thermal`, `mower-jetson power`)** — ongoing field-readiness visibility with thermal sensor readout and nvpmodel/power state queries; expanded `mower-jetson info` output
3. **Setup Assistant (`mower jetson setup`)** — laptop-side guided workflow for SSH key generation, connectivity testing, config file creation, and remote verification
4. **Systemd Service Management (`mower-jetson service install/start/stop/status`)** — install, manage, and monitor the Jetson daemon as a systemd unit with watchdog support

The existing `mower-jetson info`, `mower-jetson config show`, and laptop-side `mower jetson run/pull/info` remain unchanged and serve as foundation for these additions.

## Requirements

### Functional Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| JB-1 | `mower-jetson probe` — named check registry with severity (`critical`/`warning`/`info`), dependency gating, selective `--check` execution, `--json` output, exit codes (0=pass, 1=warning, 2=critical) | Decision #2; Research 002 all phases |
| JB-2 | Probe checks: `jetpack_version` (R36.4.4), `cuda` (12.6), `python` (≥3.11), `disk` (NVMe, free space), `ssh_hardening` (password auth disabled, AllowUsers), `oakd` (USB device present), `thermal` (zones readable, no throttle), `power_mode` (nvpmodel query) | Research 002 Phases 1–5 |
| JB-3 | `mower-jetson thermal` — read all thermal zones, show die temps + throttle status; `--json`; `--watch --interval N` for continuous mode with Rich Live display | Decision #3; Research 002 Phase 5 |
| JB-4 | `mower-jetson power` — read nvpmodel mode, CPU/GPU frequencies, fan profile; `--json`; `--watch --interval N` continuous mode | Decision #3; Research 002 Phase 5 |
| JB-5 | `mower jetson setup` — idempotent laptop-side command: detect/generate SSH key, prompt for IP/user, test connectivity, deploy key, test key auth, write `laptop.yaml`, run remote probe; skip already-completed steps; `--force` to re-run all | Decision #4; Research 002 Phase 2 |
| JB-6 | `mower-jetson service install` — generate systemd unit file with `WatchdogSec=30`, `Restart=on-failure`, `RestartSec=5`, `StartLimitBurst=5`; `service uninstall` removes it | Decision #5; Research 002 Phase 5 |
| JB-7 | `mower-jetson service start/stop/status` — wrappers around `systemctl` for the mower-jetson unit | Decision #5 |
| JB-8 | `mower-jetson service run` — event loop with `sd_notify` watchdog heartbeat, `SIGTERM` graceful shutdown, periodic `os.sync()`, periodic health logging (thermal, power, disk via structlog) | Decision #5; Research 002 Phase 5 |
| JB-9 | Expanded `mower-jetson info` — add CUDA version, NVMe presence, power mode, OAK-D Pro detection to existing PlatformInfo output | Research 002 Phases 1, 4, 5 |
| JB-10 | Laptop-side `mower jetson health` — runs `mower-jetson probe` remotely over SSH; renders results locally | Mirrors existing `mower jetson info` pattern |

### Non-Functional Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| NFR-2 | Field-offline: no internet required for any probe, thermal, power, or service command | Vision NFR-2; C-10 |
| NFR-3 | Safety: service commands that modify system state (`install`, `uninstall`, `start`, `stop`) require confirmation via `@requires_confirmation`; `--dry-run` support | Vision NFR-3 |
| NFR-4 | Structured output: all commands log via structlog with correlation IDs; `--json` on all reporting commands | Vision NFR-4 |
| NFR-6 | Cross-platform: laptop-side commands run on Windows; Jetson-side commands run on aarch64 Linux; no platform-specific code without guard | Vision C-6 |
| NFR-7 | Testability: all system reads behind `sysroot: Path` parameter; fake filesystem fixtures for CI | Decision #6 |

### Out of Scope

- DepthAI SDK installation or configuration (Phase 12 / VSLAM)
- OAK-D Pro frame capture or depth pipeline (Phase 12)
- MAVLink-based monitoring or mission control (Phase 10)
- TTS / audible announcements (Phase 10)
- Jetson daemon business logic beyond health heartbeat (Phase 10)
- JetPack flashing automation (manual procedure, research 002 Phase 1)
- DC-DC converter or hardware enclosure design
- Thermal enclosure engineering
- NVMe SSD procurement / selection

## Technical Design

### Architecture

#### File Layout (new and modified files)

```
src/mower_rover/
  probe/                         # NEW — check registry and individual checks
    __init__.py                  # Public exports: CheckResult, Severity, run_checks, REGISTRY
    registry.py                  # CheckResult dataclass, Severity enum, check registry, runner
    checks/                      # Individual check implementations
      __init__.py                # Imports all check modules to trigger registration
      jetpack.py                 # jetpack_version check
      cuda.py                    # cuda check
      python_ver.py              # python check
      disk.py                    # disk check (NVMe, free space)
      ssh_hardening.py           # ssh_hardening check
      oakd.py                    # oakd check (USB device enumeration)
      thermal.py                 # thermal check (zones readable, no throttle)
      power_mode.py              # power_mode check (nvpmodel)
  health/                        # NEW — thermal and power monitoring
    __init__.py                  # Public exports
    thermal.py                   # read_thermal_zones(), ThermalReading dataclass
    power.py                     # read_power_state(), PowerState dataclass
    disk.py                      # read_disk_usage(), DiskUsage dataclass
  service/                       # NEW — systemd service management
    __init__.py                  # Public exports
    unit.py                      # generate_unit_file(), install/uninstall helpers
    daemon.py                    # event loop with sd_notify, watchdog, health logging
  cli/
    jetson.py                    # MODIFY — add probe, thermal, power commands; expand info; add service group
    jetson_remote.py             # MODIFY — add health (remote probe) command
    setup.py                     # NEW — laptop-side idempotent setup assistant
    laptop.py                    # MODIFY — wire setup command into mower CLI
  config/
    jetson.py                    # MODIFY — add service config fields (health_interval_s, etc.)
tests/
  conftest.py                    # MODIFY — add fake sysfs fixtures
  test_probe.py                  # NEW — probe registry + all check unit tests
  test_health.py                 # NEW — thermal/power/disk reader unit tests
  test_service.py                # NEW — unit file generation, daemon loop tests
  test_setup.py                  # NEW — setup assistant step detection tests
  test_cli_jetson_smoke.py       # MODIFY — add smoke tests for new commands
```

#### Probe Check Registry Design

```python
# src/mower_rover/probe/registry.py

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

class Severity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class Status(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"

@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    severity: Severity
    detail: str
    warnings: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class CheckSpec:
    name: str
    severity: Severity
    depends_on: tuple[str, ...] = ()
    fn: Callable[[Path], CheckResult]  # sysroot param for testability

# Module-level registry populated by check modules on import
_REGISTRY: dict[str, CheckSpec] = {}

def register(name: str, *, severity: Severity,
             depends_on: tuple[str, ...] = ()) -> Callable:
    """Decorator to register a probe check function."""
    def decorator(fn: Callable[[Path], CheckResult]) -> Callable:
        _REGISTRY[name] = CheckSpec(name=name, severity=severity,
                                     depends_on=depends_on, fn=fn)
        return fn
    return decorator

def run_checks(
    sysroot: Path = Path("/"),
    only: frozenset[str] | None = None,
) -> list[CheckResult]:
    """Run all (or selected) checks in dependency order.

    Skips checks whose dependencies failed.
    Returns list of CheckResult in execution order.
    """
    ...
```

**Exit code logic:**
- Exit 0: all checks pass or only `info`-severity issues
- Exit 1: at least one `warning`-severity failure, no `critical`
- Exit 2: at least one `critical`-severity failure

**Check dependency graph:**
```
jetpack_version (critical) ── no deps
  ├── cuda (critical) ── depends_on: jetpack_version
  ├── python (critical) ── depends_on: jetpack_version
  ├── oakd (warning) ── depends_on: jetpack_version
  └── power_mode (warning) ── depends_on: jetpack_version
disk_space (critical) ── no deps
disk_nvme (warning) ── no deps
ssh_hardening (warning) ── no deps
thermal (warning) ── depends_on: jetpack_version
```

#### Individual Check Specifications

| Check | Severity | Reads | Pass Criteria | Fail Detail |
|-------|----------|-------|---------------|-------------|
| `jetpack_version` | critical | `/etc/nv_tegra_release` | Contains `R36` (L4T 36.x) | "Expected L4T R36.x, found: {actual}" or "Not a Jetson (file missing)" |
| `cuda` | critical | `nvcc --version` stdout | CUDA 12.x detected | "CUDA not found" or "Expected 12.x, found: {actual}" |
| `python` | critical | `python3.11 --version` or `python3 --version` | Python ≥3.11 | "Python 3.11+ not found; install via `uv python install 3.11`" |
| `disk_space` | critical | `read_disk_usage()` | Root partition ≥2 GB free | "Free space below 2 GB: {free}" |
| `disk_nvme` | warning | `read_disk_usage()` | Root on NVMe (`nvme` in device path) | "Root not on NVMe — performance may be reduced" |
| `ssh_hardening` | warning | `/etc/ssh/sshd_config`, `/etc/ssh/sshd_config.d/*.conf` | `PasswordAuthentication no` found | "PasswordAuthentication still enabled" |
| `oakd` | warning | `lsusb` output or `/sys/bus/usb/devices/*/idVendor` | Vendor `03e7` (Movidius/Luxonis) present | "No OAK device detected (vendor 03e7)" |
| `thermal` | warning | `/sys/class/thermal/thermal_zone*/temp` | At least one zone readable; no zone >95°C | "Thermal zone read failed" or "Zone {n} at {t}°C (throttle imminent)" |
| `power_mode` | warning | `nvpmodel -q` stdout | Mode ID parseable | "nvpmodel not found or failed" |

#### Thermal & Power Readers

```python
# src/mower_rover/health/thermal.py

@dataclass(frozen=True)
class ThermalZone:
    index: int
    name: str        # e.g., "CPU-therm", "GPU-therm", "tj-therm"
    temp_c: float    # millidegrees / 1000

@dataclass(frozen=True)
class ThermalSnapshot:
    zones: list[ThermalZone]
    timestamp: str   # ISO 8601 UTC

def read_thermal_zones(sysroot: Path = Path("/")) -> ThermalSnapshot:
    """Read all /sys/class/thermal/thermal_zone*/temp and type."""
    ...
```

```python
# src/mower_rover/health/power.py

@dataclass(frozen=True)
class PowerState:
    mode_id: int | None        # nvpmodel mode number
    mode_name: str | None      # e.g., "30W", "MAXN"
    online_cpus: int | None    # count of online CPUs
    gpu_freq_mhz: int | None   # current GPU frequency
    fan_profile: str | None     # fan PWM profile name
    timestamp: str              # ISO 8601 UTC

def read_power_state(sysroot: Path = Path("/")) -> PowerState:
    """Read nvpmodel, CPU online count, GPU freq, fan profile."""
    ...
```

```python
# src/mower_rover/health/disk.py

@dataclass(frozen=True)
class DiskUsage:
    mount_point: str
    device: str
    total_gb: float
    used_gb: float
    free_gb: float
    is_nvme: bool

def read_disk_usage(sysroot: Path = Path("/")) -> list[DiskUsage]:
    """Read mount points and statvfs for key partitions."""
    ...
```

#### Systemd Service Unit Template

> 🔄 **Updated 2026-04-23 (field bringup):** The code now uses **two templates** — one for user-level units (omits `User=`) and one for system-level (includes `User=`). `StartLimitIntervalSec` / `StartLimitBurst` moved to `[Unit]`. `ExecStart` falls back to `~/.local/bin/mower-jetson` (absolute path) when `shutil.which()` fails. See `src/mower_rover/service/unit.py`.

**User-level template** (`~/.config/systemd/user/mower-health.service`):
```ini
# Generated by mower-jetson service install
[Unit]
Description=Mower Rover health monitor daemon
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=notify
ExecStart={mower_jetson_path} service run --health-interval {health_interval_s}
Environment=MOWER_CORRELATION_ID=daemon
WorkingDirectory={home_dir}
WatchdogSec=30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**System-level template** (`/etc/systemd/system/mower-health.service`) additionally includes `User={user}` and uses `WantedBy=multi-user.target`.

The `{mower_jetson_path}` is resolved via `shutil.which("mower-jetson")` at install time, falling back to `~/.local/bin/mower-jetson` (absolute path). The unit file is written to `~/.config/systemd/user/mower-health.service` (user-level systemd) or `/etc/systemd/system/mower-health.service` (system-level, requires sudo).

#### Daemon Event Loop

```python
# src/mower_rover/service/daemon.py

def run_daemon(*, health_interval_s: int = 60, sysroot: Path = Path("/")) -> None:
    """Main event loop for the Jetson daemon.

    - Sends sd_notify READY=1 on startup
    - Sends sd_notify WATCHDOG=1 every WatchdogSec/2 (15s)
    - Runs health snapshot (thermal + power + disk) every health_interval_s
    - Logs health via structlog
    - Calls os.sync() every health_interval_s
    - Handles SIGTERM for graceful shutdown
    """
    ...
```

**sd_notify integration:** Use the `sdnotify` PyPI package (pure Python, 2KB, no C deps). Add to `pyproject.toml` as an optional dependency:
```toml
[project.optional-dependencies]
jetson = ["sdnotify>=0.3"]
```

On non-systemd platforms (Windows, macOS, or when not running under systemd), `sd_notify` calls are silently no-ops.

#### Setup Assistant Steps

```python
# src/mower_rover/cli/setup.py

@dataclass
class SetupStep:
    name: str
    check: Callable[..., bool]   # Returns True if step already done
    execute: Callable[..., None]  # Performs the step
    description: str

SETUP_STEPS: list[SetupStep] = [
    # 1. SSH key exists?
    SetupStep("ssh_key", _key_exists, _generate_key,
              "Generate Ed25519 SSH key for Jetson access"),
    # 2. Jetson IP/user known? (from args, env, or existing config)
    SetupStep("endpoint", _endpoint_configured, _prompt_endpoint,
              "Configure Jetson IP address and username"),
    # 3. Ping connectivity?
    SetupStep("connectivity", _ping_ok, _report_ping_failure,
              "Test network connectivity to Jetson"),
    # 4. Key deployed?
    SetupStep("key_deployed", _key_auth_works, _deploy_key,
              "Deploy SSH public key to Jetson"),
    # 5. laptop.yaml written?
    SetupStep("config", _config_exists, _write_config,
              "Write laptop.yaml with Jetson endpoint"),
    # 6. Remote probe passes?
    SetupStep("verify", _remote_probe_ok, _run_remote_probe,
              "Verify Jetson bringup via remote probe"),
]
```

**Key deployment step (step 4):** This is the one step that requires a password — the Jetson doesn't have the key yet. The setup command will use `ssh-copy-id` (Linux) or the `type ... | ssh` equivalent (Windows) with an explicit password prompt. After this step, all subsequent SSH operations use key auth only (`BatchMode=yes`).

**`--force` flag:** Re-runs all steps regardless of detection.

#### Expanded PlatformInfo

Add fields to the existing `PlatformInfo` dataclass in `cli/jetson.py`:

```python
@dataclass
class PlatformInfo:
    # ... existing fields ...
    cuda_version: str | None = None      # NEW: from nvcc --version
    nvme_present: bool = False           # NEW: from lsblk
    power_mode: str | None = None        # NEW: from nvpmodel -q
    oakd_detected: bool = False          # NEW: from USB vendor scan
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### JetsonConfig Changes

Add new fields to `JetsonConfig` for service daemon configuration:

```python
@dataclass
class JetsonConfig:
    log_dir: Path | None = None
    oakd_required: bool = False
    # NEW fields:
    health_interval_s: int = 60      # Daemon health logging interval
    service_user_level: bool = True  # True = user systemd, False = system-level
```

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Jetson CLI Subcommands via Typer
    location: "src/mower_rover/cli/jetson.py"
    usage: New Jetson-side commands follow existing info/config pattern
  - pattern: Laptop-side Remote Commands via SSH
    location: "src/mower_rover/cli/jetson_remote.py"
    usage: New remote health commands follow run/pull/info pattern
  - pattern: SSH Transport Layer
    location: "src/mower_rover/transport/ssh.py"
    usage: JetsonClient for remote command execution
  - pattern: Jetson Config (YAML + XDG)
    location: "src/mower_rover/config/jetson.py"
    usage: JetsonConfig dataclass with oakd_required field
  - pattern: Laptop Config (YAML + Endpoint)
    location: "src/mower_rover/config/laptop.py"
    usage: JetsonEndpoint for SSH coordinates
  - pattern: PlatformInfo Dataclass
    location: "src/mower_rover/cli/jetson.py"
    usage: Structured platform data with JSON output
  - pattern: Structured Logging
    location: "src/mower_rover/logging_setup/setup.py"
    usage: get_logger() with operation binding and correlation IDs
  - pattern: Rich Console Output
    location: "src/mower_rover/cli/detect.py"
    usage: Rich tables for high-contrast terminal output
```

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| `typer` + `rich` | Python package | Installed | CLI framework + Rich Live for continuous mode |
| `structlog` | Python package | Installed | Logging with correlation IDs |
| `PyYAML` | Python package | Installed | Config I/O |
| `sdnotify` | Python package | **NEW — optional** | Pure-Python sd_notify for systemd watchdog; add to `[project.optional-dependencies] jetson` |
| Existing `JetsonClient` / `SshError` | Internal | Complete | SSH transport for laptop-side commands |
| Existing `JetsonEndpoint` / `load_laptop_config` | Internal | Complete | Config for setup assistant |
| Existing `PlatformInfo` / `_read_jetpack_release` | Internal | Complete | Foundation for expanded info |
| Existing `SafetyContext` / `@requires_confirmation` | Internal | Complete | Confirmation gate for service install/uninstall |
| Existing `configure_logging` / `get_logger` | Internal | Complete | Structured logging |
| System `ssh` / `scp` binaries | External | Available | Windows OpenSSH + Jetson sshd |
| System `ssh-keygen` binary | External | Available | SSH key generation in setup assistant |
| JetPack system tools | External | On Jetson | `nvcc`, `nvpmodel`, `tegrastats`, `lsusb`, `systemctl` |

No new heavy external dependencies are introduced. `sdnotify` is a 2KB pure-Python package with no transitive deps.

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R-1 | Thermal zone sysfs paths differ between JetPack versions or Orin module variants | Low | Medium | `sysroot` param + glob-based discovery (`thermal_zone*`) rather than hardcoded indices; fixture tests cover expected and unexpected layouts |
| R-2 | `nvpmodel -q` output format changes between JetPack releases | Low | Low | Parse defensively with regex; return `None` fields on parse failure rather than crash |
| R-3 | Setup assistant key deployment fails due to Windows SSH quirks (no `ssh-copy-id`) | Medium | Medium | Implement `type ... | ssh` fallback for Windows (documented in research Phase 2); test with mocked subprocess |
| R-4 | `sdnotify` package unavailable on aarch64 wheels | Low | Low | Pure Python, no C extension; pip installs from sdist if no wheel; fallback: silent no-op if import fails |
| R-5 | User-level systemd (`systemctl --user`) not available in all JetPack configurations | Medium | Medium | Detect with `systemctl --user status` check; fall back to system-level with `sudo` and clear guidance; `service_user_level` config flag |
| R-6 | Fake sysfs fixtures don't match real Jetson file layouts | Medium | Low | Document expected layouts from research; verify fixtures against real device when hardware arrives (`@pytest.mark.jetson`) |
| R-7 | `os.sync()` in daemon loop causes micro-stalls under heavy I/O | Low | Low | Acceptable for MVP; frequency controlled by `health_interval_s` (default 60s) |
| R-8 | Setup assistant password prompt for initial key deployment conflicts with `BatchMode=yes` | Medium | Medium | Setup uses a separate subprocess call without `BatchMode=yes` for the one-time key deployment step only; all subsequent operations use `JetsonClient` with `BatchMode=yes` |

## Execution Plan

### Phase 1: Health Monitoring (Thermal, Power, Disk Readers)

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 4 new
**Prerequisites:** None — standalone readers
**Entry Point:** `src/mower_rover/health/thermal.py` (new file)
**Verification:** `uv run pytest tests/test_health.py -v` passes; `uv run mypy src/mower_rover/health/` clean

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 1.1 | Create `src/mower_rover/health/__init__.py` with public exports | `src/mower_rover/health/__init__.py` | ✅ Complete |
| 1.2 | Create `src/mower_rover/health/thermal.py` with ThermalZone, ThermalSnapshot, read_thermal_zones | `src/mower_rover/health/thermal.py` | ✅ Complete |
| 1.3 | Create `src/mower_rover/health/power.py` with PowerState, read_power_state | `src/mower_rover/health/power.py` | ✅ Complete |
| 1.4 | Create `src/mower_rover/health/disk.py` with DiskUsage, read_disk_usage | `src/mower_rover/health/disk.py` | ✅ Complete |
| 1.5 | Create `tests/test_health.py` with fake sysfs fixtures and tests | `tests/test_health.py` | ✅ Complete |

### Phase 2: Probe Check Registry & Core Checks

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 11 new + 1 modified
**Prerequisites:** Phase 1 (health readers — probe checks `thermal`, `disk`, `power_mode` import from `mower_rover.health`)
**Entry Point:** `src/mower_rover/probe/registry.py` (new file)
**Verification:** `uv run pytest tests/test_probe.py -v` passes; `uv run mypy src/mower_rover/probe/` clean

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 2.1 | Create `src/mower_rover/probe/__init__.py` with public exports | `src/mower_rover/probe/__init__.py` | ✅ Complete |
| 2.2 | Create `src/mower_rover/probe/registry.py` with registry, enums, dataclasses, run_checks | `src/mower_rover/probe/registry.py` | ✅ Complete |
| 2.3 | Create `src/mower_rover/probe/checks/__init__.py` to trigger registration | `src/mower_rover/probe/checks/__init__.py` | ✅ Complete |
| 2.4 | Implement `jetpack_version` check | `src/mower_rover/probe/checks/jetpack.py` | ✅ Complete |
| 2.5 | Implement `cuda` check | `src/mower_rover/probe/checks/cuda.py` | ✅ Complete |
| 2.6 | Implement `python_ver` check | `src/mower_rover/probe/checks/python_ver.py` | ✅ Complete |
| 2.7 | Implement `disk_space` check | `src/mower_rover/probe/checks/disk.py` | ✅ Complete |
| 2.8 | Implement `disk_nvme` check | `src/mower_rover/probe/checks/disk.py` | ✅ Complete |
| 2.9 | Implement `ssh_hardening` check | `src/mower_rover/probe/checks/ssh_hardening.py` | ✅ Complete |
| 2.10 | Implement `oakd` check | `src/mower_rover/probe/checks/oakd.py` | ✅ Complete |
| 2.11 | Implement `thermal` check | `src/mower_rover/probe/checks/thermal.py` | ✅ Complete |
| 2.12 | Implement `power_mode` check | `src/mower_rover/probe/checks/power_mode.py` | ✅ Complete |
| 2.13 | Create `tests/test_probe.py` with all tests | `tests/test_probe.py` | ✅ Complete |

### Phase 3: Jetson CLI Commands (probe, thermal, power, expanded info)

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2 modified + 1 modified test file
**Prerequisites:** Phase 1 (health readers); Phase 2 (probe registry + checks)
**Entry Point:** `src/mower_rover/cli/jetson.py`
**Verification:** `uv run pytest tests/test_cli_jetson_smoke.py -v` passes; `mower-jetson probe --help`, `mower-jetson thermal --help`, `mower-jetson power --help` show correct signatures

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 3.1 | Add `probe` command to `cli/jetson.py` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.2 | Add `thermal` command to `cli/jetson.py` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.3 | Add `power` command to `cli/jetson.py` | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.4 | Expand `PlatformInfo` dataclass with new fields | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 3.5 | Add smoke tests for new commands | `tests/test_cli_jetson_smoke.py` | ✅ Complete |

### Phase 4: Laptop-Side Setup Assistant

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 2 new + 2 modified
**Prerequisites:** Phase 3 (remote probe via `mower-jetson probe --json` must exist for final verify step)
**Entry Point:** `src/mower_rover/cli/setup.py` (new file)
**Verification:** `uv run pytest tests/test_setup.py -v` passes; `mower jetson setup --help` shows correct signature

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 4.1 | Create `src/mower_rover/cli/setup.py` with SetupStep and SETUP_STEPS | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.2 | Implement ssh_key step | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.3 | Implement endpoint step | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.4 | Implement connectivity step | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.5 | Implement key_deployed step | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.6 | Implement config step | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.7 | Implement verify step | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.8 | Implement main setup_command | `src/mower_rover/cli/setup.py` | ✅ Complete |
| 4.9 | Wire setup_command into jetson_remote.py | `src/mower_rover/cli/jetson_remote.py` | ✅ Complete |
| 4.10 | Add `mower jetson health` command | `src/mower_rover/cli/jetson_remote.py` | ✅ Complete |
| 4.11 | Create `tests/test_setup.py` | `tests/test_setup.py` | ✅ Complete |

### Phase 5: Systemd Service Management

**Status:** ✅ Complete
**Size:** Medium
**Files to Modify:** 3 new + 2 modified
**Prerequisites:** Phase 1 (health readers for daemon health logging); Phase 3 (Jetson CLI wiring patterns)
**Entry Point:** `src/mower_rover/service/unit.py` (new file)
**Verification:** `uv run pytest tests/test_service.py -v` passes; `mower-jetson service --help` shows install/uninstall/start/stop/status/run subcommands

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 5.1 | Create `src/mower_rover/service/__init__.py` with public exports | `src/mower_rover/service/__init__.py` | ✅ Complete |
| 5.2 | Create `src/mower_rover/service/unit.py` with unit generation and install/uninstall | `src/mower_rover/service/unit.py` | ✅ Complete |
| 5.3 | Create `src/mower_rover/service/daemon.py` with event loop | `src/mower_rover/service/daemon.py` | ✅ Complete |
| 5.4 | Add `sdnotify>=0.3` to optional dependencies | `pyproject.toml` | ✅ Complete |
| 5.5 | Add `health_interval_s` and `service_user_level` to JetsonConfig | `src/mower_rover/config/jetson.py` | ✅ Complete |
| 5.6 | Add `service` command group to cli/jetson.py | `src/mower_rover/cli/jetson.py` | ✅ Complete |
| 5.7 | Create `tests/test_service.py` | `tests/test_service.py` | ✅ Complete |

### Phase 6: Integration Tests & Conftest Fixtures

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 2 modified
**Prerequisites:** Phases 1–5 complete
**Entry Point:** `tests/conftest.py`
**Verification:** `uv run pytest -v` — full test suite passes (all existing + all new tests)

| Step | Task | Files | Acceptance Criteria |
|------|------|-------|---------------------|
| 6.1 | Add shared fake sysfs fixture to conftest.py | `tests/conftest.py` | ✅ Complete |
| 6.2 | Add `@pytest.mark.jetson` marker registration | `pyproject.toml` | ✅ Complete |
| 6.3 | Run full test suite, fix integration issues | All files | ✅ Complete |

## Review Session Log

**Questions Pending:** 0  
**Questions Resolved:** 5  
**Last Updated:** 2026-04-22

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | Probe checks using subprocess for commands not behind `sysroot` | correctness | Option B: `monkeypatch`/`unittest.mock.patch` at test level | Steps 2.5, 2.6, 2.12, 2.13 AC updated |
| 2 | Probe thermal/disk/power checks duplicate health readers | correctness | Option A: Reorder — health readers (now Phase 1) before probe (now Phase 2) | Phases 1↔2 swapped; steps 2.7, 2.8, 2.11, 2.12 import from `health.*`; Phase 3/5/6 prereqs updated |
| 3 | Disk check mixed severity (CRITICAL space + WARNING NVMe) | correctness | Option B: Split into `disk_space` (CRITICAL) + `disk_nvme` (WARNING) | Dependency graph, check spec table, Phase 2 steps updated; step count 2.1–2.13 |
| 4 | Setup assistant `--key` path not synced with `JetsonEndpoint.key_path` | completeness | Option A: Write `key_path` to `JetsonEndpoint` in `laptop.yaml` | Steps 4.5, 4.6 updated to write/read `key_path` from config |
| 5 | Phase 6 shared fixture vs per-phase fixtures | specificity | Option A: Shared fixture supplements, both coexist | Step 6.1 updated to clarify coexistence |

## Standards

⚠️ Could not access organizational standards from pch-standards-space. Proceeding without standards context.

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 3 | ~20 new files + 5 modified across 4 packages |
| New patterns introduced | 2 | Check registry with decorator registration; systemd unit generation |
| External dependencies | 1 | Only `sdnotify` (optional, 2KB pure Python) |
| Migration complexity | 1 | No migrations; all additive new code |
| Test coverage required | 3 | Unit + fake filesystem + mocked subprocess across 5 test files |
| **Overall Complexity** | **10/25** | **Low** — well-separated phases; all additive; strong existing patterns to follow |

## Review Summary

**Review Date:** 2026-04-22
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.0
**Reviewed Plan Version:** v2.1

### Review Metrics
- Issues Found: 5 (Critical: 0, Major: 2, Minor: 3)
- Clarifying Questions Asked: 5
- Sections Updated: Execution Plan (Phases 1–6), Check Specifications, Dependency Graph, Review Session Log

### Key Improvements Made
1. Reordered Phase 1 (health readers) before Phase 2 (probe checks) to enforce the architectural rule that `probe.checks.*` imports `health.*` — eliminates duplication risk
2. Split `disk` check into `disk_space` (CRITICAL) + `disk_nvme` (WARNING) for clean severity model
3. Added explicit `monkeypatch` testing requirement for subprocess-based checks (`cuda`, `python_ver`, `power_mode`)
4. Setup assistant now writes `key_path` to `JetsonEndpoint` in `laptop.yaml` so all subsequent SSH commands work without manual config
5. Clarified Phase 6 shared fixture supplements (not replaces) per-phase test fixtures

### Remaining Considerations
- All codebase claims verified as accurate; no discrepancies found
- No in-flight conflicts with plan 001 (param-focused, orthogonal)
- `@pytest.mark.jetson` marker for future on-device validation when hardware arrives
- Phases 4–5 can be deferred without breaking Phases 1–3 if time is short

### Sign-off
This plan has been reviewed and is **Ready for Implementation**

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-22 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-22 |
| Implemented By | pch-coder |
| Implementation Date | 2026-04-22 |
| Status | ✅ Complete |
| Plan Location | /docs/plans/002-jetson-bringup-automation.md |

## Implementation Notes

### Plan Completion

**All phases completed:** 2026-04-22
**Total tasks completed:** 44
**Total files created:** 23
**Total files modified:** 6
**Total tests:** 175 pass, 4 skipped, 0 failures

**Code Review:** 4 unused-import findings — all fixed.

**Phase Summary:**

| Phase | Name | Status | Tasks |
|-------|------|--------|-------|
| 1 | Health Monitoring (Thermal, Power, Disk Readers) | ✅ Complete | 5/5 |
| 2 | Probe Check Registry & Core Checks | ✅ Complete | 13/13 |
| 3 | Jetson CLI Commands (probe, thermal, power, expanded info) | ✅ Complete | 5/5 |
| 4 | Laptop-Side Setup Assistant | ✅ Complete | 11/11 |
| 5 | Systemd Service Management | ✅ Complete | 7/7 |
| 6 | Integration Tests & Conftest Fixtures | ✅ Complete | 3/3 |
