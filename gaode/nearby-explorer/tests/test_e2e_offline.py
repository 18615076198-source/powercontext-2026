"""离线端到端测试：10 条中文语句 + 关键异常场景。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import ROOT, ScriptedTransport, load_sample  # noqa: E402

import amap_client  # noqa: E402
import nearby_explorer  # noqa: E402


def load_cases():
    with open(os.path.join(ROOT, "tests", "e2e_cases.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)["cases"]


class E2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = amap_client.AmapClient(mock=True)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def run_case(self, case):
        origin = case.get("origin")
        return nearby_explorer.explore(
            case["query"],
            top=5,
            client=self.client,
            default_city=case.get("default_city"),
            origin_hint=tuple(origin) if origin else None,
        )

    def test_all_cases_return_three_or_more_with_routes(self):
        for case in load_cases():
            with self.subTest(case=case["id"]):
                result = self.run_case(case)
                self.assertEqual(result["status"], "ok", result.get("message"))
                candidates = result["candidates"]
                self.assertGreaterEqual(len(candidates), 3)
                self.assertLessEqual(len(candidates), 5)
                for candidate in candidates:
                    self.assertTrue(candidate["reason"])
                    self.assertTrue(candidate["routes"], "缺少交通方案：%s" % candidate["name"])
                    for route in candidate["routes"]:
                        self.assertTrue(route["summary"])
                    self.assertTrue(candidate["links"]["marker"])
                    self.assertTrue(candidate["links"]["navigation"])
                    self.assertIn("src=nearby-explorer", candidate["links"]["marker"])

    def test_manual_origin_transit_uses_regeo_city(self):
        result = nearby_explorer.explore(
            "离我500米内找个咖啡，坐地铁",
            client=self.client,
            origin_hint=(120.148, 30.2459),
        )
        self.assertEqual(result["status"], "ok")
        first = result["candidates"][0]
        self.assertEqual(first["routes"][0]["mode"], "transit")
        self.assertTrue(first["routes"][0]["summary"])

    def test_no_result_for_unknown_place(self):
        result = nearby_explorer.explore("火星基地附近找个咖啡", client=self.client)
        self.assertEqual(result["status"], "no_result")
        self.assertGreaterEqual(len(result["suggestions"]), 2)

    def test_need_location_when_relative_without_origin(self):
        result = nearby_explorer.explore("我附近有什么好吃的", client=self.client)
        self.assertEqual(result["status"], "need_location")
        self.assertTrue(result["questions"])

    def test_missing_key_returns_error(self):
        with mock.patch.dict(os.environ, {"AMAP_KEY": ""}, clear=False):
            result = nearby_explorer.explore("我在西湖附近想喝咖啡", mock=False)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["infocode"], "NO_KEY")
        self.assertTrue(result["suggestions"])

    def test_quota_exceeded_returns_error(self):
        errors = load_sample("errors.json")
        client = amap_client.AmapClient(
            key="testkey123456", mock=False,
            transport=ScriptedTransport([errors["10003"]]),
            sleep=lambda s: None, qps=100,
        )
        result = nearby_explorer.explore("我在西湖附近想喝咖啡", client=client)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["infocode"], "10003")
        joined = " ".join(result["suggestions"])
        self.assertTrue("配额" in joined or "明日" in joined)

    def test_json_serializable(self):
        result = self.run_case(load_cases()[0])
        text = json.dumps(result, ensure_ascii=False)
        self.assertIn("西湖", text)


if __name__ == "__main__":
    unittest.main()
