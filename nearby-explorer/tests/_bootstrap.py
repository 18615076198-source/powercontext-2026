"""测试公共设施：路径注入、样例加载、脚本化传输层。"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURES = os.path.join(ROOT, "fixtures")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
os.environ.setdefault("AMAP_MOCK", "1")


def load_sample(name: str) -> Any:
    with open(os.path.join(FIXTURES, "samples", name), "r", encoding="utf-8") as handle:
        return json.load(handle)


class ScriptedTransport:
    """按脚本依次返回 payload（或抛异常），并记录每次调用参数。"""

    def __init__(self, responses: List[Any]) -> None:
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"path": path, "params": dict(params)})
        if not self.responses:
            raise AssertionError("脚本化响应已用完：%s" % path)
        item = self.responses[0] if len(self.responses) == 1 else self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
