import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Set


TASK_DIR_PATTERN = re.compile(r"^task-(\d{8})-\d+")
ROW_CHECK_PATTERN = re.compile(r"开始第\d+行的数据检查")
REQUEST_PATTERN = re.compile(r"开始请求URL:")
EXCLUDED_INITIATOR_KEYWORDS = ("test", "测试", "debug", "重跑", "rerun", "local", "admin")


@dataclass
class DashboardSummary:
    range_start: str
    range_end: str
    task_count: int
    config_check_count: int
    issue_count: int
    request_count: int
    user_count: int
    refreshed_at: str


class DashboardStatsService:
    def __init__(self, tasks_dir: str, range_start: str):
        self.tasks_dir = tasks_dir
        self.range_start = datetime.strptime(range_start, "%Y-%m-%d").date()
        self._lock = threading.Lock()
        self._summary: Optional[DashboardSummary] = None

        # 启动时先做一次刷新，确保页面打开就有数据
        self.refresh()
        self._refresh_thread = threading.Thread(
            target=self._daily_refresh_loop,
            daemon=True,
            name="dashboard-stats-refresh",
        )
        self._refresh_thread.start()

    def get_summary(self) -> Dict:
        with self._lock:
            if self._summary is None:
                self.refresh()
            return asdict(self._summary)

    def refresh(self):
        today = date.today()
        task_count = 0
        config_check_count = 0
        issue_count = 0
        request_count = 0
        users: Set[str] = set()

        if os.path.isdir(self.tasks_dir):
            for name in os.listdir(self.tasks_dir):
                task_date = self._extract_task_date(name)
                if task_date is None:
                    continue
                if not (self.range_start <= task_date <= today):
                    continue

                task_dir = os.path.join(self.tasks_dir, name)
                if not os.path.isdir(task_dir):
                    continue

                result_path = os.path.join(task_dir, "result.json")
                meta_path = os.path.join(task_dir, "meta.json")
                log_path = os.path.join(task_dir, "task.log")

                # “已运行任务”以生成 result.json 为准
                if os.path.isfile(result_path):
                    task_count += 1
                    result_data = self._safe_load_json(result_path)
                    issue_count += self._safe_positive_int(result_data.get("error_count"))
                    users.update(self._extract_initiator(result_data))

                # 兜底从 meta 读取发起人，避免 result 缺失时漏计
                if os.path.isfile(meta_path):
                    meta_data = self._safe_load_json(meta_path)
                    users.update(self._extract_initiator(meta_data))

                if os.path.isfile(log_path):
                    text = self._safe_read_text(log_path)
                    config_check_count += len(ROW_CHECK_PATTERN.findall(text))
                    request_count += len(REQUEST_PATTERN.findall(text))

        filtered_users = {u for u in users if self._is_valid_user(u)}
        summary = DashboardSummary(
            range_start=self.range_start.isoformat(),
            range_end=today.isoformat(),
            task_count=task_count,
            config_check_count=config_check_count,
            issue_count=issue_count,
            request_count=request_count,
            user_count=len(filtered_users),
            refreshed_at=datetime.now().isoformat(timespec="seconds"),
        )
        with self._lock:
            self._summary = summary

    def _daily_refresh_loop(self):
        while True:
            now = datetime.now()
            next_midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            sleep_seconds = max(1, int((next_midnight - now).total_seconds()))
            time.sleep(sleep_seconds)
            self.refresh()

    @staticmethod
    def _extract_task_date(task_name: str) -> Optional[date]:
        match = TASK_DIR_PATTERN.match(task_name or "")
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except Exception:
            return None

    @staticmethod
    def _safe_load_json(path: str) -> Dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _safe_read_text(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    @staticmethod
    def _safe_positive_int(value) -> int:
        try:
            iv = int(value)
            return iv if iv > 0 else 0
        except Exception:
            return 0

    @staticmethod
    def _extract_initiator(payload: Dict) -> Set[str]:
        params = payload.get("params") or {}
        initiator = str(params.get("initiator") or "").strip()
        return {initiator} if initiator else set()

    @staticmethod
    def _is_valid_user(raw_name: str) -> bool:
        name = str(raw_name or "").strip().lower()
        if not name:
            return False
        if name.startswith("codex"):
            return False
        return not any(keyword in name for keyword in EXCLUDED_INITIATOR_KEYWORDS)
