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

> Languages: [English](/blog/2026/09/22/qwen3-8-27b-dual-r9700/) | [Francais](/blog/2026/09/22/qwen3-8-27b-dual-r9700-fr/) | [中文](/blog/2026/09/22/qwen3-8-27b-dual-r9700-cn/)

This is one data point, not the final word. It is a config I measured on my machine, plus the evidence behind each choice. If you run the same model on the same kind of hardware, this should save you a weekend.

**If you only want the config, read this section and stop. The comparison and reasoning are after the horizontal rule.**

## Hardware and model

- CPU: AMD EPYC 7302 (16 cores / 32 threads)
- RAM: 125 GB
- 2x Radeon AI PRO R9700 (gfx1201, RDNA4), 32 GB each, 64 GB total
- Each GPU on PCIe 5.0 x16, on different root complexes
- Kernel 6.17, ROCm 7.14
- llama.cpp at `709fe755d` (build 11116)

Model: `unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL`, 29.3 GiB. Metadata: 64 layers, `n_head=24`, `n_head_kv=4`, head dim 256, `n_ctx_train=262144`, no sliding window, and an MTP head (`nextn_predict_layers=1`). That MTP head is what makes speculative decoding cheap here.

## 1. Kernel: IOMMU passthrough

Add `amd_iommu=on iommu=pt` to the kernel command line and reboot:

```
BOOT_IMAGE=... ro quiet splash amd_iommu=on iommu=pt
```

You only need this for RCCL (step 2). Without it RCCL warns about possible hangs on multi-GPU systems.

## 2. Build llama.cpp for ROCm with RCCL

```sh
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DGGML_HIP_RCCL=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rocm -j
```

Two notes so you do not waste a rebuild:

- `GGML_HIP_ROCWMMA_FATTN` does not exist in this revision. Passing it does nothing (it stays `UNINITIALIZED` in the cache, and there is no rocWMMA code in the FA path).
- `GGML_HIP_MMQ_MFMA` only affects CDNA. On RDNA4 it is a no-op. gfx12 WMMA is compiled in automatically.

## 3. Run it

```sh
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

Same thing as a `config.ini` preset, if you use router mode:

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

## What to expect

On a ~72k-token prompt on this machine:

- Prefill: ~1450 t/s
- Decode with MTP: ~45 t/s, and it depends heavily on how predictable the text is
- Per target forward: ~53-55 ms at short context, ~62 ms at 72k context

If the acceptance rate is high (code, structured output), you will see closer to 60 t/s. If it is low (creative prose), closer to 40. That is not a bug, it is how speculative decoding behaves.

---

Everything below is the evidence. Stop here if you only want the config.

## How I measured

- Metric of record: **milliseconds per target forward**, where `forwards = predicted_tokens - accepted_draft_tokens`. Plain tokens/second is contaminated by MTP acceptance, which changes with the content. Milliseconds per forward is not.
- Unless stated otherwise, numbers are single runs. Treat small differences (under 5%) as noise.
- All runs used `-fa on`, tensor split, and MTP `n-max=3`, on the model above.

## Finding 1: with MTP, tensor split beats layer split. A naive benchmark says the opposite.

Raw `llama-bench`, no speculative decoding:

| split | tg128 |
|---|---:|
| layer | 17.96 t/s |
| tensor | 16.89 t/s |

With MTP (same prompt, 9-token start, 256 generated):

| split | ms per target forward | tg |
|---|---:|---:|
| layer | 79.8 | 32.3 t/s |
| tensor | 54.4 | 48.8 t/s |

Tensor is about 1.47x faster per forward here. The reason is that MTP turns each target forward into a small batch (1 bonus token plus up to 3 draft tokens). A small batch parallelizes across GPUs; a single token does not, and then the allreduce latency dominates.

Lesson: benchmark with the exact runtime you will use. A no-spec-decode benchmark would have told you to keep layer split, which would cost you a third of your decode throughput.

A confession: my first MTP comparison forgot to pass `-sm`, so it compared layer to itself and "confirmed" layer. Pass the flags, check the log, and if two configs produce identical numbers, suspect your harness before you suspect the hardware.

## Finding 2: P2P is real on this hardware, but irrelevant to this allreduce

The hardware supports it: `amdgpu.pcie_p2p=Y`, `hipDeviceCanAccessPeer` returns 1 both ways, and a direct peer copy measured ~27 GB/s versus ~14 GB/s for a host-staged copy.

But the built-in 2-GPU allreduce in llama.cpp stages through pinned host memory. The log says so directly:

```
ggml_cuda_ar_pipeline_init: initialized AllReduce pipeline: 2 GPUs,
1024 KB chunked kernel staging + 32 MB copy-engine staging per GPU
```

`GGML_CUDA_P2P=1` enables peer access, but it does not change that path. Measured with tensor split + MTP: 59.8 ms per forward with P2P on, 60.1 ms with it off. Noise. RCCL also picks its own transport, and disabling P2P there barely moves the numbers either.

If you build with RCCL, do the `iommu=pt` change. Otherwise P2P is a setting you can ignore.

## Finding 3: RCCL helps prefill a lot, but only with `NCCL_PROTO=Simple`

This is the one that surprised me. Tensor split + MTP, ~35.6k-token prompt:

| allreduce | prefill | ms per target forward |
|---|---:|---:|
| internal (host-staged) | 1088 t/s | 59.0 |
| RCCL, default | 1446 t/s | 64.2 |
| RCCL, `NCCL_PROTO=Simple` | 1444 t/s | 59.0 |

RCCL gives +33% prefill, but its default protocol selection costs about 10% on decode. `Simple` keeps the prefill win and removes the decode penalty. Forcing `LL` alone is terrible for prefill (641 t/s), so do not do that.

I also swept the explicit lists (`Simple`, `LL128`, `Simple,LL128`, `Simple,LL,LL128`). Once the list contains `Simple` or `LL128`, they are all within ~1 ms of each other. Pick `Simple` and move on.

## Finding 4: `-ub 1024` is a free prefill gain

At 72k context, two runs each:

| ubatch | prefill |
|---|---:|
| 512 | 1331 / 1375 t/s |
| 1024 | 1438 / 1492 t/s |

About +8%, decode unchanged. `-b 2048` stays.

## Finding 5: do not quantize the KV cache here

At 72k context with RCCL + `Simple`:

| KV type | ms per target forward |
|---|---:|
| f16 | 63.2 |
| q8_0 | 68.6 |
| q4_0 | 67.8 |

The KV cache here is large: `2 * 64 layers * 1024 * 2 bytes` = 256 KB per token, so 18 GB at 72k. It is tempting to shrink it. But with flash attention the dequantization cost in the attention kernel is larger than the bandwidth you save. Keep f16.

## Finding 6: `spec-draft-n-max` is workload-dependent

Tensor split, 384 tokens generated:

| `n-max` | prose t/s | prose accept | code t/s | code accept |
|---:|---:|---:|---:|---:|
| 2 | 44.0 | 59.0% | 50.0 | 74.8% |
| 3 | **48.7** | 54.4% | 58.3 | 72.4% |
| 4 | 42.9 | 38.2% | **62.4** | 69.4% |
| 5 | 46.7 | 40.6% | 57.6 | 55.5% |

Each extra draft token costs ~5 ms per forward. That only pays off if the tokens keep getting accepted. Prose is not predictable enough past 3. Code is. Keep 3 for mixed traffic, use 4 if your workload is mostly code or structured output.

## Things that did nothing

- `-DGGML_HIP_ROCWMMA_FATTN=ON`: not a real option in this revision.
- `GGML_HIP_MMQ_MFMA=ON`: CDNA only.
- `GGML_CUDA_P2P=1`: no measurable effect with either allreduce.
- KV quantization: actively slower.

## Caveats

- One machine, one model, one build. Your numbers will differ, especially the prefill.
- MTP acceptance is content-dependent, so tokens/second varies a lot between prompts.
- Most numbers are single runs. Differences under 5% are not significant.
- The decode numbers depend on the model quant. This is Q8. A Q4 quant of the same model will decode roughly twice as fast because decode is memory-bandwidth bound, at some quality cost.

If you reproduce this and get different numbers, I would like to hear about it.
