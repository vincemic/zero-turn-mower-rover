"""
MAVLink firmware uploader (vendored from ArduPilot).

Copyright (c) 2012-2024 PX4 Development Team. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in
   the documentation and/or other materials provided with the
   distribution.
3. Neither the name PX4 nor the names of its contributors may be
   used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

VENDORING NOTE:
This is a stub implementation for development. Real implementation
to be vendored from ArduPilot at:
https://github.com/ArduPilot/ardupilot/blob/master/Tools/scripts/uploader.py
Commit SHA: [TO_BE_REPLACED_WITH_ACTUAL_COMMIT]
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Callable

# Protocol constants
INSYNC = 0x12
EOC = 0x20
OK = 0x00
FAILED = 0x01
GET_SYNC = 0x21
GET_DEVICE = 0x22
CHIP_ERASE = 0x23
PROG_MULTI = 0x27
READ_MULTI = 0x28
GET_CRC = 0x29
GET_OTP = 0x2a
GET_SN = 0x2b
GET_CHIP = 0x2c
SET_BOOT_DELAY = 0x2d
GET_CHIP_DES = 0x2e
CHIP_VERIFY = 0x24
BOOT_APP = 0x30
GET_VERSION = 0x20


class firmware:
    """ArduPilot .apj firmware file parser."""

    def __init__(self, filename: str | Path) -> None:
        """Load and parse an .apj firmware file."""
        with open(filename, "r") as f:
            self.data = json.load(f)
        
        self.board_id: int = self.data.get("board_id", 0)
        self.image_size: int = self.data.get("image_size", 0)
        self.magic: str = self.data.get("magic", "")
        
        if self.magic != "APJFWv1":
            raise ValueError(f"Invalid APJ magic: expected 'APJFWv1', got '{self.magic}'")


class uploader:
    """MAVLink firmware uploader."""

    def __init__(self, port: str, baud: int = 57600) -> None:
        """Initialize uploader for the given port."""
        self.port = port
        self.baud = baud
        self._port_obj: Any = None
        
    def open(self) -> None:
        """Open serial connection."""
        # Stub implementation
        pass
        
    def close(self) -> None:
        """Close serial connection."""
        # Stub implementation
        pass
        
    def identify(self) -> dict[str, Any]:
        """Identify the bootloader and return device info."""
        # Stub implementation - returns fake CubeOrange info
        return {
            "board_id": 140,
            "board_rev": 0,
            "fw_maxsize": 1024 * 1024,
            "chip": 0x413,  # STM32F4
            "des": "CubeOrange",
        }
        
    def upload(
        self,
        fw: firmware,
        *,
        verify: bool = True,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Upload firmware to the device."""
        # Stub implementation
        total_size = fw.image_size
        if progress_callback:
            for i in range(0, total_size, 1024):
                progress_callback(min(i + 1024, total_size), total_size)
        return True
        
    def send_reboot(self) -> None:
        """Reboot the device."""
        # Stub implementation
        pass
        
    def __enter__(self) -> uploader:
        """Context manager entry."""
        self.open()
        return self
        
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()