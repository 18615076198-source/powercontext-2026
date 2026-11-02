/**
 * 浏览器端 embedding 封装（Transformers.js + ONNX Runtime Web）。
 *
 * - 模型、tokenizer、wasm 全部从本机静态目录加载，运行时不需要外网；
 * - 优先 WebGPU，失败或不可用时自动降级 WASM，并记录原因供界面展示；
 * - dtype 支持 INT8（q8）/ FP16 / FP32 三档，用于量化前后对比。
 */
import { env, pipeline } from "./vendor/transformers.bundle.js";

export const MODEL_ID = "Xenova/bge-small-zh-v1.5";

export const DTYPE_INFO = {
  q8: { label: "INT8", file: "onnx/model_quantized.onnx", note: "INT8 动态量化" },
  fp16: { label: "FP16", file: "onnx/model_fp16.onnx", note: "FP16 半精度" },
  fp32: { label: "FP32", file: "onnx/model.onnx", note: "FP32 基线" },
};

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = "/models/";
env.useBrowserCache = false;

const wasmBackend = env.backends?.onnx?.wasm;
if (wasmBackend) {
  wasmBackend.wasmPaths = "/vendor/";
  const threads = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1));
  wasmBackend.numThreads = threads;
}

export async function detectWebGPU() {
  if (typeof navigator === "undefined" || !navigator.gpu) {
    return { available: false, reason: "navigator.gpu 不存在" };
  }
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return { available: false, reason: "requestAdapter() 返回 null" };
    return { available: true, reason: "adapter 可用" };
  } catch (err) {
    return { available: false, reason: err?.message || String(err) };
  }
}

async function readModelBytes(dtype) {
  try {
    const res = await fetch("/models/" + MODEL_ID + "/manifest.json", { cache: "no-store" });
    if (!res.ok) return null;
    const manifest = await res.json();
    const info = DTYPE_INFO[dtype];
    return manifest.files?.[info?.file] ?? null;
  } catch {
    return null;
  }
}

export class Embedder {
  constructor() {
    this.extractor = null;
    this.device = null;
    this.requestedDevice = null;
    this.dtype = null;
    this.loadMs = 0;
    this.modelBytes = null;
    this.fallback = null;
    this.gpu = null;
  }

  async load({ dtype = "auto", device = "auto", onProgress = null } = {}) {
    this.gpu = await detectWebGPU();
    const wanted = device === "auto" ? (this.gpu.available ? "webgpu" : "wasm") : device;
    // 自动精度：WebGPU 用 FP16（GPU 原生支持），WASM 用 INT8（CPU 更快更小）
    const resolvedDtype = dtype === "auto" ? (wanted === "webgpu" ? "fp16" : "q8") : dtype;
    this.requestedDevice = wanted;
    this.dtype = resolvedDtype;

    const started = performance.now();
    try {
      this.extractor = await pipeline("feature-extraction", MODEL_ID, {
        dtype: resolvedDtype,
        device: wanted,
        progress_callback: onProgress || undefined,
      });
      this.device = wanted;
      this.fallback = null;
    } catch (err) {
      if (wanted !== "webgpu") throw err;
      // WebGPU 初始化失败：降级到 WASM（FP16 在 CPU 上不可用时进一步退到 INT8）
      this.fallback = "WebGPU 加载失败：" + (err?.message || String(err));
      const fallbackDtype = resolvedDtype === "fp16" ? "q8" : resolvedDtype;
      this.extractor = await pipeline("feature-extraction", MODEL_ID, {
        dtype: fallbackDtype,
        device: "wasm",
        progress_callback: onProgress || undefined,
      });
      this.device = "wasm";
      this.dtype = fallbackDtype;
    }
    this.loadMs = performance.now() - started;
    this.modelBytes = await readModelBytes(this.dtype);
    return this;
  }

  async embedBatch(texts) {
    if (!this.extractor) throw new Error("模型尚未加载");
    const started = performance.now();
    const output = await this.extractor(texts, { pooling: "mean", normalize: true });
    const ms = performance.now() - started;
    const dims = output.dims;
    const data = output.data;
    const count = dims[0];
    const dim = dims[1];
    const vectors = [];
    for (let i = 0; i < count; i += 1) {
      vectors.push(Array.from(data.subarray(i * dim, (i + 1) * dim)));
    }
    return { vectors, ms, dim };
  }

  async dispose() {
    try {
      await this.extractor?.dispose?.();
    } catch {}
    this.extractor = null;
  }

  describe() {
    return {
      model: MODEL_ID,
      dtype: this.dtype,
      dtypeLabel: DTYPE_INFO[this.dtype]?.label || this.dtype,
      device: this.device,
      requestedDevice: this.requestedDevice,
      loadMs: Math.round(this.loadMs),
      modelBytes: this.modelBytes,
      fallback: this.fallback,
      webgpu: this.gpu,
    };
  }
}
