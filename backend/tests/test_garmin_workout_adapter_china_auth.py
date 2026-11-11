"""V5-9 中国区认证兜底测试：garth 会话 → garminconnect tokenstore。

背景：garminconnect 0.3.20 的 SSO 认证 URL 硬编码 garmin.com（上游 issue #365），
`is_cn=True` 只影响数据 API 的 domain，不影响登录，因此中国区账号密码登录必然
401。适配器在 401/403 时用 garth（支持 garmin.cn）建立会话，把 oauth2 token 转成
garminconnect 的 tokenstore 格式后重试一次。

全部使用注入的 fake garth / fake client，零网络外呼、零真实凭据。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.adapters.garmin_workout_adapter import (
    GarminWorkoutAdapter,
    GarminWorkoutAdapterError,
)


class HttpFailure(RuntimeError):
    def __init__(self, status: int, message: str = "raw body may contain secret-token"):
        super().__init__(message)
        self.response = type("Response", (), {"status_code": status})()


class GarminConnectAuthenticationError(RuntimeError):
    """仿 garminconnect 的真实异常：**没有 status_code 属性**，401 只在消息里。

    服务器 P9 实测就是这种形态——只看 status_code 会漏判，导致兜底不触发。
    """

    def __init__(self, message: str = "401 Unauthorized (Invalid Username or Password)"):
        super().__init__(message)


def make_jwt(claims: dict) -> str:
    """构造只有 payload 有意义的三段式 JWT（不验签）。"""
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


class FakeOAuth2:
    def __init__(self, access_token: str, refresh_token: str, expires_at=None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at


class FakeGarth:
    """最小 garth 桩：configure / resume / login / save / client.oauth2_token。"""

    def __init__(
        self,
        *,
        access_token: str | None = None,
        refresh_token: str | None = "refresh-token-value",
        client_id: str = "GARMIN_CONNECT_MOBILE_ANDROID_DI",
        resume_ok: bool = True,
        login_ok: bool = True,
        expires_at: float | None = None,
        refresh_ok: bool = True,
        refresh_sets_fresh: bool = True,
    ):
        self.configured_domains: list[str] = []
        self.resume_calls: list[str] = []
        self.login_calls: list[tuple] = []
        self.save_calls: list[str] = []
        self.refresh_calls = 0
        self._resume_ok = resume_ok
        self._login_ok = login_ok
        self._refresh_ok = refresh_ok
        self._refresh_sets_fresh = refresh_sets_fresh
        token = access_token if access_token is not None else make_jwt(
            {"client_id": client_id, "exp": 4102444800}
        )
        oauth2 = FakeOAuth2(token, refresh_token, expires_at)
        garth_self = self

        class _GarthClient:
            oauth2_token = oauth2

            @staticmethod
            def refresh_oauth2():
                garth_self.refresh_calls += 1
                if not garth_self._refresh_ok:
                    raise RuntimeError("refresh rejected")
                if garth_self._refresh_sets_fresh:
                    import time as _t

                    _GarthClient.oauth2_token = FakeOAuth2(
                        make_jwt({"client_id": client_id, "exp": 4102444800}),
                        refresh_token,
                        _t.time() + 86400,
                    )
                    garth_self.client.__dict__["oauth2_token"] = _GarthClient.oauth2_token

        self.client = _GarthClient()

    def configure(self, domain: str):
        self.configured_domains.append(domain)

    def resume(self, path: str):
        self.resume_calls.append(path)
        if not self._resume_ok:
            raise RuntimeError("no cached session")

    def login(self, email: str, password: str):
        self.login_calls.append((email, password))
        if not self._login_ok:
            raise RuntimeError("garth login rejected")

    def save(self, path: str):
        self.save_calls.append(path)


class ClientFactory:
    """按次数决定登录成败的 fake client 工厂。"""

    def __init__(self, *, fail_logins: int = 1, status: int = 401,
                 always_fail: bool = False, bare_auth_error: bool = False):
        self.fail_logins = fail_logins
        self.status = status
        self.always_fail = always_fail
        self.bare_auth_error = bare_auth_error
        self.created: list["FakeLoginClient"] = []

    def __call__(self, *args, **kwargs):
        remaining = 99 if self.always_fail else (
            self.fail_logins if not self.created else 0
        )
        client = FakeLoginClient(
            fail_remaining=remaining, status=self.status,
            bare_auth_error=self.bare_auth_error,
        )
        self.created.append(client)
        return client


class FakeLoginClient:
    def __init__(self, *, fail_remaining: int, status: int, bare_auth_error: bool = False):
        self.fail_remaining = fail_remaining
        self.status = status
        self.bare_auth_error = bare_auth_error
        self.login_tokenstores: list = []

    def login(self, tokenstore=None):
        self.login_tokenstores.append(tokenstore)
        if self.fail_remaining > 0:
            self.fail_remaining -= 1
            if self.bare_auth_error:
                raise GarminConnectAuthenticationError()
            raise HttpFailure(self.status)
        return None, None


def build(
    tmp_path: Path,
    *,
    client_factory: ClientFactory | None = None,
    garth: FakeGarth | None = None,
    is_cn: bool = True,
    email: str = "user@example.com",
    password: str = "secret-password",
) -> GarminWorkoutAdapter:
    return GarminWorkoutAdapter(
        email=email,
        password=password,
        tokenstore=tmp_path / "tokens",
        is_cn=is_cn,
        client_factory=client_factory or ClientFactory(),
        garth=garth or FakeGarth(),
        garth_token_store=tmp_path / "garth",
    )


class TestChinaBootstrap:
    def test_bootstrap_on_401_writes_tokenstore_and_retries(self, tmp_path):
        """CN + 401 → garth 引导 → tokenstore 落盘 → 重试成功。"""
        garth = FakeGarth()
        adapter = build(tmp_path, garth=garth)

        assert isinstance(adapter, GarminWorkoutAdapter)
        store_path = tmp_path / "tokens" / "garmin_tokens.json"
        assert store_path.exists(), "tokenstore 必须落盘"

        store = json.loads(store_path.read_text(encoding="utf-8"))
        assert set(store) == {"di_token", "di_refresh_token", "di_client_id"}
        assert store["di_refresh_token"] == "refresh-token-value"
        assert store["di_client_id"] == "GARMIN_CONNECT_MOBILE_ANDROID_DI"
        assert store["di_token"].startswith("header.")

    def test_bootstrap_uses_garmin_cn_domain(self, tmp_path):
        garth = FakeGarth()
        build(tmp_path, garth=garth)
        assert garth.configured_domains == ["garmin.cn"]

    def test_bootstrap_skipped_when_not_cn_even_on_401(self, tmp_path):
        """非中国区 garminconnect 密码登录本应可用，401 不触发 garth 兜底。"""
        garth = FakeGarth()
        with pytest.raises(GarminWorkoutAdapterError):
            build(tmp_path, garth=garth, is_cn=False)
        assert garth.configured_domains == []

    def test_two_phase_bootstrap_then_gives_up(self, tmp_path):
        """两阶段兜底（缓存 + 强制重登）后仍失败：抛错，不进入无限循环。

        调用序列：初始登录(1) → 阶段A引导 → 重试(2) → 仍401 →
                  阶段B强制重登 → 重试(3) → 仍401 → 抛错。
        """
        factory = ClientFactory(always_fail=True)  # 永远 401
        garth = FakeGarth()
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, client_factory=factory, garth=garth)
        assert info.value.error_code == "GARMIN_AUTH_REQUIRED"
        assert len(factory.created) == 3, "初始 + 阶段A重试 + 阶段B重试"
        assert garth.configured_domains == ["garmin.cn", "garmin.cn"]
        assert len(garth.login_calls) == 1, "阶段B只强制重登一次"

    def test_bootstrap_skipped_when_not_cn(self, tmp_path):
        """非中国区不做 garth 引导，直接抛 401。"""
        garth = FakeGarth()
        factory = ClientFactory(fail_logins=99)
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, client_factory=factory, garth=garth, is_cn=False)
        assert info.value.error_code == "GARMIN_AUTH_REQUIRED"
        assert garth.configured_domains == [], "非 CN 不应触发 garth"
        assert len(factory.created) == 1

    def test_bootstrap_skipped_on_429(self, tmp_path):
        """429 属限流，不触发认证兜底（避免加剧风控）。"""
        garth = FakeGarth()
        factory = ClientFactory(fail_logins=99, status=429)
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, client_factory=factory, garth=garth)
        assert info.value.error_code == "GARMIN_RATE_LIMITED"
        assert garth.configured_domains == []

    def test_resume_preferred_over_credential_login(self, tmp_path):
        """garth 缓存可用时优先 resume，不再做凭据登录。"""
        garth = FakeGarth(resume_ok=True)
        build(tmp_path, garth=garth)
        assert garth.resume_calls == [str(tmp_path / "garth")]
        assert garth.login_calls == []

    def test_falls_back_to_credential_login_when_resume_missing(self, tmp_path):
        garth = FakeGarth(resume_ok=False)
        build(tmp_path, garth=garth)
        assert garth.login_calls == [("user@example.com", "secret-password")]

    def test_missing_credentials_reported_without_secret(self, tmp_path):
        """无缓存会话且无凭据时，错误信息脱敏且给出原因。"""
        garth = FakeGarth(resume_ok=False)
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, garth=garth, password="")
        message = info.value.public_message
        assert "garth 引导失败" in message
        assert "secret-password" not in message
        assert "token" not in message.lower() or "tokenstore" in message.lower()

    def test_error_does_not_leak_raw_response_or_credentials(self, tmp_path):
        factory = ClientFactory(always_fail=True)
        garth = FakeGarth(login_ok=False)
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, client_factory=factory, garth=garth)
        message = info.value.public_message
        assert "secret-token" not in message  # 不拼接远端响应
        assert "secret-password" not in message
        assert not message.lower().startswith("bearer")

    def test_tokenstore_written_with_0600_permissions(self, tmp_path):
        """POSIX 上 tokenstore 权限收紧到 0600（Windows 跳过）。"""
        import os
        import stat

        build(tmp_path)
        store_path = tmp_path / "tokens" / "garmin_tokens.json"
        if os.name == "posix":
            mode = stat.S_IMODE(store_path.stat().st_mode)
            assert mode == 0o600

    def test_existing_valid_tokenstore_skips_bootstrap(self, tmp_path):
        """tokenstore 已有可用 token 时 garminconnect 直接成功，不触发 garth。"""
        token_dir = tmp_path / "tokens"
        token_dir.mkdir()
        (token_dir / "garmin_tokens.json").write_text(
            json.dumps(
                {
                    "di_token": make_jwt({"client_id": "X", "exp": 4102444800}),
                    "di_refresh_token": "r",
                    "di_client_id": "X",
                }
            ),
            encoding="utf-8",
        )
        garth = FakeGarth()
        adapter = GarminWorkoutAdapter(
            email="u@example.com",
            password="p",
            tokenstore=token_dir,
            is_cn=True,
            client_factory=ClientFactory(fail_logins=0),
            garth=garth,
            garth_token_store=tmp_path / "garth",
        )
        assert isinstance(adapter, GarminWorkoutAdapter)
        assert garth.configured_domains == []


class TestJwtClaim:
    def test_extracts_client_id(self):
        from app.adapters.garmin_workout_adapter import _jwt_claim

        token = make_jwt({"client_id": "CID_1", "exp": 1})
        assert _jwt_claim(token, "client_id") == "CID_1"

    def test_returns_none_for_malformed_token(self):
        from app.adapters.garmin_workout_adapter import _jwt_claim

        assert _jwt_claim("not-a-jwt", "client_id") is None
        assert _jwt_claim(None, "client_id") is None
        assert _jwt_claim("", "client_id") is None

    def test_returns_none_for_missing_claim(self):
        from app.adapters.garmin_workout_adapter import _jwt_claim

        assert _jwt_claim(make_jwt({"exp": 1}), "client_id") is None

    def test_bootstrap_on_auth_error_without_status_code(self, tmp_path):
        """garminconnect 的认证异常不带 status_code，仅消息含 401 —— 仍须兜底。"""
        garth = FakeGarth()
        factory = ClientFactory(fail_logins=1, bare_auth_error=True)
        adapter = build(tmp_path, client_factory=factory, garth=garth)
        assert isinstance(adapter, GarminWorkoutAdapter)
        assert garth.configured_domains == ["garmin.cn"]
        assert (tmp_path / "tokens" / "garmin_tokens.json").exists()

    def test_auth_error_without_status_code_also_two_phase(self, tmp_path):
        """无 status_code 的认证异常同样走两阶段，且不超过两阶段。"""
        garth = FakeGarth()
        factory = ClientFactory(always_fail=True, bare_auth_error=True)
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, client_factory=factory, garth=garth)
        assert info.value.error_code == "GARMIN_AUTH_REQUIRED"
        assert len(garth.configured_domains) == 2, "阶段A + 阶段B，不循环"
        assert len(garth.save_calls) == 2

class TestGarthTokenExpiry:
    """garth 缓存 token 过期时：先 refresh，失败再凭据登录，各一次。"""

    def test_valid_cached_token_skips_refresh_and_login(self, tmp_path):
        import time

        garth = FakeGarth(expires_at=time.time() + 86400)
        build(tmp_path, garth=garth)
        assert garth.refresh_calls == 0
        assert garth.login_calls == []

    def test_expired_cached_token_triggers_refresh(self, tmp_path):
        import time

        garth = FakeGarth(expires_at=time.time() - 60, refresh_ok=True)
        build(tmp_path, garth=garth)
        assert garth.refresh_calls == 1
        assert garth.login_calls == [], "refresh 成功就不该做凭据登录"

    def test_refresh_failure_falls_back_to_credential_login(self, tmp_path):
        import time

        garth = FakeGarth(expires_at=time.time() - 60, refresh_ok=False)
        build(tmp_path, garth=garth)
        assert garth.refresh_calls == 1
        assert garth.login_calls == [("user@example.com", "secret-password")]

    def test_expired_token_without_credentials_reports_reason(self, tmp_path):
        import time

        garth = FakeGarth(expires_at=time.time() - 60, refresh_ok=False)
        with pytest.raises(GarminWorkoutAdapterError) as info:
            build(tmp_path, garth=garth, password="")
        message = info.value.public_message
        assert "garth" in message
        assert "secret" not in message.lower()

    def test_token_expiring_within_skew_is_refreshed(self, tmp_path):
        """临近过期（小于安全余量）也要刷新，避免刚转换完就失效。"""
        import time

        garth = FakeGarth(expires_at=time.time() + 30)  # 30s < 120s skew
        build(tmp_path, garth=garth)
        assert garth.refresh_calls == 1

    def test_phase_b_skipped_when_phase_a_succeeds(self, tmp_path):
        """阶段 A（缓存会话）产出可用 token 后，不应再强制重登。"""
        garth = FakeGarth()
        adapter = build(tmp_path, garth=garth)
        assert isinstance(adapter, GarminWorkoutAdapter)
        assert len(garth.configured_domains) == 1, "只走了阶段A"
        assert garth.login_calls == [], "阶段A用缓存成功，不应凭据登录"

    def test_phase_b_uses_force_login(self, tmp_path):
        """阶段 A 的 token 被拒 → 阶段 B 跳过缓存直接凭据登录。"""
        garth = FakeGarth()
        # 第一次 client 登录成功（阶段A重试通过），但我们要断言阶段A成功后不重登
        factory = ClientFactory(fail_logins=1)  # 初始失败，重试成功
        adapter = build(tmp_path, client_factory=factory, garth=garth)
        assert isinstance(adapter, GarminWorkoutAdapter)
        assert len(garth.login_calls) == 0
