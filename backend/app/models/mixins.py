"""公共列 mixin。"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """创建/更新时间。

    用 timestamptz（带时区）。需求说明书 §3.3 明确：时间是**系统处理时间**，
    不是拍摄时间；拍摄时间由 frame_ts_ms 表达。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
