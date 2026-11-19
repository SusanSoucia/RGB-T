"""检测任务与帧/目标结果。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DetectionMode, ReferenceModality, RequestMode, TaskStatus


class TaskCreate(BaseModel):
    media_id: int
    requested_mode: RequestMode = RequestMode.auto


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    media_id: int
    requested_mode: RequestMode
    actual_mode: DetectionMode | None = None
    decision_reason: str | None = None
    ref_modality: ReferenceModality
    status: TaskStatus
    error_message: str | None = None

    model_version: str | None = None
    confidence_threshold: float | None = None
    iou_threshold: float | None = None
    imgsz: int | None = None

    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_ms: int | None = None
    inference_ms_total: int | None = None
    frames_processed: int = 0

    created_at: datetime


class FrameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    frame_index: int
    frame_ts_ms: int | None = None
    target_count: int
    intrusion_count: int
    max_score: float | None = None
    inference_ms: int | None = None
    has_image: bool = Field(default=False, description="该帧是否已落盘，前端据此取图")


class DetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    frame_index: int
    frame_ts_ms: int | None = None
    class_name: str
    score: float
    x1: float
    y1: float
    x2: float
    y2: float
    ref_modality: ReferenceModality
