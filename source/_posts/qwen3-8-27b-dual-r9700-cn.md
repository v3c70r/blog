---
title: 在双 Radeon AI PRO R9700 上运行 Qwen3.8-27B (UD-Q8_K_XL)
slug: qwen3-8-27b-dual-r9700
date: 2026-09-22 12:00
lang: 中
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, LocalLLaMA
author: Qing Gu
summary: 在两张 Radeon AI PRO R9700 上使用 llama.cpp 和 ROCm 运行 Qwen3.8-27B UD-Q8_K_XL 的最佳配置与实测证据。
---

> 语言：[English](/blog/2026/09/22/qwen3-8-27b-dual-r9700/) | [Francais](/blog/2026/09/22/qwen3-8-27b-dual-r9700-fr/) | [中文](/blog/2026/09/22/qwen3-8-27b-dual-r9700-cn/)

这只是我机器上的一个数据点，不是最终结论。下面是我实测出来的配置，以及每个选择背后的证据。如果你在同类硬件上跑同一个模型，这应该能帮你省下一个周末。

**如果你只想要配置，读完这一节就可以停下，分割线之后是对比和推理过程。**

## 硬件与模型

- CPU：AMD EPYC 7302（16 核 / 32 线程）
- 内存：125 GB
- 2x Radeon AI PRO R9700（gfx1201，RDNA4），每张 32 GB，共 64 GB
- 每张卡走 PCIe 5.0 x16，位于不同的 Root Complex
- 内核 6.17，ROCm 7.14
- llama.cpp 版本 `709fe755d`（build 11116）

模型：`unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL`，29.3 GiB。元数据：64 层，`n_head=24`，`n_head_kv=4`，head dim 256，`n_ctx_train=262144`，无滑动窗口，带一个 MTP 头（`nextn_predict_layers=1`）。正是这个 MTP 头让投机解码在这里变得便宜。

## 1. 内核：IOMMU passthrough

在启动参数中加入 `amd_iommu=on iommu=pt` 然后重启：

```
BOOT_IMAGE=... ro quiet splash amd_iommu=on iommu=pt
```

只有用 RCCL（第 2 步）时才需要。没有它，RCCL 会警告多 GPU 系统可能挂起。

## 2. 编译带 RCCL 的 ROCm 版 llama.cpp

```sh
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DGGML_HIP_RCCL=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rocm -j
```

两点提醒，免得你白编译一次：

- `GGML_HIP_ROCWMMA_FATTN` 在这个版本里并不存在。传了也没用（它在 cache 里始终是 `UNINITIALIZED`，而且 FA 路径里没有 rocWMMA 代码）。
- `GGML_HIP_MMQ_MFMA` 只影响 CDNA。在 RDNA4 上没有任何效果。gfx12 的 WMMA 是自动编译进去的。

## 3. 启动

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

如果你用 router/preset 模式，等价的 `config.ini`：

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

## 预期性能

在这台机器上，约 72k token 的 prompt：

- Prefill：约 1450 t/s
- 带 MTP 的解码：约 45 t/s，具体取决于文本的可预测程度
- 每次 target forward：短上下文约 53-55 ms，72k 上下文约 62 ms

如果接受率高（代码、结构化输出），你会看到接近 60 t/s。如果接受率低（创意写作），接近 40。这不是 bug，而是投机解码的固有行为。

---

以下是证据。如果你只想要配置，可以停在这里。

## 测量方法

- 核心指标：**每次 target forward 的毫秒数**，其中 `forwards = 预测 token 数 - 被接受的 draft token 数`。原始 tokens/second 会被 MTP 接受率污染，而接受率随内容变化。毫秒/forward 不会。
- 除非特别说明，所有数字都是单次运行。5% 以内的差异当作噪声。
- 所有运行都使用 `-fa on`、tensor split、MTP `n-max=3`，模型同上。

## 发现 1：带 MTP 时，tensor split 快于 layer split。但一个天真的 benchmark 会得出相反结论。

原始 `llama-bench`，不开投机解码：

| split | tg128 |
|---|---:|
| layer | 17.96 t/s |
| tensor | 16.89 t/s |

带 MTP（同一 prompt，9 token 起步，生成 256）：

| split | 每次 forward 毫秒 | tg |
|---|---:|---:|
| layer | 79.8 | 32.3 t/s |
| tensor | 54.4 | 48.8 t/s |

这里 tensor 每次 forward 大约快 1.47 倍。原因是 MTP 把每次 target forward 变成一个小 batch（1 个 bonus token 加上最多 3 个 draft token）。小 batch 能在多 GPU 上并行；单个 token 不行，此时 allreduce 的延迟占主导。

教训：一定要用你实际运行时的配置来 benchmark。一个不开投机解码的 benchmark 会告诉你保留 layer split，那会让你损失三分之一的解码吞吐。

坦白：我最初的 MTP 对比忘了传 `-sm`，所以实际上是 layer 和它自己比，然后"验证"了 layer。传对参数，看日志，如果两个配置给出完全相同的数字，先怀疑你的测试脚本，再怀疑硬件。

## 发现 2：这块硬件上 P2P 是真的，但对这个 allreduce 没用

硬件是支持的：`amdgpu.pcie_p2p=Y`，`hipDeviceCanAccessPeer` 双向都返回 1，直接 peer copy 实测约 27 GB/s，而经过 host 的中转拷贝约 14 GB/s。

但是 llama.cpp 内置的双 GPU allreduce 是通过 pinned host memory 中转的。日志写得很清楚：

```
ggml_cuda_ar_pipeline_init: initialized AllReduce pipeline: 2 GPUs,
1024 KB chunked kernel staging + 32 MB copy-engine staging per GPU
```

`GGML_CUDA_P2P=1` 只是开启 peer access，并不改变这条路径。在 tensor split + MTP 下实测：开 P2P 是 59.8 ms/forward，关掉是 60.1 ms。就是噪声。RCCL 也会自己选择传输方式，在那里关掉 P2P 数字也几乎不变。

如果你用 RCCL 编译，那就做 `iommu=pt` 这一步。否则 P2P 这个设置可以完全忽略。

## 发现 3：RCCL 大幅提升 prefill，但前提是 `NCCL_PROTO=Simple`

这个最出乎意料。tensor split + MTP，约 35.6k token 的 prompt：

| allreduce | prefill | 每次 forward 毫秒 |
|---|---:|---:|
| internal（host 中转） | 1088 t/s | 59.0 |
| RCCL，默认 | 1446 t/s | 64.2 |
| RCCL，`NCCL_PROTO=Simple` | 1444 t/s | 59.0 |

RCCL 带来 +33% 的 prefill，但它默认选择的协议会让解码慢约 10%。`Simple` 保住 prefill 的收益，同时消掉解码的损失。强行只用 `LL` 会让 prefill 崩掉（641 t/s），千万别这么做。

我也扫了显式列表（`Simple`、`LL128`、`Simple,LL128`、`Simple,LL,LL128`）。只要列表里包含 `Simple` 或 `LL128`，它们彼此之间都在约 1 ms 以内。选 `Simple` 就行。

## 发现 4：`-ub 1024` 是白来的 prefill 收益

72k 上下文，各跑两次：

| ubatch | prefill |
|---|---:|
| 512 | 1331 / 1375 t/s |
| 1024 | 1438 / 1492 t/s |

约 +8%，解码不变。`-b 2048` 保持不变。

## 发现 5：在这里不要量化 KV cache

72k 上下文，RCCL + `Simple`：

| KV 类型 | 每次 forward 毫秒 |
|---|---:|
| f16 | 63.2 |
| q8_0 | 68.6 |
| q4_0 | 67.8 |

这里的 KV cache 很大：`2 * 64 层 * 1024 * 2 字节` = 每个 token 256 KB，72k 就是 18 GB。很想把它压小。但在 flash attention 下，attention kernel 里的反量化开销比省下的带宽更大。保持 f16。

## 发现 6：`spec-draft-n-max` 取决于工作负载

tensor split，生成 384 token：

| `n-max` | 散文 t/s | 散文接受率 | 代码 t/s | 代码接受率 |
|---:|---:|---:|---:|---:|
| 2 | 44.0 | 59.0% | 50.0 | 74.8% |
| 3 | **48.7** | 54.4% | 58.3 | 72.4% |
| 4 | 42.9 | 38.2% | **62.4** | 69.4% |
| 5 | 46.7 | 40.6% | 57.6 | 55.5% |

每多一个 draft token，每次 forward 大约多 5 ms。只有当这些 token 持续被接受时才划算。散文超过 3 就不够可预测了。代码可以。混合流量用 3，如果主要是代码或结构化输出就用 4。

## 没有效果的东西

- `-DGGML_HIP_ROCWMMA_FATTN=ON`：这个版本里没有这个选项。
- `GGML_HIP_MMQ_MFMA=ON`：只对 CDNA 有效。
- `GGML_CUDA_P2P=1`：两种 allreduce 下都没有可测量的效果。
- KV 量化：反而更慢。

## 注意事项

- 一台机器、一个模型、一个版本。你的数字会不同，尤其是 prefill。
- MTP 接受率取决于内容，所以不同 prompt 的 tokens/second 波动很大。
- 大部分数字是单次运行。5% 以内的差异不显著。
- 解码数字取决于模型的量化。这里是 Q8。同一个模型的 Q4 量化解码大约会快一倍，因为解码受内存带宽限制，代价是部分质量。

如果你复现了这些测试但数字不同，我很想听听。
