"""知识库 PostgreSQL 数据库连接层。

使用 SQLAlchemy 2.x 异步引擎连接专用 PostgreSQL 实例（kb-db 服务）。
"""
import logging
import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

load_dotenv()
logger = logging.getLogger("interview.kb")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://interview:kb_pass_2025_dev@localhost:5433/interview_kb",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有知识库 ORM 模型的基类。"""


async def init_db() -> None:
    """创建所有未存在的表（开发期快速建表，后续可切换 Alembic 迁移）。"""
    import auth_service  # noqa: F401  # 确保用户表注册到 metadata
    import knowledge_base  # noqa: F401  # 确保所有模型注册到 metadata
    import user_sessions  # noqa: F401  # 确保会话索引表注册到 metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """FastAPI 依赖：提供一个请求级数据库会话。"""
    async with SessionLocal() as session:
        yield session
