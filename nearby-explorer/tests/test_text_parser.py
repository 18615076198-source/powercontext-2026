"""text_parser 的确定性单元测试（不访问网络）。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import ROOT  # noqa: E402,F401

import text_parser as tp  # noqa: E402


class LocationTests(unittest.TestCase):
    def test_place_with_nearby(self):
        parsed = tp.parse("我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到")
        self.assertEqual(parsed.location_text, "西湖")
        self.assertEqual(parsed.location_kind, "absolute")
        self.assertEqual(parsed.categories, ["coffee"])
        self.assertEqual(parsed.transport, "walking")
        self.assertEqual(parsed.duration_minutes, 120)
        self.assertTrue(parsed.quiet)
        self.assertEqual(parsed.radius_m, 1000)

    def test_place_at_sentence_end(self):
        parsed = tp.parse("附近有什么安静的咖啡馆，我在五道口")
        self.assertEqual(parsed.location_text, "五道口")
        self.assertTrue(parsed.quiet)

    def test_relative_with_distance(self):
        parsed = tp.parse("离我1公里内找个公园")
        self.assertEqual(parsed.location_kind, "relative")
        self.assertEqual(parsed.radius_m, 1000)
        self.assertEqual(parsed.max_distance_m, 1000)
        self.assertEqual(parsed.categories, ["park"])

    def test_relative_without_place_needs_clarification(self):
        parsed = tp.parse("我附近有什么好吃的")
        self.assertEqual(parsed.location_kind, "relative")
        self.assertTrue(parsed.need_clarification)
        self.assertTrue(parsed.questions)

    def test_missing_location_uses_default_city(self):
        parsed = tp.parse("想找个咖啡馆", default_city="杭州市")
        self.assertEqual(parsed.location_kind, "city")
        self.assertEqual(parsed.city_hint, "杭州市")
        self.assertFalse(parsed.need_clarification)

    def test_city_detected_from_prefix(self):
        parsed = tp.parse("北京国贸附近评分4.5以上的咖啡馆")
        self.assertEqual(parsed.city_hint, "北京市")
        self.assertEqual(parsed.city_source, "explicit")
        self.assertEqual(parsed.min_rating, 4.5)

    def test_street_name_is_not_city(self):
        parsed = tp.parse("我在南京西路附近想喝杯咖啡")
        self.assertIsNone(parsed.city_hint)
        self.assertEqual(parsed.location_text, "南京西路")

    def test_from_departure(self):
        parsed = tp.parse("从天安门出发去国家博物馆，坐地铁")
        self.assertEqual(parsed.location_text, "天安门")
        self.assertEqual(parsed.transport, "transit")
        self.assertEqual(parsed.categories, ["museum"])


class ConstraintTests(unittest.TestCase):
    def test_budget(self):
        parsed = tp.parse("我在春熙路附近想吃火锅，人均100以内")
        self.assertEqual(parsed.budget_per_person, 100.0)
        self.assertEqual(parsed.focus_keywords[0], "火锅")

    def test_radius_clamped(self):
        parsed = tp.parse("离我8公里内找个商场")
        self.assertEqual(parsed.radius_m, 3000)

    def test_radius_1500(self):
        parsed = tp.parse("我在国贸附近1.5公里内找咖啡馆")
        self.assertEqual(parsed.radius_m, 1500)

    def test_transport_variants(self):
        self.assertEqual(tp.parse("骑车去附近的咖啡").transport, "bicycling")
        self.assertEqual(tp.parse("开车去附近的商场").transport, "driving")
        self.assertEqual(tp.parse("坐地铁去附近的公园").transport, "transit")
        self.assertEqual(tp.parse("附近的公园").transport, "walking")

    def test_open_and_chain_and_parking(self):
        parsed = tp.parse("我在国贸附近找个营业中、不要连锁、能停车的咖啡馆")
        self.assertTrue(parsed.require_open)
        self.assertTrue(parsed.avoid_chain)
        self.assertTrue(parsed.parking)

    def test_duration_variants(self):
        self.assertEqual(tp.parse("在西湖坐两小时").duration_minutes, 120)
        self.assertEqual(tp.parse("在西湖待半个小时").duration_minutes, 30)
        self.assertEqual(tp.parse("在西湖玩一个半小时").duration_minutes, 90)
        self.assertEqual(tp.parse("在西湖逛逛 45 分钟").duration_minutes, 45)

    def test_multi_intent(self):
        parsed = tp.parse("国贸附近有什么好玩的")
        self.assertEqual(parsed.intent, "explore")
        self.assertIn("attraction", parsed.categories)
        self.assertGreaterEqual(len(parsed.categories), 3)


class RobustnessTests(unittest.TestCase):
    def test_empty_input(self):
        parsed = tp.parse("")
        self.assertTrue(parsed.need_clarification)

    def test_weird_input_does_not_raise(self):
        for text in ["？？？", "a" * 500, "我在附近", "12345", "西湖"]:
            parsed = tp.parse(text)
            self.assertIsNotNone(parsed.to_dict())

    def test_deterministic(self):
        text = "我在西湖附近，下午想找个安静的咖啡馆坐两小时，最好步行能到"
        self.assertEqual(tp.parse(text).to_dict(), tp.parse(text).to_dict())

    def test_describe(self):
        parsed = tp.parse("我在西湖附近想喝咖啡")
        self.assertIn("西湖", tp.describe(parsed))
        self.assertIn("咖啡馆", tp.describe(parsed))


if __name__ == "__main__":
    unittest.main()
