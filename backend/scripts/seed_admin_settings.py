#!/usr/bin/env python
"""M6 / 阶段 4：合并 settings 表到 admin 用户（admin.id=1）。

**关键发现**（2026-08-26 调研）：单用户版 (main 分支 d605491) 的 settings 表里
"encrypted" 字段实际存的是占位符字面量：
- garmin_token_store_enc = 'tok' (3 字符)
- xunji_api_key_enc = 'enc' (3 字符)
- llm_keys_json_enc = '{}' (空 JSON)

真正的 API key 全部在单用户版 .env 里。multiuser-v2 设计的"settings 表 per-user
存 key"是新的，迁移时必须**从 .env 读真 key + 用 multiuser-v2 的 Fernet 重新加密**。

本脚本：
- 从环境变量取 GARMIN_EMAIL / GARMIN_PASSWORD / XUNJI_API_KEY / XUNJI_BODY_API_KEY
  以及 KIMI_API_KEY / DEEPSEEK_API_KEY / MINIMAX_API_KEY
- 用 multiuser-v2 的 FERNET_KEY 加密写入 settings 表 (user_id=1)
- 清掉可能的旧 settings 行

用法：
    docker compose exec -T \\
        -e GARMIN_EMAIL -e GARMIN_PASSWORD \\
        -e XUNJI_API_KEY -e XUNJI_BODY_API_KEY \\
        -e KIMI_API_KEY -e DEEPSEEK_API_KEY -e MINIMAX_API_KEY \\
        backend python /app/scripts/seed_admin_settings.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, "/app")

from cryptography.fernet import Fernet
from sqlalchemy import text

from app.db import engine

ADMIN_ID = 1
DEFAULT_LLM = "kimi"  # 单用户版 .env 之外的偏好（从 id=2 sqlite 数据看默认是 kimi）


def get_fernet() -> Fernet:
    key = os.environ["FERNET_KEY"]
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def enc(f: Fernet, value: str | None) -> str | None:
    if not value:
        return None
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def main() -> int:
    f = get_fernet()

    # 1) 收集所有需要加密的明文（来源：环境变量）
    garmin_email_enc = enc(f, os.environ.get("GARMIN_EMAIL"))
    garmin_password_enc = enc(f, os.environ.get("GARMIN_PASSWORD"))
    xunji_api_key_enc = enc(f, os.environ.get("XUNJI_API_KEY"))
    xunji_body_api_key_enc = enc(f, os.environ.get("XUNJI_BODY_API_KEY"))

    llm_keys: dict[str, str] = {}
    for k in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY"):
        v = os.environ.get(k)
        if v:
            llm_keys[k.removesuffix("_API_KEY").lower()] = v
    llm_keys_json = json.dumps(llm_keys, ensure_ascii=False)
    llm_keys_json_enc = enc(f, llm_keys_json) if llm_keys else enc(f, "{}")

    # 2) 摘要输出（不打印密文，只确认非空）
    summary: dict[str, Any] = {
        "garmin_email_enc": "(set)" if garmin_email_enc else "(NULL)",
        "garmin_password_enc": "(set)" if garmin_password_enc else "(NULL)",
        "xunji_api_key_enc": "(set)" if xunji_api_key_enc else "(NULL)",
        "xunji_body_api_key_enc": "(set)" if xunji_body_api_key_enc else "(NULL)",
        "llm_keys_json_enc": f"({len(llm_keys)} keys)" if llm_keys else "(empty)",
        "default_llm": DEFAULT_LLM,
    }
    print("=== 即将写入 admin settings ===")
    for k, v in summary.items():
        print(f"  {k:>30} = {v}")

    # 3) 写 postgres settings
    with engine.begin() as pconn:
        pconn.execute(text("DELETE FROM settings"))
        pconn.execute(
            text(
                "INSERT INTO settings ("
                "garmin_email_enc, garmin_password_enc, garmin_token_store_enc, "
                "xunji_api_key_enc, xunji_body_api_key_enc, "
                "default_llm, llm_keys_json_enc, leaderboard_opt_out_json, "
                "user_id"
                ") VALUES ("
                ":ge, :gp, NULL, :xa, :xb, :dl, :lk, NULL, :uid"
                ")"
            ),
            {
                "ge": garmin_email_enc,
                "gp": garmin_password_enc,
                "xa": xunji_api_key_enc,
                "xb": xunji_body_api_key_enc,
                "dl": DEFAULT_LLM,
                "lk": llm_keys_json_enc,
                "uid": ADMIN_ID,
            },
        )
        npg = pconn.execute(text("SELECT COUNT(*) FROM settings")).scalar_one()
        new_id = pconn.execute(
            text("SELECT id FROM settings WHERE user_id = :uid"), {"uid": ADMIN_ID}
        ).scalar_one()
        print(f"\nsettings rows in postgres: {npg}, admin settings id = {new_id}")

    # 4) 往返验证（解密回来应该看到原文）
    print("\n=== 往返解密验证 ===")
    with engine.connect() as pconn:
        row = pconn.execute(
            text(
                "SELECT garmin_email_enc, xunji_api_key_enc, llm_keys_json_enc "
                "FROM settings WHERE user_id = :uid"
            ),
            {"uid": ADMIN_ID},
        ).fetchone()
        if row is None:
            print("ERROR: settings row not found after insert", file=sys.stderr)
            return 1
        for label, ct in zip(
            ["garmin_email_enc", "xunji_api_key_enc", "llm_keys_json_enc"], row
        ):
            if ct is None:
                print(f"  {label:>30} = NULL")
                continue
            try:
                pt = f.decrypt(ct.encode("utf-8")).decode("utf-8")
                # 不打印 llm_keys_json (可能含敏感)；garmin email / xunji key 是可识别的
                if label == "garmin_email_enc":
                    print(f"  {label:>30} = {pt} (decrypted)")
                elif label == "xunji_api_key_enc":
                    print(f"  {label:>30} = {pt[:10]}... (decrypted, len={len(pt)})")
                else:
                    print(f"  {label:>30} = <{len(pt)} bytes json> (decrypted OK)")
            except Exception as e:
                print(f"  {label:>30} = DECRYPT FAILED: {e}", file=sys.stderr)
                return 1

    print("\n=== 阶段 4 完成 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
