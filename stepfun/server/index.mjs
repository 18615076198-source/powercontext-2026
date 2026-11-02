/**
 * HTTP 服务：静态前端 + seekdb 会话/导入/检索 API。
 * 浏览器负责 embedding，服务端只负责 seekdb 存储与混合检索。
 */
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { KnowledgeStore } from "./store.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.env.PORT || 7860);

const app = express();
app.use(express.json({ limit: "32mb" }));
// 开启跨源隔离：让 WASM 多线程（SharedArrayBuffer）可用
app.use((_req, res, next) => {
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  next();
});
app.use(express.static(path.join(ROOT, "web"), { extensions: ["html"], maxAge: 0 }));
app.use("/data", express.static(path.join(ROOT, "data"), { maxAge: 0 }));

import fs from "node:fs";
const vendorWasm = path.join(ROOT, "web", "vendor", "ort-wasm-simd-threaded.wasm");
if (!fs.existsSync(vendorWasm)) {
  console.warn("[warn] web/vendor 缺少 ORT wasm，请先执行 npm run prepare:web（npm start 已自动执行）");
}
const modelFile = path.join(ROOT, "web", "models", "Xenova", "bge-small-zh-v1.5", "onnx", "model_quantized.onnx");
if (!fs.existsSync(modelFile)) {
  console.warn("[warn] 未找到内置 INT8 模型，请执行 npm run fetch-model 下载");
}

const store = await new KnowledgeStore().init();
const sessions = new Map();

function touch(sessionId) {
  const info = sessions.get(sessionId) || { createdAt: Date.now() };
  info.lastSeen = Date.now();
  sessions.set(sessionId, info);
  return info;
}

app.get("/api/health", async (_req, res) => {
  res.json({
    ok: true,
    seekdb: store.version,
    dimension: store.dimension,
    database: process.env.SEEKDB_DB || "stepfun_kb",
    sessions: sessions.size,
  });
});

app.post("/api/session", async (_req, res, next) => {
  try {
    const sid = randomBytes(6).toString("hex");
    await store.ensureCollection(sid);
    touch(sid);
    res.json({ sessionId: sid, ...(await store.stats(sid)) });
  } catch (err) {
    next(err);
  }
});

app.get("/api/session/:sid", async (req, res, next) => {
  try {
    touch(req.params.sid);
    res.json({ sessionId: req.params.sid, ...(await store.stats(req.params.sid)) });
  } catch (err) {
    next(err);
  }
});

app.post("/api/session/:sid/reset", async (req, res, next) => {
  try {
    touch(req.params.sid);
    await store.reset(req.params.sid);
    res.json({ sessionId: req.params.sid, ...(await store.stats(req.params.sid)) });
  } catch (err) {
    next(err);
  }
});

app.post("/api/session/:sid/ingest", async (req, res, next) => {
  try {
    touch(req.params.sid);
    const docs = Array.isArray(req.body?.docs) ? req.body.docs : [];
    const started = Date.now();
    const result = await store.ingest(req.params.sid, docs);
    res.json({ ...result, serverMs: Date.now() - started });
  } catch (err) {
    next(err);
  }
});

app.post("/api/session/:sid/search", async (req, res, next) => {
  try {
    touch(req.params.sid);
    const { query, embedding, topK } = req.body || {};
    if (!query || !Array.isArray(embedding)) {
      return res.status(400).json({ error: "缺少 query 或 embedding" });
    }
    const result = await store.search(req.params.sid, String(query), embedding, Number(topK) || 5);
    res.json(result);
  } catch (err) {
    next(err);
  }
});

app.use((err, _req, res, _next) => {
  console.error("[server]", err);
  res.status(500).json({ error: err.message || String(err) });
});

const httpServer = app.listen(PORT, "127.0.0.1", () => {
  console.log("stepfun-kb listening on http://127.0.0.1:" + PORT);
  console.log("seekdb: " + store.version + " | db=" + (process.env.SEEKDB_DB || "stepfun_kb"));
});

async function shutdown() {
  httpServer.close();
  await store.close().catch(() => {});
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
