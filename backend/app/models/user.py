"""账户与角色（需求 FR-01 / FR-02）。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 不开放自主注册（FR-01），所以用户名由管理员创建
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # 只存哈希，绝不存明文（需求 §3.6）。算法用 bcrypt。
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", native_enum=False, length=16),
        nullable=False,
        default=UserRole.user,
        server_default=UserRole.user.value,
    )

    # 禁用账户不得继续获得新的业务访问授权（FR-01）
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.username} ({self.role})>"
