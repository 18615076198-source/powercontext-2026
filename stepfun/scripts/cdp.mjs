/**
 * 极简 CDP 客户端 + 浏览器启动器（无第三方依赖，Node 22+ 自带 WebSocket）。
 * 供 smoke / benchmark 脚本复用：启动 Edge 无头实例，打开页面，执行页面内 JS。
 */
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const EDGE_CANDIDATES = [
  process.env.EDGE_PATH,
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

async function findBrowser() {
  for (const candidate of EDGE_CANDIDATES) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {}
  }
  throw new Error("找不到 Edge/Chrome 可执行文件，请设置 EDGE_PATH");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class CdpSession {
  constructor(ws, id) {
    this.ws = ws;
    this.id = id;
    this.seq = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
        if (msg.method === "Runtime.exceptionThrown") {
          const detail = msg.params?.exceptionDetails;
          console.error("[page exception]", detail?.exception?.description || detail?.text);
        }
        if (msg.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(msg.params?.type)) {
          const text = (msg.params.args || []).map((a) => a.value ?? a.description ?? "").join(" ");
          if (text) console.log("[page " + msg.params.type + "]", String(text).slice(0, 300));
        }
      }
    });
  }

  send(method, params = {}, timeoutMs = 240000) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("CDP 超时: " + method));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, timeoutMs = 240000) {
    const result = await this.send(
      "Runtime.evaluate",
      { expression, awaitPromise: true, returnByValue: true, userGesture: true },
      timeoutMs,
    );
    if (result.exceptionDetails) {
      throw new Error("页面异常: " + (result.exceptionDetails.exception?.description || result.exceptionDetails.text));
    }
    return result.result?.value;
  }
}

export async function launchBrowser({ url, port = 9333, headless = true, extraArgs = [], profileDir = null, disableGpu = null }) {
  const browser = await findBrowser();
  const profile = profileDir || (await fs.mkdtemp(path.join(os.tmpdir(), "kb-browser-")));
  const gpuOff = disableGpu === null ? headless : disableGpu;
  const args = [
    headless ? "--headless=new" : "",
    gpuOff ? "--disable-gpu" : null,
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--remote-debugging-port=" + port,
    "--user-data-dir=" + profile,
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1360,900",
    ...extraArgs,
    url,
  ].filter(Boolean);
  const proc = spawn(browser, args, { stdio: "ignore", detached: false });

  let version = null;
  for (let i = 0; i < 100; i += 1) {
    try {
      const res = await fetch("http://127.0.0.1:" + port + "/json/version");
      if (res.ok) {
        version = await res.json();
        break;
      }
    } catch {}
    await sleep(200);
  }
  if (!version) {
    proc.kill();
    throw new Error("浏览器调试端口未就绪");
  }

  let page = null;
  for (let i = 0; i < 60; i += 1) {
    const list = await (await fetch("http://127.0.0.1:" + port + "/json/list")).json();
    page = list.find((t) => t.type === "page" && t.url.startsWith("http"));
    if (page) break;
    await sleep(250);
  }
  if (!page) {
    proc.kill();
    throw new Error("没有找到页面 target");
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  const session = new CdpSession(ws, page.id);
  await session.send("Runtime.enable");
  await session.send("Page.enable");

  return {
    browser,
    version: version.Browser,
    profile,
    process: proc,
    pageUrl: page.url,
    session,
    async close() {
      try {
        ws.close();
      } catch {}
      try {
        proc.kill();
      } catch {}
      await sleep(300);
      try {
        await fs.rm(profile, { recursive: true, force: true });
      } catch {}
    },
  };
}
