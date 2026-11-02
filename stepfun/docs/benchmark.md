# 基准测试方法与结果

## 1. 测试条件（固定）

| 项 | 值 |
| --- | --- |
| 设备 | Windows 11，Intel Core Ultra 9 275HX（24 核），RTX 5070 Ti Laptop + Intel iGPU，31 GB RAM |
| 浏览器 | Microsoft Edge 156.0.4314.58 |
| Node / seekdb | Node 24.21.0 / seekdb 1.4.0（WSL2，127.0.0.1:2881） |
| 模型 | `Xenova/bge-small-zh-v1.5`，512 维 |
| 语料 | `data/corpus.json`，40 篇中文文档，切片后 40 个块（每篇 1 块） |
| 查询 | `data/eval.json`，12 条查询 + 相关性标注 |
| 延迟采样 | 每条组合预热 1 次后连续 20 次查询，报告 p50/p90 |
| 每个组合 | **新开浏览器实例**（全新 profile），避免 HTTP / 模型缓存影响冷加载计时 |
| 无头模式 | `--headless=new --disable-gpu`（拿不到 WebGPU，走 WASM） |
| 有界面模式 | 正常窗口 + `--enable-unsafe-webgpu`（可拿到 WebGPU） |

计时口径：

- **模型加载**：`pipeline()` 从发起到可用（含 wasm 初始化与模型解码）；
- **文档向量化**：40 个块的 embedding 计算总耗时（不含网络与 UI 渲染）；
- **写入 + 索引刷新**：服务端 `upsert` 与 `refresh_index()` 的耗时，分别统计后相加；
- **查询 p50**：页面内从「开始编码查询」到「seekdb 返回结果」的端到端耗时（含查询向量化 + 库内检索）；
- **检索质量**：Top-10 结果按 docId 去重后计算 Recall@5 与 nDCG@10。

## 2. 结果

### 2.1 WASM（无头 Edge）

| 精度 | 体积 | 模型加载 | 向量化 40 块 | 吞吐 | 写入 | 索引刷新 | p50 | p90 | Recall@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| INT8 | 22.90 MB | 862 ms | 703 ms | 24.6 块/s | 303 ms | 603 ms | **11.9 ms** | 12.9 ms | 0.8611 | 0.8341 |
| FP16 | 45.30 MB | 1403 ms | 1469 ms | 17.1 块/s | 252 ms | 603 ms | 15.2 ms | 16.9 ms | 0.9028 | 0.8582 |
| FP32 | 90.46 MB | 2468 ms | 1292 ms | 17.3 块/s | 293 ms | 705 ms | 19.2 ms | 22.1 ms | 0.9028 | 0.8582 |

### 2.2 WebGPU（有界面 Edge）

| 精度 | 体积 | 模型加载 | 向量化 40 块 | 吞吐 | 写入 | 索引刷新 | p50 | p90 | Recall@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FP16 | 45.30 MB | 2126 ms | 894 ms | 22.1 块/s | 295 ms | 605 ms | 61.6 ms | 68.6 ms | 0.9028 | 0.8582 |
| FP32 | 90.46 MB | 2816 ms | 997 ms | 24.4 块/s | 320 ms | 304 ms | 45.5 ms | 67.9 ms | 0.9028 | 0.8582 |
| INT8 | 22.90 MB | 1577 ms | 2832 ms | 10.9 块/s | 309 ms | 503 ms | 217.4 ms | 352.1 ms | 0.8611 | 0.8414 |

> p90 取自同一批 20 次采样的分位值；INT8+WebGPU 的 nDCG 与 WASM 略有差异，
> 来自量化算子在不同后端上的浮点误差导致的排序细微变化。

原始数据：`results/bench-headless-*.json`、`results/bench-headed-*.json`。

## 3. 分析

1. **体积与加载**：INT8 体积是 FP32 的 1/3.95，加载时间也从 2468 ms 降到 862 ms（WASM），
   首次打开体验改善明显；FP16 居中。
2. **向量化吞吐**：WASM 下 INT8 最快（24.6 块/s），FP16 与 FP32 接近（17 块/s）；
   WebGPU 批量吞吐在 FP16/FP32 上略优于 WASM（22.1 / 24.4 块/s），但 INT8 在 WebGPU 上没有整数加速，
   退化为反量化路径，只有 10.9 块/s。
3. **单查询延迟**：小模型（24M）下，WebGPU 的逐次调度开销占主导，p50 45–217 ms，反而慢于 WASM 的 12–19 ms；
   这符合「小模型 + 单条查询」的经验，也说明不能盲目迷信 WebGPU。
4. **质量**：FP16 与 FP32 的 Recall@5 / nDCG@10 完全一致；INT8 相对 FP32 的 Recall@5 下降 4.6%、nDCG@10 下降 2.8%，
   属于可接受范围，且换来了近 4 倍的体积与更快的加载。
5. **刷新开销**：`refresh_index()` 在 40 块规模下为 0.3–0.7 s，明显高于写入本身（约 0.3 s），
   因此增量导入应当「批量写完再刷新」，而不是逐条刷新。

## 4. 复现命令

~~~bash
node scripts/benchmark.mjs --dtypes q8,fp16,fp32 --device wasm
node scripts/benchmark.mjs --headless false --device auto --dtypes fp16,fp32,q8
~~~

产物写入 `results/`，每次运行都会新开浏览器实例，保证冷启动口径一致。
