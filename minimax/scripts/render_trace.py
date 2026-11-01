"""把 runs/<task>/trace.jsonl 渲染成 docs/03-技术使用记录.md。

用法：
    python scripts/render_trace.py [--task task-001-report-region-filter]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEADER = """# 技术使用记录

本文件由 `scripts/render_trace.py` 从 `runs/<task>/trace.jsonl` 生成，记录三类技术的**实际调用**：
MiniMax（模型调用）、seekdb（资料入库与检索）、PowerContext（状态写入与召回）。
`minimax.chat` 表示真实在线调用，`minimax.replay` 表示 CI 中复用已冻结的真实输出。

复核方式：

```bash
cat runs/task-001-report-region-filter/trace.jsonl | python -m json.tool --json-lines
python scripts/render_trace.py
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="task-001-report-region-filter")
    parser.add_argument("--out", default="docs/03-技术使用记录.md")
    args = parser.parse_args()

    trace_path = ROOT / "runs" / args.task / "trace.jsonl"
    if not trace_path.is_file():
        print(f"找不到 {trace_path}")
        return 1
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    counters: dict[str, int] = {}
    for record in records:
        counters[record["event"]] = counters.get(record["event"], 0) + 1

    chats = [r for r in records if r["event"] == "minimax.chat"]
    total_in = sum(r.get("prompt_tokens", 0) for r in chats)
    total_out = sum(r.get("completion_tokens", 0) for r in chats)
    total_ms = sum(r.get("latency_ms", 0) for r in chats)

    lines = [HEADER, "## 1. 汇总\n", "| 事件 | 次数 |", "| --- | ---: |"]
    for event, count in sorted(counters.items()):
        lines.append(f"| `{event}` | {count} |")
    if chats:
        lines += [
            "",
            f"- MiniMax 真实调用 {len(chats)} 次，模型 `{chats[-1]['model']}`，"
            f"输入 {total_in} tokens / 输出 {total_out} tokens，累计耗时 {total_ms / 1000:.1f}s。",
        ]

    lines += ["", "## 2. 明细\n", "| 时间 | 事件 | 关键字段 |", "| --- | --- | --- |"]
    for record in records:
        event = record["event"]
        if event == "minimax.chat":
            detail = (
                f"model=`{record['model']}` latency={record['latency_ms']}ms "
                f"prompt={record['prompt_chars']}chars tokens={record['prompt_tokens']}/{record['completion_tokens']} "
                f"response={record['response_chars']}chars id=`{record.get('request_id', '')}`"
            )
        elif event == "minimax.replay":
            detail = f"file=`{record.get('file')}` chars={record.get('chars')}"
        elif event == "seekdb.import":
            detail = f"chunks={record.get('chunks')} counts={record.get('counts')} backend=`{record.get('backend')}`"
        elif event == "seekdb.search":
            detail = (
                f"backend=`{record.get('backend')}` specs={record.get('specs')} "
                f"code={record.get('code')} tests={record.get('tests')}"
            )
        elif event == "powercontext.remember":
            detail = f"kind=`{record.get('kind')}` entry=`{record.get('entry_id')}` chars={record.get('chars')}"
        elif event == "powercontext.source":
            detail = f"source_id=`{record.get('source_id')}` status=`{record.get('status')}`"
        elif event == "powercontext.recall":
            detail = f"source=`{record.get('source')}` hit={record.get('hit')}"
        elif event == "powercontext.scope":
            detail = f"scope_id=`{record.get('scope_id')}` title=`{record.get('title')}`"
        elif event == "verify.pytest":
            functional = record.get("functional", {})
            regression = record.get("regression", {})
            detail = (
                f"functional={functional.get('passed')} passed / {functional.get('failed')} failed; "
                f"regression={regression.get('passed')} passed / {regression.get('failed')} failed; "
                f"tests_untouched={record.get('tests_untouched')}"
            )
        else:
            detail = json.dumps({k: v for k, v in record.items() if k not in {"ts", "event"}}, ensure_ascii=False)[:160]
        lines.append(f"| {record['ts']} | `{event}` | {detail} |")

    out = ROOT / args.out
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写入 {out}（{len(records)} 条事件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
