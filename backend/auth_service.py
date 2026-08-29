"""用户认证服务。

- User 模型：字符串 UUID 主键，与现有 user_id 体系兼容
- 密码：bcrypt 哈希
- 会话凭证：JWT（Bearer Token），登出通过 Redis 黑名单实现
"""
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from config import settings
from database import Base, get_session
from interview_manager import _get_redis

load_dotenv()
logger = logging.getLogger("interview.auth")

JWT_SECRET = settings.jwt_secret
JWT_EXPIRE_DAYS = settings.jwt_expire_days
JWT_ALGORITHM = "HS256"

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
MIN_PASSWORD_LEN = 8

# 登录限流：同用户名连续失败 5 次锁定 15 分钟
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60


def _login_fail_key(username: str) -> str:
    return f"auth:fail:{username}"


def should_lock(fail_count: int) -> bool:
    """纯函数：失败次数达到阈值则锁定。"""
    return fail_count >= LOGIN_MAX_FAILURES


async def check_login_rate_limit(username: str) -> None:
    """检查登录限流，超限抛 429。"""
    redis = _get_redis()
    key = _login_fail_key(username)
    raw = await redis.get(key)
    if raw and should_lock(int(raw)):
        ttl = max(await redis.ttl(key), 0)
        minutes = max(ttl // 60 + 1, 1)
        raise HTTPException(status_code=429, detail=f"尝试次数过多，请在 {minutes} 分钟后重试")


async def record_login_failure(username: str) -> None:
    redis = _get_redis()
    key = _login_fail_key(username)
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, LOGIN_LOCK_SECONDS)
    await pipe.execute()


async def clear_login_failures(username: str) -> None:
    await _get_redis().delete(_login_fail_key(username))

bearer_scheme = HTTPBearer(auto_error=False)


class User(Base):
    """用户账号表。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


# ===== 密码 =====

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ===== 输入校验 =====

def validate_credentials(username: str, password: str) -> Optional[str]:
    """校验注册/登录输入，返回错误消息（None 表示通过）。"""
    if not USERNAME_RE.match(username or ""):
        return "用户名需为 3-20 位字母、数字或下划线"
    return validate_password(password)


def validate_password(password: str) -> Optional[str]:
    if not password or len(password) < MIN_PASSWORD_LEN:
        return f"密码长度至少 {MIN_PASSWORD_LEN} 位"
    return None


# ===== JWT =====

def _blacklist_key(jti: str) -> str:
    return f"auth:blacklist:{jti}"


def create_token(user: User) -> str:
    """签发 JWT，携带 jti 供登出黑名单使用。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "username": user.username,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=JWT_EXPIRE_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT，失败抛 jwt 异常（由调用方处理）。"""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


async def _is_blacklisted(jti: str) -> bool:
    redis = _get_redis()
    return await redis.get(_blacklist_key(jti)) is not None


async def blacklist_token(payload: dict) -> None:
    """把 token 的 jti 加入黑名单，TTL 截止到 token 过期时间。"""
    jti = payload.get("jti")
    if not jti:
        return
    exp = int(payload.get("exp", time.time() + 3600))
    ttl = max(exp - int(time.time()), 1)
    redis = _get_redis()
    await redis.setex(_blacklist_key(jti), ttl, "1")


# ===== 注册 / 登录 =====

async def register_user(
    session: AsyncSession, username: str, password: str, anonymous_id: str = ""
) -> Optional[dict]:
    """创建用户。用户名已存在返回 None，输入非法抛 ValueError。

    若携带匿名 ID，注册成功后自动合并其历史数据。
    """
    error = validate_credentials(username, password)
    if error:
        raise ValueError(error)

    existing = await session.scalar(select(User.id).where(User.username == username))
    if existing is not None:
        return None

    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    if anonymous_id:
        await merge_anonymous_data(anonymous_id, user.id)

    return {"token": create_token(user), "user": {"id": user.id, "username": user.username}}


async def login_user(
    session: AsyncSession, username: str, password: str, anonymous_id: str = ""
) -> Optional[dict]:
    """校验用户名密码，成功返回 token + 用户信息，失败返回 None。

    若携带匿名 ID，登录成功后自动合并其历史数据。
    """
    user = await session.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        return None

    if anonymous_id:
        await merge_anonymous_data(anonymous_id, user.id)

    return {"token": create_token(user), "user": {"id": user.id, "username": user.username}}


async def change_password(
    session: AsyncSession, user_id: str, old_password: str, new_password: str
) -> Optional[str]:
    """修改密码。返回 None 表示成功，否则返回错误消息。"""
    error = validate_password(new_password)
    if error:
        return error
    if new_password == old_password:
        return "新密码不能与原密码相同"

    user = await session.get(User, user_id)
    if user is None:
        return "用户不存在"
    if not verify_password(old_password, user.password_hash):
        return "原密码错误"

    user.password_hash = hash_password(new_password)
    await session.commit()
    return None


# ===== FastAPI 依赖 =====

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """从 Bearer Token 解析当前用户；无效/过期/已登出返回 401。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证凭证")

    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    if await _is_blacklisted(payload.get("jti", "")):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")

    user_id = payload.get("sub")
    user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    return {"id": user.id, "username": user.username}


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> Optional[dict]:
    """带 token 则校验并返回用户，无 token 返回 None（匿名模式）。"""
    if credentials is None:
        return None
    return await get_current_user(credentials, session)


# ===== 匿名历史合并 =====

async def merge_anonymous_data(anonymous_id: str, account_id: str) -> dict:
    """把匿名用户的数据迁移到账号名下。

    - PG：会话索引 + 题目评价的 user_id 迁移
    - Redis：会话 zset 与已用题集合合并到账号 key
    """
    if not anonymous_id or anonymous_id == account_id:
        return {"sessions": 0, "ratings": 0}

    from database import SessionLocal
    from user_sessions import migrate_user_data

    async with SessionLocal() as session:
        pg_result = await migrate_user_data(session, anonymous_id, account_id)

    redis = _get_redis()
    src_zset = f"interview:user:{anonymous_id}"
    dst_zset = f"interview:user:{account_id}"
    members = await redis.zrange(src_zset, 0, -1, withscores=True)
    if members:
        await redis.zadd(dst_zset, dict(members))
        await redis.delete(src_zset)

    src_used = f"interview:used_questions:{anonymous_id}"
    dst_used = f"interview:used_questions:{account_id}"
    used = await redis.smembers(src_used)
    if used:
        await redis.sadd(dst_used, *used)
        await redis.delete(src_used)

    logger.info(
        "合并匿名历史 %s -> %s: %s", anonymous_id[:8], account_id[:8], pg_result
    )
    return pg_result
