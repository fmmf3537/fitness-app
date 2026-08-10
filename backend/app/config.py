"""环境变量加载与 Fernet 加密工具。

铁律：所有密钥/token 只从环境变量或加密存储读取，代码中禁止硬编码密钥。
.env 文件位于项目根目录（被 .gitignore 忽略），模板见根目录 .env.example。
"""
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

# 项目 .env 是密钥的唯一权威来源，必须优先于 OS 环境变量（override=True）：
# 2026-08-07 实测发现 OS 级残留旧 KIMI_API_KEY 会遮蔽 .env 中的新 Key 导致 401
load_dotenv(ROOT_DIR / ".env", override=True)
load_dotenv(BACKEND_DIR / ".env", override=True)

DEFAULT_DATABASE_URL = f"sqlite:///{BACKEND_DIR}/data/app.db"


def resolve_database_url(url: str | None) -> str:
    """相对路径的 sqlite URL 一律锚定到项目根目录，避免随 CWD 漂移。

    make_engine / alembic env.py / Settings 统一走本函数，保证无论从哪个
    目录启动都指向同一个数据库文件。
    """
    url = url or DEFAULT_DATABASE_URL
    prefix = "sqlite:///"
    if url.startswith(prefix):
        path = url[len(prefix):]
        if path != ":memory:" and not Path(path).is_absolute():
            url = prefix + str((ROOT_DIR / path).resolve())
    return url


class Settings:
    """从环境变量读取的全部配置（属性不存在时为空字符串，绝不提供默认密钥）。"""

    def __init__(self) -> None:
        # 第三方凭据
        self.xunji_api_key = os.getenv("XUNJI_API_KEY", "")
        self.xunji_body_api_key = os.getenv("XUNJI_BODY_API_KEY", "")
        self.garmin_email = os.getenv("GARMIN_EMAIL", "")
        self.garmin_password = os.getenv("GARMIN_PASSWORD", "")
        # 佳明域名：中国区 garmin.cn（PRD §6.2），可用 GARMIN_DOMAIN 覆盖
        self.garmin_domain = os.getenv("GARMIN_DOMAIN", "garmin.cn")
        # LLM Keys
        self.kimi_api_key = os.getenv("KIMI_API_KEY", "")
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY", "")
        # 应用
        self.database_url = self._resolve_database_url(os.getenv("DATABASE_URL"))
        self.fernet_key = os.getenv("FERNET_KEY", "")
        self.app_password = os.getenv("APP_PASSWORD", "")
        # 历史回溯起点（V1-2）：训记 2023-02 启用；佳明每日健康与之对齐
        self.backfill_start_date = os.getenv("BACKFILL_START_DATE", "2023-02-01")
        # 佳明活动列表回溯起点（PRD US-5：2017 年起全量）
        self.garmin_backfill_start_date = os.getenv("GARMIN_BACKFILL_START_DATE", "2017-01-01")
        # 告警推送（V2-4）：Server酱 SendKey 或 SMTP 邮件，两者都配置则双通道发送
        self.serverchan_sendkey = os.getenv("SERVERCHAN_SENDKEY", "")
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_pass = os.getenv("SMTP_PASS", "")
        self.alert_email = os.getenv("ALERT_EMAIL", "")

    @staticmethod
    def _resolve_database_url(url: str | None) -> str:
        """锚定逻辑见模块级 resolve_database_url（与 make_engine/alembic 同源）。"""
        return resolve_database_url(url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise RuntimeError(
            "FERNET_KEY 未配置：请在 .env 中设置，可用命令生成："
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt_value(plain: str) -> str:
    """Fernet 对称加密，返回可入库的字符串密文。"""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_value(token: str) -> str:
    """Fernet 解密，还原 encrypt_value 的原文。"""
    return _fernet().decrypt(token.encode()).decode()
