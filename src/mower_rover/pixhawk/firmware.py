"""ArduPilot firmware update and version management.

Handles reading current firmware version from the autopilot via MAVLink,
checking for available updates on firmware.ardupilot.org, downloading
firmware files, and validating .apj firmware packages.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import serial

from mower_rover.logging_setup.setup import get_logger
from mower_rover.pixhawk._uploader import EOC, GET_SYNC, INSYNC, OK, uploader
from mower_rover.pixhawk._uploader import firmware as ApjFirmware

_log = get_logger("pixhawk.firmware")

# ArduPilot firmware server base URL
FIRMWARE_BASE_URL = "https://firmware.ardupilot.org/Rover/stable/CubeOrange"
BOARD_ID_CUBE_ORANGE = 140

# Firmware version type codes in flight_sw_version field
VERSION_TYPE_DEV = 0
VERSION_TYPE_ALPHA = 64
VERSION_TYPE_BETA = 128
VERSION_TYPE_RC = 192
VERSION_TYPE_OFFICIAL = 255

# Timeout for MAVLink requests (seconds)
MAVLINK_TIMEOUT = 10.0


@dataclass
class FirmwareInfo:
    """Information about a firmware version."""

    major: int
    minor: int
    patch: int
    type_code: int
    type_name: str
    version_string: str

    def __post_init__(self) -> None:
        """Validate firmware info fields."""
        if not (0 <= self.major <= 255):
            raise ValueError(f"Invalid major version: {self.major}")
        if not (0 <= self.minor <= 255):
            raise ValueError(f"Invalid minor version: {self.minor}")
        if not (0 <= self.patch <= 255):
            raise ValueError(f"Invalid patch version: {self.patch}")
        if not (0 <= self.type_code <= 255):
            raise ValueError(f"Invalid type code: {self.type_code}")


@dataclass
class FlashResult:
    """Result of a firmware flash operation."""

    success: bool
    old_version: FirmwareInfo | None
    new_version: FirmwareInfo | None
    error_message: str | None = None
    bytes_flashed: int = 0
    flash_time_s: float = 0.0


def decode_flight_sw_version(version_uint32: int) -> tuple[int, int, int, int]:
    """Decode ArduPilot flight_sw_version field from AUTOPILOT_VERSION message.

    ArduPilot packs version as: major<<24 | minor<<16 | patch<<8 | type

    Args:
        version_uint32: The flight_sw_version field value

    Returns:
        Tuple of (major, minor, patch, type_code)

    Examples:
        >>> decode_flight_sw_version(0x040603FF)
        (4, 6, 3, 255)
        >>> decode_flight_sw_version(0x04060300)
        (4, 6, 3, 0)
    """
    major = (version_uint32 >> 24) & 0xFF
    minor = (version_uint32 >> 16) & 0xFF
    patch = (version_uint32 >> 8) & 0xFF
    type_code = version_uint32 & 0xFF

    return (major, minor, patch, type_code)


def format_version(version_tuple: tuple[int, int, int, int]) -> str:
    """Format a version tuple into a human-readable string.

    Args:
        version_tuple: (major, minor, patch, type_code)

    Returns:
        Formatted version string

    Examples:
        >>> format_version((4, 6, 3, 255))
        '4.6.3-official'
        >>> format_version((4, 6, 3, 0))
        '4.6.3-dev'
    """
    major, minor, patch, type_code = version_tuple

    type_names = {
        VERSION_TYPE_DEV: "dev",
        VERSION_TYPE_ALPHA: "alpha",
        VERSION_TYPE_BETA: "beta",
        VERSION_TYPE_RC: "rc",
        VERSION_TYPE_OFFICIAL: "official"
    }

    type_name = type_names.get(type_code, f"unknown-{type_code}")
    return f"{major}.{minor}.{patch}-{type_name}"


def read_running_version(conn: Any) -> FirmwareInfo | None:
    """Read the currently running firmware version from the autopilot.

    Sends a AUTOPILOT_VERSION request and decodes the flight_sw_version field.

    Args:
        conn: MAVLink connection object

    Returns:
        FirmwareInfo with current version, or None if unable to read
    """
    try:
        _log.info("Requesting AUTOPILOT_VERSION from flight controller")

        # Request autopilot version
        conn.mav.command_long_send(
            conn.target_system,
            conn.target_component,
            520,  # MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES
            0, 1, 0, 0, 0, 0, 0, 0
        )

        # Wait for AUTOPILOT_VERSION response
        msg = conn.recv_match(type='AUTOPILOT_VERSION', timeout=MAVLINK_TIMEOUT)
        if not msg:
            _log.warning("No AUTOPILOT_VERSION response received")
            return None

        flight_sw_version = msg.flight_sw_version
        _log.debug(f"Received flight_sw_version: 0x{flight_sw_version:08X}")

        # Decode version fields
        major, minor, patch, type_code = decode_flight_sw_version(flight_sw_version)

        # Map type code to name
        type_names = {
            VERSION_TYPE_DEV: "dev",
            VERSION_TYPE_ALPHA: "alpha",
            VERSION_TYPE_BETA: "beta",
            VERSION_TYPE_RC: "rc",
            VERSION_TYPE_OFFICIAL: "official"
        }
        type_name = type_names.get(type_code, f"unknown-{type_code}")

        version_string = format_version((major, minor, patch, type_code))

        firmware_info = FirmwareInfo(
            major=major,
            minor=minor,
            patch=patch,
            type_code=type_code,
            type_name=type_name,
            version_string=version_string
        )

        _log.info(f"Running firmware version: {version_string}")
        return firmware_info

    except Exception as e:
        _log.error(f"Failed to read running firmware version: {e}")
        return None


def check_remote_version(track: str = "stable") -> tuple[int, int, int] | None:
    """Check the latest available firmware version on firmware.ardupilot.org.

    Args:
        track: Firmware track to check ("stable", "beta", "latest")

    Returns:
        Version tuple (major, minor, patch) or None if unable to check
    """
    try:
        # Map track names to URL paths
        track_paths = {
            "stable": "stable",
            "beta": "beta",
            "latest": "latest"
        }

        if track not in track_paths:
            _log.error(f"Unknown firmware track: {track}")
            return None

        url_path = track_paths[track]
        version_url = (
            f"{FIRMWARE_BASE_URL.replace('/stable/', f'/{url_path}/')}"
            "/firmware-version.txt"
        )

        _log.info(f"Checking remote version at: {version_url}")

        with urlopen(version_url, timeout=10) as response:
            version_text = response.read().decode('utf-8').strip()

        _log.debug(f"Remote version text: {version_text}")

        # Parse version string (e.g., "4.6.3" or "4.6.3-beta1")
        # Take only the numeric part before any dash
        version_parts = version_text.split('-')[0].split('.')

        if len(version_parts) < 3:
            _log.error(f"Invalid version format: {version_text}")
            return None

        try:
            major = int(version_parts[0])
            minor = int(version_parts[1])
            patch = int(version_parts[2])

            _log.info(f"Latest {track} version: {major}.{minor}.{patch}")
            return (major, minor, patch)

        except ValueError as e:
            _log.error(f"Failed to parse version numbers from '{version_text}': {e}")
            return None

    except URLError as e:
        _log.warning(f"Network error checking remote version: {e}")
        return None
    except Exception as e:
        _log.error(f"Failed to check remote version: {e}")
        return None


def download_firmware(
    track: str,
    version: tuple[int, int, int],
    cache_dir: Path
) -> Path | None:
    """Download firmware files to cache directory.

    Downloads both the .apj firmware file and firmware-version.txt,
    validates the board ID matches CubeOrange (140).

    Args:
        track: Firmware track ("stable", "beta", "latest")
        version: Version tuple (major, minor, patch)
        cache_dir: Directory to cache downloaded files

    Returns:
        Path to cached .apj file, or None on error
    """
    try:
        # Map track names to URL paths
        track_paths = {
            "stable": "stable",
            "beta": "beta",
            "latest": "latest"
        }

        if track not in track_paths:
            _log.error(f"Unknown firmware track: {track}")
            return None

        url_path = track_paths[track]
        base_url = FIRMWARE_BASE_URL.replace('/stable/', f'/{url_path}/')

        # Ensure cache directory exists
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Download paths
        apj_url = f"{base_url}/ardurover.apj"
        version_url = f"{base_url}/firmware-version.txt"

        version_str = f"{version[0]}.{version[1]}.{version[2]}"
        apj_cache_path = cache_dir / f"ardurover-{track}-{version_str}.apj"
        version_cache_path = cache_dir / f"firmware-version-{track}-{version_str}.txt"

        # Download .apj file
        _log.info(f"Downloading firmware from: {apj_url}")
        with urlopen(apj_url, timeout=30) as response:
            apj_data = response.read()

        with open(apj_cache_path, 'wb') as f:
            f.write(apj_data)

        _log.info(f"Downloaded firmware to: {apj_cache_path}")

        # Download version file
        _log.info(f"Downloading version info from: {version_url}")
        with urlopen(version_url, timeout=10) as response:
            version_data = response.read()

        with open(version_cache_path, 'wb') as f:
            f.write(version_data)

        # Validate the downloaded .apj file
        try:
            validate_apj(apj_cache_path)
            _log.info(f"Firmware validation passed: {apj_cache_path}")
            return apj_cache_path

        except ValueError as e:
            _log.error(f"Downloaded firmware validation failed: {e}")
            # Clean up invalid file
            apj_cache_path.unlink(missing_ok=True)
            return None

    except URLError as e:
        _log.error(f"Network error downloading firmware: {e}")
        return None
    except Exception as e:
        _log.error(f"Failed to download firmware: {e}")
        return None


def validate_apj(apj_path: Path) -> None:
    """Validate an .apj firmware file.

    Checks that the file is valid JSON with the required fields
    and that the board_id matches CubeOrange (140).

    Args:
        apj_path: Path to .apj file to validate

    Raises:
        ValueError: If validation fails
        FileNotFoundError: If file doesn't exist
    """
    if not apj_path.exists():
        raise FileNotFoundError(f"APJ file not found: {apj_path}")

    try:
        with open(apj_path) as f:
            apj_data = json.load(f)

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in APJ file: {e}") from e

    # Check required fields
    required_fields = ["board_id", "magic", "image_size", "image"]
    for field in required_fields:
        if field not in apj_data:
            raise ValueError(f"Missing required field in APJ: {field}")

    # Validate magic number
    magic = apj_data["magic"]
    if magic != "APJFWv1":
        raise ValueError(f"Invalid APJ magic: expected 'APJFWv1', got '{magic}'")

    # Validate board ID
    board_id = apj_data["board_id"]
    if board_id != BOARD_ID_CUBE_ORANGE:
        raise ValueError(
            f"Wrong board ID: expected {BOARD_ID_CUBE_ORANGE} (CubeOrange), "
            f"got {board_id}"
        )

    # Validate image size
    image_size = apj_data["image_size"]
    if not isinstance(image_size, int) or image_size <= 0:
        raise ValueError(f"Invalid image_size: {image_size}")

    # Validate image data exists
    image_data = apj_data["image"]
    if not isinstance(image_data, str) or len(image_data) == 0:
        raise ValueError("Missing or empty image data")

    _log.debug(f"APJ validation passed: board_id={board_id}, size={image_size}")

# Flash Protocol Functions (Phase 2)

def reboot_to_bootloader(conn: Any) -> None:
    """Reboot the autopilot into bootloader mode.

    Sends MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN with param1=3 to enter bootloader,
    then closes the connection as the device will re-enumerate.

    Args:
        conn: MAVLink connection object

    Raises:
        ConnectionError: If the reboot command fails
    """
    try:
        _log.info("Sending reboot to bootloader command")

        # MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN = 246, param1=3 = reboot to bootloader
        conn.mav.command_long_send(
            conn.target_system,
            conn.target_component,
            246,  # MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN
            0,    # confirmation
            3,    # param1: 3 = reboot to bootloader
            0, 0, 0, 0, 0, 0  # param2-7: unused
        )

        # Close connection - device will re-enumerate as bootloader
        _log.debug("Closing MAVLink connection - device rebooting to bootloader")
        conn.close()

        _log.info("Reboot to bootloader command sent successfully")

    except Exception as e:
        _log.error(f"Failed to send reboot to bootloader command: {e}")
        raise ConnectionError(f"Failed to reboot to bootloader: {e}") from e


def wait_for_bootloader(port: str, timeout_s: int = 30) -> str:
    """Wait for bootloader to appear on serial port.

    Polls the serial port with GET_SYNC commands until the bootloader responds
    with INSYNC + OK, indicating it's ready for firmware upload.

    Args:
        port: Serial port path (e.g., "/dev/pixhawk", "COM3")
        timeout_s: Maximum time to wait in seconds

    Returns:
        Port path on success

    Raises:
        TimeoutError: If bootloader doesn't respond within timeout
    """
    _log.info(f"Waiting for bootloader on {port} (timeout: {timeout_s}s)")

    start_time = time.time()

    # Initial delay for USB re-enumeration
    time.sleep(1.0)

    while time.time() - start_time < timeout_s:
        try:
            with serial.Serial(port, baudrate=57600, timeout=1.0) as ser:
                # Send GET_SYNC + EOC
                sync_cmd = bytes([GET_SYNC, EOC])
                ser.write(sync_cmd)
                ser.flush()

                # Check for INSYNC + OK response
                response = ser.read(2)
                if len(response) == 2 and response[0] == INSYNC and response[1] == OK:
                    elapsed_s = time.time() - start_time
                    _log.info(f"Bootloader detected on {port} after {elapsed_s:.1f}s")
                    return port

        except (serial.SerialException, OSError) as e:
            # Port not ready yet - continue polling
            _log.debug(f"Serial port not ready: {e}")

        # Poll every 0.5s
        time.sleep(0.5)

    elapsed_s = time.time() - start_time
    _log.error(f"Bootloader timeout after {elapsed_s:.1f}s on {port}")
    raise TimeoutError(f"Bootloader not detected within {timeout_s}s on {port}")


def flash_firmware(
    port: str,
    apj_path: Path,
    progress_cb: Callable[[str, int, int], None] | None = None
) -> FlashResult:
    """Flash firmware to the autopilot via bootloader.

    Uses the vendored uploader classes to flash an .apj firmware file
    to the autopilot. Provides progress callbacks for each phase.

    Args:
        port: Serial port path with bootloader
        apj_path: Path to .apj firmware file
        progress_cb: Progress callback (phase_name, current, total)

    Returns:
        FlashResult with success status and details
    """
    _log.info(f"Starting firmware flash: {apj_path} -> {port}")

    start_time = time.time()
    result = FlashResult(
        success=False,
        old_version=None,
        new_version=None
    )

    try:
        # Load firmware file
        _log.debug(f"Loading firmware file: {apj_path}")
        fw = ApjFirmware(apj_path)

        # Create uploader and flash
        with uploader(port) as up:
            _log.info("Connecting to bootloader")

            if progress_cb:
                progress_cb("sync", 0, 4)

            # Identify device
            device_info = up.identify()
            _log.info(f"Device identified: {device_info}")

            if progress_cb:
                progress_cb("sync", 1, 4)

            # Flash firmware with progress tracking
            def upload_progress(current: int, total: int) -> None:
                if progress_cb:
                    if current <= total // 4:
                        progress_cb("erase", current * 4, total * 4)
                    elif current <= total // 2:
                        progress_cb("program", current * 2, total * 2)
                    else:
                        progress_cb("verify", current, total)

            _log.info("Starting firmware upload")
            success = up.upload(fw, verify=True, progress_callback=upload_progress)

            if progress_cb:
                progress_cb("reboot", 4, 4)

            if success:
                _log.info("Sending reboot command")
                up.send_reboot()

                result.success = True
                result.bytes_flashed = fw.image_size
                result.flash_time_s = time.time() - start_time

                _log.info(f"Firmware flash completed successfully in {result.flash_time_s:.1f}s")
            else:
                result.error_message = "Upload failed - verify error"
                result.flash_time_s = time.time() - start_time
                _log.error("Firmware upload failed during verify")

    except Exception as e:
        result.error_message = str(e)
        result.flash_time_s = time.time() - start_time
        _log.error(f"Firmware flash failed after {result.flash_time_s:.1f}s: {e}")

    return result
