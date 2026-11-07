(function () {
  "use strict";

  var state = {
    stats: null,
    memories: [],
    conflicts: [],
    papers: [],
    notes: [],
    health: null,
    route: "dashboard",
    libraryTab: "papers",
    currentPaper: null
  };

  var view = document.getElementById("view");
  var crumb = document.getElementById("crumb");
  var statusEl = document.getElementById("status");
  var toastEl = document.getElementById("toast");
  var toastTimer = null;

  var ROUTE_NAMES = {
    dashboard: "工作台",
    ask: "提问",
    library: "资料库",
    memory: "记忆",
    conflicts: "冲突"
  };

  var KIND_LABELS = {
    decision: "决策",
    constraint: "约束",
    progress: "进度",
    next_step: "待办",
    review: "复核",
    todo: "待办",
    risk: "风险",
    experiment: "实验",
    meeting: "组会"
  };

  var QUESTIONS = [
    "我们为什么放弃 Self-RAG 的全量自反思？",
    "DPR 的 fine-tune 结果会不会影响我们不做 retriever 微调的决定？",
    "长上下文模型能不能替代 RAG？",
    "chunk size 最后定了多少，依据是什么？"
  ];

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function truncate(value, n) {
    var s = String(value == null ? "" : value);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  function fmt(n) {
    return typeof n === "number" ? n.toLocaleString("zh-CN") : (n == null ? "—" : String(n));
  }

  function kindLabel(kind) {
    return KIND_LABELS[kind] || kind || "记忆";
  }

  function stripMarkdown(text) {
    return String(text || "").replace(/^#+\s*/g, "").replace(/\n+/g, " ").trim();
  }

  function toast(message, isError) {
    toastEl.textContent = message;
    toastEl.className = "toast show" + (isError ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.className = "toast"; }, 2600);
  }

  function apiGet(path) {
    return fetch(path).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) { throw new Error(t || ("HTTP " + res.status)); });
      }
      return res.json();
    });
  }

  function apiPost(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) { throw new Error(t || ("HTTP " + res.status)); });
      }
      return res.json();
    });
  }

  function setStatus(health) {
    state.health = health;
    var ok = health && health.seekdb === "ok" && health.powercontext === "ok";
    var degraded = health && (health.seekdb !== "ok" || health.powercontext !== "ok");
    statusEl.className = "status " + (ok ? "ok" : (degraded ? "degraded" : "down"));
    statusEl.innerHTML = '<span class="status-dot"></span><span>' +
      (ok ? "seekdb + PowerContext 已连接" : "部分服务未连接，点击重试") + "</span>";
    statusEl.onclick = function () { refreshShell(); };
  }

  function refreshShell() {
    apiGet("/api/health").then(setStatus).catch(function () {
      statusEl.className = "status down";
      statusEl.innerHTML = '<span class="status-dot"></span><span>后端未连接</span>';
    });
    apiGet("/api/stats").then(function (s) { state.stats = s; }).catch(function () {});
    apiGet("/api/conflicts?status=open").then(function (d) {
      state.conflicts = d.conflicts || [];
      var badge = document.getElementById("conflict-badge");
      if (badge) {
        badge.textContent = state.conflicts.length ? String(state.conflicts.length) : "";
        badge.className = "nav-badge" + (state.conflicts.length ? " show" : "");
      }
    }).catch(function () {});
  }

  function setRoute(route) {
    state.route = route;
    var links = document.querySelectorAll(".nav a");
    for (var i = 0; i < links.length; i++) {
      links[i].classList.toggle("active", links[i].getAttribute("data-route") === route);
    }
    crumb.textContent = ROUTE_NAMES[route] || "工作台";
  }

  function skeleton(lines) {
    var out = '<div class="card"><div class="skeleton skeleton-line" style="width:38%"></div>';
    for (var i = 0; i < lines; i++) {
      out += '<div class="skeleton skeleton-line" style="width:' + (92 - i * 9) + '%"></div>';
    }
    return out + "</div>";
  }

  function renderDashboard() {
    setRoute("dashboard");
    view.innerHTML = '<div class="hero"><div><div class="eyebrow">RESEARCH MEMORY · 2026</div><h1>把组会的「为什么」，留在下一次组会之前。</h1>' +
      '<p class="lede">LabMemory 把论文、实验笔记和组会决策放在同一个可检索、可追溯的记忆里。问一句「上次为什么放弃这个方法」，它给你原文出处和当时的决定。</p>' +
      '<div class="hero-actions"><button class="btn" id="hero-ask">去提问</button><button class="btn ghost" id="hero-memory">写入一条记忆</button></div></div>' +
      '<div class="hero-side"><div class="tech-pill"><span class="dot"></span><div><strong>seekdb 混合检索</strong><br><span class="muted small">BM25 + 向量 + RRF，结果带段落出处</span></div></div>' +
      '<div class="tech-pill"><span class="dot"></span><div><strong>PowerContext 记忆</strong><br><span class="muted small">决策/约束/进度，按课题 scope 召回</span></div></div>' +
      '<div class="tech-pill"><span class="dot"></span><div><strong>本地抽取式回答</strong><br><span class="muted small">不调用外部 LLM，只引用检索原文</span></div></div></div></div>' +
      '<div class="stats" id="stats"><div class="card skeleton skeleton-line"></div><div class="card skeleton skeleton-line"></div><div class="card skeleton skeleton-line"></div><div class="card skeleton skeleton-line"></div></div>' +
      '<div id="conflict-slot"></div>' +
      '<div class="grid-2" style="margin-top:22px"><div><div class="section-title"><h2>最近的记忆</h2><span class="small">由 PowerContext 保存</span></div><div class="stack" id="memory-mini">' + skeleton(3) + '</div></div>' +
      '<div><div class="section-title"><h2>从一个真实问题开始</h2><span class="small">点击直接提问</span></div><div class="question-grid" id="question-grid"></div></div></div>' +
      '<div class="section-title"><h2>最近提问</h2><span class="small">来自 queries 表 · 点击重新提问</span></div><div class="stack" id="history-list">' + skeleton(2) + '</div>';

    document.getElementById("hero-ask").onclick = function () { location.hash = "#/ask"; };
    document.getElementById("hero-memory").onclick = function () { location.hash = "#/memory"; };

    var qg = document.getElementById("question-grid");
    qg.innerHTML = QUESTIONS.map(function (q, i) {
      return '<button class="question" data-q="' + esc(q) + '">' + esc(q) + '<span>示例 ' + (i + 1) + " · 带记忆与出处</span></button>";
    }).join("");

    Promise.all([
      apiGet("/api/stats"),
      apiGet("/api/memories"),
      apiGet("/api/conflicts?status=open")
    ]).then(function (values) {
      state.stats = values[0];
      state.memories = (values[1].entries || []);
      state.conflicts = values[2].conflicts || [];
      renderStats();
      renderConflictBanner();
      renderMemoryMini();
      loadHistory();
      var badge = document.getElementById("conflict-badge");
      if (badge) {
        badge.textContent = state.conflicts.length ? String(state.conflicts.length) : "";
        badge.className = "nav-badge" + (state.conflicts.length ? " show" : "");
      }
    }).catch(function (err) {
      toast("加载工作台失败：" + err.message, true);
    });
  }

  function loadHistory() {
    var host = document.getElementById("history-list");
    if (!host) return;
    host.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-history-q]");
      if (!btn) return;
      var q = btn.getAttribute("data-history-q");
      location.hash = "#/ask";
      setTimeout(function () {
        var input = document.getElementById("ask-input");
        var form = document.getElementById("ask-form");
        if (!input || !form) return;
        input.value = q;
        form.requestSubmit();
      }, 60);
    });
    apiGet("/api/history?limit=8").then(function (data) {
      var items = (data.items || []).slice(0, 5);
      if (!items.length) {
        host.innerHTML = '<div class="empty" style="padding:18px"><strong>还没有提问记录</strong>问一句就会出现在这里。</div>';
        return;
      }
      host.innerHTML = items.map(function (h) {
        return '<button class="question" data-history-q="' + esc(h.question) + '">' + esc(truncate(h.question, 120)) +
          '<span>' + esc(h.created_at || "") + " · " + esc(fmt(h.latency_ms)) + " ms</span></button>";
      }).join("");
    }).catch(function () {
      host.innerHTML = '<div class="empty" style="padding:18px"><strong>最近提问不可用</strong>queries 表暂时读不到。</div>';
    });
  }

  function renderStats() {
    var s = state.stats || {};
    var cards = [
      ["论文", s.papers, "9 篇真实 arXiv 论文"],
      ["组会/实验笔记", s.notes, "决策与实验记录"],
      ["证据片段", s.chunks, "seekdb 混合检索索引"],
      ["PowerContext 记忆", s.memories, "可召回、可追溯"]
    ];
    document.getElementById("stats").innerHTML = cards.map(function (c) {
      return '<div class="stat"><div class="label"><span>' + esc(c[0]) + '</span><span>●</span></div><div class="value">' + fmt(c[1]) + '</div><div class="hint">' + esc(c[2]) + "</div></div>";
    }).join("");
  }

  function renderConflictBanner() {
    var slot = document.getElementById("conflict-slot");
    if (!slot) return;
    if (!state.conflicts.length) { slot.innerHTML = ""; return; }
    var first = state.conflicts[0];
    slot.innerHTML = '<div class="conflict-banner"><div><div class="eyebrow">REVIEW NEEDED</div><h3>' + state.conflicts.length + ' 条决策可能需要复核</h3><p>' + esc(first.reason || "") + '</p></div><button class="btn" id="go-conflicts">查看冲突</button></div>';
    document.getElementById("go-conflicts").onclick = function () { location.hash = "#/conflicts"; };
  }

  function renderMemoryMini() {
    var host = document.getElementById("memory-mini");
    if (!host) return;
    var items = state.memories.slice(0, 4);
    if (!items.length) {
      host.innerHTML = '<div class="empty"><strong>还没有记忆</strong>去记忆页写入第一条决策。</div>';
      return;
    }
    host.innerHTML = items.map(function (m) {
      return '<div class="memory-mini"><div class="kind">' + esc(kindLabel(m.kind)) + '</div><p>' + esc(truncate(stripMarkdown(m.text), 150)) + '</p><div class="meta">' + esc(m.artifact_id || "") + ' @ r' + esc(m.revision) + "</div></div>";
    }).join("");
  }

  function renderAsk() {
    setRoute("ask");
    view.innerHTML = '<div class="page-head"><div><div class="eyebrow">ASK THE LAB</div><h1 style="font-size:34px">问课题组</h1><p>检索论文与笔记，同时召回 PowerContext 里的决策记忆。回答只引用检索到的原文。</p></div></div>' +
      '<div class="ask-box"><form class="ask-form" id="ask-form"><input class="input" id="ask-input" placeholder="例如：我们为什么放弃 Self-RAG 的全量自反思？" autocomplete="off"><select class="select" id="ask-filter"><option value="">全部资料</option><option value="paper">只看论文</option><option value="note">只看笔记</option></select><button class="btn" type="submit">提问</button></form>' +
      '<div class="examples" id="examples">' + QUESTIONS.map(function (q) { return '<button class="chip" data-q="' + esc(q) + '">' + esc(q) + "</button>"; }).join("") + '</div></div>' +
      '<div class="ask-layout"><div id="ask-result"><div class="empty"><strong>从一个问题开始</strong>回答会附上论文/笔记出处，以及用到的记忆。</div></div><aside class="memory-side" id="ask-memory"><div class="card"><div class="eyebrow">POWERCONTEXT</div><h3 style="margin-top:6px">用到的记忆</h3><p class="small muted" style="margin-top:6px">提问后这里会显示召回的决策/约束。</p></div></aside></div>';

    document.getElementById("ask-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var q = document.getElementById("ask-input").value.trim();
      if (!q) { toast("先输入一个问题", true); return; }
      var filter = document.getElementById("ask-filter").value;
      doAsk(q, filter);
    });
    var ex = document.getElementById("examples");
    ex.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-q]");
      if (!btn) return;
      document.getElementById("ask-input").value = btn.getAttribute("data-q");
      doAsk(btn.getAttribute("data-q"), document.getElementById("ask-filter").value);
    });
  }

  function doAsk(query, sourceType) {
    var result = document.getElementById("ask-result");
    var memorySide = document.getElementById("ask-memory");
    result.innerHTML = '<div class="card"><div class="skeleton skeleton-line" style="width:30%"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line" style="width:88%"></div><div class="skeleton skeleton-line" style="width:72%"></div></div>';
    memorySide.innerHTML = '<div class="card"><div class="skeleton skeleton-line" style="width:40%"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line" style="width:80%"></div></div>';
    var filters = sourceType ? { source_type: sourceType } : {};
    apiPost("/api/ask", { query: query, filters: filters }).then(function (data) {
      renderAnswer(data, query);
    }).catch(function (err) {
      result.innerHTML = '<div class="empty"><strong>提问失败</strong>' + esc(err.message) + "</div>";
      toast("提问失败：" + err.message, true);
    });
  }

  function renderAnswer(data, query) {
    var result = document.getElementById("ask-result");
    var memorySide = document.getElementById("ask-memory");
    var citations = data.citations || [];
    var memories = data.memories || [];
    var trace = data.trace || {};

    var citesHtml = citations.map(function (c, i) {
      var meta = (c.type === "memory" ? "PowerContext 记忆" : (c.type === "paper" ? "论文" : "笔记")) +
        (c.section ? " · " + c.section : "") + (c.page ? " · p." + c.page : "");
      var ref = c.artifact_id ? " · " + c.artifact_id + " @ r" + c.revision : "";
      return '<div class="citation" id="citation-' + i + '"><div class="num">' + (i + 1) + '</div><div style="min-width:0"><div><strong>' + esc(c.title) + '</strong></div><div class="snippet">' + esc(c.snippet || "") + '</div><div class="meta">' + esc(meta) + esc(ref) + "</div></div></div>";
    }).join("");

    var evidence = citations.filter(function (c) { return c.type !== "memory"; });
    var evidenceHtml = evidence.map(function (c, i) {
      var routes = (c.routes || []).map(function (r) { return '<span class="score-pill">' + esc(r) + "</span>"; }).join("");
      var ranks = c.ranks ? Object.keys(c.ranks).map(function (k) { return k + " #" + c.ranks[k]; }).join(" · ") : "";
      var scores = c.scores ? Object.keys(c.scores).map(function (k) { return k + " " + Number(c.scores[k]).toFixed(3); }).join(" · ") : "";
      var link = c.url ? '<a class="small" href="' + esc(c.url) + '" target="_blank" rel="noreferrer">arXiv 原文 ↗</a>' : "";
      return '<div class="evidence" id="evidence-' + i + '"><div class="top"><div><div class="title">' + esc(c.title) + '</div><div class="small muted">' + esc(c.section || "") + (c.page ? " · p." + c.page : "") + "</div></div>" + link + '</div><div class="snippet">' + esc(c.snippet || "") + '</div><div class="scores">' + routes + '<span class="score-pill">' + esc(ranks) + '</span><span class="score-pill">' + esc(scores) + "</span></div></div>";
    }).join("");

    var memoryHtml = memories.length ? memories.map(function (m) {
      return '<div class="memory-hit"><div class="kind">' + esc(kindLabel(m.kind)) + '</div><p>' + esc(m.text) + '</p><div class="ref">' + esc(m.artifact_id || "") + ' @ r' + esc(m.revision) + " · score " + Number(m.score || 0).toFixed(4) + "</div></div>";
    }).join("") : '<p class="small muted">本次没有召回记忆。可以到「记忆」页写入一条决策。</p>';

    var traceText = "mode: " + (trace.bm25_error ? "vector-only" : "hybrid") +
      "\nbm25_count: " + trace.bm25_count + "\nvector_count: " + trace.vector_count +
      "\nmerged_count: " + trace.merged_count + "\nrrf_k: " + trace.rrf_k +
      "\nmemory_count: " + trace.memory_count + "\nlatency_ms: " + trace.latency_ms +
      (trace.bm25_error ? "\nbm25_error: " + trace.bm25_error : "") +
      (trace.memory_error ? "\nmemory_error: " + trace.memory_error : "");

    result.innerHTML = '<div class="card answer-card fade-in"><div class="between"><div class="eyebrow">LOCAL EXTRACTIVE ANSWER</div><span class="badge accent">' + data.latency_ms + ' ms</span></div>' +
      '<div class="answer-text">' + esc(data.answer) + '</div>' +
      '<div class="answer-foot">只引用检索到的原文 · seekdb 混合检索 + PowerContext 记忆</div>' +
      (citesHtml ? '<div class="divider"></div><div class="eyebrow">CITATIONS</div><div class="citations">' + citesHtml + "</div>" : "") +
      (evidenceHtml ? '<div class="divider"></div><div class="eyebrow">EVIDENCE</div><div class="evidence-list">' + evidenceHtml + "</div>" : "") +
      '<details class="trace"><summary>检索轨迹 · ' + esc(query) + '</summary><pre>' + esc(traceText) + "</pre></details></div>";

    memorySide.innerHTML = '<div class="card"><div class="eyebrow">POWERCONTEXT</div><h3 style="margin-top:6px">用到的记忆</h3>' +
      (memories.length ? '<div class="small muted" style="margin:4px 0 8px">按 query 召回 ' + memories.length + " 条 active 记忆</div>" : "") +
      '<div style="margin-top:8px">' + memoryHtml + "</div>" +
      '<div class="divider"></div><p class="small muted">记忆由 PowerContext 存储；artifact_id @ revision 可在 Dashboard 核对。</p></div>';
  }

  function renderLibrary() {
    setRoute("library");
    view.innerHTML = '<div class="page-head"><div><div class="eyebrow">LIBRARY</div><h1 style="font-size:34px">资料库</h1><p>9 篇真实 arXiv 论文 + 8 条组会/实验笔记。论文有中文摘要和段落级 chunk；笔记是演示场景数据，论文与引用真实存在。</p></div><input class="input" id="library-search" placeholder="筛选标题 / 作者 / 标签…" style="max-width:280px"></div>' +
      '<div class="tabs"><button class="tab active" data-tab="papers">论文</button><button class="tab" data-tab="notes">笔记</button></div><div id="library-body">' + skeleton(4) + '</div><div class="detail" id="paper-detail"></div>';

    document.getElementById("library-search").addEventListener("input", function () { renderLibraryBody(this.value); });
    document.querySelector(".tabs").addEventListener("click", function (e) {
      var tab = e.target.closest("[data-tab]");
      if (!tab) return;
      state.libraryTab = tab.getAttribute("data-tab");
      var tabs = document.querySelectorAll(".tab");
      for (var i = 0; i < tabs.length; i++) tabs[i].classList.toggle("active", tabs[i] === tab);
      renderLibraryBody(document.getElementById("library-search").value);
    });

    Promise.all([apiGet("/api/papers"), apiGet("/api/notes")]).then(function (values) {
      state.papers = values[0] || [];
      state.notes = values[1] || [];
      renderLibraryBody("");
    }).catch(function (err) {
      document.getElementById("library-body").innerHTML = '<div class="empty"><strong>加载失败</strong>' + esc(err.message) + "</div>";
    });
  }

  function renderLibraryBody(filter) {
    var q = String(filter || "").toLowerCase();
    var host = document.getElementById("library-body");
    if (!host) return;
    if (state.libraryTab === "papers") {
      var papers = state.papers.filter(function (p) {
        if (!q) return true;
        return ((p.title || "") + " " + (p.authors || "") + " " + (p.tags || "") + " " + (p.summary_zh || "")).toLowerCase().indexOf(q) >= 0;
      });
      if (!papers.length) { host.innerHTML = '<div class="empty"><strong>没有匹配的论文</strong>换个关键词试试。</div>'; return; }
      host.innerHTML = '<div class="paper-grid">' + papers.map(function (p) {
        return '<article class="paper-card" data-paper="' + esc(p.id) + '"><div class="row"><span class="badge tech">' + esc(p.published || "") + '</span><span class="badge">' + esc(p.chunk_count) + " chunks</span></div><h3>" + esc(p.title) + '</h3><div class="authors">' + esc(truncate(p.authors || "", 90)) + '</div><p class="summary">' + esc(p.summary_zh || p.abstract || "") + '</p><div class="foot"><span>' + esc(p.tags || "") + '</span><span>打开 →</span></div></article>';
      }).join("") + "</div>";
    } else {
      var notes = state.notes.filter(function (n) {
        if (!q) return true;
        return ((n.title || "") + " " + (n.content || "") + " " + (n.tags || "")).toLowerCase().indexOf(q) >= 0;
      });
      if (!notes.length) { host.innerHTML = '<div class="empty"><strong>没有匹配的笔记</strong>换个关键词试试。</div>'; return; }
      host.innerHTML = notes.map(function (n) {
        return '<div class="note-row"><div class="date">' + esc(n.note_date || "") + '</div><div><span class="badge amber">' + esc(kindLabel(n.kind)) + '</span></div><div><h4>' + esc(n.title) + '</h4><p>' + esc(truncate(stripMarkdown(n.content), 220)) + '</p><p class="small muted" style="margin-top:5px">' + esc(n.tags || "") + '</p></div></div>';
      }).join("");
    }
  }

  function showPaper(id) {
    var host = document.getElementById("paper-detail");
    host.innerHTML = '<div class="card">' + skeleton(3) + "</div>";
    apiGet("/api/papers/" + encodeURIComponent(id)).then(function (data) {
      var p = data.paper || {};
      var chunks = data.chunks || [];
      host.innerHTML = '<div class="card fade-in"><div class="between"><div><div class="eyebrow">PAPER DETAIL</div><h2 style="margin-top:6px">' + esc(p.title) + '</h2><p class="small muted" style="margin-top:6px">' + esc(p.authors || "") + " · " + esc(p.published || "") + '</p></div><a class="btn ghost small" href="https://arxiv.org/abs/' + esc(p.arxiv_id || "") + '" target="_blank" rel="noreferrer">arXiv ↗</a></div>' +
        '<div class="divider"></div><p style="color:#4d4439;font-size:13px">' + esc(p.summary_zh || p.abstract || "") + "</p>" +
        '<div class="divider"></div><div class="eyebrow">CHUNKS · ' + chunks.length + '</div>' +
        chunks.map(function (c) {
          return '<div class="chunk"><div class="chunk-head"><span class="badge">' + esc(c.section || "") + '</span><span>page ' + esc(c.page) + '</span><span>#' + esc(c.chunk_index) + '</span></div>' + esc(truncate(c.content || "", 420)) + "</div>";
        }).join("") + "</div>";
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    }).catch(function (err) {
      host.innerHTML = '<div class="empty"><strong>打开失败</strong>' + esc(err.message) + "</div>";
    });
  }

  function renderMemory() {
    setRoute("memory");
    view.innerHTML = '<div class="page-head"><div><div class="eyebrow">POWERCONTEXT MEMORY</div><h1 style="font-size:34px">记忆</h1><p>决策、约束、进度、待办由 PowerContext 保存。提问时会按语义/关键词召回，并在回答里显示 artifact_id 与 revision。</p></div></div>' +
      '<div class="card" style="margin-bottom:18px"><div class="eyebrow">WRITE A MEMORY</div><form class="memory-form" id="memory-form" style="margin-top:10px"><select class="select" id="memory-kind"><option value="decision">决策</option><option value="constraint">约束</option><option value="progress">进度</option><option value="next_step">待办</option><option value="review">复核</option></select><textarea class="textarea" id="memory-text" placeholder="例如：我们决定采用 RRF(k=60) 融合 BM25 与向量检索…"></textarea><button class="btn" type="submit">写入 PowerContext</button></form></div>' +
      '<div id="memory-list">' + skeleton(3) + "</div>";

    document.getElementById("memory-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var kind = document.getElementById("memory-kind").value;
      var text = document.getElementById("memory-text").value.trim();
      if (!text) { toast("先写一条记忆内容", true); return; }
      var btn = e.target.querySelector("button");
      btn.disabled = true;
      apiPost("/api/memories", { kind: kind, text: text }).then(function (rec) {
        toast("已写入 PowerContext：" + (rec.artifact_id || ""));
        document.getElementById("memory-text").value = "";
        btn.disabled = false;
        loadMemories();
        refreshShell();
      }).catch(function (err) {
        btn.disabled = false;
        toast("写入失败：" + err.message, true);
      });
    });
    loadMemories();
  }

  function loadMemories() {
    apiGet("/api/memories").then(function (data) {
      state.memories = data.entries || [];
      var groups = {};
      state.memories.forEach(function (m) {
        var k = m.kind || "memory";
        (groups[k] = groups[k] || []).push(m);
      });
      var host = document.getElementById("memory-list");
      if (!host) return;
      if (!state.memories.length) {
        host.innerHTML = '<div class="empty"><strong>还没有记忆</strong>用上面的表单写入第一条决策。</div>';
        return;
      }
      host.innerHTML = Object.keys(groups).map(function (kind) {
        return '<div class="section-title"><h2>' + esc(kindLabel(kind)) + ' · ' + groups[kind].length + '</h2><span class="small">PowerContext active</span></div><div class="memory-grid">' +
          groups[kind].map(function (m) {
            return '<div class="memory-card"><div class="kind"><span class="badge accent">' + esc(kindLabel(m.kind)) + '</span><span class="small muted">' + esc(m.state || "") + '</span></div><p>' + esc(stripMarkdown(m.text)) + '</p><div class="ref">' + esc(m.artifact_id || "") + " @ r" + esc(m.revision) + "</div></div>";
          }).join("") + "</div>";
      }).join("");
    }).catch(function (err) {
      var host = document.getElementById("memory-list");
      if (host) host.innerHTML = '<div class="empty"><strong>读取记忆失败</strong>' + esc(err.message) + "</div>";
    });
  }

  function renderConflicts() {
    setRoute("conflicts");
    view.innerHTML = '<div class="page-head"><div><div class="eyebrow">DECISION REVIEW</div><h1 style="font-size:34px">冲突与复核</h1><p>规则版扫描：新论文的方法/关键词与既有决策重叠时，提示「可能影响决策」。不是 LLM 猜测，匹配依据可解释。</p></div><button class="btn ghost" id="rescan">重新扫描</button></div><div id="conflict-list">' + skeleton(3) + "</div>";
    document.getElementById("rescan").onclick = function () {
      apiPost("/api/conflicts/rescan", {}).then(function (r) {
        toast("扫描完成，新增 " + (r.created || 0) + " 条");
        loadConflicts();
        refreshShell();
      }).catch(function (err) { toast("扫描失败：" + err.message, true); });
    };
    loadConflicts();
  }

  function loadConflicts() {
    apiGet("/api/conflicts?status=open").then(function (data) {
      state.conflicts = data.conflicts || [];
      var host = document.getElementById("conflict-list");
      if (!host) return;
      if (!state.conflicts.length) {
        host.innerHTML = '<div class="empty"><strong>没有待复核冲突</strong>资料和决策目前一致。</div>';
        return;
      }
      host.innerHTML = '<div class="stack">' + state.conflicts.map(function (c) {
        return '<div class="conflict-card"><div class="between"><div class="eyebrow">CONFLICT</div><span class="badge red">open</span></div><h3 style="margin-top:6px">' + esc(c.paper_title || c.paper_id) + '</h3><p class="reason">' + esc(c.reason || "") + '</p><div class="memory">' + esc(truncate(c.memory_text || "", 260)) + '</div><div class="actions"><button class="btn small" data-review="' + esc(c.id) + '">生成复核任务</button><button class="btn ghost small" data-dismiss="' + esc(c.id) + '">忽略</button></div></div>';
      }).join("") + "</div>";
      host.addEventListener("click", function (e) {
        var review = e.target.closest("[data-review]");
        var dismiss = e.target.closest("[data-dismiss]");
        if (review) {
          apiPost("/api/conflicts/" + encodeURIComponent(review.getAttribute("data-review")) + "/review", {}).then(function (r) {
            toast("已写入复核记忆：" + (r.artifact_id || ""));
            loadConflicts();
            refreshShell();
          }).catch(function (err) { toast("操作失败：" + err.message, true); });
        }
        if (dismiss) {
          apiPost("/api/conflicts/" + encodeURIComponent(dismiss.getAttribute("data-dismiss")) + "/dismiss", {}).then(function () {
            toast("已忽略");
            loadConflicts();
            refreshShell();
          }).catch(function (err) { toast("操作失败：" + err.message, true); });
        }
      });
    }).catch(function (err) {
      var host = document.getElementById("conflict-list");
      if (host) host.innerHTML = '<div class="empty"><strong>加载失败</strong>' + esc(err.message) + "</div>";
    });
  }

  function route() {
    var hash = location.hash || "#/dashboard";
    var routeName = hash.replace(/^#\/?/, "").split("?")[0] || "dashboard";
    if (routeName === "ask") renderAsk();
    else if (routeName === "library") renderLibrary();
    else if (routeName === "memory") renderMemory();
    else if (routeName === "conflicts") renderConflicts();
    else renderDashboard();
  }

  document.addEventListener("click", function (e) {
    var q = e.target.closest("[data-q]");
    if (q && state.route !== "ask") {
      location.hash = "#/ask";
      setTimeout(function () {
        var input = document.getElementById("ask-input");
        if (input) { input.value = q.getAttribute("data-q"); doAsk(input.value, ""); }
      }, 60);
    }
    var paper = e.target.closest("[data-paper]");
    if (paper) showPaper(paper.getAttribute("data-paper"));
  });

  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () {
    refreshShell();
    route();
  });
})();
