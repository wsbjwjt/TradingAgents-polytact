"""JWT 鉴权：单用户 + HS256。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status

from engine.config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(username: str) -> str:
    """生成 60 分钟有效期的 access_token。"""
    expire = _now() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": username, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(username: str) -> str:
    """生成 7 天有效期的 refresh_token。"""
    expire = _now() + timedelta(days=7)
    payload = {"sub": username, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_token_response(username: str) -> dict[str, Any]:
    """登录成功标准响应体。"""
    return {
        "success": True,
        "data": {
            "access_token": create_access_token(username),
            "refresh_token": create_refresh_token(username),
            "expires_in": settings.access_token_expire_minutes * 60,
            "user": {
                "id": username,
                "username": username,
                "email": f"{username}@tradingagents.local",
                "name": username,
                "is_admin": True,
            },
        },
        "message": "登录成功",
    }


def get_current_user(token: str) -> str:
    """校验 access_token，返回用户名。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        username: str = payload.get("sub", "")
        token_type: str = payload.get("type", "")
        if not username or token_type != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 Token")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 Token")
