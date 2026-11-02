# 周边去哪儿 —— 一句话找附近去处，并说明怎么去

[![gaode-nearby-explorer-ci](https://github.com/18615076198-source/powercontext-2026/actions/workflows/gaode-ci.yml/badge.svg?branch=2026-competition-ecosystem)](https://github.com/18615076198-source/powercontext-2026/actions/workflows/gaode-ci.yml)

> 赛题：高德开放平台 × OceanBase《周边去哪儿》
> 仓库：`18615076198-source/powercontext-2026`　分支：`2026-competition-ecosystem`　产物：`gaode/nearby-explorer/`
> 运行环境：Python 3.9+（实际在 3.7.7 / 3.12 上都跑通），离线验收不联网、不需要 Key

用户一句话（例如「我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到」），
输出 3~5 个候选地点 + 每个候选「怎么去」的交通方案 + 高德跳转链接。

## 一、题目要求与实现对照

| 题目要求 | 实现 | 证据位置 |
| --- | --- | --- |
| 一句话解析位置 / 类目 / 约束 / 交通 / 时间 | 纯规则解析器，14 类目、20 城市、6 类位置句式、中文数量词 | `scripts/text_parser.py` |
| 地名定位与消歧 | geocode → 去城市重试 → inputtips → 城市中心，四级降级 | `scripts/nearby_explorer.py` `resolve_origin` |
| 多类目并行召回 | 线程池 4，`/v3/place/around`，types 优先、关键词兜底、满 25 条翻页 | `scripts/recommender.py` `recall` |
| 去重与过滤 | POI id + 同名 30m 内合并；超半径/类目不符/打烊直接剔除 | `scripts/recommender.py` `filter_pois` |
| 可解释打分 | 距离 0.30 / 评分 0.28 / 人气 0.16 / 类目 0.16 / 营业 0.10 + 约束调整 | `SCORING_WEIGHTS`、`--explain` |
| 多样性 | 同类目 ≤2、候选间距 >150m；候选不足时放宽并记录 | `recommender.diversify` |
| 四种交通方式 | 步行 / 骑行 / 公交（线路+换乘）/ 驾车（道路） | `scripts/planner.py` |
| 失败兜底 | 路线失败 → `/v3/distance?type=1` → 球面距离×路网系数，标「约」 | `_fallback_plan` |
| 高德跳转 | marker + navigation + App scheme | `candidate_links` |
| Markdown 固定字段 | 名称/类目/距离/评分/人均/营业时间/地址/理由/交通/链接 | `scripts/render.py` |
| 错误码与降级 | 40+ infocode 映射，区分「无结果 / 调用失败 / 缺位置」 | `INFO_CODE_TABLE` |
| 超时/重试/限流/缓存/脱敏 | 1.5s+3s 超时、8s 预算、重试 1 次、3 QPS、24h/30min/10min 缓存、Key 打码 | `scripts/amap_client.py` |
| 离线可测 | `AMAP_MOCK=1`：78 个单测 + 10 条 e2e，无需 Key/网络 | `tests/` |
| 不伪造数据 | 离线数据显式标注 `synthetic`；提供真实录制工具 | `fixtures/README.md` |

## 二、一条命令看效果（离线，不需要 Key）

~~~bash
cd gaode/nearby-explorer
export AMAP_MOCK=1            # PowerShell: $env:AMAP_MOCK='1'
python scripts/nearby_explorer.py "我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到"
~~~

~~~text
### 附近推荐：「西湖」 周边 1.0 公里 · 咖啡馆
> **解析**：位置「西湖（杭州市西湖区）」｜类目 咖啡馆｜半径 1000 米｜交通 步行｜停留 120 分钟
> **模式**：离线模式（AMAP_MOCK=1，数据来自 fixtures/ 合成样例，不是实时结果）

#### 1. 拾光咖啡　·　咖啡馆　·　⭐ 4.3
- **距离**：步行约 3 分钟（250 米，直线 200 米）
- **评分**：4.3 ｜ **人均**：¥49
- **营业时间**：10:00-22:30（已打烊）
- **地址**：杭州市西湖区南山路31号
- **推荐理由**：咖啡馆「安静」，步行约 3 分钟（250 米），评分 4.3，人均 49 元，符合「安静」要求。
- **交通方案**（最多 2 种）：1. 步行 3 分钟（250 米）
- **高德链接**：[查看地点](https://uri.amap.com/marker?...) · [导航过去](https://uri.amap.com/navigation?...)
~~~

在线模式：

~~~bash
export AMAP_KEY='你的Web服务Key'
python scripts/nearby_explorer.py "北京国贸附近评分4.5以上的咖啡馆，人均50以内"
~~~

## 三、目录

~~~text
gaode/nearby-explorer/
├── SKILL.md               # Skill 入口：何时使用 / 输入输出约定
├── README.md              # 详细说明：环境变量、打分公式、限制、差异
├── docs/PLAN.md           # 实现计划与 API 调用时序
├── docs/ACCEPTANCE.md     # 验收清单逐项自查
├── scripts/               # amap_client / mock_backend / text_parser / recommender / planner / render / nearby_explorer / geo
├── fixtures/              # 合成 POI 世界 + 接口样例（标注 synthetic）
├── tests/                 # 78 单测 + e2e_check + e2e.sh + Key 扫描
└── tools/                 # 生成离线世界 / 录制真实响应 / 解析调试
~~~

## 四、验收结果（离线）

~~~text
$ bash tests/e2e.sh
Ran 78 tests ... OK
[PASS] coffee_walk / coffee_rating_budget / park_relative / night_snack / study_room
[PASS] explore / mall_parking / transit_museum / shanghai_coffee / hotpot_budget
汇总：10/10 通过，平均候选 4.8 个，覆盖 bicycling、driving、transit、walking
安全检查通过：未发现明文 Key / 32 位疑似 Key。
~~~

| 场景 | 语句 | 结果 |
| --- | --- | --- |
| 单类目 + 安静 + 时长 + 步行 | 我在西湖附近，下午想找个安静的咖啡馆坐两小时… | 5 个候选 |
| 评分门槛 + 预算 | 北京国贸附近评分4.5以上的咖啡馆，人均50以内 | 3 个候选（含降级说明） |
| 相对位置 | 离我1公里内找个公园（`--origin`） | 5 个候选 |
| 夜宵 | 我在解放路附近找个夜宵（三城同名，消歧） | 5 个候选 |
| 自习（跨类目） | 帮我找五道口附近的自习室 | 5 个候选 |
| 跨类目闲逛 | 国贸附近有什么好玩的 | 5 个候选 |
| 停车 + 无障碍 + 驾车 | 我在西湖文化广场附近…开车去 | 5 个候选 |
| 公共交通优先 | 从天安门出发去国家博物馆，坐地铁 | 5 个候选（transit） |
| 口味词 | 我在春熙路附近想吃火锅，人均100以内 | 火锅店排第 1 |
| 高德赛道核心链路 | 上述全部 | 每条都有交通方案与链接 |

## 五、离线数据说明（重要）

`fixtures/mock_world.json` 是按高德文档字段结构**确定性生成**的合成世界（390 个 POI / 14 个地点 / 9 个城市），
`__meta__.synthetic = true`，**不是真实接口录制**。仓库同时提供 `tools/record_fixtures.py`，
有 Key 时录制真实响应，`AMAP_MOCK=1` 会优先回放录制数据，切换不需要改代码。详见 `fixtures/README.md`。

## 六、已知限制

- 公交方案需要城市参数；跨城退化为直线估算；
- 高德 Web 服务不返回评论数，人气分为近似；
- 单类目查询会放宽「同类目最多 2 个」以保证 3~5 个候选（写入 `degraded`）；
- 一句话多目的地只把首个地名当出发点，不做终点精确导航；
- 中文规则解析，英文/拼音会退化到默认类目。

更完整的说明见 `README.md`（环境变量、打分公式、与任务书的差异）。
