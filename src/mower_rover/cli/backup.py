"""`mower jetson backup` — pull key config files and optionally binary archives."""

from __future__ import annotations

from pathlib import Path

import typer

from mower_rover.logging_setup.setup import get_logger
from mower_rover.transport.ssh import SshError

_REMOTE_CONFIG_FILES = (
    "/etc/mower/vslam.yaml",
    "/etc/ssh/sshd_config.d/90-mower-hardening.conf",
    "/usr/local/share/mower-build/rtabmap.json",
    "/usr/local/share/mower-build/depthai.json",
    "/usr/local/share/mower-build/slam_node.json",
)


def backup_command(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="Jetson hostname or IP."),
    user: str | None = typer.Option(None, "--user", help="SSH username on the Jetson."),
    port: int | None = typer.Option(None, "--port", help="SSH port (default 22)."),
    key: Path | None = typer.Option(None, "--key", help="Path to SSH private key."),
    config: Path | None = typer.Option(
        None, "--config", help="Override laptop YAML config path."
    ),
    strict_host_keys: str = typer.Option(
        "accept-new", "--strict-host-keys", help="OpenSSH StrictHostKeyChecking policy."
    ),
    output_dir: Path = typer.Option(
        "./backups", "--output-dir", "-o", help="Local directory to save backups."
    ),
    include_binaries: bool = typer.Option(
        False, "--include-binaries", help="Also pull the binary archive from the Jetson."
    ),
) -> None:
    """Back up Jetson configuration files (and optionally binary archives) to the laptop."""
    from mower_rover.cli.jetson_remote import client_for, resolve_endpoint

    log = get_logger("cli.backup").bind(op="backup")

    endpoint = resolve_endpoint(host, user, port, key, config)
    client = client_for(ctx, endpoint, strict_host_keys)

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("backup_start", output_dir=str(output_dir))

    pulled: list[str] = []
    skipped: list[str] = []

    for remote_path in _REMOTE_CONFIG_FILES:
        local_name = remote_path.lstrip("/").replace("/", "_")
        local_dest = output_dir / local_name
        try:
            client.pull(remote_path, local_dest)
            pulled.append(remote_path)
            typer.echo(f"  Pulled {remote_path} -> {local_dest}")
        except SshError as exc:
            skipped.append(remote_path)
            log.warning("backup_skip", remote=remote_path, error=str(exc))
            typer.echo(f"  Skipped {remote_path}: {exc}", err=True)

    if include_binaries:
        # Look for the most recent archive on the Jetson
        try:
            result = client.run(
                ["ls -t /tmp/mower-binaries-*.tar.gz 2>/dev/null | head -1"],
                timeout=15,
            )
            remote_archive = result.stdout.strip() if result.ok else ""
        except SshError as exc:
            log.warning("backup_binary_list_failed", error=str(exc))
            remote_archive = ""

        if remote_archive:
            archive_name = Path(remote_archive).name
            local_dest = output_dir / archive_name
            try:
                client.pull(remote_archive, local_dest)
                pulled.append(remote_archive)
                typer.echo(f"  Pulled {remote_archive} -> {local_dest}")
            except SshError as exc:
                skipped.append(remote_archive)
                typer.echo(f"  Skipped {remote_archive}: {exc}", err=True)
        else:
            typer.echo("  No binary archive found on the Jetson.")

    typer.echo(f"\nBackup complete: {len(pulled)} pulled, {len(skipped)} skipped.")
    if skipped:
        typer.echo(f"Skipped: {', '.join(skipped)}", err=True)
