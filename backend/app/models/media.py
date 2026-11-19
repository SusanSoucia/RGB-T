"""媒体源（视频 / 图片）。

设计要点：
1. **不为每一帧建一行**。一个 10 分钟、25fps 的视频有 15000 帧，单独存 media 行
   会直接撑爆数据库。帧由 (media_id, frame_index) 表达，图像本身留在磁盘。
2. **RGB 与 IR 的分辨率不同**。UAV-CB 数据集 RGB 是 1920×1080，热红外是 640×512，
   所以不能只存一套 width/height，否则坐标换算会错。参考画面用 width/height（RGB）。
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MediaStatus, MediaType
from app.models.mixins import TimestampMixin


class Media(Base, TimestampMixin):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 数据隔离的根：每条业务数据都能追到所有者（FR-02）
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 存相对路径，不存绝对路径：避免可猜测的绝对路径绕过权限（需求 §3.4）
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(MediaType, name="media_type", native_enum=False, length=16), nullable=False
    )
    mime_type: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))

    # ---- 参考画面（RGB）尺寸：所有归一化坐标都以它为准 ----
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    # ---- 红外通道（可与 RGB 不同分辨率）----
    has_ir: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    ir_stored_path: Mapped[str | None] = mapped_column(String(512))
    ir_width: Mapped[int | None] = mapped_column(Integer)
    ir_height: Mapped[int | None] = mapped_column(Integer)

    # ---- 视频元信息 ----
    fps: Mapped[float | None] = mapped_column(Numeric(7, 3))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    total_frames: Mapped[int | None] = mapped_column(Integer)
    # 抽帧步长：1=每帧都测，5=每 5 帧测一帧。视频场景必调，否则算不完
    frame_stride: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    status: Mapped[MediaStatus] = mapped_column(
        SAEnum(MediaStatus, name="media_status", native_enum=False, length=16),
        nullable=False,
        default=MediaStatus.uploaded,
        server_default=MediaStatus.uploaded.value,
    )
    # 解析失败原因：故障要能明确提示（需求 §3.5），不能静默
    error_message: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Media {self.id} {self.original_name} ({self.media_type})>"
