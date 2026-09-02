"""V4-3 皮脂钳公式 + 服务层测试。

- 文献样例校验：四方案 6 用例，bodyfat% 误差 ≤0.1；
- 校验分支：mm 越界 / 缺部位 / 性别不匹配 / 年龄越界 / 非法 method；
- 服务层：settings 缺失提示，幂等 upsert（record + bodyfat body_metric）。
"""
from datetime import date

import pytest

from app.models import BodyMetric, Setting, SkinfoldRecord
from app.services.skinfold import (
    METHODS,
    SkinfoldValidationError,
    compute_bodyfat,
    get_profile,
    query_skinfold_records,
    upsert_skinfold_record,
)


# ---------- 公式：文献样例 ----------

_LITERATURE_CASES = [
    # (method, sites, gender, age, expected_bodyfat)
    (
        "jp3_male",
        {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
        "male", 30, 13.61,
    ),
    (
        "jp3_female",
        {"triceps": 15.0, "suprailiac": 12.0, "thigh": 20.0},
        "female", 28, 19.64,
    ),
    (
        "jp7",
        {
            "chest": 10.0, "midaxillary": 12.0, "triceps": 15.0,
            "subscapular": 14.0, "abdomen": 20.0, "suprailiac": 12.0,
            "thigh": 15.0,
        },
        "male", 30, 14.35,
    ),
    (
        "jp7",
        {
            "chest": 10.0, "midaxillary": 12.0, "triceps": 15.0,
            "subscapular": 14.0, "abdomen": 20.0, "suprailiac": 12.0,
            "thigh": 15.0,
        },
        "female", 28, 20.20,
    ),
    (
        "dw4",
        {"biceps": 10.0, "triceps": 12.0, "subscapular": 15.0, "suprailiac": 14.0},
        "male", 25, 19.11,
    ),
    (
        "dw4",
        {"biceps": 10.0, "triceps": 12.0, "subscapular": 15.0, "suprailiac": 14.0},
        "female", 35, 28.55,
    ),
]


@pytest.mark.parametrize(
    "method,sites,gender,age,expected", _LITERATURE_CASES,
    ids=[
        "jp3_male_age30", "jp3_female_age28",
        "jp7_male_age30", "jp7_female_age28",
        "dw4_male_age25", "dw4_female_age35",
    ],
)
def test_compute_bodyfat_literature(method, sites, gender, age, expected):
    density, bodyfat = compute_bodyfat(method, sites, gender=gender, age=age)
    assert 0.9 < density < 1.2
    assert abs(bodyfat - expected) < 0.1, (
        f"{method}/{gender}/age{age}: got {bodyfat}, expected {expected}"
    )


# ---------- 公式：校验分支 ----------


def test_mm_below_range_rejected():
    with pytest.raises(SkinfoldValidationError, match="超出合理区间"):
        compute_bodyfat(
            "jp3_male", {"chest": 1.0, "abdomen": 20.0, "thigh": 15.0},
            gender="male", age=30,
        )


def test_mm_above_range_rejected():
    with pytest.raises(SkinfoldValidationError, match="超出合理区间"):
        compute_bodyfat(
            "jp3_male", {"chest": 10.0, "abdomen": 20.0, "thigh": 61.0},
            gender="male", age=30,
        )


def test_missing_site_rejected():
    with pytest.raises(SkinfoldValidationError, match="缺少部位"):
        compute_bodyfat(
            "jp3_male", {"chest": 10.0, "abdomen": 20.0},  # 缺 thigh
            gender="male", age=30,
        )


def test_jp3_male_requires_male():
    with pytest.raises(SkinfoldValidationError, match="仅适用于男性"):
        compute_bodyfat(
            "jp3_male", {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            gender="female", age=30,
        )


def test_jp3_female_requires_female():
    with pytest.raises(SkinfoldValidationError, match="仅适用于女性"):
        compute_bodyfat(
            "jp3_female", {"triceps": 15.0, "suprailiac": 12.0, "thigh": 20.0},
            gender="male", age=28,
        )


def test_age_below_min_rejected():
    with pytest.raises(SkinfoldValidationError, match="超出合理区间"):
        compute_bodyfat(
            "jp3_male", {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            gender="male", age=9,
        )


def test_age_above_max_rejected():
    with pytest.raises(SkinfoldValidationError, match="超出合理区间"):
        compute_bodyfat(
            "jp3_male", {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            gender="male", age=121,
        )


def test_invalid_method_rejected():
    with pytest.raises(SkinfoldValidationError, match="未知方案"):
        compute_bodyfat(
            "jp99", {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
            gender="male", age=30,
        )


def test_invalid_gender_rejected():
    with pytest.raises(SkinfoldValidationError, match="性别非法"):
        compute_bodyfat(
            "jp7", {s: 12.0 for s in METHODS["jp7"]["sites"]},
            gender="other", age=30,
        )


# ---------- 服务层：upsert_skinfold_record ----------


def _seed_settings(session, gender="male", birth_year=1994):
    row = Setting(
        gender=gender,
        birth_date=date(birth_year, 6, 15),
    )
    session.add(row)
    session.commit()
    return row


def test_upsert_writes_record_and_bodyfat_body_metric(session):
    _seed_settings(session, gender="male", birth_year=1990)
    record, body_row = upsert_skinfold_record(
        session,
        day=date(2026, 8, 10),
        method="jp3_male",
        sites={"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
    )
    assert record.id is not None
    assert record.method == "jp3_male"
    assert record.bodyfat_result > 0
    assert record.density > 0

    assert body_row.type == "bodyfat"
    assert body_row.date == date(2026, 8, 10)
    assert body_row.value == record.bodyfat_result
    assert "皮脂钳" in (body_row.note or "")
    assert "Jackson-Pollock 3 点（男）" in (body_row.note or "")


def test_upsert_idempotent_same_day_same_method(session):
    _seed_settings(session, gender="male", birth_year=1990)
    day = date(2026, 8, 10)
    sites1 = {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0}
    sites2 = {"chest": 12.0, "abdomen": 22.0, "thigh": 16.0}

    r1, b1 = upsert_skinfold_record(session, day, "jp3_male", sites1)
    r2, b2 = upsert_skinfold_record(session, day, "jp3_male", sites2)

    assert r1.id == r2.id  # 同 (date, method) → 同一行
    assert b1.id == b2.id

    records = session.query(SkinfoldRecord).filter_by(date=day, method="jp3_male").all()
    assert len(records) == 1
    assert records[0].bodyfat_result == r2.bodyfat_result

    bms = session.query(BodyMetric).filter_by(date=day, type="bodyfat").all()
    assert len(bms) == 1
    assert bms[0].value == r2.bodyfat_result


def test_upsert_different_methods_coexist(session):
    _seed_settings(session, gender="male", birth_year=1990)
    day = date(2026, 8, 10)
    upsert_skinfold_record(
        session, day, "jp3_male",
        {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
    )
    upsert_skinfold_record(
        session, day, "dw4",
        {"biceps": 10.0, "triceps": 12.0, "subscapular": 15.0, "suprailiac": 14.0},
    )
    assert session.query(SkinfoldRecord).count() == 2


def test_upsert_without_settings_gender_raises_with_chinese_hint(session):
    """settings 单行不存在 → 抛错且消息含「设置页」。"""
    with pytest.raises(SkinfoldValidationError) as exc_info:
        upsert_skinfold_record(
            session, date(2026, 8, 10), "jp3_male",
            {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
        )
    assert "设置页" in str(exc_info.value)


def test_upsert_without_settings_birth_date_raises_with_chinese_hint(session):
    """settings 只有 gender 没有 birth_date → 同样提示。"""
    session.add(Setting(gender="male"))
    session.commit()
    with pytest.raises(SkinfoldValidationError) as exc_info:
        upsert_skinfold_record(
            session, date(2026, 8, 10), "jp3_male",
            {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
        )
    assert "设置页" in str(exc_info.value)
    assert "出生日期" in str(exc_info.value)


def test_get_profile_returns_null_when_no_settings(session):
    assert get_profile(session) == {"gender": None, "birth_date": None}


def test_get_profile_reads_settings_row(session):
    _seed_settings(session, gender="female", birth_year=1996)
    assert get_profile(session) == {
        "gender": "female",
        "birth_date": "1996-06-15",
    }


def test_query_skinfold_records_desc_by_date(session):
    _seed_settings(session, gender="male", birth_year=1990)
    upsert_skinfold_record(
        session, date(2026, 8, 10), "jp3_male",
        {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
    )
    upsert_skinfold_record(
        session, date(2026, 8, 12), "jp3_male",
        {"chest": 11.0, "abdomen": 21.0, "thigh": 16.0},
    )
    rows = query_skinfold_records(session)
    assert [r.date for r in rows] == [date(2026, 8, 12), date(2026, 8, 10)]


def test_query_filter_by_method_and_date(session):
    _seed_settings(session, gender="male", birth_year=1990)
    upsert_skinfold_record(
        session, date(2026, 8, 10), "jp3_male",
        {"chest": 10.0, "abdomen": 20.0, "thigh": 15.0},
    )
    upsert_skinfold_record(
        session, date(2026, 8, 10), "dw4",
        {"biceps": 10.0, "triceps": 12.0, "subscapular": 15.0, "suprailiac": 14.0},
    )
    only_jp3 = query_skinfold_records(session, method="jp3_male")
    assert len(only_jp3) == 1 and only_jp3[0].method == "jp3_male"
    only_day = query_skinfold_records(session, day=date(2026, 8, 10))
    assert len(only_day) == 2