/**
 * seekdb 全链路自检（不依赖浏览器）：
 * 建集合 -> 写入 3 条随机向量文档 -> 刷新索引 -> 混合检索 -> 校验 top1 -> 清理。
 */
import { KnowledgeStore } from "../server/store.mjs";

function oneHot(dim, index) {
  const vec = new Array(dim).fill(0);
  vec[index % dim] = 1;
  return vec;
}

const store = await new KnowledgeStore().init();
const sid = "verify" + Date.now().toString(36);
let ok = false;
try {
  console.log("seekdb:", store.version, "| 维度:", store.dimension);
  const dim = store.dimension;
  await store.ensureCollection(sid);
  const ing = await store.ingest(sid, [
    { id: "v1", text: "seekdb 支持向量与全文的混合检索，一条查询完成两路召回", meta: { docId: "v1" }, embedding: oneHot(dim, 0) },
    { id: "v2", text: "浏览器端用 WebGPU 运行 embedding 模型，实现本地向量化", meta: { docId: "v2" }, embedding: oneHot(dim, 1) },
    { id: "v3", text: "西湖边的咖啡馆安静适合坐一下午", meta: { docId: "v3" }, embedding: oneHot(dim, 2) },
  ]);
  console.log("写入:", ing.inserted, "条 | write=" + Math.round(ing.writeMs) + "ms refresh=" + Math.round(ing.refreshMs) + "ms | count=" + ing.count);

  const res = await store.search(sid, "混合检索", oneHot(dim, 0), 3);
  console.log("检索模式:", res.mode, "| 耗时:", Math.round(res.searchMs) + "ms", "| 结果:", res.results.map((r) => r.meta.docId).join(","));
  ok = res.results.length > 0 && res.results[0].meta.docId === "v1";

  const hit = await store.search(sid, "不存在的关键词 xyz", oneHot(dim, 2), 3);
  console.log("无关键词命中时仍返回向量结果:", hit.results.length, "条");
  ok = ok && hit.results.length > 0;
} finally {
  try {
    await store.client.deleteCollection(store.collectionName(sid));
  } catch {}
  await store.close();
}

if (ok) {
  console.log("\n[PASS] seekdb 全链路正常（写入 -> 刷新 -> 混合检索）");
  process.exit(0);
}
console.error("\n[FAIL] seekdb 自检未通过");
process.exit(1);
