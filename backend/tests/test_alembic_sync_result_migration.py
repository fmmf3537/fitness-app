"""ADR-P0-3b：sync_result_json 迁移单 head / 链 / 模型列可空性（不跑真实 DB 迁移）。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import GarminPlanSync

BACKEND_DIR = Path(__file__).resolve().parents[1]
REVISION = "b0c1d2e3f4a5"
DOWN_REVISION = "a9b0c1d2e3f4"


def _script_dir() -> ScriptDirectory:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_single_head():
    script = _script_dir()
    heads = script.get_heads()
    assert len(heads) == 1, f"迁移出现多个 head：{heads}"
    assert REVISION in {rev.revision for rev in script.walk_revisions()}


def test_down_revision():
    script = _script_dir().get_revision(REVISION)
    assert script is not None
    assert script.down_revision == DOWN_REVISION


def test_column_exists_in_model():
    cols = GarminPlanSync.__table__.columns
    assert "sync_result_json" in cols
    assert cols["sync_result_json"].nullable is True
