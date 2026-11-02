# 验收清单逐项自查

图例：✅ 已满足　🟡 部分满足（有说明）　⛔ 已知限制

## A. 交付形态（硬性）

| 项 | 状态 | 证据 |
| --- | --- | --- |
| 仓库根目录新增 Skill 目录 | ✅ | `nearby-explorer/` |
| SKILL.md（YAML frontmatter: name/description + 时机/输入输出） | ✅ | `SKILL.md` |
| scripts/amap_client.py | ✅ | 超时/重试/错误码/限流/缓存/脱敏 |
| scripts/text_parser.py | ✅ | 纯规则、确定性、无模型 |
| scripts/recommender.py | ✅ | 召回+打分+多样性+理由 |
| scripts/planner.py | ✅ | 4 种方式+兜底+URI |
| fixtures/（离线样例，无 Key） | ✅ | `fixtures/samples/`、`fixtures/mock_world.json`；扫描通过 |
| tests/（单测 + e2e 脚本） | ✅ | `tests/`，78 单测 + `e2e.sh` |
| README（用法/环境变量/限制/验收命令） | ✅ | `README.md` |
| Python 3.9+，仅标准库 + requests | ✅ | 无其他三方依赖；离线模式未安装 requests 也能跑 |
| Key 只从 `AMAP_KEY` 读取，不落盘 | ✅ | `check_no_secrets.py` 通过；日志打码 |
| `AMAP_MOCK=1` 离线可跑通全部测试 | ✅ | `bash tests/e2e.sh` 全绿 |

## B. 功能需求

| 需求 | 状态 | 说明 |
| --- | --- | --- |
| 显式地名 / 相对位置 / 缺失时询问或默认城市 | ✅ | 6 类句式；相对位置需 `--origin`，缺失返回 `need_location` |
| 类目映射（咖啡/餐厅/景点/公园/博物馆/商场/夜宵/亲子/自习…） | ✅ | 14 个类目，映射高德类型码 + 关键词 |
| 约束（半径/预算/营业中/评分/避开连锁/无障碍/停车/安静） | ✅ | 解析 + 打分/过滤；软约束有回补 |
| 交通方式（步行/骑行/公交/驾车） | ✅ | 默认步行；>1.5km 自动改公交提示 |
| 时间（停留时长、含往返） | 🟡 | 解析时长用于文案与预算提示；"含往返"仅识别不做行程排程 |
| geocode（或 inputtips）定位 | ✅ | 4 级降级 |
| place/around 多类目并行召回（radius/types/keywords/extensions=all/offset=25/page/sortrule） | ✅ | 线程池 4，最多 4 类目，page 2 自动翻页 |
| 去重（id + 名称 + <30m） | ✅ | `recall()` |
| 过滤（关闭/超距/类目不符） | ✅ | `filter_pois()` |
| 距离衰减 / 评分 / 人气（cost+评论）/ 类目匹配 | ✅ | 权重 0.30/0.28/0.16/0.16/0.10 |
| 多样性（同类目≤2、间距>150m） | 🟡 | 多类目严格执行；单类目放宽到 top N（见 README 差异第 3 条） |
| 超半径剔除 / 不营业与无评分降权 | ✅ | 硬过滤 + 营业分 |
| top 3~5 + 推荐理由（引用距离/评分/类目） | ✅ | 模板保证三要素齐全 |
| 步行/骑行/公交/驾车路线 | ✅ | 四种解析器 |
| 公交给出线路 + 换乘 + 总时长 | ✅ | `parse_transit` |
| 驾车给出时长 + 距离 + 主要道路 | ✅ | `parse_driving` |
| 失败兜底 distance?type=1 并标注「约」 | ✅ | `_fallback_plan` |
| 每候选高德 URI | ✅ | marker + navigation + app scheme |
| Markdown 固定字段 | ✅ | 名称/类目/距离/评分/人均/营业时间/地址/理由/交通/链接 |

## C. 工程要求

| 项 | 状态 | 说明 |
| --- | --- | --- |
| status/infocode 统一处理 + 映射表 | ✅ | 40+ 条；未知码保留原码 |
| 单请求超时 3s / 总预算 8s | ✅ | 连接 1.5s、读取 3s；`Deadline` |
| 重试 1 次（指数退避） | ✅ | 仅可重试错误 |
| 线程池并发 ≤4 + 遵守 QPS | ✅ | 召回/规划各 4；默认 3 QPS |
| 缓存 TTL（24h/30min/10min） | ✅ | 含参数哈希键 |
| 日志脱敏 + api/耗时/infocode | ✅ | `--verbose` 可见，Key 打码 |
| 每模块确定性单测 | ✅ | 78 个，全部离线 |
| e2e 10 条语句断言 ≥3 候选 + 有交通方案 | ✅ | `tests/e2e_check.py`，10/10 |

## D. 质量目标

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 通过率 ≥95%（正常语句稳定出结果） | ✅ | 10/10；单点失败一律降级 |
| 区分「无结果」与「调用失败」并给建议 | ✅ | `no_result` / `error` / `need_location` |
| 覆盖场景：单类目、跨类目、预算、时长、公交优先、地名模糊、地点不存在、Key 缺失、配额超限 | ✅ | e2e 10 条 + 单测（10001/10003/20000/20802/20803） |
| 至少 5 个候选/条 | 🟡 | 通常 5 个；严格评分门槛下可能 3 个 |

## E. 已知限制

1. 离线 fixtures 为合成数据，非真实接口录制（无 Key 环境）；提供录制工具可一键替换。
2. 赛题原文 Yuque 页面无法匿名抓取，实现依据题目给出的任务书正文。
3. 公交需要城市参数；跨城退化为估算。
4. 高德不返回评论数，人气分为近似值。
5. 一句话多目的地（"从 A 去 B"）只把 A 当出发地、B 当类目，不做终点精确导航。
6. 仅中文规则解析。
7. 自动扩半径最多一次且不超过 3000m。

## F. 复验命令

~~~bash
cd nearby-explorer
bash tests/e2e.sh          # 单测 + 10 条 e2e + Key 扫描
python tools/inspect_query.py "我在西湖附近想喝咖啡"
AMAP_MOCK=1 python scripts/nearby_explorer.py --explain "离我1公里内找个公园" --origin 120.148,30.246
~~~
