"""Garmin Workout 写入适配器（garminconnect 0.3.20，中国区）。

本模块故意不依赖 SQLAlchemy，便于用独立 Python 3.12 环境做真实验收。
所有 POST 均禁止自动重试；只有幂等 GET/PUT 在认证或限流失败后最多恢复一次。
异常只暴露操作名、异常类型和 HTTP 状态，绝不拼接远端原始响应。
"""
from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable


class GarminWorkoutAdapterError(RuntimeError):
    """可供同步状态机持久化的脱敏 Garmin 错误。"""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        operation: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.public_message = message
        self.operation = operation
        self.status_code = status_code


class _MFARequired(RuntimeError):
    pass


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _source_marker(payload: dict[str, Any], key: str) -> str | None:
    for part in str(payload.get("description") or "").split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == key:
            return value
    return None


class GarminWorkoutAdapter:
    """训练模板和日程的窄接口；client/sleep/clock 可注入以便零外呼测试。"""

    def __init__(
        self,
        *,
        email: str | None = None,
        password: str | None = None,
        tokenstore: str | os.PathLike[str] | None = None,
        is_cn: bool = True,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        min_interval: float = 0.5,
    ) -> None:
        self._sleep = sleep
        self._monotonic = monotonic
        self._min_interval = min_interval
        self._last_request_at: float | None = None
        self._tokenstore = str(tokenstore) if tokenstore is not None else None
        self._client = client or self._login(
            client_factory=client_factory,
            email=email if email is not None else os.getenv("GARMIN_EMAIL", ""),
            password=password if password is not None else os.getenv("GARMIN_PASSWORD", ""),
            is_cn=is_cn,
        )

    @classmethod
    def from_settings(cls, settings: Any) -> "GarminWorkoutAdapter":
        root = Path(__file__).resolve().parents[3]
        tokenstore = os.getenv(
            "GARMIN_WORKOUT_TOKENSTORE",
            str(root / "outputs" / "garmin_p1" / "tokens"),
        )
        return cls(
            email=settings.garmin_email,
            password=settings.garmin_password,
            tokenstore=tokenstore,
            is_cn=settings.garmin_domain == "garmin.cn",
        )

    def _login(
        self,
        *,
        client_factory: Callable[..., Any] | None = None,
        email: str | None = None,
        password: str | None = None,
        is_cn: bool = True,
    ) -> Any:
        if client_factory is None:
            try:
                from garminconnect import Garmin
            except ImportError as exc:
                raise GarminWorkoutAdapterError(
                    "GARMIN_DEPENDENCY_MISSING",
                    "Garmin 写入需要 Python 3.12 和 garminconnect==0.3.20",
                    operation="login",
                ) from exc
            client_factory = Garmin
        if self._tokenstore:
            Path(self._tokenstore).parent.mkdir(parents=True, exist_ok=True)

        def reject_mfa() -> str:
            raise _MFARequired()

        try:
            client = client_factory(
                email,
                password,
                is_cn=is_cn,
                # prompt_mfa 抛错即停止；正常登录可继续完成 token 持久化。
                prompt_mfa=reject_mfa,
                return_on_mfa=False,
                # 禁用库内网络/5xx 自动重试，尤其是结果不确定的创建 POST。
                retry_attempts=0,
            )
            status, _ = client.login(tokenstore=self._tokenstore)
            if status == "needs_mfa":
                raise _MFARequired()
            return client
        except _MFARequired as exc:
            raise GarminWorkoutAdapterError(
                "GARMIN_MFA_REQUIRED",
                "Garmin 要求 MFA，请账号所有者完成验证后再恢复同步",
                operation="login",
            ) from exc
        except GarminWorkoutAdapterError:
            raise
        except Exception as exc:
            raise self._error("login", exc) from exc

    @staticmethod
    def _error(operation: str, exc: BaseException) -> GarminWorkoutAdapterError:
        status = _status_code(exc)
        if status in {401, 403}:
            code = "GARMIN_AUTH_REQUIRED"
            message = f"Garmin 认证失败：{operation}（HTTP {status}）"
        elif status == 429:
            code = "GARMIN_RATE_LIMITED"
            message = f"Garmin 请求受限：{operation}（HTTP 429）"
        else:
            code = "GARMIN_REQUEST_FAILED"
            suffix = f"，HTTP {status}" if status is not None else ""
            message = f"Garmin 请求失败：{operation}（{type(exc).__name__}{suffix}）"
        return GarminWorkoutAdapterError(
            code, message, operation=operation, status_code=status
        )

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_interval - (self._monotonic() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _call(
        self,
        operation: str,
        request: Callable[[], Any],
        *,
        retryable: bool,
    ) -> Any:
        for attempt in range(2 if retryable else 1):
            self._throttle()
            try:
                return request()
            except Exception as exc:
                status = _status_code(exc)
                recoverable = status in {401, 403, 429}
                if not retryable or not recoverable or attempt > 0:
                    if isinstance(exc, GarminWorkoutAdapterError):
                        raise
                    raise self._error(operation, exc) from exc
                if status in {401, 403}:
                    # 新版库会优先刷新/恢复 token；仍失败则由外层进入 failed。
                    self._client.login(tokenstore=self._tokenstore)
                else:
                    self._sleep(1.0)
        raise AssertionError("unreachable")

    @staticmethod
    def _required_id(payload: Any, key: str, operation: str) -> str:
        value = payload.get(key) if isinstance(payload, dict) else None
        if value is None or str(value).strip() == "":
            raise GarminWorkoutAdapterError(
                "GARMIN_INVALID_RESPONSE",
                f"Garmin 响应缺少 {key}：{operation}",
                operation=operation,
            )
        return str(value)

    def create_workout(self, payload: dict[str, Any]) -> str:
        result = self._call(
            "create_workout", lambda: self._client.upload_workout(payload), retryable=False
        )
        return self._required_id(result, "workoutId", "create_workout")

    def get_workout(self, workout_id: str) -> dict[str, Any]:
        return self._call(
            "get_workout",
            lambda: self._client.get_workout_by_id(workout_id),
            retryable=True,
        )

    def update_workout(self, workout_id: str, payload: dict[str, Any]) -> None:
        self._call(
            "update_workout",
            lambda: self._client.update_workout(workout_id, payload),
            retryable=True,
        )

    def schedule_workout(self, workout_id: str, training_date: date | str) -> str:
        day = training_date.isoformat() if isinstance(training_date, date) else training_date
        result = self._call(
            "schedule_workout",
            lambda: self._client.schedule_workout(workout_id, day),
            retryable=False,
        )
        return self._required_id(result, "workoutScheduleId", "schedule_workout")

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._call(
            "get_schedule",
            lambda: self._client.get_scheduled_workout_by_id(schedule_id),
            retryable=True,
        )

    def reschedule_schedule(
        self, schedule_id: str, training_date: date | str
    ) -> None:
        """原地改期；garminconnect 回读完整日程后仅替换 calendarDate。"""
        day = training_date.isoformat() if isinstance(training_date, date) else training_date
        self._call(
            "reschedule_schedule",
            lambda: self._client.reschedule_workout(schedule_id, day),
            retryable=True,
        )

    def find_schedules(
        self, workout_id: str, training_date: date | str
    ) -> list[dict[str, Any]]:
        """创建日程前按训练 ID+日期对账，覆盖上次 POST 成功但响应丢失的恢复。"""
        day = training_date.isoformat() if isinstance(training_date, date) else training_date
        result = self._call(
            "find_schedules",
            lambda: self._client.get_scheduled_workouts_by_period(day, day),
            retryable=True,
        )
        rows = result if isinstance(result, list) else []
        return [
            row
            for row in rows
            if str((row.get("workout") or {}).get("workoutId") or row.get("workoutId") or "")
            == str(workout_id)
            and row.get("calendarDate") == day
        ]

    def find_workouts_by_source_key(self, source_key: str) -> list[dict[str, Any]]:
        """分页精确匹配 description 中的 source_key，不做模糊名称猜测。"""
        matches: list[dict[str, Any]] = []
        page_size = 100
        for page in range(100):
            rows = self._call(
                "find_workouts_by_source_key",
                lambda start=page * page_size: self._client.get_workouts(
                    start=start, limit=page_size
                ),
                retryable=True,
            )
            if not isinstance(rows, list):
                raise GarminWorkoutAdapterError(
                    "GARMIN_INVALID_RESPONSE",
                    "Garmin 训练列表响应格式无效",
                    operation="find_workouts_by_source_key",
                )
            matches.extend(
                row
                for row in rows
                if isinstance(row, dict) and _source_marker(row, "source_key") == source_key
            )
            if len(rows) < page_size:
                break
        return matches


__all__ = ["GarminWorkoutAdapter", "GarminWorkoutAdapterError"]
