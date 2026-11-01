"""MiniMax 调用与改动落地。

设计取舍：让模型输出「整文件重写」而不是 unified diff，
再用本地护栏（路径白名单、Python 语法校验、公共符号保留）兜住风险，
最后由我们生成统一的 diff 作为交付物。diff 逆向失败比整文件替换更常见，
这样可以把不确定性留在模型侧、把确定性留给校验侧。
"""

from __future__ import annotations

import ast
import difflib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

FILE_BLOCK = re.compile(r"===\s*FILE:\s*(?P<path>[^\n=]+?)\s*===\n(?P<body>.*?)\n?===\s*END FILE\s*===", re.S)

SYSTEM_PROMPT = """你是一名严格的代码修改助手，服务于「规格驱动开发」流程。
你只能依据给定的规格条目修改代码，不得臆造规格中不存在的行为。

输出协议（必须严格遵守）：
1. 只输出需要改动的文件，每个文件用如下分隔符包裹，路径必须是相对项目根目录的 POSIX 路径：
=== FILE: <relative/path.py> ===
<该文件修改后的完整内容>
=== END FILE ===
2. 不要输出 unified diff、不要输出解释性段落、不要使用 Markdown 代码围栏。
3. 未修改的文件不要输出。文件内容必须是完整可运行的新版本，而不是片段。
4. 只能修改允许路径下的文件；测试与规格由人工维护，禁止改动。
"""


@dataclass
class MiniMaxCall:
    model: str
    base_url: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    request_id: str = ""
    prompt_chars: int = 0
    response_chars: int = 0
    attempt: int = 1
    error: str = ""
    response_text: str = field(default="", repr=False)

    def to_trace(self) -> dict:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "request_id": self.request_id,
            "prompt_chars": self.prompt_chars,
            "response_chars": self.response_chars,
            "attempt": self.attempt,
            "error": self.error,
        }


class MiniMaxClient:
    """MiniMax OpenAI 兼容接口的最小客户端。"""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.last_call: MiniMaxCall | None = None

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 8000,
        attempt: int = 1,
        retries: int = 3,
    ) -> str:
        """调用一次聊天补全；网络抖动自动重试，失败时保留最后一次调用记录。"""

        last_error: Exception | None = None
        for round_index in range(1, retries + 1):
            try:
                return self._chat_once(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    attempt=attempt,
                    round_index=round_index,
                )
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
                last_error = error
                if round_index == retries:
                    break
                time.sleep(2 * round_index)
        raise RuntimeError(f"MiniMax 调用在 {retries} 次尝试后仍失败：{last_error}")

    def _chat_once(
        self,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
        attempt: int,
        round_index: int,
    ) -> str:
        if not self.settings.minimax_api_key:
            raise RuntimeError("未配置 MINIMAX_API_KEY，无法调用 MiniMax")
        payload = {
            "model": self.settings.minimax_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 代码补丁较长，用流式接收避免长连接静默超时被中间设备重置
            "stream": True,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.minimax_base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.settings.minimax_api_key}",
            },
        )
        started = time.time()
        call = MiniMaxCall(
            model=self.settings.minimax_model,
            base_url=self.settings.minimax_base_url,
            latency_ms=0,
            prompt_chars=sum(len(message["content"]) for message in messages),
            attempt=attempt,
        )
        chunks: list[str] = []
        try:
            with urllib.request.urlopen(request, timeout=self.settings.minimax_timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    call.request_id = call.request_id or str(event.get("id") or "")
                    usage = event.get("usage") or {}
                    if usage:
                        call.prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        call.completion_tokens = int(usage.get("completion_tokens") or 0)
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or choice.get("message") or {}
                        piece = delta.get("content")
                        if piece:
                            chunks.append(piece)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:600]
            call.latency_ms = int((time.time() - started) * 1000)
            call.error = f"HTTP {error.code}: {detail}"
            self.last_call = call
            raise RuntimeError(f"MiniMax 调用失败 {call.error}") from error
        except Exception as error:
            call.latency_ms = int((time.time() - started) * 1000)
            call.error = f"{type(error).__name__}: {error}"
            call.response_chars = len("".join(chunks))
            self.last_call = call
            raise

        text = "".join(chunks)
        call.latency_ms = int((time.time() - started) * 1000)
        call.response_chars = len(text)
        call.response_text = text
        self.last_call = call
        return text


def build_messages(pack: dict) -> list[dict]:
    """把上下文包渲染成模型消息。"""

    spec_block = "\n\n".join(
        f"[{entry['spec_id']}] {entry['title']}\n{entry['content']}" for entry in pack["specs"]
    )
    must_keep = "\n".join(
        f"- {item.get('spec_id', '')}: {item.get('reason', '')}" for item in pack["guards"]["must_preserve"]
    )
    files_block = "\n\n".join(
        f"### 现有文件：{path}\n```python\n{content}```" for path, content in pack["full_files"].items()
    )
    tests_block = "\n\n".join(
        f"- {entry['test_id']} ({entry['path']}:{entry['line_start']})\n{entry['content']}"
        for entry in pack["tests"]
    )
    user = f"""# 任务
{pack['task_title']}

## 需求原文
{pack.get('request', '')}

# 必须遵守的规格条目
{spec_block or '（无）'}

# 必须保持的既有行为（回归红线）
{must_keep or '（无）'}

# 现有代码
{files_block or '（无）'}

# 相关测试（只读，用于理解约束，不得修改）
{tests_block or '（无）'}

# 改动约束
- 只允许修改这些路径：{', '.join(pack['guards']['allowed_paths'])}
- 禁止修改：{', '.join(pack['guards']['forbidden_paths'])}
- 保持现有公共函数名与签名，除非规格明确要求变更
- 新增参数必须提供默认值，保证旧调用方式不变

请按输出协议给出修改后的完整文件。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_file_blocks(text: str) -> dict[str, str]:
    """解析模型输出中的文件块。"""

    files: dict[str, str] = {}
    for match in FILE_BLOCK.finditer(text):
        path = match.group("path").strip()
        body = match.group("body")
        if body.startswith("```"):
            body = body.split("\n", 1)[1] if "\n" in body else body
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        files[path] = body.strip("\n") + "\n"
    return files


def _normalise(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("/")


def validate_change(
    files: dict[str, str],
    project_root: Path,
    *,
    allowed_paths: list[str],
    forbidden_paths: list[str],
) -> list[str]:
    """护栏：路径白名单、语法合法性、禁止改动测试与规格。"""

    errors: list[str] = []
    if not files:
        errors.append("模型输出中没有解析到任何文件块")
        return errors
    for raw_path, content in files.items():
        path = _normalise(raw_path)
        if ".." in path.split("/"):
            errors.append(f"{raw_path}: 路径包含上级目录跳转")
            continue
        if forbidden_paths and any(path.startswith(prefix) for prefix in forbidden_paths):
            errors.append(f"{raw_path}: 禁止修改测试/规格目录")
            continue
        if allowed_paths and not any(path.startswith(prefix) for prefix in allowed_paths):
            errors.append(f"{raw_path}: 不在允许修改的路径内（{', '.join(allowed_paths)}）")
            continue
        if not (project_root / path).is_file():
            errors.append(f"{raw_path}: 目标文件不存在，禁止新建未登记文件")
            continue
        if not content.strip():
            errors.append(f"{raw_path}: 输出内容为空")
            continue
        if path.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as exc:
                errors.append(f"{raw_path}: Python 语法错误 {exc.msg} (line {exc.lineno})")
    return errors


def keep_public_symbols(files: dict[str, str], before: dict[str, str]) -> list[str]:
    """检查原有公共函数是否被删除（防止模型顺手重构掉兼容性）。"""

    problems: list[str] = []
    for path, old_source in before.items():
        new_source = files.get(path)
        if new_source is None:
            continue
        try:
            old_tree = ast.parse(old_source)
            new_tree = ast.parse(new_source)
        except SyntaxError:
            continue
        old_defs = {node.name for node in old_tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        new_defs = {node.name for node in new_tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        missing = {name for name in old_defs - new_defs if not name.startswith("_")}
        for name in sorted(missing):
            problems.append(f"{path}: 公共符号 {name} 被删除")
    return problems


def apply_files(files: dict[str, str], project_root: Path) -> tuple[list[str], str]:
    """写入文件并生成统一 diff（before/after）。"""

    applied: list[str] = []
    diff_parts: list[str] = []
    for raw_path, content in files.items():
        path = _normalise(raw_path)
        target = project_root / path
        old = target.read_text(encoding="utf-8")
        diff_parts.append(
            "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
        )
        target.write_text(content, encoding="utf-8")
        applied.append(path)
    return applied, "".join(diff_parts)
