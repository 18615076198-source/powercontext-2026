"""上下文包：从检索结果组装「本次任务真正需要的东西」。

输出必须能定位四类信息：
1. 适用的规格条目；2. 需要修改的代码文件/符号；3. 验证功能与兼容性的测试；
4. 已完成、待办与已有验证结果（来自 PowerContext）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Chunk, Hit, RunState, TaskSpec, now_iso, sha256_text
from .store.base import Store

SPEC_QUOTA = 6
CODE_QUOTA = 6
TEST_QUOTA = 8


def _entry_from_chunk(chunk: Chunk, *, reason: str, score: float, project_root: Path) -> dict:
    payload = {
        "id": chunk.chunk_id,
        "kind": chunk.kind,
        "path": chunk.path,
        "symbol": chunk.symbol,
        "title": chunk.title,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "content_hash": chunk.content_hash,
        "relevance": round(score, 4),
        "why": reason,
    }
    if chunk.kind == "spec":
        payload["spec_id"] = chunk.metadata.get("spec_id", chunk.symbol)
    if chunk.kind == "test":
        payload["test_id"] = chunk.metadata.get("test_id", chunk.symbol)
    file_path = project_root / chunk.path
    payload["file_exists"] = file_path.is_file()
    payload["file_hash"] = sha256_text(file_path.read_text(encoding="utf-8")) if payload["file_exists"] else ""
    payload["content"] = chunk.content
    return payload


def _dedupe(hits: list[Hit]) -> list[Hit]:
    seen: set[str] = set()
    unique: list[Hit] = []
    for hit in hits:
        if hit.chunk.chunk_id in seen:
            continue
        seen.add(hit.chunk.chunk_id)
        unique.append(hit)
    return unique


def build_context_pack(task: TaskSpec, project_root: Path, store: Store) -> dict:
    """按任务组装上下文包，并在其中记录缺口与失效来源。"""

    query = " ".join(
        [task.title, task.request]
        + [item.get("reason", "") for item in task.must_preserve]
        + [item.get("spec_id", "") for item in task.must_preserve]
    )

    gaps: list[str] = []
    spec_hits: list[Hit] = []
    code_hits: list[Hit] = []

    # 1) 规格：先按任务锚点精确取，再按查询检索补充
    for spec_id in task.spec_anchor_ids:
        chunk = store.get(f"spec:{spec_id}")
        if chunk is None:
            gaps.append(f"锚点规格 {spec_id} 尚未导入（规格缺口）")
            continue
        spec_hits.append(Hit(chunk=chunk, score=999.0, reason=f"任务锚点 {spec_id}"))
    for item in task.must_preserve:
        spec_id = item.get("spec_id")
        if spec_id and all(hit.chunk.symbol != spec_id for hit in spec_hits):
            chunk = store.get(f"spec:{spec_id}")
            if chunk is not None:
                spec_hits.append(Hit(chunk=chunk, score=998.0, reason=f"必须保持的既有行为 {spec_id}"))

    got_spec_ids = {hit.chunk.symbol for hit in spec_hits}
    for hit in store.search(query, ["spec"], SPEC_QUOTA):
        if hit.chunk.symbol in got_spec_ids:
            continue
        spec_hits.append(hit)
    spec_hits = _dedupe(spec_hits)[:SPEC_QUOTA]

    # 2) 代码：先按符号锚点，再按检索
    for symbol in task.anchors.get("symbols", []):
        found = store.find(symbol=symbol)
        for chunk in found:
            code_hits.append(Hit(chunk=chunk, score=999.0, reason=f"任务锚点 {symbol}"))
    got_symbols = {hit.chunk.chunk_id for hit in code_hits}
    for hit in store.search(query, ["code"], CODE_QUOTA):
        if hit.chunk.chunk_id not in got_symbols:
            code_hits.append(hit)
    code_hits = _dedupe(code_hits)[:CODE_QUOTA]

    # 3) 测试：检索 + 引用了目标符号的用例
    test_hits = store.search(query, ["test"], TEST_QUOTA)
    target_names = {hit.chunk.title.split(".")[-1] for hit in code_hits}
    test_hits += [
        hit for hit in store.search(" ".join(target_names), ["test"], TEST_QUOTA) if hit not in test_hits
    ]
    test_hits = _dedupe(test_hits)[:TEST_QUOTA]

    full_files: dict[str, str] = {}
    for hit in code_hits:
        path = project_root / hit.chunk.path
        if hit.chunk.path not in full_files and path.is_file():
            full_files[hit.chunk.path] = path.read_text(encoding="utf-8")

    pack = {
        "schema": "sdd-context-pack.v1",
        "task_id": task.task_id,
        "task_title": task.title,
        "request": task.request,
        "generated_at": now_iso(),
        "query": query,
        "store": store.backend_info(),
        "specs": [
            _entry_from_chunk(hit.chunk, reason=hit.reason, score=hit.score, project_root=project_root)
            for hit in spec_hits
        ],
        "code": [
            _entry_from_chunk(hit.chunk, reason=hit.reason, score=hit.score, project_root=project_root)
            for hit in code_hits
        ],
        "tests": [
            _entry_from_chunk(hit.chunk, reason=hit.reason, score=hit.score, project_root=project_root)
            for hit in test_hits
        ],
        "full_files": full_files,
        "gaps": gaps,
        "guards": {
            "allowed_paths": task.allowed_paths,
            "forbidden_paths": ["tests/", "specs/"],
            "must_preserve": task.must_preserve,
            "acceptance_tests": task.acceptance_tests,
            "regression_tests": task.regression_tests,
        },
        "state": RunState(task_id=task.task_id, todo=[]).to_dict(),
    }
    return pack


def verify_sources(pack: dict, project_root: Path) -> list[str]:
    """校验上下文包里的来源真实存在、未被改动、行号仍有效。"""

    problems: list[str] = []
    for section in ("specs", "code", "tests"):
        for entry in pack.get(section, []):
            path = project_root / entry["path"]
            if not path.is_file():
                problems.append(f"{entry['id']}: 来源文件不存在 {entry['path']}")
                continue
            text = path.read_text(encoding="utf-8")
            if entry.get("file_hash") and sha256_text(text) != entry["file_hash"]:
                problems.append(f"{entry['id']}: {entry['path']} 在导入后被修改，资料已过期，请重新导入")
                continue
            if entry["content"] not in text:
                problems.append(
                    f"{entry['id']}: 片段已不在 {entry['path']} 中（行号 {entry['line_start']}-{entry['line_end']} 失效）"
                )
    return problems


def attach_state(pack: dict, state: RunState) -> dict:
    pack["state"] = state.to_dict()
    return pack


def render_summary(pack: dict) -> str:
    """把上下文包渲染成便于人读的摘要。"""

    lines: list[str] = []
    lines.append(f"任务：{pack['task_id']} — {pack['task_title']}")
    lines.append(f"存储后端：{pack['store'].get('backend')}  资料块：{pack['store'].get('chunks')}")
    if pack.get("gaps"):
        lines.append("规格缺口：")
        lines.extend(f"  - {gap}" for gap in pack["gaps"])
    for title, section in (("适用规格", "specs"), ("待改代码", "code"), ("验证测试", "tests")):
        entries = pack.get(section, [])
        lines.append(f"{title}（{len(entries)}）：")
        for entry in entries:
            location = f"{entry['path']}:{entry['line_start']}-{entry['line_end']}"
            lines.append(f"  - [{entry['id']}] {entry['title']}  @ {location}  ({entry['why']})")
        if not entries:
            lines.append("  - （无）")
    state = pack.get("state") or {}
    lines.append(f"任务状态：{state.get('status')}  done={len(state.get('done') or [])}  todo={len(state.get('todo') or [])}")
    for item in state.get("todo") or []:
        lines.append(f"  · 待办：{item}")
    for item in state.get("verification") or []:
        lines.append(f"  · 验证：{item.get('name')} -> {item.get('status')}")
    return "\n".join(lines)


def dump_pack(pack: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
