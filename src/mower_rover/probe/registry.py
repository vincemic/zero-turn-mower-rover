"""Probe check registry — register, resolve dependencies, and run checks.

Each check is a callable decorated with :func:`register` that accepts a
``sysroot`` (:class:`~pathlib.Path`) and returns a ``(passed, detail)`` tuple.
:func:`run_checks` executes registered checks in dependency order, skipping
checks whose dependencies failed.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mower_rover.logging_setup.setup import get_logger

_log = get_logger("probe.registry")


class Severity(enum.Enum):
    """Impact level of a check failure."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Status(enum.Enum):
    """Outcome of a single probe check."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of executing a single probe check."""

    name: str
    status: Status
    severity: Severity
    detail: str


@dataclass(frozen=True)
class CheckSpec:
    """Registration metadata for a single probe check."""

    name: str
    severity: Severity
    depends_on: tuple[str, ...]
    fn: Callable[[Path], tuple[bool, str]]


# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, CheckSpec] = {}


def register(
    name: str,
    *,
    severity: Severity,
    depends_on: tuple[str, ...] = (),
) -> Callable[[Callable[[Path], tuple[bool, str]]], Callable[[Path], tuple[bool, str]]]:
    """Decorator that registers a probe check function.

    The decorated function must accept a single ``sysroot`` argument and
    return ``(passed: bool, detail: str)``.
    """

    def decorator(
        fn: Callable[[Path], tuple[bool, str]],
    ) -> Callable[[Path], tuple[bool, str]]:
        if name in _REGISTRY:
            raise ValueError(f"Duplicate check name: {name!r}")
        _REGISTRY[name] = CheckSpec(
            name=name,
            severity=severity,
            depends_on=depends_on,
            fn=fn,
        )
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Dependency resolution & execution
# ---------------------------------------------------------------------------


def _resolve_order(
    specs: dict[str, CheckSpec],
) -> list[str]:
    """Topological sort of check names by *depends_on*.

    Raises :class:`ValueError` on cycles.
    """
    visited: set[str] = set()
    visiting: set[str] = set()  # grey set for cycle detection
    order: list[str] = []

    def _visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Dependency cycle detected involving {name!r}")
        visiting.add(name)
        spec = specs.get(name)
        if spec is not None:
            for dep in spec.depends_on:
                _visit(dep)
        visiting.discard(name)
        visited.add(name)
        order.append(name)

    for n in specs:
        _visit(n)

    return order


def run_checks(
    sysroot: Path = Path("/"),
    only: frozenset[str] | None = None,
) -> list[CheckResult]:
    """Execute registered checks in dependency order.

    Parameters
    ----------
    sysroot:
        Root for file-based checks (``Path("/")`` on real hardware).
    only:
        If provided, run only the named checks (plus their transitive
        dependencies).  Omit to run everything.

    Returns a list of :class:`CheckResult` in execution order.
    """
    # Determine which specs to consider.
    if only is not None:
        # Expand transitive deps so ordering works.
        needed: set[str] = set()

        def _expand(name: str) -> None:
            if name in needed:
                return
            needed.add(name)
            spec = _REGISTRY.get(name)
            if spec is not None:
                for dep in spec.depends_on:
                    _expand(dep)

        for n in only:
            _expand(n)
        specs = {n: _REGISTRY[n] for n in needed if n in _REGISTRY}
    else:
        specs = dict(_REGISTRY)

    ordered = _resolve_order(specs)
    results: list[CheckResult] = []
    failed_names: set[str] = set()

    for name in ordered:
        spec = specs[name]

        # Skip if any dependency failed.
        deps_failed = [d for d in spec.depends_on if d in failed_names]
        if deps_failed:
            results.append(
                CheckResult(
                    name=name,
                    status=Status.SKIP,
                    severity=spec.severity,
                    detail=f"Skipped — dependency failed: {', '.join(deps_failed)}",
                )
            )
            _log.info("check_skipped", check=name, failed_deps=deps_failed)
            failed_names.add(name)
            continue

        # Execute the check.
        try:
            passed, detail = spec.fn(sysroot)
        except Exception as exc:
            passed, detail = False, f"Unexpected error: {exc}"

        status = Status.PASS if passed else Status.FAIL
        if not passed:
            failed_names.add(name)

        results.append(
            CheckResult(
                name=name,
                status=status,
                severity=spec.severity,
                detail=detail,
            )
        )
        _log.info(
            "check_result",
            check=name,
            status=status.value,
            severity=spec.severity.value,
            detail=detail,
        )

    return results


def derive_exit_code(results: list[CheckResult]) -> int:
    """Derive a CLI exit code from check results.

    - 0: all pass or only INFO-severity failures
    - 1: at least one WARNING-severity failure, no CRITICAL
    - 2: at least one CRITICAL-severity failure
    """
    has_critical = any(
        r.status in (Status.FAIL, Status.SKIP) and r.severity == Severity.CRITICAL
        for r in results
    )
    has_warning = any(
        r.status in (Status.FAIL, Status.SKIP) and r.severity == Severity.WARNING
        for r in results
    )
    if has_critical:
        return 2
    if has_warning:
        return 1
    return 0
