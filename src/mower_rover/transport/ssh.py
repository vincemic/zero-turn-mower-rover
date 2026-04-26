"""SSH transport for the laptop → Jetson link.

Wraps the system `ssh` and `scp` binaries via `subprocess` — no paramiko
dependency, available on Windows 10+ (OpenSSH client) and every modern Linux.
Key auth only; we never accept a password.

The correlation ID from the laptop-side structlog context is propagated to
the remote process via the `MOWER_CORRELATION_ID` env var so Phase 11's log
archive can stitch both sides of an operation back together.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from mower_rover.config.laptop import JetsonEndpoint
from mower_rover.logging_setup.setup import get_logger


class SshError(RuntimeError):
    """Raised when an SSH/SCP invocation fails or the system tool is missing."""


@dataclass
class SshResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# StrictHostKeyChecking values we accept on the CLI / API surface.
HOST_KEY_POLICIES = ("accept-new", "yes", "no")


class JetsonClient:
    """Run commands and pull files on the rover's Jetson over SSH.

    Parameters
    ----------
    endpoint:
        The `JetsonEndpoint` (host, user, port, optional key_path).
    correlation_id:
        Optional correlation ID; propagated to the remote process via
        `MOWER_CORRELATION_ID`. If omitted, no env var is set.
    strict_host_keys:
        OpenSSH `StrictHostKeyChecking` value. Default `accept-new` (TOFU)
        — accepts a brand-new host on first contact and refuses key swaps
        thereafter.
    connect_timeout_s:
        Passed as `ConnectTimeout` to OpenSSH.
    ssh_binary, scp_binary:
        Override the discovered `ssh` / `scp` binaries (test seam).
    """

    def __init__(
        self,
        endpoint: JetsonEndpoint,
        *,
        correlation_id: str | None = None,
        strict_host_keys: str = "accept-new",
        connect_timeout_s: int = 10,
        ssh_binary: str | None = None,
        scp_binary: str | None = None,
    ) -> None:
        if strict_host_keys not in HOST_KEY_POLICIES:
            raise ValueError(
                f"strict_host_keys must be one of {HOST_KEY_POLICIES}, got {strict_host_keys!r}"
            )
        self.endpoint = endpoint
        self.correlation_id = correlation_id
        self.strict_host_keys = strict_host_keys
        self.connect_timeout_s = connect_timeout_s
        self._ssh = ssh_binary or shutil.which("ssh")
        self._scp = scp_binary or shutil.which("scp")
        self._log = get_logger("transport.ssh").bind(
            host=endpoint.host, user=endpoint.user, port=endpoint.port
        )

    # -- argv builders -----------------------------------------------------

    def _common_opts(self) -> list[str]:
        opts: list[str] = [
            "-o", f"StrictHostKeyChecking={self.strict_host_keys}",
            "-o", f"ConnectTimeout={self.connect_timeout_s}",
            "-o", "BatchMode=yes",  # never prompt for a password
            "-o", "PasswordAuthentication=no",
        ]
        if self.endpoint.key_path is not None:
            opts += ["-i", str(self.endpoint.key_path)]
        return opts

    def build_ssh_argv(self, remote_argv: Sequence[str]) -> list[str]:
        if self._ssh is None:
            raise SshError(
                "`ssh` binary not found on PATH; install the OpenSSH client"
                " (Windows: Add Optional Feature → OpenSSH Client)."
            )
        argv: list[str] = [self._ssh, *self._common_opts(), "-p", str(self.endpoint.port)]
        target = f"{self.endpoint.user}@{self.endpoint.host}"
        argv.append(target)
        argv.extend(remote_argv)
        return argv

    def build_scp_pull_argv(self, remote_path: str, local_path: Path) -> list[str]:
        if self._scp is None:
            raise SshError("`scp` binary not found on PATH; install the OpenSSH client.")
        argv: list[str] = [self._scp, *self._common_opts(), "-P", str(self.endpoint.port)]
        target = f"{self.endpoint.user}@{self.endpoint.host}:{remote_path}"
        argv += [target, str(local_path)]
        return argv

    def build_scp_push_argv(self, local_path: Path, remote_path: str) -> list[str]:
        """Build argv for scp laptop → Jetson."""
        if self._scp is None:
            raise SshError("`scp` binary not found on PATH; install the OpenSSH client.")
        argv: list[str] = [self._scp, *self._common_opts(), "-P", str(self.endpoint.port)]
        target = f"{self.endpoint.user}@{self.endpoint.host}:{remote_path}"
        argv += [str(local_path), target]
        return argv

    # -- public API --------------------------------------------------------

    def run(
        self,
        remote_argv: Sequence[str],
        *,
        check: bool = False,
        timeout: float | None = 60.0,
        extra_env: dict[str, str] | None = None,
    ) -> SshResult:
        """Run `remote_argv` on the Jetson, returning stdout/stderr/exit.

        Set `check=True` to raise `SshError` on non-zero exit.
        """
        argv = self.build_ssh_argv(remote_argv)
        env = self._build_env(extra_env)
        self._log.info("ssh_run_start", argv=_redact(argv))
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SshError(f"ssh binary disappeared: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SshError(f"ssh timed out after {timeout}s: {' '.join(remote_argv)}") from exc

        result = SshResult(
            argv=argv,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
        self._log.info(
            "ssh_run_done",
            returncode=result.returncode,
            stdout_bytes=len(result.stdout),
            stderr_bytes=len(result.stderr),
        )
        if check and not result.ok:
            raise SshError(
                f"remote command failed (exit {result.returncode}): {result.stderr.strip()}"
            )
        return result

    def run_streaming(
        self,
        remote_argv: Sequence[str],
        *,
        timeout: float | None = 3600.0,
        on_line: Callable[[str], None] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> SshResult:
        """Run *remote_argv* on the Jetson with line-by-line stdout streaming.

        If *on_line* is provided, each stdout line is passed to it as it
        arrives.  If *on_line* is ``None``, output is buffered and returned
        in :pyattr:`SshResult.stdout`.

        Adds ``ServerAliveInterval=30`` to keep long-running builds alive.
        """
        argv = self.build_ssh_argv(remote_argv)
        # Insert ServerAliveInterval for long-running streaming commands.
        argv[1:1] = ["-o", "ServerAliveInterval=30"]
        env = self._build_env(extra_env)
        self._log.info("ssh_streaming_start", argv=_redact(argv))

        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise SshError(f"ssh binary disappeared: {exc}") from exc

        lines: list[str] = []
        assert proc.stdout is not None  # guaranteed by stdout=PIPE
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            lines.append(line)
            if on_line is not None:
                on_line(line)

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise SshError(
                f"ssh streaming timed out after {timeout}s: {' '.join(remote_argv)}"
            ) from None

        stderr = proc.stderr.read() if proc.stderr else ""
        result = SshResult(
            argv=argv,
            returncode=proc.returncode,
            stdout="\n".join(lines),
            stderr=stderr,
        )
        self._log.info(
            "ssh_streaming_done",
            returncode=result.returncode,
            stdout_lines=len(lines),
            stderr_bytes=len(result.stderr),
        )
        return result

    def pull(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout: float | None = 600.0,
    ) -> SshResult:
        """Copy `remote_path` from the Jetson to `local_path` on the laptop."""
        argv = self.build_scp_pull_argv(remote_path, local_path)
        env = self._build_env(None)
        self._log.info(
            "scp_pull_start", remote=remote_path, local=str(local_path), argv=_redact(argv)
        )
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, env=env, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise SshError(f"scp pull timed out after {timeout}s: {remote_path}") from exc
        result = SshResult(
            argv=argv,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
        self._log.info("scp_pull_done", returncode=result.returncode)
        if not result.ok:
            raise SshError(
                f"scp pull failed (exit {result.returncode}): {result.stderr.strip()}"
            )
        return result

    def push(
        self,
        local_path: Path,
        remote_path: str,
        *,
        timeout: float | None = 600.0,
    ) -> SshResult:
        """Copy *local_path* from the laptop to *remote_path* on the Jetson."""
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

    # -- helpers -----------------------------------------------------------

    def _build_env(self, extra_env: dict[str, str] | None) -> dict[str, str]:
        env = os.environ.copy()
        if self.correlation_id:
            env["MOWER_CORRELATION_ID"] = self.correlation_id
            # OpenSSH only forwards env vars whitelisted by `SendEnv`; we set
            # it locally for parity with logs and rely on the remote callback
            # picking it up if the operator pre-configured `AcceptEnv` (or
            # uses our wrapper, which reads it from its own env after the
            # remote shell sets it). For now this primarily aids debugging
            # of the local subprocess; see plan §3.
        if extra_env:
            env.update(extra_env)
        return env


def _redact(argv: Iterable[str]) -> list[str]:
    """Best-effort redaction for log lines.

    We never accept passwords, but if a user ever passes a key path we keep it
    visible (paths are not secrets); if a future flag added a password-like
    arg, redact it here.
    """
    out: list[str] = []
    skip_next = False
    for a in argv:
        if skip_next:
            out.append("***")
            skip_next = False
            continue
        if a in {"--password", "-P-PASSWORD"}:  # placeholder; we don't support these
            out.append(a)
            skip_next = True
            continue
        out.append(a)
    return out
