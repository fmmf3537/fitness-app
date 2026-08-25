#!/usr/bin/env python
"""M1-4 存量数据迁移脚本 —— thin wrapper。

脚本主体在 `backend/scripts/migrate_to_multiuser.py`，本文件只是入口转发，
保持跟《开发计划_多用户版_V1.0.md》§阶段 M-M1 / 任务 M1-4 要求的 `scripts/migrate_to_multiuser.py` 路径一致。

用法：
    python scripts/migrate_to_multiuser.py --dry-run    # 仅预览
    python scripts/migrate_to_multiuser.py --apply      # 真实执行（需备份+YES 确认）
    python scripts/migrate_to_multiuser.py --apply --yes # 非交互执行
"""
import importlib.util
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
MAIN_SCRIPT = BACKEND_DIR / "scripts" / "migrate_to_multiuser.py"

if not MAIN_SCRIPT.exists():
    sys.exit(f"[error] 主体脚本不存在：{MAIN_SCRIPT}")

# 把 backend 加到 sys.path，让主体里 `from app...` 之类的 import 能找到
sys.path.insert(0, str(BACKEND_DIR))

spec = importlib.util.spec_from_file_location("migrate_to_multiuser_main", MAIN_SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["migrate_to_multiuser_main"] = mod
spec.loader.exec_module(mod)


if __name__ == "__main__":
    sys.exit(mod.main())
