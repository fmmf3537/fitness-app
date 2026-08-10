"""V2-5 生产部署：生产配置加载 + 部署制品（compose/Dockerfile/Caddy/备份）静态校验。"""
import os
from pathlib import Path

import pytest

from app.config import Settings, get_settings, resolve_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent


def _make_settings(**env: str) -> Settings:
    """构造一个独立于全局缓存的 Settings（monkeypatch 由调用方传入的 env 已就位）。"""
    return Settings()


class TestProductionConfigLoading:
    """生产配置加载测试：密钥只来自环境变量，生产模式强制关键配置。"""

    def test_postgres_url_passes_through_resolve_unchanged(self):
        url = "postgresql+psycopg2://fitness:secret@postgres:5432/fitness"
        assert resolve_database_url(url) == url

    def test_app_env_defaults_to_development(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        get_settings.cache_clear()
        try:
            assert _make_settings().app_env == "development"
        finally:
            get_settings.cache_clear()

    def test_validate_production_ok_when_all_set(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_PASSWORD", "pw")
        monkeypatch.setenv("FERNET_KEY", "key")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg2://u:p@postgres:5432/fitness"
        )
        from app.config import validate_production_settings

        validate_production_settings(_make_settings())  # 不抛异常即通过

    def test_validate_production_missing_app_password(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("APP_PASSWORD", raising=False)
        monkeypatch.setenv("FERNET_KEY", "key")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg2://u:p@postgres:5432/fitness"
        )
        from app.config import validate_production_settings

        with pytest.raises(RuntimeError, match="APP_PASSWORD"):
            validate_production_settings(_make_settings())

    def test_validate_production_missing_fernet_key(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_PASSWORD", "pw")
        monkeypatch.delenv("FERNET_KEY", raising=False)
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg2://u:p@postgres:5432/fitness"
        )
        from app.config import validate_production_settings

        with pytest.raises(RuntimeError, match="FERNET_KEY"):
            validate_production_settings(_make_settings())

    def test_validate_production_rejects_sqlite(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_PASSWORD", "pw")
        monkeypatch.setenv("FERNET_KEY", "key")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./backend/data/app.db")
        from app.config import validate_production_settings

        with pytest.raises(RuntimeError, match="PostgreSQL"):
            validate_production_settings(_make_settings())

    def test_validate_skipped_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("APP_PASSWORD", raising=False)
        from app.config import validate_production_settings

        validate_production_settings(_make_settings())  # 开发模式不强制


class TestDeployArtifacts:
    """部署制品存在性与关键内容校验（防止部署文件被误删/改坏）。"""

    def test_docker_compose_defines_all_services(self):
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        for service in ("postgres:", "backend:", "frontend:", "backup:", "caddy:"):
            assert service in compose, f"docker-compose.yml 缺少服务 {service}"
        assert "pgdata" in compose, "postgres 必须挂数据卷"
        assert "POSTGRES_PASSWORD" in compose
        assert "APP_PASSWORD" in compose

    def test_backend_dockerfile_and_entrypoint(self):
        dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
        assert "python:3.11" in dockerfile
        assert "requirements.txt" in dockerfile
        entrypoint = (BACKEND_DIR / "docker-entrypoint.sh").read_text(encoding="utf-8")
        assert "alembic upgrade head" in entrypoint, "启动前必须重放迁移"
        assert "uvicorn" in entrypoint

    def test_frontend_dockerfile_and_nginx_proxy(self):
        dockerfile = (ROOT_DIR / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        assert "node:" in dockerfile and "nginx:" in dockerfile
        nginx = (ROOT_DIR / "frontend" / "nginx.conf").read_text(encoding="utf-8")
        assert "proxy_pass http://backend:8000" in nginx
        assert "try_files" in nginx, "SPA 路由需要 history fallback"

    def test_caddy_https_reverse_proxy(self):
        caddyfile = (ROOT_DIR / "deploy" / "Caddyfile").read_text(encoding="utf-8")
        assert "reverse_proxy" in caddyfile

    def test_backup_container_uses_pg_dump_and_retention(self):
        script = (ROOT_DIR / "deploy" / "backup" / "backup.sh").read_text(
            encoding="utf-8"
        )
        assert "pg_dump" in script
        assert "30" in script, "备份保留 30 天（PRD §7）"

    def test_env_templates_split_dev_and_prod(self):
        prod = (ROOT_DIR / ".env.production.example").read_text(encoding="utf-8")
        for var in (
            "APP_PASSWORD",
            "FERNET_KEY",
            "DATABASE_URL",
            "POSTGRES_PASSWORD",
            "SITE_ADDRESS",
            "XUNJI_API_KEY",
            "GARMIN_EMAIL",
        ):
            assert var in prod, f".env.production.example 缺少 {var}"
        assert "postgresql+psycopg2" in prod
        dev = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        assert "sqlite" in dev, "开发模板默认 SQLite"

    def test_deploy_doc_and_preflight_script_exist(self):
        doc = (ROOT_DIR / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
        for keyword in ("docker compose", "佳明", "preflight"):
            assert keyword in doc
        preflight = (ROOT_DIR / "scripts" / "preflight.sh").read_text(encoding="utf-8")
        for keyword in ("APP_PASSWORD", "80", "443", "alembic"):
            assert keyword in preflight
