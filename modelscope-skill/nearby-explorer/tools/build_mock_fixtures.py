"""生成离线 mock 世界（fixtures/mock_world.json）。

重要说明（不要误解）
--------------------
这里的数据是**按高德 Web 服务公开文档的字段结构手工构造的合成样例**，
不是真实高德返回，也不包含任何 Key。它的用途是让 AMAP_MOCK=1 时
全链路（地理编码 -> 周边搜索 -> 打分 -> 路径规划 -> 渲染）可以离线、确定性地跑通。

拿到真实 Key 之后，请用 tools/record_fixtures.py 录制真实返回，
再用 --strict 模式做回归对比（见 README「如何换成真实数据」）。

生成过程完全确定（无随机数、无时间依赖），重复运行结果一致。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "fixtures", "mock_world.json")

SEED_VERSION = "nearby-explorer-mock-v1"

CITIES: Dict[str, Dict[str, object]] = {
    "杭州市": {"lng": 120.15507, "lat": 30.274085, "citycode": "0571", "adcode": "330100", "district": "上城区", "province": "浙江省"},
    "北京市": {"lng": 116.407526, "lat": 39.904030, "citycode": "010", "adcode": "110000", "district": "东城区", "province": "北京市"},
    "上海市": {"lng": 121.473701, "lat": 31.230416, "citycode": "021", "adcode": "310000", "district": "黄浦区", "province": "上海市"},
    "成都市": {"lng": 104.066541, "lat": 30.572269, "citycode": "028", "adcode": "510100", "district": "锦江区", "province": "四川省"},
    "广州市": {"lng": 113.264385, "lat": 23.129112, "citycode": "020", "adcode": "440100", "district": "天河区", "province": "广东省"},
    "深圳市": {"lng": 114.057868, "lat": 22.543099, "citycode": "0755", "adcode": "440300", "district": "南山区", "province": "广东省"},
    "南京市": {"lng": 118.796877, "lat": 32.060255, "citycode": "025", "adcode": "320100", "district": "秦淮区", "province": "江苏省"},
    "西安市": {"lng": 108.940175, "lat": 34.341568, "citycode": "029", "adcode": "610100", "district": "新城区", "province": "陕西省"},
    "长沙市": {"lng": 112.938814, "lat": 28.228209, "citycode": "0731", "adcode": "430100", "district": "岳麓区", "province": "湖南省"},
}

# 地点：name / aliases / city / district / lng lat / 支持类目
PLACES: List[Dict[str, object]] = [
    {
        "name": "西湖", "aliases": ["西湖景区", "杭州西湖", "断桥残雪", "苏堤", "白堤"],
        "city": "杭州市", "district": "西湖区", "lng": 120.148, "lat": 30.2459, "level": "兴趣点",
        "roads": ["北山街", "南山路", "湖滨路", "孤山路", "杨公堤"],
        "categories": ["coffee", "park", "museum", "restaurant", "attraction", "tea", "mall", "bar"],
    },
    {
        "name": "国贸", "aliases": ["国贸商城", "建国门外", "CBD国贸"],
        "city": "北京市", "district": "朝阳区", "lng": 116.4617, "lat": 39.9087, "level": "兴趣点",
        "roads": ["建国门外大街", "光华路", "呼家楼南里", "金桐东路"],
        "categories": ["coffee", "restaurant", "mall", "museum", "attraction", "bar", "tea"],
    },
    {
        "name": "南京西路", "aliases": ["南京西路商圈", "静安寺", "石门一路"],
        "city": "上海市", "district": "静安区", "lng": 121.45, "lat": 31.227, "level": "道路",
        "roads": ["南京西路", "威海路", "陕西北路", "常德路"],
        "categories": ["coffee", "restaurant", "mall", "attraction", "museum", "tea"],
    },
    {
        "name": "天安门", "aliases": ["天安门广场", "故宫", "午门"],
        "city": "北京市", "district": "东城区", "lng": 116.3975, "lat": 39.9087, "level": "兴趣点",
        "roads": ["东长安街", "天安门广场东侧路", "西华门大街"],
        "categories": ["attraction", "museum", "coffee", "restaurant", "park"],
    },
    {
        "name": "春熙路", "aliases": ["春熙路商圈", "太古里", "红星路"],
        "city": "成都市", "district": "锦江区", "lng": 104.081, "lat": 30.656, "level": "道路",
        "roads": ["春熙路", "红星路三段", "中纱帽街", "大科甲巷"],
        "categories": ["restaurant", "coffee", "mall", "tea", "night_snack", "attraction"],
    },
    {
        "name": "珠江新城", "aliases": ["珠江新城CBD", "花城广场", "猎德"],
        "city": "广州市", "district": "天河区", "lng": 113.321, "lat": 23.119, "level": "兴趣点",
        "roads": ["华夏路", "花城大道", "冼村路", "珠江东路"],
        "categories": ["coffee", "mall", "park", "restaurant", "museum"],
    },
    {
        "name": "新街口", "aliases": ["新街口商圈", "中山路", "德基"],
        "city": "南京市", "district": "秦淮区", "lng": 118.784, "lat": 32.041, "level": "兴趣点",
        "roads": ["中山南路", "汉中路", "淮海路", "洪武路"],
        "categories": ["coffee", "restaurant", "mall", "museum"],
    },
    {
        "name": "深圳湾公园", "aliases": ["深圳湾", "人才公园", "红树林"],
        "city": "深圳市", "district": "南山区", "lng": 113.948, "lat": 22.511, "level": "兴趣点",
        "roads": ["滨海大道", "海德三道", "科苑南路"],
        "categories": ["park", "coffee", "attraction", "restaurant"],
    },
    {
        "name": "五道口", "aliases": ["五道口地铁站", "成府路", "清华东路"],
        "city": "北京市", "district": "海淀区", "lng": 116.337, "lat": 39.992, "level": "兴趣点",
        "roads": ["成府路", "清华东路", "学院路", "中关村东路"],
        "categories": ["library", "coffee", "restaurant", "tea"],
    },
    {
        "name": "解放路", "aliases": [], "city": "杭州市", "district": "上城区",
        "lng": 120.174, "lat": 30.251, "level": "道路",
        "roads": ["解放路", "清泰街", "庆春路"], "categories": ["night_snack", "restaurant", "coffee"],
    },
    {
        "name": "解放路", "aliases": [], "city": "成都市", "district": "青羊区",
        "lng": 104.066, "lat": 30.669, "level": "道路",
        "roads": ["解放路", "总府路", "大慈寺路"], "categories": ["night_snack", "restaurant", "coffee"],
    },
    {
        "name": "解放路", "aliases": [], "city": "西安市", "district": "新城区",
        "lng": 108.965, "lat": 34.262, "level": "道路",
        "roads": ["解放路", "东新街", "尚勤路"], "categories": ["night_snack", "restaurant", "coffee"],
    },
    {
        "name": "西湖文化广场", "aliases": ["浙江自然博物院", "武林广场"],
        "city": "杭州市", "district": "拱墅区", "lng": 120.1634, "lat": 30.2796, "level": "兴趣点",
        "roads": ["中山北路", "环城北路", "西湖文化广场路"],
        "categories": ["mall", "coffee", "attraction", "museum"],
    },
    {
        "name": "橘子洲", "aliases": ["橘子洲头", "湘江中路"],
        "city": "长沙市", "district": "岳麓区", "lng": 112.96, "lat": 28.18, "level": "兴趣点",
        "roads": ["橘洲路", "湘江中路"],
        "categories": ["attraction", "park", "coffee"],
    },
]

# 类目 -> (类型码, 类型描述, 名称库, 标签库, 人均区间, 是否可能连锁)
CATEGORY_META: Dict[str, Dict[str, object]] = {
    "coffee": {
        "typecode": "050500", "type": "餐饮服务;咖啡厅;咖啡厅",
        "names": ["拾光咖啡", "半山咖啡", "鹿野咖啡", "慢岛咖啡", "青柠咖啡", "北纬咖啡", "木棉咖啡", "浮生咖啡", "远山咖啡", "恰好咖啡", "星巴克", "瑞幸咖啡"],
        "tags": ["安静", "可久坐", "有插座", "临窗", "宠物友好", "手冲", "网红"],
        "cost": (28, 68), "chains": {"星巴克", "瑞幸咖啡"}, "rating": (4.1, 4.8),
    },
    "tea": {
        "typecode": "050600", "type": "餐饮服务;茶艺馆;茶艺馆",
        "names": ["一盏茶室", "南山茶舍", "云栖茶馆", "小满茶室", "清和茶馆"],
        "tags": ["安静", "可久坐", "包厢", "传统"], "cost": (40, 120), "chains": set(), "rating": (4.0, 4.7),
    },
    "restaurant": {
        "typecode": "050100", "type": "餐饮服务;中餐厅;中餐厅",
        "names": ["江南小馆", "桥头私房菜", "老巷面馆", "蜀香火锅", "炉边烧烤", "家常小炒", "外婆家", "弄堂菜馆"],
        "tags": ["包厢", "排队", "适合聚餐", "本地口味"], "cost": (45, 180), "chains": {"外婆家"}, "rating": (3.9, 4.7),
    },
    "night_snack": {
        "typecode": "050300", "type": "餐饮服务;快餐厅;快餐厅",
        "names": ["老张夜宵档", "桥下夜市", "深夜食堂", "巷口烧烤摊", "砂锅粥铺", "大排档一号"],
        "tags": ["夜宵", "营业到深夜", "烧烤", "烟火气"], "cost": (25, 90), "chains": set(), "rating": (3.8, 4.6),
    },
    "bar": {
        "typecode": "050400", "type": "餐饮服务;休闲餐饮场所;休闲餐饮场所",
        "names": ["白夜酒吧", "木吉他清吧", "河岸小酒馆", "午后酒馆"],
        "tags": ["音乐", "氛围好", "安静"], "cost": (60, 180), "chains": set(), "rating": (4.0, 4.7),
    },
    "park": {
        "typecode": "110101", "type": "风景名胜;公园广场;公园",
        "names": ["湖畔公园", "城市绿地", "滨河公园", "樱花公园", "市民公园", "湿地公园"],
        "tags": ["草坪", "晒太阳", "适合散步", "免费"], "cost": (0, 30), "chains": set(), "rating": (4.2, 4.8),
    },
    "attraction": {
        "typecode": "110200", "type": "风景名胜;风景名胜;风景名胜",
        "names": ["古城墙景区", "观景平台", "文化创意园", "老街古巷", "艺术街区", "湖心亭"],
        "tags": ["网红", "打卡", "适合拍照", "需预约"], "cost": (0, 80), "chains": set(), "rating": (4.0, 4.8),
    },
    "museum": {
        "typecode": "140200", "type": "科教文化服务;博物馆;博物馆",
        "names": ["城市博物馆", "当代美术馆", "民俗纪念馆", "design展览馆", "自然科技馆"],
        "tags": ["需预约", "免费", "适合亲子", "有讲解"], "cost": (0, 60), "chains": set(), "rating": (4.2, 4.9),
    },
    "library": {
        "typecode": "140300", "type": "科教文化服务;图书馆;图书馆",
        "names": ["城市书房", "24小时自习室", "区图书馆", "静读空间", "共享自习室"],
        "tags": ["安静", "有插座", "可自习", "免费"], "cost": (0, 30), "chains": set(), "rating": (4.1, 4.8),
    },
    "mall": {
        "typecode": "060100", "type": "购物服务;商场;商场",
        "names": ["万象城", "银泰百货", "印象城", "购物中心", "国际广场"],
        "tags": ["空调", "有停车位", "有电梯", "适合亲子"], "cost": (0, 300), "chains": set(), "rating": (4.0, 4.7),
    },
    "supermarket": {
        "typecode": "060400", "type": "购物服务;超级市场;超级市场",
        "names": ["盒马鲜生", "永辉超市", "社区生鲜超市"],
        "tags": ["有停车位", "24小时"], "cost": (20, 200), "chains": {"盒马鲜生", "永辉超市"}, "rating": (3.8, 4.5),
    },
    "kids": {
        "typecode": "080100", "type": "体育休闲服务;游乐场;游乐场",
        "names": ["童趣乐园", "室内亲子乐园", "儿童探索馆"],
        "tags": ["适合儿童", "适合亲子", "有停车位"], "cost": (60, 220), "chains": set(), "rating": (4.0, 4.7),
    },
    "cinema": {
        "typecode": "080601", "type": "体育休闲服务;影剧院;电影院",
        "names": ["星光影城", "百老汇影城", "万象影城"],
        "tags": ["IMAX", "可停车"], "cost": (35, 90), "chains": set(), "rating": (4.0, 4.7),
    },
}

DISTANCES_M = [180, 320, 480, 690, 940, 1560]
OPEN_TIMES = ["09:00-22:00", "10:00-22:30", "07:30-19:00", "11:00-21:30", "24小时", "09:30-24:00", "17:00-02:00"]
OPEN_NOW_BY_HOUR = [True, True, False, True, True, True, True]

BUS_LINES = {
    "杭州市": ["地铁1号线", "地铁2号线", "公交7路", "公交28路"],
    "北京市": ["地铁1号线", "地铁10号线", "公交1路", "公交59路"],
    "上海市": ["地铁2号线", "地铁12号线", "公交20路"],
    "成都市": ["地铁2号线", "地铁3号线", "公交18路"],
    "广州市": ["地铁3号线", "地铁5号线", "公交B7路"],
    "深圳市": ["地铁2号线", "地铁11号线", "公交M123路"],
    "南京市": ["地铁1号线", "地铁2号线", "公交1路"],
    "西安市": ["地铁1号线", "地铁2号线", "公交4路"],
    "长沙市": ["地铁1号线", "地铁2号线", "公交6路"],
}


def stable_hash(text: str) -> int:
    return int(hashlib.sha1((SEED_VERSION + "|" + text).encode("utf-8")).hexdigest()[:8], 16)


def poi_id(city: str, name: str) -> str:
    return "MOCK" + hashlib.sha1((SEED_VERSION + city + name).encode("utf-8")).hexdigest()[:10].upper()


def build() -> Dict[str, object]:
    pois: List[Dict[str, object]] = []
    for place_index, place in enumerate(PLACES):
        city = str(place["city"])
        district = str(place["district"])
        info = CITIES[city]
        for cat_index, cat in enumerate(place["categories"]):
            meta = CATEGORY_META[cat]
            names: List[str] = list(meta["names"])  # type: ignore[arg-type]
            tags_pool: List[str] = list(meta["tags"])  # type: ignore[arg-type]
            cost_lo, cost_hi = meta["cost"]  # type: ignore[misc]
            rating_lo, rating_hi = meta["rating"]  # type: ignore[misc]
            chains = meta["chains"]  # type: ignore[assignment]
            count = min(6, len(DISTANCES_M))
            for i in range(count):
                base = names[(place_index * 2 + i) % len(names)]
                is_chain = base in chains
                name = base + ("(" + district + "店)" if is_chain else "")
                h = stable_hash(city + cat + name + str(i))
                distance = DISTANCES_M[i] + (h % 40)
                bearing = (place_index * 37 + cat_index * 53 + i * 97) % 360
                dlat = distance * 0.000008993 * math.cos(math.radians(bearing))
                dlng = distance * 0.000008993 * math.sin(math.radians(bearing)) / max(
                    0.3, math.cos(math.radians(float(place["lat"])))
                )
                lng = round(float(place["lng"]) + dlng, 6)
                lat = round(float(place["lat"]) + dlat, 6)
                rating = round(rating_hi - (h % 8) * 0.1, 1)
                if rating < rating_lo:
                    rating = rating_lo
                if cat == "coffee" and i == 3:
                    rating = None  # 覆盖「评分缺失」分支
                cost = round(cost_lo + (h % max(1, int(cost_hi - cost_lo))), 1)
                open_time = OPEN_TIMES[h % len(OPEN_TIMES)]
                tags = [tags_pool[(h + j) % len(tags_pool)] for j in range(2)]
                if is_chain:
                    tags.append("连锁")
                if cat == "coffee" and (h % 3 == 0):
                    tags.append("安静")
                tag_text = ",".join(dict.fromkeys(tags))
                road = place["roads"][(h + i) % len(place["roads"])]  # type: ignore[index]
                address = "%s%s%s%d号" % (city, district, road, 10 + (h % 90))
                poi = {
                    "id": poi_id(city, name + str(i)),
                    "name": name,
                    "type": meta["type"],
                    "typecode": meta["typecode"],
                    "address": address,
                    "location": "%.6f,%.6f" % (lng, lat),
                    "distance": str(distance),
                    "tag": tag_text,
                    "category": cat,
                    "chain": bool(is_chain),
                    "biz_ext": {
                        "rating": "" if rating is None else "%.1f" % rating,
                        "cost": "%.2f" % cost,
                        "open_time": open_time,
                        "opentime2": open_time,
                        "parking_type": "地上停车场" if "有停车位" in tags else "",
                    },
                    "photos": [
                        {"title": "", "url": "https://example.invalid/mock/%s-%d.jpg" % (cat, i)}
                    ] if (h % 3) else [],
                    "pname": info["province"],
                    "cityname": city,
                    "adname": district,
                    "level": "兴趣点",
                }
                pois.append(poi)

    return {
        "__meta__": {
            "synthetic": True,
            "note": "按高德 Web 服务公开文档字段结构构造的离线样例，非真实接口返回，不包含任何 Key",
            "generated_by": "tools/build_mock_fixtures.py",
            "schema_version": 1,
            "seed": SEED_VERSION,
        },
        "cities": CITIES,
        "places": PLACES,
        "pois": pois,
        "bus_lines": BUS_LINES,
    }


def main() -> int:
    data = build()
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    print("已生成 %s（%d 个 POI，%d 个地点）" % (OUT, len(data["pois"]), len(PLACES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
