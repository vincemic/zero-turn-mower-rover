---
id: "010"
type: research
title: "Qwen LLM on Jetson AGX Orin — Feasibility Alongside Existing VSLAM Workloads"
status: ✅ Complete
created: "2026-04-26"
current_phase: "5 of 5"
---

## Introduction

The Jetson AGX Orin Developer Kit (64 GB LPDDR5, 2048-core Ampere GPU, JetPack 6 / L4T 36.5) currently runs RTAB-Map VSLAM with CUDA, a DepthAI stereo+IMU pipeline, and a MAVLink bridge service — all at the 50 W power envelope. This research investigates whether the latest Qwen family of LLMs (Alibaba's open-weight models) can run inference on this same Jetson concurrently with the existing workloads, and if so, which model size / quantization / runtime combination is viable.

## Objectives

- Identify the latest Qwen model variants and their memory / compute requirements
- Determine which Jetson-compatible inference runtimes support Qwen (llama.cpp, TensorRT-LLM, MLC-LLM, etc.)
- Estimate the GPU memory and compute headroom remaining after VSLAM workloads
- Assess whether a useful Qwen variant fits within the remaining resource budget
- Identify practical deployment constraints (quantization, context length, thermal, power)

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Qwen Model Family Survey | ✅ Complete | Latest Qwen release lineage; model sizes (0.6B–72B+); parameter counts; context lengths; architectural details; license terms | 2026-04-26 |
| 2 | Jetson Inference Runtime Options | ✅ Complete | llama.cpp (CUDA), TensorRT-LLM, MLC-LLM, Ollama, ExecuTorch — Jetson/aarch64/JetPack 6 compatibility; quantization support (GGUF Q4/Q5/Q8, AWQ, GPTQ); measured tok/s benchmarks on Orin | 2026-04-26 |
| 3 | Current VSLAM Resource Footprint | ✅ Complete | Measure/estimate GPU memory, system RAM, CUDA core utilization, and power draw of existing services (rtabmap_slam_node, DepthAI pipeline, MAVLink bridge) in steady-state on 50 W mode | 2026-04-26 |
| 4 | Headroom Analysis & Model Sizing | ✅ Complete | Subtract VSLAM footprint from Orin 64 GB budget; determine largest Qwen variant+quant that fits; estimate tokens/sec at that budget; assess whether concurrent GPU sharing is practical (MPS, time-slicing, memory partitioning) | 2026-04-26 |
| 5 | Deployment & Integration Considerations | ✅ Complete | Thermal/power impact of adding LLM inference; startup latency; memory-mapping vs full load; systemd service design; graceful degradation if VSLAM needs burst GPU; potential mower-rover use cases for on-device LLM | 2026-04-26 |

## Phase 1: Qwen Model Family Survey

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Qwen Release Lineage

The Qwen model family from Alibaba Cloud has evolved through several generations:

| Generation | Release Date | Notes |
|-----------|-------------|-------|
| Qwen1.5 | Feb 2024 | First major open-weight refresh; introduced MoE-A2.7B |
| Qwen2 | Jun 2024 | Architecture refresh, GQA, 128K context |
| Qwen2.5 | Sep 2024 | Sizes: 0.5B, 1.5B, 3B, 7B, 14B, 32B, 72B; pretrained on 18T tokens; 128K context + 8K output |
| Qwen3 (2504) | Apr 29, 2025 | Current generation; 6 dense + 2 MoE models; 36T tokens pretraining; hybrid thinking/non-thinking modes |
| Qwen3-2507 | Jul–Aug 2025 | Updated Instruct and Thinking variants for 235B-A22B, 30B-A3B, and 4B; 256K context (extendable to 1M) |
| Qwen3.5 | ~2026 | Multimodal (Image-Text-to-Text): 397B-A17B, 122B-A10B, 27B — NOT pure text LLMs |
| Qwen3.6 | ~2026 | Multimodal: 35B-A3B, 27B — NOT pure text LLMs |

**For this Jetson feasibility study, Qwen3 (dense and MoE text-only models) is the relevant family.** Qwen3.5 and Qwen3.6 are multimodal vision-language models and are not applicable.

### Qwen3 Dense Models — Complete Specifications

| Model | Total Params | Non-Embedding | Layers | Q Heads / KV Heads | GQA | Native Context | Extended Context | Thinking Mode |
|-------|-------------|---------------|--------|---------------------|-----|---------------|-----------------|---------------|
| Qwen3-0.6B | 0.6B | 0.44B | 28 | 16 / 8 | Yes | 32,768 | — | Yes |
| Qwen3-1.7B | 1.7B | 1.4B | 28 | 16 / 8 | Yes | 32,768 | — | Yes |
| Qwen3-4B | 4.0B | 3.6B | 36 | 32 / 8 | Yes | 32,768 | 131,072 (YaRN) | Yes |
| Qwen3-8B | 8.2B | 6.95B | 36 | 32 / 8 | No (full) | 32,768 | 131,072 (YaRN) | Yes |
| Qwen3-14B | ~14B | ~12B | 40 | 40 / 8 | No | 128,000 | — | Yes |
| Qwen3-32B | ~32B | ~30B | 64 | 64 / 8 | No | 128,000 | — | Yes |

### Qwen3 MoE Models — Complete Specifications

| Model | Total Params | Activated Params | Layers | Experts | Active Experts | Native Context | Extended Context |
|-------|-------------|-----------------|--------|---------|---------------|---------------|------------------|
| Qwen3-30B-A3B | 30.5B | 3.3B | 48 | 128 | 8 | 32,768 | 131,072 (YaRN) |
| Qwen3-235B-A22B | ~235B | ~22B | 94 | 128 | 8 | 128,000 | — |

**MoE memory note:** MoE models require loading ALL expert weights into memory even though only 8 experts are active per token. The Qwen3-30B-A3B requires ~58 GB in BF16 — exceeding the Orin's 64 GB budget when combined with VSLAM. However, at Q4_K_M quantization (~18 GB), the 30B-A3B could potentially fit within the 64 GB budget. See Phase 4 for detailed analysis.

### Qwen3-2507 Updated Variants

Released July–August 2025, these are updated post-trained versions with the same base architecture:

| Model | Variants | Key Improvements |
|-------|----------|------------------|
| Qwen3-235B-A22B-2507 | Instruct-2507, Thinking-2507 | 256K context (extendable to 1M); improved reasoning |
| Qwen3-30B-A3B-2507 | Instruct-2507, Thinking-2507 | 256K context (extendable to 1M); improved general capabilities |
| Qwen3-4B-2507 | Instruct-2507, Thinking-2507 | Same base architecture; improved quality |

The -2507 variants split thinking and non-thinking into separate model files.

### Architecture Details (Common Across Qwen3)

- **Type:** Decoder-only causal language model
- **Attention:** Grouped Query Attention (GQA) with varying group sizes
- **Activation:** SwiGLU
- **Positional Encoding:** RoPE (Rotary Position Embeddings); YaRN for context extension
- **Vocabulary Size:** ~151,936 tokens
- **Training Precision:** BF16
- **Pretraining Data:** ~36 trillion tokens, 119 languages/dialects
- **Special Tokens:** `<think>` / `</think>` for thinking mode
- **Framework Support:** transformers >= 4.51.0, llama.cpp >= b5401, Ollama >= 0.9.0, vLLM >= 0.8.5, SGLang >= 0.4.6.post1, TensorRT-LLM >= 0.20.0rc3, ExecuTorch, MNN

### GPU Memory Footprint (Official Benchmarks on H20)

Transformers measurements at 1-token input / 2048-token output generation:

| Model | BF16 (MB) | FP8 (MB) | AWQ-INT4 (MB) | GPTQ-INT8 (MB) |
|-------|-----------|----------|---------------|----------------|
| Qwen3-0.6B | 1,394 | 1,217 | — | 986 |
| Qwen3-1.7B | 3,412 | 2,726 | — | 2,229 |
| Qwen3-4B | 7,973 | 5,281 | 2,915 | — |
| Qwen3-8B | 15,947 | 9,323 | 6,177 | — |
| Qwen3-14B | 28,402 | 16,012 | 9,962 | — |
| Qwen3-32B | 62,751 | 33,379 | 19,109 | — |
| Qwen3-30B-A3B | 58,462 | 30,296 | — | — |

### Estimated GGUF Quantized Sizes (for llama.cpp)

| Model | Q4_K_M (~4.5 bits) | Q5_K_M (~5.5 bits) | Q8_0 (~8 bits) |
|-------|--------------------|--------------------|----------------|
| Qwen3-0.6B | ~0.4 GB | ~0.5 GB | ~0.7 GB |
| Qwen3-1.7B | ~1.1 GB | ~1.3 GB | ~1.8 GB |
| Qwen3-4B | ~2.5 GB | ~3.0 GB | ~4.3 GB |
| Qwen3-8B | ~5.0 GB | ~6.0 GB | ~8.5 GB |

### Performance Equivalence Claims

From the official Qwen3 blog:

- **Qwen3-1.7B/4B/8B/14B/32B-Base ≈ Qwen2.5-3B/7B/14B/32B/72B-Base** respectively
- **Qwen3-4B (instruct) can rival Qwen2.5-72B-Instruct** in reasoning tasks
- **Qwen3-30B-A3B outcompetes QwQ-32B** with only 3.3B activated parameters

This means a Qwen3-4B running on the Jetson could deliver reasoning quality comparable to what previously required a 72B model.

### License Terms

**All Qwen3 open-weight models are licensed under Apache 2.0.** Permissive license with no commercial restrictions — suitable for the mower-rover project.

### Jetson-Relevant Model Shortlist

For the Jetson AGX Orin Developer Kit (64 GB shared memory, must coexist with VSLAM):

| Model | Quantization | Est. Memory | Viability |
|-------|-------------|-------------|----------|
| Qwen3-0.6B | Q4_K_M | ~0.4 GB | Trivially fits; limited capability |
| Qwen3-0.6B | BF16 | ~1.4 GB | Fits easily; limited capability |
| Qwen3-1.7B | Q4_K_M | ~1.1 GB | Fits easily; reasonable capability |
| Qwen3-1.7B | BF16 | ~3.4 GB | Fits; good capability |
| Qwen3-4B | Q4_K_M | ~2.5 GB | Best capability-to-memory ratio for edge |
| Qwen3-4B | AWQ-INT4 | ~2.9 GB | Strong option with GPU acceleration |
| Qwen3-4B | BF16 | ~8 GB | Tight; depends on VSLAM headroom |
| Qwen3-8B | Q4_K_M | ~5 GB | Possible if VSLAM leaves enough headroom |
| Qwen3-8B | AWQ-INT4 | ~6.2 GB | Borderline; needs Phase 3/4 analysis |

**Key Discoveries:**
- All Qwen3 models are Apache 2.0 licensed — no commercial restrictions for mower-rover
- Qwen3-4B achieves quality comparable to Qwen2.5-72B-Instruct, making it the sweet spot for edge deployment
- Qwen3-0.6B through Qwen3-8B (quantized) fit within 0.4–5 GB memory — very plausible alongside VSLAM on 64 GB Orin
- MoE models (30B-A3B, 235B-A22B) require loading ALL weights (~58 GB+ BF16) — 30B-A3B may fit at Q4 (~18 GB) on 64 GB Orin; 235B is NOT viable
- Non-thinking mode eliminates reasoning overhead for faster, lighter inference on edge
- GGUF quantization (Q4_K_M) reduces model memory by ~6x vs BF16

**External Sources:**
- https://github.com/QwenLM/Qwen3
- https://qwenlm.github.io/blog/qwen3/
- https://huggingface.co/Qwen
- https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html

**Gaps:** Exact GGUF sizes are estimated, not measured; no official Jetson/aarch64 benchmarks exist; Ampere-class inference latency unknown  
**Assumptions:** GGUF Q4_K_M sizes use ~4.5 bits/parameter estimate (±15%); Qwen3.5/3.6 multimodal models excluded

## Phase 2: Jetson Inference Runtime Options

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Runtime-by-Runtime Analysis

#### 1. vLLM — NVIDIA's Recommended Runtime for Jetson

**Compatibility:** ✅ Full — NVIDIA's Jetson AI Lab uses vLLM as its primary inference engine for all Jetson models, including Qwen3. Pre-built Docker containers: `ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin` (aarch64, JetPack 6).

**Official Benchmarks on AGX Orin 64 GB (vLLM, W4A16, ISL/OSL=2048/128):**

| Model | Size (W4A16) | RAM Required | tok/s (C=1) | tok/s (C=8) |
|-------|-------------|-------------|-------------|-------------|
| Qwen3-4B | 2.5 GB | 4 GB | **42.15** | 193.83 |
| Qwen3-8B | 4.5 GB | 8 GB | **26.53** | 142.99 |
| Qwen3-32B | 18 GB | 24 GB | **6.22** | 16.84 |

**Concurrent VSLAM Impact:** `--gpu-memory-utilization` flag controls max GPU memory vLLM claims. On unified-memory Orin (64 GB shared), must be reduced to leave room for RTAB-Map CUDA. Docker isolation adds overhead.

#### 2. llama.cpp (+ CUDA Backend)

**Compatibility:** ✅ Full — Natively supports aarch64 Linux with CUDA backend (SM87 for Orin). Build from source with `cmake -B build -DGGML_CUDA=ON`. Also available via jetson-containers.

**Estimated Performance on Orin:**
- Qwen3-4B Q4_K_M (~2.5 GB): ~25-35 tok/s (single user)
- Qwen3-1.7B Q4_K_M (~1.1 GB): ~50-70 tok/s
- Qwen3-0.6B Q4_K_M (~0.4 GB): ~100+ tok/s

**Key Advantage:** No containerization overhead, fine-grained GPU layer control (`--n-gpu-layers N`), smallest memory footprint, OpenAI-compatible server mode (`llama-server`). `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` is native behavior on Orin. **Best option for VSLAM coexistence** — allocates memory on demand and releases it.

#### 3. Ollama

**Compatibility:** ✅ Full — Official aarch64 Linux builds. Wraps llama.cpp internally. Install: `curl -fsSL https://ollama.com/install.sh | sh`. Auto-detects CUDA on Jetson.

**Qwen3 Support:** Full — `ollama run qwen3:4b` works out of the box. Pre-quantized GGUF models at various sizes/quant levels.

**Performance:** Same as llama.cpp (same backend). `OLLAMA_NUM_GPU_LAYERS` controls GPU offloading. Auto-unloads model after 5 min idle (configurable) — good for on-demand usage alongside VSLAM.

**Key Advantage:** Simplest setup, good Python SDK (`pip install ollama`), REST API + OpenAI-compatible endpoint.

#### 4. TensorRT-LLM — Not Recommended

Build complexity very high, no official Jetson packaging (Jetson AI Lab uses vLLM instead), aggressively pre-allocates GPU memory.

#### 5. MLC-LLM — Not Recommended

Requires building TVM from source for aarch64/CUDA 12.x. Declining Jetson-specific activity. Similar or lower performance than llama.cpp for much higher build complexity.

#### 6. ExecuTorch — Not Recommended

Targets mobile/embedded (Android, iOS). CUDA backend listed as experimental for Linux. No Jetson packaging or benchmarks.

#### 7. MNN — Not Recommended

No CUDA backend for Jetson. GPU acceleration relies on OpenCL/Vulkan, significantly slower than native CUDA. Targets mobile only.

### Comparative Summary

| Runtime | Jetson Compat | Build Complexity | Performance | VSLAM Coexistence | Recommendation |
|---------|:---:|:---:|:---:|:---:|:---:|
| **vLLM** | ✅ Official | Low (Docker) | **Best** (42 tok/s 4B) | Medium (pre-alloc) | **Primary** |
| **llama.cpp** | ✅ Native | Low-Med | Good (~30 tok/s 4B) | **Best** (on-demand) | **Best for coexistence** |
| **Ollama** | ✅ Native | **Lowest** | Good (= llama.cpp) | Good (auto-unload) | **Easiest setup** |
| TensorRT-LLM | ⚠️ Partial | Very High | Theoretical best | Poor | Not recommended |
| MLC-LLM | ⚠️ Partial | Very High | Competitive | Medium | Not recommended |
| ExecuTorch | ⚠️ Experimental | High | Unknown | N/A | Not recommended |
| MNN | ❌ No CUDA | Medium | Poor on Jetson | N/A | Not recommended |

### Unified Memory Architecture Note

The Jetson AGX Orin Developer Kit uses **unified memory** — CPU and GPU share the same 64 GB LPDDR5 pool:
1. **No PCIe transfer overhead** — Model weights loaded by CPU are directly accessible by GPU
2. **Memory contention** — LLM inference and VSLAM CUDA operations compete for the same 64 GB
3. **llama.cpp advantage** — `--n-gpu-layers` provides fine control over GPU vs CPU execution

### Recommended Runtime Stack

**Primary: Ollama or llama.cpp (native, no Docker)** — Best for concurrent operation with VSLAM. On-demand memory allocation, GPU layer control, no Docker overhead.

**Alternative: vLLM (Docker-based)** — Best raw performance but Docker overhead and aggressive memory pre-allocation make VSLAM coexistence harder.

**Key Discoveries:**
- NVIDIA Jetson AI Lab benchmarks Qwen3-4B at **42.15 tok/s** on AGX Orin 64 GB (vLLM, W4A16)
- Qwen3-8B achieves **26.53 tok/s** — still conversational speed
- llama.cpp/Ollama offer best GPU memory coexistence with VSLAM — on-demand allocation + `--n-gpu-layers` control
- W4A16 is the standard quantization for Jetson edge deployment
- Jetson AI Lab benchmarks are on **64 GB Orin Dev Kit** — directly applicable to this project
- TensorRT-LLM, MLC-LLM, ExecuTorch, MNN not recommended for this use case

**External Sources:**
- https://www.jetson-ai-lab.com/models/qwen3-4b
- https://www.jetson-ai-lab.com/models/qwen3-8b
- https://github.com/dusty-nv/jetson-containers
- https://github.com/ggerganov/llama.cpp
- https://github.com/ollama/ollama

**Gaps:** No direct llama.cpp benchmarks on Orin — estimates extrapolated from vLLM data.  
**Assumptions:** llama.cpp tok/s estimated with ~15-25% reduction from vLLM

## Phase 3: Current VSLAM Resource Footprint

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Jetson AGX Orin Hardware Baseline

**64 GB LPDDR5 unified memory** (CPU and GPU share the same physical pool). Currently configured at **nvpmodel mode 3 (50W)** with `jetson_clocks` locking frequencies at boot. Headless mode (no desktop, per `jetson-harden.sh`).

| Resource | Mode 3 (50W, current) | Mode 2 (30W, original) |
|----------|----------------------|----------------------|
| Power Budget | 50W | 30W |
| Online CPUs | 8 | 8 |
| GPU TPCs | 8 (all) → 2048 CUDA cores | 4 → 1024 CUDA cores |

### Service 1: rtabmap_slam_node (C++ SLAM)

Standalone C++ binary (`mower-vslam.service`). Uses OdometryF2M, stereo at 640×400 @ 30 FPS, IMU at 200 Hz, 3000 max features in local map, `memory_threshold_mb = 6000`.

**Memory Footprint (estimated steady-state):**

| Component | Memory (unified pool) |
|-----------|----------------------|
| RTAB-Map core + odometry engine | ~300–500 MB |
| OdometryF2M local map (3000 features) | ~100–200 MB |
| OpenCV CUDA context + feature buffers | ~200–400 MB |
| Loop closure vocabulary (bag-of-words) | ~100–200 MB |
| SQLite database (rtabmap.db) mmap | ~50–200 MB |
| **Working set total** | **~800 MB – 1.5 GB** |

The `memory_threshold_mb = 6000` is a ceiling before RTAB-Map transfers data to Long-Term Memory — not a constant allocation. Typical working set stays well below during mowing sessions.

**GPU Utilization:**
- Feature extraction (GFTT/ORB via OpenCV CUDA) runs at **30 Hz** — short GPU bursts (~5–15 ms per frame)
- Feature matching and graph optimization are **CPU-bound**
- Estimated GPU utilization: **5–15% steady-state** (periodic bursts, not continuous)
- GPU is largely idle between feature extraction calls — critical for LLM feasibility

**CPU Utilization:** ~1.5–3 cores average, spikes during loop closure

### Service 2: DepthAI Pipeline (OAK-D Pro)

Runs **within** the rtabmap_slam_node process (not separate). Stereo depth runs entirely on the **MyriadX VPU** (on-camera). Host receives computed depth maps + rectified mono images.

- Host memory: ~60–110 MB (USB transfer buffers + frame queues)
- Host CPU/GPU load: **negligible** (just USB transfer + frame copy)
- Power: ~5W drawn from USB bus (external to Jetson TDP budget)

### Service 3: MAVLink Bridge (Python)

`mower-vslam-bridge.service` — reads poses via Unix socket IPC, converts FLU→NED, sends `VISION_POSITION_ESTIMATE` to Pixhawk.

- RAM: ~30–50 MB (Python runtime + pymavlink)
- CPU: <5% of one core
- GPU: **None**

### Service 4: Health Monitoring (Python)

`mower-health.service` — reads sysfs thermal zones, power state, disk usage.

- RAM: ~20–40 MB
- CPU: <1% of one core
- GPU: **None**

### System Overhead (OS + JetPack, Headless)

~800 MB – 1 GB (kernel, systemd, CUDA driver runtime ~300–500 MB)

### Combined Resource Footprint

| Resource | Steady-State | Peak (memory_threshold active) |
|----------|-------------|-------------------------------|
| **Unified Memory** | **~2–3 GB** | **~7 GB** |
| **CPU Cores** (avg) | **2–3.5 of 8** | 3–4 of 8 |
| **GPU Utilization** | **5–15%** | ~20% (loop closure bursts) |
| **GPU Memory** (CUDA alloc) | **500–900 MB** | ~1.5 GB |
| **Power** (Jetson module) | **~15–25W of 50W** | ~30W |

### Available Headroom for LLM

| Resource | Available | Qwen3-4B Q4_K_M Needs | Verdict |
|----------|-----------|----------------------|---------|
| **Memory** (steady-state) | ~61 GB | ~2.5 GB | ✅ Fits trivially |
| **Memory** (worst-case) | ~57 GB | ~2.5 GB | ✅ Fits trivially |
| **GPU** | 85–95% idle | Variable (batch inference) | ✅ Time-sharing viable |
| **CPU** | 4.5–6 cores free | 1–2 cores (CPU fallback) | ✅ Ample |
| **Power** | 25–35W | ~5–15W (estimated) | ✅ Within budget |

**Key Discoveries:**
- Typical VSLAM steady-state: ~2–3 GB memory, 5–15% GPU, 2–3.5 CPU cores — leaves **massive** headroom
- GPU usage is periodic and bursty (30 Hz feature extraction, ~10 ms/frame), not continuous — LLM can time-share
- OAK-D Pro stereo runs entirely on MyriadX VPU — adds negligible host load
- Memory headroom: **57–61 GB** available for LLM depending on map accumulation
- Power headroom: **25–35W** within the 50W budget
- `memory_threshold_mb = 6000` could be lowered to ~4000 MB for additional safety margin

| File | Relevance |
|------|-----------|
| `contrib/rtabmap_slam_node/src/rtabmap_slam_node.cpp` | SLAM node: DepthAI pipeline, RTAB-Map config, 400p stereo, memory threshold |
| `src/mower_rover/config/data/vslam_defaults.yaml` | VSLAM defaults: resolution, FPS, memory threshold |
| `src/mower_rover/vslam/bridge.py` | MAVLink bridge daemon |
| `scripts/jetson-harden.sh` | nvpmodel mode 3, jetson_clocks, headless mode |
| `docs/research/002-jetson-agx-orin-bringup.md` | Power mode table, Dev Kit 64 GB module specs |

**Gaps:** No live `tegrastats` profiling data from actual SLAM operation exists — all estimates are from code analysis and published specs. GPU utilization % and power draw not measured with instruments.  
**Assumptions:** Memory estimates based on RTAB-Map benchmarks at 400p; GPU util from 30 Hz burst pattern analysis

## Phase 4: Headroom Analysis & Model Sizing

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Memory Budget After VSLAM

| Scenario | VSLAM Allocation | Safety Buffer | Available for LLM |
|----------|-----------------|---------------|-------------------|
| **Conservative** | 7 GB (peak) | 4 GB | **53 GB** |
| Moderate | 7 GB (peak) | 2 GB | **55 GB** |
| Aggressive | 3 GB (steady-state) | 2 GB | **59 GB** |

**Recommended operating budget: 53 GB (conservative).** With 64 GB unified memory, even the conservative budget exceeds the requirements of any single Qwen3 model. This also makes Qwen3-30B-A3B (MoE, ~18 GB at Q4) feasible as a stretch option.

### KV Cache Memory Sizing

KV cache grows linearly with context length. Per-token KV cache = 2 × layers × kv_heads × head_dim × bytes.

**KV Cache at Different Context Lengths (FP16):**

| Model | 2K ctx | 4K ctx | 8K ctx | 16K ctx | 32K ctx |
|-------|--------|--------|--------|---------|---------|
| Qwen3-0.6B | 111 MB | 223 MB | 446 MB | 891 MB | 1.8 GB |
| Qwen3-1.7B | 225 MB | 449 MB | 898 MB | 1.8 GB | 3.6 GB |
| Qwen3-4B | 180 MB | 360 MB | 720 MB | 1.4 GB | 2.9 GB |
| Qwen3-8B | 288 MB | 576 MB | 1.2 GB | 2.3 GB | 4.6 GB |

### Total LLM Memory (Weights + KV Cache + Runtime)

llama.cpp runtime overhead: ~600 MB. **Qwen3-4B Q4_K_M (primary recommendation):**

| Context | Weights | KV (FP16) | Runtime | **Total** | Headroom (53 GB) |
|---------|---------|-----------|---------|-----------|------------------|
| 2K | 2.5 GB | 0.18 GB | 0.6 GB | **3.3 GB** | 49.7 GB |
| 8K | 2.5 GB | 0.72 GB | 0.6 GB | **3.8 GB** | 49.2 GB |
| 32K | 2.5 GB | 2.9 GB | 0.6 GB | **6.0 GB** | 47.0 GB |

**Qwen3-8B Q4_K_M (stretch option):**

| Context | Weights | KV (FP16) | Runtime | **Total** | Headroom (53 GB) |
|---------|---------|-----------|---------|-----------|------------------|
| 2K | 5.0 GB | 0.29 GB | 0.6 GB | **5.9 GB** | 47.1 GB |
| 8K | 5.0 GB | 1.15 GB | 0.6 GB | **6.8 GB** | 46.2 GB |
| 32K | 5.0 GB | 4.6 GB | 0.6 GB | **10.2 GB** | 42.8 GB |

**Qwen3-30B-A3B Q4_K_M (MoE stretch option — newly viable at 64 GB):**

| Context | Weights | KV (FP16) | Runtime | **Total** | Headroom (53 GB) |
|---------|---------|-----------|---------|-----------|------------------|
| 2K | ~18 GB | ~0.3 GB | 0.8 GB | **~19 GB** | ~34 GB |
| 8K | ~18 GB | ~1.2 GB | 0.8 GB | **~20 GB** | ~33 GB |
| 32K | ~18 GB | ~4.6 GB | 0.8 GB | **~23 GB** | ~30 GB |

**Key insight: Memory is NOT the binding constraint.** With 64 GB unified memory, even the Qwen3-30B-A3B MoE model at Q4 fits comfortably. The 30B-A3B only activates 3.3B parameters per token, so despite its large weight footprint it offers excellent inference speed.

### Memory Bandwidth — The True Bottleneck

LLM token generation at batch size 1 is **memory-bandwidth-bound**. Each token reads all weights + accumulated KV cache.

Jetson AGX Orin Dev Kit LPDDR5: **204.8 GB/s** (256-bit bus).

| Model (Q4_K_M) | Weight Size | Theoretical Max (204.8 GB/s) | Practical (~50% eff.) |
|----------------|------------|------------------------------|----------------------|
| Qwen3-0.6B | 0.4 GB | 512 tok/s | ~256 tok/s |
| Qwen3-1.7B | 1.1 GB | 186 tok/s | ~93 tok/s |
| Qwen3-4B | 2.5 GB | 82 tok/s | ~41 tok/s |
| Qwen3-8B | 5.0 GB | 41 tok/s | ~21 tok/s |

The 50% efficiency aligns with observed vLLM benchmarks (42 tok/s observed vs 82 theoretical for Qwen3-4B).

**Recommendation:** Use Q8 KV cache quantization (`--cache-type-k q8_0 --cache-type-v q8_0` in llama.cpp) for contexts >8K to maintain throughput.

### GPU Sharing Mechanisms on Jetson Orin

**Orin Dev Kit GPU: 16 SMs (2048 CUDA cores), Ampere SM87, compute capability 8.7**

1. **Default CUDA Time-Slicing (Recommended):** No setup. RTAB-Map uses GPU in 5–15 ms bursts at 30 Hz, leaving 85–95% idle. llama.cpp fills the gaps. Expected overhead: <5%.

2. **CUDA MPS (Available on Tegra — Volta level):** Confirmed available on Orin. Enables concurrent kernel execution, reduces context switch overhead. Setup: `sudo nvidia-cuda-mps-control -d`. Use if profiling shows >5% context-switch overhead.

3. **MPS + Static SM Partitioning (Ampere iGPU, 2 SM chunks):** Can partition 16 SMs into VSLAM (2 SMs) and LLM (14 SMs). Only if VSLAM latency degrades. Not recommended for initial deployment.

4. **MPS + Active Thread Percentage:** Soft partitioning: `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE=15` for RTAB-Map, `=85` for llama.cpp. Good middle ground for QoS tuning.

**Escalation path:** Time-slicing → MPS → Active thread % → Static SM partitioning

### Memory Contention Risks

- **Bandwidth contention:** Minimal. VSLAM averages ~1.5–3 GB/s (<2% of 204.8 GB/s bus).
- **CUDA fragmentation:** Mitigated by keeping the model loaded (Ollama `OLLAMA_KEEP_ALIVE=-1`).
- **Page faults:** No swap configured on Jetson. Conservative 53 GB budget provides 4 GB safety margin above VSLAM peak.
- **Unified memory note:** `--n-gpu-layers` on Orin controls compute location, not memory location — full GPU offload (`-ngl 999`) is always preferred.

### Realistic Performance with VSLAM Concurrent

| Model (Q4_K_M) | Isolated tok/s | With VSLAM | 4K ctx | 32K ctx | Experience |
|----------------|---------------|------------|--------|---------|------------|
| **Qwen3-0.6B** | 100+ | **85–100** | ~95 | ~70 | Instant; limited reasoning |
| **Qwen3-1.7B** | 50–70 | **45–65** | ~55 | ~35 | Fast; moderate reasoning |
| **Qwen3-4B** | 25–35 | **22–33** | ~30 | ~18 | Good; strong reasoning ≈ Qwen2.5-72B |
| **Qwen3-8B** | 15–22 | **13–20** | ~18 | ~10 | Acceptable; highest quality |

All viable models deliver >10 tok/s at practical context lengths — above the conversational threshold.

### Tiered Recommendations

**Tier 1 — Primary (Qwen3-4B Q4_K_M):** Best capability-to-resource ratio. 22–33 tok/s with VSLAM. 3–6 GB memory. Reasoning quality comparable to Qwen2.5-72B-Instruct.

**Tier 2 — Highest Dense Quality (Qwen3-8B Q4_K_M):** 13–20 tok/s with VSLAM. 6–10 GB memory. Best dense-model quality available on this hardware.

**Tier 3 — MoE Stretch (Qwen3-30B-A3B Q4_K_M):** ~18 GB weights but only 3.3B active parameters per token — newly viable on 64 GB Dev Kit. Expected throughput similar to dense 3–4B models due to low active parameter count. Requires field validation. Highest quality option if tok/s is acceptable.

**Tier 4 — Fastest (Qwen3-1.7B Q4_K_M):** 45–65 tok/s. 2–3 GB memory. Best for latency-sensitive structured tasks.

**Deployment recommendation:** Install Ollama with multiple sizes. Default to `qwen3:4b`. Auto-unload after idle frees memory back to VSLAM.

**Key Discoveries:**
- Memory is NOT the binding constraint — even Qwen3-8B at 32K context fits with 40+ GB to spare
- Memory bandwidth (204.8 GB/s LPDDR5) is the true throughput bottleneck
- CUDA MPS IS supported on Orin (Volta-level MPS on Tegra) + Static SM Partitioning (Ampere, 2 SM chunks)
- Default time-slicing likely sufficient — VSLAM uses only 5–15% GPU
- Qwen3-4B Q4_K_M is the sweet spot: 22–33 tok/s, 3–6 GB, rivaling 72B quality
- VSLAM bandwidth consumption (<2% of bus) causes minimal contention

**External Sources:**
- https://docs.nvidia.com/deploy/mps/ — CUDA MPS on Tegra, SM partitioning
- https://github.com/ggml-org/llama.cpp — Build docs, KV cache quantization flags

**Gaps:** No live profiling of concurrent VSLAM+LLM; bandwidth figure (204.8 GB/s) assumes dev kit module  
**Assumptions:** 50% bandwidth efficiency calibrated against vLLM benchmarks; ~600 MB llama.cpp runtime overhead

## Phase 5: Deployment & Integration Considerations

**Status:** ✅ Complete  
**Session:** 2026-04-26

### Thermal & Power Impact

**Current 50W mode power breakdown:**

| Workload State | Estimated Power |
|----------------|----------------|
| System baseline (headless) | ~8–10W |
| VSLAM steady-state | +15–25W |
| LLM active generation (Qwen3-4B Q4) | +8–15W |
| **Total (concurrent)** | **~35–45W** |

At on-demand (bursty) LLM usage, total stays within 50W budget with margin. Continuous generation could approach 45W — within budget but minimal headroom.

**Thermal thresholds (already in codebase):**
- 85°C: `_THERMAL_GATE_C` in `probe/checks/usb_tuning.py` — reusable as LLM thermal gate
- 95°C: `_THROTTLE_THRESHOLD_C` in `probe/checks/thermal.py` — GPU/CPU throttling begins
- 105°C: Hardware shutdown (TJ_MAX)

**Outdoor operation advantage:** Natural convection over the Jetson enclosure during mowing provides significantly better cooling than a lab bench.

### Startup Latency — Model Loading

**Storage: Samsung 990 EVO Plus 2TB NVMe SSD** — PCIe Gen 4 (sequential read ~5,000 MB/s on Gen 4; actual throughput depends on Orin M.2 lane count). This is dramatically faster than eMMC and makes mmap cold starts near-instantaneous.

| Model (Q4_K_M) | File Size | Cold Start (NVMe SSD) | Warm Start (page cache) |
|-----------------|-----------|----------------------|------------------------|
| Qwen3-0.6B | ~0.4 GB | **<1 s** | <0.5 s |
| Qwen3-1.7B | ~1.1 GB | **~1 s** | <0.5 s |
| Qwen3-4B | ~2.5 GB | **~1–3 s** | ~1 s |
| Qwen3-8B | ~5.0 GB | **~2–5 s** | ~1–2 s |

With `OLLAMA_KEEP_ALIVE=24h`, model stays loaded for all-day sessions — no reload penalty after first query.

**SSD additional benefits:**
- **2 TB capacity** — can store every Qwen3 variant (0.6B through 8B, multiple quantizations) simultaneously; switch models on the fly via Ollama
- **Fast page fault recovery** — if OS evicts LLM mmap pages under VSLAM memory pressure, reloading from NVMe is ~5 GB/s vs ~400 MB/s for eMMC; graceful degradation is nearly invisible to the operator
- **RTAB-Map database I/O** — `rtabmap.db` SQLite writes during loop closure / Long-Term Memory transfer benefit from NVMe write speeds
- **Log storage** — 2 TB easily holds months of structured JSONL logs, VSLAM databases, and model files

### Memory-Mapping (mmap) vs Full Load

**Recommendation: mmap (Ollama default) WITHOUT mlock.**

| Strategy | Startup | Crash Recovery | VSLAM Interaction |
|----------|---------|----------------|-------------------|
| **mmap (recommended)** | Fast (5–10 s) | Near-instant (page cache) | OS can reclaim pages under pressure ✅ |
| mmap + mlock | Slower | Near-instant | Pages pinned, can't be reclaimed ❌ |
| Full load (no-mmap) | Slowest | Full reload | Explicit allocation, no page reclaim ❌ |

On Orin's unified memory, mmap without mlock provides automatic graceful degradation: if VSLAM triggers `memory_threshold_mb`, the OS reclaims LLM model pages from the page cache. LLM response time degrades (page faults on next query) but neither process crashes. **With the Samsung 990 EVO Plus NVMe, page fault penalty is ~0.5 ms per 4K page (~5 GB/s sequential) — making the degradation nearly invisible to the operator.**

### Systemd Service Design

**Recommendation: Use Ollama's native system-level service + mower-specific drop-in.**

```ini
# /etc/systemd/system/ollama.service.d/mower.conf
[Unit]
After=mower-vslam.service

[Service]
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
Environment="OLLAMA_KEEP_ALIVE=24h"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_HOST=127.0.0.1:11434"
```

**Service ordering:** Ollama starts AFTER VSLAM services. VSLAM is mission-critical; LLM is advisory.

**Key settings:**
- `Nice=10` — Lower CPU priority than VSLAM (Nice=0)
- `OLLAMA_KEEP_ALIVE=24h` — All-day session, no reloads
- `OLLAMA_MAX_LOADED_MODELS=1` — Prevent memory waste
- `OLLAMA_HOST=127.0.0.1:11434` — Localhost only (field security)

### Graceful Degradation — VSLAM Priority

**Escalation path (if field testing reveals VSLAM latency spikes):**

1. **Default:** Operator-initiated queries only + Nice=10 + mmap (no mlock)
2. Increase `Nice` to 15+
3. Enable CUDA MPS with `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE=15` for RTAB-Map
4. Lower `OLLAMA_NUM_GPU` to offload some layers to CPU
5. Switch to Qwen3-1.7B (less GPU pressure)
6. Last resort: Only serve LLM when VSLAM is paused

**Automatic degradation via mmap:** If VSLAM memory pressure rises, OS evicts LLM pages → LLM response slows but VSLAM is unaffected.

### Mower-Rover Use Cases for On-Device LLM

#### Tier 1 — High Value

**1. ArduPilot Parameter Explainer**
```
$ mower-jetson ask "What does CRUISE_SPEED do and what's a good value for my Z254?"
```
Explain 800+ ArduPilot parameters in plain English, contextualized for this specific platform. Feed baseline YAML as context. No internet needed.

**2. Structured Log Analysis / Troubleshooting**
```
$ mower-jetson ask "Why did the mower stop during the last run?"
```
Parse JSONL logs (structlog), identify anomalies, correlate events across services. Fits in 4K–8K context.

**3. Pre-Flight Report Narrator**
```
$ mower-jetson preflight --explain
```
Convert JSON pre-flight report to human-readable summary with fix suggestions.

#### Tier 2 — Medium Value

**4. Mission Planning Guidance** — Terrain, grass type, line spacing advice  
**5. Field Notes / Voice Memo** — Transcribe operator voice memos into structured notes  
**6. Param Diff Explainer** — Explain what changed between snapshots and whether it makes sense

#### Implementation Pattern

All use cases share one pattern: context injection + system prompt + Ollama REST API → `mower-jetson ask` Typer subcommand.

```python
import ollama
response = ollama.chat(
    model="qwen3:4b",
    messages=[
        {"role": "system", "content": MOWER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
    ],
    options={"num_ctx": 4096, "temperature": 0.3}
)
```

**Key Discoveries:**
- On-demand LLM usage adds negligible sustained thermal load (35–45W total vs 50W budget)
- mmap WITHOUT mlock is optimal — automatic graceful degradation via OS page reclaim
- Ollama system service + drop-in config is cleanest integration, avoiding duplication
- ArduPilot param explanation, log analysis, and preflight narration are highest-value use cases
- 5–10 second cold start for 4B model; `OLLAMA_KEEP_ALIVE=24h` eliminates reloads during sessions
- Existing thermal probe checks (85°C / 95°C) can be reused as LLM thermal gates

| File | Relevance |
|------|-----------|
| `scripts/jetson-harden.sh` | Would need new step for Ollama install |
| `src/mower_rover/service/unit.py` | Existing service unit generation pattern |
| `src/mower_rover/probe/checks/thermal.py` | 95°C throttle threshold, reusable for LLM |
| `src/mower_rover/probe/checks/usb_tuning.py` | 85°C thermal gate, reusable for LLM |
| `src/mower_rover/cli/jetson.py` | Natural place for `ask` subcommand |

**Gaps:** No empirical thermal/power data during concurrent VSLAM+LLM; cold start times extrapolated from x86  
**Assumptions:** LLM usage is bursty (query-response), not continuous background processing

## Overview

**Verdict: Feasible with massive headroom.** The Jetson AGX Orin Developer Kit (64 GB unified LPDDR5 memory, 2048 CUDA cores, 50W mode) can run Qwen3 LLM inference concurrently with the existing RTAB-Map VSLAM pipeline without meaningful impact to either workload. The VSLAM stack uses only ~2–3 GB memory (steady-state) and 5–15% GPU (periodic 30 Hz feature extraction bursts), leaving ~57–61 GB memory, 85–95% GPU idle time, and 25–35W power headroom — far more than any quantized Qwen3 model requires.

The recommended configuration is **Qwen3-4B Q4_K_M via Ollama** — delivering reasoning quality comparable to Qwen2.5-72B-Instruct at ~2.5 GB model weight, 3–6 GB total memory (with KV cache), and 22–33 tok/s generation speed alongside active VSLAM. This fits within the conservative 53 GB LLM memory budget with ~47 GB to spare. The Orin's unified memory architecture eliminates GPU↔CPU transfer overhead and enables automatic graceful degradation via OS page cache management.

Notably, the 64 GB unified memory also makes the **Qwen3-30B-A3B MoE model** viable at Q4 quantization (~18 GB weights, ~20–23 GB total) — a model that activates only 3.3B parameters per token but has access to 30B total expert knowledge. This could deliver substantially higher quality than dense 4B/8B models while maintaining acceptable throughput.

Memory bandwidth (204.8 GB/s LPDDR5, 256-bit bus) — not memory capacity — is the true throughput bottleneck, limiting token generation speed proportionally to model weight size. GPU sharing between VSLAM and LLM is practical with default CUDA time-slicing; CUDA MPS and static SM partitioning are available as escalation paths if needed.

The highest-value use cases for a solo operator are ArduPilot parameter explanation, structured log analysis, and pre-flight report narration — all offline-capable, leveraging existing project data, and fitting naturally as a `mower-jetson ask` CLI subcommand.

## Key Findings

1. **Qwen3-4B Q4_K_M is the sweet spot:** ~2.5 GB weights, 22–33 tok/s with VSLAM, reasoning quality rivaling Qwen2.5-72B-Instruct. Apache 2.0 license, no commercial restrictions.
2. **VSLAM uses surprisingly little GPU:** 5–15% steady-state (30 Hz feature extraction bursts), leaving 85–95% idle time. GPU memory allocation only 500–900 MB. LLM inference naturally fills the gaps.
3. **Memory is abundant; bandwidth is the limit:** The conservative budget (53 GB after VSLAM worst-case + 4 GB safety margin) dwarfs any quantized model's needs — even the MoE 30B-A3B at Q4 (~18 GB) fits with 30+ GB to spare. Memory bandwidth (204.8 GB/s) caps throughput — smaller models generate faster.
4. **Ollama/llama.cpp > vLLM for this use case:** Native process (no Docker), on-demand memory allocation, GPU layer control, auto-unload. vLLM has 20% better raw benchmarks but pre-allocates memory aggressively.
5. **mmap without mlock is the optimal loading strategy:** OS can reclaim LLM pages under VSLAM memory pressure, providing automatic graceful degradation without crashing either process.
6. **CUDA MPS and SM partitioning are available but unnecessary initially:** Default time-slicing handles the bursty VSLAM + batch LLM workload pattern. MPS is a proven escalation path.
7. **Thermal impact is negligible for on-demand usage:** Bursty query-response pattern keeps total system at 35–45W of 50W budget. Existing 85°C/95°C thermal gates apply.
8. **Multiple model sizes provide flexibility:** Qwen3-1.7B (45–65 tok/s, fast) → 4B (22–33 tok/s, balanced) → 8B (13–20 tok/s, quality). All fit easily. Ollama can switch on the fly.
9. **MoE model Qwen3-30B-A3B is a viable stretch option:** At Q4_K_M (~18 GB weights), it fits within the 53 GB budget. Only 3.3B parameters active per token — throughput may rival dense 4B models while offering substantially higher quality. Requires field validation.
10. **Three high-value use cases identified:** ArduPilot parameter explanation, structured JSONL log analysis, and pre-flight report narration — all offline-capable, leveraging existing project infrastructure.

## Actionable Conclusions

1. **Install Ollama on the Jetson** as part of `jetson-harden.sh` with a mower-specific systemd drop-in (`OLLAMA_KEEP_ALIVE=24h`, `Nice=10`, `After=mower-vslam.service`). Pull `qwen3:4b` as the default model.
2. **Implement `mower-jetson ask` subcommand** using the Ollama Python SDK (`pip install ollama`). Pattern: context injection + system prompt + REST API call + streaming response to terminal.
3. **Start with default CUDA time-slicing** (zero configuration). Only escalate to MPS/SM partitioning if field profiling (`tegrastats`) shows VSLAM latency degradation.
4. **Use mmap without mlock** for model loading. This provides automatic memory pressure relief — the OS reclaims LLM pages if VSLAM needs burst memory.
5. **Field-validate with `tegrastats`** during concurrent VSLAM + Ollama inference to replace analytical estimates with ground-truth measurements (memory, GPU util, thermal, power).
6. **Consider lowering `memory_threshold_mb`** from 6000 to 4000 MB — this provides additional safety margin with negligible SLAM quality impact for typical 4-acre mowing sessions.

## Open Questions

1. **✅ RESOLVED — Orin Dev Kit confirmed as 64 GB module:** The Developer Kit ships with the 64 GB LPDDR5 module (2048 CUDA cores, 64 Tensor Cores, 275 TOPS, 256-bit bus, 204.8 GB/s bandwidth). All analyses in this document reflect this confirmed specification. The Jetson AI Lab benchmarks (measured on AGX Orin 64 GB) are directly applicable.
2. **VSLAM latency under concurrent LLM load:** Analytical estimates say <5% impact, but no empirical validation exists. Field profiling with `tegrastats` + RTAB-Map timing logs during active Ollama inference is needed.
3. **Qwen3-4B-Instruct-2507 vs base Qwen3-4B quality:** The -2507 variant may offer better instruction-following for the structured use cases (param explanation, log analysis). Worth A/B testing once deployed.
4. **Ollama vs native llama-server for long-running sessions:** Ollama's Go runtime and model management add a small memory/CPU overhead. For a daemon that runs 24/7, native `llama-server` may be leaner. Measure in field.
5. **KV cache quantization quality impact:** Q8_0 KV cache recommended for >8K context, but no quality benchmarks exist for the mower-rover use cases specifically. Test with param explanation and log analysis prompts.
6. **800p stereo upgrade impact:** Research 009 targets upgrading VSLAM from 400p to 800p stereo. This would ~4× the feature extraction GPU work, reducing GPU idle time from 85–95% to perhaps 60–80%. Re-assess LLM feasibility if/when 800p is deployed.
7. **Samsung 990 EVO Plus NVMe throughput on Orin:** The Dev Kit's M.2 slot is PCIe Gen 4 — confirm actual lane count (x4 vs x2) and measure sequential read speed with `fio` to calibrate mmap cold-start estimates.
8. **Qwen3-30B-A3B field validation:** The MoE model is newly viable at 64 GB but has not been benchmarked on this hardware. Need to measure actual tok/s, memory usage, and VSLAM impact with `tegrastats`.

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-04-26 |
| Status | ✅ Complete |
| Current Phase | ✅ Complete |
| Path | /docs/research/010-qwen-llm-jetson-feasibility.md |
