# -*- coding: utf-8 -*-
"""
@File    : shop_window_parser.py
@Author  : your-email@example.com
@Date    : 2024/9/7
@UpdatedBy : liuxingquan
@UpdatedDate : 2026/02/09
@Description : class to parse shop_window json file
@UpdateNote : 重构硬编码配置，使用config/config.py统一管理API地址
"""
import sys
from typing import Any, Optional

import requests

from config.logger import logger


from config.config import SHOP_WINDOW_API, UWP_CHANNEL, RETRY_CONFIG
from utils.utils import requests_get_with_retry

class ShopWindowParser:
    def __init__(self, shop_window_id: int, mode: str = "online", mock_country: str = "US", platform: str = "pc",
                 is_uwp: bool = False, cookie: Optional[str] = None):
        self.shop_window_id = shop_window_id
        self.mode = mode
        self.mock_country = mock_country
        # 支付橱窗 API 要求 path/query 中平台参数为小写（如 pc、android、ios、ipad）
        self.platform = str(platform or "pc").strip().lower()
        self.is_uwp = is_uwp
        self.cookie = (cookie or "").strip() or None
        self.last_error_reason = ""
        self.current_shop_window = self.__request_shop_window_list()

    def __get_shop_window_url(self) -> str:
        if self.mode not in ["online", "test"]:
            logger.warning("mode is not in ['online', 'test'], program will not work")
            sys.exit(1)
        
        # 使用配置文件中的API地址
        api_config = SHOP_WINDOW_API.get(self.mode, SHOP_WINDOW_API["online"])
        base_url = api_config["base_url"]
        endpoint_template = api_config["endpoint"]
        
        # 构建URL
        url = base_url + endpoint_template.format(
            platform=self.platform,
            shopwindow_id=self.shop_window_id,
            mock_country=self.mock_country
        )
        
        # UWP平台添加channel参数
        if self.is_uwp:
            url += f"&channel={UWP_CHANNEL}"
        
        return url

    """
    obtain shop window list, usually there is only one shop window in response
    but sometimes multiple shop windows is possible 
    """

    def __request_shop_window_list(self) -> dict:
        url = self.__get_shop_window_url()
        self.last_error_reason = ""
        logger.debug("pay_window 请求: {}".format(url))
        headers = {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        timeout = RETRY_CONFIG.get("timeout", 30)
        max_retries = RETRY_CONFIG.get("max_retries", 3)
        retry_delay = RETRY_CONFIG.get("retry_delay", 1.0)
        backoff_factor = RETRY_CONFIG.get("backoff_factor", 2.0)
        try:
            # pay_window 请求也走统一重试策略，避免瞬时网络抖动直接判错
            res = requests_get_with_retry(
                url,
                headers=headers or None,
                timeout=timeout,
                max_retries=max_retries,
                delay=retry_delay,
                backoff_factor=backoff_factor,
            )
        except Exception as e:
            self.last_error_reason = "request exception: {}".format(e)
            logger.error(
                "request shop_window failed after retries (max_retries={}): {}".format(
                    max_retries, e
                )
            )
            return {}
        if res.status_code != 200:
            self.last_error_reason = "http status {}".format(res.status_code)
            logger.warning(
                "shop_window HTTP 非200, status={}, url={}, 片段: {}".format(
                    res.status_code, url, res.text[:400].replace("\n", " ")
                )
            )
            return {}
        try:
            result = res.json()
        except ValueError:
            self.last_error_reason = "response is not json"
            logger.error(
                "shop_window 响应非 JSON, url={}, 片段: {}".format(url, res.text[:400].replace("\n", " "))
            )
            return {}
        shop_window_data = result.get("data")
        if not shop_window_data:
            self.last_error_reason = "response data is empty"
            logger.error(
                "shop_window data not exist, url={}, 片段: {}".format(url, res.text[:500].replace("\n", " "))
            )
            return {}
        shop_window_list = shop_window_data.get("list")
        if not shop_window_list or len(shop_window_list) == 0:
            self.last_error_reason = "response list is empty"
            logger.error(
                "no shop_window was found (list 空), url={}, 片段: {}".format(url, res.text[:500].replace("\n", " "))
            )
            return {}
        # request one shop_id, so it's impossible return more than one shop window, use the first element is ok
        self.current_shop_window = shop_window_list[0]
        return self.current_shop_window

    def has_valid_shop_window(self) -> bool:
        return isinstance(self.current_shop_window, dict) and bool(self.current_shop_window)

    """
    coupon and shop item is one-one, so we need to link coupon with shop window for further processing
    """

    def get_coupon_list(self) -> list:
        if self.current_shop_window == {}:
            logger.error("no shop_window was found")
            return []
        coupon_shop_id_str = self.current_shop_window.get("coupon_shop_ids")
        if coupon_shop_id_str == "":
            return ["0" for i in range(10)]
        else:
            coupon_shop_id_list = coupon_shop_id_str.split(",")
        return coupon_shop_id_list

    def get_add_buy_list(self) -> list:
        if self.current_shop_window == {}:
            logger.error("no shop_window was found")
            return []
        add_buy_id_str = self.current_shop_window.get("pay_add_buy_window_ids")
        if add_buy_id_str == "":
            return ["0" for i in range(10)]
        else:
            add_buy_id_list = add_buy_id_str.split(",")
        return add_buy_id_list

    def get_success_page_window_list(self) -> list:
        if self.current_shop_window == {}:
            logger.error("no shop_window was found")
            return []
        success_page_str = self.current_shop_window.get("success_page_window_ids")
        if success_page_str == "":
            return []
        else:
            success_page_id_list = success_page_str.split(",")
        return success_page_id_list


    def get_retain_id(self) -> int:
        if self.current_shop_window == {}:
            logger.error("no shop_window was found")
            return 0
        retain_id = self.current_shop_window.get("pay_retain_shop_id")
        return retain_id

    def get_shop_window_inner_obj_by_name(self, key_name: str) -> Any:
        if key_name is None or key_name == "":
            logger.error("key_name is empty")
            return None
        return self.current_shop_window.get(key_name)
