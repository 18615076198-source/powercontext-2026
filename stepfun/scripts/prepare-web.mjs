#!/usr/bin/env node
/**
 * 把 npm 里的浏览器运行时复制到 web/vendor/（仓库不提交这些大文件）：
 *   - @huggingface/transformers 的浏览器 ESM 构建
 *   - onnxruntime-web 的 wasm 加载器与二进制（CPU 与 WebGPU/jsep 两套）
 */
import fs from "node:fs/promises";
import path from "node:path";

const ROOT = path.resolve(process.cwd());
const VENDOR = path.join(ROOT, "web", "vendor");
const NM = path.join(ROOT, "node_modules");
const TRANSFORMERS = path.join(NM, "@huggingface", "transformers", "dist");

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function findOrtDist() {
  const direct = path.join(NM, "onnxruntime-web", "dist");
  if (await exists(direct)) return direct;
  const pnpmDir = path.join(NM, ".pnpm");
  let entries = [];
  try {
    entries = await fs.readdir(pnpmDir);
  } catch {
    return null;
  }
  const candidates = entries.filter((name) => name.startsWith("onnxruntime-web@")).sort().reverse();
  for (const name of candidates) {
    const candidate = path.join(pnpmDir, name, "node_modules", "onnxruntime-web", "dist");
    if (await exists(candidate)) return candidate;
  }
  return null;
}

async function copy(src, dest) {
  await fs.mkdir(path.dirname(dest), { recursive: true });
  await fs.copyFile(src, dest);
  const stat = await fs.stat(dest);
  console.log("  " + path.relative(ROOT, dest) + "  " + (stat.size / 1024 / 1024).toFixed(2) + " MB");
  return stat.size;
}

async function main() {
  await fs.mkdir(VENDOR, { recursive: true });
  const manifest = { files: {} };

  const ort = await findOrtDist();
  if (!ort) throw new Error("找不到 onnxruntime-web 的 dist 目录，请先 npm install");
  const wanted = [
    "ort-wasm-simd-threaded.mjs",
    "ort-wasm-simd-threaded.wasm",
    "ort-wasm-simd-threaded.jsep.mjs",
    "ort-wasm-simd-threaded.jsep.wasm",
    "ort-wasm-simd-threaded.asyncify.mjs",
    "ort-wasm-simd-threaded.asyncify.wasm",
  ];
  for (const file of wanted) {
    const src = path.join(ort, file);
    if (await exists(src)) {
      manifest.files[file] = await copy(src, path.join(VENDOR, file));
    } else {
      console.log("  ! 缺少 " + file);
    }
  }
  // transformers 自带的 jsep 加载器（版本对齐，优先使用）
  const bundledLoader = path.join(TRANSFORMERS, "ort-wasm-simd-threaded.jsep.mjs");
  if (await exists(bundledLoader)) {
    manifest.files["ort-wasm-simd-threaded.jsep.mjs"] = await copy(
      bundledLoader,
      path.join(VENDOR, "ort-wasm-simd-threaded.jsep.mjs"),
    );
  }

  manifest.totalBytes = Object.values(manifest.files).reduce((a, b) => a + b, 0);
  await fs.writeFile(path.join(VENDOR, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log("\nvendor 就绪: " + (manifest.totalBytes / 1024 / 1024).toFixed(1) + " MB");
}

main().catch((err) => {
  console.error("失败: " + err.message);
  process.exit(1);
});
