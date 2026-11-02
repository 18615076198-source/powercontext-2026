/**
 * seekdb 数据层：会话 -> collection，向量 + 全文混合检索全部在 seekdb 内完成。
 *
 * 关键点：
 *  - 每个浏览器会话一个 collection（kb_<sid>），切换/重置互不影响；
 *  - embedding 由浏览器算好后传入，服务端只做存储与检索（不调云端推理）；
 *  - 混合检索走 seekdb-js 的 hybridSearch（底层 DBMS_HYBRID_SEARCH + RRF 融合）；
 *  - 写入后 refresh_index()，保证新导入内容立即可检索。
 */
import {
  SeekdbAdminClient,
  SeekdbClient,
  Schema,
  VectorIndexConfig,
  FulltextIndexConfig,
} from "seekdb";

const DB_NAME = process.env.SEEKDB_DB || "stepfun_kb";
const DIM = Number(process.env.EMBED_DIM || 512);
const BATCH_SIZE = Number(process.env.INGEST_BATCH || 32);
const CONN = {
  host: process.env.SEEKDB_HOST || "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT || 2881),
  user: process.env.SEEKDB_USER || "root",
  password: process.env.SEEKDB_PASSWORD || "",
};

function now() {
  return Number(process.hrtime.bigint() / 1000n) / 1000;
}

function firstRow(matrix) {
  if (!Array.isArray(matrix) || matrix.length === 0) return [];
  return Array.isArray(matrix[0]) ? matrix[0] : matrix;
}

export class KnowledgeStore {
  constructor() {
    this.client = null;
    this.cache = new Map();
    this.version = "unknown";
  }

  async init() {
    const admin = new SeekdbAdminClient(CONN);
    try {
      await admin.createDatabase(DB_NAME);
    } catch (err) {
      if (!/exist/i.test(String(err.message))) throw err;
    } finally {
      await admin.close();
    }
    this.client = new SeekdbClient({ ...CONN, database: DB_NAME });
    try {
      const rows = await this.client.execute("select version() as v");
      this.version = String(rows?.[0]?.v || "unknown");
    } catch {
      this.version = "unknown";
    }
    return this;
  }

  get dimension() {
    return DIM;
  }

  async close() {
    if (this.client) await this.client.close();
  }

  collectionName(sessionId) {
    return "kb_" + sessionId;
  }

  async ensureCollection(sessionId) {
    if (!/^[a-z0-9]{6,32}$/.test(String(sessionId))) {
      throw new Error("非法会话 ID");
    }
    const name = this.collectionName(sessionId);
    if (this.cache.has(name)) return this.cache.get(name);

    let collection;
    if (await this.client.hasCollection(name)) {
      collection = await this.client.getCollection({ name, embeddingFunction: null });
    } else {
      const schema = new Schema({
        vectorIndex: new VectorIndexConfig({
          hnsw: { dimension: DIM, distance: "cosine" },
        }),
        fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
      });
      collection = await this.client.createCollection({
        name,
        schema,
        embeddingFunction: null,
      });
    }
    this.cache.set(name, collection);
    return collection;
  }

  async reset(sessionId) {
    const name = this.collectionName(sessionId);
    if (await this.client.hasCollection(name)) {
      await this.client.deleteCollection(name);
    }
    this.cache.delete(name);
    return this.ensureCollection(sessionId);
  }

  async stats(sessionId) {
    const collection = await this.ensureCollection(sessionId);
    const count = await collection.count();
    return { collection: this.collectionName(sessionId), count, dimension: DIM };
  }

  /** 批量 upsert + 刷新索引，返回分阶段耗时。 */
  async ingest(sessionId, docs) {
    const collection = await this.ensureCollection(sessionId);
    const ids = [];
    const documents = [];
    const embeddings = [];
    const metadatas = [];
    for (const doc of docs) {
      if (!doc || !doc.id || !doc.text || !Array.isArray(doc.embedding)) continue;
      if (doc.embedding.length !== DIM) {
        throw new Error("向量维度不符：" + doc.embedding.length + " != " + DIM);
      }
      ids.push(String(doc.id));
      documents.push(String(doc.text));
      embeddings.push(doc.embedding);
      metadatas.push(doc.meta || {});
    }
    if (!ids.length) return { inserted: 0, writeMs: 0, refreshMs: 0, count: await collection.count() };

    const writeStart = now();
    for (let i = 0; i < ids.length; i += BATCH_SIZE) {
      await collection.upsert({
        ids: ids.slice(i, i + BATCH_SIZE),
        documents: documents.slice(i, i + BATCH_SIZE),
        embeddings: embeddings.slice(i, i + BATCH_SIZE),
        metadatas: metadatas.slice(i, i + BATCH_SIZE),
      });
    }
    const writeMs = now() - writeStart;

    const refreshStart = now();
    await collection.refresh_index();
    const refreshMs = now() - refreshStart;

    const count = await collection.count();
    return { inserted: ids.length, writeMs, refreshMs, count };
  }

  /** 向量 + 全文混合检索；返回结果与耗时。 */
  async search(sessionId, query, embedding, topK = 5) {
    const collection = await this.ensureCollection(sessionId);
    const start = now();
    let raw = null;
    let mode = "hybrid";
    let hybridError = null;

    try {
      raw = await collection.hybridSearch({
        query: { whereDocument: { $contains: query } },
        knn: { queryEmbeddings: [embedding], nResults: topK },
        rank: { rrf: { rankWindowSize: 60, rankConstant: 60 } },
        nResults: topK,
        include: ["documents", "metadatas", "distances"],
      });
    } catch (err) {
      hybridError = err.message;
      mode = "vector";
      raw = await collection.query({
        queryEmbeddings: [embedding],
        nResults: topK,
        include: ["documents", "metadatas", "distances"],
      });
    }
    const searchMs = now() - start;

    const ids = firstRow(raw.ids);
    const docs = firstRow(raw.documents);
    const metas = firstRow(raw.metadatas);
    const dists = firstRow(raw.distances);

    const results = ids.map((id, i) => ({
      id: String(id),
      text: String(docs[i] ?? ""),
      meta: metas[i] || {},
      score: Number(dists[i] ?? 0),
    }));
    return { mode, results, searchMs, hybridError };
  }
}
