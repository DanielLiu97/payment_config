# -*- coding: utf-8 -*-
"""快速生成Excel模板 - 可直接运行"""
import pandas as pd
import os
import sys

def generate_template():
    """生成Excel模板"""
    # 定义表头（必须按顺序）
    headers = [
        "国家",      # 列0 - 需要合并单元格
        "会员类型",  # 列1 - 需要合并单元格  
        "价格类型",  # 列2 - 需要合并单元格
        "商品序号",  # 列3
        "周期",      # 列4
        "总价",      # 列5
        "均价",      # 列6
        "价格ID",    # 列7
        "商品ID",    # 列8
        "买赠周期",  # 列9
        "橱窗ID"     # 列10 - 格式：支付页：3553
    ]
    
    # 示例数据（多组数据，展示不同价格类型）
    data = [
        # 第一组：US Pro 原价（4行相同国家/会员类型/价格类型，需要合并）
        ["US", "Pro", "原价", 1, "1年", 59.99, 4.99, "", "", "", "支付页：3553"],
        ["US", "Pro", "原价", 2, "2年", 119.98, 4.99, "", "", "", ""],  # 橱窗ID留空，沿用上一行
        ["US", "Pro", "原价", 3, "3年", 179.97, 4.99, "", "", "", ""],
        # 第二组：US Pro 折扣价
        ["US", "Pro", "折扣价", 1, "1年", 35.99, 1.99, "", "", "6个月", "支付页：3553"],
        ["US", "Pro", "折扣价", 2, "2年", 71.98, 1.99, "", "", "6个月", ""],
        # 第三组：US Pro 试用价
        ["US", "Pro", "试用价", 1, "1年", 59.99, 4.99, "", "", "", "支付页：3553"],
        # 第四组：US Pro 折扣价-3天试用
        ["US", "Pro", "折扣价-3天试用", 1, "1年", 35.99, 1.99, "", "", "6个月", "支付页：3553"],
    ]
    
    # 创建DataFrame
    df = pd.DataFrame(data, columns=headers)
    
    # 获取输出路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "payment_config_template.xlsx")
    
    # 保存为Excel
    df.to_excel(output_file, index=False, sheet_name="Sheet1")
    
    print("=" * 60)
    print("✅ Excel模板已生成成功！")
    print(f"📁 文件路径: {output_file}")
    print("=" * 60)
    print("\n📋 列说明：")
    print("  列0: 国家（如：US、印度、T1等）")
    print("  列1: 会员类型（如：Pro、Premium等）")
    print("  列2: 价格类型（原价、折扣价、试用价等）")
    print("  列3: 商品序号（从1开始，对应橱窗中的商品顺序）")
    print("  列4: 周期（如：1年、2年、3个月等）")
    print("  列5: 总价（美元，如：59.99）")
    print("  列6: 均价（美元/月，如：4.99）")
    print("  列7: 价格ID（可留空，程序会自动校验）")
    print("  列8: 商品ID（可留空，程序会自动校验）")
    print("  列9: 买赠周期（如：6个月，原价可不填）")
    print("  列10: 橱窗ID（格式：支付页：3553，相同橱窗可只填第一行）")
    print("\n⚠️  重要提示：")
    print("  1. 前3列（国家、会员类型、价格类型）需要合并相同值的单元格")
    print("  2. 橱窗ID格式必须是：支付页：数字")
    print("  3. 相同橱窗可以只在第一行填写，后续行留空会自动沿用")
    print("  4. 价格ID和商品ID可以留空，程序会从API获取并校验")
    print("\n💡 下一步：")
    print("  1. 打开生成的Excel文件")
    print("  2. 合并前3列的相同值单元格")
    print("  3. 填写你的实际数据")
    print("  4. 修改 main.py 中的 excel_file_path 和 sheet_index")
    print("  5. 运行 python main.py 开始校验")
    print("=" * 60)

if __name__ == "__main__":
    try:
        generate_template()
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
