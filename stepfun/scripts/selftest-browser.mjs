/**
 * 浏览器端自测（无头）：验证「导入 -> 本地向量化 -> 写 seekdb -> 混合检索 -> 增量导入 -> 重置」。
 * 需要先启动服务（npm start）与 seekdb。
 *
 * 用法：node scripts/selftest-browser.mjs
 */
import { launchBrowser } from "./cdp.mjs";

const URL = process.env.APP_URL || "http://127.0.0.1:7860/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log((ok ? "[PASS] " : "[FAIL] ") + name + (detail ? "  " + detail : ""));
}

const browser = await launchBrowser({ url: URL });
try {
  const s = browser.session;
  for (let i = 0; i < 100 && !(await s.evaluate("typeof window.__kb === 'object' && !!window.__kb")); i += 1) {
    await sleep(200);
  }

  const model = await s.evaluate("window.__kb.waitReady(240000)");
  check("模型加载（本地文件）", !!model.model && model.loadMs > 0, "后端=" + model.device + " 精度=" + model.dtype + " 体积=" + (model.modelBytes / 1024 / 1024).toFixed(2) + "MB");

  await s.evaluate("window.__kb.reset()");
  const ing = await s.evaluate("window.__kb.importSample()");
  check("导入 40 篇并写入 seekdb", ing.count === 40 && ing.inserted === 40, "写入=" + Math.round(ing.writeMs) + "ms 刷新=" + Math.round(ing.refreshMs) + "ms");

  const found = await s.evaluate("window.__kb.search('seekdb 怎么做向量与全文的混合检索', 5)");
  check("混合检索走 seekdb", found.mode === "hybrid" && found.results.length > 0, "mode=" + found.mode + " 命中=" + found.results.length);
  check("检索结果包含相关文档", found.results.some((r) => ["d04", "d02", "d03"].includes(r.meta?.docId)), "top1=" + (found.results[0]?.meta?.title || found.results[0]?.id));

  const inc = await s.evaluate(
    "window.__kb.importDocs([{id:'inc-1', title:'增量导入验证文档', category:'测试', text:'seekdb 增量导入后需要 refresh_index 才能立刻检索到新文档，本段用于验证这条链路的正确性。'}])",
  );
  const incSearch = await s.evaluate("window.__kb.search('增量导入后如何让新文档可检索', 5)");
  check("增量导入后计数增加", inc.count === 41, "count=" + inc.count);
  check("刷新后新文档可检索", incSearch.results.some((r) => (r.meta?.docId || r.id).startsWith("inc-1")), "top1=" + (incSearch.results[0]?.meta?.title || incSearch.results[0]?.id));

  const reset = await s.evaluate("window.__kb.reset()");
  const after = await s.evaluate("window.__kb.search('seekdb', 5)");
  check("重置清空知识库", reset && after.results.length === 0, "重置后命中=" + after.results.length);

  const metrics = await s.evaluate("window.__kb.getMetrics()");
  check("指标齐全", !!(metrics.model && metrics.ingest && metrics.query), "model/ingest/query 三段均有数据");
} catch (err) {
  check("执行异常", false, err.message);
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok).length;
console.log("\n" + (results.length - failed) + "/" + results.length + " 通过");
process.exit(failed ? 1 : 0);
