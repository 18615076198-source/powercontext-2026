# nearby-explorer（周边去哪儿）

一句话找到附近 3~5 个去处，并说明怎么去。基于高德开放平台 Web 服务，Python 3.9+，只依赖 requests。

## 它能做什么

- 输入：「我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到」
- 输出：3~5 个候选（距离、评分、人均、营业时间、地址、推荐理由）+ 步行/骑行/公交/驾车方案 + 高德跳转链接

支持约束：半径、预算、评分门槛、营业中、避开连锁、安静、无障碍、停车、停留时长。
支持交通：步行 / 骑行 / 公交（线路+换乘）/ 驾车（道路），失败自动降级为估算并标注「约」。

## 安装与运行

~~~bash
pip install -r requirements.txt
AMAP_MOCK=1 python scripts/nearby_explorer.py "我在西湖附近想找个安静的咖啡馆"
~~~

联网：

~~~bash
export AMAP_KEY='你的Web服务Key'          # 高德控制台申请「Web 服务」类型 Key
python scripts/nearby_explorer.py "北京国贸附近评分4.5以上的咖啡馆，人均50以内"
~~~

## 离线模式

AMAP_MOCK=1 时读取 fixtures/，无网络、无 Key 也能完整跑通（数据是合成样例，仅用于流程演示）。
拿到真实 Key 后可用 tools/record_fixtures.py 录制真实响应。

## 示例

见 examples/quickstart.md。

## 许可

MIT。高德接口的使用需遵守高德开放平台的服务条款与配额限制。
