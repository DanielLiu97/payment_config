# -*- coding: utf-8 -*-
"""
基线配置生成核心逻辑

通过橱窗ID调用 pay_window API，解析所有商品槽位，
反向映射为 Excel 配置文档的行数据。
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from config.config import SHOP_WINDOW_API
from parser.shop_window_parser import ShopWindowParser
from utils.utils import (
    get_price_beautiful_by_sku_id,
    get_price_detail_by_sku_id,
    get_regular_time_expression,
    get_regular_time_expression_1,
)

logger = logging.getLogger(__name__)

# ── 槽位 → 价格类型 映射 ──────────────────────────────────
# 主橱窗中 shop_items 每个分组可能包含的槽位
MAIN_SLOTS = [
    ("origin_item_info", "原价"),
    ("discount_origin_item_info", "折扣价"),
    ("trial_item_info", "试用"),
    ("discount_trial_item_info", "折扣价-3天试用"),
    ("one_time_origin_item_info", "一次性原价"),
    ("one_time_discount_item_info", "一次性折扣价"),
    ("first_exp_item_info", "体验价"),
    ("trial_first_exp_item_info", "体验价"),
]

RETAIN_SLOTS = [
    ("retain_pay_origin_item_info", "挽回价"),
    ("retain_pay_try_item_info", "挽回试用"),
    ("retain_pay_one_time_item_info", "一次性挽回价"),
]

ADD_BUY_SLOTS = [
    ("origin_item_info", "加购"),
    ("trial_item_info", "加购试用"),
]


@dataclass
class BaselineRow:
    """一行基线配置数据，对应 Excel 的 A~M 列"""
    country: str = ""
    member_type: str = ""
    price_type: str = ""
    product_order: int = 0
    cycle: str = ""
    total_price: float = 0.0
    avg_price: float = 0.0
    price_id: int = 0
    product_id: int = 0
    give_cycle: str = ""
    shop_window_id: str = ""
    exp_price: str = ""
    exp_cycle: str = ""

    def to_list(self) -> list:
        return [
            self.country,
            self.member_type,
            self.price_type,
            self.product_order,
            self.cycle,
            self.total_price,
            self.avg_price,
            self.price_id,
            self.product_id,
            self.give_cycle,
            self.shop_window_id,
            self.exp_price,
            self.exp_cycle,
        ]


@dataclass
class GenerateResult:
    """生成结果"""
    rows: List[BaselineRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    showcase_ids: List[int] = field(default_factory=list)
    platform: str = ""
    env: str = ""
    country: str = ""


def _get_cycle_months(period, period_unit: str) -> int:
    """周期转月数"""
    if not period:
        return 0
    unit = str(period_unit or "").strip().upper()
    p = int(period)
    if unit in {"Y", "YEAR", "YEARS"}:
        return p * 12
    if unit in {"M", "MON", "MONTH", "MONTHS"}:
        return p
    if unit in {"Q", "QUARTER"}:
        return p * 3
    if unit in {"D", "DAY", "DAYS"}:
        return 1
    return 0


def _get_give_months(give_cycle, give_unit: str) -> int:
    """买赠周期转月数"""
    if not give_cycle or not give_unit:
        return 0
    return _get_cycle_months(give_cycle, give_unit)


def _infer_member_type(group_data: dict) -> str:
    """从商品组中推断会员类型"""
    for slot_key in ["origin_item_info", "discount_origin_item_info",
                     "trial_item_info", "one_time_origin_item_info"]:
        item = group_data.get(slot_key)
        if isinstance(item, dict) and item.get("name"):
            name = item["name"].strip()
            # 常见模式提取
            for pattern in [
                r"(AI\s*Pro)", r"(Super\s*Pro)", r"(Pro\s*Plus)",
                r"(Premium)", r"(Pro)", r"(Basic)",
                r"(超级会员\w+)", r"(会员\w+)",
            ]:
                m = re.search(pattern, name, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            return name
    return "未知"


def _extract_slot_row(
    slot_data: dict,
    price_type: str,
    group_index: int,
    showcase_id: int,
    country: str,
    member_type: str,
    cookie: str,
) -> Optional[BaselineRow]:
    """从单个槽位数据中提取一行基线配置"""
    if not slot_data or not isinstance(slot_data, dict):
        return None
    product_id = slot_data.get("id")
    if not product_id:
        return None

    sku_id = slot_data.get("sku_id")
    amount_cents = slot_data.get("amount") or 0
    total_price = amount_cents / 100

    period = slot_data.get("period")
    period_unit = slot_data.get("period_unit", "")
    give_cycle_val = slot_data.get("give_cycle", 0)
    give_unit_val = slot_data.get("give_unit", "")

    main_months = _get_cycle_months(period, period_unit)
    give_months = _get_give_months(give_cycle_val, give_unit_val)
    total_months = main_months + give_months

    # 价格 API 查询
    price_id = 0
    price_usd = 0.0
    if sku_id:
        try:
            price_id, _ = get_price_detail_by_sku_id(sku_id, cookie)
        except Exception as e:
            logger.warning("获取价格ID失败, sku_id=%s: %s", sku_id, e)
        try:
            price_usd, _, _, _, _ = get_price_beautiful_by_sku_id(sku_id, cookie)
        except Exception as e:
            logger.warning("获取价格USD失败, sku_id=%s: %s", sku_id, e)

    avg_price = round(price_usd / total_months, 2) if total_months > 0 else 0.0

    # 周期文本
    cycle_str = ""
    if period:
        cycle_str = str(period) + get_regular_time_expression_1(period_unit)

    # 买赠文本
    give_str = ""
    if give_unit_val and give_cycle_val:
        give_str = "买赠" + str(give_cycle_val) + get_regular_time_expression(give_unit_val)

    # 体验价
    exp_price_str = ""
    exp_cycle_str = ""
    first_exp_info = slot_data.get("first_exp_info")
    if first_exp_info and isinstance(first_exp_info, dict):
        exp_amount = first_exp_info.get("amount", 0)
        if exp_amount:
            exp_price_str = str(round(exp_amount / 100, 2))
        exp_duration = first_exp_info.get("duration")
        exp_duration_unit = first_exp_info.get("duration_unit", "")
        if exp_duration and exp_duration_unit:
            exp_cycle_str = str(exp_duration) + get_regular_time_expression_1(exp_duration_unit)

    return BaselineRow(
        country=country,
        member_type=member_type,
        price_type=price_type,
        product_order=group_index + 1,
        cycle=cycle_str,
        total_price=round(total_price, 2),
        avg_price=avg_price,
        price_id=price_id,
        product_id=product_id,
        give_cycle=give_str,
        shop_window_id=str(showcase_id),
        exp_price=exp_price_str,
        exp_cycle=exp_cycle_str,
    )


def _process_showcase(
    showcase_id: int,
    platform: str,
    env: str,
    country: str,
    cookie: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> tuple:
    """处理单个橱窗，返回 (rows, warnings)"""
    rows: List[BaselineRow] = []
    warnings: List[str] = []

    def _log(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    _log(f"正在获取橱窗 {showcase_id} 的数据 (platform={platform}, env={env}, country={country})...")

    parser = ShopWindowParser(
        shop_window_id=showcase_id,
        mode=env,
        mock_country=country,
        platform=platform,
        cookie=cookie,
    )

    if not parser.has_valid_shop_window():
        msg = f"橱窗 {showcase_id} 获取失败: {parser.last_error_reason}"
        warnings.append(msg)
        _log(msg)
        return rows, warnings

    shop_window = parser.current_shop_window
    shop_items = shop_window.get("shop_items") or []

    if not shop_items:
        msg = f"橱窗 {showcase_id} 没有商品数据 (shop_items 为空)"
        warnings.append(msg)
        _log(msg)
        return rows, warnings

    _log(f"橱窗 {showcase_id} 包含 {len(shop_items)} 个商品组")

    # 遍历每个商品组
    for group_idx, group in enumerate(shop_items):
        if not isinstance(group, dict):
            continue

        member_type = _infer_member_type(group)
        _log(f"  商品组 {group_idx + 1}: {member_type}")

        # 处理主槽位
        for slot_key, price_type in MAIN_SLOTS:
            slot_data = group.get(slot_key)
            if not slot_data or not isinstance(slot_data, dict) or not slot_data.get("id"):
                continue

            _log(f"    处理槽位: {price_type} (slot={slot_key}, 商品ID={slot_data.get('id')})")
            row = _extract_slot_row(
                slot_data, price_type, group_idx, showcase_id,
                country, member_type, cookie,
            )
            if row:
                rows.append(row)

        # 处理挽回槽位（部分平台在主橱窗中直接包含）
        for slot_key, price_type in RETAIN_SLOTS:
            slot_data = group.get(slot_key)
            if not slot_data or not isinstance(slot_data, dict) or not slot_data.get("id"):
                continue

            _log(f"    处理槽位: {price_type} (slot={slot_key}, 商品ID={slot_data.get('id')})")
            row = _extract_slot_row(
                slot_data, price_type, group_idx, showcase_id,
                country, member_type, cookie,
            )
            if row:
                rows.append(row)

        # 处理加购商品
        add_buy_list = group.get("add_buy_info") or []
        if isinstance(add_buy_list, list):
            for add_idx, add_buy_group in enumerate(add_buy_list):
                if not isinstance(add_buy_group, dict):
                    continue
                for slot_key, price_type in ADD_BUY_SLOTS:
                    slot_data = add_buy_group.get(slot_key)
                    if not slot_data or not isinstance(slot_data, dict) or not slot_data.get("id"):
                        continue

                    _log(f"    处理加购: {price_type} (商品ID={slot_data.get('id')})")
                    row = _extract_slot_row(
                        slot_data, price_type, group_idx, showcase_id,
                        country, member_type, cookie,
                    )
                    if row:
                        rows.append(row)

    # 处理挽回橱窗（独立橱窗）
    retain_shop_id = shop_window.get("pay_retain_shop_id")
    if retain_shop_id and int(retain_shop_id) > 0:
        _log(f"  发现挽回橱窗: {retain_shop_id}，开始获取...")
        retain_parser = ShopWindowParser(
            shop_window_id=int(retain_shop_id),
            mode=env,
            mock_country=country,
            platform=platform,
            cookie=cookie,
        )
        if retain_parser.has_valid_shop_window():
            retain_items = (retain_parser.current_shop_window.get("shop_items") or [])
            for g_idx, g in enumerate(retain_items):
                if not isinstance(g, dict):
                    continue
                member_type = _infer_member_type(g)
                for slot_key, price_type in RETAIN_SLOTS:
                    slot_data = g.get(slot_key)
                    if not slot_data or not isinstance(slot_data, dict) or not slot_data.get("id"):
                        continue
                    # 避免重复：检查商品ID是否已存在
                    pid = slot_data.get("id")
                    if any(r.product_id == pid and r.price_type == price_type for r in rows):
                        continue
                    _log(f"    挽回橱窗槽位: {price_type} (商品ID={pid})")
                    row = _extract_slot_row(
                        slot_data, price_type, g_idx,
                        retain_shop_id, country, member_type, cookie,
                    )
                    if row:
                        row.shop_window_id = f"挽回：{retain_shop_id}"
                        rows.append(row)
        else:
            msg = f"挽回橱窗 {retain_shop_id} 获取失败: {retain_parser.last_error_reason}"
            warnings.append(msg)
            _log(msg)

    _log(f"橱窗 {showcase_id} 共提取 {len(rows)} 行配置数据")
    return rows, warnings


def generate_baseline(
    showcase_ids: List[int],
    platform: str,
    env: str,
    country: str,
    cookie: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> GenerateResult:
    """
    生成基线配置数据。

    Args:
        showcase_ids: 橱窗ID列表
        platform: 平台 (pc/android/ios/mac/web/mobile/ipad)
        env: 环境 (online/test)
        country: 国家代码 (US/MY/...)
        cookie: 星宿后台 Cookie
        progress_callback: 进度回调，接收日志消息字符串

    Returns:
        GenerateResult 包含所有行数据和警告信息
    """
    result = GenerateResult(
        showcase_ids=showcase_ids,
        platform=platform,
        env=env,
        country=country,
    )

    for sid in showcase_ids:
        rows, warnings = _process_showcase(
            showcase_id=sid,
            platform=platform,
            env=env,
            country=country,
            cookie=cookie,
            progress_callback=progress_callback,
        )
        result.rows.extend(rows)
        result.warnings.extend(warnings)

    if progress_callback:
        progress_callback(f"生成完成，共 {len(result.rows)} 行数据，{len(result.warnings)} 条警告")

    return result
