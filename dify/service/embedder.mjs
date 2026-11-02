/**
 * 本地 embedding（bge-small-zh-v1.5，INT8 ONNX），用于把「相亲简历」和角色档案映射到同一向量空间。
 * 完全离线，不调用任何云端接口。
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { env, pipeline } from "@huggingface/transformers";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const DIM = 512;
export const MODEL_ID = "Xenova/bge-small-zh-v1.5";

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = path.join(__dirname, "models") + path.sep;

let extractorPromise = null;

async function getExtractor() {
  if (!extractorPromise) {
    extractorPromise = pipeline("feature-extraction", MODEL_ID, { dtype: "q8", device: "cpu" });
  }
  return extractorPromise;
}

export async function embed(texts) {
  const extractor = await getExtractor();
  const output = await extractor(texts, { pooling: "mean", normalize: true });
  const [count, dim] = output.dims;
  const vectors = [];
  for (let i = 0; i < count; i += 1) {
    vectors.push(Array.from(output.data.subarray(i * dim, (i + 1) * dim)));
  }
  return vectors;
}
