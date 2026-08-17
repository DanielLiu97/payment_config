# -*- coding: utf-8 -*-
"""
运营自助校验页面启动入口。

用法:
    set PAYMENT_ADMIN_COOKIE=ovsmgr_sid=xxx
    set WEB_ACCESS_TOKEN=your_token
    python run_web.py
"""

import uvicorn

from webui.settings import load_settings


if __name__ == "__main__":
    s = load_settings()
    uvicorn.run("webui.app:app", host=s.host, port=s.port, reload=False)

