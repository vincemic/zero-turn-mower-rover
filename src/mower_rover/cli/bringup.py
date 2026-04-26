"""`mower jetson bringup` — automated end-to-end Jetson provisioning.

Runs on the **laptop** (Windows or Linux). Walks through 18 steps:

 1. clear-host-key     — Remove stale SSH host key
 2. check-ssh          — SSH connectivity gate
 3. enable-linger      — Enable systemd linger
 4. harden-os          — Field hardening script
 5. reboot-and-wait    — Reboot and verify kernel params
 6. restore-binaries   — Restore C++ binary archive (if available)
 7. build-rtabmap      — Build RTAB-Map from source
 8. build-depthai      — Build depthai-core from source
 9. build-slam-node    — Build RTAB-Map SLAM node binary
10. archive-binaries   — Archive C++ build outputs
11. pixhawk-udev       — Pixhawk udev rules + runtime dirs
12. install-uv         — uv + Python 3.11
13. install-cli        — mower-jetson CLI wheel deploy
14. verify             — Remote probe verification
15. vslam-config       — Default VSLAM configuration
16. service            — mower-health.service install + start
17. vslam-services     — VSLAM + bridge systemd services
18. final-verify       — Final reboot + full probe verification
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.resources
import json as _json
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mower_rover.logging_setup.setup import get_logger
from mower_rover.transport.ssh import JetsonClient, SshError

STEP_NAMES = (
    "clear-host-key",
    "check-ssh",
    "enable-linger",
    "harden-os",
    "reboot-and-wait",
    "restore-binaries",
    "build-rtabmap",
    "build-depthai",
    "build-slam-node",
    "archive-binaries",
    "pixhawk-udev",
    "install-uv",
    "install-cli",
    "verify",
    "vslam-config",
    "service",
    "vslam-services",
    "final-verify",
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BringupStep:
    """One logical step in the bringup sequence."""

    name: str
    description: str
    check: Callable[[JetsonClient], bool]
    execute: Callable[[JetsonClient, BringupContext], None]
    needs_confirm: bool = False
    gate: bool = False


@dataclass
class BringupContext:
    """Shared state threaded through each bringup step."""

    project_root: Path
    dry_run: bool
    yes: bool
    correlation_id: str | None
    console: Console
    parallel_builds: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Walk up from this file looking for ``pyproject.toml``."""
    current = Path(__file__).resolve().parent
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    typer.echo(
        "ERROR: Could not locate pyproject.toml in any parent directory.\n"
        "Run this command from the source checkout: uv run mower jetson bringup",
        err=True,
    )
    raise typer.Exit(code=3)


def _confirm_or_skip(action: str, bctx: BringupContext) -> bool:
    """Return True if the operator confirms (or --yes); False to skip."""
    if bctx.yes:
        return True
    try:
        answer = input(f"{action} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


# ---------------------------------------------------------------------------
# Step: clear-host-key
# ---------------------------------------------------------------------------


def _clear_host_key_needed(client: JetsonClient) -> bool:
    """Return True if no host-key issue (step can be skipped).

    Returns False only when SSH fails due to a host-key mismatch.
    Other SSH errors return True so this step is skipped and the
    check-ssh gate handles them instead.
    """
    try:
        result = client.run(["echo", "ok"], timeout=30)
        if result.ok:
            return True
        # SSH returned non-zero — check stderr for host-key errors
        stderr_lower = result.stderr.lower()
        if (
            "remote host identification has changed" in stderr_lower
            or "host key verification failed" in stderr_lower
        ):
            return False
        return True  # other failure, not a host-key issue
    except SshError as exc:
        msg = str(exc).lower()
        if (
            "remote host identification has changed" in msg
            or "host key verification failed" in msg
        ):
            return False
        return True  # other SSH failure, let check-ssh handle it


def _run_clear_host_key(client: JetsonClient, bctx: BringupContext) -> None:
    host = client.endpoint.host
    bctx.console.print(f"  Removing stale host key for [bold]{host}[/bold]…")
    try:
        proc = subprocess.run(
            ["ssh-keygen", "-R", host],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        bctx.console.print(f"  [red]ssh-keygen failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if proc.returncode != 0:
        bctx.console.print(
            f"  [red]ssh-keygen -R exited {proc.returncode}:[/red] {proc.stderr.strip()}"
        )
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: check-ssh
# ---------------------------------------------------------------------------


def _check_ssh_ok(client: JetsonClient) -> bool:
    try:
        result = client.run(["echo", "ok"], timeout=30)
        return result.ok and "ok" in result.stdout
    except SshError:
        return False


def _run_check_ssh(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print(
        "  [red]SSH connectivity failed.[/red]\n"
        "  Run [bold]mower jetson setup[/bold] first to configure SSH keys and connectivity."
    )
    raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: enable-linger
# ---------------------------------------------------------------------------


def _linger_enabled(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["loginctl", "show-user", client.endpoint.user, "-p", "Linger", "--value"],
            timeout=15,
        )
        return result.ok and result.stdout.strip().lower() == "yes"
    except SshError:
        return False


def _run_enable_linger(client: JetsonClient, bctx: BringupContext) -> None:
    user = client.endpoint.user
    bctx.console.print(f"  Enabling linger for [bold]{user}[/bold]…")
    try:
        result = client.run(
            ["sudo", "loginctl", "enable-linger", user],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]enable-linger failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok:
        bctx.console.print(
            f"  [red]enable-linger exited {result.returncode}:[/red] {result.stderr.strip()}"
        )
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: harden
# ---------------------------------------------------------------------------


def _harden_done(client: JetsonClient) -> bool:
    try:
        r1 = client.run(
            ["test", "-f", "/etc/ssh/sshd_config.d/90-mower-hardening.conf"],
            timeout=10,
        )
        r2 = client.run(["systemctl", "get-default"], timeout=10)
        return r1.ok and r2.stdout.strip() == "multi-user.target"
    except SshError:
        return False


def _run_harden(client: JetsonClient, bctx: BringupContext) -> None:
    if not _confirm_or_skip("Apply field-hardening script to the Jetson?", bctx):
        bctx.console.print("  Skipped by operator.")
        return

    script = bctx.project_root / "scripts" / "jetson-harden.sh"
    if not script.exists():
        bctx.console.print(f"  [red]Script not found:[/red] {script}")
        raise typer.Exit(code=3)

    bctx.console.print("  Pushing jetson-harden.sh…")
    try:
        client.push(script, "~/jetson-harden.sh")
    except SshError as exc:
        bctx.console.print(f"  [red]Push failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    bctx.console.print("  Running sudo bash jetson-harden.sh --os-only…")
    try:
        result = client.run(
            ["sudo", "bash", "~/jetson-harden.sh", "--os-only"], timeout=300,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Hardening failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if result.stdout:
        bctx.console.print(result.stdout, highlight=False)
    if result.stderr:
        bctx.console.print(result.stderr, style="dim", highlight=False)

    if not result.ok:
        bctx.console.print(
            f"  [red]Hardening script exited {result.returncode}.[/red]"
        )
        raise typer.Exit(code=3)

    # Clean up temp file
    with contextlib.suppress(SshError):
        client.run(["rm", "-f", "~/jetson-harden.sh"], timeout=10)


# ---------------------------------------------------------------------------
# Step: reboot-and-wait
# ---------------------------------------------------------------------------


def _reboot_check(client: JetsonClient) -> bool:
    """Return True if SSH connects and /proc/cmdline has usbcore.autosuspend=-1."""
    try:
        result = client.run(["cat", "/proc/cmdline"], timeout=30)
        return result.ok and "usbcore.autosuspend=-1" in result.stdout
    except SshError:
        return False


def _run_reboot_and_wait(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Rebooting Jetson…")
    try:
        client.run(["sudo", "reboot"], timeout=10)
    except SshError:
        pass  # SSH disconnect on reboot is expected

    bctx.console.print("  Waiting for Jetson to come back (up to 180s)…")
    deadline = time.monotonic() + 180
    connected = False
    while time.monotonic() < deadline:
        time.sleep(10)
        try:
            result = client.run(["echo", "ok"], timeout=15)
            if result.ok:
                connected = True
                break
        except SshError:
            continue

    if not connected:
        bctx.console.print("  [red]Jetson did not come back after 180s.[/red]")
        raise typer.Exit(code=3)

    # Verify kernel cmdline
    try:
        result = client.run(["cat", "/proc/cmdline"], timeout=15)
    except SshError as exc:
        bctx.console.print(f"  [red]Post-reboot cmdline check failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if "usbcore.autosuspend=-1" not in result.stdout:
        bctx.console.print(
            "  [red]Kernel cmdline missing usbcore.autosuspend=-1 after reboot.[/red]"
        )
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Build step constants
# ---------------------------------------------------------------------------

RTABMAP_VERSION = "0.21.6"
DEPTHAI_VERSION = "v3.5.0"
SLAM_NODE_VERSION = "1.0.0"
VERSION_MARKER_DIR = "/usr/local/share/mower-build"
_BACKUP_DIR = Path.home() / ".local" / "share" / "mower" / "backups"


def _read_version_marker(
    client: JetsonClient, component: str,
) -> dict | None:
    """Read a version marker JSON from the Jetson, return parsed dict or None."""
    path = f"{VERSION_MARKER_DIR}/{component}.json"
    try:
        result = client.run(["cat", path], timeout=15)
        if result.ok and result.stdout.strip():
            return _json.loads(result.stdout)
    except (SshError, _json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Step: restore-binaries
# ---------------------------------------------------------------------------


def _restore_binaries_check(client: JetsonClient) -> bool:
    """True if all 3 version markers match expected versions."""
    rtabmap = _read_version_marker(client, "rtabmap")
    depthai = _read_version_marker(client, "depthai")
    slam = _read_version_marker(client, "slam_node")
    return (
        rtabmap is not None
        and rtabmap.get("version") == RTABMAP_VERSION
        and depthai is not None
        and depthai.get("version") == DEPTHAI_VERSION
        and slam is not None
        and slam.get("version") == SLAM_NODE_VERSION
    )


def _run_restore_binaries(client: JetsonClient, bctx: BringupContext) -> None:
    """Restore a binary archive from the laptop backup dir to the Jetson."""
    if not _BACKUP_DIR.is_dir():
        bctx.console.print("  No backup directory found — skipping restore.")
        return

    archives = sorted(_BACKUP_DIR.glob("mower-binaries-*.tar.gz"), reverse=True)
    if not archives:
        bctx.console.print("  No binary archive found — skipping restore.")
        return

    archive = archives[0]  # most recent
    bctx.console.print(f"  Restoring from [bold]{archive.name}[/bold]…")

    try:
        client.push(archive, f"~/{archive.name}")
    except SshError as exc:
        bctx.console.print(f"  [red]Push failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    try:
        result = client.run(
            [f"sudo tar -xzf ~/{archive.name} -C / && sudo ldconfig"],
            timeout=300,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Restore failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok:
        bctx.console.print(
            f"  [red]Restore exited {result.returncode}:[/red] {result.stderr.strip()}"
        )
        raise typer.Exit(code=3)

    # Clean up remote archive
    with contextlib.suppress(SshError):
        client.run([f"rm -f ~/{archive.name}"], timeout=10)


# ---------------------------------------------------------------------------
# Step: build-rtabmap
# ---------------------------------------------------------------------------


def _build_rtabmap_check(client: JetsonClient) -> bool:
    marker = _read_version_marker(client, "rtabmap")
    return marker is not None and marker.get("version") == RTABMAP_VERSION


def _run_build_rtabmap(
    client: JetsonClient,
    bctx: BringupContext,
    *,
    jobs: str = "$(nproc)",
) -> None:
    tag = RTABMAP_VERSION
    bctx.console.print(f"  Building RTAB-Map {tag} (this may take 30-60 min)…")

    build_cmd = (
        f"set -e"
        f" && export CCACHE_DIR=/var/lib/mower/ccache && mkdir -p $CCACHE_DIR && ccache -M 5G"
        f" && apt-get update -qq"
        f" && apt-get install -y --no-install-recommends"
        f"    cmake build-essential git ccache jq"
        f"    libopencv-dev libsqlite3-dev libpcl-dev"
        f"    libboost-all-dev libeigen3-dev libsuitesparse-dev"
        f" && (if [ -d /opt/rtabmap-src/.git ]; then"
        f"       cd /opt/rtabmap-src && git checkout {tag} 2>/dev/null || true;"
        f"     else"
        f"       rm -rf /opt/rtabmap-src"
        f"       && git clone --depth 1 --branch {tag}"
        f"         https://github.com/introlab/rtabmap.git /opt/rtabmap-src;"
        f"     fi)"
        f" && mkdir -p /opt/rtabmap-src/build && cd /opt/rtabmap-src/build"
        f" && cmake .."
        f"    -DCMAKE_BUILD_TYPE=Release"
        f"    -DCMAKE_INSTALL_PREFIX=/usr/local"
        f"    -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
        f"    -DCMAKE_C_COMPILER_LAUNCHER=ccache"
        f"    -DCMAKE_CUDA_COMPILER_LAUNCHER=ccache"
        f"    -DWITH_CUDA=ON -DWITH_QT=OFF -DWITH_PYTHON=OFF -DBUILD_EXAMPLES=OFF"
        f" && make -j{jobs}"
        f" && make install && ldconfig"
        f" && mkdir -p {VERSION_MARKER_DIR}"
        f' && echo \'{{"component":"rtabmap","version":"{tag}","built":"\'$(date -u +%Y-%m-%dT%H:%M:%SZ)\'"}}\''
        f"    | tee {VERSION_MARKER_DIR}/rtabmap.json"
    )

    try:
        result = client.run_streaming(
            [f"sudo bash -c '{build_cmd}'"],
            timeout=3600,
            on_line=lambda line: bctx.console.print(f"    {line}", highlight=False),
        )
    except SshError as exc:
        bctx.console.print(f"  [red]RTAB-Map build failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok:
        bctx.console.print(
            f"  [red]RTAB-Map build exited {result.returncode}.[/red]"
        )
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: build-depthai
# ---------------------------------------------------------------------------


def _build_depthai_check(client: JetsonClient) -> bool:
    marker = _read_version_marker(client, "depthai")
    return marker is not None and marker.get("version") == DEPTHAI_VERSION


def _run_build_depthai(
    client: JetsonClient,
    bctx: BringupContext,
    *,
    jobs: str = "$(nproc)",
) -> None:
    tag = DEPTHAI_VERSION
    bctx.console.print(f"  Building depthai-core {tag} (this may take 30-60 min)…")

    build_cmd = (
        f"set -e"
        f" && export CCACHE_DIR=/var/lib/mower/ccache && mkdir -p $CCACHE_DIR && ccache -M 5G"
        f" && apt-get install -y --no-install-recommends"
        f"    cmake build-essential git ccache jq libusb-1.0-0-dev"
        f" && (if [ -d /opt/depthai-core-src/.git ]; then"
        f"       echo Re-using existing source;"
        f"     else"
        f"       rm -rf /opt/depthai-core-src"
        f"       && git clone --depth 1 --branch {tag} --recursive"
        f"         https://github.com/luxonis/depthai-core.git /opt/depthai-core-src;"
        f"     fi)"
        f" && mkdir -p /opt/depthai-core-src/build && cd /opt/depthai-core-src/build"
        f" && cmake .."
        f"    -DCMAKE_BUILD_TYPE=Release"
        f"    -DCMAKE_INSTALL_PREFIX=/usr/local"
        f"    -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
        f"    -DCMAKE_C_COMPILER_LAUNCHER=ccache"
        f"    -DBUILD_SHARED_LIBS=ON"
        f" && make -j{jobs}"
        f" && make install && ldconfig"
        f" && mkdir -p {VERSION_MARKER_DIR}"
        f' && echo \'{{"component":"depthai","version":"{tag}","built":"\'$(date -u +%Y-%m-%dT%H:%M:%SZ)\'"}}\''
        f"    | tee {VERSION_MARKER_DIR}/depthai.json"
    )

    try:
        result = client.run_streaming(
            [f"sudo bash -c '{build_cmd}'"],
            timeout=3600,
            on_line=lambda line: bctx.console.print(f"    {line}", highlight=False),
        )
    except SshError as exc:
        bctx.console.print(f"  [red]depthai-core build failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok:
        bctx.console.print(
            f"  [red]depthai-core build exited {result.returncode}.[/red]"
        )
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: build-slam-node
# ---------------------------------------------------------------------------


def _build_slam_node_check(client: JetsonClient) -> bool:
    try:
        r = client.run(
            ["test", "-f", "/usr/local/bin/rtabmap_slam_node"],
            timeout=10,
        )
        if not r.ok:
            return False
    except SshError:
        return False
    marker = _read_version_marker(client, "slam_node")
    return marker is not None and marker.get("version") == SLAM_NODE_VERSION


def _run_build_slam_node(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Building SLAM node…")

    contrib_dir = bctx.project_root / "contrib" / "rtabmap_slam_node"
    if not contrib_dir.is_dir():
        bctx.console.print(
            f"  [red]contrib/rtabmap_slam_node not found:[/red] {contrib_dir}"
        )
        raise typer.Exit(code=3)

    # Push the source tree
    bctx.console.print("  Pushing contrib/rtabmap_slam_node…")
    try:
        client.run(["mkdir", "-p", "/tmp/rtabmap_slam_node"], timeout=10)
    except SshError:
        pass

    for f in contrib_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(contrib_dir)
            remote = f"/tmp/rtabmap_slam_node/{rel.as_posix()}"
            # Ensure remote parent dir exists
            remote_parent = str(Path(remote).parent).replace("\\", "/")
            with contextlib.suppress(SshError):
                client.run([f"mkdir -p {remote_parent}"], timeout=10)
            try:
                client.push(f, remote)
            except SshError as exc:
                bctx.console.print(f"  [red]Push failed ({rel}):[/red] {exc}")
                raise typer.Exit(code=3) from exc

    build_cmd = (
        f"set -e"
        f" && mkdir -p /tmp/rtabmap_slam_node/build"
        f" && cd /tmp/rtabmap_slam_node/build"
        f" && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local"
        f" && make -j$(nproc)"
        f" && make install"
        f" && mkdir -p {VERSION_MARKER_DIR}"
        f' && echo \'{{"component":"slam_node","version":"{SLAM_NODE_VERSION}","built":"\'$(date -u +%Y-%m-%dT%H:%M:%SZ)\'"}}\''
        f"    | tee {VERSION_MARKER_DIR}/slam_node.json"
    )

    try:
        result = client.run_streaming(
            [f"sudo bash -c '{build_cmd}'"],
            timeout=600,
            on_line=lambda line: bctx.console.print(f"    {line}", highlight=False),
        )
    except SshError as exc:
        bctx.console.print(f"  [red]SLAM node build failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok:
        bctx.console.print(
            f"  [red]SLAM node build exited {result.returncode}.[/red]"
        )
        raise typer.Exit(code=3)

    # Clean up
    with contextlib.suppress(SshError):
        client.run(["rm", "-rf", "/tmp/rtabmap_slam_node"], timeout=10)


# ---------------------------------------------------------------------------
# Step: archive-binaries
# ---------------------------------------------------------------------------


def _archive_binaries_check(client: JetsonClient) -> bool:
    today = datetime.date.today().isoformat()
    archive_name = f"mower-binaries-{today}.tar.gz"
    return (_BACKUP_DIR / archive_name).is_file()


def _run_archive_binaries(client: JetsonClient, bctx: BringupContext) -> None:
    today = datetime.date.today().isoformat()
    archive_name = f"mower-binaries-{today}.tar.gz"
    remote_archive = f"/tmp/{archive_name}"

    bctx.console.print(f"  Creating binary archive [bold]{archive_name}[/bold]…")

    tar_cmd = (
        f"tar -czf {remote_archive}"
        f" /usr/local/lib/librtabmap*"
        f" /usr/local/lib/libdepthai*"
        f" /usr/local/bin/rtabmap*"
        f" /usr/local/bin/rtabmap_slam_node"
        f" {VERSION_MARKER_DIR}/"
        f" 2>/dev/null || true"
    )

    try:
        result = client.run([tar_cmd], timeout=120)
    except SshError as exc:
        bctx.console.print(f"  [yellow]Archive creation failed (non-fatal):[/yellow] {exc}")
        return

    if not result.ok:
        bctx.console.print(
            f"  [yellow]Archive exited {result.returncode} (non-fatal).[/yellow]"
        )
        return

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    local_archive = _BACKUP_DIR / archive_name
    bctx.console.print(f"  Pulling archive to [bold]{local_archive}[/bold]…")
    try:
        client.pull(remote_archive, local_archive)
    except SshError as exc:
        bctx.console.print(f"  [yellow]Pull failed (non-fatal):[/yellow] {exc}")
        return

    # Clean up remote archive
    with contextlib.suppress(SshError):
        client.run([f"rm -f {remote_archive}"], timeout=10)


# ---------------------------------------------------------------------------
# Step: install-uv
# ---------------------------------------------------------------------------


def _uv_installed(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["~/.local/bin/uv", "--version"],
            timeout=15,
        )
        return result.ok
    except SshError:
        return False


def _run_install_uv(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Installing uv…")
    # Prefer curl, fall back to wget
    try:
        has_curl = client.run(["which", "curl"], timeout=10)
    except SshError:
        has_curl = None
    if has_curl and has_curl.ok:
        dl_cmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"
    else:
        dl_cmd = "wget -qO- https://astral.sh/uv/install.sh | sh"
    try:
        result = client.run(
            [dl_cmd],
            timeout=120,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]uv install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]uv install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    bctx.console.print("  Installing Python 3.11 via uv…")
    try:
        result = client.run(
            ["~/.local/bin/uv", "python", "install", "3.11"],
            timeout=300,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Python install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Python install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: install-cli
# ---------------------------------------------------------------------------


def _cli_installed(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["~/.local/bin/mower-jetson", "--version"],
            timeout=15,
        )
        return result.ok
    except SshError:
        return False


def _run_install_cli(client: JetsonClient, bctx: BringupContext) -> None:
    log = get_logger("bringup").bind(step="install-cli")

    bctx.console.print("  Building wheel locally…")
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            build_result = subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(tmp_dir)],
                cwd=bctx.project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            bctx.console.print(f"  [red]Wheel build failed:[/red] {exc}")
            raise typer.Exit(code=3) from exc

        if build_result.returncode != 0:
            bctx.console.print(
                f"  [red]uv build exited {build_result.returncode}:[/red]"
            )
            if build_result.stderr:
                bctx.console.print(build_result.stderr, style="dim", highlight=False)
            raise typer.Exit(code=3)

        tmp_path = Path(tmp_dir)
        whls = list(tmp_path.glob("*.whl"))
        if not whls:
            bctx.console.print("  [red]No .whl file found after build.[/red]")
            raise typer.Exit(code=3)
        whl = whls[0]
        whl_name = whl.name
        log.info("wheel_built", whl=whl_name)

        bctx.console.print(f"  Pushing {whl_name}…")
        try:
            client.push(whl, f"~/{whl_name}")
        except SshError as exc:
            bctx.console.print(f"  [red]Push failed:[/red] {exc}")
            raise typer.Exit(code=3) from exc

    bctx.console.print("  Installing mower-jetson via uv tool…")
    try:
        result = client.run(
            [
                f"~/.local/bin/uv tool install --python 3.11 --force"
                f" ~/{whl_name}[jetson]",
            ],
            timeout=300,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Tool install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Tool install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    # Clean up remote wheel
    with contextlib.suppress(SshError):
        client.run(["rm", "-f", f"~/{whl_name}"], timeout=10)


# ---------------------------------------------------------------------------
# Step: verify
# ---------------------------------------------------------------------------


def _verify_check(_client: JetsonClient) -> bool:
    return False  # always runs


def _run_verify(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Running remote probe…")
    try:
        result = client.run(
            ["~/.local/bin/mower-jetson", "probe", "--json"],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Remote probe failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    if not result.ok and not result.stdout.strip():
        bctx.console.print(
            f"  [red]Remote probe exited {result.returncode}:[/red] {result.stderr.strip()}"
        )
        raise typer.Exit(code=3)

    try:
        checks = _json.loads(result.stdout)
    except (_json.JSONDecodeError, ValueError) as exc:
        bctx.console.print(f"  [red]Remote probe returned invalid JSON:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    status_emoji = {"pass": "\u2705", "fail": "\u274c", "skip": "\u23ed\ufe0f"}
    table = Table(title="Remote Probe Results")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Detail")
    critical_fails = []
    for c in checks:
        status = c.get("status", "?")
        emoji = status_emoji.get(status, "?")
        table.add_row(
            c.get("name", "?"),
            emoji,
            c.get("severity", "?"),
            c.get("detail", ""),
        )
        if status == "fail" and c.get("severity") == "critical":
            critical_fails.append(c.get("name", "?"))
    bctx.console.print(table)

    if critical_fails:
        bctx.console.print(
            f"  [red]Critical failures:[/red] {', '.join(critical_fails)}"
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Step: service
# ---------------------------------------------------------------------------


def _service_active(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["systemctl", "--user", "is-active", "mower-health.service"],
            timeout=10,
        )
        return result.ok
    except SshError:
        return False


def _run_service(client: JetsonClient, bctx: BringupContext) -> None:
    if not _confirm_or_skip("Install and start mower-health.service?", bctx):
        bctx.console.print("  Skipped by operator.")
        return

    bctx.console.print("  Installing service…")
    try:
        result = client.run(
            [
                "~/.local/bin/mower-jetson service install --yes",
            ],
            timeout=60,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Service install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Service install exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    bctx.console.print("  Starting service…")
    try:
        result = client.run(
            [
                "~/.local/bin/mower-jetson service start",
            ],
            timeout=120,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Service start failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(f"  [red]Service start exited {result.returncode}:[/red]")
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: pixhawk-udev
# ---------------------------------------------------------------------------


def _pixhawk_udev_done(client: JetsonClient) -> bool:
    try:
        r1 = client.run(
            ["test", "-f", "/etc/udev/rules.d/90-pixhawk-usb.rules"],
            timeout=10,
        )
        r2 = client.run(["test", "-d", "/var/lib/mower"], timeout=10)
        r3 = client.run(["test", "-d", "/etc/mower"], timeout=10)
        return r1.ok and r2.ok and r3.ok
    except SshError:
        return False


def _run_pixhawk_udev(client: JetsonClient, bctx: BringupContext) -> None:
    if not _confirm_or_skip(
        "Deploy Pixhawk udev rules and create runtime directories?", bctx,
    ):
        bctx.console.print("  Skipped by operator.")
        return

    rules_file = bctx.project_root / "scripts" / "90-pixhawk-usb.rules"
    if not rules_file.exists():
        bctx.console.print(f"  [red]Rules file not found:[/red] {rules_file}")
        raise typer.Exit(code=3)

    bctx.console.print("  Pushing 90-pixhawk-usb.rules…")
    try:
        client.push(rules_file, "~/90-pixhawk-usb.rules")
    except SshError as exc:
        bctx.console.print(f"  [red]Push failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    bctx.console.print("  Installing udev rules…")
    try:
        result = client.run(
            ["sudo cp ~/90-pixhawk-usb.rules /etc/udev/rules.d/"],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]udev rules copy failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]udev rules copy exited {result.returncode}:[/red]"
        )
        raise typer.Exit(code=3)

    bctx.console.print("  Reloading udev…")
    try:
        result = client.run(
            ["sudo udevadm control --reload-rules && sudo udevadm trigger"],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]udev reload failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]udev reload exited {result.returncode}:[/red]"
        )
        raise typer.Exit(code=3)

    jetson_user = client.endpoint.user
    bctx.console.print("  Creating runtime directories…")
    try:
        result = client.run(
            [f"sudo mkdir -p /var/lib/mower /etc/mower /run/mower"
             f" && sudo chown {jetson_user}:{jetson_user} /var/lib/mower /etc/mower /run/mower"],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Directory creation failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]Directory creation exited {result.returncode}:[/red]"
        )
        raise typer.Exit(code=3)

    # Clean up temp file
    with contextlib.suppress(SshError):
        client.run(["rm", "-f", "~/90-pixhawk-usb.rules"], timeout=10)


# ---------------------------------------------------------------------------
# Step: vslam-config
# ---------------------------------------------------------------------------


def _vslam_config_exists(client: JetsonClient) -> bool:
    try:
        result = client.run(
            ["test", "-f", "/etc/mower/vslam.yaml"],
            timeout=10,
        )
        return result.ok
    except SshError:
        return False


def _run_vslam_config(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Pushing default VSLAM configuration…")
    ref = importlib.resources.files("mower_rover.config.data").joinpath(
        "vslam_defaults.yaml",
    )
    with importlib.resources.as_file(ref) as defaults_path:
        try:
            client.push(defaults_path, "~/vslam.yaml")
        except SshError as exc:
            bctx.console.print(f"  [red]Push failed:[/red] {exc}")
            raise typer.Exit(code=3) from exc

    try:
        result = client.run(
            ["sudo cp ~/vslam.yaml /etc/mower/vslam.yaml"],
            timeout=30,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Config copy failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]Config copy exited {result.returncode}:[/red]"
        )
        raise typer.Exit(code=3)

    # Clean up temp file
    with contextlib.suppress(SshError):
        client.run(["rm", "-f", "~/vslam.yaml"], timeout=10)


# ---------------------------------------------------------------------------
# Step: vslam-services
# ---------------------------------------------------------------------------


def _vslam_services_active(client: JetsonClient) -> bool:
    try:
        r1 = client.run(
            ["systemctl", "--user", "is-active", "mower-vslam.service"],
            timeout=10,
        )
        r2 = client.run(
            ["systemctl", "--user", "is-active", "mower-vslam-bridge.service"],
            timeout=10,
        )
        return r1.ok and r2.ok
    except SshError:
        return False


def _run_vslam_services(client: JetsonClient, bctx: BringupContext) -> None:
    if not _confirm_or_skip(
        "Install and start VSLAM + bridge systemd services?", bctx,
    ):
        bctx.console.print("  Skipped by operator.")
        return

    bctx.console.print("  Installing mower-vslam service…")
    try:
        result = client.run(
            ["~/.local/bin/mower-jetson vslam install --yes"],
            timeout=120,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]VSLAM install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]VSLAM install exited {result.returncode}:[/red]"
        )
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    bctx.console.print("  Installing mower-vslam-bridge service…")
    try:
        result = client.run(
            ["~/.local/bin/mower-jetson vslam bridge-install --yes"],
            timeout=120,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Bridge install failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]Bridge install exited {result.returncode}:[/red]"
        )
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)

    bctx.console.print("  Starting VSLAM services…")
    try:
        result = client.run(
            ["systemctl --user start mower-vslam.service mower-vslam-bridge.service"],
            timeout=60,
        )
    except SshError as exc:
        bctx.console.print(f"  [red]Service start failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    if not result.ok:
        bctx.console.print(
            f"  [red]Service start exited {result.returncode}:[/red]"
        )
        if result.stderr:
            bctx.console.print(result.stderr, style="dim", highlight=False)
        raise typer.Exit(code=3)


# ---------------------------------------------------------------------------
# Step: final-verify
# ---------------------------------------------------------------------------


def _final_verify_check(_client: JetsonClient) -> bool:
    return False  # always runs


def _run_final_verify(client: JetsonClient, bctx: BringupContext) -> None:
    bctx.console.print("  Final reboot…")
    try:
        client.run(["sudo", "reboot"], timeout=10)
    except SshError:
        pass  # expected disconnect

    # Poll SSH (10s intervals, 180s deadline)
    bctx.console.print("  Waiting for Jetson to come back (up to 180s)…")
    deadline = time.monotonic() + 180
    connected = False
    while time.monotonic() < deadline:
        time.sleep(10)
        try:
            result = client.run(["echo", "ok"], timeout=15)
            if result.ok:
                connected = True
                break
        except SshError:
            continue

    if not connected:
        bctx.console.print("  [red]Jetson did not come back after 180s.[/red]")
        raise typer.Exit(code=3)

    # Poll mower-jetson probe --json every 10s for up to 120s
    bctx.console.print("  Polling remote probe (up to 120s)…")
    probe_deadline = time.monotonic() + 120
    checks = None
    critical_fails: list[str] = []

    while time.monotonic() < probe_deadline:
        try:
            result = client.run(
                ["~/.local/bin/mower-jetson", "probe", "--json"],
                timeout=30,
            )
        except SshError:
            time.sleep(10)
            continue

        if not result.ok and not result.stdout.strip():
            time.sleep(10)
            continue

        try:
            checks = _json.loads(result.stdout)
        except (_json.JSONDecodeError, ValueError):
            time.sleep(10)
            continue

        critical_fails = [
            c.get("name", "?")
            for c in checks
            if c.get("status") == "fail" and c.get("severity") == "critical"
        ]
        if not critical_fails:
            break
        time.sleep(10)

    if checks is None:
        bctx.console.print("  [red]Could not get probe results after 120s.[/red]")
        raise typer.Exit(code=3)

    # Print probe table
    status_emoji = {"pass": "\u2705", "fail": "\u274c", "skip": "\u23ed\ufe0f"}
    table = Table(title="Final Verification — Remote Probe")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Detail")
    for c in checks:
        status = c.get("status", "?")
        emoji = status_emoji.get(status, "?")
        table.add_row(
            c.get("name", "?"),
            emoji,
            c.get("severity", "?"),
            c.get("detail", ""),
        )
    bctx.console.print(table)

    if critical_fails:
        bctx.console.print(
            f"  [red]Critical failures after final reboot:[/red] {', '.join(critical_fails)}"
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Step table
# ---------------------------------------------------------------------------

BRINGUP_STEPS: list[BringupStep] = [
    BringupStep(
        name="clear-host-key",
        description="Clear stale SSH host key",
        check=lambda c: _clear_host_key_needed(c),
        execute=lambda c, b: _run_clear_host_key(c, b),
    ),
    BringupStep(
        name="check-ssh",
        description="SSH connectivity",
        check=lambda c: _check_ssh_ok(c),
        execute=lambda c, b: _run_check_ssh(c, b),
        gate=True,
    ),
    BringupStep(
        name="enable-linger",
        description="Enable systemd linger",
        check=lambda c: _linger_enabled(c),
        execute=lambda c, b: _run_enable_linger(c, b),
    ),
    BringupStep(
        name="harden-os",
        description="Field hardening",
        check=lambda c: _harden_done(c),
        execute=lambda c, b: _run_harden(c, b),
        needs_confirm=True,
    ),
    BringupStep(
        name="reboot-and-wait",
        description="Reboot and verify kernel params",
        check=lambda c: _reboot_check(c),
        execute=lambda c, b: _run_reboot_and_wait(c, b),
    ),
    BringupStep(
        name="restore-binaries",
        description="Restore C++ binary archive (if available)",
        check=lambda c: _restore_binaries_check(c),
        execute=lambda c, b: _run_restore_binaries(c, b),
    ),
    BringupStep(
        name="build-rtabmap",
        description="Build RTAB-Map from source",
        check=lambda c: _build_rtabmap_check(c),
        execute=lambda c, b: _run_build_rtabmap(c, b),
    ),
    BringupStep(
        name="build-depthai",
        description="Build depthai-core from source",
        check=lambda c: _build_depthai_check(c),
        execute=lambda c, b: _run_build_depthai(c, b),
    ),
    BringupStep(
        name="build-slam-node",
        description="Build RTAB-Map SLAM node binary",
        check=lambda c: _build_slam_node_check(c),
        execute=lambda c, b: _run_build_slam_node(c, b),
    ),
    BringupStep(
        name="archive-binaries",
        description="Archive C++ build outputs",
        check=lambda c: _archive_binaries_check(c),
        execute=lambda c, b: _run_archive_binaries(c, b),
    ),
    BringupStep(
        name="pixhawk-udev",
        description="Pixhawk udev rules + runtime dirs",
        check=lambda c: _pixhawk_udev_done(c),
        execute=lambda c, b: _run_pixhawk_udev(c, b),
        needs_confirm=True,
    ),
    BringupStep(
        name="install-uv",
        description="uv + Python 3.11",
        check=lambda c: _uv_installed(c),
        execute=lambda c, b: _run_install_uv(c, b),
    ),
    BringupStep(
        name="install-cli",
        description="mower-jetson CLI",
        check=lambda c: _cli_installed(c),
        execute=lambda c, b: _run_install_cli(c, b),
    ),
    BringupStep(
        name="verify",
        description="Remote probe verification",
        check=lambda c: _verify_check(c),
        execute=lambda c, b: _run_verify(c, b),
    ),
    BringupStep(
        name="vslam-config",
        description="Default VSLAM configuration",
        check=lambda c: _vslam_config_exists(c),
        execute=lambda c, b: _run_vslam_config(c, b),
    ),
    BringupStep(
        name="service",
        description="mower-health.service",
        check=lambda c: _service_active(c),
        execute=lambda c, b: _run_service(c, b),
        needs_confirm=True,
    ),
    BringupStep(
        name="vslam-services",
        description="VSLAM + bridge systemd services",
        check=lambda c: _vslam_services_active(c),
        execute=lambda c, b: _run_vslam_services(c, b),
        needs_confirm=True,
    ),
    BringupStep(
        name="final-verify",
        description="Final reboot + probe verification",
        check=lambda c: _final_verify_check(c),
        execute=lambda c, b: _run_final_verify(c, b),
    ),
]


# ---------------------------------------------------------------------------
# Main bringup command
# ---------------------------------------------------------------------------


def bringup_command(
    ctx: typer.Context,
    step: str | None = typer.Option(
        None,
        "--step",
        help=f"Run only this step: {', '.join(STEP_NAMES)}",
    ),
    from_step: str | None = typer.Option(
        None,
        "--from-step",
        help=f"Resume from this step onward: {', '.join(STEP_NAMES)}",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Continue past non-gate step failures; gate failures still abort.",
    ),
    parallel_builds: bool = typer.Option(
        False,
        "--parallel-builds",
        help="Run independent build steps in parallel (requires Phase 3).",
    ),
    host: str | None = typer.Option(None, "--host"),
    user: str | None = typer.Option(None, "--user"),
    port: int | None = typer.Option(None, "--port"),
    key: Path | None = typer.Option(None, "--key"),
    config: Path | None = typer.Option(None, "--config"),
    strict_host_keys: str = typer.Option("accept-new", "--strict-host-keys"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
) -> None:
    """Automated end-to-end Jetson provisioning (18 steps).

    Walks through SSH check, hardening, C++ builds, uv/Python install,
    CLI deploy, VSLAM config, service setup, and final probe verification
    — skipping steps already satisfied.
    """
    from mower_rover.cli.jetson_remote import client_for, resolve_endpoint

    log = get_logger("bringup").bind(op="bringup")

    # -- mutual-exclusion / name validation --------------------------------

    if step is not None and from_step is not None:
        typer.echo(
            "ERROR: --step and --from-step are mutually exclusive.",
            err=True,
        )
        raise typer.Exit(code=2)

    if step is not None and step not in STEP_NAMES:
        typer.echo(
            f"ERROR: Unknown step '{step}'. Valid steps: {', '.join(STEP_NAMES)}",
            err=True,
        )
        raise typer.Exit(code=2)

    if from_step is not None and from_step not in STEP_NAMES:
        typer.echo(
            f"ERROR: Unknown step '{from_step}'. Valid steps: {', '.join(STEP_NAMES)}",
            err=True,
        )
        raise typer.Exit(code=2)

    dry_run = bool(ctx.obj and ctx.obj.get("dry_run"))
    project_root = _find_project_root()
    console = Console()

    bctx = BringupContext(
        project_root=project_root,
        dry_run=dry_run,
        yes=yes,
        correlation_id=ctx.obj.get("correlation_id") if ctx.obj else None,
        console=console,
        parallel_builds=parallel_builds,
    )

    endpoint = resolve_endpoint(host, user, port, key, config)
    client = client_for(ctx, endpoint, strict_host_keys)

    # -- build step list ---------------------------------------------------

    if step is not None:
        steps = [s for s in BRINGUP_STEPS if s.name == step]
    else:
        steps = list(BRINGUP_STEPS)

    # Resolve --from-step index inside the actual step list
    from_step_idx: int | None = None
    if from_step is not None:
        for idx, s in enumerate(steps):
            if s.name == from_step:
                from_step_idx = idx
                break
        if from_step_idx is None:
            typer.echo(
                f"ERROR: Step '{from_step}' is valid but not yet implemented.",
                err=True,
            )
            raise typer.Exit(code=2)

    # -- main loop ---------------------------------------------------------

    console.print("[bold]Jetson Bringup[/bold]\n")
    total = len(steps)
    failures: list[tuple[str, str]] = []

    for i, s in enumerate(steps, 1):
        # --- parallel build support ---
        if (
            bctx.parallel_builds
            and s.name == "build-rtabmap"
            and not dry_run
            and step is None
        ):
            # Find build-depthai in the remaining steps
            depthai_step = None
            depthai_idx = None
            for j, ss in enumerate(steps):
                if ss.name == "build-depthai":
                    depthai_step = ss
                    depthai_idx = j
                    break

            rtabmap_needs_run = not s.check(client)
            depthai_needs_run = depthai_step is not None and not depthai_step.check(client)

            if rtabmap_needs_run or depthai_needs_run:
                console.print(
                    f"[bold]Steps {i}/{total}:[/bold]"
                    " build-rtabmap + build-depthai (parallel, -j6)"
                )
                errors: list[tuple[str, str]] = []

                def _run_in_thread(
                    name: str,
                    run_fn: Callable[[JetsonClient, BringupContext], None],
                ) -> None:
                    try:
                        run_fn(client, bctx)
                    except (typer.Exit, SshError) as exc:
                        error_msg = (
                            str(exc) if isinstance(exc, SshError)
                            else f"exit code {getattr(exc, 'code', '?')}"
                        )
                        errors.append((name, error_msg))

                threads: list[threading.Thread] = []
                if rtabmap_needs_run:
                    t1 = threading.Thread(
                        target=_run_in_thread,
                        args=(
                            "build-rtabmap",
                            lambda c, b: _run_build_rtabmap(c, b, jobs="6"),
                        ),
                    )
                    threads.append(t1)
                if depthai_needs_run:
                    t2 = threading.Thread(
                        target=_run_in_thread,
                        args=(
                            "build-depthai",
                            lambda c, b: _run_build_depthai(c, b, jobs="6"),
                        ),
                    )
                    threads.append(t2)

                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                if errors:
                    for name, msg in errors:
                        if not continue_on_error:
                            console.print(
                                f"  [red]{name} failed: {msg}[/red]"
                            )
                            raise typer.Exit(code=3)
                        failures.append((name, msg))
                        console.print(
                            f"  [red]{name} failed (continuing): {msg}[/red]"
                        )
                else:
                    console.print("  [green]\u2714 Parallel builds done.[/green]")

                continue  # skip normal processing for this step
            # If neither needs to run, fall through to normal "already satisfied"

        # --- skip build-depthai if it was handled in parallel ---
        if (
            bctx.parallel_builds
            and s.name == "build-depthai"
            and not dry_run
            and step is None
        ):
            # Already handled by parallel block above
            rtabmap_step = next(
                (ss for ss in steps if ss.name == "build-rtabmap"), None,
            )
            if rtabmap_step is not None:
                console.print(
                    f"[bold]Step {i}/{total}:[/bold] {s.description}"
                )
                console.print(
                    "  [green]\u2714 Handled in parallel build — skipping.[/green]"
                )
                continue

        console.print(f"[bold]Step {i}/{total}:[/bold] {s.description}")

        if dry_run:
            console.print(f"  DRY RUN — would execute step '{s.name}'.")
            log.info("dry_run_step", step=s.name)
            continue

        # --from-step: skip steps before the target
        if from_step_idx is not None and (i - 1) < from_step_idx:
            console.print("  [dim]Skipping — before --from-step target.[/dim]")
            log.info("step_skipped_before_from_step", step=s.name)
            continue

        # Normal check-and-skip (unless --step forces execution)
        if step is None and s.check(client):
            console.print("  [green]\u2714 Already satisfied — skipping.[/green]")
            log.info("step_skipped", step=s.name)
            continue

        log.info("step_executing", step=s.name)
        try:
            s.execute(client, bctx)
            console.print("  [green]\u2714 Done.[/green]")
        except (typer.Exit, SshError) as exc:
            if not continue_on_error or s.gate:
                raise
            error_msg = (
                str(exc) if isinstance(exc, SshError)
                else f"exit code {getattr(exc, 'code', '?')}"
            )
            failures.append((s.name, error_msg))
            console.print("  [red]\u2718 Failed (continuing).[/red]")
            log.warning("step_failed_continue", step=s.name, error=error_msg)

    if failures:
        console.print("\n[bold red]Bringup completed with failures:[/bold red]")
        fail_table = Table(title="Failed Steps")
        fail_table.add_column("Step")
        fail_table.add_column("Error")
        for name, msg in failures:
            fail_table.add_row(name, msg)
        console.print(fail_table)
        raise typer.Exit(code=1)

    console.print("\n[bold green]Bringup complete![/bold green]")
