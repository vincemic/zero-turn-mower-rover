# Procedure 001 — Verify Pixhawk USB Enumeration

**Objective:** Confirm the Pixhawk Cube Orange enumerates as `/dev/ttyACM0` on the Jetson AGX Orin and that the udev rule creates a stable `/dev/pixhawk` symlink with disconnect detection.

**Related test:** `tests/test_vslam_field.py::test_field_usb_enumeration`

## Equipment Needed

- Jetson AGX Orin (powered, JetPack 6 flashed, `jetson-harden.sh` applied)
- Pixhawk Cube Orange (powered via mower battery or bench PSU)
- Short USB micro-B cable with strain relief

## Pre-Conditions

- `90-pixhawk-usb.rules` deployed to `/etc/udev/rules.d/` on the Jetson
- udev rules reloaded: `sudo udevadm control --reload-rules`

## Steps

1. **Disconnect** the USB cable between Jetson and Pixhawk if connected.
2. **Verify no ACM device present:**
   ```bash
   ls /dev/ttyACM* 2>/dev/null && echo "FAIL: device present before connect" || echo "OK"
   ```
3. **Connect** the Pixhawk micro-USB cable to the Jetson USB host port.
4. **Wait 3 seconds**, then verify device appeared:
   ```bash
   ls -l /dev/ttyACM0 /dev/pixhawk
   ```
   - `/dev/ttyACM0` must exist (character device)
   - `/dev/pixhawk` must be a symlink pointing to `ttyACM0`
5. **Check permissions:**
   ```bash
   stat -c '%a' /dev/ttyACM0
   ```
   - Expected: `666` (world-readable/writable, no `sudo` needed for MAVLink)
6. **Verify USB autosuspend disabled:**
   ```bash
   cat /sys/bus/usb/devices/*/power/autosuspend | head -5
   ```
   - The Pixhawk device should show `-1`
7. **Verify MAVLink heartbeat:**
   ```bash
   python3 -c "
   from pymavlink import mavutil
   m = mavutil.mavlink_connection('/dev/pixhawk')
   hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
   print('HEARTBEAT received' if hb else 'FAIL: no heartbeat')
   m.close()
   "
   ```
8. **Test disconnect detection — unplug** the USB cable:
   ```bash
   ls /dev/pixhawk 2>/dev/null && echo "FAIL: symlink still present" || echo "OK: symlink removed"
   systemctl status mower-vslam-bridge.service | grep -i "inactive\|dead"
   ```
   - Symlink must disappear
   - If bridge service was running, `BindsTo=dev-ttyACM0.device` should have stopped it

## Pass / Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| `/dev/ttyACM0` appears on connect | Device file exists | Not found within 5 s |
| `/dev/pixhawk` symlink created | Symlink → ttyACM0 | Missing or wrong target |
| Permissions | `666` | Requires `sudo` |
| MAVLink heartbeat | Received within 5 s | Timeout |
| Disconnect removes symlink | `/dev/pixhawk` gone | Symlink persists |

## Data Recording

| Field | Value |
|-------|-------|
| Date | |
| Operator | |
| Jetson serial / IP | |
| USB cable length | |
| Enumeration time (s) | |
| Heartbeat latency (s) | |
| Disconnect detection (s) | |
| Pass / Fail | |
| Notes | |
