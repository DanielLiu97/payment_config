# -*- coding: utf-8 -*-
"""
@File    : main.py
@Author  : your-email@example.com
@Date    : 2024/9/7
@UpdatedBy : liuxingquan
@UpdatedDate : 2026/02/09
@Description : The entry point of the program.
@UpdateNote : 重构配置管理，将运行时参数与系统配置分离，优化配置层次结构
"""
from analysis_sku.analysis_sku import analysis_sku_xls_file_new, send_check_error_msg_bot


# todo
# 1. 商品name字段检查是否有非法字符%d
# 2. 优惠券折扣和挽回折扣比例是否正确
# 3. 价格三方id是否存在空格

# mac商店包的买赠是以天为单位的
# mac商店包的三方价格可以提取出来做主商品周期判断
# 程序卡住的问题

if __name__ == '__main__':
    """
    主程序入口
    
    配置说明：
    - excel_file_path: Excel文件路径（默认使用项目根目录下的payment_config_template.xlsx）
    - platform: 平台类型，可选值：pc, android, ios, ipad, mobile
    - env: 环境，可选值：online, test
    - country: 国家代码，例如：MY（马来西亚）、US（美国）、IN（印度）等
    - is_uwp: 是否为UWP平台（Windows Store）
    - cookie: 星宿平台管理后台的Cookie（需要从浏览器获取）
    - sheet_index: Excel Sheet索引（从0开始，0表示第1个Sheet）
    - restart: 是否从指定行重新开始（用于断点续传）
    - restart_index: 重新开始的行索引（从0开始）
    - restart_shop_window_id: 重新开始的橱窗ID
    """
    import os
    from config.config import (
        PROJECT_ROOT, EXCEL_TEMPLATE_NAME, DEFAULT_CONFIG
    )
    
    # ==================== 运行时参数配置 ====================
    # 说明：
    #   - 以下参数是每次执行时可能需要修改的运行时参数
    #   - 系统配置（API地址、阈值等）在 config/config.py 中，一般不需要修改
    #   - Cookie 等敏感信息需要从浏览器获取，每次执行前请确认是否有效
    
    # Excel文件路径（默认使用项目根目录下的模板文件）
    excel_file_path = os.path.join(PROJECT_ROOT, EXCEL_TEMPLATE_NAME)
    
    # ==================== 测试环境配置 ====================
    # 平台配置
    platform = "pc"          # 可选：pc, android, ios, ipad, mobile（大小写均可，内部会规范为小写以匹配支付橱窗 API）
    env = "online"            # 可选：online, test
    country = "US"           # 国家代码：MY（马来西亚）、US（美国）、IN（印度）等
    
    # UWP配置
    is_uwp = False            # Windows Store平台设置为True
    
    # Sheet索引（从0开始：Sheet1=0，Sheet13=12）
    sheet_index = 15   # Sheet13
    # 临时：连续跑多 Sheet 时改为 [8, 9, 10]（Sheet9/10/11），不跑多 Sheet 时保持 None
    RUN_SHEETS_SEQUENCE = None  # [8, 9, 10]
    # 仅跑指定行（Excel 行号 1-based），如 [16, 23] 只校验第16、23行；不限制时设为 None
    ONLY_ROW_NUMBERS = None
    
    # ==================== 认证配置 ====================
    # Cookie配置（⚠️ 必须填写，需要从浏览器获取）
    # 获取方式：
    #   1. 登录星宿平台管理后台：https://example.com/
    #   2. 打开浏览器开发者工具（F12）
    #   3. 查看 Network 请求，复制完整 Cookie（建议整串，而非只拷贝 ovsmgr_sid）
    #   4. 粘贴到下方 cookie 变量（格式示例：a=1; b=2; ovsmgr_sid=xxx）
    # 注意：Cookie可能会过期，如果API请求返回401或403，需要重新获取
    # 本 cookie 用于全项目所有接口（橱窗、price、product/listnew 等），请与浏览器登录后台后的一致
    cookie = os.getenv("PAYMENT_ADMIN_COOKIE", "")  # 从环境变量读取，不在代码中硬编码
    
    # ==================== 断点续传配置 ====================
    # 如果脚本执行中断，可以使用断点续传功能
    restart = False           # 是否启用断点续传
    restart_index = 0         # 重新开始的行索引（从0开始）
    restart_shop_window_id = 0 # 重新开始的橱窗ID（可选，用于缓存优化）
    restart_end_index = None  # 仅跑多行时填结束索引（含），如 4 表示跑到第6行；与 restart 同用

    # ==================== 执行校验 ====================
    sheets_to_run = RUN_SHEETS_SEQUENCE if RUN_SHEETS_SEQUENCE else [sheet_index]
    for si in sheets_to_run:
        print(">>> 开始校验 Sheet{} (index={})".format(si + 1, si))
        try:
            error_msg_list = analysis_sku_xls_file_new(
                excel_file_path, env, country, platform, is_uwp,
                si, cookie, restart, restart_index, restart_shop_window_id, restart_end_index,
                ONLY_ROW_NUMBERS
            )
            send_check_error_msg_bot(error_msg_list, excel_file_path, si, platform=platform)
            print(">>> Sheet{} 校验完成\n".format(si + 1))
        except ValueError as e:
            if "invalid" in str(e).lower() and "worksheet" in str(e).lower():
                print(">>> Sheet{} (index={}) 不存在，已跳过（当前 Excel 工作表数量不足）\n".format(si + 1, si))
            else:
                raise
    print("全部完成，共 {} 个 Sheet".format(len(sheets_to_run)))
