---
title: 在双 Radeon AI PRO R9700 上运行 Qwen3.8-Flash-Next (UD-Q4_K_XL, 125B MoE) 并启用 MTP
slug: qwen3-8-flash-next-dual-r9700
date: 2026-09-27 12:00
lang: 中
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, MTP, LocalLLaMA
author: Qing Gu
summary: 在同一台机器上运行 125B Qwen3.8-Flash-Next MoE 的实测配置与证据，包含 MTP 显存溢出修复与专家层卸载策略。
---

> 语言：[English](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700/) | [Français](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700-fr/) | [中文](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700-cn/)

**注意：** 以下数据仅源于我的个人测试环境，不代表最终结论。本文是此前 Qwen3.8-27B 文章的续篇，仍在同一台机器上。本模型架构不同，体积约为前者的 3.5 倍，因此此前的大部分调优经验并不适用。本文分享我实测到的配置及其背后的证据。

**如果你只想快速获取配置，请直接阅读第一章节即可。分割线之后将深入探讨性能对比与技术推理。**

## 硬件与模型概览

与此前文章使用同一台机器：

- **CPU：** AMD EPYC 7302（16 核 / 32 线程）
- **内存：** 125 GB
- **GPU：** 2x Radeon AI PRO R9700（gfx1201，RDNA4），每张 32 GB（共 64 GB）
- **互连：** 每张卡连接至独立的 PCIe 5.0 x16 通道（位于不同的 Root Complex）
- **软件环境：** 内核 6.17，ROCm 7.14
- **推理框架：** llama.cpp 的 `qwen4exp/mtp` 分支，版本 `6fcaa16f4`（build 11098），ROCm 编译

**目标模型：** `unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL`，大小 103.7 GiB（111.3 GB），是一个 125B MoE。
**MTP 头：** `unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf`，2.6 GB。

**模型元数据：** 架构 `qwen4exp`，48 个 block。每 4 个 block 中有 1 个完整注意力层（共 12 层），其余 36 层为线性注意力 / SSM 层。`n_embd=2560`，`n_head=24`，`n_head_kv=2`，key/value 维度 256，`n_ctx_train=262144`。每层 512 个专家，激活 10 个，专家 FFN 为 640，共享专家 FFN 为 640。完整注意力层使用分块索引器（`attention.indexer.top_k=2048`），压缩比为 4，因此长上下文注意力由 top-k 决定，而非原始上下文长度。模型自带一个 MTP 头（`nextn_predict_layers=1`）。

## 1. 框架：必须使用 MTP 分支，而非原版 llama.cpp

原版 llama.cpp（实测 `709fe755d`，build 11116）虽然提供 `--spec-type draft-mtp`，但 `qwen4exp` 架构没有 MTP 计算图。共享 MTP 头在其中甚至无法加载：

```text
E llama_model_load: error loading model: check_tensor_dims: tensor 'token_embd.weight' not found
```

共享头刻意省略了 token embedding 和输出投影，改为从目标模型借用。原版没有跨模型张量借用机制，因此共享头根本无法加载。请改编译该分支：

```bash
git clone --branch qwen4exp/mtp https://github.com/danielhanchen/llama.cpp
cmake -S llama.cpp -B llama.cpp/build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build llama.cpp/build-rocm -j
```

**注：** 我的分支编译使用 `GGML_HIP_RCCL=OFF`。此前文章关于 tensor split 和 RCCL 的结论在这里本来也不适用：该架构未实现 tensor split（见发现 3）。

## 2. 下载模型与共享 MTP 头

```bash
hf download unsloth/Qwen3.8-Flash-Next-GGUF \
  --local-dir unsloth/Qwen3.8-Flash-Next-GGUF \
  --include "UD-Q4_K_XL/*" \
  --include "*mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf*"
```

MTP 头会落在 `MTP/` 子目录。自动发现不会搜索该目录，因此必须显式传入 `-md`。

## 3. 启动命令

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

两个 `-ot` 模式把第 0-10 层和第 37-47 层的路由专家保留在内存，其余全部放到 GPU。这样把常驻内存的专家分散在靠前和靠后的层，使两张卡分到的 GPU 专家层数量接近。

如果你只想让模型能启动、可以接受较小的上下文，那么修复 MTP 显存溢出的唯一改动就是加大 fit 余量：

```bash
./llama-server \
  -hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL \
  -md unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  --spec-type draft-mtp --spec-draft-n-max 3 \
  --fit-target 4096 \
  --host 0.0.0.0 --port 8080
```

## 预期性能

在这台机器上，131072 上下文、贪心采样：

- **Prefill 速度：** 使用 `-ub 1024` 时约 474 t/s
- **MTP 解码：** 约 34 t/s
- **MTP 接受率：** 约 0.54，平均接受长度约 2.6
- **显存占用：** 64 GB 中约 59.8 GB
- **内存占用：** 约 44 GB

完整 128k 提示词的 prefill 约需 4.5 分钟。解码速度随上下文变化较平缓，因为 48 层中有 36 层是线性注意力，而完整注意力层由索引器 top-k 限界。

---

*以下章节包含技术证据与推理。*

## 测试方法

- **记录指标：** prefill（pp）与解码（tg）的 tokens/秒，以及服务端输出的 MTP 接受率与平均接受长度。
- **采样：** 所有测试均使用贪心（`temperature=0`）。投机解码吞吐取决于文本的可预测性，因此温度 0 可以消除一个方差来源。不同配置之间的接受率仍有差异，因为不同的 GPU/CPU 放置会略微改变浮点结果，从而改变生成的文本。
- **提示词：** 除特别说明外，使用 6669 token 的提示词并生成 400 token。
- **统计原则：** 单次运行。低于 5% 的差异视为环境噪声。
- **一致性：** 所有测试均使用 `-c 131072 -np 1`、`-fa on` 与 `--no-mmproj`。

## 发现 1：默认 fit 下共享 MTP 头会显存溢出

模型卡上的默认配置在加载时失败：

```text
E ggml_backend_cuda_buffer_type_alloc_buffer: allocating 2647.04 MiB on device 1: cudaMalloc failed: out of memory
E alloc_tensor_range: failed to allocate ROCm1 buffer of size 2775623424
E llama_model_load: error loading model: unable to allocate ROCm1 buffer
```

两个因素叠加：

1. `--fit` 为主模型预留的默认余量是每张卡 1024 MiB，因此两张卡都会用到只剩不到 1 GiB。
2. `--fit` 无法计入 MTP 头。测量额外上下文需要目标上下文，而目标上下文此时尚不存在，因此 fit 会打印 `qwen4exp requires ctx_other to be set (this warning is normal during memory fitting)` 并在忽略它的情况下进行配置。

该头需要 2.6 GB，但只预留了约 1 GB。加大余量即可修复：

```bash
--fit-target 4096
```

这样就能正常加载。配合 `-c 32768` 也能加载，因为显式指定上下文后，fit 可以把更多层移到 CPU 来腾出空间。

## 发现 2：MTP 值得开启，而原版 llama.cpp 无法提供

相同提示词、相同卸载策略（24 层专家在内存，`--load-mode none`）：

| 编译版本 | MTP | Prefill | 解码 | 接受率 |
|---|---|---|---|---|
| 原版 llama.cpp `709fe755d` | 否 | 368 t/s | 23.7 t/s | - |
| 分支 `qwen4exp/mtp` | 否 | 368 t/s | 23.4 t/s | - |
| 分支 `qwen4exp/mtp` | 是，`n-max 3` | 351 t/s | 33.8 t/s | 0.54 |

不启用 MTP 时两个版本完全相同。启用 MTP 后分支解码约快 1.45 倍。因此在这台机器上既有理由开启 MTP，也没有理由使用原版 llama.cpp。

## 发现 3：该架构未实现 tensor split

此前文章显示 tensor split 在 MTP 下优于 layer split。这里并不适用：

```text
E llama_model_load: error loading model: LLAMA_SPLIT_MODE_TENSOR not implemented for architecture 'qwen4exp'
```

layer split（配合逐张量的 `-ot` 覆盖）是唯一选择。这也是此前文章中 RCCL 与 P2P 调优对本模型不适用的原因。

## 发现 4：该模型装不下，因此专家卸载是核心

来自 UD-Q4_K_XL 分片的精确张量大小：

| 类别 | 大小 |
|---|---|
| 路由专家 | 71.7 GiB |
| PLE n-gram 嵌入表 | 26.8 GiB |
| 注意力 | 2.4 GiB |
| 输出投影 | 0.6 GiB |
| Token 嵌入 | 0.6 GiB |
| SSM | 0.6 GiB |
| 超连接 | 0.3 GiB |
| 共享专家 | 0.2 GiB |
| 索引器 | 0.04 GiB |
| **合计** | **103.7 GiB** |

仅路由专家就超过 64 GB 显存。PLE 表是惰性读取的，留在内存即可。因此策略与 27B 相反：除路由专家外的所有内容都留在 GPU（`-ngl 999`），并把所需数量的专家层留在内存。

| 内存中的专家层数 | Prefill | 解码 | 显存 |
|---|---|---|---|
| 48（全部） | 170 t/s | 24.9 t/s | 17 GB |
| 24 | 280 t/s | 32.9 t/s | 55 GB |
| 22 | 474 t/s | 34.1 t/s | 60 GB |
| 20 | 490 t/s | 34.5 t/s | 63 GB |

20 层这一行只剩不到 1 GiB 余量，日常使用过于脆弱。我最终选择 22 层。

## 发现 5：`--n-cpu-moe` 会把专家集中到一张卡

把前 N 层专家留在内存最直观的做法是 `--n-cpu-moe N`。这里不要这样做。由于按层划分，把第 0-19 层放入内存会使所有 GPU 专家层集中在第 20-47 层，而这些层会被分配到第二张卡：

```text
E alloc_tensor_range: failed to allocate ROCm1 buffer of size 39613846784
```

这是在单张卡上一次 37.8 GiB 的分配。改为把覆盖分散到靠前和靠后的层，就能平衡两张卡并正常加载。这就是启动命令中的 `-ot` 模式。

## 发现 6：`--load-mode none` 对常驻内存的专家有帮助

相同卸载、相同生成，仅改变加载模式：

| 加载模式 | Prefill | 解码 |
|---|---|---|
| mmap（默认） | 280 t/s | 32.9 t/s |
| none | 327 t/s | 36.4 t/s |

内存中的专家在每个 token 都会被读取，因此避免缺页确实有收益：prefill 约 +17%，解码约 +11%。加载器本身也给出了提示：

```text
W llama_model_loader: tensor overrides to CPU are used with mmap enabled
  - consider using --load-mode none for better performance
```

代价是启动更慢，因为模型是被读入内存而不是映射。

## 发现 7：prefill 用 `-ub 1024`，解码用 `n-max 2` 或 `3`

prefill 方面，22 层专家在内存：

| ubatch | Prefill |
|---|---|
| 512 | 351 t/s |
| 1024 | 398 t/s |
| 2048 | 386 t/s |

1024 是最佳点。对 128k 提示词而言 prefill 是主要成本，因此值得优化。

解码方面，24 层专家在内存：

| `n-max` | 解码 | 接受率 | 平均长度 |
|---|---|---|---|
| 2 | 33.0 t/s | 0.669 | 2.33 |
| 3 | **33.8 t/s** | 0.542 | 2.62 |
| 4 | 28.8 t/s | 0.415 | 2.65 |
| 5 | 26.7 t/s | 0.359 | 2.78 |

超过 3 后，接受率崩塌而 draft 成本继续上升，因为 MTP 头本身就是一层 512 专家的 MoE，每多一个 draft 就多一次完整前向。混合流量用 2，输出可预测时用 3。这与 27B 的结论形状相同，但这里的下跌更陡。

## 发现 8：用 24 线程，而不是 32

24 层专家在内存：

| 线程数 | 解码 |
|---|---|
| 16 | 33.3 t/s |
| 24 | 33.8 t/s |
| 32 | 20.9 t/s |

32 线程（SMT）明显更差。24 相比默认的 16 有小幅提升。

## 无效的优化

- Tensor split：`qwen4exp` 未实现。
- RCCL：MTP 分支编译中没有，且没有 tensor split 时无意义。
- `--n-cpu-moe N`：把 GPU 专家集中到一张卡并导致显存溢出。
- `n-max` 4 或 5：解码吞吐低于 2 或 3。
- 超过 24 线程：SMT 争用反而有害。
- 使用原版 llama.cpp：该架构没有 MTP。

## 说明与限制

- **环境特定性：** 数据反映我的机器与版本。prefill 尤其会因环境而异。
- **单次运行：** 低于 5% 的差异是噪声。当两个配置无法区分时，我已说明。
- **MTP 波动性：** 接受率取决于内容，因此 tokens/秒不是稳定指标。
- **分支稳定性：** `qwen4exp/mtp` 分支是正在评审的 pull request。选项与行为在合入主线前可能变化。
- **未测试：** KV cache 量化与 CPU 线程亲和性。这里 KV 占用很小（48 层中仅 12 层带完整 KV），因此量化它看起来不值得冒险，我保留了 f16。

如果你复现后发现不同的数字，我很乐意了解。

---

### 关键数据清单

- **硬件：** 2x Radeon AI PRO R9700（gfx1201），125 GB 内存
- **模型：** Qwen3.8-Flash-Next-GGUF (UD-Q4_K_XL)，103.7 GiB
- **MTP 头：** mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf
- **编译：** llama.cpp `qwen4exp/mtp` 分支 `6fcaa16f4`，`GGML_HIP=ON`，`AMDGPU_TARGETS=gfx1201`
- **核心优化：** `-ngl 999` 配合 `-ot` 分散 CPU 专家、`--load-mode none`、`-ub 1024`、`-t 24`
- **MTP 配置：** `--spec-type draft-mtp --spec-draft-n-max 3`
- **上下文：** `-c 131072 -np 1`
- **KV 状态：** f16（未测试量化）
- **实测性能：** Prefill ~474 t/s | 解码 ~34 t/s | 接受率 ~0.54
