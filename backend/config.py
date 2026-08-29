"""集中配置管理（pydantic-settings）。

所有环境相关配置在此统一定义，从 .env / 环境变量读取。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库与依赖服务
    database_url: str = (
        "postgresql+asyncpg://interview:kb_pass_2025_dev@localhost:5433/interview_kb"
    )
    redis_url: str = "redis://localhost:6379/0"
    judge0_url: str = "http://localhost:2358"

    # AI
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # 认证
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_expire_days: int = 7

    # Web
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
