# 第三方组件与许可

| 组件 | 版本 | 许可 | 用途 |
| --- | --- | --- | --- |
| `Xenova/bge-small-zh-v1.5`（基于 BAAI/bge-small-zh-v1.5） | onnx 转换 | MIT | 端侧 embedding 模型 |
| Transformers.js（`@huggingface/transformers`） | 4.3.2 | Apache-2.0 | 浏览器推理运行时 |
| ONNX Runtime Web | 1.31 | MIT | WebGPU / WASM 推理后端 |
| seekdb-js（`seekdb`） | 1.4.0 | Apache-2.0 | seekdb 客户端 |
| Express | 5.3.0 | MIT | 本地 HTTP 服务 |
| esbuild | 0.2x | MIT | 打包 transformers.js（构建期） |

模型文件从 Hugging Face 镜像下载（`scripts/fetch-model.mjs`），未做任何再分发修改；
语料为自编中文示例（`data/corpus.json`），不含第三方版权内容。
