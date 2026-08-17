# -*- coding: utf-8 -*-
"""
@File    : shop_item_parser.py
@Author  : your-email@example.com
@Date    : 2024/9/7
@UpdatedBy : liuxingquan
@UpdatedDate : 2026/02/09
@Description : extract shop price information only, each json_data means a product
@UpdateNote : 
    1. 修复月均价计算逻辑：新增get_give_cycle_months函数，月均价计算包含加赠月数
       计算公式：月均价 = 总价 / (周期月数 + 加赠月数)
    2. 修复所有价格类型解析方法（共13个），统一使用USD价格和总周期计算月均价
    3. 修复加购商品解析：支持从add_buy_group直接解析和从add_buy_info列表解析两种数据结构
    4. 增强错误处理：添加None检查（shop_item_info、name等），防止AttributeError和TypeError
    5. 修复name字段处理：使用get("name", "")确保name始终为字符串，避免None导致的错误
    6. 修复NameError：修复main_period_str未定义问题，确保所有方法中main_period_str正确赋值
"""
import logging

from utils.utils import *

logger = logging.getLogger(__name__)

def _normalize_cycle_unit(unit_value) -> str:
    """归一化周期单位，统一返回 Y/M/D/Q；无法识别返回空字符串。"""
    if unit_value is None:
        return ""
    raw = str(unit_value).strip()
    if not raw:
        return ""
    up = raw.upper()
    if up in {"Y", "YEAR", "YEARS", "YR", "YRS"} or "年" in raw:
        return "Y"
    if up in {"M", "MON", "MONTH", "MONTHS"} or "月" in raw:
        return "M"
    if up in {"Q", "QUARTER", "QUARTERS"} or "季度" in raw:
        return "Q"
    if up in {"D", "DAY", "DAYS"} or "天" in raw:
        return "D"
    return ""

def get_cycle(inner_period: int, inner_period_unit: str) -> int:
    norm_unit = _normalize_cycle_unit(inner_period_unit)
    if norm_unit == "Y":
        return inner_period * 12
    if norm_unit == "M":
        return inner_period
    if norm_unit == "Q":
        return inner_period * 3
    if norm_unit == "D":
        # 保持历史口径：天周期按 1 个月计，避免出现 0 月导致无法计算
        return 1
    logger.warning("未知周期单位: %s，inner_period=%s，返回0避免误算月均价", inner_period_unit, inner_period)
    return 0


def get_give_cycle_months(give_cycle: int, give_unit: str) -> int:
    """将加赠周期转换为月数"""
    if not give_cycle or not give_unit:
        return 0
    norm_unit = _normalize_cycle_unit(give_unit)
    if norm_unit == "Y":
        return give_cycle * 12
    elif norm_unit == "M":
        return give_cycle
    elif norm_unit == "Q":
        return give_cycle * 3
    elif norm_unit == "D":
        return int(give_cycle / 30)  # 天数转换为月数（向下取整）
    else:
        logger.warning("未知买赠单位: %s，give_cycle=%s，按0月处理", give_unit, give_cycle)
        return 0


class ShopItemNewParser:
    def __init__(self, json_data: dict):
        self.json_data = json_data

    """
    get detailed shop json data by key name
    """

    def get_item_obj(self, shop_name: str, desc: str) -> dict:
        shop_item_info = self.json_data.get(shop_name)
        if not shop_item_info:
            logger.error("%s未配置", desc)
            return {}
        product_id = shop_item_info.get("id")
        if not product_id:
            logger.error("%s id为空", desc)
            return {}
        logger.info("当前%s的id是: %s", desc, product_id)
        return shop_item_info

    """
    if there is no exp price, the method will be called when calculate origin price
    """

    @staticmethod
    def print_key_info_log(key_name: str, data: dict):
        info_id = data.get("id")
        sku_id = data.get("sku_id")
        description = data.get("description")
        sku_name = data.get("sku_name")
        logger.info("%s id is %s, sku_id is %s, description is %s, sku_name is %s", key_name, info_id, sku_id,
                    description, sku_name)

    def get_origin_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('origin_item_info')
        if not shop_item_info:
            logger.error("get_origin_price_new: origin_item_info为空")
            return {}
        product_id = shop_item_info.get("id")
        name = shop_item_info.get("name", "")
        # 部分橱窗配置只填了 sku_name，name 为空；这里兜底避免直接返回空字典
        if not name:
            fallback_name = shop_item_info.get("sku_name", "")
            if fallback_name:
                name = fallback_name
                logger.warning("get_origin_price_new: name为空，回退使用sku_name，商品ID: %s", str(product_id))
        if not name:
            logger.error("get_origin_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        # K列=/ 时 product/listnew 直接返回 price_id，用 price_id 查价格详情；否则用 sku_id
        direct_price_id = shop_item_info.get("price_id") if isinstance(shop_item_info.get("price_id"), (int, float)) else None
        if direct_price_id is not None:
            price_id, msg_list = get_price_detail_by_price_id(int(direct_price_id), cookie)
            price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_price_id(int(direct_price_id), cookie)
        else:
            sku_id = shop_item_info.get("sku_id")
            if sku_id is None:
                logger.error("get_origin_price_new: origin_item_info 既无 price_id 也无 sku_id，商品ID: " + str(product_id))
                return {}
            price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
            price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # origin_first_exp_info = shop_item_info.get("first_exp_info")
        # # 没有体验价就取原价
        # if not origin_first_exp_info:
        #     origin_item_price_total = shop_item_info.get('amount') / 100
        #     origin_item_price_avg = shop_item_info.get('avg_price_amount_num') / 100
        # else:
        #     origin_item_price_total = origin_first_exp_info.get("amount") / 100
        #     origin_item_price_avg = origin_first_exp_info.get("avg_amount") / 100

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            origin_first_exp_info = shop_item_info.get("first_exp_info")
            # 没有体验价就取原价
            if not origin_first_exp_info:
                origin_item_price_total = shop_item_info.get('amount') / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                origin_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
            else:
                origin_item_price_total = origin_first_exp_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                origin_item_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
        else:
            origin_item_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            origin_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": origin_item_price_total,
            "price_avg": origin_item_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_exp_price_new(self, cookie: str) -> dict:
        """
        获取体验价信息（基于原价或折扣原价的体验价）
        优先从折扣原价商品获取体验价，如果没有则从原价商品获取体验价
        如果商品有体验价配置，则返回体验价；如果没有体验价，则返回原价/折扣原价
        """
        # 新版橱窗中，体验价可能作为独立商品槽位下发（first_exp_item_info / trial_first_exp_item_info）
        # 这种场景不应再回到 origin/discount_origin 的 first_exp_info 逻辑，否则会取到错误 sku_id。
        exp_slot_item = self.json_data.get("first_exp_item_info")
        if not exp_slot_item:
            exp_slot_item = self.json_data.get("trial_first_exp_item_info")
        if exp_slot_item and isinstance(exp_slot_item, dict) and exp_slot_item.get("id"):
            product_id = exp_slot_item.get("id")
            sku_id = exp_slot_item.get("sku_id")
            name = exp_slot_item.get("name", "")
            if not name:
                logger.error("get_exp_price_new: first_exp/trial_first_exp name为空，商品ID: %s", str(product_id))
                return {}
            if sku_id is None:
                logger.error("get_exp_price_new: first_exp/trial_first_exp sku_id为空，商品ID: %s", str(product_id))
                return {}
            try:
                price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
            except Exception as e:
                logger.warning("get_exp_price_new: 取price_id失败，商品ID: %s, sku_id: %s, 错误: %s", str(product_id), str(sku_id), str(e))
                price_id, msg_list = 0, []
            try:
                price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
            except Exception as e:
                logger.warning("get_exp_price_new: 取价格展示失败，商品ID: %s, sku_id: %s, 错误: %s", str(product_id), str(sku_id), str(e))
                price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = 0, 0, 0, 0, ""

            name_check_msg = ""
            if "%" in name:
                name_check_msg = "商品名称: " + name + "有非法字符%"

            main_period = exp_slot_item.get("period")
            main_period_unit = exp_slot_item.get("period_unit")
            main_cycle = get_cycle(main_period, main_period_unit)
            give_unit = exp_slot_item.get("give_unit")
            give_cycle_months = 0
            if give_unit != "":
                give_cycle = exp_slot_item.get("give_cycle", 0)
                give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
            total_cycle = main_cycle + give_cycle_months

            exp_item_price_total = (exp_slot_item.get("amount", 0) or 0) / 100
            exp_item_price_avg = (exp_item_price_total / total_cycle) if total_cycle > 0 else 0

            period_chinese = get_regular_time_expression_1(main_period_unit)
            main_period_str = str(main_period) + period_chinese
            if give_unit != "":
                give_cycle = exp_slot_item.get("give_cycle")
                give_unit_chinese = get_regular_time_expression(give_unit)
                give_period = "买赠" + str(give_cycle) + give_unit_chinese
                give_contents = exp_slot_item.get("give_contents")
            else:
                give_period = ""
                give_contents = ""

            return {
                "product_id": product_id,
                "price_id": price_id,
                "msg_list": msg_list,
                "name_check_msg": name_check_msg,
                "price_total": exp_item_price_total,
                "price_avg": exp_item_price_avg,
                "main_period": main_period_str,
                "give_period": give_period,
                "give_contents": give_contents,
                "price_usd": price_usd,
                "price_usd_beauty": price_usd_beauty,
                "first_exp_price_usd": first_exp_price_usd,
                "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
                "price_name": price_name,
            }

        # 优先检查折扣原价商品，如果存在则使用折扣原价商品的体验价
        shop_item_info = self.json_data.get('discount_origin_item_info')
        is_discount_origin = True
        if not shop_item_info:
            # 如果没有折扣原价商品，则使用原价商品
            shop_item_info = self.json_data.get('origin_item_info')
            is_discount_origin = False
            if not shop_item_info:
                logger.error("get_exp_price_new: origin_item_info和discount_origin_item_info都为空，json_data keys: " + str(list(self.json_data.keys())))
                return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_exp_price_new: name为空")
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        # 体验价：优先使用first_exp_info，如果没有体验价则使用原价
        # 【修复】体验价总价应该使用first_exp_info.get("amount")（体验价的实际总价），而不是first_exp_price_usd（可能是其他值）
        # 月均价计算：如果first_exp_price_usd太小（<1），说明不是总价，应该使用总价/周期计算
        if "first_exp_info" in shop_item_info:
            origin_first_exp_info = shop_item_info.get("first_exp_info")
            if origin_first_exp_info:
                # 【修复】体验价总价逻辑：
                # 1. 如果first_exp_info.amount >= 100（>=1美元），使用它作为体验价总价
                # 2. 如果first_exp_info.amount < 100，说明可能不是总价，使用price_usd（从价格详情API获取，应该是正确的体验价总价）
                # 注意：不应该使用原价总价，因为体验价总价通常小于原价总价
                first_exp_amount = origin_first_exp_info.get("amount", 0)
                original_amount = shop_item_info.get('amount', 0)
                logger.debug("get_exp_price_new: 商品ID: %s, first_exp_info.amount: %s, 原价amount: %s, price_usd: %s", product_id, first_exp_amount, original_amount, price_usd)
                
                if first_exp_amount >= 100:  # >= 1美元
                    exp_item_price_total = first_exp_amount / 100
                    logger.info("get_exp_price_new: 使用first_exp_info.amount作为体验价总价，商品ID: %s, first_exp_info.amount: %s, 总价: %s", product_id, first_exp_amount, exp_item_price_total)
                else:
                    # first_exp_info.amount太小，使用price_usd（从价格详情API获取，应该是正确的体验价总价）
                    exp_item_price_total = price_usd
                    logger.warning("get_exp_price_new: first_exp_info.amount(%s)太小，使用price_usd作为体验价总价，商品ID: %s, price_usd: %s, 总价: %s", first_exp_amount, product_id, price_usd, exp_item_price_total)
                
                # 【修复】月均价计算：如果first_exp_price_usd >= 1，说明可能是总价，使用它计算；否则使用总价/周期
                if first_exp_price_usd >= 1:
                    # first_exp_price_usd可能是总价，使用它计算月均价
                    exp_item_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
                    logger.info("get_exp_price_new: 使用first_exp_price_usd计算月均价，商品ID: %s, first_exp_price_usd: %s, 月均价: %s", product_id, first_exp_price_usd, exp_item_price_avg)
                else:
                    # first_exp_price_usd太小，使用总价/周期计算月均价
                    exp_item_price_avg = exp_item_price_total / total_cycle if total_cycle > 0 else 0
                    logger.info("get_exp_price_new: first_exp_price_usd(%s)太小，使用总价/周期计算月均价，商品ID: %s, 总价: %s, 月均价: %s", first_exp_price_usd, product_id, exp_item_price_total, exp_item_price_avg)
                item_type = "折扣原价商品" if is_discount_origin else "原价商品"
                logger.info("get_exp_price_new: 使用%s的体验价，商品ID: %s, 总价: %s, 月均价: %s", item_type, product_id, exp_item_price_total, exp_item_price_avg)
            else:
                # 没有体验价，使用原价/折扣原价
                exp_item_price_total = shop_item_info.get('amount') / 100
                exp_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
                item_type = "折扣原价商品" if is_discount_origin else "原价商品"
                logger.warning("get_exp_price_new: %s没有体验价配置，使用原价，商品ID: %s, 总价: %s, 月均价: %s", item_type, product_id, exp_item_price_total, exp_item_price_avg)
        else:
            # 没有first_exp_info字段，使用原价/折扣原价
            exp_item_price_total = shop_item_info.get('amount') / 100
            exp_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
            item_type = "折扣原价商品" if is_discount_origin else "原价商品"
            logger.warning("get_exp_price_new: %s没有体验价配置，使用原价，商品ID: %s, 总价: %s, 月均价: %s", item_type, product_id, exp_item_price_total, exp_item_price_avg)

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": exp_item_price_total,
            "price_avg": exp_item_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_trial_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('trial_item_info')
        if not shop_item_info:
            logger.error("get_trial_price_new: trial_item_info为空")
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            trial_first_exp_info = shop_item_info.get("first_exp_info")
            # 没有体验价就取原价
            if not trial_first_exp_info:
                origin_item_price_total = shop_item_info.get('amount') / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                origin_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
            else:
                origin_item_price_total = trial_first_exp_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                origin_item_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
        else:
            origin_item_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            origin_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": origin_item_price_total,
            "price_avg": origin_item_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_discount_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('discount_origin_item_info')
        if not shop_item_info:
            logger.error("get_discount_price_new: discount_origin_item_info为空，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        # 【修复】如果discount_origin_item_info的name为空，尝试从origin_item_info获取name
        if not name:
            origin_item_info = self.json_data.get('origin_item_info')
            if origin_item_info:
                name = origin_item_info.get("name", "")
                if name:
                    logger.warning("get_discount_price_new: discount_origin_item_info的name为空，使用origin_item_info的name，商品ID: " + str(product_id))
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            discount_first_exp_info = shop_item_info.get("first_exp_info")
            # 没有体验价就取原价
            if not discount_first_exp_info:
                discount_item_price_total = shop_item_info.get('amount') / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                discount_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
            else:
                discount_item_price_total = discount_first_exp_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                discount_item_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
        else:
            discount_item_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            discount_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": discount_item_price_total,
            "price_avg": discount_item_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_priority_original_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('discount_origin_item_info')
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # discount_first_exp_info = shop_item_info.get("first_exp_info")
        # # 没有体验价就取原价
        # if not discount_first_exp_info:
        #     discount_item_price_total = shop_item_info.get('amount') / 100
        #     discount_item_price_avg = shop_item_info.get('avg_price_amount_num') / 100
        # else:
        #     discount_item_price_total = discount_first_exp_info.get("amount") / 100
        #     discount_item_price_avg = discount_first_exp_info.get("avg_amount") / 100

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            # 无论有没有体验价都取原价
            discount_item_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            discount_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
        else:
            discount_item_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            discount_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": discount_item_price_total,
            "price_avg": discount_item_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": 0,
            "first_exp_price_usd_beauty": '',
            "price_name": price_name
        }
        return result_dict

    def get_discount_trial_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('discount_trial_item_info')
        if not shop_item_info:
            logger.error("get_discount_trial_price_new: discount_trial_item_info为空，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        # 【修复】如果discount_trial_item_info的name为空，尝试从trial_item_info获取name
        if not name:
            trial_item_info = self.json_data.get('trial_item_info')
            if trial_item_info:
                name = trial_item_info.get("name", "")
                if name:
                    logger.warning("get_discount_trial_price_new: discount_trial_item_info的name为空，使用trial_item_info的name，商品ID: " + str(product_id))
        # 【修复】如果trial_item_info的name也为空，尝试从origin_item_info获取name
        if not name:
            origin_item_info = self.json_data.get('origin_item_info')
            if origin_item_info:
                name = origin_item_info.get("name", "")
                if name:
                    logger.warning("get_discount_trial_price_new: discount_trial_item_info和trial_item_info的name都为空，使用origin_item_info的name，商品ID: " + str(product_id))
        if not name:
            logger.error("get_discount_trial_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            discount_first_exp_info = shop_item_info.get("first_exp_info")
            # 没有体验价就取原价
            if not discount_first_exp_info:
                discount_item_price_total = shop_item_info.get('amount') / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                discount_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
            else:
                discount_item_price_total = discount_first_exp_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                discount_item_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
        else:
            discount_item_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            discount_item_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": discount_item_price_total,
            "price_avg": discount_item_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_retain_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('retain_pay_origin_item_info')
        if shop_item_info is None:
            logger.error("获取retain_pay_origin_item_info为空")
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            retain_item_exp_info = shop_item_info.get("first_exp_info")
            if retain_item_exp_info:
                retain_item_exp_price_total = retain_item_exp_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                retain_item_exp_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
            else:
                retain_item_exp_price_total = shop_item_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                retain_item_exp_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
        else:
            retain_item_exp_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            retain_item_exp_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": retain_item_exp_price_total,
            "price_avg": retain_item_exp_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict


    def get_retain_trial_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('retain_pay_try_item_info')
        if shop_item_info is None:
            logger.error("获取retain_pay_origin_item_info为空")
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 获取周期信息用于计算月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        
        if "first_exp_info" in shop_item_info:
            retain_item_exp_info = shop_item_info.get("first_exp_info")
            if retain_item_exp_info:
                retain_item_exp_price_total = retain_item_exp_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                retain_item_exp_price_avg = first_exp_price_usd / total_cycle if total_cycle > 0 else 0
            else:
                retain_item_exp_price_total = shop_item_info.get("amount") / 100
                # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
                retain_item_exp_price_avg = price_usd / total_cycle if total_cycle > 0 else 0
        else:
            retain_item_exp_price_total = shop_item_info.get('amount') / 100
            # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
            retain_item_exp_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": retain_item_exp_price_total,
            "price_avg": retain_item_exp_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_onetime_origin_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('one_time_origin_item_info')
        if not shop_item_info:
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        one_time_origin_price_total = shop_item_info.get("amount") / 100
        # 使用USD价格计算USD月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
        one_time_origin_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": one_time_origin_price_total,
            "price_avg": one_time_origin_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_onetime_discount_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('one_time_discount_item_info')
        if not shop_item_info:
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        one_time_discount_price_total = shop_item_info.get("amount") / 100
        # 使用USD价格计算USD月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
        one_time_discount_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        give_unit = shop_item_info.get("give_unit")
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": one_time_discount_price_total,
            "price_avg": one_time_discount_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_onetime_retain_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('retain_pay_one_time_item_info')
        if not shop_item_info:
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        one_time_discount_price_total = shop_item_info.get("amount") / 100
        # 使用USD价格计算USD月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
        one_time_discount_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": one_time_discount_price_total,
            "price_avg": one_time_discount_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_add_buy_origin_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        # 【修复】支持两种数据结构：
        # 1. 如果 self.json_data 本身就是 add_buy_group（从加购商品组直接获取的），直接使用
        # 2. 如果 self.json_data 包含 add_buy_info 列表（从主商品组获取的），取第一个
        if 'add_buy_info' in self.json_data and isinstance(self.json_data.get('add_buy_info'), list):
            add_buy_price_info_list = self.json_data.get('add_buy_info')
            if not add_buy_price_info_list or len(add_buy_price_info_list) == 0:
                logger.error("get_add_buy_origin_price_new: add_buy_info列表为空")
                return {}
            add_buy_price_info = add_buy_price_info_list[0]
        else:
            # self.json_data 本身就是 add_buy_group
            add_buy_price_info = self.json_data
            # 【修复】检查add_buy_price_info是否为None
            if add_buy_price_info is None:
                logger.error("get_add_buy_origin_price_new: add_buy_price_info为None，json_data keys: " + str(list(self.json_data.keys())))
                return {}
            origin_item_info = add_buy_price_info.get("origin_item_info")
            if origin_item_info:
                logger.info("get_add_buy_origin_price_new: 使用add_buy_group数据结构，商品ID: " + str(origin_item_info.get("id", "N/A")))
            else:
                logger.warning("get_add_buy_origin_price_new: add_buy_group中没有origin_item_info，keys: " + str(list(add_buy_price_info.keys())))
        
        shop_item_info = add_buy_price_info.get("origin_item_info") if add_buy_price_info else None
        if not shop_item_info:
            logger.error("get_add_buy_origin_price_new: origin_item_info为空，add_buy_price_info keys: " + str(list(add_buy_price_info.keys())))
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_discount_price_new: name为空，商品ID: " + str(product_id) + "，json_data keys: " + str(list(self.json_data.keys())))
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"
        add_buy_price_total = shop_item_info.get('amount') / 100
        # 使用USD价格计算USD月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
        add_buy_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": add_buy_price_total,
            "price_avg": add_buy_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_add_buy_trail_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        # 【修复】支持两种数据结构：
        # 1. 如果 self.json_data 本身就是 add_buy_group（从加购商品组直接获取的），直接使用
        # 2. 如果 self.json_data 包含 add_buy_info 列表（从主商品组获取的），取第一个
        if 'add_buy_info' in self.json_data and isinstance(self.json_data.get('add_buy_info'), list):
            add_buy_price_info_list = self.json_data.get('add_buy_info')
            if not add_buy_price_info_list or len(add_buy_price_info_list) == 0:
                logger.error("get_add_buy_trail_price_new: add_buy_info列表为空")
                return {}
            add_buy_price_info = add_buy_price_info_list[0]
        else:
            # self.json_data 本身就是 add_buy_group
            add_buy_price_info = self.json_data
            # 【修复】检查add_buy_price_info是否为None，以及trial_item_info是否存在
            if add_buy_price_info is None:
                logger.error("get_add_buy_trail_price_new: add_buy_price_info为None，json_data keys: " + str(list(self.json_data.keys())))
                return {}
            trial_item_info = add_buy_price_info.get("trial_item_info")
            if trial_item_info:
                logger.info("get_add_buy_trail_price_new: 使用add_buy_group数据结构，商品ID: " + str(trial_item_info.get("id", "N/A")))
            else:
                logger.warning("get_add_buy_trail_price_new: add_buy_group中没有trial_item_info，keys: " + str(list(add_buy_price_info.keys())))
        
        # 【修复】检查trial_item_info是否存在且不为None
        shop_item_info = None
        if add_buy_price_info:
            trial_item_info = add_buy_price_info.get("trial_item_info")
            if trial_item_info and isinstance(trial_item_info, dict) and trial_item_info.get("id"):
                shop_item_info = trial_item_info
            else:
                # 尝试其他字段：trial_first_exp_item_info
                trial_first_exp_item_info = add_buy_price_info.get("trial_first_exp_item_info")
                if trial_first_exp_item_info and isinstance(trial_first_exp_item_info, dict) and trial_first_exp_item_info.get("id"):
                    shop_item_info = trial_first_exp_item_info
                    logger.warning("get_add_buy_trail_price_new: trial_item_info为空，使用trial_first_exp_item_info")
        
        if not shop_item_info:
            logger.error("get_add_buy_trail_price_new: trial_item_info和trial_first_exp_item_info都为空，add_buy_price_info keys: " + str(list(add_buy_price_info.keys() if add_buy_price_info else [])))
            return {}
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name", "")
        if not name:
            logger.error("get_add_buy_trail_price_new: name为空")
            return {}
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(sku_id, cookie)
        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"
        add_buy_price_total = shop_item_info.get('amount') / 100
        # 使用USD价格计算USD月均价
        main_period = shop_item_info.get("period")
        main_period_unit = shop_item_info.get("period_unit")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
        add_buy_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese
        # if the give_unit is "", means no give behavior
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle")
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents")
        else:
            give_period = ""
            give_contents = ""

        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": add_buy_price_total,
            "price_avg": add_buy_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": first_exp_price_usd,
            "first_exp_price_usd_beauty": first_exp_price_usd_beauty,
            "price_name": price_name
        }
        return result_dict

    def get_onetime_add_buy_price_new(self, cookie: str) -> dict:
        # 返回信息，商品id、名称校验，三方价格校验、总价、月均价、买赠周期、主商品周期
        shop_item_info = self.json_data.get('add_buy_info')  # 假设数据源字段名
        product_id = shop_item_info.get("id")
        sku_id = shop_item_info.get("sku_id")
        name = shop_item_info.get("name")
        price_id, msg_list = get_price_detail_by_sku_id(sku_id, cookie)
        price_usd, price_usd_beauty, first_exp_price_usd, first_exp_price_usd_beauty, price_name = get_price_beautiful_by_sku_id(
            sku_id, cookie)

        # name 里面不能有%的
        name_check_msg = ""
        if "%" in name:
            name_check_msg = "商品名称: " + name + "有非法字符%"

        # 价格计算 - 一次性加购通常没有体验价
        onetime_add_buy_price_total = shop_item_info.get("amount", 0) / 100
        # 使用USD价格计算USD月均价
        main_period = shop_item_info.get("period", 1)
        main_period_unit = shop_item_info.get("period_unit", "month")
        main_cycle = get_cycle(main_period, main_period_unit)
        
        # 【修复】先获取加赠信息，用于计算月均价
        give_unit = shop_item_info.get("give_unit", "")
        give_cycle_months = 0
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_cycle_months = get_give_cycle_months(give_cycle, give_unit)
        
        # 计算总周期（主周期 + 加赠月数）
        total_cycle = main_cycle + give_cycle_months
        # 【修复】使用总周期计算月均价：总价 / (周期月数 + 加赠月数)
        onetime_add_buy_price_avg = price_usd / total_cycle if total_cycle > 0 else 0

        # 周期信息
        period_chinese = get_regular_time_expression_1(main_period_unit)
        main_period_str = str(main_period) + period_chinese

        # 买赠信息
        # give_unit已经在上面获取过了，这里可以复用
        if give_unit != "":
            give_cycle = shop_item_info.get("give_cycle", 0)
            give_unit_chinese = get_regular_time_expression(give_unit)
            give_period = "买赠" + str(give_cycle) + give_unit_chinese
            give_contents = shop_item_info.get("give_contents", "")
        else:
            give_period = ""
            give_contents = ""

        # 强制忽略体验价（一次性商品通常没有体验价）
        result_dict = {
            "product_id": product_id,
            "price_id": price_id,
            "msg_list": msg_list,
            "name_check_msg": name_check_msg,
            "price_total": onetime_add_buy_price_total,
            "price_avg": onetime_add_buy_price_avg,
            "main_period": main_period_str,
            "give_period": give_period,
            "give_contents": give_contents,
            "price_usd": price_usd,
            "price_usd_beauty": price_usd_beauty,
            "first_exp_price_usd": 0,  # 强制设为0
            "first_exp_price_usd_beauty": "",  # 强制设为空
            "price_name": price_name
        }
        return result_dict

    def get_origin_price(self) -> (int, float, float):
        origin_item_info = self.get_item_obj('origin_item_info', "原价商品")
        if not origin_item_info or origin_item_info == {}:
            logger.error("没有原价商品")
            return 0, 0.0, 0.0
        self.print_key_info_log('原价商品', origin_item_info)
        origin_item_price_total = origin_item_info.get('amount')
        origin_item_price_avg = origin_item_info.get('avg_price_amount_num')
        logger.info("原价商品订阅总价: %s, 月均价: %s", origin_item_price_total,
                    origin_item_price_avg)
        return get_round_numbers(origin_item_info.get("id"), origin_item_price_total, origin_item_price_avg)

    """
    如果有配置体验价，则返回体验价，如果没配置体验价，则调用上面的原价展示方法
    """

    def get_origin_exp_price(self) -> (int, float, float):
        origin_item_info = self.get_item_obj('origin_item_info', "原价商品")
        if not origin_item_info or origin_item_info == {}:
            logger.error("没有原价商品")
            return 0, 0.0, 0.0
        origin_first_exp_info = origin_item_info.get("first_exp_info")
        # if exp price is none, which means origin price will be the result
        if not origin_first_exp_info:
            logger.error("原价商品没有体验价，返回原价")
            return self.get_origin_price()
        self.print_key_info_log("基于原价的体验价", origin_item_info)
        origin_first_exp_total = origin_first_exp_info.get("amount")
        origin_first_exp_avg = origin_first_exp_info.get("avg_amount")
        logger.info("基于原价的体验价订阅总价是: %s, 月均价是: %s", origin_first_exp_total,
                    origin_first_exp_avg)
        return get_round_numbers(origin_item_info.get("id"), origin_first_exp_total, origin_first_exp_avg)

    def get_discount_origin_price(self) -> (int, float, float):
        discount_origin_item_info = self.get_item_obj('discount_origin_item_info', "折扣原价商品")
        if not discount_origin_item_info or discount_origin_item_info == {}:
            logger.error("没有折扣商品价格")
            return 0, 0.0, 0.0
        self.print_key_info_log("折扣原价", discount_origin_item_info)
        discount_origin_item_price_total = discount_origin_item_info.get('amount')
        discount_origin_item_price_avg = discount_origin_item_info.get('avg_price_amount_num')
        logger.info("折扣原价订阅总价是: %s, 月均价是: %s", discount_origin_item_price_total,
                    discount_origin_item_price_avg)
        return get_round_numbers(discount_origin_item_info.get("id"), discount_origin_item_price_total,
                                 discount_origin_item_price_avg)

    def get_discount_origin_exp_price(self) -> (int, float, float):
        discount_origin_item_info = self.get_item_obj('discount_origin_item_info', "折扣原价商品")
        if not discount_origin_item_info or discount_origin_item_info == {}:
            logger.error("没有折扣商品价格")
            return 0, 0.0, 0.0

        discount_origin_first_exp_info = discount_origin_item_info.get("first_exp_info")
        # if exp price is none, which means origin price will be the result
        if not discount_origin_first_exp_info:
            logger.error("折扣商品没有配置体验价，默认返回折扣原价")
            return self.get_discount_origin_price()
        self.print_key_info_log("基于折扣价的体验价", discount_origin_item_info)
        discount_origin_item_first_exp_total = discount_origin_first_exp_info.get("amount")
        discount_origin_item_first_exp_avg = discount_origin_first_exp_info.get("avg_amount")
        logger.info("基于折扣价的体验价订阅总价是: %s, 月均价为: %s", discount_origin_item_first_exp_total,
                    discount_origin_item_first_exp_avg)
        return get_round_numbers(discount_origin_item_info.get("id"), discount_origin_item_first_exp_total,
                                 discount_origin_item_first_exp_avg)

    """
    一次性没有体验价，只有原价和折扣价
    """

    def get_one_time_origin_price(self) -> (int, float, float):
        one_time_item_info = self.get_item_obj('one_time_origin_item_info', "一次性原价商品")
        if not one_time_item_info or one_time_item_info == {}:
            logger.error("没有配置一次性原价，检查是否将一次性商品配置到了原价商品上")
            return self.get_origin_price()
        # 不能直接return，因为存在一次性商品配置到原价商品和折扣价商品上去（比如印度印尼的一次性）

        self.print_key_info_log("一次性原价", one_time_item_info)
        one_time_item_price_total = one_time_item_info.get("amount")
        one_time_item_price_avg = one_time_item_info.get("avg_price_amount_num")
        logger.info("一次性原价总价是: %s, 月均价是: %s",
                    one_time_item_price_total,
                    one_time_item_price_avg)
        return get_round_numbers(one_time_item_info.get("id"), one_time_item_price_total, one_time_item_price_avg)

    def get_one_time_discount_origin_price(self) -> (int, float, float):
        one_time_discount_item_info = self.get_item_obj('one_time_discount_item_info', "一次性折扣商品")
        if not one_time_discount_item_info or one_time_discount_item_info == {}:
            logger.error("没有配置一次性折扣价, 检查是否将一次性商品配置到了折扣商品上")
            return self.get_discount_origin_price()
        self.print_key_info_log("一次性折扣价", one_time_discount_item_info)
        one_time_discount_item_price_total = one_time_discount_item_info.get("amount")
        one_time_discount_item_price_avg = one_time_discount_item_info.get("avg_price_amount_num")
        logger.info("一次性折扣价总价是: %s, 月均价是: %s",
                    one_time_discount_item_price_total,
                    one_time_discount_item_price_avg)
        return get_round_numbers(one_time_discount_item_info.get("id"), one_time_discount_item_price_total,
                                 one_time_discount_item_price_avg)

    """
    挽回默认先只取了原价或原价体验价
    """

    def get_retain_origin_price(self) -> (int, float, float):
        retain_item_info = self.get_item_obj('retain_pay_origin_item_info', "挽回原价商品")
        if not retain_item_info or retain_item_info == {}:
            logger.error("没有配置挽回商品")
            return 0, 0.0, 0.0

        retain_item_exp_info = retain_item_info.get("first_exp_info")
        if retain_item_exp_info:
            self.print_key_info_log("基于挽回原价的体验价", retain_item_info)
            retain_item_exp_price_total = retain_item_exp_info.get("amount")
            retain_item_exp_price_avg = retain_item_exp_info.get("avg_amount")
            logger.info("基于挽回原价的体验价总价是: %s, 月均价是: %s",
                        retain_item_exp_price_total,
                        retain_item_exp_price_avg)
            return get_round_numbers(retain_item_info.get("id"), retain_item_exp_price_total, retain_item_exp_price_avg)
        self.print_key_info_log("挽回原价", retain_item_info)
        retain_item_origin_item_price_total = retain_item_info.get("amount")
        retain_item_origin_item_price_avg = retain_item_info.get("avg_price_amount_num")
        logger.info("挽回原价订阅总价是: %s, 月均价是: %s",
                    retain_item_origin_item_price_total,
                    retain_item_origin_item_price_avg)
        return get_round_numbers(retain_item_info.get("id"), retain_item_origin_item_price_total,
                                 retain_item_origin_item_price_avg)

    """
    加购信息，直接通过判断来获取其价格展示,均未考虑试用价格为0的场景
    """

    def get_add_buy_price(self) -> (int, float, float):
        add_buy_price_info_list = self.json_data.get('add_buy_info')
        if not add_buy_price_info_list or len(add_buy_price_info_list) == 0:
            logger.error("未配置加购商品")
            return 0, 0.0, 0.0
        add_buy_price_info = add_buy_price_info_list[0]
        discount_origin_item_info = add_buy_price_info.get("discount_origin_item_info")
        if not discount_origin_item_info:
            logger.info("加购商品折扣价信息为空，转为计算原价")
            origin_item_info = add_buy_price_info.get("origin_item_info")
            if not origin_item_info:
                logger.error("加购商品原价未配置")
                return 0, 0.0, 0.0
            first_exp_info = origin_item_info.get("first_exp_info")
            if not first_exp_info:
                self.print_key_info_log("加购商品的原价", origin_item_info)
                add_buy_price_total = origin_item_info.get('amount')
                add_buy_price_avg = origin_item_info.get('avg_price_amount_num')
                logger.info("加购商品原价订阅总价是: %s, 月均价是: %s",
                            add_buy_price_total, add_buy_price_avg)
                return get_round_numbers(origin_item_info.get("id"), add_buy_price_total, add_buy_price_avg)
            else:
                self.print_key_info_log("基于原价的加购商品体验价", origin_item_info)
                add_buy_price_total = first_exp_info.get("amount")
                add_buy_price_avg = first_exp_info.get("avg_amount")
                logger.info("基于原价的加购商品体验价订阅总价是: %s, 月均价是: %s",
                            add_buy_price_total, add_buy_price_avg)
                return get_round_numbers(origin_item_info.get("id"), add_buy_price_total, add_buy_price_avg)
        else:
            discount_first_exp_info = discount_origin_item_info.get("first_exp_info")
            if not discount_first_exp_info:
                logger.info("加购商品折扣价未配置体验价，转为计算折扣原价信息")
                self.print_key_info_log("加购商品的折扣原价", discount_origin_item_info)
                discount_item_price_total = discount_origin_item_info.get('amount')
                discount_item_price_avg = discount_origin_item_info.get('avg_price_amount_num')
                logger.info("加购商品折扣原价订阅总价是: %s, 月均价是: %s",
                            discount_item_price_total, discount_item_price_avg)
                return get_round_numbers(discount_origin_item_info.get("id"), discount_item_price_total,
                                         discount_item_price_avg)
            else:
                self.print_key_info_log("基于折扣原价的加购商品体验价", discount_origin_item_info)
                discount_item_price_total = discount_first_exp_info.get('amount')
                discount_item_price_avg = discount_first_exp_info.get('avg_amount')
                logger.info("加购商品基于折扣原价的体验价订阅总价是: %s, 月均价是: %s",
                            discount_item_price_total, discount_item_price_avg)
                return get_round_numbers(discount_origin_item_info.get("id"), discount_item_price_total,
                                         discount_item_price_avg)

    """
    obtain main product's order period
    """

    def get_main_product_total_period(self):
        origin_item_info = self.get_item_obj('origin_item_info', "原价商品")
        if not origin_item_info:
            logger.error("原价商品未配置")
            return None
        main_period = origin_item_info.get("period")
        main_period_unit = origin_item_info.get("period_unit")

        # if the give_unit is "", means no give behavior
        give_unit = origin_item_info.get("give_unit")
        if give_unit != "":
            give_cycle = origin_item_info.get("give_cycle")
            total_period = (str(main_period) + get_regular_time_expression(main_period_unit) +
                            str(give_cycle) + get_regular_time_expression(give_unit))
        else:
            total_period = str(main_period) + get_regular_time_expression(main_period_unit)
        logger.info("主商品周期（包含买赠）是: %s", total_period)
        return total_period

    """
        obtain follow product's order period
    """

    def get_follow_product_total_period(self):
        add_buy_price_info_list = self.json_data.get('add_buy_info')
        if not add_buy_price_info_list or len(add_buy_price_info_list) == 0:
            logger.error("没有加购商品")
            return None
        add_buy_price_info = add_buy_price_info_list[0]
        origin_item_info = add_buy_price_info.get("origin_item_info")
        main_period = origin_item_info.get("period")
        main_period_unit = origin_item_info.get("period_unit")

        # if the give_unit is "", means no give behavior
        give_unit = origin_item_info.get("give_unit")
        if give_unit != "":
            give_cycle = origin_item_info.get("give_cycle")
            total_period = (str(main_period) + get_regular_time_expression(main_period_unit) +
                            str(give_cycle) + get_regular_time_expression(give_unit))
        else:
            total_period = str(main_period) + get_regular_time_expression(main_period_unit)
        logger.info("加购商品周期是: %s", total_period)
        return total_period

    # def get_target_info_by_key_name(self, key_name: str, attr: str, **kwargs):
    #     p_id = 0
    #     total = 0.0
    #     avg = 0.0
    #     if key_name == "origin_price":
    #         p_id, total, avg = self.get_origin_exp_price()
    #     if key_name == "discount_price":
    #         p_id, total, avg = self.get_discount_origin_exp_price()
    #     if key_name == "coupon_origin_price" or key_name == "coupon_discount_price":
    #         coupon_value = kwargs["coupon_id"]
    #         # for key, value in kwargs.items():
    #         #     if key == "coupon_id":
    #         #         coupon_value = value
    #         #         break
    #         if coupon_value != "0":
    #             current_shop_item_coupon_id = int(coupon_value.strip())
    #             coupon_shop_window_parser = ShopWindowParser(current_shop_item_coupon_id, kwargs["mode"],
    #                                                          kwargs["mock_country"], kwargs["platform"])
    #             # 优惠券默认会取第一个做为展示，因此可以直接取第一个即可。
    #             coupon_shop_item = coupon_shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")[0]
    #             coupon_shop_item_parser = ShopItemParser(coupon_shop_item)
    #             if key_name == "coupon_origin_price":
    #                 p_id, total, avg = coupon_shop_item_parser.get_origin_exp_price()
    #             if key_name == "coupon_discount_price":
    #                 p_id, total, avg = coupon_shop_item_parser.get_discount_origin_exp_price()
    #     if key_name == "retain_price":
    #         p_id, total, avg = self.get_retain_origin_price()
    #     if key_name == "add_buy_price":
    #         p_id, total, avg = self.get_add_buy_price()
    #     if key_name == "one_time_origin_price":
    #         p_id, total, avg = self.get_one_time_origin_price()
    #     if key_name == "one_time_discount_price":
    #         p_id, total, avg = self.get_one_time_discount_origin_price()
    #
    #     if attr == "product_id":
    #         return p_id
    #     if attr == "total":
    #         return total
    #     if attr == "avg":
    #         return avg
