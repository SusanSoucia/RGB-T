"""认证接口（docs/api.md §3）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import current_user, get_db
from app.core.errors import ApiError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.models.enums import UserRole
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

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


@router.post("/register", response_model=UserOut, status_code=201, summary="注册（受开关控制）")
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> UserOut:
    """自主注册。

    ⚠️ 需求说明书 FR-01 规定「不开放自主注册」，账户由管理员创建，
    验收会检查这一点。所以这里由 `settings.allow_self_register` 控制，
    默认关闭：前端可以展示注册页，但提交时会收到 REGISTER_DISABLED，
    引导用户联系管理员。

    要临时开放（演示/比赛），把环境变量 `ALLOW_SELF_REGISTER=true` 打开即可。
    """
    if not settings.allow_self_register:
        raise ApiError(
            "REGISTER_DISABLED",
            "本系统不开放自主注册，请联系管理员开通账号",
            403,
        )

    if db.scalar(select(User).where(User.username == payload.username)) is not None:
        raise ApiError("AUTH_USERNAME_TAKEN", "该用户名已被占用", 409)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        role=UserRole.user,          # 自主注册只能拿到普通用户
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/logout", summary="退出登录")
def logout(user: User = Depends(current_user)) -> dict:
    # JWT 是无状态的，服务端不需要做什么；前端丢弃 token 即可。
    # 这里保留接口是为了让前端有确定的调用点，将来要加黑名单也在这里。
    return {"ok": True}


@router.get("/me", response_model=UserOut, summary="当前用户")
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)
