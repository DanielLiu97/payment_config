import os
import ipaddress
import socket
import threading
import time
from tempfile import NamedTemporaryFile
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from config.config import (
    ADMIN_API_BASE_URL,
    EXCEL_TEMPLATE_NAME,
    PRODUCT_LISTNEW_BASE_URL,
    PROJECT_ROOT,
    SHOP_WINDOW_API,
)
from config.logger import logger
from baseline_generator.web_routes import router as baseline_router
from webui.dashboard_stats import DashboardStatsService
from webui.runner import RunParams
from webui.settings import load_settings
from webui.task_manager import QueueFullError, TaskManager
from webui.validators import validate_admin_cookie

settings = load_settings()
task_manager = TaskManager(
    settings.data_dir,
    workers=settings.workers,
    max_queue_size=settings.max_queue_size,
    retention_days=settings.task_retention_days,
    cleanup_interval_seconds=settings.cleanup_interval_seconds,
    cleanup_enabled=(not settings.disable_task_cleanup),
)
DASHBOARD_RANGE_START = "2026-01-24"
dashboard_stats_service = DashboardStatsService(
    tasks_dir=task_manager.tasks_dir,
    range_start=DASHBOARD_RANGE_START,
)
app = FastAPI(title="支付配置自助校验", version="1.0.0")
app.include_router(baseline_router)
REFRESH_INTERVAL_SECONDS = 5
_task_refresh_lock = threading.Lock()
_task_last_refresh: dict = {}

DEFAULT_EXPECTED_HEADERS = [
    "国家",
    "会员类型",
    "价格类型",
    "商品序号",
    "周期",
    "总价",
    "均价",
    "价格ID",
    "商品ID",
    "买赠周期",
    "橱窗ID",
]
DEFAULT_EXPECTED_HEADERS_WITH_EXP = DEFAULT_EXPECTED_HEADERS + ["体验价价格", "体验价周期"]
HEADER_NAME_ALIASES = {
    "顺序": "商品序号",
    "月均价": "均价",
    "商品备注": "买赠周期",
    "体验价格": "体验价价格",
}


def _normalize_header_name(name: str) -> str:
    # 表头比较不区分大小写，并忽略首尾空格
    return str(name or "").strip().lower()


def _normalize_headers(headers: List[str]) -> List[str]:
    return [_normalize_header_name(h) for h in headers]


def _canonicalize_header_name(name: str) -> str:
    normalized = _normalize_header_name(name)
    return _normalize_header_name(HEADER_NAME_ALIASES.get(normalized, normalized))


def _canonicalize_headers(headers: List[str]) -> List[str]:
    return [_canonicalize_header_name(h) for h in headers]


def _format_header_diff(expected_headers: List[str], actual_headers: List[str]) -> str:
    """
    生成可读的表头差异说明：
    - 同列不一致（逐列列出）
    - 缺失列
    - 多余列
    """
    mismatch_parts: List[str] = []
    min_len = min(len(expected_headers), len(actual_headers))

    for idx in range(min_len):
        expected = str(expected_headers[idx]).strip()
        actual = str(actual_headers[idx]).strip()
        if _normalize_header_name(expected) != _normalize_header_name(actual):
            mismatch_parts.append(f"第{idx + 1}列: 当前[{actual}]，标准[{expected}]")

    if len(actual_headers) < len(expected_headers):
        missing = expected_headers[len(actual_headers):]
        mismatch_parts.append(f"缺失列({len(missing)}): {missing}")
    elif len(actual_headers) > len(expected_headers):
        extra = actual_headers[len(expected_headers):]
        mismatch_parts.append(f"多余列({len(extra)}): {extra}")

    if not mismatch_parts:
        return "表头存在差异，但未能定位具体列，请检查模板与上传文件。"
    return "；".join(mismatch_parts)


def _load_expected_headers(sheet_index: int) -> Tuple[List[str], str]:
    """
    读取用于校验的标准表头。
    约束：任务校验与模板下载必须使用同一模板文件，避免标准不一致。
    """
    template_path = _template_file_for_download()
    try:
        sheet_names = list(pd.ExcelFile(template_path).sheet_names)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=f"读取模板失败: {exc}") from exc

    if sheet_index < 0 or sheet_index >= len(sheet_names):
        raise HTTPException(
            status_code=400,
            detail=(
                f"模板sheet不存在：请求Sheet{sheet_index + 1}，"
                f"模板仅包含{len(sheet_names)}个sheet（{sheet_names}）。"
            ),
        )

    try:
        df = pd.read_excel(template_path, sheet_name=sheet_index, nrows=0)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=f"读取模板sheet失败: {exc}") from exc

    headers = [str(c).strip() for c in list(df.columns)]
    if not headers:
        raise HTTPException(status_code=500, detail=f"模板Sheet{sheet_index + 1}表头为空，请检查模板文件")
    return headers, template_path


def auth_guard(x_access_token: Optional[str] = Header(default=None)):
    return


def _parse_only_rows(raw: str) -> Optional[List[int]]:
    text = (raw or "").strip()
    if not text:
        return None
    values = []
    for part in text.replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        if not p.isdigit():
            raise HTTPException(status_code=400, detail=f"行号格式错误: {p}")
        row_no = int(p)
        if row_no <= 1:
            raise HTTPException(status_code=400, detail=f"Excel行号必须>=2: {row_no}")
        values.append(row_no)
    return sorted(set(values))


def _parse_sheet_numbers(raw: str) -> List[int]:
    text = (raw or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请填写要执行的Sheet序号")
    items: List[int] = []
    normalized = text.replace("，", ",")
    for part in normalized.split(","):
        p = part.strip()
        if not p:
            continue
        if "-" in p:
            seg = p.split("-", 1)
            if len(seg) != 2 or (not seg[0].strip().isdigit()) or (not seg[1].strip().isdigit()):
                raise HTTPException(status_code=400, detail=f"Sheet范围格式错误: {p}")
            start = int(seg[0].strip())
            end = int(seg[1].strip())
            if start <= 0 or end <= 0 or start > end:
                raise HTTPException(status_code=400, detail=f"Sheet范围不合法: {p}")
            items.extend(list(range(start, end + 1)))
        else:
            if not p.isdigit():
                raise HTTPException(status_code=400, detail=f"Sheet序号格式错误: {p}")
            num = int(p)
            if num <= 0:
                raise HTTPException(status_code=400, detail=f"Sheet序号必须>=1: {p}")
            items.append(num)
    if not items:
        raise HTTPException(status_code=400, detail="请填写至少一个Sheet序号")
    return sorted(set(items))


def _extract_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").strip().lower()


def _resolve_host_ips(host: str) -> List[str]:
    ips = set()
    if not host:
        return []
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            sockaddr = info[4]
            if sockaddr and len(sockaddr) > 0:
                ips.add(str(sockaddr[0]))
    except Exception as exc:
        logger.warning("解析主机失败 host=%s error=%s", host, exc)
        return []
    return sorted(ips)


def _is_suspicious_ip(ip_str: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
            or ip_obj.is_reserved
        )
    except Exception:
        return True


def _guard_online_env_integrity(env_name: str):
    if not settings.online_env_guard:
        return
    if (env_name or "").strip().lower() != "online":
        return

    online_base = (SHOP_WINDOW_API.get("online", {}) or {}).get("base_url", "")
    test_base = (SHOP_WINDOW_API.get("test", {}) or {}).get("base_url", "")
    online_host = _extract_host(online_base)
    test_host = _extract_host(test_base)
    admin_host = _extract_host(ADMIN_API_BASE_URL)
    product_host = _extract_host(PRODUCT_LISTNEW_BASE_URL)

    if not online_host:
        raise HTTPException(status_code=500, detail="online环境未配置 pay_window 域名")
    if "test" in online_host:
        raise HTTPException(status_code=400, detail=f"online环境域名疑似污染：{online_host}")

    online_ips = _resolve_host_ips(online_host)
    if not online_ips:
        raise HTTPException(status_code=400, detail=f"online环境域名解析失败：{online_host}")

    suspicious_ips = [ip for ip in online_ips if _is_suspicious_ip(ip)]
    if suspicious_ips:
        raise HTTPException(
            status_code=400,
            detail=f"online环境域名解析异常（疑似被hosts/本地网络污染）：{online_host} -> {suspicious_ips}",
        )

    test_ips = _resolve_host_ips(test_host) if test_host else []
    overlap = sorted(set(online_ips) & set(test_ips))
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=(
                "online/test 域名解析到同一IP，疑似环境污染："
                f"online({online_host})={online_ips}, test({test_host})={test_ips}"
            ),
        )

    # 记录诊断信息，便于排查 SwitchHosts 影响（不阻断）
    logger.info(
        "环境诊断 online_host=%s online_ips=%s test_host=%s test_ips=%s admin_host=%s admin_ips=%s product_host=%s product_ips=%s",
        online_host,
        online_ips,
        test_host,
        test_ips,
        admin_host,
        _resolve_host_ips(admin_host) if admin_host else [],
        product_host,
        _resolve_host_ips(product_host) if product_host else [],
    )


def _validate_headers(file_path: str, sheet_index: int):
    expected_headers, template_path = _load_expected_headers(sheet_index)
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_index, nrows=0)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail=f"读取sheet失败: {exc}") from exc
    headers = [str(c).strip() for c in list(df.columns)]
    canonical_headers = _canonicalize_headers(headers)
    has_exp_price = _canonicalize_header_name("体验价价格") in canonical_headers
    has_exp_cycle = _canonicalize_header_name("体验价周期") in canonical_headers
    if has_exp_price != has_exp_cycle:
        raise HTTPException(
            status_code=400,
            detail=(
                "模板表头不匹配：体验价扩展列必须同时存在。"
                f"当前表头: {headers}。"
                "请确保 L1=体验价价格 且 M1=体验价周期，或移除两列并使用旧模板。"
            ),
        )

    canonical_expected = _canonicalize_headers(expected_headers)
    valid_header_sets = [
        _canonicalize_headers(DEFAULT_EXPECTED_HEADERS),
        _canonicalize_headers(DEFAULT_EXPECTED_HEADERS_WITH_EXP),
    ]
    if canonical_expected not in valid_header_sets:
        valid_header_sets.append(canonical_expected)

    if canonical_headers not in valid_header_sets:
        expected_for_diff = DEFAULT_EXPECTED_HEADERS_WITH_EXP if has_exp_price else DEFAULT_EXPECTED_HEADERS
        diff_text = _format_header_diff(expected_for_diff, headers)
        raise HTTPException(
            status_code=400,
            detail=(
                "模板表头不匹配。"
                f"当前校验标准来源: {template_path} 的 Sheet{sheet_index + 1}。"
                f"差异: {diff_text}。"
                "（已兼容别名：顺序=商品序号，月均价=均价，商品备注=买赠周期，体验价格=体验价价格）"
                "请按标准表头调整后重试。"
            ),
        )


def _template_file_for_download() -> str:
    """返回页面下载模板的原文件路径（不做改写）。"""
    candidates = [
        settings.template_path,
        os.path.join(PROJECT_ROOT, "payment_config_template_empty.xlsx"),
        os.path.join(PROJECT_ROOT, EXCEL_TEMPLATE_NAME),
    ]
    seen = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p):
            return p
    raise HTTPException(
        status_code=500,
        detail=(
            "模板文件不存在。请在项目根目录放置 payment_config_template_empty.xlsx 或 "
            f"{EXCEL_TEMPLATE_NAME}，或正确设置环境变量 WEB_TEMPLATE_PATH。"
        ),
    )


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>支付配置自助校验</title>
  <style>
    body { font-family: "Google Sans", "Segoe UI", Arial, sans-serif; margin: 0; color: #202124; background: #f1f3f4; }
    .page { max-width: 1020px; margin: 24px auto; padding: 0 12px; }
    .hero { margin-bottom: 14px; }
    .hero h2 { margin: 0 0 6px 0; font-size: 26px; letter-spacing: .2px; }
    .hero .sub { color: #5f6368; font-size: 13px; }
    .card { border: 1px solid #dadce0; padding: 16px; border-radius: 12px; margin-bottom: 14px; background: #fff; box-shadow: 0 1px 2px rgba(60,64,67,.15); }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(320px, 1fr)); gap: 12px 16px; }
    label { display: block; margin-top: 4px; font-size: 13px; color: #3c4043; font-weight: 500; }
    input, select { padding: 9px 10px; width: 100%; box-sizing: border-box; margin-top: 6px; border: 1px solid #dadce0; border-radius: 8px; background: #fff; }
    input:focus, select:focus { border-color: #1a73e8; outline: none; box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.15); }
    input[type="file"] { padding: 6px; }
    input[type="file"]::file-selector-button {
      margin-right: 10px;
      padding: 7px 12px;
      border: 1px solid #dadce0;
      border-radius: 16px;
      background: #fff;
      color: #1f1f1f;
      font-weight: 600;
      cursor: pointer;
    }
    input[type="file"]::file-selector-button:hover {
      border-color: #1a73e8;
      color: #1a73e8;
      background: #f8faff;
    }
    input[type="file"]::-webkit-file-upload-button {
      margin-right: 10px;
      padding: 7px 12px;
      border: 1px solid #dadce0;
      border-radius: 16px;
      background: #fff;
      color: #1f1f1f;
      font-weight: 600;
      cursor: pointer;
    }
    input[type="file"]::-webkit-file-upload-button:hover {
      border-color: #1a73e8;
      color: #1a73e8;
      background: #f8faff;
    }
    button { margin-top: 10px; padding: 8px 14px; cursor: pointer; border: 1px solid #dadce0; border-radius: 20px; background: #fff; color: #1f1f1f; font-weight: 600; }
    button:hover { border-color: #1a73e8; color: #1a73e8; background: #f8faff; }
    .btn-link { display: inline-block; margin-top: 10px; padding: 8px 14px; border: 1px solid #dadce0; border-radius: 20px; background: #fff; color: #1f1f1f; font-weight: 600; text-decoration: none; }
    .btn-link:hover { border-color: #1a73e8; color: #1a73e8; background: #f8faff; }
    pre { background: #f8f9fa; border: 1px solid #e0e0e0; padding: 12px; border-radius: 8px; overflow: auto; max-height: 420px; }
    .muted { color: #5f6368; font-size: 12px; }
    .tips { font-size: 12px; color: #3c4043; background: #f8f9fa; border: 1px dashed #dadce0; padding: 8px 10px; margin: 8px 0 0; border-radius: 8px; }
    details { margin-top: 10px; }
    summary { cursor: pointer; color: #3c4043; font-size: 13px; }
    .summary-box { background: #e8f0fe; border: 1px solid #d2e3fc; border-radius: 10px; padding: 12px; margin-bottom: 10px; }
    .summary-title { font-weight: bold; margin-bottom: 8px; }
    .ok { color: #0b7a0b; }
    .bad { color: #b42318; }
    .required::after { content: " *"; color: #d93025; font-weight: bold; }
    .action-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; }
    .action-row .left { display: inline-flex; align-items: center; gap: 14px; flex-wrap: wrap; }
    .checkbox-inline { display: inline-flex; align-items: center; gap: 8px; margin: 0; font-weight: 500; color: #3c4043; }
    .checkbox-inline input[type="checkbox"] { width: 16px; height: 16px; margin: 0; }
    .action-row button { margin-top: 0; }
    .result-top { margin-bottom: 12px; }
    .result-pane { border: 1px solid #e0e0e0; border-radius: 10px; padding: 12px; background: #fff; }
    .result-pane h4 { margin: 0 0 8px 0; font-size: 14px; color: #3c4043; }
    .progress-compact { margin-bottom: 10px; }
    .progress-compact progress { width: 100%; }
    .inline-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
    .inline-actions button { margin-top: 0; }
    .split-layout { display: grid; grid-template-columns: 360px 1fr; gap: 12px; align-items: start; }
    .task-list { border: 1px solid #e0e0e0; border-radius: 8px; background: #fff; max-height: 520px; overflow: auto; }
    .task-item { border-bottom: 1px solid #eceff1; padding: 10px 12px; cursor: pointer; }
    .task-item:last-child { border-bottom: none; }
    .task-item:hover { background: #f8faff; }
    .task-item.active { background: #e8f0fe; }
    .task-title { font-weight: 600; font-size: 13px; }
    .task-meta { color: #5f6368; font-size: 12px; margin-top: 3px; }
    .status-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
    .status-queued { background:#f59e0b; }
    .status-running { background:#2563eb; }
    .status-succeeded { background:#16a34a; }
    .status-failed { background:#dc2626; }
    .toast-container {
      position: fixed;
      top: 16px;
      right: 16px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 8px;
      pointer-events: none;
    }
    .toast {
      min-width: 240px;
      max-width: 420px;
      padding: 12px 16px;
      border-radius: 8px;
      color: #fff;
      font-size: 14px;
      line-height: 1.5;
      box-shadow: 0 4px 12px rgba(60,64,67,.25);
      opacity: 0;
      transform: translateY(-8px);
      transition: opacity .2s ease, transform .2s ease;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    .toast-error { background: #d93025; }
    .toast-info { background: #1a73e8; }
    @media (max-width: 980px) {
      .split-layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="page">
  <div class="hero">
    <h2>支付配置自助校验</h2>
    <div class="sub">上传模板后，按步骤发起任务并查看结果。</div>
  </div>
  <div class="card">
    <h3>步骤1：下载模板</h3>
    <p class="muted">先下载空模板，填写后再上传。</p>
    <a class="btn-link" href="/api/template" onclick="return downloadTemplate(event)">下载xlsx模板</a>
    <a class="btn-link" href="/baseline" style="margin-left:10px;">基线文档生成器</a>
  </div>
  <div class="card">
    <h3>步骤2：上传并启动</h3>
    <div class="grid">
      <label>Excel文件 <input id="xlsx" type="file" accept=".xlsx"></label>
      <label class="required">发起人姓名 <input id="initiator"></label>
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
      <label class="required">国家代码（影响配置场景，价格仍按USD校验） <input id="country" value="US"></label>
      <label>Sheet编号（支持多个）<input id="sheets" value="1" placeholder="如: 1,3,5-8"></label>
    </div>
    <p class="tips">
      多个Sheet可用逗号或区间：<code>1,3,5-8</code>。同一次提交共用一个任务ID。
    </p>
    <details>
      <summary>高级选项（不常用）</summary>
      <label>仅跑指定行（Excel行号，逗号分隔，可空）<input id="rows" placeholder="如: 30,32,44,46"></label>
    </details>
    <div class="action-row">
      <div class="left">
        <label class="checkbox-inline"><input id="sendBot" type="checkbox" checked> 发送Bot消息（校验群）</label>
        <label class="checkbox-inline"><input id="debugBot" type="checkbox"> 调试推送（仅私人群）</label>
      </div>
      <button type="button" onclick="startTask()">启动任务</button>
    </div>
    <div id="taskInfo" class="muted"></div>
  </div>
  <div class="card">
    <h3>步骤3：查看任务结果</h3>
    <div class="split-layout">
      <div class="result-pane">
        <h4>任务筛选与列表</h4>
        <label>状态筛选
          <select id="statusFilter">
            <option value="">全部</option>
            <option value="queued">排队中</option>
            <option value="running">执行中</option>
            <option value="succeeded">已通过</option>
            <option value="failed">已失败</option>
          </select>
        </label>
        <label>任务搜索（任务ID/关键字）<input id="taskQuery" placeholder="如: task-20260409-01"></label>
        <label>发起人筛选<input id="taskInitiator"></label>
        <div class="inline-actions">
          <button type="button" onclick="useCurrentInitiatorFilter()">只看我发起</button>
          <button type="button" onclick="clearInitiatorFilter()">清空筛选</button>
          <button type="button" onclick="refreshTasks()">刷新任务列表</button>
        </div>
        <div id="taskList" class="task-list" style="margin-top:10px;"></div>
      </div>
      <div class="result-pane">
        <h4>任务详情</h4>
        <div class="progress-compact">
          <progress id="progressBar" value="0" max="100"></progress>
          <div><span id="progressText" class="muted">0%</span></div>
        </div>
        <div id="resultSummary" class="summary-box" style="display:none;"></div>
        <details open>
          <summary>查看原始结果(JSON)</summary>
        <pre id="result"></pre>
        </details>
      </div>
    </div>
  </div>
  <div id="toastContainer" class="toast-container" aria-live="polite"></div>
<script>
let currentTaskId = '';
let latestTasks = [];

function showToast(message, type) {
  const container = document.getElementById('toastContainer');
  if (!container || !message) return;
  const toast = document.createElement('div');
  toast.className = 'toast ' + (type === 'error' ? 'toast-error' : 'toast-info');
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(function() { toast.classList.add('show'); });
  setTimeout(function() {
    toast.classList.remove('show');
    setTimeout(function() {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 200);
  }, 4000);
}

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
    fd.append('debug_bot', document.getElementById('debugBot').checked ? 'true' : 'false');

    const res = await fetch('/api/tasks', { method: 'POST', body: fd, headers: tokenHeader() });
    const data = await res.json();
    if (!res.ok) {
      const msg = data.detail || JSON.stringify(data);
      taskInfo.innerText = '启动失败: ' + msg;
      showToast(msg, 'error');
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
</script>
  </div>
</body>
</html>
        """
    )


@app.get("/api/template")
def api_template(_: None = Depends(auth_guard)):
    template_path = _template_file_for_download()
    return FileResponse(
        template_path,
        filename=os.path.basename(template_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/statistics-panel", response_class=HTMLResponse)
def dashboard_page():
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>数据面板</title>
  <style>
    body { font-family: "Google Sans", "Segoe UI", Arial, sans-serif; margin: 0; background: #f1f3f4; color: #202124; }
    .page { max-width: 1000px; margin: 24px auto; padding: 0 12px; }
    .hero { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
    .hero h2 { margin: 0; font-size: 26px; }
    .sub { color: #5f6368; font-size: 13px; margin-top: 4px; }
    .btn-link { display: inline-block; padding: 8px 14px; border: 1px solid #dadce0; border-radius: 20px; background: #fff; color: #1f1f1f; font-weight: 600; text-decoration: none; }
    .btn-link:hover { border-color: #1a73e8; color: #1a73e8; background: #f8faff; }
    .meta-card { border: 1px solid #dadce0; border-radius: 12px; background: #fff; padding: 12px 14px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(60,64,67,.15); }
    .cards { display: grid; grid-template-columns: repeat(2, minmax(320px, 1fr)); gap: 12px; }
    .card { border: 1px solid #dadce0; border-radius: 12px; background: #fff; padding: 16px; box-shadow: 0 1px 2px rgba(60,64,67,.15); }
    .k { font-size: 14px; color: #5f6368; }
    .v { margin-top: 8px; font-size: 30px; font-weight: 700; letter-spacing: 0.4px; }
    .line { margin-top: 10px; color: #3c4043; font-size: 14px; }
    .muted { color: #5f6368; font-size: 12px; }
    @media (max-width: 900px) { .cards { grid-template-columns: 1fr; } .hero { flex-direction: column; align-items: flex-start; } }
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div>
        <h2>校验数据面板</h2>
        <div class="sub">每天 00:00 自动更新。显示统计范围内的累计结果。</div>
      </div>
      <a class="btn-link" href="/">返回任务页面</a>
    </div>
    <div class="meta-card">
      <div id="rangeText" class="line">统计范围：-</div>
      <div id="updatedText" class="muted" style="margin-top:6px;">最近刷新：-</div>
    </div>
    <div class="cards">
      <div class="card">
        <div class="k">任务数量</div>
        <div class="v" id="taskCount">-</div>
        <div class="line">已经运行任务</div>
      </div>
      <div class="card">
        <div class="k">配置数量</div>
        <div class="v" id="configCount">-</div>
        <div class="line">配置行检查</div>
      </div>
      <div class="card">
        <div class="k">问题发现</div>
        <div class="v" id="issueCount">-</div>
        <div class="line">条错误/异常</div>
      </div>
      <div class="card">
        <div class="k">接口调用验证</div>
        <div class="v" id="requestCount">-</div>
        <div class="line">次请求</div>
      </div>
      <div class="card">
        <div class="k">使用人数</div>
        <div class="v" id="userCount">-</div>
        <div class="line">人</div>
      </div>
    </div>
  </div>
<script>
function formatNum(n) {
  const v = Number(n || 0);
  return Number.isFinite(v) ? v.toLocaleString('zh-CN') : '-';
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

async function loadSummary() {
  const res = await fetch('/api/dashboard/summary');
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));

  setText('rangeText', '统计范围：' + data.range_start + ' 至 ' + data.range_end);
  setText('updatedText', '最近刷新：' + (data.refreshed_at || '-'));

  setText('taskCount', formatNum(data.task_count));

  setText('configCount', formatNum(data.config_check_count));

  setText('issueCount', formatNum(data.issue_count));

  setText('requestCount', formatNum(data.request_count));

  setText('userCount', formatNum(data.user_count));
}

loadSummary().catch((e) => {
  setText('updatedText', '加载失败：' + (e && e.message ? e.message : String(e)));
});
</script>
</body>
</html>
        """
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page_legacy():
    return dashboard_page()


@app.get("/api/dashboard/summary")
def api_dashboard_summary(_: None = Depends(auth_guard)):
    return dashboard_stats_service.get_summary()


@app.post("/api/tasks")
def api_create_task(
    file: UploadFile = File(...),
    platform: str = Form("pc"),
    env: str = Form("online"),
    country: str = Form("US"),
    initiator: str = Form(""),
    sheet_numbers: str = Form("1"),
    only_rows: str = Form(""),
    send_bot: bool = Form(True),
    debug_bot: bool = Form(False),
    _: None = Depends(auth_guard),
):
    if not settings.admin_cookie:
        raise HTTPException(status_code=500, detail="未配置 PAYMENT_ADMIN_COOKIE，无法执行任务")
    initiator = (initiator or "").strip()
    if not initiator:
        raise HTTPException(status_code=400, detail="请填写发起人姓名")
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")
    country = (country or "").strip()
    if not country:
        raise HTTPException(status_code=400, detail="请填写国家代码")
    _guard_online_env_integrity(env)
    sheet_numbers_list = _parse_sheet_numbers(sheet_numbers)
    sheet_indices = [n - 1 for n in sheet_numbers_list]
    only_row_numbers = _parse_only_rows(only_rows)

    with NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file.file.read())
        upload_path = tmp.name

    for sheet_index in sheet_indices:
        _validate_headers(upload_path, sheet_index)
    try:
        validate_admin_cookie(settings.admin_cookie)
    except HTTPException:
        try:
            os.unlink(upload_path)
        except OSError:
            pass
        raise
    params = RunParams(
        file_path=upload_path,
        env=env.strip().lower(),
        country=country.strip(),
        platform=platform.strip().lower(),
        is_uwp=False,
        sheet_index=sheet_indices[0],
        sheet_indices=sheet_indices,
        cookie=settings.admin_cookie,
        initiator=initiator,
        only_row_numbers=only_row_numbers,
        send_bot=send_bot,
        debug_bot=debug_bot,
    )
    try:
        task = task_manager.create_task(upload_path, params)
    except QueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return JSONResponse({"id": task.id, "status": task.status, "message": task.message})


@app.get("/api/tasks")
def api_list_tasks(
    status: str = "",
    q: str = "",
    initiator: str = "",
    limit: int = 50,
    _: None = Depends(auth_guard),
):
    tasks = task_manager.list_tasks(status=status, q=q, initiator=initiator, limit=limit)
    return [TaskManager._to_dict(t) for t in tasks]


@app.get("/api/tasks/{task_id}")
def api_task_detail(task_id: str, _: None = Depends(auth_guard)):
    now = time.time()
    with _task_refresh_lock:
        last = _task_last_refresh.get(task_id, 0.0)
        if now - last < REFRESH_INTERVAL_SECONDS:
            retry = round(REFRESH_INTERVAL_SECONDS - (now - last), 2)
            raise HTTPException(status_code=429, detail=f"任务刷新过于频繁，请{retry}秒后再试")
        _task_last_refresh[task_id] = now
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    out = TaskManager._to_dict(task)
    out["result_url"] = f"/api/tasks/{task_id}/result"
    out["log_url"] = f"/api/tasks/{task_id}/log"
    out["errors_txt_url"] = f"/api/tasks/{task_id}/errors.txt"
    return out


@app.get("/api/tasks/{task_id}/result")
def api_task_result(task_id: str, _: None = Depends(auth_guard)):
    result = task_manager.read_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="结果尚未生成")
    return result


@app.get("/api/tasks/{task_id}/errors.txt")
def api_task_errors(task_id: str, _: None = Depends(auth_guard)):
    result = task_manager.read_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="结果尚未生成")
    errors = result.get("errors") or []
    text = "\n".join(errors) if errors else "未检测出错误结果，well done"
    return PlainTextResponse(text)


@app.get("/api/tasks/{task_id}/log")
def api_task_log(task_id: str, _: None = Depends(auth_guard)):
    log_text = task_manager.read_task_log(task_id)
    if log_text is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return PlainTextResponse(log_text)

