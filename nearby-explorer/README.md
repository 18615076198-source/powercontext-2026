# nearby-explorer · 周边去哪儿

一句话 → **3~5 个候选地点 + 怎么去**。基于高德开放平台 Web 服务，Python 3.9+，
只依赖标准库与 `requests`，支持 **无网络 / 无 Key 的离线模式**。

> 这是「OceanBase 数据库大赛 2026 · 周边去哪儿」赛题的参赛作品。
> 所有面向用户的文案为中文；坐标全程使用高德 GCJ-02，不做二次转换。

---

## 1. 30 秒上手

### 离线模式（默认推荐先跑这个）

~~~bash
cd nearby-explorer
export AMAP_MOCK=1          # Windows PowerShell: $env:AMAP_MOCK='1'
python scripts/nearby_explorer.py "我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到"
~~~

无需网络、无需 Key，数据来自 `fixtures/`（合成样例，见第 10 节）。输出示例：

~~~text
### 附近推荐：「西湖」 周边 1.0 公里 · 咖啡馆

> **解析**：位置「西湖（杭州市西湖区）」｜类目 咖啡馆｜半径 1000 米｜交通 步行｜停留 120 分钟
> **模式**：离线模式（AMAP_MOCK=1，数据来自 fixtures/ 合成样例，不是实时结果）

#### 1. 拾光咖啡　·　咖啡馆　·　⭐ 4.3

- **类目**：咖啡馆
- **距离**：步行约 3 分钟（250 米，直线 200 米）
- **评分**：4.3 ｜ **人均**：¥49
- **营业时间**：10:00-22:30（已打烊）
- **地址**：杭州市西湖区南山路31号
- **推荐理由**：咖啡馆「安静」，步行约 3 分钟（250 米），评分 4.3，人均 49 元，符合「安静」要求。
- **交通方案**（最多 2 种）：
  1. 步行 3 分钟（250 米）
- **高德链接**：[查看地点](https://uri.amap.com/marker?...) · [导航过去](https://uri.amap.com/navigation?...)
~~~

### 在线模式

~~~bash
export AMAP_KEY='你的Web服务Key'    # 必须是「Web 服务」类型的 Key
unset AMAP_MOCK
python scripts/nearby_explorer.py "北京国贸附近评分4.5以上的咖啡馆，人均50以内"
~~~

申请地址：<https://console.amap.com/dev/key/app>（选「Web 服务」）。
**代码、fixtures、日志里都不会出现明文 Key**，日志中 Key 形如 `abcd****yz`。

---

## 2. 目录结构

~~~text
nearby-explorer/
├── SKILL.md                   # Skill 入口：何时使用 / 输入输出约定 / 调用方式
├── README.md                  # 本文件
├── docs/
│   ├── PLAN.md                # 实现计划、文件职责、API 调用时序
│   └── ACCEPTANCE.md          # 验收清单逐项自查表
├── scripts/
│   ├── __init__.py
│   ├── amap_client.py         # 高德 API 封装：超时/重试/限流/预算/缓存/错误码/mock
│   ├── mock_backend.py        # 离线后端：合成世界 + 真实录制回放
│   ├── text_parser.py         # 一句话 → 结构化请求（纯规则、确定性）
│   ├── recommender.py         # 召回 + 过滤 + 打分 + 多样性 + 推荐理由
│   ├── planner.py             # 四种交通方式 + 兜底估算 + 高德 URI
│   ├── render.py              # Markdown 渲染
│   ├── nearby_explorer.py     # 编排入口 / CLI
│   └── geo.py                 # 球面距离、方位、格式化
├── fixtures/
│   ├── mock_world.json        # 合成 POI 世界（390 个 POI / 14 个地点）
│   ├── README.md              # 数据来源声明（必读）
│   ├── samples/               # 按文档结构手工构造的接口样例（单测用）
│   └── recorded/              # 真实录制目录（默认不存在，用工具生成）
├── tests/
│   ├── e2e.sh                 # 一键验收：单测 + 10 条语句 + 安全检查
│   ├── e2e_check.py           # 10 条语句逐条断言
│   ├── e2e_cases.json         # 10 条用例（录制工具共用）
│   ├── check_no_secrets.py    # 禁止明文 Key 的静态检查
│   ├── test_amap_client.py
│   ├── test_text_parser.py
│   ├── test_recommender.py
│   ├── test_planner.py
│   └── test_e2e_offline.py
└── tools/
    ├── build_mock_fixtures.py # 生成 fixtures/mock_world.json（确定性）
    ├── record_fixtures.py     # 用真实 Key 录制 fixtures/recorded/
    └── inspect_query.py       # 只看解析结果，不调 API
~~~

---

## 3. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AMAP_KEY` | 空 | 高德「Web 服务」Key；联网模式必填 |
| `AMAP_MOCK` | 0 | `1` 时使用离线后端，不联网 |
| `AMAP_QPS` | 3（在线）/ 100（离线） | 限流 QPS，遵守高德配额 |
| `AMAP_BUDGET` | 8.0 | 单次查询总时间预算（秒） |
| `AMAP_CONNECT_TIMEOUT` | 1.5 | 连接超时（秒） |
| `AMAP_READ_TIMEOUT` | 3.0 | 读取超时（秒） |
| `AMAP_DEFAULT_CITY` | 空 | 缺省城市，用于补全歧义地名 |
| `AMAP_ORIGIN` | 空 | 当前坐标 `lng,lat`，等同 `--origin` |
| `AMAP_MOCK_WORLD` | fixtures/mock_world.json | 自定义离线世界文件 |

---

## 4. 命令行

~~~text
python scripts/nearby_explorer.py [选项] "一句话"

  --json                 输出 JSON（含 query / origin / candidates / diagnostics）
  --top N                候选数量 1~8，默认 5
  --origin lng,lat       当前坐标（"我附近"/"离我 N 米" 时必须）
  --default-city 杭州市   缺省城市
  --mock / --no-mock     强制离线 / 强制联网
  --explain              追加打印打分拆解与召回明细
  --verbose              打开脱敏调用日志（api / 耗时 / infocode / key 打码）
~~~

退出码：`0` 成功、`2` 无结果、`3` 需要位置、`4` 调用失败、`1` 其他。

JSON 状态语义：

| status | 含义 | 用户该怎么处理 |
| --- | --- | --- |
| `ok` | 有候选（1~5 个） | 直接用；若不足 3 个看 `suggestions` |
| `no_result` | 高德返回空 / 地点不存在 | 扩大半径、换类目、补城市名 |
| `need_location` | 缺少位置 | 给地名或 `--origin` |
| `error` | Key/配额/网络等调用失败 | 看 `error.infocode` 与建议 |

---

## 5. 架构与调用时序

~~~text
一句话
  │
  ├─ text_parser.parse()                    纯规则：位置 / 类目 / 约束 / 交通 / 时长
  │
  ├─ resolve_origin()                       逐级降级
  │    1. /v3/geocode/geo?address=..&city=..      （显式城市才带 city）
  │    2. /v3/geocode/geo?address=..               （去掉 city 再试）
  │    3. /v3/assistant/inputtips?keywords=..
  │    4. /v3/geocode/geo?address=<城市名>         （城市中心兜底）
  │
  ├─ recommender.recall()                   线程池 4，最多 4 个类目查询
  │    /v3/place/around?location=..&radius=..&types=..&keywords=..&offset=25
  │                        &page=..&extensions=all&sortrule=weight
  │    规则：精确关键词优先 → 结果不足 3 条时放宽为纯类型码 → 合并去重
  │
  ├─ filter → score → diversify            硬过滤 / 5 维打分 / 同类目≤2 + 间距>150m
  │
  ├─ planner.plan_routes()                  线程池 4，每候选 1~2 种方式
  │    /v3/direction/walking
  │    /v4/direction/bicycling
  │    /v3/direction/transit/integrated?city=..
  │    /v3/direction/driving
  │    失败 → /v3/distance?type=1 → 球面距离 × 路网系数（标注「约」）
  │
  └─ render_markdown() / --json
~~~

### 可靠性参数

| 项目 | 取值 |
| --- | --- |
| 单请求超时 | 连接 1.5s / 读取 3s |
| 单次查询总预算 | 8s（`Deadline`，超时即降级为估算） |
| 重试 | 1 次，指数退避 0.25s（仅对 10004/10014/10015/网络类可重试错误） |
| 并发 | 召回与路线规划各 4 线程；限流默认 3 QPS |
| 缓存 | 地理编码 24h / 周边搜索 30min / 路径规划 10min / 输入提示 30min，内存 LRU（512 条，线程安全） |
| 日志 | 每次调用记录 api、耗时、infocode、缓存命中；Key 打码 |

---

## 6. 打分公式（可解释、可复现）

~~~text
final = 0.30·距离 + 0.28·评分 + 0.16·人气 + 0.16·类目 + 0.10·营业
        + 约束调整（安静 +0.04 / 无障碍 +0.03 / 停车 +0.03 /
                    连锁 −0.10 / 超预算 −0.02~−0.12 / 口味词 +0.12 或 −0.04）
        最终截断到 [0, 1]
~~~

| 维度 | 公式 | 说明 |
| --- | --- | --- |
| 距离 | 步行 `exp(-d/500)`、骑行 `exp(-d/1200)`、公交/驾车 `exp(-d/3000)` | 越近越高，1→0 |
| 评分 | `clamp((rating-3.0)/2.0)` | 缺失按中性 **3.8**（=0.40） |
| 人气 | 0.55·人均合理度 + 0.30·评论数 + 0.15·图片数 | 高德不返回评论数时用图片数近似 |
| 类目 | 类型码命中 1.0 / 关键词命中 0.9 / 同大类 0.65 / 未知 0.5 | 支持父类类型码 |
| 营业 | 营业中 1.0 / 未知 0.6 / 已打烊 0.0 | 支持跨夜与 24 小时 |

排序 tie-break 用 POI id，保证同一输入同一排序。

### 多样性

- 多类目查询：同一类目最多 **2** 个，候选间直线距离 **> 150m**；
- 单类目查询（用户明确只要咖啡）：允许填满 top N，否则无法满足"3~5 个候选"；
- 候选不足时会放宽间距/类目上限并写入 `degraded`，保证不空手而归。

---

## 7. 错误码映射（节选）

完整表在 `scripts/amap_client.py` 的 `INFO_CODE_TABLE`（40+ 条），未知码会保留原码并给通用建议。

| infocode | 用户可读文案 | 处理 |
| --- | --- | --- |
| 10000 | 请求成功 | — |
| 10001 | Key 不正确或已过期 | 检查 `AMAP_KEY` 是否为 Web 服务 Key |
| 10002 | 该 Key 未开通此服务 | 控制台开通 Web 服务 API |
| 10003 | 今日调用配额已用尽 | 明日再试 / 换 Key / 提额度；可切离线模式 |
| 10004 | 访问过于频繁 | 自动降频重试 1 次 |
| 10009 | Key 平台类型不匹配 | 不能用 JS/Android/iOS Key |
| 20000 | 未查询到结果 | 扩大半径 / 换类目 / 补城市 |
| 20802 | 起终点距离过近 | 改用直线估算 |
| 20803 | 超出路径规划范围 | 改用直线估算并标注「约」 |
| 20805 | 路径规划失败 | 同上 |

---

## 8. 测试与验收

~~~bash
# 一键验收（单元测试 + 10 条端到端 + 安全检查）
bash tests/e2e.sh

# 分项
export AMAP_MOCK=1
python -m unittest discover -s tests -p "test_*.py" -v
python tests/e2e_check.py
python tests/check_no_secrets.py
~~~

本机实测（Python 3.12 / Windows，Git Bash）：

~~~text
Ran 78 tests in ~1.7s
OK

端到端验收：10 条中文语句（离线模式 AMAP_MOCK=1）
[PASS] coffee_walk          ok 候选=5  拾光咖啡、青柠咖啡、半山咖啡
[PASS] coffee_rating_budget ok 候选=3  鹿野咖啡、木棉咖啡、青柠咖啡
[PASS] park_relative        ok 候选=5  湖畔公园、城市绿地、樱花公园
[PASS] night_snack          ok 候选=5  老张夜宵档、巷口烧烤摊、老巷面馆
[PASS] study_room           ok 候选=5  区图书馆、24小时自习室、青柠咖啡
[PASS] explore              ok 候选=5  文化创意园、民俗纪念馆、自然科技馆
[PASS] mall_parking         ok 候选=5  购物中心、银泰百货、印象城
[PASS] transit_museum       ok 候选=5  民俗纪念馆、design展览馆、当代美术馆
[PASS] shanghai_coffee      ok 候选=5  青柠咖啡、远山咖啡、北纬咖啡
[PASS] hotpot_budget        ok 候选=5  蜀香火锅、深夜食堂、桥头私房菜
汇总：10/10 通过，平均候选 4.8 个，覆盖 bicycling、driving、transit、walking
~~~

另外做过一次**真实联网**验证（故意用无效 Key，确认 HTTP 链路与错误映射正常）：

~~~text
$ AMAP_MOCK=0 AMAP_KEY=<无效Key> python scripts/nearby_explorer.py --json "我在西湖附近想喝咖啡"
{
  "status": "error",
  "message": "Key 不正确或已过期（10001）",
  "error": {"infocode": "10001", "category": "auth", "raw_info": "INVALID_USER_KEY", "api": "geocode"},
  "source": {"offline": false, "key_masked": "dumm****00"}
}
退出码 4
~~~

---

## 9. 已知限制

1. **离线数据是合成的**：`fixtures/mock_world.json` 按高德文档字段结构构造，不是真实接口录制，
   只用于验证流程与回归；不能把它当真实业务数据引用。
2. **没有真实 Key 时无法验证真实数据的质量**：真实 POI 覆盖率、评分字段缺失率只有接上 Key 才能评估。
3. **公交方案需要城市**：跨城或城市缺失时退化为直线估算。
4. **评论数不可得**：高德 Web 服务不返回评论数，人气分为近似；排序在「同分同距」场景下依赖 POI id 兜底。
5. **单句多意图**：最多取前 3~4 个类目；「从天安门去国家博物馆」把天安门当出发地、博物馆当类目，
   不做"指定终点"的精确导航（这是另一个产品形态）。
6. **配额**：个人 Key 默认 3000 次/日、3 QPS；一次推荐约 5~12 次调用，重度使用需申请配额。
7. **仅中文**：解析器是中文规则表，英文/拼音会退化到默认类目。
8. Windows 控制台需要 UTF-8（脚本已自动 `reconfigure`，仍建议 `chcp 65001`）。

---

## 10. fixtures 来源（重要）

| 目录 | 内容 | 是否真实 |
| --- | --- | --- |
| `fixtures/samples/` | 按高德文档响应结构**手工构造**的样例（地理编码、周边、四种路径、错误码） | 否，仅结构真实 |
| `fixtures/mock_world.json` | 由 `tools/build_mock_fixtures.py` 确定性生成的合成 POI 世界（390 个 POI / 14 个地点 / 9 个城市） | 否，完全合成 |
| `fixtures/recorded/` | 用真实 Key 运行 `tools/record_fixtures.py` 得到的**真实录制**，存在时优先回放 | 是（需要你自己录制） |

### 换成真实数据（推荐比赛验收时做）

~~~bash
export AMAP_KEY='你的Web服务Key'
unset AMAP_MOCK
python tools/record_fixtures.py --cases tests/e2e_cases.json
# 之后 AMAP_MOCK=1 会优先命中 fixtures/recorded/ 的真实响应
~~~

录制只保存请求参数（**已剔除 key**）与响应体，`tests/check_no_secrets.py` 会检查是否有 Key 残留。

---

## 11. 与任务书 / 参考资料的差异（以赛题原文为准）

1. **赛题原文链接无法匿名抓取**：<https://oceanbase.yuque.com/.../qp60miwsbk1mcgod> 需要登录且是前端渲染，
   本机只能拿到标题，因此实现依据是题目给出的任务书正文。若原文与本文档冲突，以原文为准。
2. **距离衰减公式**：任务书写「步行 `1-exp(-d/500)`」。该式随距离**递增**，直接作为距离得分会把远处排前面；
   本实现用其补数 `exp(-d/500)` 表示衰减（等价于 `1-(1-exp(-d/500))`），并保留 `DISTANCE_DECAY_M` 可调。
3. **"同一类目最多 2 个"**：多类目查询严格执行；单类目查询（用户只要咖啡）放宽到 top N，
   否则与"输出 3~5 个候选"冲突。放宽动作会写入 `degraded`。
4. **评分门槛 / 避开连锁是软约束**：满足条件的候选不足 3 个时回补并提示，
   优先保证「正常语句稳定出结果（通过率 ≥95%）」。
5. **相对位置**：任务书说"我附近"由宿主提供坐标；本实现要求 `--origin` / `AMAP_ORIGIN`，
   缺失时返回 `need_location` 而不是猜测。
6. **fixtures 不是真实录制**：无 Key 环境下无法录制，用合成数据替代，并提供了录制工具与回放通道。

---

## 12. 安全声明

- Key 只从环境变量读取，不落盘、不进代码、不进 fixtures、不进日志（日志统一打码）；
- `tests/check_no_secrets.py` 会扫描仓库里的 32 位疑似 Key 与 `AMAP_KEY=` 赋值；
- 录制工具写盘前剔除 `key` 参数；
- URI 链接只包含坐标与名称，不包含 Key。
