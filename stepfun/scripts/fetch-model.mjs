#!/usr/bin/env node
/**
 * 下载端侧 embedding 模型（默认 Xenova/bge-small-zh-v1.5）到 web/models/。
 * 默认走 hf-mirror.com（国内可用），可用 HF_MIRROR 覆盖；模型文件不提交进仓库。
 *
 * 用法：
 *   node scripts/fetch-model.mjs                 # 下载 fp32 + fp16 + int8 三个精度
 *   node scripts/fetch-model.mjs --dtypes int8   # 只下 INT8（最小可运行集合）
 */
import { createWriteStream } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline as streamPipeline } from "node:stream/promises";

const MODEL_ID = process.env.MODEL_ID || "Xenova/bge-small-zh-v1.5";
const MIRROR = (process.env.HF_MIRROR || "https://hf-mirror.com").replace(/\/+$/, "");
const ROOT = path.resolve(process.cwd());
const OUT_DIR = path.join(ROOT, "web", "models", MODEL_ID);

const args = process.argv.slice(2);
const dtypeArg = args.includes("--dtypes") ? args[args.indexOf("--dtypes") + 1] : "int8";
const dtypes = new Set(dtypeArg.split(",").map((s) => s.trim()).filter(Boolean));

const BASE_FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"];
const ONNX_FILES = {
  fp32: "onnx/model.onnx",
  fp16: "onnx/model_fp16.onnx",
  int8: "onnx/model_quantized.onnx",
  int8_alt: "onnx/model_int8.onnx",
};

function human(bytes) {
  return (bytes / 1024 / 1024).toFixed(2) + " MB";
}

async function download(relPath) {
  const target = path.join(OUT_DIR, relPath);
  await fs.mkdir(path.dirname(target), { recursive: true });
  try {
    const stat = await fs.stat(target);
    if (stat.size > 0) {
      console.log("  = 已存在 " + relPath + " (" + human(stat.size) + ")");
      return stat.size;
    }
  } catch {}

  const url = MIRROR + "/" + MODEL_ID + "/resolve/main/" + relPath + "?download=true";
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok || !res.body) {
    throw new Error("下载失败 " + relPath + " HTTP " + res.status);
  }
  const total = Number(res.headers.get("content-length") || 0);
  console.log("  ↓ " + relPath + (total ? " (" + human(total) + ")" : ""));
  await streamPipeline(Readable.fromWeb(res.body), createWriteStream(target));
  const stat = await fs.stat(target);
  console.log("    -> " + human(stat.size));
  return stat.size;
}

async function main() {
  console.log("模型: " + MODEL_ID);
  console.log("镜像: " + MIRROR);
  console.log("目录: " + OUT_DIR);
  const manifest = { model: MODEL_ID, mirror: MIRROR, files: {}, totalBytes: 0 };

  for (const file of BASE_FILES) {
    try {
      manifest.files[file] = await download(file);
    } catch (err) {
      if (file === "special_tokens_map.json") {
        console.log("  ! 可选文件缺失，跳过: " + file);
        continue;
      }
      throw err;
    }
  }
  for (const dtype of dtypes) {
    const file = ONNX_FILES[dtype];
    if (!file) continue;
    try {
      manifest.files[file] = await download(file);
    } catch (err) {
      console.log("  ! " + dtype + " 下载失败: " + err.message);
    }
  }
  manifest.totalBytes = Object.values(manifest.files).reduce((a, b) => a + b, 0);
  await fs.writeFile(path.join(OUT_DIR, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log("\n完成，共 " + human(manifest.totalBytes) + "，清单写入 " + path.join(OUT_DIR, "manifest.json"));
}

main().catch((err) => {
  console.error("失败: " + err.message);
  process.exit(1);
});
