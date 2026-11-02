# 赛博月老 · 缘分交易所（Dify × seekdb）

> 赛题：Dify × OceanBase《Just for Fun——用 Dify 做一个好玩的智能应用》
> 仓库：`18615076198-source/powercontext-2026`　分支：`2026-competition-dify`　产物：`dify/`
> 技术组合：**Dify（编排/对话/生成）+ seekdb（角色池混合检索 + 相亲档案记忆）+ 本地 embedding 后端**

## 一、这是什么

把相亲简历丢进「缘分交易所」，AI 月老用 **seekdb 的向量 + 全文混合检索** 从 24 位奇葩角色里给你撮合 3 位，
毒舌但有温度地写出撮合报告；每次批语都会写进 seekdb 的相亲档案，**下一次（甚至新会话）月老会先翻档案**：

> 「上次你见过盆栽哲学家·阿植，他说你像一盆缺水的绿萝。今天给你换了个写诗的。」

玩法：

1. 输入简历（一句话就行）：昵称/年龄/爱好/雷点/想找什么样的人；
2. 月老检索候选人，输出「缘分指数 + 匹配点 + 雷点预警 + 首次约会建议 + 月老签文」；
3. 想换人直接说「再换一批」「还有别的吗」；
4. 说「查档案」可以看到自己的相亲战报（数据来自 seekdb 记忆库）。

## 二、技术分工（评审可核对）

| 组件 | 在应用里实际做什么 | 证据 |
| --- | --- | --- |
| **Dify** | Chatflow 编排：开始节点 → 意图分支（if-else 判断「查档案」）→ HTTP 调 seekdb 后端 → LLM 月老生成 → HTTP 写档案 → 回复 | `dsl/cyber-matchmaker.yml` |
| **seekdb** | ① `personas` collection 存 24 位角色（512 维向量 + ik 全文索引），混合检索完成撮合；② `matches` collection 存每次相亲批语，作为跨会话记忆 | 后端日志、`evidence/`、`/api/history` 返回 |
| 本地后端 | 用 bge-small-zh（INT8 ONNX）把简历和角色向量化，封装 seekdb 读写，供 Dify 的 HTTP Request 节点调用 | `service/` |

> 说明：本题要求「必须使用 Dify，并实际使用 seekdb、PowerContext 中的至少一种」。本项目选 seekdb，
> 且 seekdb 同时承担**检索**（混合检索在库内完成）与**记忆**（跨会话档案）两项职责。

## 三、目录

~~~text
dify/
├── dsl/
│   ├── cyber-matchmaker.yml    # Dify Chatflow DSL（导入即用）
│   └── README.md               # 导入顺序、节点说明、模型绑定
├── service/
│   ├── server.mjs              # HTTP API：/api/match /api/archive /api/history /api/seed
│   ├── store.mjs               # seekdb 数据层（personas / matches 两个 collection）
│   ├── embedder.mjs            # 本地 bge-small-zh INT8 embedding
│   ├── personas.json           # 24 位角色设定
│   ├── seed.mjs                # 重建角色池
│   └── models/                 # INT8 模型（22.9MB，开箱离线）
├── tools/
│   ├── build_dsl.py            # 重新生成 DSL
│   ├── validate_dsl.py         # 校验节点/边/变量引用
│   ├── smoke_api.mjs           # 后端 API 冒烟
│   └── run_workflow.mjs        # Dify 工作流本地等价执行器（验证接线与后端契约）
├── docs/
│   ├── 运行说明.md
│   ├── 验证样例.md
│   └── 技术说明.md
└── evidence/                   # 运行记录（JSON + 对话转录）
~~~

## 四、快速开始

### 1. 准备 seekdb

需要 seekdb 1.4.0 在 `127.0.0.1:2881`（root / 空密码）。已有实例可跳过；否则：

~~~bash
bash scripts/start-seekdb.sh     # 若在 stepfun/ 目录下用过；也可直接用你的 seekdb 启动方式
~~~

### 2. 启动配套后端

~~~bash
cd dify
npm install
npm start          # http://0.0.0.0:7870，首次启动自动建库并写入 24 位角色
curl http://127.0.0.1:7870/health
# {"ok":true,"personas":24,"matches":0,"seekdb":"5.7.25-OceanBase seekdb-v1.4.0.0"}
~~~

### 3. 在 Dify 里导入 DSL

1. Dify 版本：1.x（DSL `version: 0.1.5`，与社区 1.x 导出的 Chatflow 兼容）；
2. 应用 → 导入 DSL 文件 → 选择 `dsl/cyber-matchmaker.yml`；
3. 打开 Chatflow，做三件事（详见 `dsl/README.md`）：
   - 把两个 LLM 节点的模型换成你环境里可用的模型（如 DeepSeek / Qwen / OpenAI）；
   - 把三个 HTTP Request 节点的地址 `http://host.docker.internal:7870` 换成后端实际地址；
   - 保存并发布。
4. 在 Dify 应用里输入：「帮我撮合一下：程序员，喜欢猫和手冲咖啡」，然后再说「查档案」。

> 若 Dify 跑在 Linux Docker 上，`host.docker.internal` 需要 compose 里加
> `extra_hosts: ["host.docker.internal:host-gateway"]`，或直接把 URL 改成宿主 IP。

### 4. 没有 Dify 环境时（本地验证）

~~~bash
node tools/run_workflow.mjs --user demo --profile "程序员，喜欢猫和手冲咖啡" --message "帮我撮合" --vibe 认真
node tools/run_workflow.mjs --user demo --message "查一下我的档案"
~~~

它会读取 DSL、按节点顺序执行：if-else 分支 → HTTP 调 seekdb 后端 → LLM（可用 `--llm-base` 指向任意 OpenAI 兼容服务）→ 写档案 → 输出回复，并把每一步写进 `evidence/`。
未配置 LLM 时会用模板输出并明确标注（便于离线验证接线，不代表最终文案）。

## 五、验证样例（摘要）

| 步骤 | 输入 | 预期 |
| --- | --- | --- |
| 1 | 简历「程序员，喜欢猫和手冲咖啡」+「帮我撮合」 | 返回 3 位角色，至少 1 位带「代码/咖啡/猫」标签；报告引用口头禅与雷点 |
| 2 | 再说「查档案」 | 命中 seekdb 里的历史记录，复述上次候选人 |
| 3 | 再说「再换一批」 | 排除已匹配的人，给出新候选人 |

完整步骤、预期表现与证据文件见 `docs/验证样例.md`。

## 六、已知限制

1. **本机没有 Dify 运行时**（无 Docker / 无 root），所以仓库里的运行证据来自「DSL 本地等价执行器 + 真实 seekdb 后端」；
   DSL 的导入与模型绑定需要在评审环境的 Dify 1.x 中完成，步骤已写在 `docs/运行说明.md`。
2. LLM 节点默认写的是 `openai/gpt-4o-mini`，导入后必须换成你环境可用的模型（这是 Dify 的常规操作）。
3. HTTP 节点地址默认 `host.docker.internal:7870`，按你的部署方式替换。
4. 角色池是虚构设定，纯属娱乐；24 位角色、每次相亲批语都是演示数据。
