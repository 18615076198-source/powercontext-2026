/** 浏览器端冒烟测试：加载页面 -> 等模型 -> 导入示例 -> 检索 -> 输出指标。 */
import { launchBrowser } from "./cdp.mjs";

const URL = process.env.APP_URL || "http://127.0.0.1:7860/";
const browser = await launchBrowser({ url: URL });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForKb(session, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const ok = await session.evaluate("typeof window.__kb === 'object' && !!window.__kb");
    if (ok) return true;
    await sleep(300);
  }
  return false;
}

try {
  console.log("browser:", browser.version);
  if (!(await waitForKb(browser.session))) {
    const errors = await browser.session.evaluate("window.__errors || []");
    throw new Error("页面未初始化 window.__kb：" + JSON.stringify(errors));
  }
  const ready = await browser.session.evaluate("window.__kb.waitReady(240000)");
  console.log("model ready:", JSON.stringify(ready));

  const imported = await browser.session.evaluate("window.__kb.importSample()");
  console.log("import:", JSON.stringify(imported).slice(0, 400));

  const found = await browser.session.evaluate(
    "window.__kb.search('seekdb 怎么做向量和全文的混合检索', 5)",
  );
  console.log("search mode:", found.mode, "| results:", found.results.length);
  console.log("top:", JSON.stringify(found.results.slice(0, 3).map((r) => ({ id: r.id, title: r.meta?.title, score: r.score }))));
  console.log("query metrics:", JSON.stringify(found.query));

  const metrics = await browser.session.evaluate("window.__kb.getMetrics()");
  console.log("metrics:", JSON.stringify(metrics).slice(0, 900));
} catch (err) {
  console.error("SMOKE FAILED:", err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
