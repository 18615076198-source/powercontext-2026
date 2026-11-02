---
name: nearby-explorer
description: 一句话找到附近 3~5 个合适的去处，并给出步行/骑行/公交/驾车方案与高德跳转链接。当用户说「我在西湖附近想找个安静的咖啡馆」「附近有什么好玩的」「离我 1 公里内找个公园」「从国贸出发坐地铁去看展」时使用；也适用于带预算、评分门槛、营业中、避开连锁、停车/无障碍等约束的周边推荐。
---

# nearby-explorer（周边去哪儿）

把一句中文请求变成**可解释的候选列表 + 可执行的交通方案**。

## 何时使用

适用：

- 用户在某个地点附近找地方：咖啡、餐厅、夜宵、公园、景点、博物馆、商场、超市、亲子、自习、酒吧、茶馆、电影院；
- 用户给了约束：半径、预算、评分门槛、营业中、避开连锁、安静、无障碍、停车、停留时长、含往返；
- 用户问「怎么去」「坐地铁/骑车/开车方便吗」；
- 用户说「我附近」但没有说地名（此时需要宿主提供当前坐标）。

不适用：

- 跨城市的行程规划、多日游排程；
- 需要真实实时数据（排队人数、实时路况）的问题；
- 与地理位置无关的推荐（例如「推荐一部电影」）。

## 输入约定

必填：一条自然语言请求。可选：当前位置坐标（lng,lat）。

解析器是**纯规则**的（`text_parser.py`），确定性、可单测，不依赖大模型。识别不到位置时不会瞎猜：

| 情况 | 行为 |
| --- | --- |
| 有地名 + 有城市 | 直接用地理编码定位 |
| 只有地名 | 地理编码 → 输入提示 → 城市中心，逐级降级 |
| 只说「我附近」且给了 `--origin` | 用给定坐标 |
| 只说「我附近」但没坐标 | 返回 `need_location`，提示补充地名或坐标 |
| 地名在多个城市都存在 | 默认取第一个，并在 `degraded` 里提示可补充城市名 |

## 输出约定

默认输出 Markdown，每条候选固定字段：

**名称、类目、距离（步行分钟 + 距离）、评分、人均、营业时间、地址、推荐理由、交通方案（最多 2 种）、高德跳转链接。**

`--json` 时输出结构化结果，关键字段：

~~~json
{
  "status": "ok | no_result | need_location | error",
  "message": "给人看的一句话",
  "query": { "location_text": "西湖", "categories": ["coffee"], "radius_m": 1000, "transport": "walking" },
  "origin": { "name": "西湖", "lng": 120.148, "lat": 30.2459, "city": "杭州市" },
  "candidates": [{
    "name": "拾光咖啡", "category": "coffee", "distance_m": 201, "walk_minutes": 3,
    "rating": 4.3, "cost": 49, "open_time": "10:00-22:30",
    "reason": "咖啡馆「安静」，步行约 3 分钟（250 米），评分 4.3，人均 49 元。",
    "routes": [{ "mode": "walking", "summary": "步行 3 分钟（250 米）", "estimated": false }],
    "links": { "marker": "https://uri.amap.com/marker?...", "navigation": "https://uri.amap.com/navigation?..." }
  }],
  "degraded": ["周边 1000 米内没有结果，已自动扩大到 2000 米"],
  "suggestions": ["候选偏少，可以放宽半径"]
}
~~~

状态语义（**明确区分「无结果」和「调用失败」**）：

- `ok`：有 1~5 个候选；候选不足 3 个时会给出 `suggestions`；
- `no_result`：高德返回空结果或地点不存在，附「扩大半径 / 换类目 / 补城市」建议；
- `need_location`：缺位置，附提问；
- `error`：调用失败，带 `infocode`、分类（auth/quota/rate/network/route…）与处置建议。

## 怎么调用

~~~bash
# 离线（无需网络与 Key，使用 fixtures 合成数据）
AMAP_MOCK=1 python nearby-explorer/scripts/nearby_explorer.py "我在西湖附近想找个安静的咖啡馆"

# 在线（需要 Web 服务 Key）
export AMAP_KEY='你的Web服务Key'
python nearby-explorer/scripts/nearby_explorer.py "北京国贸附近评分4.5以上的咖啡馆，人均50以内"

# 结构化输出 + 打分拆解
python nearby-explorer/scripts/nearby_explorer.py --json --explain "..."

# 相对位置：宿主提供当前坐标
python nearby-explorer/scripts/nearby_explorer.py --origin 120.148,30.246 "离我1公里内找个公园"
~~~

## 关键行为

1. **永不因单点失败报错退出**：召回失败换关键词、路径规划失败用 `/v3/distance` 兜底、再失败用球面距离估算并标「约」。
2. **结果可解释**：每条候选有 `score_parts`（距离/评分/人气/类目/营业 + 调整项），`--explain` 会打印。
3. **缓存与限流**：地理编码 24h、周边搜索 30min、路径规划 10min；默认 3 QPS，单请求超时 3s，总预算 8s。
4. **Key 安全**：只从 `AMAP_KEY` 读取，日志里打码，fixtures 与录制数据都不含 Key。

## 已知限制

- 公共交通方案需要城市参数；跨城路线会退化为直线距离估算；
- 高德 Web 服务不返回真实评论数，人气分用「人均消费 + 图片数 +（若有）评论数」近似；
- 一句话里出现多个意图时只取前 3 个类目；
- 离线模式的数据是**合成的**，只用于流程验证，不能当真实结果引用。
