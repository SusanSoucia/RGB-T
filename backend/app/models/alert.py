"""告警（需求 FR-09 / FR-10 / FR-11 / FR-12）。

关于视频带来的一个真实问题（README §12-Q2）：
需求说明书说首版「不包含跨帧告警抑制」，但又要求视频输入。25fps 下每帧都可能
触发侵入判定，如果每帧都插一条告警，数据库和用户都会被淹没。

折中方案（不是目标跟踪，只是告警去重）：同一 (media, region) 上，
若新判定与上一条未确认告警的时间间隔 < 阈值且位置相近，就**并入原告警**：
  occurrence_count += 1，last_seen_at = 本帧时间，score_max = max(...)
所以表里必须有 occurrence_count / first_seen_at / last_seen_at 这三个字段。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AlertStatus
from app.models.mixins import TimestampMixin


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_owner_status", "owner_id", "status"),
        Index("ix_alerts_owner_created", "owner_id", "created_at"),
        Index("ix_alerts_media_region", "media_id", "region_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 告警必须能追到来龙去脉（FR-09：关联检测结果、来源图片及区域）
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("detect_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="CASCADE"), nullable=False, index=True
    )
    region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("regions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 触发这条告警的"代表检测"；归并后保留首次触发的那条
    detection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("detections.id", ondelete="SET NULL")
    )

    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_ts_ms: Mapped[int | None] = mapped_column(BigInteger)

    score_max: Mapped[float] = mapped_column(Double, nullable=False)
    # 告警现场截图（需求 §3.3 要求告警带截图）
    snapshot_path: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, name="alert_status", native_enum=False, length=16),
        nullable=False,
        default=AlertStatus.unconfirmed,
        server_default=AlertStatus.unconfirmed.value,
    )

    # 确认记录：确认人 + 确认时间，持久保存（FR-10）
    confirmed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ---- 归并用字段（见模块 docstring）----
    occurrence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Alert {self.id} media={self.media_id} {self.status} x{self.occurrence_count}>"
