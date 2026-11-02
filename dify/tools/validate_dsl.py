import yaml, re, sys
from pathlib import Path
p = Path(r"D:\deepseek\dify-work\dsl\cyber-matchmaker.yml")
d = yaml.safe_load(open(p, encoding="utf-8"))
errors = []
nodes = d["workflow"]["graph"]["nodes"]
edges = d["workflow"]["graph"]["edges"]
ids = [n["id"] for n in nodes]
if len(ids) != len(set(ids)):
    errors.append("node id 重复")
by_id = {n["id"]: n for n in nodes}
for e in edges:
    if e["source"] not in by_id: errors.append("edge source 不存在: " + e["source"])
    if e["target"] not in by_id: errors.append("edge target 不存在: " + e["target"])
# 可达性
seen, stack = set(), [ids[0]]
adj = {}
for e in edges: adj.setdefault(e["source"], []).append(e["target"])
while stack:
    cur = stack.pop()
    if cur in seen: continue
    seen.add(cur); stack.extend(adj.get(cur, []))
missing = set(ids) - seen
if missing: errors.append("不可达节点: " + str(missing))
# answer 必须终点
for n in nodes:
    if n["data"]["type"] == "answer" and n["id"] in adj:
        errors.append("answer 节点有出边: " + n["id"])
# 变量引用检查
refs = set()
for n in nodes:
    text = yaml.safe_dump(n, allow_unicode=True)
    for m in re.finditer(r"\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}", text):
        refs.add((m.group(1), m.group(2)))
for sel, var in sorted(refs):
    if sel in ("sys", "env"): continue
    if sel not in by_id: errors.append("变量引用不存在的节点: " + sel + "." + var)
# 节点类型统计
from collections import Counter
print("节点:", Counter(n["data"]["type"] for n in nodes))
print("边:", len(edges), "| 变量引用:", len(refs))
print("检查结果:", "OK" if not errors else errors)
sys.exit(0 if not errors else 1)
