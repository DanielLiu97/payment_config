# -*- coding: utf-8 -*-
"""
基线配置生成器 Web 路由

提供独立的页面和 API，挂载到主 FastAPI 应用即可使用。
"""
import os
import tempfile
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from baseline_generator.generator import generate_baseline
from baseline_generator.excel_writer import write_baseline_excel
from webui.validators import validate_admin_cookie

router = APIRouter(prefix="/baseline", tags=["baseline-generator"])

# 简易的异步任务存储（内存）
_tasks: dict = {}
_tasks_lock = threading.Lock()


def _parse_showcase_ids(raw: str) -> list:
    """解析橱窗ID输入，支持逗号、加号、空格分隔"""
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail="请填写橱窗ID")
    text = raw.strip().replace("+", ",").replace("，", ",").replace(" ", ",")
    ids = []
    for part in text.split(","):
        p = part.strip()
        if not p:
            continue
        # 支持 "支付页：3553" 格式
        import re
        m = re.search(r"\d+", p)
        if m:
            ids.append(int(m.group()))
        else:
            raise HTTPException(status_code=400, detail=f"无法解析橱窗ID: {p}")
    if not ids:
        raise HTTPException(status_code=400, detail="请填写至少一个橱窗ID")
    return list(dict.fromkeys(ids))


@router.get("", response_class=HTMLResponse)
def baseline_page():
    return HTMLResponse(_PAGE_HTML)


@router.post("/api/generate")
def api_generate(
    showcase_ids: str = Form(...),
    platform: str = Form("pc"),
    env: str = Form("online"),
    country: str = Form("US"),
):
    """创建基线生成任务（后台异步执行）"""
    from webui.settings import load_settings
    settings = load_settings()

    if not settings.admin_cookie:
        raise HTTPException(status_code=500, detail="未配置 PAYMENT_ADMIN_COOKIE，无法调用价格接口")

    validate_admin_cookie(settings.admin_cookie)

    parsed_ids = _parse_showcase_ids(showcase_ids)
    task_id = f"bl-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    task_state = {
        "id": task_id,
        "status": "running",
        "progress": [],
        "showcase_ids": parsed_ids,
        "platform": platform,
        "env": env,
        "country": country,
        "file_path": None,
        "error": None,
        "row_count": 0,
        "warnings": [],
    }
    with _tasks_lock:
        _tasks[task_id] = task_state

    def _run():
        try:
            def _on_progress(msg: str):
                with _tasks_lock:
                    task_state["progress"].append(msg)

            result = generate_baseline(
                showcase_ids=parsed_ids,
                platform=platform,
                env=env,
                country=country,
                cookie=settings.admin_cookie,
                progress_callback=_on_progress,
            )

            if not result.rows:
                task_state["status"] = "failed"
                task_state["error"] = "未生成任何数据行，请检查橱窗ID是否正确"
                task_state["warnings"] = result.warnings
                return

            output_dir = tempfile.mkdtemp(prefix="baseline_")
            ids_label = "_".join(str(s) for s in parsed_ids)
            filename = f"baseline_{platform}_{country}_{ids_label}.xlsx"
            output_path = os.path.join(output_dir, filename)

            write_baseline_excel(result, output_path)

            task_state["status"] = "completed"
            task_state["file_path"] = output_path
            task_state["row_count"] = len(result.rows)
            task_state["warnings"] = result.warnings
        except Exception as e:
            task_state["status"] = "failed"
            task_state["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return JSONResponse({"id": task_id, "status": "running"})


@router.get("/api/tasks/{task_id}")
def api_task_status(task_id: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": task["id"],
        "status": task["status"],
        "progress": task["progress"],
        "row_count": task["row_count"],
        "warnings": task["warnings"],
        "error": task["error"],
        "has_file": bool(task["file_path"]),
    }


@router.get("/api/tasks/{task_id}/download")
def api_download(task_id: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed" or not task["file_path"]:
        raise HTTPException(status_code=400, detail="文件尚未生成")
    if not os.path.isfile(task["file_path"]):
        raise HTTPException(status_code=404, detail="文件已过期")
    return FileResponse(
        task["file_path"],
        filename=os.path.basename(task["file_path"]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── 页面 HTML ─────────────────────────────────────────────
_PAGE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>基线配置生成器</title>
  <style>
    body { font-family: "Google Sans", "Segoe UI", Arial, sans-serif; margin: 0; color: #202124; background: #f1f3f4; }
    .page { max-width: 820px; margin: 24px auto; padding: 0 12px; }
    .hero { margin-bottom: 14px; }
    .hero h2 { margin: 0 0 6px 0; font-size: 26px; }
    .hero .sub { color: #5f6368; font-size: 13px; }
    .card { border: 1px solid #dadce0; padding: 16px; border-radius: 12px; margin-bottom: 14px; background: #fff; box-shadow: 0 1px 2px rgba(60,64,67,.15); }
    .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
    label { display: block; margin-top: 4px; font-size: 13px; color: #3c4043; font-weight: 500; }
    input, select { padding: 9px 10px; width: 100%; box-sizing: border-box; margin-top: 6px; border: 1px solid #dadce0; border-radius: 8px; background: #fff; }
    input:focus, select:focus { border-color: #1a73e8; outline: none; box-shadow: 0 0 0 2px rgba(26,115,232,.15); }
    button { margin-top: 12px; padding: 10px 20px; cursor: pointer; border: none; border-radius: 20px; background: #1a73e8; color: #fff; font-weight: 600; font-size: 14px; }
    button:hover { background: #1557b0; }
    button:disabled { background: #dadce0; color: #80868b; cursor: not-allowed; }
    .btn-outline { background: #fff; color: #1a73e8; border: 1px solid #dadce0; }
    .btn-outline:hover { background: #f8faff; border-color: #1a73e8; }
    .btn-link { display: inline-block; padding: 8px 14px; border: 1px solid #dadce0; border-radius: 20px; background: #fff; color: #1f1f1f; font-weight: 600; text-decoration: none; font-size: 13px; }
    .btn-link:hover { border-color: #1a73e8; color: #1a73e8; background: #f8faff; }
    pre { background: #f8f9fa; border: 1px solid #e0e0e0; padding: 12px; border-radius: 8px; overflow: auto; max-height: 300px; font-size: 12px; line-height: 1.6; }
    .muted { color: #5f6368; font-size: 12px; }
    .required::after { content: " *"; color: #d93025; font-weight: bold; }
    .tips { font-size: 12px; color: #3c4043; background: #f8f9fa; border: 1px dashed #dadce0; padding: 8px 10px; margin: 8px 0 0; border-radius: 8px; }
    .summary-box { background: #e8f0fe; border: 1px solid #d2e3fc; border-radius: 10px; padding: 12px; margin-top: 10px; }
    .ok { color: #0b7a0b; }
    .bad { color: #b42318; }
    .warn { color: #e37400; }
    .action-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .flow-steps { display: flex; align-items: center; gap: 6px; margin: 10px 0; font-size: 12px; color: #5f6368; flex-wrap: wrap; }
    .flow-steps .step { background: #e8f0fe; color: #1a73e8; padding: 4px 10px; border-radius: 12px; font-weight: 600; white-space: nowrap; }
    .flow-steps .arrow { color: #dadce0; font-size: 16px; }
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h2>基线配置生成器</h2>
      <div class="sub">通过橱窗ID自动生成支付配置Excel基线文档，减少人工建档工作。</div>
    </div>

    <div class="card">
      <div style="font-size:13px; font-weight:600; margin-bottom:8px;">推荐工作流</div>
      <div class="flow-steps">
        <span class="step">输入橱窗ID</span> <span class="arrow">→</span>
        <span class="step">生成基线Excel</span> <span class="arrow">→</span>
        <span class="step">运营调整配置</span> <span class="arrow">→</span>
        <span class="step">星宿平台修改</span> <span class="arrow">→</span>
        <span class="step">上传校验</span>
      </div>
      <div class="tips">基线文档的数据来自橱窗接口实时查询。首优折扣率、部分条件商品可能未包含，需手动补充。</div>
    </div>

    <div class="card">
      <h3 style="margin:0 0 8px 0;">生成配置</h3>
      <div class="grid">
        <label class="required" style="grid-column:1/-1;">橱窗ID（支持多个，逗号分隔）
          <input id="showcaseIds" placeholder="如: 3553 或 3553,3554 或 支付页：3553">
        </label>
        <label class="required">平台
          <select id="platform">
            <option value="pc">pc</option>
            <option value="mac">mac</option>
            <option value="android">android</option>
            <option value="ios">ios</option>
            <option value="ipad">ipad</option>
            <option value="mobile">mobile</option>
            <option value="web">web</option>
          </select>
        </label>
        <label class="required">环境
          <select id="env">
            <option value="online">正式环境</option>
            <option value="test">测试环境</option>
          </select>
        </label>
        <label class="required">国家代码
          <input id="country" value="US">
        </label>
      </div>
      <div class="action-row" style="margin-top:14px;">
        <button id="btnGenerate" onclick="startGenerate()">生成基线文档</button>
        <a class="btn-link" href="/">返回校验页面</a>
      </div>
    </div>

    <div id="resultCard" class="card" style="display:none;">
      <h3 style="margin:0 0 8px 0;">生成结果</h3>
      <div id="statusText" class="muted"></div>
      <pre id="progressLog"></pre>
      <div id="resultSummary" class="summary-box" style="display:none;"></div>
      <div id="downloadRow" class="action-row" style="display:none; margin-top:10px;">
        <button id="btnDownload" class="btn-outline" onclick="downloadFile()">下载基线Excel</button>
      </div>
    </div>
  </div>
<script>
let currentTaskId = '';

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function startGenerate() {
  const btn = document.getElementById('btnGenerate');
  const showcaseIds = document.getElementById('showcaseIds').value.trim();
  if (!showcaseIds) { alert('请填写橱窗ID'); return; }
  const country = document.getElementById('country').value.trim();
  if (!country) { alert('请填写国家代码'); return; }

  btn.disabled = true;
  btn.textContent = '生成中...';
  document.getElementById('resultCard').style.display = 'block';
  document.getElementById('statusText').textContent = '正在创建任务...';
  document.getElementById('progressLog').textContent = '';
  document.getElementById('resultSummary').style.display = 'none';
  document.getElementById('downloadRow').style.display = 'none';

  const fd = new FormData();
  fd.append('showcase_ids', showcaseIds);
  fd.append('platform', document.getElementById('platform').value);
  fd.append('env', document.getElementById('env').value);
  fd.append('country', country);

  try {
    const res = await fetch('/baseline/api/generate', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('statusText').textContent = '创建失败: ' + (data.detail || JSON.stringify(data));
      btn.disabled = false; btn.textContent = '生成基线文档';
      return;
    }
    currentTaskId = data.id;
    pollTask(data.id);
  } catch (e) {
    document.getElementById('statusText').textContent = '请求异常: ' + (e.message || String(e));
    btn.disabled = false; btn.textContent = '生成基线文档';
  }
}

async function pollTask(taskId) {
  const logEl = document.getElementById('progressLog');
  const statusEl = document.getElementById('statusText');
  let done = false;
  while (!done) {
    if (currentTaskId !== taskId) return;
    try {
      const res = await fetch('/baseline/api/tasks/' + taskId);
      const task = await res.json();
      if (!res.ok) { statusEl.textContent = JSON.stringify(task); break; }

      statusEl.textContent = '状态: ' + task.status;
      logEl.textContent = (task.progress || []).join('\\n');
      logEl.scrollTop = logEl.scrollHeight;

      if (task.status === 'completed') {
        done = true;
        renderSuccess(task);
      } else if (task.status === 'failed') {
        done = true;
        renderFail(task);
      }
    } catch (e) {
      statusEl.textContent = '轮询异常: ' + (e.message || String(e));
      break;
    }
    if (!done) await new Promise(r => setTimeout(r, 2000));
  }
  const btn = document.getElementById('btnGenerate');
  btn.disabled = false; btn.textContent = '生成基线文档';
}

function renderSuccess(task) {
  const summary = document.getElementById('resultSummary');
  let html = '<div style="font-weight:600;margin-bottom:6px;">生成完成</div>';
  html += '<div class="ok">共 ' + task.row_count + ' 行配置数据</div>';
  if (task.warnings && task.warnings.length > 0) {
    html += '<div class="warn" style="margin-top:6px;">警告 (' + task.warnings.length + '):</div>';
    html += '<ul style="margin:4px 0 0 16px;">';
    task.warnings.forEach(w => { html += '<li class="warn">' + esc(w) + '</li>'; });
    html += '</ul>';
  }
  summary.innerHTML = html;
  summary.style.display = 'block';
  document.getElementById('downloadRow').style.display = 'flex';
}

function renderFail(task) {
  const summary = document.getElementById('resultSummary');
  let html = '<div style="font-weight:600;margin-bottom:6px;">生成失败</div>';
  html += '<div class="bad">' + esc(task.error || '未知错误') + '</div>';
  if (task.warnings && task.warnings.length > 0) {
    html += '<div class="warn" style="margin-top:6px;">警告:</div>';
    html += '<ul style="margin:4px 0 0 16px;">';
    task.warnings.forEach(w => { html += '<li>' + esc(w) + '</li>'; });
    html += '</ul>';
  }
  summary.innerHTML = html;
  summary.style.display = 'block';
}

function downloadFile() {
  if (!currentTaskId) return;
  const a = document.createElement('a');
  a.href = '/baseline/api/tasks/' + currentTaskId + '/download';
  a.click();
}
</script>
</body>
</html>
"""
