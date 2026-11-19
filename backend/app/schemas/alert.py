"""告警。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AlertStatus


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    task_id: int
    media_id: int
    region_id: int
    detection_id: int | None = None

    frame_index: int
    frame_ts_ms: int | None = None
    score_max: float
    snapshot_path: str | None = None

    status: AlertStatus
    confirmed_by_id: int | None = None
    confirmed_at: datetime | None = None

    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime


class AlertConfirmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: AlertStatus
    confirmed_by_id: int | None = None
    confirmed_at: datetime | None = None
