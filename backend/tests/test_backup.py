"""V2-4 每日数据库备份测试（PRD §7：每日备份，保留 30 天滚动清理）。"""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models import JobRun

NOW = datetime(2026, 8, 10, 3, 17, 0)


@pytest.fixture
def db_file(tmp_path) -> Path:
    p = tmp_path / "app.db"
    p.write_bytes(b"sqlite-bytes-for-test")
    return p


def _url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_backup_creates_dated_copy(session, db_file, tmp_path):
    """备份生成 app_YYYY-MM-DD.db，内容与源库一致，并写 job_run 日志。"""
    from app.services.backup import backup_database

    backup_dir = tmp_path / "backups"
    out = backup_database(session=session, db_url=_url(db_file),
                          backup_dir=backup_dir, now=NOW)

    assert out["status"] == "success"
    target = backup_dir / "app_2026-08-10.db"
    assert target.read_bytes() == db_file.read_bytes()
    assert out["path"] == str(target)

    run = session.query(JobRun).filter(JobRun.job_name == "db_backup").one()
    assert run.status == "success"


def test_backup_rolling_cleanup(session, db_file, tmp_path):
    """滚动清理：超过 30 天的备份删除，30 天及以内保留。"""
    from app.services.backup import backup_database

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old = backup_dir / "app_2026-07-10.db"   # 31 天前 → 删除
    edge = backup_dir / "app_2026-07-11.db"  # 30 天前 → 保留
    recent = backup_dir / "app_2026-08-09.db"
    for f in (old, edge, recent):
        f.write_bytes(b"x")

    out = backup_database(session=session, db_url=_url(db_file),
                          backup_dir=backup_dir, now=NOW)

    assert not old.exists()
    assert edge.exists()
    assert recent.exists()
    assert str(old) in out["removed"]


def test_backup_same_day_idempotent(session, db_file, tmp_path):
    """同一天重复备份覆盖同一日期戳文件，不堆积。"""
    from app.services.backup import backup_database

    backup_dir = tmp_path / "backups"
    backup_database(session=session, db_url=_url(db_file), backup_dir=backup_dir, now=NOW)
    later = NOW + timedelta(hours=2)
    backup_database(session=session, db_url=_url(db_file), backup_dir=backup_dir, now=later)

    assert [f.name for f in backup_dir.iterdir()] == ["app_2026-08-10.db"]


def test_backup_skips_non_sqlite(session, tmp_path):
    """非 SQLite（部署期 PostgreSQL）跳过文件复制，状态 skipped。"""
    from app.services.backup import backup_database

    backup_dir = tmp_path / "backups"
    out = backup_database(session=session, db_url="postgresql+psycopg2://u:p@h/db",
                          backup_dir=backup_dir, now=NOW)
    assert out["status"] == "skipped"
    assert not backup_dir.exists() or list(backup_dir.iterdir()) == []


def test_backup_missing_source_fails_gracefully(session, tmp_path):
    """源库文件不存在：status=failed 并写日志，不抛异常。"""
    from app.services.backup import backup_database

    out = backup_database(session=session, db_url=_url(tmp_path / "nope.db"),
                          backup_dir=tmp_path / "backups", now=NOW)
    assert out["status"] == "failed"
    run = session.query(JobRun).filter(JobRun.job_name == "db_backup").one()
    assert run.status == "failed"
