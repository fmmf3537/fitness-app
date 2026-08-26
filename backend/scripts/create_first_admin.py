"""创建第一个 admin 账号（multiuser-v2 部署初始化）。

为什么需要这个脚本
====================
multiuser-v2 注册端点（M5-4 frontend /api/auth/register）尚未实现，
且设计上**禁止开放注册**——避免公网/内网被扫到后被批量注册。
所以「部署后第一个 admin」必须由运维手动通过容器内脚本创建。

使用方法
========
**必须在 backend 容器内执行**（脚本依赖 app.services.users + app.db）：

方法 A（推荐，脚本内置）::

    docker exec fitness-hub-backend-1 python /app/scripts/create_first_admin.py

方法 B（自定义用户名/密码）::

    docker exec fitness-hub-backend-1 python /app/scripts/create_first_admin.py <username> <password>

方法 C（主机上一行，复制后跑）::

    docker cp backend/scripts/create_first_admin.py fitness-hub-backend-1:/tmp/cfa.py
    docker exec fitness-hub-backend-1 python /tmp/cfa.py admin 'MyP@ssw0rd!'

行为
====
- 用户名已存在：打印 USER_EXISTS 并退出（不覆盖，不报错）
- 用户名不存在：调用 app.services.users.create_user(role='admin', is_active=True)
  内部自动 bcrypt 哈希密码 + 写一条 audit_log(action='create_user')
- 默认用户名：admin
- 默认密码：Admin@2026（仅本地 dev 首次使用，**生产请立刻在数据库改**）
- 数据库：读 DATABASE_URL 环境变量（docker compose 已注入）

迁移到新机器
============
新机器上 multiuser-v2 启动后，第一件事就是跑这个脚本建 admin，
然后用 admin 登录走 /api/admin/users 邀请/创建其他用户。
"""
from __future__ import annotations

import sys

# 脚本不在 app 包内，注入 /app 让 import app.* 生效
sys.path.insert(0, "/app")

from app.services.users import create_user
from app.db import SessionLocal
from app.models import User

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "admin"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else "Admin@2026"


def main() -> int:
    session = SessionLocal()
    try:
        existing = session.query(User).filter_by(username=USERNAME).first()
        if existing is not None:
            print(
                f"USER_EXISTS id={existing.id} "
                f"role={existing.role} "
                f"is_active={existing.is_active}"
            )
            return 0

        user = create_user(
            session,
            username=USERNAME,
            password=PASSWORD,
            role="admin",
            is_active=True,
        )
        print(
            f"CREATED id={user.id} "
            f"username={user.username} "
            f"role={user.role} "
            f"is_active={user.is_active}"
        )
        print(
            f"PASSWORD={PASSWORD} "
            f"(首次登录后建议在数据库 UPDATE 改密，frontend 修改密码 UI 尚未实现)"
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
