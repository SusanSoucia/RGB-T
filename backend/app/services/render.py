"""标注视频导出。

把「警戒区域轮廓 + 检测框」烧进画面，输出可下载播放的视频。

## 三条实现要点

1. **编码**：OpenCV 自带编码器没有 libx264，只能写 mp4v 或 VP8/VP9，
   而 **mp4v 在 Chromium 里放不了**。所以先用 VP8 写 WebM，
   再用系统 `ffmpeg` 转成 **H.264(MP4)**——MP4 通用性最好（PPT、手机、浏览器都能放）。
   没有 ffmpeg 时自动退回 WebM，不会报错。

2. **中文标签**：`cv2.putText` 用 Hershey 矢量字体，**只支持 ASCII**，
   直接写中文会变成问号。镜像里装了 `fonts-wqy-microhei`，
   所以这里用 **PIL + 中文字体**绘制；找不到字体时退回 `Region N`。

3. **区域每帧都画，检测框沿用最近的处理帧**：抽帧步长通常 >1，
   没有那些帧的检测结果，沿用最近一个已处理帧的框，视频看起来才连续。
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
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
COLOR_TEXT_BG = (32, 32, 32)

# 中文字体查找顺序：
#   1) 仓库里自带的字体（推荐：把任意开源中文字体丢进 backend/app/assets/fonts/）
#   2) 系统字体（如果镜像里装过 fonts-wqy-microhei / noto-cjk）
# 都没有时，视频里的区域名退回 "Region N"（cv2 的 Hershey 字体只支持 ASCII）。
_REPO_FONT_DIR = Path("/app/assets/fonts")
_FONT_CANDIDATES = (
    str(_REPO_FONT_DIR / "wqy-microhei.ttc"),
    str(_REPO_FONT_DIR / "NotoSansCJK-Regular.ttc"),
    str(_REPO_FONT_DIR / "SourceHanSansCN-Regular.otf"),
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


@lru_cache(maxsize=1)
def cjk_font_path() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    # 兜底：assets/fonts 下任何 .ttf/.ttc/.otf 都认
    if _REPO_FONT_DIR.is_dir():
        for f in sorted(_REPO_FONT_DIR.glob("*")):
            if f.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                return str(f)
    return None


@lru_cache(maxsize=16)
def _load_font(size: int):
    path = cjk_font_path()
    if not path:
        return None
    try:
        from PIL import ImageFont

        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return None


def draw_text(
    img: np.ndarray,
    text: str,
    x: int,
    y: int,
    color_bgr: tuple[int, int, int],
    size: int = 18,
    bg_bgr: tuple[int, int, int] | None = None,
) -> None:
    """在 BGR 图上画一段文字（支持中文），自动选 PIL 或 cv2。

    y 是文本框顶边；绘制时会在文字下方留 4px 内边距。
    """
    if not text:
        return

    font = _load_font(size)
    if font is not None:
        from PIL import Image, ImageDraw

        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = 4
        if bg_bgr is not None:
            draw.rectangle([x, y, x + tw + pad * 2, y + th + pad * 2], fill=tuple(reversed(bg_bgr)))
        draw.text((x + pad, y + pad - bbox[1]), text, font=font, fill=tuple(reversed(color_bgr)))
        img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        return

    # 没有中文字体：退回 cv2，只能画 ASCII
    safe = text if text.isascii() else "Region"
    scale, thick = 0.5, 1
    (tw, th), base = cv2.getTextSize(safe, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    if bg_bgr is not None:
        cv2.rectangle(img, (x, y), (x + tw + 6, y + th + base + 4), bg_bgr, -1)
    cv2.putText(img, safe, (x + 3, y + th + 3),
                cv2.FONT_HERSHEY_SIMPLEX, scale, color_bgr, thick, cv2.LINE_AA)


def _label_for(name: str | None, idx: int) -> str:
    """区域名：有中文字体就用原名，否则退回 Region N。"""
    text = (name or "").strip()
    if not text:
        return f"Region {idx}"
    if cjk_font_path() is None:
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            return f"Region {idx}"
    return text


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

    x, y = int(pts[0][0]), int(pts[0][1])
    draw_text(img, _label_for(name, idx), x + 2, max(0, y - 24), COLOR_REGION, 16, COLOR_TEXT_BG)


def _draw_boxes(img: np.ndarray, boxes: list[dict]) -> None:
    h, w = img.shape[:2]
    for b in boxes:
        x1 = int(round(b["x1"] * w)); y1 = int(round(b["y1"] * h))
        x2 = int(round(b["x2"] * w)); y2 = int(round(b["y2"] * h))
        color = COLOR_BOX_HOT if b.get("inside") else COLOR_BOX
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

        label = f"{b['score']:.2f}" + (" IN" if b.get("inside") else "")
        draw_text(img, label, x1, max(0, y1 - 22), (255, 255, 255), 14, color)


def render_video(
    *,
    src_path: Path,
    out_path: Path,
    regions: list[dict],
    boxes_by_frame: dict[int, list[dict]],
    max_frames: int | None = None,
) -> bool:
    """把标注烧进画面，先写成 WebM(VP8)。成功返回 True。"""
    cap = cv2.VideoCapture(str(src_path))
    if not cap.isOpened():
        return False

    writer = None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if w <= 0 or h <= 0:
            return False

        limit = max_frames or settings.render_max_frames
        step = 1
        if total > limit > 0:
            step = max(1, total // limit)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h))
        if not writer.isOpened():
            return False

        processed = sorted(boxes_by_frame.keys())
        cur_idx = -1
        idx = written = 0

        while written < limit:
            ok, frame = cap.read()
            if not ok:
                break

            if idx % step == 0:
                while cur_idx + 1 < len(processed) and processed[cur_idx + 1] <= idx:
                    cur_idx += 1
                boxes = boxes_by_frame.get(processed[cur_idx], []) if cur_idx >= 0 else []

                for ri, r in enumerate(regions, start=1):
                    _draw_region(frame, r["points"], r.get("name"), ri)
                _draw_boxes(frame, boxes)

                draw_text(frame, f"frame {idx}", 8, h - 30, (225, 225, 225), 14, (45, 45, 45))

                writer.write(frame)
                written += 1
            idx += 1
    finally:
        cap.release()
        if writer is not None:
            try:
                writer.release()
            except Exception:  # noqa: BLE001
                pass

    return out_path.exists() and out_path.stat().st_size > 0


def _ffmpeg_exe() -> str | None:
    """找一个能用的 ffmpeg。

    优先系统 ffmpeg（如果镜像里有），否则用 pip 包 `imageio-ffmpeg`
    自带的那份静态二进制。后者专门用来避开 apt 装 ffmpeg 的坑：
    apt 要拉 269 个包 / 222MB，受限网络下会反复失败。
    """
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def ffmpeg_available() -> bool:
    return _ffmpeg_exe() is not None


def transcode_to_mp4(src: Path, dst: Path, timeout_s: int = 300) -> bool:
    """WebM → H.264 MP4。没有 ffmpeg 或失败都返回 False（由调用方退回 WebM）。"""
    exe = _ffmpeg_exe()
    if not exe:
        return False
    cmd = [
        exe, "-y", "-loglevel", "error",
        "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except Exception:  # noqa: BLE001
        return False
    return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def export_annotated(
    *,
    src_path: Path,
    out_dir: Path,
    stem: str,
    regions: list[dict],
    boxes_by_frame: dict[int, list[dict]],
    prefer_mp4: bool = True,
) -> tuple[Path, str] | None:
    """渲染并（可选）转码，返回 (文件路径, mime)。失败返回 None。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    webm = out_dir / f"{stem}.webm"

    if not render_video(
        src_path=src_path, out_path=webm,
        regions=regions, boxes_by_frame=boxes_by_frame,
    ):
        return None

    if prefer_mp4 and ffmpeg_available():
        mp4 = out_dir / f"{stem}.mp4"
        if mp4.exists() and mp4.stat().st_mtime >= webm.stat().st_mtime:
            return mp4, "video/mp4"
        if transcode_to_mp4(webm, mp4):
            return mp4, "video/mp4"

    return webm, "video/webm"


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
