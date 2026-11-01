"""技术使用记录：把每次外部调用写进 JSONL，作为可审计的证据链。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import now_iso


class Trace:
    """一次运行的事件记录器。

    记录三类事件：``minimax``（模型调用）、``seekdb``（资料入库/检索）、
    ``powercontext``（任务状态读写），全部带耗时与结果摘要。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.events: list[dict] = []

    def emit(self, event: str, **fields) -> dict:
        record = {"ts": now_iso(), "event": event, **fields}
        self.events.append(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def summary(self) -> dict:
        agg: dict[str, int] = {}
        for record in self.events:
            agg[record["event"]] = agg.get(record["event"], 0) + 1
        return {"total": len(self.events), "by_event": agg, "path": str(self.path)}
