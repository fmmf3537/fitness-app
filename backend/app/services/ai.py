"""AI 报告服务：V1-3 单次训练点评（session_review）+ V1-4 下次训练建议（next_advice）。

纪律：
- prompt 组装函数纯函数化，方便测试；
- 历史与恢复数据查询独立封装，便于 mock；
- 生成失败抛 LLMError，由调用方（daily_sync）捕获并写 job_run，不阻塞主流程；
- 不直接操作 HTTP，统一调用 adapters/llm.chat；
- next_advice 只读 xunji_plan 本地缓存，不在生成时发起网络请求（限频纪律）；
- next_advice 的 AI 输出必须通过结构化 JSON 校验（含标准动作名白名单）才允许落库。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import llm
from app.models import AIReport, BodyMetric, GarminDaily, JobRun, Workout, XunjiPlan
from app.movements import load_movement_names
# V2-8：计划缓存解析原语提取到 services/plans.py 共享（禁止复制粘贴）
from app.services import plans as plan_service
from app.services.plans import normalize_plan_movement as _normalize_plan_movement
from app.services.plans import parse_json as _parse_json

PROMPT_SECTIONS = ("完成质量", "与历史对比", "恢复评估", "注意事项")


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_movements(workout: Workout) -> list[dict]:
    if not workout.movements_json:
        return []
    try:
        data = json.loads(workout.movements_json)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "未知"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{minutes // 60} 小时 {minutes % 60} 分钟"


def _extract_sleep_seconds(sleep_data: dict | None) -> tuple[int | None, int | None]:
    """从佳明 sleep_json 提取总睡眠秒数与深睡秒数，容忍多种字段名。"""
    if not isinstance(sleep_data, dict):
        return None, None
    dto = sleep_data.get("dailySleepDTO") or sleep_data
    total = dto.get("sleepTimeInSeconds") or dto.get("totalSleepTimeInSeconds")
    deep = dto.get("deepSleepSeconds") or dto.get("deepSleepSecondsInWaves")
    return _int_or_none(total), _int_or_none(deep)


def query_movement_history(
    session: Session,
    movement_name: str,
    current_date: date,
    *,
    weeks: int = 4,
    limit: int = 3,
    user_id: int | None = None,
) -> dict:
    """查询近 N 周某动作的历史摘要（最近几次 + PR）。

    返回：
        {
            "count": 出现次数,
            "pr_weight": 最大重量（kg，浮点数）,
            "recent": [
                {"date": "YYYY-MM-DD", "best_weight": float, "best_reps": int,
                 "total_volume": float, "sets_count": int},
                ...
            ]
        }
    """
    start = current_date - timedelta(weeks=weeks)
    end = current_date - timedelta(days=1)
    filters = [
        Workout.date >= start,
        Workout.date <= end,
        Workout.movements_json.isnot(None),
        Workout.deleted_at.is_(None),
    ]
    if user_id is not None:
        filters.append(Workout.user_id == user_id)
    rows = (
        session.query(Workout)
        .filter(*filters)
        .order_by(Workout.date.desc())
        .all()
    )

    recent: list[dict] = []
    pr_weight: float = 0.0
    count = 0
    for w in rows:
        movements = _parse_movements(w)
        for mv in movements:
            if (mv.get("name") or "").strip() != movement_name:
                continue
            sets = mv.get("sets") or []
            if not sets:
                continue
            count += 1
            best_weight = 0.0
            best_reps = 0
            total_volume = 0.0
            valid_sets = 0
            for s in sets:
                weight = _float_or_none(s.get("weight")) or 0.0
                reps = _int_or_none(s.get("reps")) or 0
                if weight <= 0 and reps <= 0:
                    continue
                valid_sets += 1
                total_volume += weight * reps
                if weight > best_weight or (weight == best_weight and reps > best_reps):
                    best_weight = weight
                    best_reps = reps
                if weight > pr_weight:
                    pr_weight = weight
            if valid_sets:
                recent.append(
                    {
                        "date": w.date.isoformat(),
                        "best_weight": round(best_weight, 2),
                        "best_reps": best_reps,
                        "total_volume": round(total_volume, 2),
                        "sets_count": valid_sets,
                    }
                )
            break  # 同一个 workout 中同名动作只计一次

    recent = sorted(recent, key=lambda x: x["date"], reverse=True)[:limit]
    return {
        "count": count,
        "pr_weight": round(pr_weight, 2) if pr_weight > 0 else None,
        "recent": recent,
    }


def query_recovery_summary(
    session: Session,
    current_date: date,
    *,
    days: int = 7,
    user_id: int | None = None,
) -> dict:
    """汇总近 N 天睡眠/HRV/身体电量/压力/静息心率/体重趋势。

    训练准备度当前未接入，故在返回中显式标注为 None，prompt 中说明缺失。
    """
    start = current_date - timedelta(days=days - 1)
    garmin_filters = [
        GarminDaily.date >= start,
        GarminDaily.date <= current_date,
    ]
    if user_id is not None:
        garmin_filters.append(GarminDaily.user_id == user_id)
    rows = (
        session.query(GarminDaily)
        .filter(*garmin_filters)
        .order_by(GarminDaily.date.desc())
        .all()
    )

    sleep_hours: list[float] = []
    deep_ratios: list[float] = []
    hrv_statuses: list[str] = []
    body_battery_high: list[int] = []
    body_battery_low: list[int] = []
    resting_hrs: list[int] = []
    stress_avgs: list[int] = []

    for row in rows:
        sleep_json = _parse_json(row.sleep_json)
        total_s, deep_s = _extract_sleep_seconds(sleep_json)
        if total_s and total_s > 0:
            sleep_hours.append(total_s / 3600)
            if deep_s and deep_s > 0:
                deep_ratios.append(deep_s / total_s)
        if row.hrv_status:
            hrv_statuses.append(row.hrv_status)
        if row.body_battery_high is not None:
            body_battery_high.append(row.body_battery_high)
        if row.body_battery_low is not None:
            body_battery_low.append(row.body_battery_low)
        if row.resting_hr is not None:
            resting_hrs.append(row.resting_hr)
        if row.stress_avg is not None:
            stress_avgs.append(row.stress_avg)

    # 近 4 周体重趋势（纳入 AI 上下文，US-12 AC6）
    weight_start = current_date - timedelta(weeks=4)
    weight_filters = [
        BodyMetric.date >= weight_start,
        BodyMetric.date <= current_date,
        BodyMetric.type == "weight",
    ]
    if user_id is not None:
        weight_filters.append(BodyMetric.user_id == user_id)
    weight_rows = (
        session.query(BodyMetric)
        .filter(*weight_filters)
        .order_by(BodyMetric.date.desc())
        .limit(7)
        .all()
    )
    weights = [
        {"date": r.date.isoformat(), "value": round(r.value, 2)}
        for r in weight_rows
    ]

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    return {
        "days_count": len(rows),
        "avg_sleep_hours": avg(sleep_hours),
        "avg_deep_ratio": avg(deep_ratios),
        "hrv_status": hrv_statuses[0] if hrv_statuses else None,
        "hrv_status_list": hrv_statuses,
        "body_battery_high": avg(body_battery_high),
        "body_battery_low": avg(body_battery_low),
        "resting_hr": avg(resting_hrs),
        "stress_avg": avg(stress_avgs),
        "weight_trend": weights,
        "training_readiness": None,  # 当前 GarminDaily 未收录该字段
    }


def build_session_review_prompt(
    workout: dict,
    history: dict[str, dict],
    recovery: dict,
) -> list[dict]:
    """纯函数：组装单次训练点评 prompt。

    输出固定四节 Markdown 要求：完成质量 / 与历史对比 / 恢复评估 / 注意事项。
    """
    movements = workout.get("movements") or []
    lines: list[str] = []
    lines.append(f"# 本次训练（{workout.get('date') or '未知日期'}）")
    if workout.get("title"):
        lines.append(f"标题：{workout['title']}")
    tags = workout.get("tags")
    if tags:
        lines.append(f"活动类型：{tags}")
    lines.append(
        f"时长：{_format_duration(workout.get('duration_s'))} | "
        f"热量：{workout.get('calories') or '-'} 千卡 | "
        f"平均心率：{workout.get('avg_hr') or '-'} bpm | "
        f"最大心率：{workout.get('max_hr') or '-'} bpm"
    )

    lines.append("")
    lines.append("## 动作组次")
    if movements:
        for mv in movements:
            sets = mv.get("sets") or []
            lines.append(f"- {mv.get('name') or '未命名动作'}：共 {len(sets)} 组")
            for i, s in enumerate(sets, 1):
                weight = s.get("weight")
                unit = s.get("unit") or "kg"
                reps = s.get("reps")
                rpe = s.get("rpe")
                done = s.get("done")
                part = f"  - 第{i}组："
                if weight is not None and reps is not None:
                    part += f"{weight}{unit} × {reps}"
                elif reps is not None:
                    part += f"{reps} 次"
                else:
                    part += "数据缺失"
                if rpe is not None:
                    part += f"（RPE {rpe}）"
                if done is False:
                    part += "【未完成】"
                lines.append(part)
    else:
        lines.append("- 无动作数据")

    lines.append("")
    lines.append(f"# 近4周同动作历史（截至 {workout.get('date') or '今日'}）")
    if history:
        for name, hist in history.items():
            lines.append(f"## {name}")
            lines.append(f"- 出现次数：{hist['count']}")
            if hist.get("pr_weight") is not None:
                lines.append(f"- 个人纪录（PR）重量：{hist['pr_weight']} kg")
            recent = hist.get("recent") or []
            if recent:
                lines.append("- 最近记录：")
                for r in recent:
                    lines.append(
                        f"  - {r['date']}：最佳 {r['best_weight']}kg × {r['best_reps']}，"
                        f"总容量 {r['total_volume']}kg，{r['sets_count']} 组"
                    )
            else:
                lines.append("- 近4周无该动作记录")
    else:
        lines.append("近4周无同动作历史数据。")

    lines.append("")
    lines.append("# 近7天恢复数据")
    if recovery.get("days_count", 0) > 0:
        if recovery.get("avg_sleep_hours") is not None:
            lines.append(f"- 平均睡眠时长：{recovery['avg_sleep_hours']} 小时")
        if recovery.get("avg_deep_ratio") is not None:
            lines.append(f"- 平均深睡比例：{round(recovery['avg_deep_ratio'] * 100, 1)}%")
        if recovery.get("hrv_status"):
            lines.append(f"- HRV 状态：{recovery['hrv_status']}")
        if recovery.get("body_battery_high") is not None and recovery.get("body_battery_low") is not None:
            lines.append(
                f"- 身体电量：高 {recovery['body_battery_high']} / 低 {recovery['body_battery_low']}"
            )
        if recovery.get("resting_hr") is not None:
            lines.append(f"- 平均静息心率：{recovery['resting_hr']} bpm")
        if recovery.get("stress_avg") is not None:
            lines.append(f"- 平均压力：{recovery['stress_avg']}")
    else:
        lines.append("- 近7天无恢复数据")

    if recovery.get("weight_trend"):
        lines.append("- 近4周体重趋势（kg）：")
        for item in recovery["weight_trend"]:
            lines.append(f"  - {item['date']}：{item['value']} kg")
    else:
        lines.append("- 近4周无体重记录")

    if recovery.get("training_readiness") is None:
        lines.append("- 训练准备度：当前未接入该数据源，将结合睡眠/HRV/身体电量综合评估")

    system = (
        "你是一位资深力量训练教练。请根据用户本次训练、近4周同动作历史、"
        "近7天睡眠/HRV/身体电量/压力/静息心率/体重趋势，撰写单次训练点评。"
        "输出为 Markdown，正文必须且只能包含以下四节（按顺序）：\n"
        "\n".join(f"## {s}" for s in PROMPT_SECTIONS)
        + "\n每节需结合真实数据，给出具体、可执行的评价与建议。"
        "\n正文结束后，必须附加一个 ```json 围栏块，schema 为 session_review_v1，格式：\n"
        "```json\n"
        '{"schema":"session_review_v1","score":0-100整数,'
        '"subscores":{"completion":0-100,"intensity":0-100,"recovery_fit":0-100},'
        '"one_liner":"一句30字以内口语化点评（供分享海报用，禁 markdown 符号）"}\n'
        "```\n"
        "score 为本次训练综合评分；completion=完成度、intensity=强度合理性、"
        "recovery_fit=训练与恢复状态的匹配度。"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _resolve_provider(session: Session) -> str:
    """读取默认 provider；若 settings 未配置则回退 deepseek。"""
    try:
        return llm.get_default_provider(session)
    except Exception:
        return llm.DEFAULT_PROVIDER


def generate_session_review(
    session: Session,
    workout_id: int,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> AIReport:
    """为单个 workout 生成单次点评并落库 ai_report。

    chat_fn 用于测试注入；默认调用 adapters.llm.chat。
    """
    workout = session.get(Workout, workout_id)
    if workout is None or workout.deleted_at is not None:
        raise ValueError(f"workout {workout_id} 不存在")

    movements = _parse_movements(workout)
    history: dict[str, dict] = {}
    for mv in movements:
        name = (mv.get("name") or "").strip()
        if not name:
            continue
        history[name] = query_movement_history(
            session, name, workout.date, user_id=workout.user_id
        )

    recovery = query_recovery_summary(session, workout.date, user_id=workout.user_id)

    workout_dict = {
        "date": workout.date.isoformat(),
        "title": workout.title,
        "tags": workout.tags,
        "duration_s": workout.duration_s,
        "calories": workout.calories,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "movements": movements,
    }

    messages = build_session_review_prompt(workout_dict, history, recovery)

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="session_review"
        )

    # V3-4：正文后须附 session_review_v1 评分 JSON 块；解析失败重试 1 次，
    # 仍失败则降级为仅落 markdown 正文（score 置 null，不阻断）。
    content = ""
    prompt_tokens = 0
    completion_tokens = 0
    parsed: dict | None = None
    for attempt in range(2):
        result = chat_fn(messages)
        content = result.get("content", "")
        prompt_tokens += result.get("prompt_tokens") or 0
        completion_tokens += result.get("completion_tokens") or 0
        try:
            parsed = parse_session_review(content)
            break
        except SessionReviewParseError:
            if attempt == 0:
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            "上次输出缺少合法的 session_review_v1 JSON 围栏块，"
                            "请原样输出四节正文，并在结尾补上格式正确的 ```json 评分块。"
                        ),
                    }
                ]

    provider = _resolve_provider(session)
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    report = AIReport(
        type="session_review",
        workout_id=workout.id,
        user_id=workout.user_id,
        period_start=workout.date,
        period_end=workout.date,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=round(cost, 6),
        content_md=parsed["markdown"] if parsed else content,
        score=parsed["score"] if parsed else None,
        one_liner=parsed["one_liner"] if parsed else None,
        subscores_json=(
            json.dumps(parsed["subscores"], ensure_ascii=False) if parsed else None
        ),
    )
    session.add(report)
    session.commit()
    return report


def run_daily_reviews(
    session: Session,
    day: date | str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> dict:
    """为某日全部 workout 生成单次点评。

    返回 summary：{"date", "generated", "skipped", "reports": [id, ...]}。
    """
    day_date = date.fromisoformat(day) if isinstance(day, str) else day
    workouts = (
        session.query(Workout)
        .filter(Workout.date == day_date, Workout.deleted_at.is_(None))
        .order_by(Workout.id)
        .all()
    )

    reports: list[int] = []
    skipped = 0
    for w in workouts:
        # 幂等：同日同 workout 已存在 session_review 则跳过
        existing = session.scalars(
            select(AIReport).where(
                AIReport.workout_id == w.id,
                AIReport.type == "session_review",
                AIReport.period_start == day_date,
            )
        ).first()
        if existing:
            skipped += 1
            continue
        report = generate_session_review(session, w.id, chat_fn=chat_fn, user_id=w.user_id)
        reports.append(report.id)

    return {
        "date": day_date.isoformat(),
        "generated": len(reports),
        "skipped": skipped,
        "reports": reports,
    }


def regenerate_session_reviews(
    session: Session,
    day: date | str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> dict:
    """V3-4：删除某日全部旧 session_review 后重新生成（复用 V2-7b 删旧重生成逻辑）。

    仅清理 session_review，不动 next_advice / weekly / monthly 等其他类型。
    """
    day_date = date.fromisoformat(day) if isinstance(day, str) else day
    session.query(AIReport).filter(
        AIReport.type == "session_review",
        AIReport.period_start == day_date,
    ).delete(synchronize_session=False)
    session.commit()
    return run_daily_reviews(session, day_date, chat_fn=chat_fn)


# =====================================================================
# V3-4 session_review 评分块解析（schema session_review_v1）
# =====================================================================

SCORE_JSON_SCHEMA = "session_review_v1"
SCORE_SUBSCORE_KEYS = ("completion", "intensity", "recovery_fit")
ONE_LINER_MAX_LEN = 40


class SessionReviewParseError(ValueError):
    """session_review 评分 JSON 块解析/校验失败。"""


def _is_int_0_100(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100


def parse_session_review(content_md: str) -> dict:
    """从 AI 输出中提取并校验 session_review_v1 评分块。

    返回 {"markdown": 剔除评分块后的正文, "score", "subscores", "one_liner"}；
    校验失败抛 SessionReviewParseError（由调用方重试/降级）。
    """
    content = content_md or ""
    matches = list(_ADVICE_BLOCK_RE.finditer(content))
    if not matches:
        raise SessionReviewParseError("缺少 ```json 评分块")
    block = matches[-1]  # 取最后一个围栏块，防止正文引用示例 JSON 干扰
    try:
        data = json.loads(block.group(1))
    except json.JSONDecodeError as exc:
        raise SessionReviewParseError(f"评分块 JSON 非法：{exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCORE_JSON_SCHEMA:
        raise SessionReviewParseError("schema 不是 session_review_v1")
    if not _is_int_0_100(data.get("score")):
        raise SessionReviewParseError("score 须为 0-100 整数")
    sub = data.get("subscores")
    if not isinstance(sub, dict) or any(
        not _is_int_0_100(sub.get(k)) for k in SCORE_SUBSCORE_KEYS
    ):
        raise SessionReviewParseError(
            "subscores 须含 completion/intensity/recovery_fit 三个 0-100 整数"
        )
    one_liner = data.get("one_liner")
    if not isinstance(one_liner, str) or not one_liner.strip():
        raise SessionReviewParseError("one_liner 须为非空文本")
    one_liner = one_liner.strip()
    if len(one_liner) > ONE_LINER_MAX_LEN:
        raise SessionReviewParseError(f"one_liner 超过 {ONE_LINER_MAX_LEN} 字")
    markdown = (content[: block.start()] + content[block.end() :]).strip()
    return {
        "markdown": markdown,
        "score": data["score"],
        "subscores": {k: sub[k] for k in SCORE_SUBSCORE_KEYS},
        "one_liner": one_liner,
    }


# =====================================================================
# V1-4 下次训练建议（type='next_advice'）
# =====================================================================

ADVICE_JSON_SCHEMA = "next_advice_v1"
ADVICE_CATEGORIES = ("auto_writable", "manual")
_ADVICE_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


class NextAdviceParseError(ValueError):
    """下次训练建议的结构化 JSON 解析/校验失败。"""


def parse_next_advice(content_md: str) -> dict:
    """从 AI 输出中提取并校验结构化建议 JSON 块。

    要求 content_md 内含一个 ```json 围栏块，schema 为 next_advice_v1，
    suggestions 中每条必须含：movement（标准动作名表内）/ category
    （auto_writable|manual）/ original / suggested / reason。
    任一校验失败抛 NextAdviceParseError（非法动作名一并拒绝）。
    """
    if not content_md:
        raise NextAdviceParseError("内容为空，缺少 JSON 建议块")
    match = _ADVICE_BLOCK_RE.search(content_md)
    if match is None:
        raise NextAdviceParseError("缺少 ```json 建议块")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise NextAdviceParseError(f"JSON 块解析失败: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != ADVICE_JSON_SCHEMA:
        raise NextAdviceParseError(f"schema 必须为 {ADVICE_JSON_SCHEMA}")
    suggestions = data.get("suggestions")
    if not isinstance(suggestions, list):
        raise NextAdviceParseError("suggestions 必须为数组")

    valid_names = set(load_movement_names())
    for i, s in enumerate(suggestions):
        if not isinstance(s, dict):
            raise NextAdviceParseError(f"第 {i + 1} 条建议不是对象")
        movement = s.get("movement")
        if not isinstance(movement, str) or movement.strip() not in valid_names:
            raise NextAdviceParseError(f"第 {i + 1} 条建议动作名非法: {movement!r}")
        if s.get("category") not in ADVICE_CATEGORIES:
            raise NextAdviceParseError(
                f"第 {i + 1} 条建议 category 非法: {s.get('category')!r}"
            )
        for field in ("original", "suggested"):
            if not isinstance(s.get(field), dict):
                raise NextAdviceParseError(f"第 {i + 1} 条建议缺少 {field} 对象")
        if not isinstance(s.get("reason"), str) or not s["reason"].strip():
            raise NextAdviceParseError(f"第 {i + 1} 条建议缺少 reason")
    return data


def classify_suggestions(data: dict) -> dict:
    """把已校验的建议数据分为「可自动写回」与「需手动调整」两类。"""
    grouped = {category: [] for category in ADVICE_CATEGORIES}
    for s in data.get("suggestions") or []:
        category = s.get("category")
        if category in grouped:
            grouped[category].append(s)
    return grouped


def query_next_plan_day(
    session: Session,
    current_date: date,
    *,
    days_ahead: int = 30,
    user_id: int | None = None,
) -> dict | None:
    """从训记官方计划缓存中找下一次训练日（未来 days_ahead 天内、movements 非空）。

    只读本地 xunji_plan 缓存，不发起网络请求（缓存由 sync_plan_cache 每日刷新）。
    返回 {"plan_ref", "plan_name", "date", "movements"} 或 None。
    """
    horizon = current_date + timedelta(days=days_ahead)
    plan_filters = [
        XunjiPlan.plan_json.isnot(None),
        XunjiPlan.date_from.isnot(None),
        XunjiPlan.date_to.isnot(None),
        XunjiPlan.date_from <= horizon,
        XunjiPlan.date_to >= current_date,
    ]
    if user_id is not None:
        plan_filters.append(XunjiPlan.user_id == user_id)
    rows = (
        session.query(XunjiPlan)
        .filter(*plan_filters)
        .all()
    )
    best: dict | None = None
    for row in rows:
        data = _parse_json(row.plan_json)
        if not isinstance(data, dict):
            continue
        plan_name = (data.get("plan") or {}).get("name") or (data.get("plan") or {}).get("title")
        for day in data.get("days") or []:
            # 真实 get 响应用 datestr + workout.movements；旧结构用 date + movements
            day_str = day.get("date") or day.get("datestr")
            movements = day.get("movements") or (day.get("workout") or {}).get("movements") or []
            if not day_str or not movements:
                continue
            try:
                day_date = date.fromisoformat(day_str)
            except (ValueError, TypeError):
                continue
            if day_date <= current_date or day_date > horizon:
                continue
            if best is None or day_str < best["date"]:
                best = {
                    "plan_ref": row.plan_ref,
                    "plan_name": plan_name,
                    "date": day_str,
                    "movements": [_normalize_plan_movement(mv) for mv in movements],
                }
    return best


def build_next_advice_prompt(
    workout: dict,
    plan_day: dict,
    recovery: dict,
    movement_names: list[str] | tuple[str, ...],
) -> list[dict]:
    """纯函数：组装下次训练建议 prompt（动作名表注入 system 约束模型）。"""
    lines: list[str] = []
    lines.append(f"# 本次训练完成情况（{workout.get('date') or '未知日期'}）")
    if workout.get("title"):
        lines.append(f"标题：{workout['title']}")
    lines.append(
        f"时长：{_format_duration(workout.get('duration_s'))} | "
        f"热量：{workout.get('calories') or '-'} 千卡 | "
        f"平均心率：{workout.get('avg_hr') or '-'} bpm | "
        f"最大心率：{workout.get('max_hr') or '-'} bpm"
    )
    for mv in workout.get("movements") or []:
        sets = mv.get("sets") or []
        parts = []
        for s in sets:
            part = f"{s.get('weight')}{s.get('unit') or 'kg'}×{s.get('reps')}"
            if s.get("rpe") is not None:
                part += f"(RPE{s['rpe']})"
            if s.get("done") is False:
                part += "【未完成】"
            parts.append(part)
        lines.append(f"- {mv.get('name') or '未命名动作'}：" + "，".join(parts))

    lines.append("")
    lines.append(
        f"# 训记官方计划 · 下一次训练日（{plan_day.get('date')}，"
        f"计划：{plan_day.get('plan_name') or plan_day.get('plan_ref') or '未命名'}）"
    )
    for mv in plan_day.get("movements") or []:
        sets = mv.get("sets") or []
        if sets:
            parts = [f"{s.get('weight')}{s.get('unit') or 'kg'}×{s.get('reps')}" for s in sets]
            lines.append(f"- {mv.get('name') or '未命名动作'}：计划 {len(sets)} 组（" + "，".join(parts) + "）")
        else:
            lines.append(f"- {mv.get('name') or '未命名动作'}")

    lines.append("")
    lines.append("# 近7天恢复指标")
    if recovery.get("days_count", 0) > 0:
        if recovery.get("avg_sleep_hours") is not None:
            lines.append(f"- 平均睡眠时长：{recovery['avg_sleep_hours']} 小时")
        if recovery.get("hrv_status"):
            lines.append(f"- HRV 状态：{recovery['hrv_status']}")
        if recovery.get("body_battery_high") is not None:
            lines.append(
                f"- 身体电量：高 {recovery.get('body_battery_high')} / 低 {recovery.get('body_battery_low')}"
            )
        if recovery.get("resting_hr") is not None:
            lines.append(f"- 平均静息心率：{recovery['resting_hr']} bpm")
        if recovery.get("stress_avg") is not None:
            lines.append(f"- 平均压力：{recovery['stress_avg']}")
    else:
        lines.append("- 近7天无恢复数据")

    system = (
        "你是一位资深力量训练教练。请对照训记官方计划的下一次训练日，结合本次训练完成情况"
        "与恢复指标，逐动作给出调整建议，粒度到「动作/重量/组数/次数」。\n"
        "输出要求：\n"
        "1. 先输出给人看的 Markdown 正文（计划对照与调整说明）；\n"
        "2. 再输出一个 ```json 围栏代码块，schema 为 next_advice_v1，结构：\n"
        '{"schema": "next_advice_v1", "next_plan_date": "YYYY-MM-DD", "suggestions": ['
        '{"movement": "标准动作中文名", "category": "auto_writable 或 manual", '
        '"original": {...}, "suggested": {...}, "reason": "理由"}]}\n'
        "3. category=auto_writable 仅用于对已发生训练的 RPE/难度等修正；"
        "category=manual 用于对计划本身的修改（需用户去训记 App 手动调整）；\n"
        "4. movement 只能使用下列训记标准动作中文名表中的名字，禁止自造动作名：\n"
        + "、".join(movement_names)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def generate_next_advice(
    session: Session,
    workout_id: int,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> AIReport | None:
    """为单个 workout 生成下次训练建议并落库（type='next_advice'）。

    无计划缓存（找不到下一次训练日）时返回 None 且不调用模型；
    AI 输出未通过结构化校验（含非法动作名）时抛 NextAdviceParseError，不落库。
    """
    workout = session.get(Workout, workout_id)
    if workout is None or workout.deleted_at is not None:
        raise ValueError(f"workout {workout_id} 不存在")

    plan_day = query_next_plan_day(session, workout.date, user_id=workout.user_id)
    if plan_day is None:
        return None

    movements = _parse_movements(workout)
    recovery = query_recovery_summary(session, workout.date, user_id=workout.user_id)
    workout_dict = {
        "date": workout.date.isoformat(),
        "title": workout.title,
        "tags": workout.tags,
        "duration_s": workout.duration_s,
        "calories": workout.calories,
        "avg_hr": workout.avg_hr,
        "max_hr": workout.max_hr,
        "movements": movements,
    }
    messages = build_next_advice_prompt(
        workout_dict, plan_day, recovery, load_movement_names()
    )

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="next_advice"
        )

    result = chat_fn(messages)
    content = result.get("content", "")
    # 先校验再落库：非法动作名/非法结构一律拒绝
    parse_next_advice(content)

    prompt_tokens = result.get("prompt_tokens") or 0
    completion_tokens = result.get("completion_tokens") or 0
    provider = _resolve_provider(session)
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    plan_date = date.fromisoformat(plan_day["date"])
    report = AIReport(
        type="next_advice",
        workout_id=workout.id,
        user_id=workout.user_id,
        period_start=workout.date,
        period_end=plan_date,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=round(cost, 6),
        content_md=content,
    )
    session.add(report)
    session.commit()
    return report


def _plan_cache_note(session: Session) -> str:
    """无下一次训练日时给出可读原因（供 run_daily_next_advices 摘要说明）。"""
    rows = session.query(XunjiPlan).all()
    if not rows:
        return "训记计划缓存为空，无法生成下次训练建议"
    statuses: set[str] = set()
    for row in rows:
        data = _parse_json(row.plan_json)
        if not isinstance(data, dict):
            continue
        # 兼容两种缓存结构：list 行顶层 status / get 行 plan.status
        status = data.get("status") or (data.get("plan") or {}).get("status")
        if status:
            statuses.add(str(status))
    if statuses and statuses <= {"ended"}:
        return "训记计划已全部结束（status=ended），无下一次训练日，跳过生成"
    return "计划缓存覆盖范围内无未来训练日，跳过生成"


def run_daily_next_advices(
    session: Session,
    day: date | str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
) -> dict:
    """为某日全部 workout 连锁生成下次训练建议（在单次点评之后触发）。

    幂等：同日同 workout 已存在 next_advice 则跳过。
    返回 summary：{"date", "generated", "skipped", "no_plan", "note", "reports"}。
    no_plan > 0 时 note 给出可读原因（如计划 status=ended 优雅跳过）。
    """
    day_date = date.fromisoformat(day) if isinstance(day, str) else day
    workouts = (
        session.query(Workout)
        .filter(Workout.date == day_date, Workout.deleted_at.is_(None))
        .order_by(Workout.id)
        .all()
    )

    reports: list[int] = []
    skipped = 0
    no_plan = 0
    for w in workouts:
        existing = session.scalars(
            select(AIReport).where(
                AIReport.workout_id == w.id,
                AIReport.type == "next_advice",
                AIReport.period_start == day_date,
            )
        ).first()
        if existing:
            skipped += 1
            continue
        report = generate_next_advice(session, w.id, chat_fn=chat_fn, user_id=w.user_id)
        if report is None:
            no_plan += 1
        else:
            reports.append(report.id)

    return {
        "date": day_date.isoformat(),
        "generated": len(reports),
        "skipped": skipped,
        "no_plan": no_plan,
        "note": _plan_cache_note(session) if no_plan else None,
        "reports": reports,
    }


# =====================================================================
# V2-8 计划级 AI 点评（type='plan_review'）
# =====================================================================

PLAN_REVIEW_SCHEMA = "plan_review_v1"
PLAN_REVIEW_FIELDS = ("weight", "reps", "sets", "add", "remove")


class PlanReviewParseError(ValueError):
    """计划点评的结构化 JSON 解析/校验失败。"""


def parse_plan_review(content_md: str) -> dict:
    """从 AI 输出中提取并校验 plan_review_v1 结构化 JSON 块。

    modifications 每条必须含：movement（标准动作名白名单内）/
    field（weight|reps|sets|add|remove）/ from / to / reason。
    任一校验失败抛 PlanReviewParseError。
    """
    if not content_md:
        raise PlanReviewParseError("内容为空，缺少 JSON 修改建议块")
    match = _ADVICE_BLOCK_RE.search(content_md)
    if match is None:
        raise PlanReviewParseError("缺少 ```json 修改建议块")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PlanReviewParseError(f"JSON 块解析失败: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != PLAN_REVIEW_SCHEMA:
        raise PlanReviewParseError(f"schema 必须为 {PLAN_REVIEW_SCHEMA}")
    if not isinstance(data.get("plan_date"), str) or not data["plan_date"].strip():
        raise PlanReviewParseError("缺少 plan_date")
    modifications = data.get("modifications")
    if not isinstance(modifications, list):
        raise PlanReviewParseError("modifications 必须为数组")

    valid_names = set(load_movement_names())
    for i, m in enumerate(modifications):
        if not isinstance(m, dict):
            raise PlanReviewParseError(f"第 {i + 1} 条修改建议不是对象")
        movement = m.get("movement")
        if not isinstance(movement, str) or movement.strip() not in valid_names:
            raise PlanReviewParseError(f"第 {i + 1} 条修改建议动作名非法: {movement!r}")
        if m.get("field") not in PLAN_REVIEW_FIELDS:
            raise PlanReviewParseError(
                f"第 {i + 1} 条修改建议 field 非法: {m.get('field')!r}"
            )
        for key in ("from", "to"):
            if key not in m:
                raise PlanReviewParseError(f"第 {i + 1} 条修改建议缺少 {key}")
        if not isinstance(m.get("reason"), str) or not m["reason"].strip():
            raise PlanReviewParseError(f"第 {i + 1} 条修改建议缺少 reason")
    return data


def query_last_similar_workout(
    session: Session,
    plan_day: dict,
    target_date: date,
    *,
    user_id: int | None = None,
) -> dict | None:
    """最近一次同类型 workout：标题与计划日标题一致优先，否则动作名重叠兜底。"""
    last_filters = [
        Workout.date < target_date,
        Workout.movements_json.isnot(None),
        Workout.deleted_at.is_(None),
    ]
    if user_id is not None:
        last_filters.append(Workout.user_id == user_id)
    rows = (
        session.query(Workout)
        .filter(*last_filters)
        .order_by(Workout.date.desc(), Workout.id.desc())
        .all()
    )
    title = (plan_day.get("title") or "").strip()
    plan_names = {
        (mv.get("name") or "").strip() for mv in plan_day.get("movements") or []
    } - {""}

    def to_dict(w: Workout, movements: list[dict]) -> dict:
        return {
            "date": w.date.isoformat(),
            "title": w.title,
            "tags": w.tags,
            "duration_s": w.duration_s,
            "calories": w.calories,
            "avg_hr": w.avg_hr,
            "max_hr": w.max_hr,
            "movements": movements,
        }

    fallback: dict | None = None
    for w in rows:
        movements = _parse_movements(w)
        if title and (w.title or "").strip() == title:
            return to_dict(w, movements)
        if fallback is None:
            w_names = {(m.get("name") or "").strip() for m in movements}
            if plan_names & w_names:
                fallback = to_dict(w, movements)
    return fallback


def query_part_volume_trend(
    session: Session,
    plan_day: dict,
    target_date: date,
    *,
    weeks: int = 4,
    user_id: int | None = None,
) -> list[dict]:
    """近 N 周计划涉及部位的容量趋势（复用周期汇总 + 部位归类）。"""
    from app.services import stats as stats_service

    parts = {
        stats_service.classify_part(mv.get("name"))
        for mv in plan_day.get("movements") or []
    }
    summary = query_period_training_summary(
        session,
        target_date - timedelta(weeks=weeks),
        target_date - timedelta(days=1),
        user_id=user_id,
    )
    return [p for p in summary["part_distribution"] if p["part"] in parts]


def build_plan_review_prompt(
    plan_day: dict,
    last_workout: dict | None,
    part_trend: list[dict],
    recovery: dict,
    movement_names: list[str] | tuple[str, ...],
) -> list[dict]:
    """纯函数：组装计划级点评 prompt（动作名表注入 system 约束模型）。"""
    lines: list[str] = []
    lines.append(
        f"# 训记官方计划 · {plan_day.get('date')}（计划："
        f"{plan_day.get('plan_name') or plan_day.get('plan_ref') or '未命名'}"
        f"{(' · ' + plan_day['title']) if plan_day.get('title') else ''}）"
    )
    for mv in plan_day.get("movements") or []:
        sets = mv.get("sets") or []
        if sets:
            parts = [f"{s.get('weight')}{s.get('unit') or 'kg'}×{s.get('reps')}" for s in sets]
            lines.append(f"- {mv.get('name') or '未命名动作'}：计划 {len(sets)} 组（" + "，".join(parts) + "）")
        else:
            lines.append(f"- {mv.get('name') or '未命名动作'}")

    lines.append("")
    lines.append("# 最近一次同类型训练完成情况")
    if last_workout:
        lines.append(
            f"日期：{last_workout.get('date')} | 标题：{last_workout.get('title') or '-'} | "
            f"时长：{_format_duration(last_workout.get('duration_s'))} | "
            f"热量：{last_workout.get('calories') or '-'} 千卡 | "
            f"平均心率：{last_workout.get('avg_hr') or '-'} bpm"
        )
        for mv in last_workout.get("movements") or []:
            sets = mv.get("sets") or []
            parts = []
            for s in sets:
                part = f"{s.get('weight')}{s.get('unit') or 'kg'}×{s.get('reps')}"
                if s.get("rpe") is not None:
                    part += f"(RPE{s['rpe']})"
                if s.get("done") is False:
                    part += "【未完成】"
                parts.append(part)
            lines.append(f"- {mv.get('name') or '未命名动作'}：" + "，".join(parts))
    else:
        lines.append("- 无同类型训练历史")

    lines.append("")
    lines.append("# 近4周同部位容量趋势")
    if part_trend:
        for p in part_trend:
            lines.append(f"- {p['part']}：{p['sets']} 组 / {p['volume_kg']} kg")
    else:
        lines.append("- 近4周无同部位训练记录")

    lines.append("")
    lines.append("# 近7天恢复指标")
    if recovery.get("days_count", 0) > 0:
        if recovery.get("avg_sleep_hours") is not None:
            lines.append(f"- 平均睡眠时长：{recovery['avg_sleep_hours']} 小时")
        if recovery.get("hrv_status"):
            lines.append(f"- HRV 状态：{recovery['hrv_status']}")
        if recovery.get("body_battery_high") is not None:
            lines.append(
                f"- 身体电量：高 {recovery.get('body_battery_high')} / 低 {recovery.get('body_battery_low')}"
            )
        if recovery.get("resting_hr") is not None:
            lines.append(f"- 平均静息心率：{recovery['resting_hr']} bpm")
        if recovery.get("stress_avg") is not None:
            lines.append(f"- 平均压力：{recovery['stress_avg']}")
    else:
        lines.append("- 近7天无恢复数据")

    if recovery.get("weight_trend"):
        lines.append("- 近4周体重趋势（kg）：")
        for item in recovery["weight_trend"]:
            lines.append(f"  - {item['date']}：{item['value']} kg")
    else:
        lines.append("- 近4周无体重记录")

    system = (
        "你是一位资深力量训练教练。请针对训记官方计划的指定训练日，结合最近一次同类型"
        "训练完成情况、近4周同部位容量趋势、恢复指标与体重趋势，点评该计划日安排是否合理，"
        "并给出逐动作的调整建议（重量/次数/组数/增删动作）。\n"
        "输出要求：\n"
        "1. 先输出给人看的 Markdown 正文（计划合理性点评与调整说明）；\n"
        "2. 再输出一个 ```json 围栏代码块，schema 为 plan_review_v1，结构：\n"
        '{"schema": "plan_review_v1", "plan_date": "YYYY-MM-DD", "modifications": ['
        '{"movement": "标准动作中文名", "field": "weight|reps|sets|add|remove", '
        '"from": "原计划", "to": "建议改为", "reason": "理由"}]}\n'
        "3. 训记计划接口只读，所有修改建议仅供用户去训记 App 手动调整，"
        "严禁暗示可以自动写回计划；\n"
        "4. movement 只能使用下列训记标准动作中文名表中的名字，禁止自造动作名：\n"
        + "、".join(movement_names)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def generate_plan_review(
    session: Session,
    target_date: date | str,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> AIReport | None:
    """为某日计划训练日生成计划级点评并落库（type='plan_review'）。

    - 无计划日（休息日/缓存缺失/计划已结束）返回 None，不调用模型，
      可读原因见 plans.plan_day_skip_reason；
    - AI 输出未通过结构化校验（含非法动作名）时重试 1 次，仍失败抛
      PlanReviewParseError，不落库；
    - 幂等覆盖：同日已有 plan_review 先删旧再生成（用户会反复调整计划，
      与 next_advice 的跳过策略不同）。
    """
    target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date

    plan_day = plan_service.query_plan_day(session, target, user_id=user_id)
    if plan_day is None:
        return None

    last_workout = query_last_similar_workout(session, plan_day, target, user_id=user_id)
    part_trend = query_part_volume_trend(session, plan_day, target, user_id=user_id)
    recovery = query_recovery_summary(session, target, user_id=user_id)  # 含近4周体重趋势
    messages = build_plan_review_prompt(
        plan_day, last_workout, part_trend, recovery, load_movement_names()
    )

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose="plan_review"
        )

    result = chat_fn(messages)
    content = result.get("content", "")
    try:
        parse_plan_review(content)
    except PlanReviewParseError:
        # 校验失败重试 1 次；仍失败向外抛，不落库
        result = chat_fn(messages)
        content = result.get("content", "")
        parse_plan_review(content)

    prompt_tokens = result.get("prompt_tokens") or 0
    completion_tokens = result.get("completion_tokens") or 0
    provider = _resolve_provider(session)
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    # 幂等覆盖：先删旧再生成
    session.query(AIReport).filter(
        AIReport.type == "plan_review",
        AIReport.period_start == target,
    ).delete()
    report = AIReport(
        type="plan_review",
        workout_id=None,
        user_id=user_id,
        period_start=target,
        period_end=target,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=round(cost, 6),
        content_md=content,
    )
    session.add(report)
    session.commit()
    return report


# =====================================================================
# V2-2 周期复盘（type='weekly' / 'monthly'）
# =====================================================================

WEEKLY_SECTIONS = (
    "本周概览", "部位分布与容量", "PR 事件",
    "睡眠与恢复关联", "上周建议执行情况", "下周建议",
)
MONTHLY_SECTIONS = (
    "月度概览", "计划完成率", "训练趋势", "体成分变化", "下月建议",
)

# 上周复盘回读注入 prompt 的最大字符数（AI 分析只发最小必要数据子集）
_PREV_REVIEW_MAX_CHARS = 3000


def week_range(day: date) -> tuple[date, date]:
    """ISO 周区间（周一至周日）。"""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_range(day: date) -> tuple[date, date]:
    """自然月区间。"""
    start = day.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - timedelta(days=1)


def query_period_training_summary(
    session: Session, start: date, end: date, *, user_id: int | None = None
) -> dict:
    """周期内全部融合训练汇总：频率 / 部位分布 / 总容量 / 时长 / 热量。"""
    from app.services import stats as stats_service

    summary_filters = [
        Workout.date >= start,
        Workout.date <= end,
        Workout.deleted_at.is_(None),
    ]
    if user_id is not None:
        summary_filters.append(Workout.user_id == user_id)
    rows = (
        session.query(Workout)
        .filter(*summary_filters)
        .order_by(Workout.date, Workout.id)
        .all()
    )

    total_volume = 0.0
    total_duration = 0
    total_calories = 0
    part_stats: dict[str, dict] = {}
    workouts: list[dict] = []
    for w in rows:
        movements = _parse_movements(w)
        volume = 0.0
        for mv in movements:
            part = stats_service.classify_part(mv.get("name"))
            entry = part_stats.setdefault(part, {"part": part, "sets": 0, "volume_kg": 0.0})
            for s in mv.get("sets") or []:
                v = stats_service.set_volume_kg(s)
                if v > 0:
                    entry["sets"] += 1
                    entry["volume_kg"] += v
                    volume += v
        total_volume += volume
        total_duration += w.duration_s or 0
        total_calories += w.calories or 0
        workouts.append({
            "date": w.date.isoformat(),
            "title": w.title,
            "volume_kg": round(volume, 2),
            "duration_s": w.duration_s,
            "calories": w.calories,
        })

    part_distribution = sorted(
        (
            {**p, "volume_kg": round(p["volume_kg"], 2)}
            for p in part_stats.values()
        ),
        key=lambda p: p["volume_kg"],
        reverse=True,
    )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "workout_count": len(rows),
        "training_days": len({w.date for w in rows}),
        "total_volume_kg": round(total_volume, 2),
        "total_duration_s": total_duration,
        "total_calories": total_calories,
        "part_distribution": part_distribution,
        "workouts": workouts,
    }


def query_pr_events(session: Session, start: date, end: date, *, user_id: int | None = None) -> list[dict]:
    """PR 事件：周期内某动作最佳重量超过该动作周期前的历史最大重量。"""
    def best_weights(s: date, e: date, uid: int | None = None) -> dict[str, tuple[float, str | None]]:
        bw_filters = [
            Workout.date >= s,
            Workout.date <= e,
            Workout.movements_json.isnot(None),
            Workout.deleted_at.is_(None),
        ]
        if uid is not None:
            bw_filters.append(Workout.user_id == uid)
        rows = (
            session.query(Workout)
            .filter(*bw_filters)
            .order_by(Workout.date)
            .all()
        )
        best: dict[str, tuple[float, str | None]] = {}
        for w in rows:
            for mv in _parse_movements(w):
                name = (mv.get("name") or "").strip()
                if not name:
                    continue
                for st in mv.get("sets") or []:
                    if st.get("done", True) is False:
                        continue
                    weight = _float_or_none(st.get("weight")) or 0.0
                    reps = _int_or_none(st.get("reps")) or 0
                    if weight <= 0 or reps <= 0:
                        continue
                    if name not in best or weight > best[name][0]:
                        best[name] = (weight, w.date.isoformat())
        return best

    # 周期前历史最佳（有记录起点较早，全量扫描即可，单用户数据量可控）
    history = best_weights(date(1970, 1, 1), start - timedelta(days=1), user_id)
    current = best_weights(start, end, user_id)

    events: list[dict] = []
    for name, (weight, day) in current.items():
        prev = history.get(name)
        if prev is not None and weight > prev[0]:
            events.append({
                "movement": name,
                "date": day,
                "weight": round(weight, 2),
                "prev_best": round(prev[0], 2),
            })
    return sorted(events, key=lambda e: (e["date"], e["movement"]))


def query_plan_completion(session: Session, start: date, end: date, *, user_id: int | None = None) -> dict:
    """训记官方计划完成率：周期内计划训练日 vs workout 表实际训练日。"""
    plan_filters = [
        XunjiPlan.plan_json.isnot(None),
        XunjiPlan.date_from.isnot(None),
        XunjiPlan.date_to.isnot(None),
        XunjiPlan.date_from <= end,
        XunjiPlan.date_to >= start,
    ]
    if user_id is not None:
        plan_filters.append(XunjiPlan.user_id == user_id)
    rows = (
        session.query(XunjiPlan)
        .filter(*plan_filters)
        .all()
    )
    planned_dates: set[str] = set()
    plan_name: str | None = None
    for row in rows:
        data = _parse_json(row.plan_json)
        if not isinstance(data, dict):
            continue
        plan_name = plan_name or (data.get("plan") or {}).get("name")
        for day in data.get("days") or []:
            day_str = day.get("date") or day.get("datestr")
            movements = day.get("movements") or (day.get("workout") or {}).get("movements") or []
            if not day_str or not movements:
                continue
            try:
                day_date = date.fromisoformat(day_str)
            except (ValueError, TypeError):
                continue
            if start <= day_date <= end:
                planned_dates.add(day_str)

    actual_filters = [
        Workout.date >= start,
        Workout.date <= end,
        Workout.deleted_at.is_(None),
    ]
    if user_id is not None:
        actual_filters.append(Workout.user_id == user_id)
    actual_dates = {
        w.date.isoformat()
        for w in session.query(Workout)
        .filter(*actual_filters)
        .all()
    }
    completed = planned_dates & actual_dates
    return {
        "plan_name": plan_name,
        "planned_days": len(planned_dates),
        "completed_days": len(completed),
        "rate": round(len(completed) / len(planned_dates), 3) if planned_dates else None,
        "missed_dates": sorted(planned_dates - actual_dates),
    }


def query_body_composition(session: Session, start: date, end: date, *, user_id: int | None = None) -> dict:
    """体成分变化：体重 / 体脂率的首末值与差值。"""
    result: dict[str, dict | None] = {}
    for metric_type in ("weight", "bodyfat"):
        bc_filters = [
            BodyMetric.type == metric_type,
            BodyMetric.date >= start,
            BodyMetric.date <= end,
        ]
        if user_id is not None:
            bc_filters.append(BodyMetric.user_id == user_id)
        rows = (
            session.query(BodyMetric)
            .filter(*bc_filters)
            .order_by(BodyMetric.date)
            .all()
        )
        if not rows:
            result[metric_type] = None
            continue
        first, last = rows[0], rows[-1]
        result[metric_type] = {
            "first": round(first.value, 2),
            "last": round(last.value, 2),
            "delta": round(last.value - first.value, 2),
            "count": len(rows),
            "unit": first.unit,
        }
    return result


def query_previous_review(
    session: Session, report_type: str, period_start: date, *, user_id: int | None = None
) -> dict | None:
    """上一期同类型复盘报告（供模型自评上期建议执行情况）。"""
    prev_filters = [
        AIReport.type == report_type,
        AIReport.period_start < period_start,
    ]
    if user_id is not None:
        prev_filters.append(AIReport.user_id == user_id)
    row = (
        session.query(AIReport)
        .filter(*prev_filters)
        .order_by(AIReport.period_start.desc(), AIReport.id.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "content_md": row.content_md or "",
    }


def _append_summary_lines(lines: list[str], summary: dict) -> None:
    lines.append(
        f"- 训练次数：{summary['workout_count']} 次 / {summary['training_days']} 天"
    )
    lines.append(
        f"- 总容量：{summary['total_volume_kg']} kg | "
        f"总时长：{_format_duration(summary['total_duration_s'])} | "
        f"总热量：{summary['total_calories']} 千卡"
    )
    if summary["part_distribution"]:
        lines.append("- 部位分布：")
        for p in summary["part_distribution"]:
            lines.append(
                f"  - {p['part']}：{p['sets']} 组，容量 {p['volume_kg']} kg"
            )
    else:
        lines.append("- 本周期无训练记录")
    if summary["workouts"]:
        lines.append("- 每次训练：")
        for w in summary["workouts"]:
            lines.append(
                f"  - {w['date']} {w['title'] or '未命名'}：容量 {w['volume_kg']} kg，"
                f"时长 {_format_duration(w['duration_s'])}，{w['calories'] or '-'} 千卡"
            )


def _append_recovery_lines(lines: list[str], recovery: dict, label: str) -> None:
    lines.append(f"# {label}")
    if recovery.get("days_count", 0) > 0:
        if recovery.get("avg_sleep_hours") is not None:
            lines.append(f"- 平均睡眠时长：{recovery['avg_sleep_hours']} 小时")
        if recovery.get("avg_deep_ratio") is not None:
            lines.append(f"- 平均深睡比例：{round(recovery['avg_deep_ratio'] * 100, 1)}%")
        if recovery.get("hrv_status_list"):
            lines.append(f"- HRV 状态序列：{'、'.join(recovery['hrv_status_list'])}")
        if recovery.get("resting_hr") is not None:
            lines.append(f"- 平均静息心率：{recovery['resting_hr']} bpm")
        if recovery.get("stress_avg") is not None:
            lines.append(f"- 平均压力：{recovery['stress_avg']}")
    else:
        lines.append("- 本周期无恢复数据")


_ECHARTS_REQUIREMENT = (
    "除上述章节外，文末必须附加一个 ```echarts 围栏代码块，内容为合法的 ECharts "
    "option JSON（前端直接渲染），用于可视化本周期关键数据（如部位分布饼图或容量柱状图）。"
)


def build_weekly_prompt(
    summary: dict,
    recovery: dict,
    pr_events: list[dict],
    prev_review: dict | None,
) -> list[dict]:
    """纯函数：组装周复盘 prompt（含上周建议回读，供模型自评执行情况）。"""
    lines: list[str] = []
    lines.append(f"# 本周训练汇总（{summary['start']} ~ {summary['end']}）")
    _append_summary_lines(lines, summary)

    lines.append("")
    lines.append("# 本周 PR 事件（突破历史最大重量）")
    if pr_events:
        for e in pr_events:
            lines.append(
                f"- {e['date']} {e['movement']}：{e['weight']} kg（原纪录 {e['prev_best']} kg）"
            )
    else:
        lines.append("- 本周无 PR 事件")

    lines.append("")
    _append_recovery_lines(lines, recovery, "本周睡眠与 HRV 趋势")

    lines.append("")
    lines.append("# 上周复盘报告（请自评其中建议的执行情况）")
    if prev_review:
        lines.append(
            f"上周区间：{prev_review['period_start']} ~ {prev_review['period_end']}"
        )
        lines.append(prev_review["content_md"][:_PREV_REVIEW_MAX_CHARS])
    else:
        lines.append("上周无复盘报告（本周为首次复盘）。")

    system = (
        "你是一位资深力量训练教练。请根据本周训练汇总、PR 事件、睡眠与 HRV 趋势，"
        "以及上周复盘中的建议，撰写周复盘报告。输出为 Markdown，必须且只能包含以下章节"
        "（按顺序），另加文末的 echarts 数据块：\n"
        + "\n".join(f"## {s}" for s in WEEKLY_SECTIONS)
        + "\n「上周建议执行情况」一节须逐条对照上周建议评价完成度；若上周无复盘报告，"
        "该节说明即可。\n" + _ECHARTS_REQUIREMENT
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def build_monthly_prompt(
    summary: dict,
    plan_completion: dict,
    body_composition: dict,
    recovery: dict,
) -> list[dict]:
    """纯函数：组装月复盘 prompt（含计划完成率与体成分变化）。"""
    lines: list[str] = []
    lines.append(f"# 本月训练汇总（{summary['start']} ~ {summary['end']}）")
    _append_summary_lines(lines, summary)

    lines.append("")
    lines.append("# 训记官方计划完成率")
    if plan_completion["planned_days"] > 0:
        lines.append(f"- 计划：{plan_completion['plan_name'] or '未命名计划'}")
        lines.append(
            f"- 计划训练日：{plan_completion['planned_days']} 天，"
            f"实际完成：{plan_completion['completed_days']} 天，"
            f"完成率：{round(plan_completion['rate'] * 100, 1)}%"
        )
        if plan_completion["missed_dates"]:
            lines.append(f"- 错过日期：{'、'.join(plan_completion['missed_dates'])}")
    else:
        lines.append("- 本周期无训记计划缓存，无法计算完成率")

    lines.append("")
    lines.append("# 体成分变化")
    label = {"weight": "体重", "bodyfat": "体脂率"}
    for key in ("weight", "bodyfat"):
        item = body_composition.get(key)
        if item:
            sign = "+" if item["delta"] > 0 else ""
            lines.append(
                f"- {label[key]}：{item['first']} → {item['last']} {item['unit']}"
                f"（{sign}{item['delta']}，{item['count']} 条记录）"
            )
        else:
            lines.append(f"- {label[key]}：本周期无体重记录" if key == "weight"
                         else f"- {label[key]}：本周期无记录")

    lines.append("")
    _append_recovery_lines(lines, recovery, "本月睡眠与恢复概况")

    system = (
        "你是一位资深力量训练教练。请根据本月训练汇总、训记计划完成率、体成分变化"
        "与睡眠恢复概况，撰写月复盘报告。输出为 Markdown，必须且只能包含以下章节"
        "（按顺序），另加文末的 echarts 数据块：\n"
        + "\n".join(f"## {s}" for s in MONTHLY_SECTIONS)
        + "\n" + _ECHARTS_REQUIREMENT
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _generate_period_review(
    session: Session,
    report_type: str,
    period_start: date,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> AIReport:
    """周/月复盘共用生成流程：组装 prompt → 调用模型 → 落库 ai_report。

    user_id 用于归属报告（多用户隔离，M2-4）。
    """
    if report_type == "weekly":
        start, end = week_range(period_start)
        summary = query_period_training_summary(session, start, end, user_id=user_id)
        recovery = query_recovery_summary(session, end, days=7, user_id=user_id)
        pr_events = query_pr_events(session, start, end, user_id=user_id)
        prev = query_previous_review(session, "weekly", start, user_id=user_id)
        messages = build_weekly_prompt(summary, recovery, pr_events, prev)
    else:
        start, end = month_range(period_start)
        summary = query_period_training_summary(session, start, end, user_id=user_id)
        recovery = query_recovery_summary(session, end, days=30, user_id=user_id)
        plan_completion = query_plan_completion(session, start, end, user_id=user_id)
        body_composition = query_body_composition(session, start, end, user_id=user_id)
        messages = build_monthly_prompt(summary, plan_completion, body_composition, recovery)

    if chat_fn is None:
        chat_fn = lambda msgs: llm.chat(  # noqa: E731
            msgs, session=session, purpose=report_type
        )

    result = chat_fn(messages)
    content = result.get("content", "")
    prompt_tokens = result.get("prompt_tokens") or 0
    completion_tokens = result.get("completion_tokens") or 0

    provider = _resolve_provider(session)
    model = result.get("model") or llm.PROVIDERS[provider]["default_model"]
    cost = llm.compute_cost(provider, prompt_tokens, completion_tokens)

    report = AIReport(
        type=report_type,
        workout_id=None,
        user_id=user_id,
        period_start=start,
        period_end=end,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate=round(cost, 6),
        content_md=content,
    )
    session.add(report)
    session.commit()
    return report


def generate_weekly_review(
    session: Session,
    week_day: date,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> AIReport:
    """生成 week_day 所在 ISO 周（周一至周日）的周复盘。"""
    return _generate_period_review(session, "weekly", week_day, chat_fn=chat_fn, user_id=user_id)


def generate_monthly_review(
    session: Session,
    month_day: date,
    *,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> AIReport:
    """生成 month_day 所在自然月的月复盘。"""
    return _generate_period_review(session, "monthly", month_day, chat_fn=chat_fn, user_id=user_id)


def _write_review_job_run(session: Session, job_name: str, started_at: datetime,
                          result: dict) -> None:
    import json as _json

    session.add(JobRun(
        job_name=job_name,
        started_at=started_at,
        finished_at=datetime.now(),
        status=result["status"],
        error=result["error"],
        detail_json=_json.dumps(result["detail"], ensure_ascii=False, default=str),
    ))
    session.commit()


def _run_period_review(
    report_type: str,
    day: date | str | None,
    *,
    session: Session | None = None,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> dict:
    """周/月复盘编排：幂等（同周期已存在则跳过），每次运行写 JobRun，失败不外抛。

    user_id 用于归属与幂等去重（多用户隔离，M2-4；None 匹配存量 NULL 行）。
    """
    from app.db import SessionLocal

    job_name = f"{report_type}_review"
    if day is None:
        day_date = date.today()
    elif isinstance(day, str):
        day_date = date.fromisoformat(day)
    else:
        day_date = day
    range_fn = week_range if report_type == "weekly" else month_range
    start, end = range_fn(day_date)

    own_session = session is None
    session = session or SessionLocal()
    started_at = datetime.now()
    try:
        detail: dict[str, Any] = {
            "period_start": start.isoformat(), "period_end": end.isoformat(),
        }
        existing_filters = [
            AIReport.type == report_type,
            AIReport.period_start == start,
        ]
        if user_id is not None:
            existing_filters.append(AIReport.user_id == user_id)
        existing = session.scalars(
            select(AIReport).where(*existing_filters)
        ).first()
        if existing is not None:
            detail["report_id"] = existing.id
            result = {"status": "success", "error": None, "detail": detail,
                      "generated": False, "skipped": True,
                      "report_id": existing.id,
                      "period_start": start.isoformat(), "period_end": end.isoformat()}
            _write_review_job_run(session, job_name, started_at, result)
            return result

        try:
            report = _generate_period_review(
                session, report_type, start, chat_fn=chat_fn, user_id=user_id
            )
        except Exception as exc:
            detail["reason"] = "generate_failed"
            result = {"status": "failed", "error": str(exc), "detail": detail,
                      "generated": False, "skipped": False, "report_id": None,
                      "period_start": start.isoformat(), "period_end": end.isoformat()}
            _write_review_job_run(session, job_name, started_at, result)
            return result

        detail["report_id"] = report.id
        result = {"status": "success", "error": None, "detail": detail,
                  "generated": True, "skipped": False, "report_id": report.id,
                  "period_start": start.isoformat(), "period_end": end.isoformat()}
        _write_review_job_run(session, job_name, started_at, result)
        return result
    finally:
        if own_session:
            session.close()


def run_weekly_review(
    day: date | str | None = None,
    *,
    session: Session | None = None,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> dict:
    """每周日 21:13 调度：生成 day（默认今天）所在周的周复盘。"""
    return _run_period_review("weekly", day, session=session, chat_fn=chat_fn, user_id=user_id)


def run_monthly_review(
    day: date | str | None = None,
    *,
    session: Session | None = None,
    chat_fn: Callable[[list[dict]], dict] | None = None,
    user_id: int | None = None,
) -> dict:
    """每月 1 日 09:23 调度：生成 day 所在月的月复盘（调度器传入前一天，即复盘上月）。"""
    return _run_period_review("monthly", day, session=session, chat_fn=chat_fn, user_id=user_id)
