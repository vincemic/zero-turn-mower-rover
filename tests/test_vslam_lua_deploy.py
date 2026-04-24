"""Tests for VSLAM Lua script deployment — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mower_rover.vslam.lua_deploy import (
    _REMOTE_PATH,
    _SCRIPT_NAME,
    _extract_version,
    check_and_deploy_lua,
)

# ------------------------------------------------------------------
# _extract_version helper
# ------------------------------------------------------------------


class TestExtractVersion:
    def test_extracts_version_from_lua(self) -> None:
        content = b"-- ahrs-source-gps-vslam.lua\n-- VERSION: 1.0\n-- stuff"
        assert _extract_version(content) == "1.0"

    def test_extracts_semver(self) -> None:
        content = b"-- VERSION: 2.3.1\ncode here"
        assert _extract_version(content) == "2.3.1"

    def test_returns_none_when_missing(self) -> None:
        content = b"-- no version here\nlocal x = 1"
        assert _extract_version(content) is None

    def test_handles_empty_bytes(self) -> None:
        assert _extract_version(b"") is None


# ------------------------------------------------------------------
# Mock helpers
# ------------------------------------------------------------------

_BUNDLED_CONTENT = b"-- ahrs-source-gps-vslam.lua\n-- VERSION: 1.0\nfunction update() end\n"


def _make_mock_ftp_session(
    *,
    listing: list[str] | None = None,
    listing_error: str | None = None,
    remote_content: bytes | None = None,
    read_error: str | None = None,
    write_error: str | None = None,
) -> MagicMock:
    """Build a mock ``_FTPSession`` with configurable behaviour."""
    mock = MagicMock()

    if listing_error:
        mock.list_directory.side_effect = OSError(listing_error)
    else:
        mock.list_directory.return_value = listing or []

    if read_error:
        mock.read_file.side_effect = OSError(read_error)
    else:
        mock.read_file.return_value = remote_content or b""

    if write_error:
        mock.write_file.side_effect = OSError(write_error)

    mock.mkdir.return_value = None

    return mock


# ------------------------------------------------------------------
# check_and_deploy_lua — happy paths
# ------------------------------------------------------------------


class TestLuaDeployMissing:
    """Script not on Pixhawk → upload."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_uploads_when_missing(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        mock_ftp = _make_mock_ftp_session(listing=[])
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        check_and_deploy_lua(conn)

        mock_ftp.write_file.assert_called_once_with(_REMOTE_PATH, _BUNDLED_CONTENT)


class TestLuaDeployOutdated:
    """Script on Pixhawk with old version → upload."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_uploads_when_outdated(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        old_content = b"-- VERSION: 0.9\nold code"
        mock_ftp = _make_mock_ftp_session(
            listing=[_SCRIPT_NAME],
            remote_content=old_content,
        )
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        check_and_deploy_lua(conn)

        mock_ftp.write_file.assert_called_once_with(_REMOTE_PATH, _BUNDLED_CONTENT)


class TestLuaDeployCurrent:
    """Script on Pixhawk with matching version → skip."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_skips_when_current(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        mock_ftp = _make_mock_ftp_session(
            listing=[_SCRIPT_NAME],
            remote_content=_BUNDLED_CONTENT,
        )
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        check_and_deploy_lua(conn)

        mock_ftp.write_file.assert_not_called()


# ------------------------------------------------------------------
# check_and_deploy_lua — failure paths
# ------------------------------------------------------------------


class TestLuaDeployListFailure:
    """FTP list_directory fails → WARNING, no crash."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_graceful_on_list_failure(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        mock_ftp = _make_mock_ftp_session(
            listing_error="Timeout waiting for response",
        )
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        # Should NOT raise
        check_and_deploy_lua(conn)

        mock_ftp.write_file.assert_not_called()


class TestLuaDeployReadFailure:
    """FTP read_file fails → treat as outdated, attempt upload."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_uploads_when_read_fails(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        mock_ftp = _make_mock_ftp_session(
            listing=[_SCRIPT_NAME],
            read_error="Read timeout",
        )
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        check_and_deploy_lua(conn)

        # read failed → remote_ver=None ≠ bundled_ver → upload
        mock_ftp.write_file.assert_called_once_with(_REMOTE_PATH, _BUNDLED_CONTENT)


class TestLuaDeployWriteFailure:
    """FTP write_file fails → WARNING, no crash."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_graceful_on_write_failure(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        mock_ftp = _make_mock_ftp_session(
            listing=[],
            write_error="SD card full",
        )
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        # Should NOT raise — caught by outer try/except
        check_and_deploy_lua(conn)


class TestLuaDeployFTPSessionCreationFails:
    """pymavlink import or FTPSession init fails → WARNING, no crash."""

    @patch(
        "mower_rover.vslam.lua_deploy._FTPSession",
        side_effect=ImportError("no mavftp"),
    )
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_graceful_on_ftp_init_failure(
        self, _mock_bundled: MagicMock, _mock_ftp_cls: MagicMock
    ) -> None:
        conn = MagicMock()

        # Should NOT raise
        check_and_deploy_lua(conn)


class TestLuaDeployNoVersionInRemote:
    """Remote file has no version comment → treated as outdated → upload."""

    @patch("mower_rover.vslam.lua_deploy._FTPSession")
    @patch(
        "mower_rover.vslam.lua_deploy._bundled_script_bytes",
        return_value=_BUNDLED_CONTENT,
    )
    def test_uploads_when_remote_has_no_version(
        self, _mock_bundled: MagicMock, mock_ftp_cls: MagicMock
    ) -> None:
        no_ver_content = b"-- some old script\nfunction update() end\n"
        mock_ftp = _make_mock_ftp_session(
            listing=[_SCRIPT_NAME],
            remote_content=no_ver_content,
        )
        mock_ftp_cls.return_value = mock_ftp
        conn = MagicMock()

        check_and_deploy_lua(conn)

        mock_ftp.write_file.assert_called_once_with(_REMOTE_PATH, _BUNDLED_CONTENT)
