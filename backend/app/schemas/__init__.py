"""Pydantic 模型汇总。

API 层只从这里 import，避免各处散落地引用具体模块。
"""

from app.schemas.alert import AlertConfirmOut, AlertOut
from app.schemas.auth import LoginIn, TokenOut, UserOut
from app.schemas.common import Page
from app.schemas.media import MediaOut
from app.schemas.region import RegionIn, RegionOut
from app.schemas.task import DetectionOut, FrameOut, TaskCreate, TaskOut

__all__ = [
    "AlertConfirmOut",
    "AlertOut",
    "DetectionOut",
    "FrameOut",
    "LoginIn",
    "MediaOut",
    "Page",
    "RegionIn",
    "RegionOut",
    "TaskCreate",
    "TaskOut",
    "TokenOut",
    "UserOut",
]
