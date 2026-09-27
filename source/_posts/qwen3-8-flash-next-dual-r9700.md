---
title: Running Qwen3.8-Flash-Next (UD-Q4_K_XL, 125B MoE) with MTP on 2x Radeon AI PRO R9700
slug: qwen3-8-flash-next-dual-r9700
date: 2026-09-27 12:00
lang: en
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, MTP, LocalLLaMA
author: Qing Gu
summary: Measured config and evidence for running the 125B Qwen3.8-Flash-Next MoE with MTP speculative decoding on two Radeon AI PRO R9700, including the MTP OOM fix and the expert offload strategy.
---

> Languages: [English](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700/) | [Français](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700-fr/) | [中文](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700-cn/)

**Note:** The following data points are derived solely from my personal test environment and do not represent universal conclusions. This is a follow-up to my earlier post on running Qwen3.8-27B on the same machine. This model is a different architecture and about 3.5x larger, so most of the earlier tuning does not carry over. Here I share the configurations I measured and the evidence behind each choice.

**If you only want the configuration, read this section and stop. The comparison and reasoning are located after the horizontal rule.**

## Hardware and Model Overview

Same machine as the previous post:

- **CPU:** AMD EPYC 7302 (16 cores / 32 threads)
- **RAM:** 125 GB
- **GPU:** 2x Radeon AI PRO R9700 (gfx1201, RDNA4), 32 GB each (64 GB total)
- **Interconnect:** Each GPU connected to a dedicated PCIe 5.0 x16 lane (on different root complexes)
- **Software Environment:** Kernel 6.17, ROCm 7.14
- **Inference Framework:** llama.cpp on the `qwen4exp/mtp` branch at `6fcaa16f4` (build 11098), built for ROCm

**Target Model:** `unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL`, size 103.7 GiB (111.3 GB). This is a 125B MoE.
**MTP Head:** `unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf`, 2.6 GB.

**Metadata:** architecture `qwen4exp`, 48 blocks. Every 4th block is a full attention layer (12 total); the other 36 are linear attention / SSM layers. `n_embd=2560`, `n_head=24`, `n_head_kv=2`, key/value length 256, `n_ctx_train=262144`. 512 experts per layer, 10 active, expert FFN 640, shared expert FFN 640. The full attention layers use a block indexer (`attention.indexer.top_k=2048`) with a compression ratio of 4, so long-context attention is bounded by the top-k rather than the raw context length. The model ships one MTP head (`nextn_predict_layers=1`).

## 1. Framework: you need the MTP fork, not stock llama.cpp

Stock llama.cpp (I tested `709fe755d`, build 11116) exposes `--spec-type draft-mtp`, but it has no MTP graph for the `qwen4exp` architecture. The shared MTP head also fails to load there:

```text
E llama_model_load: error loading model: check_tensor_dims: tensor 'token_embd.weight' not found
```

The shared head deliberately omits the token embedding and output projection and borrows them from the target model. Mainline has no cross-model tensor borrowing, so the shared head cannot be loaded at all. Build the branch instead:

```bash
git clone --branch qwen4exp/mtp https://github.com/danielhanchen/llama.cpp
cmake -S llama.cpp -B llama.cpp/build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build llama.cpp/build-rocm -j
```

**Note:** My fork build is `GGML_HIP_RCCL=OFF`. The tensor split and RCCL findings from the previous post do not apply here anyway: tensor split is not implemented for this architecture (see Finding 3).

## 2. Download the model and the shared MTP head

```bash
hf download unsloth/Qwen3.8-Flash-Next-GGUF \
  --local-dir unsloth/Qwen3.8-Flash-Next-GGUF \
  --include "UD-Q4_K_XL/*" \
  --include "*mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf*"
```

The head lands in the `MTP/` subfolder. Auto-discovery does not search that folder, so always pass `-md` explicitly.

## 3. Execution

```bash
./llama-server \
  -hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL \
  -md unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  --spec-type draft-mtp --spec-draft-n-max 3 \
  -ngl 999 \
  -ot "blk\.(0|1|2|3|4|5|6|7|8|9|10)\.ffn_(up|down|gate|gate_up)_(ch|)exps=CPU,blk\.(37|38|39|40|41|42|43|44|45|46|47)\.ffn_(up|down|gate|gate_up)_(ch|)exps=CPU" \
  -c 131072 -np 1 \
  -b 2048 -ub 1024 -t 24 \
  -fa on --load-mode none --no-mmproj \
  --host 0.0.0.0 --port 8080
```

The two `-ot` patterns keep the routed experts of layers 0-10 and 37-47 in RAM and everything else on the GPUs. This distributes the RAM-resident experts across low and high layers so that both cards end up with a similar number of GPU expert layers.

If you just want the model to start and are happy with a small context, the single change that fixes the MTP out-of-memory error is a larger fit margin:

```bash
./llama-server \
  -hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL \
  -md unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  --spec-type draft-mtp --spec-draft-n-max 3 \
  --fit-target 4096 \
  --host 0.0.0.0 --port 8080
```

## Expected Performance

On this machine, at 131072 context, greedy sampling:

- **Prefill Speed:** ~474 t/s with `-ub 1024`
- **Decode with MTP:** ~34 t/s
- **MTP Acceptance:** ~0.54, mean accepted length ~2.6
- **VRAM in use:** ~59.8 GB of 64 GB
- **RAM in use:** ~44 GB

Prefill of a full 128k prompt takes roughly 4.5 minutes. Decode speed is fairly flat with context because 36 of 48 layers are linear attention and the full attention layers are bounded by the indexer top-k.

---

*The following sections contain technical evidence and reasoning.*

## Methodology

- **Metric of Record:** tokens/second for both prefill (pp) and decode (tg), plus the MTP acceptance rate and mean accepted length reported by the server.
- **Sampling:** greedy (`temperature=0`) for every run. Speculative decoding throughput depends on how predictable the text is, so temperature 0 removes one source of variance. Acceptance still differs between configurations because a different GPU/CPU placement changes floating-point results slightly and therefore the generated text.
- **Prompt:** unless noted, a 6669-token prompt and 400 generated tokens.
- **Statistical Principle:** single runs. Differences under 5% are treated as environmental noise.
- **Consistency:** `-c 131072 -np 1`, `-fa on`, and `--no-mmproj` for all runs.

## Finding 1: The shared MTP head OOMs Under the Default Fit

The default configuration from the model card fails during load:

```text
E ggml_backend_cuda_buffer_type_alloc_buffer: allocating 2647.04 MiB on device 1: cudaMalloc failed: out of memory
E alloc_tensor_range: failed to allocate ROCm1 buffer of size 2775623424
E llama_model_load: error loading model: unable to allocate ROCm1 buffer
```

Two things combine here:

1. `--fit` sizes the main model with a default margin of 1024 MiB per device, so both cards are filled to within 1 GiB.
2. `--fit` cannot account for the MTP head. Measuring an extra context needs the target context, which does not exist yet, so the fit logs `qwen4exp requires ctx_other to be set (this warning is normal during memory fitting)` and fits without it.

The head needs 2.6 GB but only ~1 GB was reserved. Raising the margin fixes it:

```bash
--fit-target 4096
```

That loaded cleanly. With `-c 32768` it also loads, because an explicit context lets the fit move more layers to the CPU to make room.

## Finding 2: MTP is Worth It, and Stock llama.cpp Cannot Provide It

Same prompt, same offload (24 expert layers in RAM, `--load-mode none`):

| Build | MTP | Prefill | Decode | Acceptance |
|---|---|---|---|---|
| stock llama.cpp `709fe755d` | no | 368 t/s | 23.7 t/s | - |
| fork `qwen4exp/mtp` | no | 368 t/s | 23.4 t/s | - |
| fork `qwen4exp/mtp` | yes, `n-max 3` | 351 t/s | 33.8 t/s | 0.54 |

Without MTP the two builds are identical. With MTP the fork is about 1.45x faster on decode. So there is no reason to run this model without MTP here, and no reason to use stock llama.cpp for it.

## Finding 3: Tensor Split Is Not Implemented for This Architecture

The previous post showed tensor split beating layer split with MTP. It does not apply here:

```text
E llama_model_load: error loading model: LLAMA_SPLIT_MODE_TENSOR not implemented for architecture 'qwen4exp'
```

Layer split (with per-tensor `-ot` overrides) is the only option. This is also why the RCCL and P2P tuning from the previous post is not relevant on this model.

## Finding 4: This Model Does Not Fit, so Expert Offload Dominates

Exact tensor sizes from the UD-Q4_K_XL shards:

| Category | Size |
|---|---|
| Routed experts | 71.7 GiB |
| PLE n-gram embedding table | 26.8 GiB |
| Attention | 2.4 GiB |
| Output projection | 0.6 GiB |
| Token embedding | 0.6 GiB |
| SSM | 0.6 GiB |
| Hyper-connections | 0.3 GiB |
| Shared experts | 0.2 GiB |
| Indexer | 0.04 GiB |
| **Total** | **103.7 GiB** |

The routed experts alone are larger than the 64 GB of VRAM. The PLE table is read lazily and stays in RAM. The strategy is therefore the opposite of the 27B: keep everything except the routed experts on the GPU (`-ngl 999`), and keep as many expert layers in RAM as needed to fit.

| Expert layers in RAM | Prefill | Decode | VRAM |
|---|---|---|---|
| 48 (all) | 170 t/s | 24.9 t/s | 17 GB |
| 24 | 280 t/s | 32.9 t/s | 55 GB |
| 22 | 474 t/s | 34.1 t/s | 60 GB |
| 20 | 490 t/s | 34.5 t/s | 63 GB |

The 20-layer row fits with less than 1 GB to spare, which is too fragile for everyday use. I settled on 22.

## Finding 5: `--n-cpu-moe` Concentrates the Experts on One GPU

The obvious way to keep the first N layers of experts in RAM is `--n-cpu-moe N`. Do not use it here. Because the split is by layer, putting layers 0-19 in RAM leaves all of the GPU expert layers at layers 20-47, and those are assigned to the second GPU:

```text
E alloc_tensor_range: failed to allocate ROCm1 buffer of size 39613846784
```

That is a single 37.8 GiB allocation on one card. Distributing the override across low and high layers instead balances both cards and loads fine. This is the `-ot` pattern in the execution section.

## Finding 6: `--load-mode none` Helps the RAM-Resident Experts

Same offload and same generation, only the load mode changed:

| Load Mode | Prefill | Decode |
|---|---|---|
| mmap (default) | 280 t/s | 32.9 t/s |
| none | 327 t/s | 36.4 t/s |

The experts in RAM are read on every token, so avoiding page faults for them is a real gain: about +17% prefill and +11% decode. The loader even hinted at this:

```text
W llama_model_loader: tensor overrides to CPU are used with mmap enabled
  - consider using --load-mode none for better performance
```

The cost is a slower startup, since the model is read into RAM instead of mapped.

## Finding 7: `-ub 1024` for Prefill, `n-max 2` or `3` for Decode

For prefill, at 22 expert layers in RAM:

| ubatch | Prefill |
|---|---|
| 512 | 351 t/s |
| 1024 | 398 t/s |
| 2048 | 386 t/s |

1024 is the sweet spot. Prefill is the dominant cost for a 128k prompt, so it is worth optimizing.

For decode, with 24 expert layers in RAM:

| `n-max` | Decode | Acceptance | Mean Length |
|---|---|---|---|
| 2 | 33.0 t/s | 0.669 | 2.33 |
| 3 | **33.8 t/s** | 0.542 | 2.62 |
| 4 | 28.8 t/s | 0.415 | 2.65 |
| 5 | 26.7 t/s | 0.359 | 2.78 |

Above 3 the acceptance collapses while the draft cost keeps growing, because the MTP head is itself a 512-expert MoE layer and every extra draft is a full extra forward. Use 2 for mixed traffic and 3 when the output is predictable. This is the same shape as the finding on the 27B, but the cliff is steeper here.

## Finding 8: 24 Threads, Not 32

With 24 expert layers in RAM:

| Threads | Decode |
|---|---|
| 16 | 33.3 t/s |
| 24 | 33.8 t/s |
| 32 | 20.9 t/s |

32 threads (SMT) is much worse. 24 is a small win over the default 16.

## Ineffective Optimizations

- Tensor split: not implemented for `qwen4exp`.
- RCCL: not available in the MTP fork build, and irrelevant without tensor split.
- `--n-cpu-moe N`: concentrates the GPU experts on one card and OOMs.
- `n-max` 4 or 5: lower decode throughput than 2 or 3.
- Threads above 24: SMT contention hurts.
- Running the stock llama.cpp build: no MTP for this architecture.

## Caveats

- **Environment Specificity:** Data reflects my machine and versions. Prefill in particular will vary.
- **Single Runs:** Differences under 5% are noise. Where I could not separate two configs, I said so.
- **MTP Variability:** Acceptance depends on content, so tokens/second is not a stable metric.
- **Fork Stability:** The `qwen4exp/mtp` branch is the pull request under review. Flags and behavior may change before it lands in mainline.
- **Not Tested:** KV cache quantization and CPU-side thread affinity. I kept f16 KV because the KV footprint is small here (only 12 of 48 layers carry a full KV), so quantizing it did not look worth the risk.

If you reproduce this and get different numbers, I would like to hear about it.

---

### Key Data Checklist

- **Hardware:** 2x Radeon AI PRO R9700 (gfx1201), 125 GB RAM
- **Model:** Qwen3.8-Flash-Next-GGUF (UD-Q4_K_XL), 103.7 GiB
- **MTP Head:** mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf
- **Build:** llama.cpp `qwen4exp/mtp` at `6fcaa16f4`, `GGML_HIP=ON`, `AMDGPU_TARGETS=gfx1201`
- **Core Optimizations:** `-ngl 999` with distributed `-ot` CPU experts, `--load-mode none`, `-ub 1024`, `-t 24`
- **MTP Config:** `--spec-type draft-mtp --spec-draft-n-max 3`
- **Context:** `-c 131072 -np 1`
- **KV State:** f16 (not tested with quantization)
- **Measured Performance:** Prefill ~474 t/s | Decode ~34 t/s | Acceptance ~0.54
