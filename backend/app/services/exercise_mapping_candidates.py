"""训记动作 → Garmin 动作的 4 级窄化候选生成（纯函数）。

不访问 DB、网络、文件；只用 exercise_tokens 静态词表与
garminconnect.exercises 离线目录（可注入 catalog 便于单测）。
不负责落库、LLM 兜底或 API（见 V6-3 / V6-7）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from garminconnect import exercises as garmin_exercises

from app.services.exercise_tokens import (
    CARDIO_KEYWORDS,
    CARDIO_ONLY_CATEGORIES,
    EQUIPMENT_TO_GARMIN_CATEGORY,
    EQUIPMENT_TOKENS,
    FLEXIBILITY_KEYWORDS,
    MOVEMENT_NAME_EXCLUDES,
    MOVEMENT_TOKENS,
    PART_ANCHORED_MOVEMENTS,
    PART_TO_GARMIN_CATEGORIES,
    POSTURE_TOKENS,
)
from app.services.stats import classify_part


@dataclass(frozen=True)
class Candidate:
    xunji_name: str
    garmin_category: str
    garmin_exercise_name: str  # 可为空串
    garmin_display_name: str
    confidence: str  # "high" / "medium" / "low"
    rank: int  # 1 = 主推
    reason: str  # 中文，说明命中依据


def classify_applicability(xunji_name: str) -> tuple[bool, str | None]:
    """返回 (可映射为力量训练?, 不可映射原因)。

    命中顺序：先 CARDIO 后 FLEXIBILITY。
    """
    if not xunji_name or not str(xunji_name).strip():
        return True, None
    name = str(xunji_name)
    for kw in CARDIO_KEYWORDS:
        if kw in name:
            return False, "有氧动作，非力量训练"
    for kw in FLEXIBILITY_KEYWORDS:
        if kw in name:
            return False, "拉伸/放松动作，非力量训练"
    return True, None


def _match_tokens(name: str, tokens: dict[str, str]) -> list[str]:
    """长键优先抽取英文词根；同一位置命中长词后不再计入短词。"""
    remaining = name
    hit: list[str] = []
    for zh, en in sorted(tokens.items(), key=lambda kv: len(kv[0]), reverse=True):
        if zh and zh in remaining:
            hit.append(en)
            remaining = remaining.replace(zh, "\0" * len(zh), 1)
    return hit


def extract_tokens(xunji_name: str) -> dict[str, object]:
    """抽取 {equipment, postures, movements, part}。

    - 长键优先（同一位置命中更长的词后不再重复计入短词）
    - 允许同时含多个 posture
    - movements 取命中列表，可能多个
    """
    name = xunji_name or ""
    return {
        "equipment": _match_tokens(name, EQUIPMENT_TOKENS),
        "postures": _match_tokens(name, POSTURE_TOKENS),
        "movements": _match_tokens(name, MOVEMENT_TOKENS),
        "part": classify_part(name),
    }


def _norm(text: str) -> str:
    """归一化为「仅小写字母数字」的紧凑串，消除空格/连字符/下划线差异。

    Garmin 目录里有 "Lat Pull-down"、"Push-up"、"Sit-up" 这类带连字符的写法，
    而词表里是 pulldown / push up / sit up 这类无连字符写法。若只把 '-' 换成空格，
    "pulldown" 无法在 "lat pull down" 里命中——这是 V6-2 首版实测 empty 达 29% 的主因。
    统一去掉所有非字母数字后，"Lat Pull-down" → "latpulldown"，可命中 "pulldown"。
    """
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# 命中器械专属分类时的额外加分：确保它排在「仅部位命中」的候选之前
EQUIPMENT_CATEGORY_BONUS = 20


def _score_to_confidence(score: int) -> str:
    """分数 → 置信度。

    分数构成：基础 20 + 器械命中 40 + 姿态命中 +20/缺失 −20（各上限 40）+ 完全相等 20。
    因此关键分界是 60 = 「动作词根命中（硬条件）+ 器械命中」——器械与动作都对上
    已是很强的信号，判 high；40 = 只有动作词根命中（器械可能不匹配）判 medium；
    20 = 兜底路径（无动作词）判 low（V6-2 实测：60 分有 109 条被判成 medium，
    与 80 分的 120 条在可信度上并无实质差异，故下调阈值）。
    """
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _other_equipment_roots() -> list[str]:
    return [v for v in EQUIPMENT_TOKENS.values() if v]


def _equipment_bonus(equip_list: list[str], name_norm: str) -> tuple[int, str]:
    """返回 (加分, 用于 reason 的器械展示串)。"""
    non_empty = [e for e in equip_list if e]
    for eq in non_empty:
        if _norm(eq) in name_norm:
            return 40, eq
    if any(e == "" for e in equip_list):
        if not any(_norm(root) in name_norm for root in _other_equipment_roots()):
            return 20, "无"
    if non_empty:
        return 0, non_empty[0]
    return 0, "无"


def _movement_alternatives(mv: str) -> tuple[str, ...]:
    """同一语义的不同英文写法。Garmin 里单臂动作常写作 One-arm / Single-arm。"""
    base = _norm(mv)
    if not base:
        return ()
    alts = {base}
    if "singlearm" in base:
        alts.add(base.replace("singlearm", "onearm"))
    if "onearm" in base:
        alts.add(base.replace("onearm", "singlearm"))
    return tuple(alts)


def _posture_bonus(postures: list[str], name_norm: str) -> int:
    """姿态打分：匹配 +20/个、缺失 −20/个（各上限 40）；**全部命中再 +40**。

    姿态词（上斜/下斜/坐姿/俯身/单臂…）是区分 Garmin 变体的关键。
    - 只加分不扣分时，"Dumbbell Bench Press" 靠 _exact_bonus 的 +20 与
      "Incline Dumbbell Bench Press" 的 +20 打平，字典序选中了不带 incline 的。
    - 只扣分还不够：目录里没有 DECLINE_BARBELL 时，
      "Barbell Bench Press"（20+器械40−姿态20+完全相等20=60）仍会压过
      "Decline Dumbbell Bench Press"（20+0+20=40），下斜照样丢。
    - 因此对「姿态全部命中」额外 +40 作强偏好：它能让真正对应的变体胜出，
      同时**不做硬过滤**——目录里确实没有对应变体时，仍会降级到近似项
      （置信度随之降低），而不是让动作变成「无候选」。
    """
    if not postures:
        return 0
    hits = sum(1 for p in postures if p and _norm(p) in name_norm)
    misses = sum(1 for p in postures if p and _norm(p) not in name_norm)
    score = min(40, hits * 20) - min(40, misses * 20)
    if hits and not misses:
        score += 40
    return score


def _is_inconsistent(xunji_name: str, part: str, name_norm: str) -> bool:
    """候选与动作语义明显不符时返回 True（该候选直接跳过，不给分）。"""
    # 1) 中文名排除：如"弯举"未限定"腿"时不得命中 hamstring
    for must_have, must_not_have, banned in MOVEMENT_NAME_EXCLUDES:
        if must_have in xunji_name and must_not_have not in xunji_name:
            if any(term in name_norm for term in banned):
                return True
    # 2) 部位锚词：外展/内收 必须落在对应部位的英文词上
    for keyword, anchors_by_part in PART_ANCHORED_MOVEMENTS.items():
        if keyword not in xunji_name:
            continue
        anchors = anchors_by_part.get(part)
        if not anchors:
            continue
        if not any(_norm(a) in name_norm for a in anchors):
            return True
    # 3) 单手/单臂/单边：候选须含 singlearm 或 onearm
    # （否则「单手绳索臂屈伸」会因器械 +40 压过姿态 −20，仍落到非单臂项；
    #  单手动作的重量是单侧口径，落到双臂项会把语义搞错，故用硬过滤）
    if any(k in xunji_name for k in ("单手", "单臂", "单边")):
        if "singlearm" not in name_norm and "onearm" not in name_norm:
            return True
    # 注意：**不要**对「上斜/下斜」加同类硬过滤。
    # 姿态的 ±20 打分已经能让带 incline/decline 的变体胜出；若目录里根本没有
    # 对应变体（如 DECLINE_BARBELL 不存在），硬过滤会让动作直接变成「无候选」，
    # 而降到 flat 变体 + medium 置信度是有用得多的降级（实测误杀 28 条）。
    return False


def _exact_bonus(equip: str, mv: str, name_norm: str) -> int:
    target = _norm(f"{equip} {mv}".strip() if equip else mv)
    return 20 if target and target == name_norm else 0


def _dedupe_catalog(catalog: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for entry in catalog:
        key = (entry.get("category", ""), entry.get("exercise", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _fallback_candidates(
    xunji_name: str,
    part: str,
    categories: list[str],
    catalog: list[dict[str, str]],
    limit: int,
) -> list[Candidate]:
    """无 movement 或硬过滤全落空时：取 exercise 为空串的 category 级条目。"""
    if categories:
        cat_set = set(categories)
        pool = [e for e in catalog if e.get("category") in cat_set]
        order = {c: i for i, c in enumerate(categories)}
    else:
        pool = list(catalog)
        order = {}

    pool = [
        e
        for e in pool
        if e.get("category") not in CARDIO_ONLY_CATEGORIES
        and e.get("exercise") != "INDOOR_ROW"
    ]

    empties = [e for e in pool if e.get("exercise", "") == ""]
    empties.sort(
        key=lambda e: (
            order.get(e.get("category", ""), 10_000),
            e.get("category", ""),
            e.get("name", ""),
        )
    )

    scored: list[tuple[int, dict[str, str], str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in empties:
        key = (entry.get("category", ""), entry.get("exercise", ""))
        if key in seen:
            continue
        seen.add(key)
        scored.append((10, entry, "无", "兜底"))

    return _finalize(xunji_name, part, scored, limit)


def _category_tie_order(part: str) -> dict[str, int]:
    """同分时按部位映射表顺序（更贴近部位），再比 name。

    纯 category 字母序会让 LUNGE 压过 SQUAT，导致「杠铃深蹲」主推落到分腿蹲。
    """
    return {c: i for i, c in enumerate(PART_TO_GARMIN_CATEGORIES.get(part) or [])}


def _finalize(
    xunji_name: str,
    part: str,
    scored: list[tuple[int, dict[str, str], str, str]],
    limit: int,
) -> list[Candidate]:
    cat_order = _category_tie_order(part)
    scored.sort(
        key=lambda row: (
            -row[0],
            cat_order.get(row[1].get("category", ""), 10_000),
            row[1].get("category", ""),
            row[1].get("name", ""),
        )
    )
    results: list[Candidate] = []
    for i, (score, entry, equip_label, mv_label) in enumerate(scored[:limit], start=1):
        results.append(
            Candidate(
                xunji_name=xunji_name,
                garmin_category=entry.get("category", ""),
                garmin_exercise_name=entry.get("exercise", ""),
                garmin_display_name=entry.get("name", ""),
                confidence=_score_to_confidence(score),
                rank=i,
                reason=(
                    f"部位={part}；器械={equip_label or '无'}；"
                    f"动作={mv_label}；命中 {score} 分"
                ),
            )
        )
    return results


def generate_candidates(
    xunji_name: str,
    *,
    limit: int = 3,
    catalog: list[dict[str, str]] | None = None,
) -> list[Candidate]:
    """4 级窄化生成候选，按 rank 升序返回最多 limit 条。"""
    if limit <= 0:
        return []
    if not xunji_name or not str(xunji_name).strip():
        return []

    name = str(xunji_name).strip()
    applicable, _reason = classify_applicability(name)
    if not applicable:
        return []

    source = catalog if catalog is not None else garmin_exercises.EXERCISES
    catalog_rows = _dedupe_catalog(source)

    tokens = extract_tokens(name)
    part = str(tokens["part"])
    part_categories = list(PART_TO_GARMIN_CATEGORIES.get(part) or [])
    equipment = list(tokens["equipment"])  # type: ignore[arg-type]
    postures = list(tokens["postures"])  # type: ignore[arg-type]
    movements = list(tokens["movements"])  # type: ignore[arg-type]

    # 器械专属分类优先排在前面（既进池，也用于加分判定）
    eq_categories = [
        EQUIPMENT_TO_GARMIN_CATEGORY[e]
        for e in equipment
        if e in EQUIPMENT_TO_GARMIN_CATEGORY
    ]
    # 去重保序：器械分类在前，部位分类在后
    categories = list(dict.fromkeys([*eq_categories, *part_categories]))

    if part_categories:
        cat_set = set(categories)
        pool = [e for e in catalog_rows if e.get("category") in cat_set]
    else:
        # 部位未知（classify_part 返回"其他"）时**不缩窄**：器械分类只用于加分，
        # 候选池保持全目录。否则会漏掉挂在其它分类下的器械动作——例如
        # 「弹力带-面拉」的正确答案 Banded Face Pulls 并不在 BANDED_EXERCISES 里，
        # 一旦按器械分类缩池就会从「有候选」退化成「无候选」。
        pool = catalog_rows

    # 排除有氧分类；INDOOR_ROW 是 ROW 下的划船机 exercise，不是 category
    pool = [
        e
        for e in pool
        if e.get("category") not in CARDIO_ONLY_CATEGORIES
        and e.get("exercise") != "INDOOR_ROW"
    ]

    if not movements:
        return _fallback_candidates(name, part, part_categories, catalog_rows, limit)

    best: dict[tuple[str, str], tuple[int, dict[str, str], str, str]] = {}
    # 先按窄化池扫描；若完全没命中且确实做过窄化，再回退全目录扫一遍。
    # 原因：classify_part 会按关键词误判部位——例如「上斜负重颈弯举」含"弯举"
    # 被判成「臂」，而 Garmin 把颈部动作放在 WARM_UP，窄化后必然扫不到。
    full_pool = [
        e
        for e in catalog_rows
        if e.get("category") not in CARDIO_ONLY_CATEGORIES
        and e.get("exercise") != "INDOOR_ROW"
    ]
    scan_pools = [pool]
    if part_categories:
        scan_pools.append(full_pool)
    for scan_pool in scan_pools:
        for mv in movements:
            alts = _movement_alternatives(mv)
            if not alts:
                continue
            for entry in scan_pool:
                display = entry.get("name", "")
                name_norm = _norm(display)
                if not any(a in name_norm for a in alts):
                    continue
                if _is_inconsistent(name, part, name_norm):
                    continue
                score = 20
                eq_bonus, eq_label = _equipment_bonus(equipment, name_norm)
                score += eq_bonus
                score += _posture_bonus(postures, name_norm)
                # 精确加成：优先用已命中的非空器械词根
                exact_equip = eq_label if eq_label != "无" else ""
                if not exact_equip and equipment:
                    exact_equip = next((e for e in equipment if e), "")
                score += _exact_bonus(exact_equip, mv, name_norm)
                if eq_categories and entry.get("category") in eq_categories:
                    score += EQUIPMENT_CATEGORY_BONUS

                key = (entry.get("category", ""), entry.get("exercise", ""))
                prev = best.get(key)
                if prev is None or score > prev[0]:
                    best[key] = (score, entry, eq_label, mv)
        if best:
            break

    if not best:
        return _fallback_candidates(name, part, categories, catalog_rows, limit)

    scored_rows = [
        (score, entry, eq_label, mv)
        for score, entry, eq_label, mv in best.values()
    ]
    return _finalize(name, part, scored_rows, limit)


def generate_batch(
    names: list[str],
    *,
    limit: int = 3,
) -> dict[str, list[Candidate]]:
    """批量版；对每个名字调用 generate_candidates。"""
    return {n: generate_candidates(n, limit=limit) for n in names}
