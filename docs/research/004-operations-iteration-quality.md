---
id: "004"
type: research
title: "Zero-Turn Mower Robotic Conversion — Release 2: Operations & Iteration Quality"
status: ✅ Complete
created: "2026-04-22"
current_phase: "✅ Complete"
vision_source: /docs/vision/001-zero-turn-mower-rover.md
target_release: 2
---

## Introduction

Release 2 adds operational tooling on top of the RTK-only MVP: a live mission monitor, audible status announcements via on-rover TTS, and a post-run log archive with summary. This research investigates the two technology decisions that gate implementation — TTS engine selection for the Jetson and USB audio output configuration on JetPack — and surveys the log-archive design space to ensure the planner has all the information needed.

## Objectives

- Select an offline TTS engine for the Jetson AGX Orin (aarch64, JetPack 6.2.1) that meets latency, licensing, and resource-contention constraints
- Determine USB audio device requirements and ALSA/PulseAudio configuration on headless JetPack
- Confirm that the live-monitoring MAVLink consumer can coexist on the same SiK link with mission control traffic
- Identify the Pixhawk DataFlash log pull mechanism and Jetson log paths for the post-run archive

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | TTS engine & USB audio on Jetson | ✅ Complete | TTS engine selection (Piper, eSpeak-NG, NVIDIA Riva); offline aarch64 constraints; latency benchmarks; licensing; USB audio device selection; ALSA/PulseAudio config on headless JetPack; volume/mute control | 2026-04-22 |
| 2 | Live monitoring & log archive design | ✅ Complete | MAVLink consumer coexistence on SiK link; terminal display patterns for sun-readable output; alert threshold architecture; DataFlash log pull (MAVLink LOG_REQUEST vs. SD card); Jetson log paths; archive bundle format and manifest schema | 2026-04-22 |

## Phase 1: TTS engine & USB audio on Jetson

**Status:** ✅ Complete
**Session:** 2026-04-22

### TTS Engine Comparison

#### Piper TTS

Piper is a fast, local neural TTS engine using VITS models exported to ONNX runtime. It embeds eSpeak-NG internally for phonemization.

**aarch64 Support:** Fully supported. Pre-built `piper_linux_aarch64.tar.gz` binary (24.8 MB) available from the archived `rhasspy/piper` repo (release 2023.11.14-2). The `piper-tts` PyPI package (v1.4.2, April 2026) also installs on aarch64 via pip.

**Latency:** Neural inference via ONNX runtime on CPU. For short phrases (< 10 words) on ARM64, expect ~100–400 ms synthesis time. Well under the 1-second requirement. The CLI tool reloads the model on every invocation (slow), but the Python API and HTTP server keep the model loaded for near-instant repeated synthesis.

**Voice quality:** Excellent neural speech quality. Multiple English voices available (e.g., `en_US-lessac-medium`, `en_US-amy-medium`, `en_GB-alan-medium`). Medium-quality models are ~60 MB ONNX files. Clear and natural enough for outdoor announcements.

**Resource contention:** CPU-only by default (ONNX runtime CPU). Optional CUDA acceleration available via `onnxruntime-gpu` but **not needed** for short phrase synthesis. CPU-only mode means zero GPU contention with future VSLAM (Release 3). On the AGX Orin's 12-core ARM Cortex-A78AE, a single TTS call uses a small fraction of CPU capacity.

**Python API:**

```python
import wave
from piper import PiperVoice

voice = PiperVoice.load("/path/to/en_US-lessac-medium.onnx")
with wave.open("output.wav", "wb") as wav_file:
    voice.synthesize_wav("RTK fix lost", wav_file)

# Streaming API also available:
for chunk in voice.synthesize("Mission complete"):
    write_raw_data(chunk.audio_int16_bytes)

# Volume and speed control:
from piper import SynthesisConfig
config = SynthesisConfig(volume=0.8, length_scale=0.9)
voice.synthesize_wav("Arming", wav_file, syn_config=config)
```

**CLI usage (subprocess approach):**

```bash
echo "RTK fix lost" | piper --model en_US-lessac-medium --output_file alert.wav
```

**Licensing:**

| Version | Repo | License |
|---------|------|---------|
| Original Piper (rhasspy/piper) | Archived Oct 2025 | **MIT** ✅ |
| Piper 1.x (OHF-Voice/piper1-gpl) | Active development | **GPL-3.0** ❌ |
| `piper-tts` v1.4.2 on PyPI | From piper1-gpl | **GPL-3.0** ❌ |
| Pre-built arm64 binary (2023.11.14-2) | From rhasspy/piper | **MIT** ✅ |

The vision requires "Apache/MIT-compatible licensing." The current active Piper package is GPL-3.0, which is incompatible. Three mitigation paths:

1. **Subprocess isolation** — Call the Piper binary as an external process (not imported as a Python library). Under GPL's "mere aggregation" clause, a GPL program invoked via subprocess does not impose GPL on the calling MIT-licensed code.
2. **Old MIT binaries** — The archived `rhasspy/piper` 2023.11.14-2 release includes pre-built `piper_linux_aarch64.tar.gz` under the MIT license. Frozen (no updates) but the architecture for fixed-phrase TTS doesn't need ongoing updates.
3. **Pre-generate WAV files** — Since FR-14 specifies a **fixed phrase set**, all WAV files can be generated once at install/configuration time. The Piper engine is only a build-time dependency, not a runtime dependency. This completely eliminates runtime licensing concerns and runtime resource contention.

#### eSpeak-NG

Compact formant-based speech synthesizer. Written in C, ~few MB total. Supports 100+ languages.

**aarch64 Support:** Available on Ubuntu 22.04 (JetPack 6.x base) via `apt install espeak-ng`. Fully supports aarch64.

**Latency:** Formant synthesis is extremely fast — ~10–50 ms for short phrases on any hardware. Effectively instant.

**Voice quality:** Robotic/synthetic but highly intelligible. For outdoor announcements on a mower (competing with engine noise), intelligibility matters more than naturalness. eSpeak-NG is very clear at high volume.

**Resource contention:** Negligible. Formant synthesis uses minimal CPU, no GPU. Zero contention with VSLAM.

**Python integration:**

```python
# Option A: py-espeak-ng wrapper (Apache-2.0 licensed wrapper, requires espeak-ng binary)
from espeakng import ESpeakNG
esng = ESpeakNG()
esng.voice = 'english-us'
esng.speed = 150
esng.pitch = 50
wav_data = esng.synth_wav('RTK fix lost')  # Returns raw WAV bytes

# Option B: Subprocess (simplest, no Python dependency)
import subprocess
subprocess.run(["espeak-ng", "-v", "en-us", "-w", "output.wav", "RTK fix lost"])
# Or direct audio output:
subprocess.run(["espeak-ng", "-v", "en-us", "RTK fix lost"])
```

**Licensing:** eSpeak-NG engine is GPL-3.0 ❌. The `py-espeak-ng` Python wrapper is Apache-2.0 ✅. Same subprocess/pre-generation mitigation applies.

#### NVIDIA Riva

Enterprise-grade speech AI platform. Uses deep learning models (FastPitch + HiFi-GAN or MagpieTTS) via Triton Inference Server in Docker containers. Client-server architecture with gRPC API.

| Riva Version | Required JetPack | Supported Hardware |
|--------------|------------------|--------------------|
| Riva 2.24.0 (latest) | JetPack 7.0 | Jetson Thor **only** |
| Riva 2.19.0 | JetPack 6.0 | Jetson Orin ✅ |

**Resource requirements:** FastPitch + HiFi-GAN needs ~2 GB GPU memory; MagpieTTS needs ~5.8 GB. Requires Docker, Triton Inference Server, model download from NGC (~2+ GB). This is massive overkill for ~15 short phrases.

**Licensing:** NVIDIA proprietary EULA. Not Apache/MIT-compatible ❌.

**Verdict: Eliminated.** Overkill in every dimension — resource usage, infrastructure complexity, licensing restrictions, deployment burden. Solves a completely different problem (real-time conversational TTS at scale) than what FR-14 needs.

### TTS Engine Comparison Matrix

| Criterion | Piper | eSpeak-NG | Riva | Requirement |
|-----------|-------|-----------|------|-------------|
| **Offline aarch64** | ✅ Yes | ✅ Yes | ✅ (2.19.0) | Must |
| **Latency (short phrase)** | ~100–400 ms | ~10–50 ms | ~200–500 ms* | < 1 s |
| **Voice quality** | Excellent (neural) | Robotic but clear | Excellent | Acceptable outdoor |
| **CPU contention** | Low (ONNX CPU) | Negligible | Low (GPU inference) | Low |
| **GPU contention** | None (CPU default) | None | **2+ GB GPU** ❌ | None (VSLAM R3) |
| **Install size** | ~25 MB binary + ~60 MB model | ~few MB (apt) | ~2+ GB Docker | Hobby budget |
| **Complexity** | Low (binary or pip) | Very low (apt) | Very high (Docker+Triton) | Low |
| **License (engine)** | GPL-3.0 (new) / MIT (old) | GPL-3.0 | Proprietary EULA | Apache/MIT ⚠️ |
| **License mitigation** | Subprocess / pre-gen | Subprocess / pre-gen | None available | — |
| **Python API** | ✅ Rich (PiperVoice) | ✅ py-espeak-ng (Apache-2.0) | ✅ gRPC client | — |

*Riva latency includes gRPC overhead; first call is much slower due to model warm-up.

### Recommended Architecture: Pre-Generated Phrase Set

Since FR-14 specifies a **fixed phrase set** keyed off MAVLink events, the optimal architecture pre-generates all WAV files rather than doing real-time TTS:

```
Install / Config time:              Runtime (on MAVLink event):
┌──────────────┐                    ┌──────────────┐
│ Piper binary │──► WAV files ──►   │ aplay / ALSA │──► USB speaker
│ (one-time)   │    (~15 files)     │ (instant)    │
└──────────────┘                    └──────────────┘
```

**Benefits:**
- Zero runtime latency — `aplay` plays a WAV in < 50 ms
- Zero CPU/GPU contention — no inference during operation
- No runtime TTS dependency — Piper is a build/config tool only
- License-clean — Piper called via subprocess at install time; WAV files are just data
- Fallback trivial — if Piper isn't available, eSpeak-NG generates the same WAVs

**Phrase set (from vision FR-14):**

| Event | Phrase |
|-------|--------|
| Arming | "Vehicle armed" |
| Mode change | "Mode changed to {mode}" |
| RTK fix lost | "RTK fix lost" |
| RTK fix regained | "RTK fix regained" |
| Fence breach | "Fence breach detected" |
| Mission start | "Mission started" |
| Mission complete | "Mission complete" |
| Safe-stop | "Safe stop activated" |

Mode-parameterized phrases (e.g., "Mode changed to Hold") need a WAV per mode — still a small finite set (~5–8 modes: Manual, Hold, Auto, Guided, RTL, etc.).

**Configuration YAML for phrases:**

```yaml
tts:
  engine: piper               # or espeak-ng
  voice: en_US-lessac-medium  # Piper voice name
  phrases_dir: /opt/mower-rover/phrases/
  volume: 0.8                 # 0.0–1.0
  muted: false
  rate_limit_s: 5.0           # minimum seconds between same phrase
```

**Generation command (proposed CLI):**

```bash
mower-jetson tts generate --voice en_US-lessac-medium --output-dir /opt/mower-rover/phrases/
```

### USB Audio on Jetson AGX Orin

#### Audio Stack on JetPack 6.x

JetPack 6.x (based on Ubuntu 22.04 L4T) has two common configurations:

- **Desktop image:** PulseAudio is installed and running as a user service
- **Headless/minimal image:** Only ALSA (kernel + alsa-lib) is present; no PulseAudio

For a headless rover companion computer, **ALSA-only is the correct target**. This avoids PulseAudio daemon overhead and complexity. The `snd-usb-audio` kernel module is built into the JetPack kernel. USB audio devices are detected automatically on plug-in.

#### Configuring USB Audio as Default Output

**Identify the USB device:**

```bash
aplay -l
# card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]

cat /proc/asound/cards
#  0 [tegra          ]: tegra - tegra
#  1 [Device         ]: USB-Audio - USB Audio Device
```

**Set as default** via `/etc/asound.conf` (system-wide), using card name for stability across reboots:

```
# /etc/asound.conf
defaults.pcm.!card "Device"
defaults.ctl.!card "Device"
```

Or via environment variable:

```bash
export ALSA_CARD=Device
```

**Test:**

```bash
speaker-test -c 2          # Plays pink noise on default card
aplay test.wav              # Play a specific file
aplay -D hw:Device test.wav # Play explicitly on USB device
```

#### Volume and Mute Control from Python

**Recommended: `amixer` subprocess (simplest, no extra dependency)**

```python
import subprocess

def set_volume(card: str, percent: int) -> None:
    """Set output volume on the specified ALSA card."""
    subprocess.run(
        ["amixer", "-c", card, "sset", "Speaker", f"{percent}%"],
        check=True, capture_output=True,
    )

def set_mute(card: str, muted: bool) -> None:
    """Mute or unmute the specified ALSA card."""
    state = "mute" if muted else "unmute"
    subprocess.run(
        ["amixer", "-c", card, "sset", "Speaker", state],
        check=True, capture_output=True,
    )

def play_wav(wav_path: str, card: str | None = None) -> None:
    """Play a WAV file via aplay."""
    cmd = ["aplay"]
    if card:
        cmd.extend(["-D", f"hw:{card}"])
    cmd.append(wav_path)
    subprocess.run(cmd, check=True, capture_output=True)
```

**Alternative: `alsaaudio` Python package (native ALSA bindings)**

```python
# pip install pyalsaaudio
import alsaaudio
mixer = alsaaudio.Mixer('Speaker', cardindex=1)
mixer.setvolume(80)   # Set to 80%
mixer.setmute(1)      # Mute
mixer.setmute(0)      # Unmute
```

Needs `libasound2-dev` on the Jetson. Works on aarch64. Recommend subprocess calls to `amixer`/`aplay` for simplicity and zero additional Python dependencies — these are part of `alsa-utils` which is standard on JetPack.

#### USB Audio Device Selection for Outdoor Mower Use

**Recommended setup:**
1. **Generic USB audio adapter** (USB-C/A to 3.5mm DAC, ~$5–15) — small, no driver issues on Linux, class-compliant
2. **Small powered outdoor speaker** (marine/motorcycle-grade 3" speaker with amplifier, IP65+) — powered from the rover's 12V bus via a buck converter or from the Jetson's USB power
3. **Weatherproof enclosure** for the USB adapter connection point

**Volume considerations:** The Kawasaki FR691V produces significant noise (~85–90 dB at operator position). A small USB-powered speaker (~3W) may not suffice; a powered speaker with an external amplifier (5–10W) is more appropriate.

**Budget (C-8):** ~$10 USB sound card + ~$20 marine/outdoor speaker + ~$5 weatherproof box.

#### Known Issues with USB Audio on Jetson

- **Device enumeration order:** USB audio card number can change across reboots if multiple USB devices are present. Mitigate by using card name (not index) in ALSA configuration, or by using a udev rule to assign a stable name.
- **Power management:** Some USB audio devices may be affected by USB autosuspend. If audio drops out, disable autosuspend: `echo -1 > /sys/bus/usb/devices/<device>/power/autosuspend`
- **No HDMI audio by default on headless:** The Tegra HDMI audio device may appear as card 0, pushing USB audio to card 1+. Use card names to avoid confusion.

### TTS Engine Recommendation

**Primary: Piper TTS (pre-generation mode)**
- Best voice quality for announcements
- Pre-generate all phrase WAVs at install time
- Call Piper binary via subprocess (MIT-licensed old binary, or GPL via subprocess isolation)
- Zero runtime resource contention
- ~60 MB model file + 25 MB binary = ~85 MB total on disk

**Fallback: eSpeak-NG**
- Available via `apt install espeak-ng` with zero configuration
- Call via subprocess at install time to generate fallback WAVs
- Lower voice quality but perfectly intelligible outdoors
- ~3 MB total footprint

**Key Discoveries:**
- **Piper TTS is the best-fit engine** — neural quality, ~100–400 ms latency, CPU-only (no GPU contention), aarch64 pre-built binary available. However, the active `piper-tts` PyPI package is now GPL-3.0 (repo moved from MIT rhasspy/piper to GPL OHF-Voice/piper1-gpl in late 2025).
- **The optimal architecture is pre-generated WAV files**, not real-time TTS. Since FR-14 specifies a fixed phrase set, generating all WAVs at install time eliminates runtime latency, resource contention, and runtime licensing concerns entirely.
- **NVIDIA Riva is eliminated** — requires JetPack 7.0 / Jetson Thor for the latest version; Riva 2.19.0 works on Orin but needs 2+ GB GPU memory, Docker/Triton infrastructure, and proprietary EULA.
- **eSpeak-NG is the ideal fallback** — `apt install espeak-ng`, ~10–50 ms synthesis, negligible resource usage. Robotic but clear voice.
- **USB audio on headless JetPack 6.x uses ALSA directly** (no PulseAudio needed). The `snd-usb-audio` kernel module is built-in. Set default card via `/etc/asound.conf` using card name (not index) for stability.
- **Volume/mute control via `amixer` subprocess** is the simplest approach — part of standard `alsa-utils`, no additional Python dependencies needed.
- **All three TTS candidates have licensing complications** vs. the "Apache/MIT-compatible" vision requirement. The subprocess/pre-generation approach is the clean mitigation for both Piper and eSpeak-NG.

| File | Relevance |
|------|-----------|
| `pyproject.toml` | Project dependencies and license (MIT); no existing TTS/audio dependencies |
| `src/mower_rover/cli/jetson.py` | Jetson CLI entry point; TTS commands would be added here |
| `src/mower_rover/config/jetson.py` | Jetson configuration; TTS config would extend this |
| `src/mower_rover/service/unit.py` | Systemd unit management pattern; TTS daemon could follow this |
| `src/mower_rover/service/daemon.py` | Daemon pattern for health monitoring; TTS daemon would be similar |

**Gaps:**
- Exact Piper synthesis latency on Jetson AGX Orin aarch64 not benchmarked (estimates based on Raspberry Pi 4 arm64 reports; AGX Orin will be faster). Field validation needed.
- Specific USB audio adapter model compatibility with Jetson AGX Orin not verified (class-compliant USB audio should work, but specific product testing needed).
- Whether JetPack 6.2.1 headless image includes `alsa-utils` by default or if it needs to be installed separately — needs field verification.
- Volume level needed to overcome Kawasaki FR691V engine noise at operator distance — needs field testing with candidate speaker.

**Assumptions:**
- JetPack 6.x headless images include ALSA kernel support and `snd-usb-audio` module (standard Linux kernel components, NVIDIA's L4T kernel built with USB audio support).
- Class-compliant USB audio devices work out of the box on the Jetson AGX Orin (`snd-usb-audio` handles USB Audio Class 1.0/2.0 universally).
- The phrase set for FR-14 is small enough (~15–25 total WAVs including mode variants) that pre-generation is practical.
- The pre-built MIT-licensed Piper arm64 binary (2023.11.14-2) works on JetPack 6.x aarch64 (statically linked binary targeting generic aarch64 Linux).

## Phase 2: Live monitoring & log archive design

**Status:** ✅ Complete
**Session:** 2026-04-22

### MAVLink Consumer Coexistence on SiK Link

#### Serial Port Exclusivity

A serial port can only be opened by one process/connection at a time. pymavlink's `mavutil.mavlink_connection()` opens the serial device exclusively. Two processes trying to open the same port will conflict.

**Three viable patterns for coexistence:**

**Pattern A: Single pymavlink connection, shared (RECOMMENDED)**

The monitoring consumer and mission control operations share one `mavutil.mavlink_connection()` instance. One `recv_match()` loop dispatches messages to both the monitor display and any command/response handlers. This is how the existing `detect.py` works — a single `_collect()` loop reads HEARTBEAT, GPS_RAW_INT, GPS_RTK, SERVO_OUTPUT_RAW, RADIO_STATUS, and EKF_STATUS_REPORT from one connection.

```python
with open_link(config) as conn:
    _configure_stream_rates(conn)
    while running:
        msg = conn.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            continue
        _update_display(msg)      # monitoring consumer
        _check_alerts(msg)         # alert evaluation
        _handle_command_queue(msg)  # any pending command responses
```

**Pattern B: MAVProxy / mavlink-router as UDP multiplexer**

MAVProxy or mavlink-router opens the serial port and re-broadcasts to multiple UDP endpoints. Each consumer (monitoring CLI, Mission Planner) connects via UDP. This is the standard multi-GCS pattern.

```
Serial (SiK) → MAVProxy → UDP :14550 (monitor CLI)
                         → UDP :14551 (Mission Planner)
```

**Pattern C: Mission Planner TCP/UDP forwarding** — creates a dependency on Mission Planner running; not ideal for field-offline use.

**Recommendation: Pattern A** for the `mower monitor` command. The monitoring CLI IS the GCS during a mowing run. If the operator also wants Mission Planner, Pattern B (MAVProxy multiplexer) is the documented path. The `--endpoint` option already supports UDP/TCP/serial, so the monitor works with any pattern.

#### SiK Radio Bandwidth

From Release 1 research:
- AIR_SPEED=64 kbps, effective throughput ≈ 7 KB/s (after TDM framing overhead)
- Estimated telemetry traffic with SR1_* rates: 600–800 B/s — well under capacity
- ArduPilot auto-adapts rates downward using `RADIO_STATUS.txbuf` percentage
- The monitoring consumer adds **zero** additional bandwidth — it reads messages ArduPilot already streams

#### ArduPilot Message Rate Mechanism

Four mechanisms for controlling message rates:

1. **`SRx_` parameters** (persistent, stored on reboot): Set `SR1_EXT_STAT=2`, `SR1_POSITION=2`, etc. **Recommended for the mower — set once, always active.**
2. **`REQUEST_DATA_STREAM`** (deprecated): Requests groups of messages at a rate.
3. **`SET_MESSAGE_INTERVAL`** (MAV_CMD 511): Per-message rate control. Best for adding specific messages not in a stream group.
4. **`REQUEST_MESSAGE`** (MAV_CMD 512): One-shot request for a single message instance.

**Key finding:** `RPM` is in the `SR1_EXTRA3` stream group along with `BATTERY_STATUS`, `EKF_STATUS_REPORT`, and `VIBRATION`. Setting `SR1_EXTRA3=2` (2 Hz) covers all engine monitoring needs.

**Stream rate conflict warning:** If the monitoring CLI and Mission Planner both set different stream rates, ArduPilot takes the most recent request. Setting `SERIAL1_OPTIONS` bit 12 ("Ignore Streamrate") prevents GCS overrides.

#### Messages Needed for Monitoring Display

| Message | Stream Group | Content | Rate |
|---------|-------------|---------|------|
| `HEARTBEAT` | Always 1 Hz | Mode, armed state, system status | 1 Hz |
| `GLOBAL_POSITION_INT` | `SR1_POSITION` | Lat/lon/alt for position tracking | 2 Hz |
| `GPS_RAW_INT` | `SR1_EXT_STAT` | Fix type, satellites, HDOP, yaw | 2 Hz |
| `GPS_RTK` | `SR1_EXT_STAT` | RTK fix status, IAR hypotheses | 2 Hz |
| `MISSION_CURRENT` | `SR1_EXT_STAT` | Current waypoint (coverage progress) | 2 Hz |
| `SYS_STATUS` | `SR1_EXT_STAT` | Onboard sensor health | 2 Hz |
| `BATTERY_STATUS` | `SR1_EXTRA3` | Bus voltage (engine-running indicator) | 2 Hz |
| `RPM` | `SR1_EXTRA3` | Engine RPM from inductive pickup | 2 Hz |
| `EKF_STATUS_REPORT` | `SR1_EXTRA3` | EKF health flags | 2 Hz |
| `VFR_HUD` | `SR1_EXTRA2` | Groundspeed, heading | 2 Hz |
| `RADIO_STATUS` | SiK-injected | Link RSSI, noise, txbuf | ~1 Hz |
| `STATUSTEXT` | Event-driven | ArduPilot alerts/warnings | Async |
| `FENCE_STATUS` | `SR1_EXT_STAT` | Fence breach status | 2 Hz |

#### pymavlink Long-Running Consumer Pattern

Synchronous polling loop with timeout, consistent with existing codebase (`detect.py`):

```python
def monitor_loop(conn, display, alert_engine, shutdown_event):
    """Main monitoring loop — reads messages and updates display + alerts."""
    while not shutdown_event.is_set():
        msg = conn.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            display.mark_stale()  # no messages for 0.5s
            continue
        mtype = msg.get_type()
        display.update(mtype, msg)
        alert_engine.evaluate(mtype, msg)
```

Heartbeat watchdog: if no `HEARTBEAT` received for >5 s, flag link loss (mirrors `FS_GCS_TIMEOUT=5` on ArduPilot).

### Terminal Display Patterns for Sun-Readable Output

#### Existing Codebase Patterns

The codebase uses **Rich** (`rich>=13.7` in pyproject.toml) extensively:
- `detect.py`: `Console`, `Table` for static output
- `jetson.py`: `Console`, `Table`, `Live`, `Panel` for thermal monitoring
- `params/diff.py`: `Console`, `Table` for colored diff display

Key pattern from `jetson.py` thermal command:
```python
with Live(console=console, refresh_per_second=1) as live:
    while True:
        snapshot = read_thermal_zones()
        live.update(_render_thermal_table(snapshot))
        time.sleep(interval)
```

This `rich.live.Live` pattern is the correct foundation for the monitoring display.

#### Sun-Readable Design Recommendations

1. **Rich's `Live` + `Table` + `Panel`** — already proven in the codebase
2. **High contrast = bold text + semantic colors only (green/red/yellow)** — avoid pastel or muted colors
3. **Minimize color reliance** — use text symbols alongside colors: `✓ RTK Fixed`, `⚠ Float`, `✗ No Fix`
4. **Large, uncluttered layout** — few rows, wide columns, key metrics prominently displayed
5. **No curses/blessed** — Rich handles terminal clearing and re-rendering on Windows and Linux

**Proposed display layout:**

```
┌─── Mower Monitor ──────────────────────────────────┐
│ Mode: AUTO  Armed: YES  WP: 45/120  Speed: 2.1 m/s │
│ RTK: Fixed (★★★★★)  Sats: 24  HDOP: 0.8            │
│ Engine: RUNNING  RPM: 3200  Volts: 14.1             │
│ Radio: RSSI 187  TxBuf 95%                           │
│ Alerts: 0 active                                     │
│ Updated: 14:32:05  Link: OK (3.2s ago)               │
└──────────────────────────────────────────────────────┘
```

6. **`--json` flag** for machine-readable output (consistent with every other CLI command)
7. **`--watch` flag** enters Live mode; without it prints a single snapshot
8. **Narrow terminal handling** — Rich wraps automatically; degrade gracefully at 80 columns minimum
9. **SSH sessions** — Rich works over SSH; `NO_COLOR` env var handles dumb terminals

**Rich components (no new dependencies):**

| Component | Use Case |
|-----------|----------|
| `rich.live.Live` | Real-time updating display |
| `rich.table.Table` | Structured data presentation |
| `rich.panel.Panel` | Bordered status panel |
| `rich.text.Text` | Styled status labels |
| `rich.console.Console` | Output control, color detection |

### Alert Threshold Architecture

#### Configuration Design

YAML config extending the existing `LaptopConfig` pattern:

```yaml
monitor:
  alerts:
    rtk_fix_min: 5              # GPS_RAW_INT.fix_type: 5=RTK_FLOAT, 6=RTK_FIXED
    battery_voltage_min: 12.0   # Below = engine off
    battery_voltage_warn: 13.0  # Below alternator charging range
    engine_rpm_min: 1500        # Below = engine stalled
    engine_rpm_warn: 1700       # Below governed idle
    radio_rssi_min: 50          # RADIO_STATUS.rssi
    radio_txbuf_min: 20         # RADIO_STATUS.txbuf %
    ekf_variance_max: 0.8       # Matches FS_EKF_THRESH
    heartbeat_timeout_s: 5.0    # Seconds without HEARTBEAT = link loss
    alert_cooldown_s: 30.0      # Minimum seconds between repeated alerts
    alert_hysteresis_count: 3   # Consecutive bad readings before alerting
```

#### Alert Events

| Event | Source Message | Condition | Severity |
|-------|--------------|-----------|----------|
| RTK fix degraded | `GPS_RAW_INT` | `fix_type < rtk_fix_min` | CRITICAL |
| RTK fix lost | `GPS_RAW_INT` | `fix_type < 3` (no 3D fix) | CRITICAL |
| Mode change | `HEARTBEAT` | `custom_mode` changed | INFO |
| Disarmed unexpectedly | `HEARTBEAT` | `base_mode & 128 == 0` while monitoring | CRITICAL |
| Fence breach | `FENCE_STATUS` | `breach_status != 0` | CRITICAL |
| Engine RPM low | `RPM` | `rpm1 < engine_rpm_warn` | WARN |
| Engine stall | `RPM` | `rpm1 < engine_rpm_min` for N readings | CRITICAL |
| Battery voltage low | `BATTERY_STATUS` | `voltage < battery_voltage_warn` | WARN |
| Battery voltage critical | `BATTERY_STATUS` | `voltage < battery_voltage_min` | CRITICAL |
| Radio RSSI low | `RADIO_STATUS` | `rssi < radio_rssi_min` | WARN |
| Link loss | HEARTBEAT absence | `>heartbeat_timeout_s` since last HB | CRITICAL |
| EKF variance high | `EKF_STATUS_REPORT` | variance > threshold | WARN |
| ArduPilot warning | `STATUSTEXT` | severity <= `MAV_SEVERITY_WARNING` | WARN |

#### Rate-Limiting / Hysteresis

Anti-flapping design:

1. **Hysteresis counter:** An alert fires only after N consecutive readings exceed the threshold (`alert_hysteresis_count`). Prevents flapping from noisy sensors.
2. **Cooldown period:** After an alert fires, the same alert type cannot re-fire for `alert_cooldown_s` seconds.
3. **Recovery notification:** When an alert condition clears (N consecutive good readings), emit a "resolved" notification.

```python
@dataclass
class AlertState:
    name: str
    threshold: float
    consecutive_bad: int = 0
    consecutive_good: int = 0
    last_fired_at: float | None = None
    is_active: bool = False

    def evaluate(self, value: float, now: float, config: AlertConfig) -> AlertEvent | None:
        if self._is_bad(value):
            self.consecutive_bad += 1
            self.consecutive_good = 0
            if (self.consecutive_bad >= config.hysteresis_count
                and not self.is_active
                and (self.last_fired_at is None
                     or now - self.last_fired_at >= config.cooldown_s)):
                self.is_active = True
                self.last_fired_at = now
                return AlertEvent(self.name, AlertSeverity.WARN, value)
        else:
            self.consecutive_good += 1
            self.consecutive_bad = 0
            if self.is_active and self.consecutive_good >= config.hysteresis_count:
                self.is_active = False
                return AlertEvent(self.name, AlertSeverity.RESOLVED, value)
        return None
```

#### Alert → TTS Integration

Alerts connect to TTS (Phase 1 pre-generated WAV architecture) via:

1. Alert event emitted → structlog logs the alert (NFR-4)
2. Alert event emitted → if TTS daemon is running on the Jetson, send the alert phrase key via SSH: `mower-jetson tts play engine-stall`
3. TTS daemon maps phrase key to pre-generated WAV file and plays via `aplay`

The alert engine runs on the **laptop** (where pymavlink reads MAVLink). The TTS daemon runs on the **Jetson** (where the USB speaker is). If TTS is not available, alerts still appear on the terminal and in structlog.

### DataFlash Log Pull Mechanism

#### ArduPilot Log Storage

ArduPilot stores DataFlash logs on the Pixhawk's SD card (Cube Orange has a microSD slot). Logs are binary `.BIN` files in `/APM/LOGS/` with sequential numbering. `LASTLOG.TXT` contains the current log number.

#### MAVFTP (Recommended)

MAVFTP is ArduPilot's MAVLink File Transfer Protocol implementation. pymavlink includes a full client in `pymavlink/mavftp.py` (class `MAVFTP`).

```python
from pymavlink import mavftp

def download_latest_log(conn, local_dir: Path) -> Path:
    """Download the latest DataFlash log via MAVFTP."""
    ftp = mavftp.MAVFTP(conn.target_system, conn.target_component)
    result = ftp.cmd_list(['/APM/LOGS/'])
    # Parse file listing to find latest .BIN
    local_path = local_dir / f"{log_name}.bin"
    ftp.cmd_get([f'/APM/LOGS/{log_name}', str(local_path)])
    return local_path
```

**Advantages:** Works over any MAVLink link (serial, UDP, TCP) including SiK radio; no physical SD card access needed; pymavlink already has the client; supports directory listing and `BurstReadFile`.

**Disadvantage:** Slow over SiK radio — at 7 KB/s effective throughput, a 10 MB log takes ~24 minutes.

#### Direct SD Card Read (Alternative, not default)

Pull the SD card from the Cube Orange and read directly on laptop. Much faster but requires physical access, disarming + power down, and is not automatable.

**Recommendation:** MAVFTP over MAVLink as the primary mechanism. Direct SD card read as a documented escape hatch. For large logs, suggest the operator connect via USB (direct serial at 115200+ baud) for faster downloads.

#### DataFlash Log Size Estimates

| Logging Rate | Duration | Approximate Size |
|-------------|----------|-----------------|
| Default (most messages at 10 Hz) | 30 min | 10–20 MB |
| Reduced (key messages at 2 Hz) | 30 min | 3–8 MB |
| Full (all messages at max rate) | 30 min | 30–60 MB |

### Jetson Log Paths

#### structlog JSON Logs

From `logging_setup/setup.py`:
- **Linux path:** `$XDG_DATA_HOME/mower-rover/logs/` (defaults to `~/.local/share/mower-rover/logs/`)
- **File naming:** `mower-{timestamp}-{correlation_id}.jsonl`
- **Format:** JSONL (one JSON object per line)
- **Correlation ID:** Propagated from laptop via `MOWER_CORRELATION_ID` env var (from `transport/ssh.py`)

#### Relevant Jetson Logs for Archive

| Log Source | Path | Content |
|-----------|------|---------|
| structlog JSONL | `~/.local/share/mower-rover/logs/mower-*.jsonl` | Application logs (health, TTS, probes) |
| systemd journal | `journalctl -u mower-health` | Health daemon output |
| JetPack system | `/var/log/syslog` or `journalctl` | System-level events |

#### Log Collection Strategy

1. SSH + `find` to list logs filtered by correlation ID
2. SCP via existing `JetsonClient.pull()` from `transport/ssh.py`
3. journalctl export: `journalctl -u mower-health --since "..." --until "..." -o json`

The correlation ID is the key — the laptop propagates it to the Jetson via SSH, and all Jetson-side structlog entries include it, enabling log stitching across both sides.

### Archive Bundle Format and Manifest Schema

#### Archive Format: tar.gz (Recommended)

Standard, smallest, cross-platform (Python `tarfile` module). The `--json` flag on the archive command can output the manifest without extracting.

#### Archive Directory Structure

```
mower-run-20260422T143000-{corr_id}/
├── manifest.json          # Archive metadata + file inventory
├── summary.json           # Run summary (JSON for tooling)
├── params-at-start.json   # Parameter snapshot at run start
├── pixhawk/
│   └── 00000042.BIN       # DataFlash log from Pixhawk
├── laptop/
│   └── mower-*.jsonl      # Laptop-side structlog
├── jetson/
│   ├── mower-*.jsonl      # Jetson-side structlog
│   └── health-journal.jsonl  # journalctl export
└── alerts.jsonl            # Alert events from the run
```

#### Manifest Schema

```json
{
  "schema": "mower-rover.run-archive.v1",
  "correlation_id": "a1b2c3d4e5f6",
  "created_at": "2026-04-22T14:30:00Z",
  "run_start": "2026-04-22T14:00:00Z",
  "run_end": "2026-04-22T14:28:00Z",
  "duration_s": 1680,
  "vehicle": {
    "endpoint": "COM5",
    "firmware_version": "0x040600FF",
    "vehicle_type": 10
  },
  "files": [
    {
      "path": "params-at-start.json",
      "type": "param-snapshot",
      "size_bytes": 12345,
      "sha256": "abc123..."
    },
    {
      "path": "pixhawk/00000042.BIN",
      "type": "dataflash-log",
      "size_bytes": 15728640,
      "sha256": "def456..."
    }
  ],
  "params_hash": "sha256:...",
  "mission_hash": "sha256:..."
}
```

#### Summary Report Schema

```json
{
  "schema": "mower-rover.run-summary.v1",
  "correlation_id": "a1b2c3d4e5f6",
  "duration_s": 1680,
  "duration_human": "28m 0s",
  "waypoints_completed": 120,
  "waypoints_total": 120,
  "coverage_pct": 100.0,
  "distance_m": 4250.0,
  "avg_speed_ms": 2.0,
  "rtk_fix_pct": 98.5,
  "engine": {
    "avg_rpm": 3200,
    "min_rpm": 2800,
    "avg_voltage": 14.1
  },
  "alerts": [
    {
      "timestamp": "2026-04-22T14:15:33Z",
      "type": "rtk_fix_degraded",
      "severity": "warn",
      "detail": "Fix type dropped to FLOAT for 12s"
    }
  ],
  "link_quality": {
    "avg_rssi": 185,
    "min_rssi": 142,
    "packet_loss_pct": 0.1
  }
}
```

#### Integration with Existing Architecture

The archive builds on existing patterns:
- `write_json_snapshot()` from `params/io.py` — reuse for `params-at-start.json`
- `JetsonClient.pull()` from `transport/ssh.py` — reuse for pulling Jetson logs
- `configure_logging()` correlation ID — already propagated across laptop and Jetson
- structlog JSON output — already produces JSONL, just needs collection

**`mower run-archive` command flow:**
1. Fetch current param snapshot (reuse `fetch_params` + `write_json_snapshot`)
2. Download DataFlash log via MAVFTP
3. Pull Jetson logs via SSH/SCP (correlation ID-filtered)
4. Collect laptop-side logs (already on disk)
5. Compute checksums, build manifest
6. Generate summary from collected alert events + mission progress
7. Bundle into tar.gz

**Key Discoveries:**
- pymavlink serial ports are exclusive — the monitoring consumer MUST share one `mavlink_connection` instance; multi-GCS requires MAVProxy/mavlink-router UDP multiplexer
- SiK radio bandwidth (~7 KB/s) is ample for monitoring (600–800 B/s telemetry); the monitor adds zero additional bandwidth
- `RPM` message is in `SR1_EXTRA3` stream group alongside `BATTERY_STATUS` and `EKF_STATUS_REPORT` — setting `SR1_EXTRA3=2` covers all engine monitoring
- Rich `Live` + `Table` + `Panel` is already proven in the codebase (Jetson thermal command) — correct pattern for live monitor display
- MAVFTP is the recommended DataFlash log download mechanism — pymavlink includes a full client (`mavftp.py`); download speed over SiK is ~24 min for 10 MB
- Correlation ID propagation from laptop → Jetson via `MOWER_CORRELATION_ID` is already implemented in `transport/ssh.py` — the key for stitching archive logs
- Alert hysteresis (N consecutive bad readings) + cooldown prevents flapping; alerts connect to TTS via SSH command to Jetson

| File | Relevance |
|------|-----------|
| `src/mower_rover/mavlink/connection.py` | ConnectionConfig, open_link; foundation for monitoring consumer |
| `src/mower_rover/cli/detect.py` | Existing recv_match polling pattern; template for monitor |
| `src/mower_rover/cli/jetson.py` | Rich Live + Table + Panel patterns; direct template for monitor UI |
| `src/mower_rover/params/mav.py` | fetch_params/apply_params MAVLink sequences |
| `src/mower_rover/params/io.py` | write_json_snapshot schema; reusable for archive manifests |
| `src/mower_rover/logging_setup/setup.py` | structlog config, correlation IDs, log paths |
| `src/mower_rover/transport/ssh.py` | JetsonClient.pull() for SCP; correlation ID propagation |
| `src/mower_rover/config/laptop.py` | LaptopConfig YAML schema; extend for alert thresholds |
| `src/mower_rover/config/jetson.py` | JetsonConfig log_dir; Jetson log paths |
| `src/mower_rover/service/daemon.py` | Health daemon loop; similar to monitoring pattern |
| `src/mower_rover/params/data/z254_baseline.yaml` | SR1_* stream rates; must include monitoring rates |

**Gaps:**
- MAVFTP integration with pymavlink's connection object needs validation in SITL
- Exact DataFlash log path on Cube Orange SD card (`/APM/LOGS/` vs. `@MAV_LOG`) should be confirmed
- Coverage progress calculation (waypoints completed / total) requires confirming `MISSION_CURRENT.seq` behavior in Auto mode

**Assumptions:**
- Monitoring CLI is the primary GCS during autonomous mowing (no simultaneous Mission Planner); MAVProxy multiplexer is the documented path for multi-GCS
- DataFlash log sizes for a 30-minute mowing run are 5–20 MB based on typical ArduPilot Rover logging rates
- `SR1_EXTRA3` at 2 Hz is sufficient for engine RPM monitoring

## Overview

Release 2 adds three operational capabilities to the MVP: live mission monitoring, audible TTS announcements on the rover, and post-run log archiving. This research resolved the two technology decisions that gate implementation and mapped out the design space for all three features.

### Key Findings Summary

1. **Pre-generated WAV architecture eliminates runtime TTS complexity.** Since FR-14 specifies a fixed phrase set (~15–25 phrases including mode variants), the optimal approach generates all WAV files at install time using Piper TTS (primary) or eSpeak-NG (fallback), then plays them instantly via `aplay` at runtime. This avoids runtime resource contention with future VSLAM, eliminates licensing concerns (GPL engines invoked via subprocess at build time only), and delivers zero-latency playback.

2. **Piper TTS is the recommended generator; eSpeak-NG is the fallback.** Piper produces excellent neural speech quality with ~100–400 ms latency on aarch64 CPU. The original MIT-licensed aarch64 binary (rhasspy/piper 2023.11.14-2) is available; the active repo has moved to GPL-3.0. eSpeak-NG is installable via apt with negligible resource usage but robotic voice quality. NVIDIA Riva is eliminated — overkill infrastructure, GPU-hungry, proprietary.

3. **USB audio on headless JetPack 6.x is ALSA-only.** The `snd-usb-audio` kernel module is built into the JetPack kernel. Configuration via `/etc/asound.conf` with card names (not indices) for stability. Volume/mute control via `amixer` subprocess — no additional Python dependencies. Hardware recommendation: generic USB DAC + marine-grade powered speaker (5–10W) for outdoor audibility over engine noise.

4. **The monitoring consumer shares a single pymavlink connection.** Serial ports are exclusive — the `mower monitor` command IS the GCS during mowing. Multi-GCS (with Mission Planner) requires MAVProxy/mavlink-router as a UDP multiplexer. Monitoring adds zero additional SiK bandwidth since it reads messages ArduPilot already streams at the configured `SR1_*` rates.

5. **Rich `Live` + `Table` + `Panel` is the proven display pattern.** Already used in the Jetson thermal command with `refresh_per_second=1`. Sun-readable design uses bold text, semantic colors (green/red/yellow), and text symbols alongside colors. No new dependencies needed.

6. **Alert hysteresis + cooldown prevents flapping.** Configurable thresholds in YAML, N consecutive bad readings before firing, cooldown period between repeated alerts, recovery notifications. Alerts connect to TTS via SSH command to the Jetson daemon.

7. **MAVFTP is the recommended DataFlash log pull mechanism.** pymavlink includes a full client (`mavftp.py`). Download is slow over SiK (~24 min for 10 MB) but automatable and requires no physical SD card access. USB direct connect is the documented escape hatch for large logs.

8. **Correlation ID stitches the archive.** The existing `MOWER_CORRELATION_ID` propagation from laptop → Jetson via SSH enables filtered log collection. Archive uses tar.gz with manifest.json (versioned schema `mower-rover.run-archive.v1`) and summary.json, following existing `write_json_snapshot` patterns.

### Cross-Cutting Patterns

- **No new dependencies needed.** Rich, pymavlink, structlog, and SSH transport are already in the project. TTS engines are external binaries invoked via subprocess, not Python library dependencies.
- **Existing codebase patterns directly applicable.** The monitoring display follows the Jetson thermal command's `Live` pattern. The archive manifest follows the param snapshot JSON schema. Log collection uses the existing `JetsonClient.pull()` transport. Alert config extends `LaptopConfig` YAML.
- **Laptop → Jetson split is clear.** Monitoring + alerts run on the laptop (where MAVLink is). TTS playback + log storage run on the Jetson (where the speaker and application logs are). SSH bridges the two.

### Actionable Conclusions

- The planner can design the TTS subsystem around pre-generated WAV files with a `mower-jetson tts generate` command and a phrase-key → WAV-file playback daemon
- The live monitor command (`mower monitor`) is architecturally simple: a single `recv_match` polling loop feeding a Rich `Live` display and an alert evaluation engine
- The log archive command (`mower run-archive`) orchestrates MAVFTP download + SSH log pull + manifest generation + tar.gz bundling
- All three features share the existing `open_link` connection, `LaptopConfig` / `JetsonConfig` YAML, and correlation-ID-based log stitching

### Open Questions

- Exact Piper synthesis latency on Jetson AGX Orin needs field benchmarking
- USB speaker volume adequacy over Kawasaki FR691V engine noise needs field testing
- MAVFTP integration with pymavlink's connection object should be validated in SITL
- Whether `MISSION_CURRENT.seq` provides reliable coverage progress in Auto mode needs SITL confirmation

## References

### Phase 1 Sources
- [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) — Active Piper repo (GPL-3.0)
- [rhasspy/piper 2023.11.14-2](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2) — Archived MIT-licensed Piper with aarch64 binary
- [espeak-ng/espeak-ng](https://github.com/espeak-ng/espeak-ng) — eSpeak-NG repo (GPL-3.0)
- [py-espeak-ng on PyPI](https://pypi.org/project/py-espeak-ng/) — Apache-2.0 Python wrapper
- [piper-tts on PyPI](https://pypi.org/project/piper-tts/) — PyPI package (v1.4.2, GPL-3.0)
- [NVIDIA Riva TTS Overview](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tts/tts-overview.html)
- [NVIDIA Riva Support Matrix](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/support-matrix/support-matrix.html)
- [ALSA Configuration Reference](https://wiki.archlinux.org/title/Advanced_Linux_Sound_Architecture)

### Phase 2 Sources
- [ArduPilot MAVLink Requesting Data](https://ardupilot.org/dev/docs/mavlink-requesting-data.html) — SRx parameters, SET_MESSAGE_INTERVAL, stream groups
- [MAVLink FTP Protocol](https://mavlink.io/en/services/ftp.html) — MAVFTP specification for log download
- [ArduPilot MAVFTP](https://ardupilot.org/dev/docs/mavlink-mavftp.html) — ArduPilot MAVFTP usage
- [pymavlink on GitHub](https://github.com/ArduPilot/pymavlink) — mavftp.py client, mavutil.py connection patterns

## Follow-Up Research

### From Phase 1
- Field-test Piper arm64 binary on actual Jetson AGX Orin with JetPack 6.2.1 to confirm it runs and measure synthesis latency
- Field-test USB audio adapter + speaker combination to verify adequate volume over engine noise and USB audio stability
- Verify `alsa-utils` presence on headless JetPack 6.2.1 image; document install steps if missing
- Confirm the exact set of MAVLink events/phrases needed (some may require parameterization beyond simple fixed strings)

### From Phase 2
- MAVFTP log download should be validated in SITL before the planner finalizes the implementation plan
- Alert threshold YAML schema should be reviewed during planning to ensure it covers all FR-10/FR-14 requirements
- Consider whether the summary report should also be generated in Markdown (human-readable on sunlit screen) in addition to JSON
- Confirm `MISSION_CURRENT.seq` behavior in Auto mode for coverage progress tracking

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-22 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/004-operations-iteration-quality.md |
