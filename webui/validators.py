from fastapi import HTTPException

from config.logger import logger
from utils.utils import check_admin_cookie_valid

COOKIE_EXPIRED_DETAIL = "cookie已过期，请联系管理员更新后，再发起任务"
COOKIE_EXPIRED_MAINTAINER_LOG = (
    "Cookie 已过期或未登录。"
    "请从浏览器打开 https://example.com/internal/toc/kshopwindow/price/list "
    "登录后复制 Cookie 中的 ovsmgr_sid，更新 PAYMENT_ADMIN_COOKIE 并重启 Web 服务。"
)
ADMIN_NETWORK_ERROR_DETAIL = "无法连接星宿后台，请检查网络后重试。"


def validate_admin_cookie(cookie: str) -> None:
    """表头校验通过后、任务入队前调用；Cookie 过期或网络不可达时抛 HTTPException。"""
    ok, reason = check_admin_cookie_valid(cookie)
    if ok:
        return
    if reason == "expired":
        logger.warning(COOKIE_EXPIRED_MAINTAINER_LOG)
        raise HTTPException(status_code=401, detail=COOKIE_EXPIRED_DETAIL)
    logger.warning("Cookie 预检失败：%s", ADMIN_NETWORK_ERROR_DETAIL)
    raise HTTPException(status_code=503, detail=ADMIN_NETWORK_ERROR_DETAIL)