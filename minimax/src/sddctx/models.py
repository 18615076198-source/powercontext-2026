"""核心数据结构。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    """工程资料的最小检索单元。

    kind 取值：``spec``（规格条目）、``code``（函数/类）、``test``（测试用例）。
    """

    chunk_id: str
    kind: str
    path: str
    symbol: str
    title: str
    content: str
    line_start: int
    line_end: int
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = sha256_text(self.content)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content_hash"] = self.content_hash
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Chunk:
        return cls(**payload)


@dataclass
class Hit:
    """一次检索命中。"""

    chunk: Chunk
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": round(self.score, 4), "reason": self.reason, "chunk": self.chunk.to_dict()}


@dataclass
class SourceRef:
    """上下文包的来源引用，必须能落到真实文件与行号。"""

    path: str
    line_start: int
    line_end: int
    content_hash: str


@dataclass
class TaskSpec:
    """验证样例：描述「要改什么」与「哪些原有行为必须保持」。"""

    task_id: str
    title: str
    project: str
    request: str
    anchors: dict[str, list[str]] = field(default_factory=dict)
    must_preserve: list[dict[str, str]] = field(default_factory=list)
    spec_update: list[dict[str, str]] = field(default_factory=list)
    acceptance_tests: list[str] = field(default_factory=list)
    regression_tests: str = "tests"
    allowed_paths: list[str] = field(default_factory=lambda: ["src/"])
    extra_context: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> TaskSpec:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        payload.pop("$comment", None)
        return cls(**payload)

    @property
    def spec_anchor_ids(self) -> list[str]:
        return list(self.anchors.get("spec_ids", []))


@dataclass
class RunState:
    """跨进程保存的任务状态，写入 PowerContext 并回读。"""

    task_id: str
    status: str = "planned"
    done: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    verification: list[dict[str, Any]] = field(default_factory=list)
    change: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=now_iso)
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunState:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in known})
