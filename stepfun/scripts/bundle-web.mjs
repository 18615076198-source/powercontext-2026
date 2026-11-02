#!/usr/bin/env node
/** 用 esbuild 把 transformers.js 打成浏览器可直接加载的单文件 ESM（含依赖解析）。 */
import { build } from "esbuild";
import path from "node:path";

const ROOT = path.resolve(process.cwd());
const outfile = path.join(ROOT, "web", "vendor", "transformers.bundle.js");

await build({
  entryPoints: [path.join(ROOT, "web", "src", "transformers-entry.js")],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  outfile,
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
});
console.log("bundle 生成: " + path.relative(ROOT, outfile));
