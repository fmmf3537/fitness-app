"""训记标准动作中文名表（GitHub Foveluy/Xunji-movements，2026-08-07 快照，1091 个去重名称）。

PRD §5.4：写回/建议中的动作名只允许使用该表中的标准中文名。
数据文件：app/data/xunji_movements.json（源表含一条重复"壶铃硬拉"，已去重）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

MOVEMENTS_PATH = Path(__file__).resolve().parent / "data" / "xunji_movements.json"


@lru_cache(maxsize=1)
def load_movement_names() -> tuple[str, ...]:
    """加载标准动作中文名表（进程内缓存）。"""
    with open(MOVEMENTS_PATH, encoding="utf-8") as f:
        names = json.load(f)
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"动作名表格式非法: {MOVEMENTS_PATH}")
    return tuple(names)


@lru_cache(maxsize=1)
def _name_set() -> frozenset:
    return frozenset(load_movement_names())


def is_standard_movement(name: str) -> bool:
    """判断是否为训记标准动作中文名。"""
    if not name or not isinstance(name, str):
        return False
    return name.strip() in _name_set()
