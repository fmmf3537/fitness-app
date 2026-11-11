"""Garmin Workout 写入适配器（garminconnect 0.3.20，中国区）。

本模块故意不依赖 SQLAlchemy，便于用独立 Python 3.12 环境做真实验收。
所有 POST 均禁止自动重试；只有幂等 GET/PUT 在认证或限流失败后最多恢复一次。
异常只暴露操作名、异常类型和 HTTP 状态，绝不拼接远端原始响应。

中国区认证兜底（V5-9）：
garminconnect 0.3.20 的 SSO 认证 URL 硬编码在 garmin.com（上游 issue #365，
PR #366 尚未合并），`is_cn=True` 只影响数据 API 的 domain，不影响登录。
因此中国区账号用密码登录必然 401（"Invalid Username or Password"）。
garth 支持 `configure(domain='garmin.cn')`，本模块在密码登录遇 401/403 时用
garth 建立会话，把 oauth2 token 转成 garminconnect 的 tokenstore 格式
（di_token / di_refresh_token / di_client_id），再重试一次 tokenstore 登录。
只兜底一次，不循环登录；token 落盘后后续进程直接复用。
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

# garth 会话目录（与 adapters/garmin_adapter.py 的 DEFAULT_TOKEN_STORE 一致）
GARTH_TOKEN_STORE = Path.home() / ".garminconnect"


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


def _is_auth_failure(exc: BaseException) -> bool:
    """判断是否属于「认证失败」——中国区兜底的触发条件。

    garminconnect 的 `GarminConnectAuthenticationError` 通常**不带** status_code
    属性（消息里才有 "401 Unauthorized"），因此不能只看 `_status_code`。
    """
    if _status_code(exc) in {401, 403}:
        return True
    # 按类名判断：GarminConnectAuthenticationError / AuthenticationError 等
    for klass in type(exc).__mro__:
        if "authentication" in klass.__name__.lower():
            return True
    # 兜底：消息里明确出现 401/403（不匹配泛化的 "40x"）
    text = str(exc)
    return "401" in text or "403" in text


def _jwt_claim(token: str | None, claim: str) -> str | None:
    """读取 JWT payload 的单个声明（不验签，仅用于取 client_id）。"""
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, TypeError):
        return None
    value = data.get(claim) if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


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
        garth: Any = None,
        garth_token_store: str | os.PathLike[str] | None = None,
    ) -> None:
        self._sleep = sleep
        self._monotonic = monotonic
        self._min_interval = min_interval
        self._last_request_at: float | None = None
        self._tokenstore = str(tokenstore) if tokenstore is not None else None
        # 中国区认证兜底用：garth 模块与 garth 会话目录均可注入以便零外呼测试。
        self._garth = garth
        self._garth_token_store = (
            Path(garth_token_store) if garth_token_store is not None else GARTH_TOKEN_STORE
        )
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
            # 中国区兜底：密码登录认证失败时改用 garth 会话引导 tokenstore，
            # 之后再用 tokenstore 重试。两阶段，最多各一次，不循环：
            #   A：复用 garth 缓存会话（必要时 refresh）
            #   B：A 产出的 token 仍被 API 拒绝时，强制 garth 凭据重登一次再写
            if is_cn and _is_auth_failure(exc):
                return self._login_via_garth_bootstrap(
                    client_factory=client_factory,
                    email=email,
                    password=password,
                    is_cn=is_cn,
                    reject_mfa=reject_mfa,
                    original_exc=exc,
                )
            raise self._error("login", exc) from exc

    def _login_via_garth_bootstrap(
        self,
        *,
        client_factory: Callable[..., Any],
        email: str | None,
        password: str | None,
        is_cn: bool,
        reject_mfa: Callable[[], str],
        original_exc: BaseException,
    ) -> Any:
        """中国区认证兜底：garth 引导 tokenstore 后重试 garminconnect 登录。

        - 阶段 A：复用 garth 缓存会话（过期则 refresh），写 tokenstore 后重试。
        - 阶段 B：A 的 token 仍被 API 拒绝（如 "Failed to retrieve social profile"）
          且具备凭据时，强制 garth 凭据登录一次，重写 tokenstore 后最后重试。
        两阶段各自最多一次，总登录尝试不超过「一次刷新技术 + 一次凭据登录」。
        """
        bootstrap_error: str | None = None
        for phase in ("cached", "relogin"):
            if phase == "relogin":
                if not email or not password:
                    break  # 无凭据，无法强制重登
                if bootstrap_error is not None:
                    break  # 阶段 A 本身就没成功，重登也无基础
            err = self._bootstrap_tokenstore_from_garth(
                email=email,
                password=password,
                is_cn=is_cn,
                force_login=(phase == "relogin"),
            )
            if err is not None:
                bootstrap_error = err
                if phase == "cached":
                    continue  # 让阶段 B 用凭据再试一次
                break
            bootstrap_error = None
            try:
                client = client_factory(
                    email,
                    password,
                    is_cn=is_cn,
                    prompt_mfa=reject_mfa,
                    return_on_mfa=False,
                    retry_attempts=0,
                )
                status, _ = client.login(tokenstore=self._tokenstore)
                if status == "needs_mfa":
                    raise _MFARequired()
                return client
            except _MFARequired as mfa_exc:
                raise GarminWorkoutAdapterError(
                    "GARMIN_MFA_REQUIRED",
                    "Garmin 要求 MFA，请账号所有者完成验证后再恢复同步",
                    operation="login",
                ) from mfa_exc
            except Exception as retry_exc:  # noqa: BLE001
                if phase == "cached" and _is_auth_failure(retry_exc):
                    continue  # 缓存 token 不被接受 → 走阶段 B 强制重登
                raise self._bootstrap_failed_error(
                    retry_exc, bootstrap_error=None
                ) from retry_exc
        raise self._bootstrap_failed_error(
            original_exc, bootstrap_error=bootstrap_error or "garth 引导未产出可用 token"
        ) from original_exc

    def _bootstrap_failed_error(
        self, exc: BaseException, *, bootstrap_error: str | None
    ) -> GarminWorkoutAdapterError:
        """中国区兜底也失败时的脱敏错误（不暴露 token/密码/远端响应）。"""
        base = self._error("login", exc)
        detail = base.public_message
        if bootstrap_error:
            detail = f"{detail}；garth 引导失败（{bootstrap_error}）"
        return GarminWorkoutAdapterError(
            base.error_code,
            detail,
            operation=base.operation,
            status_code=base.status_code,
        )

    def _bootstrap_tokenstore_from_garth(
        self,
        *,
        email: str | None,
        password: str | None,
        is_cn: bool,
        force_login: bool = False,
    ) -> str | None:
        """用 garth 建立中国区会话，写入 garminconnect tokenstore。

        返回 None 表示成功；返回字符串表示失败原因（脱敏，可直接进错误信息）。

        `force_login=True` 时跳过缓存，直接用凭据重登一次——用于「缓存 token 看起来
        有效但被 API 拒绝」（garminconnect 报 Failed to retrieve social profile）的场景。
        无论哪种模式，登录/刷新各最多一次，不做循环。
        """
        if not self._tokenstore:
            return "未配置 tokenstore"
        try:
            garth_mod = self._garth_module()
        except Exception as exc:  # noqa: BLE001 - 依赖缺失只报告类型
            return f"garth 不可用（{type(exc).__name__}）"

        domain = "garmin.cn" if is_cn else "garmin.com"
        try:
            garth_mod.configure(domain=domain)
        except Exception as exc:  # noqa: BLE001
            return f"garth configure 失败（{type(exc).__name__}）"

        resumed = False
        if not force_login:
            try:
                garth_mod.resume(str(self._garth_token_store))
                resumed = True
            except Exception:  # noqa: BLE001 - 缓存缺失/失效都转凭据登录
                resumed = False

        if resumed and self._garth_token_usable(garth_mod):
            pass  # 缓存里的 token 仍有效，直接用
        else:
            refreshed = False
            if resumed:
                refreshed = self._garth_refresh(garth_mod)
            if not refreshed:
                if not email or not password:
                    reason = "garth token 已过期" if resumed else "无可用 garth 会话"
                    return f"{reason}且缺少 GARMIN_EMAIL/GARMIN_PASSWORD"
                try:
                    garth_mod.login(email, password)
                except Exception as exc:  # noqa: BLE001
                    return f"garth 登录失败（{type(exc).__name__}）"

        oauth2 = getattr(getattr(garth_mod, "client", None), "oauth2_token", None)
        access_token = getattr(oauth2, "access_token", None)
        refresh_token = getattr(oauth2, "refresh_token", None)
        client_id = _jwt_claim(access_token, "client_id")
        if not access_token or not refresh_token or not client_id:
            return "garth 会话缺少 access_token/refresh_token/client_id"

        store = {
            "di_token": access_token,
            "di_refresh_token": refresh_token,
            "di_client_id": client_id,
        }
        try:
            self._write_tokenstore(store)
            garth_mod.save(str(self._garth_token_store))
        except Exception as exc:  # noqa: BLE001
            return f"tokenstore 写入失败（{type(exc).__name__}）"
        return None

    def _garth_module(self) -> Any:
        """惰性加载 garth（测试可注入 self._garth）。"""
        if self._garth is None:
            import garth as garth_module

            self._garth = garth_module
        return self._garth

    # token 提前刷新的安全余量（秒）：避免「刚转换完就过期」
    TOKEN_REFRESH_SKEW_S = 120

    def _garth_token_usable(self, garth_mod: Any) -> bool:
        """garth 当前 oauth2 token 是否足够新鲜（不存在视为不可用）。"""
        oauth2 = getattr(getattr(garth_mod, "client", None), "oauth2_token", None)
        token = getattr(oauth2, "access_token", None)
        if not token:
            return False
        expires_at = getattr(oauth2, "expires_at", None)
        if not isinstance(expires_at, (int, float)):
            return True  # 无过期信息时按可用处理，交给 API 判定
        return float(expires_at) > time.time() + self.TOKEN_REFRESH_SKEW_S

    def _garth_refresh(self, garth_mod: Any) -> bool:
        """用 refresh_token 换新 access_token；成功返回 True（失败不抛）。"""
        refresh = getattr(getattr(garth_mod, "client", None), "refresh_oauth2", None)
        if not callable(refresh):
            return False
        try:
            refresh()
        except Exception:  # noqa: BLE001 - 刷新失败转凭据登录
            return False
        return self._garth_token_usable(garth_mod)

    def _write_tokenstore(self, store: dict[str, str]) -> None:
        """把 tokenstore 写到 `self._tokenstore`（目录则补 garmin_tokens.json）。

        与 garminconnect 的 `token_file_path` 语义一致：目录 → 目录内
        `garmin_tokens.json`；以 `.json` 结尾 → 视为文件本身。
        权限收紧到 0600（仅属主可读写）。
        """
        target = Path(self._tokenstore)
        if target.suffix.casefold() != ".json":
            target = target / "garmin_tokens.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(store), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # Windows 无 POSIX 权限位，忽略
            pass
        os.replace(tmp, target)

    @staticmethod
    def _error(operation: str, exc: BaseException) -> GarminWorkoutAdapterError:
        status = _status_code(exc)
        # 认证类异常即使没有 status_code（garminconnect 的
        # GarminConnectAuthenticationError 只在消息里带 401）也归为 AUTH_REQUIRED，
        # 否则会被误报成 GARMIN_REQUEST_FAILED，掩盖真实原因。
        if _is_auth_failure(exc):
            code = "GARMIN_AUTH_REQUIRED"
            suffix = f"HTTP {status}" if status is not None else type(exc).__name__
            message = f"Garmin 认证失败：{operation}（{suffix}）"
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
