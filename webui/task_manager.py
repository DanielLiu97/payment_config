import json
import os
import queue
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from webui.runner import RunParams, run_validation


class QueueFullError(Exception):
    """Raised when pending task queue reaches configured limit."""


@dataclass
class TaskRecord:
    id: str
    status: str
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    message: str
    error_count: Optional[int]
    progress_current: int
    progress_total: int
    progress_percent: float
    current_row_number: Optional[int]
    task_dir: str
    input_file: str
    params: Dict
    safe_params: Dict


class TaskManager:
    def __init__(
        self,
        data_dir: str,
        workers: int = 1,
        max_queue_size: int = 0,
        retention_days: int = 7,
        cleanup_interval_seconds: int = 3600,
        cleanup_enabled: bool = True,
    ):
        self.data_dir = data_dir
        self.tasks_dir = os.path.join(data_dir, "tasks")
        os.makedirs(self.tasks_dir, exist_ok=True)
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = threading.Lock()
        self._max_queue_size = max(0, int(max_queue_size))
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=self._max_queue_size)
        self._workers: List[threading.Thread] = []
        self._worker_count = max(1, workers)
        self._sequence_by_day: Dict[str, int] = {}
        self._retention_days = max(1, retention_days)
        self._cleanup_interval_seconds = max(60, cleanup_interval_seconds)
        self._cleanup_enabled = bool(cleanup_enabled)
        for i in range(self._worker_count):
            t = threading.Thread(target=self._worker_loop, daemon=True, name=f"task-worker-{i+1}")
            t.start()
            self._workers.append(t)
        self._cleanup_worker = None
        if self._cleanup_enabled:
            self._cleanup_worker = threading.Thread(target=self._cleanup_loop, daemon=True, name="task-cleanup-worker")
            self._cleanup_worker.start()

    def _next_task_id_locked(self) -> str:
        day = datetime.now().strftime("%Y%m%d")
        current = self._sequence_by_day.get(day, 0)
        if current <= 0:
            prefix = f"task-{day}-"
            max_seq = 0
            for name in os.listdir(self.tasks_dir):
                if not name.startswith(prefix):
                    continue
                tail = name.replace(prefix, "", 1)
                if tail.isdigit():
                    max_seq = max(max_seq, int(tail))
            current = max_seq
        current += 1
        self._sequence_by_day[day] = current
        return f"task-{day}-{current:02d}"

    def create_task(self, upload_path: str, params: RunParams) -> TaskRecord:
        with self._lock:
            if self._max_queue_size > 0 and self._queue.qsize() >= self._max_queue_size:
                raise QueueFullError(f"排队任务已满（上限{self._max_queue_size}），请稍后重试")
            task_id = self._next_task_id_locked()
            task_dir = os.path.join(self.tasks_dir, task_id)
            os.makedirs(task_dir, exist_ok=True)
            input_name = os.path.basename(upload_path)
            input_file = os.path.join(task_dir, input_name)
            shutil.move(upload_path, input_file)
            params.file_path = input_file
            params.task_id = task_id
            now = datetime.now().isoformat()
            runtime_params = params.__dict__.copy()
            safe_params = runtime_params.copy()
            if safe_params.get("cookie"):
                safe_params["cookie"] = str(safe_params["cookie"])[:12] + "***"
            record = TaskRecord(
                id=task_id,
                status="queued",
                created_at=now,
                started_at=None,
                finished_at=None,
                message="任务已入队",
                error_count=None,
                progress_current=0,
                progress_total=0,
                progress_percent=0.0,
                current_row_number=None,
                task_dir=task_dir,
                input_file=input_file,
                params=runtime_params,
                safe_params=safe_params,
            )
            self._tasks[task_id] = record
            self._persist_meta(record)
        self._queue.put(task_id)
        return record

    def list_tasks(self, status: str = "", q: str = "", initiator: str = "", limit: int = 50) -> List[TaskRecord]:
        status = (status or "").strip().lower()
        q = (q or "").strip().lower()
        initiator = (initiator or "").strip().lower()
        limit = max(1, min(limit, 200))
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda x: x.created_at, reverse=True)
            if status:
                tasks = [t for t in tasks if t.status.lower() == status]
            if initiator:
                tasks = [
                    t for t in tasks
                    if initiator in str((t.safe_params or {}).get("initiator", "")).lower()
                ]
            if q:
                tasks = [
                    t for t in tasks
                    if q in t.id.lower()
                    or q in t.message.lower()
                    or q in str((t.safe_params or {}).get("initiator", "")).lower()
                ]
            return tasks[:limit]

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def read_result(self, task_id: str) -> Optional[dict]:
        task = self.get_task(task_id)
        if not task:
            return None
        result_path = os.path.join(task.task_dir, "result.json")
        if not os.path.exists(result_path):
            return None
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def read_task_log(self, task_id: str) -> Optional[str]:
        task = self.get_task(task_id)
        if not task:
            return None
        log_path = os.path.join(task.task_dir, "task.log")
        if not os.path.exists(log_path):
            return ""
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _worker_loop(self):
        while True:
            task_id = self._queue.get()
            task = self.get_task(task_id)
            if not task:
                self._queue.task_done()
                continue
            self._update_task(task_id, status="running", started_at=datetime.now().isoformat(), message="任务执行中")
            task.params.setdefault("initiator", "")
            task.params.setdefault("sheet_indices", [int(task.params.get("sheet_index", 0))])
            params = RunParams(**task.params)
            result = run_validation(
                params,
                task.task_dir,
                progress_callback=lambda c, t, r: self._update_progress(task_id, c, t, r),
            )
            status = "succeeded" if result.get("ok") else "failed"
            msg = "任务完成" if status == "succeeded" else "任务失败"
            update_kwargs = {
                "status": status,
                "finished_at": datetime.now().isoformat(),
                "message": msg,
                "error_count": result.get("error_count"),
            }
            if status == "succeeded":
                update_kwargs["progress_percent"] = 100.0
            self._update_task(task_id, **update_kwargs)
            self._queue.task_done()

    def _update_progress(self, task_id: str, current: int, total: int, row_no: int):
        total_safe = max(1, total) if total else 0
        percent = round((current / total_safe) * 100, 2) if total_safe else 0.0
        self._update_task(
            task_id,
            progress_current=current,
            progress_total=total,
            progress_percent=percent,
            current_row_number=row_no,
            message=f"任务执行中：第{row_no}行",
        )

    def _update_task(self, task_id: str, **kwargs):
        with self._lock:
            rec = self._tasks[task_id]
            for key, value in kwargs.items():
                setattr(rec, key, value)
            self._persist_meta(rec)

    @staticmethod
    def _to_dict(record: TaskRecord) -> dict:
        return {
            "id": record.id,
            "status": record.status,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "message": record.message,
            "error_count": record.error_count,
            "progress_current": record.progress_current,
            "progress_total": record.progress_total,
            "progress_percent": record.progress_percent,
            "current_row_number": record.current_row_number,
            "task_dir": record.task_dir,
            "input_file": record.input_file,
            "params": record.safe_params,
        }

    def _persist_meta(self, record: TaskRecord):
        path = os.path.join(record.task_dir, "meta.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._to_dict(record), f, ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_iso(value: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _cleanup_loop(self):
        while True:
            try:
                self._cleanup_expired_tasks()
            except Exception:
                pass
            threading.Event().wait(self._cleanup_interval_seconds)

    def _cleanup_expired_tasks(self):
        now = datetime.now()
        cutoff = now - timedelta(days=self._retention_days)
        remove_ids = []
        with self._lock:
            for task_id, rec in list(self._tasks.items()):
                ref_time = self._parse_iso(rec.finished_at or rec.created_at)
                if ref_time and ref_time < cutoff:
                    remove_ids.append(task_id)
            for task_id in remove_ids:
                rec = self._tasks.pop(task_id, None)
                if rec and os.path.isdir(rec.task_dir):
                    shutil.rmtree(rec.task_dir, ignore_errors=True)

        # 兼容重启后仅落盘目录存在但内存中还未加载的情况
        for entry in os.listdir(self.tasks_dir):
            task_dir = os.path.join(self.tasks_dir, entry)
            if not os.path.isdir(task_dir):
                continue
            meta_path = os.path.join(task_dir, "meta.json")
            if not os.path.exists(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                ref_time = self._parse_iso(meta.get("finished_at") or meta.get("created_at"))
                if ref_time and ref_time < cutoff:
                    shutil.rmtree(task_dir, ignore_errors=True)
            except Exception:
                continue

