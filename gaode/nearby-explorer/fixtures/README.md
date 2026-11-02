# fixtures 说明（数据来源，必读）

| 文件/目录 | 是什么 | 是否真实高德数据 |
| --- | --- | --- |
| `samples/*.json` | 按高德 Web 服务文档的响应结构**手工构造**的样例，覆盖 geocode / around / walking / bicycling / driving / transit / distance / 错误码 | ❌ 结构真实，内容是示例 |
| `mock_world.json` | `tools/build_mock_fixtures.py` 确定性生成的合成 POI 世界（390 个 POI、14 个地点、9 个城市、公交线路表） | ❌ 完全合成 |
| `recorded/` | 用真实 Key 运行 `tools/record_fixtures.py` 得到，`index.json` 记录请求参数（已剔除 key） | ✅ 真实（需要你录制） |

## 为什么用合成数据

赛题要求「必须支持 `AMAP_MOCK=1`，无网络、无 Key 也能跑通全部测试」。本项目开发环境没有 Key，
也不能伪造「录制」名义把编造的数据说成真实返回，所以：

1. 合成数据在 `mock_world.json.__meta__.synthetic = true` 与本文档中明确标注；
2. 另提供 `tools/record_fixtures.py`，有 Key 时一条命令录真实响应；
3. `scripts/mock_backend.py` 会**优先回放真实录制**，未命中才用合成世界，所以换成真实数据不需要改代码。

## 如何录制真实数据

~~~bash
export AMAP_KEY='你的Web服务Key'
unset AMAP_MOCK
python tools/record_fixtures.py --cases tests/e2e_cases.json
~~~

录制完成后：

~~~bash
AMAP_MOCK=1 python scripts/nearby_explorer.py "..."
~~~

此时命中的请求来自 `fixtures/recorded/`（真实），其余仍走合成世界。
`tests/check_no_secrets.py` 会验证录制索引里没有残留 key 参数。

## 生成合成世界

~~~bash
python tools/build_mock_fixtures.py
~~~

生成过程无随机数、无时间依赖，重复执行结果完全一致。
