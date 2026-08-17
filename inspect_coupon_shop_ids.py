# -*- coding: utf-8 -*-
"""
查看主橱窗接口返回的 coupon_shop_ids，用于确认「为什么会走优惠券校验」。
Sheet8 未填任何「校验优惠券」信息，触发来源是：K列橱窗id 请求主橱窗接口后，接口里的 coupon_shop_ids 字段。
运行方式：在 payment_config_checker 目录下执行  python inspect_coupon_shop_ids.py
"""
import sys
import os

# 保证能引用到 config 和 parser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser.shop_window_parser import ShopWindowParser


def main():
    # 与 main.py 保持一致：平台、环境、国家
    platform = "pc"
    env = "online"
    mock_country = "US"   # 若你 Sheet8 用马来西亚，可改为 "MY" 或日志里看到的 mock_country
    shop_window_ids = [7556, 7626, 7633]  # Sheet8 最近一次日志里出现的主橱窗 id

    print("=" * 60)
    print("主橱窗接口返回的 coupon_shop_ids（决定是否走优惠券校验）")
    print("参数: platform=%s, env=%s, mock_country=%s" % (platform, env, mock_country))
    print("=" * 60)

    for wid in shop_window_ids:
        try:
            p = ShopWindowParser(wid, mode=env, mock_country=mock_country, platform=platform, is_uwp=False)
            raw = p.current_shop_window.get("coupon_shop_ids")
            coupon_list = p.get_coupon_list()
            # 展示前 10 个槽位，对应商品序号 1~10
            slot_preview = list(coupon_list[:10]) if len(coupon_list) >= 10 else coupon_list
            print("\n橱窗 id: %s" % wid)
            print("  接口字段 coupon_shop_ids 原始值: %r" % raw)
            print("  解析后列表(按商品序号 1~10): %s" % slot_preview)
            non_zero = [i for i, v in enumerate(slot_preview) if v != "0"]
            if non_zero:
                print("  非 0 的槽位(商品序号): %s → 会触发优惠券橱窗请求并做 4 类校验" % [i + 1 for i in non_zero])
            else:
                print("  全部为 0 → 本橱窗不会走优惠券校验")
        except Exception as e:
            print("\n橱窗 id: %s  请求失败: %s" % (wid, e))

    print("\n" + "=" * 60)
    print("说明：若某橱窗的 coupon_shop_ids 在某个商品序号位置非 0，")
    print("该行校验时就会去请求该「优惠券橱窗」并执行原价/折扣价/一次性原价/一次性折扣价 4 类校验。")
    print("=" * 60)


if __name__ == "__main__":
    main()
