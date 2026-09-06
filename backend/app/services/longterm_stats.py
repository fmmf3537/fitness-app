"""V5-3 AI 教练长期记忆：L3 长期统计（12 周聚合）。

复用 ai.query_period_training_summary / query_pr_events / query_body_composition，
输出适配 build_memory_section(l3=...) 的中文字典；无训练数据返回 None。
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

LONGTERM_WEEKS = 12  # 默认 12 周窗口（PRD-V5 §6.3）

# weekly / monthly 注入时只保留这三项，避免与本期 summary 段重复
PERIOD_L3_KEYS = ("训练频率", "总容量", "部位分布")


def _last_n_weeks_range(anchor_date: date, weeks: int = LONGTERM_WEEKS) -> tuple[date, date]:
    """[anchor_date - weeks * 7, anchor_date) —— 不含锚点日当天。"""
    start = anchor_date - timedelta(days=weeks * 7)
    end = anchor_date - timedelta(days=1)
    return start, end


def _fmt_num(value: float) -> str:
    """整数去小数点，否则保留原精度（已 round 的聚合值）。"""
    if value == int(value):
        return str(int(value))
    return str(value)


def _fmt_freq(value: float) -> str:
    """训练频率：保留 1 位小数；整数值省略小数点。"""
    rounded = round(value, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}"


def query_longterm_stats(
    session: Session,
    anchor_date: date,
    *,
    weeks: int = LONGTERM_WEEKS,
) -> dict | None:
    """返回 l3 段数据（dict 形态适配 build_memory_section 的 l3 参数）。

    返回字段（key → 中文 value 字符串）：
        训练频率: "X 次/周（Y 个训练日，共 Z 周）"
        总容量: "X kg（Y 次有效组）"
        平均时长: "X 分钟/次"
        平均热量: "X 千卡/次"
        部位分布: "胸 X kg / 腿 Y kg / ..."  （按容量降序取 top-5）
        PR 事件: "N 次突破历史最大重量"  （仅 N>0 时显示）
        体重趋势: "X.X kg（Δ±Y.Y）"  （仅当有 weight 数据且 delta != 0 时显示）

    全空（无训练数据）返回 None（与 build_memory_section 的 l3=None 行为一致）。
    """
    from app.services.ai import (
        query_body_composition,
        query_period_training_summary,
        query_pr_events,
    )

    if weeks <= 0:
        return None

    start, end = _last_n_weeks_range(anchor_date, weeks)
    if end < start:
        return None

    summary = query_period_training_summary(session, start, end)
    if not summary.get("workout_count"):
        return None

    out: dict[str, str] = {}

    training_days = int(summary.get("training_days") or 0)
    if training_days > 0:
        freq = training_days / weeks
        out["训练频率"] = (
            f"{_fmt_freq(freq)} 次/周（{training_days} 个训练日，共 {weeks} 周）"
        )

    total_volume = float(summary.get("total_volume_kg") or 0)
    effective_sets = sum(
        int(p.get("sets") or 0) for p in (summary.get("part_distribution") or [])
    )
    if total_volume > 0:
        out["总容量"] = f"{_fmt_num(total_volume)} kg（{effective_sets} 次有效组）"

    workout_count = int(summary.get("workout_count") or 0)
    total_duration_s = int(summary.get("total_duration_s") or 0)
    if workout_count > 0 and total_duration_s > 0:
        avg_min = int(total_duration_s / 60 / workout_count)
        if avg_min > 0:
            out["平均时长"] = f"{avg_min} 分钟/次"

    total_calories = int(summary.get("total_calories") or 0)
    if workout_count > 0 and total_calories > 0:
        avg_cal = int(total_calories / workout_count)
        if avg_cal > 0:
            out["平均热量"] = f"{avg_cal} 千卡/次"

    parts = sorted(
        summary.get("part_distribution") or [],
        key=lambda p: float(p.get("volume_kg") or 0),
        reverse=True,
    )[:5]
    part_bits = []
    for p in parts:
        vol = float(p.get("volume_kg") or 0)
        if vol <= 0:
            continue
        part_bits.append(f"{p.get('part', '其他')} {_fmt_num(vol)} kg")
    if part_bits:
        out["部位分布"] = " / ".join(part_bits)

    pr_events = query_pr_events(session, start, end)
    if pr_events:
        out["PR 事件"] = f"{len(pr_events)} 次突破历史最大重量"

    body = query_body_composition(session, start, end)
    weight = body.get("weight") if isinstance(body, dict) else None
    if weight and weight.get("delta") not in (None, 0, 0.0):
        last = float(weight["last"])
        delta = float(weight["delta"])
        sign = "+" if delta > 0 else ""
        out["体重趋势"] = f"{_fmt_num(last)} kg（Δ{sign}{_fmt_num(delta)}）"

    return out or None


def filter_period_l3(l3: dict | None) -> dict | None:
    """weekly / monthly：只保留训练频率 / 总容量 / 部位分布，避免与本期 summary 重叠。"""
    if not l3:
        return None
    filtered = {k: l3[k] for k in PERIOD_L3_KEYS if k in l3 and l3[k]}
    return filtered or None
