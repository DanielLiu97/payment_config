# 支付配置校验工具（payment_config_checker）

自动化校验支付相关配置（商品、店铺橱窗、SKU 等）并产出检查报告的工具。支持命令行（CLI）与运营自助 Web 页面两种使用方式。

> 本仓库已做脱敏处理：所有 Cookie、Webhook Key、内部域名、同事邮箱等敏感信息均已移除或占位，**真实值通过环境变量注入，不入库**。

## 环境要求

- Python 3.9+
- 依赖见 `requirements.txt`（pandas / requests / openpyxl / fastapi / uvicorn / python-multipart / colorlog）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 准备环境变量
cp .env.example .env
#   然后编辑 .env，至少填入 PAYMENT_ADMIN_COOKIE（见下）

# 3. 运行
python run_web.py        # 启动运营自助校验 Web 页面（默认 http://127.0.0.1:8000）
python main.py           # 命令行模式执行校验
```

## 环境变量配置

本工具**不内置任何密钥**，运行时从环境变量读取。请复制 `.env.example` 为 `.env` 并填入真实值：

```bash
cp .env.example .env
```

> `.env` 已被 `.gitignore` 忽略，不会被提交；Windows 用户也可参考 `scripts/windows/web_service.env.ps1.example`。

### 变量清单

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `PAYMENT_ADMIN_COOKIE` | ✅ 必填 | 星宿平台管理后台 Cookie，格式为 `ovsmgr_sid=xxx`。从浏览器开发者工具（Network → 任一管理后台请求 → Request Headers 的 Cookie）复制 `ovsmgr_sid` 值。 |
| `WEB_ACCESS_TOKEN` | 可选 | Web 服务访问令牌，用于保护 Web 页面。生产环境请改为随机强口令。 |
| `BOT_WEBHOOK_URL` | 可选 | 校验结果推送群机器人 Webhook 地址（含 key）。 |
| `BOT_DEBUG_WEBHOOK_URLS` | 可选 | 调试用 Webhook 地址，多个用逗号分隔。 |
| `PAYMENT_X_APP_ID` | 可选 | 内部应用标识（X-App-Id）。 |
| `ADMIN_API_BASE_URL` | 可选 | 管理后台 API 基址，默认占位 `https://example.com`，请改为实际内部地址。 |
| `PRODUCT_LISTNEW_BASE_URL` | 可选 | 商品列表接口基址。 |
| `PAY_WINDOW_ONLINE_BASE_URL` | 可选 | 线上支付橱窗基址。 |
| `PAY_WINDOW_TEST_BASE_URL` | 可选 | 测试环境支付橱窗基址。 |

`.env` 示例：

```dotenv
PAYMENT_ADMIN_COOKIE=ovsmgr_sid=你的真实cookie值
WEB_ACCESS_TOKEN=一段随机强口令
# 其余可选变量按需填写，留空即可使用默认值
```

## 目录结构

```
.
├── main.py                 # CLI 校验入口
├── run_web.py              # Web 服务入口（uvicorn）
├── config/                 # 配置与日志
├── parser/                 # 各类配置解析器
├── analysis_sku/           # SKU 分析
├── baseline_generator/     # 基线 / Excel 生成
├── webui/                  # Web 页面与接口
├── scripts/                # 运维脚本（含 .example 模板）
├── docs/                   # 接口 / 字段映射 / 使用 SOP 等文档
├── tests/                  # 测试
├── requirements.txt
├── .env.example            # 环境变量模板（复制为 .env 使用）
└── .gitignore
```

## 注意事项

- **敏感数据不入库**：`web_data/`、`logs/`、`支付页请求链路/`、`shop_info.json`、`shop_window.json`、`*.xlsx`、真实 `web_service.env.ps1` 等已在 `.gitignore` 中排除。
- 仓库内的 `@Author` 等署名为占位邮箱，发布前可替换为本人公开署名。
- 运行所需的真实 Cookie / Webhook / 内部 API 地址均由你本地的 `.env` 提供，请勿提交到版本库。
