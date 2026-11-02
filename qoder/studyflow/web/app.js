const $ = (id) => document.getElementById(id);
const state = { kind: '学习' };

const localMemoryKey = 'studyflow-memories';
function localMemories() { return JSON.parse(localStorage.getItem(localMemoryKey) || '[]'); }
function saveLocalMemories(items) { localStorage.setItem(localMemoryKey, JSON.stringify(items)); }
function offlineResponse(path, options = {}) {
  const body = options.body ? JSON.parse(options.body) : {};
  const memories = localMemories();
  if (path.startsWith('/api/context')) {
    const query = decodeURIComponent(path.split('?q=')[1] || '').toLowerCase();
    return { items: memories.filter((item) => !query || item.text.toLowerCase().includes(query)), online: false, mode: '浏览器演示模式', memory_count: memories.length };
  }
  if (path === '/api/plan') {
    const topic = body.topic || '未命名主题';
    return { topic, actions: [`用 25 分钟补齐“${topic}”的一个关键概念，并写下 3 句自己的解释。`, `把当前进展“${(body.progress || '').slice(0, 42)}”拆成一个可验证的小问题。`, '在今天结束前做一次 5 分钟复盘，记录卡点和下一次开始的位置。'], context: memories, online: false, mode: '浏览器演示模式' };
  }
  if (path === '/api/remember' || path === '/api/review') {
    const text = path === '/api/review' ? `复盘｜${body.topic || '学习主题'}：${body.note || ''}` : body.text;
    const item = { id: `browser-${Date.now()}`, kind: body.kind || 'review', text, source: '浏览器本地存储', created_at: new Date().toISOString() };
    saveLocalMemories([item, ...memories]);
    return { item, message: '复盘已保存，下一次可以从这里继续。', online: false, mode: '浏览器演示模式', memory_count: memories.length + 1 };
  }
  return { online: false, mode: '浏览器演示模式', memory_count: memories.length };
}
async function request(path, options = {}) {
  try {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
    if (!response.ok) return offlineResponse(path, options);
    return await response.json();
  } catch { return offlineResponse(path, options); }
}

function showToast(node, text) { node.textContent = text; node.classList.remove('hidden'); setTimeout(() => node.classList.add('hidden'), 4200); }
function renderMemories(items) {
  $('memoryList').innerHTML = items.length ? items.map((item) => `<article class="memory-item"><p>${escapeHtml(item.text)}</p><small>${escapeHtml(item.kind || 'memory')} · ${escapeHtml(item.source || 'PowerContext')}</small></article>`).join('') : '<div class="memory-item"><p>还没有匹配的记忆，先保存一条吧。</p></div>';
}
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char])); }
function renderStatus(data) { $('status').classList.toggle('online', data.online); $('status').innerHTML = `<span class="status-dot"></span>${escapeHtml(data.mode)}`; }

async function refresh(query = '复习') { const data = await request(`/api/context?q=${encodeURIComponent(query)}`); renderStatus(data); renderMemories(data.items); }

document.querySelectorAll('.chip').forEach((chip) => chip.addEventListener('click', () => { document.querySelectorAll('.chip').forEach((c) => c.classList.remove('active')); chip.classList.add('active'); state.kind = chip.dataset.kind; }));
$('planBtn').addEventListener('click', async () => {
  const button = $('planBtn'); button.disabled = true; button.innerHTML = '生成中…';
  try { const data = await request('/api/plan', { method: 'POST', body: JSON.stringify({ topic: $('topic').value, progress: $('progress').value }) }); renderStatus(data); $('planResult').innerHTML = `<h3>为「${escapeHtml(data.topic)}」安排的下一步</h3><ol>${data.actions.map(escapeHtml).map((x) => `<li>${x}</li>`).join('')}</ol>`; $('planResult').classList.remove('hidden'); } catch (error) { alert(error.message); } finally { button.disabled = false; button.innerHTML = '生成下一步 <span>→</span>'; }
});
$('saveBtn').addEventListener('click', async () => { try { const data = await request('/api/remember', { method: 'POST', body: JSON.stringify({ text: $('memoryText').value, kind: state.kind }) }); renderStatus(data); showToast($('memoryToast'), `已保存到${data.online ? ' PowerContext' : '本地演示存储'}：${data.item.id}`); $('memoryText').value = ''; await refresh($('searchText').value); } catch (error) { showToast($('memoryToast'), error.message); } });
$('searchBtn').addEventListener('click', () => refresh($('searchText').value));
$('reviewBtn').addEventListener('click', async () => { try { const data = await request('/api/review', { method: 'POST', body: JSON.stringify({ topic: $('topic').value, note: $('reviewText').value }) }); renderStatus(data); showToast($('reviewToast'), data.message); $('reviewText').value = ''; await refresh('复盘'); } catch (error) { showToast($('reviewToast'), error.message); } });
refresh().catch((error) => showToast($('memoryToast'), error.message));


