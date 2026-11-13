"""ADR-P0-1：relation 迁移单 head / 链 / 模型列可空性（不跑真实 DB 迁移）。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import Base, ExerciseMapping

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISION = "a9b0c1d2e3f4"
DOWN_REVISION = "f8a9b0c1d2e3"


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


def test_down_revision_chain():
    script = _script_dir().get_revision(REVISION)
    assert script is not None
    assert script.down_revision == DOWN_REVISION


def test_upgrade_adds_three_nullable_columns():
    """用 Base.metadata 断言三列存在且 nullable=True（不跑真实 DB 迁移）。"""
    table = Base.metadata.tables[ExerciseMapping.__tablename__]
    for col_name in ("relation", "match_basis", "unmapped_reason"):
        assert col_name in table.c
        assert table.c[col_name].nullable is True
