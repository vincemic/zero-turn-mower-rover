from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mower_rover.config.laptop import JetsonEndpoint
from mower_rover.transport.ssh import JetsonClient, SshError


@pytest.fixture
def endpoint() -> JetsonEndpoint:
    return JetsonEndpoint(host="rover.lan", user="mower", port=2222, key_path=Path("/keys/id"))


def test_build_ssh_argv_includes_security_options(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(
        endpoint, ssh_binary="C:/fake/ssh.exe", scp_binary="C:/fake/scp.exe"
    )
    argv = client.build_ssh_argv(["uname", "-a"])
    assert argv[0] == "C:/fake/ssh.exe"
    assert "-o" in argv and "StrictHostKeyChecking=accept-new" in argv
    assert "BatchMode=yes" in argv
    assert "PasswordAuthentication=no" in argv
    assert "-i" in argv and str(endpoint.key_path) in argv
    assert "-p" in argv and "2222" in argv
    assert argv[-3:] == ["mower@rover.lan", "uname", "-a"]


def test_build_scp_pull_argv(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(
        endpoint, ssh_binary="C:/fake/ssh.exe", scp_binary="C:/fake/scp.exe"
    )
    argv = client.build_scp_pull_argv("/tmp/log.bin", Path("C:/local/log.bin"))
    assert argv[0] == "C:/fake/scp.exe"
    assert "-P" in argv and "2222" in argv
    assert "mower@rover.lan:/tmp/log.bin" in argv
    assert str(Path("C:/local/log.bin")) in argv


def test_strict_host_keys_validation(endpoint: JetsonEndpoint) -> None:
    with pytest.raises(ValueError):
        JetsonClient(endpoint, strict_host_keys="bogus")


def test_missing_ssh_binary_raises(endpoint: JetsonEndpoint) -> None:
    with patch("mower_rover.transport.ssh.shutil.which", return_value=None):
        client = JetsonClient(endpoint)
    with pytest.raises(SshError, match="ssh"):
        client.build_ssh_argv(["whoami"])
    with pytest.raises(SshError, match="scp"):
        client.build_scp_pull_argv("/x", Path("/y"))


def test_run_propagates_correlation_id(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(
        endpoint,
        correlation_id="abc123def456",
        ssh_binary="ssh",
        scp_binary="scp",
    )
    fake = MagicMock(returncode=0, stdout="ok\n", stderr="")
    with patch("mower_rover.transport.ssh.subprocess.run", return_value=fake) as run_mock:
        result = client.run(["whoami"])
    assert result.ok
    assert result.stdout == "ok\n"
    _, kwargs = run_mock.call_args
    assert kwargs["env"]["MOWER_CORRELATION_ID"] == "abc123def456"


def test_run_check_raises_on_nonzero(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    fake = MagicMock(returncode=2, stdout="", stderr="boom")
    with (
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
        pytest.raises(SshError, match="exit 2"),
    ):
        client.run(["false"], check=True)


def test_run_timeout_raises_ssh_error(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    with (
        patch(
            "mower_rover.transport.ssh.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=1.0),
        ),
        pytest.raises(SshError, match="timed out"),
    ):
        client.run(["sleep", "5"], timeout=1.0)


def test_pull_failure_raises(endpoint: JetsonEndpoint, tmp_path: Path) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    fake = MagicMock(returncode=1, stdout="", stderr="No such file")
    with (
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
        pytest.raises(SshError, match="No such file"),
    ):
        client.pull("/nope", tmp_path / "out.bin")


# -- push / build_scp_push_argv -------------------------------------------


def test_build_scp_push_argv(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(
        endpoint, ssh_binary="C:/fake/ssh.exe", scp_binary="C:/fake/scp.exe"
    )
    argv = client.build_scp_push_argv(Path("C:/local/script.sh"), "/tmp/script.sh")
    assert argv[0] == "C:/fake/scp.exe"
    assert "-P" in argv and "2222" in argv
    assert str(Path("C:/local/script.sh")) in argv
    assert "mower@rover.lan:/tmp/script.sh" in argv
    # local comes before remote in push (opposite of pull)
    local_idx = argv.index(str(Path("C:/local/script.sh")))
    remote_idx = argv.index("mower@rover.lan:/tmp/script.sh")
    assert local_idx < remote_idx


def test_build_scp_push_argv_missing_scp(endpoint: JetsonEndpoint) -> None:
    with patch("mower_rover.transport.ssh.shutil.which", return_value=None):
        client = JetsonClient(endpoint)
    with pytest.raises(SshError, match="scp"):
        client.build_scp_push_argv(Path("/x"), "/y")


def test_push_success(endpoint: JetsonEndpoint, tmp_path: Path) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    fake = MagicMock(returncode=0, stdout="", stderr="")
    with patch("mower_rover.transport.ssh.subprocess.run", return_value=fake):
        result = client.push(tmp_path / "file.sh", "/opt/mower/file.sh")
    assert result.ok


def test_push_failure_raises(endpoint: JetsonEndpoint, tmp_path: Path) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    fake = MagicMock(returncode=1, stdout="", stderr="Permission denied")
    with (
        patch("mower_rover.transport.ssh.subprocess.run", return_value=fake),
        pytest.raises(SshError, match="Permission denied"),
    ):
        client.push(tmp_path / "file.sh", "/opt/mower/file.sh")


def test_push_timeout_raises(endpoint: JetsonEndpoint, tmp_path: Path) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    with (
        patch(
            "mower_rover.transport.ssh.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="scp", timeout=1.0),
        ),
        pytest.raises(SshError, match="timed out"),
    ):
        client.push(tmp_path / "file.sh", "/opt/mower/file.sh", timeout=1.0)


# -- run_streaming ---------------------------------------------------------


def test_run_streaming_collects_output(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n", "line2\n", "line3\n"])
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    with patch("mower_rover.transport.ssh.subprocess.Popen", return_value=mock_proc):
        result = client.run_streaming(["make", "-j12"])

    assert result.ok
    assert result.stdout == "line1\nline2\nline3"
    assert result.returncode == 0


def test_run_streaming_on_line_callback(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    collected: list[str] = []
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["hello\n", "world\n"])
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    with patch("mower_rover.transport.ssh.subprocess.Popen", return_value=mock_proc):
        result = client.run_streaming(["echo", "test"], on_line=collected.append)

    assert collected == ["hello", "world"]
    assert result.ok


def test_run_streaming_no_callback_buffers(endpoint: JetsonEndpoint) -> None:
    """When on_line is None, output is still captured in SshResult.stdout."""
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["alpha\n", "beta\n"])
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    with patch("mower_rover.transport.ssh.subprocess.Popen", return_value=mock_proc):
        result = client.run_streaming(["ls"], on_line=None)

    assert result.stdout == "alpha\nbeta"


def test_run_streaming_includes_server_alive_interval(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    with patch(
        "mower_rover.transport.ssh.subprocess.Popen", return_value=mock_proc
    ) as popen_mock:
        client.run_streaming(["ls"])

    argv = popen_mock.call_args[0][0]
    assert "ServerAliveInterval=30" in argv


def test_run_streaming_timeout_raises(endpoint: JetsonEndpoint) -> None:
    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="ssh", timeout=0.1),
        0,  # after kill()
    ]
    mock_proc.kill.return_value = None
    mock_proc.returncode = -9

    with (
        patch("mower_rover.transport.ssh.subprocess.Popen", return_value=mock_proc),
        pytest.raises(SshError, match="timed out"),
    ):
        client.run_streaming(["sleep", "9999"], timeout=0.1)


def test_run_streaming_does_not_deadlock_on_large_stderr(
    endpoint: JetsonEndpoint,
) -> None:
    """Regression: stderr must be drained concurrently with stdout.

    The previous implementation read ``proc.stdout`` to EOF before reading
    ``proc.stderr``.  When a remote build (cmake/make compiling a large CXX
    translation unit) writes more than ~64 KiB to stderr, the OS pipe buffer
    fills, the remote process blocks on its next stderr write, no further
    stdout arrives, and the entire pipeline deadlocks indefinitely.

    This test launches a real subprocess that writes a large stderr payload
    and a small stdout payload, and asserts the call returns within a few
    seconds with both streams fully captured.
    """
    import sys
    import time

    client = JetsonClient(endpoint, ssh_binary="ssh", scp_binary="scp")

    # 256 KiB to stderr — well above any plausible pipe buffer (Linux 64 KiB,
    # Windows 4 KiB).  Followed by a stdout flush so the test can verify both
    # streams round-tripped.
    payload = (
        "import sys; "
        "sys.stderr.write('X' * 262144); sys.stderr.flush(); "
        "sys.stdout.write('done\\n'); sys.stdout.flush()"
    )
    real_proc = subprocess.Popen(  # noqa: S603 — fixed argv, test-only
        [sys.executable, "-c", payload],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    start = time.monotonic()
    with patch("mower_rover.transport.ssh.subprocess.Popen", return_value=real_proc):
        result = client.run_streaming(["irrelevant"], timeout=10.0)
    elapsed = time.monotonic() - start

    assert result.ok, f"non-zero return: {result.returncode}, stderr={result.stderr[:200]}"
    assert result.stdout == "done"
    assert len(result.stderr) == 262144
    assert elapsed < 5.0, f"streaming took {elapsed:.1f}s — likely deadlocked"
