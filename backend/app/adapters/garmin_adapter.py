"""佳明数据适配器（PRD §6.2，2026-08-04 中国区返工：底层 garth 直连）。

纪律：
- 佳明接入只允许通过本模块暴露的函数调用，业务代码不得直接 import garth/garminconnect；
- 凭据只从环境变量 GARMIN_EMAIL / GARMIN_PASSWORD 读取，禁止硬编码；
- 域名读 GARMIN_DOMAIN（默认中国区 garmin.cn，全球区登录成功但返回空数据）；
- 登录链路：garth.configure → garth.resume(token_store)（失效才 garth.login + garth.save）；
- token 缓存于 ~/.garminconnect，同一进程只登录一次并复用会话（佳明有 IP 级 429 风控）；
- 全局限速：任意两次佳明 API 调用间隔 ≥ 0.5s；
- 收到 429 指数退避 60s/300s/900s，3 次仍失败抛 GarminAdapterError；
- 401/403（会话中途失效）自动凭据重登并重试一次；
- 所有原始异常统一包装为 GarminAdapterError，调用方不接触 garth 原始异常。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GarminActivity, GarminDaily

# 全局限速：任意两次佳明 API 调用的最小间隔（秒）
MIN_CALL_INTERVAL_S = 0.5

# 429 指数退避（秒）：依次等待 60 / 300 / 900，仍失败则抛 GarminAdapterError
BACKOFFS_429 = (60.0, 300.0, 900.0)

DEFAULT_TOKEN_STORE = Path.home() / ".garminconnect"

# Garmin Connect API 端点（与 garminconnect 库及网页端实际请求一致）
ACTIVITIES_PATH = "/activitylist-service/activities/search/activities"
ACTIVITY_PATH = "/activity-service/activity"
SOCIAL_PROFILE_PATH = "/userprofile-service/socialProfile"
DAILY_SUMMARY_PATH = "/usersummary-service/usersummary/daily"
SLEEP_PATH = "/wellness-service/wellness/dailySleepData"
HRV_PATH = "/hrv-service/hrv"
BODY_BATTERY_PATH = "/wellness-service/wellness/bodyBattery/reports/daily"

# 活动列表分页大小（与网页端行为一致）
PAGE_SIZE = 20


class GarminAdapterError(Exception):
    """佳明适配器统一异常：包装 garth/网络/认证的一切失败。"""


def _http_status(exc: BaseException) -> int | None:
    """从 garth.exc.GarthHTTPError / requests.HTTPError 中提取 HTTP 状态码。"""
    for err in (exc, getattr(exc, "error", None)):
        resp = getattr(err, "response", None)
        status = getattr(resp, "status_code", None)
        if status is not None:
            return status
    return None


class GarminClient:
    """佳明客户端（garth 直连）。garth/sleep/time_fn 可注入以便测试。"""

    def __init__(
        self,
        session: Session,
        *,
        email: str | None = None,
        password: str | None = None,
        token_store: str | Path | None = None,
        domain: str | None = None,
        garth: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = get_settings()
        self._email = email if email is not None else settings.garmin_email
        self._password = password if password is not None else settings.garmin_password
        if not self._email or not self._password:
            raise RuntimeError(
                "GARMIN_EMAIL/GARMIN_PASSWORD 未配置：请在环境变量或 .env 中设置"
            )
        self._domain = (
            domain if domain is not None else (settings.garmin_domain or "garmin.cn")
        )
        self._session = session
        self._token_store = Path(token_store) if token_store else DEFAULT_TOKEN_STORE
        self._garth = garth  # None 时首次使用再 import 真实 garth 模块
        self._sleep = sleep
        self._time = time_fn
        self._last_call: float | None = None
        self._logged_in = False
        self._display_name: str | None = None

    # ---------- 底层：garth 模块 / 登录 / 限速 / 异常包装 ----------

    def _garth_mod(self) -> Any:
        """惰性加载真实 garth 模块（测试时注入桩，不走这里）。"""
        if self._garth is None:
            import garth

            self._garth = garth
        return self._garth

    def login(self) -> None:
        """登录：优先用 token 缓存 resume 恢复会话；失效/缺失时凭据重登并刷新缓存。"""
        if self._logged_in:
            return
        g = self._garth_mod()
        g.configure(domain=self._domain)
        try:
            if not self._token_store.is_dir():
                raise FileNotFoundError(str(self._token_store))
            g.resume(str(self._token_store))
        except Exception:
            self._relogin()
        self._logged_in = True

    def _relogin(self) -> None:
        """凭据全量登录并把 token save 到缓存目录。"""
        g = self._garth_mod()
        try:
            g.configure(domain=self._domain)
            g.login(self._email, self._password)
            self._token_store.mkdir(parents=True, exist_ok=True)
            g.save(str(self._token_store))
        except Exception as exc:
            raise GarminAdapterError(f"佳明凭据重登失败：{exc}") from exc

    def _throttle(self) -> None:
        """全局限速：距上次 API 调用不足 MIN_CALL_INTERVAL_S 时先等待。"""
        now = self._time()
        if self._last_call is not None:
            wait = MIN_CALL_INTERVAL_S - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._time()

    def _connect(self, path: str, params: dict | None) -> Any:
        """单次 connectapi 调用：限速 + 429 指数退避（60/300/900，3 次后抛原始异常）。"""
        for attempt in range(len(BACKOFFS_429) + 1):
            if attempt:
                self._sleep(BACKOFFS_429[attempt - 1])
            self._throttle()
            try:
                return self._garth_mod().connectapi(path, params=params)
            except Exception as exc:
                if _http_status(exc) == 429 and attempt < len(BACKOFFS_429):
                    continue
                raise

    def _api(self, path: str, params: dict | None = None) -> Any:
        """佳明 API 统一入口：登录 → 调用；401/403 自动重登重试一次；异常统一包装。"""
        self.login()
        try:
            return self._connect(path, params)
        except Exception as exc:
            if _http_status(exc) in (401, 403):
                # token 会话中途失效：凭据重登并重试一次
                self._relogin()
                self._logged_in = True
                try:
                    return self._connect(path, params)
                except Exception as exc2:
                    raise GarminAdapterError(f"佳明 API 重试仍失败：{exc2}") from exc2
            raise GarminAdapterError(f"佳明 API 调用失败：{exc}") from exc

    def _require_display_name(self) -> str:
        """获取并缓存佳明账号 displayName（每日健康类端点的路径组成部分）。"""
        if not self._display_name:
            profile = self._api(SOCIAL_PROFILE_PATH) or {}
            name = profile.get("displayName")
            if not name:
                raise GarminAdapterError(
                    "佳明账号缺少 displayName（个人资料不完整），请先在 Garmin Connect 完善资料"
                )
            self._display_name = name
        return self._display_name

    # ---------- 活动同步 ----------

    def sync_activities(self, datestr: str) -> list[GarminActivity]:
        """拉取某日全部活动（含详情与 exercise sets）落库 garmin_activity。

        按 activity_id upsert，重复运行幂等。
        """
        activities = self._list_activities(datestr)
        rows = []
        for act in activities:
            activity_id = str(act.get("activityId"))
            details = self._api(
                f"{ACTIVITY_PATH}/{activity_id}/details",
                params={"maxChartSize": 2000, "maxPolylineSize": 4000},
            )
            try:
                exercise_sets = self._api(f"{ACTIVITY_PATH}/{activity_id}/exerciseSets")
            except GarminAdapterError:
                # 非力量训练活动可能无组次数据，忽略失败
                exercise_sets = None
            rows.append(self._upsert_activity(act, details, exercise_sets))
        self._session.commit()
        return rows

    def _list_activities(self, datestr: str) -> list[dict]:
        """按日期分页拉取活动列表（start/limit，网页端同款行为）。"""
        activities: list[dict] = []
        start = 0
        while True:
            page = self._api(
                ACTIVITIES_PATH,
                params={
                    "startDate": datestr,
                    "endDate": datestr,
                    "start": start,
                    "limit": PAGE_SIZE,
                },
            ) or []
            activities.extend(page)
            if len(page) < PAGE_SIZE:
                break
            start += PAGE_SIZE
        return activities

    def _upsert_activity(
        self, act: dict, details: dict | None, exercise_sets: dict | None
    ) -> GarminActivity:
        activity_id = str(act.get("activityId"))
        stmt = select(GarminActivity).where(GarminActivity.activity_id == activity_id)
        row = self._session.scalars(stmt).first()
        if row is None:
            row = GarminActivity(activity_id=activity_id)
            self._session.add(row)

        start = self._parse_dt(act.get("startTimeLocal"))
        duration = act.get("duration")
        duration_s = int(duration) if isinstance(duration, (int, float)) else None
        row.activity_type = (act.get("activityType") or {}).get("typeKey")
        row.name = act.get("activityName")
        row.start_ts = start
        row.end_ts = start + timedelta(seconds=duration_s) if start and duration_s else None
        row.duration_s = duration_s
        row.calories = self._int_or_none(act.get("calories"))
        row.avg_hr = self._int_or_none(act.get("averageHR"))
        row.max_hr = self._int_or_none(act.get("maxHR"))
        row.raw_json = json.dumps(
            {"summary": act, "details": details, "exercise_sets": exercise_sets},
            ensure_ascii=False,
            default=str,
        )
        row.fetched_at = datetime.now()
        return row

    # ---------- 每日健康同步 ----------

    def sync_daily(self, datestr: str) -> GarminDaily:
        """拉取某日睡眠/HRV/Body Battery/静息心率/压力/步数落库 garmin_daily（按 date upsert）。"""
        name = self._require_display_name()
        summary = self._api(
            f"{DAILY_SUMMARY_PATH}/{name}", params={"calendarDate": datestr}
        ) or {}
        sleep_data = self._api(
            f"{SLEEP_PATH}/{name}",
            params={"date": datestr, "nonSleepBufferMinutes": 60},
        )
        hrv = self._api(f"{HRV_PATH}/{datestr}")
        body_battery = self._api(
            BODY_BATTERY_PATH, params={"startDate": datestr, "endDate": datestr}
        )

        day = datetime.strptime(datestr, "%Y-%m-%d").date()
        stmt = select(GarminDaily).where(GarminDaily.date == day)
        row = self._session.scalars(stmt).first()
        if row is None:
            row = GarminDaily(date=day)
            self._session.add(row)

        high = self._int_or_none(summary.get("bodyBatteryHighestValue"))
        low = self._int_or_none(summary.get("bodyBatteryLowestValue"))
        if (high is None or low is None) and body_battery:
            # 真实返回结构：{"date", "charged", "drained",
            #   "bodyBatteryValuesArray": [[timestamp_ms, value], ...]}，取绝对电位的极值
            vals = [
                int(pair[1])
                for entry in body_battery
                for pair in (entry.get("bodyBatteryValuesArray") or [])
                if isinstance(pair, (list, tuple))
                and len(pair) >= 2
                and isinstance(pair[1], (int, float))
            ]
            if vals:
                high = high if high is not None else max(vals)
                low = low if low is not None else min(vals)

        row.steps = self._int_or_none(summary.get("totalSteps"))
        row.resting_hr = self._int_or_none(summary.get("restingHeartRate"))
        row.stress_avg = self._int_or_none(summary.get("averageStressLevel"))
        row.body_battery_high = high
        row.body_battery_low = low
        row.hrv_status = ((hrv or {}).get("hrvSummary") or {}).get("status")
        row.sleep_json = (
            json.dumps(sleep_data, ensure_ascii=False, default=str)
            if sleep_data is not None
            else None
        )
        row.raw_json = json.dumps(
            {
                "summary": summary,
                "sleep": sleep_data,
                "hrv": hrv,
                "body_battery": body_battery,
            },
            ensure_ascii=False,
            default=str,
        )
        row.fetched_at = datetime.now()
        self._session.commit()
        return row

    # ---------- FIT/TCX 手动导入（降级通道） ----------

    def import_fit_file(self, path: str) -> None:
        # TODO(V2-4): 解析 FIT/TCX 文件并落库 garmin_activity，作为接口失效时的降级通道
        raise NotImplementedError("FIT/TCX 手动导入将在 V2-4 实现")

    # ---------- 工具 ----------

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        """解析佳明本地时间字符串（如 '2026-08-03 18:30:00'）。"""
        if not value:
            return None
        return datetime.strptime(value.strip()[:19], "%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        return int(value) if isinstance(value, (int, float)) else None
