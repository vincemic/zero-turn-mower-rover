---
id: "005"
type: implementation-plan
title: "Automated Jetson Bringup via SSH"
status: ✅ Complete
created: 2026-04-22
updated: 2026-04-23
completed: 2026-04-23
owner: pch-planner
version: v2.2
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-04-22 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-04-22 | pch-planner | Decisions #1-3 recorded |
| v1.2 | 2026-04-22 | pch-planner | Decisions #4-6 (all recommendations accepted) |
| v2.0 | 2026-04-22 | pch-planner | Holistic review + full execution plan complete |
| v2.1 | 2026-04-23 | pch-planner | Decision #7: fold plan 004 prerequisites into 005; close 004 |
| v2.2 | 2026-04-23 | pch-plan-reviewer | Review complete: 4 issues resolved; File Layout corrected; step 3.0 added; `resolve_endpoint`/`client_for` made public |

## Review Session Log

**Questions Pending:** 0
**Questions Resolved:** 4
**Last Updated:** 2026-04-23

| # | Issue | Category | Decision | Plan Update |
|---|-------|----------|----------|-------------|
| 1 | `_find_project_root()` won't work from installed package | correctness | Option C: Require source checkout via `uv run` | Step 3.2 updated — removed "works from installed package" AC |
| 2 | Importing private `_resolve_endpoint()` from `jetson_remote.py` | correctness | Option B: Rename to `resolve_endpoint()`, add to `__all__` | Step 3.9 updated; new step 3.0 added for rename in `jetson_remote.py` |
| 3 | Registration section header says `laptop.py` but code goes in `jetson_remote.py` | clarity | Option A: Fix header to `jetson_remote.py` | Registration section header updated |
| 4 | `service` step check needs `--user` only when `service_user_level=True` | correctness | Option A: Keep `--user` hardcoded; harmless re-run on mismatch | No plan change needed — existing design accepted |

## Introduction

This plan supersedes plan 004 (Jetson Physical Bringup & Field Hardening). It folds plan 004's manual prerequisites (JetPack flash, networking, SSH setup) into a self-contained Prerequisites section, then automates the remaining phases (hardening, Python/CLI install, verification) into a single SSH-driven command: `mower jetson bringup`. The operator runs this from the Windows laptop after completing the manual prerequisites. The already-implemented plan 002 tooling (`mower jetson setup`, `mower-jetson probe`, `mower-jetson thermal/power`, `mower-jetson service`) is consumed as verification and monitoring tools.

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|---------------|--------|-----------|
| 1 | Command structure | D — Single `mower jetson bringup` with `--step` flag | Single-operator tool; bringup runs once per flash; `--step` enables selective re-run for troubleshooting; aligns with setup wizard pattern; `push` added to JetsonClient as internal infrastructure |
| 2 | SSH hardening deployment | C — Include SSH hardening in `jetson-harden.sh` | SSH hardening is same class of system config as other hardening steps; script already runs as root; eliminates manual step from plan 004 Phase 2.5; key-auth guard before disabling passwords |
| 3 | Python/uv installation method | A — Direct SSH commands from laptop | Jetson already has internet from Phase 1 SDK install; uv install is a single `curl \| sh`; no need for bootstrap script overhead; stdout/stderr stream back for visibility; NFR-2 offline requirement applies to operational commands, not one-time bringup |
| 4 | Project transfer method | C+D — Build wheel via `uv build`, add `push()` to JetsonClient | Wheel is ~50-100KB vs hundreds of MB for full dir; `push()` mirrors existing `pull()` pattern in transport layer; needed for hardening script transfer too; `uv tool install ./file.whl` on Jetson is clean |
| 5 | Setup prerequisite | Check SSH first, direct to `mower jetson setup` if not configured | Bringup should not duplicate the setup wizard; verify key auth as step 1; clear error message if setup not done |
| 6 | Service install | Include as final optional step | Natural end-state: service running; step is skippable via `--step` if not wanted |
| 7 | Plan 004 disposition | B — Close 004, fold prerequisites into 005 | Plan 005 becomes the single bringup document; manual flash + networking procedures copied here; avoids cross-document maintenance burden |

## Holistic Review

### Decision Interactions

1. **Decisions #1 (single command + --step) + #5 (setup prerequisite):** The `check-ssh` step acts as a gate — if the operator hasn't run `mower jetson setup`, bringup fails fast with a clear message. This avoids duplicating setup logic while ensuring the prerequisite is met. The `--step` flag lets operators skip `check-ssh` if they know SSH works (e.g., re-running `--step install-cli` after fixing a wheel build issue).

2. **Decisions #2 (SSH hardening in script) + #4 (wheel transfer via push):** Both depend on `JetsonClient.push()` — the harden step pushes the `.sh` file, the install-cli step pushes the `.whl` file. This makes `push()` the critical new transport primitive and validates it gets exercised by two different steps.

3. **Decisions #3 (direct SSH for uv) + #4 (wheel for CLI):** The uv installation requires internet on the Jetson; the CLI installation does NOT (wheel is pushed from laptop). This means if the Jetson loses internet after `install-uv`, the remaining steps still work. The dependency ordering is correct: `install-uv` before `install-cli` (uv must exist to install the wheel).

4. **Decision #2 (SSH hardening in script) + R-2 (key auth broken):** This is the highest-interaction risk. The mitigation chain is: `check-ssh` verifies key auth → `harden` pushes + runs script → script's section 9 disables password auth + restarts sshd → subsequent steps (`install-uv`, `install-cli`, `verify`, `service`) implicitly verify SSH still works. If section 9 breaks SSH, the operator uses serial console to edit `/etc/ssh/sshd_config.d/90-mower-hardening.conf`.

### Architectural Considerations

- **No new CLI entry point.** The command is registered on the existing `jetson` sub-app (`mower jetson bringup`), not as a new top-level command. This follows the existing pattern where all laptop→Jetson operations live under `mower jetson`.

- **`push()` is infrastructure.** Adding `push()` to `JetsonClient` is a natural extension — the class already has `run()` and `pull()`. The three together cover all SSH operations needed for any future automation (execute, download, upload).

- **Hardening script remains the single source of truth** for system configuration. The bringup command is just a delivery mechanism — it doesn't know what the script does internally. This separation means the script can be updated independently (add new hardening steps) without changing the bringup code.

- **`sudo` handling.** R-6 identifies that `sudo bash` may prompt for a password. `JetsonClient.run()` uses `BatchMode=yes` which prevents interactive prompts. The recommended mitigation is to ensure the `mower` user has passwordless sudo (configured during initial Jetson setup). This is documented as a prerequisite rather than coded as a feature, since modifying sudoers is a one-time manual step.

### Trade-offs Accepted

- **Internet dependency in `install-uv` step:** Accepted because JetPack flash (Phase 1) already requires internet, and this is a one-time bringup operation, not an operational command. NFR-2 (field-offline) applies to mission execution, not setup.
- **No interactive sudo support:** Accepted because `BatchMode=yes` is a security feature (prevents hanging on unexpected prompts). Operator configures passwordless sudo once.
- **Wheel build on laptop:** The wheel is built on Windows but installed on aarch64 Linux. This works because mower-rover is a pure Python package with no C extensions. If native extensions are ever added, cross-compilation would be needed — but that's out of scope (NG-3, NG-5).
- **Single `.whl` file transfer vs full project:** Smaller transfer, cleaner install, but means the Jetson doesn't have the source tree. If the operator wants to develop on the Jetson, they'd need to `scp` the project separately. This is acceptable — the Jetson is a deployment target, not a development environment.

### Risks Acknowledged

- **R-2 (SSH lockout)** is the highest-impact risk. Mitigation is defense-in-depth: verify key auth first, then disable passwords. Serial console is the escape hatch.
- **R-6 (sudo password prompt)** is the most likely operational friction. Documented as a prerequisite.
- **R-7 (CRLF corruption)** is resolved as the first task in Phase 1.

## Prerequisites (Manual — from plan 004)

These manual steps must be completed before running `mower jetson bringup`. They require physical hardware access and cannot be automated over SSH.

### Prerequisite 1: JetPack Flash & First Boot

Source: Research 002 Phase 1. Requires: AGX Orin dev kit, USB-C cable, Windows laptop with SDK Manager, internet.

| Step | Task | Acceptance Criteria |
|------|------|---------------------|
| P1.1 | Download + install NVIDIA SDK Manager on Windows; install APX Driver if prompted | SDK Manager launches and logs in with NVIDIA developer account |
| P1.2 | Enter Force Recovery Mode: hold Force Recovery → press/release Power → release Force Recovery; connect USB-C (port next to 40-pin header) to laptop | SDK Manager detects "Jetson AGX Orin Developer Kit" |
| P1.3 | SDK Manager STEP 01: select Jetson AGX Orin, JetPack 6.2.2 | Correct target + version selected |
| P1.4 | SDK Manager STEP 02: review components, accept licenses | No errors |
| P1.5 | SDK Manager STEP 03: select eMMC storage target; choose Pre-Config with username=`mower`, hostname=`jetson-mower`, operator's locale/timezone | Flash begins |
| P1.6 | Wait for flash to complete (15–45 min) | SDK Manager reports flash success |
| P1.7 | Connect Jetson Ethernet to router/internet; SDK Manager STEP 03 continued: enter Jetson IP + credentials for SDK component install (CUDA, cuDNN, TensorRT) | SDK component install completes |
| P1.8 | SDK Manager STEP 04: finalize | No errors; export debug logs if needed |
| P1.9 | SSH into Jetson (via router IP or serial console) and run post-flash verification: `cat /etc/nv_tegra_release`, `cat /proc/device-tree/model`, `uname -m`, `uname -r`, `nvcc --version`, `dpkg -l \| grep nvidia-jetpack`, `python3 --version`, `lsblk` | All checks match research 002 Phase 1 §6 expected values |

### Prerequisite 2: Networking & SSH Setup

Source: Research 002 Phase 2. Requires: Ethernet cable for direct laptop↔Jetson link.

| Step | Task | Acceptance Criteria |
|------|------|---------------------|
| P2.1 | Connect Ethernet cable directly between laptop and Jetson | Physical connection |
| P2.2 | Configure Windows laptop static IP: `New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.4.1 -PrefixLength 24` | `ping 192.168.4.1` succeeds from laptop loopback |
| P2.3 | Configure Jetson static IP via nmcli: `sudo nmcli con add type ethernet con-name mower-bench ifname eth0 ipv4.addresses 192.168.4.38/24 ipv4.method manual; sudo nmcli con up mower-bench` | `ping 192.168.4.38` succeeds from laptop |
| P2.4 | Run `mower jetson setup` on the laptop. **When prompted for the Jetson host, enter `192.168.4.38`** (the wizard defaults to `10.0.0.42` which is not the bench IP). Wizard handles: SSH key generation, endpoint config, connectivity test, key deployment, laptop.yaml write, remote probe | All 6 steps report ✓; `mower jetson info` returns Jetson platform data |

### Prerequisite 3: Passwordless sudo

The `mower` user must have passwordless sudo for the hardening script to run non-interactively over SSH (`BatchMode=yes` prevents interactive password prompts).

```bash
# On the Jetson (via SSH with password auth still enabled):
echo 'mower ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/mower-nopasswd
sudo chmod 440 /etc/sudoers.d/mower-nopasswd
```

Verify: `ssh mower@192.168.4.38 sudo whoami` returns `root` without prompting.

> **Future NVMe migration:** When an M.2 2280 NVMe SSD is procured, re-flash to NVMe using research 002 Phase 1, re-run Prerequisites 2-3, then run `mower jetson bringup` again — all steps are idempotent.

## Overview

This plan replaces the manual operator steps from plan 004 (Phases 2–5) with a single automated command: `mower jetson bringup`. The operator runs this from the Windows laptop after completing Phase 1 (JetPack flash) and basic SSH setup (`mower jetson setup`). The bringup command orchestrates the full sequence over SSH:

1. **check-ssh** — Verify SSH key auth works (prerequisite gate)
2. **harden** — Push `scripts/jetson-harden.sh` → Jetson, execute via `sudo bash` (now includes SSH hardening)
3. **install-uv** — Install uv + Python 3.11 on Jetson via remote commands
4. **install-cli** — Build wheel locally (`uv build`), push `.whl` to Jetson, install via `uv tool install`
5. **verify** — Run `mower-jetson probe --json` remotely, report results
6. **service** — Install + start the systemd health monitoring service

Each step is idempotent and can be selectively re-run via `--step <name>`. The command follows the existing setup wizard pattern: check if already done → skip or execute → report status.

**Key infrastructure additions:**
- `JetsonClient.push()` method (laptop → Jetson file transfer, mirrors existing `pull()`)
- SSH hardening section added to `scripts/jetson-harden.sh`
- `.gitattributes` for LF line ending enforcement (completes plan 004 step 3.0a)

## Requirements

### Functional Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| AB-1 | `mower jetson bringup` command orchestrates full Jetson setup over SSH from laptop | Plan 004 Phases 2-5; user request |
| AB-2 | `--step` flag allows selective re-run of individual steps (`check-ssh`, `harden`, `install-uv`, `install-cli`, `verify`, `service`) | Decision #1 |
| AB-3 | `check-ssh` step verifies key-based SSH auth works; exits with clear message directing to `mower jetson setup` if not | Decision #5 |
| AB-4 | `harden` step pushes `scripts/jetson-harden.sh` to Jetson and executes via `sudo bash` | Plan 004 Phase 3 |
| AB-5 | SSH hardening drop-in config (`90-mower-hardening.conf`) is created by `jetson-harden.sh` section 9 | Decision #2; Plan 004 PB-4 |
| AB-6 | `install-uv` step installs uv + Python 3.11 on Jetson via SSH commands | Decision #3; Plan 004 Phase 4 |
| AB-7 | `install-cli` step builds a wheel locally via `uv build`, pushes `.whl` to Jetson, installs via `uv tool install` | Decision #4 |
| AB-8 | `verify` step runs `mower-jetson probe --json` on Jetson via SSH and reports results | Plan 004 Phase 5 |
| AB-9 | `service` step installs + starts the systemd health monitoring service on Jetson via SSH | Decision #6; Plan 004 PB-18 |
| AB-10 | `JetsonClient.push()` method enables laptop → Jetson file transfer via `scp` | Decision #4 |
| AB-11 | Each step is idempotent: checks if already done and skips unless `--step` forces re-run | NFR-7 from plan 004 |
| AB-12 | All steps support `--dry-run` (prints what would happen without executing) | Vision NFR; copilot instructions |
| AB-13 | `.gitattributes` created with `*.sh text eol=lf` to prevent CRLF corruption | Plan 004 R-9, step 3.0a |

### Non-Functional Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| NFR-1 | Cross-platform: bringup runs on Windows laptop, targets aarch64 Jetson | Vision C-6 |
| NFR-2 | Structured logging: each step logs inputs, remote responses, and outcome with correlation IDs | Vision NFR-4 |
| NFR-3 | Confirmation prompt before destructive steps (hardening, service install) unless `--yes` | Copilot instructions: safety primitive |
| NFR-4 | Internet required on Jetson for `install-uv` step only; other steps work offline | Vision NFR-2 (field-offline for operational commands) |
| NFR-5 | Remote command stdout/stderr streamed to laptop console for operator visibility | Vision NFR-4 (structured output) |

### Out of Scope

- JetPack flash (Phase 1 — requires physical USB-C connection, SDK Manager)
- Initial SSH setup (`mower jetson setup` — already exists, prerequisite for bringup)
- Jetson static IP / networking configuration (physical/manual — plan 004 Phase 2 steps 2.1–2.3)
- DepthAI SDK installation (Phase 12)
- MAVLink integration (Phase 10)
- Auto-power-on configuration (deferred in plan 004)
- NVMe migration (future, when SSD procured)

## Technical Design

### Architecture

#### File Layout

```
.gitattributes                           # NEW — LF enforcement for shell scripts
scripts/
  jetson-harden.sh                       # MODIFIED — add section 9: SSH hardening
src/mower_rover/
  transport/
    ssh.py                               # MODIFIED — add push() + build_scp_push_argv()
  cli/
    bringup.py                           # NEW — mower jetson bringup command
    jetson_remote.py                     # MODIFIED — publish resolve_endpoint/client_for; register bringup
tests/
  test_bringup.py                        # NEW — bringup command tests
  test_transport_ssh.py                  # MODIFIED — add push() tests
```

#### Transport Layer: `push()` Method

Add to `JetsonClient` in `src/mower_rover/transport/ssh.py`, mirroring the existing `pull()`:

```python
def build_scp_push_argv(self, local_path: Path, remote_path: str) -> list[str]:
    """Build argv for scp laptop → Jetson."""
    if self._scp is None:
        raise SshError("`scp` binary not found on PATH; install the OpenSSH client.")
    argv: list[str] = [self._scp, *self._common_opts(), "-P", str(self.endpoint.port)]
    target = f"{self.endpoint.user}@{self.endpoint.host}:{remote_path}"
    argv += [str(local_path), target]
    return argv

def push(
    self,
    local_path: Path,
    remote_path: str,
    *,
    timeout: float | None = 600.0,
) -> SshResult:
    """Copy local_path from laptop to remote_path on Jetson."""
    argv = self.build_scp_push_argv(local_path, remote_path)
    env = self._build_env(None)
    self._log.info("scp_push_start", local=str(local_path), remote=remote_path)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise SshError(f"scp push timed out after {timeout}s: {local_path}") from exc
    result = SshResult(
        argv=argv,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    self._log.info("scp_push_done", returncode=result.returncode)
    if not result.ok:
        raise SshError(
            f"scp push failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result
```

#### Bringup Command: `src/mower_rover/cli/bringup.py`

New module implementing the `mower jetson bringup` command. Follows the setup wizard step pattern from `setup.py`.

**Command signature:**

```python
STEP_NAMES = ("check-ssh", "harden", "install-uv", "install-cli", "verify", "service")

def bringup_command(
    ctx: typer.Context,
    step: str | None = typer.Option(
        None, "--step",
        help=f"Run only this step: {', '.join(STEP_NAMES)}",
    ),
    host: str | None = typer.Option(None, "--host"),
    user: str | None = typer.Option(None, "--user"),
    port: int | None = typer.Option(None, "--port"),
    key: Path | None = typer.Option(None, "--key"),
    config: Path | None = typer.Option(None, "--config"),
    strict_host_keys: str = typer.Option("accept-new", "--strict-host-keys"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
) -> None:
```

**Step data model:**

```python
@dataclass(frozen=True)
class BringupStep:
    name: str
    description: str
    check: Callable[[JetsonClient], bool]       # True if already done
    execute: Callable[[JetsonClient, BringupContext], None]
    needs_confirm: bool = False                   # Requires --yes or prompt
```

**BringupContext** carries shared state:

```python
@dataclass
class BringupContext:
    project_root: Path          # Detected from pyproject.toml location
    dry_run: bool
    yes: bool
    correlation_id: str | None
    console: Console
```

**Step implementations:**

| Step | Check (skip if true) | Execute | Confirm? |
|------|---------------------|---------|----------|
| `check-ssh` | `client.run(["true"])` returns ok | Print error directing to `mower jetson setup`; `typer.Exit(3)` | No |
| `harden` | `client.run(["test", "-f", "/etc/ssh/sshd_config.d/90-mower-hardening.conf"])` ok AND `client.run(["systemctl", "get-default"])` stdout = `multi-user.target` | Push `scripts/jetson-harden.sh` via `client.push()`, run `sudo bash ~/jetson-harden.sh`, remove temp file | Yes |
| `install-uv` | `client.run(["bash", "-c", ". ~/.local/bin/env 2>/dev/null; uv --version"])` ok | Run `curl -LsSf https://astral.sh/uv/install.sh \| sh`, then `. ~/.local/bin/env && uv python install 3.11` | No |
| `install-cli` | `client.run(["bash", "-c", ". ~/.local/bin/env 2>/dev/null; mower-jetson --version"])` ok | Run `uv build --wheel` locally, find `.whl` in `dist/`, push via `client.push()`, run `uv tool install --python 3.11 --force --with sdnotify ~/mower_rover-*.whl`, clean up | No |
| `verify` | Never skips (read-only) | Run `mower-jetson probe --json`, parse JSON, print results table, exit non-zero if critical failures | No |
| `service` | `client.run(["systemctl", "--user", "is-active", "mower-health.service"])` ok | Run `mower-jetson service install --yes`, then `mower-jetson service start` (no `--yes` — `start` has no confirmation flag) | Yes |

**Remote command execution pattern:**
All remote commands use `client.run()`. For commands that need the uv-managed PATH:
```python
client.run(["bash", "-c", ". ~/.local/bin/env && <command>"], timeout=<appropriate>)
```

**Local wheel build:**
```python
import subprocess
result = subprocess.run(
    ["uv", "build", "--wheel", "--out-dir", str(tmp_dir)],
    cwd=project_root,
    capture_output=True, text=True, timeout=120,
)
# Find the .whl file in tmp_dir
whl = next(tmp_dir.glob("*.whl"))
```

**Progress output:**
Uses Rich Console matching the setup wizard pattern:
```
[bold]Jetson Bringup[/bold]

[bold]Step 1/6:[/bold] SSH connectivity
  [green]✔ Already satisfied — skipping.[/green]
[bold]Step 2/6:[/bold] Field hardening
  Pushing jetson-harden.sh...
  Running sudo bash jetson-harden.sh...
  [green]✔ Done.[/green]
...
```

#### SSH Hardening in `jetson-harden.sh`

Add as section 9 (before summary), following the existing pattern. The script's main function counter changes from `[N/8]` to `[N/9]`.

```bash
# ---------------------------------------------------------------------------
# 9. SSH hardening — drop-in config for sshd
# ---------------------------------------------------------------------------
harden_ssh() {
    local conf="/etc/ssh/sshd_config.d/90-mower-hardening.conf"
    local desired
    desired=$(cat <<'SSHEOF'
# Mower rover SSH hardening — managed by jetson-harden.sh
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers mower
X11Forwarding no
AllowTcpForwarding no
ClientAliveInterval 60
ClientAliveCountMax 5
AcceptEnv MOWER_CORRELATION_ID
SSHEOF
)

    if [[ -f "$conf" ]] && diff -q <(echo "$desired") "$conf" &>/dev/null; then
        STATUS[ssh_hardening]="already"
        return
    fi

    echo "$desired" > "$conf"
    chmod 644 "$conf"
    systemctl restart sshd
    STATUS[ssh_hardening]="applied"
}
```

The summary section adds:
```bash
"ssh_hardening:SSH hardening (sshd drop-in)"
```

**Safety note:** The bringup command's `check-ssh` step already verified key auth works before `harden` runs. After `harden` completes (which restarts sshd with password auth disabled), the subsequent steps (`install-uv`, `install-cli`, etc.) implicitly verify that SSH still works with key auth only.

#### Registration in `jetson_remote.py`

Add the bringup command to the existing `jetson` sub-app:

```python
# In src/mower_rover/cli/jetson_remote.py — alongside existing setup/health registrations
from mower_rover.cli.bringup import bringup_command
# The bringup command is added to the jetson sub-app
app.command("bringup")(bringup_command)
```

The command is registered on the `jetson` sub-app so it's invoked as `mower jetson bringup`.

#### `.gitattributes`

```
# Enforce LF line endings for shell scripts — prevents CRLF corruption on Windows checkout
*.sh text eol=lf
```

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: SSH Transport Layer
    location: "src/mower_rover/transport/ssh.py"
    usage: Extend JetsonClient with push() for laptop→Jetson file transfer
  - pattern: Jetson Remote CLI Commands
    location: "src/mower_rover/cli/jetson_remote.py"
    usage: New bringup command follows existing remote command patterns
  - pattern: Setup Wizard Steps
    location: "src/mower_rover/cli/setup.py"
    usage: Reuse setup step logic (key gen, endpoint config, key deploy) in bringup flow
  - pattern: Laptop CLI App Registration
    location: "src/mower_rover/cli/laptop.py"
    usage: Register new commands/subcommands via app.add_typer or app.command
  - pattern: Safety Confirmation
    location: "src/mower_rover/safety/confirm.py"
    usage: Destructive/actuator-touching steps require confirmation + --dry-run
  - pattern: Probe Check Registry
    location: "src/mower_rover/probe/registry.py"
    usage: Remote probe verification via existing probe system
```

## Dependencies

| Dependency | Type | Status | Notes |
|-----------|------|--------|-------|
| `mower jetson setup` (plan 002) | Internal tool | ✅ Complete | Must be run before bringup; provides SSH key + endpoint config |
| `JetsonClient` transport layer (plan 002) | Internal code | ✅ Complete | Extended with `push()` in this plan |
| `scripts/jetson-harden.sh` (plan 004) | Internal script | ✅ Complete | Extended with SSH hardening section in this plan |
| `mower-jetson probe` (plan 002) | Internal tool | ✅ Complete | Used by `verify` step |
| `mower-jetson service` (plan 002) | Internal tool | ✅ Complete | Used by `service` step |
| `uv` on laptop | External tool | Required | For `uv build --wheel`; already a project dependency for development |
| `scp` on laptop | System tool | Required | Part of OpenSSH Client; Windows 10+ built-in |
| `ssh` on laptop | System tool | Required | Part of OpenSSH Client; already used by existing commands |
| Internet on Jetson | Infrastructure | Required | Only for `install-uv` step (curl uv installer) |
| JetPack flash complete | Prerequisite | Manual | Plan 004 Phase 1 — SDK Manager on Windows |
| Jetson static IP configured | Prerequisite | Manual | Plan 004 Phase 2 steps 2.1–2.3 — operator configures networking |

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R-1 | SSH connection drops mid-hardening-script | Low | Medium | Script is idempotent — re-run `mower jetson bringup --step harden` to resume; `set -euo pipefail` ensures no partial state on failure |
| R-2 | Key auth broken after SSH hardening disables password auth | Low | High | `check-ssh` step verifies key auth works BEFORE `harden` runs; if key auth somehow fails post-hardening, operator can use serial console to fix sshd config |
| R-3 | `uv build --wheel` fails on laptop | Low | Low | Operator can debug locally; `uv build` is standard Python packaging |
| R-4 | uv installer URL changes or is unreachable | Low | Medium | The `install-uv` step uses the official `https://astral.sh/uv/install.sh`; if unreachable, operator can install uv manually and re-run `--step install-cli` |
| R-5 | Wheel filename glob doesn't match on Jetson | Low | Low | Use `uv tool install --force ~/mower_rover-*.whl`; cleanup removes stale wheels before push |
| R-6 | `sudo bash` requires password interactively | Medium | Medium | First-run after setup may prompt for sudo password; `JetsonClient.run()` doesn't handle interactive input. Mitigation: operator adds `mower ALL=(ALL) NOPASSWD: ALL` to sudoers during initial setup, OR the bringup step documents this requirement |
| R-7 | Shell script CRLF corruption (plan 004 R-9) | High | High | `.gitattributes` with `*.sh text eol=lf` is created as first task in this plan |
| R-8 | `uv tool install` path not in remote shell PATH | Medium | Low | All remote commands sourcing uv use `bash -c ". ~/.local/bin/env && ..."` to ensure PATH includes uv-managed tools |

## Execution Plan

### Phase 1: Transport Layer — `push()` + `.gitattributes`

**Status:** ✅ Complete
**Completed:** 2026-04-23
**Size:** Small
**Files to Modify:** 3 (1 new, 2 modified)
**Prerequisites:** None
**Entry Point:** `src/mower_rover/transport/ssh.py`
**Verification:** `uv run pytest tests/test_transport_ssh.py -v` passes — 13/13

| Step | Task | Files | Status |
|------|------|-------|--------|
| 1.1 | Create `.gitattributes` at repo root with `*.sh text eol=lf` | `.gitattributes` (new) | ✅ Complete |
| 1.2 | Add `build_scp_push_argv()` to `JetsonClient` | `src/mower_rover/transport/ssh.py` | ✅ Complete |
| 1.3 | Add `push()` to `JetsonClient` | `src/mower_rover/transport/ssh.py` | ✅ Complete |
| 1.4 | Add tests for `push()` and `build_scp_push_argv()` | `tests/test_transport_ssh.py` | ✅ Complete |

**Implementation Notes:** Added `build_scp_push_argv()` and `push()` mirroring existing pull patterns. 5 new tests added (argv construction, missing-scp error, push success/failure/timeout). All 13 tests pass.

### Phase 2: SSH Hardening in `jetson-harden.sh`

**Status:** ✅ Complete
**Completed:** 2026-04-23
**Size:** Small
**Files to Modify:** 1
**Prerequisites:** Phase 1 complete (`.gitattributes` exists)
**Entry Point:** `scripts/jetson-harden.sh`
**Verification:** `bash -n scripts/jetson-harden.sh` passes; 9 sections confirmed

| Step | Task | Files | Status |
|------|------|-------|--------|
| 2.1 | Add `harden_ssh()` function as section 9 | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.2 | Update `print_summary()` labels array with SSH hardening entry | `scripts/jetson-harden.sh` | ✅ Complete |
| 2.3 | Update `main()` counters from [N/8] to [N/9]; add [9/9] SSH hardening call | `scripts/jetson-harden.sh` | ✅ Complete |

**Implementation Notes:** harden_ssh() follows existing heredoc+diff idempotency pattern. Writes /etc/ssh/sshd_config.d/90-mower-hardening.conf with chmod 644, restarts sshd only on change. LF line endings preserved.

### Phase 3: Bringup Command Module

**Status:** ✅ Complete
**Completed:** 2026-04-23
**Size:** Medium
**Files to Modify:** 3 (1 new, 2 modified)
**Prerequisites:** Phase 1 + 2 complete
**Entry Point:** `src/mower_rover/cli/bringup.py` (new)
**Verification:** `mower jetson bringup --help` shows all options; ruff/mypy clean; existing tests pass

| Step | Task | Files | Status |
|------|------|-------|--------|
| 3.0 | Rename `_resolve_endpoint`/`_client_for` to public; update `__all__` and call sites | `src/mower_rover/cli/jetson_remote.py`, `src/mower_rover/cli/setup.py` | ✅ Complete |
| 3.1 | Create bringup.py with imports, constants, data models | `src/mower_rover/cli/bringup.py` (new) | ✅ Complete |
| 3.2 | Implement `_find_project_root()` helper | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.3 | Implement check-ssh step functions | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.4 | Implement harden step functions | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.5 | Implement install-uv step functions | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.6 | Implement install-cli step functions | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.7 | Implement verify step functions | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.8 | Implement service step functions | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.9 | Assemble BRINGUP_STEPS + bringup_command() | `src/mower_rover/cli/bringup.py` | ✅ Complete |
| 3.10 | Register bringup_command in jetson sub-app | `src/mower_rover/cli/jetson_remote.py` | ✅ Complete |

**Implementation Notes:** All 6 bringup steps implemented following setup.py wizard pattern. Ruff lint findings (UP037, SIM105×2, SIM108, F541) fixed during implementation. setup.py updated for renamed resolve_endpoint/client_for imports.

### Phase 4: Tests

**Status:** ✅ Complete
**Completed:** 2026-04-23
**Size:** Small
**Files to Modify:** 1 new
**Prerequisites:** Phase 3 complete
**Entry Point:** `tests/test_bringup.py` (new)
**Verification:** `uv run pytest tests/test_bringup.py tests/test_transport_ssh.py -v` all pass; full suite 208 passed, 4 skipped

| Step | Task | Files | Status |
|------|------|-------|--------|
| 4.1 | CLI smoke tests (--help, --step validation, --dry-run) | `tests/test_bringup.py` (new) | ✅ Complete |
| 4.2 | Unit tests for all check functions with mocked JetsonClient | `tests/test_bringup.py` | ✅ Complete |
| 4.3 | Unit test for `_run_install_cli` with mocked subprocess/push | `tests/test_bringup.py` | ✅ Complete |
| 4.4 | Unit test for `_run_harden` with mocked push/run | `tests/test_bringup.py` | ✅ Complete |
| 4.5 | Full test suite verification — no regressions | — | ✅ Complete |

**Implementation Notes:** 28 tests across 8 test classes. Used `click.exceptions.Exit` for direct function-call tests (typer.Exit raises click.exceptions.Exit outside CliRunner). All check functions tested for True/False/SshError paths.

## Standards

⚠️ Could not access organizational standards from pch-standards-space. Proceeding without standards context.

No organizational standards applicable to this plan.

## Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 2 new files (`bringup.py`, `.gitattributes`, `test_bringup.py`), 3 modified (`ssh.py`, `jetson-harden.sh`, `jetson_remote.py`, `test_transport_ssh.py`) |
| New patterns introduced | 1 | Follows existing setup wizard step pattern; `push()` mirrors `pull()` |
| External dependencies | 1 | No new dependencies; uses existing `scp`, `ssh`, `uv`, `subprocess` |
| Migration complexity | 1 | No data migration; no breaking changes to existing commands |
| Test coverage required | 2 | Mock-based unit tests for step checks + execute functions; no SITL needed |
| **Overall Complexity** | **7/25** | **Low** — extends existing patterns with one new module + transport method |

## Review Summary

**Review Date:** 2026-04-23
**Reviewer:** pch-plan-reviewer
**Original Plan Version:** v2.1
**Reviewed Plan Version:** v2.2

### Review Metrics
- Issues Found: 4 (Critical: 0, Major: 2, Minor: 2)
- Clarifying Questions Asked: 4
- Sections Updated: Step 3.2 (project root AC), Step 3.9 (endpoint resolution), Step 3.0 (new — rename private functions), File Layout (laptop.py → jetson_remote.py), Registration section header

### Key Improvements Made
1. Fixed contradictory acceptance criterion in step 3.2 — `_find_project_root()` now correctly documented as requiring source checkout (won't work from installed package)
2. Added step 3.0 to make `_resolve_endpoint` and `_client_for` public in `jetson_remote.py` — eliminates cross-module private function import
3. Corrected File Layout and Registration section header from `laptop.py` to `jetson_remote.py` — matching actual codebase registration pattern
4. Verified all codebase claims: file paths, method signatures, patterns, dataclass shapes, test patterns, script structure all confirmed accurate

### Remaining Considerations
- The `service` step's `systemctl --user` check will cause a harmless re-run if the operator has configured system-level service (non-default). Accepted trade-off for simplicity.
- Step 3.2's `_find_project_root()` requires `uv run` from the source checkout. If the operator installs the package globally, they must still run bringup from the source tree.

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-04-22 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-04-23 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/005-automated-jetson-bringup-ssh.md |
| Phases | 4 |
| Total Tasks | 19 |
