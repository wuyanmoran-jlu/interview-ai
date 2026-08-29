"""用户认证服务测试（SQLite 内存库，不依赖 Redis/PostgreSQL）。"""
import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auth_service import (
    User,
    change_password,
    create_token,
    decode_token,
    get_current_user,
    hash_password,
    login_user,
    register_user,
    validate_credentials,
    validate_password,
    verify_password,
)
from database import Base


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


# ===== 密码 =====

def test_password_hash_roundtrip():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed) is True
    assert verify_password("wrong-pass", hashed) is False


# ===== 输入校验 =====

def test_validate_credentials_rules():
    assert validate_credentials("alice", "password123") is None
    assert "用户名" in validate_credentials("ab", "password123")       # 用户名过短
    assert "用户名" in validate_credentials("bad name!", "password123")  # 非法字符
    assert "密码" in validate_credentials("alice", "short")             # 密码过短


def test_validate_password_rules():
    assert validate_password("password123") is None
    assert "密码" in validate_password("short")


# ===== 注册 / 登录 =====

@pytest.mark.asyncio
async def test_register_user_success(db):
    result = await register_user(db, "alice", "password123")
    assert result is not None
    assert result["user"]["username"] == "alice"
    assert result["token"]
    assert decode_token(result["token"])["sub"] == result["user"]["id"]


@pytest.mark.asyncio
async def test_register_duplicate_username(db):
    await register_user(db, "alice", "password123")
    assert await register_user(db, "alice", "another123") is None


@pytest.mark.asyncio
async def test_register_invalid_input_raises(db):
    with pytest.raises(ValueError):
        await register_user(db, "x", "password123")


@pytest.mark.asyncio
async def test_login_success(db):
    await register_user(db, "alice", "password123")
    result = await login_user(db, "alice", "password123")
    assert result is not None
    assert result["user"]["username"] == "alice"


@pytest.mark.asyncio
async def test_login_wrong_password(db):
    await register_user(db, "alice", "password123")
    assert await login_user(db, "alice", "wrong-pass") is None


@pytest.mark.asyncio
async def test_login_unknown_user(db):
    assert await login_user(db, "nobody", "password123") is None


# ===== JWT =====

@pytest.mark.asyncio
async def test_token_roundtrip(db):
    await register_user(db, "alice", "password123")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    token = create_token(stored)
    payload = decode_token(token)
    assert payload["sub"] == stored.id
    assert payload["username"] == "alice"
    assert payload["jti"]


def test_decode_invalid_token_raises():
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token("not-a-token")


# ===== 修改密码 =====

@pytest.mark.asyncio
async def test_change_password_success(db):
    await register_user(db, "alice", "oldpassword")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    assert await change_password(db, stored.id, "oldpassword", "newpassword") is None
    # 新密码可登录，旧密码失效
    assert await login_user(db, "alice", "newpassword") is not None
    assert await login_user(db, "alice", "oldpassword") is None


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(db):
    await register_user(db, "alice", "oldpassword")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    assert "原密码错误" in await change_password(db, stored.id, "wrong-old", "newpassword")


@pytest.mark.asyncio
async def test_change_password_too_short(db):
    await register_user(db, "alice", "oldpassword")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    assert "密码" in await change_password(db, stored.id, "oldpassword", "short")


@pytest.mark.asyncio
async def test_change_password_same_as_old(db):
    await register_user(db, "alice", "oldpassword")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    assert "相同" in await change_password(db, stored.id, "oldpassword", "oldpassword")


# ===== get_current_user 依赖 =====

@pytest.mark.asyncio
async def test_get_current_user_missing_credentials(db):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(None, db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(db):
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(creds, db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_valid_token(db, monkeypatch):
    await register_user(db, "alice", "password123")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    token = create_token(stored)

    async def fake_is_blacklisted(jti):
        return False

    monkeypatch.setattr("auth_service._is_blacklisted", fake_is_blacklisted)

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = await get_current_user(creds, db)
    assert user["username"] == "alice"
    assert user["id"] == stored.id


@pytest.mark.asyncio
async def test_get_current_user_blacklisted_token(db, monkeypatch):
    await register_user(db, "alice", "password123")
    from sqlalchemy import select

    stored = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
    token = create_token(stored)

    async def fake_is_blacklisted(jti):
        return True

    monkeypatch.setattr("auth_service._is_blacklisted", fake_is_blacklisted)

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(creds, db)
    assert exc.value.status_code == 401
