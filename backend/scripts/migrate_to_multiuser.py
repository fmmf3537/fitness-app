#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M1-4 存量数据迁移脚本：把各业务表中 user_id IS NULL 的记录归属到默认管理员。

用法（在 backend/ 目录下执行）：

    # 干跑（默认）：仅输出迁移计划，不写库
    python scripts/migrate_to_multiuser.py --dry-run

    # 真实写入：执行前必须先备份数据库！
    python scripts/migrate_to_multiuser.py --apply

    # 自动化场景跳过交互确认（仍需显式 --apply）
    python scripts/migrate_to_multiuser.py --apply --yes

行为说明：
    1. 检查 users 表：为空则创建默认管理员（用户名取环境变量 ADMIN_USERNAME，
       默认 "admin"；密码取 ADMIN_PASSWORD，为空则随机生成 16 位大小写字母+数字
       密码，并仅打印一次到控制台，请立即保存）；非空则取第一个 role='admin'
       的用户作为归属用户。
    2. 对 TARGET_TABLES 中所有 user_id IS NULL 的记录执行参数化 UPDATE。
       红线：绝不删除/清空任何表，仅 UPDATE user_id。
    3. settings 表若存在多行 user_id IS NULL，无法在不删数据的前提下自动合并
       为单行（UNIQUE(user_id) 约束），将打印警告并跳过 settings 赋值、记入报告。
    4. 每张表输出「待处理行数 → 实际更新行数」，最后打印汇总。

数据库连接：优先 os.environ["DATABASE_URL"]，否则解析 backend/.env。
脚本不 import app.models / app.db，直接使用原生 sqlalchemy Engine，避免循环导入。
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

# 需要回填 user_id 的目标表（settings 为每用户一行，需特殊处理）
TARGET_TABLES = [
    "settings",
    "xunji_train",
    "garmin_activity",
    "garmin_daily",
    "body_metric",
    "workout",
    "match_candidate",
    "xunji_plan",
    "ai_report",
    "llm_call",
    "job_run",  # user_id 业务上可 NULL，仅回填当前 NULL 的行
    "report_chat_message",
]

BACKEND_DIR = Path(__file__).resolve().parents[1]
# .env 查找顺序：backend/.env → 仓库根目录 .env
ENV_CANDIDATES = [BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"]


# --------------------------------------------------------------------------- #
# 数据库连接
# --------------------------------------------------------------------------- #

def _parse_env_file(path: Path) -> dict:
    """极简 .env 解析（key=value，忽略注释与空行），避免依赖 app.config。"""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def resolve_database_url() -> str:
    """优先环境变量 DATABASE_URL，否则读 backend/.env；都没有则报错。

    若 SQLite 路径为相对路径（sqlite:///./... 或 sqlite:///... 无 scheme 主机），
    则以「找到该 DATABASE_URL 的 .env 所在目录」为基准解析为绝对路径，
    避免从 backend/ 目录运行时相对路径错位（如 ./backend/data/app.db）。
    """
    url = os.environ.get("DATABASE_URL")
    base_dir = None
    if not url:
        for env_path in ENV_CANDIDATES:
            url = _parse_env_file(env_path).get("DATABASE_URL")
            if url:
                base_dir = env_path.parent
                break
    if not url:
        searched = "、".join(str(p) for p in ENV_CANDATES)
        raise RuntimeError(
            "未找到 DATABASE_URL：请设置环境变量 DATABASE_URL，"
            f"或在 .env（已查找：{searched}）中配置。"
        )
    if url.startswith("sqlite:///"):
        # 去掉协议前缀，得到文件部分
        file_part = url[len("sqlite:///"):]
        if not os.path.isabs(file_part) and base_dir is not None:
            abs_path = (base_dir / file_part).resolve()
            url = f"sqlite:///{abs_path.as_posix()}"
    return url


def make_engine(database_url: str) -> Engine:
    """建立原生 Engine 并立即验证连通性，连不上直接抛错，不静默吞异常。"""
    engine = create_engine(database_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


def check_tables(engine: Engine) -> None:
    """确认 users 与全部目标表存在，缺表立即报错。"""
    existing = set(inspect(engine).get_table_names())
    missing = [t for t in ["users", *TARGET_TABLES] if t not in existing]
    if missing:
        raise RuntimeError(
            f"数据库缺少必需表：{', '.join(missing)}。"
            "请确认 DATABASE_URL 指向正确的库，且 M1-1~M1-3 迁移已执行。"
        )


# --------------------------------------------------------------------------- #
# 默认管理员
# --------------------------------------------------------------------------- #

def generate_password(length: int = 16) -> str:
    """随机生成指定长度的大小写字母+数字密码。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_password(plain: str) -> str:
    """口令哈希：优先 bcrypt（cost=12），未安装时退回 stdlib PBKDF2-SHA256。"""
    try:
        import bcrypt  # type: ignore

        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except ImportError:
        import hashlib

        salt = secrets.token_hex(16)
        iterations = 200_000
        digest = hashlib.pbkdf2_hmac(
            "sha256", plain.encode("utf-8"), salt.encode("utf-8"), iterations
        ).hex()
        return f"pbkdf2_sha256${iterations}${salt}${digest}"


def find_admin_id(conn: Connection):
    """返回第一个 role='admin' 的用户 id；无则返回 None。"""
    row = conn.execute(
        text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
    ).first()
    return row[0] if row else None


def ensure_admin(conn: Connection, apply: bool) -> tuple[int | None, str]:
    """确保存在默认管理员，返回 (admin_id, 描述信息)。

    dry-run 模式下不执行 INSERT，admin_id 返回 None。
    """
    admin_id = find_admin_id(conn)
    if admin_id is not None:
        return admin_id, f"复用已有管理员用户 id={admin_id}"

    user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
    if user_count > 0:
        raise RuntimeError(
            "users 表非空但不存在 role='admin' 的用户，无法确定归属用户，"
            "请手工指定或先创建管理员。"
        )

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD")
    password_generated = not password
    if password_generated:
        password = generate_password(16)

    if not apply:
        return None, (
            f"计划创建默认管理员 username={username!r}（users 表当前为空；"
            f"密码来源：{'随机生成' if password_generated else 'ADMIN_PASSWORD'}）"
        )

    conn.execute(
        text(
            "INSERT INTO users (username, password_hash, role, is_active) "
            "VALUES (:username, :password_hash, 'admin', :is_active)"
        ),
        {
            "username": username,
            "password_hash": hash_password(password),
            "is_active": True,
        },
    )
    admin_id = conn.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": username},
    ).scalar_one()

    msg = f"已创建默认管理员 username={username!r} id={admin_id}"
    if password_generated:
        # 随机密码仅在此打印一次，请立即保存；不落日志、不落库（明文）
        msg += (
            f"\n{'!' * 60}\n"
            f"!! 随机生成的管理员密码（仅此一次显示，请立即保存）: {password}\n"
            f"{'!' * 60}"
        )
    return admin_id, msg


# --------------------------------------------------------------------------- #
# 回填逻辑
# --------------------------------------------------------------------------- #

def count_pending(conn: Connection, table: str) -> int:
    return conn.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")  # noqa: S608 - 表名来自白名单
    ).scalar_one()


def backfill_table(conn: Connection, table: str, admin_id: int) -> int:
    """参数化 UPDATE，禁止字符串拼接 id 值。返回实际更新行数。"""
    result = conn.execute(
        text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),  # noqa: S608
        {"uid": admin_id},
    )
    return result.rowcount


def migrate(database_url: str, apply: bool = False) -> dict:
    """执行（或模拟）迁移，返回报告字典。

    report["tables"][table] = {"pending": int, "updated": int, "skipped": bool, "note": str}
    """
    started = time.monotonic()
    engine = make_engine(database_url)
    try:
        check_tables(engine)
        report = {"apply": apply, "tables": {}, "admin_message": "", "elapsed_s": 0.0}

        ctx = engine.begin() if apply else engine.connect()
        with ctx as conn:
            admin_id, admin_msg = ensure_admin(conn, apply=apply)
            report["admin_message"] = admin_msg
            report["admin_id"] = admin_id
            print(f"[管理员] {admin_msg}")

            for table in TARGET_TABLES:
                pending = count_pending(conn, table)
                entry = {"pending": pending, "updated": 0, "skipped": False, "note": ""}

                if table == "settings" and pending > 1:
                    # 红线是不删数据；多行 NULL 无法自动合并为单行
                    # （UNIQUE(user_id)），打印警告并跳过、记入报告。
                    entry["skipped"] = True
                    entry["note"] = (
                        f"settings 存在 {pending} 行 user_id IS NULL，无法在不删除数据的"
                        "前提下自动合并为单行，已跳过赋值，请人工处理。"
                    )
                    print(f"[警告] {entry['note']}")
                elif apply and pending > 0:
                    entry["updated"] = backfill_table(conn, table, admin_id)
                    print(f"[回填] {table}: 待处理 {pending} 行 → 实际更新 {entry['updated']} 行")
                else:
                    print(f"[计划] {table}: {pending} 行将被更新")

                report["tables"][table] = entry

        report["elapsed_s"] = round(time.monotonic() - started, 3)
        _print_summary(report)
        return report
    finally:
        engine.dispose()


def _print_summary(report: dict) -> None:
    mode = "真实写入 (--apply)" if report["apply"] else "干跑 (--dry-run，未修改任何数据)"
    total_pending = sum(t["pending"] for t in report["tables"].values())
    total_updated = sum(t["updated"] for t in report["tables"].values())
    print("=" * 60)
    print(f"迁移报告（{mode}）")
    print(f"  表数量: {len(report['tables'])} 张")
    print(f"  待处理总行数: {total_pending}")
    print(f"  实际更新总行数: {total_updated}")
    print(f"  耗时: {report['elapsed_s']}s")
    print("=" * 60)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

WARNING_BANNER = """
############################################################
#                      危 险 操 作 警 告                    #
#  即将对数据库执行【破坏性回填】：批量 UPDATE user_id。     #
#  执行前请确认已完成数据库备份！                            #
############################################################
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="M1-4 存量数据迁移：回填各业务表 user_id 到默认管理员。"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="仅输出迁移计划（默认）")
    group.add_argument("--apply", action="store_true", help="真实写入（执行前必须先备份数据库）")
    parser.add_argument("--yes", action="store_true", help="跳过 --apply 的交互确认（自动化用）")
    args = parser.parse_args(argv)

    apply = bool(args.apply)
    if apply:
        print(WARNING_BANNER)
        if not args.yes:
            try:
                answer = input("确认已备份数据库并继续执行？请输入 YES 继续: ").strip()
            except EOFError:
                answer = ""
            if answer != "YES":
                print("已取消：未收到 YES 确认。如需非交互执行请追加 --yes。")
                return 1
    else:
        print("[模式] --dry-run（默认）：仅输出迁移计划，不执行任何 UPDATE。")

    try:
        url = resolve_database_url()
        migrate(url, apply=apply)
    except Exception as exc:  # 明确报错，不静默吞异常
        print(f"[错误] 迁移失败: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
