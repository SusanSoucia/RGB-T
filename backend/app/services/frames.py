"""分帧。

按步长抽帧、最多处理 `settings.max_process_frames` 帧。

**`frame_index` 一律是原始视频帧号**（0, stride, 2*stride, ...），
不是"抽帧后的第几个样本"——这个语义必须全链路一致，
否则坐标、时间戳、前端跳转全都会错（见 docs/api.md §1.4）。

### 有效步长（重要）

如果只按 `frame_stride=5` 顺序抽、抽满 limit 帧就停，长视频**只会处理开头一小段**：
5610 帧的视频、limit=30 → 只处理 0~145 帧，覆盖率 0.5%，看起来像"只分析了前两秒"。

所以这里会按**视频总长度反推一个更小的采样密度**：

    eff_stride = max(stride, ceil(total_frames / limit))

这样 limit 帧被均匀铺满整段视频。实测解码速度约 600 帧/秒，
90 秒的视频整段解码约 9 秒，代价可接受。
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings
from app.services.imaging import read_image


@dataclass
class FramePair:
    frame_index: int
    ts_ms: int | None
    rgb: np.ndarray | None
    ir: np.ndarray | None


def iter_frame_pairs(
    rgb_path: str | Path,
    ir_path: str | Path | None = None,
    *,
    is_video: bool = False,
    stride: int = 1,
    max_frames: int | None = None,
) -> Iterator[FramePair]:
    stride = max(1, int(stride))
    limit = max_frames or settings.max_process_frames

    # ---------- 单张图片 ----------
    if not is_video:
        rgb = read_image(rgb_path)
        ir = read_image(ir_path) if ir_path else None
        if rgb is not None or ir is not None:
            # 图片没有"视频帧号"概念，统一记 0
            yield FramePair(frame_index=0, ts_ms=0, rgb=rgb, ir=ir)
        return

    # ---------- 视频 ----------
    cap_rgb = cv2.VideoCapture(str(rgb_path))
    cap_ir = cv2.VideoCapture(str(ir_path)) if ir_path else None
    if not cap_rgb.isOpened():
        cap_rgb.release()
        if cap_ir:
            cap_ir.release()
        return

    fps = cap_rgb.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(cap_rgb.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    # 有效步长：让 limit 帧均匀铺满整段，而不是只覆盖开头
    eff_stride = stride
    if total > 0:
        eff_stride = max(stride, math.ceil(total / limit))

    try:
        idx = 0
        yielded = 0
        while yielded < limit:
            ok_rgb, frame_rgb = cap_rgb.read()
            # 红外与可见光同步读取（同一帧号），长度不一致时以可见光为准
            frame_ir = None
            if cap_ir is not None:
                ok_ir, tmp = cap_ir.read()
                frame_ir = tmp if ok_ir else None

            if not ok_rgb and frame_ir is None:
                break

            if idx % eff_stride == 0:
                if frame_rgb is None and frame_ir is None:
                    break
                ts = int(idx / fps * 1000) if fps > 0 else None
                yield FramePair(frame_index=idx, ts_ms=ts, rgb=frame_rgb, ir=frame_ir)
                yielded += 1
            idx += 1
    finally:
        cap_rgb.release()
        if cap_ir is not None:
            cap_ir.release()


def frame_image_path(media_id: int, frame_index: int) -> Path:
    """处理过的帧落盘位置。前端按 (media_id, frame_index) 取图。"""
    d = Path(settings.frames_dir) / str(media_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{frame_index}.jpg"


def save_frame_image(media_id: int, frame_index: int, img: np.ndarray | None) -> str | None:
    if img is None:
        return None
    path = frame_image_path(media_id, frame_index)
    try:
        if not cv2.imwrite(str(path), img):
            return None
    except Exception:  # noqa: BLE001
        return None
    # 存相对路径进库（禁止绝对路径，避免可猜测路径绕过权限，需求 §3.4）
    return f"frames/{media_id}/{frame_index}.jpg"
