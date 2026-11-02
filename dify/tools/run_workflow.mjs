/**
 * Dify 工作流本地等价执行器（不替代 Dify，用于在没有 Dify 运行时的环境里验证 DSL 接线与后端契约）。
 *
 * 读取 dsl/cyber-matchmaker.yml，按节点逐条执行：
 *   start -> if-else -> http-request -> llm -> answer
 * HTTP 节点真实调用配套后端（seekdb），LLM 节点可调用任意 OpenAI 兼容服务；
 * 未配置 LLM 时退化为模板输出（会在结果里标注）。
 *
 * 用法：
 *   node tools/run_workflow.mjs --profile "程序员，喜欢猫和咖啡" --message "帮我撮合" --vibe 认真
 *   node tools/run_workflow.mjs --llm-base http://127.0.0.1:8080 --llm-model qwen2.5-1.5b-instruct
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    const name = key.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
    out[name] = value;
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const HOST = args.host || "127.0.0.1";
const LLM_BASE = args["llm-base"] || process.env.LLM_BASE_URL || "";
const LLM_KEY = args["llm-key"] || process.env.LLM_API_KEY || "local";
const LLM_MODEL = args["llm-model"] || process.env.LLM_MODEL || "qwen2.5-1.5b-instruct";

const dsl = YAML.parse(await fs.readFile(path.join(ROOT, "dsl", "cyber-matchmaker.yml"), "utf8"));
const graph = dsl.workflow.graph;
const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
const outEdges = new Map();
for (const edge of graph.edges) {
  if (!outEdges.has(edge.source)) outEdges.set(edge.source, []);
  outEdges.get(edge.source).push(edge);
}

const sys = {
  user_id: args.user || "demo-" + Date.now().toString(36),
  query: args.message || "帮我撮合一个对象",
};
const startVars = {
  profile: args.profile || "",
  vibe: args.vibe || "认真",
};

const state = new Map(); // nodeId -> {body, status_code, text, parsed}
const log = { startedAt: new Date().toISOString(), sys, startVars, steps: [] };

function resolveValue(selector) {
  const [id, field] = selector.split(".");
  if (id === "sys") return sys[field] ?? "";
  if (id === "env") return "";
  const output = state.get(id) || {};
  if (field in output) return output[field];
  if (field === "body" && output.parsed) return JSON.stringify(output.parsed);
  return "";
}

function render(template) {
  return String(template ?? "").replace(/\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}/g, (_, id, field) =>
    String(resolveValue(id + "." + field) ?? ""),
  );
}

function nextNode(nodeId, handle) {
  const edges = outEdges.get(nodeId) || [];
  const edge = handle ? edges.find((e) => e.sourceHandle === handle) : edges[0];
  return edge ? edge.target : null;
}

function evalCondition(condition) {
  const left = String(resolveValue((condition.variable_selector || []).join(".")) ?? "");
  const right = String(condition.value ?? "");
  switch (condition.comparison_operator) {
    case "contains":
      return left.includes(right);
    case "not contains":
      return !left.includes(right);
    case "is":
      return left === right;
    case "is not":
      return left !== right;
    case "empty":
      return left.length === 0;
    case "not empty":
      return left.length > 0;
    case "in":
      return right.split(",").map((s) => s.trim()).includes(left);
    default:
      return false;
  }
}

async function callLlm(messages, temperature) {
  if (!LLM_BASE) return null;
  const res = await fetch(LLM_BASE.replace(/\/$/, "") + "/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: "Bearer " + LLM_KEY },
    body: JSON.stringify({ model: LLM_MODEL, messages, temperature: temperature ?? 0.85, max_tokens: 1200 }),
  });
  if (!res.ok) throw new Error("LLM HTTP " + res.status + ": " + (await res.text()).slice(0, 300));
  const data = await res.json();
  return data.choices?.[0]?.message?.content || "";
}

function templateHistory(historyJson) {
  const matches = historyJson?.matches || [];
  const lines = ["## 相亲战报"];
  if (!matches.length) {
    lines.push("你的档案还是空的，先去让月老撮合一次吧。");
  } else {
    for (const item of matches.slice(0, 5)) {
      lines.push("### " + (item.candidates || []).join("、") + " · " + String(item.createdAt).slice(0, 10));
      lines.push("- 月老点评：" + String(item.report || "").split("\n").filter(Boolean).slice(-1)[0]);
    }
    lines.push("## 下一步建议");
    lines.push("同一批角色不要反复相，换点新爱好，缘分池会更大。");
  }
  lines.push("");
  lines.push("> 数据来自 seekdb 记忆库；本地未配置 LLM，以上为模板输出。");
  return lines.join("\n");
}

function templateReport(matchJson) {
  const candidates = matchJson.candidates || [];
  const history = matchJson.history || [];
  const lines = [];
  lines.push("## 月老开场");
  lines.push(
    history.length
      ? "上次你见过「" + (history[0].candidates || []).join("、") + "」，月老可都记着呢。"
      : "第一次来？先坐，喝口茶。",
  );
  lines.push("## 今日撮合");
  candidates.forEach((c, index) => {
    const score = 62 + Math.round((1 - index) * 11 + Math.random() * 8);
    lines.push("### " + (index + 1) + ". " + c.name + " · 缘分指数 " + score);
    lines.push("- 匹配点：" + (c.tags || []).slice(0, 2).join("、") + "；口头禅「" + c.catchphrase + "」");
    lines.push("- 雷点预警：" + (c.redflags || []).join("；"));
    lines.push("- 首次约会建议：" + (c.city || "") + "找个能安静聊天的地方，别去他/她工作的地方。");
  });
  lines.push("## 月老悄悄话");
  lines.push("（本地未配置 LLM，以上为模板输出；接入模型后由月老本人开麦。）");
  lines.push("## 月老签文");
  lines.push("有缘千里来相会，无缘对面不相识。");
  lines.push("");
  lines.push("> 本产品纯属娱乐，月老不负责任何人的人生选择。");
  return lines.join("\n");
}

async function run() {
  let current = graph.nodes.find((n) => n.data.type === "start")?.id;
  const visited = [];
  while (current) {
    const node = nodes.get(current);
    if (!node) break;
    visited.push(current);
    const type = node.data.type;
    const started = Date.now();

    if (type === "start") {
      state.set(current, { ...startVars });
      log.steps.push({ node: current, type, title: node.data.title, ms: Date.now() - started });
      current = nextNode(current);
      continue;
    }

    if (type === "if-else") {
      const caseDef = node.data.cases?.[0];
      const hit = (caseDef?.conditions || []).some((cond) => evalCondition(cond));
      log.steps.push({
        node: current,
        type,
        title: node.data.title,
        ms: Date.now() - started,
        detail: { matched: hit, query: sys.query },
      });
      current = nextNode(current, hit ? "true" : "false");
      continue;
    }

    if (type === "http-request") {
      const raw = node.data.body?.data?.[0]?.value || "";
      const bodyText = render(raw);
      const url = render(node.data.url).replace("host.docker.internal", HOST);
      let response = null;
      let parsed = null;
      let status = 0;
      try {
        const res = await fetch(url, {
          method: (node.data.method || "post").toUpperCase(),
          headers: { "content-type": "text/plain; charset=utf-8" },
          body: bodyText,
        });
        status = res.status;
        response = await res.text();
        parsed = JSON.parse(response);
      } catch (err) {
        status = -1;
        response = String(err.message || err);
      }
      state.set(current, {
        body: parsed ? JSON.stringify(parsed) : response,
        status_code: String(status),
        parsed,
        rawBody: bodyText,
      });
      log.steps.push({
        node: current,
        type,
        title: node.data.title,
        ms: Date.now() - started,
        detail: { url, status, request: bodyText.slice(0, 800), responsePreview: String(response).slice(0, 400) },
      });
      current = nextNode(current);
      continue;
    }

    if (type === "llm") {
      const matchOutput = [...state.entries()].find(([id]) => id === "1700000000003");
      const matchJson = matchOutput?.[1]?.parsed || { candidates: [], history: [] };
      const messages = (node.data.prompt_template || []).map((item) => ({
        role: item.role,
        content: render(item.text),
      }));
      let text = "";
      let llmMode = "template";
      const temperature = node.data.model?.completion_params?.temperature;
      const remote = await callLlm(messages, temperature).catch((err) => {
        log.steps.push({ node: current, type, title: node.data.title, error: String(err.message || err) });
        return null;
      });
      if (remote) {
        text = remote;
        llmMode = "llm:" + LLM_MODEL;
      } else if (current === "1700000000008") {
        text = templateHistory(state.get("1700000000007")?.parsed);
      } else {
        text = templateReport(matchJson);
      }
      state.set(current, { text });
      log.steps.push({
        node: current,
        type,
        title: node.data.title,
        ms: Date.now() - started,
        detail: { mode: llmMode, promptChars: messages.reduce((sum, m) => sum + m.content.length, 0), outputChars: text.length },
      });
      current = nextNode(current);
      continue;
    }

    if (type === "answer") {
      const answer = render(node.data.answer);
      state.set(current, { text: answer });
      log.steps.push({ node: current, type, title: node.data.title, ms: Date.now() - started });
      console.log("\n===== 月老回复 =====\n");
      console.log(answer);
      console.log("\n====================");
      log.answer = answer;
      current = null;
      continue;
    }

    current = nextNode(current);
  }
  log.finishedAt = new Date().toISOString();
  log.visited = visited;
  return log;
}

const result = await run();
await fs.mkdir(path.join(ROOT, "evidence"), { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outFile = path.join(ROOT, "evidence", "run-" + stamp + ".json");
await fs.writeFile(outFile, JSON.stringify(result, null, 2));
console.log("\n[evidence] " + path.relative(ROOT, outFile));
console.log("[nodes] " + result.visited.join(" -> "));

if (args.save) {
  const transcript = [
    "# 工作流运行记录",
    "",
    "- 时间：" + new Date().toISOString(),
    "- 用户：" + sys.user_id,
    "- 输入：" + sys.query,
    "- 简历：" + (startVars.profile || "(空)"),
    "- 模式：" + (startVars.vibe || "(空)"),
    "- 执行节点：" + result.visited.join(" -> "),
    "",
    "## 月老回复",
    "",
    result.answer || "(无输出)",
    "",
  ].join("\n");
  await fs.writeFile(path.resolve(ROOT, args.save), transcript);
  console.log("[saved] " + args.save);
}
