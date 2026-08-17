# -*- coding: utf-8 -*-
"""
完整错误提取脚本：确保不遗漏任何错误，特别是总价校验错误
"""
import re
from collections import defaultdict
from datetime import datetime

log_file = r'D:\cursor\2026Test Project\海外新春活动\payment_config_checker_0910\payment_config_checker\logs\20260206.log'

errors = []
error_by_type = defaultdict(list)
error_by_row = defaultdict(list)

# 错误类型关键词
error_keywords = {
    '商品id校验错误': ['商品id.*校验错误'],
    '价格id校验错误': ['价格id.*校验错误'],
    '总价校验错误': ['总价.*校验错误', '总价-体验价.*校验错误'],
    '月均价校验错误': ['月均价.*校验错误'],
    '商品周期校验错误': ['商品周期.*校验错误'],
    '优惠券校验错误': ['优惠券.*校验错误'],
    '价格类型未命中': ['未命中配置价格类型检查'],
    '其他错误': []
}

print("=" * 80)
print("开始提取错误信息...")
print("=" * 80)

with open(log_file, 'r', encoding='utf-8') as f:
    for line_num, line in enumerate(f, 1):
        if '[ERROR]' in line:
            errors.append((line_num, line.strip()))
            
            # 提取行号
            row_match = re.search(r'第(\d+)行', line)
            if row_match:
                row_num = int(row_match.group(1))
                
                # 分类错误
                found = False
                for error_type, patterns in error_keywords.items():
                    for pattern in patterns:
                        if re.search(pattern, line):
                            error_by_type[error_type].append((row_num, line.strip()))
                            error_by_row[row_num].append((error_type, line.strip()))
                            found = True
                            break
                    if found:
                        break
                
                if not found:
                    error_by_type['其他错误'].append((row_num, line.strip()))
                    error_by_row[row_num].append(('其他错误', line.strip()))

print(f"\n共找到 {len(errors)} 条错误信息")
print(f"涉及 {len(error_by_row)} 行数据")

# 生成报告
report_lines = []
report_lines.append("# PC端支付配置校验错误报告（完整版）")
report_lines.append(f"**日期**: {datetime.now().strftime('%Y-%m-%d')}")
report_lines.append("**平台**: PC")
report_lines.append("**环境**: online")
report_lines.append("**国家**: MY (马来西亚)")
report_lines.append("**Sheet**: 第3个sheet (sheet_index=2)")
report_lines.append("")
report_lines.append("---")
report_lines.append("")
report_lines.append("## 错误统计概览")
report_lines.append("")
report_lines.append("| 错误类型 | 数量 | 说明 |")
report_lines.append("|---------|------|------|")

for error_type in sorted(error_by_type.keys()):
    count = len(error_by_type[error_type])
    if error_type == '商品id校验错误':
        desc = 'Excel中的商品ID与API返回不一致'
    elif error_type == '价格id校验错误':
        desc = 'Excel中的价格ID与API返回不一致'
    elif error_type == '总价校验错误':
        desc = 'Excel中的总价与API返回不一致'
    elif error_type == '月均价校验错误':
        desc = 'Excel中的月均价与API返回不一致'
    elif error_type == '商品周期校验错误':
        desc = 'Excel中的商品周期与API返回不一致'
    elif error_type == '优惠券校验错误':
        desc = '优惠券橱窗与原橱窗的商品ID不匹配'
    elif error_type == '价格类型未命中':
        desc = 'Excel中的价格类型无法匹配到对应的处理逻辑'
    else:
        desc = '其他错误'
    report_lines.append(f"| {error_type} | {count} | {desc} |")

total_errors = sum(len(errors) for errors in error_by_type.values())
report_lines.append("")
report_lines.append(f"**总计**: {total_errors}条错误信息")
report_lines.append("")
report_lines.append("---")
report_lines.append("")
report_lines.append("## 详细错误信息（按行号排序）")
report_lines.append("")

# 按行号排序
for row_num in sorted(error_by_row.keys()):
    report_lines.append(f"### {row_num}. 第{row_num}行（包含表头，即第{row_num-1}行数据）")
    report_lines.append("")
    report_lines.append("**错误项：**")
    
    # 按错误类型分组
    row_errors_by_type = defaultdict(list)
    for error_type, error_msg in error_by_row[row_num]:
        row_errors_by_type[error_type].append(error_msg)
    
    for error_type in sorted(row_errors_by_type.keys()):
        for error_msg in row_errors_by_type[error_type]:
            # 提取关键信息
            if '总价' in error_type:
                # 提取总价信息
                price_match = re.search(r'单元格中值为:\s*([\d.]+).*接口中的值为:\s*([\d.]+)', error_msg)
                if price_match:
                    excel_val = price_match.group(1)
                    api_val = price_match.group(2)
                    report_lines.append(f"- **{error_type}**: 单元格值 `{excel_val}`，接口值 `{api_val}`")
                else:
                    report_lines.append(f"- **{error_type}**: {error_msg}")
            elif '商品id' in error_type:
                # 提取商品ID信息
                id_match = re.search(r'单元格中值为:\s*(\d+).*接口中的值为:\s*(\d+)', error_msg)
                if id_match:
                    excel_id = id_match.group(1)
                    api_id = id_match.group(2)
                    report_lines.append(f"- **{error_type}**: 单元格值 `{excel_id}`，接口值 `{api_id}`")
                else:
                    report_lines.append(f"- **{error_type}**: {error_msg}")
            elif '价格id' in error_type:
                # 提取价格ID信息
                id_match = re.search(r'单元格中值为:\s*(\d+).*接口中的值为:\s*(\d+)', error_msg)
                if id_match:
                    excel_id = id_match.group(1)
                    api_id = id_match.group(2)
                    report_lines.append(f"- **{error_type}**: 单元格值 `{excel_id}`，接口值 `{api_id}`")
                else:
                    report_lines.append(f"- **{error_type}**: {error_msg}")
            elif '月均价' in error_type:
                # 提取月均价信息
                price_match = re.search(r'单元格中值为:\s*([\d.]+).*接口中的值为:\s*([\d.]+)', error_msg)
                if price_match:
                    excel_val = price_match.group(1)
                    api_val = price_match.group(2)
                    report_lines.append(f"- **{error_type}**: 单元格值 `{excel_val}`，接口值 `{api_val}`")
                else:
                    report_lines.append(f"- **{error_type}**: {error_msg}")
            elif '商品周期' in error_type:
                # 提取周期信息
                cycle_match = re.search(r'单元格中值为:\s*([^,]+).*接口中的值为:\s*([^,]+)', error_msg)
                if cycle_match:
                    excel_cycle = cycle_match.group(1).strip()
                    api_cycle = cycle_match.group(2).strip()
                    report_lines.append(f"- **{error_type}**: 单元格值 `{excel_cycle}`，接口值 `{api_cycle}`")
                else:
                    report_lines.append(f"- **{error_type}**: {error_msg}")
            else:
                # 其他错误，直接显示
                report_lines.append(f"- **{error_type}**: {error_msg}")
    
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

# 特别强调总价错误
total_price_errors = error_by_type.get('总价校验错误', [])
if total_price_errors:
    report_lines.append("")
    report_lines.append("## ⚠️ 总价校验错误详情（重点检查）")
    report_lines.append("")
    for row_num, error_msg in total_price_errors:
        report_lines.append(f"### 第{row_num}行")
        price_match = re.search(r'单元格中值为:\s*([\d.]+).*接口中的值为:\s*([\d.]+)', error_msg)
        if price_match:
            excel_val = price_match.group(1)
            api_val = price_match.group(2)
            diff = abs(float(excel_val) - float(api_val))
            report_lines.append(f"- Excel总价: `{excel_val}`")
            report_lines.append(f"- API总价: `{api_val}`")
            report_lines.append(f"- 差异: `{diff:.2f}`")
        report_lines.append("")
        report_lines.append(f"完整错误信息: {error_msg}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

# 写入报告文件
report_file = r'D:\cursor\2026Test Project\海外新春活动\payment_config_checker_0910\payment_config_checker\校验错误报告_20260206_完整版.md'
with open(report_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))

print(f"\n报告已生成: {report_file}")
print(f"\n错误统计:")
for error_type, error_list in sorted(error_by_type.items()):
    print(f"  {error_type}: {len(error_list)}条")

if total_price_errors:
    print(f"\n⚠️ 特别注意: 发现 {len(total_price_errors)} 条总价校验错误，请重点检查！")
