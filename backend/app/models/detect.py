"""检测任务与检测结果（需求 FR-04 / FR-05 / FR-06 / FR-07 / FR-13）。

任务表负责"这一次检测"的元信息与可复现参数；
结果表负责"帧 × 目标"的原始模型输出。

刻意分离：**检测结果只放模型输出，不放业务判定**。
"是否在区域内"属于告警逻辑，写在 alerts 上，这样改了告警规则不需要动历史检测数据。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DetectionMode, ReferenceModality, RequestMode, TaskStatus
from app.models.mixins import TimestampMixin


class DetectTask(Base, TimestampMixin):
    __tablename__ = "detect_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 用户请求的模式 vs 实际使用的模式。
    # 两者分开存：手动模式要校验输入是否匹配（FR-05），自动模式要能解释为什么这么选（FR-06）。
    requested_mode: Mapped[RequestMode] = mapped_column(
        SAEnum(RequestMode, name="request_mode", native_enum=False, length=16), nullable=False
    )
    actual_mode: Mapped[DetectionMode | None] = mapped_column(
        SAEnum(DetectionMode, name="detection_mode", native_enum=False, length=16)
    )
    # 选择原因必须持久化：自动回退不能静默（需求 §3.5）
    decision_reason: Mapped[str | None] = mapped_column(String(512))

    # 双模态输出统一到哪个坐标系（需求 FR-07 要求"说明参考模态"）
    ref_modality: Mapped[ReferenceModality] = mapped_column(
        SAEnum(ReferenceModality, name="reference_modality", native_enum=False, length=16),
        nullable=False,
        default=ReferenceModality.rgb,
        server_default=ReferenceModality.rgb.value,
    )

    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False, length=16),
        nullable=False,
        default=TaskStatus.pending,
        server_default=TaskStatus.pending.value,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    # ---- 可复现参数（FR-13 / §3.2.1 要求注明口径）----
    model_version: Mapped[str | None] = mapped_column(String(64))
    confidence_threshold: Mapped[float | None] = mapped_column(Numeric(4, 3))
    iou_threshold: Mapped[float | None] = mapped_column(Numeric(4, 3))
    imgsz: Mapped[int | None] = mapped_column(Integer)

    # ---- 时间与耗时（§3.2.2 要求推理耗时与端到端耗时分列）----
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)          # 端到端
    inference_ms_total: Mapped[int | None] = mapped_column(BigInteger)  # 纯推理累计
    frames_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    detections: Mapped[list["Detection"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    # 帧级汇总（每处理一帧一行，含"无目标"的帧）
    frame_results: Mapped[list["FrameResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DetectTask {self.id} {self.requested_mode}->{self.actual_mode} {self.status}>"


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        Index("ix_detections_task_frame", "task_id", "frame_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("detect_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 该帧在源视频里的时间（毫秒），用于对齐与去重；不等于处理时间
    frame_ts_ms: Mapped[int | None] = mapped_column(BigInteger)

    class_name: Mapped[str] = mapped_column(
        String(32), nullable=False, default="uav", server_default="uav"
    )
    score: Mapped[float] = mapped_column(Double, nullable=False)

    # ---- 归一化坐标 [0,1]，基于 ref_modality 的**画面尺寸**换算 ----
    # 存归一化而不是像素：页面缩放、不同分辨率展示都不会错（需求 §3.2.1）
    x1: Mapped[float] = mapped_column(Double, nullable=False)
    y1: Mapped[float] = mapped_column(Double, nullable=False)
    x2: Mapped[float] = mapped_column(Double, nullable=False)
    y2: Mapped[float] = mapped_column(Double, nullable=False)

    ref_modality: Mapped[ReferenceModality] = mapped_column(
        SAEnum(ReferenceModality, name="reference_modality", native_enum=False, length=16),
        nullable=False,
        default=ReferenceModality.rgb,
        server_default=ReferenceModality.rgb.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    task: Mapped["DetectTask"] = relationship(back_populates="detections")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Detection task={self.task_id} f={self.frame_index} s={self.score:.3f}>"
