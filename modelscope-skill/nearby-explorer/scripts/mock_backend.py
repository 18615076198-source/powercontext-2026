"""离线 mock 后端：读取 fixtures/mock_world.json，按高德 Web 服务的返回结构作答。

用途：AMAP_MOCK=1 时，没有网络 / 没有 Key 也能跑通完整链路和全部测试。
数据是合成的（见 fixtures/mock_world.json 的 __meta__），不是真实接口录制。

实现的是高德文档里与本 Skill 相关的接口子集：
    /v3/geocode/geo, /v3/geocode/regeo, /v3/assistant/inputtips,
    /v3/place/around, /v3/place/text,
    /v3/direction/walking, /v4/direction/bicycling, /v3/direction/driving,
    /v3/direction/transit/integrated, /v3/distance, /v3/weather/weatherInfo
"""
from __future__ import annotations

import json
import os
import threading
import time
import zlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__:
    from . import geo
else:
    import geo  # type: ignore

FIXTURE_NAME = "mock_world.json"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_world_path() -> str:
    override = os.environ.get("AMAP_MOCK_WORLD")
    if override:
        return override
    return os.path.join(_repo_root(), "fixtures", FIXTURE_NAME)


def _ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    base = {"status": "1", "info": "OK", "infocode": "10000"}
    base.update(payload)
    return base


def _stable_hash(text: str) -> int:
    """跨进程稳定的哈希（不能用内置 hash，它受 PYTHONHASHSEED 影响）。"""
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


class MockBackend:
    """线程安全的离线后端：同一请求永远返回同一结果。"""

    def __init__(self, world_path: Optional[str] = None, recorded_dir: Optional[str] = None) -> None:
        path = world_path or default_world_path()
        with open(path, "r", encoding="utf-8") as handle:
            self.world = json.load(handle)
        self.path = path
        self.recorded_dir = recorded_dir or os.path.join(_repo_root(), "fixtures", "recorded")
        self.recorded: List[Dict[str, Any]] = []
        self._load_recordings()
        self.places: List[Dict[str, Any]] = list(self.world.get("places") or [])
        self.pois: List[Dict[str, Any]] = list(self.world.get("pois") or [])
        self.cities: Dict[str, Dict[str, Any]] = dict(self.world.get("cities") or {})
        self.bus_lines: Dict[str, List[str]] = dict(self.world.get("bus_lines") or {})
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._by_city: Dict[str, List[Dict[str, Any]]] = {}
        for poi in self.pois:
            self._by_city.setdefault(poi.get("cityname", ""), []).append(poi)

    # -- 真实录制回放（tools/record_fixtures.py 产出） --------------------
    def _load_recordings(self) -> None:
        index_path = os.path.join(self.recorded_dir, "index.json")
        if not os.path.exists(index_path):
            return
        try:
            with open(index_path, "r", encoding="utf-8") as handle:
                index = json.load(handle)
            entries = index.get("entries") or []
            for entry in entries:
                file_path = os.path.join(self.recorded_dir, entry.get("file") or "")
                if not entry.get("file") or not os.path.exists(file_path):
                    continue
                self.recorded.append(
                    {
                        "path": entry.get("path") or "",
                        "params": entry.get("params") or {},
                        "file": file_path,
                    }
                )
        except (OSError, ValueError):
            self.recorded = []

    def _replay(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """命中真实录制数据时优先返回录制内容（比合成世界更可信）。"""
        if not self.recorded:
            return None
        clean = {k: str(v) for k, v in params.items() if k != "key"}
        best: Optional[Dict[str, Any]] = None
        best_score = -1
        for entry in self.recorded:
            if entry["path"] != path:
                continue
            match = 0
            for key, value in (entry["params"] or {}).items():
                if key == "key":
                    continue
                if clean.get(key) != str(value):
                    break
                match += 1
            else:
                if match > best_score:
                    best_score = match
                    best = entry
        if best is None:
            return None
        try:
            with open(best["file"], "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    # -- 工具 -------------------------------------------------------------
    def _log(self, path: str, params: Dict[str, Any]) -> None:
        with self._lock:
            self.calls.append({"path": path, "params": dict(params), "time": time.time()})

    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)

    @staticmethod
    def _type_prefix(code: str) -> str:
        stripped = code.rstrip("0")
        return stripped or code

    def _nearest_city(self, lng: float, lat: float) -> Optional[str]:
        best = None
        best_distance = float("inf")
        for city, info in self.cities.items():
            distance = geo.haversine_m((lng, lat), (float(info["lng"]), float(info["lat"])))
            if distance < best_distance:
                best_distance = distance
                best = city
        return best

    @staticmethod
    def _location_of(poi: Dict[str, Any]) -> Tuple[float, float]:
        parsed = geo.parse_lnglat(poi.get("location"))
        if parsed is None:
            return 0.0, 0.0
        return parsed

    # -- 地理编码 ---------------------------------------------------------
    def _match_places(self, address: str, city: Optional[str]) -> List[Dict[str, Any]]:
        query = (address or "").strip()
        for suffix in ("特别行政区",):
            query = query.replace(suffix, "")
        if not query:
            return []
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for place in self.places:
            names = [str(place["name"])] + [str(a) for a in place.get("aliases") or []]
            best = 0
            for name in names:
                if query == name:
                    best = max(best, 100 + len(name))
                elif query.startswith(name) and len(query) > len(name):
                    best = max(best, 80 + len(name))
                elif name in query:
                    best = max(best, 70 + len(name))
                elif query in name:
                    best = max(best, 60 + len(query))
            if best > 0:
                scored.append((best, place))
        if not scored:
            return []
        if city:
            filtered = [item for item in scored if item[1].get("city") == city]
            if filtered:
                scored = filtered
        scored.sort(key=lambda item: (-item[0], str(item[1].get("city"))))
        # 只保留得分最高的一档：精确命中"西湖"时不要再带出"西湖文化广场"
        best_score = scored[0][0]
        top = [item for item in scored if item[0] >= best_score - 5]
        return [place for _, place in top[:3]]

    def geocode(self, params: Dict[str, Any]) -> Dict[str, Any]:
        address = str(params.get("address") or "")
        city = params.get("city") or None
        matches = self._match_places(address, city)
        geocodes = []
        for place in matches:
            city_info = self.cities.get(str(place["city"]), {})
            geocodes.append(
                {
                    "formatted_address": "%s%s%s" % (place["city"], place["district"], place["name"]),
                    "country": "中国",
                    "province": city_info.get("province", ""),
                    "citycode": city_info.get("citycode", ""),
                    "city": place["city"],
                    "district": place["district"],
                    "adcode": city_info.get("adcode", ""),
                    "location": "%.6f,%.6f" % (float(place["lng"]), float(place["lat"])),
                    "level": place.get("level", "兴趣点"),
                    "raw_name": place["name"],
                }
            )
        # 直接输入城市名：返回城市中心
        if not geocodes:
            for city_name, info in self.cities.items():
                if address in (city_name, city_name.rstrip("市")):
                    geocodes.append(
                        {
                            "formatted_address": city_name,
                            "country": "中国",
                            "province": info.get("province", ""),
                            "citycode": info.get("citycode", ""),
                            "city": city_name,
                            "district": "",
                            "adcode": info.get("adcode", ""),
                            "location": "%.6f,%.6f" % (float(info["lng"]), float(info["lat"])),
                            "level": "市",
                        }
                    )
                    break
        if not geocodes:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20000", "count": "0", "geocodes": []}
        return _ok({"count": str(len(geocodes)), "geocodes": geocodes})

    def regeo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        lnglat = geo.parse_lnglat(params.get("location"))
        if lnglat is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        city = self._nearest_city(*lnglat) or ""
        info = self.cities.get(city, {})
        nearest = min(
            self.places,
            key=lambda p: geo.haversine_m(lnglat, (float(p["lng"]), float(p["lat"]))),
        )
        return _ok(
            {
                "regeocode": {
                    "formatted_address": "%s%s%s" % (city, nearest["district"], nearest["name"]),
                    "addressComponent": {
                        "province": info.get("province", ""),
                        "city": city,
                        "district": nearest["district"],
                        "township": "",
                        "adcode": info.get("adcode", ""),
                        "citycode": info.get("citycode", ""),
                        "distance": "%.0f" % geo.haversine_m(lnglat, (float(nearest["lng"]), float(nearest["lat"]))),
                    },
                }
            }
        )

    def inputtips(self, params: Dict[str, Any]) -> Dict[str, Any]:
        keywords = str(params.get("keywords") or "").strip()
        city = params.get("city") or None
        if not keywords:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001", "tips": []}
        tips: List[Dict[str, Any]] = []
        for place in self.places:
            if city and place.get("city") != city:
                continue
            names = [str(place["name"])] + [str(a) for a in place.get("aliases") or []]
            if any(keywords in name for name in names):
                info = self.cities.get(str(place["city"]), {})
                tips.append(
                    {
                        "id": "MOCKTIP" + str(_stable_hash(str(place["name"]) + str(place["city"])) % 10 ** 8),
                        "name": place["name"],
                        "district": "%s%s" % (place["city"], place["district"]),
                        "adcode": info.get("adcode", ""),
                        "location": "%.6f,%.6f" % (float(place["lng"]), float(place["lat"])),
                        "address": "",
                        "typecode": "110000",
                        "citycode": info.get("citycode", ""),
                    }
                )
        if not tips:
            for poi in self.pois:
                if city and poi.get("cityname") != city:
                    continue
                if keywords in poi["name"]:
                    tips.append(
                        {
                            "id": poi["id"],
                            "name": poi["name"],
                            "district": "%s%s" % (poi["cityname"], poi["adname"]),
                            "adcode": "",
                            "location": poi["location"],
                            "address": poi.get("address", ""),
                            "typecode": poi["typecode"],
                            "citycode": "",
                        }
                    )
                if len(tips) >= 10:
                    break
        if not tips:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20000", "tips": []}
        return _ok({"count": str(len(tips)), "tips": tips})

    # -- 周边搜索 ---------------------------------------------------------
    def place_around(self, params: Dict[str, Any]) -> Dict[str, Any]:
        lnglat = geo.parse_lnglat(params.get("location"))
        if lnglat is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        radius = float(params.get("radius") or 1000)
        types = [t for t in str(params.get("types") or "").split("|") if t]
        keywords = [k for k in str(params.get("keywords") or "").split("|") if k]
        offset = int(params.get("offset") or 25)
        page = int(params.get("page") or 1)
        sortrule = str(params.get("sortrule") or "weight")

        matched: List[Tuple[float, Dict[str, Any]]] = []
        for poi in self.pois:
            location = self._location_of(poi)
            distance = geo.haversine_m(lnglat, location)
            if distance > radius:
                continue
            if types and not any(poi.get("typecode", "").startswith(self._type_prefix(t)) for t in types):
                continue
            if keywords:
                haystack = "%s %s %s %s" % (poi.get("name", ""), poi.get("tag", ""), poi.get("type", ""), poi.get("address", ""))
                if not any(keyword in haystack for keyword in keywords):
                    continue
            matched.append((distance, poi))

        if sortrule == "distance":
            matched.sort(key=lambda item: item[0])
        else:
            def weight(item: Tuple[float, Dict[str, Any]]) -> float:
                biz = item[1].get("biz_ext") or {}
                try:
                    rating = float(biz.get("rating") or 0)
                except (TypeError, ValueError):
                    rating = 0.0
                return -(rating * 100 - item[0] / 20.0)

            matched.sort(key=weight)

        start = max(0, (page - 1) * offset)
        page_items = matched[start: start + offset]
        pois = []
        for distance, poi in page_items:
            item = dict(poi)
            item["distance"] = str(int(round(distance)))
            pois.append(item)
        return _ok({"count": str(len(matched)), "pois": pois})

    def place_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        keywords = str(params.get("keywords") or "").strip()
        city = params.get("city") or None
        if not keywords:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001", "pois": []}
        matched = []
        for poi in self.pois:
            if city and poi.get("cityname") != city:
                continue
            if keywords in poi.get("name", ""):
                matched.append(poi)
        offset = int(params.get("offset") or 25)
        page = int(params.get("page") or 1)
        start = max(0, (page - 1) * offset)
        return _ok({"count": str(len(matched)), "pois": [dict(p) for p in matched[start:start + offset]]})

    # -- 路径规划 ---------------------------------------------------------
    @staticmethod
    def _road(city: Optional[str], seed: str) -> str:
        roads = ["人民路", "中山路", "建设大道", "环城北路", "解放路", "学院路"]
        index = _stable_hash((seed + (city or ""))[:32]) % len(roads)
        return roads[index]

    def _coords(self, params: Dict[str, Any]) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        origin = geo.parse_lnglat(params.get("origin"))
        destination = geo.parse_lnglat(params.get("destination"))
        if origin is None or destination is None:
            return None
        return origin, destination

    def walking(self, params: Dict[str, Any]) -> Dict[str, Any]:
        coords = self._coords(params)
        if coords is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        origin, destination = coords
        straight = geo.haversine_m(origin, destination)
        if straight < 1:
            return {"status": "0", "info": "TOO_CLOSE", "infocode": "20802"}
        distance = max(30.0, straight * 1.25)
        duration = distance / 1.25
        city = self._nearest_city(*origin)
        road = self._road(city, "%s%s" % (origin[0], destination[1]))
        steps = [
            {
                "instruction": "沿%s步行%d米" % (road, int(distance * 0.5)),
                "orientation": "东",
                "road": road,
                "distance": str(int(distance * 0.5)),
                "duration": str(int(duration * 0.5)),
                "polyline": "",
            },
            {
                "instruction": "继续步行%d米到达目的地" % int(distance * 0.5),
                "orientation": "北",
                "road": road,
                "distance": str(int(distance * 0.5)),
                "duration": str(int(duration * 0.5)),
                "polyline": "",
            },
        ]
        return _ok(
            {
                "route": {
                    "origin": params.get("origin"),
                    "destination": params.get("destination"),
                    "paths": [
                        {
                            "distance": str(int(round(distance))),
                            "duration": str(int(round(duration))),
                            "steps": steps,
                        }
                    ],
                }
            }
        )

    def driving(self, params: Dict[str, Any]) -> Dict[str, Any]:
        coords = self._coords(params)
        if coords is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        origin, destination = coords
        straight = geo.haversine_m(origin, destination)
        if straight < 1:
            return {"status": "0", "info": "TOO_CLOSE", "infocode": "20802"}
        distance = straight * 1.35
        duration = distance / 8.5 + 120
        city = self._nearest_city(*origin)
        road = self._road(city, "%s%s" % (destination[0], origin[1]))
        steps = [
            {
                "instruction": "沿%s向东南行驶%d米" % (road, int(distance * 0.6)),
                "orientation": "东南",
                "road": road,
                "distance": str(int(distance * 0.6)),
                "duration": str(int(duration * 0.6)),
                "toll": "0",
                "toll_distance": "0",
                "polyline": "",
            },
            {
                "instruction": "右转进入%s，行驶%d米到达目的地" % (road, int(distance * 0.4)),
                "orientation": "南",
                "road": road,
                "distance": str(int(distance * 0.4)),
                "duration": str(int(duration * 0.4)),
                "toll": "0",
                "toll_distance": "0",
                "polyline": "",
            },
        ]
        return _ok(
            {
                "route": {
                    "origin": params.get("origin"),
                    "destination": params.get("destination"),
                    "taxi_cost": "%.1f" % (10 + distance / 1000.0 * 2.5),
                    "paths": [
                        {
                            "distance": str(int(round(distance))),
                            "duration": str(int(round(duration))),
                            "traffic_lights": "6",
                            "steps": steps,
                        }
                    ],
                }
            }
        )

    def bicycling(self, params: Dict[str, Any]) -> Dict[str, Any]:
        coords = self._coords(params)
        if coords is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        origin, destination = coords
        straight = geo.haversine_m(origin, destination)
        if straight < 1:
            return {"status": "0", "info": "TOO_CLOSE", "infocode": "20802"}
        distance = straight * 1.2
        duration = distance / 3.6
        return _ok(
            {
                "data": {
                    "origin": params.get("origin"),
                    "destination": params.get("destination"),
                    "paths": [
                        {
                            "distance": str(int(round(distance))),
                            "duration": str(int(round(duration))),
                            "steps": [],
                        }
                    ],
                }
            }
        )

    def transit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        coords = self._coords(params)
        if coords is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        origin, destination = coords
        straight = geo.haversine_m(origin, destination)
        if straight < 1:
            return {"status": "0", "info": "TOO_CLOSE", "infocode": "20802"}
        city = params.get("city") or self._nearest_city(*origin) or "杭州市"
        lines = self.bus_lines.get(str(city)) or ["公交1路"]
        line = lines[int(_stable_hash(str(origin) + str(destination)) % len(lines))]
        total_distance = straight * 1.3
        total_duration = total_distance / 6.5 + 300
        return _ok(
            {
                "route": {
                    "origin": params.get("origin"),
                    "destination": params.get("destination"),
                    "distance": str(int(total_distance)),
                    "taxi_cost": "%.1f" % (10 + straight / 1000.0 * 2.5),
                    "transits": [
                        {
                            "cost": "4.0",
                            "duration": str(int(total_duration)),
                            "nightflag": "0",
                            "walking_distance": "620",
                            "distance": str(int(total_distance)),
                            "missing_lines": 0,
                            "segments": [
                                {
                                    "walking": {
                                        "origin": params.get("origin"),
                                        "destination": "",
                                        "distance": "300",
                                        "duration": "240",
                                        "steps": [],
                                    },
                                    "bus": {"buslines": []},
                                },
                                {
                                    "bus": {
                                        "buslines": [
                                            {
                                                "departure_stop": {"name": "起点站"},
                                                "arrival_stop": {"name": "换乘站"},
                                                "name": line + "(开往市中心)",
                                                "type": "地铁线路" if line.startswith("地铁") else "公交线路",
                                                "distance": str(int(total_distance * 0.7)),
                                                "duration": str(int(total_duration * 0.6)),
                                                "via_num": "4",
                                                "via_stops": [{"name": "途经站%d" % i} for i in range(1, 5)],
                                            }
                                        ]
                                    },
                                },
                                {
                                    "walking": {
                                        "origin": "",
                                        "destination": params.get("destination"),
                                        "distance": "320",
                                        "duration": "256",
                                        "steps": [],
                                    },
                                    "bus": {"buslines": []},
                                },
                            ],
                        }
                    ],
                }
            }
        )

    def distance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        origins = str(params.get("origins") or "")
        destination = str(params.get("destination") or "")
        origin = geo.parse_lnglat(origins)
        dest = geo.parse_lnglat(destination)
        if origin is None or dest is None:
            return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
        straight = geo.haversine_m(origin, dest)
        dtype = str(params.get("type") or "1")
        if dtype == "0":
            distance = straight
            duration = 0
        else:
            distance = straight * 1.35
            duration = distance / 8.5 + 120
        return _ok(
            {
                "results": [
                    {
                        "origin_id": "1",
                        "dest_id": "1",
                        "distance": str(int(round(distance))),
                        "duration": str(int(round(duration))),
                        "info": "ok",
                    }
                ]
            }
        )

    def weather(self, params: Dict[str, Any]) -> Dict[str, Any]:
        city = str(params.get("city") or "杭州市")
        index = _stable_hash(city) % 3
        weathers = ["晴", "多云", "小雨"]
        return _ok(
            {
                "count": "1",
                "lives": [
                    {
                        "province": "",
                        "city": city,
                        "adcode": "",
                        "weather": weathers[index],
                        "temperature": str(18 + index * 4),
                        "winddirection": "东南",
                        "windpower": "≤3",
                        "humidity": "62",
                        "reporttime": "2026-11-02 20:00:00",
                    }
                ],
            }
        )

    # -- 分发 -------------------------------------------------------------
    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._log(path, params)
        replayed = self._replay(path, params)
        if replayed is not None:
            return replayed
        if path == "/v3/geocode/geo":
            return self.geocode(params)
        if path == "/v3/geocode/regeo":
            return self.regeo(params)
        if path == "/v3/assistant/inputtips":
            return self.inputtips(params)
        if path == "/v3/place/around":
            return self.place_around(params)
        if path == "/v3/place/text":
            return self.place_text(params)
        if path == "/v3/direction/walking":
            return self.walking(params)
        if path == "/v4/direction/bicycling":
            return self.bicycling(params)
        if path == "/v3/direction/driving":
            return self.driving(params)
        if path == "/v3/direction/transit/integrated":
            return self.transit(params)
        if path == "/v3/distance":
            return self.distance(params)
        if path == "/v3/weather/weatherInfo":
            return self.weather(params)
        return {"status": "0", "info": "INVALID_PARAMS", "infocode": "20001"}
