# -*- coding: utf-8 -*-
import re
from collections import defaultdict

import os
script_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(script_dir, 'logs', '20260206.log')

errors = []
error_by_type = defaultdict(list)

with open(log_file, 'r', encoding='utf-8') as f:
    for line in f:
        if '[ERROR]' in line:
            errors.append(line.strip())
            # 提取错误类型
            if '【商品id】校验错误' in line:
                error_by_type['商品id校验错误'].append(line.strip())
            elif '【价格id】校验错误' in line:
                error_by_type['价格id校验错误'].append(line.strip())
            elif '【总价】校验错误' in line:
                error_by_type['总价校验错误'].append(line.strip())
            elif '【月均价】校验错误' in line:
                error_by_type['月均价校验错误'].append(line.strip())
            elif '【商品周期】校验错误' in line:
                error_by_type['商品周期校验错误'].append(line.strip())
            elif '【优惠券与原橱窗' in line:
                error_by_type['优惠券校验错误'].append(line.strip())
            elif '未命中配置价格类型检查' in line:
                error_by_type['价格类型未命中'].append(line.strip())
            else:
                error_by_type['其他错误'].append(line.strip())

print(f"共找到 {len(errors)} 条错误信息\n")
print("=" * 80)
print("错误统计（按类型）")
print("=" * 80)
for error_type, error_list in sorted(error_by_type.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"\n【{error_type}】共 {len(error_list)} 条")
    print("-" * 80)
    for err in error_list:
        # 提取行号
        match = re.search(r'第(\d+)行', err)
        if match:
            row_num = match.group(1)
            print(f"  行号: {row_num} | {err}")

print("\n" + "=" * 80)
print("所有错误详情")
print("=" * 80)
for i, err in enumerate(errors, 1):
    print(f"{i}. {err}")
