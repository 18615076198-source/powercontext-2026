"""资料切分：把规格、代码、测试切成可检索、可引用的最小单元。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import Chunk

SPEC_HEADING = re.compile(r"^##\s+(?P<spec_id>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)\s+(?P<title>.+?)\s*$")
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "runs", ".sddctx", "node_modules"}


def iter_files(root: Path, suffix: str, subdirs: list[str] | None = None) -> list[Path]:
    """遍历工程目录下的指定后缀文件，跳过缓存与产物目录。"""

    bases = [root / sub for sub in subdirs] if subdirs else [root]
    found: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        for path in sorted(base.rglob(f"*{suffix}")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                found.append(path)
    return found


def chunk_specs(root: Path) -> list[Chunk]:
    """按 ``## BR-XXX-01 标题`` 切分规格文件，一条规格一个 chunk。"""

    chunks: list[Chunk] = []
    for path in iter_files(root, ".md", ["specs"]):
        rel = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        heads: list[tuple[int, str, str]] = []
        for index, line in enumerate(lines):
            match = SPEC_HEADING.match(line)
            if match:
                heads.append((index, match.group("spec_id"), match.group("title")))

        for position, (index, spec_id, title) in enumerate(heads):
            end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
            body = "\n".join(lines[index:end]).rstrip()
            chunks.append(
                Chunk(
                    chunk_id=f"spec:{spec_id}",
                    kind="spec",
                    path=rel,
                    symbol=spec_id,
                    title=title,
                    content=body,
                    line_start=index + 1,
                    line_end=end,
                    metadata={"spec_id": spec_id, "file": rel},
                )
            )
    return chunks


def _segment(lines: list[str], node: ast.AST) -> tuple[str, int, int]:
    start = (getattr(node, "lineno", 1) or 1) - 1
    end = getattr(node, "end_lineno", len(lines)) or len(lines)
    return "\n".join(lines[start:end]).rstrip(), start + 1, end


def _names_used(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return sorted(names)


def _chunk_python_file(path: Path, root: Path, kind: str) -> list[Chunk]:
    rel = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    module = ".".join(Path(rel).with_suffix("").parts)
    if module.startswith("src."):
        module = module[len("src.") :]
    chunks: list[Chunk] = []

    def add(node: ast.AST, name: str, title: str) -> None:
        content, start, end = _segment(lines, node)
        if not content.strip():
            return
        symbol = f"{module}:{name}"
        metadata = {"file": rel, "name": name, "module": module, "kind_hint": kind}
        doc = ast.get_docstring(node)  # type: ignore[arg-type]
        if doc:
            metadata["docstring"] = doc.splitlines()[0][:200]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            metadata["signature"] = f"{name}({', '.join(a.arg for a in node.args.args)})"
        if kind == "test":
            metadata["test_id"] = f"{rel}::{name}"
            metadata["names_used"] = _names_used(node)
        chunks.append(
            Chunk(
                chunk_id=f"{kind}:{module}:{name}",
                kind=kind,
                path=rel,
                symbol=symbol,
                title=title,
                content=content,
                line_start=start,
                line_end=end,
                metadata=metadata,
            )
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node, node.name, node.name)
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        add(sub, f"{node.name}.{sub.name}", f"{node.name}.{sub.name}")
    return chunks


def chunk_code(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in iter_files(root, ".py", ["src"]):
        chunks.extend(_chunk_python_file(path, root, "code"))
    return chunks


def chunk_tests(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in iter_files(root, ".py", ["tests"]):
        for chunk in _chunk_python_file(path, root, "test"):
            if chunk.title.startswith("test_"):
                chunks.append(chunk)
    return chunks


def chunk_project(root: Path) -> list[Chunk]:
    """切分整个工程，返回去重后的 chunk 列表。"""

    seen: dict[str, Chunk] = {}
    for chunk in chunk_specs(root) + chunk_code(root) + chunk_tests(root):
        seen.setdefault(chunk.chunk_id, chunk)
    return list(seen.values())
