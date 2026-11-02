#!/usr/bin/env python3
"""把 nearby-explorer 打包成 ModelScope Skill zip。

- 在 SKILL.md 正文末尾追加平台验证行（独立一行、原样保留）；
- 校验 frontmatter（name/version/description）与 zip 结构（根目录恰好一个 SKILL.md）；
- 输出 dist/nearby-explorer-<sha>.zip 和同名 manifest.json。

用法：
  python build_skill.py --verify-line "平台弹窗里复制的那一整行"
  python build_skill.py --verify-line-file verify.txt
  python build_skill.py --verify-line "..." --out dist/custom.zip
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "nearby-explorer"
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "dist", "tests"}


def fail(msg: str) -> None:
    print("[FAIL] " + msg, file=sys.stderr)
    raise SystemExit(1)


def read_verify_line(args) -> str:
    if args.verify_line_file:
        raw = Path(args.verify_line_file).read_text(encoding="utf-8")
    else:
        raw = args.verify_line or ""
    line = raw.replace("\r\n", "\n").strip("\n")
    if "\n" in line:
        fail("验证行必须是单行文本（当前包含换行）")
    line = line.strip()
    if not line:
        fail("缺少验证行：请从提测弹窗复制完整验证行，用 --verify-line 传入")
    return line


def parse_frontmatter(text: str):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        fail("SKILL.md 缺少 YAML frontmatter")
    fm = match.group(1)
    values = {}
    for key in ("name", "version", "description"):
        m = re.search(r"^" + key + r":\s*(.+)$", fm, re.M)
        if not m:
            fail("frontmatter 缺少字段: " + key)
        values[key] = m.group(1).strip()
    return values


def append_verify_line(skill_md: Path, line: str) -> None:
    text = skill_md.read_text(encoding="utf-8").rstrip("\n")
    skill_md.write_text(text + "\n\n" + line + "\n", encoding="utf-8")


def stage(verify_line: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ms-skill-"))
    target = tmp / "nearby-explorer"
    shutil.copytree(
        SRC,
        target,
        ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc", "*.log"),
    )
    append_verify_line(target / "SKILL.md", verify_line)
    return target


def build_zip(staging: Path, out: Path, verify_line: str) -> dict:
    front = parse_frontmatter((staging / "SKILL.md").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", front["name"]):
        fail("skill name 只能是小写字母、数字和连字符: " + front["name"])

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    file_count = 0
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(staging).as_posix()
            zf.write(path, rel)
            file_count += 1
            total += path.stat().st_size

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        root_skill = [n for n in names if n.count("/") == 0 and n.endswith("SKILL.md")]
        if len(root_skill) != 1:
            fail("zip 根目录必须恰好有一个 SKILL.md，当前: " + str(root_skill))
        if any(n.startswith("nearby-explorer/") for n in names):
            fail("zip 内不能多套一层目录")
        final_text = zf.read("SKILL.md").decode("utf-8")
        last_line = [line for line in final_text.splitlines() if line.strip()][-1]
        if last_line.strip() != verify_line:
            fail("SKILL.md 末尾不是验证行（实际最后一行: " + last_line[:60] + "）")

    size = out.stat().st_size
    if size > 5 * 1024 * 1024:
        fail("zip 超过 5MB 限制: " + str(size))

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    manifest = {
        "skill": front["name"],
        "version": front["version"],
        "zip": str(out),
        "bytes": size,
        "sha256": digest,
        "files": file_count,
        "uncompressedBytes": total,
        "verifyLine": verify_line,
        "builtAt": datetime.now(timezone.utc).isoformat(),
    }
    out.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 ModelScope Skill")
    parser.add_argument("--verify-line", default="")
    parser.add_argument("--verify-line-file", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if not SRC.is_dir():
        fail("找不到源目录: " + str(SRC))
    verify_line = read_verify_line(args)

    staging = stage(verify_line)
    out = Path(args.out) if args.out else (ROOT / "dist" / ("nearby-explorer-" + hashlib.sha1(verify_line.encode()).hexdigest()[:8] + ".zip"))
    manifest = build_zip(staging, out, verify_line)
    shutil.rmtree(staging.parent, ignore_errors=True)

    print("zip:      " + manifest["zip"])
    print("size:     " + "%.1f KB" % (manifest["bytes"] / 1024))
    print("sha256:   " + manifest["sha256"])
    print("files:    " + str(manifest["files"]))
    print("验证行:   " + manifest["verifyLine"])
    print("manifest: " + str(out.with_suffix('.manifest.json')))
    return 0


if __name__ == "__main__":
    sys.exit(main())
