"""一次性手工冒烟：scripts/migrate_sqlite_to_pg.py 真实跑通验证（非 pytest 用例）。"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import create_engine, text  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

from migrate_sqlite_to_pg import migrate  # noqa: E402

# 1. 造一个带数据的 SQLite 源库（用 alembic 建真结构 + 插几行）
tmp = Path(tempfile.mkdtemp())
sqlite_url = f"sqlite:///{tmp}/src.db"
env = {"DATABASE_URL": sqlite_url, "SCHEDULER_ENABLED": "0",
       "PATH": subprocess.os.environ["PATH"], "SYSTEMROOT": r"C:\WINDOWS"}
# -x url= 穿透根目录 .env 的 override=True（同 test_alembic_postgres 的坑）
subprocess.run([sys.executable, "-m", "alembic", "-x", f"url={sqlite_url}",
                "upgrade", "head"],
               cwd=BACKEND, env=env, check=True, capture_output=True)
eng = create_engine(sqlite_url)
with eng.begin() as c:
    c.execute(text("INSERT INTO job_run (job_name, status) VALUES ('smoke', 'ok')"))
    c.execute(text("INSERT INTO xunji_train (datestr, localid, title) VALUES ('2026-08-09', 'abc', '胸')"))
    c.execute(text("INSERT INTO garmin_activity (activity_id, name) VALUES ('999', '力量')"))
    c.execute(text(
        "INSERT INTO workout (date, title, xunji_train_id, garmin_activity_id, match_status) "
        "VALUES ('2026-08-09', '胸', 1, 1, 'auto_matched')"))
eng.dispose()

with PostgresContainer("postgres:16-alpine") as pg:
    pg_url = pg.get_connection_url()
    subprocess.run([sys.executable, "-m", "alembic", "-x", f"url={pg_url}",
                    "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
    migrate(sqlite_url, pg_url)
    migrate(sqlite_url, pg_url)  # 幂等：第二次全部跳过
    dst = create_engine(pg_url)
    with dst.connect() as c:
        w = c.execute(text("SELECT title, match_status FROM workout")).all()
        j = c.execute(text("SELECT status FROM job_run")).all()
    dst.dispose()
    assert w == [("胸", "auto_matched")], w
    assert j == [("ok",)] * 1, j
    print("MIGRATE SMOKE OK:", w, j)
