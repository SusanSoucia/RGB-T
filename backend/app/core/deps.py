"""FastAPI 依赖：当前用户、权限、会话。

**数据隔离在这里落地**：`current_user` 之后，所有业务查询都必须带
`owner_id == user.id`（admin 走"不过滤"分支）。不要靠前端隐藏按钮。
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

__all__ = ["get_db", "current_user", "require_admin", "owned_or_admin"]


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if cred is None or not cred.credentials:
        raise ApiError("AUTH_TOKEN_EXPIRED", "未登录或登录失效", 401)

    payload = decode_access_token(cred.credentials)
    if not payload or not payload.get("sub"):
        raise ApiError("AUTH_TOKEN_EXPIRED", "登录失效，请重新登录", 401)

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise ApiError("AUTH_TOKEN_EXPIRED", "账户不存在", 401)
    if not user.is_active:
        # 需求 FR-01：禁用账户不得继续获得新的业务访问授权
        raise ApiError("AUTH_ACCOUNT_DISABLED", "账户已被禁用", 403)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.admin:
        raise ApiError("FORBIDDEN_NOT_OWNER", "需要管理员权限", 403)
    return user


def owned_or_admin(user: User, owner_id: int) -> None:
    """单条记录的所有者校验。admin 放行。"""
    if user.role == UserRole.admin:
        return
    if owner_id != user.id:
        raise ApiError("FORBIDDEN_NOT_OWNER", "无权访问该资源", 403)
