"""图像度量与媒体探测。

自适应选择需要三个客观指标，全部来自**可见光**帧：
- 亮度：决定是不是低照度场景（低照度下热红外更可靠）
- 对比度：决定画面层次是否糊成一片
- 清晰度：拉普拉斯方差，判断是否模糊/失焦
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class ImageStats:
    brightness: float   # 灰度均值 0~255
    contrast: float     # 灰度标准差
    sharpness: float    # 拉普拉斯方差

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_bgr(cls, img: np.ndarray) -> "ImageStats":
        if img is None or img.size == 0:
            return cls(0.0, 0.0, 0.0)
        # 统一转灰度：红外图本身是单通道，imread 会补成 3 通道，这里都能处理
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        return cls(
            brightness=float(gray.mean()),
            contrast=float(gray.std()),
            sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        )


@dataclass
class MediaProbe:
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    total_frames: int | None = None
    duration_ms: int | None = None
    is_video: bool = False


def read_image(path: str | Path) -> np.ndarray | None:
    """读图。中文路径在 Windows 下 cv2.imread 会失败，所以用 fromfile 兜底。"""
    p = str(path)
    img = cv2.imread(p, cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        buf = np.fromfile(p, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        return None


def probe_media(path: str | Path, is_video: bool) -> MediaProbe:
    p = str(path)
    if is_video:
        cap = cv2.VideoCapture(p)
        try:
            if not cap.isOpened():
                return MediaProbe(is_video=True)
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            duration = int(total / fps * 1000) if fps > 0 else None
            return MediaProbe(
                width=w or None, height=h or None,
                fps=round(fps, 3) or None, total_frames=total or None,
                duration_ms=duration, is_video=True,
            )
        finally:
            cap.release()

    img = read_image(p)
    if img is None:
        return MediaProbe()
    return MediaProbe(width=int(img.shape[1]), height=int(img.shape[0]))


def guess_is_video(filename: str, content_type: str | None = None) -> bool:
    video_ext = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".m4v", ".webm"}
    if os.path.splitext(filename)[1].lower() in video_ext:
        return True
    if content_type and content_type.startswith("video/"):
        return True
    return False
