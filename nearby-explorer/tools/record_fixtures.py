"""录制真实高德返回，存到 fixtures/recorded/，供 AMAP_MOCK=1 回放。

用法：
    set AMAP_KEY=你的Web服务Key
    python tools/record_fixtures.py --cases tests/e2e_cases.json

说明：
* 只会写入 response body 与请求参数（已剔除 key），**绝不写入 Key 本身**。
* 录制完成后，AMAP_MOCK=1 会优先回放 fixtures/recorded/ 里的真实数据；
  没有命中的请求再退回 fixtures/mock_world.json 的合成数据。
* 录制会消耗真实配额：默认每天免费额度 3000 次，10 条用例大约 60~80 次调用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import amap_client  # noqa: E402
import nearby_explorer  # noqa: E402


class RecordingTransport:
    def __init__(self, inner: Any, out_dir: str) -> None:
        self.inner = inner
        self.out_dir = out_dir
        self.entries: List[Dict[str, Any]] = []
        self._seen = set()
        os.makedirs(out_dir, exist_ok=True)

    def _file_for(self, path: str, params: Dict[str, Any]) -> str:
        raw = path + "|" + json.dumps({k: v for k, v in params.items() if k != "key"}, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        api = path.strip("/").replace("/", "_")
        return "%s_%s.json" % (api, digest)

    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = self.inner.get(path, params)
        clean = {k: v for k, v in params.items() if k != "key"}
        key = (path, json.dumps(clean, sort_keys=True, ensure_ascii=False))
        if key in self._seen:
            return payload
        self._seen.add(key)
        filename = self._file_for(path, clean)
        with open(os.path.join(self.out_dir, filename), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        self.entries.append({"path": path, "params": clean, "file": filename})
        return payload


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="录制高德真实返回，供离线回放")
    parser.add_argument("--cases", default=os.path.join(ROOT, "tests", "e2e_cases.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "fixtures", "recorded"))
    args = parser.parse_args(argv)

    key = os.environ.get("AMAP_KEY", "").strip()
    if not key:
        print("未设置 AMAP_KEY，无法录制。请先 export AMAP_KEY=你的 Web 服务 Key。", file=sys.stderr)
        return 2
    if amap_client.env_flag("AMAP_MOCK"):
        print("当前是 AMAP_MOCK=1 离线模式，录制需要真实网络，请先 unset AMAP_MOCK。", file=sys.stderr)
        return 2

    with open(args.cases, "r", encoding="utf-8") as handle:
        cases = json.load(handle).get("cases") or []

    transport = RecordingTransport(amap_client.HttpTransport(), args.out)
    client = amap_client.AmapClient(key=key, transport=transport)
    ok = 0
    for case in cases:
        query = case["query"]
        origin = case.get("origin")
        origin_hint = tuple(origin) if origin else None
        result = nearby_explorer.explore(
            query,
            top=5,
            client=client,
            default_city=case.get("default_city"),
            origin_hint=origin_hint,
        )
        status = result.get("status")
        print("[%s] %s -> %s / %d 个候选" % (status, query, case.get("id") or "-", len(result.get("candidates") or [])))
        if status == "ok":
            ok += 1
        else:
            print("   失败信息：%s" % (result.get("message") or ""))
    client.close()

    index = {"version": 1, "note": "由 tools/record_fixtures.py 录制，参数中已剔除 key", "entries": transport.entries}
    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    print("\n录制完成：%d/%d 条成功，%d 个接口响应 -> %s" % (ok, len(cases), len(transport.entries), args.out))
    print("现在可以用 AMAP_MOCK=1 回放真实数据了。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
