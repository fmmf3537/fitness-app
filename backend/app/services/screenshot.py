"""V2-3 截图识别补录：视觉抽取 → JSON Schema 校验（不合法自动重试 1 次）→ 确认入库并重跑匹配。

纪律：
- 视觉调用固定走 adapters.llm.vision_extract（Kimi 多模态），含 llm_call 记账；
- 识别结果不落库，confirm_import 才是唯一入库入口（先校验，后写 xunji_train，再 match_day 重跑当日匹配）；
- 截图来源训练 localid 以 "shot-" 前缀合成，raw_json 标记 source="screenshot" 可追溯。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.llm import vision_extract
from app.models import MatchCandidate, Workout, XunjiTrain
from app.services.matcher import match_day

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)


class ExtractionError(Exception):
    """截图识别失败（含 JSON 解析失败、Schema 校验重试后仍不合法、入库数据不合法）。"""


# ---------- prompt ----------


def build_prompt(feedback: str | None = None) -> str:
    """构造视觉抽取 prompt；feedback 非空时附上次校验错误让模型自我修正。"""
    prompt = (
        "你是健身数据结构化助手。请识别这张训记/佳明训练截图，抽取训练数据，"
        "只输出严格 JSON（不要输出任何其他文字，不要用代码块包裹）。字段：\n"
        "{\n"
        '  "datestr": "YYYY-MM-DD",        // 训练日期，必填\n'
        '  "title": "训练标题",             // 必填，非空字符串\n'
        '  "start_time": "HH:MM 或 null",  // 截图中若有训练开始时间\n'
        '  "end_time": "HH:MM 或 null",    // 截图中若有训练结束时间\n'
        '  "duration_s": 整数秒 或 null,    // 总耗时换算为秒\n'
        '  "calories": 数字 或 null,        // 消耗（大卡/千卡）\n'
        '  "movements": [                  // 必填，至少一个动作\n'
        '    {"name": "动作中文名",\n'
        '     "sets": [{"weight": 重量数字, "unit": "kg", "reps": 次数整数}]}\n'
        "  ]\n"
        "}\n"
        "规则：\n"
        "- 每个动作至少一组；每组必须有 weight（kg 数字，自重为 0），reps 或 time（秒）至少其一；\n"
        "- 哑铃/双侧动作重量记两侧之和（如 (5+5)kg 记为 10）；\n"
        "- 时长、热量没有就给 null，不要编造；\n"
        "- 只输出 JSON。"
    )
    if feedback:
        prompt += f"\n\n上次输出未通过校验：{feedback}。请修正后重新输出严格 JSON。"
    return prompt


# ---------- JSON 解析 ----------


def parse_json_content(content: str) -> dict:
    """从模型输出中解析 JSON 对象（容忍 ```json 代码块与前后杂文本）。"""
    text = (content or "").strip()
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise ExtractionError("模型输出不是合法 JSON") from None
    if not isinstance(data, dict):
        raise ExtractionError("模型输出不是 JSON 对象")
    return data


# ---------- Schema 校验 ----------


def validate_extraction(data: Any) -> list[str]:
    """校验识别结果，返回错误列表（空列表 = 合法）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["整体必须是 JSON 对象"]

    datestr = data.get("datestr")
    if not isinstance(datestr, str) or not datestr:
        errors.append("缺少 datestr")
    else:
        try:
            date.fromisoformat(datestr)
        except ValueError:
            errors.append(f"datestr 格式非法：{datestr!r}（应为 YYYY-MM-DD）")

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title 必须是非空字符串")

    for key in ("start_time", "end_time"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not _TIME_RE.match(value)):
            errors.append(f"{key} 格式非法：{value!r}（应为 HH:MM）")

    duration_s = data.get("duration_s")
    if duration_s is not None and (
        isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or duration_s < 0
    ):
        errors.append("duration_s 必须是非负数字")

    calories = data.get("calories")
    if calories is not None and (
        isinstance(calories, bool) or not isinstance(calories, (int, float)) or calories < 0
    ):
        errors.append("calories 必须是非负数字")

    movements = data.get("movements")
    if not isinstance(movements, list) or not movements:
        errors.append("movements 必须是非空数组")
        return errors
    for i, mv in enumerate(movements):
        if not isinstance(mv, dict):
            errors.append(f"movements[{i}] 必须是对象")
            continue
        name = mv.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"movements[{i}].name 必须是非空字符串")
        sets = mv.get("sets")
        if not isinstance(sets, list) or not sets:
            errors.append(f"movements[{i}].sets 必须是非空数组")
            continue
        for j, s in enumerate(sets):
            if not isinstance(s, dict):
                errors.append(f"movements[{i}].sets[{j}] 必须是对象")
                continue
            weight = s.get("weight")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
                errors.append(f"movements[{i}].sets[{j}].weight 缺失或非非负数字")
            reps = s.get("reps")
            set_time = s.get("time")
            if reps is None and set_time is None:
                errors.append(f"movements[{i}].sets[{j}] reps/time 至少其一")
            if reps is not None and (
                isinstance(reps, bool) or not isinstance(reps, (int, float)) or reps <= 0
            ):
                errors.append(f"movements[{i}].sets[{j}].reps 必须是正数")
            if set_time is not None and (
                isinstance(set_time, bool) or not isinstance(set_time, (int, float)) or set_time <= 0
            ):
                errors.append(f"movements[{i}].sets[{j}].time 必须是正数")
    return errors


# ---------- 识别编排（校验失败自动重试 1 次） ----------


def extract_from_image(
    image_bytes: bytes,
    *,
    session: Session | None = None,
    mime: str = "image/png",
) -> dict:
    """调视觉模型抽取并校验；不合法时附错误反馈重试 1 次，仍失败抛 ExtractionError。"""
    feedback: str | None = None
    last_error = ""
    for attempt in range(2):
        result = vision_extract(image_bytes, build_prompt(feedback), session=session, mime=mime)
        try:
            data = parse_json_content(result["content"])
        except ExtractionError as exc:
            last_error = str(exc)
        else:
            errors = validate_extraction(data)
            if not errors:
                return data
            last_error = "；".join(errors)
        feedback = last_error
    raise ExtractionError(f"识别结果两次校验均不合法：{last_error}")


# ---------- 确认入库 + 重跑匹配 ----------


def _normalize_movements(movements: list[dict]) -> list[dict]:
    """补默认字段：unit 默认 kg、done 默认 True（与训记 raw movements 结构对齐）。"""
    normalized = []
    for mv in movements:
        sets = []
        for s in mv["sets"]:
            item = {
                "weight": s["weight"],
                "unit": s.get("unit") or "kg",
                "done": s.get("done", True),
            }
            if s.get("reps") is not None:
                item["reps"] = s["reps"]
            if s.get("time") is not None:
                item["time"] = s["time"]
            sets.append(item)
        normalized.append({"name": mv["name"].strip(), "sets": sets})
    return normalized


def _to_ms(day: date, hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    hh, mm = int(hhmm[:2]), int(hhmm[3:])
    # 与 matcher.XUNJI_TZ 对齐：墙钟时间按固定 +08:00 编码为 epoch 毫秒，
    # 保证匹配引擎在任何本地时区的机器上渲染结果一致
    from app.services.matcher import XUNJI_TZ

    return int(datetime.combine(day, time(hh, mm), tzinfo=XUNJI_TZ).timestamp() * 1000)


def confirm_import(session: Session, data: dict) -> dict:
    """用户确认后入库：写 xunji_train（source=screenshot），重跑当日匹配，返回结果摘要。"""
    errors = validate_extraction(data)
    if errors:
        raise ExtractionError("；".join(errors))

    day = date.fromisoformat(data["datestr"])
    localid = f"shot-{uuid.uuid4().hex[:8]}"
    start_ms = _to_ms(day, data.get("start_time"))
    end_ms = _to_ms(day, data.get("end_time"))
    raw = {
        "localid": localid,
        "title": data["title"].strip(),
        "start": start_ms,
        "end": end_ms,
        "movements": _normalize_movements(data["movements"]),
        "duration_s": data.get("duration_s"),
        "calories": data.get("calories"),
        "source": "screenshot",
    }
    train = XunjiTrain(
        datestr=data["datestr"],
        localid=localid,
        title=raw["title"],
        start_ms=start_ms,
        end_ms=end_ms,
        raw_json=json.dumps(raw, ensure_ascii=False),
    )
    session.add(train)
    session.commit()

    match_day(session, day)

    workout = session.query(Workout).filter(Workout.xunji_train_id == train.id).first()
    if workout is not None:
        match_status = workout.match_status
        workout_id = workout.id
    else:
        candidate = (
            session.query(MatchCandidate)
            .filter(MatchCandidate.xunji_train_id == train.id, MatchCandidate.status == "pending")
            .first()
        )
        match_status = "pending" if candidate is not None else "unmatched"
        workout_id = None

    return {
        "xunji_train_id": train.id,
        "localid": localid,
        "workout_id": workout_id,
        "match_status": match_status,
    }
