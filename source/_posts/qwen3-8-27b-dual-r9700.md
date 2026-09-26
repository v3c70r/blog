---
title: Running Qwen3.8-27B (UD-Q8_K_XL) on 2x Radeon AI PRO R9700
slug: qwen3-8-27b-dual-r9700
date: 2026-09-22 12:00
lang: en
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, LocalLLaMA
author: Qing Gu
summary: Best-practice config plus measured evidence for running Qwen3.8-27B UD-Q8_K_XL on two Radeon AI PRO R9700 with llama.cpp and ROCm.
---

> Languages: [English](/blog/2026/09/22/qwen3-8-27b-dual-r9700/) | [Français](/blog/2026/09/22/qwen3-8-27b-dual-r9700-fr/) | [中文](/blog/2026/09/22/qwen3-8-27b-dual-r9700-cn/)

**Note:** The following data points are derived solely from my personal test environment and do not represent universal conclusions. This post shares the optimal configurations I've measured, along with the technical evidence supporting each choice. If you are planning to run the same model on similar hardware, this guide should save you significant trial-and-error time.

**If you only want the configuration, read this section and stop. The comparison and reasoning are located after the horizontal rule.**

## Hardware and Model Overview

- **CPU:** AMD EPYC 7302 (16 cores / 32 threads)
- **RAM:** 125 GB
- **GPU:** 2x Radeon AI PRO R9700 (gfx1201, RDNA4), 32 GB each (64 GB total)
- **Interconnect:** Each GPU connected to a dedicated PCIe 5.0 x16 lane (on different root complexes)
- **Software Environment:** Kernel 6.17, ROCm 7.14
- **Inference Framework:** llama.cpp at `709fe755d` (build 11116)

**Target Model:** `unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL`, size 29.3 GiB.
**Metadata:** 64 layers, `n_head=24`, `n_head_kv=4`, head dim 256, `n_ctx_train=262144`. The model has no sliding window and includes an MTP head (`nextn_predict_layers=1`), which makes speculative decoding highly efficient here.

## 1. Kernel: IOMMU Passthrough

Add `amd_iommu=on iommu=pt` to the kernel command line and reboot:

```bash
BOOT_IMAGE=... ro quiet splash amd_iommu=on iommu=pt
```

*Note: This is only required for RCCL (step 2). Without it, RCCL will warn about potential hangs in multi-GPU systems.*

## 2. Build llama.cpp for ROCm with RCCL

```bash
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DGGML_HIP_RCCL=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rocm -j
```

**Build Notes to Avoid Redundant Compilations:**
- `GGML_HIP_ROCWMMA_FATTN`: This option does not exist in the current revision. Passing it is a no-op (it remains `UNINITIALIZED` in the cache, and there is no rocWMMA code in the FA path).
- `GGML_HIP_MMQ_MFMA`: Only affects CDNA. It is a no-op on RDNA4; gfx12 WMMA is automatically compiled in.

## 3. Execution

```bash
NCCL_PROTO=Simple GGML_CUDA_ALLREDUCE=nccl \
  ./llama-server \
    -m Qwen3.8-27B-UD-Q8_K_XL.gguf \
    -ngl 99 -fa on \
    -sm tensor -ts 1,1 \
    -b 2048 -ub 1024 \
    --spec-type draft-mtp --spec-draft-n-max 3 \
    --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 \
    -c 98304 -np 1 \
    --host 0.0.0.0 --port 8080
```

The same can be achieved via `config.ini` in router/preset mode:

```ini
[*]
host = 0.0.0.0
port = 8080

[qwen3-27b]
hf = unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL
ngl = 99
flash-attn = true
spec-type = draft-mtp
spec-draft-n-max = 3
split-mode = tensor
tensor-split = 1,1
batch-size = 2048
ubatch-size = 1024
temp = 1.0
top-p = 0.95
top-k = 20
min-p = 0.0
presence-penalty = 0.0
repeat-penalty = 1.0
```

## Expected Performance

On this machine, for a ~72k-token prompt:

- **Prefill Speed:** ~1450 t/s
- **Decode with MTP:** ~45 t/s (highly dependent on how predictable the text is)
- **Time per Target Forward:** ~53-55 ms at short context, ~62 ms at 72k context
- **Performance Variance:** High acceptance (code, structured output) can reach nearly 60 t/s; low acceptance (creative prose) stays near 40 t/s. This fluctuation is an inherent characteristic of speculative decoding.

---

*The following sections contain technical evidence and reasoning.*

## Methodology

- **Metric of Record:** **Milliseconds per Target Forward**, where `forwards = predicted_tokens - accepted_draft_tokens`. Plain tokens/second is contaminated by MTP acceptance variance. Milliseconds per forward provides a cleaner picture of hardware capability.
- **Statistical Principle:** The data comes from single runs. Differences under 5% are treated as environmental noise.
- **Consistency:** All tests used `-fa on`, tensor split, and MTP `n-max=3` on the aforementioned model.

## Finding 1: Tensor Split Beats Layer Split with MTP

Raw `llama-bench` (no speculative decoding) results:

| Split Mode | tg128 Speed |
|---|---|
| Layer | 17.96 t/s |
| Tensor | 16.89 t/s |

With MTP (same prompt, 9-token start, 256 generated):

| Split Mode | ms per Target Forward | Generation Speed (tg) |
|---|---|---|
| Layer | 79.8 ms | 32.3 t/s |
| Tensor | 54.4 ms | 48.8 t/s |

**Conclusion:** Tensor split is roughly 1.47x faster per forward here. This is because MTP turns each target forward into a small batch (1 bonus token + up to 3 draft tokens). Small batches parallelize across GPUs, whereas a single token is bottlenecked by allreduce latency.

**Lesson:** Always benchmark using the exact runtime configuration you intend to use. A naive `llama-bench` would incorrectly suggest keeping Layer Split, which would cost you a third of your decode throughput.

A confession: my first MTP comparison forgot to pass `-sm`, so it compared layer to itself and "confirmed" layer. Pass the flags, check the log, and if two configs produce identical numbers, suspect your harness before you suspect the hardware.

## Finding 2: Hardware Supports P2P, but it's Irrelevant to this AllReduce

The hardware supports it: `amdgpu.pcie_p2p=Y`, `hipDeviceCanAccessPeer` returns 1 both ways. Direct peer copy measures ~27 GB/s versus ~14 GB/s for host-staged copy.

However, the built-in 2-GPU AllReduce in llama.cpp stages through Pinned Host Memory. The log confirms this:
`ggml_cuda_ar_pipeline_init: initialized AllReduce pipeline: 2 GPUs, 1024 KB chunked kernel staging + 32 MB copy-engine staging per GPU`

`GGML_CUDA_P2P=1` enables peer access but does not alter the path. Measured with tensor split + MTP: 59.8 ms per forward with P2P on, 60.1 ms with it off. Pure noise. RCCL also picks its own transport, and disabling P2P there barely moves the numbers either.

If you build with RCCL, do the `iommu=pt` change. Otherwise P2P is a setting you can ignore.

## Finding 3: RCCL Boosts Prefill, but Requires `NCCL_PROTO=Simple`

In Tensor Split + MTP mode, for a ~35.6k-token prompt:

| AllReduce Type | Prefill Speed | ms per Target Forward |
|---|---|---|
| Internal (Host-staged) | 1088 t/s | 59.0 ms |
| RCCL (Default) | 1446 t/s | 64.2 ms |
| RCCL (`NCCL_PROTO=Simple`) | 1444 t/s | 59.0 ms |

RCCL provides a ~33% prefill boost, but its default protocol selection costs about 10% on decode. Using `Simple` preserves the prefill gain while removing the decode penalty. Forcing `LL` alone is disastrous for prefill (drops to 641 t/s); avoid this.

I also swept the explicit lists (`Simple`, `LL128`, `Simple,LL128`, `Simple,LL,LL128`). Once the list contains `Simple` or `LL128`, they are all within ~1 ms of each other. Pick `Simple` and move on.

## Finding 4: `-ub 1024` is a "Free" Prefill Gain

At 72k context (two runs each):

| ubatch | Prefill Speed |
|---|---|
| 512 | 1331 / 1375 t/s |
| 1024 | 1438 / 1492 t/s |

About +8% gain, while decode speed remains unchanged. `-b 2048` remains optimal.

## Finding 5: Do Not Quantize the KV Cache here

At 72k context with RCCL + `Simple`:

| KV Type | ms per Target Forward |
|---|---|
| f16 | 63.2 ms |
| q8_0 | 68.6 ms |
| q4_0 | 67.8 ms |

The KV cache is substantial (~18 GB). While it is tempting to shrink it, the dequantization overhead in the attention kernel outweighs the bandwidth savings in a Flash Attention architecture. Keep f16 for optimal performance.

## Finding 6: `spec-draft-n-max` is Workload-Dependent

Tensor Split mode, 384 tokens generated:

| `n-max` | Prose Speed | Prose Accept | Code Speed | Code Accept |
|---|---|---|---|---|
| 2 | 44.0 t/s | 59.0% | 50.0 t/s | 74.8% |
| 3 | **48.7 t/s** | 54.4% | 58.3 t/s | 72.4% |
| 4 | 42.9 t/s | 38.2% | **62.4 t/s** | 69.4% |
| 5 | 46.7 t/s | 40.6% | 57.6 t/s | 55.5% |

Each extra draft token costs ~5 ms per forward. This only pays off if the draft tokens are consistently accepted. Prose predictability drops off significantly past 3; code remains viable. Use 3 for mixed traffic, and 4 for code-heavy or structured output workloads.

## Ineffective Optimizations
- `-DGGML_HIP_ROCWMMA_FATTN=ON`: Not a valid option in this revision.
- `GGML_HIP_MMQ_MFMA=ON`: CDNA only.
- `GGML_CUDA_P2P=1`: No measurable effect on the current AllReduce path.
- KV Quantization: Actively slower in this configuration.

## Caveats
- **Environment Specificity:** Data reflects my specific machine; numbers will differ based on your hardware/versions (especially Prefill).
- **MTP Variability:** Acceptance rates fluctuate with content, so tokens/second is not a stable metric.
- **Quantization Differences:** This test used Q8. A Q4 quant of the same model might decode roughly twice as fast (as it's memory-bandwidth bound), but at a noticeable quality cost.

If you reproduce this and get different numbers, I would like to hear about it.

---

### Key Data Checklist
- **Hardware:** 2x Radeon AI PRO R9700 (gfx1201)
- **Model:** Qwen3.8-27B-GGUF (UD-Q8_K_XL)
- **Kernel Params:** `amd_iommu=on iommu=pt`
- **Build Params:** `GGML_HIP=ON`, `GGML_HIP_RCCL=ON`, `AMDGPU_TARGETS=gfx1201`
- **Core Optimizations:** `NCCL_PROTO=Simple`, `GGML_CUDA_ALLREDUCE=nccl`
- **MTP Config:** `spec-type=draft-mtp`, `spec-draft-n-max=3`
- **Tensor Split:** `split-mode=tensor`, `tensor-split=1,1`
- **KV State:** Keep f16 (No KV quantization)
- **Measured Performance:** Prefill ~1450 t/s | Decode ~45-60 t/s (content dependent)
