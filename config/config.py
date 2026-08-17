# -*- coding: utf-8 -*-
"""
@File    : config.py
@Author  : liuxingquan
@Date    : 2026/02/09
@Description : 统一管理所有硬编码的配置项（系统配置）
"""
import os

# ==================== 基础配置 ====================

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Excel模板文件名
EXCEL_TEMPLATE_NAME = "payment_config_template.xlsx"

# 日志目录
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

# ==================== Excel列配置 ====================

# Excel列索引（从0开始）
EXCEL_COLUMN_INDEX = {
    "country": 0,              # 国家
    "member_type": 1,          # 会员类型
    "price_type": 2,           # 价格类型
    "product_order": 3,        # 商品序号
    "cycle": 4,                # 周期
    "total_price": 5,          # 总价
    "avg_price": 6,            # 月均价
    "price_id": 7,             # 价格ID
    "product_id": 8,           # 商品ID
    "product_give_cycle": 9,   # 买赠周期
    "shop_window_id": 10,      # 橱窗ID（K列）
    "exp_price": 11,           # 体验价价格（L列，可选）
    "exp_cycle": 12,           # 体验价周期（M列，可选）
}

# 需要合并单元格的列（程序会自动填充空值）
MERGED_CELL_COLUMNS = ["国家", "会员类型", "价格类型"]

# 橱窗ID匹配关键字（支持"支付页"和"支付"两种格式）
SHOP_WINDOW_ID_KEYWORDS = ["支付页", "支付"]

# ==================== API配置 ====================


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default

# 星宿平台管理后台API（用于查询价格详情）
# 2026-05 起后台网关迁移到 example.com 的 shop-admin 路径
ADMIN_API_BASE_URL = _env("ADMIN_API_BASE_URL", "https://example.com/shopwindow/shop-admin/manage/1")
ADMIN_API_ROLE_URL = f"{ADMIN_API_BASE_URL}/role"
ADMIN_API_PRICE_LIST_URL = f"{ADMIN_API_BASE_URL}/price/list?page_num=1&page_size=20&kpay_sku_ids="
# 按价格ID查询列表（当价格详情接口返回 price_usd=0 时兜底）
ADMIN_API_PRICE_LIST_BY_IDS = f"{ADMIN_API_BASE_URL}/price/list?ids={{ids}}&page_num=1&page_size=20&status=0&use_status=0"
ADMIN_API_PRICE_DETAIL_URL = f"{ADMIN_API_BASE_URL}/price/"

# 根据商品ID获取商品信息API（K列="/"时使用，不依赖橱窗）
# 后台商品列表接口：GET manage/1/product/listnew?ids={product_id}&page_num=1&page_size=20&status=0&used_status=0
PRODUCT_LISTNEW_BASE_URL = _env("PRODUCT_LISTNEW_BASE_URL", "https://example.com/shopwindow/shop-admin/manage/1")
PRODUCT_LISTNEW_PATH = "/product/listnew"
# 请求头（与浏览器访问后台一致，避免被判定为未登录）
X_APP_ID = os.getenv("PAYMENT_X_APP_ID", "")
PRODUCT_LISTNEW_HEADERS_EXTRA = {
    "X-App-Id": X_APP_ID,
    "Referer": f"{PRODUCT_LISTNEW_BASE_URL.rstrip('/')}/",
    "Origin": "https://example.com",
}

# 后台橱窗详情API（管理视角，返回所有槽位商品，含首优等条件商品）
ADMIN_SHOPWINDOW_LISTNEW_PATH = "/shop-window/listnew"

# 支付橱窗API（用于查询橱窗配置）
SHOP_WINDOW_API = {
    "online": {
        "base_url": _env("PAY_WINDOW_ONLINE_BASE_URL", "http://example.com"),
        "endpoint": "/api/v1/pay_window/type/{platform}?shopwindow_id={shopwindow_id}&lang=zh-CN&platform={platform}&mock_country={mock_country}"
    },
    "test": {
        "base_url": _env("PAY_WINDOW_TEST_BASE_URL", "http://example.com"),
        "endpoint": "/api/v1/pay_window/type/{platform}?shopwindow_id={shopwindow_id}&lang=zh-CN&platform={platform}&mock_country={mock_country}"
    }
}

# UWP平台特殊配置
UWP_CHANNEL = "00100.00000802"

# ==================== 校验阈值配置 ====================

# 价格校验阈值（允许的误差范围，单位：美元）
PRICE_THRESHOLD = 0.02
# 体验价价格校验阈值（更严格，单位：美元）
EXP_PRICE_THRESHOLD = 0.01

# 是否校验「优惠券橱窗与原橱窗」商品一致性（原价/折扣价/一次性原价/一次性折扣价）
# 默认 False：仅用橱窗id查商品、校验价格（总价/月均价/周期等），不校验优惠券橱窗
CHECK_COUPON_WITH_SHOP_WINDOW = False

# 通用阈值
THRESHOLD = 0.5

# ==================== 网络请求配置 ====================

# 重试配置
RETRY_CONFIG = {
    "max_retries": 3,          # 最大重试次数
    "retry_delay": 1.0,        # 重试延迟时间（秒）
    "backoff_factor": 2.0,     # 退避因子
    "timeout": 30              # 请求超时时间（秒）
}

# 需要重试的HTTP状态码
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# ==================== Bot消息配置 ====================

# Bot Webhook URL（对外校验群）
BOT_WEBHOOK_URL = os.getenv("BOT_WEBHOOK_URL", "")
# Bot Webhook URL 列表（页面“发送Bot消息”默认走该列表）
BOT_WEBHOOK_URLS = [BOT_WEBHOOK_URL]
# 调试Bot Webhook URL（页面“调试推送”勾选后仅走该列表）
BOT_DEBUG_WEBHOOK_URLS = [u for u in os.getenv("BOT_DEBUG_WEBHOOK_URLS", "").split(",") if u]

# Bot消息超时时间（秒）
BOT_TIMEOUT = 10

# Bot 单条消息文本最大长度（超过则分段发送）
BOT_MSG_MAX_LENGTH = 5000

# ==================== 价格类型映射 ====================

# 支持的价格类型列表（与 get_target_info_by_condition 分支一致）
SUPPORTED_PRICE_TYPES = [
    "原价",
    "划线价",       # 展示用划线价，K列=/ 时与原价同源
    "盲盒1M AI价",  # 盲盒1M AI，K列=/ 时与原价同源；K列有橱窗id时按橱窗匹配商品id后校验
    "盲盒1M Bundle价",  # 盲盒1M Bundle，同上
    "盲盒3M Pro价",     # 运营标识，K列有橱窗id时按橱窗匹配商品id后走折扣价校验
    "盲盒10% OFF Coupon价",
    "盲盒1M Pro Gift Card价",
    "试用", "试用价",
    "折扣价",
    "首优原价",
    "折扣价-3天试用",
    "挽回", "挽回价",
    "挽回试用",
    "一次性原价",
    "一次性折扣价",
    "一次性挽回价",
    "加购",
    "加购试用", "试用加购",
    "体验价"  # 体验价（基于原价的体验价）
]

# ==================== 平台配置 ====================

# 支持的平台列表（与支付橱窗 API 的 platform 参数一致）
SUPPORTED_PLATFORMS = ["pc", "mac", "android", "ios", "ipad", "mobile", "web"]

# 支持的环境列表
SUPPORTED_ENVIRONMENTS = ["online", "test"]

# ==================== 默认配置（仅供参考） ====================

# 注意：以下默认配置仅供参考，实际运行时参数请在 main.py 中填写
# 运行时参数（每次执行可能不同）：
#   - cookie: 需要在 main.py 中填写（从浏览器获取）
#   - platform, env, country, sheet_index: 根据实际测试需求在 main.py 中修改
#   - restart, restart_index, restart_shop_window_id: 断点续传参数，在 main.py 中配置
DEFAULT_CONFIG = {
    "platform": "pc",
    "env": "online",
    "country": "MY",
    "is_uwp": False,
    "sheet_index": 0,
    "cookie": "",  # ⚠️ 需要在 main.py 中填写实际值
    "restart": False,
    "restart_index": 0,
    "restart_shop_window_id": 0
}

# ==================== 日志配置 ====================

# 日志格式
LOG_FORMAT = "[%(asctime)s][%(filename)s %(lineno)d][%(levelname)s]: %(message)s"

# 日志日期格式
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
