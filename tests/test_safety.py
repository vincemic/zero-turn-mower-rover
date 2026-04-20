from __future__ import annotations

import pytest

from mower_rover.safety.confirm import (
    ConfirmationAborted,
    SafetyContext,
    requires_confirmation,
)


@requires_confirmation("test action")
def _action(ctx: SafetyContext, value: int = 0) -> int:
    if ctx.dry_run:
        return -1
    return value + 1


def test_dry_run_runs_function_but_skips_actuator_path() -> None:
    ctx = SafetyContext(dry_run=True)
    assert _action(ctx, value=10) == -1


def test_assume_yes_bypasses_prompt() -> None:
    ctx = SafetyContext(assume_yes=True)
    assert _action(ctx, value=10) == 11


def test_missing_context_raises_typeerror() -> None:
    with pytest.raises(TypeError):
        _action(value=10)  # type: ignore[call-arg]


def test_decline_raises_aborted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    ctx = SafetyContext()
    with pytest.raises(ConfirmationAborted):
        _action(ctx, value=10)


def test_safe_stop_runs_all_hooks_and_swallows_errors() -> None:
    calls: list[str] = []

    def good() -> None:
        calls.append("good")

    def bad() -> None:
        calls.append("bad")
        raise RuntimeError("boom")

    ctx = SafetyContext()
    ctx.register_safe_stop(good)
    ctx.register_safe_stop(bad)
    ctx.register_safe_stop(good)

    ctx.safe_stop()  # must not raise

    assert calls == ["good", "bad", "good"]
