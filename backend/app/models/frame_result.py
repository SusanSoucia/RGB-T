"""帧级处理记录。

## 为什么需要这张表

`detections` 只在**检出目标**时才有行。如果某帧处理了、但画面里没有无人机，
那张表里没有任何痕迹——于是下面两个问题都答不出来：

- 第 120 帧到底处理过没有？
- 处理过的话，是"没检出目标"，还是"这一帧根本没被抽到"？

而需求明确要求页面能区分六种状态：**处理中 / 成功 / 失败 / 无目标 /
区域外目标 / 区域侵入**。没有这张表，前四种之后就断片了。

所以：**每处理一帧就写一行**，无论有没有目标。代价是行数等于处理帧数
（10 分钟 25fps、stride=5 约 3000 行/任务），换来的是可直查的时间轴。

## 与 detections 的关系

`frame_results` 是"这一帧的汇总"，`detections` 是"这一帧里每个目标的明细"。
两者用 `(task_id, frame_index)` 关联，两边都有索引。

    无目标  ⟺  target_count = 0
    有侵入  ⟺  intrusion_count > 0

## frame_index 的语义（重要）

`frame_index` 是 **原始视频中的帧号，从 0 起**，不是"抽帧后的第几个样本"。
所以 `frame_stride=5` 时它会是 0, 5, 10, 15...，**跳跃是正确的**。

只有这样，才能：
- 和 `frame_ts_ms` 对上（`ts = frame_index / fps * 1000`）
- 跳回原视频对应位置看现场
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FrameResult(Base):
    __tablename__ = "frame_results"
    __table_args__ = (
        # 同一任务同一帧只能一行。重复提交/重跑时靠它做幂等，避免重复写。
        # 这个唯一约束自带 (task_id, frame_index) 的 btree 索引，
        # 时间轴查询（按任务取帧、按帧号排序）直接复用它，**不要再单独建索引**，
        # 否则这张行数最多的表会多一份多余的写放大。
        UniqueConstraint("task_id", "frame_index", name="uq_frame_results_task_frame"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("detect_tasks.id", ondelete="CASCADE"), nullable=False
    )

    # 原始视频帧号（从 0 起，步长跳跃是正常的）
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 该帧在源视频中的时间偏移（毫秒）
    frame_ts_ms: Mapped[int | None] = mapped_column(BigInteger)

    # 该帧检出目标数（0 = 无目标，这就是"无目标"状态的判据）
    target_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 其中落在警戒区域内的目标数（> 0 表示这一帧有侵入）
    intrusion_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 该帧最高置信度，方便前端在时间轴上标色深浅
    max_score: Mapped[float | None] = mapped_column(Double)

    # 该帧推理耗时（毫秒），用于报告里的每帧耗时统计（需求 §3.2.2）
    inference_ms: Mapped[int | None] = mapped_column(Integer)

    # 留档截图路径（一般只对侵入帧生成，控体积）
    snapshot_path: Mapped[str | None] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    task: Mapped["DetectTask"] = relationship(back_populates="frame_results")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<FrameResult task={self.task_id} f={self.frame_index} "
            f"targets={self.target_count} intrusions={self.intrusion_count}>"
        )
