"""planner 单元测试：四种方式解析、兜底、URI、并行规划。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import ScriptedTransport, load_sample  # noqa: E402

import amap_client  # noqa: E402
import geo  # noqa: E402
import planner  # noqa: E402
import recommender  # noqa: E402
import text_parser as tp  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_walking(self):
        plan = planner.parse_walking(load_sample("walking.json"))
        self.assertEqual(plan.mode, "walking")
        self.assertEqual(plan.distance_m, 320.0)
        self.assertEqual(plan.to_dict()["duration_minutes"], 5)
        self.assertIn("步行", plan.summary)

    def test_driving(self):
        plan = planner.parse_driving(load_sample("driving.json"))
        self.assertEqual(plan.mode, "driving")
        self.assertIn("驾车", plan.summary)
        self.assertIn("北山街", plan.summary)
        self.assertEqual(plan.detail["roads"][:2], ["北山街", "环城西路"])

    def test_transit(self):
        plan = planner.parse_transit(load_sample("transit.json"))
        self.assertEqual(plan.mode, "transit")
        self.assertEqual(plan.detail["lines"], ["地铁1号线"])
        self.assertEqual(plan.detail["transfers"], 0)
        self.assertIn("换乘 0 次", plan.summary)
        self.assertIn("地铁1号线", plan.summary)

    def test_bicycling(self):
        plan = planner.parse_bicycling(load_sample("bicycling.json"))
        self.assertEqual(plan.mode, "bicycling")
        self.assertEqual(plan.distance_m, 1700.0)

    def test_invalid_payload_raises(self):
        with self.assertRaises(ValueError):
            planner.parse_walking({"status": "1"})


class FallbackTests(unittest.TestCase):
    def test_estimate_marks_approximate(self):
        plan = planner.estimate_plan("walking", 1000)
        self.assertTrue(plan.estimated)
        self.assertIn("约", plan.summary)
        self.assertIsNotNone(plan.distance_m)

    def test_route_failure_uses_distance_api(self):
        errors = load_sample("errors.json")
        distance_payload = load_sample("distance.json")

        def handler(path, params):
            if "direction" in path:
                return errors["20803"]
            return distance_payload

        client = amap_client.AmapClient(
            key="testkey123456", mock=False, transport=ScriptedTransport([distance_payload]),
            sleep=lambda s: None, qps=100,
        )
        client.transport = amap_client.CallableTransport(handler)
        candidate = recommender.Candidate(
            poi={"id": "x", "name": "测试点", "lng": 120.161, "lat": 30.256},
            category="coffee",
            distance_m=1200,
            score=0.5,
            parts={},
        )
        plan = planner._plan_one(client, "walking", (120.148, 30.2459), candidate, "杭州市", None)
        self.assertTrue(plan.estimated)
        self.assertEqual(plan.detail.get("fallback"), "distance_api")
        self.assertEqual(plan.distance_m, 6400.0)


class ModeTests(unittest.TestCase):
    def _candidate(self, distance):
        return recommender.Candidate(
            poi={"id": "x", "name": "点", "lng": 120.15, "lat": 30.25},
            category="coffee",
            distance_m=distance,
            score=0.5,
            parts={},
        )

    def test_two_modes_max(self):
        parsed = tp.parse("在西湖附近找咖啡馆")
        modes = planner.desired_modes(parsed, self._candidate(3000))
        self.assertLessEqual(len(modes), 2)
        self.assertEqual(modes[0], "walking")
        self.assertIn("transit", modes)

    def test_short_walk_gets_bike_alternative(self):
        parsed = tp.parse("在西湖附近找咖啡馆")
        modes = planner.desired_modes(parsed, self._candidate(1200))
        self.assertEqual(modes, ["walking", "bicycling"])

    def test_driving_short_distance_gets_walk(self):
        parsed = tp.parse("开车去附近的咖啡")
        modes = planner.desired_modes(parsed, self._candidate(800))
        self.assertEqual(modes, ["driving", "walking"])


class UriTests(unittest.TestCase):
    def test_marker_uri(self):
        uri = planner.marker_uri(120.148, 30.2459, "拾光咖啡")
        self.assertTrue(uri.startswith("https://uri.amap.com/marker?"))
        self.assertIn("position=120.148000,30.245900", uri)
        self.assertIn("%E6%8B%BE%E5%85%89", uri)

    def test_navigation_uri_modes(self):
        walk = planner.navigation_uri((120.1, 30.2), (120.2, 30.3), "A", "walking")
        ride = planner.navigation_uri((120.1, 30.2), (120.2, 30.3), "A", "bicycling")
        self.assertIn("mode=walk", walk)
        self.assertIn("mode=ride", ride)
        self.assertIn("coordinate=gaode", walk)


class PlanRoutesIntegrationTests(unittest.TestCase):
    def test_routes_attached_to_candidates(self):
        client = amap_client.AmapClient(mock=True)
        try:
            parsed = tp.parse("我在西湖附近找咖啡馆")
            origin = (120.148, 30.2459)
            result = recommender.recommend(client, parsed, origin, top=3)
            routes, diagnostics = planner.plan_routes(
                client, parsed, origin, result["candidates"], city="杭州市"
            )
            self.assertEqual(len(routes), 3)
            for candidate in result["candidates"]:
                plans = routes[candidate.poi_id]
                self.assertGreaterEqual(len(plans), 1)
                self.assertLessEqual(len(plans), 2)
                self.assertTrue(plans[0]["summary"])
                self.assertFalse(plans[0]["estimated"])
            self.assertEqual(diagnostics, [])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
