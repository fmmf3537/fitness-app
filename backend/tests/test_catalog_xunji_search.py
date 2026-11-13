"""ADR-P2-8：按训记动作名子串匹配 → 复用 generate_candidates。"""
from __future__ import annotations

from app.services.exercise_mapping import search_by_xunji_name

_RESULT_KEYS = frozenset(
    {
        "xunji_name",
        "match_rank",
        "category",
        "exercise",
        "name",
        "confidence",
        "rank",
        "reason",
    }
)


def test_substring_match_returns_candidates():
    items = search_by_xunji_name("上斜哑铃")
    assert items
    assert any(row["xunji_name"].startswith("上斜哑铃") for row in items)


def test_result_shape():
    items = search_by_xunji_name("上斜哑铃")
    assert items
    for row in items:
        assert _RESULT_KEYS <= set(row.keys())


def test_short_name_first():
    # 真实数据：「侧平举」短于「半俯身侧平举」「器械侧平举」等
    items = search_by_xunji_name("侧平举", limit=20, candidates_per_movement=1)
    assert items
    names_in_order: list[str] = []
    ranks: list[int] = []
    for row in items:
        if row["xunji_name"] not in names_in_order:
            names_in_order.append(row["xunji_name"])
            ranks.append(row["match_rank"])
    assert ranks == sorted(ranks)
    assert all(
        ranks[i] < ranks[i + 1] for i in range(len(ranks) - 1)
    )
    lengths = [len(n) for n in names_in_order]
    assert lengths == sorted(lengths)
    assert names_in_order[0] == "侧平举"


def test_skips_movements_without_candidates():
    items = search_by_xunji_name("哑铃卧推")
    assert all(row.get("exercise") not in (None, "") for row in items)


def test_respects_candidates_per_movement():
    items = search_by_xunji_name(
        "上斜哑铃", limit=50, candidates_per_movement=1
    )
    seen: set[str] = set()
    for row in items:
        name = row["xunji_name"]
        assert name not in seen
        seen.add(name)


def test_respects_limit():
    items = search_by_xunji_name("哑铃卧推", limit=1)
    assert len(items) == 1


def test_blank_query_returns_empty():
    assert search_by_xunji_name("   ") == []


def test_no_match_returns_empty():
    assert search_by_xunji_name("完全不存在的动作xyz") == []
