"""标注视频导出。

把「警戒区域轮廓 + 检测框」烧进画面，输出一个可直接下载播放的视频。

## 两个关键约束

1. **输出容器必须用 WebM(VP8)，不能用 mp4**
   本镜像里的 OpenCV 没有 libx264（实测 avc1/H264 都打不开），
   只能写 mp4v 或 VP8/VP9；而 **mp4v 在 Chromium 里无法播放**。
   所以输出固定为 `.webm` + VP8，浏览器可以直接播。

2. **区域轮廓每一帧都画，检测框只在"已处理帧"上更新**
   抽帧步长通常 >1，没有那些帧的检测结果。做法是"沿用最近一个已处理帧的框"，
   这样视频看起来是连续的，框会每 N 帧跳一次（符合实际数据）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings
from app.services.intrusion import region_contains


# 配色（BGR）
COLOR_REGION = (0, 165, 255)      # 橙色：警戒区域
COLOR_REGION_FILL = (0, 210, 255)
COLOR_BOX = (60, 200, 60)         # 绿色：区域外目标
COLOR_BOX_HOT = (40, 40, 230)     # 红色：区域内目标
COLOR_TEXT_BG = (30, 30, 30)


def _safe_label(name: str | None, idx: int) -> str:
    """cv2.putText 用的是 Hershey 矢量字体，**只支持 ASCII**。

    直接写中文会变成一串问号（容器里也没有中文字体可加载）。
    所以：纯 ASCII 的名字保留，其余退回 "Region N"。
    页面上显示的中文名不受影响——那是浏览器 canvas 渲染的。
    """
    text = (name or "").strip()
    if not text:
        return f"Region {idx}"
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return f"Region {idx}"


def _draw_region(img: np.ndarray, points: list[list[float]], name: str | None, idx: int) -> None:
    h, w = img.shape[:2]
    pts = np.array([[int(round(x * w)), int(round(y * h))] for x, y in points], dtype=np.int32)
    if len(pts) < 3:
        return

    # 半透明填充，让区域一眼可见
    overlay = img.copy()
    cv2.fillPoly(overlay, [pts], COLOR_REGION_FILL)
    cv2.addWeighted(overlay, 0.18, img, 0.82, 0, dst=img)

    cv2.polylines(img, [pts], isClosed=True, color=COLOR_REGION, thickness=2)

    label = _safe_label(name, idx)
    if label:
        x, y = pts[0]
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        ty = max(th + 6, y - 6)
        cv2.rectangle(img, (x, ty - th - 6), (x + tw + 8, ty), COLOR_TEXT_BG, -1)
        cv2.putText(img, label, (x + 4, ty - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_REGION, 2, cv2.LINE_AA)


def _draw_boxes(img: np.ndarray, boxes: list[dict]) -> None:
    h, w = img.shape[:2]
    for b in boxes:
        x1 = int(round(b["x1"] * w)); y1 = int(round(b["y1"] * h))
        x2 = int(round(b["x2"] * w)); y2 = int(round(b["y2"] * h))
        color = COLOR_BOX_HOT if b.get("inside") else COLOR_BOX
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

        label = f"{b['score']:.2f}" + (" IN" if b.get("inside") else "")
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = max(th + 4, y1 - 4)
        cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 6, ty), color, -1)
        cv2.putText(img, label, (x1 + 3, ty - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


def render_video(
    *,
    src_path: Path,
    out_path: Path,
    regions: list[dict],
    boxes_by_frame: dict[int, list[dict]],
    max_frames: int | None = None,
) -> bool:
    """渲染标注视频。成功返回 True。

    Args:
        src_path: 源视频
        out_path: 输出 .webm
        regions: [{"name": str, "points": [[x,y],...]}]
        boxes_by_frame: {原始帧号: [{"x1","y1","x2","y2","score","inside"}]}
    """
    cap = cv2.VideoCapture(str(src_path))
    if not cap.isOpened():
        return False

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if w <= 0 or h <= 0:
            return False

        limit = max_frames or settings.render_max_frames
        # 帧数超过上限时按步长抽，保证时长不变、体积可控
        step = 1
        if total > limit > 0:
            step = max(1, total // limit)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h)
        )
        if not writer.isOpened():
            return False

        # 已处理帧的框，按帧号排序后"沿用最近一个"
        processed = sorted(boxes_by_frame.keys())
        cur_idx = -1

        idx = 0
        written = 0
        while written < limit:
            ok, frame = cap.read()
            if not ok:
                break

            if idx % step == 0:
                # 更新到"不超过当前帧的最近一个已处理帧"
                while cur_idx + 1 < len(processed) and processed[cur_idx + 1] <= idx:
                    cur_idx += 1
                boxes = boxes_by_frame.get(processed[cur_idx], []) if cur_idx >= 0 else []

                for ri, r in enumerate(regions, start=1):
                    _draw_region(frame, r["points"], r.get("name"), ri)
                _draw_boxes(frame, boxes)

                # 角落写帧号，方便对照
                txt = f"frame {idx}"
                cv2.putText(frame, txt, (8, h - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)

                writer.write(frame)
                written += 1
            idx += 1
    finally:
        cap.release()
        try:
            writer.release()
        except Exception:  # noqa: BLE001
            pass

    return out_path.exists() and out_path.stat().st_size > 0


def boxes_from_detections(
    detections: list[dict], regions: list[dict]
) -> dict[int, list[dict]]:
    """把检测记录按帧分组，并标出每个框是否落在任一区域内。

    `inside` 由后端重算（而不是信前端），保证导出视频和页面上颜色一致。
    """
    out: dict[int, list[dict]] = {}
    for d in detections:
        cx = (d["x1"] + d["x2"]) / 2
        cy = (d["y1"] + d["y2"]) / 2
        inside = any(
            region_contains(r["points"], cx, cy, boundary_inclusive=settings.region_boundary_inclusive)
            for r in regions
        )
        out.setdefault(d["frame_index"], []).append({**d, "inside": inside})
    return out
