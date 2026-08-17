import os
from dataclasses import dataclass

from config.config import PROJECT_ROOT


@dataclass(frozen=True)
class WebSettings:
    host: str
    port: int
    access_token: str
    admin_cookie: str
    data_dir: str
    template_path: str
    workers: int
    max_queue_size: int
    task_retention_days: int
    cleanup_interval_seconds: int
    disable_task_cleanup: bool
    online_env_guard: bool


def load_settings() -> WebSettings:
    def _to_bool(name: str, default: str = "1") -> bool:
        return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8010"))
    access_token = os.getenv("WEB_ACCESS_TOKEN", "").strip()
    admin_cookie = os.getenv("PAYMENT_ADMIN_COOKIE", "").strip()
    data_dir = os.getenv("WEB_DATA_DIR", os.path.join(PROJECT_ROOT, "web_data"))
    template_path = os.getenv("WEB_TEMPLATE_PATH", os.path.join(PROJECT_ROOT, "payment_config_template_empty.xlsx"))
    workers = max(1, int(os.getenv("WEB_WORKERS", "2")))
    max_queue_size = max(1, int(os.getenv("WEB_MAX_QUEUE_SIZE", "4")))
    task_retention_days = max(1, int(os.getenv("WEB_TASK_RETENTION_DAYS", "7")))
    cleanup_interval_seconds = max(60, int(os.getenv("WEB_CLEANUP_INTERVAL_SECONDS", "3600")))
    disable_task_cleanup = _to_bool("WEB_DISABLE_TASK_CLEANUP", "0")
    online_env_guard = _to_bool("WEB_ONLINE_ENV_GUARD", "1")
    return WebSettings(
        host=host,
        port=port,
        access_token=access_token,
        admin_cookie=admin_cookie,
        data_dir=data_dir,
        template_path=template_path,
        workers=workers,
        max_queue_size=max_queue_size,
        task_retention_days=task_retention_days,
        cleanup_interval_seconds=cleanup_interval_seconds,
        disable_task_cleanup=disable_task_cleanup,
        online_env_guard=online_env_guard,
    )

