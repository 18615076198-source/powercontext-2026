"""资料切分测试。"""

from __future__ import annotations

from pathlib import Path

from sddctx.chunker import chunk_code, chunk_project, chunk_specs, chunk_tests


def test_specs_are_split_by_requirement_id(project: Path) -> None:
    chunks = chunk_specs(project)

    ids = {chunk.symbol for chunk in chunks}
    assert "BR-REPORT-01" in ids
    assert "BR-REPORT-04" in ids
    assert "BR-PRICE-03" in ids
    assert all(chunk.kind == "spec" for chunk in chunks)
    assert all(chunk.content.startswith("## BR-") for chunk in chunks)


def test_spec_chunk_keeps_line_numbers(project: Path) -> None:
    chunk = next(item for item in chunk_specs(project) if item.symbol == "BR-REPORT-02")

    lines = (project / chunk.path).read_text(encoding="utf-8").splitlines()
    assert lines[chunk.line_start - 1].startswith("## BR-REPORT-02")
    assert chunk.line_start <= chunk.line_end


def test_code_chunks_expose_function_symbols(project: Path) -> None:
    chunks = chunk_code(project)

    symbols = {chunk.symbol for chunk in chunks}
    assert "billing.report:build_monthly_report" in symbols
    assert "billing.pricing:compute_payable_minor" in symbols
    assert "billing.report:MonthlyReport.to_dict" in symbols


def test_test_chunks_only_contain_test_functions(project: Path) -> None:
    chunks = chunk_tests(project)

    assert chunks
    assert all(chunk.title.startswith("test_") for chunk in chunks)
    ids = {chunk.metadata["test_id"] for chunk in chunks}
    assert "tests/test_report.py::test_currency_filter" in ids


def test_chunk_ids_are_unique(project: Path) -> None:
    chunks = chunk_project(project)

    ids = [chunk.chunk_id for chunk in chunks]
    assert len(ids) == len(set(ids))
    assert {chunk.kind for chunk in chunks} == {"spec", "code", "test"}
