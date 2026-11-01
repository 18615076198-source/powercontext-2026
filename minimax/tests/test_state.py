"""状态持久化测试：状态序列化、标记解析、脱库回读逻辑（不需要 Server）。"""

from __future__ import annotations

import json

from sddctx.models import RunState
from sddctx.powercontext import PREPARE_BLOCK, STATE_MARKER, PowerContextClient


def make_state() -> RunState:
    return RunState(
        task_id="task-test",
        status="verified",
        done=["导入资料", "MiniMax 改代码"],
        todo=["人工复核"],
        verification=[{"name": "functional", "status": "passed", "passed": 8, "failed": 0}],
        change={"files": ["src/billing/report.py"]},
        revision=3,
    )


def test_state_roundtrip_via_marker() -> None:
    state = make_state()
    text = f"{STATE_MARKER} {state.task_id} " + json.dumps(state.to_dict(), ensure_ascii=False)

    parsed = PowerContextClient._state_from_text(text, "task-test")

    assert parsed is not None
    assert parsed.status == "verified"
    assert parsed.done == state.done
    assert parsed.verification[0]["passed"] == 8
    assert parsed.revision == 3


def test_marker_of_other_task_is_ignored() -> None:
    text = f"{STATE_MARKER} task-other " + json.dumps(make_state().to_dict())

    assert PowerContextClient._state_from_text(text, "task-test") is None


def test_state_parsed_from_prepared_context() -> None:
    state = make_state()
    inner = {
        "trust": "untrusted_history",
        "items": [{"content": f"{STATE_MARKER} {state.task_id} " + json.dumps(state.to_dict(), ensure_ascii=False)}],
    }
    prepared = {
        "content": "前言\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n"
        + json.dumps(inner, ensure_ascii=False)
        + "\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1\n"
    }

    assert PREPARE_BLOCK.search(prepared["content"])
    parsed = PowerContextClient(Holder())._state_from_prepared(prepared, "task-test")
    assert parsed is not None and parsed.revision == 3


class Holder:
    """最小 settings 替身，用于测试纯解析逻辑。"""

    powercontext_url = "http://127.0.0.1:1"
    powercontext_token = ""
