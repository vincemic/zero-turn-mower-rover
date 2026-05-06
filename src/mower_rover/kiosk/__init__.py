"""Kiosk operational display package for Jetson."""

from mower_rover.kiosk.app import KIOSK_SOCKET_PATH, run_kiosk
from mower_rover.kiosk.state import SharedState

__all__ = ["KIOSK_SOCKET_PATH", "SharedState", "run_kiosk"]
