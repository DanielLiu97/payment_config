# -*- coding: utf-8 -*-
import re
import os
from collections import defaultdict

log_file = r"logs\20260205.log"
script_dir = os.path.dirname(os.path.abspath(__file__))
log_path = os.path.join(script_dir, log_file)

if not os.path.exists(log_path):
    print(f"日志文件不存在: {log_path}")
    exit(1)

# 读取从842行开始的内容
with open(log_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    
    # 从842行开始（索引841）
    if len(lines) < 842:
        print(f"日志文件只有 {len(lines)} 行，无法从842行开始读取")
        exit(1)
    
    content_from_842 = ''.join(lines[841:])  # 841是842行的索引（从0开始）

print("=" * 80)
print("2月5日日志分析 - 从842行开始至结束")
print("=" * 80)

# 统计错误信息
errors = []
error_types = defaultdict(list)

# 查找所有ERROR级别的日志
error_pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\d]*)\]\[.*?\]\[ERROR\]:\s*(.+)'
error_matches = re.findall(error_pattern, content_from_842)

for timestamp, error_msg in error_matches:
    errors.append((timestamp, error_msg))
    # 分类错误
    if "月均价" in error_msg:
        error_types["月均价校验错误"].append((timestamp, error_msg))
    elif "总价" in error_msg:
        error_types["总价校验错误"].append((timestamp, error_msg))
    elif "商品id" in error_msg or "商品ID" in error_msg:
        error_types["商品ID校验错误"].append((timestamp, error_msg))
    elif "价格id" in error_msg or "价格ID" in error_msg:
        error_types["价格ID校验错误"].append((timestamp, error_msg))
    elif "商品周期" in error_msg:
        error_types["商品周期校验错误"].append((timestamp, error_msg))
    elif "买赠周期" in error_msg:
        error_types["买赠周期校验错误"].append((timestamp, error_msg))
    elif "未命中配置价格类型" in error_msg:
        error_types["价格类型配置错误"].append((timestamp, error_msg))
    elif "未配置" in error_msg:
        error_types["配置缺失"].append((timestamp, error_msg))
    elif "转换出错" in error_msg:
        error_types["数据转换错误"].append((timestamp, error_msg))
    elif "优惠券" in error_msg:
        error_types["优惠券校验错误"].append((timestamp, error_msg))
    elif "非法字符" in error_msg:
        error_types["非法字符错误"].append((timestamp, error_msg))
    else:
        error_types["其他错误"].append((timestamp, error_msg))

# 统计信息
print(f"\n【错误统计】")
print(f"  总错误数: {len(errors)} 条")
print(f"  错误类型分布:")
for error_type, error_list in sorted(error_types.items(), key=lambda x: len(x[1]), reverse=True):
    if error_list:
        print(f"    - {error_type}: {len(error_list)} 条")

# 详细错误列表
print(f"\n【详细错误列表】")
print("-" * 80)

for error_type, error_list in sorted(error_types.items(), key=lambda x: len(x[1]), reverse=True):
    if error_list:
        print(f"\n### {error_type} ({len(error_list)}条)")
        print()
        # 显示所有错误
        for i, (timestamp, error_msg) in enumerate(error_list, 1):
            print(f"{i}. [{timestamp}] {error_msg}")

# 提取行号信息
print(f"\n【涉及的行号】")
row_numbers = set()
for _, error_msg in errors:
    row_match = re.search(r'第(\d+)行', error_msg)
    if row_match:
        row_numbers.add(int(row_match.group(1)))

if row_numbers:
    print(f"  涉及Excel行号: {sorted(row_numbers)}")
    print(f"  共 {len(row_numbers)} 行数据有问题")
else:
    print("  未找到行号信息")

print("\n" + "=" * 80)
