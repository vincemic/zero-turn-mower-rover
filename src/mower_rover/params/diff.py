"""Structured diff between two `ParamSet`s."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

from mower_rover.params.io import ParamSet

# Single-precision tolerance — MAV_PARAM_TYPE_REAL32 round-trip noise.
_DEFAULT_TOL = 1e-6


@dataclass(frozen=True)
class ParamChange:
    name: str
    old: float | None
    new: float | None

    @property
    def kind(self) -> str:
        if self.old is None:
            return "added"
        if self.new is None:
            return "removed"
        return "changed"


@dataclass
class ParamDiff:
    """Diff result of `diff_params(left, right)` (left = old, right = new)."""

    added: list[ParamChange] = field(default_factory=list)
    removed: list[ParamChange] = field(default_factory=list)
    changed: list[ParamChange] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, Any]:
        def _row(c: ParamChange) -> dict[str, Any]:
            return {"name": c.name, "old": c.old, "new": c.new}

        return {
            "schema": "mower-rover.params.diff.v1",
            "added": [_row(c) for c in self.added],
            "removed": [_row(c) for c in self.removed],
            "changed": [_row(c) for c in self.changed],
        }


def diff_params(
    old: ParamSet,
    new: ParamSet,
    *,
    tolerance: float = _DEFAULT_TOL,
) -> ParamDiff:
    """Diff two param sets. Numeric equality uses an absolute tolerance."""
    old_map = old.as_sorted_dict()
    new_map = new.as_sorted_dict()
    diff = ParamDiff()

    for name in sorted(set(old_map) | set(new_map)):
        ov = old_map.get(name)
        nv = new_map.get(name)
        if ov is None:
            diff.added.append(ParamChange(name, None, nv))
        elif nv is None:
            diff.removed.append(ParamChange(name, ov, None))
        elif abs(ov - nv) > tolerance:
            diff.changed.append(ParamChange(name, ov, nv))
    return diff


def render_diff(
    diff: ParamDiff,
    console: Console,
    *,
    label_old: str = "old",
    label_new: str = "new",
) -> None:
    """Render a diff as a rich table to `console`."""
    if diff.is_empty:
        console.print("[bold green]No parameter differences.[/bold green]")
        return

    table = Table(title=f"Param diff ({label_old} → {label_new})")
    table.add_column("kind")
    table.add_column("name")
    table.add_column(label_old, justify="right")
    table.add_column(label_new, justify="right")

    for c in (*diff.changed, *diff.added, *diff.removed):
        style = {
            "changed": "yellow",
            "added": "green",
            "removed": "red",
        }[c.kind]
        table.add_row(
            c.kind,
            c.name,
            "-" if c.old is None else _fmt(c.old),
            "-" if c.new is None else _fmt(c.new),
            style=style,
        )
    console.print(table)
    console.print(
        f"[bold]{len(diff.changed)} changed, "
        f"{len(diff.added)} added, "
        f"{len(diff.removed)} removed[/bold]"
    )


def _fmt(v: float) -> str:
    if float(v).is_integer():
        return f"{int(v)}"
    return f"{v:g}"


__all__ = ["ParamChange", "ParamDiff", "diff_params", "render_diff"]
