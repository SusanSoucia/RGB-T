"""警戒区域。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import RegionShape


class RegionIn(BaseModel):
    media_id: int
    name: str = Field(default="默认区域", max_length=64)
    shape_type: RegionShape = RegionShape.rect
    # [[x, y], ...] 归一化到 [0,1]
    points: list[list[float]]

    @field_validator("points")
    @classmethod
    def _check_points(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError("至少 3 个点")
        for p in v:
            if len(p) != 2:
                raise ValueError("每个点必须是 [x, y]")
            if not (0.0 <= p[0] <= 1.0 and 0.0 <= p[1] <= 1.0):
                raise ValueError("坐标必须归一化到 [0,1]")
        # 退化检查：面积近似为 0 时拒绝
        xs = [p[0] for p in v]
        ys = [p[1] for p in v]
        if max(xs) - min(xs) <= 1e-6 or max(ys) - min(ys) <= 1e-6:
            raise ValueError("区域退化为一条线，请重新绘制")
        return v


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    media_id: int
    name: str
    shape_type: RegionShape
    points: list[list[float]]
    is_active: bool
    created_at: datetime
