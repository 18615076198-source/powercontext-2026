/**
 * 端侧知识库前端：
 *   导入文本 -> 浏览器内 embedding -> 写入 seekdb -> 查询向量 + seekdb 混合检索
 *
 * 页面不包含任何云端推理调用；服务端只负责 seekdb 读写。
 * 暴露 window.__kb 供自动化基准脚本驱动。
 */
import { Embedder, MODEL_ID, DTYPE_INFO, detectWebGPU } from "./embedder.js";

const $ = (id) => document.getElementById(id);
const state = {
  sessionId: null,
  embedder: null,
  health: null,
  corpus: null,
  evalSet: null,
  docs: [],
  loading: false,
  metrics: {
    model: null,
    ingest: null,
    query: null,
    quality: null,
    history: [],
  },
};

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) throw new Error((data && data.error) || "HTTP " + res.status);
  return data;
}

function fmtMs(ms) {
  if (ms == null || Number.isNaN(ms)) return "-";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return Math.round(ms) + " ms";
  return (ms / 1000).toFixed(2) + " s";
}

function fmtBytes(bytes) {
  if (!bytes) return "-";
  return (bytes / 1024 / 1024).toFixed(2) + " MB";
}

function setBadge(id, text, kind) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "warn");
  if (kind) el.classList.add(kind);
}

/* ------------------------------------------------------------------ */
/* 会话                                                                */
/* ------------------------------------------------------------------ */
async function ensureSession() {
  const saved = localStorage.getItem("kb.sessionId");
  if (saved) {
    try {
      const info = await api("/api/session/" + saved);
      state.sessionId = saved;
      updateDocCount(info.count);
      return;
    } catch {}
  }
  const info = await api("/api/session", { method: "POST" });
  state.sessionId = info.sessionId;
  localStorage.setItem("kb.sessionId", state.sessionId);
  updateDocCount(info.count);
}

async function resetSession() {
  const info = await api("/api/session/" + state.sessionId + "/reset", { method: "POST" });
  state.docs = [];
  state.chunks = [];
  updateDocCount(info.count);
  renderDocList();
  $("results").innerHTML = "";
}

function updateDocCount(count) {
  $("docCount").textContent = (count ?? 0) + " 个文档块";
}

/* ------------------------------------------------------------------ */
/* 模型                                                                */
/* ------------------------------------------------------------------ */
async function loadModel({ dtype, device } = {}) {
  const chosenDtype = dtype || $("dtypeSelect").value || "auto";
  const chosenDevice = device || $("deviceSelect").value || "auto";
  setBadge("badgeBackend", "后端：加载模型中…");
  const modelStatus = $("modelStatus");
  const dtypeLabel = DTYPE_INFO[chosenDtype]?.label || "自动精度";
  if (modelStatus) modelStatus.textContent = "正在加载 " + dtypeLabel + " 模型…";

  if (state.embedder) await state.embedder.dispose();
  const embedder = new Embedder();
  try {
    await embedder.load({
      dtype: chosenDtype,
      device: chosenDevice,
      onProgress: (p) => {
        if (modelStatus && p && p.status === "progress" && p.file) {
          modelStatus.textContent = "加载 " + p.file + " " + (p.progress ? Math.round(p.progress) + "%" : "");
        }
      },
    });
  } catch (err) {
    setBadge("badgeBackend", "后端：模型加载失败", "warn");
    if (modelStatus) modelStatus.textContent = "模型加载失败：" + err.message;
    throw err;
  }
  state.embedder = embedder;
  state.metrics.model = embedder.describe();

  const info = embedder.describe();
  setBadge("badgeBackend", "后端：" + (info.device === "webgpu" ? "WebGPU" : "WASM"), info.device === "webgpu" ? "ok" : "");
  setBadge("badgeDtype", "精度：" + info.dtypeLabel);
  setBadge("badgeSize", "模型：" + fmtBytes(info.modelBytes));
  $("footBackend").textContent = info.device === "webgpu" ? "WebGPU" : "WASM";
  if (modelStatus) {
    modelStatus.textContent =
      info.device === "webgpu"
        ? "WebGPU 已启用"
        : info.fallback
          ? info.fallback + "，已降级 WASM"
          : "WASM 后端（当前环境无 WebGPU）";
  }
  renderMetrics();
  return embedder;
}

/* ------------------------------------------------------------------ */
/* 语料与切片                                                          */
/* ------------------------------------------------------------------ */
function chunkText(text, size, overlap) {
  const clean = String(text || "").replace(/\r/g, "").trim();
  if (!clean) return [];
  if (clean.length <= size) return [clean];
  const chunks = [];
  let start = 0;
  while (start < clean.length) {
    let end = Math.min(clean.length, start + size);
    if (end < clean.length) {
      const tail = clean.slice(Math.max(start, end - 50), end);
      const cut = Math.max(tail.lastIndexOf("。"), tail.lastIndexOf("\n"), tail.lastIndexOf("；"), tail.lastIndexOf("！"));
      if (cut > 20) end = Math.max(start, end - 50) + cut + 1;
    }
    const piece = clean.slice(start, end).trim();
    if (piece) chunks.push(piece);
    if (end >= clean.length) break;
    start = Math.max(start + 1, end - overlap);
  }
  return chunks;
}

async function loadSampleCorpus() {
  if (!state.corpus) {
    state.corpus = await api("/data/corpus.json");
  }
  return state.corpus.documents;
}

function parsePastedText(text) {
  return String(text || "")
    .split(/\n\s*\n/)
    .map((block, index) => block.trim())
    .filter(Boolean)
    .map((body, index) => {
      const firstLine = body.split("\n")[0];
      const isTitle = firstLine.length <= 40 && body.includes("\n");
      return {
        id: "paste-" + Date.now().toString(36) + "-" + index,
        title: isTitle ? firstLine.replace(/^#+\s*/, "") : "粘贴文本 " + (index + 1),
        text: isTitle ? body.split("\n").slice(1).join("\n").trim() : body,
        category: "粘贴",
      };
    });
}

/* ------------------------------------------------------------------ */
/* 导入                                                                */
/* ------------------------------------------------------------------ */
async function importDocuments(documents, { silent = false } = {}) {
  if (!state.embedder) throw new Error("模型尚未加载");
  const size = Number($("chunkSize").value) || 320;
  const overlap = Number($("chunkOverlap").value) || 40;
  const batchSize = Number($("batchSize").value) || 8;

  const chunks = [];
  for (const doc of documents) {
    const pieces = chunkText(doc.text, size, overlap);
    pieces.forEach((text, index) => {
      chunks.push({
        id: doc.id + "#" + index,
        text,
        meta: { docId: doc.id, title: doc.title || doc.id, category: doc.category || "", chunk: index },
      });
    });
  }
  if (!chunks.length) return { inserted: 0 };

  const progress = $("importProgress");
  const fill = $("progressFill");
  const text = $("progressText");
  if (!silent) progress.hidden = false;

  const totalStart = performance.now();
  const embedStart = performance.now();
  let embedMs = 0;
  for (let i = 0; i < chunks.length; i += batchSize) {
    const slice = chunks.slice(i, i + batchSize);
    const { vectors, ms } = await state.embedder.embedBatch(slice.map((c) => c.text));
    embedMs += ms;
    slice.forEach((chunk, index) => {
      chunk.embedding = vectors[index];
    });
    if (!silent) {
      const done = Math.min(chunks.length, i + slice.length);
      fill.style.width = Math.round((done / chunks.length) * 100) + "%";
      text.textContent = "向量化 " + done + "/" + chunks.length + "（" + fmtMs(ms) + "/批）";
    }
    await tick();
  }
  const embedWallMs = performance.now() - embedStart;

  if (!silent) text.textContent = "写入 seekdb 并刷新索引…";
  const payload = {
    docs: chunks.map((chunk) => ({
      id: chunk.id,
      text: chunk.text,
      meta: chunk.meta,
      embedding: chunk.embedding,
    })),
  };
  const res = await api("/api/session/" + state.sessionId + "/ingest", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const wallMs = performance.now() - totalStart;

  state.metrics.ingest = {
    docs: documents.length,
    chunks: chunks.length,
    embedMs: Math.round(embedMs),
    embedWallMs: Math.round(embedWallMs),
    writeMs: Math.round(res.writeMs),
    refreshMs: Math.round(res.refreshMs),
    serverMs: res.serverMs,
    totalMs: Math.round(wallMs),
    chunksPerSec: wallMs > 0 ? Math.round((chunks.length / (wallMs / 1000)) * 10) / 10 : 0,
  };
  state.docs = documents;
  updateDocCount(res.count);
  renderDocList();
  renderMetrics();

  if (!silent) {
    fill.style.width = "100%";
    text.textContent =
      "完成：" + chunks.length + " 个块，写入 " + fmtMs(res.writeMs) + "，索引刷新 " + fmtMs(res.refreshMs);
    setTimeout(() => {
      progress.hidden = true;
      fill.style.width = "0";
    }, 1800);
  }
  return res;
}

/* ------------------------------------------------------------------ */
/* 检索                                                                */
/* ------------------------------------------------------------------ */
function dedupeByDoc(results) {
  const seen = new Set();
  const out = [];
  for (const item of results) {
    const docId = item.meta?.docId || item.id;
    if (seen.has(docId)) continue;
    seen.add(docId);
    out.push(item);
  }
  return out;
}

async function searchRaw(query, topK = 5) {
  const started = performance.now();
  const embedStart = performance.now();
  const { vectors } = await state.embedder.embedBatch([query]);
  const embedMs = performance.now() - embedStart;
  const res = await api("/api/session/" + state.sessionId + "/search", {
    method: "POST",
    body: JSON.stringify({ query, embedding: vectors[0], topK }),
  });
  const e2eMs = performance.now() - started;
  state.metrics.query = {
    query,
    embedMs: Math.round(embedMs),
    searchMs: Math.round(res.searchMs),
    e2eMs: Math.round(e2eMs),
    mode: res.mode,
  };
  state.metrics.history.push({ at: new Date().toISOString(), query, embedMs, searchMs: res.searchMs, e2eMs });
  return { ...res, embedMs, e2eMs };
}

function renderResults(results) {
  const list = $("results");
  list.innerHTML = "";
  for (const [index, item] of results.entries()) {
    const li = document.createElement("li");
    li.className = "result";
    const title = item.meta?.title || item.id;
    const cat = item.meta?.category ? " · " + item.meta.category : "";
    li.innerHTML =
      '<div class="result-head"><span class="result-title">' +
      (index + 1) +
      ". " +
      escapeHtml(title) +
      '</span><span class="result-score">score ' +
      Number(item.score).toFixed(4) +
      "</span></div>" +
      '<div class="result-meta">' +
      escapeHtml(item.id) +
      cat +
      "</div>" +
      '<p class="result-text">' +
      escapeHtml(String(item.text).slice(0, 220)) +
      (String(item.text).length > 220 ? "…" : "") +
      "</p>";
    list.appendChild(li);
  }
  renderMetrics();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

/* ------------------------------------------------------------------ */
/* 质量评测                                                            */
/* ------------------------------------------------------------------ */
async function loadEvalSet() {
  if (!state.evalSet) state.evalSet = await api("/data/eval.json");
  return state.evalSet;
}

function ndcgAtK(docIds, relevant, k) {
  let dcg = 0;
  for (let i = 0; i < Math.min(k, docIds.length); i += 1) {
    if (relevant.has(docIds[i])) dcg += 1 / Math.log2(i + 2);
  }
  const idealHits = Math.min(k, relevant.size);
  let idcg = 0;
  for (let i = 0; i < idealHits; i += 1) idcg += 1 / Math.log2(i + 2);
  return idcg ? dcg / idcg : 0;
}

async function runEval({ topK = 10 } = {}) {
  const evalSet = await loadEvalSet();
  const perQuery = [];
  for (const item of evalSet.queries) {
    const relevant = new Set(item.relevant);
    const res = await searchRaw(item.query, topK);
    const ranked = dedupeByDoc(res.results).map((r) => r.meta?.docId || r.id);
    const hits5 = ranked.slice(0, 5).filter((id) => relevant.has(id));
    perQuery.push({
      query: item.query,
      recall5: relevant.size ? hits5.length / relevant.size : 0,
      ndcg10: ndcgAtK(ranked, relevant, 10),
      ranked: ranked.slice(0, 5),
    });
    $("statusLine").textContent = "评测中：" + perQuery.length + "/" + evalSet.queries.length;
  }
  const avg = (key) => perQuery.reduce((sum, item) => sum + item[key], 0) / Math.max(1, perQuery.length);
  const result = {
    recall5: Number(avg("recall5").toFixed(4)),
    ndcg10: Number(avg("ndcg10").toFixed(4)),
    queries: perQuery.length,
    perQuery,
  };
  state.metrics.quality = result;
  renderMetrics();
  return result;
}

/* ------------------------------------------------------------------ */
/* 渲染                                                                */
/* ------------------------------------------------------------------ */
function renderDocList() {
  const list = $("docList");
  list.innerHTML = "";
  for (const doc of state.docs.slice(0, 12)) {
    const li = document.createElement("li");
    li.innerHTML = "<b>" + escapeHtml(doc.title || doc.id) + "</b> · " + escapeHtml(doc.category || "");
    list.appendChild(li);
  }
}

function renderMetrics() {
  const m = state.metrics;
  $("mLoad").textContent = m.model ? fmtMs(m.model.loadMs) : "-";
  $("mEmbed").textContent = m.ingest ? fmtMs(m.ingest.embedMs) : "-";
  $("mWrite").textContent = m.ingest ? fmtMs(m.ingest.writeMs) + " + " + fmtMs(m.ingest.refreshMs) : "-";
  $("mQEmbed").textContent = m.query ? fmtMs(m.query.embedMs) : "-";
  $("mSearch").textContent = m.query ? fmtMs(m.query.searchMs) : "-";
  $("mE2E").textContent = m.query ? fmtMs(m.query.e2eMs) : "-";
  $("mThroughput").textContent = m.ingest ? m.ingest.chunksPerSec + " 块/秒" : "-";
  $("mQuality").textContent = m.quality ? "R@5 " + m.quality.recall5.toFixed(3) + " · nDCG@10 " + m.quality.ndcg10.toFixed(3) : "-";
  $("rawMetrics").textContent = JSON.stringify(m, null, 2);
}

/* ------------------------------------------------------------------ */
/* 事件绑定与启动                                                      */
/* ------------------------------------------------------------------ */
function bindUI() {
  $("btnSample").addEventListener("click", async () => {
    const docs = await loadSampleCorpus();
    await importDocuments(docs).catch((err) => alert("导入失败：" + err.message));
  });

  $("btnImportPaste").addEventListener("click", async () => {
    const docs = parsePastedText($("pasteBox").value);
    if (!docs.length) return alert("请先粘贴一些文本（空行分隔多个文档）");
    await importDocuments(docs).catch((err) => alert("导入失败：" + err.message));
  });

  $("btnReset").addEventListener("click", async () => {
    await resetSession();
    $("statusLine").textContent = "知识库已清空";
  });

  const doSearch = async () => {
    const query = $("queryInput").value.trim();
    if (!query) return;
    if (!state.embedder) return alert("模型仍在加载，请稍候");
    $("statusLine").textContent = "检索中…";
    try {
      const res = await searchRaw(query, Number($("topK").value) || 5);
      $("statusLine").textContent =
        "检索方式：" + (res.mode === "hybrid" ? "seekdb 混合检索（向量 + 全文，RRF）" : "向量检索（降级）") +
        " · 查询向量化 " + fmtMs(res.embedMs) + " · 库内检索 " + fmtMs(res.searchMs) + " · 端到端 " + fmtMs(res.e2eMs);
      renderResults(dedupeByDoc(res.results));
    } catch (err) {
      $("statusLine").textContent = "检索失败：" + err.message;
    }
  };
  $("btnSearch").addEventListener("click", doSearch);
  $("queryInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });

  $("btnEval").addEventListener("click", async () => {
    if (!state.embedder) return alert("模型仍在加载");
    if (!state.docs.length) return alert("请先导入示例语料");
    $("btnEval").disabled = true;
    try {
      await runEval({ topK: 10 });
    } catch (err) {
      $("statusLine").textContent = "评测失败：" + err.message;
    } finally {
      $("btnEval").disabled = false;
      $("statusLine").textContent = "";
    }
  });

  $("btnExport").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(state.metrics, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "nearby-bench-" + Date.now() + ".json";
    a.click();
  });

  $("btnReload").addEventListener("click", () => loadModel().catch(() => {}));
}

async function boot() {
  try {
    state.health = await api("/api/health");
    setBadge("badgeSeekdb", "seekdb：" + state.health.seekdb.split("-")[0], "ok");
    await ensureSession();
    bindUI();
    // 后台预加载默认模型，避免阻塞页面
    loadModel({ dtype: "auto", device: "auto" }).catch((err) => {
      $("statusLine").textContent = "模型加载失败：" + err.message;
    });
  } catch (err) {
    setBadge("badgeSeekdb", "seekdb：连接失败", "warn");
    $("statusLine").textContent = "无法连接后端：" + err.message;
  }
}

/* ------------------------------------------------------------------ */
/* 自动化接口（供 scripts/benchmark.mjs 通过 CDP 调用）                 */
/* ------------------------------------------------------------------ */
window.__kb = {
  state,
  async waitReady(timeoutMs = 120000) {
    const started = Date.now();
    while (!state.embedder) {
      if (Date.now() - started > timeoutMs) throw new Error("模型加载超时");
      await new Promise((r) => setTimeout(r, 200));
    }
    return state.embedder.describe();
  },
  async loadModel(opts) {
    return (await loadModel(opts)).describe();
  },
  async reload(opts) {
    return (await loadModel(opts)).describe();
  },
  async reset() {
    await resetSession();
    return { sessionId: state.sessionId };
  },
  async importSample() {
    const docs = await loadSampleCorpus();
    return importDocuments(docs, { silent: true });
  },
  async importDocs(docs) {
    return importDocuments(docs, { silent: true });
  },
  async search(query, topK = 5) {
    const res = await searchRaw(query, topK);
    return { mode: res.mode, results: dedupeByDoc(res.results), query: state.metrics.query };
  },
  async eval(topK = 10) {
    return runEval({ topK });
  },
  async scenario({ dtype = "q8", device = "auto", evalTopK = 10, latencyRuns = 12, topK = 5 } = {}) {
    await loadModel({ dtype, device });
    await resetSession();
    const importRes = await importDocuments(await loadSampleCorpus(), { silent: true });
    const quality = await runEval({ topK: evalTopK });

    const evalSet = await loadEvalSet();
    const queries = evalSet.queries.map((q) => q.query);
    // 预热
    await searchRaw(queries[0], topK);
    const latencies = [];
    for (let i = 0; i < latencyRuns; i += 1) {
      const q = queries[i % queries.length];
      const started = performance.now();
      await searchRaw(q, topK);
      latencies.push(performance.now() - started);
    }
    const sorted = [...latencies].sort((a, b) => a - b);
    const pick = (p) => Number(sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))].toFixed(1));
    return {
      model: state.metrics.model,
      ingest: state.metrics.ingest,
      quality: { recall5: quality.recall5, ndcg10: quality.ndcg10 },
      latency: {
        runs: latencies.length,
        p50: pick(0.5),
        p90: pick(0.9),
        min: Number(sorted[0].toFixed(1)),
        max: Number(sorted[sorted.length - 1].toFixed(1)),
      },
      importRes,
      seekdb: state.health?.seekdb,
    };
  },
  getMetrics() {
    return JSON.parse(JSON.stringify(state.metrics));
  },
  async detectWebGPU() {
    return detectWebGPU();
  },
};

boot();
