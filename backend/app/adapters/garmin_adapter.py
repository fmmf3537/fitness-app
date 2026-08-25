"""佳明数据适配器（PRD §6.2，2026-08-04 中国区返工：底层 garth 直连）。

纪律：
- 佳明接入只允许通过本模块暴露的函数调用，业务代码不得直接 import garth/garminconnect；
- 凭据只从环境变量 GARMIN_EMAIL / GARMIN_PASSWORD / settings 表 (按 user_id) 读取，禁止硬编码；
- 域名读 GARMIN_DOMAIN（默认中国区 garmin.cn，全球区登录成功但返回空数据）；
- 登录链路：M3-1 重构——**每个 GarminClient 自带 garth.Client 实例**（避免模块级单例串 token），
  token 走 settings.garmin_token_store_enc（Fernet 加密，**完全在内存**），不再写 ~/.garminconnect 目录；
- 全局限速：任意两次佳明 API 调用间隔 ≥ 0.5s；
- 收到 429 指数退避 60s/300s/900s，3 次仍失败抛 GarminAdapterError；
- 401/403（会话中途失效）自动凭据重登并重试一次；
- 所有原始异常统一包装为 GarminAdapterError，调用方不接触 garth 原始异常。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GarminActivity, GarminDaily, Setting

# 全局限速：任意两次佳明 API 调用的最小间隔（秒）
MIN_CALL_INTERVAL_S = 0.5

# 429 指数退避（秒）：依次等待 60 / 300 / 900，仍失败则抛 GarminAdapterError
BACKOFFS_429 = (60.0, 300.0, 900.0)

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


class GarminKeyNotConfiguredError(GarminAdapterError):
    """M3-1：某用户/全局佳明凭据未配置（settings 表与环境变量都没有）。

    区别于 GarminAdapterError（运行时调用失败）：这是**配置缺失**，应让上层明确提示
    用户去 settings 页面绑定佳明账号。
    """


def _http_status(exc: BaseException) -> int | None:
    """从 garth.exc.GarthHTTPError / requests.HTTPError 中提取 HTTP 状态码。"""
    for err in (exc, getattr(exc, "error", None)):
        resp = getattr(err, "response", None)
        status = getattr(resp, "status_code", None)
        if status is not None:
            return status
    return None


# ---------- Key 解析（M3-1 多用户按 user_id 隔离） ----------


def _resolve_garmin_credentials(
    session: Session | None,
    user_id: int | None,
) -> tuple[str | None, str | None, str | None]:
    """佳明凭据解析优先级：参数 > settings 表（按 user_id，Fernet 解密）> 环境变量。

    返回 (email, password, domain)。任一缺失返回 None 占位。
    """
    from app.config import decrypt_value

    email = password = domain = None
    if session is not None and user_id is not None:
        row = session.scalars(
            select(Setting).where(Setting.user_id == user_id)
        ).first()
        if row is not None:
            try:
                if row.garmin_email_enc:
                    email = decrypt_value(row.garmin_email_enc)
                if row.garmin_password_enc:
                    password = decrypt_value(row.garmin_password_enc)
            except Exception:
                pass
    settings = get_settings()
    if not email:
        email = settings.garmin_email
    if not password:
        password = settings.garmin_password
    domain = settings.garmin_domain or "garmin.cn"
    return email, password, domain


def _serialize_garmin_token(client: Any) -> str:
    """从登录后的 garth.Client 提取 token，序列化为 JSON 字符串。

    M3-1：settings.garmin_token_store_enc 存的就是这个 JSON 加密后的产物。
    完全在内存操作，不写任何磁盘文件。
    兼容 dataclass 实例（生产 garth.Client）和 dict（测试桩）。
    """
    from dataclasses import asdict, is_dataclass

    def _to_dict(obj):
        if obj is None:
            return None
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, dict):
            return obj
        # 兜底：尝试 vars()（普通对象）
        return vars(obj) if hasattr(obj, "__dict__") else obj

    oauth1 = client.oauth1_token
    oauth2 = client.oauth2_token
    domain = getattr(client, "domain", "garmin.com")
    return json.dumps(
        {
            "oauth1": _to_dict(oauth1),
            "oauth2": _to_dict(oauth2),
            "domain": domain,
        },
        ensure_ascii=False,
    )


def _restore_garmin_token(client: Any, token_json: str) -> None:
    """从 JSON 还原 token 到给定的 garth.Client 实例。

    解析失败 / oauth1+oauth2 都为空 → 抛 GarminAdapterError（让上层 fallback 重登）。
    """
    from garth.auth_tokens import OAuth1Token, OAuth2Token

    try:
        data = json.loads(token_json)
        oauth1_dict = data.get("oauth1")
        oauth2_dict = data.get("oauth2")
        domain = data.get("domain") or "garmin.com"
        # oauth1 + oauth2 都为空视为无效 token（不能 resume）
        if not oauth1_dict or not oauth2_dict:
            raise GarminAdapterError(
                "佳明 token 不完整（缺 oauth1 或 oauth2）"
            )
        oauth1 = OAuth1Token(**oauth1_dict)
        oauth2 = OAuth2Token(**oauth2_dict)
    except GarminAdapterError:
        raise
    except Exception as exc:
        raise GarminAdapterError(f"佳明 token 解析失败：{exc}") from exc
    # 测试桩模式（FakeGarth）也支持 configure
    client.configure(oauth1_token=oauth1, oauth2_token=oauth2, domain=domain)


def _save_garmin_token_to_settings(
    session: Session, user_id: int, token_json: str
) -> None:
    """M3-1：将 token 加密存到 settings.garmin_token_store_enc（按用户）。"""
    from app.config import encrypt_value
    from app.models import Setting

    row = session.scalars(
        select(Setting).where(Setting.user_id == user_id)
    ).first()
    if row is None:
        row = Setting(user_id=user_id)
        session.add(row)
        session.flush()
    row.garmin_token_store_enc = encrypt_value(token_json)
    session.commit()


def _load_garmin_token_from_settings(
    session: Session, user_id: int
) -> str | None:
    """M3-1：从 settings.garmin_token_store_enc 按用户读取并解密 token JSON。"""
    from app.config import decrypt_value

    row = session.scalars(
        select(Setting).where(Setting.user_id == user_id)
    ).first()
    if row is None or not row.garmin_token_store_enc:
        return None
    try:
        return decrypt_value(row.garmin_token_store_enc)
    except Exception:
        return None


class GarminClient:
    """佳明客户端（garth 直连）。garth/sleep/time_fn 可注入以便测试。

    M3-1：构造函数收 user_id（kw-only），凭据按 user_id 从 settings 表读取。
    每个 GarminClient 持**自己的 garth.Client 实例**（避免模块级单例串 token），
    token 完全在内存流转，**不再写 ~/.garminconnect 目录**。
    """

    def __init__(
        self,
        session: Session,
        *,
        user_id: int | None = None,
        email: str | None = None,
        password: str | None = None,
        token_store: str | Any = None,  # noqa: ARG003  # M3-1: 已废弃，仅为向后兼容
        domain: str | None = None,
        garth: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._user_id = user_id

        # 凭据解析：参数 > settings 表(按 user_id) > 环境变量
        # 当显式传 email/password 时不查 settings（保持调用方预期）
        # 无论走哪条分支，都要保证 env_domain 有值（用于 domain fallback）
        _, _, env_domain = _resolve_garmin_credentials(session, user_id)
        if email is not None or password is not None:
            self._email = email
            self._password = password
        else:
            resolved_email, resolved_password, _ = _resolve_garmin_credentials(
                session, user_id
            )
            self._email = resolved_email
            self._password = resolved_password
        self._domain = domain or env_domain or "garmin.cn"

        if not self._email or not self._password:
            scope = f"用户 {user_id} " if user_id is not None else ""
            raise GarminKeyNotConfiguredError(
                f"{scope}GARMIN_EMAIL/GARMIN_PASSWORD 未配置"
                f"（settings 表与环境变量都没有）"
            )

        # M3-1：每个 client 自带 garth.Client 实例（避免全局单例串 token）
        # 测试时可注入桩模块（garth 参数）：桩实现 configure/login/connectapi 等接口
        if garth is not None:
            self._garth_mod_obj = garth
            self._client = garth  # FakeGarth 实现与 garth.Client 相同的接口
        else:
            # 生产路径：每个 client 一个 garth.Client 实例
            import garth as garth_mod
            from garth.http import Client as GarthClient
            self._garth_mod_obj = garth_mod
            self._client = GarthClient()
        self._sleep = sleep
        self._time = time_fn
        self._last_call: float | None = None
        self._logged_in = False
        self._display_name: str | None = None

    # ---------- 底层：garth 模块 / 登录 / 限速 / 异常包装 ----------

    def _garth_mod(self) -> Any:
        return self._garth_mod_obj

    def _garth_client(self) -> Any:
        """获取本 client 专属的 garth.Client 实例（生产路径）；测试桩时为 FakeGarth。"""
        return self._client

    def login(self) -> None:
        """登录：优先从 settings 表恢复 token（按 user_id）；失效/缺失时凭据重登并刷新 settings。

        M3-1：完全在内存流转，不写 ~/.garminconnect 目录。
        """
        if self._logged_in:
            return
        # 步骤 1：尝试从 settings 表恢复
        if self._user_id is not None:
            token_json = _load_garmin_token_from_settings(self._session, self._user_id)
            if token_json:
                try:
                    _restore_garmin_token(self._garth_client(), token_json)
                    self._logged_in = True
                    return
                except GarminAdapterError:
                    # 解析失败：fall through 到凭据重登
                    pass
        # 步骤 2：凭据重登
        self._relogin()

    def _relogin(self) -> None:
        """凭据全量登录 + 提取 token 加密存 settings 表（M3-1，**不写磁盘**）。"""
        g = self._garth_mod()
        try:
            client = self._garth_client()
            client.configure(domain=self._domain)
            client.login(self._email, self._password)
            # 提取 token 并加密存 settings
            if self._user_id is not None:
                token_json = _serialize_garmin_token(client)
                _save_garmin_token_to_settings(self._session, self._user_id, token_json)
        except GarminAdapterError:
            raise
        except Exception as exc:
            raise GarminAdapterError(f"佳明凭据重登失败：{exc}") from exc
        self._logged_in = True

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
                return self._garth_client().connectapi(path, params=params)
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
        if row is not None and row.excluded:
            # V3-11 墓碑：用户已删除该活动关联的训练，同步不再更新（防复活）
            return row
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

    def sync_all_activities(
        self,
        *,
        page_size: int = 100,
        start_offset: int = 0,
        skip_ids: set[str] | None = None,
        on_page: Callable[[int, int], None] | None = None,
    ) -> int:
        """全量活动列表分页拉取（V1-2 历史导入，PRD US-5 AC2）。

        - 每页 page_size 条（默认 100），页间间隔由全局限速保证 ≥0.5s；
        - start_offset：断点续传起始偏移（已完成页不再请求）；
        - skip_ids：已入库活动的 activity_id，跳过详情拉取（幂等）；
        - on_page(start, page_len)：每页处理完成后回调（用于进度落库）；
        - 返回本次新落库（含详情）的活动数。
        """
        skip_ids = skip_ids or set()
        start = start_offset
        total = 0
        while True:
            page = self._api(ACTIVITIES_PATH, params={"start": start, "limit": page_size}) or []
            for act in page:
                activity_id = str(act.get("activityId"))
                if activity_id in skip_ids:
                    continue
                details = self._api(
                    f"{ACTIVITY_PATH}/{activity_id}/details",
                    params={"maxChartSize": 2000, "maxPolylineSize": 4000},
                )
                try:
                    exercise_sets = self._api(f"{ACTIVITY_PATH}/{activity_id}/exerciseSets")
                except GarminAdapterError:
                    # 非力量训练活动可能无组次数据，忽略失败
                    exercise_sets = None
                self._upsert_activity(act, details, exercise_sets)
                total += 1
            self._session.commit()
            if on_page:
                on_page(start, len(page))
            if len(page) < page_size:
                break
            start += page_size
        return total

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

    # ---------- FIT/TCX 手动导入（降级通道，V2-4） ----------

    def import_fit_file(self, path: str) -> dict:
        """解析 FIT/TCX 文件落库 garmin_activity 并触发该日重匹配（无需登录）。"""
        return import_fit_file(self._session, path)

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


# ---------- FIT/TCX 文件导入（V2-4 降级通道，模块级函数，无需登录） ----------

# 佳明接口失效时的手动降级：用户从 Garmin Connect 导出 FIT/TCX 上传，
# 解析后按 garmin_activity 落库并触发当日重匹配，与在线拉取走同一融合管线。

BJ_TZ = timezone(timedelta(hours=8))

# TCX Sport 属性 → garmin_activity.activity_type（与佳明 API typeKey 对齐）
TCX_SPORT_MAP = {
    "strength": "strength_training",
    "running": "running",
    "biking": "cycling",
    "swimming": "swimming",
    "walking": "walking",
    "hiking": "hiking",
    "other": "other",
}


class FitImportError(Exception):
    """FIT/TCX 文件导入失败（格式不支持/文件损坏/内容为空）。"""


def _to_beijing_naive(dt: datetime) -> datetime:
    """UTC 时间转北京墙钟（naive），与佳明 startTimeLocal 的存储口径一致。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BJ_TZ).replace(tzinfo=None)


def _parse_iso_utc(raw: str) -> datetime:
    """解析 ISO8601 UTC 时间（如 '2026-08-05T10:00:00Z'）为带时区 datetime。"""
    return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两经纬度点的大圆距离（米），math 模块自实现（零新依赖）。"""
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def _parse_fit(path: Path) -> dict:
    """用 fitparse 解析 FIT：优先 session 消息，缺失时回退聚合 record 消息。"""
    try:
        import io

        from fitparse import FitFile

        # 读入内存再解析：损坏文件会在 FitFile 构造期抛错并泄漏文件句柄，
        # Windows 下会导致调用方无法删除临时文件
        blob = io.BytesIO(path.read_bytes())
        sessions = [m.get_values() for m in FitFile(blob, check_crc=False).get_messages("session")]
        if not sessions:
            records = [
                m.get_values()
                for m in FitFile(io.BytesIO(blob.getvalue()), check_crc=False).get_messages("record")
            ]
        else:
            records = []
    except FitImportError:
        raise
    except Exception as exc:
        raise FitImportError(f"FIT 文件解析失败：{exc}") from exc

    def _int(v):
        return int(v) if isinstance(v, (int, float)) else None

    if sessions:
        s = sessions[0]
        start = s.get("start_time")
        if start is None:
            raise FitImportError("FIT 文件缺少 start_time")
        duration = s.get("total_elapsed_time")
        sport = s.get("sub_sport") or s.get("sport")
        return {
            "activity_type": str(sport) if sport else None,
            "start_ts": _to_beijing_naive(start),
            "duration_s": _int(duration),
            "calories": _int(s.get("total_calories")),
            "avg_hr": _int(s.get("avg_heart_rate")),
            "max_hr": _int(s.get("max_heart_rate")),
        }
    if not records:
        raise FitImportError("FIT 文件不含 session/record 数据")
    times = [r["timestamp"] for r in records if r.get("timestamp")]
    hrs = [r["heart_rate"] for r in records if isinstance(r.get("heart_rate"), (int, float))]
    if not times:
        raise FitImportError("FIT 文件缺少时间戳")
    start, end = min(times), max(times)
    return {
        "activity_type": None,
        "start_ts": _to_beijing_naive(start),
        "duration_s": _int((end - start).total_seconds()),
        "calories": None,
        "avg_hr": _int(sum(hrs) / len(hrs)) if hrs else None,
        "max_hr": _int(max(hrs)) if hrs else None,
    }


def _parse_tcx(path: Path) -> dict:
    """用标准库 XML 解析 TCX（TrainingCenterDatabase v2），聚合所有 Lap。"""
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise FitImportError(f"TCX 文件解析失败：{exc}") from exc
    ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
    activity = root.find(".//t:Activities/t:Activity", ns)
    if activity is None:
        raise FitImportError("TCX 文件不含 Activity")
    laps = activity.findall("t:Lap", ns)
    if not laps:
        raise FitImportError("TCX 文件不含 Lap")

    def _int(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    def _float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _lap_hr(lap, tag):
        # 标准结构是 <tag><Value>n</Value></tag>；小米导出为裸值 <tag>n</tag>（V3-11）
        node = lap.find(f"t:{tag}/t:Value", ns)
        if node is None:
            node = lap.find(f"t:{tag}", ns)
        return _int(node.text) if node is not None else None

    def _lap_avg_hr(lap):
        # avg 回退链（V3-11b）：AverageHeartRateBpm/Value → AverageHeartRateBpm 裸值
        # → HeartRateBpm/Value → HeartRateBpm 裸值（小米 Lap 级无 Average 前缀）
        v = _lap_hr(lap, "AverageHeartRateBpm")
        if v is None:
            v = _lap_hr(lap, "HeartRateBpm")
        return v

    # StartTime 回退链（V3-11）：Lap@StartTime → Activity/Id（小米是 ISO 时间戳）
    # → 首个 Trackpoint/Time，三者皆无才报错
    start_raw = laps[0].get("StartTime")
    if not start_raw:
        start_raw = (activity.findtext("t:Id", default="", namespaces=ns) or "").strip() or None
    if start_raw:
        try:
            start = _to_beijing_naive(_parse_iso_utc(start_raw))
        except ValueError:
            start = None
    else:
        start = None
    if start is None:
        tp_time = activity.find(".//t:Trackpoint/t:Time", ns)
        if tp_time is not None and tp_time.text and tp_time.text.strip():
            start = _to_beijing_naive(_parse_iso_utc(tp_time.text))
    if start is None:
        raise FitImportError(
            "TCX 文件缺少开始时间（Lap@StartTime / Activity/Id / Trackpoint/Time 均无）"
        )
    duration = sum(_int(lap.findtext("t:TotalTimeSeconds", default="0", namespaces=ns)) or 0 for lap in laps)
    calories = sum(_int(lap.findtext("t:Calories", default="0", namespaces=ns)) or 0 for lap in laps)
    distance = sum(_float(lap.findtext("t:DistanceMeters", default="0", namespaces=ns)) or 0.0 for lap in laps)
    avg_hrs = [v for v in (_lap_avg_hr(lap) for lap in laps) if v]
    max_hrs = [v for v in (_lap_hr(lap, "MaximumHeartRateBpm") for lap in laps) if v]
    sport_raw = (activity.get("Sport") or "").strip().lower()
    return {
        "activity_type": TCX_SPORT_MAP.get(sport_raw, sport_raw or None),
        "start_ts": start,
        "duration_s": duration or None,
        "distance_m": round(distance, 1) if distance else None,
        "calories": calories or None,
        "avg_hr": round(sum(avg_hrs) / len(avg_hrs)) if avg_hrs else None,
        "max_hr": max(max_hrs) if max_hrs else None,
    }


# ---------- GPX/KML 解析（V3-7，stdlib ElementTree，零新依赖） ----------

# GPX 命名空间：兼容 1.1 与 1.0。XML 命名空间是大小写敏感的 URI，官方为大写 GPX；
# 小写形式是非官方写法，仅作兜底候选（V3-10c：曾误写成小写导致真实文件 422）。
GPX_NAMESPACES = (
    "http://www.topografix.com/GPX/1/1",
    "http://www.topografix.com/GPX/1/0",
    "http://www.topografix.com/gpx/1/1",
    "http://www.topografix.com/gpx/1/0",
)
# 佳明心率扩展命名空间（gpxtpx:TrackPointExtension/gpxtpx:hr）
GPXTPX_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
# KML 2.2 与 Google 轨迹扩展
KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"


def _summarize_track(
    points: list[tuple], *, activity_name, activity_type, distance_m_override=None
) -> dict:
    """轨迹点列表 [(lat, lon, dt, hr|None)] → 与 _parse_tcx 同构的归一化 dict。

    缺失字段一律给 None；distance_m 优先取 distance_m_override（如 GPX totalDistance），
    无则用 haversine 逐点累加。
    """
    times = [p[2] for p in points if p[2] is not None]
    if not times:
        raise FitImportError("文件缺少时间戳，无法确定运动时间")
    hrs = [p[3] for p in points if isinstance(p[3], (int, float))]
    coords = [(p[0], p[1]) for p in points if p[0] is not None and p[1] is not None]
    distance_m = None
    if distance_m_override is not None:
        distance_m = round(distance_m_override, 1)
    elif len(coords) >= 2:
        distance_m = round(
            sum(_haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:])),
            1,
        )
    start, end = min(times), max(times)
    return {
        "activity_name": activity_name,
        "activity_type": activity_type or "other",
        "start_ts": _to_beijing_naive(start),
        "duration_s": int((end - start).total_seconds()) or None,
        "distance_m": distance_m,
        "calories": None,
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "max_hr": max(hrs) if hrs else None,
    }


def _local_name(tag: str) -> str:
    """XML tag 的 local-name（去掉 {namespace} 前缀），用于命名空间兜底的野路子导出器。"""
    return tag.rsplit("}", 1)[-1]


def _find_by_local(scope, name: str):
    """在 scope 子树（含自身）按 local-name 找第一个匹配元素，无则 None。"""
    for el in scope.iter():
        if _local_name(el.tag) == name:
            return el
    return None


def _parse_gpx(path: Path) -> dict:
    """用标准库 XML 解析 GPX（兼容 1.1/1.0 命名空间），聚合所有 trkpt。

    心率取 gpxtpx:TrackPointExtension/gpxtpx:hr，无则 None；
    运动类型取 trk 下 type/name，无则 'other'；
    trk/extensions/totalDistance 存在时直接采用为 distance_m（小米导出带此字段），
    无则 haversine 逐点累加；命名空间全不匹配时按 local-name 兜底匹配。
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise FitImportError(f"GPX 文件解析失败：{exc}") from exc

    trk = ns = None
    for candidate in GPX_NAMESPACES:
        trk = root.find(f".//{{{candidate}}}trk")
        if trk is not None:
            ns = candidate
            break
    if trk is None:
        # 命名空间全不匹配（野路子导出器自定义 URI）→ 按 local-name 兜底
        trk = _find_by_local(root, "trk")
    if trk is None:
        raise FitImportError("GPX 文件不含轨迹（trk）")

    def _int(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    def _float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if ns is not None:
        pt_nodes = trk.findall(f".//{{{ns}}}trkpt")

        def _find_time(pt):
            return pt.find(f"{{{ns}}}time")

        name_raw = trk.findtext(f"{{{ns}}}name")
        type_raw = (trk.findtext(f"{{{ns}}}type") or "").strip()
        dist_node = trk.find(f".//{{{ns}}}totalDistance")
    else:
        pt_nodes = [el for el in trk.iter() if _local_name(el.tag) == "trkpt"]

        def _find_time(pt):
            return _find_by_local(pt, "time")

        name_node = _find_by_local(trk, "name")
        name_raw = name_node.text if name_node is not None else None
        type_node = _find_by_local(trk, "type")
        type_raw = ((type_node.text if type_node is not None else None) or "").strip()
        dist_node = None
    if dist_node is None:
        # totalDistance 可能挂在 trk/extensions 且命名空间不一致，统一再兜底一次
        dist_node = _find_by_local(trk, "totalDistance")
    total_distance = _float(dist_node.text) if dist_node is not None else None

    points = []
    for pt in pt_nodes:
        time_node = _find_time(pt)
        dt = _parse_iso_utc(time_node.text) if time_node is not None and time_node.text else None
        hr_node = pt.find(f".//{{{GPXTPX_NS}}}hr")
        points.append((
            _float(pt.get("lat")),
            _float(pt.get("lon")),
            dt,
            _int(hr_node.text) if hr_node is not None else None,
        ))
    if not points:
        raise FitImportError("GPX 文件不含轨迹点（trkpt）")

    name = (name_raw or "").strip() or None
    if name is None:
        # 小米 1.0 风格：<name> 挂在 gpx 根节点而非 trk 下（V3-11）
        if ns is not None:
            root_name = root.findtext(f"{{{ns}}}name")
        else:
            root_name_node = _find_by_local(root, "name")
            root_name = root_name_node.text if root_name_node is not None else None
        name = (root_name or "").strip() or None
    return _summarize_track(
        points, activity_name=name, activity_type=type_raw or name,
        distance_m_override=total_distance,
    )


def _parse_kml(path: Path) -> dict:
    """用标准库 XML 解析 KML 2.2：优先 gx:Track（<when> 与 <gx:coord> 一一对应）。

    仅 LineString（无时间戳）时无法确定运动日期，直接报错提示；
    KML 一般无心率/类型，相应字段 None，activity_type 默认 'other'。
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise FitImportError(f"KML 文件解析失败：{exc}") from exc

    ns = {"k": KML_NS, "gx": GX_NS}
    track = root.find(".//gx:Track", ns)
    if track is None:
        if root.find(".//k:LineString", ns) is not None:
            raise FitImportError("该 KML 缺少时间信息，请导出含 gx:Track 的版本")
        raise FitImportError("KML 文件不含轨迹（gx:Track）")

    whens = [w.text.strip() for w in track.findall("k:when", ns) if w.text and w.text.strip()]
    coords = []
    for c in track.findall("gx:coord", ns):
        parts = (c.text or "").split()  # gx:coord 固定 "lon lat ele"
        if len(parts) >= 2:
            try:
                coords.append((float(parts[1]), float(parts[0])))
            except ValueError:
                continue
    points = [
        (lat, lon, _parse_iso_utc(whens[i]), None)
        for i, (lat, lon) in enumerate(coords)
        if i < len(whens)
    ]
    if not points:
        raise FitImportError("该 KML 缺少时间信息，请导出含 gx:Track 的版本")

    name = None
    for pm in root.findall(".//k:Placemark", ns):
        if pm.find(".//gx:Track", ns) is not None:
            name = (pm.findtext("k:name", default="", namespaces=ns) or "").strip() or None
            break
    if name is None:
        # 回退根节点名称：Document/name 优先，其次 kml/name（V3-11）
        for candidate in ("k:Document/k:name", "k:name"):
            text = root.findtext(candidate, default="", namespaces=ns)
            name = (text or "").strip() or None
            if name:
                break
    return _summarize_track(points, activity_name=name, activity_type=None)


def parse_activity_file(path: str | Path) -> dict:
    """解析 FIT/TCX/GPX/KML 文件为统一 dict（activity_type/start_ts/duration_s/calories/avg_hr/max_hr）。"""
    path = Path(path)
    if not path.is_file():
        raise FitImportError(f"文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix == ".fit":
        parsed = _parse_fit(path)
        parsed["format"] = "fit"
    elif suffix == ".tcx":
        parsed = _parse_tcx(path)
        parsed["format"] = "tcx"
    elif suffix == ".gpx":
        parsed = _parse_gpx(path)
        parsed["format"] = "gpx"
    elif suffix == ".kml":
        parsed = _parse_kml(path)
        parsed["format"] = "kml"
    else:
        raise FitImportError(f"不支持的文件类型：{suffix or '(无后缀)'}（仅支持 .fit / .tcx / .gpx / .kml）")
    if parsed.get("start_ts") is None:
        raise FitImportError("文件缺少开始时间，无法入库")
    return parsed


def import_fit_file(session: Session, path: str | Path, *, match_fn=None,
                    user_id: int | None = None) -> dict:
    """FIT/TCX 手动导入降级通道：解析 → 按内容哈希 upsert garmin_activity → 触发该日重匹配。

    - activity_id 取文件内容哈希（file_<sha256[:16]>），同一文件重复导入幂等；
    - match_fn 可注入（默认 services.matcher.match_day），仅当解析出日期时触发；
    - 返回 {"activity": GarminActivity, "match": match_fn 结果或 None}。
    """
    import hashlib

    path = Path(path)
    parsed = parse_activity_file(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    activity_id = f"file_{digest}"

    stmt = select(GarminActivity).where(GarminActivity.activity_id == activity_id)
    row = session.scalars(stmt).first()
    if row is not None and row.excluded:
        # V3-11 墓碑：同一文件重复导入不更新、不触发重匹配（防复活）
        return {"activity": row, "match": None}
    if row is None:
        row = GarminActivity(activity_id=activity_id, user_id=user_id)
        session.add(row)
    row.activity_type = parsed.get("activity_type")
    row.name = row.name or parsed.get("activity_name") or f"{path.stem}（文件导入）"
    row.start_ts = parsed["start_ts"]
    duration_s = parsed.get("duration_s")
    row.duration_s = duration_s
    row.end_ts = row.start_ts + timedelta(seconds=duration_s) if duration_s else None
    row.calories = parsed.get("calories")
    row.avg_hr = parsed.get("avg_hr")
    row.max_hr = parsed.get("max_hr")
    row.raw_json = json.dumps(
        {"source": "file_import", "format": parsed["format"],
         "filename": path.name, "parsed": parsed},
        ensure_ascii=False, default=str,
    )
    row.fetched_at = datetime.now()
    session.commit()

    if match_fn is None:
        from app.services.matcher import match_day
        match_fn = match_day
    match_result = match_fn(session, row.start_ts.date(), user_id=user_id)
    return {"activity": row, "match": match_result}
