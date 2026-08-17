# Excel格式与校验逻辑详解

## 一、Excel数据格式要求

### 1.1 列结构定义

Excel表格必须包含以下11列（从A列开始）：

| 列索引 | 列名 | 数据类型 | 说明 | 示例 | 必填 | 校验规则 |
|--------|------|----------|------|------|------|----------|
| 0 (A) | 国家 | 字符串 | 国家代码或名称 | MY、US、印度、T1 | ✅ | 必须填写 |
| 1 (B) | 会员类型 | 字符串 | 会员类型 | Pro、Premium | ✅ | 必须填写 |
| 2 (C) | 价格类型 | 字符串 | 价格类型名称 | 原价、折扣价 | ✅ | 必须填写，必须是支持的价格类型 |
| 3 (D) | 商品序号 | 数字 | 从1开始 | 1、2、3 | ✅ | 必须填写，必须是正整数 |
| 4 (E) | 周期 | 字符串 | 商品周期 | 1年、2年、3个月 | ✅ | 必须填写，格式：数字+单位（年/月） |
| 5 (F) | 总价 | 数字 | 美元总价 | 59.99 | ✅ | 必须填写，必须是正数 |
| 6 (G) | 均价 | 数字 | 美元/月 | 4.99 | ✅ | 必须填写，必须是正数 |
| 7 (H) | 价格ID | 数字 | 价格ID | 1530 | ⚠️ | 可留空，如果填写会进行校验 |
| 8 (I) | 商品ID | 数字 | 商品ID | 2800 | ⚠️ | 可留空，如果填写会进行校验；如果为空，该行会被跳过 |
| 9 (J) | 买赠周期 | 字符串 | 买赠周期 | 6个月 | ❌ | 原价类型可不填，其他类型建议填写 |
| 10 (K) | 橱窗ID | 字符串 | 格式：支付页：3553 或 支付：3553 | 支付页：3553 | ✅ | 必须填写，格式必须正确 |

### 1.2 合并单元格规则

**必须合并的列**：前3列（国家、会员类型、价格类型）

**合并规则**：
- 如果连续多行的前3列值相同，必须合并这些单元格
- 程序会自动填充合并单元格的空值（使用`ffill()`方法）

**示例**：
```
行2-5都是：MY | Pro | 原价
需要合并：A2:A5, B2:B5, C2:C5
```

### 1.3 橱窗ID格式要求

**支持的格式**：
1. `支付页：3553`（推荐）
2. `支付：3553`
3. `挽回：6187`（用于挽回橱窗ID，在K列）

**解析逻辑**：
- 程序会从字符串中提取数字ID
- 如果K列为空，会沿用上一行的橱窗ID
- 如果K列包含"挽回"关键字，会提取为挽回橱窗ID

### 1.4 支持的价格类型

| 价格类型 | 说明 | 适用平台 | 备注 |
|---------|------|---------|------|
| 原价 | 标准原价 | 全部 | 最常用 |
| 试用 / 试用价 | 试用价格 | 全部 |  |
| 折扣价 | 折扣后的价格 | 全部 |  |
| 首优原价 | 首次优惠原价 | 全部 |  |
| 折扣价-3天试用 | 折扣价带3天试用 | 全部 |  |
| 挽回 / 挽回价 | 挽回价格 | 全部 | 需要配置挽回橱窗ID |
| 挽回试用 | 挽回试用价格 | 全部 | 需要配置挽回橱窗ID |
| 一次性原价 | 一次性支付原价 | 全部 |  |
| 一次性折扣价 | 一次性支付折扣价 | 全部 |  |
| 一次性挽回价 | 一次性支付挽回价 | 全部 | 需要配置挽回橱窗ID |
| 加购 | 加购商品原价 | PC |  |
| 加购试用 / 试用加购 | 加购商品试用价 | PC |  |

## 二、数据提取逻辑

### 2.1 Excel文件读取

**实现位置**：`analysis_sku/analysis_sku.py`

**步骤**：
1. 使用pandas读取Excel文件：`pd.read_excel(file_path, sheet_name=sheet_index)`
2. 填充合并单元格的空值：
   ```python
   for col_name in ["国家", "会员类型", "价格类型"]:
       df[col_name] = df[col_name].ffill()  # 用前面的值填充
   ```
3. 逐行遍历数据：`for index, row in df.iterrows()`

### 2.2 橱窗ID提取

**实现位置**：`analysis_sku/analysis_sku.py` - `get_each_line_shop_window_id()`

**提取逻辑**：
```python
def get_each_line_shop_window_id(shop_window_id_value: str, index: int, previous_shop_window_id: int) -> int:
    # 1. 如果值为空或NaN，沿用上一行的橱窗ID
    if shop_window_id_value in [None, '', ' '] or pd.isna(shop_window_id_value):
        return previous_shop_window_id
    
    # 2. 如果包含"支付页"或"支付"关键字，提取数字ID
    if "支付页" in shop_window_id_value or "支付" in str(shop_window_id_value):
        match = re.search(r'\d+', shop_window_id_value)
        if match:
            return int(match.group())
    
    # 3. 其他情况沿用上一行的橱窗ID
    return previous_shop_window_id
```

**挽回橱窗ID提取**：
```python
# 从K列读取挽回橱窗ID（格式：挽回：6187）
if "挽回" in str(current_shop_window_id_value):
    match = re.search(r'\d+', str(current_shop_window_id_value))
    if match:
        excel_retain_id = int(match.group())
```

### 2.3 商品匹配逻辑

**实现位置**：`analysis_sku/analysis_sku.py`

**匹配策略**（优先级从高到低）：

1. **通过商品ID匹配**（优先）：
   - 遍历所有主商品组（`shop_items`）
   - 检查每个主商品的以下字段：
     - `origin_item_info`（原价商品）
     - `discount_origin_item_info`（折扣原价商品）
     - `trial_item_info`（试用商品）
     - `discount_trial_item_info`（折扣试用商品）
     - `one_time_origin_item_info`（一次性原价商品）
     - `one_time_discount_item_info`（一次性折扣商品）
   - 检查每个主商品的`add_buy_info`（加购商品组）：
     - 遍历所有加购商品组
     - 检查加购商品组的上述所有字段

2. **回退到索引匹配**：
   - 如果商品ID匹配失败，使用商品序号（`product_order`）作为索引
   - 从`shop_items_list[product_order]`获取商品
   - 如果索引越界，记录错误并跳过该行

**关键代码**：
```python
# 优先通过商品ID匹配
if excel_product_id:
    for shop_item in shop_items_list:
        # 检查主商品的各种商品类型
        if shop_item.get("origin_item_info") and shop_item["origin_item_info"].get("id") == excel_product_id:
            current_product_info = shop_item
            break
        
        # 检查加购商品组
        if shop_item.get("add_buy_info"):
            for add_buy_group in shop_item["add_buy_info"]:
                if add_buy_group.get("origin_item_info") and add_buy_group["origin_item_info"].get("id") == excel_product_id:
                    current_product_info = add_buy_group
                    break

# 如果商品ID匹配失败，回退到索引匹配
if current_product_info is None:
    try:
        current_product_info = shop_items_list[product_order]
    except IndexError:
        # 记录错误并跳过
        pass
```

## 三、数据校验逻辑

### 3.1 商品ID校验

**校验规则**：
- Excel中的商品ID必须与API返回的商品ID一致
- 如果Excel中商品ID为空，程序会从API获取并记录（不校验）

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
excel_product_id = current_row_data[product_id_index]
api_product_id = result_dict.get("product_id")

if pd.notna(excel_product_id) and excel_product_id not in [None, '', ' ']:
    if int(excel_product_id) != api_product_id:
        error_msg = f"第{index+2}行的【商品id】校验错误,单元格中值为: {excel_product_id}, 接口中的值为: {api_product_id}"
        error_config_msg.append(error_msg)
```

### 3.2 价格ID校验

**校验规则**：
- Excel中的价格ID必须与API返回的价格ID一致
- 如果Excel中价格ID为空，程序会从API获取并记录（不校验）

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
excel_price_id = current_row_data[price_id_index]
api_price_id = result_dict.get("price_id")

if pd.notna(excel_price_id) and excel_price_id not in [None, '', ' ']:
    if int(excel_price_id) != api_price_id:
        error_msg = f"第{index+2}行的【价格id】校验错误,单元格中值为: {excel_price_id}, 接口中的值为: {api_price_id}"
        error_config_msg.append(error_msg)
```

### 3.3 总价校验

**校验规则**：
- Excel中的总价必须与API返回的总价一致
- 允许误差：±0.5美元（`PRICE_THRESHOLD = 0.5`）
- 优先使用美化价格的总价，如果没有则使用API原始总价
- 单位：统一使用美元（USD）

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
excel_total_price = float(current_row_data[total_price_index])
api_total_price = result_dict.get("total_price")
beautiful_total_price = result_dict.get("beautiful_total_price")

# 优先使用美化价格
compare_price = beautiful_total_price if beautiful_total_price else api_total_price

if abs(excel_total_price - compare_price) > PRICE_THRESHOLD:
    error_msg = f"第{index+2}行的【总价】校验错误,单元格中值为: {excel_total_price}, 接口中的值为: {api_total_price}, 对应美化价格的总价为: {beautiful_total_price}"
    error_config_msg.append(error_msg)
```

### 3.4 月均价校验

**校验规则**：
- Excel中的月均价必须与API计算的月均价一致
- 允许误差：±0.5美元（`PRICE_THRESHOLD = 0.5`）
- 计算公式：`月均价 = 总价 / (周期月数 + 加赠月数)`
- 单位：统一使用美元（USD）

**计算公式详解**：
```python
# 1. 获取主周期月数
main_period = shop_item_info.get("period")  # 例如：24（2年）
main_period_unit = shop_item_info.get("period_unit")  # 例如："M"（月）或"Y"（年）
main_cycle = get_cycle(main_period, main_period_unit)  # 转换为月数：24

# 2. 获取加赠月数
give_cycle = shop_item_info.get("give_cycle", 0)  # 例如：6
give_unit = shop_item_info.get("give_unit")  # 例如："M"（月）
give_cycle_months = get_give_cycle_months(give_cycle, give_unit)  # 转换为月数：6

# 3. 计算总周期
total_cycle = main_cycle + give_cycle_months  # 24 + 6 = 30

# 4. 计算月均价（使用USD价格）
price_usd = price_detail.get("price_usd")  # 例如：179.97
monthly_avg_price = price_usd / total_cycle  # 179.97 / 30 = 5.999
```

**实现位置**：`parser/shop_item_new_parser.py` - 所有价格类型解析方法

**校验代码**：
```python
excel_avg_price = float(current_row_data[avg_price_index])
api_avg_price = result_dict.get("avg_price")

if abs(excel_avg_price - api_avg_price) > PRICE_THRESHOLD:
    error_msg = f"第{index+2}行的【月均价】校验错误,单元格中值为: {excel_avg_price}, 接口中的值为: {api_avg_price}"
    error_config_msg.append(error_msg)
```

### 3.5 商品周期校验

**校验规则**：
- Excel中的商品周期必须与API返回的商品周期一致
- 格式：支持"1年"、"2年"、"3个月"、"6个月"等

**周期转换逻辑**：
```python
def get_cycle(period: int, period_unit: str) -> int:
    """将周期转换为月数"""
    if period_unit == "Y":  # 年
        return period * 12
    elif period_unit == "M":  # 月
        return period
    else:
        return 1  # 默认1个月
```

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
excel_cycle = str(current_row_data[cycle_index])
api_cycle = result_dict.get("main_period")  # 例如："2年"

if excel_cycle != api_cycle:
    error_msg = f"第{index+2}行的【商品周期】校验错误,单元格中值为: {excel_cycle}, 接口中的值为: {api_cycle}"
    error_config_msg.append(error_msg)
```

### 3.6 买赠周期校验

**校验规则**：
- Excel中的买赠周期必须与API返回的买赠周期一致
- 格式：支持"买赠6个月"、"买赠12个月"等
- 原价类型可以不填，其他类型建议填写

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
excel_give_cycle = current_row_data[product_give_cycle_index]
api_give_cycle = result_dict.get("give_cycle_str")  # 例如："买赠6个月"

if pd.notna(excel_give_cycle) and excel_give_cycle not in [None, '', ' ']:
    if excel_give_cycle != api_give_cycle:
        error_msg = f"第{index+2}行的【买赠周期】校验错误,单元格中值为: {excel_give_cycle}, 接口中的值为: {api_give_cycle}"
        error_config_msg.append(error_msg)
```

### 3.7 商品名称校验

**校验规则**：
- 检查商品名称中是否包含非法字符（如`%d`）

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
product_name = result_dict.get("name", "")
if "%d" in product_name:
    error_msg = f"第{index+2}行的【商品名称】非法字符校验错误,商品名称包含非法字符%d: {product_name}"
    error_config_msg.append(error_msg)
```

### 3.8 三方价格名称校验

**校验规则**：
- 检查三方价格名称中是否包含空格

**实现位置**：`analysis_sku/analysis_sku.py`

**校验代码**：
```python
third_party_price_name = result_dict.get("third_party_price_name", "")
if " " in third_party_price_name:
    error_msg = f"第{index+2}行的【商品三方价格名称】校验错误,三方价格名称包含空格: {third_party_price_name}"
    error_config_msg.append(error_msg)
```

## 四、错误处理逻辑

### 4.1 数据缺失处理

**场景**：
- Excel中商品ID为空
- API返回数据为空
- 商品匹配失败

**处理策略**：
1. **商品ID为空**：跳过该行，不进行校验
2. **API返回数据为空**：记录警告日志，跳过该行
3. **商品匹配失败**：记录警告日志，回退到索引匹配；如果索引匹配也失败，记录错误并跳过该行

### 4.2 数据转换失败处理

**场景**：
- 商品ID转换失败（非数字）
- 价格ID转换失败（非数字）
- 总价/月均价转换失败（非数字）

**处理策略**：
- 捕获`ValueError`、`TypeError`异常
- 记录警告日志
- 使用默认值或跳过该行

### 4.3 API请求失败处理

**场景**：
- 网络超时
- HTTP错误（500、502等）
- SSL证书错误

**处理策略**：
- 自动重试（最多3次，指数退避）
- 记录错误日志
- 如果重试失败，跳过该行继续执行

## 五、校验报告生成

### 5.1 错误汇总

**实现位置**：`analysis_sku/analysis_sku.py` - `send_check_error_msg_bot()`

**错误分类**：
- 商品ID校验错误
- 价格ID校验错误
- 总价校验错误
- 月均价校验错误
- 商品周期校验错误
- 买赠周期校验错误
- 商品名称校验错误
- 三方价格名称校验错误
- 价格类型未命中

### 5.2 报告格式

**Bot消息格式**：
```json
{
  "msgtype": "text",
  "text": {
    "content": "支付配置校验报告\n\n总错误数: 10\n\n详细错误:\n1. 第2行的【总价】校验错误..."
  }
}
```

**日志格式**：
- 所有校验结果都会记录到日志文件（`logs/YYYYMMDD.log`）
- 日志级别：INFO（校验通过）、WARNING（警告）、ERROR（校验失败）

---

**最后更新**: 2026-02-09
