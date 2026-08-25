"""V3-9 体脂秤"身体测量报告"图片导入：视觉抽取 → 校验（失败重试 1 次）→ 确认批量入库。

纪律（仿 services/screenshot.py 模式，不改动 screenshot.py）：
- 视觉调用固定走 adapters.llm.vision_extract（Kimi 多模态），含 llm_call 记账；
- JSON 解析复用 screenshot.parse_json_content / ExtractionError（禁止复制粘贴）；
- 识别结果不落库，confirm_import 才是唯一入库入口（按 (date, type) 幂等 upsert）；
- 新指标软区间：越界仅警告（warning），不拦截入库；
- sync_xunji 勾选后仅 weight/bodyfat（SYNCABLE_TYPES）走训记三段式同步。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.llm import vision_extract
from app.services.body_metrics import (
    METRIC_TYPES,
    SYNCABLE_TYPES,
    BodyMetricValidationError,
    range_warning,
    to_dict,
    upsert_body_metric,
)
from app.services.screenshot import ExtractionError, parse_json_content

_FULL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 无年份日期：08-18 / 8/18 / 8月18日
_YEARLESS_DATE_RE = re.compile(r"^(\d{1,2})\s*(?:[-/月])\s*(\d{1,2})\s*日?$")


# ---------- prompt ----------


def build_prompt(feedback: str | None = None) -> str:
    """构造视觉抽取 prompt；feedback 非空时附上次校验错误让模型自我修正。"""
    prompt = (
        "你是健康数据结构化助手。请识别这张体脂秤「身体测量报告」图片，抽取全部数值指标，"
        "只输出严格 JSON（不要输出任何其他文字，不要用代码块包裹）。字段：\n"
        "{\n"
        '  "schema": "body_scale_v1",   // 固定值\n'
        '  "date": "YYYY-MM-DD",        // 测量日期，必填；图片若只有"8月18日"无年份，只输出 "MM-DD"（如 08-18），不要猜测年份\n'
        '  "metrics": [                 // 必填，至少一条\n'
        '    {"type": "指标类型", "value": 数值}\n'
        "  ]\n"
        "}\n"
        "指标名 → type 映射表（只输出表中数值型指标）：\n"
        "- 体重 → weight（kg）\n"
        "- 脂肪率/体脂率 → bodyfat（%）\n"
        "- 内脏脂肪指数 → visceral_fat（级）\n"
        "- 基础代谢率 → bmr（kcal）\n"
        "- 肌肉率 → muscle_rate（%）\n"
        "- 水分/水分率 → water_rate（%）\n"
        "- 蛋白质 → protein_rate（%）\n"
        "- 骨量 → bone_mass（kg）\n"
        "- 储肌能力等级 → muscle_ability（级）\n"
        "- BMI → bmi\n"
        "- 身体年龄 → body_age（岁）\n"
        "- 总分/身体评分 → body_score（分）\n"
        "规则：\n"
        "- 图片中所有数值型指标都要抽取，value 为纯数字（去掉单位）；\n"
        "- 文本类指标（如身体类型「偏胖型」）不要输出到 metrics；\n"
        "- date 有年份时输出 YYYY-MM-DD；无年份时只输出 MM-DD（服务端默认补当前年）；\n"
        "- 没有出现的指标不要编造；\n"
        "- 只输出 JSON。"
    )
    if feedback:
        prompt += f"\n\n上次输出未通过校验：{feedback}。请修正后重新输出严格 JSON。"
    return prompt


# ---------- 规范化（数值化 + 无年份日期默认当前年） ----------


def _resolve_date(raw: Any, today: date) -> str:
    """无年份日期（08-18 / 8/18 / 8月18日）补当前年；完整 ISO 日期原样返回。"""
    text = str(raw or "").strip()
    if _FULL_DATE_RE.match(text):
        return text
    m = _YEARLESS_DATE_RE.match(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            return date(today.year, month, day).isoformat()
        except ValueError:
            return text
    return text


def normalize_extraction(data: Any, today: date | None = None) -> dict:
    """规范化模型输出：value 数值化（字符串转 float）、未知类型剔除、无年份日期补当前年。"""
    today = today or date.today()
    if not isinstance(data, dict):
        return {"date": "", "metrics": []}
    out: dict[str, Any] = {
        "schema": data.get("schema"),
        "date": _resolve_date(data.get("date"), today),
        "metrics": [],
    }
    metrics = data.get("metrics")
    if not isinstance(metrics, list):
        return out
    for item in metrics:
        if not isinstance(item, dict):
            continue
        type_ = item.get("type")
        if not isinstance(type_, str) or type_ not in METRIC_TYPES:
            continue  # 未知类型（含文本类指标）剔除
        value = item.get("value")
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                pass  # 留给 validate 报错
        out["metrics"].append({"type": type_, "value": value})
    return out


# ---------- Schema 校验 ----------


def validate_extraction(data: Any) -> list[str]:
    """校验规范化后的识别结果，返回错误列表（空列表 = 合法）。越界仅警告，不在此拦截。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["整体必须是 JSON 对象"]

    raw_date = data.get("date")
    if not isinstance(raw_date, str) or not raw_date:
        errors.append("缺少 date")
    else:
        try:
            date.fromisoformat(raw_date)
        except ValueError:
            errors.append(f"date 格式非法：{raw_date!r}（应为 YYYY-MM-DD）")

    metrics = data.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        errors.append("metrics 必须是非空数组")
        return errors
    for i, item in enumerate(metrics):
        if not isinstance(item, dict):
            errors.append(f"metrics[{i}] 必须是对象")
            continue
        type_ = item.get("type")
        if not isinstance(type_, str) or type_ not in METRIC_TYPES:
            errors.append(f"metrics[{i}].type 不支持的指标类型：{type_!r}")
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"metrics[{i}].value 必须是数值：{value!r}")
    return errors


# ---------- 识别编排（校验失败自动重试 1 次） ----------


def extract_from_image(
    image_bytes: bytes,
    *,
    session: Session | None = None,
    mime: str = "image/jpeg",
) -> dict:
    """调视觉模型抽取并校验；不合法时附错误反馈重试 1 次，仍失败抛 ExtractionError。

    返回 {"schema", "date", "metrics": [{type, value, warning?}]}；越界值保留并附 warning。
    """
    feedback: str | None = None
    last_error = ""
    for _attempt in range(2):
        result = vision_extract(image_bytes, build_prompt(feedback), session=session, mime=mime)
        try:
            raw = parse_json_content(result["content"])
        except ExtractionError as exc:
            last_error = str(exc)
        else:
            data = normalize_extraction(raw)
            errors = validate_extraction(data)
            if not errors:
                for item in data["metrics"]:
                    warning = range_warning(item["type"], item["value"])
                    if warning:
                        item["warning"] = warning
                return data
            last_error = "；".join(errors)
        feedback = last_error
    raise ExtractionError(f"识别结果两次校验均不合法：{last_error}")


# ---------- 确认批量入库 ----------


def confirm_import(
    session: Session,
    day: date,
    metrics: list[dict],
    *,
    sync_xunji: bool = False,
    body_client: Any = None,
    user_id: int | None = None,
) -> dict:
    """用户确认后批量入库：selected=true 的指标按 (date, type) upsert（幂等）。

    sync_xunji=True 时，weight/bodyfat（SYNCABLE_TYPES）走训记三段式同步：
    dry_run 预览 → confirmed 执行 → 置 synced_to_xunji。
    """
    imported = []
    warnings: list[str] = []
    for item in metrics:
        if not isinstance(item, dict) or not item.get("selected", True):
            continue
        type_ = item.get("type")
        value = item.get("value")
        row = upsert_body_metric(session, day, type_, value, user_id=user_id)  # 非法类型/数值抛 BodyMetricValidationError
        warning = range_warning(row.type, row.value)
        if warning:
            warnings.append(warning)
        imported.append(row)

    sync_result = None
    targets = [r for r in imported if r.type in SYNCABLE_TYPES]
    if sync_xunji and targets:
        if body_client is None:
            raise BodyMetricValidationError("同步训记需要 body_client")
        records = [
            {"datestr": r.date.isoformat(), "type": r.type, "value": r.value} for r in targets
        ]
        body_client.upsert_body_metrics(records, dry_run=True)  # 第一段：预览
        data = body_client.upsert_body_metrics(records, dry_run=False, confirmed=True)
        for r in targets:
            r.synced_to_xunji = True
        session.commit()
        sync_result = {
            "status": "synced",
            "summary": (data.get("res") or {}).get("summary") or "",
        }

    return {
        "imported": [to_dict(r) for r in imported],
        "count": len(imported),
        "warnings": warnings,
        "sync": sync_result,
    }
