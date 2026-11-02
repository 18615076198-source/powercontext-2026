/** 重建角色池：node service/seed.mjs */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { MatchmakerStore } from "./store.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const personas = JSON.parse(await fs.readFile(path.join(__dirname, "personas.json"), "utf8"));
const store = await new MatchmakerStore().init();
const stats = await store.seed(personas);
console.log("seed 完成:", JSON.stringify(stats));
await store.close();
