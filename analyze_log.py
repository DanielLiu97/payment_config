# -*- coding: utf-8 -*-
import re
import os

log_file = r"D:\cursor\2026Test Project\海外新春活动\payment_config_checker_0910\payment_config_checker\logs\20260205.log"

if not os.path.exists(log_file):
    print(f"日志文件不存在: {log_file}")
    exit(1)

with open(log_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 统计月均价校验情况
avg_price_pass = len(re.findall(r'【月均价】校验通过', content))
avg_price_error = len(re.findall(r'【月均价】校验错误', content))

# 统计所有ERROR
errors = re.findall(r'\[ERROR\].*', content)

# 统计未命中配置价格类型
price_type_errors = re.findall(r'未命中配置价格类型检查', content)

print("=" * 60)
print("2月5日日志分析结果")
print("=" * 60)
print(f"\n【月均价校验】")
print(f"  校验通过: {avg_price_pass} 条")
print(f"  校验错误: {avg_price_error} 条")

print(f"\n【其他错误】")
print(f"  未命中配置价格类型: {len(price_type_errors)} 条")
if price_type_errors:
    print("  错误详情:")
    for i, error in enumerate(price_type_errors, 1):
        # 找到对应的行号
        error_lines = re.findall(r'第\d+行未命中配置价格类型检查', content)
        if error_lines:
            print(f"    {i}. {error_lines[i-1] if i <= len(error_lines) else '未知行号'}")

print(f"\n【总结】")
if avg_price_error == 0:
    print("  ✅ 月均价校验全部通过！USD单位切换成功！")
else:
    print(f"  ⚠️  仍有 {avg_price_error} 条月均价校验错误，需要检查")

if len(price_type_errors) > 0:
    print(f"  ⚠️  有 {len(price_type_errors)} 条价格类型配置错误（非月均价问题）")
else:
    print("  ✅ 无价格类型配置错误")

print("=" * 60)
