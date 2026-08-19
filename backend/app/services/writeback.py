"""V1-5 训记写回确认流服务：PRD §5.4 逐条落实。

纪律：
- 预览（preview）只用 include_full_data=true 读原训练生成本地 diff，绝不调用写回接口；
- 确认（confirm）是唯一传 dry_run=False 的代码路径，进程内锁串行 + 适配器 45s 限频排队；
- 合并 payload 保留 localid/datestr/start/end/note 全量元数据（含 trainColor/heartRate）；
- 动作名只允许 GitHub Foveluy/Xunji-movements 标准中文名；
- 约束：单次 ≤4 条且同一天、每训练 ≤15 动作、每动作 ≤20 组，违反一律拒绝且不外呼；
- 写回成功用服务端返回的标准化 res 覆盖本地缓存，并重跑当日融合（更新受影响 workout）；
- 每次写回（成功/失败）写 job_run 留痕（请求体摘要 + 结果）。
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.xunji import XunjiAPIError
from app.models import JobRun, Workout, XunjiTrain
from app.movements import is_standard_movement
from app.services.fuse import _extract_movements

# 写回硬约束（PRD §6.1）
MAX_TRAINS_PER_REQUEST = 4
MAX_MOVEMENTS_PER_TRAIN = 15
MAX_SETS_PER_MOVEMENT = 20

# 确认流进程内串行锁（多请求排队，配合适配器 45s 限频）
_CONFIRM_LOCK = threading.Lock()


class WritebackValidationError(ValueError):
    """写回请求违反约束（数量上限/同一天/非标准动作名），一律拒绝且不外呼。"""


class WritebackNotFoundError(ValueError):
    """指定 datestr+localid 的训记训练不存在。"""


def validate_writeback_trains(trains: list[dict]) -> None:
    """校验写回 payload：≤4 条、同一天、每训练 ≤15 动作、每动作 ≤20 组。"""
    if not isinstance(trains, list) or not trains:
        raise WritebackValidationError("写回内容为空")
    if len(trains) > MAX_TRAINS_PER_REQUEST:
        raise WritebackValidationError(f"单次最多 {MAX_TRAINS_PER_REQUEST} 条训练")
    datestrs = {str(t.get("datestr", "")) for t in trains if isinstance(t, dict)}
    if len(datestrs) != 1:
        raise WritebackValidationError("单次写回的训练必须属于同一天")
    for i, train in enumerate(trains):
        movements = train.get("movements") or []
        if len(movements) > MAX_MOVEMENTS_PER_TRAIN:
            raise WritebackValidationError(
                f"第 {i + 1} 条训练动作数超过 {MAX_MOVEMENTS_PER_TRAIN} 个"
            )
        for j, mv in enumerate(movements):
            sets = mv.get("sets") or []
            if len(sets) > MAX_SETS_PER_MOVEMENT:
                raise WritebackValidationError(
                    f"第 {i + 1} 条训练第 {j + 1} 个动作组数超过 {MAX_SETS_PER_MOVEMENT} 组"
                )


def validate_movement_names(movements: list[dict]) -> None:
    """PRD §5.4：写回动作名只允许标准中文名表内的名字。"""
    for mv in movements:
        name = (mv.get("name") or "").strip() if isinstance(mv, dict) else ""
        if not is_standard_movement(name):
            raise WritebackValidationError(f"非标准动作名，禁止写回: {mv.get('name')!r}")


def _match_movement_index(pool: list[dict], change: dict, used: set[int]) -> int | None:
    """动作匹配：按 name（辅以 index 消歧），返回 pool 下标；未匹配返回 None。"""
    name = (change.get("name") or "").strip()
    candidates = [
        i
        for i, m in enumerate(pool)
        if i not in used and (m.get("name") or "").strip() == name
    ]
    if not candidates:
        return None
    ci = change.get("index")
    if isinstance(ci, int):
        for i in candidates:
            if pool[i].get("index") == ci:
                return i
    return candidates[0]


def _merge_sets(orig_sets: list[dict], change_sets: list[dict]) -> list[dict]:
    """组级合并：按 index（缺省按顺序）匹配；`_delete: true` 显式删除；
    未指定的组原样保留；匹配到的组仅覆盖 changes 显式给出的字段。"""
    sets = list(orig_sets)
    for pos, cs in enumerate(change_sets):
        if not isinstance(cs, dict):
            raise WritebackValidationError("sets 元素必须为对象")
        target: dict | None = None
        ci = cs.get("index")
        if isinstance(ci, int):
            for s in sets:
                if s.get("index") == ci:
                    target = s
                    break
            if target is None and 1 <= ci <= len(sets):
                target = sets[ci - 1]  # 原组无 index 字段时按序号兜底
        elif pos < len(sets):
            target = sets[pos]  # 未显式给 index 时才按顺序匹配
        if cs.get("_delete") is True:
            if target is not None:
                sets.remove(target)
            continue
        if target is None:
            sets.append({k: v for k, v in cs.items() if k != "_delete"})
        else:
            for k, v in cs.items():
                if k not in ("index", "_delete"):
                    target[k] = v
    return sets


def _merge_movements(orig: list[dict], changes: list[dict]) -> list[dict]:
    """动作级合并：changes 动作按 name（辅以 index）匹配原动作；
    未在 changes 中出现的原动作原样保留、顺序不变；
    name 匹配不到的变更动作视为新增动作追加，不得静默丢弃原动作。"""
    merged = copy.deepcopy(orig)
    used: set[int] = set()
    for change in changes:
        if not isinstance(change, dict):
            raise WritebackValidationError("movements 元素必须为对象")
        i = _match_movement_index(merged, change, used)
        if i is None:
            appended = copy.deepcopy(change)
            appended["sets"] = [
                {k: v for k, v in s.items() if k != "_delete"}
                for s in (appended.get("sets") or [])
                if isinstance(s, dict) and s.get("_delete") is not True
            ]
            merged.append(appended)
            continue
        used.add(i)
        target = merged[i]
        for k, v in change.items():
            if k not in ("name", "sets", "index"):
                target[k] = v
        if "sets" in change:
            change_sets = change["sets"]
            if not isinstance(change_sets, list):
                raise WritebackValidationError("sets 必须为数组")
            target["sets"] = _merge_sets(target.get("sets") or [], change_sets)
    return merged


def build_merged_train(original: dict, datestr: str, changes: dict) -> dict:
    """把变更合并到原训练上，保留全部元数据（V1-5-FIX 三级深度合并）。

    以原训练为底（localid/start/end/note/heartRate 等全量保留），
    datestr 强制为目标日期；title 整体覆盖；movements 三级深度合并：
    - 动作级：changes 动作按 name（辅以 index）匹配，未提到的原动作原样保留、
      顺序不变，匹配不到的变更动作作为新增动作追加；
    - 组级：匹配动作内 sets 按 index（缺省按顺序）匹配合并，未指定的组保留，
      `_delete: true` 显式删除；
    - 字段级：被指定的组只覆盖 changes 显式给出的字段，未给字段保留原值。
    """
    if not isinstance(changes, dict):
        raise WritebackValidationError("changes 必须为对象")
    unknown = set(changes) - {"title", "movements"}
    if unknown:
        raise WritebackValidationError(f"不允许修改的字段: {sorted(unknown)}")
    merged = dict(original)
    merged["datestr"] = datestr
    merged["localid"] = original.get("localid")
    if "title" in changes:
        merged["title"] = changes["title"]
    if "movements" in changes:
        movements = changes["movements"]
        if not isinstance(movements, list):
            raise WritebackValidationError("movements 必须为数组")
        validate_movement_names(movements)
        merged["movements"] = _merge_movements(original.get("movements") or [], movements)
    return merged


def _diff_row(rows: list[dict], field: str, old: Any, new: Any) -> None:
    rows.append({"field": field, "old": old, "new": new, "changed": old != new})


def build_diff(original: dict, merged: dict) -> list[dict]:
    """生成「字段/原值/新值」diff 行，changed 标记供前端高亮。"""
    rows: list[dict] = []
    _diff_row(rows, "title", original.get("title"), merged.get("title"))
    old_movements = original.get("movements") or []
    new_movements = merged.get("movements") or []
    for i in range(max(len(old_movements), len(new_movements))):
        if i >= len(old_movements):
            mv = new_movements[i]
            _diff_row(rows, f"动作{i + 1} {mv.get('name')}", None, "新增动作")
            continue
        if i >= len(new_movements):
            mv = old_movements[i]
            _diff_row(rows, f"动作{i + 1} {mv.get('name')}", "原有动作", None)
            continue
        old_mv, new_mv = old_movements[i], new_movements[i]
        name = new_mv.get("name") or old_mv.get("name") or f"动作{i + 1}"
        _diff_row(rows, f"动作{i + 1} name", old_mv.get("name"), new_mv.get("name"))
        _diff_row(rows, f"动作{i + 1} {name} difficulty", old_mv.get("difficulty"), new_mv.get("difficulty"))
        old_sets = old_mv.get("sets") or []
        new_sets = new_mv.get("sets") or []
        for j in range(max(len(old_sets), len(new_sets))):
            if j >= len(old_sets):
                _diff_row(rows, f"动作{i + 1} {name} 第{j + 1}组", None, json.dumps(new_sets[j], ensure_ascii=False))
                continue
            if j >= len(new_sets):
                _diff_row(rows, f"动作{i + 1} {name} 第{j + 1}组", json.dumps(old_sets[j], ensure_ascii=False), None)
                continue
            for prop in ("weight", "unit", "reps", "time", "rpe", "done"):
                _diff_row(
                    rows,
                    f"动作{i + 1} {name} 第{j + 1}组 {prop}",
                    old_sets[j].get(prop),
                    new_sets[j].get(prop),
                )
    return rows


def _extract_server_trains(resp: dict) -> list[dict]:
    """写回响应的 res 可能是训练数组，也可能是 {"trains": [...]}（PRD §6.1）。"""
    res = resp.get("res")
    if isinstance(res, list):
        return [t for t in res if isinstance(t, dict)]
    if isinstance(res, dict):
        return [t for t in (res.get("trains") or []) if isinstance(t, dict)]
    return []


class WritebackService:
    """写回确认流编排。xunji 可注入以便测试；默认懒创建 XunjiClient。"""

    def __init__(self, session: Session, xunji=None) -> None:
        self._session = session
        self._xunji = xunji

    @property
    def xunji(self):
        if self._xunji is None:
            from app.adapters.xunji import XunjiClient

            self._xunji = XunjiClient(self._session)
        return self._xunji

    # ---------- 预览（只读，绝不写） ----------

    def preview(self, datestr: str, localid: int | str, changes: dict) -> dict:
        """include_full_data=true 强制刷新读原训练，合并变更生成 diff 返回。"""
        self.xunji.fetch_trains(datestr, include_full_data=True, force_refresh=True)
        row = self._find_train(datestr, localid)
        if row is None:
            raise WritebackNotFoundError(f"{datestr} 不存在 localid={localid} 的训练")
        return self._build(datestr, row, changes)

    # ---------- 确认（唯一 dry_run=False 路径） ----------

    def confirm(self, datestr: str, localid: int | str, changes: dict) -> dict:
        """用户确认后执行真实写回：串行锁 + 45s 限频，成功覆盖缓存并重跑当日融合。"""
        with _CONFIRM_LOCK:
            started_at = datetime.now()
            built: dict | None = None
            try:
                row = self._find_train(datestr, localid)
                if row is None:
                    # 未经过预览时兜底：完整读一次再合并
                    self.xunji.fetch_trains(datestr, include_full_data=True, force_refresh=True)
                    row = self._find_train(datestr, localid)
                if row is None:
                    raise WritebackNotFoundError(f"{datestr} 不存在 localid={localid} 的训练")
                built = self._build(datestr, row, changes)

                resp = self.xunji.upsert_trains([built["train"]], dry_run=False)
                if isinstance(resp, dict) and resp.get("error"):
                    raise XunjiAPIError(f"训记写回失败: {resp.get('error')}")

                # 服务端标准化数据覆盖本地缓存；无返回时以已确认的合并结果兜底
                server_trains = _extract_server_trains(resp)
                self.xunji.cache_trains(datestr, server_trains or [built["train"]])

                # 重跑当日融合：更新引用该训记记录的 workout
                workouts_updated = self._refuse_day(date.fromisoformat(datestr))

                result = {
                    "status": "written",
                    "datestr": datestr,
                    "localid": str(localid),
                    "diff": built["diff"],
                    "workouts_updated": workouts_updated,
                }
                self._write_job_run(started_at, "success", None, built, result)
                return result
            except Exception as exc:
                self._session.rollback()
                self._write_job_run(started_at, "failed", str(exc), built, None)
                raise

    # ---------- 内部 ----------

    def _find_train(self, datestr: str, localid: int | str) -> XunjiTrain | None:
        stmt = select(XunjiTrain).where(
            XunjiTrain.datestr == datestr, XunjiTrain.localid == str(localid)
        )
        return self._session.scalars(stmt).first()

    def _build(self, datestr: str, row: XunjiTrain, changes: dict) -> dict:
        """合并 + 校验 + diff。校验失败抛 WritebackValidationError，不发生任何外呼写。"""
        original = json.loads(row.raw_json) if row.raw_json else {}
        merged = build_merged_train(original, datestr, changes)
        validate_writeback_trains([merged])
        return {
            "datestr": datestr,
            "localid": str(row.localid),
            "diff": build_diff(original, merged),
            "train": merged,
        }

    def _refuse_day(self, day: date) -> list[int]:
        """重跑当日融合：用覆盖后的训记缓存更新受影响 workout 的标题与组次。"""
        datestr = day.isoformat()
        updated: list[int] = []
        trains = self._session.scalars(
            select(XunjiTrain).where(XunjiTrain.datestr == datestr)
        ).all()
        for train in trains:
            workouts = self._session.scalars(
                select(Workout).where(
                    Workout.xunji_train_id == train.id,
                    Workout.deleted_at.is_(None),
                )
            ).all()
            for w in workouts:
                w.title = train.title or w.title
                w.movements_json = _extract_movements(train)
                updated.append(w.id)
        self._session.commit()
        return updated

    def _write_job_run(
        self,
        started_at: datetime,
        status: str,
        error: str | None,
        built: dict | None,
        result: dict | None,
    ) -> None:
        """写回留痕：请求体摘要（datestr/localid/变更字段）+ 结果。"""
        detail: dict[str, Any] = {}
        if built is not None:
            changed_fields = [r["field"] for r in built["diff"] if r["changed"]]
            detail.update(
                {
                    "datestr": built["datestr"],
                    "localid": built["localid"],
                    "changed_fields": changed_fields,
                    "train_count": 1,
                }
            )
        if result is not None:
            detail["workouts_updated"] = result["workouts_updated"]
        self._session.add(
            JobRun(
                job_name="writeback",
                started_at=started_at,
                finished_at=datetime.now(),
                status=status,
                error=error,
                detail_json=json.dumps(detail, ensure_ascii=False, default=str),
            )
        )
        self._session.commit()
