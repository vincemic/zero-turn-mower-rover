"""Pre-flight probe checks for Jetson bringup.

Public surface:
- ``Severity``, ``Status``, ``CheckResult`` — result data types.
- ``register`` — decorator to add a check to the global registry.
- ``run_checks`` — execute registered checks in dependency order.
- ``derive_exit_code`` — map check results to a CLI exit code.
"""

from __future__ import annotations

from mower_rover.probe.registry import (
    CheckResult,
    Severity,
    Status,
    derive_exit_code,
    register,
    run_checks,
)

__all__ = [
    "CheckResult",
    "Severity",
    "Status",
    "derive_exit_code",
    "register",
    "run_checks",
]
