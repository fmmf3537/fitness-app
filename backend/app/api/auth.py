"""M6 登录口令认证（单用户简单会话，PRD §7）。"""
import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 内存会话表（单用户自用，重启后重新登录即可）
_ACTIVE_TOKENS: set[str] = set()


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(req: LoginRequest) -> dict:
    expected = get_settings().app_password
    if not expected:
        raise HTTPException(status_code=503, detail="APP_PASSWORD 未配置")
    if not secrets.compare_digest(req.password, expected):
        raise HTTPException(status_code=401, detail="口令错误")
    token = secrets.token_urlsafe(32)
    _ACTIVE_TOKENS.add(token)
    return {"token": token}


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """FastAPI 依赖：校验 Bearer token，未通过一律 401。"""
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[len(prefix):]
    if token not in _ACTIVE_TOKENS:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return token
