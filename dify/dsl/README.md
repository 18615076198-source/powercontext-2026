# DSL 说明

## 文件

| 文件 | 用途 | 导入顺序 |
| --- | --- | --- |
| `cyber-matchmaker.yml` | 「赛博月老 · 缘分交易所」Chatflow | 唯一必需文件，直接导入 |

- 适用版本：Dify 1.x（DSL `version: 0.1.5`，与社区 1.x 导出的 Chatflow 同构）；
- 无插件依赖（`dependencies: []`），只用内置节点：start / if-else / http-request / llm / answer；
- 导入后需要绑定模型与后端地址，见下文。

## 节点地图

~~~text
start（简历 profile / 模式 vibe）
  └─ if-else「查档案还是撮合？」：sys.query 包含 档案/历史/战报？
       ├─ true  → HTTP「读取相亲档案」(POST /api/history)
       │           → LLM「档案管理员」→ answer
       └─ false → HTTP「seekdb 检索候选人」(POST /api/match)
                   → LLM「月老撮合」→ HTTP「写入相亲档案」(POST /api/archive) → answer
~~~

- 分支条件用的是 Dify 内置的 `contains` 比较符，选中 `sys.query`；
- 三条 HTTP 节点的 body 都是 `raw-text`（`USER=/PROFILE=/MESSAGE=/VIBE=…`），后端按行解析，
  这样可以避免 LLM 输出里的换行/引号破坏 JSON 转义；
- 两条 LLM 节点的输出变量都是 `text`，answer 节点通过 `{{#节点id.text#}}` 引用。

## 导入后必须做的两件事

### 1. 绑定模型

「月老撮合」和「档案管理员」两个 LLM 节点默认是 `openai / gpt-4o-mini`，
导入后在你自己的 Dify 里选中可用模型即可（节点不会因为模型不同而失效，prompt 里没有模型相关依赖）。
建议温度 0.7–0.9，max_tokens ≥ 1200。

### 2. 改后端地址

三个 HTTP 节点的 URL 形如 `http://host.docker.internal:7870/api/match`，按 `docs/运行说明.md` 第 3.3 节替换。

## 重新生成 DSL

~~~bash
python tools/build_dsl.py     # 修改 BASE_URL / prompt 后重新生成
python tools/validate_dsl.py  # 校验节点、边、变量引用
~~~
