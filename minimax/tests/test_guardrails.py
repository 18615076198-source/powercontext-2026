"""护栏测试：模型输出的解析、路径白名单、语法校验、公共符号保留。"""

from __future__ import annotations

from pathlib import Path

from sddctx.minimax import (
    build_messages,
    keep_public_symbols,
    parse_file_blocks,
    validate_change,
)

GOOD = """=== FILE: src/billing/report.py ===
def build_monthly_report(orders, year, month, currency=None, region=None):
    return None
=== END FILE ==="""


def _files(project: Path) -> dict[str, str]:
    return {"src/billing/report.py": (project / "src" / "billing" / "report.py").read_text(encoding="utf-8")}


def test_parse_file_blocks() -> None:
    files = parse_file_blocks(GOOD)

    assert list(files) == ["src/billing/report.py"]
    assert files["src/billing/report.py"].startswith("def build_monthly_report")
    assert parse_file_blocks("随便说点什么") == {}


def test_guard_allows_expected_patch(project: Path) -> None:
    files = parse_file_blocks(GOOD)

    errors = validate_change(files, project, allowed_paths=["src/"], forbidden_paths=["tests/", "specs/"])

    assert errors == []


def test_guard_rejects_tests_and_specs(project: Path) -> None:
    files = {
        "tests/test_report.py": "print('x')\n",
        "specs/02-report.md": "# 随便改规格\n",
    }

    errors = validate_change(files, project, allowed_paths=["src/"], forbidden_paths=["tests/", "specs/"])

    assert len(errors) == 2
    assert all("禁止修改" in error for error in errors)


def test_guard_rejects_path_escape_and_unknown_file(project: Path) -> None:
    files = {"../evil.py": "print(1)\n", "src/billing/new_module.py": "print(1)\n"}

    errors = validate_change(files, project, allowed_paths=["src/"], forbidden_paths=["tests/"])

    assert any("上级目录" in error for error in errors)
    assert any("不存在" in error for error in errors)


def test_guard_rejects_syntax_error(project: Path) -> None:
    files = {"src/billing/report.py": "def broken(:\n"}

    errors = validate_change(files, project, allowed_paths=["src/"], forbidden_paths=["tests/"])

    assert errors and "语法错误" in errors[0]


def test_guard_rejects_empty_output(project: Path) -> None:
    errors = validate_change({}, project, allowed_paths=["src/"], forbidden_paths=["tests/"])

    assert errors and "没有解析到任何文件块" in errors[0]


def test_public_symbol_deletion_is_detected(project: Path) -> None:
    before = _files(project)
    after = {"src/billing/report.py": "def _private():\n    return 1\n"}

    problems = keep_public_symbols(after, before)

    assert any("build_monthly_report" in problem for problem in problems)


def test_prompt_contains_specs_guards_and_files(project: Path, store) -> None:
    from sddctx.chunker import chunk_project
    from sddctx.context import build_context_pack
    from tests.conftest import make_task

    store.upsert(chunk_project(project))
    pack = build_context_pack(make_task(project), project, store)

    messages = build_messages(pack)
    user = messages[-1]["content"]

    assert "[BR-REPORT-02]" in user
    assert "src/billing/report.py" in user
    assert "只允许修改这些路径" in user
    assert "=== FILE:" in messages[0]["content"]
