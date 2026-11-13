"""ADR-P2-2：exercise_mapping_review 迁移单 head / 链 / 模型列（不跑真实 DB 迁移）。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import Base, ExerciseMappingReview

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISION = "d2e3f4a5b6c7"
DOWN_REVISION = "c1d2e3f4a5b6"


def _script_dir() -> ScriptDirectory:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_single_head():
    """只断言「单 head」这一不变式，不写死具体版本号。

    写死 head 会让每次新增迁移都打破本测试（ADR-P0-3b 加迁移时踩过），
    这里改为断言本 revision 仍在链上且 head 唯一。
    """
    script = _script_dir()
    heads = script.get_heads()
    assert len(heads) == 1, f"迁移出现多个 head：{heads}"
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert REVISION in revisions, f"{REVISION} 不在迁移链上"


def test_down_revision():
    script = _script_dir().get_revision(REVISION)
    assert script is not None
    assert script.down_revision == DOWN_REVISION


def test_model_table_matches():
    """模型表名与必要列存在。"""
    assert ExerciseMappingReview.__tablename__ == "exercise_mapping_review"
    table = Base.metadata.tables[ExerciseMappingReview.__tablename__]
    for col_name in (
        "id",
        "mapping_id",
        "xunji_name",
        "verdict",
        "suggested_category",
        "suggested_exercise_name",
        "suggested_display_name",
        "reason",
        "model",
        "batch_id",
        "resolved",
        "created_at",
    ):
        assert col_name in table.c
