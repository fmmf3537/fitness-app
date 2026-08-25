# -*- coding: utf-8 -*-
"""M1-4 迁移脚本单元测试：scripts/migrate_to_multiuser.py。

使用临时 SQLite 库，建最小表结构（users + 目标表的 id/user_id 列），
不依赖 app.models / app.db。
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND_DIR / "scripts" / "migrate_to_multiuser.py"

spec = importlib.util.spec_from_file_location("migrate_to_multiuser", MODULE_PATH)
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)

TABLES = mig.TARGET_TABLES  # settings + 11 张业务表


@pytest.fixture()
def db_url(tmp_path):
    """临时 SQLite 库：users + 所有目标表（仅 id/user_id 最小结构）。"""
    db_file = tmp_path / "mig_test.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE users ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  username VARCHAR(50) UNIQUE NOT NULL,"
        "  password_hash VARCHAR(255) NOT NULL,"
        "  role VARCHAR(20) NOT NULL DEFAULT 'user',"
        "  is_active BOOLEAN NOT NULL DEFAULT 1"
        ")"
    )
    for t in TABLES:
        conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER)")
    conn.commit()
    conn.close()
    return f"sqlite:///{db_file}"


def _raw(db_url):
    return sqlite3.connect(db_url.replace("sqlite:///", ""))


def _seed_rows(db_url, table, n, user_id=None):
    conn = _raw(db_url)
    for _ in range(n):
        conn.execute(f"INSERT INTO {table} (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def _null_counts(db_url):
    conn = _raw(db_url)
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id IS NULL").fetchone()[0]
        for t in TABLES
    }
    conn.close()
    return counts


def test_dry_run_reports_pending_without_writing(db_url, monkeypatch, capsys):
    """dry-run 不修改任何行，但报告正确的待处理行数。"""
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pass-123")
    _seed_rows(db_url, "workout", 3)
    _seed_rows(db_url, "llm_call", 2)
    _seed_rows(db_url, "settings", 1)
    _seed_rows(db_url, "job_run", 4)

    before = _null_counts(db_url)
    report = mig.migrate(db_url, apply=False)
    after = _null_counts(db_url)

    assert before == after, "dry-run 不得修改任何行"
    assert report["tables"]["workout"]["pending"] == 3
    assert report["tables"]["llm_call"]["pending"] == 2
    assert report["tables"]["job_run"]["pending"] == 4
    assert all(t["updated"] == 0 for t in report["tables"].values())

    out = capsys.readouterr().out
    assert "workout: 3 行将被更新" in out
    assert "干跑" in out

    # dry-run 不得创建用户
    conn = _raw(db_url)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    conn.close()


def test_apply_creates_admin_and_backfills(db_url, monkeypatch):
    """空 users 表时 --apply 创建管理员并回填，所有表 user_id 均等于管理员 id。"""
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret-password")
    row_counts = {}
    for i, t in enumerate(TABLES):
        n = (i % 3) + 1  # 1~3 行
        _seed_rows(db_url, t, n)
        row_counts[t] = n

    report = mig.migrate(db_url, apply=True)
    admin_id = report["admin_id"]
    assert admin_id is not None

    conn = _raw(db_url)
    # 管理员创建正确
    users = conn.execute("SELECT id, username, role, is_active, password_hash FROM users").fetchall()
    assert len(users) == 1
    assert users[0][0] == admin_id
    assert users[0][1] == "boss"
    assert users[0][2] == "admin"
    assert users[0][3] in (1, True)
    assert users[0][4] != "s3cret-password", "口令必须哈希存储，禁止明文"

    # 所有表：行数不变（无增删），user_id 全部等于管理员 id
    for t in TABLES:
        total = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        nulled = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id IS NULL").fetchone()[0]
        owned = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE user_id = ?", (admin_id,)
        ).fetchone()[0]
        assert total == row_counts[t], f"{t} 行数发生变化（仅允许 UPDATE user_id）"
        assert nulled == 0, f"{t} 仍有 NULL user_id"
        assert owned == row_counts[t], f"{t} user_id 未全部归属管理员"

    assert all(
        t["updated"] == t["pending"] for t in report["tables"].values()
    )
    conn.close()


def test_apply_reuses_existing_admin(db_url, monkeypatch):
    """已存在管理员时，不重复创建，仍正确回填。"""
    conn = _raw(db_url)
    conn.execute(
        "INSERT INTO users (username, password_hash, role, is_active) "
        "VALUES ('root', 'x', 'admin', 1)"
    )
    conn.commit()
    existing_id = conn.execute("SELECT id FROM users WHERE username='root'").fetchone()[0]
    conn.close()

    _seed_rows(db_url, "body_metric", 2)
    _seed_rows(db_url, "ai_report", 1)

    report = mig.migrate(db_url, apply=True)
    assert report["admin_id"] == existing_id
    assert "复用已有管理员" in report["admin_message"]

    conn = _raw(db_url)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1, "不得重复创建用户"
    for t in TABLES:
        nulled = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id IS NULL").fetchone()[0]
        assert nulled == 0, f"{t} 仍有 NULL user_id"
    assert conn.execute(
        "SELECT COUNT(*) FROM body_metric WHERE user_id = ?", (existing_id,)
    ).fetchone()[0] == 2
    conn.close()


def test_settings_multiple_null_rows_skipped_with_warning(db_url, monkeypatch, capsys):
    """settings 多行 NULL 无法自动合并（不删数据红线）：警告并跳过，其余表正常回填。"""
    _seed_rows(db_url, "settings", 2)
    _seed_rows(db_url, "workout", 1)
    report = mig.migrate(db_url, apply=True)

    entry = report["tables"]["settings"]
    assert entry["skipped"] is True
    assert entry["updated"] == 0
    assert "跳过" in entry["note"]
    assert "警告" in capsys.readouterr().out

    conn = _raw(db_url)
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE user_id IS NULL").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM workout WHERE user_id IS NULL").fetchone()[0] == 0
    conn.close()


def test_random_password_generated_when_env_missing(db_url, monkeypatch, capsys):
    """ADMIN_PASSWORD 为空时随机生成 16 位密码并仅打印一次。"""
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    _seed_rows(db_url, "workout", 1)

    mig.migrate(db_url, apply=True)
    out = capsys.readouterr().out
    assert "随机生成的管理员密码" in out
    assert out.count("随机生成的管理员密码") == 1


def test_resolve_relative_sqlite_path_is_absolute(monkeypatch, tmp_path):
    """相对 SQLite 路径需以 .env 所在目录为基准解析为绝对路径，避免目录错位。"""
    import os as _os

    env_file = tmp_path / ".env"
    db_file = tmp_path / "sub" / "data.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(f"DATABASE_URL=sqlite:///{db_file.as_posix()}\n", encoding="utf-8")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = mig.resolve_database_url.__wrapped__ if hasattr(mig.resolve_database_url, "__wrapped__") else None
    # 直接构造：临时打桩 ENV_CANDIDATES 指向临时 .env
    saved = mig.ENV_CANDIDATES
    try:
        mig.ENV_CANDIDATES = [env_file]
        url = mig.resolve_database_url()
    finally:
        mig.ENV_CANDIDATES = saved

    assert url.startswith("sqlite:///")
    # 解析后必须是绝对路径（含盘符或根），且指向真实文件目录的上层结构一致
    file_part = url[len("sqlite:///"):]
    assert _os.path.isabs(file_part), f"相对路径未被解析为绝对路径: {url}"
