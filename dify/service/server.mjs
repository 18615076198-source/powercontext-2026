/**
 * 赛博月老配套后端：Dify 通过 HTTP Request 节点调用。
 *
 *   POST /api/match    按简历 + 聊天内容检索 3 位候选人（seekdb 混合检索）
 *   POST /api/archive  把本次相亲批语写入 seekdb（记忆）
 *   POST /api/history  读取某位用户的相亲档案
 *   POST /api/seed     重建 24 位角色池
 *   GET  /health       健康检查
 */
import express from "express";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { MatchmakerStore } from "./store.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 7870);
const personas = JSON.parse(await fs.readFile(path.join(__dirname, "personas.json"), "utf8"));

const store = await new MatchmakerStore().init();
const initial = await store.stats();
if (initial.personas === 0) {
  console.log("[seed] 角色池为空，正在初始化 " + personas.length + " 位角色…");
  await store.seed(personas);
}

const app = express();
app.use(express.json({ limit: "4mb" }));
// Dify 的 HTTP 节点用 raw-text body 传结构化文本，避免 JSON 字符串里出现引号/换行导致转义问题
app.use(express.text({ type: () => true, limit: "4mb" }));

function parseBlocks(req) {
  if (req.is("application/json")) return req.body || {};
  const raw = typeof req.body === "string" ? req.body : "";
  const out = {};
  let key = null;
  for (const line of raw.split(/\r?\n/)) {
    const match = /^([A-Z][A-Z_]{1,20})=(.*)$/.exec(line);
    if (match) {
      key = match[1].toLowerCase();
      out[key] = match[2];
    } else if (key) {
      out[key] = (out[key] || "") + "\n" + line;
    }
  }
  return out;
}

const personaNames = personas.map((item) => item.name);

function extractCandidates(report, explicit) {
  if (Array.isArray(explicit) && explicit.length) {
    return explicit.map((item) => (typeof item === "string" ? item : item.name)).filter(Boolean);
  }
  return personaNames.filter((name) => String(report || "").includes(name));
}
app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "content-type");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

app.get("/health", async (_req, res, next) => {
  try {
    res.json({ ok: true, ...(await store.stats()) });
  } catch (err) {
    next(err);
  }
});

app.post("/api/seed", async (_req, res, next) => {
  try {
    res.json({ ok: true, ...(await store.seed(personas)) });
  } catch (err) {
    next(err);
  }
});

app.get("/api/personas", async (_req, res, next) => {
  try {
    res.json({ personas: await store.listPersonas() });
  } catch (err) {
    next(err);
  }
});

app.post("/api/match", async (req, res, next) => {
  try {
    const body = parseBlocks(req);
    const { user = "anonymous", profile = "", message = "", vibe = "", topK = 3 } = body;
    if (!profile && !message) {
      return res.status(400).json({ error: "profile 或 message 至少提供一个" });
    }
    const result = await store.match({ user, profile, message, vibe, topK: Number(topK) || 3 });
    res.json(result);
  } catch (err) {
    next(err);
  }
});

app.post("/api/archive", async (req, res, next) => {
  try {
    const body = parseBlocks(req);
    const { user = "anonymous", profile = "", report = "" } = body;
    if (!String(report).trim()) return res.status(400).json({ error: "report 不能为空" });
    const candidates = extractCandidates(report, body.candidates);
    res.json(await store.archive({ user, profile, candidates, report }));
  } catch (err) {
    next(err);
  }
});

app.post("/api/history", async (req, res, next) => {
  try {
    const body = parseBlocks(req);
    const { user = "anonymous", limit = 5 } = body;
    const matches = await store.history(user, Number(limit) || 5);
    res.json({ user, count: matches.length, matches });
  } catch (err) {
    next(err);
  }
});

app.use((err, _req, res, _next) => {
  console.error("[server]", err);
  res.status(500).json({ error: err.message || String(err) });
});

const server = app.listen(PORT, "0.0.0.0", () => {
  console.log("赛博月老后端已启动: http://0.0.0.0:" + PORT);
  console.log("seekdb: " + store.version + " | personas=" + personas.length);
});

async function shutdown() {
  server.close();
  await store.close().catch(() => {});
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
