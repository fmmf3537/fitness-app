"""V1-7 身体数据业务逻辑（PRD US-12 / §4 body_metric）。

- 六类指标：height / weight / bodyfat / bp_systolic / bp_diastolic / blood_glucose；
- 按 (date, type) upsert，同日同类型重复录入覆盖旧值；
- 边界值校验：超出合理区间直接拒绝（如血糖 0.5~40 mmol/L）；
- 仅 weight/bodyfat 可同步训记（PRD §6.1b），其余仅本地。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMetric

# 指标定义：默认单位 + 合理区间 [min, max]
METRIC_TYPES: dict[str, dict] = {
    "height": {"unit": "cm", "min": 50.0, "max": 250.0},
    "weight": {"unit": "kg", "min": 10.0, "max": 400.0},
    "bodyfat": {"unit": "%", "min": 1.0, "max": 70.0},
    "bp_systolic": {"unit": "mmHg", "min": 40.0, "max": 300.0},
    "bp_diastolic": {"unit": "mmHg", "min": 20.0, "max": 200.0},
    "blood_glucose": {"unit": "mmol/L", "min": 0.5, "max": 40.0},
}

# 可同步到训记的类型（PRD §6.1b：训记仅支持 weight/bodyfat/围度）
SYNCABLE_TYPES = frozenset({"weight", "bodyfat"})


class BodyMetricValidationError(ValueError):
    """指标类型或数值非法。"""


def validate_metric(type_: str, value: float) -> str:
    """校验类型与数值区间，返回默认单位；非法抛 BodyMetricValidationError。"""
    spec = METRIC_TYPES.get(type_)
    if spec is None:
        raise BodyMetricValidationError(
            f"不支持的指标类型: {type_!r}（支持：{'/'.join(METRIC_TYPES)}）"
        )
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise BodyMetricValidationError(f"数值非法: {value!r}") from exc
    if not (spec["min"] <= v <= spec["max"]):
        raise BodyMetricValidationError(
            f"{type_} 数值 {v} 超出合理区间 [{spec['min']}, {spec['max']}] {spec['unit']}"
        )
    return spec["unit"]


def upsert_body_metric(
    session: Session,
    day: date,
    type_: str,
    value: float,
    *,
    unit: str | None = None,
    note: str | None = None,
) -> BodyMetric:
    """按 (date, type) upsert：同日同类型覆盖旧值（幂等）。"""
    default_unit = validate_metric(type_, value)
    stmt = select(BodyMetric).where(BodyMetric.date == day, BodyMetric.type == type_)
    row = session.scalars(stmt).first()
    if row is None:
        row = BodyMetric(date=day, type=type_)
        session.add(row)
    row.value = float(value)
    row.unit = unit or default_unit
    row.note = note
    session.commit()
    return row


def query_body_metrics(
    session: Session,
    type_: str | None = None,
    from_: date | None = None,
    to: date | None = None,
) -> list[BodyMetric]:
    """趋势查询：按类型/日期区间过滤，日期升序。"""
    stmt = select(BodyMetric).order_by(BodyMetric.date, BodyMetric.id)
    if type_ is not None:
        stmt = stmt.where(BodyMetric.type == type_)
    if from_ is not None:
        stmt = stmt.where(BodyMetric.date >= from_)
    if to is not None:
        stmt = stmt.where(BodyMetric.date <= to)
    return list(session.scalars(stmt))


def to_dict(row: BodyMetric) -> dict:
    """序列化为 API 响应字典。"""
    return {
        "id": row.id,
        "date": row.date.isoformat(),
        "type": row.type,
        "value": row.value,
        "unit": row.unit,
        "synced_to_xunji": bool(row.synced_to_xunji),
        "note": row.note,
    }
