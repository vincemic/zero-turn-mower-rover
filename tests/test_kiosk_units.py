"""Tests for kiosk-related systemd unit file generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mower_rover.config.jetson import JetsonConfig, KioskConfig
from mower_rover.kiosk.units import install_kiosk_units, uninstall_kiosk_units
from mower_rover.safety.confirm import SafetyContext
from mower_rover.service.unit import (
    KIOSK_DATA_UNIT_NAME,
    KIOSK_RENDERER_UNIT_NAME,
    KIOSK_UNIT_NAME,
    MAVPROXY_UNIT_NAME,
    WESTON_UNIT_NAME,
    generate_kiosk_data_unit_file,
    generate_kiosk_renderer_unit_file,
    generate_kiosk_unit_file,
    generate_mavproxy_unit_file,
    generate_service_unit,
    generate_unit_file,
    generate_weston_unit_file,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestKioskConstants:
    def test_weston_unit_name(self) -> None:
        assert WESTON_UNIT_NAME == "mower-weston"

    def test_kiosk_unit_name(self) -> None:
        assert KIOSK_UNIT_NAME == "mower-kiosk"

    def test_mavproxy_unit_name(self) -> None:
        assert MAVPROXY_UNIT_NAME == "mower-mavproxy"


# ---------------------------------------------------------------------------
# service_type parameter on generate_service_unit
# ---------------------------------------------------------------------------


class TestServiceTypeParameter:
    def test_default_service_type_is_notify(self) -> None:
        content = generate_service_unit(
            description="Test",
            exec_start="/usr/bin/test",
            user="testuser",
            home_dir="/home/testuser",
            user_level=False,
        )
        assert "Type=notify" in content

    def test_service_type_simple(self) -> None:
        content = generate_service_unit(
            description="Test",
            exec_start="/usr/bin/test",
            user="testuser",
            home_dir="/home/testuser",
            user_level=False,
            service_type="simple",
        )
        assert "Type=simple" in content
        assert "Type=notify" not in content

    def test_service_type_oneshot(self) -> None:
        content = generate_service_unit(
            description="Test",
            exec_start="/usr/bin/test",
            user="testuser",
            home_dir="/home/testuser",
            user_level=True,
            service_type="oneshot",
        )
        assert "Type=oneshot" in content


# ---------------------------------------------------------------------------
# Backward compatibility — existing unit generation unchanged
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_generate_unit_file_still_notify(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "Type=notify" in content

    def test_generate_unit_file_has_watchdog(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "WatchdogSec=30" in content

    def test_generate_unit_file_restart_on_failure(self) -> None:
        content = generate_unit_file(
            mower_jetson_path="/usr/bin/mower-jetson",
            user="mower",
            home_dir="/home/mower",
            health_interval_s=60,
        )
        assert "Restart=on-failure" in content
        assert "RestartSec=5" in content


# ---------------------------------------------------------------------------
# generate_weston_unit_file
# ---------------------------------------------------------------------------


class TestGenerateWestonUnit:
    def test_type_simple(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "Type=simple" in content

    def test_exec_start(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert (
            "ExecStart=/usr/bin/weston --shell=desktop-shell.so"
            " --drm-device=card0"
            " --renderer=pixman"
            " --idle-time=0"
            " --log=/var/log/mower-jetson/weston.log"
            " --continue-without-input"
        ) in content

    def test_xdg_runtime_dir(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "Environment=XDG_RUNTIME_DIR=/run/user/1000" in content

    def test_restart_always(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "Restart=always" in content

    def test_restart_sec_2(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "RestartSec=2" in content

    def test_start_limit_burst_30(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "StartLimitBurst=30" in content

    def test_no_nvidia_smi(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "nvidia-smi" not in content

    def test_no_exec_condition(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "ExecCondition" not in content

    def test_user_field(self) -> None:
        content = generate_weston_unit_file(user="testuser", home_dir="/home/testuser")
        assert "User=testuser" in content

    def test_multi_user_target(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "WantedBy=multi-user.target" in content

    def test_after_seatd(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "After=seatd.service systemd-modules-load.service" in content

    def test_requires_seatd(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "Requires=seatd.service" in content

    def test_no_after_multi_user_target(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "After=multi-user.target" not in content

    def test_seatd_poll_exec_start_pre(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        assert "[ -S /run/seatd.sock ]" in content
        # seatd poll must appear before DRM device poll
        seatd_pos = content.index("seatd.sock")
        drm_pos = content.index("/dev/dri/card0")
        assert seatd_pos < drm_pos

    def test_exec_start_pre_order(self) -> None:
        content = generate_weston_unit_file(user="vincent", home_dir="/home/vincent")
        lines = [l for l in content.splitlines() if l.startswith("ExecStartPre=")]
        assert len(lines) == 3
        assert "mkdir" in lines[0]
        assert "seatd" in lines[1]
        assert "card0" in lines[2]


# ---------------------------------------------------------------------------
# generate_mavproxy_unit_file
# ---------------------------------------------------------------------------


class TestGenerateMavproxyUnit:
    def test_type_simple(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550", "udp:127.0.0.1:14551"],
        )
        assert "Type=simple" in content

    def test_exec_start_master(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
        )
        assert "--master=/dev/ttyACM0" in content

    def test_exec_start_outputs(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550", "udp:127.0.0.1:14551"],
        )
        assert "--out=udp:127.0.0.1:14550" in content
        assert "--out=udp:127.0.0.1:14551" in content

    def test_daemon_non_interactive(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
        )
        assert "--non-interactive" in content
        assert "--daemon" not in content

    def test_restart_always(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
        )
        assert "Restart=always" in content

    def test_user_field(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
            user="testuser",
            home_dir="/home/testuser",
        )
        assert "User=testuser" in content

    def test_multi_user_target(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
        )
        assert "WantedBy=multi-user.target" in content

    def test_binds_to_pixhawk_device(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
        )
        assert "BindsTo=dev-pixhawk.device" in content

    def test_after_includes_pixhawk_device(self) -> None:
        content = generate_mavproxy_unit_file(
            master="/dev/ttyACM0",
            outputs=["udp:127.0.0.1:14550"],
        )
        assert "After=network.target dev-pixhawk.device" in content


# ---------------------------------------------------------------------------
# generate_kiosk_unit_file
# ---------------------------------------------------------------------------


class TestGenerateKioskUnit:
    def test_type_notify(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "Type=notify" in content

    def test_binds_to_weston(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "BindsTo=mower-weston.service" in content

    def test_after_weston_health_and_mavproxy(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "After=mower-weston.service mower-health.service mower-mavproxy.service" in content

    def test_watchdog_sec(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "WatchdogSec=30" in content

    def test_exec_start(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert (
            "ExecStart=/home/vincent/.local/bin/mower-jetson kiosk run" in content
        )

    def test_user_field(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
            user="vincent",
        )
        assert "User=vincent" in content

    def test_multi_user_target(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "WantedBy=multi-user.target" in content

    def test_wayland_display_env(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "Environment=WAYLAND_DISPLAY=wayland-0" in content

    def test_xdg_runtime_dir_env(self) -> None:
        content = generate_kiosk_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )
        assert "Environment=XDG_RUNTIME_DIR=/run/user/1000" in content


# ---------------------------------------------------------------------------
# install_kiosk_units / uninstall_kiosk_units
# ---------------------------------------------------------------------------


class TestInstallKioskUnits:
    @patch("mower_rover.kiosk.units._systemctl")
    def test_install_writes_three_unit_files(self, mock_ctl: MagicMock, tmp_path):
        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=False, assume_yes=True)
            config = JetsonConfig(kiosk=KioskConfig())
            install_kiosk_units(
                safety,
                config=config,
                target_user="vincent",
                target_home="/home/vincent",
            )

        written = list(tmp_path.glob("*.service"))
        names = sorted(f.stem for f in written)
        assert names == sorted(
            [WESTON_UNIT_NAME, MAVPROXY_UNIT_NAME, KIOSK_UNIT_NAME]
        )

    @patch("mower_rover.kiosk.units._systemctl")
    def test_install_calls_daemon_reload(self, mock_ctl: MagicMock, tmp_path):
        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=False, assume_yes=True)
            config = JetsonConfig(kiosk=KioskConfig())
            install_kiosk_units(
                safety,
                config=config,
                target_user="vincent",
                target_home="/home/vincent",
            )

        daemon_reload_calls = [
            c for c in mock_ctl.call_args_list if c[0][0] == ["daemon-reload"]
        ]
        assert len(daemon_reload_calls) >= 1

    @patch("mower_rover.kiosk.units._systemctl")
    def test_install_enables_all_units(self, mock_ctl: MagicMock, tmp_path):
        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=False, assume_yes=True)
            config = JetsonConfig(kiosk=KioskConfig())
            install_kiosk_units(
                safety,
                config=config,
                target_user="vincent",
                target_home="/home/vincent",
            )

        enable_calls = [
            c[0][0] for c in mock_ctl.call_args_list if "enable" in c[0][0]
        ]
        assert ["enable", f"{WESTON_UNIT_NAME}.service"] in enable_calls
        assert ["enable", f"{MAVPROXY_UNIT_NAME}.service"] in enable_calls
        assert ["enable", f"{KIOSK_UNIT_NAME}.service"] in enable_calls

    @patch("mower_rover.kiosk.units._systemctl")
    def test_install_dry_run_no_files(self, mock_ctl: MagicMock, tmp_path):
        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=True, assume_yes=True)
            config = JetsonConfig(kiosk=KioskConfig())
            install_kiosk_units(
                safety,
                config=config,
                target_user="vincent",
                target_home="/home/vincent",
            )

        written = list(tmp_path.glob("*.service"))
        assert len(written) == 0
        mock_ctl.assert_not_called()

    @patch("mower_rover.kiosk.units._systemctl")
    def test_install_uses_config_mavproxy_master(self, mock_ctl: MagicMock, tmp_path):
        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            kiosk_cfg = KioskConfig(
                mavproxy_master="/dev/ttyUSB0",
                mavproxy_outputs=["udp:127.0.0.1:14560"],
            )
            safety = SafetyContext(dry_run=False, assume_yes=True)
            config = JetsonConfig(kiosk=kiosk_cfg)
            install_kiosk_units(
                safety,
                config=config,
                target_user="vincent",
                target_home="/home/vincent",
            )

        mavproxy_unit = (tmp_path / f"{MAVPROXY_UNIT_NAME}.service").read_text()
        assert "--master=/dev/ttyUSB0" in mavproxy_unit
        assert "--out=udp:127.0.0.1:14560" in mavproxy_unit


class TestUninstallKioskUnits:
    @patch("mower_rover.kiosk.units._systemctl")
    def test_uninstall_removes_unit_files(self, mock_ctl: MagicMock, tmp_path):
        # Create fake unit files
        for name in [WESTON_UNIT_NAME, MAVPROXY_UNIT_NAME, KIOSK_UNIT_NAME]:
            (tmp_path / f"{name}.service").write_text("fake", encoding="utf-8")

        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=False, assume_yes=True)
            uninstall_kiosk_units(safety)

        remaining = list(tmp_path.glob("*.service"))
        assert len(remaining) == 0

    @patch("mower_rover.kiosk.units._systemctl")
    def test_uninstall_calls_daemon_reload(self, mock_ctl: MagicMock, tmp_path):
        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=False, assume_yes=True)
            uninstall_kiosk_units(safety)

        daemon_reload_calls = [
            c for c in mock_ctl.call_args_list if c[0][0] == ["daemon-reload"]
        ]
        assert len(daemon_reload_calls) >= 1

    @patch("mower_rover.kiosk.units._systemctl")
    def test_uninstall_dry_run_keeps_files(self, mock_ctl: MagicMock, tmp_path):
        for name in [WESTON_UNIT_NAME, MAVPROXY_UNIT_NAME, KIOSK_UNIT_NAME]:
            (tmp_path / f"{name}.service").write_text("fake", encoding="utf-8")

        with patch("mower_rover.kiosk.units.unit_dir", return_value=tmp_path):
            safety = SafetyContext(dry_run=True, assume_yes=True)
            uninstall_kiosk_units(safety)

        remaining = list(tmp_path.glob("*.service"))
        assert len(remaining) == 3
        mock_ctl.assert_not_called()


# ---------------------------------------------------------------------------
# generate_kiosk_data_unit_file
# ---------------------------------------------------------------------------


class TestGenerateKioskDataUnitFile:
    def _content(self) -> str:
        return generate_kiosk_data_unit_file(
            mower_jetson_path="/home/vincent/.local/bin/mower-jetson",
        )

    def test_after_includes_weston_and_mavproxy(self) -> None:
        content = self._content()
        assert (
            f"After={WESTON_UNIT_NAME}.service {MAVPROXY_UNIT_NAME}.service"
            in content
        )

    def test_requires_weston(self) -> None:
        content = self._content()
        assert f"Requires={WESTON_UNIT_NAME}.service" in content

    def test_no_requires_mavproxy(self) -> None:
        content = self._content()
        assert f"Requires={MAVPROXY_UNIT_NAME}.service" not in content
        assert "Requires=mower-mavproxy" not in content


# ---------------------------------------------------------------------------
# generate_kiosk_renderer_unit_file
# ---------------------------------------------------------------------------


class TestGenerateKioskRendererUnitFile:
    def _content(self) -> str:
        return generate_kiosk_renderer_unit_file()

    def test_after_includes_kiosk_data(self) -> None:
        content = self._content()
        assert f"{KIOSK_DATA_UNIT_NAME}.service" in content
        assert (
            f"After={WESTON_UNIT_NAME}.service {KIOSK_DATA_UNIT_NAME}.service"
            in content
        )

    def test_start_limit_burst_15(self) -> None:
        content = self._content()
        assert "StartLimitBurst=15" in content
