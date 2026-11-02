"""安全检查：仓库里不允许出现疑似真实 Key 的 32 位十六进制串。"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEX32 = re.compile(r"\b[0-9a-fA-F]{32}\b")
ASSIGN = re.compile(r"AMAP_KEY\s*[=:]\s*['\"]?([A-Za-z0-9]{8,})")
SCAN_DIRS = ("scripts", "fixtures", "tests", "tools", "docs")
SCAN_EXT = (".py", ".json", ".md", ".sh", ".txt")
ALLOWED = {"your_key_here", "testkey123456", "test-key", "mock", "dummy"}


def main():
    issues = []
    for folder in SCAN_DIRS:
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for dirpath, _, files in os.walk(base):
            for filename in files:
                if not filename.endswith(SCAN_EXT):
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        text = handle.read()
                except OSError:
                    continue
                for match in HEX32.finditer(text):
                    issues.append("%s 含 32 位十六进制串（疑似 Key）：%s" % (path, match.group(0)[:8] + "..."))
                for match in ASSIGN.finditer(text):
                    value = match.group(1)
                    if value.lower() in ALLOWED:
                        continue
                    if value in ("你的Web服务Key", "你的key", "YOUR_KEY"):
                        continue
                    issues.append("%s 出现 Key 赋值：AMAP_KEY=%s" % (path, value[:6] + "..."))

    index_path = os.path.join(ROOT, "fixtures", "recorded", "index.json")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as handle:
            index = json.load(handle)
        for entry in index.get("entries") or []:
            if "key" in (entry.get("params") or {}):
                issues.append("fixtures/recorded/index.json 中残留了 key 参数")

    if issues:
        print("安全检查失败：")
        for issue in issues:
            print("  - %s" % issue)
        return 1
    print("安全检查通过：未发现明文 Key / 32 位疑似 Key。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
