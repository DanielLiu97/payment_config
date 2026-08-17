# -*- coding: utf-8 -*-
"""
@File    : analysis_sku.py
@Author  : your-email@example.com
@Date    : 2024/12/26
@UpdatedBy : liuxingquan
@UpdatedDate : 2026/02/09
@Description : Excel数据提取和校验逻辑
@UpdateNote : 
    1. 重构硬编码配置，使用config/config.py统一管理配置项
    2. 修复商品匹配逻辑：
       - 优先通过商品ID匹配（支持主商品组和加购商品组）
       - 支持匹配所有商品类型（原价、折扣、试用、一次性等）
       - 如果ID匹配失败，回退到索引匹配
    3. 修复挽回橱窗ID读取逻辑：
       - 优先从Excel K列读取（支持"挽回：XXXX"格式）
       - 如果K列为空，使用API的retain_id
       - 添加异常处理，防止解析失败导致程序中断
    4. 优化错误处理：
       - 将"在橱窗中未找到匹配的商品ID"从ERROR降级为WARNING（因为存在回退机制）
       - 添加商品ID转换的异常处理（ValueError, TypeError）
       - 添加挽回橱窗ID解析的异常处理（ValueError, TypeError, AttributeError）
       - 添加IndexError处理，防止列表越界
    5. 修复PC平台加购商品处理：明确区分iOS/Android/PC平台的价格类型分发逻辑
    6. 优化Bot消息发送：添加timeout参数，防止请求挂起
    7. 修复橱窗ID格式支持：支持"支付页：XXXX"和"支付：XXXX"两种格式（Sheet4使用"支付："格式）
"""
import re
import time
from datetime import datetime
from typing import Union, List, Optional, Tuple

import pandas as pd
import requests

from config.logger import logger
from parser.shop_item_new_parser import ShopItemNewParser
from parser.shop_window_parser import ShopWindowParser

from config.config import (
    MERGED_CELL_COLUMNS, EXCEL_COLUMN_INDEX, SHOP_WINDOW_ID_KEYWORDS,
    PRICE_THRESHOLD, EXP_PRICE_THRESHOLD,
    BOT_WEBHOOK_URL, BOT_WEBHOOK_URLS, BOT_DEBUG_WEBHOOK_URLS, BOT_TIMEOUT, BOT_MSG_MAX_LENGTH, CHECK_COUPON_WITH_SHOP_WINDOW, RETRY_CONFIG
)
from utils.utils import (
    get_product_by_id,
    get_shopwindow_admin_detail,
    find_product_slot_in_admin,
    get_price_detail_by_price_id,
    get_price_detail_data_by_price_id,
    get_price_beautiful_by_price_id,
    get_price_list_item_by_price_id,
    get_regular_time_expression,
    get_regular_time_expression_1,
    reset_auth_issue_flags,
    is_auth_login_required_suspected,
)
from parser.shop_item_new_parser import get_cycle, get_give_cycle_months

# 使用配置文件中的列索引
read_merged_cell_list = MERGED_CELL_COLUMNS

country_index = EXCEL_COLUMN_INDEX["country"]
member_type_index = EXCEL_COLUMN_INDEX["member_type"]
price_type_index = EXCEL_COLUMN_INDEX["price_type"]
product_order_index = EXCEL_COLUMN_INDEX["product_order"]
cycle_index = EXCEL_COLUMN_INDEX["cycle"]
total_price_index = EXCEL_COLUMN_INDEX["total_price"]
avg_price_index = EXCEL_COLUMN_INDEX["avg_price"]
price_id_index = EXCEL_COLUMN_INDEX["price_id"]
product_id_index = EXCEL_COLUMN_INDEX["product_id"]
product_give_cycle_index = EXCEL_COLUMN_INDEX["product_give_cycle"]
shop_window_id_index = EXCEL_COLUMN_INDEX["shop_window_id"]
exp_price_index = EXCEL_COLUMN_INDEX.get("exp_price", 11)
exp_cycle_index = EXCEL_COLUMN_INDEX.get("exp_cycle", 12)
IOS_LIKE_PLATFORMS = {"ios", "ipad"}

# 使用配置文件中的关键字
match_key_word = SHOP_WINDOW_ID_KEYWORDS[0]  # "支付页"

shop_window_id_obj_dict = {}

# 使用配置文件中的阈值
threshold = PRICE_THRESHOLD
PRICE_THRESHOLD = PRICE_THRESHOLD

# 使用配置文件中的Bot URL（支持多机器人）
msg_bot_urls = [u for u in (BOT_WEBHOOK_URLS or [BOT_WEBHOOK_URL]) if u]
debug_bot_urls = [u for u in (BOT_DEBUG_WEBHOOK_URLS or []) if u]

# 橱窗槽位 -> 取价方法名（从数组中找到匹配商品id后，按命中的槽位调用对应方法，保证取价与槽位一致）
_SLOT_TO_GET_METHOD = {
    "origin_item_info": "get_origin_price_new",
    "discount_origin_item_info": "get_discount_price_new",
    "trial_item_info": "get_trial_price_new",
    "discount_trial_item_info": "get_discount_trial_price_new",
    "one_time_origin_item_info": "get_onetime_origin_price_new",
    "one_time_discount_item_info": "get_onetime_discount_price_new",
    "retain_pay_origin_item_info": "get_retain_price_new",
    "retain_pay_try_item_info": "get_retain_trial_price_new",
    "retain_pay_one_time_item_info": "get_onetime_retain_price_new",
}
# 仅用于“按商品ID找候选”的体验价补充槽位（不直接映射取价方法）
_EXTRA_MATCH_ONLY_SLOTS = ["first_exp_item_info", "trial_first_exp_item_info"]
# 主商品组 + 加购组内要遍历的槽位（用于“从数组里找匹配的商品id”）
_ALL_MATCH_SLOTS = list(_SLOT_TO_GET_METHOD.keys()) + _EXTRA_MATCH_ONLY_SLOTS
# 价格类型 -> 该类型对应的槽位（仅在这些槽位中匹配，保证取价与行一致，避免原价行取到折扣价槽位导致月均价误报）
_SLOTS_BY_PRICE_TYPE = {
    "原价": ["origin_item_info"],
    "划线价": ["origin_item_info"],
    "折扣价": ["discount_origin_item_info"],
    "体验价": ["trial_item_info", "discount_trial_item_info", "first_exp_item_info", "trial_first_exp_item_info"],
    "试用": ["trial_item_info"],
    "试用价": ["trial_item_info"],
    "折扣价-3天试用": ["discount_trial_item_info"],
    "一次性原价": ["one_time_origin_item_info"],
    "一次性折扣价": ["one_time_discount_item_info"],
    "挽回": ["retain_pay_origin_item_info"],
    "挽回价": ["retain_pay_origin_item_info"],
    "挽回试用": ["retain_pay_try_item_info"],
    "一次性挽回价": ["retain_pay_one_time_item_info"],
    "成交价": ["origin_item_info", "discount_origin_item_info"],
    "一次性成交价": ["one_time_origin_item_info", "one_time_discount_item_info"],
    "加购": ["origin_item_info"],
    "试用加购": ["trial_item_info"],
    "加购试用": ["trial_item_info"],
}
_RETAIN_PRICE_TYPES = {"挽回", "挽回价", "挽回试用", "一次性挽回价"}
_DEAL_PRICE_TYPES = {"成交价", "一次性成交价", "折扣价"}

# ---------- 价格类型归一化 ----------
# 运营在 Excel 中可能使用不同的别名描述同一种价格类型，
# 在此统一映射为代码已适配的标准名称，避免每次出现新别名都要改取价逻辑。
# 新增别名时只需在这里加一条映射即可。
_PRICE_TYPE_ALIAS = {
    "试用折扣价":       "折扣价-3天试用",
    "直接订阅折扣价":   "折扣价",
    "加购试用":         "试用加购",
    "挽回-折扣价":      "挽回价",
    "挽回-试用折扣价":  "折扣价-3天试用",
}

# 运营有时在价格类型前加业务前缀（如"挽回-折扣价"），需要剥离的前缀列表
_PRICE_TYPE_PREFIXES_TO_STRIP = ["挽回-", "挽留-"]


def _normalize_price_type(raw_name: str) -> str:
    """将 Excel 中的价格类型别名归一化为标准名称。
    1. 精确匹配别名表（优先，可处理 "挽回-折扣价" → "挽回价" 等特殊映射）
    2. 剥离业务前缀后再匹配别名表
    3. 剥离前缀后的名称本身若是已适配类型则直接使用
    4. 均不命中则原样返回
    """
    if raw_name in _PRICE_TYPE_ALIAS:
        return _PRICE_TYPE_ALIAS[raw_name]
    for prefix in _PRICE_TYPE_PREFIXES_TO_STRIP:
        if raw_name.startswith(prefix):
            stripped = raw_name[len(prefix):]
            if stripped in _PRICE_TYPE_ALIAS:
                return _PRICE_TYPE_ALIAS[stripped]
            return stripped
    return raw_name


def _id_equals(left, right) -> bool:
    """比较商品ID，兼容 int/float/数字字符串。"""
    if left is None or right is None:
        return False
    try:
        return int(str(left).strip()) == int(str(right).strip())
    except (ValueError, TypeError):
        return str(left).strip() == str(right).strip()


def _collect_matching_candidates(shop_items_list, slots_to_try, excel_product_id):
    """从主商品组与加购组收集匹配商品ID的候选 (container, slot)。"""
    candidates = []
    for shop_item in shop_items_list:
        for slot in slots_to_try:
            item = shop_item.get(slot)
            if isinstance(item, dict) and _id_equals(item.get("id"), excel_product_id):
                candidates.append((shop_item, slot))
        if shop_item.get("add_buy_info") and isinstance(shop_item["add_buy_info"], list):
            for add_buy_group in shop_item["add_buy_info"]:
                for slot in slots_to_try:
                    item = add_buy_group.get(slot)
                    if isinstance(item, dict) and _id_equals(item.get("id"), excel_product_id):
                        candidates.append((add_buy_group, slot))
    return candidates


def _is_k_cell_blank(val) -> bool:
    """K 列单元格是否视为空白（空、缺、NaN）。"""
    return val in [None, '', ' '] or pd.isna(val)


def _is_blank_cell(val) -> bool:
    return val in [None, "", " "] or pd.isna(val)


def _is_ios_like_platform(system: str) -> bool:
    return str(system or "").strip().lower() in IOS_LIKE_PLATFORMS


def _norm_cycle_unit(unit_value: str) -> str:
    s = str(unit_value or "").strip().upper()
    if not s:
        return ""
    if s in {"D", "DAY", "DAYS"} or "天" in s:
        return "D"
    if s in {"M", "MON", "MONTH", "MONTHS"} or "月" in s:
        return "M"
    if s in {"Y", "YEAR", "YEARS"} or "年" in s:
        return "Y"
    if s in {"Q", "QUARTER", "QUARTERS"} or "季" in s:
        return "Q"
    return ""


def _normalize_cycle_value_unit(value, unit_value: str) -> str:
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return ""
    u = _norm_cycle_unit(unit_value)
    if n <= 0 or not u:
        return ""
    return f"{n}{u}"


def _normalize_cycle_text(cell_value) -> str:
    text = str(cell_value or "").strip()
    if not text:
        return ""
    m = re.search(r"(\d+)\s*([dDmMyYqQ])\b", text)
    if m:
        return _normalize_cycle_value_unit(m.group(1), m.group(2))
    m = re.search(r"(\d+)\s*(天|日|个月|月|年|季度|季)", text)
    if m:
        return _normalize_cycle_value_unit(m.group(1), m.group(2))
    m = re.search(r"(\d+)\s*(day|days|month|months|year|years|quarter|quarters)\b", text, flags=re.IGNORECASE)
    if m:
        return _normalize_cycle_value_unit(m.group(1), m.group(2))
    return ""


def _collect_exp_info_from_current_product_info(current_product_info: dict) -> tuple:
    """从当前命中的橱窗商品结构中尝试提取体验价金额(USD)与周期。"""
    if not isinstance(current_product_info, dict):
        return None, ""
    for slot in [
        "origin_item_info",
        "discount_origin_item_info",
        "trial_item_info",
        "discount_trial_item_info",
        "first_exp_item_info",
        "trial_first_exp_item_info",
    ]:
        item = current_product_info.get(slot)
        if not isinstance(item, dict):
            continue
        first_exp = item.get("first_exp_info") or {}
        price_usd = None
        amount_cents = first_exp.get("amount")
        if amount_cents not in [None, ""]:
            try:
                price_usd = round(float(amount_cents) / 100.0, 2)
            except (ValueError, TypeError):
                price_usd = None
        cycle_norm = _normalize_cycle_value_unit(first_exp.get("duration"), first_exp.get("duration_unit"))
        if price_usd is not None or cycle_norm:
            return price_usd, cycle_norm
    return None, ""


def _parse_excel_cycle_to_months(cell_value: str):
    """将 Excel 周期单元格（如「1年」「12月」「1y」「6m」）解析为月数。无法解析返回 None。"""
    if not cell_value or not str(cell_value).strip():
        return None
    s = str(cell_value).strip()
    m = re.search(r"(\d+)\s*年", s)
    if m:
        return int(m.group(1)) * 12
    m = re.search(r"(\d+)\s*月", s)
    if m:
        return int(m.group(1))
    # 支付配置简写：1y / 6m / 12M（与接口「1年」「6月」等价）
    m = re.match(r"^(\d+)\s*([yYmM])$", s)
    if m:
        n, u = int(m.group(1)), m.group(2).upper()
        if u == "Y":
            return n * 12
        if u == "M":
            return n
    return None


def _cycle_cell_matches_api(excel_cell: str, api_main_period: str) -> bool:
    """Excel 商品周期与接口 main_period 是否同一语义（含 1y≈1年、6m≈6月、12m≈1年）。"""
    if excel_cell is None or api_main_period is None:
        return False
    ex = str(excel_cell).strip()
    ap = str(api_main_period).strip()
    if not ex or not ap:
        return False
    if ex == ap:
        return True
    mx = _parse_excel_cycle_to_months(ex)
    ma = _parse_excel_cycle_to_months(ap)
    return mx is not None and ma is not None and mx == ma


def _expand_give_cycle_shorthand(cell: str) -> str:
    """买赠列简写 6m/1y → 与接口文案易匹配的「6个月」「1年」（仅用于双向包含判断）。"""
    if not cell or not str(cell).strip():
        return ""
    s = str(cell).strip()
    m = re.match(r"^(\d+)\s*([mMyY])$", s)
    if not m:
        return s
    n, u = int(m.group(1)), m.group(2).upper()
    if u == "M":
        return str(n) + "个月"
    return str(n) + "年"


def _normalize_give_cycle_text(text: str) -> str:
    """规范化买赠文案：去掉「买赠/加赠」前缀，保留周期表达本体。"""
    if text is None:
        return ""
    cleaned = str(text).strip()
    # 兼容「首优20%、买赠6个月」：买赠比对前先剔除首优折扣段，避免把首优文案误当买赠内容
    cleaned = re.sub(r"首优\s*\d+(?:\.\d+)?\s*[%％]", "", cleaned)
    cleaned = cleaned.replace("首优", "")
    cleaned = cleaned.replace("买赠", "").replace("加赠", "")
    return cleaned.strip("，,、;； ").strip()


def _parse_first_discount(cell_text: object) -> Tuple[bool, Optional[float], bool]:
    """
    解析 J 列中的「首优n%」。
    返回: (是否包含首优, 折扣比例(0~1), 是否有效)
    """
    raw = "" if cell_text is None else str(cell_text).strip()
    if not raw:
        return False, None, True
    has_first = "首优" in raw
    if not has_first:
        return False, None, True
    m = re.search(r"首优\s*(\d+(?:\.\d+)?)\s*[%％]", raw)
    if not m:
        return True, None, False
    try:
        pct = float(m.group(1))
    except ValueError:
        return True, None, False
    if pct < 0 or pct > 100:
        return True, None, False
    return True, pct / 100.0, True


def _apply_first_discount(value: object, rate: Optional[float]) -> object:
    """按首优折扣比例折算数值；无折扣时原样返回。"""
    if rate is None:
        return value
    try:
        return round(float(value) * (1 - rate), 2)
    except (TypeError, ValueError):
        return value


def _strip_first_discount_text(cell_text: object) -> str:
    """从 J 列中剥离首优相关文本，返回剩余的买赠内容；若只有首优信息则返回空串。"""
    if cell_text is None:
        return ""
    try:
        if pd.isna(cell_text):
            return ""
    except (TypeError, ValueError):
        pass
    raw = str(cell_text).strip()
    if not raw or raw.lower() == "nan":
        return ""
    cleaned = re.sub(r"首优\s*\d+(?:\.\d+)?\s*[%％]\s*(?:OFF)?(?:\([^)]*\))?", "", raw)
    cleaned = re.sub(r"[、，,\s]+$", "", cleaned.strip())
    cleaned = re.sub(r"^[、，,\s]+", "", cleaned.strip())
    return cleaned.strip()


def _is_no_give_text(text: str) -> bool:
    """判断文本是否表达「无买赠」语义。"""
    if text is None:
        return True
    normalized = str(text).strip()
    if not normalized:
        return True
    # 仅有首优折扣信息时，不应被当作买赠信息
    normalized = re.sub(r"首优\s*\d+(?:\.\d+)?\s*[%％]", "", normalized)
    normalized = normalized.replace("首优", "").strip("，,、;； ").strip()
    if not normalized:
        return True
    compact = re.sub(r"\s+", "", normalized)
    return compact in {
        "/",
        "-",
        "--",
        "无",
        "无买赠",
        "不买赠",
        "不带买赠",
        "无加赠",
        "不加赠",
        "none",
        "null",
        "nil",
    }


def _extract_give_months(give_period: str) -> int:
    """从接口买赠文案中提取加赠月数（如 买赠6个月 -> 6；买赠1年 -> 12）。"""
    if give_period is None:
        return 0
    raw = str(give_period).strip()
    if not raw:
        return 0
    normalized = _normalize_give_cycle_text(raw)
    months = _parse_excel_cycle_to_months(normalized)
    if months is not None and months > 0:
        return int(months)
    m = re.search(r"(\d+)\s*(年|个月|月|[mMyY])", raw)
    if not m:
        return 0
    n = int(m.group(1))
    unit = m.group(2)
    if unit in ("年", "y", "Y"):
        return n * 12
    return n


def _give_cycle_matches_api(cell_give: str, api_give: str) -> bool:
    """
    买赠文案一致性判断：
    1) 先按文案双向包含（兼容老逻辑）
    2) 再按月数等价（兼容「买赠2M」vs「买赠2个月」这类命名差异）
    """
    _cell = str(cell_give or "").strip()
    _api = str(api_give or "").strip()
    if _is_no_give_text(_cell):
        _cell = ""
    if _is_no_give_text(_api):
        _api = ""
    if not _cell and not _api:
        return True
    if not _cell or not _api:
        return False
    _cell_x = _expand_give_cycle_shorthand(_normalize_give_cycle_text(_cell))
    if (
        _api in _cell
        or _cell in _api
        or (_cell_x and (_api in _cell_x or _cell_x in _api))
    ):
        return True
    _cell_months = _extract_give_months(_cell)
    _api_months = _extract_give_months(_api)
    return _cell_months > 0 and _api_months > 0 and _cell_months == _api_months


def _item_main_period_str(item: dict) -> str:
    """从槽位 item（如 origin_item_info）中取 period、period_unit，返回与 Excel 周期可比的字符串，如 '1年'、'2年'。"""
    if not item or not isinstance(item, dict):
        return ""
    period = item.get("period") or 0
    # 保留原始单位（如 "个月"/"month"），由 get_regular_time_expression_1 与下游归一化处理
    period_unit = str(item.get("period_unit") or "Y").strip() or "Y"
    period_chinese = get_regular_time_expression_1(period_unit)
    return str(period) + period_chinese


def _price_avg_from_product_item(product_item: dict) -> tuple:
    """
    从 product/listnew 映射出的 product_item（含 amount 分、period、period_unit、give_cycle、give_unit）
    计算 总价(USD)、主周期月数、加赠月数、月均价。无加赠时 月均价=总价/主周期月数。
    :return: (price_total_usd, main_cycle_months, give_cycle_months, price_avg) 任一无法计算时 price_avg 为 None
    """
    if not product_item or not isinstance(product_item, dict):
        return (None, None, None, None)
    amount_cents = product_item.get("amount")
    if amount_cents is None:
        return (None, None, None, None)
    price_total_usd = amount_cents / 100.0
    period = product_item.get("period") or 0
    # 不截断单位，避免 "个月" -> "个" 导致 get_cycle 误判为 1 个月
    period_unit = str(product_item.get("period_unit") or "Y").strip() or "Y"
    give_cycle = product_item.get("give_cycle") or 0
    give_unit = str(product_item.get("give_unit") or "").strip() if product_item.get("give_unit") else ""
    main_cycle = get_cycle(int(period) if period is not None else 0, period_unit)
    give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
    total_cycle = main_cycle + give_cycle_months
    if total_cycle <= 0:
        return (price_total_usd, main_cycle, give_cycle_months, None)
    price_avg = round(price_total_usd / total_cycle, 2)
    return (price_total_usd, main_cycle, give_cycle_months, price_avg)


def _item_give_period_str(item: dict) -> str:
    """从槽位 item 中取 give_cycle、give_unit，返回与 Excel 买赠列可比的字符串，如 '买赠1个月'；无加赠返回 ''。"""
    if not item or not isinstance(item, dict):
        return ""
    give_cycle = item.get("give_cycle") or 0
    give_unit = str(item.get("give_unit") or "").strip() if item.get("give_unit") else ""
    if not give_cycle or not give_unit:
        return ""
    give_unit_chinese = get_regular_time_expression(give_unit)
    return "买赠" + str(give_cycle) + give_unit_chinese


def get_each_line_shop_window_id(shop_window_id_value: str, index: int, previous_shop_window_id_inner: int,
                                  sheet_has_k_slash: bool = False) -> Union[int, List[int]]:
    """
    解析当前行 K 列得到橱窗 id。
    规则：
    - 若本 sheet 中存在 K 列为 "/"：该 sheet 下 K 只有 "/" 或橱窗 id 两种填写，不应出现空白；若出现空白则告警并沿用上一行。
    - 若本 sheet 中 K 列没有 "/"：空白格沿用上一行橱窗 id（正常用法）。
    - K 列为 "7664+7722" 这种加号拼接时：返回 [7664, 7722]，表示该行分别用这两个橱窗 id 各校验一次。
    """
    # 空/缺/NaN：沿用上一行（若本 sheet 有 "/" 则打一条提示：通常不应空白）
    if _is_k_cell_blank(shop_window_id_value):
        if sheet_has_k_slash:
            logger.warning("第" + str(index + 2) + "行 K 列为空；本 sheet 存在 K=/，通常 K 只填 / 或橱窗 id，已沿用上一行橱窗 id: " + str(previous_shop_window_id_inner))
        else:
            logger.info("第" + str(index + 2) + "行沿用橱窗id: " + str(previous_shop_window_id_inner))
        return previous_shop_window_id_inner
    # Excel 有时把数字读成 float（如 3553.0）：按整数解析
    if type(shop_window_id_value) is float:
        if shop_window_id_value == int(shop_window_id_value) and shop_window_id_value > 0:
            wid = int(shop_window_id_value)
            logger.info("第" + str(index + 2) + "行解析橱窗id为" + str(wid) + "（K列为数字）")
            return wid
        if sheet_has_k_slash:
            logger.warning("第" + str(index + 2) + "行 K 列值异常（非正数）；本 sheet 存在 K=/，已沿用上一行橱窗 id: " + str(previous_shop_window_id_inner))
        else:
            logger.info("第" + str(index + 2) + "行沿用橱窗id: " + str(previous_shop_window_id_inner))
        return previous_shop_window_id_inner
    # K 列为纯数字（Excel 可能读成 int 或 "3553"）：直接当作橱窗 id
    if type(shop_window_id_value) is int:
        if shop_window_id_value > 0:
            logger.info("第" + str(index + 2) + "行解析橱窗id为" + str(shop_window_id_value) + "（K列为数字）")
            return shop_window_id_value
        logger.info("第" + str(index + 2) + "行沿用橱窗id: " + str(previous_shop_window_id_inner))
        return previous_shop_window_id_inner
    s = str(shop_window_id_value).strip()
    # K 列为 "7664+7722" 这种加号拼接：返回多个橱窗 id，该行分别用每个橱窗各校验一次
    if "+" in s:
        parts = [p.strip() for p in s.split("+") if p.strip()]
        ids = []
        for p in parts:
            if p.isdigit():
                ids.append(int(p))
            else:
                m = re.search(r"\d+", p)
                if m:
                    ids.append(int(m.group()))
        if len(ids) >= 2:
            logger.info("第" + str(index + 2) + "行解析橱窗id为多橱窗: " + str(ids) + "（K列加号拼接，将分别校验）")
            return ids
        if len(ids) == 1:
            logger.info("第" + str(index + 2) + "行解析橱窗id为" + str(ids[0]) + "（K列加号拼接仅一个有效数字）")
            return ids[0]
    # K 列为纯数字字符串如 "3553"
    if s.isdigit():
        shop_window_id_int = int(s)
        logger.info("第" + str(index + 2) + "行解析橱窗id为" + str(shop_window_id_int) + "（K列为数字）")
        return shop_window_id_int
    # K 列含任意数字：默认取第一个数字为橱窗 id（支持 "挽回：7621"、"支付页：3553" 等）
    match = re.search(r'\d+', s)
    if match:
        shop_window_id_int = int(match.group())
        logger.info("第" + str(index + 2) + "行解析橱窗id为" + str(shop_window_id_int) + "（K列含数值）")
        return shop_window_id_int
    # 含「支付页」「支付」的文案：从文案中提取数字（保留兼容，上面已覆盖）
    if any(keyword in s for keyword in SHOP_WINDOW_ID_KEYWORDS) or "支付" in s:
        match = re.search(r'\d+', s)
        if match:
            shop_window_id_int = int(match.group())
            logger.info("第" + str(index + 2) + "行解析橱窗id为" + str(shop_window_id_int))
            return shop_window_id_int
        return 0
    # 其他（如合并单元格占位、无关文字）：沿用
    if sheet_has_k_slash:
        logger.warning("第" + str(index + 2) + "行 K 列既非 / 也非橱窗 id；本 sheet 存在 K=/，已沿用上一行橱窗 id: " + str(previous_shop_window_id_inner))
    else:
        logger.info("第" + str(index + 2) + "行沿用橱窗id: " + str(previous_shop_window_id_inner))
    return previous_shop_window_id_inner


def analysis_sku_xls_file_new(file_path: str, mod: str, mock_country: str, system: str, is_uwp: bool, sheet_index: int,
                              cookie: str, restart: bool, restart_index: int, restart_shop_window_id: int,
                              restart_end_index: int = None, only_row_numbers: list = None,
                              progress_callback=None) -> list:
    time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.warning("=================" + time_str + " 开始校验" + "================")
    reset_auth_issue_flags()
    # 支付橱窗 pay_window 接口要求 platform 为小写 pc/android/ios；main 里写 PC 会导致 data 为空
    system = str(system or "pc").strip().lower()
    df = pd.read_excel(file_path, sheet_name=sheet_index)

    # 填充合并单元格的空值
    for col_name in read_merged_cell_list:
        df[col_name] = df[col_name].ffill()  # 用前面的值填充

    # 本 sheet K 列是否出现过 "/"：有则 K 只应有 "/" 或橱窗 id；无则空白格正常沿用上一行橱窗 id
    k_col = df.iloc[:, shop_window_id_index]
    sheet_has_k_slash = any(
        not _is_k_cell_blank(v) and str(v).strip() == "/"
        for v in k_col
    )

    error_config_msg = []
    price_detail_cache = {}
    _admin_shopwindow_cache = {}  # 橱窗ID → admin shop-window/listnew 响应，避免同一橱窗重复请求

    headers = [str(c).strip() for c in list(df.columns)]
    exp_header_alias = {
        "体验价格": "体验价价格",
    }
    normalized_headers = [exp_header_alias.get(h, h) for h in headers]
    has_exp_columns = (
        len(normalized_headers) > max(exp_price_index, exp_cycle_index)
        and normalized_headers[exp_price_index] == "体验价价格"
        and normalized_headers[exp_cycle_index] == "体验价周期"
    )
    exp_pair_error_reported = set()
    exp_format_error_reported = set()

    def _get_price_detail_cached(price_id_value):
        try:
            pid = int(price_id_value)
        except (ValueError, TypeError):
            return {}
        if pid <= 0:
            return {}
        if pid not in price_detail_cache:
            price_detail_cache[pid] = get_price_detail_data_by_price_id(pid, cookie) or {}
        return price_detail_cache.get(pid) or {}

    def _validate_exp_for_row(
        index_inner: int,
        current_shop_window_id_inner,
        exp_price_cell_inner,
        exp_cycle_cell_inner,
        price_id_inner,
        result_dict_inner,
        current_product_info_inner,
    ):
        if not has_exp_columns:
            return
        has_exp_price = not _is_blank_cell(exp_price_cell_inner)
        has_exp_cycle = not _is_blank_cell(exp_cycle_cell_inner)
        if not has_exp_price and not has_exp_cycle:
            return
        if has_exp_price != has_exp_cycle:
            if index_inner in exp_pair_error_reported:
                return
            exp_pair_error_reported.add(index_inner)
            msg = (
                "第" + str(index_inner + 2)
                + "行的【体验价扩展列】填写不完整：L列体验价价格与M列体验价周期必须同时填写或同时留空"
                + "，当前 L=" + str(exp_price_cell_inner) + "，M=" + str(exp_cycle_cell_inner)
            )
            logger.error(msg)
            error_config_msg.append(msg)
            return

        try:
            excel_exp_price = round(float(exp_price_cell_inner), 2)
        except (ValueError, TypeError):
            if index_inner in exp_format_error_reported:
                return
            exp_format_error_reported.add(index_inner)
            msg = (
                "第" + str(index_inner + 2)
                + "行的【体验价价格】格式错误，期望数字（美元），实际: " + str(exp_price_cell_inner)
            )
            logger.error(msg)
            error_config_msg.append(msg)
            return

        excel_exp_cycle_norm = _normalize_cycle_text(exp_cycle_cell_inner)
        if not excel_exp_cycle_norm:
            if index_inner in exp_format_error_reported:
                return
            exp_format_error_reported.add(index_inner)
            msg = (
                "第" + str(index_inner + 2)
                + "行的【体验价周期】格式错误，支持示例：3天/3d/3D，实际: " + str(exp_cycle_cell_inner)
            )
            logger.error(msg)
            error_config_msg.append(msg)
            return

        detail = _get_price_detail_cached(price_id_inner)
        api_exp_price = None
        api_exp_cycle_norm = ""
        detail_first_exp_price_cents = None
        detail_first_exp_cycle = None
        detail_first_exp_unit = ""
        if detail:
            detail_first_exp_price_cents = detail.get("first_exp_price_usd")
            detail_first_exp_cycle = detail.get("first_exp_cycle")
            detail_first_exp_unit = detail.get("first_exp_unit")
            if detail_first_exp_price_cents not in [None, ""]:
                try:
                    api_exp_price = round(float(detail_first_exp_price_cents) / 100.0, 2)
                except (ValueError, TypeError):
                    api_exp_price = None
            api_exp_cycle_norm = _normalize_cycle_value_unit(detail_first_exp_cycle, detail_first_exp_unit)

        # 兜底：价格取 result_dict，周期取橱窗槽位 first_exp_info.duration
        if api_exp_price is None and isinstance(result_dict_inner, dict):
            first_exp_price_usd = result_dict_inner.get("first_exp_price_usd")
            if first_exp_price_usd not in [None, ""]:
                try:
                    api_exp_price = round(float(first_exp_price_usd), 2)
                except (ValueError, TypeError):
                    api_exp_price = None
        if not api_exp_cycle_norm:
            _, fallback_cycle_norm = _collect_exp_info_from_current_product_info(current_product_info_inner)
            api_exp_cycle_norm = fallback_cycle_norm

        if api_exp_price is None:
            if detail and detail_first_exp_price_cents in [0, "0", 0.0]:
                msg = (
                    "第" + str(index_inner + 2)
                    + "行的price_id-" + str(price_id_inner)
                    + "未配置体验价（first_exp_price_usd=0），但模板填写了【体验价价格】="
                    + str(excel_exp_price)
                    + "，对应商品橱窗id-" + str(current_shop_window_id_inner)
                )
            else:
                msg = (
                    "第" + str(index_inner + 2)
                    + "行无法从接口获取【体验价价格】（price_id=" + str(price_id_inner) + "）"
                    + "，橱窗id-" + str(current_shop_window_id_inner)
                )
            logger.error(msg)
            error_config_msg.append(msg)
        else:
            diff = abs(excel_exp_price - api_exp_price)
            if diff < EXP_PRICE_THRESHOLD:
                logger.info(
                    "第%s行的【体验价价格】校验通过, 单元格=%s, 接口=%s, 橱窗id=%s",
                    index_inner + 2, excel_exp_price, api_exp_price, current_shop_window_id_inner
                )
            else:
                msg = (
                    "第" + str(index_inner + 2)
                    + "行的【体验价价格】校验错误, 单元格: " + str(excel_exp_price)
                    + ", 接口: " + str(api_exp_price)
                    + ", 对应price_id-" + str(price_id_inner)
                    + ", 对应商品橱窗id-" + str(current_shop_window_id_inner)
                )
                logger.error(msg)
                error_config_msg.append(msg)

        if not api_exp_cycle_norm:
            if detail and (detail_first_exp_cycle in [None, 0, "0", 0.0] or not _norm_cycle_unit(detail_first_exp_unit)):
                msg = (
                    "第" + str(index_inner + 2)
                    + "行的price_id-" + str(price_id_inner)
                    + "未配置体验价周期（first_exp_cycle/first_exp_unit无效），但模板填写了【体验价周期】="
                    + str(excel_exp_cycle_norm)
                    + "，对应商品橱窗id-" + str(current_shop_window_id_inner)
                )
            else:
                msg = (
                    "第" + str(index_inner + 2)
                    + "行无法从接口获取【体验价周期】（price_id=" + str(price_id_inner) + "）"
                    + "，橱窗id-" + str(current_shop_window_id_inner)
                )
            logger.error(msg)
            error_config_msg.append(msg)
        elif api_exp_cycle_norm == excel_exp_cycle_norm:
            logger.info(
                "第%s行的【体验价周期】校验通过, 单元格=%s, 接口=%s, 橱窗id=%s",
                index_inner + 2, excel_exp_cycle_norm, api_exp_cycle_norm, current_shop_window_id_inner
            )
        else:
            msg = (
                "第" + str(index_inner + 2)
                + "行的【体验价周期】校验错误, 单元格: " + str(excel_exp_cycle_norm)
                + ", 接口: " + str(api_exp_cycle_norm)
                + ", 对应price_id-" + str(price_id_inner)
                + ", 对应商品橱窗id-" + str(current_shop_window_id_inner)
            )
            logger.error(msg)
            error_config_msg.append(msg)

    total_rows_for_progress = 0
    if only_row_numbers is not None:
        total_rows_for_progress = len([idx for idx in df.index if (idx + 2) in only_row_numbers])
    elif restart:
        if restart_end_index is not None:
            total_rows_for_progress = len([idx for idx in df.index if restart_index <= idx <= restart_end_index])
        else:
            total_rows_for_progress = len([idx for idx in df.index if idx == restart_index])
    else:
        total_rows_for_progress = len(df.index)
    processed_rows_for_progress = 0

    # 打印每一行数据
    coupon_shop_item_origin_product_id = 0
    coupon_shop_item_discount_product_id = 0
    coupon_shop_item_one_time_origin_product_id = 0
    coupon_shop_item_one_time_discount_product_id = 0
    previous_shop_window_id = 0
    _group_first_deal_discount = None
    _group_shop_window_id_for_deal = 0
    if restart:
        previous_shop_window_id = restart_shop_window_id
    for index, row in df.iterrows():
        # 仅跑指定行（Excel 行号 1-based，如 [16, 23] 只跑第16、23行）
        if only_row_numbers is not None:
            if (index + 2) not in only_row_numbers:
                # 非目标行：仅追踪橱窗组上下文和首优基础折扣，不做 API 校验
                _skip_row = row.tolist()
                _skip_k = _skip_row[shop_window_id_index] if shop_window_id_index < len(_skip_row) else None
                if not _is_k_cell_blank(_skip_k) and str(_skip_k).strip() != "/":
                    _skip_sw = get_each_line_shop_window_id(_skip_k, index, previous_shop_window_id, sheet_has_k_slash)
                    if isinstance(_skip_sw, int) and _skip_sw > 0:
                        previous_shop_window_id = _skip_sw
                _skip_pt = _normalize_price_type((_skip_row[price_type_index] or "").strip().replace("\n", "")) if price_type_index < len(_skip_row) else ""
                _skip_j = _skip_row[product_give_cycle_index] if product_give_cycle_index < len(_skip_row) else None
                _sf, _sr, _sv = _parse_first_discount(_skip_j)
                if _sf and _sv and _sr is not None and _skip_pt in _DEAL_PRICE_TYPES:
                    if previous_shop_window_id != _group_shop_window_id_for_deal:
                        _group_first_deal_discount = None
                        _group_shop_window_id_for_deal = previous_shop_window_id
                    _group_first_deal_discount = _sr
                continue
            logger.info("仅跑指定行模式：当前处理第" + str(index + 2) + "行")
        elif restart:
            if index < restart_index:
                continue
            # 若指定了 restart_end_index，则只处理 [restart_index, restart_end_index] 行后停止；否则只处理 restart_index 一行
            if restart_end_index is not None:
                if index > restart_end_index:
                    logger.info("已完成第" + str(restart_end_index + 2) + "行的校验，停止执行")
                    break
            else:
                if index > restart_index:
                    logger.info("已完成第" + str(restart_index + 2) + "行的校验，停止执行")
                    break

        # 数据格式：['T1', 'Pro\n', '原价', 1.0, '2年', 143.76, 5.99, 1530.0, 2800.0, '不带买赠', '支付页：3553', '支付页：3577', 3578]
        logger.warning("=================================================================")
        logger.info("开始第" + str(index + 2) + "行的数据检查, 橱窗id: " + str(previous_shop_window_id))
        processed_rows_for_progress += 1
        if callable(progress_callback):
            try:
                progress_callback(processed_rows_for_progress, total_rows_for_progress, index + 2)
            except Exception as _:
                pass
        current_row_data = row.tolist()
        current_row_exp_price = (
            current_row_data[exp_price_index]
            if has_exp_columns and exp_price_index < len(current_row_data)
            else None
        )
        current_row_exp_cycle = (
            current_row_data[exp_cycle_index]
            if has_exp_columns and exp_cycle_index < len(current_row_data)
            else None
        )

        # 先判断商品id，如果商品id为空，则直接跳过，不用往下走
        product_id_value = current_row_data[product_id_index]

        # 提取支付页，
        if product_id_value in [None, '', ' ', "商品id"] or pd.isna(product_id_value):
            logger.info("第" + str(index + 2) + "行未配置商品id，跳过")
            continue
        current_row_give_cycle_raw = current_row_data[product_give_cycle_index]
        has_first_discount, first_discount_rate, first_discount_valid = _parse_first_discount(current_row_give_cycle_raw)
        if has_first_discount and not first_discount_valid:
            msg = "第" + str(index + 2) + "行备注存在首优，但不存在具体首优折扣，跳过该行配置继续校验"
            logger.error(msg)
            error_config_msg.append(msg)
            continue
        if has_first_discount and first_discount_rate is not None:
            logger.info(
                "第" + str(index + 2) + "行命中首优折扣: "
                + str(round(first_discount_rate * 100, 2))
                + "%，总价/月均价按折后口径校验"
            )
        # 判定橱窗id
        current_shop_window_id_value = current_row_data[shop_window_id_index]
        is_k_slash = (
            current_shop_window_id_value not in [None, '', ' ']
            and not pd.isna(current_shop_window_id_value)
            and str(current_shop_window_id_value).strip() == "/"
        )
        if is_k_slash:
            # K列="/"：不依赖橱窗，根据 I 列商品 id 调 product/listnew 后走已有校验逻辑
            try:
                product_id_excel = int(current_row_data[product_id_index])
            except (ValueError, TypeError):
                logger.warning("第" + str(index + 2) + "行 K列=/ 但 I列商品id无效，跳过")
                continue
            product_item = get_product_by_id(product_id_excel, cookie)
            if not product_item:
                error_config_msg.append("第" + str(index + 2) + "行 K列=/ 时根据商品id " + str(product_id_excel) + " 拉取 product/listnew 失败或返回空，跳过")
                continue
            # 校验原则：以 API 为准。月均价 = 总价/(主周期月数+加赠月数)，加赠须来自 API（product/listnew 或价格详情），不能从表格 J 列取
            current_product_info = {"origin_item_info": product_item}
            current_country_name = current_row_data[country_index].strip()
            current_member_type = current_row_data[member_type_index].strip()
            price_type_name = _normalize_price_type((current_row_data[price_type_index] or "").strip().replace("\n", ""))
            if has_first_discount and first_discount_rate is not None:
                if price_type_name in _DEAL_PRICE_TYPES:
                    _group_first_deal_discount = first_discount_rate
                    _group_shop_window_id_for_deal = previous_shop_window_id
                if price_type_name in _RETAIN_PRICE_TYPES and _group_first_deal_discount is not None:
                    compound = 1 - (1 - _group_first_deal_discount) * (1 - first_discount_rate)
                    logger.info(
                        "第%s行挽回价首优复合折扣: 基础折扣%.1f%% x 挽回折扣%.1f%% = 等效%.1f%%",
                        index + 2, _group_first_deal_discount * 100,
                        first_discount_rate * 100, compound * 100,
                    )
                    first_discount_rate = compound
            excel_product_id = product_id_excel
            product_order = 0
            retain_id = 0
            coupon_id_str = "0"
            coupon_shop_item_origin_product_id = product_item.get("id") or product_id_excel
            coupon_shop_item_discount_product_id = 0
            coupon_shop_item_one_time_origin_product_id = 0
            coupon_shop_item_one_time_discount_product_id = 0
            current_item_parser = ShopItemNewParser(current_product_info)
            logger.info("第" + str(index + 2) + "行 K列=/，按商品id " + str(product_id_excel) + " 校验")
            try:
                result_dict = get_target_info_by_condition(
                    price_type_name, current_item_parser, cookie,
                    current_country_name, system, retain_id,
                    mod=mod, mock_country=mock_country,
                    product_order=product_order, excel_product_id=excel_product_id
                )
            except Exception as e:
                logger.error("第" + str(index + 2) + "行 K列=/ get_target_info_by_condition 异常: " + str(e))
                result_dict = {}
            if not result_dict:
                logger.warning("第" + str(index + 2) + "行 K列=/ get_target_info_by_condition 返回空，价格类型: " + price_type_name)
            # 兜底：当 result_dict 为空或 price_id/总价为 0 时，若本行配置了价格id，则通过星宿按价格id查询并继续校验
            need_fallback = (
                not result_dict
                or result_dict.get("price_id") in (0, None)
                or (result_dict.get("price_total", 0) == 0 and result_dict.get("price_avg", 0) == 0)
            )
            if need_fallback:
                current_row_price_id_raw = current_row_data[price_id_index]
                if current_row_price_id_raw not in [None, "", " "] and not pd.isna(current_row_price_id_raw):
                    try:
                        fallback_price_id = int(current_row_price_id_raw)
                        _, msg_list_fb = get_price_detail_by_price_id(fallback_price_id, cookie)
                        (
                            price_usd_fb,
                            price_usd_beauty_fb,
                            first_exp_price_usd_fb,
                            first_exp_price_usd_beauty_fb,
                            price_name_fb,
                        ) = get_price_beautiful_by_price_id(fallback_price_id, cookie)
                        period = product_item.get("period") or 0
                        period_unit = (str(product_item.get("period_unit") or "Y").strip().upper())[:1] or "Y"
                        give_cycle = product_item.get("give_cycle") or 0
                        give_unit = (str(product_item.get("give_unit") or "").strip().upper())[:1] if product_item.get("give_unit") else ""
                        main_cycle = get_cycle(int(period) if period is not None else 0, period_unit)
                        give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
                        total_cycle = main_cycle + give_cycle_months
                        price_avg_fb = (price_usd_fb / total_cycle) if total_cycle > 0 else 0
                        period_chinese = get_regular_time_expression_1(period_unit)
                        main_period_str_fb = str(period) + period_chinese
                        if give_cycle and give_unit:
                            give_unit_chinese = get_regular_time_expression(give_unit)
                            give_period_fb = "买赠" + str(give_cycle) + give_unit_chinese
                        else:
                            give_period_fb = ""
                        result_dict = {
                            "product_id": product_id_excel,
                            "price_id": fallback_price_id,
                            "msg_list": msg_list_fb,
                            "name_check_msg": None,
                            "price_total": price_usd_fb,
                            "price_avg": price_avg_fb,
                            "main_period": main_period_str_fb,
                            "give_period": give_period_fb,
                            "give_contents": product_item.get("give_contents") or "",
                            "price_usd": price_usd_fb,
                            "price_usd_beauty": price_usd_beauty_fb,
                            "price_name": price_name_fb,
                        }
                        logger.info(
                            "第" + str(index + 2) + "行 K列=/ 按价格id " + str(fallback_price_id) + " 星宿兜底查询成功，继续校验"
                        )
                    except (ValueError, TypeError) as e:
                        logger.warning("第" + str(index + 2) + "行 K列=/ 按价格id星宿兜底解析失败: " + str(e))
            if result_dict:
                try:
                    product_id = result_dict['product_id']
                    price_id = result_dict['price_id']
                    msg_list = result_dict['msg_list']
                    name_check_msg = result_dict['name_check_msg']
                    price_total = result_dict['price_total']
                    price_avg = result_dict['price_avg']
                    main_period = result_dict['main_period']
                    give_period = result_dict['give_period']
                    give_contents = result_dict['give_contents']
                    price_usd = result_dict['price_usd']
                    price_usd_beauty = result_dict['price_usd_beauty']
                    price_name = result_dict['price_name']
                except KeyError as e:
                    logger.error("第" + str(index + 2) + "行 K列=/ result_dict 缺少字段: " + str(e))
                    error_config_msg.append("第" + str(index + 2) + "行 K列=/ 价格解析失败，缺少字段: " + str(e))
                    continue
                price_list_item_k = get_price_list_item_by_price_id(price_id, cookie)
                is_installment_k = (price_list_item_k or {}).get("installment") is True
                current_row_product_id = current_row_data[product_id_index]
                current_row_price_id = current_row_data[price_id_index]
                current_row_price_total = current_row_data[total_price_index]
                current_row_price_avg = current_row_data[avg_price_index]
                current_row_cycle = current_row_data[cycle_index]
                current_row_give_cycle = current_row_data[product_give_cycle_index]
                price_total_for_compare = _apply_first_discount(price_total, first_discount_rate)
                price_avg_for_compare = _apply_first_discount(price_avg, first_discount_rate)
                price_usd_for_compare = _apply_first_discount(price_usd, first_discount_rate)
                api_main_cycle_months = _parse_excel_cycle_to_months(str(main_period).strip()) if main_period else None
                main_cycle_invalid = api_main_cycle_months is None or api_main_cycle_months <= 0
                if main_cycle_invalid:
                    msg = (
                        "第" + str(index + 2) + "行检测到接口主周期异常(main_cycle<=0)，"
                        + "接口主周期字段为: " + str(main_period)
                        + "。已跳过本行月均价校验，请核对接口 period/period_unit。 (K列=/)"
                    )
                    logger.warning(msg)
                    error_config_msg.append(msg)
                if name_check_msg:
                    msg = "第" + str(index + 2) + "行的【商品名称】非法字符校验错误: " + name_check_msg
                    logger.error(msg)
                    error_config_msg.append(msg)
                if msg_list:
                    logger.info("第" + str(index + 2) + "行的【商品三方价格名称】校验结果: " + "\n".join(msg_list))
                try:
                    current_row_product_id_int = int(current_row_product_id)
                    if current_row_product_id_int != product_id:
                        msg = "第" + str(index + 2) + "行的【商品id】校验错误,单元格: " + str(current_row_product_id_int) + ", 接口: " + str(product_id) + " (K列=/)"
                        logger.error(msg)
                        error_config_msg.append(msg)
                    else:
                        logger.info("第" + str(index + 2) + "行的【商品id】校验通过 (K列=/)")
                except ValueError:
                    error_config_msg.append("第" + str(index + 2) + "行商品id转换出错 (K列=/)")
                try:
                    if current_row_price_id not in [None, '', ' '] and not pd.isna(current_row_price_id):
                        current_row_price_id_int = int(current_row_price_id)
                        if current_row_price_id_int != price_id:
                            msg = "第" + str(index + 2) + "行的【价格id】校验错误,单元格: " + str(current_row_price_id_int) + ", 接口: " + str(price_id) + " (K列=/)"
                            logger.error(msg)
                            error_config_msg.append(msg)
                    else:
                        msg = "第" + str(index + 2) + "行未配置价格id (K列=/)"
                        logger.error(msg)
                        error_config_msg.append(msg)
                except ValueError:
                    error_config_msg.append("第" + str(index + 2) + "行价格id转换出错 (K列=/)")
                try:
                    if current_row_price_total not in [None, '', ' '] and not pd.isna(current_row_price_total):
                        current_row_price_total_float = round(float(current_row_price_total), 2)
                        if (is_installment_k or "分期" in price_type_name) and current_row_cycle not in [None, '', ' '] and not pd.isna(current_row_cycle):
                            excel_cycle_months = _parse_excel_cycle_to_months(str(current_row_cycle).strip())
                            if excel_cycle_months and excel_cycle_months > 0:
                                api_total_installment = round(price_usd_for_compare * excel_cycle_months, 2)
                                diff = abs(current_row_price_total_float - api_total_installment)
                            else:
                                diff = abs(current_row_price_total_float - price_usd_for_compare)
                        else:
                            diff = abs(current_row_price_total_float - price_usd_for_compare)
                        if diff >= threshold:
                            msg = "第" + str(index + 2) + "行的【总价】校验错误,单元格: " + str(current_row_price_total_float) + ", 接口: " + str(price_usd_for_compare) + " (K列=/)"
                            logger.error(msg)
                            error_config_msg.append(msg)
                        else:
                            logger.info("第" + str(index + 2) + "行的【总价】校验通过 (K列=/)")
                    else:
                        error_config_msg.append("第" + str(index + 2) + "行未配置总价 (K列=/)")
                except ValueError:
                    error_config_msg.append("第" + str(index + 2) + "行总价转换出错 (K列=/)")
                try:
                    if current_row_price_avg not in [None, '', ' '] and not pd.isna(current_row_price_avg):
                        if main_cycle_invalid:
                            logger.info("第" + str(index + 2) + "行已跳过【月均价】校验 (K列=/)，原因: 接口主周期异常(main_cycle<=0)")
                        else:
                            current_row_price_avg_float = round(float(current_row_price_avg), 2)
                            diff = abs(current_row_price_avg_float - price_avg_for_compare)
                            if diff >= threshold:
                                msg = "第" + str(index + 2) + "行的【月均价】校验错误,单元格: " + str(current_row_price_avg_float) + ", 接口: " + str(price_avg_for_compare) + " (K列=/)"
                                logger.error(msg)
                                error_config_msg.append(msg)
                            else:
                                logger.info("第" + str(index + 2) + "行的【月均价】校验通过 (K列=/)")
                    else:
                        error_config_msg.append("第" + str(index + 2) + "行未配置月均价 (K列=/)")
                except ValueError:
                    error_config_msg.append("第" + str(index + 2) + "行月均价转换出错 (K列=/)")
                if current_row_cycle in [None, '', ' '] or pd.isna(current_row_cycle):
                    error_config_msg.append("第" + str(index + 2) + "行未配置商品周期 (K列=/)")
                elif _cycle_cell_matches_api(str(current_row_cycle).strip(), str(main_period).strip()):
                    logger.info("第" + str(index + 2) + "行的【商品周期】校验通过 (K列=/)")
                elif (is_installment_k or "分期" in price_type_name) and main_period in ("1月", "1个月") and _parse_excel_cycle_to_months(str(current_row_cycle).strip()):
                    logger.info("第" + str(index + 2) + "行的【商品周期-分期】校验通过,单元格: " + str(current_row_cycle) + ", 接口: " + str(main_period) + " (K列=/)")
                else:
                    msg = "第" + str(index + 2) + "行的【商品周期】校验错误,单元格: " + str(current_row_cycle) + ", 接口: " + str(main_period) + " (K列=/)"
                    logger.error(msg)
                    error_config_msg.append(msg)
                api_give_months = _extract_give_months(give_period)
                _give_for_check = _strip_first_discount_text(current_row_give_cycle)
                if not _give_for_check:
                    if api_give_months > 0:
                        try:
                            product_id_for_msg = int(str(current_row_product_id).strip())
                        except (ValueError, TypeError):
                            product_id_for_msg = product_id
                        msg = "第" + str(index + 2) + "行商品" + str(product_id_for_msg) + "存在买赠月数" + str(api_give_months) + "月，未在商品备注体现 (K列=/)"
                        logger.error(msg)
                        error_config_msg.append(msg)
                    else:
                        logger.info("第" + str(index + 2) + "行未配置商品买赠信息，且接口无买赠配置，跳过 (K列=/)")
                else:
                    _cell_give = _give_for_check
                    _api_give = str(give_period).strip()
                    _give_ok = _give_cycle_matches_api(_cell_give, _api_give)
                    if not _give_ok:
                        msg = "第" + str(index + 2) + "行的【买赠周期】校验错误,单元格: " + str(current_row_give_cycle) + ", 接口: " + str(give_period) + " (K列=/)"
                        logger.error(msg)
                        error_config_msg.append(msg)
                    else:
                        logger.info("第" + str(index + 2) + "行的【买赠周期】校验通过 (K列=/)")

                _validate_exp_for_row(
                    index,
                    "/",
                    current_row_exp_price,
                    current_row_exp_cycle,
                    price_id,
                    result_dict,
                    current_product_info,
                )
            continue
        result_shop_window_id = get_each_line_shop_window_id(
            current_shop_window_id_value, index, previous_shop_window_id, sheet_has_k_slash
        )
        if isinstance(result_shop_window_id, list):
            shop_window_ids_for_row = result_shop_window_id
        else:
            shop_window_ids_for_row = [result_shop_window_id] if result_shop_window_id != 0 else []
        for _cur_shop_window_id in shop_window_ids_for_row:
            previous_shop_window_id = _cur_shop_window_id
            # 开始解析操作
            if previous_shop_window_id != 0:
                shop_window_parser = None
                # 说明有缓存过，则直接取出来用
                if shop_window_id_obj_dict.get(previous_shop_window_id):
                    logger.info("复用已有的橱窗" + str(previous_shop_window_id) + "信息")
                    cached_parser = shop_window_id_obj_dict[previous_shop_window_id]
                    if cached_parser.has_valid_shop_window():
                        shop_window_parser = cached_parser
                    else:
                        logger.warning(
                            "橱窗{}缓存对象为空，触发重新拉取。上一轮失败原因: {}".format(
                                str(previous_shop_window_id), getattr(cached_parser, "last_error_reason", "")
                            )
                        )
                else:
                    logger.info("发起新橱窗" + str(previous_shop_window_id) + "请求，并缓存")
                if shop_window_parser is None:
                    shop_window_parser = ShopWindowParser(previous_shop_window_id, mode=mod, mock_country=mock_country,
                                                          platform=system, is_uwp=is_uwp, cookie=cookie)
                    if shop_window_parser.has_valid_shop_window():
                        shop_window_id_obj_dict[previous_shop_window_id] = shop_window_parser
                    else:
                        # 避免缓存空对象导致后续行持续复用失败状态
                        shop_window_id_obj_dict.pop(previous_shop_window_id, None)
                # logger.info(previous_shop_window_id)
                # shop_window_parser = ShopWindowParser(previous_shop_window_id, mode=mod, mock_country=mock_country,
                #                                       platform=system, is_uwp=is_uwp)
                # logger.info("shopWindowParser: " + str(shop_window_parser))

                # 优惠券信息:如果有优惠券，则需要同时校对优惠券里面的商品id和原橱窗的商品是否完全一致
                # coupon_list是一定有值的，不配置的话均为0,0,0这种格式
                coupon_list = shop_window_parser.get_coupon_list()



                success_page_window_list = shop_window_parser.get_success_page_window_list()

                # 修复：优先从Excel当前行的K列读取挽回橱窗ID（格式：挽回：6187），如果当前行K列为空，再使用API的retain_id
                # 重要：直接读取当前行的K列原始值，不依赖合并单元格填充，确保每行都读取自己的K列值
                excel_retain_id = None
                # 直接读取当前行的K列值（使用iloc确保读取的是当前行的原始值）
                current_row_k_column_value = df.iloc[index, shop_window_id_index]
            
                # 检查当前行的K列是否包含"挽回"关键字
                if pd.notna(current_row_k_column_value) and current_row_k_column_value not in [None, '', ' ']:
                    try:
                        current_row_k_column_str = str(current_row_k_column_value)
                        if "挽回" in current_row_k_column_str:
                            match = re.search(r'\d+', current_row_k_column_str)
                            if match:
                                excel_retain_id = int(match.group())
                                logger.info("第" + str(index + 2) + "行从Excel K列（K" + str(index + 2) + "单元格）读取挽回橱窗ID: " + str(excel_retain_id))
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.warning("第" + str(index + 2) + "行解析挽回橱窗ID失败: " + str(e))
                        excel_retain_id = None
            
                # 优先使用Excel当前行的retain_id，如果当前行K列为空，再使用API的retain_id
                retain_id_from_api = shop_window_parser.get_retain_id()
                retain_id = excel_retain_id if excel_retain_id else retain_id_from_api
                if excel_retain_id:
                    logger.info("第" + str(index + 2) + "行使用Excel K" + str(index + 2) + "单元格的挽回橱窗ID: " + str(retain_id))
                elif retain_id_from_api:
                    logger.info("第" + str(index + 2) + "行K" + str(index + 2) + "单元格为空，使用API的挽回橱窗ID: " + str(retain_id))
                # 获取当前行商品的index
                product_order = int(current_row_data[product_order_index]) - 1
                coupon_shop_item = None
                # 获取对应的优惠券橱窗
                if coupon_list:
                    coupon_id_str = coupon_list[product_order]
                    # 说明有配置优惠券
                    if coupon_id_str != "0":
                        coupon_id = int(coupon_id_str)
                        coupon_shop_window_parser = ShopWindowParser(coupon_id, mode=mod, mock_country=mock_country,
                                                                     platform=system, is_uwp=is_uwp, cookie=cookie)
                        coupon_shop_items_list = coupon_shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                        # 获取第一个商品即可
                        try:
                            coupon_shop_item = coupon_shop_items_list[0]
                            coupon_shop_item_origin_product_id = 0
                            coupon_shop_item_discount_product_id = 0
                            coupon_shop_item_one_time_origin_product_id = 0
                            coupon_shop_item_one_time_discount_product_id = 0
                            if coupon_shop_item.get("origin_item_info"):
                                coupon_shop_item_origin_product_id = coupon_shop_item["origin_item_info"]["id"]
                            if coupon_shop_item.get("discount_origin_item_info"):
                                coupon_shop_item_discount_product_id = coupon_shop_item["discount_origin_item_info"]["id"]
                            if coupon_shop_item.get("one_time_origin_item_info"):
                                coupon_shop_item_one_time_origin_product_id = coupon_shop_item["one_time_origin_item_info"]["id"]
                            if coupon_shop_item.get("one_time_discount_item_info"):
                                coupon_shop_item_one_time_discount_product_id = coupon_shop_item["one_time_discount_item_info"]["id"]
                            logger.info("优惠券橱窗id: " + coupon_id_str + ", 优惠券原价id: " + str(
                                coupon_shop_item_origin_product_id) + ", 优惠券折扣价id: " + str(
                                coupon_shop_item_discount_product_id)
                                        + ", 一次性优惠券原价id: " + str(
                                coupon_shop_item_one_time_origin_product_id) + ", 一次性优惠券折扣价id: " + str(
                                coupon_shop_item_one_time_discount_product_id))
                        except IndexError:
                            logger.error("获取优惠券商品失败，优惠券橱窗id: " + coupon_id_str)
                else:
                    current_main_shop_window_list = shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                    if current_main_shop_window_list is None:
                        fail_reason = getattr(shop_window_parser, "last_error_reason", "")
                        msg = (
                            "第" + str(index + 2) + "行获取主橱窗商品列表失败，橱窗id: " + str(previous_shop_window_id)
                            + "，可能原因：橱窗不存在、API返回异常、或橱窗无商品数据"
                            + ("，失败详情: " + str(fail_reason) if fail_reason else "")
                        )
                        logger.error(msg)
                        error_config_msg.append(msg)
                        continue
                    if not isinstance(current_main_shop_window_list, list) or len(current_main_shop_window_list) == 0:
                        fail_reason = getattr(shop_window_parser, "last_error_reason", "")
                        msg = (
                            "第" + str(index + 2) + "行主橱窗商品列表为空，橱窗id: " + str(previous_shop_window_id)
                            + ("，失败详情: " + str(fail_reason) if fail_reason else "")
                        )
                        logger.error(msg)
                        error_config_msg.append(msg)
                        continue
                    try:
                        main_shop_item = current_main_shop_window_list[product_order]
                    except IndexError:
                        msg = (
                            "第" + str(index + 2) + "行主橱窗商品索引越界，橱窗id: " + str(previous_shop_window_id)
                            + "，商品索引: " + str(product_order)
                            + "，商品列表长度: " + str(len(current_main_shop_window_list))
                        )
                        logger.error(msg)
                        error_config_msg.append(msg)
                        continue

                    if main_shop_item:
                        if main_shop_item["origin_item_info"]:
                            coupon_shop_item_origin_product_id = main_shop_item["origin_item_info"]["id"]
                        if main_shop_item["discount_origin_item_info"]:
                            coupon_shop_item_discount_product_id = main_shop_item["discount_origin_item_info"]["id"]
                        if main_shop_item["one_time_origin_item_info"]:
                            coupon_shop_item_one_time_origin_product_id = main_shop_item["one_time_origin_item_info"]["id"]
                        if main_shop_item["one_time_discount_item_info"]:
                            coupon_shop_item_one_time_discount_product_id = main_shop_item["one_time_discount_item_info"][
                                "id"]
                    else:
                        coupon_shop_item_origin_product_id = 0 if main_shop_item is None else \
                            main_shop_item["origin_item_info"]["id"]
                        coupon_shop_item_discount_product_id = 0 if main_shop_item is None else \
                            main_shop_item["discount_origin_item_info"]["id"]
                        coupon_shop_item_one_time_origin_product_id = 0 if main_shop_item is None else \
                            main_shop_item["one_time_origin_item_info"]["id"]
                        coupon_shop_item_one_time_discount_product_id = 0 if main_shop_item is None else \
                            main_shop_item["one_time_discount_item_info"]["id"]

                price_type_name = _normalize_price_type(current_row_data[price_type_index].strip())
                if has_first_discount and first_discount_rate is not None:
                    if price_type_name in _DEAL_PRICE_TYPES:
                        _group_first_deal_discount = first_discount_rate
                        _group_shop_window_id_for_deal = previous_shop_window_id
                    if price_type_name in _RETAIN_PRICE_TYPES and _group_first_deal_discount is not None:
                        compound = 1 - (1 - _group_first_deal_discount) * (1 - first_discount_rate)
                        logger.info(
                            "第%s行挽回价首优复合折扣: 基础折扣%.1f%% x 挽回折扣%.1f%% = 等效%.1f%%",
                            index + 2, _group_first_deal_discount * 100,
                            first_discount_rate * 100, compound * 100,
                        )
                        first_discount_rate = compound

                success_page_window_info = None

                if system == "android" and "加购" in price_type_name and len(success_page_window_list) > 0:
                    success_page_window_item_id_str = success_page_window_list[product_order]
                    success_page_window_item_id = int(success_page_window_item_id_str)
                    success_page_window_parser = ShopWindowParser(success_page_window_item_id, mode=mod, mock_country=mock_country,
                                                                    platform=system, is_uwp=is_uwp, cookie=cookie)
                    success_page_window_items_list = success_page_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                    if success_page_window_items_list is None:
                        logger.error("第" + str(index + 2) + "行获取成功页橱窗商品列表失败，橱窗id: " + str(success_page_window_item_id) + "，可能原因：橱窗不存在、API返回异常、或橱窗无商品数据")
                        success_page_window_info = None
                    elif not isinstance(success_page_window_items_list, list) or len(success_page_window_items_list) == 0:
                        logger.error("第" + str(index + 2) + "行成功页橱窗商品列表为空，橱窗id: " + str(success_page_window_item_id))
                        success_page_window_info = None
                    else:
                        # 修复：通过商品ID匹配，而不是通过索引匹配
                        # 获取Excel中配置的商品ID
                        excel_product_id = None
                        try:
                            if pd.notna(current_row_data[product_id_index]) and current_row_data[product_id_index] not in [None, '', ' ', "商品id"]:
                                excel_product_id = int(current_row_data[product_id_index])
                        except (ValueError, TypeError) as e:
                            logger.warning("第" + str(index + 2) + "行商品ID转换失败，将使用索引匹配: " + str(e))
                            excel_product_id = None
                        success_page_window_info = None
                        if excel_product_id:
                            # 【修复】遍历所有商品，包括加购商品组，找到匹配的商品ID
                            for item in success_page_window_items_list:
                                # 检查主商品组中的各种商品类型
                                if item.get("origin_item_info") and item["origin_item_info"].get("id") == excel_product_id:
                                    success_page_window_info = item
                                    logger.info("第" + str(index + 2) + "行在成功页橱窗中找到匹配的商品ID: " + str(excel_product_id) + "（原价商品），橱窗id: " + str(success_page_window_item_id))
                                    break
                                if item.get("discount_origin_item_info") and item["discount_origin_item_info"].get("id") == excel_product_id:
                                    success_page_window_info = item
                                    logger.info("第" + str(index + 2) + "行在成功页橱窗中找到匹配的商品ID: " + str(excel_product_id) + "（折扣原价商品），橱窗id: " + str(success_page_window_item_id))
                                    break
                                if item.get("trial_item_info") and item["trial_item_info"].get("id") == excel_product_id:
                                    success_page_window_info = item
                                    logger.info("第" + str(index + 2) + "行在成功页橱窗中找到匹配的商品ID: " + str(excel_product_id) + "（试用商品），橱窗id: " + str(success_page_window_item_id))
                                    break
                                if item.get("discount_trial_item_info") and item["discount_trial_item_info"].get("id") == excel_product_id:
                                    success_page_window_info = item
                                    logger.info("第" + str(index + 2) + "行在成功页橱窗中找到匹配的商品ID: " + str(excel_product_id) + "（折扣试用商品），橱窗id: " + str(success_page_window_item_id))
                                    break
                                # 【修复】检查加购商品组
                                if item.get("add_buy_info") and isinstance(item["add_buy_info"], list):
                                    for add_buy_group in item["add_buy_info"]:
                                        if add_buy_group.get("origin_item_info") and add_buy_group["origin_item_info"].get("id") == excel_product_id:
                                            success_page_window_info = add_buy_group
                                            logger.info("第" + str(index + 2) + "行在成功页橱窗的加购商品组中找到匹配的商品ID: " + str(excel_product_id) + "（原价商品），橱窗id: " + str(success_page_window_item_id))
                                            break
                                        if add_buy_group.get("discount_origin_item_info") and add_buy_group["discount_origin_item_info"].get("id") == excel_product_id:
                                            success_page_window_info = add_buy_group
                                            logger.info("第" + str(index + 2) + "行在成功页橱窗的加购商品组中找到匹配的商品ID: " + str(excel_product_id) + "（折扣原价商品），橱窗id: " + str(success_page_window_item_id))
                                            break
                                        if add_buy_group.get("trial_item_info") and add_buy_group["trial_item_info"].get("id") == excel_product_id:
                                            success_page_window_info = add_buy_group
                                            logger.info("第" + str(index + 2) + "行在成功页橱窗的加购商品组中找到匹配的商品ID: " + str(excel_product_id) + "（试用商品），橱窗id: " + str(success_page_window_item_id))
                                            break
                                        if add_buy_group.get("discount_trial_item_info") and add_buy_group["discount_trial_item_info"].get("id") == excel_product_id:
                                            success_page_window_info = add_buy_group
                                            logger.info("第" + str(index + 2) + "行在成功页橱窗的加购商品组中找到匹配的商品ID: " + str(excel_product_id) + "（折扣试用商品），橱窗id: " + str(success_page_window_item_id))
                                            break
                                    if success_page_window_info:
                                        break
                        
                            if success_page_window_info is None:
                                logger.error("第" + str(index + 2) + "行，商品" + str(excel_product_id) + "不在成功页橱窗" + str(success_page_window_item_id) + "的商品列表中")
                        else:
                            # 如果Excel中没有商品ID，回退到使用索引匹配（兼容旧逻辑）
                            try:
                                success_page_window_info = success_page_window_items_list[product_order]
                            except IndexError:
                                logger.error("第" + str(index + 2) + "行成功页橱窗商品索引越界，橱窗id: " + str(success_page_window_item_id) + "，商品索引: " + str(product_order) + "，商品列表长度: " + str(len(success_page_window_items_list)))
                                success_page_window_info = None

                # iOS 系（ios/ipad）才需要单独处理加购逻辑
                add_buy_item = None
                if _is_ios_like_platform(system):
                    add_buy_id_list = shop_window_parser.get_add_buy_list()
                    # 获取对应的优惠券橱窗
                    if add_buy_id_list:
                        add_buy_id_str = add_buy_id_list[product_order]
                        # 说明有配置优惠券
                        if add_buy_id_str != "0":
                            add_buy_window_id = int(add_buy_id_str)
                            add_buy_shop_window_parser = ShopWindowParser(add_buy_window_id, mode=mod,
                                                                          mock_country=mock_country, platform=system,
                                                                          is_uwp=is_uwp, cookie=cookie)
                            add_buy_items_list = add_buy_shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                            # 获取第一个商品即可
                            if add_buy_items_list is None:
                                logger.error("第" + str(index + 2) + "行获取加购橱窗商品列表失败，加购橱窗id: " + str(add_buy_window_id) + "，可能原因：橱窗不存在、API返回异常、或橱窗无商品数据")
                                add_buy_item = None
                            elif not isinstance(add_buy_items_list, list) or len(add_buy_items_list) == 0:
                                logger.error("第" + str(index + 2) + "行加购橱窗商品列表为空，加购橱窗id: " + str(add_buy_window_id))
                                add_buy_item = None
                            else:
                                try:
                                    add_buy_item = add_buy_items_list[0]
                                except IndexError:
                                    logger.error("第" + str(index + 2) + "行获取iOS加购配置失败，加购橱窗id: " + str(add_buy_window_id) + "，商品列表长度: " + str(len(add_buy_items_list)))
                                    add_buy_item = None
                                # coupon_shop_item_origin_product_id = coupon_shop_item["origin_item_info"]["id"]
                                # coupon_shop_item_discount_product_id = coupon_shop_item["discount_origin_item_info"]["id"]
                                # if "one_time_origin_item_info" in coupon_shop_item:
                                #     coupon_shop_item_one_time_origin_product_id = coupon_shop_item["one_time_origin_item_info"][
                                #         "id"]
                                # if "one_time_discount_item_info" in coupon_shop_item:
                                #     coupon_shop_item_one_time_discount_product_id = \
                                #     coupon_shop_item["one_time_discount_item_info"][
                                #         "id"]
                                # logger.info("优惠券橱窗id: " + coupon_id_str + ", 优惠券原价id: " + str(
                                #     coupon_shop_item_origin_product_id) + ", 优惠券折扣价id: " + str(
                                #     coupon_shop_item_discount_product_id)
                                #             + ", 一次性优惠券原价id: " + str(
                                #     coupon_shop_item_one_time_origin_product_id) + ", 一次性优惠券折扣价id: " + str(
                                #     coupon_shop_item_one_time_discount_product_id))
                    # else:
                    #     coupon_shop_item_origin_product_id = 0
                    #     coupon_shop_item_discount_product_id = 0
                    #     coupon_shop_item_one_time_origin_product_id = 0
                    #     coupon_shop_item_one_time_discount_product_id = 0

                # 商品列表
                shop_items_list = shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                # 提取对应的索引的商品
                if shop_items_list is None:
                    msg = "第" + str(index + 2) + "行获取商品列表失败，商品橱窗: " + str(
                        previous_shop_window_id) + "，可能原因：橱窗不存在、API返回异常、或橱窗无商品数据，跳过后续操作，请检查"
                    logger.error(msg)
                    error_config_msg.append(msg)
                    continue
                if not isinstance(shop_items_list, list) or len(shop_items_list) == 0:
                    msg = "第" + str(index + 2) + "行商品列表为空，商品橱窗: " + str(previous_shop_window_id) + "，跳过后续操作，请检查"
                    logger.error(msg)
                    error_config_msg.append(msg)
                    continue
            
                # 【修复】优先通过商品ID匹配，支持从主商品组和加购商品组中查找
                excel_product_id = None
                try:
                    if pd.notna(current_row_data[product_id_index]) and current_row_data[product_id_index] not in [None, '', ' ', "商品id"]:
                        excel_product_id = int(current_row_data[product_id_index])
                except (ValueError, TypeError) as e:
                    logger.warning("第" + str(index + 2) + "行商品ID转换失败，将使用索引匹配: " + str(e))
                    excel_product_id = None
            
                current_product_info = None
                matched_slot = None  # 在橱窗数组中找到商品id时所在的槽位，用于按槽位取价
                matched_slot_by_period = False  # 本行是否按「与Excel周期一致」选中的槽位（未匹配时用首槽位可能为长周期导致月均价极小，易误报）
                if excel_product_id:
                    # 当前行价格类型：只在对应槽位中匹配，避免原价行取到折扣价槽位（总价/周期不同）导致月均价误报
                    price_type_name_row = _normalize_price_type((current_row_data[price_type_index] or "").strip().replace("\n", ""))
                    slots_to_try = _SLOTS_BY_PRICE_TYPE.get(price_type_name_row) if price_type_name_row else None
                    if not slots_to_try:
                        slots_to_try = _ALL_MATCH_SLOTS
                    # 当前行 Excel 周期、买赠，用于同商品多周期/多买赠时优先匹配一致，月均价=总价/(主周期月数+加赠月数) 才能对上
                    current_row_cycle_raw = current_row_data[cycle_index]
                    current_row_cycle_for_match = (str(current_row_cycle_raw).strip() if current_row_cycle_raw not in [None, '', ' '] and not pd.isna(current_row_cycle_raw) else None)
                    current_row_give_raw = current_row_data[product_give_cycle_index]
                    current_row_give_for_match = (str(current_row_give_raw).strip() if current_row_give_raw not in [None, '', ' '] and not pd.isna(current_row_give_raw) else None)
                    # 从橱窗数组（主商品组+加购组）收集匹配该商品id且槽位符合本行价格类型的 (container, slot)，再按周期+加赠优先选取
                    candidates = _collect_matching_candidates(shop_items_list, slots_to_try, excel_product_id)
                    # 兜底1：若当前价格类型槽位未命中，放宽为全槽位再试一次（应对价格类型映射差异/脏数据）
                    if not candidates and slots_to_try != _ALL_MATCH_SLOTS:
                        candidates = _collect_matching_candidates(shop_items_list, _ALL_MATCH_SLOTS, excel_product_id)
                        if candidates:
                            logger.warning(
                                "第" + str(index + 2) + "行商品ID " + str(excel_product_id)
                                + " 未在价格类型槽位命中，已回退到全槽位命中，橱窗id: " + str(previous_shop_window_id)
                            )
                    # 兜底2：刷新橱窗后再匹配（应对橱窗缓存与后台配置短暂不一致）
                    if not candidates:
                        try:
                            latest_shop_window_parser = ShopWindowParser(
                                previous_shop_window_id,
                                mode=mod,
                                mock_country=mock_country,
                                platform=system,
                                is_uwp=is_uwp,
                                cookie=cookie,
                            )
                            latest_shop_items = latest_shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                            if isinstance(latest_shop_items, list) and latest_shop_items:
                                refreshed = _collect_matching_candidates(latest_shop_items, _ALL_MATCH_SLOTS, excel_product_id)
                                if refreshed:
                                    candidates = refreshed
                                    shop_items_list = latest_shop_items
                                    shop_window_id_obj_dict[previous_shop_window_id] = latest_shop_window_parser
                                    logger.warning(
                                        "第" + str(index + 2) + "行商品ID " + str(excel_product_id)
                                        + " 在刷新橱窗后命中，橱窗id: " + str(previous_shop_window_id)
                                    )
                        except Exception as e:
                            logger.warning("第" + str(index + 2) + "行刷新橱窗重试失败: " + str(e))
                    if candidates:
                        # 优先选与 Excel 主周期一致的槽位；若有多条同主周期且本行有加赠备注，再优先选加赠一致的（月均价=总价/(主+赠) 才与单元格对上）
                        chosen = None
                        if current_row_cycle_for_match:
                            main_matched = [
                                (c, s) for c, s in candidates
                                if _cycle_cell_matches_api(current_row_cycle_for_match, _item_main_period_str(c.get(s)))
                            ]
                            if main_matched and current_row_give_for_match:
                                _cell_core = current_row_give_for_match.replace("加赠", "").replace("买赠", "").strip()
                                for container, slot in main_matched:
                                    item = container.get(slot)
                                    api_give = _item_give_period_str(item) if item else ""
                                    _api_core = api_give.replace("买赠", "").replace("加赠", "").strip() if api_give else ""
                                    if _api_core and _cell_core and (_api_core in _cell_core or _cell_core in _api_core):
                                        chosen = (container, slot)
                                        matched_slot_by_period = True
                                        logger.info("第" + str(index + 2) + "行按商品ID " + str(excel_product_id) + " 匹配到与Excel周期+加赠一致槽位: " + slot + "，周期: " + current_row_cycle_for_match + "，加赠: " + current_row_give_for_match + "，橱窗id: " + str(previous_shop_window_id))
                                        break
                            if chosen is None and main_matched:
                                # Excel 未填加赠时优先选「无加赠」槽位，月均价=总价/主周期 才与单元格一致，避免取到 1年+加赠1月 导致 总价/13 误报
                                if not current_row_give_for_match:
                                    no_give = [(c, s) for c, s in main_matched if not _item_give_period_str(c.get(s))]
                                    if no_give:
                                        chosen = no_give[0]
                                        matched_slot_by_period = True
                                        logger.info("第" + str(index + 2) + "行按商品ID " + str(excel_product_id) + " 匹配到与Excel周期一致且无加赠槽位: " + chosen[1] + "，周期: " + current_row_cycle_for_match + "，橱窗id: " + str(previous_shop_window_id))
                                    else:
                                        # 所有主周期匹配都有加赠时，按「总价/主周期」最接近单元格月均价的槽位选取，避免取到 39.91/13 而表格填 59.88/12
                                        try:
                                            cell_avg = float(current_row_data[avg_price_index])
                                            cell_avg = round(cell_avg, 2)
                                        except (ValueError, TypeError):
                                            cell_avg = None
                                        if cell_avg is not None:
                                            best_diff = None
                                            for container, slot in main_matched:
                                                try:
                                                    parser = ShopItemNewParser(container)
                                                    method_name = _SLOT_TO_GET_METHOD.get(slot)
                                                    if not method_name:
                                                        continue
                                                    rd = getattr(parser, method_name)(cookie)
                                                    if not rd or not isinstance(rd, dict):
                                                        continue
                                                    pt = rd.get("price_total") or 0
                                                    mp = (rd.get("main_period") or "")
                                                    mc = _parse_excel_cycle_to_months(str(mp).strip()) if mp else None
                                                    if not mc or mc <= 0:
                                                        continue
                                                    expected_avg = round(pt / mc, 2)
                                                    d = abs(expected_avg - cell_avg)
                                                    if best_diff is None or d < best_diff:
                                                        best_diff = d
                                                        chosen = (container, slot)
                                                except Exception as e:
                                                    logger.debug("第" + str(index + 2) + "行候选槽位取价失败 " + str(slot) + ": " + str(e))
                                                    continue
                                            if chosen is not None:
                                                matched_slot_by_period = True
                                                logger.info("第" + str(index + 2) + "行按商品ID " + str(excel_product_id) + " 按总价/主周期最接近单元格月均价选取槽位: " + chosen[1] + "，橱窗id: " + str(previous_shop_window_id))
                                if chosen is None:
                                    chosen = main_matched[0]
                                    matched_slot_by_period = True
                                    logger.info("第" + str(index + 2) + "行按商品ID " + str(excel_product_id) + " 匹配到与Excel周期一致槽位: " + chosen[1] + "，周期: " + current_row_cycle_for_match + "，橱窗id: " + str(previous_shop_window_id))
                        if chosen is None:
                            chosen = candidates[0]
                            logger.info("第" + str(index + 2) + "行在主/加购商品组中找到匹配的商品ID: " + str(excel_product_id) + "（槽位: " + chosen[1] + "），橱窗id: " + str(previous_shop_window_id))
                        current_product_info, matched_slot = chosen[0], chosen[1]
                    if current_product_info is None:
                        # ---- 2级兜底：后台 shop-window/listnew，获取槽位信息 ----
                        _admin_slot = None
                        if excel_product_id and previous_shop_window_id:
                            _sw_key = int(previous_shop_window_id)
                            if _sw_key not in _admin_shopwindow_cache:
                                _admin_shopwindow_cache[_sw_key] = get_shopwindow_admin_detail(_sw_key, cookie)
                            _admin_data = _admin_shopwindow_cache.get(_sw_key)
                            if _admin_data:
                                _admin_slot = find_product_slot_in_admin(_admin_data, excel_product_id)
                        if _admin_slot and excel_product_id:
                            _fallback_product = get_product_by_id(excel_product_id, cookie)
                            if _fallback_product:
                                current_product_info = {_admin_slot: _fallback_product}
                                matched_slot = _admin_slot
                                logger.warning(
                                    "第%s行商品%s未在橱窗%s的 pay_window 响应中匹配到，"
                                    "已通过后台 shop-window/listnew 确认槽位: %s，继续校验",
                                    str(index + 2), str(excel_product_id),
                                    str(previous_shop_window_id), _admin_slot
                                )
                        # ---- 3级兜底：product/listnew 验证商品存在 ----
                        if current_product_info is None:
                            _fallback_product = get_product_by_id(excel_product_id, cookie) if excel_product_id else None
                            if _fallback_product:
                                current_product_info = {"origin_item_info": _fallback_product}
                                _fb_msg = (
                                    "第" + str(index + 2) + "行的【商品橱窗匹配】校验警告,商品"
                                    + str(excel_product_id) + "未在橱窗" + str(previous_shop_window_id)
                                    + "的任何槽位中找到(pay_window及后台shop-window均无匹配),"
                                    + "该商品在product/listnew中存在,请确认橱窗配置是否正确"
                                )
                                logger.warning(_fb_msg)
                                error_config_msg.append(_fb_msg)
                            else:
                                msg = (
                                    "第" + str(index + 2) + "行，商品" + str(excel_product_id)
                                    + "未在橱窗" + str(previous_shop_window_id)
                                    + "匹配到，且 product/listnew 二次验证也未找到该商品，请核对橱窗配置或商品id"
                                )
                                logger.error(msg)
                                error_config_msg.append(msg)
                                continue
                else:
                    # 如果Excel中没有商品ID，回退到使用索引匹配（兼容旧逻辑）
                    try:
                        current_product_info = shop_items_list[product_order]
                    except IndexError:
                        msg = "第" + str(index + 2) + "行商品配置越界，商品橱窗: " + str(
                            previous_shop_window_id) + "-商品索引: " + str(product_order) + "，商品列表长度: " + str(len(shop_items_list)) + "，跳过后续操作，请配置请检查"
                        logger.error(msg)
                        error_config_msg.append(msg)
                        continue

                if matched_slot is not None:
                    if system == "android" and "加购" in price_type_name and success_page_window_info is not None:
                        current_product_info = success_page_window_info

                    if system == "android" and "折扣价" in price_type_name and coupon_shop_item is not None:
                        current_product_info = coupon_shop_item
                    if _is_ios_like_platform(system) and "加购" in price_type_name and add_buy_item is not None:
                        current_product_info = add_buy_item
                else:
                    _fb_data = current_product_info.get("origin_item_info") if current_product_info else None
                    if _fb_data:
                        _target_slots = _SLOTS_BY_PRICE_TYPE.get(price_type_name)
                        if _target_slots and _target_slots[0] != "origin_item_info":
                            current_product_info = {_target_slots[0]: _fb_data}
                            logger.debug(
                                "第%s行3级兜底：将 origin_item_info 数据重映射到 %s 槽位（价格类型: %s）",
                                str(index + 2), _target_slots[0], price_type_name
                            )
                current_item_parser = ShopItemNewParser(current_product_info)
                # logger.info("shopItemNewParser: " + str(current_item_parser))
                current_country_name = current_row_data[country_index].strip()
                current_member_type = current_row_data[member_type_index].strip()
                logger.debug("第" + str(index + 2) + "行价格类型: " + price_type_name + ", 平台: " + system + ", 国家: " + current_country_name)
                # 获取Excel中配置的商品ID，用于挽回价格匹配
                excel_product_id = None
                try:
                    if pd.notna(current_row_data[product_id_index]) and current_row_data[product_id_index] not in [None, '', ' ', "商品id"]:
                        excel_product_id = int(current_row_data[product_id_index])
                except (ValueError, TypeError):
                    excel_product_id = None
            
                result_dict = {}
                last_exception = None
                max_retries = int(RETRY_CONFIG.get("max_retries", 3))
                retry_delay = float(RETRY_CONFIG.get("retry_delay", 1.0))
                backoff_factor = float(RETRY_CONFIG.get("backoff_factor", 2.0))
                current_delay = retry_delay
                for attempt in range(max_retries + 1):
                    try:
                        candidate = get_target_info_by_condition(
                            price_type_name, current_item_parser, cookie,
                            current_country_name, system, retain_id, mod=mod, mock_country=mock_country,
                            product_order=product_order, excel_product_id=excel_product_id,
                            matched_slot=matched_slot
                        )
                        if candidate:
                            result_dict = candidate
                            break
                        if attempt < max_retries:
                            logger.warning(
                                "第%s行get_target_info_by_condition返回空字典，价格类型: %s, 平台: %s，准备第%s次重试，延迟%.2f秒",
                                str(index + 2), price_type_name, system, str(attempt + 1), current_delay
                            )
                            time.sleep(current_delay)
                            current_delay *= backoff_factor
                    except Exception as e:
                        last_exception = e
                        if attempt < max_retries:
                            logger.warning(
                                "第%s行get_target_info_by_condition执行异常，价格类型: %s, 平台: %s，准备第%s次重试，延迟%.2f秒，错误: %s",
                                str(index + 2), price_type_name, system, str(attempt + 1), current_delay, str(e)
                            )
                            time.sleep(current_delay)
                            current_delay *= backoff_factor
                        else:
                            logger.error(
                                "第%s行get_target_info_by_condition执行异常（重试后仍失败），价格类型: %s, 平台: %s, 错误: %s",
                                str(index + 2), price_type_name, system, str(e)
                            )
                            logger.exception("get_target_info_by_condition异常详情:")
                if not result_dict:
                    if last_exception is not None:
                        msg = (
                            "第" + str(index + 2)
                            + "行get_target_info_by_condition执行异常（已重试" + str(max_retries) + "次后失败），价格类型: "
                            + price_type_name + ", 平台: " + system + ", 错误: " + str(last_exception)
                        )
                    else:
                        msg = (
                            "第" + str(index + 2)
                            + "行get_target_info_by_condition返回空字典（已重试" + str(max_retries) + "次后仍为空），价格类型: "
                            + price_type_name + ", 平台: " + system
                        )
                    logger.error(msg)
                    error_config_msg.append(msg)
                    continue
                # 兜底：当 result_dict 非空但 price_id/总价为 0 时（橱窗槽位缺 sku_id 或按 sku_id 查不到价格），若本行配置了价格id，则按价格id星宿兜底
                need_fallback = (
                    result_dict
                    and (
                        result_dict.get("price_id") in (0, None)
                        or (result_dict.get("price_total", 0) == 0 and result_dict.get("price_avg", 0) == 0)
                    )
                )
                if need_fallback:
                    current_row_price_id_raw = current_row_data[price_id_index]
                    if current_row_price_id_raw not in [None, "", " "] and not pd.isna(current_row_price_id_raw):
                        try:
                            fallback_price_id = int(current_row_price_id_raw)
                            _, msg_list_fb = get_price_detail_by_price_id(fallback_price_id, cookie)
                            (
                                price_usd_fb,
                                price_usd_beauty_fb,
                                first_exp_price_usd_fb,
                                first_exp_price_usd_beauty_fb,
                                price_name_fb,
                            ) = get_price_beautiful_by_price_id(fallback_price_id, cookie)
                            product_item = None
                            if matched_slot and current_product_info.get(matched_slot):
                                product_item = current_product_info[matched_slot]
                            else:
                                for key in _ALL_MATCH_SLOTS:
                                    if current_product_info.get(key):
                                        product_item = current_product_info[key]
                                        break
                            if product_item is None:
                                product_item = {}
                            period = product_item.get("period") or 0
                            period_unit = (str(product_item.get("period_unit") or "Y").strip().upper())[:1] or "Y"
                            give_cycle = product_item.get("give_cycle") or 0
                            give_unit = (str(product_item.get("give_unit") or "").strip().upper())[:1] if product_item.get("give_unit") else ""
                            main_cycle = get_cycle(int(period) if period is not None else 0, period_unit)
                            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
                            total_cycle = main_cycle + give_cycle_months
                            price_avg_fb = (price_usd_fb / total_cycle) if total_cycle > 0 else 0
                            period_chinese = get_regular_time_expression_1(period_unit)
                            main_period_str_fb = str(period) + period_chinese
                            if give_cycle and give_unit:
                                give_unit_chinese = get_regular_time_expression(give_unit)
                                give_period_fb = "买赠" + str(give_cycle) + give_unit_chinese
                            else:
                                give_period_fb = ""
                            result_dict = {
                                "product_id": result_dict.get("product_id") or excel_product_id,
                                "price_id": fallback_price_id,
                                "msg_list": msg_list_fb or result_dict.get("msg_list") or [],
                                "name_check_msg": result_dict.get("name_check_msg") or "",
                                "price_total": price_usd_fb,
                                "price_avg": price_avg_fb,
                                "main_period": main_period_str_fb,
                                "give_period": give_period_fb,
                                "give_contents": product_item.get("give_contents") or "",
                                "price_usd": price_usd_fb,
                                "price_usd_beauty": price_usd_beauty_fb,
                                "price_name": price_name_fb,
                                "first_exp_price_usd": first_exp_price_usd_fb,
                                "first_exp_price_usd_beauty": first_exp_price_usd_beauty_fb,
                            }
                            if result_dict.get("product_id") is None:
                                result_dict["product_id"] = excel_product_id
                            logger.info("第" + str(index + 2) + "行按价格id " + str(fallback_price_id) + " 星宿兜底查询成功（橱窗取价接口返回0），继续校验")
                        except (ValueError, TypeError) as e:
                            logger.warning("第" + str(index + 2) + "行按价格id星宿兜底解析失败: " + str(e))
                if result_dict:
                    try:
                        product_id = result_dict['product_id']
                        price_id = result_dict['price_id']
                        msg_list = result_dict['msg_list']
                        name_check_msg = result_dict['name_check_msg']
                        price_total = result_dict['price_total']
                        price_avg = result_dict['price_avg']
                        main_period = result_dict['main_period']
                        give_period = result_dict['give_period']
                        give_contents = result_dict['give_contents']
                        price_usd = result_dict['price_usd']
                        price_usd_beauty = result_dict['price_usd_beauty']
                        price_name = result_dict['price_name']
                    except KeyError as e:
                        logger.error("第" + str(index + 2) + "行result_dict缺少必要字段: " + str(e) + ", result_dict keys: " + str(list(result_dict.keys())))
                        error_config_msg.append("第" + str(index + 2) + "行价格类型解析失败，缺少必要字段: " + str(e))
                        continue
                    except Exception as e:
                        logger.error("第" + str(index + 2) + "行解析result_dict异常: " + str(e))
                        logger.exception("解析result_dict异常详情:")
                        error_config_msg.append("第" + str(index + 2) + "行价格类型解析失败: " + str(e))
                        continue

                    # 有商品 id 时优先用 product/listnew 直接算月均价（总价/周期，无加赠=总价/主周期），与表格口径一致，避免橱窗多槽位取错
                    product_item_for_avg = None
                    if excel_product_id:
                        if matched_slot is None and current_product_info and current_product_info.get("origin_item_info"):
                            product_item_for_avg = current_product_info["origin_item_info"]
                        else:
                            product_item_for_avg = get_product_by_id(excel_product_id, cookie)
                        if product_item_for_avg and isinstance(product_item_for_avg, dict) and product_item_for_avg.get("amount") is not None:
                            _pt, _mc, _gc, _pa = _price_avg_from_product_item(product_item_for_avg)
                            # 保护条件：
                            # 1) product/listnew 主周期必须可识别（_mc>0），避免主周期缺失时被误算为“仅按加赠周期”
                            # 2) 若 Excel 周期可解析，要求与 product/listnew 主周期一致，避免覆盖正确的橱窗槽位口径
                            current_row_cycle_raw_for_avg = current_row_data[cycle_index]
                            excel_cycle_months_for_avg = None
                            if current_row_cycle_raw_for_avg not in [None, '', ' '] and not pd.isna(current_row_cycle_raw_for_avg):
                                excel_cycle_months_for_avg = _parse_excel_cycle_to_months(str(current_row_cycle_raw_for_avg).strip())
                            can_override_from_product = (
                                _pa is not None
                                and _mc is not None
                                and _mc > 0
                                and (
                                    excel_cycle_months_for_avg is None
                                    or excel_cycle_months_for_avg <= 0
                                    or _mc == excel_cycle_months_for_avg
                                )
                            )
                            if can_override_from_product:
                                price_avg = _pa
                                if _pt is not None:
                                    price_total = _pt
                                    price_usd = _pt
                                # product/listnew 在部分月价场景会返回更贴近运营配置的 price_id（如 *_upgrade）
                                # 当它与 Excel 填写一致时，同步覆盖 price_id/main_period，避免“总价通过但价格ID/周期误报”
                                product_price_id_raw = product_item_for_avg.get("price_id")
                                if product_price_id_raw not in [None, "", " "]:
                                    try:
                                        product_price_id = int(str(product_price_id_raw).strip())
                                        excel_price_id = None
                                        excel_price_id_raw = current_row_data[price_id_index]
                                        if excel_price_id_raw not in [None, "", " "] and not pd.isna(excel_price_id_raw):
                                            excel_price_id = int(str(excel_price_id_raw).strip())
                                        if excel_price_id is not None and product_price_id == excel_price_id:
                                            prev_price_id = price_id
                                            price_id = product_price_id
                                            product_main_period = _item_main_period_str(product_item_for_avg)
                                            if product_main_period:
                                                main_period = product_main_period
                                            if prev_price_id != price_id:
                                                logger.info(
                                                    "第%s行使用 product/listnew 返回的 price_id 覆盖橱窗取价口径：%s -> %s（价格类型: %s）",
                                                    index + 2, prev_price_id, price_id, price_type_name
                                                )
                                    except (ValueError, TypeError):
                                        logger.debug("第%s行 product/listnew 的 price_id 无法解析，跳过覆盖", index + 2)
                                logger.info("第" + str(index + 2) + "行使用商品id " + str(excel_product_id) + " 的 product/listnew 数据校验月均价/总价: 月均价=" + str(price_avg) + " (总价/周期)")
                            else:
                                logger.warning(
                                    "第%s行跳过 product/listnew 月均价覆盖：_mc=%s, _gc=%s, _pa=%s, excel_cycle_months=%s（继续使用橱窗槽位口径）",
                                    index + 2, _mc, _gc, _pa, excel_cycle_months_for_avg
                                )

                    # 通过 price/list?ids=xxx 接口确认是否分期（返回 installment=true 则为分期）
                    # 注意：需在可能的 price_id 覆盖之后再判断，确保分期口径与价格ID校验一致
                    price_list_item = get_price_list_item_by_price_id(price_id, cookie)
                    is_installment = (price_list_item or {}).get("installment") is True

                    current_row_product_id = current_row_data[product_id_index]
                    current_row_price_id = current_row_data[price_id_index]
                    current_row_price_total = current_row_data[total_price_index]
                    current_row_price_avg = current_row_data[avg_price_index]
                    current_row_cycle = current_row_data[cycle_index]

                    current_row_give_cycle = current_row_data[product_give_cycle_index]
                    price_total_for_compare = _apply_first_discount(price_total, first_discount_rate)
                    price_avg_for_compare = _apply_first_discount(price_avg, first_discount_rate)
                    price_usd_for_compare = _apply_first_discount(price_usd, first_discount_rate)
                    first_exp_price_usd_for_compare = _apply_first_discount(result_dict.get('first_exp_price_usd', 0), first_discount_rate)
                    api_main_cycle_months = _parse_excel_cycle_to_months(str(main_period).strip()) if main_period else None
                    main_cycle_invalid = api_main_cycle_months is None or api_main_cycle_months <= 0
                    if main_cycle_invalid:
                        msg = (
                            "第" + str(index + 2) + "行检测到接口主周期异常(main_cycle<=0)，"
                            + "接口主周期字段为: " + str(main_period)
                            + "。已跳过本行月均价校验，请核对接口 period/period_unit。"
                        )
                        logger.warning(msg)
                        error_config_msg.append(msg)
                    if name_check_msg == "":
                        logger.info("第" + str(index + 2) + "行的【商品名称】非法字符校验通过")
                    else:
                        msg = "第" + str(index + 2) + "行的【商品名称】非法字符校验错误: " + name_check_msg
                        logger.error(msg)
                        error_config_msg.append(msg)
                    if msg_list:
                        logger.info("第" + str(index + 2) + "行的【商品三方价格名称】校验结果: " + "\n".join(msg_list))

                    try:
                        if current_row_product_id in [None, '', ' '] or pd.isna(current_row_product_id):
                            msg = "第" + str(index + 2) + "行未配置商品id信息, 对应商品序号-" + str(
                                product_order) + ", 对应商品橱窗id-" + str(previous_shop_window_id)
                            logger.error(msg)
                            error_config_msg.append(msg)
                        else:
                            current_row_product_id_int = int(current_row_product_id)
                            if current_row_product_id_int == product_id:
                                logger.info("第" + str(index + 2) + "行的【商品id】校验通过,单元格中值为: " + str(
                                    current_row_product_id_int) + ", 接口中的值为: " + str(product_id))
                            else:
                                msg = "第" + str(index + 2) + "行的【商品id】校验错误,单元格中值为: " + str(
                                    current_row_product_id_int) + ", 接口中的值为: " + str(
                                    product_id) + ", 对应商品橱窗id-" + str(previous_shop_window_id)
                                logger.error(msg)
                                error_config_msg.append(msg)
                    except ValueError as e:
                        msg = "第" + str(index + 2) + "行的【商品id】转换出错, 对应商品橱窗id-" + str(
                            previous_shop_window_id) + ", 请检查: " + str(e)
                        logger.error(msg)
                        error_config_msg.append(msg)
                    try:
                        if current_row_price_id in [None, '', ' '] or pd.isna(current_row_price_id):
                            msg = "第" + str(index + 2) + "行未配置价格id信息, 对应商品橱窗id-" + str(
                                previous_shop_window_id)
                            logger.error(msg)
                            error_config_msg.append(msg)
                        else:
                            current_row_price_id_int = int(current_row_price_id)
                            if current_row_price_id_int == price_id:
                                logger.info("第" + str(index + 2) + "行的【价格id】校验通过,单元格中值为: " + str(
                                    current_row_price_id_int) + ", 接口中的值为: " + str(price_id))
                            else:
                                msg = "第" + str(index + 2) + "行的【价格id】校验错误,单元格中值为: " + str(
                                    current_row_price_id_int) + ", 接口中的值为: " + str(
                                    price_id) + ", 对应商品橱窗id-" + str(previous_shop_window_id)
                                logger.error(msg)
                                error_config_msg.append(msg)
                    except ValueError as e:
                        msg = "第" + str(index + 2) + "行的【价格id】转换出错，" + ", 对应商品橱窗id-" + str(
                            previous_shop_window_id) + ",请检查: " + str(e)
                        logger.error(msg)
                        error_config_msg.append(msg)
                    try:
                        if current_row_price_total in [None, '', ' '] or pd.isna(current_row_price_total):
                            msg = "第" + str(index + 2) + "行未配置商品总价信息, 对应商品橱窗id-" + str(
                                previous_shop_window_id)
                            logger.error(msg)
                            error_config_msg.append(msg)
                        else:
                            current_row_price_total_float = float(current_row_price_total)
                            current_row_price_total_float = round(current_row_price_total_float, 2)

                            # 仅当价格类型为「体验价」时，才用体验价/first_exp 相关字段做总价校验；非体验价用 price_usd/分期，避免误报
                            if price_type_name == "体验价" and result_dict.get('price_total', 0) > 0:
                                # 体验价使用price_total字段（已修复为使用first_exp_info.amount）
                                diff = abs(current_row_price_total_float - price_total_for_compare)
                                if diff < PRICE_THRESHOLD:
                                    msg = f"第{index + 2}行的【总价-体验价】校验通过,单元格中值为: {current_row_price_total_float}, 接口中的值为: {price_total_for_compare}, 对应参考展示价(US)为: {result_dict.get('first_exp_price_usd_beauty', 'N/A')}"
                                    logger.info(msg)
                                else:
                                    msg = f"第{index + 2}行的【总价-体验价】校验错误,单元格中值为: {current_row_price_total_float}, 接口中的值为: {price_total_for_compare}, 对应参考展示价(US)为: {result_dict.get('first_exp_price_usd_beauty', 'N/A')}, 对应商品id-{product_id}, 对应商品橱窗id-{previous_shop_window_id}"
                                    logger.error(msg)
                                    error_config_msg.append(msg)
                            elif price_type_name == "体验价" and result_dict.get('first_exp_price_usd', 0) > 0:
                                # 体验价且 price_total 未用上时，用 first_exp_price_usd 校验
                                diff = abs(current_row_price_total_float - first_exp_price_usd_for_compare)
                                if diff < PRICE_THRESHOLD:
                                    msg = f"第{index + 2}行的【总价-体验价】校验通过,单元格中值为: {current_row_price_total_float}, 接口中的值为: {first_exp_price_usd_for_compare}, 对应参考展示价(US)为: {result_dict['first_exp_price_usd_beauty']}"
                                    logger.info(msg)
                                else:
                                    msg = f"第{index + 2}行的【总价-体验价】校验错误,单元格中值为: {current_row_price_total_float}, 接口中的值为: {first_exp_price_usd_for_compare}, 对应参考展示价(US)为: {result_dict['first_exp_price_usd_beauty']}, 对应商品id-{product_id}, 对应商品橱窗id-{previous_shop_window_id}"
                                    logger.error(msg)
                                    error_config_msg.append(msg)
                            elif (is_installment or "分期" in price_type_name) and current_row_cycle not in [None, '', ' '] and not pd.isna(current_row_cycle):
                                # 分期：接口返回的为月单价，总价 = 月单价 × 订阅周期（按 Excel 周期换算月数）；is_installment 来自 price/list 接口
                                excel_cycle_months = _parse_excel_cycle_to_months(str(current_row_cycle).strip())
                                if excel_cycle_months and excel_cycle_months > 0:
                                    api_total_installment = round(price_usd_for_compare * excel_cycle_months, 2)
                                    diff = abs(current_row_price_total_float - api_total_installment)
                                    if diff < threshold:
                                        logger.info("第" + str(index + 2) + "行的【总价-分期】校验通过,单元格总价: " + str(
                                            current_row_price_total_float) + ", 接口月单价×周期月数: " + str(
                                            price_usd_for_compare) + "×" + str(excel_cycle_months) + "=" + str(api_total_installment))
                                    else:
                                        msg = ("第" + str(index + 2) + "行的【总价】校验错误(分期),单元格中值为: " + str(
                                            current_row_price_total_float) + ", 接口月单价×订阅周期月数: " + str(
                                            price_usd_for_compare) + "×" + str(excel_cycle_months) + "=" + str(api_total_installment)
                                               + ", 对应商品id-" + str(current_row_product_id_int) + ", 对应商品橱窗id-" + str(previous_shop_window_id))
                                        logger.error(msg)
                                        error_config_msg.append(msg)
                                else:
                                    diff = abs(current_row_price_total_float - price_usd_for_compare)
                                    if diff < threshold:
                                        logger.info("第" + str(index + 2) + "行的【总价】校验通过,单元格中值为: " + str(
                                            current_row_price_total_float) + ", 接口中的值为: " + str(price_usd_for_compare))
                                    else:
                                        msg = ("第" + str(index + 2) + "行的【总价】校验错误,单元格中值为: " + str(
                                            current_row_price_total_float) + ", 接口中的值为: " + str(price_usd_for_compare)
                                               + ", 对应商品id-" + str(current_row_product_id_int) + ", 对应商品橱窗id-" + str(previous_shop_window_id))
                                        logger.error(msg)
                                        error_config_msg.append(msg)
                            else:
                                diff = abs(current_row_price_total_float - price_usd_for_compare)
                                if diff < threshold:
                                    logger.info("第" + str(index + 2) + "行的【总价】校验通过,单元格中值为: " + str(
                                        current_row_price_total_float) + ", 接口中的值为: " + str(
                                        price_usd_for_compare) + ", 对应参考展示价(US)为: " + str(price_usd_beauty))
                                else:
                                    msg = ("第" + str(index + 2) + "行的【总价】校验错误,单元格中值为: " + str(
                                        current_row_price_total_float) + ", 接口中的值为: " + str(
                                        price_usd_for_compare) + ", 对应参考展示价(US)为: " + str(price_usd_beauty)
                                           + ", 对应商品id-" + str(current_row_product_id_int) + ", 对应商品橱窗id-" + str(
                                                previous_shop_window_id))
                                    logger.error(msg)
                                    error_config_msg.append(msg)
                    except ValueError as e:
                        msg = "第" + str(index + 2) + "行的商品【总价】转换出错, 对应商品id-" + str(
                            current_row_product_id_int) + ", 对应商品橱窗id-" + str(
                            previous_shop_window_id) + ". 请检查: " + str(e)
                        logger.error(msg)
                        error_config_msg.append(msg)
                    try:
                        if current_row_price_avg in [None, '', ' '] or pd.isna(current_row_price_avg):
                            msg = "第" + str(index + 2) + "行未配置商品均价信息, 对应商品橱窗id-" + str(
                                previous_shop_window_id)
                            logger.error(msg)
                            error_config_msg.append(msg)
                        elif main_cycle_invalid:
                            logger.info("第" + str(index + 2) + "行已跳过【月均价】校验，原因: 接口主周期异常(main_cycle<=0)")
                        else:
                            current_row_price_avg_float = float(current_row_price_avg)
                            current_row_price_avg_float = round(current_row_price_avg_float, 2)

                            diff = abs(current_row_price_avg_float - price_avg_for_compare)
                            if diff < threshold:
                                logger.info("第" + str(index + 2) + "行的【月均价】校验通过,单元格中值为: " + str(
                                    current_row_price_avg_float) + ", 接口中的值为: " + str(price_avg_for_compare))
                            else:
                                # Excel 未填加赠且接口有加赠时：表格常用「总价/主周期」口径，接口为「总价/(主+赠)」，按主周期口径再比一次
                                current_row_give_cycle = current_row_data[product_give_cycle_index]
                                excel_give_blank = current_row_give_cycle in [None, '', ' '] or pd.isna(current_row_give_cycle)
                                api_has_give = give_period and str(give_period).strip()
                                main_cycle_months = _parse_excel_cycle_to_months(str(main_period).strip()) if main_period else None
                                use_main_only_ok = (
                                    excel_give_blank and api_has_give and main_cycle_months and main_cycle_months > 0
                                    and abs(current_row_price_avg_float - round(price_total_for_compare / main_cycle_months, 2)) < threshold
                                )
                                if use_main_only_ok:
                                    logger.info("第" + str(index + 2) + "行的【月均价】校验通过(按主周期口径),单元格: " + str(
                                        current_row_price_avg_float) + ", 接口总价/主周期: " + str(round(price_total_for_compare / main_cycle_months, 2)) + ", 接口总价/(主+赠): " + str(price_avg_for_compare))
                                else:
                                    # 接口月均价≈1/240 等异常小时，多为未匹配到与Excel周期一致的槽位、取到了长周期(如20年)槽位导致误报
                                    if not matched_slot_by_period and price_avg_for_compare < 0.02 and current_row_price_avg_float >= 0.5:
                                        msg = "第" + str(index + 2) + "行未匹配到与Excel周期一致的槽位，接口月均价(" + str(price_avg_for_compare) + ")可能来自长周期槽位，请核对橱窗是否配置该商品对应周期后再比对月均价，对应商品id-" + str(current_row_product_id_int) + "，橱窗id-" + str(previous_shop_window_id)
                                        logger.warning(msg)
                                        error_config_msg.append(msg)
                                    else:
                                        msg = "第" + str(index + 2) + "行的【月均价】校验错误,单元格中值为: " + str(
                                            current_row_price_avg_float) + ", 接口中的值为: " + str(
                                            price_avg_for_compare) + ", 对应商品id-" + str(
                                            current_row_product_id_int) + ", 对应商品橱窗id-" + str(previous_shop_window_id)
                                        logger.error(msg)
                                        error_config_msg.append(msg)
                    except ValueError as e:
                        msg = "第" + str(index + 2) + "行的商品【月均价】转换出错, 对应商品id-" + str(
                            current_row_product_id_int) + ", 对应商品橱窗id-" + str(
                            previous_shop_window_id) + ". 请检查: " + str(e)
                        logger.error(msg)
                        error_config_msg.append(msg)
                    if current_row_cycle in [None, '', ' '] or pd.isna(current_row_cycle):
                        msg = "第" + str(index + 2) + "行的【商品周期】未配置, 对应商品id-" + str(
                            current_row_product_id_int) + ", 对应商品橱窗id-" + str(previous_shop_window_id)
                        logger.error(msg)
                        error_config_msg.append(msg)
                    elif _cycle_cell_matches_api(str(current_row_cycle).strip(), str(main_period).strip()):
                        logger.info("第" + str(index + 2) + "行的【商品周期】校验通过,单元格中值为: " + str(
                            current_row_cycle) + ", 接口中的值为: " + str(main_period))
                    elif (is_installment or "分期" in price_type_name) and main_period in ("1月", "1个月") and _parse_excel_cycle_to_months(str(current_row_cycle).strip()):
                        # 分期：接口多为 1月（计费周期），Excel 填 1年 等为订阅总周期，用于算总价，二者语义不同均视为有效；is_installment 来自 price/list 接口
                        logger.info("第" + str(index + 2) + "行的【商品周期-分期】校验通过,单元格: " + str(
                            current_row_cycle) + ", 接口(计费周期): " + str(main_period))
                    else:
                        msg = "第" + str(index + 2) + "行的【商品周期】校验错误,单元格中值为: " + str(
                            current_row_cycle) + ", 接口中的值为: " + str(main_period) + ", 对应商品id-" + str(
                            current_row_product_id_int) + ", 对应商品橱窗id-" + str(previous_shop_window_id)
                        logger.error(msg)
                        error_config_msg.append(msg)

                    _give_for_check = _strip_first_discount_text(current_row_give_cycle)
                    if not _give_for_check:
                        api_give_months = _extract_give_months(give_period)
                        if api_give_months > 0:
                            try:
                                product_id_for_msg = int(str(current_row_product_id).strip())
                            except (ValueError, TypeError):
                                product_id_for_msg = product_id
                            msg = "第" + str(index + 2) + "行商品" + str(product_id_for_msg) + "存在买赠月数" + str(api_give_months) + "月，未在商品备注体现"
                            logger.error(msg)
                            error_config_msg.append(msg)
                        else:
                            logger.info("第" + str(index + 2) + "行未配置商品买赠信息，跳过")
                    else:
                        _cell_give = _give_for_check
                        _api_give = str(give_period).strip()
                        _give_ok = _give_cycle_matches_api(_cell_give, _api_give)
                        if _give_ok:
                            logger.info("第" + str(index + 2) + "行的【买赠周期】校验正确,单元格中值为: " + str(
                                current_row_give_cycle)
                                        + ", 接口中的值为: " + str(give_period) + ", 价格名称: " + price_name)
                            logger.info("第" + str(index + 2) + "行的【买赠周期】校验正确, 接口中的买赠权益值为: " + str(give_contents) + ", 配置的商品权益为: " + current_member_type)
                        else:
                            msg = ("第" + str(index + 2) + "行的【买赠周期】校验错误,单元格中值为: " + str(
                                current_row_give_cycle) + ", 接口中的值为: " + str(
                                give_period) + ", 价格名称: " + price_name
                                   + ", 对应商品id-" + str(current_row_product_id_int) + ", 对应商品橱窗id-" + str(
                                        previous_shop_window_id))
                            logger.error(msg)
                            error_config_msg.append(msg)

                    _validate_exp_for_row(
                        index,
                        previous_shop_window_id,
                        current_row_exp_price,
                        current_row_exp_cycle,
                        price_id,
                        result_dict,
                        current_product_info,
                    )

                    # 优惠券与原橱窗校验：仅当配置开启时执行（默认关，仅做：橱窗id→商品id→价格id→总价/月均价/周期等）
                    if CHECK_COUPON_WITH_SHOP_WINDOW:
                        if "原价" == price_type_name:
                            if coupon_id_str == "0":
                                logger.info("第" + str(index + 2) + "行未配置优惠券橱窗")
                            elif coupon_shop_item_origin_product_id == current_row_product_id_int:
                                logger.info(
                                    "第" + str(index + 2) + "行的【优惠券与原橱窗-原价商品】校验正确, 原橱窗原价id: " + str(
                                        current_row_product_id_int) + ", 优惠券原价id: " + str(
                                        coupon_shop_item_origin_product_id))
                            else:
                                msg = "第" + str(index + 2) + "行的【优惠券与原橱窗-原价商品】校验错误,  原橱窗原价id: " + str(
                                    current_row_product_id_int) + ", 优惠券原价id: " + str(coupon_shop_item_origin_product_id)
                                logger.error(msg)
                                error_config_msg.append(msg)
                        if "折扣价" == price_type_name:
                            if coupon_id_str == "0":
                                logger.info("第" + str(index + 2) + "行未配置优惠券橱窗")
                            elif coupon_shop_item_discount_product_id == current_row_product_id_int:
                                logger.info(
                                    "第" + str(index + 2) + "行的【优惠券与原橱窗-折扣价商品】校验正确, 原橱窗折扣价id: " + str(
                                        current_row_product_id_int) + ", 优惠券折扣价id: " + str(
                                        coupon_shop_item_discount_product_id))
                            else:
                                msg = "第" + str(index + 2) + "行的【优惠券与原橱窗-折扣价商品】校验错误, 原橱窗折扣价id: " + str(
                                    current_row_product_id_int) + ", 优惠券折扣价id: " + str(
                                    coupon_shop_item_discount_product_id)
                                logger.error(msg)
                                error_config_msg.append(msg)

                        if "一次性原价" == price_type_name:
                            if coupon_id_str == "0":
                                logger.info("第" + str(index + 2) + "行未配置优惠券橱窗")
                            elif coupon_shop_item_one_time_origin_product_id == current_row_product_id_int:
                                logger.info(
                                    "第" + str(index + 2) + "行的【一次性优惠券与原橱窗-原价商品】校验正确, 原橱窗原价id: " + str(
                                        current_row_product_id_int) + ", 优惠券原价id: " + str(
                                        coupon_shop_item_one_time_origin_product_id))
                            else:
                                msg = "第" + str(
                                    index + 2) + "行的【一次性优惠券与原橱窗-原价商品】校验错误,  原橱窗原价id: " + str(
                                    current_row_product_id_int) + ", 优惠券原价id: " + str(
                                    coupon_shop_item_one_time_origin_product_id)
                                logger.error(msg)
                                error_config_msg.append(msg)
                        if "一次性折扣价" == price_type_name:
                            if current_country_name == "印度":
                                if "原价" in price_type_name:
                                    if coupon_id_str == "0":
                                        logger.info("第" + str(index + 2) + "行未配置优惠券橱窗")
                                    elif coupon_shop_item_origin_product_id == current_row_product_id_int:
                                        logger.info("第" + str(
                                            index + 2) + "行的【优惠券与原橱窗-原价商品】校验正确, 原橱窗原价id: " + str(
                                            current_row_product_id_int) + ", 优惠券原价id: " + str(
                                            coupon_shop_item_origin_product_id))
                                    else:
                                        msg = "第" + str(
                                            index + 2) + "行的【优惠券与原橱窗-原价商品】校验错误,  原橱窗原价id: " + str(
                                            current_row_product_id_int) + ", 优惠券原价id: " + str(
                                            coupon_shop_item_origin_product_id)
                                        logger.error(msg)
                                        error_config_msg.append(msg)
                                if "折扣价" in price_type_name:
                                    if coupon_id_str == "0":
                                        logger.info("第" + str(index + 2) + "行未配置优惠券橱窗")
                                    elif coupon_shop_item_discount_product_id == current_row_product_id_int:
                                        logger.info("第" + str(
                                            index + 2) + "行的【优惠券与原橱窗-折扣价商品】校验正确, 原橱窗折扣价id: " + str(
                                            current_row_product_id_int) + ", 优惠券折扣价id: " + str(
                                            coupon_shop_item_discount_product_id))
                                    else:
                                        msg = "第" + str(
                                            index + 2) + "行的【优惠券与原橱窗-折扣价商品】校验错误, 原橱窗折扣价id: " + str(
                                            current_row_product_id_int) + ", 优惠券折扣价id: " + str(
                                            coupon_shop_item_discount_product_id)
                                        logger.error(msg)
                                        error_config_msg.append(msg)
                            else:
                                if coupon_id_str == "0":
                                    logger.info("第" + str(index + 2) + "行未配置优惠券橱窗")
                                elif coupon_shop_item_one_time_discount_product_id == current_row_product_id_int:
                                    logger.info("第" + str(
                                        index + 2) + "行的【一次性优惠券与原橱窗-折扣价商品】校验正确, 原橱窗折扣价id: " + str(
                                        current_row_product_id_int) + ", 优惠券折扣价id: " + str(
                                        coupon_shop_item_one_time_discount_product_id))
                                else:
                                    msg = "第" + str(
                                        index + 2) + "行的【一次性优惠券与原橱窗-折扣价商品】校验错误, 原橱窗折扣价id: " + str(
                                        current_row_product_id_int) + ", 优惠券折扣价id: " + str(
                                    coupon_shop_item_one_time_discount_product_id)
                                logger.error(msg)
                                error_config_msg.append(msg)

            else:
                logger.error("第" + str(index + 2) + "行未命中配置价格类型检查，请检查")

        if shop_window_ids_for_row:
            previous_shop_window_id = shop_window_ids_for_row[-1]

    if is_auth_login_required_suspected():
        logger.warning("命中多次「请先登录」，判定为 cookie 失效场景，错误列表收敛为单条提醒")
        return ["cookie已失效@刘幸全"]

    return error_config_msg


def _split_content_for_bot(full_content: str, max_length: int = BOT_MSG_MAX_LENGTH):
    """按 max_length 将文本分段，按行切分不打断单行。返回分段后的字符串列表。"""
    if not full_content:
        return []
    if len(full_content) <= max_length:
        return [full_content]
    chunks = []
    lines = full_content.split("\n")
    current = []
    for line in lines:
        candidate = "\n".join(current) + ("\n" if current else "") + line
        if len(candidate) > max_length and current:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _is_all_shop_window_empty_case(error_msg_list: list) -> bool:
    """是否为“所有橱窗返回空”场景（用于精简 Bot 通知文案）。"""
    if not error_msg_list:
        return False

    marker_msgs = {"no shop_window was found"}
    core_errors = [
        str(msg).strip()
        for msg in error_msg_list
        if str(msg).strip() and str(msg).strip() not in marker_msgs
    ]
    if not core_errors:
        return False

    return all(
        (
            "橱窗" in msg
            and (
                "获取主橱窗商品列表失败" in msg
                or "商品列表为空，商品橱窗" in msg
            )
            and (
                "response data is empty" in msg
                or "无商品数据" in msg
                or "商品列表为空" in msg
            )
        )
        for msg in core_errors
    )


def send_check_error_msg_bot(
        error_msg_list: list,
        file_path: str,
        index: int,
        task_id: str = "",
        initiator: str = "",
        platform: str = "",
        debug_only: bool = False,
):
    try:
        logger.info("准备发送校验结果到Bot，错误数量: " + str(len(error_msg_list) if error_msg_list else 0))
        excel_file = pd.ExcelFile(file_path)

        # 获取所有 sheet 名称  <at email=\"your-email@example.com\">同事A</at>
        sheet_names = excel_file.sheet_names
        sheet_name = sheet_names[index]
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        task_prefix = f"[{task_id}] " if task_id else ""
        initiator_prefix = (initiator or "").strip()
        platform_norm = str(platform or "").strip().lower() or "unknown"
        all_shop_window_empty = _is_all_shop_window_empty_case(error_msg_list)

        if error_msg_list and all_shop_window_empty:
            if initiator_prefix and task_id:
                full_content = (
                    f"{initiator_prefix}，你发起的{task_id}已完成：不通过，共{len(error_msg_list)}项。"
                    f"该任务所有橱窗信息返回空，平台参数是{platform_norm}，请确认是否与业务一致"
                )
            elif task_id:
                full_content = (
                    f"{task_id}已完成：不通过，共{len(error_msg_list)}项。"
                    f"该任务所有橱窗信息返回空，平台参数是{platform_norm}，请确认是否与业务一致"
                )
            else:
                full_content = (
                    f"任务已完成：不通过，共{len(error_msg_list)}项。"
                    f"该任务所有橱窗信息返回空，平台参数是{platform_norm}，请确认是否与业务一致"
                )
            logger.info("命中全橱窗返回空场景，使用精简Bot文案推送")
        else:
            if initiator_prefix and task_id:
                if error_msg_list:
                    summary = f"{initiator_prefix}，你发起的{task_id}已完成：不通过，共{len(error_msg_list)}项。\n不通过项如下：\n"
                else:
                    summary = f"{initiator_prefix}，你发起的{task_id}已完成：通过。\n"
            elif initiator_prefix:
                if error_msg_list:
                    summary = f"{initiator_prefix}，你发起的任务已完成：不通过，共{len(error_msg_list)}项。\n不通过项如下：\n"
                else:
                    summary = f"{initiator_prefix}，你发起的任务已完成：通过。\n"
            else:
                summary = ""
            if error_msg_list:
                full_content = summary + task_prefix + sheet_name + "-" + time_str + " sku校验结果: \n" + "\n".join(error_msg_list) + "\n"
            else:
                full_content = summary + task_prefix + sheet_name + "-" + time_str + " sku校验结果: \n" + "未检测出错误结果，well done\n"

        chunks = _split_content_for_bot(full_content)
        bot_targets = debug_bot_urls if debug_only else msg_bot_urls
        if not bot_targets:
            logger.warning("未配置可用Bot webhook，跳过消息推送。debug_only=%s", debug_only)
            return
        try:
            logger.info(
                "开始发送校验结果到Bot...（模式: %s，共 %s 个机器人，%s 段）",
                "debug_only" if debug_only else "normal",
                len(bot_targets),
                len(chunks),
            )
            for webhook in bot_targets:
                logger.debug("Bot Webhook URL: " + webhook)
                for i, content in enumerate(chunks):
                    msg_body = {"msgtype": "text", "text": {"content": content}}
                    response = requests.post(webhook, json=msg_body, timeout=BOT_TIMEOUT)
                    logger.info(
                        "Bot[" + webhook[-12:] + "]消息第 " + str(i + 1) + "/" + str(len(chunks))
                        + " 段发送完成，状态码: " + str(response.status_code)
                    )
                    if response.status_code != 200:
                        logger.warning("Bot消息发送返回非200状态码: " + str(response.status_code) + ", 响应内容: " + response.text[:200])
        except requests.exceptions.Timeout:
            logger.warning("Bot消息发送超时，跳过")
        except Exception as e:
            logger.warning("Bot消息发送失败: " + str(e))
            logger.exception("Bot消息发送异常详情:")  # 打印完整异常堆栈
    except Exception as e:
        logger.error("send_check_error_msg_bot函数执行异常: " + str(e))
        logger.exception("send_check_error_msg_bot异常详情:")  # 打印完整异常堆栈


def get_target_info_by_condition(price_type_name_inner: str, current_item_parser_inner: ShopItemNewParser,
                                 cookie: str, country: str, system: str, retain_id: int, **kwargs) -> dict:
    system = str(system or "pc").strip().lower()
    result_dict = {}
    # 橱窗路径下从数组找到匹配商品id时传入 matched_slot，优先按槽位取价（保证与橱窗配置一致）
    # 例外：体验价不按槽位取价，必须走 get_exp_price_new，否则会取到原价/折扣价或错误商品，导致接口值 0.05 等错误
    matched_slot = kwargs.get("matched_slot")
    if matched_slot and matched_slot in _SLOT_TO_GET_METHOD and price_type_name_inner != "体验价":
        method_name = _SLOT_TO_GET_METHOD[matched_slot]
        result_dict = getattr(current_item_parser_inner, method_name)(cookie)
        return result_dict
    if price_type_name_inner == "原价":
        result_dict = current_item_parser_inner.get_origin_price_new(cookie)
    # 划线价、盲盒1M AI价、盲盒1M Bundle价：K列=/ 时无橱窗，与原价同源（同一 price_id / 同一商品）
    if price_type_name_inner == "划线价":
        result_dict = current_item_parser_inner.get_origin_price_new(cookie)
    if price_type_name_inner == "盲盒1M AI价":
        result_dict = current_item_parser_inner.get_origin_price_new(cookie)
    if price_type_name_inner == "盲盒1M Bundle价":
        result_dict = current_item_parser_inner.get_origin_price_new(cookie)
    # 运营标识：K列有橱窗id时按橱窗匹配商品id后走折扣价校验
    if price_type_name_inner in ["盲盒3M Pro价", "盲盒10% OFF Coupon价", "盲盒1M Pro Gift Card价"]:
        result_dict = current_item_parser_inner.get_discount_price_new(cookie)
    if price_type_name_inner in ["体验价", "折扣价体验价"]:
        result_dict = current_item_parser_inner.get_exp_price_new(cookie)
    if price_type_name_inner in ["试用", "试用价"]:
        result_dict = current_item_parser_inner.get_trial_price_new(cookie)
    if price_type_name_inner == "折扣价":
        result_dict = current_item_parser_inner.get_discount_price_new(cookie)
    if price_type_name_inner == "首优原价":
        result_dict = current_item_parser_inner.get_priority_original_price_new(cookie)

    if price_type_name_inner == "折扣价-3天试用":
        result_dict = current_item_parser_inner.get_discount_trial_price_new(cookie)

    if price_type_name_inner in ["挽回", "挽回价"] and system != "android":
        result_dict = current_item_parser_inner.get_retain_price_new(cookie)

    if price_type_name_inner in ["挽回试用"]:
        result_dict = current_item_parser_inner.get_retain_trial_price_new(cookie)

    # 【修复】android平台的挽回价格类型处理
    if system == "android" and price_type_name_inner in ["挽回", "挽回价"] and retain_id != 0:
        mod = kwargs.get("mod")
        mock_country = kwargs.get("mock_country")
        product_order = kwargs.get("product_order")
        excel_product_id = kwargs.get("excel_product_id")
        retain_shop_window_parser = ShopWindowParser(retain_id, mode=mod, mock_country=mock_country,
                                                     platform=system, is_uwp=False, cookie=cookie)
        retain_shop_items_list = retain_shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
        if retain_shop_items_list is None:
            logger.error("获取挽回橱窗商品列表失败，挽回橱窗id: " + str(retain_id) + "，可能原因：橱窗不存在、API返回异常、或橱窗无商品数据")
            return {}
        if not isinstance(retain_shop_items_list, list) or len(retain_shop_items_list) == 0:
            logger.error("挽回橱窗商品列表为空，挽回橱窗id: " + str(retain_id) + "，商品索引: " + str(product_order))
            return {}
        
        # 【修复】优先使用商品ID匹配，如果失败则回退到索引匹配
        retain_shop_item = None
        if excel_product_id:
            # 遍历所有商品，找到匹配的商品ID（检查所有可能的商品类型）
            for item in retain_shop_items_list:
                item_product_id = None
                # 检查所有可能的商品类型
                for item_type in ["origin_item_info", "discount_origin_item_info", "trial_item_info", 
                                 "discount_trial_item_info", "one_time_origin_item_info", "one_time_discount_item_info"]:
                    if item.get(item_type) and item[item_type].get("id") == excel_product_id:
                        item_product_id = excel_product_id
                        retain_shop_item = item
                        logger.info("get_target_info_by_condition: 在挽回橱窗中找到匹配的商品ID: " + str(excel_product_id) + "，商品类型: " + item_type)
                        break
                if retain_shop_item:
                    break
            
            if not retain_shop_item:
                all_product_ids = []
                for item in retain_shop_items_list:
                    for item_type in ["origin_item_info", "discount_origin_item_info", "trial_item_info", 
                                     "discount_trial_item_info", "one_time_origin_item_info", "one_time_discount_item_info"]:
                        if item.get(item_type) and item[item_type].get("id"):
                            all_product_ids.append(item[item_type].get("id"))
                logger.warning("get_target_info_by_condition: 在挽回橱窗中未找到匹配的商品ID " + str(excel_product_id) + "，商品列表: " + str(all_product_ids) + "，将回退到索引匹配")
        
        # 如果商品ID匹配失败，回退到索引匹配
        if not retain_shop_item:
            try:
                retain_shop_item = retain_shop_items_list[product_order]
                logger.info("get_target_info_by_condition: 使用索引匹配获取挽回橱窗商品，索引: " + str(product_order))
            except IndexError:
                logger.error("挽回橱窗商品索引越界，挽回橱窗id: " + str(retain_id) + "，商品索引: " + str(product_order) + "，商品列表长度: " + str(len(retain_shop_items_list)))
                return {}
        
        current_item_parser = ShopItemNewParser(retain_shop_item)
        if price_type_name_inner == "挽回" or price_type_name_inner == "挽回价":
            result_dict = current_item_parser.get_discount_price_new(cookie)

    # 【修复】android平台的挽回价-3天试用处理（需要retain_id）
    if system == "android" and price_type_name_inner == "挽回价-3天试用" and retain_id != 0:
        mod = kwargs.get("mod")
        mock_country = kwargs.get("mock_country")
        product_order = kwargs.get("product_order")
        excel_product_id = kwargs.get("excel_product_id")
        retain_shop_window_parser = ShopWindowParser(retain_id, mode=mod, mock_country=mock_country,
                                                     platform=system, is_uwp=False, cookie=cookie)
        retain_shop_items_list = retain_shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")
        if retain_shop_items_list is None:
            logger.error("获取挽回橱窗商品列表失败，挽回橱窗id: " + str(retain_id) + "，可能原因：橱窗不存在、API返回异常、或橱窗无商品数据")
            return {}
        if not isinstance(retain_shop_items_list, list) or len(retain_shop_items_list) == 0:
            logger.error("挽回橱窗商品列表为空，挽回橱窗id: " + str(retain_id) + "，商品索引: " + str(product_order))
            return {}
        
        # 【修复】优先使用商品ID匹配，如果失败则回退到索引匹配
        retain_shop_item = None
        if excel_product_id:
            # 遍历所有商品，找到匹配的商品ID（检查所有可能的商品类型）
            for item in retain_shop_items_list:
                item_product_id = None
                # 检查所有可能的商品类型
                for item_type in ["origin_item_info", "discount_origin_item_info", "trial_item_info", 
                                 "discount_trial_item_info", "one_time_origin_item_info", "one_time_discount_item_info"]:
                    if item.get(item_type) and item[item_type].get("id") == excel_product_id:
                        item_product_id = excel_product_id
                        retain_shop_item = item
                        logger.info("get_target_info_by_condition: 在挽回橱窗中找到匹配的商品ID: " + str(excel_product_id) + "，商品类型: " + item_type)
                        break
                if retain_shop_item:
                    break
            
            if not retain_shop_item:
                all_product_ids = []
                for item in retain_shop_items_list:
                    for item_type in ["origin_item_info", "discount_origin_item_info", "trial_item_info", 
                                     "discount_trial_item_info", "one_time_origin_item_info", "one_time_discount_item_info"]:
                        if item.get(item_type) and item[item_type].get("id"):
                            all_product_ids.append(item[item_type].get("id"))
                logger.warning("get_target_info_by_condition: 在挽回橱窗中未找到匹配的商品ID " + str(excel_product_id) + "，商品列表: " + str(all_product_ids) + "，将回退到索引匹配")
        
        # 如果商品ID匹配失败，回退到索引匹配
        if not retain_shop_item:
            try:
                retain_shop_item = retain_shop_items_list[product_order]
                logger.info("get_target_info_by_condition: 使用索引匹配获取挽回橱窗商品，索引: " + str(product_order))
            except IndexError:
                logger.error("挽回橱窗商品索引越界，挽回橱窗id: " + str(retain_id) + "，商品索引: " + str(product_order) + "，商品列表长度: " + str(len(retain_shop_items_list)))
                return {}
        
        current_item_parser = ShopItemNewParser(retain_shop_item)
        result_dict = current_item_parser.get_discount_trial_price_new(cookie)

    if price_type_name_inner == "一次性原价":
        if "印度" in country or "T4" in country:
            result_dict = current_item_parser_inner.get_origin_price_new(cookie)
        else:
            result_dict = current_item_parser_inner.get_onetime_origin_price_new(cookie)
    if price_type_name_inner == "一次性折扣价":
        if "印度" in country or "T4" in country:
            result_dict = current_item_parser_inner.get_discount_price_new(cookie)
        else:
            result_dict = current_item_parser_inner.get_onetime_discount_price_new(cookie)
    if price_type_name_inner == "一次性挽回价":
        if "印度" in country or "T4" in country:
            result_dict = current_item_parser_inner.get_retain_price_new(cookie)
        else:
            result_dict = current_item_parser_inner.get_onetime_retain_price_new(cookie)

    if _is_ios_like_platform(system):
        if price_type_name_inner == "加购":
            result_dict = current_item_parser_inner.get_origin_price_new(cookie)

        if price_type_name_inner in ["加购试用", "试用加购"]:
            result_dict = current_item_parser_inner.get_trial_price_new(cookie)
    elif system == "pc":
        # PC端加购商品处理
        if price_type_name_inner == "加购":
            logger.info("get_target_info_by_condition: PC端加购商品，调用get_add_buy_origin_price_new，价格类型: " + price_type_name_inner)
            result_dict = current_item_parser_inner.get_add_buy_origin_price_new(cookie)
            if not result_dict:
                logger.error("get_target_info_by_condition: get_add_buy_origin_price_new返回空字典，价格类型: " + price_type_name_inner)
        elif price_type_name_inner == "试用加购" or price_type_name_inner == "加购试用":
            logger.info("get_target_info_by_condition: PC端试用加购商品，调用get_add_buy_trail_price_new，价格类型: " + price_type_name_inner)
            result_dict = current_item_parser_inner.get_add_buy_trail_price_new(cookie)
            if not result_dict:
                logger.error("get_target_info_by_condition: get_add_buy_trail_price_new返回空字典，价格类型: " + price_type_name_inner)
    else:
        # 其他平台（包括android）的加购商品处理
        # 【修复】android平台的加购商品应该使用get_add_buy_origin_price_new和get_add_buy_trail_price_new
        # 而不是get_origin_price_new和get_trial_price_new（这些是主商品的方法）
        if price_type_name_inner == "加购":
            result_dict = current_item_parser_inner.get_add_buy_origin_price_new(cookie)
        if price_type_name_inner == "试用加购" or price_type_name_inner == "加购试用":
            result_dict = current_item_parser_inner.get_add_buy_trail_price_new(cookie)

    return result_dict


if __name__ == '__main__':
    # analysis_sku_xls_file("E://Chrome-Downloads//客户端SKU汇总表 (1).xlsx", "", "", "", True, 0)
    pass