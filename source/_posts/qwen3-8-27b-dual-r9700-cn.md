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

**注意：** 以下数据仅源于我的个人测试环境，不代表最终结论。本文旨在分享我实测出的最优配置及其背后的技术支撑。如果你正计划在同类硬件上运行相同模型，这份实测指南将帮你节省大量的试错成本。

**如果你只想快速获取配置，请直接阅读第一章节即可。分割线之后将深入探讨性能对比与技术推理。**

## 硬件与模型概览

- **CPU：** AMD EPYC 7302（16 核 / 32 线程）
- **内存：** 125 GB
- **GPU：** 2x Radeon AI PRO R9700（gfx1201，RDNA4），每张 32 GB（共 64 GB）
- **互连：** 每张卡连接至独立的 PCIe 5.0 x16 通道（位于不同的 Root Complex）
- **软件环境：** 内核 6.17，ROCm 7.14
- **推理框架：** llama.cpp 版本 `709fe755d`（build 11116）

**目标模型：** `unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL`，模型大小 29.3 GiB。
**模型元数据：** 64 层，`n_head=24`，`n_head_kv=4`，head dim 256，`n_ctx_train=262144`。模型支持滑动窗口并带有一个 MTP 头（`nextn_predict_layers=1`），这使得投机解码（Speculative Decoding）在这里非常高效。

## 1. 内核：IOMMU Passthrough

在启动参数中加入 `amd_iommu=on iommu=pt` 并重启：

```bash
BOOT_IMAGE=... ro quiet splash amd_iommu=on iommu=pt
```

*注：此步骤仅在后续使用 RCCL（第 2 步）时必需。若不配置，RCCL 会发出多 GPU 系统可能挂起的警告。*

## 2. 编译带 RCCL 支持的 ROCm 版 llama.cpp

```bash
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DGGML_HIP_RCCL=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rocm -j
```

**编译避坑指南：**
- `GGML_HIP_ROCWMMA_FATTN`：当前版本不支持该选项，传参无效（Cache 中始终为 `UNINITIALIZED`）。
- `GGML_HIP_MMQ_MFMA`：仅对 CDNA 架构有效。在 RDNA4 上无任何影响，gfx12 的 WMMA 代码会自动编译入库。

## 3. 启动命令

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

如果你更倾向于使用 Router/Preset 模式，对应的 `config.ini` 配置如下：

```ini
[*]
host = 0.0.0.0
port = 8080

+[qwen3-27b]
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

## 预期性能表现

在当前配置下，针对约 72k token 的 Prompt 测试结果：

- **Prefill 速度：** 约 1450 t/s
- **带 MTP 的解码速度：** 约 45 t/s（高度依赖文本的可预测性）
- **单次 Target Forward 耗时：** 短上下文约 53-55 ms，72k 上下文约 62 ms
- **性能波动：** 逻辑性强的文本（如代码、结构化输出）接受率高，速度可接近 60 t/s；创意类文本接受率低，速度接近 40 t/s。这种波动属于投机解码的固有特性。

---

*以下为技术细节对比与推理过程。*

## 测量方法论

- **核心指标：** **每次 Target Forward 的耗时**。因为 MTP 的接受率会随内容变动，导致原始 tokens/s 波动剧烈。而耗时指标更能真实反映硬件能力。
- **统计原则：** 所有数据均源于单次运行。5% 以内的波动视为环境噪声。
- **一致性：** 所有测试均开启 `-fa on`、使用 tensor split、MTP `n-max=3`。

## 发现 1：Tensor Split 在带 MTP 时优于 Layer Split

原始 `llama-bench`（不带投机解码）结果：
| 分割模式 | tg128 速度 |
|---|---|
| Layer | 17.96 t/s |
| Tensor | 16.89 t/s |

带 MTP 模式下（同一 Prompt，9 token 起步，生成 256）：
| 分割模式 | 每次 Forward 耗时 | 生成速度 (tg) |
|---|---|---|
| Layer | 79.8 ms | 32.3 t/s |
| Tensor | 54.4 ms | 48.8 t/s |

**结论：** Tensor 分割在每次 Forward 中快了约 1.47 倍。原因是 MTP 将单次目标转发转化为一个小 Batch（1 个 Bonus token + 最多 3 个 Draft token），小 Batch 极利于多 GPU 并行，而单个 Token 会受限于 allreduce 的延迟。

**教训：** 务必使用你实际运行时的配置进行 Benchmark。单纯的 `llama-bench` 会误导你保留 Layer Split，实则会让你损失 1/3 的解码吞吐。

## 发现 2：硬件支持 P2P，但对当前 AllReduce 无效

硬件端支持 P2P：`amdgpu.pcie_p2p=Y`，`hipDeviceCanAccessPeer` 双向返回 1。实测 Peer 直接拷贝约 27 GB/s，而经过 Host 中转约 14 GB/s。

然而，llama.cpp 内置的双 GPU AllReduce 仍通过 Pinned Host Memory 中转。日志明确显示：
`ggml_cuda_ar_pipeline_init: initialized AllReduce pipeline: 2 GPUs, 1024 KB chunked kernel staging + 32 MB copy-engine staging per GPU`

`GGML_CUDA_P2P=1` 仅开启了 Peer 权限，并没改变这一路径。实测开启 P2P 时为 59.8 ms/Forward，关闭时为 60.1 ms。纯属噪声。

## 发现 3：RCCL 显著提升 Prefill，但必须配合 `NCCL_PROTO=Simple`

在 Tensor Split + MTP 模式下，针对 ~35.6k token 的 Prompt：
| AllReduce 类型 | Prefill 速度 | 每次 Forward 耗时 |
|---|---|---|
| 内部（Host 中转） | 1088 t/s | 59.0 ms |
| RCCL（默认） | 1446 t/s | 64.2 ms |
| RCCL (`NCCL_PROTO=Simple`) | 1444 t/s | 59.0 ms |

RCCL 提供了约 33% 的 Prefill 收益，但默认协议会让解码变慢 10%。使用 `Simple` 协议可以保留 Prefill 收益并消除解码惩罚。强行使用 `LL` 协议会导致 Prefill 崩溃（降至 641 t/s），切勿尝试。

## 发现 4：`-ub 1024` 是“免费”的 Prefill 收益

针对 72k 上下文（两次运行）：
| ubatch | Prefill 速度 |
|---|---|
| 512 | 1331 / 1375 t/s |
| 1024 | 1438 / 1492 t/s |

收益约 +8%，而解码速度保持不变。`-b 2048` 参数依然适用。

## 发现 5：此场景下不要量化 KV Cache

在 RCCL + `Simple` 模式下（72k 上下文）：
| KV 类型 | 每次 Forward 耗时 |
|---|---|
| f16 | 63.2 ms |
| q8_0 | 68.6 ms |
| q4_0 | 67.8 ms |

KV Cache 占用巨大（约 18 GB）。虽然想通过量化节省空间，但在 Flash Attention 架构下，反量化带来的内核开销超过了节省的带宽。保持 f16 性能最优。

## 发现 6：`spec-draft-n-max` 取决于负载类型

Tensor Split 模式，生成 384 token：
| `n-max` | 散文速度 | 散文接受率 | 代码速度 | 代码接受率 |
|---|---|---|---|---|
| 2 | 44.0 t/s | 59.0% | 50.0 t/s | 74.8% |
| 3 | **48.7 t/s** | 54.4% | 58.3 t/s | 72.4% |
| 4 | 42.9 t/s | 38.2% | **62.4 t/s** | 69.4% |
| 5 | 46.7 t/s | 40.6% | 57.6 t/s | 55.5% |

每增加一个 Draft token，每次 Forward 耗时约增加 5 ms。只有当 Draft token 被持续接受时，这才是划算的。散文在超过 3 个时可预测性大幅下降；代码则可以。建议混合流量使用 3，纯代码/结构化输出使用 4。

## 无效的优化项
- `-DGGML_HIP_ROCWMMA_FATTN=ON`：此版本不支持。
- `GGML_HIP_MMQ_MFMA=ON`：仅对 CDNA 架构有效。
- `GGML_CUDA_P2P=1`：对当前 AllReduce 路径无显著影响。
- KV 量化：反而降低了推理速度。

## 注意事项
- **环境唯一性：** 数据仅代表我的机器，你的硬件/版本差异会导致数字不同（尤其是 Prefill）。
- **MTP 变动性：** 接受率随内容剧烈变动，因此 tokens/s 不是稳定的衡量标准。
- **量化差异：** 此测试基于 Q8 量化。Q4 量化虽然解码速度可能翻倍（受限于内存带宽），但会伴随明显的质量损失。

---

### 关键数据校验核对表
- **硬件：** 2x Radeon AI PRO R9700 (gfx1201)
- **模型：** Qwen3.8-27B-GGUF (UD-Q8_K_XL)
- **内核参数：** `amd_iommu=on iommu=pt`
- **编译参数：** `GGML_HIP=ON`, `GGML_HIP_RCCL=ON`, `AMDGPU_TARGETS=gfx1201`
- **核心优化：** `NCCL_PROTO=Simple`, `GGML_CUDA_ALLREDUCE=nccl`
- **MTP 配置：** `spec-type=draft-mtp`, `spec-draft-n-max=3`
- **Tensor Split：** `tensor-split=1,1`
- **KV 状态：** 保持 f16（不进行 KV 量化）
- **测得性能：** Prefill ~1450 t/s | 解码 ~45-60 t/s (视内容而定)
