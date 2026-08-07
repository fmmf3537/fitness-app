"""训记 Open API 适配器（PRD §6.1）。

纪律：
- 所有训记调用必须经过统一的限频装饰器（读 15s / 完整读 30s / 写回 45s，
  按"同一 datestr"维度计时；官方计划按 key+action+plan_ref 15s）；
- upsert_trains 默认 dry_run=True，只有写回确认流（services/writeback）才传 dry_run=False；
- Key 只从环境变量 XUNJI_API_KEY 读取，禁止硬编码；
- 按 datestr 缓存：同日已拉取过且未强制刷新时直接读库不发请求；
- 原始响应完整存入 raw_json 字段。
"""
from __future__ import annotations

import gzip
import json
import time
import uuid
from datetime import date, datetime
from functools import wraps
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import XunjiPlan, XunjiTrain

TRAINS_READ_URL = "https://trains.xunjiapp.cn/api_trains_for_llm_v2"
TRAINS_UPSERT_URL = "https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2"
PLAN_URL = "https://api.xunjiapp.cn/open/plan/query_gzip"

# 限频档位（秒）：普通读 15s / 完整读 30s / 写回 45s
RATE_LIMITS = {"read": 15.0, "full_read": 30.0, "write": 45.0}
MAX_TOO_FREQUENT_RETRIES = 3


class XunjiAPIError(Exception):
    """训记 API 调用失败。"""


class XunjiRateLimitError(XunjiAPIError):
    """too frequent 重试 3 次后仍失败。"""


def rate_limited(func: Callable) -> Callable:
    """统一限频装饰器：训记的所有 HTTP 调用必须经此装饰器。

    被装饰方法签名约定为 ``(self, url, body, *, kind, rl_key)``：
    - kind：限频档位（read / full_read / write）；
    - rl_key：计时维度键（训练读/写用 datestr，计划用 action+plan_ref）。
    """

    @wraps(func)
    def wrapper(self, url, body, *, kind, rl_key):
        self._throttle(kind, rl_key)
        return func(self, url, body, kind=kind, rl_key=rl_key)

    return wrapper


class XunjiClient:
    """训记 API 客户端。clock/sleep 可注入以便测试限频行为。"""

    def __init__(
        self,
        session: Session,
        api_key: str | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
        http: httpx.Client | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key if api_key is not None else get_settings().xunji_api_key
        if not self._api_key:
            raise RuntimeError("XUNJI_API_KEY 未配置：请在环境变量或 .env 中设置")
        self._sleep = sleep
        self._time = time_fn
        self._http = http or httpx.Client(timeout=30.0)
        self._last_call: dict[tuple[str, str], float] = {}

    # ---------- 底层：限频 + 请求 ----------

    def _throttle(self, kind: str, rl_key: str) -> None:
        """同一 (kind, rl_key) 维度距离上次调用不足限频间隔时先等待。"""
        key = (kind, rl_key)
        now = self._time()
        last = self._last_call.get(key)
        if last is not None:
            wait = RATE_LIMITS[kind] - (now - last)
            if wait > 0:
                self._sleep(wait)
        self._last_call[key] = self._time()

    @rate_limited
    def _post(self, url: str, body: dict, *, kind: str, rl_key: str) -> dict:
        """发 POST 请求（限频装饰器入口），处理 gzip 与 too frequent 重试。"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        }
        for attempt in range(1, MAX_TOO_FREQUENT_RETRIES + 1):
            resp = self._http.post(url, json=body, headers=headers)
            data = self._decode_json(resp)
            retry_ms = self._too_frequent_retry_ms(data)
            if retry_ms is None:
                return data
            if attempt >= MAX_TOO_FREQUENT_RETRIES:
                raise XunjiRateLimitError(
                    f"too frequent：{rl_key} 重试 {MAX_TOO_FREQUENT_RETRIES} 次后仍被限频"
                )
            self._sleep(retry_ms / 1000.0)
        raise XunjiAPIError("unreachable")  # pragma: no cover

    @staticmethod
    def _decode_json(resp: httpx.Response) -> dict:
        """解析响应 JSON；body 为裸 gzip 字节流（无 Content-Encoding 头）时先解压。"""
        content = resp.content
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8"))

    @staticmethod
    def _too_frequent_retry_ms(data: Any) -> float | None:
        """响应包含 too frequent 时返回应等待毫秒数，否则返回 None。"""
        if not isinstance(data, dict):
            return None
        text = json.dumps(data, ensure_ascii=False).lower()
        if "too frequent" in text:
            retry = data.get("retry_after_ms")
            try:
                return float(retry) if retry is not None else 15000.0
            except (TypeError, ValueError):
                return 15000.0
        return None

    # ---------- 读取训练 ----------

    def fetch_trains(
        self,
        datestr: str,
        include_full_data: bool = False,
        *,
        force_refresh: bool = False,
    ) -> list[XunjiTrain]:
        """拉取某日训练并落库 xunji_train（按 (datestr, localid) upsert，幂等）。

        同一 datestr 当天已拉取过时直接返回库中缓存，不发请求（force_refresh 除外）。
        """
        if not force_refresh:
            cached = self._cached_trains(datestr)
            if cached:
                return cached

        kind = "full_read" if include_full_data else "read"
        body = {
            "schema_version": "train_open_api_v2",
            "datestr": datestr,
            "include_full_data": include_full_data,
        }
        data = self._post(TRAINS_READ_URL, body, kind=kind, rl_key=datestr)
        trains = (data.get("res") or {}).get("trains") or []
        for train in trains:
            self._upsert_train(datestr, train)
        self._session.commit()
        return list(self._session.scalars(select(XunjiTrain).where(XunjiTrain.datestr == datestr)))

    def _cached_trains(self, datestr: str) -> list[XunjiTrain]:
        """当天已拉取过的 datestr 缓存命中。"""
        today_start = datetime.combine(date.today(), datetime.min.time())
        stmt = select(XunjiTrain).where(
            XunjiTrain.datestr == datestr,
            XunjiTrain.fetched_at >= today_start,
        )
        return list(self._session.scalars(stmt))

    def _upsert_train(self, datestr: str, train: dict) -> XunjiTrain:
        localid = str(train.get("localid"))
        stmt = select(XunjiTrain).where(
            XunjiTrain.datestr == datestr, XunjiTrain.localid == localid
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            row = XunjiTrain(datestr=datestr, localid=localid)
            self._session.add(row)
        row.title = train.get("title")
        row.start_ms = train.get("start")
        row.end_ms = train.get("end")
        note = train.get("note")
        row.note_json = json.dumps(note, ensure_ascii=False) if note is not None else None
        row.raw_json = json.dumps(train, ensure_ascii=False)
        row.fetched_at = datetime.now()
        return row

    # ---------- 写回训练（V1-5：默认 dry_run，确认流才传 False） ----------

    def upsert_trains(self, payload: list[dict], dry_run: bool = True) -> dict:
        """写回训练。默认 dry_run=True；dry_run=False 仅限写回确认流内部调用。"""
        datestrs = sorted({str(r.get("datestr", "")) for r in payload if isinstance(r, dict)})
        rl_key = ",".join(datestrs) or "unknown"
        body = {
            "schema_version": "train_open_api_v2",
            "client_request_id": str(uuid.uuid4()),
            "dry_run": dry_run,
            "include_full_data": False,
            "res": payload,
        }
        return self._post(TRAINS_UPSERT_URL, body, kind="write", rl_key=rl_key)

    def cache_trains(self, datestr: str, trains: list[dict]) -> None:
        """用服务端返回的标准化训练数据覆盖本地 xunji_train 缓存（PRD §5.4）。"""
        for train in trains:
            self._upsert_train(datestr, train)
        self._session.commit()

    # ---------- 官方计划（只读） ----------

    def fetch_plan_list(self) -> list[XunjiPlan]:
        """列出官方计划并落库 xunji_plan（按 plan_ref 覆盖，幂等）。

        同步解析 list 响应中的 start_date/end_date 写入 date_from/date_to，
        并清理历史遗留的日期为 NULL 的脏行（V1-4-FIX）。
        """
        body = {"schema_version": "plan_open_api_v1", "action": "list"}
        data = self._post(PLAN_URL, body, kind="read", rl_key="plan:list")
        plans = (data.get("res") or {}).get("plans") or []
        self._purge_dirty_plan_rows()
        rows = []
        for plan in plans:
            plan_ref = str(plan.get("plan_ref", ""))
            self._delete_plan_rows(plan_ref)
            row = XunjiPlan(
                plan_ref=plan_ref,
                plan_json=json.dumps(plan, ensure_ascii=False, default=str),
                date_from=self._parse_date(plan.get("start_date")),
                date_to=self._parse_date(plan.get("end_date")),
                fetched_at=datetime.now(),
            )
            self._session.add(row)
            rows.append(row)
        self._session.commit()
        return rows

    def fetch_plan(self, plan_ref: str, start_date: str | date, end_date: str | date) -> XunjiPlan:
        """读取计划详情并落库 xunji_plan（按 plan_ref 覆盖，幂等）。

        start_date/end_date 接受 str 或 date/datetime，请求体一律序列化为 ISO 字符串。
        """
        body = {
            "schema_version": "plan_open_api_v1",
            "action": "get",
            "plan_ref": plan_ref,
            "start_date": self._iso_date(start_date),
            "end_date": self._iso_date(end_date),
            "include_movements": True,
        }
        data = self._post(PLAN_URL, body, kind="read", rl_key=f"plan:get:{plan_ref}")
        res = data.get("res") or {}
        self._delete_plan_rows(plan_ref)
        date_range = res.get("date_range") or {}
        row = XunjiPlan(
            plan_ref=plan_ref,
            plan_json=json.dumps(res, ensure_ascii=False, default=str),
            date_from=self._parse_date(date_range.get("start_date") or start_date),
            date_to=self._parse_date(date_range.get("end_date") or end_date),
            fetched_at=datetime.now(),
        )
        self._session.add(row)
        self._session.commit()
        return row

    def _delete_plan_rows(self, plan_ref: str) -> None:
        stmt = select(XunjiPlan).where(XunjiPlan.plan_ref == plan_ref)
        for old in self._session.scalars(stmt):
            self._session.delete(old)
        self._session.flush()

    def _purge_dirty_plan_rows(self) -> None:
        """清理 date_from/date_to 为 NULL 的历史脏行（V1-4-FIX 前的 list 写入遗留）。"""
        stmt = select(XunjiPlan).where(
            (XunjiPlan.date_from.is_(None)) | (XunjiPlan.date_to.is_(None))
        )
        for old in self._session.scalars(stmt):
            self._session.delete(old)
        self._session.flush()

    @staticmethod
    def _iso_date(value: str | date | datetime) -> str:
        """date/datetime 统一转 ISO 日期字符串，str 原样透传。"""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _parse_date(value: str | date | datetime | None) -> date | None:
        """解析 ISO 日期；兼容 date/datetime 入参（真实链路防御）。"""
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.strptime(str(value), "%Y-%m-%d").date()
