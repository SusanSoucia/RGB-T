"""媒体。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import MediaStatus, MediaType


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    original_name: str
    media_type: MediaType
    status: MediaStatus
    error_message: str | None = None

    width: int | None = None
    height: int | None = None
    has_ir: bool = False
    ir_width: int | None = None
    ir_height: int | None = None

    fps: float | None = None
    duration_ms: int | None = None
    total_frames: int | None = None
    frame_stride: int = 1

    created_at: datetime
