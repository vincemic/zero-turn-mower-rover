"""Tests for mower_rover.service — unit file generation, install/uninstall, daemon loop."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mower_rover.config.jetson import (
    JetsonConfig,
    JetsonConfigError,
    load_jetson_config,
)
from mower_rover.safety.confirm import SafetyContext
from mower_rover.service.unit import (
    UNIT_NAME,
    generate_unit_file,
    install_service,
    uninstall_service,
    unit_dir,
)

# ---------------------------------------------------------------------------
# generate_unit_file
# ---------------------------------------------------------------------------


class TestGenerateUnitFile:
    def test_contains_watchdog_sec(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "WatchdogSec=30" in content

    def test_contains_restart_policy(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "Restart=on-failure" in content
        assert "RestartSec=5" in content

    def test_contains_start_limit(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "StartLimitIntervalSec=300" in content
        assert "StartLimitBurst=5" in content

    def test_system_level_contains_user(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="testuser",
            home_dir="/home/testuser",
            health_interval_s=60,
            user_level=False,
        )
        assert "User=testuser" in content

    def test_user_level_omits_user(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="testuser",
            home_dir="/home/testuser",
            health_interval_s=60,
            user_level=True,
        )
        assert "User=" not in content

    def test_contains_exec_start(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/local/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=120,
        )
        assert "ExecStart=/usr/local/bin/mower-jetson service run --health-interval 120" in content

    def test_contains_type_notify(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "Type=notify" in content

    def test_contains_correlation_id_env(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "Environment=MOWER_CORRELATION_ID=daemon" in content

    def test_working_directory(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/opt/mower",
            health_interval_s=60,
        )
        assert "WorkingDirectory=/opt/mower" in content


# ---------------------------------------------------------------------------
# unit_dir
# ---------------------------------------------------------------------------


class TestUnitDir:
    def test_user_level_dir(self) -> None:
        d = unit_dir(user_level=True)
        assert str(d).endswith(".config/systemd/user") or "systemd\\user" in str(d)

    def test_system_level_dir(self) -> None:
        d = unit_dir(user_level=False)
        assert str(d) == "/etc/systemd/system" or d == Path("/etc/systemd/system")


# ---------------------------------------------------------------------------
# install_service
# ---------------------------------------------------------------------------


class TestInstallService:
    def test_dry_run_skips_write(self) -> None:
        ctx = SafetyContext(dry_run=True, assume_yes=True)
        with patch("mower_rover.service.unit.subprocess.run") as mock_run:
            install_service(ctx, user_level=True)
        mock_run.assert_not_called()

    def test_install_writes_unit_and_reloads(self, tmp_path: Path) -> None:
        ctx = SafetyContext(dry_run=False, assume_yes=True)
        fake_dir = tmp_path / "systemd" / "user"

        with (
            patch("mower_rover.service.unit.unit_dir", return_value=fake_dir),
            patch("mower_rover.service.unit.shutil.which", return_value="/usr/bin/mower-jetson"),
            patch("mower_rover.service.unit.getpass.getuser", return_value="testuser"),
            patch("mower_rover.service.unit.Path.home", return_value=tmp_path),
            patch("mower_rover.service.unit.load_jetson_config", return_value=JetsonConfig()),
            patch("mower_rover.service.unit.subprocess.run") as mock_run,
        ):
            install_service(ctx, user_level=True)

        unit_path = fake_dir / f"{UNIT_NAME}.service"
        assert unit_path.exists()
        content = unit_path.read_text(encoding="utf-8")
        assert "WatchdogSec=30" in content
        assert "User=" not in content  # user-level units must not set User=

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "daemon-reload" in args
        assert "--user" in args

    def test_install_system_level_no_user_flag(self, tmp_path: Path) -> None:
        ctx = SafetyContext(dry_run=False, assume_yes=True)
        fake_dir = tmp_path / "systemd" / "system"

        with (
            patch("mower_rover.service.unit.unit_dir", return_value=fake_dir),
            patch("mower_rover.service.unit.shutil.which", return_value="/usr/bin/mower-jetson"),
            patch("mower_rover.service.unit.getpass.getuser", return_value="root"),
            patch("mower_rover.service.unit.Path.home", return_value=tmp_path),
            patch("mower_rover.service.unit.load_jetson_config", return_value=JetsonConfig()),
            patch("mower_rover.service.unit.subprocess.run") as mock_run,
        ):
            install_service(ctx, user_level=False)

        args = mock_run.call_args[0][0]
        assert "--user" not in args
        assert "daemon-reload" in args


# ---------------------------------------------------------------------------
# uninstall_service
# ---------------------------------------------------------------------------


class TestUninstallService:
    def test_dry_run_skips_all(self) -> None:
        ctx = SafetyContext(dry_run=True, assume_yes=True)
        with patch("mower_rover.service.unit.subprocess.run") as mock_run:
            uninstall_service(ctx, user_level=True)
        mock_run.assert_not_called()

    def test_uninstall_stops_disables_removes_reloads(self, tmp_path: Path) -> None:
        ctx = SafetyContext(dry_run=False, assume_yes=True)
        fake_dir = tmp_path / "systemd" / "user"
        fake_dir.mkdir(parents=True)
        unit_path = fake_dir / f"{UNIT_NAME}.service"
        unit_path.write_text("[Unit]\n", encoding="utf-8")

        with (
            patch("mower_rover.service.unit.unit_dir", return_value=fake_dir),
            patch("mower_rover.service.unit.subprocess.run") as mock_run,
        ):
            uninstall_service(ctx, user_level=True)

        assert not unit_path.exists()

        # Should call: stop, disable, daemon-reload (3 calls).
        assert mock_run.call_count == 3
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert any("stop" in c for c in calls)
        assert any("disable" in c for c in calls)
        assert any("daemon-reload" in c for c in calls)

    def test_uninstall_tolerates_not_active(self, tmp_path: Path) -> None:
        ctx = SafetyContext(dry_run=False, assume_yes=True)
        fake_dir = tmp_path / "systemd" / "user"
        fake_dir.mkdir(parents=True)

        def side_effect(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            if "stop" in cmd or "disable" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with (
            patch("mower_rover.service.unit.unit_dir", return_value=fake_dir),
            patch("mower_rover.service.unit.subprocess.run", side_effect=side_effect),
        ):
            # Should not raise despite stop/disable failing.
            uninstall_service(ctx, user_level=True)


# ---------------------------------------------------------------------------
# daemon
# ---------------------------------------------------------------------------


class TestDaemon:
    def test_daemon_sends_ready_and_watchdog(self) -> None:
        mock_notifier = MagicMock()
        notifications: list[str] = []
        mock_notifier.notify = MagicMock(side_effect=lambda s: notifications.append(s))

        shutdown = threading.Event()

        with (
            patch("mower_rover.service.daemon._notifier", mock_notifier),
            patch("mower_rover.service.daemon.read_thermal_zones") as mock_thermal,
            patch("mower_rover.service.daemon.read_power_state") as mock_power,
            patch("mower_rover.service.daemon.read_disk_usage") as mock_disk,
        ):
            mock_thermal.return_value = MagicMock(zones=[])
            mock_power.return_value = MagicMock(mode_name="MAXN")
            mock_disk.return_value = []

            from mower_rover.service.daemon import run_daemon

            def _run() -> None:
                run_daemon(
                    health_interval_s=1,
                    sysroot=Path("/fake"),
                    _shutdown_event=shutdown,
                )

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            time.sleep(2.5)
            shutdown.set()
            t.join(timeout=5)

        assert "READY=1" in notifications
        assert "WATCHDOG=1" in notifications

    def test_daemon_logs_health(self) -> None:
        mock_notifier = MagicMock()
        shutdown = threading.Event()

        with (
            patch("mower_rover.service.daemon._notifier", mock_notifier),
            patch("mower_rover.service.daemon.read_thermal_zones") as mock_thermal,
            patch("mower_rover.service.daemon.read_power_state") as mock_power,
            patch("mower_rover.service.daemon.read_disk_usage") as mock_disk,
        ):
            mock_thermal.return_value = MagicMock(zones=[1, 2])
            mock_power.return_value = MagicMock(mode_name="30W")
            mock_disk.return_value = [MagicMock(), MagicMock()]

            from mower_rover.service.daemon import run_daemon

            def _run() -> None:
                run_daemon(
                    health_interval_s=1,
                    sysroot=Path("/fake"),
                    _shutdown_event=shutdown,
                )

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            time.sleep(2.5)
            shutdown.set()
            t.join(timeout=5)

        # Health readers should have been called at least once.
        assert mock_thermal.call_count >= 1
        assert mock_power.call_count >= 1
        assert mock_disk.call_count >= 1

    def test_daemon_sigterm_on_posix(self) -> None:
        if sys.platform == "win32":
            pytest.skip("SIGTERM not reliably catchable on Windows")

        mock_notifier = MagicMock()

        with (
            patch("mower_rover.service.daemon._notifier", mock_notifier),
            patch("mower_rover.service.daemon.read_thermal_zones") as mock_thermal,
            patch("mower_rover.service.daemon.read_power_state") as mock_power,
            patch("mower_rover.service.daemon.read_disk_usage") as mock_disk,
        ):
            mock_thermal.return_value = MagicMock(zones=[])
            mock_power.return_value = MagicMock(mode_name=None)
            mock_disk.return_value = []

            import os

            from mower_rover.service.daemon import run_daemon

            # This test runs in the main thread to test real signal handling.
            # We use a timer thread to send SIGTERM after a brief delay.
            def _send_sigterm() -> None:
                time.sleep(1.5)
                os.kill(os.getpid(), signal.SIGTERM)

            timer = threading.Thread(target=_send_sigterm, daemon=True)
            timer.start()
            # run_daemon blocks until SIGTERM sets the shutdown flag.
            run_daemon(health_interval_s=60, sysroot=Path("/fake"))
            timer.join(timeout=5)


class TestDaemonNoSdnotify:
    def test_fallback_noop_notifier(self) -> None:
        """Verify the daemon works when sdnotify is not installed."""
        # Simulate ImportError by using a no-op notifier directly.
        from mower_rover.service.daemon import _NoOpNotifier

        notifier = _NoOpNotifier()
        # Should not raise.
        notifier.notify("READY=1")
        notifier.notify("WATCHDOG=1")


# ---------------------------------------------------------------------------
# JetsonConfig new fields
# ---------------------------------------------------------------------------


class TestJetsonConfigServiceFields:
    def test_defaults(self) -> None:
        cfg = JetsonConfig()
        assert cfg.health_interval_s == 60
        assert cfg.service_user_level is True

    def test_round_trip(self, tmp_path: Path) -> None:
        target = tmp_path / "jetson.yaml"
        target.write_text(
            yaml.safe_dump({"health_interval_s": 30, "service_user_level": False}),
            encoding="utf-8",
        )
        cfg = load_jetson_config(target)
        assert cfg.health_interval_s == 30
        assert cfg.service_user_level is False

    def test_missing_fields_use_defaults(self, tmp_path: Path) -> None:
        target = tmp_path / "jetson.yaml"
        target.write_text(yaml.safe_dump({"oakd_required": True}), encoding="utf-8")
        cfg = load_jetson_config(target)
        assert cfg.health_interval_s == 60
        assert cfg.service_user_level is True

    def test_rejects_non_positive_interval(self, tmp_path: Path) -> None:
        target = tmp_path / "jetson.yaml"
        target.write_text(yaml.safe_dump({"health_interval_s": 0}), encoding="utf-8")
        with pytest.raises(JetsonConfigError, match="positive integer"):
            load_jetson_config(target)

    def test_rejects_negative_interval(self, tmp_path: Path) -> None:
        target = tmp_path / "jetson.yaml"
        target.write_text(yaml.safe_dump({"health_interval_s": -5}), encoding="utf-8")
        with pytest.raises(JetsonConfigError, match="positive integer"):
            load_jetson_config(target)

    def test_rejects_non_int_interval(self, tmp_path: Path) -> None:
        target = tmp_path / "jetson.yaml"
        target.write_text(yaml.safe_dump({"health_interval_s": "fast"}), encoding="utf-8")
        with pytest.raises(JetsonConfigError, match="positive integer"):
            load_jetson_config(target)

    def test_rejects_non_bool_user_level(self, tmp_path: Path) -> None:
        target = tmp_path / "jetson.yaml"
        target.write_text(yaml.safe_dump({"service_user_level": "yes"}), encoding="utf-8")
        with pytest.raises(JetsonConfigError, match="service_user_level must be bool"):
            load_jetson_config(target)
