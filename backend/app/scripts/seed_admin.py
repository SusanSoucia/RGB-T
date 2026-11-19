"""创建初始管理员账号。

需求 FR-01 规定**不开放自主注册**，账户由管理员创建。所以系统初始化时必须
先有一个管理员，否则谁也登不进去。

用法（容器内）：
    docker compose exec api python -m app.scripts.seed_admin

可用环境变量覆盖默认值：
    SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD / SEED_ADMIN_DISPLAY

⚠️ 默认密码只用于本地开发，交付前必须改掉，并且不要写进文档/PPT。
"""

import os
import sys

from passlib.context import CryptContext
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.enums import UserRole
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main() -> int:
    username = os.getenv("SEED_ADMIN_USERNAME", "admin")
    password = os.getenv("SEED_ADMIN_PASSWORD", "Admin@12345")
    display = os.getenv("SEED_ADMIN_DISPLAY", "系统管理员")

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            print(f"[skip] 管理员 '{username}' 已存在（id={existing.id}），未做修改")
            return 0

        user = User(
            username=username,
            password_hash=pwd_context.hash(password),
            display_name=display,
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"[ok] 已创建管理员 id={user.id} username={username}")
        if password == "Admin@12345":
            print("[warn] 正在使用默认密码，交付前务必修改！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
