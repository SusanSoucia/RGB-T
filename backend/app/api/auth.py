"""认证接口（docs/api.md §3）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import current_user, get_db
from app.core.errors import ApiError
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas import LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut, summary="登录")
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.username == payload.username))

    # 用户不存在和密码错误返回**同一个**错误码，避免账户枚举
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError("AUTH_INVALID_CREDENTIALS", "用户名或密码错误", 401)

    if not user.is_active:
        raise ApiError("AUTH_ACCOUNT_DISABLED", "账户已被禁用", 403)

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=str(user.id), extra={"role": user.role.value})
    return TokenOut(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", summary="退出登录")
def logout(user: User = Depends(current_user)) -> dict:
    # JWT 是无状态的，服务端不需要做什么；前端丢弃 token 即可。
    # 这里保留接口是为了让前端有确定的调用点，将来要加黑名单也在这里。
    return {"ok": True}


@router.get("/me", response_model=UserOut, summary="当前用户")
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)
