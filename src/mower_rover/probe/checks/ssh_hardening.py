"""SSH hardening check — verifies PasswordAuthentication is disabled."""

from __future__ import annotations

import glob
from pathlib import Path

from mower_rover.probe.registry import Severity, register


def _password_auth_disabled(sysroot: Path) -> bool | None:
    """Scan sshd_config and sshd_config.d/*.conf for PasswordAuthentication.

    Returns ``True`` if a definitive ``PasswordAuthentication no`` is found,
    ``False`` if ``PasswordAuthentication yes`` is found, or ``None`` if
    neither is found (OpenSSH defaults to yes).
    """
    files: list[Path] = []
    main_config = sysroot / "etc" / "ssh" / "sshd_config"
    if main_config.is_file():
        files.append(main_config)

    conf_d = sysroot / "etc" / "ssh" / "sshd_config.d"
    for p in sorted(glob.glob(str(conf_d / "*.conf"))):
        files.append(Path(p))

    # Last match wins (same as OpenSSH).
    last_value: str | None = None
    for fpath in files:
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            lower = stripped.lower()
            if lower.startswith("passwordauthentication"):
                parts = lower.split()
                if len(parts) >= 2:
                    last_value = parts[1]

    if last_value == "no":
        return True
    if last_value == "yes":
        return False
    return None  # not explicitly set


@register("ssh_hardening", severity=Severity.WARNING)
def check_ssh_hardening(sysroot: Path) -> tuple[bool, str]:
    """Verify PasswordAuthentication is disabled in sshd_config."""
    result = _password_auth_disabled(sysroot)
    if result is True:
        return True, "PasswordAuthentication disabled"
    if result is False:
        return False, "PasswordAuthentication still enabled"
    # Not explicitly set — OpenSSH defaults to yes.
    return False, "PasswordAuthentication still enabled"
