# -*- coding: utf-8 -*-
"""
@Description : 日志配置，供 analysis_sku、utils、parser 等模块使用。
              同时输出到控制台和 logs 目录下的日志文件。
"""
import logging
import os
import sys

from config.config import LOG_FORMAT, LOG_DATE_FORMAT, LOG_DIR

# 确保日志目录存在
if LOG_DIR and not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILENAME = "payment_config_checker.log"  # 日志文件名

logger = logging.getLogger("payment_config_checker")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 写入 logs 目录
    if LOG_DIR:
        log_path = os.path.join(LOG_DIR, LOG_FILENAME)
        try:
            file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception:
            pass  # 无写权限等则仅控制台输出
