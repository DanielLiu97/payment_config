
let currentTaskId = '';
let latestTasks = [];

function tokenHeader() {
  return {};
}

async function downloadTemplate(ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
  const filename = 'payment_config_template_empty.xlsx';
  try {
    const res = await fetch('/api/template?t=' + Date.now(), { headers: tokenHeader(), credentials: 'same-origin' });
    if (!res.ok) {
      let msg = '下载失败 HTTP ' + res.status;
      try {
        const err = await res.json();
        if (err.detail) msg = (typeof err.detail === 'string') ? err.detail : JSON.stringify(err.detail);
      } catch (e) {}
      alert(msg);
      return false;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert('下载失败: ' + (e && e.message ? e.message : String(e)));
  }
  return false;
}

async function startTask() {
  const taskInfo = document.getElementById('taskInfo');
  try {
    const fileEl = document.getElementById('xlsx');
    const file = fileEl && fileEl.files ? fileEl.files[0] : null;
    if (!file) { alert('请先选择xlsx文件'); return; }
    const initiator = document.getElementById('initiator').value.trim();
    if (!initiator) { alert('请填写发起人姓名'); return; }
    const country = document.getElementById('country').value.trim();
    if (!country) { alert('请填写国家代码'); return; }

    taskInfo.innerText = '正在创建任务...';
    const fd = new FormData();
    fd.append('file', file);
    fd.append('platform', document.getElementById('platform').value);
    fd.append('env', document.getElementById('env').value);
    fd.append('country', country);
    fd.append('initiator', initiator);
    fd.append('sheet_numbers', document.getElementById('sheets').value.trim());
    fd.append('only_rows', document.getElementById('rows').value.trim());
    fd.append('send_bot', document.getElementById('sendBot').checked ? 'true' : 'false');

    const res = await fetch('/api/tasks', { method: 'POST', body: fd, headers: tokenHeader() });
    const data = await res.json();
    if (!res.ok) {
      const msg = data.detail || JSON.stringify(data);
      taskInfo.innerText = '启动失败: ' + msg;
      alert(msg);
      return;
    }
    taskInfo.innerText = '任务已创建: ' + data.id;
    pollTask(data.id);
  } catch (e) {
    const msg = e && e.message ? e.message : String(e);
    taskInfo.innerText = '启动失败（前端异常）: ' + msg;
    alert('启动失败（前端异常）: ' + msg);
  }
}

async function refreshTasks() {
  const st = document.getElementById('statusFilter').value.trim();
  const q = document.getElementById('taskQuery').value.trim();
  const initiator = document.getElementById('taskInitiator').value.trim();
  const params = new URLSearchParams();
  if (st) params.set('status', st);
  if (q) params.set('q', q);
  if (initiator) params.set('initiator', initiator);
  const suffix = params.toString() ? ('?' + params.toString()) : '';
  try {
    const res = await fetch('/api/tasks' + suffix, { headers: tokenHeader() });
    const data = await res.json();
    latestTasks = Array.isArray(data) ? data : [];
    renderTaskList(latestTasks);
    if (!currentTaskId && latestTasks.length > 0) {
      openTask(latestTasks[0].id);
    } else if (currentTaskId && latestTasks.some(t => t.id === currentTaskId)) {
      highlightTask(currentTaskId);
    }
  } catch (e) {
    const box = document.getElementById('taskList');
    const msg = e && e.message ? e.message : String(e);
    box.innerHTML = '<div class="task-item"><div class="task-meta">任务列表加载失败: ' + esc(msg) + '</div></div>';
  }
}

function useCurrentInitiatorFilter() {
  const current = document.getElementById('initiator').value.trim();
  if (!current) { alert('请先在上方填写发起人姓名'); return; }
  document.getElementById('taskInitiator').value = current;
  refreshTasks();
}

function clearInitiatorFilter() {
  document.getElementById('taskInitiator').value = '';
  refreshTasks();
}

function renderTaskList(tasks) {
  const box = document.getElementById('taskList');
  if (!tasks || tasks.length === 0) {
    box.innerHTML = '<div class="task-item"><div class="task-meta">暂无任务</div></div>';
    return;
  }
  box.innerHTML = tasks.map(t => {
    const init = (t.params && t.params.initiator) ? t.params.initiator : '-';
    const statusCls = 'status-' + (t.status || 'queued');
    const active = t.id === currentTaskId ? 'active' : '';
    return (
      '<div class="task-item ' + active + '" data-task-id="' + esc(t.id) + '">' +
      '<div class="task-title"><span class="status-dot ' + statusCls + '"></span>' + esc(t.id) + '</div>' +
      '<div class="task-meta">状态: ' + esc(t.status) + ' | 发起人: ' + esc(init) + '</div>' +
      '<div class="task-meta">创建: ' + esc(t.created_at || '-') + '</div>' +
      '</div>'
    );
  }).join('');
  box.querySelectorAll('.task-item[data-task-id]').forEach((el) => {
    el.addEventListener('click', () => {
      const tid = el.getAttribute('data-task-id');
      if (tid) openTask(tid);
    });
  });
}

function highlightTask(taskId) {
  const items = document.querySelectorAll('#taskList .task-item');
  items.forEach((el) => {
    if (el.getAttribute('data-task-id') === taskId) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });
}

function openTask(taskId) {
  currentTaskId = taskId;
  highlightTask(taskId);
  pollTask(taskId);
}

async function pollTask(id) {
  const box = document.getElementById('result');
  const summary = document.getElementById('resultSummary');
  const bar = document.getElementById('progressBar');
  const ptxt = document.getElementById('progressText');
  summary.style.display = 'none';
  box.textContent = '任务加载中: ' + id;
  let done = false;
  while (!done) {
    if (currentTaskId !== id) { return; }
    const res = await fetch('/api/tasks/' + id, { headers: tokenHeader() });
    if (res.status === 429) {
      const err = await res.json();
      box.textContent = JSON.stringify(err, null, 2);
      await new Promise(r => setTimeout(r, 5000));
      continue;
    }
    const task = await res.json();
    if (!res.ok) { box.textContent = JSON.stringify(task, null, 2); return; }
    const pct = task.progress_percent || 0;
    bar.value = pct;
    ptxt.innerText = pct + '%';
    box.textContent = JSON.stringify(task, null, 2);
    done = task.status === 'succeeded' || task.status === 'failed';
    if (!done) {
      await new Promise(r => setTimeout(r, 5000));
    }
  }
  const rr = await fetch('/api/tasks/' + id + '/result', { headers: tokenHeader() });
  const data = await rr.json();
  box.textContent = JSON.stringify(data, null, 2);
  renderResultSummary(id, data);
}

function esc(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function renderResultSummary(taskId, result) {
  const summary = document.getElementById('resultSummary');
  const totalErrors = Number(result.error_count || 0);
  const sheetResults = Array.isArray(result.sheet_results) ? result.sheet_results : [];
  const failedSheets = sheetResults.filter(x => Number(x.error_count || 0) > 0);
  const statusCls = totalErrors > 0 ? 'bad' : 'ok';
  const statusText = totalErrors > 0 ? '不通过' : '通过';

  let rows = '';
  if (sheetResults.length > 0) {
    rows = sheetResults.map(x => {
      const ec = Number(x.error_count || 0);
      const cls = ec > 0 ? 'bad' : 'ok';
      return '<li>Sheet' + esc(x.sheet_number) + '（' + esc(x.sheet_name) + '）：<span class="' + cls + '">' + (ec > 0 ? ('不通过，' + ec + '项') : '通过') + '</span></li>';
    }).join('');
  } else {
    rows = '<li class="' + statusCls + '">单Sheet结果：' + statusText + '</li>';
  }

  summary.innerHTML =
    '<div class="summary-title">任务摘要</div>' +
    '<div>任务ID：<code>' + esc(taskId) + '</code></div>' +
    '<div>结论：<span class="' + statusCls + '">' + statusText + '</span></div>' +
    '<div>错误总数：<span class="' + statusCls + '">' + esc(totalErrors) + '</span></div>' +
    '<div style="margin-top:6px;">Sheet结果：</div><ul style="margin:4px 0 0 18px;">' + rows + '</ul>';
  summary.style.display = 'block';
}

refreshTasks();
