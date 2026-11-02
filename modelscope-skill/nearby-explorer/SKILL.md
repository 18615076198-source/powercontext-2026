---
name: nearby-explorer
version: 1.0.0
description: 用一句话找到附近 3~5 个合适的去处，并给出步行 / 骑行 / 公交 / 驾车方案与高德跳转链接。当用户说「我在西湖附近想找个安静的咖啡馆」「附近有什么好玩的」「离我 1 公里内找个公园」「从国贸出发坐地铁去看展」时使用；也适用于带预算、评分门槛、营业中、避开连锁、停车 / 无障碍等约束的周边推荐。
license: MIT
---

# nearby-explorer（周边去哪儿）

把一句中文请求变成**可解释的候选列表 + 可执行的交通方案**，数据来自高德开放平台 Web 服务。

## 何时使用

- 用户在某个地点附近找地方：咖啡、餐厅、夜宵、公园、景点、博物馆、商场、超市、亲子、自习、酒吧、茶馆、电影院；
- 用户给了约束：半径、预算、评分门槛、营业中、避开连锁、安静、无障碍、停车、停留时长、含往返；
- 用户问「怎么去」「坐地铁 / 骑车 / 开车方便吗」；
- 用户说「我附近」但没有说地名（此时需要提供当前坐标）。

不适用：跨城市行程规划、多日游排程、实时排队/路况、与地理位置无关的推荐。

## 快速开始

~~~bash
pip install requests                     # 唯一第三方依赖；离线模式无需联网

# 离线模式（无 Key、无网络，使用内置 fixtures 合成样例）
AMAP_MOCK=1 python scripts/nearby_explorer.py "我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到"

# 在线模式（需要高德 Web 服务 Key）
export AMAP_KEY='你的Web服务Key'
python scripts/nearby_explorer.py "北京国贸附近评分4.5以上的咖啡馆，人均50以内"

# 相对位置：宿主提供当前坐标
python scripts/nearby_explorer.py --origin 120.148,30.246 "离我1公里内找个公园"

# 结构化输出 + 打分拆解
python scripts/nearby_explorer.py --json --explain "我在西湖附近想喝咖啡"
~~~

Windows PowerShell 用 `$env:AMAP_MOCK='1'` / `$env:AMAP_KEY='...'`。

## 输入约定

必填：一条自然语言请求。可选：当前位置坐标（`lng,lat`）。

| 情况 | 行为 |
| --- | --- |
| 有地名 + 有城市 | 地理编码直接定位 |
| 只有地名 | 地理编码 → 输入提示 → 城市中心，逐级降级 |
| 只说「我附近」且给了 `--origin` | 使用给定坐标 |
| 只说「我附近」但没坐标 | 返回 `need_location`，提示补充地名或坐标 |
| 地名在多个城市都存在 | 默认取第一个，并在 `degraded` 里提示可补充城市名 |

## 输出约定

默认输出 Markdown，每条候选固定字段：**名称、类目、距离（步行分钟 + 距离）、评分、人均、营业时间、地址、推荐理由、交通方案（最多 2 种）、高德跳转链接。**

`--json` 输出结构化结果，关键字段：

~~~json
{
  "status": "ok | no_result | need_location | error",
  "query": { "location_text": "西湖", "categories": ["coffee"], "radius_m": 1000, "transport": "walking" },
  "origin": { "name": "西湖", "city": "杭州市", "lng": 120.148, "lat": 30.2459 },
  "candidates": [{
    "name": "拾光咖啡", "category_label": "咖啡馆", "distance_m": 201, "walk_minutes": 3,
    "rating": 4.3, "cost": 49, "open_time": "10:00-22:30",
    "reason": "咖啡馆「安静」，步行约 3 分钟（250 米），评分 4.3，人均 49 元。",
    "routes": [{ "mode": "walking", "summary": "步行 3 分钟（250 米）" }],
    "links": { "marker": "https://uri.amap.com/...", "navigation": "https://uri.amap.com/..." }
  }],
  "degraded": [],
  "suggestions": []
}
~~~

状态语义：`ok` 有候选；`no_result` 高德返回空/地点不存在（附扩大半径、换类目建议）；`need_location` 缺位置；`error` 调用失败（带 infocode 与处置建议）。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AMAP_KEY` | 空 | 高德「Web 服务」Key；联网必填 |
| `AMAP_MOCK` | 0 | `1` 时离线运行，不联网 |
| `AMAP_QPS` | 3（在线）/ 100（离线） | 限流 |
| `AMAP_BUDGET` | 8.0 | 单次查询总预算（秒） |
| `AMAP_DEFAULT_CITY` | 空 | 缺省城市 |
| `AMAP_ORIGIN` | 空 | 当前坐标，等同 `--origin` |

## 设计要点

1. **解析**：纯规则（14 类目 / 20 城市 / 6 类位置句式 / 中文数量词），确定性、可复现；
2. **召回**：多类目并行（线程池 4），优先类型码、空结果退关键词，`/v3/place/around` 翻页；
3. **打分**：距离 0.30 + 评分 0.28 + 人气 0.16 + 类目 0.16 + 营业 0.10，外加安静/停车/预算等约束调整；权重集中在 `recommender.py` 顶部，可调；
4. **多样性**：多类目查询同类目 ≤2、候选间距 >150m；候选不足时放宽并记录；
5. **交通**：步行 / 骑行 / 公交（线路+换乘）/ 驾车（道路），失败时用 `/v3/distance` 或球面距离兜底，文案标注「约」；
6. **可靠性**：单请求 3s 超时、总预算 8s、重试 1 次、3 QPS、缓存（地理编码 24h / 周边 30min / 路线 10min）、日志中 Key 打码。

## 目录

~~~text
nearby-explorer/
├── SKILL.md
├── references/         # README / LICENSE / requirements（说明与许可）
├── scripts/            # amap_client / text_parser / recommender / planner / render / nearby_explorer / geo / mock_backend
├── fixtures/           # 离线合成样例（samples + mock_world.json）
├── tools/              # 生成离线世界 / 录制真实响应 / 解析调试
└── examples/           # 示例请求与输出
~~~

## 已知限制

- 离线 fixtures 为合成数据，仅用于流程验证，不是真实高德结果；
- 公交路线需要城市参数，跨城会退化为估算；
- 高德不返回评论数，人气分为近似；
- 单类目查询会放宽「同类目最多 2 个」以保证 3~5 个候选；
- 仅支持中文规则解析。

## License

MIT
