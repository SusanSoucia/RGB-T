"""模型汇总。

alembic 的 autogenerate 靠 `Base.metadata` 发现表，所以**每加一个模型文件，
都必须在这里 import 一次**，否则迁移里会漏表（这个坑很隐蔽）。
"""

from app.models.alert import Alert
from app.models.detect import Detection, DetectTask
from app.models.enums import (
    AlertStatus,
    DetectionMode,
    MediaStatus,
    MediaType,
    ReferenceModality,
    RegionShape,
    RequestMode,
    TaskStatus,
    UserRole,
)
from app.models.frame_result import FrameResult
from app.models.media import Media
from app.models.region import Region
from app.models.user import User

__all__ = [
    "Alert",
    "AlertStatus",
    "Detection",
    "DetectionMode",
    "DetectTask",
    "FrameResult",
    "Media",
    "MediaStatus",
    "MediaType",
    "ReferenceModality",
    "Region",
    "RegionShape",
    "RequestMode",
    "TaskStatus",
    "User",
    "UserRole",
]
