"""V2-5 Alembic 在 PostgreSQL 上的迁移测试。

- 离线模式：`alembic upgrade head --sql` 以 PostgreSQL 方言渲染全部 DDL，
  不需要真实数据库，任何环境可跑；
- 在线模式：优先读 TEST_DATABASE_URL_PG（CI 服务容器注入），否则用
  testcontainers 起一个 postgres:16-alpine；两者都不可用则跳过。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 表清单从 ORM 元数据动态派生，任何新表自动纳入迁移回归，杜绝清单陈旧
# （2026-11-11 审计发现：此前硬编码 13 张，漏掉 coach_* / skinfold_record /
#  workout_set_hr / training_insights 系列共 10 张表在 PG 上从未被验证存在）
from app.models import Base  # noqa: E402

ALL_TABLES = sorted(Base.metadata.tables)

# 动态派生会包含 Alembic 自身不建的表时，显式排除（当前无）
ALL_TABLES = [t for t in ALL_TABLES if not t.startswith("alembic_")]

EXPECTED_ALEMBIC_HEAD = "c5d6e7f8a9b0"

GARMIN_PLAN_SYNC_COLUMNS = {
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
    "created_at",
    "updated_at",
    "synced_at",
}

PG_URL_PLACEHOLDER = "postgresql+psycopg2://fitness:fitness@localhost:5432/fitness"


def _alembic(args: list[str], database_url: str) -> subprocess.CompletedProcess:
    # 必须用 -x url= 显式指定目标库：根目录 .env 的 DATABASE_URL 会经
    # config.py load_dotenv(override=True) 盖掉 OS 环境变量
    env = os.environ.copy()
    env["SCHEDULER_ENABLED"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={database_url}", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


class TestAlembicOfflinePostgres:
    """离线渲染：验证迁移脚本与 PostgreSQL 方言兼容（无需真实 PG）。"""

    def test_upgrade_head_sql_renders_all_tables_for_postgres(self):
        proc = _alembic(["upgrade", "head", "--sql"], PG_URL_PLACEHOLDER)
        assert proc.returncode == 0, proc.stderr
        sql = proc.stdout
        for table in ALL_TABLES:
            assert f"CREATE TABLE {table}" in sql, f"PG 离线 DDL 缺少 {table}"
        assert "workout" in sql and "tags" in sql, "tags 列迁移未渲染"

    def test_downgrade_base_sql_renders_for_postgres(self):
        proc = _alembic(["downgrade", "head:base", "--sql"], PG_URL_PLACEHOLDER)
        assert proc.returncode == 0, proc.stderr
        assert "DROP TABLE" in proc.stdout


@pytest.fixture(scope="module")
def pg_url():
    """在线 PG：CI 注入 TEST_DATABASE_URL_PG 优先；否则 testcontainers 起容器。"""
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if url:
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers 未安装且无 TEST_DATABASE_URL_PG")
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:  # Docker 不可用（无 daemon 等）时跳过
        pytest.skip(f"Docker 不可用，跳过在线 PG 迁移测试: {exc}")
    with container:
        yield container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+psycopg2://"
        )


@pytest.mark.usefixtures("pg_url")
class TestAlembicOnlinePostgres:
    """真实 PostgreSQL 上的迁移重放验证（V2-5 验收核心）。"""

    def test_upgrade_head_creates_all_tables(self, pg_url):
        proc = _alembic(["upgrade", "head"], pg_url)
        assert proc.returncode == 0, proc.stderr

        from sqlalchemy import inspect, text

        from app.db import make_engine

        engine = make_engine(pg_url)
        try:
            inspector = inspect(engine)
            existing = set(inspector.get_table_names())
            for table in ALL_TABLES:
                assert table in existing, f"PG 中缺少表 {table}"
            assert "alembic_version" in existing

            garmin_cols = {c["name"] for c in inspector.get_columns("garmin_plan_sync")}
            assert garmin_cols == GARMIN_PLAN_SYNC_COLUMNS, (
                f"garmin_plan_sync 字段不完整: missing="
                f"{GARMIN_PLAN_SYNC_COLUMNS - garmin_cols} extra="
                f"{garmin_cols - GARMIN_PLAN_SYNC_COLUMNS}"
            )
            assert len(garmin_cols) == 22

            uniques = {
                u["name"]: set(u["column_names"])
                for u in inspector.get_unique_constraints("garmin_plan_sync")
            }
            assert uniques.get("uq_garmin_plan_sync_source_key") == {"source_key"}
            assert uniques.get("uq_garmin_plan_sync_plan_date") == {
                "plan_ref",
                "training_date",
            }

            # 写入/读取冒烟：确认 PG 方言下 CRUD 正常
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO job_run (job_name, status) VALUES (:n, :s)"),
                    {"n": "pg_migration_smoke", "s": "ok"},
                )
                row = conn.execute(
                    text("SELECT status FROM job_run WHERE job_name = :n"),
                    {"n": "pg_migration_smoke"},
                ).one()
            assert row[0] == "ok"
        finally:
            engine.dispose()

    def test_alembic_current_equals_head(self, pg_url):
        proc = _alembic(["upgrade", "head"], pg_url)
        assert proc.returncode == 0, proc.stderr
        current = _alembic(["current"], pg_url)
        assert current.returncode == 0, current.stderr
        head = _alembic(["heads"], pg_url)
        assert head.returncode == 0, head.stderr
        current_rev = current.stdout.strip().split()[0]
        head_rev = head.stdout.strip().split()[0]
        assert head_rev == EXPECTED_ALEMBIC_HEAD
        assert current_rev.startswith(EXPECTED_ALEMBIC_HEAD)
        assert current_rev.startswith(head_rev)
