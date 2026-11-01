"""sddctx 命令行入口。

输入：一份验证样例（任务 JSON）+ 一个业务工程目录。
输出：上下文包、代码差异、测试结果、PowerContext 中的任务状态。

命令一览：
    sddctx doctor                     环境自检
    sddctx import   --task T          导入规格/代码/测试到 seekdb
    sddctx plan     --task T          组装并校验上下文包
    sddctx spec-apply --task T        把样例里的规格更新写入工程（规格演进）
    sddctx apply    --task T          调 MiniMax 改代码，过护栏后落盘
    sddctx verify   --task T          跑功能测试 + 回归测试
    sddctx save     --task T          把任务状态写入 PowerContext
    sddctx resume   --task T          新进程回读状态并重新组装上下文
    sddctx run      --task T          一条龙：import → plan → apply → verify → save
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import context as context_mod
from .chunker import chunk_project
from .config import PROJECT_ROOT, Settings
from .minimax import (
    MiniMaxClient,
    apply_files,
    build_messages,
    keep_public_symbols,
    parse_file_blocks,
    validate_change,
)
from .models import RunState, TaskSpec, now_iso, sha256_text
from .powercontext import PowerContextClient, PowerContextError, build_state
from .store import open_store
from .trace import Trace
from .verify import run_acceptance, run_pytest

DEFAULT_TASK = PROJECT_ROOT / "samples" / "task-001-report-region-filter" / "task.json"


# --------------------------------------------------------------------- 公共
def load_task(task_path: str | Path) -> tuple[TaskSpec, Path, Path]:
    task_file = Path(task_path).resolve()
    task = TaskSpec.load(task_file)
    project_root = (PROJECT_ROOT / task.project).resolve()
    if not project_root.is_dir():
        raise SystemExit(f"找不到业务工程目录：{project_root}")
    run_dir = PROJECT_ROOT / "runs" / task.task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return task, project_root, run_dir


def make_store(settings: Settings):
    return open_store(settings)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _mirror_state(run_dir: Path, state: RunState) -> None:
    _write_json(run_dir / "state.json", state.to_dict())


def _load_mirror(run_dir: Path, task_id: str) -> RunState:
    payload = _read_json(run_dir / "state.json") or {}
    if payload:
        return RunState.from_dict(payload)
    return RunState(task_id=task_id, status="new")


# --------------------------------------------------------------------- 命令
def cmd_doctor(args) -> int:
    settings = Settings.load()
    print("== 环境自检 ==")
    print(f"项目根目录 : {PROJECT_ROOT}")
    print(f"存储后端   : {settings.store_backend}")
    print(f"MiniMax    : {settings.minimax_base_url} / {settings.minimax_model} / key={'已配置' if settings.minimax_api_key else '缺失'}")
    store = make_store(settings)
    print(f"存储状态   : {json.dumps(store.backend_info(), ensure_ascii=False)}")
    # 自检阶段还没有 run_dir，不挂 trace
    client = PowerContextClient(settings)
    health = client.health()
    print(f"PowerContext: {settings.powercontext_url} -> {health.get('status')}")
    if health.get("status") != "ready":
        print(f"  详情：{json.dumps(health, ensure_ascii=False)[:400]}")
    print(f"pytest     : {sys.executable} -m pytest")
    return 0


def cmd_import(args) -> int:
    settings = Settings.load()
    task, project_root, run_dir = load_task(args.task)
    trace = Trace(run_dir / "trace.jsonl", reset=bool(args.reset))
    store = make_store(settings)
    if args.reset:
        store.reset()
    chunks = chunk_project(project_root)
    if not chunks:
        print("没有切出任何资料块，请检查工程目录结构")
        return 1
    started = now_iso()
    store.upsert(chunks)
    counts = store.count()
    trace.emit("seekdb.import", project=str(project_root), chunks=len(chunks), counts=counts, backend=store.name)
    print(f"[import] 资料块 {len(chunks)} 条 → {store.name}：{counts}")
    _write_json(
        run_dir / "import.json",
        {
            "backend": store.name,
            "store": store.backend_info(),
            "chunks": len(chunks),
            "counts": counts,
            "spec_ids": sorted({chunk.symbol for chunk in chunks if chunk.kind == "spec"}),
            "started_at": started,
            "finished_at": now_iso(),
        },
    )
    return 0


def cmd_plan(args) -> int:
    settings = Settings.load()
    task, project_root, run_dir = load_task(args.task)
    trace = Trace(run_dir / "trace.jsonl")
    store = make_store(settings)
    pack = context_mod.build_context_pack(task, project_root, store)
    trace.emit(
        "seekdb.search",
        task_id=task.task_id,
        backend=store.name,
        specs=len(pack["specs"]),
        code=len(pack["code"]),
        tests=len(pack["tests"]),
    )
    problems = context_mod.verify_sources(pack, project_root)
    pack["source_problems"] = problems
    path = context_mod.dump_pack(pack, run_dir / "context-pack.json")
    print(context_mod.render_summary(pack))
    print(f"[plan] 上下文包已写入 {path.relative_to(PROJECT_ROOT)}")
    if problems:
        print("[plan] 来源校验失败：")
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    print("[plan] 来源校验通过：所有条目都能落到真实文件与行号")
    return 0


def cmd_spec_apply(args) -> int:
    task, project_root, run_dir = load_task(args.task)
    if not task.spec_update:
        print("该任务没有规格更新")
        return 0
    applied = []
    for item in task.spec_update:
        source = Path(task_file_dir(args.task)) / item["source"]
        target = project_root / item["target"]
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        new = source.read_text(encoding="utf-8")
        if old == new:
            print(f"[spec-apply] {item['target']} 已是目标版本，跳过")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new, encoding="utf-8")
        applied.append(item["target"])
        print(f"[spec-apply] {item['target']} 更新：{len(old)} → {len(new)} 字符")
    _write_json(run_dir / "spec-apply.json", {"applied": applied, "at": now_iso()})
    if applied:
        print("[spec-apply] 规格已演进，请重新执行 sddctx import 后再 plan")
    return 0


def task_file_dir(task_path: str | Path) -> Path:
    return Path(task_path).resolve().parent


def cmd_apply(args) -> int:
    settings = Settings.load()
    task, project_root, run_dir = load_task(args.task)
    trace = Trace(run_dir / "trace.jsonl")
    store = make_store(settings)
    pack = context_mod.build_context_pack(task, project_root, store)
    problems = context_mod.verify_sources(pack, project_root)
    if problems:
        print("[apply] 上下文来源校验失败，先修复资料再改代码：")
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    if pack["gaps"]:
        print("[apply] 存在规格缺口，模型缺少可依据的规格：")
        for gap in pack["gaps"]:
            print(f"  ! {gap}")
        print("        先执行 sddctx spec-apply --task ... 并重新 import")
        return 1

    context_mod.dump_pack(pack, run_dir / "context-pack.json")
    before = {path: content for path, content in pack["full_files"].items()}
    messages = build_messages(pack)
    client = MiniMaxClient(settings)

    errors: list[str] = []
    text = ""
    replay_file = os.environ.get("SDDCTX_MINIMAX_REPLAY_FILE", "")
    for attempt in range(1, args.max_attempts + 1):
        if replay_file:
            text = Path(replay_file).read_text(encoding="utf-8")
            trace.emit("minimax.replay", attempt=attempt, file=replay_file, chars=len(text))
        else:
            print(f"[apply] 调用 MiniMax（{settings.minimax_model}，第 {attempt} 次）…", flush=True)
            text = client.chat(messages, attempt=attempt)
            call = client.last_call
            if call is not None:
                trace.emit("minimax.chat", **call.to_trace(), stage="code-edit")
        files = parse_file_blocks(text)
        errors = validate_change(
            files,
            project_root,
            allowed_paths=pack["guards"]["allowed_paths"],
            forbidden_paths=pack["guards"]["forbidden_paths"],
        )
        symbol_problems = keep_public_symbols(files, before)
        errors.extend(symbol_problems)
        if not errors:
            break
        print(f"[apply] 第 {attempt} 次输出未通过护栏：{errors}")
        if attempt < args.max_attempts:
            messages = messages + [
                {"role": "assistant", "content": text[:4000]},
                {
                    "role": "user",
                    "content": "上面的输出违反了以下约束，请修正后重新按输出协议给出完整文件：\n"
                    + "\n".join(f"- {error}" for error in errors),
                },
            ]

    if errors:
        _write_json(run_dir / "apply.json", {"ok": False, "errors": errors, "at": now_iso()})
        print("[apply] 护栏未通过，未写入任何文件")
        return 1

    applied, diff = apply_files(files, project_root)
    (run_dir / "change.patch").write_text(diff, encoding="utf-8")
    (run_dir / "minimax-output.txt").write_text(text, encoding="utf-8")
    after = {path: sha256_text((project_root / path).read_text(encoding="utf-8")) for path in applied}
    payload = {
        "ok": True,
        "task_id": task.task_id,
        "files": applied,
        "file_hashes": after,
        "diff_lines": len(diff.splitlines()),
        "minimax": (client.last_call.to_trace() if client.last_call else {}),
        "model_output_chars": len(text),
        "at": now_iso(),
    }
    _write_json(run_dir / "apply.json", payload)
    print(f"[apply] MiniMax 修改了 {len(applied)} 个文件：{', '.join(applied)}")
    print(f"[apply] 代码差异 {payload['diff_lines']} 行 → runs/{task.task_id}/change.patch")
    return 0


def cmd_verify(args) -> int:
    task, project_root, run_dir = load_task(args.task)
    trace = Trace(run_dir / "trace.jsonl")
    acceptance = [task_file_dir(args.task) / name for name in task.acceptance_tests]
    missing = [str(path) for path in acceptance if not path.is_file()]
    if missing:
        print(f"[verify] 找不到验收测试：{missing}")
        return 1

    tests_before = {path: sha256_text(path.read_text(encoding="utf-8")) for path in sorted((project_root / task.regression_tests).rglob("test_*.py"))}

    functional = run_acceptance(project_root, acceptance, name="functional")
    regression = run_pytest(project_root, [task.regression_tests], name="regression")

    tests_after = {path: sha256_text(path.read_text(encoding="utf-8")) for path in sorted((project_root / task.regression_tests).rglob("test_*.py"))}
    tests_intact = tests_before == tests_after

    payload = {
        "task_id": task.task_id,
        "functional": functional.to_dict(),
        "regression": regression.to_dict(),
        "tests_untouched": tests_intact,
        "ok": functional.ok and regression.ok and tests_intact,
        "at": now_iso(),
    }
    _write_json(run_dir / "verify.json", payload)
    trace.emit(
        "verify.pytest",
        functional=functional.to_dict() | {"tests": len(functional.tests)},
        regression={"passed": regression.passed, "failed": regression.failed, "ok": regression.ok},
        tests_untouched=tests_intact,
    )

    for result in (functional, regression):
        print(f"[verify] {result.name}: {result.passed} passed, {result.failed} failed, {result.errors} error, "
              f"{result.skipped} skipped  ({result.duration_s:.2f}s)")
        if not result.ok:
            print(result.output_tail)
    print(f"[verify] 既有测试未被改动：{tests_intact}")
    print(f"[verify] 结论：{'通过' if payload['ok'] else '未通过'} → runs/{task.task_id}/verify.json")
    return 0 if payload["ok"] else 1


def cmd_save(args) -> int:
    settings = Settings.load()
    task, project_root, run_dir = load_task(args.task)
    trace = Trace(run_dir / "trace.jsonl")
    apply_payload = _read_json(run_dir / "apply.json") or {}
    verify_payload = _read_json(run_dir / "verify.json") or {}
    mirror = _load_mirror(run_dir, task.task_id)

    done: list[str] = []
    if apply_payload.get("ok"):
        files = apply_payload.get("files") or []
        done.append(f"导入资料并确定上下文（待改文件 {len(files)} 个）")
        done.append(f"MiniMax 生成改动：{', '.join(files)}")
    verification = []
    for name in ("functional", "regression"):
        suite = verify_payload.get(name)
        if suite:
            verification.append(
                {
                    "name": name,
                    "status": "passed" if suite.get("ok") else "failed",
                    "passed": suite.get("passed", 0),
                    "failed": suite.get("failed", 0),
                }
            )
            if suite.get("ok"):
                done.append(f"{name} 测试通过（{suite.get('passed')} 条）")

    todo: list[str] = []
    if not verify_payload.get("ok"):
        todo.append("修复未通过的功能或回归测试")
    todo.append("人工复核 change.patch 与规格一致性")

    state = build_state(
        task.task_id,
        status="verified" if verify_payload.get("ok") else "in_progress",
        done=done,
        todo=todo,
        verification=verification,
        change={
            "files": apply_payload.get("files") or [],
            "patch": f"runs/{task.task_id}/change.patch",
            "diff_lines": apply_payload.get("diff_lines", 0),
        },
        revision=int(mirror.revision) + 1,
    )

    client = PowerContextClient(settings, trace)
    scope_id = settings.powercontext_scope_id
    prior_revision = 0 if mirror.status == "new" else mirror.revision
    try:
        if not scope_id:
            scope_id = client.ensure_scope(
                f"sddctx · {task.project}",
                "规有所依：SDD 上下文管理系统的任务状态分区",
                f"sddctx-{sha256_text(str(project_root))[:12]}",
            )
        # 服务端可能留有更早的状态快照，revision 以两端较大值为准，保证单调递增
        recalled = client.recall_state(scope_id, task.task_id)
        if recalled.state is not None:
            prior_revision = max(prior_revision, recalled.state.revision)
        state.revision = prior_revision + 1
        client.save_state(scope_id, state)
    except PowerContextError as error:
        print(f"[save] PowerContext 不可用：{error}")
        _mirror_state(run_dir, state)
        print(f"[save] 已退回本地镜像 runs/{task.task_id}/state.json")
        return 1

    _mirror_state(run_dir, state)
    (run_dir / "scope.txt").write_text(scope_id, encoding="utf-8")
    print(f"[save] 状态已写入 PowerContext：scope={scope_id} revision={state.revision}")
    print(f"[save] done={len(state.done)} todo={len(state.todo)} verification={len(state.verification)}")
    return 0


def cmd_resume(args) -> int:
    settings = Settings.load()
    task, project_root, run_dir = load_task(args.task)
    trace = Trace(run_dir / "trace.jsonl")
    client = PowerContextClient(settings, trace)
    scope_file = run_dir / "scope.txt"
    scope_id = args.scope_id or (scope_file.read_text(encoding="utf-8").strip() if scope_file.is_file() else "")
    scope_id = scope_id or settings.powercontext_scope_id
    if not scope_id:
        print("[resume] 没有找到 scope，先执行 sddctx save")
        return 1
    result = client.recall_state(scope_id, task.task_id)
    if result.state is None:
        print(f"[resume] 未回读到状态（{result.detail}）")
        return 1

    state = result.state
    print(f"[resume] 从 PowerContext 回读状态（{result.source}）：{result.detail}")
    print(f"[resume] 任务 {state.task_id} 状态={state.status} revision={state.revision} updated_at={state.updated_at}")
    print(f"[resume] 已完成 {len(state.done)} 项：")
    for item in state.done:
        print(f"   ✓ {item}")
    print(f"[resume] 待办 {len(state.todo)} 项：")
    for item in state.todo:
        print(f"   · {item}")
    print("[resume] 已有验证结果：")
    for item in state.verification:
        print(f"   - {item.get('name')}: {item.get('status')} (passed={item.get('passed')}, failed={item.get('failed')})")

    store = make_store(settings)
    pack = context_mod.build_context_pack(task, project_root, store)
    context_mod.attach_state(pack, state)
    path = context_mod.dump_pack(pack, run_dir / "context-pack.resume.json")
    print(f"[resume] 状态已并入上下文包 → {path.relative_to(PROJECT_ROOT)}（待办与验证结果随之带出）")
    return 0


def cmd_run(args) -> int:
    steps = [
        ("import", lambda: cmd_import(argparse.Namespace(**{**vars(args), "reset": False}))),
        ("plan", lambda: cmd_plan(args)),
        ("apply", lambda: cmd_apply(argparse.Namespace(**{**vars(args), "max_attempts": 2}))),
        ("verify", lambda: cmd_verify(args)),
        ("save", lambda: cmd_save(args)),
    ]
    for name, action in steps:
        print(f"\n===== {name} =====")
        code = action()
        if code != 0:
            print(f"[run] 步骤 {name} 失败，中止")
            return code
    return 0


# --------------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddctx", description="面向软件持续演进的 SDD 上下文管理")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_task(p, required=True):
        p.add_argument("--task", default=str(DEFAULT_TASK), help="验证样例 JSON 路径")

    p = sub.add_parser("doctor", help="环境自检")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("import", help="导入规格/代码/测试到存储")
    add_task(p)
    p.add_argument("--reset", action="store_true", help="清空后重建索引")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("plan", help="组装上下文包")
    add_task(p)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("spec-apply", help="应用样例中的规格更新")
    add_task(p)
    p.set_defaults(func=cmd_spec_apply)

    p = sub.add_parser("apply", help="调用 MiniMax 修改代码")
    add_task(p)
    p.add_argument("--max-attempts", type=int, default=2)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", help="运行功能与回归测试")
    add_task(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("save", help="保存任务状态到 PowerContext")
    add_task(p)
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("resume", help="回读任务状态并继续")
    add_task(p)
    p.add_argument("--scope-id", default="")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("run", help="import → plan → apply → verify → save")
    add_task(p)
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
