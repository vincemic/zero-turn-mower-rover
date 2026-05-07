"""Pixhawk configuration sync — ensure shipped profiles and scripts are applied.

Designed to run on the Jetson during startup (systemd oneshot) or on demand
via ``mower-jetson pixhawk sync``. Idempotent: diffs the autopilot's current
state against the shipped profiles and Lua scripts, applies only if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mower_rover.logging_setup.setup import get_logger
from mower_rover.params.baseline import PROFILES, load_profile
from mower_rover.params.diff import diff_params
from mower_rover.params.io import ParamSet
from mower_rover.params.mav import apply_params, fetch_params
from mower_rover.vslam.lua_deploy import check_and_deploy_lua

_log = get_logger("pixhawk.sync")

# Profiles applied during sync, in order.  Additional profiles can be
# appended here — each is applied as an independent overlay.
DEFAULT_SYNC_PROFILES: tuple[str, ...] = ("safety-defaults",)


@dataclass
class SyncResult:
    """Outcome of a single sync run."""

    params_checked: int = 0
    params_applied: int = 0
    params_already_current: bool = False
    lua_deployed: bool = False
    profiles_applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def sync_params(
    conn: Any,
    *,
    profiles: tuple[str, ...] = DEFAULT_SYNC_PROFILES,
    dry_run: bool = False,
) -> SyncResult:
    """Diff shipped profiles against the live autopilot and apply any drift.

    Parameters
    ----------
    conn:
        An open pymavlink connection.
    profiles:
        Ordered tuple of profile names from ``PROFILES`` to sync.
    dry_run:
        If True, log what would change but don't write.

    Returns
    -------
    SyncResult with details of what was applied (or would be applied).
    """
    result = SyncResult()
    log = _log.bind(op="sync_params", profiles=list(profiles), dry_run=dry_run)

    # Build the combined desired state from all requested profiles.
    combined: dict[str, float] = {}
    for name in profiles:
        if name not in PROFILES:
            msg = f"unknown profile {name!r}"
            log.error("sync_unknown_profile", profile=name)
            result.errors.append(msg)
            continue
        ps = load_profile(name)
        for k in ps:
            combined[k] = ps[k]
    desired = ParamSet.from_mapping(combined)
    result.params_checked = len(desired)

    if not desired:
        log.info("sync_no_params")
        result.params_already_current = True
        return result

    # Fetch current autopilot state (only the keys we care about).
    try:
        current_full = fetch_params(conn)
    except Exception as exc:
        msg = f"fetch_params failed: {exc}"
        log.error("sync_fetch_failed", error=str(exc), exc_info=True)
        result.errors.append(msg)
        return result

    current_subset = ParamSet.from_pairs(
        (k, current_full[k]) for k in desired if k in current_full
    )
    diff = diff_params(current_subset, desired)

    if diff.is_empty:
        log.info("sync_params_current", count=len(desired))
        result.params_already_current = True
        result.profiles_applied = list(profiles)
        return result

    # There are differences — apply them.
    n_changes = len(diff.changed) + len(diff.added)
    log.info(
        "sync_params_drift_detected",
        changed=[c.name for c in diff.changed],
        added=[c.name for c in diff.added],
        total=n_changes,
    )

    if dry_run:
        log.info("sync_dry_run_skip", would_apply=n_changes)
        result.params_applied = n_changes
        result.profiles_applied = list(profiles)
        return result

    # Warn about params in desired but not on firmware (diff.added means
    # present in desired but absent from autopilot's current param set).
    for c in diff.added:
        log.warning(
            "sync_param_not_on_firmware",
            name=c.name,
            value=c.new,
            hint="param may require firmware upgrade",
        )

    # Build set of params that actually need changing (only drifted params).
    to_apply = ParamSet.from_mapping({c.name: c.new for c in diff.changed})

    if to_apply:
        try:
            apply_result = apply_params(conn, to_apply)
        except Exception as exc:
            msg = f"apply_params failed: {exc}"
            log.error("sync_apply_failed", error=str(exc), exc_info=True)
            result.errors.append(msg)
            return result

        if not apply_result.ok:
            for name, value, reason in apply_result.failures:
                msg = f"param {name}={value} failed: {reason}"
                log.error("sync_param_failed", name=name, value=value, reason=reason)
                result.errors.append(msg)

    result.params_applied = len(diff.changed)
    result.profiles_applied = list(profiles)
    log.info("sync_params_applied", count=len(diff.changed), profiles=list(profiles))
    return result


def sync_lua(conn: Any) -> SyncResult:
    """Deploy the AHRS source-switching Lua script if needed.

    Delegates to the existing ``check_and_deploy_lua`` which is already
    idempotent (compares versions, skips if current).
    """
    result = SyncResult()
    try:
        check_and_deploy_lua(conn)
        result.lua_deployed = True
    except Exception as exc:  # noqa: BLE001
        _log.warning("sync_lua_failed", error=str(exc), exc_info=True)
        result.errors.append(f"lua deploy: {exc}")
    return result


def sync_pixhawk(
    conn: Any,
    *,
    profiles: tuple[str, ...] = DEFAULT_SYNC_PROFILES,
    dry_run: bool = False,
) -> SyncResult:
    """Full sync: params + Lua scripts.

    This is the main entry point for the ``mower-jetson pixhawk sync`` command
    and the ``mower-pixhawk-sync.service`` oneshot unit.
    """
    log = _log.bind(op="sync_pixhawk", dry_run=dry_run)
    log.info("sync_start")

    # 1. Sync parameters.
    param_result = sync_params(conn, profiles=profiles, dry_run=dry_run)

    # 2. Deploy Lua scripts (always, even in dry_run — Lua deploy is
    #    read-heavy and only writes when the version differs).
    lua_result = sync_lua(conn)

    # Merge results.
    merged = SyncResult(
        params_checked=param_result.params_checked,
        params_applied=param_result.params_applied,
        params_already_current=param_result.params_already_current,
        lua_deployed=lua_result.lua_deployed,
        profiles_applied=param_result.profiles_applied,
        errors=param_result.errors + lua_result.errors,
    )
    log.info(
        "sync_complete",
        params_applied=merged.params_applied,
        params_current=merged.params_already_current,
        lua_ok=merged.lua_deployed,
        errors=merged.errors or None,
    )
    return merged
