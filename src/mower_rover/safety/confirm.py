"""Safety primitive: confirmation, dry-run, and centralized safe-stop hook.

Every actuator-touching command MUST route through this module. The pattern:

    @requires_confirmation("This will move SERVO1 across full range")
    def servo_cal(ctx: SafetyContext) -> None:
        if ctx.dry_run:
            return
        ...  # actuator command

Tests can pass `assume_yes=True` to bypass the interactive prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import ParamSpec, TypeVar

from mower_rover.logging_setup.setup import get_logger

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class SafetyContext:
    """Shared safety state passed into every actuator-touching command."""

    dry_run: bool = False
    assume_yes: bool = False
    safe_stop_hooks: list[Callable[[], None]] = field(default_factory=list)

    def register_safe_stop(self, hook: Callable[[], None]) -> None:
        self.safe_stop_hooks.append(hook)

    def safe_stop(self) -> None:
        """Run every registered safe-stop hook. Idempotent; logs failures but never raises."""
        log = get_logger("safety")
        for hook in list(self.safe_stop_hooks):
            try:
                hook()
            except Exception as exc:  # noqa: BLE001 - safe-stop must never raise
                log.error(
                    "safe_stop_hook_failed",
                    hook=getattr(hook, "__name__", "?"),
                    error=str(exc),
                )


class ConfirmationAborted(RuntimeError):
    """Raised when an operator declines a confirmation prompt."""


def _prompt(message: str) -> bool:
    try:
        answer = input(f"{message} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def requires_confirmation(
    message: str,
    *,
    ctx_arg: str = "ctx",
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator: require explicit confirmation before executing an actuator command.

    The decorated function MUST accept a `SafetyContext` (default kwarg name `ctx`).
    Honors `ctx.dry_run` (skips the prompt and the function body's actuator path is
    expected to short-circuit on dry_run) and `ctx.assume_yes` (bypasses the prompt
    for headless/test use).
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            ctx = kwargs.get(ctx_arg)
            if ctx is None:
                for arg in args:
                    if isinstance(arg, SafetyContext):
                        ctx = arg
                        break
            if not isinstance(ctx, SafetyContext):
                raise TypeError(
                    f"{func.__name__} must receive a SafetyContext (kwarg '{ctx_arg}')"
                )

            log = get_logger("safety").bind(command=func.__name__)
            if ctx.dry_run:
                log.info("dry_run_skip_confirmation", message=message)
                return func(*args, **kwargs)

            if ctx.assume_yes:
                log.info("assume_yes_skip_confirmation", message=message)
                return func(*args, **kwargs)

            if not _prompt(message):
                log.warning("confirmation_declined", message=message)
                raise ConfirmationAborted(f"Operator declined: {message}")

            log.info("confirmation_accepted", message=message)
            return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "ConfirmationAborted",
    "SafetyContext",
    "requires_confirmation",
]
