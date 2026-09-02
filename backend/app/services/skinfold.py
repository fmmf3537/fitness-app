"""V4-3 皮脂钳体脂率测量（PRD F5）。

4 方案公式：
- Jackson-Pollock 3 点（男 / 女，部位和 + 年龄）
- Jackson-Pollock 7 点（男 / 女）
- Durnin-Womersley 4 点（性别 + 年龄带查表）
四方案共用 Siri 公式把身体密度换算成体脂率。

同日同 method 幂等 upsert 体脂率到 ``body_metric``；
性别 / 出生日期存在 ``settings`` 单行（一次录入永久生效）。
"""
from __future__ import annotations

import json
import math
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting, SkinfoldRecord
from app.services.body_metrics import upsert_body_metric

# ---- 部位 key → 中文名（前端回显用） ----
SITE_NAME_ZH: dict[str, str] = {
    "chest": "胸",
    "abdomen": "腹",
    "thigh": "大腿",
    "triceps": "肱三头",
    "suprailiac": "髂前上棘",
    "biceps": "肱二头",
    "subscapular": "肩胛下",
    "midaxillary": "腋中",
}

# ---- 方案元数据 ----
# - name_zh：方案中文名（note 写入 body_metric 用）；
# - sites：必需部位 key 列表；
# - sex：该方案限定的性别（None=不限）；
# - self_test：自测难度（前端引导文案用）：
#   yes=自测即可 / assist=建议他人协助 / no=需专业人员。
METHODS: dict[str, dict] = {
    "jp3_male": {
        "name_zh": "Jackson-Pollock 3 点（男）",
        "sites": ["chest", "abdomen", "thigh"],
        "sex": "male",
        "self_test": "yes",
    },
    "jp3_female": {
        "name_zh": "Jackson-Pollock 3 点（女）",
        "sites": ["triceps", "suprailiac", "thigh"],
        "sex": "female",
        "self_test": "assist",
    },
    "dw4": {
        "name_zh": "Durnin-Womersley 4 点",
        "sites": ["biceps", "triceps", "subscapular", "suprailiac"],
        "sex": None,
        "self_test": "no",
    },
    "jp7": {
        "name_zh": "Jackson-Pollock 7 点",
        "sites": [
            "chest", "midaxillary", "triceps", "subscapular",
            "abdomen", "suprailiac", "thigh",
        ],
        "sex": None,
        "self_test": "no",
    },
}

# Durnin-Womersley 4 点：按 (性别, 年龄带) 查 (c0, c1)
# 年龄 <17 按 17-19 带
_DW_TABLE: dict[tuple[str, str], tuple[float, float]] = {
    ("male", "17-19"): (1.1620, 0.0630),
    ("male", "20-29"): (1.1631, 0.0632),
    ("male", "30-39"): (1.1422, 0.0544),
    ("male", "40-49"): (1.1620, 0.0700),
    ("male", "50+"):   (1.1715, 0.0779),
    ("female", "17-19"): (1.1549, 0.0678),
    ("female", "20-29"): (1.1599, 0.0717),
    ("female", "30-39"): (1.1423, 0.0632),
    ("female", "40-49"): (1.1333, 0.0612),
    ("female", "50+"):   (1.1339, 0.0645),
}

_MM_MIN = 2.0
_MM_MAX = 60.0
_AGE_MIN = 10
_AGE_MAX = 120


class SkinfoldValidationError(ValueError):
    """皮脂钳测量输入非法（部位缺失、mm 超界、性别不匹配、年龄越界等）。"""


def _age_band(age: int) -> str:
    if age < 17:
        return "17-19"
    if age <= 19:
        return "17-19"
    if age <= 29:
        return "20-29"
    if age <= 39:
        return "30-39"
    if age <= 49:
        return "40-49"
    return "50+"


def _calc_density(method: str, sites: dict[str, float], gender: str, age: int) -> float:
    if method == "jp3_male":
        if gender != "male":
            raise SkinfoldValidationError("该方案仅适用于男性，请选择正确的方案")
        total = sites["chest"] + sites["abdomen"] + sites["thigh"]
        return (
            1.10938
            - 0.0008267 * total
            + 0.0000016 * total * total
            - 0.0002574 * age
        )
    if method == "jp3_female":
        if gender != "female":
            raise SkinfoldValidationError("该方案仅适用于女性，请选择正确的方案")
        total = sites["triceps"] + sites["suprailiac"] + sites["thigh"]
        return (
            1.0994921
            - 0.0009929 * total
            + 0.0000023 * total * total
            - 0.0001392 * age
        )
    if method == "jp7":
        total = sum(sites[s] for s in METHODS["jp7"]["sites"])
        if gender == "male":
            return (
                1.112
                - 0.00043499 * total
                + 0.00000055 * total * total
                - 0.00028826 * age
            )
        return (
            1.097
            - 0.00046971 * total
            + 0.00000056 * total * total
            - 0.00012828 * age
        )
    if method == "dw4":
        total = sum(sites[s] for s in METHODS["dw4"]["sites"])
        log_sum = math.log10(total)
        c0, c1 = _DW_TABLE[(gender, _age_band(age))]
        return c0 - c1 * log_sum
    raise SkinfoldValidationError(f"未知方案: {method!r}")


def compute_bodyfat(
    method: str,
    sites: dict[str, float],
    *,
    gender: str,
    age: int,
) -> tuple[float, float]:
    """计算身体密度与体脂率（%）。

    返回 ``(density, bodyfat%)``；bodyfat 保留 2 位小数。
    校验失败抛 :class:`SkinfoldValidationError`，中文消息。
    """
    if method not in METHODS:
        raise SkinfoldValidationError(
            f"未知方案: {method!r}（支持: {', '.join(METHODS)}）"
        )
    if gender not in ("male", "female"):
        raise SkinfoldValidationError(
            f"性别非法: {gender!r}（应为 male / female）"
        )
    if not isinstance(age, int) or age < _AGE_MIN or age > _AGE_MAX:
        raise SkinfoldValidationError(
            f"年龄 {age} 超出合理区间 [{_AGE_MIN}, {_AGE_MAX}]"
        )

    expected_sites = METHODS[method]["sites"]
    missing = [s for s in expected_sites if s not in sites]
    if missing:
        names = "、".join(f"{s}({SITE_NAME_ZH[s]})" for s in missing)
        raise SkinfoldValidationError(f"缺少部位: {names}")
    extra = [s for s in sites if s not in expected_sites]
    if extra:
        names = "、".join(s for s in extra)
        raise SkinfoldValidationError(f"该方案无需部位: {names}")

    for site in expected_sites:
        v = sites[site]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise SkinfoldValidationError(f"部位 {site} 数值类型非法: {v!r}")
        if v < _MM_MIN or v > _MM_MAX:
            names_zh = SITE_NAME_ZH.get(site, site)
            raise SkinfoldValidationError(
                f"部位 {names_zh} 数值 {v} mm 超出合理区间 "
                f"[{_MM_MIN:.0f}, {_MM_MAX:.0f}]"
            )

    sex_required = METHODS[method]["sex"]
    if sex_required is not None and sex_required != gender:
        zh = "男" if sex_required == "male" else "女"
        raise SkinfoldValidationError(
            f"该方案仅适用于{zh}性，请选择正确的方案"
        )

    density = _calc_density(method, sites, gender, age)
    bodyfat = (4.95 / density - 4.5) * 100
    return density, round(bodyfat, 2)


def _get_or_create_settings(session: Session) -> Setting:
    row = session.scalars(select(Setting)).first()
    if row is None:
        row = Setting()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _require_profile(session: Session) -> Setting:
    """读取 settings 单行；缺 gender / birth_date 抛 SkinfoldValidationError。

    与 :func:`_get_or_create_settings` 不同：缺失时不会落空行到库。
    """
    row = session.scalars(select(Setting)).first()
    if row is None or not row.gender or not row.birth_date:
        missing: list[str] = []
        if row is None or not row.gender:
            missing.append("性别")
        if row is None or not row.birth_date:
            missing.append("出生日期")
        raise SkinfoldValidationError(
            f"请先在设置页填写{'、'.join(missing)}后再录入皮脂钳测量"
        )
    return row


def get_profile(session: Session) -> dict:
    """从 settings 单行读性别 / 出生日期；未设置字段返回 None。"""
    row = session.scalars(select(Setting)).first()
    if row is None:
        return {"gender": None, "birth_date": None}
    return {
        "gender": row.gender,
        "birth_date": row.birth_date.isoformat() if row.birth_date else None,
    }


def upsert_skinfold_record(
    session: Session,
    day: date,
    method: str,
    sites: dict[str, Any],
    note: str | None = None,
) -> tuple[SkinfoldRecord, Any]:
    """按 (date, method) 幂等 upsert 一条皮脂钳测量。

    流程：从 settings 单行读 gender / birth_date（缺失抛 SkinfoldValidationError，
    消息明确提示"请先在设置页填写性别/出生日期"）→ 按测量日期推算 age →
    :func:`compute_bodyfat` → 写入 :class:`SkinfoldRecord` → 复用
    :func:`app.services.body_metrics.upsert_body_metric` 把体脂率落
    ``body_metric(type='bodyfat')``（note 注明来源方案）。整体一个事务。
    """
    settings_row = _require_profile(session)

    if not isinstance(sites, dict):
        raise SkinfoldValidationError(f"sites 必须为字典，收到: {type(sites).__name__}")

    sites_clean = {k: float(v) for k, v in sites.items()}
    today = date.today()
    age = today.year - settings_row.birth_date.year - (
        (today.month, today.day) < (settings_row.birth_date.month, settings_row.birth_date.day)
    )
    if age < _AGE_MIN or age > _AGE_MAX:
        raise SkinfoldValidationError(
            f"根据出生日期推算年龄 {age} 超出合理区间 [{_AGE_MIN}, {_AGE_MAX}]"
        )

    density, bodyfat = compute_bodyfat(
        method, sites_clean, gender=settings_row.gender, age=age
    )

    stmt = select(SkinfoldRecord).where(
        SkinfoldRecord.date == day, SkinfoldRecord.method == method
    )
    row = session.scalars(stmt).first()
    if row is None:
        row = SkinfoldRecord(date=day, method=method)
        session.add(row)
    row.sites_json = json.dumps(sites_clean, ensure_ascii=False)
    row.density = density
    row.bodyfat_result = bodyfat
    row.note = note
    session.commit()

    method_zh = METHODS[method]["name_zh"]
    bodyfat_note = note or f"皮脂钳 {method_zh}"
    body_row = upsert_body_metric(
        session, day, "bodyfat", bodyfat, note=bodyfat_note
    )
    return row, body_row


def query_skinfold_records(
    session: Session,
    method: str | None = None,
    day: date | None = None,
) -> list[SkinfoldRecord]:
    """按 method / day 过滤查询，日期倒序。"""
    stmt = select(SkinfoldRecord).order_by(SkinfoldRecord.date.desc(), SkinfoldRecord.id.desc())
    if method is not None:
        stmt = stmt.where(SkinfoldRecord.method == method)
    if day is not None:
        stmt = stmt.where(SkinfoldRecord.date == day)
    return list(session.scalars(stmt))


def to_dict(row: SkinfoldRecord) -> dict:
    """序列化为 API 响应字典；``sites_json`` 反序列化为 dict。"""
    try:
        sites = json.loads(row.sites_json) if row.sites_json else {}
    except (TypeError, ValueError):
        sites = {}
    return {
        "id": row.id,
        "date": row.date.isoformat(),
        "method": row.method,
        "method_zh": METHODS.get(row.method, {}).get("name_zh", row.method),
        "sites": sites,
        "density": round(row.density, 5),
        "bodyfat_result": row.bodyfat_result,
        "note": row.note,
    }