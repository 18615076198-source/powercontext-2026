/**
 * 端到端基准：对 (精度 × 后端) 组合跑同一套语料与查询，输出体积/吞吐/延迟/质量。
 *
 * 每个组合都新开一个浏览器实例（全新 profile，避免 HTTP 缓存影响「冷加载」计时）。
 *
 * 用法：
 *   node scripts/benchmark.mjs --dtypes q8,fp16,fp32 --device wasm
 *   node scripts/benchmark.mjs --dtypes fp16,fp32,q8 --device auto --headless false
 */
import fs from "node:fs/promises";
import path from "node:path";
import { launchBrowser } from "./cdp.mjs";

const argv = process.argv.slice(2);
function arg(name, fallback) {
  const index = argv.indexOf("--" + name);
  if (index === -1) return fallback;
  return argv[index + 1] ?? fallback;
}

const DTYPES = String(arg("dtypes", "q8,fp16,fp32")).split(",").map((s) => s.trim()).filter(Boolean);
const DEVICES = String(arg("device", "wasm")).split(",").map((s) => s.trim()).filter(Boolean);
const HEADLESS = String(arg("headless", "true")) !== "false";
const LATENCY_RUNS = Number(arg("runs", "16"));
const TOP_K = Number(arg("topk", "5"));
const OUT_DIR = path.resolve(process.cwd(), "results");
const URL = process.env.APP_URL || "http://127.0.0.1:7860/";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForKb(session, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await session.evaluate("typeof window.__kb === 'object' && !!window.__kb")) return true;
    await sleep(200);
  }
  return false;
}

async function runScenario({ dtype, device }) {
  const browser = await launchBrowser({
    url: URL,
    headless: HEADLESS,
    disableGpu: HEADLESS,
    extraArgs: HEADLESS ? [] : ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
  });
  try {
    if (!(await waitForKb(browser.session))) {
      throw new Error("页面未初始化：" + JSON.stringify(await browser.session.evaluate("window.__errors || []")));
    }
    const started = Date.now();
    const item = await browser.session.evaluate(
      "window.__kb.scenario({dtype:'" + dtype + "', device:'" + device + "', latencyRuns:" + LATENCY_RUNS + ", topK:" + TOP_K + ", evalTopK:10})",
      300000,
    );
    return {
      dtype,
      requestedDevice: device,
      ok: true,
      wallMs: Date.now() - started,
      browserVersion: browser.version,
      effectiveDevice: item.model.device,
      ...item,
    };
  } finally {
    await browser.close();
  }
}

async function main() {
  const out = { when: new Date().toISOString(), headless: HEADLESS, appUrl: URL, device: DEVICES.join(","), scenarios: [] };
  let version = null;
  for (const device of DEVICES) {
    for (const dtype of DTYPES) {
      process.stdout.write("scenario " + dtype + "/" + device + " ... ");
      const started = Date.now();
      let item;
      try {
        item = await runScenario({ dtype, device });
        if (!version) version = item.browserVersion;
        console.log(
          "ok  后端=" + item.effectiveDevice +
          "  加载=" + item.model.loadMs + "ms" +
          "  体积=" + (item.model.modelBytes / 1024 / 1024).toFixed(2) + "MB" +
          "  向量化=" + item.ingest.embedMs + "ms(" + item.ingest.chunksPerSec + "块/s)" +
          "  写入=" + item.ingest.writeMs + "ms  刷新=" + item.ingest.refreshMs + "ms" +
          "  p50=" + item.latency.p50 + "ms  R@5=" + item.quality.recall5 + " nDCG@10=" + item.quality.ndcg10,
        );
      } catch (err) {
        item = { dtype, requestedDevice: device, ok: false, error: err.message, wallMs: Date.now() - started };
        console.log("FAILED: " + err.message);
      }
      out.scenarios.push(item);
    }
  }
  out.browser = version;
  await fs.mkdir(OUT_DIR, { recursive: true });
  const file = path.join(OUT_DIR, "bench-" + (HEADLESS ? "headless" : "headed") + "-" + Date.now() + ".json");
  await fs.writeFile(file, JSON.stringify(out, null, 2));
  console.log("\n结果写入 " + file);
}

main().catch((err) => {
  console.error("benchmark failed:", err.message);
  process.exit(1);
});
