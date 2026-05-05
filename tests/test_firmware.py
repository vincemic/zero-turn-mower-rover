"""Tests for pixhawk.firmware module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from mower_rover.pixhawk.firmware import (
    BOARD_ID_CUBE_ORANGE,
    VERSION_TYPE_ALPHA,
    VERSION_TYPE_BETA,
    VERSION_TYPE_DEV,
    VERSION_TYPE_OFFICIAL,
    VERSION_TYPE_RC,
    FirmwareInfo,
    FlashResult,
    check_remote_version,
    decode_flight_sw_version,
    download_firmware,
    flash_firmware,
    format_version,
    read_running_version,
    reboot_to_bootloader,
    validate_apj,
    wait_for_bootloader,
)


class TestVersionDecoding:
    """Tests for version decoding and formatting functions."""

    def test_decode_flight_sw_version_official(self) -> None:
        """Test decoding official release version."""
        result = decode_flight_sw_version(0x040603FF)
        assert result == (4, 6, 3, 255)

    def test_decode_flight_sw_version_dev(self) -> None:
        """Test decoding development version.""" 
        result = decode_flight_sw_version(0x04060300)
        assert result == (4, 6, 3, 0)

    def test_decode_flight_sw_version_beta(self) -> None:
        """Test decoding beta version."""
        result = decode_flight_sw_version(0x04060380)
        assert result == (4, 6, 3, 128)

    def test_decode_flight_sw_version_edge_cases(self) -> None:
        """Test edge cases for version decoding."""
        # Maximum values
        result = decode_flight_sw_version(0xFFFFFFFF)
        assert result == (255, 255, 255, 255)
        
        # Zero
        result = decode_flight_sw_version(0x00000000)
        assert result == (0, 0, 0, 0)

    def test_format_version_official(self) -> None:
        """Test formatting official release version."""
        result = format_version((4, 6, 3, VERSION_TYPE_OFFICIAL))
        assert result == "4.6.3-official"

    def test_format_version_dev(self) -> None:
        """Test formatting development version."""
        result = format_version((4, 6, 3, VERSION_TYPE_DEV))
        assert result == "4.6.3-dev"

    def test_format_version_beta(self) -> None:
        """Test formatting beta version."""
        result = format_version((4, 6, 3, VERSION_TYPE_BETA))
        assert result == "4.6.3-beta"

    def test_format_version_alpha(self) -> None:
        """Test formatting alpha version."""
        result = format_version((4, 6, 3, VERSION_TYPE_ALPHA))
        assert result == "4.6.3-alpha"

    def test_format_version_rc(self) -> None:
        """Test formatting release candidate version."""
        result = format_version((4, 6, 3, VERSION_TYPE_RC))
        assert result == "4.6.3-rc"

    def test_format_version_unknown(self) -> None:
        """Test formatting unknown type code."""
        result = format_version((4, 6, 3, 42))
        assert result == "4.6.3-unknown-42"


class TestFirmwareInfo:
    """Tests for FirmwareInfo dataclass."""

    def test_firmware_info_valid(self) -> None:
        """Test creating valid FirmwareInfo."""
        info = FirmwareInfo(
            major=4,
            minor=6,
            patch=3,
            type_code=VERSION_TYPE_OFFICIAL,
            type_name="official",
            version_string="4.6.3-official"
        )
        assert info.major == 4
        assert info.minor == 6
        assert info.patch == 3
        assert info.type_code == VERSION_TYPE_OFFICIAL
        assert info.type_name == "official"
        assert info.version_string == "4.6.3-official"

    def test_firmware_info_validation_major(self) -> None:
        """Test FirmwareInfo validation for major version."""
        with pytest.raises(ValueError, match="Invalid major version"):
            FirmwareInfo(
                major=256,  # Invalid: > 255
                minor=6,
                patch=3,
                type_code=VERSION_TYPE_OFFICIAL,
                type_name="official",
                version_string="256.6.3-official"
            )

    def test_firmware_info_validation_minor(self) -> None:
        """Test FirmwareInfo validation for minor version."""
        with pytest.raises(ValueError, match="Invalid minor version"):
            FirmwareInfo(
                major=4,
                minor=-1,  # Invalid: < 0
                patch=3,
                type_code=VERSION_TYPE_OFFICIAL,
                type_name="official", 
                version_string="4.-1.3-official"
            )

    def test_firmware_info_validation_patch(self) -> None:
        """Test FirmwareInfo validation for patch version."""
        with pytest.raises(ValueError, match="Invalid patch version"):
            FirmwareInfo(
                major=4,
                minor=6,
                patch=256,  # Invalid: > 255
                type_code=VERSION_TYPE_OFFICIAL,
                type_name="official",
                version_string="4.6.256-official"
            )

    def test_firmware_info_validation_type_code(self) -> None:
        """Test FirmwareInfo validation for type code."""
        with pytest.raises(ValueError, match="Invalid type code"):
            FirmwareInfo(
                major=4,
                minor=6,
                patch=3,
                type_code=-1,  # Invalid: < 0
                type_name="official",
                version_string="4.6.3-official"
            )


class TestFlashResult:
    """Tests for FlashResult dataclass."""

    def test_flash_result_success(self) -> None:
        """Test creating successful FlashResult."""
        old_version = FirmwareInfo(4, 5, 0, VERSION_TYPE_OFFICIAL, "official", "4.5.0-official")
        new_version = FirmwareInfo(4, 6, 3, VERSION_TYPE_OFFICIAL, "official", "4.6.3-official")
        
        result = FlashResult(
            success=True,
            old_version=old_version,
            new_version=new_version,
            bytes_flashed=524288,
            flash_time_s=45.2
        )
        
        assert result.success is True
        assert result.old_version == old_version
        assert result.new_version == new_version
        assert result.error_message is None
        assert result.bytes_flashed == 524288
        assert result.flash_time_s == 45.2

    def test_flash_result_failure(self) -> None:
        """Test creating failed FlashResult."""
        result = FlashResult(
            success=False,
            old_version=None,
            new_version=None,
            error_message="Flash timeout"
        )
        
        assert result.success is False
        assert result.old_version is None
        assert result.new_version is None
        assert result.error_message == "Flash timeout"
        assert result.bytes_flashed == 0
        assert result.flash_time_s == 0.0


class TestReadRunningVersion:
    """Tests for read_running_version function."""

    def test_read_running_version_success(self) -> None:
        """Test successful version reading."""
        mock_conn = Mock()
        mock_msg = Mock()
        mock_msg.flight_sw_version = 0x040603FF  # 4.6.3-official
        mock_conn.recv_match.return_value = mock_msg
        
        result = read_running_version(mock_conn)
        
        assert result is not None
        assert result.major == 4
        assert result.minor == 6
        assert result.patch == 3
        assert result.type_code == VERSION_TYPE_OFFICIAL
        assert result.type_name == "official"
        assert result.version_string == "4.6.3-official"
        
        # Verify MAVLink command was sent
        mock_conn.mav.command_long_send.assert_called_once()

    def test_read_running_version_timeout(self) -> None:
        """Test timeout when reading version."""
        mock_conn = Mock()
        mock_conn.recv_match.return_value = None  # Timeout
        
        result = read_running_version(mock_conn)
        
        assert result is None

    def test_read_running_version_exception(self) -> None:
        """Test exception handling when reading version."""
        mock_conn = Mock()
        mock_conn.mav.command_long_send.side_effect = Exception("Connection lost")
        
        result = read_running_version(mock_conn)
        
        assert result is None


class TestCheckRemoteVersion:
    """Tests for check_remote_version function."""

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_check_remote_version_stable(self, mock_urlopen: Mock) -> None:
        """Test checking stable track version."""
        mock_response = Mock()
        mock_response.read.return_value = b"4.6.3"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=None)
        mock_urlopen.return_value = mock_response
        
        result = check_remote_version("stable")
        
        assert result == (4, 6, 3)

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_check_remote_version_beta_with_suffix(self, mock_urlopen: Mock) -> None:
        """Test checking beta track version with suffix."""
        mock_response = Mock()
        mock_response.read.return_value = b"4.6.4-beta1"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=None)
        mock_urlopen.return_value = mock_response
        
        result = check_remote_version("beta")
        
        assert result == (4, 6, 4)

    def test_check_remote_version_unknown_track(self) -> None:
        """Test checking unknown track."""
        result = check_remote_version("unknown")
        
        assert result is None

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_check_remote_version_invalid_format(self, mock_urlopen: Mock) -> None:
        """Test handling invalid version format."""
        mock_response = Mock()
        mock_response.read.return_value = b"invalid.version"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=None)
        mock_urlopen.return_value = mock_response
        
        result = check_remote_version("stable")
        
        assert result is None

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_check_remote_version_network_error(self, mock_urlopen: Mock) -> None:
        """Test handling network error."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Network unreachable")
        
        result = check_remote_version("stable")
        
        assert result is None


class TestValidateApj:
    """Tests for validate_apj function."""

    def test_validate_apj_valid_file(self) -> None:
        """Test validating a valid .apj file."""
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "APJFWv1",
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            validate_apj(apj_path)  # Should not raise
        finally:
            apj_path.unlink()

    def test_validate_apj_missing_file(self) -> None:
        """Test validating non-existent file."""
        with pytest.raises(FileNotFoundError):
            validate_apj(Path("/nonexistent/file.apj"))

    def test_validate_apj_invalid_json(self) -> None:
        """Test validating file with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            f.write("{ invalid json }")
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()

    def test_validate_apj_missing_fields(self) -> None:
        """Test validating file with missing required fields."""
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "APJFWv1",
            # Missing image_size and image
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Missing required field"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()

    def test_validate_apj_wrong_magic(self) -> None:
        """Test validating file with wrong magic."""
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "WRONGMAG",  # Wrong magic
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Invalid APJ magic"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()

    def test_validate_apj_wrong_board_id(self) -> None:
        """Test validating file with wrong board ID."""
        apj_data = {
            "board_id": 999,  # Wrong board ID
            "magic": "APJFWv1",
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Wrong board ID"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()


# Phase 2 Tests: Flash Protocol Wrapper

class TestRebootToBootloader:
    """Tests for reboot_to_bootloader function."""
    
    def test_reboot_to_bootloader_success(self) -> None:
        """Test successful reboot to bootloader."""
        mock_conn = Mock()
        
        reboot_to_bootloader(mock_conn)
        
        # Verify MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN was sent
        mock_conn.mav.command_long_send.assert_called_once_with(
            mock_conn.target_system,
            mock_conn.target_component,
            246,  # MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN
            0,    # confirmation
            3,    # param1: reboot to bootloader
            0, 0, 0, 0, 0, 0  # param2-7
        )
        
        # Verify connection was closed
        mock_conn.close.assert_called_once()

    def test_reboot_to_bootloader_command_failure(self) -> None:
        """Test handling command send failure."""
        mock_conn = Mock()
        mock_conn.mav.command_long_send.side_effect = Exception("MAVLink error")
        
        with pytest.raises(ConnectionError, match="Failed to reboot to bootloader"):
            reboot_to_bootloader(mock_conn)


class TestWaitForBootloader:
    """Tests for wait_for_bootloader function."""
    
    @patch('mower_rover.pixhawk.firmware.serial.Serial')
    @patch('mower_rover.pixhawk.firmware.time.sleep')
    def test_wait_for_bootloader_success(self, mock_sleep: Mock, mock_serial: Mock) -> None:
        """Test successful bootloader detection."""
        from mower_rover.pixhawk.firmware import INSYNC, EOC, OK, GET_SYNC
        
        # Mock serial connection
        mock_ser = Mock()
        mock_ser.read.return_value = bytes([INSYNC, OK])
        mock_serial.return_value.__enter__ = Mock(return_value=mock_ser)
        mock_serial.return_value.__exit__ = Mock(return_value=None)
        
        result = wait_for_bootloader("/dev/pixhawk", timeout_s=5)
        
        assert result == "/dev/pixhawk"
        
        # Verify correct command was sent
        mock_ser.write.assert_called_with(bytes([GET_SYNC, EOC]))
        mock_ser.flush.assert_called_once()

    @patch('mower_rover.pixhawk.firmware.serial.Serial')
    @patch('mower_rover.pixhawk.firmware.time.time')
    @patch('mower_rover.pixhawk.firmware.time.sleep')
    def test_wait_for_bootloader_timeout(self, mock_sleep: Mock, mock_time: Mock, mock_serial: Mock) -> None:
        """Test bootloader detection timeout."""
        from mower_rover.pixhawk.firmware import INSYNC, OK
        
        # Use a counter so time.time() never runs out of values
        call_count = [0]
        def advancing_time():
            call_count[0] += 1
            # First call is start_time=0, then advance past timeout on 4th+ call
            if call_count[0] <= 1:
                return 0.0
            elif call_count[0] <= 3:
                return float(call_count[0])
            else:
                return 100.0  # Well past any timeout
        mock_time.side_effect = advancing_time
        
        # Mock serial connection that never returns bootloader response
        mock_ser = Mock()
        mock_ser.read.return_value = bytes([0x99, 0x99])  # Wrong response, not INSYNC + OK
        mock_serial.return_value.__enter__ = Mock(return_value=mock_ser)
        mock_serial.return_value.__exit__ = Mock(return_value=None)
        
        with pytest.raises(TimeoutError, match="Bootloader not detected within"):
            wait_for_bootloader("/dev/pixhawk", timeout_s=5)

    @patch('mower_rover.pixhawk.firmware.serial.Serial')
    @patch('mower_rover.pixhawk.firmware.time.sleep')
    def test_wait_for_bootloader_wrong_response(self, mock_sleep: Mock, mock_serial: Mock) -> None:
        """Test handling wrong bootloader response."""
        from mower_rover.pixhawk.firmware import INSYNC, OK
        
        # Mock serial with wrong response, then timeout
        mock_ser = Mock()
        mock_ser.read.side_effect = [
            bytes([0x99, 0x99]),  # Wrong response
            bytes([0x88, 0x88]),  # Wrong response
            bytes([INSYNC, OK])   # Correct response on third try
        ]
        mock_serial.return_value.__enter__ = Mock(return_value=mock_ser)
        mock_serial.return_value.__exit__ = Mock(return_value=None)
        
        result = wait_for_bootloader("/dev/pixhawk", timeout_s=10)
        
        assert result == "/dev/pixhawk"
        assert mock_ser.read.call_count == 3


class TestFlashFirmware:
    """Tests for flash_firmware function."""
    
    @patch('mower_rover.pixhawk.firmware.ApjFirmware')
    @patch('mower_rover.pixhawk.firmware.uploader')
    def test_flash_firmware_success(self, mock_uploader_class: Mock, mock_firmware_class: Mock) -> None:
        """Test successful firmware flash."""
        # Mock firmware
        mock_fw = Mock()
        mock_fw.image_size = 524288
        mock_firmware_class.return_value = mock_fw
        
        # Mock uploader
        mock_up = Mock()
        mock_up.identify.return_value = {"board_id": 140, "des": "CubeOrange"}
        mock_up.upload.return_value = True
        mock_uploader_class.return_value.__enter__ = Mock(return_value=mock_up)
        mock_uploader_class.return_value.__exit__ = Mock(return_value=None)
        
        # Mock progress callback
        progress_calls = []
        def progress_cb(phase: str, current: int, total: int) -> None:
            progress_calls.append((phase, current, total))
        
        result = flash_firmware("/dev/pixhawk", Path("test.apj"), progress_cb)
        
        assert result.success is True
        assert result.bytes_flashed == 524288
        assert result.flash_time_s >= 0
        assert result.error_message is None
        
        # Verify firmware was loaded
        mock_firmware_class.assert_called_once_with(Path("test.apj"))
        
        # Verify uploader was used
        mock_uploader_class.assert_called_once_with("/dev/pixhawk")
        mock_up.identify.assert_called_once()
        mock_up.upload.assert_called_once()
        mock_up.send_reboot.assert_called_once()
        
        # Verify progress callbacks
        assert len(progress_calls) >= 2  # At least sync and reboot
        assert progress_calls[0][0] == "sync"
        assert progress_calls[-1][0] == "reboot"

    @patch('mower_rover.pixhawk.firmware.ApjFirmware')
    def test_flash_firmware_load_error(self, mock_firmware_class: Mock) -> None:
        """Test firmware loading error."""
        mock_firmware_class.side_effect = Exception("File not found")
        
        result = flash_firmware("/dev/pixhawk", Path("missing.apj"))
        
        assert result.success is False
        assert "File not found" in result.error_message
        assert result.flash_time_s >= 0

    @patch('mower_rover.pixhawk.firmware.ApjFirmware')
    @patch('mower_rover.pixhawk.firmware.uploader')
    def test_flash_firmware_upload_failure(self, mock_uploader_class: Mock, mock_firmware_class: Mock) -> None:
        """Test firmware upload failure."""
        # Mock firmware
        mock_fw = Mock()
        mock_fw.image_size = 524288
        mock_firmware_class.return_value = mock_fw
        
        # Mock uploader failure
        mock_up = Mock()
        mock_up.identify.return_value = {"board_id": 140, "des": "CubeOrange"}
        mock_up.upload.return_value = False  # Upload failed
        mock_uploader_class.return_value.__enter__ = Mock(return_value=mock_up)
        mock_uploader_class.return_value.__exit__ = Mock(return_value=None)
        
        result = flash_firmware("/dev/pixhawk", Path("test.apj"))
        
        assert result.success is False
        assert "Upload failed - verify error" in result.error_message
        assert result.flash_time_s >= 0
        
        # Verify upload was attempted but reboot was not sent
        mock_up.upload.assert_called_once()
        mock_up.send_reboot.assert_not_called()

    @patch('mower_rover.pixhawk.firmware.ApjFirmware')
    @patch('mower_rover.pixhawk.firmware.uploader')
    def test_flash_firmware_progress_tracking(self, mock_uploader_class: Mock, mock_firmware_class: Mock) -> None:
        """Test firmware flash progress tracking."""
        # Mock firmware
        mock_fw = Mock()
        mock_fw.image_size = 1024
        mock_firmware_class.return_value = mock_fw
        
        # Mock uploader
        mock_up = Mock()
        mock_up.identify.return_value = {"board_id": 140, "des": "CubeOrange"}
        
        # Mock upload with progress calls
        def mock_upload(fw, *, verify=True, progress_callback=None):
            if progress_callback:
                progress_callback(256, 1024)    # 25% - erase phase
                progress_callback(512, 1024)    # 50% - program phase  
                progress_callback(1024, 1024)   # 100% - verify phase
            return True
            
        mock_up.upload.side_effect = mock_upload
        mock_uploader_class.return_value.__enter__ = Mock(return_value=mock_up)
        mock_uploader_class.return_value.__exit__ = Mock(return_value=None)
        
        # Collect progress calls
        progress_calls = []
        def progress_cb(phase: str, current: int, total: int) -> None:
            progress_calls.append((phase, current, total))
        
        result = flash_firmware("/dev/pixhawk", Path("test.apj"), progress_cb)
        
        assert result.success is True
        
        # Verify progress phases were called
        phase_names = [call[0] for call in progress_calls]
        assert "sync" in phase_names
        assert "erase" in phase_names
        assert "program" in phase_names
        assert "verify" in phase_names
        assert "reboot" in phase_names

    def test_validate_apj_wrong_magic(self) -> None:
        """Test validating file with wrong magic number."""
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "WrongMagic",
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Invalid APJ magic"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()

    def test_validate_apj_wrong_board_id(self) -> None:
        """Test validating file with wrong board ID."""
        apj_data = {
            "board_id": 999,  # Wrong board ID
            "magic": "APJFWv1",
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Wrong board ID"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()

    def test_validate_apj_invalid_image_size(self) -> None:
        """Test validating file with invalid image size."""
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "APJFWv1",
            "image_size": -1,  # Invalid size
            "image": "base64encodeddata..."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Invalid image_size"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()

    def test_validate_apj_empty_image(self) -> None:
        """Test validating file with empty image data."""
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "APJFWv1",
            "image_size": 524288,
            "image": ""  # Empty image data
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
            json.dump(apj_data, f)
            apj_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Missing or empty image data"):
                validate_apj(apj_path)
        finally:
            apj_path.unlink()


class TestDownloadFirmware:
    """Tests for download_firmware function."""

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_download_firmware_success(self, mock_urlopen: Mock) -> None:
        """Test successful firmware download."""
        # Mock .apj file content
        apj_data = {
            "board_id": BOARD_ID_CUBE_ORANGE,
            "magic": "APJFWv1",
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        apj_bytes = json.dumps(apj_data).encode('utf-8')
        
        # Mock version file content
        version_bytes = b"4.6.3"
        
        # Create mock responses
        def mock_urlopen_side_effect(url: str, timeout: int = 10):
            mock_response = Mock()
            if url.endswith('.apj'):
                mock_response.read.return_value = apj_bytes
            else:  # version file
                mock_response.read.return_value = version_bytes
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            return mock_response
        
        mock_urlopen.side_effect = mock_urlopen_side_effect
        
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            result = download_firmware("stable", (4, 6, 3), cache_dir)
            
            assert result is not None
            assert result.exists()
            assert result.name == "ardurover-stable-4.6.3.apj"
            
            # Verify version file was also downloaded
            version_file = cache_dir / "firmware-version-stable-4.6.3.txt"
            assert version_file.exists()

    def test_download_firmware_unknown_track(self) -> None:
        """Test download with unknown track."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            result = download_firmware("unknown", (4, 6, 3), cache_dir)
            
            assert result is None

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_download_firmware_network_error(self, mock_urlopen: Mock) -> None:
        """Test download with network error."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Network unreachable")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            result = download_firmware("stable", (4, 6, 3), cache_dir)
            
            assert result is None

    @patch('mower_rover.pixhawk.firmware.urlopen')
    def test_download_firmware_invalid_apj(self, mock_urlopen: Mock) -> None:
        """Test download with invalid .apj file."""
        # Mock invalid .apj file content (wrong board ID)
        apj_data = {
            "board_id": 999,  # Wrong board ID
            "magic": "APJFWv1",
            "image_size": 524288,
            "image": "base64encodeddata..."
        }
        apj_bytes = json.dumps(apj_data).encode('utf-8')
        version_bytes = b"4.6.3"
        
        def mock_urlopen_side_effect(url: str, timeout: int = 10):
            mock_response = Mock()
            if url.endswith('.apj'):
                mock_response.read.return_value = apj_bytes
            else:  # version file
                mock_response.read.return_value = version_bytes
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=None)
            return mock_response
        
        mock_urlopen.side_effect = mock_urlopen_side_effect
        
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            result = download_firmware("stable", (4, 6, 3), cache_dir)
            
            # Should return None due to validation failure
            assert result is None
            
            # Invalid file should be cleaned up
            apj_file = cache_dir / "ardurover-stable-4.6.3.apj"
            assert not apj_file.exists()


# Fixture APJ files for testing
@pytest.fixture
def valid_apj_file() -> Path:
    """Create a valid .apj fixture file."""
    apj_data = {
        "board_id": BOARD_ID_CUBE_ORANGE,
        "magic": "APJFWv1",
        "image_size": 524288,
        "image": "base64encodeddata..." * 100  # Make it reasonably long
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
        json.dump(apj_data, f)
        return Path(f.name)


@pytest.fixture
def invalid_board_apj_file() -> Path:
    """Create an .apj fixture file with wrong board ID."""
    apj_data = {
        "board_id": 999,  # Wrong board ID
        "magic": "APJFWv1",
        "image_size": 524288,
        "image": "base64encodeddata..." * 100
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.apj', delete=False) as f:
        json.dump(apj_data, f)
        return Path(f.name)