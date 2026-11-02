const $ = (id) => document.getElementById(id);
const state = { kind: '学习' };

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
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


