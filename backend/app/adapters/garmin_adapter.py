"""佳明数据适配器（PRD §6.2）。

纪律：
- 佳明接入只允许通过本模块暴露的函数调用，业务代码不得直接 import garminconnect；
- 凭据只从环境变量 GARMIN_EMAIL / GARMIN_PASSWORD 读取，禁止硬编码；
- token 缓存于 ~/.garminconnect，过期时自动用缓存凭据重登；
- 全局限速：任意两次佳明 API 调用间隔 ≥ 0.5s，防止触发风控；
- 所有 garminconnect 原始异常统一包装为 GarminAdapterError，调用方不接触原始异常。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from garminconnect.exceptions import GarminConnectAuthenticationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GarminActivity, GarminDaily

# 全局限速：任意两次佳明 API 调用的最小间隔（秒）
MIN_CALL_INTERVAL_S = 0.5

DEFAULT_TOKEN_STORE = Path.home() / ".garminconnect"


class GarminAdapterError(Exception):
    """佳明适配器统一异常：包装 garminconnect/网络/认证的一切失败。"""


class GarminClient:
    """佳明客户端。garmin/sleep/time_fn 可注入以便测试。"""

    def __init__(
        self,
        session: Session,
        *,
        email: str | None = None,
        password: str | None = None,
        token_store: str | Path | None = None,
        garmin: Any = None,
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
        self._session = session
        self._token_store = Path(token_store) if token_store else DEFAULT_TOKEN_STORE
        self._garmin = garmin  # None 时首次使用再创建真实 garminconnect.Garmin
        self._sleep = sleep
        self._time = time_fn
        self._last_call: float | None = None
        self._logged_in = False

    # ---------- 底层：客户端 / 登录 / 限速 / 异常包装 ----------

    def _client(self) -> Any:
        """惰性创建真实 garminconnect.Garmin（测试时注入桩，不走这里）。"""
        if self._garmin is None:
            from garminconnect import Garmin

            self._garmin = Garmin(self._email, self._password)
        return self._garmin

    def login(self) -> None:
        """登录：优先用 token 缓存恢复会话；失效/缺失时用凭据全量重登并刷新缓存。"""
        if self._logged_in:
            return
        garmin = self._client()
        try:
            if not self._token_store.is_dir():
                raise FileNotFoundError(str(self._token_store))
            garmin.login(str(self._token_store))
        except Exception:
            self._relogin()
        self._logged_in = True

    def _relogin(self) -> None:
        """凭据全量登录并把 token dump 到缓存目录。"""
        garmin = self._client()
        try:
            garmin.login()
            self._token_store.mkdir(parents=True, exist_ok=True)
            garmin.garth.dump(str(self._token_store))
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

    def _call(self, method: Callable, *args, **kwargs) -> Any:
        """佳明 API 统一入口：登录 → 限速 → 调用；401 自动重登重试一次；异常统一包装。"""
        self.login()
        self._throttle()
        try:
            return method(*args, **kwargs)
        except GarminConnectAuthenticationError:
            # token 会话中途失效：凭据重登并重试一次
            self._relogin()
            self._logged_in = True
            self._throttle()
            try:
                return method(*args, **kwargs)
            except Exception as exc:
                raise GarminAdapterError(f"佳明 API 重试仍失败：{exc}") from exc
        except Exception as exc:
            raise GarminAdapterError(f"佳明 API 调用失败：{exc}") from exc

    # ---------- 活动同步 ----------

    def sync_activities(self, datestr: str) -> list[GarminActivity]:
        """拉取某日全部活动（含详情与 exercise sets）落库 garmin_activity。

        按 activity_id upsert，重复运行幂等。
        """
        garmin = self._client()
        activities = self._call(garmin.get_activities_by_date, datestr, datestr) or []
        rows = []
        for act in activities:
            activity_id = str(act.get("activityId"))
            details = self._call(garmin.get_activity_details, activity_id)
            try:
                exercise_sets = self._call(garmin.get_activity_exercise_sets, activity_id)
            except GarminAdapterError:
                # 非力量训练活动可能无组次数据，忽略失败
                exercise_sets = None
            rows.append(self._upsert_activity(act, details, exercise_sets))
        self._session.commit()
        return rows

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
        garmin = self._client()
        summary = self._call(garmin.get_user_summary, datestr) or {}
        sleep_data = self._call(garmin.get_sleep_data, datestr)
        hrv = self._call(garmin.get_hrv_data, datestr)
        body_battery = self._call(garmin.get_body_battery, datestr, datestr)

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
