"""测试引导：让 `pytest` 直接从 ``src/`` 导入 ``billing``。"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
