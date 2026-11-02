"""调试工具：只看一句话的解析结果，不调用任何 API。

用法：python tools/inspect_query.py "我在西湖附近想找个安静的咖啡馆"
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from text_parser import describe, parse  # noqa: E402


def main(argv):
    text = " ".join(argv[1:]) if len(argv) > 1 else ""
    if not text:
        print('用法：python tools/inspect_query.py "一句话"')
        return 1
    parsed = parse(text, default_city=os.environ.get("AMAP_DEFAULT_CITY"))
    print(describe(parsed))
    print(json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
