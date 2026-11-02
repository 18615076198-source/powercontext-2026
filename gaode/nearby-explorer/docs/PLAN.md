# 实现计划（PLAN）

> 这份文档是先写计划、再落代码的产物，保留下来便于评审对照「说到的」和「做到的」。

## 1. 文件清单与职责

| 文件 | 职责 | 关键点 |
| --- | --- | --- |
| `scripts/amap_client.py` | 高德 Web 服务封装 | 超时 1.5s/3s、总预算 8s、重试 1 次（指数退避）、3 QPS 限流、TTL+LRU 缓存、`status/infocode` 统一校验、40+ 错误码映射、Key 脱敏日志、mock 传输层注入 |
| `scripts/mock_backend.py` | 离线后端 | 优先回放 `fixtures/recorded/` 真实录制，未命中则用 `fixtures/mock_world.json` 合成世界作答；实现 geocode / regeo / inputtips / around / text / 4 种方向 / distance / weather |
| `scripts/text_parser.py` | 一句话 → 结构化请求 | 类目表（14 个）、城市别名表（20 个）、位置正则（6 种句式）、半径/预算/评分/营业/连锁/安静/无障碍/停车/时长/往返/时间、中文数量词、口味词、置信度 |
| `scripts/recommender.py` | 召回 + 打分 + 多样性 | 并行召回、精确关键词优先、id + 名称30m 去重、硬/软过滤、5 维打分、贪心多样性、模板化推荐理由、自动扩半径 |
| `scripts/planner.py` | 怎么去 | walking / bicycling / transit / driving 解析、降级链（路线→distance 接口→球面估算）、每候选 ≤2 种方式、高德 URI（marker / navigation / app scheme） |
| `scripts/render.py` | 展示 | Markdown 固定字段；失败/无结果/缺位置三种文案 |
| `scripts/nearby_explorer.py` | 编排 / CLI | 位置解析降级、状态机、JSON 输出、退出码、异常兜底 |
| `scripts/geo.py` | 地理计算 | haversine、方位角、坐标偏移、距离/时长格式化、城市名归一 |
| `tools/build_mock_fixtures.py` | 生成离线世界 | 确定性（无随机、无时间依赖），390 个 POI |
| `tools/record_fixtures.py` | 录制真实响应 | 剔除 key，生成 index.json |
| `tools/inspect_query.py` | 调试 | 只看解析结果 |
| `tests/*` | 测试 | 78 个单测 + 10 条 e2e + Key 扫描 |

## 2. API 调用时序

~~~text
用户输入
  │
  ▼
[text_parser.parse]  ── 无网络
  │ parsed{location, city, categories, radius, constraints, transport}
  ▼
[resolve_origin]
  ├─(有坐标)──────────────────────────────────────────────► 直接用
  ├─(有地名, 显式城市) /v3/geocode/geo?address&city
  ├─(失败/无城市)      /v3/geocode/geo?address
  ├─(仍失败)          /v3/assistant/inputtips?keywords&city
  └─(仍失败)          /v3/geocode/geo?address=<城市>
  │
  ▼
[recommender.recall]  ThreadPool(4)
  ├─ /v3/place/around (types=父类码, radius, extensions=all, sortrule=weight, offset=25, page=1)
  ├─ 精确召回不足 3 条 → 再发一次纯类型码查询合并
  └─ 第一页满 25 条 → 翻 page=2
  │
  ▼
[filter → score → diversify]  ── 无网络
  │
  ▼
[planner.plan_routes]  ThreadPool(4)
  ├─ walking  /v3/direction/walking
  ├─ bicycling/v4/direction/bicycling
  ├─ transit  /v3/direction/transit/integrated?city
  ├─ driving  /v3/direction/driving
  └─ 任一失败 → /v3/distance?type=1 → 球面距离×系数（estimated=true）
  │
  ▼
[render] Markdown / JSON
~~~

## 3. 降级矩阵

| 失败点 | 降级动作 | 用户可见 |
| --- | --- | --- |
| 地理编码带城市失败 | 去掉 city 重试 | 无感 |
| 地理编码失败 | inputtips → 城市中心 | `degraded` 提示 |
| 某类目召回失败 | 其他类目继续，记录 `diagnostics.errors` | 候选可能变少 |
| 类型码召回为空 | 关键词召回 | 无感 |
| 1000m 内无结果 | 自动扩到 2000~3000m（不超过用户上限） | `degraded` 提示 |
| 评分/连锁过滤后不足 3 个 | 回补并提示 | `degraded` 提示 |
| 路线规划失败 | distance 接口 → 球面估算 | 文案带「约」「（估算）」 |
| 总预算耗尽 | 剩余候选全部估算 | `degraded` / `estimated` |
| Key 缺失/无效/配额 | 直接返回 `error` + 处置建议 | 明确区分「无结果」 |

## 4. 关键决策记录

1. **离线世界用合成数据而不是伪造"录制"**：没有 Key 就录不到真实响应，所以明确标注 synthetic，
   同时提供 `record_fixtures.py` 与回放通道，拿到 Key 后一条命令切换为真实数据。
2. **距离分用 `exp(-d/500)`**：任务书公式随距离递增，作为得分方向反了（见 README 第 11 节）。
3. **单类目放宽多样性上限**：否则「只要咖啡」永远最多 2 个候选，与 3~5 个的目标冲突。
4. **mock 模式不限流**：本地回放没有真实配额，默认 QPS=100，避免 10 条 e2e 跑几十秒。
5. **精确关键词优先召回**：用户说"火锅"时先按关键词召回，不足 3 条再放宽，兼顾相关性与召回率。
6. **打分结果落盘到 JSON（score_parts）**：便于调参与复现，`--explain` 直接展示。
