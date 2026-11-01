"""上下文包测试：定位能力、来源真实性、规格演进后的新鲜度。"""

from __future__ import annotations

from pathlib import Path

from sddctx.chunker import chunk_project
from sddctx.context import build_context_pack, render_summary, verify_sources
from tests.conftest import make_task


def _index(project: Path, store) -> None:
    store.upsert(chunk_project(project))


def test_pack_locates_specs_code_and_tests(project: Path, store) -> None:
    _index(project, store)
    task = make_task(project)

    pack = build_context_pack(task, project, store)

    spec_ids = {entry["spec_id"] for entry in pack["specs"]}
    assert {"BR-REPORT-02", "BR-REPORT-03"} <= spec_ids
    symbols = {entry["symbol"] for entry in pack["code"]}
    assert "billing.report:build_monthly_report" in symbols
    assert pack["tests"], "必须能定位验证测试"
    assert all(entry["test_id"].startswith("tests/") for entry in pack["tests"])


def test_every_source_points_to_a_real_file(project: Path, store) -> None:
    _index(project, store)
    pack = build_context_pack(make_task(project), project, store)

    assert verify_sources(pack, project) == []
    for section in ("specs", "code", "tests"):
        for entry in pack[section]:
            text = (project / entry["path"]).read_text(encoding="utf-8")
            assert entry["content"] in text
            assert entry["file_exists"] is True


def test_missing_spec_is_reported_as_gap(project: Path, store) -> None:
    _index(project, store)
    task = make_task(project, anchors={"spec_ids": ["BR-REPORT-99"], "symbols": []})

    pack = build_context_pack(task, project, store)

    assert any("BR-REPORT-99" in gap for gap in pack["gaps"])


def test_pack_follows_updated_spec_after_reimport(project: Path, store) -> None:
    _index(project, store)
    before = build_context_pack(make_task(project, anchors={"spec_ids": [], "symbols": []}), project, store)
    assert "BR-REPORT-77" not in {entry["spec_id"] for entry in before["specs"]}

    spec_file = project / "specs" / "02-report.md"
    spec_file.write_text(
        spec_file.read_text(encoding="utf-8")
        + "\n## BR-REPORT-77 区域白名单\n\n- 优先级：必须\n- 规则：只允许导出白名单内的区域。\n",
        encoding="utf-8",
    )
    _index(project, store)

    after = build_context_pack(
        make_task(project, anchors={"spec_ids": ["BR-REPORT-77"], "symbols": []}, request="区域白名单导出"),
        project,
        store,
    )
    assert "BR-REPORT-77" in {entry["spec_id"] for entry in after["specs"]}
    assert verify_sources(after, project) == []


def test_stale_file_is_detected(project: Path, store) -> None:
    _index(project, store)
    pack = build_context_pack(make_task(project), project, store)

    spec_file = project / "specs" / "02-report.md"
    spec_file.write_text(spec_file.read_text(encoding="utf-8") + "\n<!-- 人工改动 -->\n", encoding="utf-8")

    problems = verify_sources(pack, project)
    assert any("导入后被修改" in problem for problem in problems)


def test_summary_mentions_state(project: Path, store) -> None:
    _index(project, store)
    pack = build_context_pack(make_task(project), project, store)

    text = render_summary(pack)

    assert "适用规格" in text
    assert "待改代码" in text
    assert "任务状态" in text
