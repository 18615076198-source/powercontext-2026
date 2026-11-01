"""验证：功能测试（新行为）+ 回归测试（原有行为必须保持）。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

RESULT_LINE = re.compile(
    r"^(?P<nodeid>\S+\.py::\S+?)\s+(?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b"
)
SUMMARY = re.compile(r"(?P<count>\d+)\s+(?P<kind>passed|failed|error|errors|skipped)")


@dataclass
class SuiteResult:
    name: str
    command: str
    returncode: int
    duration_s: float
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    tests: list[dict] = field(default_factory=list)
    output_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.failed == 0 and self.errors == 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 2),
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "tests": self.tests,
            "output_tail": self.output_tail,
            "ok": self.ok,
        }


def parse_pytest_output(text: str) -> dict:
    tests: list[dict] = []
    counters = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for line in text.splitlines():
        match = RESULT_LINE.match(line.strip())
        if match:
            outcome = match.group("outcome")
            tests.append({"nodeid": match.group("nodeid"), "outcome": outcome})
            if outcome == "PASSED":
                counters["passed"] += 1
            elif outcome == "FAILED":
                counters["failed"] += 1
            elif outcome == "ERROR":
                counters["errors"] += 1
            elif outcome == "SKIPPED":
                counters["skipped"] += 1

    # 兜底：用例级别的行可能被 -q 之类配置抑制，改为读汇总行
    summary: dict[str, int] = {}
    for line in text.splitlines():
        if " in " in line and ("passed" in line or "failed" in line or "error" in line):
            for match in SUMMARY.finditer(line):
                kind = match.group("kind")
                if kind in {"error", "errors"}:
                    summary["errors"] = int(match.group("count"))
                elif kind in counters:
                    summary[kind] = int(match.group("count"))
    for key, value in summary.items():
        counters[key] = max(counters[key], value)
    return {"tests": tests, **counters}


def run_pytest(
    project_root: Path,
    targets: list[str],
    *,
    name: str,
    timeout: int = 300,
    cwd: Path | None = None,
) -> SuiteResult:
    """在工程目录内跑 pytest，逐条收集结果。"""

    working_dir = cwd or project_root
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",  # 屏蔽工程自带 addopts，保证拿到逐条用例结果
        "-v",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        *targets,
    ]
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = f"pytest 超时（>{timeout}s）: {exc}"
        returncode = 124
    duration = time.time() - started
    parsed = parse_pytest_output(output)
    return SuiteResult(
        name=name,
        command=" ".join(command),
        returncode=returncode,
        duration_s=duration,
        passed=parsed["passed"],
        failed=parsed["failed"],
        errors=parsed["errors"],
        skipped=parsed["skipped"],
        tests=parsed["tests"],
        output_tail="\n".join(output.strip().splitlines()[-25:]),
    )


def run_acceptance(
    project_root: Path,
    acceptance_files: list[Path],
    *,
    name: str = "functional",
    timeout: int = 300,
) -> SuiteResult:
    """把验收测试临时放进工程内运行，结束后清理，保证不污染仓库。"""

    staging = project_root / ".sddctx" / "acceptance"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for source in acceptance_files:
            shutil.copy2(source, staging / source.name)
        relative = [f".sddctx/acceptance/{source.name}" for source in acceptance_files]
        return run_pytest(project_root, relative, name=name, timeout=timeout)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
