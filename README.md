# Zero-Turn Mower Rover

CLI tooling for converting a Husqvarna Z254 zero-turn mower into an autonomous RTK-mowing robot.

This is **not** the autopilot firmware, **not** the physical build, and **not** a replacement for Mission Planner / QGroundControl. See [docs/vision/001-zero-turn-mower-rover.md](docs/vision/001-zero-turn-mower-rover.md) and [docs/research/001-mvp-bringup-rtk-mowing.md](docs/research/001-mvp-bringup-rtk-mowing.md).

## Install

Requires Python 3.11+. Recommended via [`pipx`](https://pipx.pypa.io/):

```
pipx install .
```

Or, for development with [`uv`](https://docs.astral.sh/uv/):

```
uv sync --extra dev
```

### Jetson install

On the rover's Jetson AGX Orin (JetPack Ubuntu, aarch64):

```
pipx install .
```

This installs `mower-jetson` on the Jetson. Configure key-based SSH from the
laptop to the Jetson user before using `mower jetson` from the laptop side
(no password auth — `mower jetson` runs OpenSSH with `BatchMode=yes`).

## Commands

### Laptop (`mower`)

- `mower detect` — read-only hardware enumeration over MAVLink (autopilot, GNSS, servos, radio, EKF).
- `mower params snapshot OUT.json` — fetch every autopilot param to a JSON snapshot.
- `mower params diff LEFT RIGHT` — diff two param files (YAML / JSON snapshot / `.parm`); pass `baseline` to use the shipped Z254 baseline.
- `mower params apply FILE` — snapshot, diff, confirm, then write params to the autopilot. Honors `--dry-run` and `--yes`.
- `mower jetson run -- CMD…` — run `CMD` on the Jetson over SSH (key auth only).
- `mower jetson pull REMOTE LOCAL` — copy a file from the Jetson to the laptop; prompts on overwrite (`--yes` to bypass).
- `mower jetson info` — runs `mower-jetson info --json` over SSH and prints the parsed result.
- `mower version` — print the installed version.

Endpoint resolution for `mower jetson …`: `--host/--user/--port/--key` flags
> `MOWER_JETSON_HOST` / `MOWER_JETSON_USER` / `MOWER_JETSON_PORT` / `MOWER_JETSON_KEY`
env vars > `~/.config/mower-rover/laptop.yaml` (Linux/macOS) or
`%APPDATA%\mower-rover\laptop.yaml` (Windows). Example:

```yaml
jetson:
  host: 10.0.0.42
  user: mower
  port: 22
  key_path: ~/.ssh/mower_id_ed25519
```

### Jetson (`mower-jetson`)

- `mower-jetson info` — platform identity (hostname, kernel, JetPack release). Add `--json` for machine output.
- `mower-jetson config show` — print resolved Jetson YAML config (default path: `~/.config/mower-rover/jetson.yaml`). Override with `--config PATH`.
- `mower-jetson version` — print the installed version.

Default MAVLink endpoint is SITL UDP (`udp:127.0.0.1:14550`); pass `--port COM5` (Windows) or `--port /dev/ttyUSB0` (Linux) for the SiK radio link.

## Test

```
pytest -m "not field and not sitl"        # fast unit tests, all platforms
pytest -m sitl                             # requires sim_vehicle.py on PATH (Linux/WSL2)
```

`@pytest.mark.field` tests require physical hardware and are excluded from CI.
