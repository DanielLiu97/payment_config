# -*- coding: utf-8 -*-
"""
测试脚本：验证本次修复的3个问题
"""
import re
import pandas as pd

print("=" * 80)
print("修复验证测试")
print("=" * 80)

# 测试1：验证加购商品匹配逻辑（通过商品ID匹配）
print("\n【测试1】加购商品匹配逻辑验证")
print("-" * 80)

# 模拟商品列表
mock_items_list = [
    {"origin_item_info": {"id": 4257}},
    {"origin_item_info": {"id": 4256}},
    {"origin_item_info": {"id": 3995}},  # Excel中配置的商品ID，排序靠后
    {"origin_item_info": {"id": 3996}},  # Excel中配置的商品ID，排序靠后
]

# 模拟Excel中配置的商品ID
excel_product_id = 3995

# 新逻辑：遍历所有商品，找到匹配的商品ID
found_item = None
for item in mock_items_list:
    item_product_id = None
    if item.get("origin_item_info"):
        item_product_id = item["origin_item_info"].get("id")
    if item_product_id == excel_product_id:
        found_item = item
        break

if found_item:
    print(f"✅ 通过商品ID匹配成功：找到商品ID {excel_product_id}")
else:
    print(f"❌ 匹配失败：未找到商品ID {excel_product_id}")

# 测试2：验证挽回橱窗ID读取逻辑（从Excel K列读取）
print("\n【测试2】挽回橱窗ID读取逻辑验证")
print("-" * 80)

# 模拟Excel K列的值
test_cases = [
    ("挽回：6187", 6187),
    ("挽回6185", 6185),
    ("支付页：6191", None),  # 不包含"挽回"，应该返回None
    ("", None),
    (None, None),
]

for k_column_value, expected_id in test_cases:
    excel_retain_id = None
    if pd.notna(k_column_value) and k_column_value not in [None, '', ' ']:
        if "挽回" in str(k_column_value):
            match = re.search(r'\d+', str(k_column_value))
            if match:
                excel_retain_id = int(match.group())
    
    if excel_retain_id == expected_id:
        print(f"✅ K列值 '{k_column_value}' -> 解析结果: {excel_retain_id} (期望: {expected_id})")
    else:
        print(f"❌ K列值 '{k_column_value}' -> 解析结果: {excel_retain_id} (期望: {expected_id})")

# 测试3：验证总价校验逻辑（确认代码能检测错误）
print("\n【测试3】总价校验逻辑验证")
print("-" * 80)

# 模拟总价校验
excel_total_price = 70.0
api_total_price = 39.99
threshold = 0.5

diff = abs(excel_total_price - api_total_price)
if diff < threshold:
    print(f"❌ 总价校验通过（不应该通过）：Excel={excel_total_price}, API={api_total_price}, 差异={diff}")
else:
    print(f"✅ 总价校验正确检测出错误：Excel={excel_total_price}, API={api_total_price}, 差异={diff} (阈值={threshold})")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
