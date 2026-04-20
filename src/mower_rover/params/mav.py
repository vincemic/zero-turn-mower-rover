"""MAVLink param protocol helpers — fetch all params, set + verify a set."""

from __future__ import annotations

import time
from typing import Any

from mower_rover.logging_setup.setup import get_logger
from mower_rover.params.io import ParamSet

# Single-precision verify tolerance.
_VERIFY_TOL = 1e-4


def fetch_params(
    conn: Any,
    *,
    timeout_s: float = 60.0,
    quiet_window_s: float = 1.5,
) -> ParamSet:
    """Request and collect every parameter from the autopilot.

    Sends `PARAM_REQUEST_LIST` and reads `PARAM_VALUE` messages until either
    `param_count` items have arrived, no params have arrived for `quiet_window_s`,
    or the overall `timeout_s` elapses.
    """
    log = get_logger("params").bind(op="fetch")
    conn.mav.param_request_list_send(conn.target_system, conn.target_component)

    collected: dict[str, float] = {}
    expected: int | None = None
    last_rx = time.monotonic()
    deadline = last_rx + timeout_s

    while time.monotonic() < deadline:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
        if msg is None:
            if collected and (time.monotonic() - last_rx) > quiet_window_s:
                break
            continue
        name = _decode_name(msg.param_id)
        collected[name] = float(msg.param_value)
        last_rx = time.monotonic()
        if expected is None:
            expected = int(msg.param_count)
        if expected and len(collected) >= expected:
            break

    log.info(
        "fetch_complete",
        received=len(collected),
        expected=expected,
        elapsed_s=round(time.monotonic() - (deadline - timeout_s), 2),
    )
    return ParamSet.from_mapping(collected)


def apply_params(
    conn: Any,
    params: ParamSet,
    *,
    verify: bool = True,
    per_param_timeout_s: float = 2.0,
    max_retries: int = 3,
) -> dict[str, float]:
    """Apply each param via `param_set_send` and verify by reading back the echo.

    Returns the dict of values actually applied (post-verify). Raises
    `RuntimeError` listing any params that could not be verified.
    """
    from pymavlink import mavutil  # lazy import — keeps test collection cheap

    log = get_logger("params").bind(op="apply")
    applied: dict[str, float] = {}
    failures: list[tuple[str, float, str]] = []

    for name, value in params.as_sorted_dict().items():
        encoded = _encode_name(name)
        success_value: float | None = None
        last_error = "no response"

        for _attempt in range(1, max_retries + 1):
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                encoded,
                float(value),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
            )
            if not verify:
                success_value = float(value)
                break

            echo = _await_param_echo(conn, name, per_param_timeout_s)
            if echo is None:
                last_error = "no PARAM_VALUE echo"
                continue
            if abs(echo - float(value)) <= _VERIFY_TOL:
                success_value = echo
                break
            last_error = f"echo {echo} != requested {value}"

        if success_value is None:
            log.warning("param_apply_failed", name=name, value=value, error=last_error)
            failures.append((name, value, last_error))
        else:
            applied[name] = success_value
            log.debug("param_applied", name=name, value=success_value)

    log.info("apply_complete", applied=len(applied), failures=len(failures))
    if failures:
        joined = ", ".join(f"{n}={v} ({e})" for n, v, e in failures[:10])
        raise RuntimeError(
            f"Failed to apply/verify {len(failures)} param(s): {joined}"
            + (" ..." if len(failures) > 10 else "")
        )
    return applied


def _await_param_echo(conn: Any, name: str, timeout_s: float) -> float | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.25)
        if msg is None:
            continue
        if _decode_name(msg.param_id) == name:
            return float(msg.param_value)
    return None


def _decode_name(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").upper()
    return str(raw).split("\x00", 1)[0].strip().upper()


def _encode_name(name: str) -> bytes:
    encoded = name.upper().encode("ascii")
    if len(encoded) > 16:
        raise ValueError(f"param name {name!r} exceeds 16 bytes")
    return encoded


__all__ = ["apply_params", "fetch_params"]
