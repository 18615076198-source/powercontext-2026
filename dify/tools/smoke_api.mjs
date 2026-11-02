/** 后端 API 冒烟测试（UTF-8 安全）：match -> archive -> history -> match again */
const BASE = process.env.API_BASE || "http://127.0.0.1:7870";

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(path + " -> " + res.status + " " + JSON.stringify(data));
  return data;
}

const user = "node-tester-" + Date.now().toString(36);
const profile = "我是程序员，28 岁，喜欢猫和手冲咖啡，周末想找人一起看展，能接受宅家";
const match = await post("/api/match", { user, profile, message: "你好，我想认真找个人", vibe: "认真" });
console.log("match mode:", match.mode, "| tags:", match.query_tags.join(","), "| history:", match.history.length);
for (const c of match.candidates) console.log("  -", c.name, "score=" + c.score, "|", c.tags.join("/"), "|", c.redflags.join(";"));

const report = "月老批语：你与「" + match.candidates[0].name + "」同频，但请先确认对方能否接受你周末不出门。";
const archived = await post("/api/archive", { user, profile, candidates: match.candidates.map((c) => c.name), report });
console.log("archive:", JSON.stringify(archived));

const history = await post("/api/history", { user });
console.log("history count:", history.count, "| report intact:", history.matches[0]?.report === report);

const again = await post("/api/match", { user, profile, message: "再给我看看别人", vibe: "认真" });
console.log("second match history:", again.history.length, "| first:", again.candidates[0]?.name, "| mode:", again.mode);
