# -*- coding: utf-8 -*-
"""
调试脚本：针对运营反馈的4个问题进行调试分析
"""
import os

import pandas as pd
from parser.shop_window_parser import ShopWindowParser
from config.logger import logger

# 配置信息
excel_file_path = "payment_config_template.xlsx"
sheet_index = 2  # 第3个sheet
platform = "pc"
env = "online"
country = "MY"
is_uwp = False
cookie = os.getenv("PAYMENT_ADMIN_COOKIE", "")

# 读取Excel
df = pd.read_excel(excel_file_path, sheet_name=sheet_index)

# 列索引定义（从analysis_sku.py复制）
country_index = 0
member_type_index = 1
price_type_index = 2
product_order_index = 3
cycle_index = 4
total_price_index = 5
avg_price_index = 6
price_id_index = 7
product_id_index = 8
product_give_cycle_index = 9
shop_window_id_index = 10

print("=" * 80)
print("问题调试分析")
print("=" * 80)

# 问题1：第18、19行（加购商品匹配问题）
print("\n【问题1】第18、19行 - 加购商品匹配问题")
print("-" * 80)
for row_num in [17, 18]:  # Excel行号18、19（索引17、18，包含表头）
    if row_num >= len(df):
        continue
    row_data = df.iloc[row_num].tolist()
    product_id = row_data[product_id_index]
    price_type = row_data[price_type_index]
    product_order = int(row_data[product_order_index]) - 1 if pd.notna(row_data[product_order_index]) else 0
    shop_window_id_value = row_data[shop_window_id_index]
    
    print(f"\n第{row_num + 1}行（Excel行号，包含表头）:")
    print(f"  商品ID: {product_id}")
    print(f"  价格类型: {price_type}")
    print(f"  商品索引: {product_order}")
    print(f"  橱窗ID: {shop_window_id_value}")
    
    # 解析橱窗ID
    import re
    match_key_word = "支付页"
    if pd.notna(shop_window_id_value) and match_key_word in str(shop_window_id_value):
        match = re.search(r'\d+', str(shop_window_id_value))
        if match:
            shop_window_id = int(match.group())
            print(f"  解析后的橱窗ID: {shop_window_id}")
            
            # 获取橱窗信息
            shop_window_parser = ShopWindowParser(shop_window_id, mode=env, mock_country=country, platform=platform, is_uwp=is_uwp)
            success_page_window_list = shop_window_parser.get_success_page_window_list()
            print(f"  成功页橱窗ID列表（从API获取）: {success_page_window_list}")
            print(f"  成功页橱窗数量: {len(success_page_window_list)}")
            
            if len(success_page_window_list) > 0:
                if product_order < len(success_page_window_list):
                    success_page_window_id = int(success_page_window_list[product_order])
                    print(f"  使用的成功页橱窗ID（索引{product_order}）: {success_page_window_id}")
                    
                    # 获取该橱窗的商品列表
                    success_page_window_parser = ShopWindowParser(success_page_window_id, mode=env, mock_country=country, platform=platform, is_uwp=is_uwp)
                    success_page_items_list = success_page_window_parser.get_shop_window_inner_obj_by_name("shop_items")
                    if success_page_items_list:
                        print(f"  成功页橱窗商品列表长度: {len(success_page_items_list)}")
                        print(f"  成功页橱窗所有商品ID: {[item.get('origin_item_info', {}).get('id') if item.get('origin_item_info') else 'N/A' for item in success_page_items_list[:10]]}")
                        if product_order < len(success_page_items_list):
                            used_item = success_page_items_list[product_order]
                            used_product_id = used_item.get('origin_item_info', {}).get('id') if used_item.get('origin_item_info') else None
                            print(f"  使用的商品ID（索引{product_order}）: {used_product_id}")
                            print(f"  Excel中的商品ID: {product_id}")
                            print(f"  是否匹配: {used_product_id == product_id}")
                        else:
                            print(f"  ⚠️ 商品索引{product_order}超出列表长度{len(success_page_items_list)}")
                else:
                    print(f"  ⚠️ 商品索引{product_order}超出成功页橱窗列表长度{len(success_page_window_list)}")

# 问题2：第25行总价问题
print("\n\n【问题2】第25行 - 总价获取问题")
print("-" * 80)
row_num = 24  # Excel行号25（索引24，包含表头）
if row_num < len(df):
    row_data = df.iloc[row_num].tolist()
    product_id = row_data[product_id_index]
    total_price = row_data[total_price_index]
    price_type = row_data[price_type_index]
    
    print(f"\n第{row_num + 1}行（Excel行号，包含表头）:")
    print(f"  商品ID: {product_id}")
    print(f"  价格类型: {price_type}")
    print(f"  Excel中的总价（F列，索引{total_price_index}）: {total_price}")
    print(f"  总价类型: {type(total_price)}")
    
    # 检查是否有其他列包含总价信息
    print(f"\n  该行的所有数据:")
    for i, val in enumerate(row_data):
        print(f"    列{i}（索引{i}）: {val}")

# 问题3：第45、46、47行 - 挽回橱窗ID读取问题
print("\n\n【问题3】第45、46、47行 - 挽回橱窗ID读取问题")
print("-" * 80)
for row_num in [44, 45, 46]:  # Excel行号45、46、47（索引44、45、46，包含表头）
    if row_num >= len(df):
        continue
    row_data = df.iloc[row_num].tolist()
    product_id = row_data[product_id_index]
    price_type = row_data[price_type_index]
    
    print(f"\n第{row_num + 1}行（Excel行号，包含表头）:")
    print(f"  商品ID: {product_id}")
    print(f"  价格类型: {price_type}")
    
    # 检查K列（索引10之后，需要确认K列是哪个索引）
    # Excel列：A=0, B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, J=9, K=10
    # 但shop_window_id_index = 10，所以K列应该是索引11
    if len(row_data) > 11:
        k_column_value = row_data[11]  # K列
        print(f"  K列（索引11）的值: {k_column_value}")
    else:
        print(f"  ⚠️ 行数据长度不足，无法读取K列")
        print(f"  当前行数据长度: {len(row_data)}")
        print(f"  所有列数据: {row_data}")
    
    # 检查从API获取的retain_id
    shop_window_id_value = row_data[shop_window_id_index]
    if pd.notna(shop_window_id_value):
        import re
        match_key_word = "支付页"
        if match_key_word in str(shop_window_id_value):
            match = re.search(r'\d+', str(shop_window_id_value))
            if match:
                shop_window_id = int(match.group())
                shop_window_parser = ShopWindowParser(shop_window_id, mode=env, mock_country=country, platform=platform, is_uwp=is_uwp)
                retain_id_from_api = shop_window_parser.get_retain_id()
                print(f"  从API获取的retain_id: {retain_id_from_api}")
                if len(row_data) > 11:
                    print(f"  Excel K列的值: {k_column_value}")
                    print(f"  是否匹配: {retain_id_from_api == k_column_value or (pd.notna(k_column_value) and str(retain_id_from_api) in str(k_column_value))}")

# 问题4：第62-76行 - 挽回橱窗ID读取问题
print("\n\n【问题4】第62-76行 - 挽回橱窗ID读取问题")
print("-" * 80)
for row_num in [61, 75]:  # Excel行号62、76（索引61、75，包含表头）
    if row_num >= len(df):
        continue
    row_data = df.iloc[row_num].tolist()
    product_id = row_data[product_id_index]
    price_type = row_data[price_type_index]
    
    print(f"\n第{row_num + 1}行（Excel行号，包含表头）:")
    print(f"  商品ID: {product_id}")
    print(f"  价格类型: {price_type}")
    
    # 检查K列
    if len(row_data) > 11:
        k_column_value = row_data[11]  # K列
        print(f"  K列（索引11）的值: {k_column_value}")
    else:
        print(f"  ⚠️ 行数据长度不足，无法读取K列")
        print(f"  当前行数据长度: {len(row_data)}")
    
    # 检查从API获取的retain_id
    shop_window_id_value = row_data[shop_window_id_index]
    if pd.notna(shop_window_id_value):
        import re
        match_key_word = "支付页"
        if match_key_word in str(shop_window_id_value):
            match = re.search(r'\d+', str(shop_window_id_value))
            if match:
                shop_window_id = int(match.group())
                shop_window_parser = ShopWindowParser(shop_window_id, mode=env, mock_country=country, platform=platform, is_uwp=is_uwp)
                retain_id_from_api = shop_window_parser.get_retain_id()
                print(f"  从API获取的retain_id: {retain_id_from_api}")
                if len(row_data) > 11:
                    print(f"  Excel K列的值: {k_column_value}")
                    print(f"  是否匹配: {retain_id_from_api == k_column_value or (pd.notna(k_column_value) and str(retain_id_from_api) in str(k_column_value))}")

print("\n" + "=" * 80)
print("调试完成")
print("=" * 80)
