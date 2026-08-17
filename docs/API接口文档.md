# API接口文档

## 一、支付橱窗API

### 1.1 接口说明

**用途**：获取橱窗配置数据（商品列表、加购商品组、挽回橱窗ID等）

**实现位置**：`parser/shop_window_parser.py`

### 1.2 请求信息

**URL格式**：
```
{base_url}/api/v1/pay_window/type/{platform}?shopwindow_id={shopwindow_id}&lang=zh-CN&platform={platform}&mock_country={mock_country}
```

**环境配置**：
- **线上环境**：`http://example.com`
- **测试环境**：`http://example.com`

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| platform | string | ✅ | 平台类型 | pc、android、ios |
| shopwindow_id | int | ✅ | 橱窗ID | 7302 |
| lang | string | ✅ | 语言 | zh-CN |
| mock_country | string | ✅ | 国家代码 | MY、US、IN |

**UWP平台特殊参数**：
- 如果`is_uwp=True`，URL会添加`&channel=00100.00000802`参数

### 1.3 响应结构

**响应示例**：
```json
{
  "data": {
    "list": [
      {
        "id": 7302,
        "shop_items": [
          {
            "origin_item_info": {
              "id": 2800,
              "sku_id": 4390,
              "name": "WPS Office Premium",
              "period": 24,
              "period_unit": "M",
              "amount": 14376,
              "avg_price_amount_num": 599
            },
            "discount_origin_item_info": {
              "id": 7364,
              "sku_id": 6044,
              "name": "WPS Office Premium Discount",
              "period": 24,
              "period_unit": "M",
              "amount": 7999,
              "avg_price_amount_num": 333
            },
            "trial_item_info": {
              "id": 2637,
              "sku_id": 4391,
              "name": "WPS Office Premium Trial",
              "period": 12,
              "period_unit": "M",
              "amount": 7188,
              "avg_price_amount_num": 599
            },
            "add_buy_info": [
              {
                "origin_item_info": {
                  "id": 7408,
                  "sku_id": 6048,
                  "name": "Add-on Product",
                  "period": 3,
                  "period_unit": "M",
                  "amount": 4799,
                  "avg_price_amount_num": 1599
                },
                "trial_item_info": {
                  "id": 7409,
                  "sku_id": 6049,
                  "name": "Add-on Product Trial",
                  "period": 3,
                  "period_unit": "M",
                  "amount": 4799,
                  "avg_price_amount_num": 1599
                }
              }
            ]
          }
        ],
        "retain_id": 7334,
        "coupon_shop_ids": "6185,6186",
        "pay_add_buy_window_ids": "7407,7408"
      }
    ]
  }
}
```

**关键字段说明**：

| 字段路径 | 类型 | 说明 |
|---------|------|------|
| `data.list[0].shop_items` | array | 主商品组列表 |
| `data.list[0].shop_items[].origin_item_info` | object | 原价商品信息 |
| `data.list[0].shop_items[].discount_origin_item_info` | object | 折扣原价商品信息 |
| `data.list[0].shop_items[].trial_item_info` | object | 试用商品信息 |
| `data.list[0].shop_items[].add_buy_info` | array | 加购商品组列表 |
| `data.list[0].retain_id` | int | 挽回橱窗ID |
| `data.list[0].coupon_shop_ids` | string | 优惠券橱窗ID列表（逗号分隔） |

### 1.4 使用示例

```python
from parser.shop_window_parser import ShopWindowParser

# 创建解析器
shop_window_parser = ShopWindowParser(
    shop_window_id=7302,
    mode="online",
    mock_country="MY",
    platform="pc",
    is_uwp=False
)

# 获取主商品组
shop_items = shop_window_parser.get_shop_window_inner_obj_by_name("shop_items")

# 获取挽回橱窗ID
retain_id = shop_window_parser.get_retain_id()
```

## 二、价格列表API（星宿平台管理后台）

### 2.1 接口说明

**用途**：根据SKU ID查询价格列表

**实现位置**：`utils/utils.py`

### 2.2 请求信息

**URL格式**：
```
https://example.com/manage/1/price/list?page_num=1&page_size=20&kpay_sku_ids={sku_id}
```

**请求方法**：GET

**请求头**：
```
Cookie: ovsmgr_sid=xxx
```

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| page_num | int | ✅ | 页码 | 1 |
| page_size | int | ✅ | 每页数量 | 20 |
| kpay_sku_ids | int | ✅ | SKU ID | 4390 |

### 2.3 响应结构

**响应示例**：
```json
{
  "data": {
    "list": [
      {
        "id": 1530,
        "sku_id": 4390,
        "price_usd": 143.76,
        "first_exp_price_usd": 143.76,
        "price_name": "sub_2y_0t_143.76_"
      }
    ]
  }
}
```

**关键字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.list[].id` | int | 价格ID |
| `data.list[].sku_id` | int | SKU ID |
| `data.list[].price_usd` | float | 价格（USD） |
| `data.list[].first_exp_price_usd` | float | 首次体验价格（USD） |
| `data.list[].price_name` | string | 价格名称 |

### 2.4 使用示例

```python
from utils.utils import get_price_beautiful_by_sku_id

# 获取价格详情
price_detail = get_price_beautiful_by_sku_id(sku_id=4390, cookie="ovsmgr_sid=xxx")
price_id = price_detail.get("price_id")
price_usd = price_detail.get("price_usd")
```

## 三、价格详情API（星宿平台管理后台）

### 3.1 接口说明

**用途**：获取价格详细信息

**实现位置**：`utils/utils.py`

### 3.2 请求信息

**URL格式**：
```
https://example.com/manage/1/price/{price_id}
```

**请求方法**：GET

**请求头**：
```
Cookie: ovsmgr_sid=xxx
```

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| price_id | int | ✅ | 价格ID | 1530 |

### 3.3 响应结构

**响应示例**：
```json
{
  "data": {
    "id": 1530,
    "sku_id": 4390,
    "price_usd": 143.76,
    "first_exp_price_usd": 143.76,
    "price_name": "sub_2y_0t_143.76_",
    "beautiful_price": {
      "total_price_usd": 143.76,
      "monthly_price_usd": 5.99
    }
  }
}
```

**关键字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.id` | int | 价格ID |
| `data.sku_id` | int | SKU ID |
| `data.price_usd` | float | 价格（USD） |
| `data.first_exp_price_usd` | float | 首次体验价格（USD） |
| `data.beautiful_price.total_price_usd` | float | 美化价格总价（USD） |
| `data.beautiful_price.monthly_price_usd` | float | 美化价格月均价（USD） |

### 3.4 使用示例

```python
from utils.utils import get_price_beautiful_by_sku_id

# 获取价格详情（包含美化价格）
price_detail = get_price_beautiful_by_sku_id(sku_id=4390, cookie="ovsmgr_sid=xxx")
beautiful_total_price = price_detail.get("beautiful_total_price")
```

## 四、Bot Webhook API

### 4.1 接口说明

**用途**：发送校验结果到企业微信/钉钉等

**实现位置**：`analysis_sku/analysis_sku.py` - `send_check_error_msg_bot()`

### 4.2 请求信息

**URL格式**：
```
https://xz.wps.cn/api/v1/webhook/send?key={key}
```

**请求方法**：POST

**请求头**：
```
Content-Type: application/json
```

**请求体**：
```json
{
  "msgtype": "text",
  "text": {
    "content": "支付配置校验报告\n\n总错误数: 10\n\n详细错误:\n1. 第2行的【总价】校验错误..."
  }
}
```

### 4.3 响应结构

**成功响应**：
```json
{
  "errcode": 0,
  "errmsg": "ok"
}
```

**失败响应**：
```json
{
  "errcode": 40001,
  "errmsg": "invalid key"
}
```

## 五、API调用流程

### 5.1 完整调用流程

```
1. 读取Excel文件，提取配置数据
   ↓
2. 调用支付橱窗API，获取橱窗配置
   - 获取主商品组（shop_items）
   - 获取加购商品组（add_buy_info）
   - 获取挽回橱窗ID（retain_id）
   ↓
3. 根据价格类型，调用对应的解析方法
   - 获取商品信息（商品ID、SKU ID等）
   ↓
4. 调用价格列表API，获取价格ID
   - 根据SKU ID查询价格列表
   ↓
5. 调用价格详情API，获取价格详情
   - 根据价格ID获取价格详情
   - 获取美化价格信息
   ↓
6. 对比Excel和API数据，生成校验报告
   ↓
7. 调用Bot Webhook API，发送校验结果
```

### 5.2 错误处理

**重试机制**：
- 最大重试次数：3次
- 重试延迟：1秒（首次），每次重试延迟时间翻倍
- 超时时间：30秒
- 重试条件：HTTP状态码为408, 429, 500, 502, 503, 504

**错误处理**：
- 网络超时：自动重试
- HTTP错误：记录错误日志，跳过该行
- 数据缺失：记录警告日志，跳过该行

## 六、认证说明

### 6.1 Cookie获取

**星宿平台管理后台API**需要Cookie认证：

1. 登录星宿平台管理后台：`https://example.com/`
2. 打开浏览器开发者工具（F12）
3. 查看Network请求，找到Cookie：`ovsmgr_sid=xxx`
4. 将Cookie复制到`main.py`的`cookie`配置中

**Cookie格式**：
```
ovsmgr_sid=xxx
```

**Cookie有效期**：
- Cookie可能会过期，如果API请求返回401或403，需要重新获取Cookie

### 6.2 支付橱窗API认证

**支付橱窗API**不需要认证，可以直接访问。

---

**最后更新**: 2026-02-09
