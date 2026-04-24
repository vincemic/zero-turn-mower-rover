"""MAVLink FTP-based deployment of the AHRS source-switching Lua script.

Checks the Pixhawk SD card for ``/APM/scripts/ahrs-source-gps-vslam.lua``,
compares the embedded ``-- VERSION:`` comment against the bundled copy, and
uploads when missing or outdated.  All FTP failures are logged as warnings
— they never abort the bridge.
"""

from __future__ import annotations

import contextlib
import importlib.resources
import re
import time
from typing import TYPE_CHECKING

from mower_rover.logging_setup.setup import get_logger

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

    Encapsulates the callback-driven FTP API into simple blocking helpers
    that are easy to mock in tests.
    """

    def __init__(self, conn: object) -> None:
        from pymavlink import mavftp

        self._conn = conn
        self._ftp = mavftp.MAVFTP(
            conn,  # type: ignore[arg-type]
            target_system=conn.target_system,  # type: ignore[attr-defined]
            target_component=conn.target_component,  # type: ignore[attr-defined]
        )
        self._result: bytes | None = None
        self._error: str | None = None
        self._listing: list[str] | None = None
        self._done = False

    # -- blocking helpers --------------------------------------------------

    def list_directory(self, path: str) -> list[str]:
        """Return filenames in *path* on the remote SD card."""
        self._done = False
        self._listing = None
        self._error = None
        self._ftp.cmd_list([path], callback=self._list_cb)
        self._pump()
        if self._error:
            raise OSError(self._error)
        return self._listing or []

    def read_file(self, path: str) -> bytes:
        """Download a remote file and return its contents."""
        self._done = False
        self._result = None
        self._error = None
        self._ftp.cmd_get([path], callback=self._read_cb)
        self._pump()
        if self._error:
            raise OSError(self._error)
        return self._result or b""

    def write_file(self, path: str, data: bytes) -> None:
        """Upload *data* to *path* on the remote SD card."""
        self._done = False
        self._error = None
        self._ftp.cmd_put([path], data, callback=self._write_cb)
        self._pump()
        if self._error:
            raise OSError(self._error)

    def mkdir(self, path: str) -> None:
        """Create a directory on the remote SD card (idempotent)."""
        self._done = False
        self._error = None
        self._ftp.cmd_mkdir([path], callback=self._generic_cb)
        self._pump()
        # Ignore "already exists" errors
        if self._error and "exist" not in self._error.lower():
            raise OSError(self._error)

    # -- internal callbacks ------------------------------------------------

    def _list_cb(self, entry: object) -> None:
        if isinstance(entry, str):
            if entry.startswith("ERR:") or entry.startswith("Timeout"):
                self._error = entry
                self._done = True
            else:
                if self._listing is None:
                    self._listing = []
                # Entries may have trailing info (size, etc.); take just the name
                name = entry.split("\t")[0].strip()
                if name:
                    self._listing.append(name)
        elif entry is None:
            self._done = True

    def _read_cb(self, data: object) -> None:
        if isinstance(data, bytes):
            self._result = data
            self._done = True
        elif isinstance(data, str):
            self._error = data
            self._done = True
        elif data is None:
            self._done = True

    def _write_cb(self, result: object) -> None:
        if isinstance(result, str) and ("ERR" in result or "Timeout" in result):
            self._error = result
        self._done = True

    def _generic_cb(self, result: object) -> None:
        if isinstance(result, str) and ("ERR" in result or "Timeout" in result):
            self._error = result
        self._done = True

    def _pump(self, timeout_s: float = 10.0) -> None:
        """Pump the MAVLink connection until the FTP operation completes."""
        deadline = time.monotonic() + timeout_s
        while not self._done and time.monotonic() < deadline:
            self._conn.recv_match(type="FILE_TRANSFER_PROTOCOL", timeout=0.1)  # type: ignore[attr-defined]
            self._ftp.idle_task()
        if not self._done:
            self._error = "FTP operation timed out"
            self._done = True


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
