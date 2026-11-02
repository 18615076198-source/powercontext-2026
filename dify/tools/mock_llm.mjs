/** 极简 OpenAI 兼容 mock 服务：只用于验证「LLM 模式」的接线，不代表真实模型输出。 */
import http from "node:http";

const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    if (!req.url.endsWith("/chat/completions")) {
      res.writeHead(404).end("not found");
      return;
    }
    let userText = "";
    try {
      const payload = JSON.parse(body);
      userText = (payload.messages || []).map((m) => m.content).join("\n");
    } catch {}
    const names = [...userText.matchAll(/###\s*\d+\.\s*([^·\n]+)/g)].map((m) => m[1].trim());
    const text = [
      "## 月老开场（mock 模型接线验证）",
      "茶刚泡上，月老我看你印堂发亮，今天有戏。",
      "## 今日撮合",
      names.length ? "本轮从 seekdb 捞到：" + names.join("、") : "（提示词里未解析到候选人，仅验证协议）",
      "## 月老悄悄话",
      "这条回复由本地 mock 模型返回，用于证明 Dify 的 LLM 节点调用链、变量替换与证据落盘都工作正常；真实效果请在 Dify 中绑定模型体验。",
      "## 月老签文",
      "代码写得再溜，也怕月老一句：你俩不合适。",
    ].join("\n");
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ id: "mock", object: "chat.completion", choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }] }));
  });
});
server.listen(8080, "127.0.0.1", () => console.log("mock llm on http://127.0.0.1:8080"));
