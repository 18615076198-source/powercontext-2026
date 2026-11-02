/**
 * seekdb 数据层：角色档案（向量 + 全文）与相亲档案（记忆）。
 *
 * - personas：24 位角色，hybridSearch（向量 + 全文，库内 RRF）负责撮合检索；
 * - matches：每次相亲的批语与结论，按 user 归档，用于跨会话记忆。
 */
import {
  SeekdbAdminClient,
  SeekdbClient,
  Schema,
  VectorIndexConfig,
  FulltextIndexConfig,
} from "seekdb";
import { DIM, embed } from "./embedder.mjs";

const DB_NAME = process.env.SEEKDB_DB || "dify_matchmaker";
const CONN = {
  host: process.env.SEEKDB_HOST || "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT || 2881),
  user: process.env.SEEKDB_USER || "root",
  password: process.env.SEEKDB_PASSWORD || "",
};

const TAGS = [
  "植物", "手冲咖啡", "黑胶", "雨天", "加班", "飞盘", "精酿", "OKR", "诗歌", "深夜", "猫", "便利店",
  "玄学", "塔罗", "代码", "道观", "撸铁", "鸡胸肉", "早起", "蛋白粉", "动漫", "手办", "漫展", "同人",
  "菜市场", "人类学", "辣", "方言", "电音", "夜骑", "耳机", "livehouse", "钓鱼", "养生", "茶", "早睡",
  "脱口秀", "段子", "酒吧", "社恐", "海淘", "香水", "vintage", "旅行", "狗", "救助", "流浪动物",
  "地铁", "城市", "摄影", "地图", "减肥", "轻食", "直播", "科幻", "极客", "广场舞", "砍价", "火锅",
  "魔方", "中医", "哲学", "徒步", "剧本杀", "推理", "戏剧", "夜宵", "极简", "播客", "展览", "咖啡",
  "露营", "藏区", "拍摄", "做饭", "美食", "菜谱", "自由职业", "反内卷", "MBTI", "算命", "书店", "酒",
  "音乐", "电影", "游戏", "骑行", "爬山", "滑雪", "健身", "读书", "写作", "绘画", "烘焙", "宠物",
].sort((a, b) => b.length - a.length);

export function extractTags(text) {
  const found = [];
  for (const tag of TAGS) {
    if (text.includes(tag) && !found.some((item) => item.includes(tag) || tag.includes(item))) {
      found.push(tag);
    }
    if (found.length >= 4) break;
  }
  return found;
}

function firstRow(matrix) {
  if (!Array.isArray(matrix) || matrix.length === 0) return [];
  return Array.isArray(matrix[0]) ? matrix[0] : matrix;
}

function toPersona(meta, score) {
  return {
    id: meta.id,
    name: meta.name,
    age: meta.age,
    city: meta.city,
    job: meta.job,
    tags: meta.tags || [],
    redflags: meta.redflags || [],
    catchphrase: meta.catchphrase || "",
    bio: meta.bio || "",
    score: Number(Number(score || 0).toFixed(4)),
  };
}

export class MatchmakerStore {
  constructor() {
    this.client = null;
    this.version = "unknown";
    this.personas = null;
    this.matches = null;
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
    } catch {}

    for (const name of ["personas", "matches"]) {
      if (await this.client.hasCollection(name)) {
        await this.client.getCollection({ name, embeddingFunction: null });
      } else {
        await this.client.createCollection({ name, schema: this.schema(), embeddingFunction: null });
      }
    }
    this.personas = await this.client.getCollection({ name: "personas", embeddingFunction: null });
    this.matches = await this.client.getCollection({ name: "matches", embeddingFunction: null });
    return this;
  }

  schema() {
    return new Schema({
      vectorIndex: new VectorIndexConfig({ hnsw: { dimension: DIM, distance: "cosine" } }),
      fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
    });
  }

  async close() {
    if (this.client) await this.client.close();
  }

  async stats() {
    return {
      personas: await this.personas.count(),
      matches: await this.matches.count(),
      seekdb: this.version,
    };
  }

  /** 重建角色池（幂等，可反复调用）。 */
  async seed(personas) {
    try {
      await this.client.deleteCollection("personas");
    } catch {}
    this.personas = await this.client.createCollection({
      name: "personas",
      schema: this.schema(),
      embeddingFunction: null,
    });

    const documents = personas.map((p) => [p.name, p.tags.join(" "), p.catchphrase, p.bio].join(" "));
    const embeddings = await embed(documents);
    const metadatas = personas.map((p) => ({ ...p }));
    await this.personas.add({ ids: personas.map((p) => p.id), documents, embeddings, metadatas });
    await this.personas.refresh_index();
    return this.stats();
  }

  async listPersonas() {
    const res = await this.personas.get({ limit: 50, include: ["metadatas", "documents"] });
    const metas = firstRow(res.metadatas);
    return metas.map((meta) => toPersona(meta, 0));
  }

  async history(user, limit = 5) {
    try {
      const res = await this.matches.get({ where: { user }, limit, include: ["metadatas", "documents"] });
      const metas = firstRow(res.metadatas);
      return metas
        .map((meta) => ({
          candidates: meta.candidates || [],
          report: String(meta.report || "").slice(0, 400),
          createdAt: meta.createdAt || "",
        }))
        .sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
    } catch {
      return [];
    }
  }

  async match({ user, profile, message, vibe, topK = 3 }) {
    const text = [profile, message, vibe].filter(Boolean).join("。");
    const tags = extractTags(text);
    const [vector] = await embed([text || "一个想谈恋爱的人"]);

    let raw = null;
    let mode = "vector";
    if (tags.length) {
      try {
        raw = await this.personas.hybridSearch({
          query: { whereDocument: { $contains: tags[0] } },
          knn: { queryEmbeddings: [vector], nResults: Math.max(6, topK * 2) },
          rank: { rrf: { rankWindowSize: 60, rankConstant: 60 } },
          nResults: Math.max(6, topK * 2),
          include: ["documents", "metadatas", "distances"],
        });
        mode = "hybrid";
      } catch {
        raw = null;
      }
    }
    if (!raw) {
      raw = await this.personas.query({
        queryEmbeddings: [vector],
        nResults: Math.max(6, topK * 2),
        include: ["documents", "metadatas", "distances"],
      });
      mode = "vector";
    }

    const metas = firstRow(raw.metadatas);
    const scores = firstRow(raw.distances);
    const history = await this.history(user, 5);
    const seen = new Set(history.flatMap((item) => item.candidates || []));

    let candidates = metas.map((meta, index) => toPersona(meta, scores[index]));
    const unseen = candidates.filter((item) => !seen.has(item.name));
    if (unseen.length >= topK) candidates = unseen;
    candidates = candidates.slice(0, topK);

    return {
      user: user || "anonymous",
      mode,
      query_tags: tags,
      candidates,
      history,
      hints: {
        must_quote: ["catchphrase", "redflags", "tags"],
        style: "月老口吻，毒舌但有温度",
        history_note: history.length ? "开头必须引用一次历史相亲记录" : "这是第一次相亲，开头先递一杯茶",
      },
    };
  }

  async archive({ user, profile, candidates, report }) {
    const names = (candidates || [])
      .map((item) => (typeof item === "string" ? item : item.name))
      .filter(Boolean);
    const createdAt = new Date().toISOString();
    const id = "m-" + Date.now().toString(36);
    const text = [profile, "匹配对象：" + names.join("、"), report].filter(Boolean).join("\n");
    const [vector] = await embed([text || "一次相亲"]);
    await this.matches.upsert({
      ids: [id],
      documents: [text],
      embeddings: [vector],
      metadatas: [
        {
          user: user || "anonymous",
          candidates: names,
          report: String(report || "").slice(0, 4000),
          createdAt,
          profile: String(profile || "").slice(0, 1000),
        },
      ],
    });
    await this.matches.refresh_index();
    return { ok: true, id, total: await this.matches.count(), createdAt };
  }
}
