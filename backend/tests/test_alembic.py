"""Alembic 初始迁移 upgrade/downgrade 往返测试。"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "settings",
    "skinfold_record",
    "xunji_train",
    "garmin_activity",
    "garmin_daily",
    "body_metric",
    "workout",
    "match_candidate",
    "xunji_plan",
    "ai_report",
    "llm_call",
    "job_run",
    "backfill_progress",
    "report_chat_message",
    "workout_set_hr",
    "coach_preference",
    "coach_preference_draft",
    "coach_memory",
    "coach_chat_message",
    "garmin_plan_sync",
    "exercise_mapping",
    "exercise_mapping_candidate",
    "exercise_mapping_audit",
}


def _make_config(db_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_upgrade_creates_all_tables(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert EXPECTED_TABLES <= set(insp.get_table_names())


def test_upgrade_downgrade_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    insp = inspect(create_engine(db_url))
    remaining = set(insp.get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_workout_soft_delete_columns_roundtrip(tmp_path):
    """V3-11：workout.deleted_at + 两源表 excluded，升级出现、回滚消失、再升级回来。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "deleted_at" in {c["name"] for c in insp.get_columns("workout")}
    assert "excluded" in {c["name"] for c in insp.get_columns("garmin_activity")}
    assert "excluded" in {c["name"] for c in insp.get_columns("xunji_train")}

    command.downgrade(cfg, "e4f5a6b7c8d9")  # 回退到 f5a6b7c8d9e0 之前
    insp = inspect(create_engine(db_url))
    assert "deleted_at" not in {c["name"] for c in insp.get_columns("workout")}
    assert "excluded" not in {c["name"] for c in insp.get_columns("garmin_activity")}
    assert "excluded" not in {c["name"] for c in insp.get_columns("xunji_train")}

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "deleted_at" in {c["name"] for c in insp.get_columns("workout")}


def test_ai_report_score_columns_roundtrip(tmp_path):
    """V3-4：ai_report 增加 score/one_liner/subscores_json，升级出现、回滚消失。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("ai_report")}
    assert {"score", "one_liner", "subscores_json"} <= cols

    command.downgrade(cfg, "c2d3e4f5a6b7")  # 回退一个版本
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("ai_report")}
    assert {"score", "one_liner", "subscores_json"}.isdisjoint(cols)

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("ai_report")}
    assert {"score", "one_liner", "subscores_json"} <= cols


def test_report_chat_message_table_roundtrip(tmp_path):
    """V3-8：report_chat_message 表随升级出现、回退一个版本消失、再升级恢复。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "report_chat_message" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("report_chat_message")}
    assert {
        "id",
        "report_id",
        "role",
        "content",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cost_estimate",
        "client_request_id",
        "created_at",
    } == cols

    command.downgrade(cfg, "d3e4f5a6b7c8")  # 回退一个版本
    insp = inspect(create_engine(db_url))
    assert "report_chat_message" not in insp.get_table_names()

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    assert "report_chat_message" in insp.get_table_names()


def test_upgrade_twice_is_stable(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # 重复执行不报错
    insp = inspect(create_engine(db_url))
    assert EXPECTED_TABLES <= set(insp.get_table_names())


def test_skinfold_and_settings_profile_roundtrip(tmp_path):
    """V4-3：skinfold_record 表 + settings.gender/birth_date，升级出现、回滚消失、再升级恢复。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "skinfold_record" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("skinfold_record")}
    assert {
        "id",
        "date",
        "method",
        "sites_json",
        "density",
        "bodyfat_result",
        "note",
        "created_at",
        "updated_at",
    } == cols
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "gender" in settings_cols
    assert "birth_date" in settings_cols

    command.downgrade(cfg, "f5a6b7c8d9e0")  # 回退到 f5a6b7c8d9e0 之前
    insp = inspect(create_engine(db_url))
    assert "skinfold_record" not in insp.get_table_names()
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "gender" not in settings_cols
    assert "birth_date" not in settings_cols

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    assert "skinfold_record" in insp.get_table_names()
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "gender" in settings_cols
    assert "birth_date" in settings_cols


def test_workout_set_hr_table_roundtrip(tmp_path):
    """V4-7：workout_set_hr 表，升级出现、回滚 a6b7c8d9e0f1 消失、再升级恢复。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "workout_set_hr" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("workout_set_hr")}
    assert {
        "id",
        "workout_id",
        "movement_name",
        "set_index",
        "hr_avg",
        "hr_max",
        "hr_min",
        "hr_recovery_30s",
        "set_start",
        "set_end",
        "confidence",
        "match_method",
        "created_at",
    } == cols
    uqs = insp.get_unique_constraints("workout_set_hr")
    assert any(
        uq.get("name") == "uq_workout_set_hr_wms"
        and set(uq.get("column_names") or []) == {"workout_id", "movement_name", "set_index"}
        for uq in uqs
    )

    command.downgrade(cfg, "a6b7c8d9e0f1")  # 回退到 V4-3 之前
    insp = inspect(create_engine(db_url))
    assert "workout_set_hr" not in insp.get_table_names()

    command.upgrade(cfg, "head")  # 再次升级恢复
    insp = inspect(create_engine(db_url))
    assert "workout_set_hr" in insp.get_table_names()


def test_llm_model_selection_column_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "llm_models_json" in {c["name"] for c in insp.get_columns("settings")}

    command.downgrade(cfg, "e1f2a3b4c5d6")
    insp = inspect(create_engine(db_url))
    assert "llm_models_json" not in {c["name"] for c in insp.get_columns("settings")}

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "llm_models_json" in {c["name"] for c in insp.get_columns("settings")}


def test_coach_memory_tables_and_settings_column_roundtrip(tmp_path):
    """V5-1：4 张 coach_* 表 + settings.memory_default_provider，显式回退 b7c8d9e0f1a2。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    for name in (
        "coach_preference",
        "coach_preference_draft",
        "coach_memory",
        "coach_chat_message",
    ):
        assert name in tables
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "memory_default_provider" in settings_cols

    command.downgrade(cfg, "b7c8d9e0f1a2")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    for name in (
        "coach_preference",
        "coach_preference_draft",
        "coach_memory",
        "coach_chat_message",
    ):
        assert name not in tables
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "memory_default_provider" not in settings_cols

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    for name in (
        "coach_preference",
        "coach_preference_draft",
        "coach_memory",
        "coach_chat_message",
    ):
        assert name in tables
    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "memory_default_provider" in settings_cols


def test_garmin_plan_sync_table_roundtrip(tmp_path):
    """Garmin 同步状态表字段、两个唯一约束及迁移往返。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "garmin_plan_sync" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert {
        "id",
        "plan_ref",
        "training_date",
        "source_key",
        "source_hash",
        "content_hash",
        "synced_hash",
        "payload_json",
        "workout_id",
        "workout_schedule_id",
        "reschedule_to_date",
        "reschedule_from_date",
        "reschedule_source_key",
        "previous_workout_schedule_id",
        "status",
        "phase",
        "error_code",
        "last_error",
        "attempt_count",
        "mapping_hash",
        "created_at",
        "updated_at",
        "synced_at",
    } == cols
    uqs = insp.get_unique_constraints("garmin_plan_sync")
    assert any(
        uq.get("name") == "uq_garmin_plan_sync_source_key"
        and uq.get("column_names") == ["source_key"]
        for uq in uqs
    )
    assert any(
        uq.get("name") == "uq_garmin_plan_sync_plan_date"
        and uq.get("column_names") == ["plan_ref", "training_date"]
        for uq in uqs
    )

    command.downgrade(cfg, "f2a3b4c5d6e7")
    insp = inspect(create_engine(db_url))
    assert "garmin_plan_sync" not in insp.get_table_names()

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    assert "garmin_plan_sync" in insp.get_table_names()


def test_garmin_reschedule_audit_columns_roundtrip(tmp_path):
    """顺延原日期/来源审计字段独立回滚，不影响既有同步字段。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert {"reschedule_from_date", "reschedule_source_key"} <= cols

    command.downgrade(cfg, "b4c5d6e7f8a9")
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert {"reschedule_from_date", "reschedule_source_key"}.isdisjoint(cols)
    assert "reschedule_to_date" in cols

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert {"reschedule_from_date", "reschedule_source_key"} <= cols


def test_exercise_mapping_tables_and_mapping_hash_roundtrip(tmp_path):
    """V6-1：3 张映射表 + garmin_plan_sync.mapping_hash，显式回退 c5d6e7f8a9b0。"""
    db_url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _make_config(db_url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    for name in (
        "exercise_mapping",
        "exercise_mapping_candidate",
        "exercise_mapping_audit",
    ):
        assert name in tables

    mapping_cols = {c["name"] for c in insp.get_columns("exercise_mapping")}
    assert mapping_cols == {
        "id",
        "xunji_name",
        "garmin_category",
        "garmin_exercise_name",
        "garmin_display_name",
        "weight_strategy",
        "status",
        "not_applicable_reason",
        "confidence",
        "source",
        "verified_level",
        "verified_at",
        "mapping_version",
        "note",
        "created_at",
        "updated_at",
    }
    sync_cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert "mapping_hash" in sync_cols

    command.downgrade(cfg, "c5d6e7f8a9b0")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    for name in (
        "exercise_mapping",
        "exercise_mapping_candidate",
        "exercise_mapping_audit",
    ):
        assert name not in tables
    sync_cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert "mapping_hash" not in sync_cols

    command.upgrade(cfg, "head")
    insp = inspect(create_engine(db_url))
    tables = set(insp.get_table_names())
    for name in (
        "exercise_mapping",
        "exercise_mapping_candidate",
        "exercise_mapping_audit",
    ):
        assert name in tables
    sync_cols = {c["name"] for c in insp.get_columns("garmin_plan_sync")}
    assert "mapping_hash" in sync_cols
