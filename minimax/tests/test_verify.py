"""验证器测试：pytest 输出解析与工程内测试执行。"""

from __future__ import annotations

from pathlib import Path

from sddctx.verify import parse_pytest_output, run_pytest


def test_parse_verbose_output() -> None:
    text = """tests/test_a.py::test_one PASSED                                      [ 50%]
tests/test_a.py::test_two FAILED                                      [100%]
=========================== short test summary info ===========================
========================= 1 failed, 1 passed in 0.12s =========================
"""
    result = parse_pytest_output(text)

    assert result["passed"] == 1
    assert result["failed"] == 1
    assert {test["nodeid"] for test in result["tests"]} == {"tests/test_a.py::test_one", "tests/test_a.py::test_two"}


def test_parse_quiet_output_falls_back_to_summary() -> None:
    text = "........ 8 passed in 0.26s\n"

    result = parse_pytest_output(text)

    assert result["passed"] == 8
    assert result["tests"] == []


def test_run_pytest_over_demo_project(project: Path) -> None:
    result = run_pytest(project, ["tests"], name="regression", timeout=180)

    assert result.ok, result.output_tail
    assert result.passed >= 20
    assert all(test["outcome"] == "PASSED" for test in result.tests)
