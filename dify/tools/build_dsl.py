#!/usr/bin/env python3
"""生成 Dify Chatflow DSL（赛博月老·缘分交易所）。改完直接重新生成本文件即可。"""
import json
import uuid
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dsl" / "cyber-matchmaker.yml"

N_START = "1700000000001"
N_IF = "1700000000002"
N_MATCH = "1700000000003"
N_LLM_MATCH = "1700000000004"
N_ARCHIVE = "1700000000005"
N_ANSWER_MATCH = "1700000000006"
N_HISTORY = "1700000000007"
N_LLM_HISTORY = "1700000000008"
N_ANSWER_HISTORY = "1700000000009"

BASE_URL = "http://host.docker.internal:7870"

SYSTEM_MATCH = """你是「赛博月老 · 缘分交易所」的月老，编号 OB-2026。你阅人无数、毒舌但心软，擅长用一杯茶的时间看穿两个人的灵魂（和雷点）。

【检索结果】以下是系统用 seekdb 混合检索（向量 + 全文 + RRF 融合）为这位客人找到的候选人，它是你唯一的事实来源：
{{#%s.body#}}

【铁律】
1. 只能介绍检索结果里出现的人，不得虚构姓名、职业、爱好、城市。名单为空就诚实说「今天缘分池没捞到人」。
2. 每位候选人必须逐字引用：一句 catchphrase（用「」括起来）、至少一个 tags、一条 redflags。
3. 缘分指数用 0-100 整数，分数必须能追溯到共同点（例如「你写代码他写诗，都是夜猫子」）。
4. 检索结果里的 history 是本客人的历史相亲记录：非空时开场必须先回访一次（「上次你见过……」），为空时先给客人递一杯茶。
5. 语气像老茶馆里说媒：口语、有梗、不端着；不要客服腔，不要空话。
6. 结尾必须加一句免责声明：本产品纯属娱乐，月老不负责任何人的人生选择。

【输出格式】Markdown：
## 月老开场
（1-2 句）
## 今日撮合
### 1. 名字 · 缘分指数 NN
- 匹配点：……
- 雷点预警：……（引用 redflags 原文）
- 首次约会建议：……
（最多 3 位，按缘分指数从高到低）
## 月老悄悄话
（1-2 句，损一点）
## 月老签文
（四句短句，可押韵）""" % N_MATCH

USER_MATCH = """我的相亲简历：
{{#%s.profile#}}

我刚刚说：{{#sys.query#}}
月老模式：{{#%s.vibe#}}""" % (N_START, N_START)

SYSTEM_HISTORY = """你是「赛博月老 · 缘分交易所」的档案管理员，负责把客人的相亲历史整理成一份损人不伤人的「相亲战报」。

【档案数据】来自 seekdb 的记忆记录（候选人、批语、时间）：
{{#%s.body#}}

【规则】
1. 只使用档案里出现的事实，不得编造候选人或批语。
2. 如果档案为空，直接告诉客人「你的档案还是空的」，并邀请他先做一次撮合。
3. 输出 Markdown：## 相亲战报 / 每位候选人一行小结 + 一条「月老点评」/ 结尾给「下一步建议」。
4. 语气轻快、毒舌但善意；结尾注明数据来自 seekdb 记忆库。""" % N_HISTORY

USER_HISTORY = """我想看看我的相亲档案。
我刚刚说：{{#sys.query#}}"""


def node(node_id, node_type, title, x, y, extra, width=244, height=140):
    data = {"type": node_type, "title": title, "desc": "", "selected": False}
    data.update(extra)
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "width": width,
        "height": height,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": data,
    }


def edge(src, dst, src_type, dst_type, handle="source"):
    return {
        "data": {"isInIteration": False, "sourceType": src_type, "targetType": dst_type},
        "id": "%s-%s-%s-target" % (src, handle, dst),
        "selected": False,
        "source": src,
        "sourceHandle": handle,
        "target": dst,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
    }


def http_node(node_id, title, path, text_body, description="", x=0, y=0):
    return node(
        node_id,
        "http-request",
        title,
        x,
        y,
        {
            "authorization": {"type": "no-auth", "config": None},
            "body": {
                "type": "raw-text",
                "data": [{"id": "key-value-1", "key": "", "type": "text", "value": text_body}],
            },
            "headers": "",
            "method": "post",
            "params": "",
            "retry_config": {"max_retries": 1, "retry_enabled": False, "retry_interval": 100},
            "timeout": {"max_connect_timeout": 0, "max_read_timeout": 0, "max_write_timeout": 0},
            "url": BASE_URL + path,
            "variables": [],
        },
        height=150,
    )


def llm_node(node_id, title, system_prompt, user_prompt, x, y):
    return node(
        node_id,
        "llm",
        title,
        x,
        y,
        {
            "context": {"enabled": False, "variable_selector": []},
            "model": {
                "provider": "langgenius/openai/openai",
                "name": "gpt-4o-mini",
                "mode": "chat",
                "completion_params": {"temperature": 0.85, "max_tokens": 1200},
            },
            "prompt_template": [
                {"id": str(uuid.uuid4()), "role": "system", "text": system_prompt},
                {"id": str(uuid.uuid4()), "role": "user", "text": user_prompt},
            ],
            "variables": [],
            "vision": {"enabled": False, "configs": {"detail": "high"}},
        },
        height=180,
    )


start_node = node(
    N_START,
    "start",
    "开始",
    30,
    320,
    {
        "variables": [
            {
                "variable": "profile",
                "label": "你的相亲简历（昵称/年龄/爱好/雷点/想要的关系）",
                "type": "paragraph",
                "required": False,
                "max_length": 2000,
                "options": [],
                "allowed_file_extensions": [],
                "allowed_file_types": ["image"],
                "allowed_file_upload_methods": ["local_file", "remote_url"],
            },
            {
                "variable": "vibe",
                "label": "今日月老模式",
                "type": "select",
                "required": False,
                "max_length": 48,
                "options": ["认真", "发疯", "抽象"],
                "allowed_file_extensions": [],
                "allowed_file_types": ["image"],
                "allowed_file_upload_methods": ["local_file", "remote_url"],
            },
        ]
    },
    height=190,
)

if_node = node(
    N_IF,
    "if-else",
    "查档案还是撮合？",
    330,
    320,
    {
        "cases": [
            {
                "case_id": "true",
                "id": "true",
                "logical_operator": "or",
                "conditions": [
                    {
                        "id": str(uuid.uuid4()),
                        "comparison_operator": "contains",
                        "value": keyword,
                        "varType": "string",
                        "variable_selector": ["sys", "query"],
                    }
                    for keyword in ("档案", "历史", "战报")
                ],
            }
        ]
    },
    height=150,
)

match_node = http_node(
    N_MATCH,
    "seekdb 检索候选人",
    "/api/match",
    "USER={{#sys.user_id#}}\nPROFILE={{#%s.profile#}}\nMESSAGE={{#sys.query#}}\nVIBE={{#%s.vibe#}}\nTOP_K=3"
    % (N_START, N_START),
    x=640,
    y=470,
)
llm_match_node = llm_node(N_LLM_MATCH, "月老撮合", SYSTEM_MATCH, USER_MATCH, 960, 470)
archive_node = http_node(
    N_ARCHIVE,
    "写入相亲档案（seekdb）",
    "/api/archive",
    "USER={{#sys.user_id#}}\nPROFILE={{#%s.profile#}}\nREPORT={{#%s.text#}}" % (N_START, N_LLM_MATCH),
    x=1280,
    y=470,
)
answer_match_node = node(
    N_ANSWER_MATCH,
    "answer",
    "直接回复",
    1600,
    470,
    {"answer": "{{#%s.text#}}" % N_LLM_MATCH, "variables": []},
    height=110,
)

history_node = http_node(
    N_HISTORY,
    "读取相亲档案（seekdb）",
    "/api/history",
    "USER={{#sys.user_id#}}\nLIMIT=5",
    x=640,
    y=120,
)
llm_history_node = llm_node(N_LLM_HISTORY, "档案管理员", SYSTEM_HISTORY, USER_HISTORY, 960, 120)
answer_history_node = node(
    N_ANSWER_HISTORY,
    "answer",
    "直接回复",
    1280,
    120,
    {"answer": "{{#%s.text#}}" % N_LLM_HISTORY, "variables": []},
    height=110,
)

dsl = {
    "app": {
        "description": "把相亲简历丢进缘分交易所，AI 月老用 seekdb 混合检索在 24 位奇葩角色里撮合，并把每次批语写进档案——下次它还记得你上次为什么黄了。",
        "icon": "💘",
        "icon_background": "#FFE4E6",
        "mode": "advanced-chat",
        "name": "赛博月老·缘分交易所",
        "use_icon_as_answer_icon": False,
    },
    "dependencies": [],
    "kind": "app",
    "version": "0.1.5",
    "workflow": {
        "conversation_variables": [],
        "environment_variables": [],
        "features": {
            "file_upload": {
                "allowed_file_extensions": [".JPG", ".JPEG", ".PNG", ".GIF", ".WEBP", ".SVG"],
                "allowed_file_types": ["image"],
                "allowed_file_upload_methods": ["local_file", "remote_url"],
                "enabled": False,
                "fileUploadConfig": {
                    "audio_file_size_limit": 50,
                    "batch_count_limit": 5,
                    "file_size_limit": 15,
                    "image_file_size_limit": 10,
                    "video_file_size_limit": 100,
                    "workflow_file_upload_limit": 10,
                },
                "image": {"enabled": False, "number_limits": 3, "transfer_methods": ["local_file", "remote_url"]},
                "number_limits": 3,
            },
            "opening_statement": "月老在的。把简历丢过来，或者先说一句「查档案」。",
            "retriever_resource": {"enabled": True},
            "sensitive_word_avoidance": {"enabled": False},
            "speech_to_text": {"enabled": False},
            "suggested_questions": [
                "帮我撮合一下：程序员，喜欢猫和手冲咖啡，周末想去看展",
                "查一下我的相亲档案",
            ],
            "suggested_questions_after_answer": {"enabled": False},
            "text_to_speech": {"enabled": False, "language": "", "voice": ""},
        },
        "graph": {
            "edges": [
                edge(N_START, N_IF, "start", "if-else"),
                edge(N_IF, N_HISTORY, "if-else", "http-request", handle="true"),
                edge(N_IF, N_MATCH, "if-else", "http-request", handle="false"),
                edge(N_HISTORY, N_LLM_HISTORY, "http-request", "llm"),
                edge(N_LLM_HISTORY, N_ANSWER_HISTORY, "llm", "answer"),
                edge(N_MATCH, N_LLM_MATCH, "http-request", "llm"),
                edge(N_LLM_MATCH, N_ARCHIVE, "llm", "http-request"),
                edge(N_ARCHIVE, N_ANSWER_MATCH, "http-request", "answer"),
            ],
            "nodes": [
                start_node,
                if_node,
                history_node,
                llm_history_node,
                answer_history_node,
                match_node,
                llm_match_node,
                archive_node,
                answer_match_node,
            ],
        },
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
    yaml.safe_dump(dsl, handle, allow_unicode=True, sort_keys=False, width=1200)
print("written:", OUT)
