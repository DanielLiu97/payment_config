import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional

import pandas as pd
from analysis_sku.analysis_sku import analysis_sku_xls_file_new, send_check_error_msg_bot
from config.config import EXCEL_COLUMN_INDEX
from config.logger import logger


@dataclass
class RunParams:
    file_path: str
    env: str
    country: str
    platform: str
    is_uwp: bool
    sheet_index: int
    sheet_indices: Optional[List[int]]
    cookie: str
    initiator: str
    only_row_numbers: Optional[List[int]]
    send_bot: bool
    debug_bot: bool = False
    task_id: str = ""
    restart: bool = False
    restart_index: int = 0
    restart_shop_window_id: int = 0
    restart_end_index: Optional[int] = None


_CRITICAL_LOG_PATTERNS = [
    r"get_target_info_by_condition执行异常",
    r"get_target_info_by_condition返回空字典",
    r"获取主橱窗商品列表失败",
    r"主橱窗商品列表为空",
    r"request shop_window failed",
    r"no shop_window was found",
]


def _redact_params(params: RunParams) -> dict:
    data = asdict(params)
    cookie = data.get("cookie") or ""
    if cookie:
        data["cookie"] = cookie[:12] + "***"
    return data


def _attach_task_log_handler(log_file: str) -> logging.Handler:
    formatter = logging.Formatter("[%(asctime)s][%(filename)s %(lineno)d][%(levelname)s]: %(message)s")
    handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return handler


def _read_log_delta(log_file: str, start_offset: int) -> str:
    if not os.path.exists(log_file):
        return ""
    with open(log_file, "rb") as f:
        f.seek(max(0, int(start_offset)))
        data = f.read()
    return data.decode("utf-8", errors="ignore")


def _collect_unreported_critical_errors(log_delta: str, existing_errors: List[str]) -> List[str]:
    if not log_delta:
        return []
    existing_text = "\n".join(existing_errors or [])
    pattern = re.compile("|".join(_CRITICAL_LOG_PATTERNS))
    extras = []
    for line in log_delta.splitlines():
        # 仅兜底 ERROR 级日志，避免把“重试中的 WARNING”误判为最终错误
        if "[ERROR]" not in line:
            continue
        if not pattern.search(line):
            continue
        message = line
        if "]: " in line:
            message = line.split("]: ", 1)[1].strip()
        if message and message not in existing_text and message not in extras:
            extras.append(message)
    return extras


def run_validation(
    params: RunParams,
    task_dir: str,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    os.makedirs(task_dir, exist_ok=True)
    task_log = os.path.join(task_dir, "task.log")
    handler = _attach_task_log_handler(task_log)
    try:
        sheet_indices = params.sheet_indices or [params.sheet_index]
        sheet_indices = [int(i) for i in sheet_indices if int(i) >= 0]
        if not sheet_indices:
            raise ValueError("未提供有效的sheet序号")
        sheet_indices = sorted(set(sheet_indices))

        excel_file = None
        try:
            excel_file = pd.ExcelFile(params.file_path)
            sheet_names = list(excel_file.sheet_names)
        except Exception:
            sheet_names = []
        finally:
            if excel_file is not None:
                excel_file.close()

        product_id_col = int(EXCEL_COLUMN_INDEX.get("product_id", 8))

        def _is_effective_product_id(value) -> bool:
            if value is None:
                return False
            if pd.isna(value):
                return False
            text = str(value).strip()
            if not text or text == "商品id":
                return False
            return True

        def _estimate_effective_rows(sheet_idx: int) -> int:
            try:
                df = pd.read_excel(params.file_path, sheet_name=sheet_idx)
                if df.empty:
                    return 0
                if product_id_col >= len(df.columns):
                    return 0
                if params.only_row_numbers:
                    valid = [r for r in params.only_row_numbers if 2 <= r <= len(df) + 1]
                    count = 0
                    for row_no in valid:
                        row_idx = row_no - 2
                        if _is_effective_product_id(df.iloc[row_idx, product_id_col]):
                            count += 1
                    return count
                series = df.iloc[:, product_id_col]
                return int(series.apply(_is_effective_product_id).sum())
            except Exception:
                return 0

        per_sheet_totals = {idx: _estimate_effective_rows(idx) for idx in sheet_indices}
        empty_sheets = [idx for idx, total in per_sheet_totals.items() if total <= 0]
        if empty_sheets:
            names = [
                (sheet_names[idx] if idx < len(sheet_names) else f"Sheet{idx + 1}")
                for idx in empty_sheets
            ]
            details = "、".join([f"Sheet{idx + 1}({name})" for idx, name in zip(empty_sheets, names)])
            result = {
                "ok": False,
                "error_count": 1,
                "errors": [f"未检测到可校验数据（有效商品ID）: {details}。请检查是否仅有表头或商品ID列为空。"],
                "sheet_results": [
                    {
                        "sheet_index": idx,
                        "sheet_number": idx + 1,
                        "sheet_name": (sheet_names[idx] if idx < len(sheet_names) else f"Sheet{idx + 1}"),
                        "error_count": -1,
                    }
                    for idx in empty_sheets
                ],
                "params": _redact_params(params),
                "log_file": task_log,
            }
            with open(os.path.join(task_dir, "result.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return result

        grand_total = sum(per_sheet_totals.values())
        done_before = 0

        all_errors = []
        sheet_results = []
        for sheet_idx in sheet_indices:
            current_total = per_sheet_totals.get(sheet_idx, 0)
            log_offset_before_sheet = os.path.getsize(task_log) if os.path.exists(task_log) else 0

            def _progress(c: int, t: int, r: int):
                if not progress_callback:
                    return
                effective_total = grand_total if grand_total > 0 else max(1, t)
                progress_callback(done_before + c, effective_total, r)

            errors = analysis_sku_xls_file_new(
                params.file_path,
                params.env,
                params.country,
                params.platform,
                params.is_uwp,
                sheet_idx,
                params.cookie,
                params.restart,
                params.restart_index,
                params.restart_shop_window_id,
                params.restart_end_index,
                params.only_row_numbers,
                progress_callback=_progress,
            )
            # 收口保险：如果日志里有关键ERROR/WARNING但返回errors漏了，自动补记，防止假通过
            log_delta = _read_log_delta(task_log, log_offset_before_sheet)
            extra_errors = _collect_unreported_critical_errors(log_delta, errors)
            if extra_errors:
                logger.warning("检测到日志关键错误未进入结果列表，自动补记 %s 条", len(extra_errors))
                errors = (errors or []) + extra_errors
            sheet_name = (
                sheet_names[sheet_idx]
                if sheet_idx < len(sheet_names)
                else f"Sheet{sheet_idx + 1}"
            )
            sheet_results.append(
                {
                    "sheet_index": sheet_idx,
                    "sheet_number": sheet_idx + 1,
                    "sheet_name": sheet_name,
                    "error_count": len(errors),
                }
            )
            if len(sheet_indices) > 1 and errors:
                all_errors.extend([f"[{sheet_name}] {e}" for e in errors])
            else:
                all_errors.extend(errors)
            if params.debug_bot:
                send_check_error_msg_bot(
                    errors,
                    params.file_path,
                    sheet_idx,
                    task_id=params.task_id,
                    initiator=params.initiator,
                    platform=params.platform,
                    debug_only=True,
                )
            elif params.send_bot:
                send_check_error_msg_bot(
                    errors,
                    params.file_path,
                    sheet_idx,
                    task_id=params.task_id,
                    initiator=params.initiator,
                    platform=params.platform,
                    debug_only=False,
                )
            done_before += current_total

        result = {
            "ok": True,
            "error_count": len(all_errors),
            "errors": all_errors,
            "sheet_results": sheet_results,
            "params": _redact_params(params),
            "log_file": task_log,
        }
        with open(os.path.join(task_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("任务执行失败: %s", exc)
        result = {
            "ok": False,
            "error_count": -1,
            "errors": [f"任务执行异常: {exc}"],
            "params": _redact_params(params),
            "log_file": task_log,
        }
        with open(os.path.join(task_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    finally:
        logger.removeHandler(handler)
        handler.close()

