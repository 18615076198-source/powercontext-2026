"""模块测试的公共夹具：临时业务工程 + 可切换的存储后端。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sddctx.config import PROJECT_ROOT, Settings
from sddctx.models import TaskSpec
from sddctx.store import open_store

DEMO = PROJECT_ROOT / "demo" / "billing-service"
TASK_FILE = PROJECT_ROOT / "samples" / "task-001-report-region-filter" / "task.json"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """把业务工程复制到临时目录，避免测试污染仓库。"""

    target = tmp_path / "billing-service"
    shutil.copytree(
        DEMO,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".sddctx", ".pytest_cache"),
    )
    return target


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SDDCTX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SDDCTX_SQLITE_PATH", str(tmp_path / "home" / "sddctx.db"))
    monkeypatch.setenv("SDDCTX_SEEKDB_PATH", str(tmp_path / "home" / "seekdb"))
    monkeypatch.setenv("SDDCTX_SEEKDB_DATABASE", "sddctx_test")
    monkeypatch.setenv("SDDCTX_SEEKDB_EMBEDDING", "off")
    return Settings.load()


@pytest.fixture()
def store(settings: Settings):
    backend = open_store(settings)
    backend.reset()
    yield backend
    backend.reset()


def make_task(project: Path, **overrides) -> TaskSpec:
    payload = {
        "task_id": "task-test",
        "title": "月度报表支持按销售区域过滤",
        "project": str(project),
        "request": "报表需要按销售区域过滤，并保持原有币种过滤行为不变。",
        "anchors": {
            "spec_ids": ["BR-REPORT-02"],
            "symbols": ["billing.report:build_monthly_report"],
        },
        "must_preserve": [{"spec_id": "BR-REPORT-03", "reason": "汇总口径不变"}],
        "spec_update": [],
        "acceptance_tests": ["acceptance/test_acceptance_report_region.py"],
        "regression_tests": "tests",
        "allowed_paths": ["src/"],
    }
    payload.update(overrides)
    return TaskSpec(**payload)
