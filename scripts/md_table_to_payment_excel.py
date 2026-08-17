# -*- coding: utf-8 -*-
"""
将 wps-doc 导出的 Markdown（含「管道表格」）转为支付配置校验用 xlsx。

衔接方式：
  python scripts/md_table_to_payment_excel.py path/to/export.md -o from_kdocs.xlsx
  再在 main.py 里把 excel_file_path 指向 from_kdocs.xlsx，sheet_index=0。

注意：智能文档里若插入的是「在线表格组件」（导出仅为 spreadsheet 块、无单元格），
本脚本无法从 .md 取数；请改为在文档中插入原生 Markdown 表格，或下载 xlsx 后用原流程。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

# 与 generate_excel_template.py / analysis_sku 期望一致（列顺序固定）
CANONICAL_HEADERS = [
    "国家",
    "会员类型",
    "价格类型",
    "商品序号",
    "周期",
    "总价",
    "均价",
    "价格ID",
    "商品ID",
    "买赠周期",
    "橱窗ID",
]

# 云文档/口语别名 -> 标准表头
HEADER_ALIASES = {
    "月均价": "均价",
    "商品id": "商品ID",
    "价格id": "价格ID",
    "橱窗id": "橱窗ID",
}


def _is_separator_row(line: str) -> bool:
    s = line.replace(" ", "").replace("|", "")
    return bool(s) and all(c in "-:" for c in s)


def parse_md_pipe_tables(text: str) -> list[list[str]]:
    """从全文提取管道表格行（支持多个表，取列数与表头匹配的那一个）。"""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            lines.append(line)

    if not lines:
        return []

    # 按空行/非表行断表太复杂；这里合并连续表行，遇到分隔行则开始新表
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in lines:
        if _is_separator_row(line):
            if current:
                tables.append(current)
                current = []
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        current.append(cells)
    if current:
        tables.append(current)

    best = []
    ncols = len(CANONICAL_HEADERS)
    for tbl in tables:
        if not tbl:
            continue
        header = tbl[0]
        # 表头列数对齐 11 列的表优先
        if len(header) == ncols:
            return tbl
        if len(header) >= 8 and len(tbl) > len(best):
            best = tbl
    return best


def normalize_header(h: str) -> str:
    h = (h or "").strip()
    return HEADER_ALIASES.get(h.lower(), HEADER_ALIASES.get(h, h))


def md_text_to_dataframe(text: str) -> pd.DataFrame:
    rows = parse_md_pipe_tables(text)
    if len(rows) < 2:
        raise ValueError(
            "未解析到有效的 Markdown 管道表格（至少需要表头+1 行数据）。"
            "若文档是在智能文档里插入的在线表格，导出往往只有 spreadsheet 块而无表格内容，"
            "请改用文档内 Markdown 表格，或导出/下载 xlsx。"
        )

    header = [normalize_header(x) for x in rows[0]]
    body = rows[1:]
    df = pd.DataFrame(body, columns=header)

    missing = [h for h in CANONICAL_HEADERS if h not in df.columns]
    if missing:
        raise ValueError(f"缺少列（与模板不一致）: {missing}；当前列: {list(df.columns)}")

    df = df[CANONICAL_HEADERS].copy()

    # 与 Excel 行为接近：数值列尝试转换
    for col in ("商品序号", "总价", "均价"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in CANONICAL_HEADERS:
        if col in ("商品序号", "总价", "均价"):
            continue
        df[col] = df[col].apply(lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip())

    return df


def convert_md_file_to_xlsx(md_path: Path, xlsx_path: Path, sheet_name: str = "Sheet1") -> None:
    text = md_path.read_text(encoding="utf-8")
    df = md_text_to_dataframe(text)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(xlsx_path, index=False, sheet_name=sheet_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown 管道表 -> payment_config 用 xlsx")
    parser.add_argument("md_path", type=Path, help="wps-doc export 生成的 .md 路径")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("from_kdocs_export.xlsx"),
        help="输出 xlsx 路径（默认 from_kdocs_export.xlsx）",
    )
    parser.add_argument("-s", "--sheet", default="Sheet1", help="工作表名")
    args = parser.parse_args()
    if not args.md_path.is_file():
        print(f"文件不存在: {args.md_path}", file=sys.stderr)
        return 1
    try:
        convert_md_file_to_xlsx(args.md_path, args.output, args.sheet)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"已写入: {args.output.resolve()}")
    print("下一步: 在 main.py 中设置 excel_file_path 为该文件，sheet_index=0（或你的目标 sheet）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
