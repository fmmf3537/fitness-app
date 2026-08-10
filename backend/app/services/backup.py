"""V2-4 每日数据库备份（PRD §7：每日备份，保留 30 天）。

- 开发期 SQLite：文件复制 + 日期戳（app_YYYY-MM-DD.db），同日重跑覆盖不堆积；
- 滚动清理：删除 30 天前的备份（按文件名日期解析）；
- 部署期 PostgreSQL：文件复制不适用，status=skipped（后续可换 pg_dump 实现）；
- 每次运行写一行 job_run('db_backup')，失败不向外抛。
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.db import SessionLocal
from app.models import JobRun

RETENTION_DAYS = 30
DEFAULT_BACKUP_DIR = BACKEND_DIR / "data" / "backups"
_FILENAME_RE = re.compile(r"^app_(\d{4}-\d{2}-\d{2})\.db$")


def _sqlite_path(db_url: str) -> str | None:
    """从 SQLAlchemy URL 提取 SQLite 文件路径；非 SQLite/内存库返回 None。"""
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    path = db_url[len(prefix):]
    return None if path == ":memory:" else path


def _cleanup_old_backups(backup_dir: Path, today: date) -> list[str]:
    """删除超过 RETENTION_DAYS 的备份文件，返回被删文件路径列表。"""
    removed = []
    for f in backup_dir.iterdir():
        m = _FILENAME_RE.match(f.name)
        if not m:
            continue
        try:
            fdate = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if (today - fdate).days > RETENTION_DAYS:
            f.unlink()
            removed.append(str(f))
    return removed


def backup_database(
    *,
    session: Session | None = None,
    db_url: str | None = None,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
) -> dict:
    """执行一次备份：复制当前库 → 日期戳文件，滚动清理 30 天前的备份。"""
    now = now or datetime.now()
    own_session = session is None
    session = session or SessionLocal()
    db_url = db_url or get_settings().database_url
    backup_dir = Path(backup_dir) if backup_dir else DEFAULT_BACKUP_DIR
    started_at = datetime.now()

    result: dict = {"status": "failed", "error": None, "detail": {}}
    try:
        src = _sqlite_path(db_url)
        if src is None:
            result["status"] = "skipped"
            result["detail"] = {"reason": "非 SQLite 数据库，跳过文件复制备份", "db_url_scheme": db_url.split(":", 1)[0]}
        elif not Path(src).is_file():
            result["error"] = f"数据库文件不存在：{src}"
            result["detail"] = {"source": src}
        else:
            backup_dir.mkdir(parents=True, exist_ok=True)
            target = backup_dir / f"app_{now.date().isoformat()}.db"
            shutil.copyfile(src, target)
            removed = _cleanup_old_backups(backup_dir, now.date())
            result["status"] = "success"
            result["detail"] = {"path": str(target), "removed": removed}

        if result["status"] == "success":
            result["path"] = result["detail"]["path"]
            result["removed"] = result["detail"]["removed"]
    except Exception as exc:  # 备份失败不向外抛，落日志即可
        result["status"] = "failed"
        result["error"] = str(exc)

    session.add(JobRun(
        job_name="db_backup",
        started_at=started_at,
        finished_at=datetime.now(),
        status=result["status"],
        error=result["error"],
        detail_json=json.dumps(result["detail"], ensure_ascii=False, default=str),
    ))
    session.commit()
    if own_session:
        session.close()
    return result
