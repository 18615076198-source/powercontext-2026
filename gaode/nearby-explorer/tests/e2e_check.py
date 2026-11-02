"""端到端验收脚本：用命令行跑 10 条中文语句，逐条断言。

断言规则：
  1) status == ok
  2) 候选数 3~5
  3) 每个候选都有交通方案（至少 1 条，且 summary 非空）
  4) 每个候选都有高德跳转链接
  5) 每个候选都有推荐理由

用法：AMAP_MOCK=1 python tests/e2e_check.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "scripts", "nearby_explorer.py")
CASES_FILE = os.path.join(ROOT, "tests", "e2e_cases.json")


def load_cases():
    with open(CASES_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def run_case(case):
    command = [sys.executable, CLI, "--json", "--top", "5"]
    origin = case.get("origin")
    if origin:
        command += ["--origin", "%.6f,%.6f" % (float(origin[0]), float(origin[1]))]
    if case.get("default_city"):
        command += ["--default-city", case["default_city"]]
    command.append(case["query"])

    env = dict(os.environ)
    env["AMAP_MOCK"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    elapsed = time.time() - started
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        payload = None
    return proc, payload, elapsed


def check_case(case):
    proc, payload, elapsed = run_case(case)
    errors = []
    if payload is None:
        errors.append("输出不是合法 JSON（exit=%s）: %s" % (proc.returncode, (proc.stderr or "")[-300:]))
        return None, errors, elapsed
    if payload.get("status") != "ok":
        errors.append("status=%s，message=%s" % (payload.get("status"), payload.get("message")))
        return payload, errors, elapsed
    candidates = payload.get("candidates") or []
    if not 3 <= len(candidates) <= 5:
        errors.append("候选数 %d 不在 3~5" % len(candidates))
    for candidate in candidates:
        name = candidate.get("name") or "?"
        routes = candidate.get("routes") or []
        if not routes:
            errors.append("%s 没有交通方案" % name)
        for route in routes:
            if not route.get("summary"):
                errors.append("%s 的交通方案缺少文案" % name)
        links = candidate.get("links") or {}
        if not links.get("marker") or not links.get("navigation"):
            errors.append("%s 缺少高德链接" % name)
        if not candidate.get("reason"):
            errors.append("%s 缺少推荐理由" % name)
    return payload, errors, elapsed


def main():
    cases = load_cases()
    failures = 0
    total_candidates = 0
    modes = set()
    print("=" * 78)
    print("端到端验收：%d 条中文语句（离线模式 AMAP_MOCK=1）" % len(cases))
    print("=" * 78)
    for case in cases:
        payload, errors, elapsed = check_case(case)
        candidates = (payload or {}).get("candidates") or []
        total_candidates += len(candidates)
        for candidate in candidates:
            for route in candidate.get("routes") or []:
                modes.add(route.get("mode"))
        status = (payload or {}).get("status", "NO-JSON")
        mark = "PASS" if not errors else "FAIL"
        names = "、".join(c.get("name", "?") for c in candidates[:3])
        print("[%s] %-18s %-4s 候选=%d 用时=%.2fs  %s" % (mark, case["id"], status, len(candidates), elapsed, names))
        for error in errors:
            print("       x %s" % error)
        failures += 1 if errors else 0
    print("-" * 78)
    print(
        "汇总：%d/%d 通过，平均候选 %.1f 个，覆盖交通方式 %s"
        % (len(cases) - failures, len(cases), total_candidates / max(1, len(cases)), "、".join(sorted(modes)))
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
