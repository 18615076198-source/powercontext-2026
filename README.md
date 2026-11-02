# 周边去哪儿 · 高德地点推荐 Skill

用一句话找到附近 3~5 个合适的去处，并给出「怎么去」的步行 / 骑行 / 公交 / 驾车方案与高德跳转链接。
基于高德开放平台 Web 服务，Python 3.9+，只依赖标准库（联网时才需要 `requests`）。

> 赛题：高德开放平台 × OceanBase《周边去哪儿》
> 本分支：`2026-competition-gaode`（根目录即 Skill，供平台校验 `SKILL.md`）
> 完整实现：`nearby-explorer/`

## 目录

~~~text
SKILL.md               # Skill 定义（平台校验入口，含 name / description）
README.md              # 本文件
nearby-explorer/       # 完整工程：脚本、离线夹具、78 个单测、10 条 e2e、录制工具、文档
~~~

## 快速开始（离线，不需要 Key）

~~~bash
cd nearby-explorer
export AMAP_MOCK=1                 # PowerShell: $env:AMAP_MOCK='1'
python scripts/nearby_explorer.py "我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到"
~~~

~~~text
### 附近推荐：「西湖」 周边 1.0 公里 · 咖啡馆
> **解析**：位置「西湖（杭州市西湖区）」｜类目 咖啡馆｜半径 1000 米｜交通 步行｜停留 120 分钟
#### 1. 拾光咖啡　·　咖啡馆　·　⭐ 4.3
- **距离**：步行约 3 分钟（250 米，直线 200 米）
- **推荐理由**：咖啡馆「安静」，步行约 3 分钟（250 米），评分 4.3，人均 49 元，符合「安静」要求。
- **交通方案**（最多 2 种）：1. 步行 3 分钟（250 米）
~~~

在线模式：

~~~bash
export AMAP_KEY='你的Web服务Key'
python scripts/nearby_explorer.py "北京国贸附近评分4.5以上的咖啡馆，人均50以内"
~~~

## 验收

~~~bash
cd nearby-explorer
bash tests/e2e.sh      # 78 单测 + 10 条中文 e2e + Key 扫描
~~~

结果：78 tests OK、10/10 通过、平均 4.8 个候选、覆盖步行/骑行/公交/驾车四种方式、无明文 Key。

## 说明

- `nearby-explorer/fixtures/` 是**合成样例**（无 Key 环境无法录制），已显式标注；
  提供 `tools/record_fixtures.py`，有 Key 时可录制真实响应并优先回放。
- 详细文档见 `nearby-explorer/README.md`、`nearby-explorer/SKILL.md`、`nearby-explorer/docs/PLAN.md`。
