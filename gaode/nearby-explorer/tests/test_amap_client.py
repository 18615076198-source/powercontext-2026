"""amap_client 单元测试：错误码映射、重试、缓存、限流、脱敏、mock 模式。"""
from __future__ import annotations

import io
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import FakeClock, ScriptedTransport, load_sample  # noqa: E402

import amap_client as ac  # noqa: E402


class InfoCodeTests(unittest.TestCase):
    def test_core_codes_present(self):
        for code in ["10000", "10001", "10002", "10003", "10004", "10009", "20000", "20802", "20803"]:
            self.assertIn(code, ac.INFO_CODE_TABLE)
            self.assertTrue(ac.INFO_CODE_TABLE[code].message)
            if code != "10000":  # 成功码不需要处置建议
                self.assertTrue(ac.INFO_CODE_TABLE[code].suggestion)

    def test_categories(self):
        self.assertEqual(ac.describe_infocode("10001").category, "auth")
        self.assertEqual(ac.describe_infocode("10003").category, "quota")
        self.assertTrue(ac.describe_infocode("10004").retryable)
        self.assertEqual(ac.describe_infocode("20000").category, "no_result")
        self.assertEqual(ac.describe_infocode("20802").category, "route")

    def test_unknown_code(self):
        info = ac.describe_infocode("99999")
        self.assertEqual(info.code, "99999")
        self.assertIn("99999", info.message)

    def test_mask_key(self):
        self.assertEqual(ac.mask_key(""), "<empty>")
        self.assertEqual(ac.mask_key("short"), "****")
        self.assertEqual(ac.mask_key("abcdefghijklmnop"), "abcd****op")


class CacheTests(unittest.TestCase):
    def test_ttl_expiry(self):
        clock = FakeClock()
        cache = ac.TtlCache(maxsize=2, clock=clock)
        cache.set("k", {"v": 1}, ttl=10)
        self.assertEqual(cache.get("k"), {"v": 1})
        clock.advance(11)
        self.assertIsNone(cache.get("k"))

    def test_lru_eviction(self):
        cache = ac.TtlCache(maxsize=2)
        cache.set("a", 1, 100)
        cache.set("b", 2, 100)
        cache.set("c", 3, 100)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("c"), 3)

    def test_client_cache_hit(self):
        transport = ScriptedTransport([load_sample("geocode_success.json")])
        client = ac.AmapClient(key="testkey123456", mock=False, transport=transport, sleep=lambda s: None)
        first = client.geocode("西湖")
        second = client.geocode("西湖")
        self.assertEqual(first, second)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(client.cache_stats()["hits"], 1)


class RetryTests(unittest.TestCase):
    def test_retry_on_rate_limit(self):
        errors = load_sample("errors.json")
        transport = ScriptedTransport([errors["10004"], load_sample("geocode_success.json")])
        client = ac.AmapClient(
            key="testkey123456", mock=False, transport=transport, sleep=lambda s: None, qps=100
        )
        result = client.geocode("西湖")
        self.assertEqual(len(result), 1)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(client.stats["retries"], 1)

    def test_no_retry_on_auth_error(self):
        errors = load_sample("errors.json")
        transport = ScriptedTransport([errors["10001"]])
        client = ac.AmapClient(key="testkey123456", mock=False, transport=transport, sleep=lambda s: None, qps=100)
        with self.assertRaises(ac.AmapError) as ctx:
            client.geocode("西湖")
        self.assertEqual(ctx.exception.code, "10001")
        self.assertEqual(ctx.exception.category, "auth")
        self.assertEqual(len(transport.calls), 1)

    def test_network_error_is_retryable(self):
        transport = ScriptedTransport([ac.AmapError("NET_TIMEOUT"), load_sample("geocode_success.json")])
        client = ac.AmapClient(key="testkey123456", mock=False, transport=transport, sleep=lambda s: None, qps=100)
        result = client.geocode("西湖")
        self.assertEqual(len(result), 1)
        self.assertEqual(len(transport.calls), 2)

    def test_no_result_does_not_raise_for_place(self):
        errors = load_sample("errors.json")
        transport = ScriptedTransport([errors["20000"]])
        client = ac.AmapClient(key="testkey123456", mock=False, transport=transport, sleep=lambda s: None, qps=100)
        count, pois = client.place_around(120.1, 30.2)
        self.assertEqual(count, 0)
        self.assertEqual(pois, [])


class BudgetAndConfigTests(unittest.TestCase):
    def test_budget_exceeded(self):
        transport = ScriptedTransport([load_sample("geocode_success.json")])
        client = ac.AmapClient(key="testkey123456", mock=False, transport=transport, qps=100)
        deadline = ac.Deadline(0.0)
        with self.assertRaises(ac.BudgetExceeded):
            client.geocode("西湖", deadline=deadline)

    def test_missing_key_raises(self):
        old = os.environ.pop("AMAP_KEY", None)
        try:
            with self.assertRaises(ac.AmapError) as ctx:
                ac.AmapClient(mock=False)
            self.assertEqual(ctx.exception.code, "NO_KEY")
            self.assertEqual(ctx.exception.category, "config")
        finally:
            if old is not None:
                os.environ["AMAP_KEY"] = old

    def test_log_redaction(self):
        transport = ScriptedTransport([load_sample("geocode_success.json")])
        client = ac.AmapClient(key="SECRETKEY1234567890", mock=False, transport=transport, qps=100)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        previous_level = ac.LOGGER.level
        ac.LOGGER.setLevel(logging.INFO)
        ac.LOGGER.addHandler(handler)
        try:
            client.geocode("西湖")
        finally:
            ac.LOGGER.removeHandler(handler)
            ac.LOGGER.setLevel(previous_level)
        output = stream.getvalue()
        self.assertNotIn("SECRETKEY1234567890", output)
        self.assertIn("SECR****90", output)


class LoggingConfigTests(unittest.TestCase):
    def test_configure_logging_emits_and_masks(self):
        stream = io.StringIO()
        previous = list(ac.LOGGER.handlers)
        for handler in previous:
            ac.LOGGER.removeHandler(handler)
        try:
            ac.configure_logging(logging.INFO, stream=stream)
            transport = ScriptedTransport([load_sample("geocode_success.json")])
            client = ac.AmapClient(key="abcdefghijklmnop", mock=False, transport=transport, qps=100)
            client.geocode("西湖")
            output = stream.getvalue()
            self.assertIn("api=geocode", output)
            self.assertIn("infocode=10000", output)
            self.assertNotIn("abcdefghijklmnop", output)
            self.assertIn("abcd****op", output)
        finally:
            for handler in list(ac.LOGGER.handlers):
                ac.LOGGER.removeHandler(handler)
            for handler in previous:
                ac.LOGGER.addHandler(handler)


class NormalizeTests(unittest.TestCase):
    def test_poi_with_missing_rating(self):
        payload = load_sample("place_around_coffee.json")
        pois = [ac.normalize_poi(item) for item in payload["pois"]]
        self.assertEqual(pois[0]["rating"], 4.6)
        self.assertIsNone(pois[2]["rating"])
        self.assertEqual(pois[0]["distance_m"], 260.0)
        self.assertIn("安静", pois[0]["tags"])
        self.assertEqual(pois[0]["city"], "杭州市")

    def test_geocode_normalize(self):
        payload = load_sample("geocode_success.json")
        item = ac.normalize_geocode(payload["geocodes"][0])
        self.assertAlmostEqual(item["lng"], 120.14798, places=4)
        self.assertEqual(item["city"], "杭州市")


class MockModeTests(unittest.TestCase):
    def setUp(self):
        self.client = ac.AmapClient(mock=True)

    def tearDown(self):
        self.client.close()

    def test_geocode(self):
        items = self.client.geocode("西湖", city="杭州市")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["city"], "杭州市")

    def test_ambiguous_place(self):
        items = self.client.geocode("解放路")
        self.assertEqual(len(items), 3)
        self.assertEqual({item["city"] for item in items}, {"杭州市", "成都市", "西安市"})

    def test_place_around(self):
        count, pois = self.client.place_around(120.148, 30.2459, radius=1000, types="050500")
        self.assertGreaterEqual(count, 3)
        self.assertGreaterEqual(len(pois), 3)
        self.assertTrue(all(poi["distance_m"] <= 1000 for poi in pois))

    def test_routes(self):
        origin = "120.148000,30.245900"
        destination = "120.148000,30.247708"
        walking = self.client.walking(origin, destination)
        self.assertGreater(int(walking["route"]["paths"][0]["distance"]), 0)
        driving = self.client.driving(origin, destination)
        self.assertGreater(int(driving["route"]["paths"][0]["duration"]), 0)
        transit = self.client.transit(origin, "120.161000,30.277000", city="杭州市")
        self.assertTrue(transit["route"]["transits"][0]["segments"])
        bicycling = self.client.bicycling(origin, destination)
        self.assertGreater(int(bicycling["data"]["paths"][0]["distance"]), 0)
        distance = self.client.distance(origin, destination)
        self.assertGreater(int(distance["results"][0]["distance"]), 0)

    def test_no_result_place(self):
        count, pois = self.client.place_around(0.0, 0.0, radius=100, types="050500")
        self.assertEqual(count, 0)
        self.assertEqual(pois, [])


if __name__ == "__main__":
    unittest.main()
