"""recommender 单元测试：打分、过滤、去重、多样性、端到端（mock）。"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import ROOT  # noqa: E402,F401

import amap_client  # noqa: E402
import geo  # noqa: E402
import recommender as rec  # noqa: E402
import text_parser as tp  # noqa: E402

NOON = datetime(2026, 11, 2, 12, 0, 0)


def make_poi(
    name,
    lng,
    lat,
    *,
    typecode="050500",
    rating=4.5,
    cost=45.0,
    open_time="09:00-22:00",
    tags=(),
    poi_id=None,
    distance=None,
    poi_type=None,
):
    return {
        "id": poi_id or name,
        "name": name,
        "typecode": typecode,
        "type": poi_type if poi_type is not None else "餐饮服务;咖啡厅;咖啡厅",
        "rating": rating,
        "cost": cost,
        "open_time": open_time,
        "tags": list(tags),
        "lng": lng,
        "lat": lat,
        "distance_m": distance,
        "photos": [],
        "city": "杭州市",
        "raw": {"biz_ext": {}},
    }


class ScoreTests(unittest.TestCase):
    def test_distance_score_decreases(self):
        scores = [rec.distance_score(d) for d in (0, 200, 500, 1000)]
        self.assertEqual(scores[0], 1.0)
        self.assertTrue(all(a > b for a, b in zip(scores, scores[1:])))

    def test_rating_neutral_when_missing(self):
        self.assertAlmostEqual(rec.rating_score(None), 0.4, places=4)
        self.assertAlmostEqual(rec.rating_score(3.8), 0.4, places=4)
        self.assertAlmostEqual(rec.rating_score(5.0), 1.0, places=4)

    def test_is_open_now(self):
        self.assertTrue(rec.is_open_now("09:00-22:00", NOON))
        self.assertFalse(rec.is_open_now("09:00-22:00", datetime(2026, 11, 2, 23, 0)))
        self.assertTrue(rec.is_open_now("17:00-02:00", datetime(2026, 11, 2, 23, 30)))
        self.assertTrue(rec.is_open_now("24小时", datetime(2026, 11, 2, 3, 0)))
        self.assertIsNone(rec.is_open_now("", NOON))

    def test_category_score(self):
        coffee = make_poi("任意", 120.1, 30.2, typecode="050500")
        self.assertEqual(rec.category_score(coffee, "coffee"), 1.0)
        coffee_by_name = make_poi("拾光咖啡", 120.1, 30.2, typecode="050100")
        self.assertGreaterEqual(rec.category_score(coffee_by_name, "coffee"), 0.9)
        mall = make_poi(
            "万象城", 120.1, 30.2, typecode="060100", poi_type="购物服务;商场;商场"
        )
        self.assertLessEqual(rec.category_score(mall, "coffee"), 0.5)

    def test_chain_detection(self):
        self.assertTrue(rec.is_chain(make_poi("星巴克(湖滨店)", 120.1, 30.2)))
        self.assertFalse(rec.is_chain(make_poi("拾光咖啡", 120.1, 30.2)))

    def test_budget_penalty(self):
        parsed = tp.parse("附近咖啡馆，预算50元")
        cheap = make_poi("A", 120.1, 30.2, cost=40)
        pricey = make_poi("B", 120.1, 30.2, cost=180)
        score_cheap, _ = rec.score_poi(cheap, "coffee", 300, parsed, NOON)
        score_pricey, _ = rec.score_poi(pricey, "coffee", 300, parsed, NOON)
        self.assertGreater(score_cheap, score_pricey)

    def test_score_is_deterministic(self):
        parsed = tp.parse("附近咖啡馆")
        poi = make_poi("A", 120.1, 30.2)
        first = rec.score_poi(poi, "coffee", 300, parsed, NOON)
        second = rec.score_poi(poi, "coffee", 300, parsed, NOON)
        self.assertEqual(first, second)


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.origin = (120.148, 30.2459)

    def test_radius_filter(self):
        parsed = tp.parse("我在西湖附近找咖啡馆")
        inside = make_poi("近", 120.148, 30.2470)
        outside = make_poi("远", 120.148, 30.2600, poi_id="远")
        kept, dropped, notes = rec.filter_pois([inside, outside], parsed, self.origin, now=NOON)
        self.assertEqual([item[0]["name"] for item in kept], ["近"])
        self.assertEqual(dropped[0]["reason"], "超出搜索半径")

    def test_require_open_filter(self):
        parsed = tp.parse("附近营业中的咖啡馆")
        opened = make_poi("开", 120.148, 30.2470, open_time="09:00-22:00")
        closed = make_poi("关", 120.148, 30.2471, open_time="09:00-10:00")
        kept, dropped, _ = rec.filter_pois([opened, closed], parsed, self.origin, now=NOON)
        self.assertEqual([item[0]["name"] for item in kept], ["开"])

    def test_rating_threshold_soft_fallback(self):
        parsed = tp.parse("附近评分4.5以上的咖啡馆")
        low = make_poi("低分", 120.148, 30.2470, rating=4.0)
        kept, dropped, notes = rec.filter_pois([low], parsed, self.origin, now=NOON)
        # 候选不足 3 个时会回补，而不是直接空结果
        self.assertEqual(len(kept), 1)
        self.assertTrue(any("评分门槛" in note for note in notes))


class DiversityTests(unittest.TestCase):
    def _candidate(self, name, category, lng, lat, score):
        return rec.Candidate(
            poi=make_poi(name, lng, lat),
            category=category,
            distance_m=geo.haversine_m((120.148, 30.2459), (lng, lat)),
            score=score,
            parts={},
        )

    def test_max_two_per_category(self):
        candidates = [
            self._candidate("咖啡1", "coffee", 120.148, 30.2470, 0.9),
            self._candidate("咖啡2", "coffee", 120.150, 30.2470, 0.8),
            self._candidate("咖啡3", "coffee", 120.152, 30.2470, 0.7),
            self._candidate("公园1", "park", 120.148, 30.2500, 0.6),
            self._candidate("公园2", "park", 120.150, 30.2500, 0.5),
        ]
        chosen, _ = rec.diversify(candidates, limit=4, max_per_category=2)
        counts = {}
        for item in chosen:
            counts[item.category] = counts.get(item.category, 0) + 1
        self.assertEqual(len(chosen), 4)
        self.assertLessEqual(counts["coffee"], 2)
        self.assertLessEqual(counts["park"], 2)

    def test_single_category_can_fill(self):
        candidates = [
            self._candidate("咖啡%d" % i, "coffee", 120.148 + i * 0.002, 30.2470, 0.9 - i * 0.05)
            for i in range(5)
        ]
        chosen, _ = rec.diversify(candidates, limit=5, max_per_category=5)
        self.assertEqual(len(chosen), 5)

    def test_min_separation(self):
        near = self._candidate("A", "coffee", 120.148, 30.2470, 0.9)
        near2 = self._candidate("B", "coffee", 120.148, 30.2475, 0.8)  # 约 55 米
        far = self._candidate("C", "park", 120.150, 30.2500, 0.7)
        chosen, _ = rec.diversify([near, near2, far], limit=2, max_per_category=2)
        self.assertEqual([item.name for item in chosen], ["A", "C"])

    def test_fill_keeps_enough_candidates(self):
        # 候选实在不够时，宁可填满 3 个也不返回空（并在 notes 里说明）
        near = self._candidate("A", "coffee", 120.148, 30.2470, 0.9)
        near2 = self._candidate("B", "coffee", 120.148, 30.2475, 0.8)
        chosen, _ = rec.diversify([near, near2], limit=3, max_per_category=2)
        self.assertEqual(len(chosen), 2)


class RecommendIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = amap_client.AmapClient(mock=True)
        self.origin = (120.148, 30.2459)

    def tearDown(self):
        self.client.close()

    def test_recommend_returns_ranked_candidates(self):
        parsed = tp.parse("我在西湖附近想找个安静的咖啡馆")
        result = rec.recommend(self.client, parsed, self.origin, top=5, now=NOON)
        self.assertEqual(result["status"], "ok")
        candidates = result["candidates"]
        self.assertGreaterEqual(len(candidates), 3)
        self.assertLessEqual(len(candidates), 5)
        scores = [item.score for item in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for item in candidates:
            self.assertIn("分钟", item.reason)
            self.assertIn("评分", item.reason)
            self.assertIn(item.category, ("coffee", "park", "restaurant"))

    def test_recommend_empty_area(self):
        parsed = tp.parse("我在西湖附近找咖啡馆")
        result = rec.recommend(self.client, parsed, (0.0, 0.0), top=5, now=NOON)
        self.assertEqual(result["status"], "no_result")
        self.assertTrue(result["suggestions"])

    def test_explain_parts_present(self):
        parsed = tp.parse("我在西湖附近想喝咖啡")
        result = rec.recommend(self.client, parsed, self.origin, top=3, now=NOON)
        parts = result["candidates"][0].parts
        for key in ("distance", "rating", "popularity", "category", "open", "final"):
            self.assertIn(key, parts)


if __name__ == "__main__":
    unittest.main()
