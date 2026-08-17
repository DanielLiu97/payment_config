# -*- coding: utf-8 -*-
"""
@File    : utils.py
@Author  : your-email@example.com
@Date    : 2024/9/7
@UpdatedBy : liuxingquan
@UpdatedDate : 2026/02/09
@Description : common methods for the program
@UpdateNote : 重构硬编码配置，使用config/config.py统一管理API地址和重试配置
"""

import re
import requests
import time
from functools import wraps
from threading import local
from typing import Optional, Callable, Any, Tuple
import logging
from config.logger import logger


from config.config import (
    ADMIN_API_PRICE_LIST_URL, ADMIN_API_PRICE_DETAIL_URL,
    ADMIN_API_PRICE_LIST_BY_IDS, ADMIN_API_ROLE_URL,
    RETRY_CONFIG, RETRYABLE_STATUS_CODES,
    PRODUCT_LISTNEW_BASE_URL, PRODUCT_LISTNEW_PATH, PRODUCT_LISTNEW_HEADERS_EXTRA,
    ADMIN_API_BASE_URL, ADMIN_SHOPWINDOW_LISTNEW_PATH,
)

# 使用配置文件中的API地址
price_by_sku_id_url = ADMIN_API_PRICE_LIST_URL
price_detail_url = ADMIN_API_PRICE_DETAIL_URL

# 使用配置文件中的重试参数
DEFAULT_MAX_RETRIES = RETRY_CONFIG["max_retries"]
DEFAULT_RETRY_DELAY = RETRY_CONFIG["retry_delay"]
DEFAULT_BACKOFF_FACTOR = RETRY_CONFIG["backoff_factor"]
DEFAULT_TIMEOUT = RETRY_CONFIG["timeout"]

# 使用配置文件中的重试状态码
# RETRYABLE_STATUS_CODES 已在config中定义，直接使用
_ROLE_WARMUP_DONE_KEYS = set()
_AUTH_STATE = local()


def _get_auth_issue_count() -> int:
    return int(getattr(_AUTH_STATE, "login_required_hits", 0) or 0)


def reset_auth_issue_flags() -> None:
    """重置当前线程的鉴权异常计数。"""
    _AUTH_STATE.login_required_hits = 0


def mark_auth_login_required() -> None:
    """记录一次「请先登录」命中。"""
    _AUTH_STATE.login_required_hits = _get_auth_issue_count() + 1


def is_auth_login_required_suspected(threshold: int = 3) -> bool:
    """是否疑似 cookie 失效（同一任务内命中多次「请先登录」）。"""
    return _get_auth_issue_count() >= max(1, int(threshold or 1))


def _build_admin_cookie_headers(cookie: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
    }
    headers.update(PRODUCT_LISTNEW_HEADERS_EXTRA or {})
    return headers


def _is_login_required_response(api_json: Any) -> bool:
    if not isinstance(api_json, dict):
        return False
    api_code = api_json.get("code")
    api_msg = str(api_json.get("msg") or "").strip()
    return api_code == 5 and "请先登录" in api_msg


def check_admin_cookie_valid(cookie: str, timeout: int = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
    """
    预检后台 Cookie 是否有效（不修改线程内鉴权计数）。

    Returns:
        (True, "") — Cookie 有效或可继续
        (False, "expired") — Cookie 过期或未登录
        (False, "network") — 无法连接星宿后台
    """
    cookie = (cookie or "").strip()
    if not cookie:
        return False, "expired"

    headers = _build_admin_cookie_headers(cookie)
    probe_urls = [
        ADMIN_API_ROLE_URL,
        f"{ADMIN_API_BASE_URL.rstrip('/')}/price/list?page_num=1&page_size=1",
    ]

    saw_network_error = False
    for url in probe_urls:
        try:
            res = requests.get(url, headers=headers, timeout=timeout)
            if res.status_code != 200:
                continue
            try:
                data = res.json()
            except ValueError:
                continue
            if _is_login_required_response(data):
                return False, "expired"
            return True, ""
        except (requests.exceptions.RequestException, requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            saw_network_error = True

    if saw_network_error:
        return False, "network"
    return True, ""


def _maybe_warmup_admin_role(url: str, headers: dict, timeout: int) -> None:
    """
    新后台在部分场景需要先请求 role 接口完成鉴权态初始化。
    该预热失败不应阻断主请求。
    """
    if not headers:
        return
    if "/shop-admin/manage/1/" not in str(url or ""):
        return
    if str(url or "").rstrip("/").endswith("/role"):
        return
    cookie = str((headers or {}).get("Cookie") or "").strip()
    if not cookie:
        return
    warmup_key = "role|" + cookie
    if warmup_key in _ROLE_WARMUP_DONE_KEYS:
        return
    role_headers = {
        "User-Agent": (headers or {}).get("User-Agent", "Mozilla/5.0"),
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
    }
    extra_headers = PRODUCT_LISTNEW_HEADERS_EXTRA or {}
    if extra_headers.get("Referer"):
        role_headers["Referer"] = extra_headers["Referer"]
    if extra_headers.get("Origin"):
        role_headers["Origin"] = extra_headers["Origin"]
    try:
        role_res = requests.get(ADMIN_API_ROLE_URL, headers=role_headers, timeout=timeout)
        logger.info("鉴权预热 role 请求完成，status=%s", role_res.status_code)
    except Exception as e:
        logger.warning("鉴权预热 role 请求失败（忽略，不阻断主流程）: %s", e)
    finally:
        _ROLE_WARMUP_DONE_KEYS.add(warmup_key)


def retry_on_failure(max_retries: int = DEFAULT_MAX_RETRIES, 
                    delay: float = DEFAULT_RETRY_DELAY,
                    backoff_factor: float = DEFAULT_BACKOFF_FACTOR):
    """
    重试装饰器，用于网络请求失败时自动重试
    
    Args:
        max_retries: 最大重试次数
        delay: 重试延迟时间（秒）
        backoff_factor: 退避因子，每次重试延迟时间会乘以此值
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.RequestException, 
                       requests.exceptions.Timeout,
                       requests.exceptions.ConnectionError) as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        logger.warning(f"请求失败，第 {attempt + 1} 次重试，延迟 {current_delay:.2f} 秒: {str(e)}")
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(f"请求最终失败，已重试 {max_retries} 次: {str(e)}")
                        raise
                except Exception as e:
                    # 对于其他类型的异常，不进行重试
                    logger.error(f"请求发生不可重试的异常: {str(e)}")
                    raise
            
            # 如果所有重试都失败了，抛出最后一个异常
            raise last_exception
            
        return wrapper
    return decorator


def requests_get_with_retry(url: str, headers: dict = None, timeout: int = DEFAULT_TIMEOUT,
                           max_retries: int = DEFAULT_MAX_RETRIES,
                           delay: float = DEFAULT_RETRY_DELAY,
                           backoff_factor: float = DEFAULT_BACKOFF_FACTOR) -> requests.Response:
    """
    带重试机制的GET请求
    
    Args:
        url: 请求URL
        headers: 请求头
        timeout: 超时时间
        max_retries: 最大重试次数
        delay: 重试延迟时间
        backoff_factor: 退避因子
        
    Returns:
        requests.Response: 响应对象
        
    Raises:
        requests.exceptions.RequestException: 请求失败
    """
    last_exception = None
    current_delay = delay
    
    logger.debug(f"开始请求URL: {url}")
    _maybe_warmup_admin_role(url, headers or {}, timeout)
    
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            
            # 检查状态码是否需要重试
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < max_retries:
                    logger.warning(f"收到可重试状态码 {response.status_code}，第 {attempt + 1} 次重试，延迟 {current_delay:.2f} 秒")
                    time.sleep(current_delay)
                    current_delay *= backoff_factor
                    continue
                else:
                    logger.error(f"请求最终失败，状态码: {response.status_code}")
                    response.raise_for_status()
            
            logger.debug(f"请求成功，状态码: {response.status_code}")
            return response
            
        except (requests.exceptions.RequestException, 
               requests.exceptions.Timeout,
               requests.exceptions.ConnectionError) as e:
            last_exception = e
            
            if attempt < max_retries:
                logger.warning(f"请求失败，第 {attempt + 1} 次重试，延迟 {current_delay:.2f} 秒: {str(e)}")
                time.sleep(current_delay)
                current_delay *= backoff_factor
            else:
                logger.error(f"请求最终失败，已重试 {max_retries} 次: {str(e)}")
                raise
    
    # 如果所有重试都失败了，抛出最后一个异常
    raise last_exception


def get_round_numbers(product_id: int, a: int, b: int) -> (int, float, float):
    return product_id, a / 100, b / 100


def get_regular_time_expression(name: str) -> str:
    s = str(name or "").strip()
    up = s.upper()
    if up in {"Y", "YEAR", "YEARS", "YR", "YRS"} or "年" in s:
        return "年"
    if up in {"M", "MON", "MONTH", "MONTHS"} or "月" in s:
        return "个月"
    if up in {"Q", "QUARTER", "QUARTERS"} or "季度" in s:
        return "个月"
    if up in {"D", "DAY", "DAYS"} or "天" in s:
        return "天"
    return "unknown"

def get_regular_time_expression_1(name: str) -> str:
    s = str(name or "").strip()
    up = s.upper()
    if up in {"Y", "YEAR", "YEARS", "YR", "YRS"} or "年" in s:
        return "年"
    if up in {"M", "MON", "MONTH", "MONTHS"} or "月" in s:
        return "月"
    if up in {"Q", "QUARTER", "QUARTERS"} or "季度" in s:
        return "月"
    if up in {"D", "DAY", "DAYS"} or "天" in s:
        return "天"
    return "unknown"

def _extract_response_data(api_json: Any, api_name: str, id_key: str, id_value: Any) -> Optional[dict]:
    """统一校验接口响应结构，避免 data 为空导致下标异常。"""
    if not isinstance(api_json, dict):
        logger.warning("%s 响应非字典，%s=%s，响应片段: %s", api_name, id_key, id_value, str(api_json)[:200])
        return None
    api_code = api_json.get("code")
    api_msg = str(api_json.get("msg") or "").strip()
    data_obj = api_json.get("data")
    if not isinstance(data_obj, dict):
        logger.warning(
            "%s 响应 data 为空或非对象，%s=%s，code=%s msg=%s，响应片段: %s",
            api_name,
            id_key,
            id_value,
            api_code,
            api_msg,
            str(api_json)[:300],
        )
        if api_code == 5 and "请先登录" in api_msg:
            mark_auth_login_required()
            logger.warning(
                "接口返回「请先登录」：请从浏览器打开 https://example.com/internal/toc/kshopwindow/price/list 登录后，复制 Cookie 中的 ovsmgr_sid（可能已过期）"
            )
        return None
    return data_obj

def get_price_detail_by_sku_id(sku_id: int, cookie: str) -> (int, list):
    logger.info(f"开始获取SKU ID {sku_id} 的价格详情")
    msg_list = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Cookie': cookie
    }
    
    try:
        # 使用带重试机制的请求获取价格列表
        res = requests_get_with_retry(price_by_sku_id_url + str(sku_id), headers=headers)
        if res.status_code == 200:
            res_json = res.json()
            list_data = _extract_response_data(res_json, "price/list", "sku_id", sku_id)
            if not list_data:
                msg_list.append(f"sku id: {sku_id} 价格列表返回异常（data为空），请检查 cookie 是否过期或权限不足")
                return 0, msg_list
            count = int(list_data.get("total") or 0)
            price_list = list_data.get("list") or []
            if count != 0 and price_list:
                price_id = (price_list[0] or {}).get("id")
                if not price_id:
                    msg_list.append(f"sku id: {sku_id} 价格列表返回异常，首条价格缺少id")
                    return 0, msg_list

                try:
                    # 使用带重试机制的请求获取价格详情
                    price_detail_res = requests_get_with_retry(price_detail_url + str(price_id), headers=headers)
                    if price_detail_res.status_code == 200:
                        price_json = price_detail_res.json()
                        detail_data = _extract_response_data(price_json, "price/detail", "price_id", price_id)
                        if not detail_data:
                            msg_list.append(f"价格id: {price_id} 详情返回异常（data为空）")
                            return price_id, msg_list
                        payment_types_detail_list = detail_data.get("payment_types_detail") or []
                        if payment_types_detail_list:
                            for payment_type in payment_types_detail_list:
                                third_prod_val = str(payment_type.get("third_prod_val", ""))
                                if " " in third_prod_val:
                                    msg_list.append("三方价格: " + third_prod_val + "配置有空格，检查失败！")
                                else:
                                    msg_list.append("三方价格: " + third_prod_val + "配置无空格, 检查通过")
                            return price_id, msg_list
                        msg_list.append("价格id: " + str(price_id) + "未找到三方价格")
                        return price_id, msg_list
                    msg_list.append(f"价格id: {price_id} 详情接口请求失败，状态码: {price_detail_res.status_code}")
                    return price_id, msg_list
                except requests.exceptions.RequestException as e:
                    msg_list.append(f"价格id: {price_id} 详情接口请求失败，网络错误: {str(e)}")
                    return price_id, msg_list
            else:
                msg_list.append("sku id: " + str(sku_id) + "未找到，请确认是否正确")
                return 0, msg_list
        else:
            msg_list.append(f"sku id: {sku_id} 详情接口请求失败，状态码: {res.status_code}")
            return 0, msg_list
    except requests.exceptions.RequestException as e:
        msg_list.append(f"sku id: {sku_id} 详情接口请求失败，网络错误: {str(e)}")
        return 0, msg_list


def get_price_beautiful_by_sku_id(sku_id: int, cookie: str) -> (float, float, float, float, str):
    logger.info(f"开始获取SKU ID {sku_id} 的参考展示价(US)信息")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Cookie': cookie
    }
    price_usd = 0
    price_usd_beauty = 0
    first_exp_price_usd = 0
    first_exp_price_usd_beauty = 0
    price_name = ""
    
    try:
        # 使用带重试机制的请求获取价格列表
        res = requests_get_with_retry(price_by_sku_id_url + str(sku_id), headers=headers)
        if res.status_code == 200:
            res_json = res.json()
            list_data = _extract_response_data(res_json, "price/list", "sku_id", sku_id)
            if not list_data:
                logger.warning("sku id: %s 获取参考展示价(US)失败，price/list data为空", sku_id)
                return price_usd / 100, price_usd_beauty / 100, first_exp_price_usd / 100, first_exp_price_usd_beauty / 100, price_name
            count = int(list_data.get("total") or 0)
            price_list = list_data.get("list") or []
            if count != 0 and price_list:
                price_id = (price_list[0] or {}).get("id")
                if not price_id:
                    logger.warning("sku id: %s 获取参考展示价(US)失败，price/list 首条缺少id", sku_id)
                    return price_usd / 100, price_usd_beauty / 100, first_exp_price_usd / 100, first_exp_price_usd_beauty / 100, price_name

                try:
                    # 使用带重试机制的请求获取价格详情
                    price_detail_res = requests_get_with_retry(price_detail_url + str(price_id), headers=headers)
                    if price_detail_res.status_code == 200:
                        price_json = price_detail_res.json()
                        detail_data = _extract_response_data(price_json, "price/detail", "price_id", price_id)
                        if not detail_data:
                            return price_usd / 100, price_usd_beauty / 100, first_exp_price_usd / 100, first_exp_price_usd_beauty / 100, price_name
                        price_name = detail_data.get("price_name", "")
                        price_usd = detail_data.get("price_usd", 0)
                        first_exp_price_usd = detail_data.get("first_exp_price_usd", 0)
                        other_country_price_list = detail_data.get("other_country_prices") or []

                        for other_country_price in other_country_price_list:
                            country_info = other_country_price.get("country") or {}
                            country_code = country_info.get("country")
                            if country_code == "US":
                                price_usd_beauty = other_country_price.get("price", 0)
                                break
                        first_exp_price_usd_list = detail_data.get("first_exp_other_country_prices") or []
                        for first_exp_price_usd_item in first_exp_price_usd_list:
                            country_info = first_exp_price_usd_item.get("country") or {}
                            country_code = country_info.get("country")
                            if country_code == "US":
                                first_exp_price_usd_beauty = first_exp_price_usd_item.get("price", 0)
                                break
                    else:
                        logger.error(f"获取价格详情失败，价格id: {price_id}, 状态码: {price_detail_res.status_code}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"获取价格详情失败，价格id: {price_id}, 网络错误: {str(e)}")
            else:
                logger.warning(f"sku id: {sku_id} 未找到价格信息")
        else:
            logger.error(f"获取价格列表失败，sku id: {sku_id}, 状态码: {res.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"获取价格列表失败，sku id: {sku_id}, 网络错误: {str(e)}")
    
    return price_usd / 100, price_usd_beauty / 100, first_exp_price_usd / 100, first_exp_price_usd_beauty / 100, price_name


def get_price_detail_by_price_id(price_id: int, cookie: str) -> tuple:
    """已知 price_id 时直接请求价格详情，返回 (price_id, msg_list)。K列=/ 且 product/listnew 返回 price_id 时使用。"""
    logger.info("开始通过价格ID %s 获取价格详情", price_id)
    msg_list = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Cookie": cookie,
    }
    try:
        res = requests_get_with_retry(price_detail_url + str(price_id), headers=headers)
        if res.status_code == 200:
            price_json = res.json()
            payment_types_detail_list = (price_json.get("data") or {}).get("payment_types_detail") or []
            for payment_type in payment_types_detail_list:
                third_prod_val = payment_type.get("third_prod_val", "")
                if " " in third_prod_val:
                    msg_list.append("三方价格: " + third_prod_val + " 配置有空格，检查失败！")
                else:
                    msg_list.append("三方价格: " + third_prod_val + " 配置无空格, 检查通过")
            return price_id, msg_list
        msg_list.append("价格id: " + str(price_id) + " 详情接口请求失败，状态码: " + str(res.status_code))
        return price_id, msg_list
    except Exception as e:
        msg_list.append("价格id: " + str(price_id) + " 详情接口请求异常: " + str(e))
        return price_id, msg_list


def get_price_beautiful_by_price_id_from_list(price_id: int, cookie: str) -> tuple:
    """按价格ID请求 price/list?ids=xxx，返回 (price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name)。单位已转为元。"""
    url = ADMIN_API_PRICE_LIST_BY_IDS.format(ids=price_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
    }
    headers.update(PRODUCT_LISTNEW_HEADERS_EXTRA or {})
    price_usd = first_exp_price_usd = 0
    price_name = ""
    try:
        res = requests_get_with_retry(url, headers=headers)
        if res.status_code == 200:
            data = res.json().get("data") or {}
            lst = data.get("list") or []
            if lst:
                item = lst[0]
                price_usd = item.get("price_usd", 0)
                first_exp_price_usd = item.get("first_exp_price_usd", 0)
                price_name = item.get("price_name", "")
    except Exception as e:
        logger.error("通过价格ID %s 请求 price/list 异常: %s", price_id, e)
    # list 接口无 other_country_prices，beauty 用 price_usd 折算
    return price_usd / 100, price_usd / 100, first_exp_price_usd / 100, first_exp_price_usd / 100, price_name


def get_price_list_item_by_price_id(price_id: int, cookie: str) -> Optional[dict]:
    """按价格ID请求 price/list?ids=xxx，返回列表第一条原始数据（含 installment、sub_cycle、sub_unit 等），用于判断是否分期。失败或空返回 None。"""
    if not price_id:
        return None
    url = ADMIN_API_PRICE_LIST_BY_IDS.format(ids=price_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
    }
    headers.update(PRODUCT_LISTNEW_HEADERS_EXTRA or {})
    try:
        res = requests_get_with_retry(url, headers=headers)
        if res.status_code == 200:
            data = res.json().get("data") or {}
            lst = data.get("list") or []
            if lst:
                return lst[0]
    except Exception as e:
        logger.debug("get_price_list_item_by_price_id 请求异常 price_id=%s: %s", price_id, e)
    return None


def get_price_beautiful_by_price_id(price_id: int, cookie: str) -> tuple:
    """已知 price_id 时直接请求价格详情，返回 (price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name)。若详情返回 price_usd=0 则用 price/list?ids=xxx 兜底。"""
    logger.info("开始通过价格ID %s 获取参考展示价(US)信息", price_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Cookie": cookie,
    }
    price_usd = price_usd_beauty = first_exp_price_usd = first_exp_price_usd_beauty = 0
    price_name = ""
    try:
        res = requests_get_with_retry(price_detail_url + str(price_id), headers=headers)
        if res.status_code == 200:
            data = (res.json().get("data") or {})
            price_name = data.get("price_name", "")
            price_usd = data.get("price_usd", 0)
            first_exp_price_usd = data.get("first_exp_price_usd", 0)
            for p in data.get("other_country_prices") or []:
                if (p.get("country") or {}).get("country") == "US":
                    price_usd_beauty = p.get("price", 0)
                    break
            for p in data.get("first_exp_other_country_prices") or []:
                if (p.get("country") or {}).get("country") == "US":
                    first_exp_price_usd_beauty = p.get("price", 0)
                    break
    except Exception as e:
        logger.error("通过价格ID %s 获取参考展示价(US)异常: %s", price_id, e)
    # 详情接口返回 price_usd 为 0 时，用 price/list?ids=xxx 兜底（部分价格仅列表有值）
    if price_usd == 0:
        logger.info("价格ID %s 详情 price_usd=0，改用 price/list 兜底", price_id)
        return get_price_beautiful_by_price_id_from_list(price_id, cookie)  # 已为元，直接返回
    return price_usd / 100, price_usd_beauty / 100, first_exp_price_usd / 100, first_exp_price_usd_beauty / 100, price_name


def get_price_detail_data_by_price_id(price_id: int, cookie: str) -> dict:
    """按价格ID请求价格详情，返回 data 字典（原始单位：分）。失败返回空字典。"""
    if not price_id:
        return {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Cookie": cookie,
    }
    try:
        res = requests_get_with_retry(price_detail_url + str(price_id), headers=headers)
        if res.status_code != 200:
            logger.warning("通过价格ID %s 获取价格详情失败，状态码: %s", price_id, res.status_code)
            return {}
        return (res.json().get("data") or {})
    except Exception as e:
        logger.warning("通过价格ID %s 获取价格详情异常: %s", price_id, e)
        return {}


def get_product_by_id(product_id: int, cookie: str) -> Optional[dict]:
    """
    根据商品ID从后台 product/listnew 接口获取商品信息，并映射为橱窗 shop_item 的 origin_item_info 结构，
    供 ShopItemNewParser 与后续校验逻辑复用。
    K列="/" 时使用，不依赖橱窗。
    Cookie 与 main.py 中配置的 cookie 一致，全项目统一使用 main 的 cookie，不读 config。
    :param product_id: 商品ID（Excel I列）
    :param cookie: 后台 Cookie（ovsmgr_sid=xxx），由 main.py 传入
    :return: 映射后的 origin_item_info 字典，可直接用于 {"origin_item_info": ...}；失败返回 None
    """
    if not (cookie or "").strip():
        logger.warning("product/listnew 未传入 cookie，请检查 main.py 中是否已填写 cookie（ovsmgr_sid=xxx）")
        return None
    # 与后台页面请求保持一致：带上全部入参（空值也传），避免后端对「缺参」与「空参」处理不一致导致 list 为空
    url = (
        PRODUCT_LISTNEW_BASE_URL.rstrip("/") + PRODUCT_LISTNEW_PATH
        + "?platform=&ids=" + str(product_id)
        + "&name=&price_ids=&rights_ids=&sub_cycle=&sub_cycle_unit=&one_time_cycle=&one_time_unit="
        + "&try_cycle=&try_unit=&price_amount=&pay_type=&status=0&used_status=0"
        + "&sku_item_name=&item_feat=&remark=&page_num=1&page_size=20"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
    }
    headers.update(PRODUCT_LISTNEW_HEADERS_EXTRA or {})

    try:
        res = requests_get_with_retry(url, headers=headers)
        if res.status_code != 200:
            logger.error("product/listnew 请求失败，商品id: %s, 状态码: %s", product_id, res.status_code)
            return None
        data = res.json()
        lst = (data.get("data") or {}).get("list") or []
        if not lst:
            # 便于排查：打出接口 code/msg 及 data 情况，区分「未登录」「无数据」等
            api_code = data.get("code")
            api_msg = (data.get("msg") or "").strip()
            data_obj = data.get("data")
            list_len = len(data_obj.get("list") or []) if isinstance(data_obj, dict) else 0
            logger.warning(
                "product/listnew 未返回商品，商品id: %s，响应 code=%s msg=%s data.list长度=%s",
                product_id, api_code, api_msg, list_len
            )
            if api_code == 5 and "请先登录" in api_msg:
                logger.warning(
                    "接口返回「请先登录」：请从浏览器打开 %s 登录后，复制 Cookie 中的 ovsmgr_sid 到 main.py 的 cookie 变量（可能已过期）",
                    PRODUCT_LISTNEW_BASE_URL.rstrip("/").replace("/manage/1", "") if PRODUCT_LISTNEW_BASE_URL else "星宿管理后台"
                )
            return None
        raw = lst[0]
    except Exception as e:
        logger.error("product/listnew 请求异常，商品id: %s, 错误: %s", product_id, e)
        return None

    # 映射为 ShopItemNewParser.get_origin_price_new 使用的 origin_item_info 结构
    # 真实 API：price_id、price_amount(分)、周期在 rights[0].sub_cycle/sub_cycle_unit、name 用 sku_item_name
    rights_list = raw.get("rights") or []
    first_right = rights_list[0] if rights_list else {}
    period = (raw.get("period") or raw.get("sub_cycle") or first_right.get("sub_cycle")
              or raw.get("one_time_cycle") or first_right.get("one_time_cycle"))
    period_unit = (raw.get("period_unit") or raw.get("sub_cycle_unit") or first_right.get("sub_cycle_unit")
                   or raw.get("one_time_cycle_unit") or raw.get("one_time_unit")
                   or first_right.get("one_time_cycle_unit") or first_right.get("one_time_unit") or "Y")
    # 加赠：优先从 give_right_display[0].right_duration 解析（如 "6月"、"1年"），再试 raw/rights[0].right_duration，否则 give_cycle/give_unit
    def _parse_duration_to_give(dur_str):
        if not dur_str:
            return 0, ""
        _dur = str(dur_str).strip()
        _m_y = re.search(r"(\d+)\s*年", _dur)
        _m_m = re.search(r"(\d+)\s*个?月", _dur)
        if _m_y:
            return int(_m_y.group(1)), "Y"
        if _m_m:
            return int(_m_m.group(1)), "M"
        return 0, ""

    give_cycle = raw.get("give_cycle") or first_right.get("give_cycle") or 0
    _give_unit_raw = raw.get("give_unit") or first_right.get("give_unit") or ""
    # 同上，保留原始单位字符串，避免 "个月" 被截断成 "个"
    give_unit = _give_unit_raw.strip() if _give_unit_raw else ""
    if not give_cycle or not give_unit:
        give_right_display = raw.get("give_right_display") or []
        if give_right_display and isinstance(give_right_display, list):
            first_display = give_right_display[0] if give_right_display else {}
            if isinstance(first_display, dict):
                _gc, _gu = _parse_duration_to_give(first_display.get("right_duration"))
                if _gc and _gu:
                    give_cycle, give_unit = _gc, _gu
        if not give_cycle or not give_unit:
            right_duration = raw.get("right_duration") or first_right.get("right_duration") or ""
            if right_duration:
                give_cycle, give_unit = _parse_duration_to_give(right_duration)
    amount = raw.get("amount")
    if amount is None and "price_amount" in raw:
        amount = raw.get("price_amount")
    if amount is None:
        amount = 0
    price_id_from_api = raw.get("price_id")
    origin_item_info = {
        "id": raw.get("id") or product_id,
        "sku_id": raw.get("sku_id"),
        "price_id": price_id_from_api,
        "name": (raw.get("name") or raw.get("sku_item_name") or "").strip(),
        "period": period,
        "period_unit": period_unit,
        "give_cycle": give_cycle,
        "give_unit": give_unit,
        "give_contents": raw.get("give_contents") or "",
        "amount": int(amount) if amount is not None else 0,
    }
    if not origin_item_info.get("sku_id") and not origin_item_info.get("price_id"):
        logger.warning("product/listnew 返回商品缺少 sku_id 与 price_id，商品id: %s", product_id)
    return origin_item_info


def get_shopwindow_admin_detail(shopwindow_id: int, cookie: str) -> Optional[dict]:
    """
    通过后台 shop-window/listnew 接口查询橱窗详情（管理视角）。
    返回完整的 window_data dict（含 rule_config 槽位映射），失败返回 None。
    """
    if not (cookie or "").strip():
        logger.warning("shop-window/listnew 未传入 cookie")
        return None
    url = (
        ADMIN_API_BASE_URL.rstrip("/") + ADMIN_SHOPWINDOW_LISTNEW_PATH
        + "?platform=&ids=" + str(shopwindow_id)
        + "&name=&status=0&item_ids=&discount_itme_ids="
        + "&sub_cycle=&sub_unit=&one_time_cycle=&one_time_unit="
        + "&trial_cycle=&trial_unit=&price_usd=&price_type="
        + "&payment_types=%5B%5D&gp_grace_days=&use_status="
        + "&style_ids=&remark=&page_num=1&page_size=20"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
    }
    headers.update(PRODUCT_LISTNEW_HEADERS_EXTRA or {})

    try:
        res = requests_get_with_retry(url, headers=headers)
        if res.status_code != 200:
            logger.error("shop-window/listnew 请求失败，橱窗id: %s, 状态码: %s", shopwindow_id, res.status_code)
            return None
        data = res.json()
        api_code = data.get("code")
        if api_code != 0:
            api_msg = (data.get("msg") or "").strip()
            logger.warning("shop-window/listnew 返回非成功，橱窗id: %s, code=%s, msg=%s", shopwindow_id, api_code, api_msg)
            return None
        lst = (data.get("data") or {}).get("list") or []
        if not lst:
            logger.warning("shop-window/listnew 未返回橱窗数据，橱窗id: %s", shopwindow_id)
            return None
        window_data = lst[0]
        logger.debug(
            "shop-window/listnew 橱窗 %s 响应顶层字段: %s",
            shopwindow_id, list(window_data.keys())
        )
        return window_data
    except Exception as e:
        logger.error("shop-window/listnew 请求异常，橱窗id: %s, 错误: %s", shopwindow_id, e)
        return None


# 后台 rule_config 扁平字段 → pay_window 槽位名的映射
ADMIN_FIELD_TO_SLOT = {
    "origin_item_id":              "origin_item_info",
    "discount_origin_item_id":     "discount_origin_item_info",
    "has_try_item_id":             "trial_item_info",
    "discount_try_item_id":        "discount_trial_item_info",
    "onetime_item_id":             "one_time_origin_item_info",
    "onetime_item_id_discount":    "one_time_discount_item_info",
    "first_exp_item_id":           "first_exp_item_info",
    "trial_first_exp_item_id":     "trial_first_exp_item_info",
    "retain_pay_origin_item_id":   "retain_pay_origin_item_info",
    "retain_pay_try_item_id":      "retain_pay_try_item_info",
    "retain_pay_one_time_item_id": "retain_pay_one_time_item_info",
}


def find_product_slot_in_admin(window_data: dict, product_id: int) -> Optional[str]:
    """
    在后台橱窗 rule_config 中查找 product_id 所在的槽位。
    rule_config 每条规则的槽位字段是逗号分隔的商品ID字符串，如 "9827,9514,9518"。
    :return: 匹配到的 pay_window 槽位名（如 "discount_origin_item_info"），未找到返回 None
    """
    rule_config = window_data.get("rule_config")
    if not isinstance(rule_config, list):
        return None
    pid_str = str(product_id)
    for rule in rule_config:
        if not isinstance(rule, dict):
            continue
        for admin_field, slot_name in ADMIN_FIELD_TO_SLOT.items():
            ids_raw = rule.get(admin_field) or ""
            if not ids_raw:
                continue
            ids_list = [x.strip() for x in str(ids_raw).split(",") if x.strip()]
            if pid_str in ids_list:
                logger.debug(
                    "后台 rule_config 中商品 %s 在字段 %s 中匹配到，映射槽位: %s",
                    product_id, admin_field, slot_name
                )
                return slot_name
    return None


if __name__ == "__main__":
    get_price_beautiful_by_sku_id(4646, "ovsmgr_sid=xxx")
