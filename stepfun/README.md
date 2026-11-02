# 端侧知识库：浏览器本地向量化 + seekdb 混合检索

> 赛题：seekdb × 阶跃星辰《端侧 AI 推理性能优化与 seekdb 混合检索》
> 仓库：`18615076198-source/powercontext-2026`　分支：`2026-competition-stepfun`　产物：`stepfun/`
> 定位：**推理在浏览器、存储在 seekdb、融合在数据库里**，全流程无云端推理调用。

用户导入一批文本 → 浏览器用 ONNX 模型（INT8 / FP16 / FP32 可选）在本地算 embedding →
通过 seekdb-js 写入 seekdb（向量 + 原文 + 元数据）→ 查询时同样本地算向量 →
一条 `hybridSearch` 在 seekdb 内完成「向量 + 全文」两路召回与 RRF 融合，返回排序结果。

## 一、架构

~~~text
┌──────────────────────────── 浏览器（端侧） ────────────────────────────┐
│  文本切片 → transformers.js (WebGPU / WASM) → 向量 (512 维)              │
│  查询文本 → 同一个本地模型 → 查询向量                                    │
│  UI：后端徽标（WebGPU/WASM）、精度、导入进度、检索结果、实测指标          │
└───────────────┬───────────────────────────────────────────┬────────────┘
                │ POST /api/session/:id/ingest               │ POST .../search
                ▼                                            ▼
┌──────────────────────────── Node 服务（本地） ───────────────────────────┐
│  express：会话 → collection 映射、批量写入、索引刷新、混合检索              │
│  seekdb-js：upsert(向量+原文+元数据) / refresh_index()                     │
│             hybridSearch({ whereDocument, knn, rank.rrf })                │
└───────────────┬────────────────────────────────────────────────────────┘
                ▼
        seekdb 1.4（127.0.0.1:2881）
        collection：VECTOR(512) HNSW + 全文索引(ik) + 元数据 JSON
        混合检索由 DBMS_HYBRID_SEARCH 在库内完成，RRF(k=60) 融合
~~~

## 二、环境要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Node.js | ≥ 20（实测 24.21） | seekdb-js 要求 Node 20+ |
| seekdb | 1.4.0 | 本地 server 模式，默认 `127.0.0.1:2881`，root/空密码 |
| 浏览器 | Chrome / Edge 最新版 | WebGPU 可用时自动启用，否则降级 WASM |
| 操作系统 | 有 seekdb 即可（Linux/macOS/WSL） | 本仓库在 Windows 11 + WSL2 上实测 |

## 三、快速开始

### 1. 启动 seekdb

Linux / macOS / WSL：

~~~bash
bash scripts/start-seekdb.sh          # 数据目录默认 ~/seekdb-kb，端口 2881
~~~

如果已有 seekdb 在跑，可跳过；用下面的命令确认：

~~~bash
node scripts/verify-seekdb.mjs        # 连接、建表、写入、混合检索全链路自检
~~~

Windows 用户可让 seekdb 跑在 WSL 里（WSL2 会把 2881 转发到 Windows 的 127.0.0.1）：

~~~powershell
wsl -e bash scripts/start-seekdb.sh
~~~

### 2. 安装依赖并准备浏览器运行时

~~~bash
npm install
~~~

> `npm start` 的 prestart 会自动把 onnxruntime-web 的 wasm 复制到 `web/vendor/`，
> 并用 esbuild 打包 transformers.js。这两个产物都不提交进仓库（避免二进制体积与构建产物污染）。

### 3. 启动应用

~~~bash
npm start               # http://127.0.0.1:7860
~~~

打开页面后：

1. 点「载入示例语料」→ 浏览器本地向量化 40 篇文档 → 写入 seekdb 并刷新索引；
2. 输入问题（例如「seekdb 怎么在一条 SQL 里同时做向量和全文检索」）→ 点「检索」；
3. 顶部徽标会显示当前后端（WebGPU / WASM）、精度与模型体积；
4. 点「跑质量评测」得到 Recall@5 / nDCG@10。

### 4. 模型文件说明

仓库内置 **INT8** 模型（22.90 MB）用于开箱即用；FP16 / FP32 用于量化对比，按需下载：

~~~bash
npm run fetch-model -- --dtypes fp16,fp32     # 从 hf-mirror 下载，约 136 MB
~~~

模型来源：`Xenova/bge-small-zh-v1.5`（BAAI bge-small-zh-v1.5 的 ONNX 转换，MIT）；
由 `scripts/fetch-model.mjs` 固定版本下载，见 `docs/技术说明.md`。

## 四、目录

~~~text
stepfun/
├── README.md                     # 本文件
├── package.json
├── .env.example                  # seekdb 连接配置
├── server/
│   ├── index.mjs                 # HTTP API + 静态资源
│   └── store.mjs                 # seekdb-js 封装：collection / upsert / refresh / hybridSearch
├── web/
│   ├── index.html  style.css
│   ├── app.js                    # 导入 / 检索 / 评测 / 指标 / 自动化接口
│   ├── embedder.js               # transformers.js 封装：WebGPU/WASM、dtype、降级
│   ├── src/transformers-entry.js # esbuild 打包入口
│   ├── vendor/                   # 生成的 transformers.bundle.js 与 ORT wasm（不提交）
│   └── models/                   # 模型文件（INT8 提交，FP16/FP32 按需下载）
├── data/
│   ├── corpus.json               # 40 篇中文示例语料
│   └── eval.json                 # 12 条查询 + 相关性标注（Recall@5 / nDCG@10）
├── scripts/
│   ├── prepare-web.mjs           # 复制 ORT wasm
│   ├── bundle-web.mjs            # esbuild 打包 transformers.js
│   ├── fetch-model.mjs           # 下载模型（hf-mirror）
│   ├── start-seekdb.sh           # 本地 seekdb 启动脚本
│   ├── verify-seekdb.mjs         # 不依赖浏览器的 seekdb 全链路自检
│   ├── cdp.mjs                   # 无依赖 CDP 客户端（驱动 Edge/Chrome）
│   ├── selftest-browser.mjs      # 浏览器端自测（导入/检索/增量/重置）
│   └── benchmark.mjs             # 精度 × 后端基准，输出 results/*.json
├── docs/
│   ├── 技术说明.md                # 一页技术说明（模型/量化/后端/seekdb/优化/结果）
│   └── benchmark.md              # 测试方法与完整数据
└── results/                      # 实测原始 JSON
~~~

## 五、实现要点

### 1. 浏览器本地推理

- 运行时：Transformers.js 4.3.2 + ONNX Runtime Web 1.31（esbuild 打包成单文件，离线加载）；
- 模型：`bge-small-zh-v1.5`，512 维，中文语义效果好、体积小，适合端侧；
- 文档与查询的 embedding 都在浏览器里算，服务端只接收向量，**不调用任何云端推理 API**；
- 模型、tokenizer、wasm 全部从本站静态目录加载（`env.allowRemoteModels = false`）。

### 2. 量化

| 精度 | 文件 | 体积 | 说明 |
| --- | --- | ---: | --- |
| FP32 | `onnx/model.onnx` | 90.46 MB | 基线 |
| FP16 | `onnx/model_fp16.onnx` | 45.30 MB | 2.00× 压缩 |
| INT8 | `onnx/model_quantized.onnx` | 22.90 MB | 3.95× 压缩（默认） |

质量变化（12 条查询，Recall@5 / nDCG@10）：FP32 0.9028 / 0.8582 → INT8 0.8611 / 0.8341，
相对下降 4.6% / 2.8%，见 `docs/benchmark.md`。

### 3. WebGPU 优先 + WASM 降级

- 启动时探测 `navigator.gpu.requestAdapter()`，可用则显式 `device: "webgpu"`，否则 `device: "wasm"`；
- WebGPU 初始化失败会自动重试 WASM，并把原因显示在界面上；
- 自动精度：WebGPU → FP16，WASM → INT8；
- 服务端返回 COOP/COEP 头，让 WASM 多线程（SharedArrayBuffer）可用。

### 4. seekdb 混合检索（库内完成）

- collection schema：`VectorIndexConfig(hnsw, dim=512, cosine)` + `FulltextIndexConfig("ik", smart)`；
- 写入：`upsert` 幂等（id = 文档 ID + 块序号），同一请求内批量写；
- 检索：一次 `collection.hybridSearch({ query: { whereDocument: { $contains } }, knn: { queryEmbeddings }, rank: { rrf } })`，
  底层是 seekdb 的 `DBMS_HYBRID_SEARCH`，两路召回与融合都在数据库内完成，客户端不做结果拼合；
- 混合检索失败时降级为 `collection.query` 向量检索，并在返回里标注 `mode="vector"`。

### 5. 增量导入与索引刷新

- 每次导入只写新增文档，`upsert` 保证重复导入不重复计数；
- 写入后调用 `refresh_index()`，新文档立刻可检索（自测脚本验证了这一点）；
- 索引刷新耗时单独计时（约 0.3–0.7 s / 40 块），不混入向量化耗时。

### 6. 会话与集合

- 每个浏览器会话一个 collection（`kb_<sessionId>`），会话 ID 校验后拼接，避免非法表名；
- 切换/重置会话只影响自己的 collection；「清空知识库」= 删除并重建 collection；
- 服务端重启后按 collection 名重新挂载，浏览器用 localStorage 里的 sessionId 恢复。

## 六、实测结果（摘要）

测试环境：Windows 11 · Intel Core Ultra 9 275HX（24 核）· RTX 5070 Ti Laptop + Intel iGPU ·
Edge 156.0.4314.58 · Node 24.21 · seekdb 1.4.0 · 40 篇语料 / 40 块 / 12 条查询 / 20 次延迟采样。

| 配置 | 模型体积 | 向量化 | 写入+刷新 | 查询 p50 | Recall@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| INT8 + WASM | 22.90 MB | 703 ms（24.6 块/s） | 303+603 ms | **11.9 ms** | 0.8611 | 0.8341 |
| FP16 + WASM | 45.30 MB | 1469 ms（17.1 块/s） | 252+603 ms | 15.2 ms | 0.9028 | 0.8582 |
| FP32 + WASM | 90.46 MB | 1292 ms（17.3 块/s） | 293+705 ms | 19.2 ms | 0.9028 | 0.8582 |
| FP16 + WebGPU | 45.30 MB | 894 ms（22.1 块/s） | 295+605 ms | 61.6 ms | 0.9028 | 0.8582 |
| FP32 + WebGPU | 90.46 MB | 997 ms（24.4 块/s） | 320+304 ms | 45.5 ms | 0.9028 | 0.8582 |
| INT8 + WebGPU | 22.90 MB | 2832 ms（10.9 块/s） | 309+503 ms | 217.4 ms | 0.8611 | 0.8414 |

结论：

1. **INT8 是端侧最佳默认**：体积最小、加载最快、检索质量仅小幅下降；
2. 本机小模型场景 **WASM 的单次查询延迟明显低于 WebGPU**（11.9 vs 45~217 ms），
   原因是逐次 GPU 调度开销占比高；WebGPU 在大批量导入时吞吐接近甚至略优；
3. 因此产品默认仍是「WebGPU 优先」，但允许手动切换后端，并在技术说明中给出如实数据。

## 七、自测

~~~bash
node scripts/verify-seekdb.mjs        # seekdb 全链路（无需浏览器）
npm run selftest                      # 浏览器端 8 项断言（无头 Edge）
node scripts/benchmark.mjs --dtypes q8,fp16,fp32 --device wasm
node scripts/benchmark.mjs --headless false --device auto --dtypes fp16,fp32,q8   # 有界面，可拿到 WebGPU
~~~

## 八、已知限制

1. 端侧模型是通用小模型，中文短查询效果良好，但专业领域术语仍可能召回不准；
2. WebGPU 依赖浏览器与驱动，无头浏览器/虚拟机常拿不到 adapter，此时只能跑 WASM；
3. 单库单 collection 的会话模型够用但不做多用户鉴权，生产化需要加会话隔离与限流；
4. 图片等富媒体未实现（题面允许作为扩展）；
5. 模型首次加载需要下载/读盘，未做 Service Worker 预缓存（浏览器 HTTP 缓存已生效）。
