"""VSLAM pre-flight probe checks.

Verifies that the VSLAM pipeline (RTAB-Map SLAM + pymavlink bridge) is
operational before autonomous mowing.  All checks accept only a ``sysroot``
path so they can be tested with fake sysfs trees on any platform.

Dependency chain::

    oakd → vslam_process → vslam_bridge → vslam_pose_rate
    (vslam_params and vslam_lua_script are independent of the services)
"""

from __future__ import annotations

import importlib.resources
import subprocess
from pathlib import Path

import yaml

from mower_rover.probe.registry import Severity, register

_VSLAM_SERVICE = "mower-vslam.service"
_BRIDGE_SERVICE = "mower-vslam-bridge.service"
_SOCKET_PATH = "run/mower/vslam-pose.sock"
_VSLAM_CONFIG_PATH = "etc/mower/vslam.yaml"
_LUA_SCRIPT_NAME = "ahrs-source-gps-vslam.lua"
_LUA_SCRIPT_SYSROOT_PATH = "APM/scripts"

# ArduPilot params required for VSLAM integration
_REQUIRED_PARAMS = {
    "VISO_TYPE": 1,
    "SCR_ENABLE": 1,
}
_EK3_SRC2_KEYS = ("EK3_SRC2_POSXY", "EK3_SRC2_VELXY", "EK3_SRC2_YAW")


def _systemctl_is_active(service: str) -> tuple[bool, str]:
    """Check whether a systemd unit is active via ``systemctl is-active``."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, f"{service} is active"
        return False, f"{service} is not active"
    except FileNotFoundError:
        return False, "systemctl not found (not running on systemd host)"
    except subprocess.TimeoutExpired:
        return False, f"systemctl timed out checking {service}"


# ------------------------------------------------------------------
# Pixhawk symlink check (independent — no service dependency)
# ------------------------------------------------------------------


@register("pixhawk_symlink", severity=Severity.CRITICAL, depends_on=())
def check_pixhawk_symlink(sysroot: Path) -> tuple[bool, str]:
    """Check /dev/pixhawk symlink exists."""
    dev_pixhawk = sysroot / "dev" / "pixhawk"
    if dev_pixhawk.exists():
        return True, f"/dev/pixhawk -> {dev_pixhawk.resolve()}"
    return False, "/dev/pixhawk not found; deploy 90-pixhawk-usb.rules"


# ------------------------------------------------------------------
# Service checks (dependency chain: oakd → vslam_process → vslam_bridge)
# ------------------------------------------------------------------


@register("vslam_process", severity=Severity.CRITICAL, depends_on=("oakd",))
def check_vslam_process(sysroot: Path) -> tuple[bool, str]:
    """Verify the RTAB-Map SLAM systemd service is active."""
    return _systemctl_is_active(_VSLAM_SERVICE)


@register("vslam_bridge", severity=Severity.CRITICAL, depends_on=("vslam_process",))
def check_vslam_bridge(sysroot: Path) -> tuple[bool, str]:
    """Verify the VSLAM bridge service is active and socket exists."""
    active, detail = _systemctl_is_active(_BRIDGE_SERVICE)
    if not active:
        return False, detail
    sock = sysroot / _SOCKET_PATH
    if not sock.exists():
        return False, f"{_BRIDGE_SERVICE} active but socket missing: {sock}"
    return True, f"{_BRIDGE_SERVICE} active, socket present"


@register("vslam_pose_rate", severity=Severity.WARNING, depends_on=("vslam_bridge",))
def check_vslam_pose_rate(sysroot: Path) -> tuple[bool, str]:
    """Check VSLAM config declares pose output rate >= 5 Hz."""
    cfg_path = sysroot / _VSLAM_CONFIG_PATH
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return False, f"Cannot read VSLAM config: {exc}"
    try:
        rate = int(raw["vslam"]["pose_output_rate_hz"])
    except (KeyError, TypeError, ValueError):
        return False, "pose_output_rate_hz not set in VSLAM config"
    if rate >= 5:
        return True, f"Pose output rate: {rate} Hz (>= 5 Hz)"
    return False, f"Pose output rate: {rate} Hz (need >= 5 Hz)"


# ------------------------------------------------------------------
# Param / config checks (independent of service state)
# ------------------------------------------------------------------


@register("vslam_params", severity=Severity.CRITICAL, depends_on=("oakd",))
def check_vslam_params(sysroot: Path) -> tuple[bool, str]:
    """Verify VSLAM-related ArduPilot params are configured in VSLAM config.

    Checks the VSLAM config YAML for an ``ardupilot_params`` section
    containing VISO_TYPE=1, SCR_ENABLE=1, and EK3_SRC2_* entries.
    If no ``ardupilot_params`` section exists, falls back to checking
    that the VSLAM config file at least exists and has valid extrinsics
    (proving the operator has configured VSLAM).
    """
    cfg_path = sysroot / _VSLAM_CONFIG_PATH
    if not cfg_path.is_file():
        return False, f"VSLAM config missing: {cfg_path}"
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return False, f"Cannot parse VSLAM config: {exc}"

    # If config has an ardupilot_params section, validate it
    ap_params = (raw or {}).get("ardupilot_params")
    if ap_params and isinstance(ap_params, dict):
        missing = []
        for key, expected in _REQUIRED_PARAMS.items():
            val = ap_params.get(key)
            if val != expected:
                missing.append(f"{key}={expected} (got {val})")
        for key in _EK3_SRC2_KEYS:
            if key not in ap_params:
                missing.append(f"{key} not set")
        if missing:
            return False, f"VSLAM params incomplete: {', '.join(missing)}"
        return True, "VSLAM ArduPilot params configured"

    # Fallback: config exists with valid vslam section
    vslam_section = (raw or {}).get("vslam")
    if vslam_section and isinstance(vslam_section, dict):
        return True, "VSLAM config present (ardupilot_params section not yet added)"
    return False, "VSLAM config file invalid or empty"


@register("vslam_lua_script", severity=Severity.WARNING, depends_on=("oakd",))
def check_vslam_lua_script(sysroot: Path) -> tuple[bool, str]:
    """Verify the AHRS source-switching Lua script is bundled in package data."""
    try:
        ref = importlib.resources.files("mower_rover.params.data").joinpath(
            _LUA_SCRIPT_NAME
        )
        # Check the bundled script is accessible
        with importlib.resources.as_file(ref) as p:
            if p.is_file():
                return True, f"Lua script bundled: {_LUA_SCRIPT_NAME}"
        return False, f"Lua script not found in package data: {_LUA_SCRIPT_NAME}"
    except (TypeError, FileNotFoundError, ModuleNotFoundError):
        return False, f"Cannot locate bundled Lua script: {_LUA_SCRIPT_NAME}"


@register("vslam_confidence", severity=Severity.WARNING, depends_on=("vslam_bridge",))
def check_vslam_confidence(sysroot: Path) -> tuple[bool, str]:
    """Check VSLAM config enables loop closure (proxy for mapping confidence)."""
    cfg_path = sysroot / _VSLAM_CONFIG_PATH
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return False, f"Cannot read VSLAM config: {exc}"
    try:
        loop_closure = raw["vslam"]["loop_closure"]
    except (KeyError, TypeError):
        return False, "loop_closure not set in VSLAM config"
    if loop_closure:
        return True, "Loop closure enabled (supports Medium/High confidence)"
    return False, "Loop closure disabled — mapping confidence will be Low"
