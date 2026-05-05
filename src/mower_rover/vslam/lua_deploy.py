"""MAVLink FTP-based deployment of the AHRS source-switching Lua script.

Checks the Pixhawk SD card for ``/APM/scripts/ahrs-source-gps-vslam.lua``,
compares the embedded ``-- VERSION:`` comment against the bundled copy, and
uploads when missing or outdated.  All FTP failures are logged as warnings
— they never abort the bridge.
"""

from __future__ import annotations

import contextlib
import errno
import importlib.resources
import os
import re
import tempfile
from typing import TYPE_CHECKING, Any

from mower_rover.logging_setup.setup import get_logger

# Common POSIX errnos returned by ArduPilot's FTP server in the FailErrno
# (code 2) reply payload.  Translated to operator-friendly hints so the
# ``lua_deploy_failed`` warning surfaces actionable causes instead of a
# bare numeric code.
_ERRNO_HINTS: dict[int, str] = {
    errno.ENOSPC: "SD card full — delete old logs from /APM/LOGS",
    errno.EACCES: "permission denied — check SD card write-protect",
    errno.EROFS: "read-only filesystem — SD card may be locked",
    errno.ENOENT: "parent directory missing",
    errno.EIO: "SD card I/O error — card may be failing",
    errno.ENOTDIR: "path component is not a directory",
    errno.EISDIR: "target path is a directory, not a file",
    errno.ENAMETOOLONG: "filename too long for filesystem",
}


def _decode_ftp_error(ret: Any, op: str, path: str) -> str:
    """Format an FTP NAK as ``"{op} {path}: <reason>"`` with errno hints.

    When ``ret.error_code`` is ``FailErrno`` (2), include the POSIX errno
    name and a human-readable hint from :data:`_ERRNO_HINTS` if known.
    """
    from pymavlink.mavftp import FtpError

    code = ret.error_code
    sys_err = getattr(ret, "system_error", None)
    try:
        name = FtpError(code).name
    except ValueError:
        name = f"code {code}"
    if code == FtpError.FailErrno and sys_err is not None:
        errno_name = errno.errorcode.get(sys_err, f"errno {sys_err}")
        hint = _ERRNO_HINTS.get(sys_err, "see ArduPilot FTP server logs")
        return f"{op} {path}: {name} ({errno_name}: {hint})"
    return f"{op} {path}: {name}"

if TYPE_CHECKING:
    pass  # pymavlink types are dynamic; avoid import-time failures on Windows

_SCRIPT_NAME = "ahrs-source-gps-vslam.lua"
_REMOTE_DIR = "/APM/scripts"
_REMOTE_PATH = f"{_REMOTE_DIR}/{_SCRIPT_NAME}"
_VERSION_RE = re.compile(r"^-- VERSION:\s*(.+)$", re.MULTILINE)

log = get_logger("vslam.lua_deploy")


def _bundled_script_bytes() -> bytes:
    """Read the bundled Lua script from package data."""
    ref = importlib.resources.files("mower_rover.params.data").joinpath(_SCRIPT_NAME)
    return ref.read_bytes()


def _extract_version(content: bytes) -> str | None:
    """Extract the ``-- VERSION: x.y`` comment from Lua source bytes."""
    text = content.decode("utf-8", errors="replace")
    m = _VERSION_RE.search(text)
    return m.group(1).strip() if m else None


class _FTPSession:
    """Thin wrapper around pymavlink's MAVLink FTP operations.

    Encapsulates the synchronous pymavlink 2.4.49 MAVFTP API into simple
    blocking helpers that are easy to mock in tests.
    """

    def __init__(self, conn: object) -> None:
        from pymavlink import mavftp

        self._conn = conn
        self._ftp = mavftp.MAVFTP(
            conn,
            target_system=conn.target_system,  # type: ignore[attr-defined]
            target_component=conn.target_component,  # type: ignore[attr-defined]
        )
        self._tmpdir = tempfile.mkdtemp()

    # -- blocking helpers --------------------------------------------------

    def list_directory(self, path: str) -> list[str]:
        """Return filenames in *path* on the remote SD card."""
        from pymavlink.mavftp import FtpError

        ret = self._ftp.cmd_list([path])
        if ret.error_code != FtpError.Success:
            raise OSError(_decode_ftp_error(ret, "list", path))
        return [entry.name for entry in self._ftp.list_result]

    def read_file(self, path: str) -> bytes:
        """Download a remote file and return its contents."""
        self._ftp.filename = os.path.join(self._tmpdir, "mavftp_dl")
        data = self._ftp.read(path, 0x40000)
        if data is None:
            raise OSError(f"read {path}: FTP transfer failed")
        return bytes(data)

    def write_file(self, path: str, data: bytes) -> None:
        """Upload *data* to *path* on the remote SD card."""
        from io import BytesIO

        from pymavlink.mavftp import FtpError

        ret = self._ftp.cmd_put([path, path], fh=BytesIO(data))
        if ret.error_code != FtpError.Success:
            raise OSError(_decode_ftp_error(ret, "write-create", path))
        ret = self._ftp.process_ftp_reply("CreateFile", timeout=30)
        if ret.error_code != FtpError.Success:
            raise OSError(_decode_ftp_error(ret, "write", path))

    def mkdir(self, path: str) -> None:
        """Create a directory on the remote SD card (idempotent)."""
        from pymavlink.mavftp import FtpError

        ret = self._ftp.cmd_mkdir([path])
        if ret.error_code not in (FtpError.Success, FtpError.FileExists):
            raise OSError(_decode_ftp_error(ret, "mkdir", path))


def check_and_deploy_lua(conn: object) -> None:
    """Deploy the AHRS source-switching Lua script to the Pixhawk if needed.

    Parameters
    ----------
    conn:
        An open pymavlink ``mavutil.mavlink_connection`` object.

    Behaviour:
        - Script missing on Pixhawk → upload, log reboot-needed warning.
        - Script version outdated   → upload, log reboot-needed warning.
        - Script version matches    → skip, log info.
        - Any FTP failure           → WARNING log, continue without upload.
    """
    try:
        bundled = _bundled_script_bytes()
        bundled_ver = _extract_version(bundled)
        log.info(
            "lua_deploy_check",
            script=_SCRIPT_NAME,
            bundled_version=bundled_ver,
        )

        ftp = _FTPSession(conn)

        # Ensure the scripts directory exists
        with contextlib.suppress(OSError):
            ftp.mkdir(_REMOTE_DIR)

        # Check if script exists on Pixhawk
        try:
            listing = ftp.list_directory(_REMOTE_DIR)
        except OSError as exc:
            log.warning("lua_deploy_list_failed", error=str(exc))
            return

        if _SCRIPT_NAME in listing:
            # Script exists — check version
            try:
                remote_bytes = ftp.read_file(_REMOTE_PATH)
                remote_ver = _extract_version(remote_bytes)
            except OSError as exc:
                log.warning("lua_deploy_read_failed", error=str(exc))
                remote_ver = None

            if remote_ver == bundled_ver:
                log.info(
                    "lua_deploy_current",
                    version=remote_ver,
                )
                return

            log.info(
                "lua_deploy_outdated",
                remote_version=remote_ver,
                bundled_version=bundled_ver,
            )
        else:
            log.info("lua_deploy_missing")

        # Upload bundled script
        ftp.write_file(_REMOTE_PATH, bundled)

        # Verify upload integrity via read-back
        try:
            readback = ftp.read_file(_REMOTE_PATH)
            if readback != bundled:
                log.warning(
                    "lua_deploy_verify_mismatch",
                    expected_len=len(bundled),
                    got_len=len(readback),
                )
        except OSError as exc:
            log.warning("lua_deploy_verify_failed", error=str(exc))

        log.warning(
            "lua_deploy_uploaded",
            version=bundled_ver,
            message="Lua script uploaded; ArduPilot reboot required for changes to take effect",
        )

    except Exception as exc:  # noqa: BLE001
        log.warning(
            "lua_deploy_failed",
            error=str(exc),
            message="Lua deploy failed — continuing bridge without script update",
        )
