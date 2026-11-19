"""媒体上传与取图（docs/api.md §5）。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import current_user, get_db, owned_or_admin
from app.core.errors import ApiError, not_found
from app.models import Media, MediaStatus, MediaType, User
from app.schemas import MediaOut, Page
from app.services.frames import frame_image_path
from app.services.imaging import guess_is_video, probe_media

import cv2

router = APIRouter(prefix="/media", tags=["media"])

_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


async def _save_upload(upload: UploadFile, dest: Path) -> int:
    """分块写盘，顺便卡大小（需求 FR-03 / §3.5：超大文件要明确拒绝）。"""
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as f:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ApiError(
                        "MEDIA_TOO_LARGE",
                        f"文件超过 {settings.max_upload_mb}MB 上限",
                        413,
                    )
                f.write(chunk)
    except ApiError:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return size


@router.post("", response_model=MediaOut, status_code=201, summary="上传媒体")
async def upload_media(
    file: UploadFile = File(..., description="可见光视频或图片"),
    ir_file: UploadFile | None = File(None, description="红外文件（可选，成对时提供）"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MediaOut:
    if not file.filename:
        raise ApiError("MEDIA_UNSUPPORTED_FORMAT", "缺少文件名", 415)

    is_video = guess_is_video(file.filename, file.content_type)
    ext = Path(file.filename).suffix.lower()
    if not is_video and ext not in _IMG_EXT:
        raise ApiError(
            "MEDIA_UNSUPPORTED_FORMAT",
            f"不支持的文件类型：{ext or '未知'}",
            415,
        )

    media_dir = Path(settings.upload_dir) / "media"
    rgb_name = f"{uuid4().hex}{ext or '.bin'}"
    rgb_dest = media_dir / rgb_name
    size = await _save_upload(file, rgb_dest)

    ir_rel: str | None = None
    ir_dest: Path | None = None
    if ir_file is not None and ir_file.filename:
        ir_ext = Path(ir_file.filename).suffix.lower()
        ir_name = f"{uuid4().hex}_ir{ir_ext or '.bin'}"
        ir_dest = media_dir / ir_name
        await _save_upload(ir_file, ir_dest)
        ir_rel = f"media/{ir_name}"

    probe = probe_media(rgb_dest, is_video)
    ir_probe = probe_media(ir_dest, is_video) if ir_dest else None

    media = Media(
        owner_id=user.id,
        original_name=file.filename,
        stored_path=f"media/{rgb_name}",
        media_type=MediaType.video if is_video else MediaType.image,
        mime_type=file.content_type,
        size_bytes=size,
        width=probe.width,
        height=probe.height,
        has_ir=ir_rel is not None,
        ir_stored_path=ir_rel,
        ir_width=ir_probe.width if ir_probe else None,
        ir_height=ir_probe.height if ir_probe else None,
        fps=probe.fps if is_video else None,
        duration_ms=probe.duration_ms if is_video else None,
        total_frames=probe.total_frames if is_video else 1,
        # 视频按 5 帧抽 1 帧；图片无所谓
        frame_stride=5 if is_video else 1,
        status=MediaStatus.ready if probe.width else MediaStatus.failed,
        error_message=None if probe.width else "无法解析媒体（可能是损坏或编码不支持）",
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return MediaOut.model_validate(media)


@router.get("", response_model=Page[MediaOut], summary="我的媒体列表")
def list_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[MediaOut]:
    stmt = select(Media)
    if user.role.value != "admin":
        stmt = stmt.where(Media.owner_id == user.id)
    rows = db.scalars(
        stmt.order_by(Media.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    total = len(db.scalars(stmt).all())
    return Page[MediaOut](
        items=[MediaOut.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


def _get_owned_media(db: Session, media_id: int, user: User) -> Media:
    media = db.get(Media, media_id)
    if media is None:
        raise not_found("媒体")
    owned_or_admin(user, media.owner_id)
    return media


@router.get("/{media_id}", response_model=MediaOut, summary="媒体详情")
def get_media(
    media_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MediaOut:
    return MediaOut.model_validate(_get_owned_media(db, media_id, user))


@router.get("/{media_id}/image", summary="原始画面（用于画框）")
def get_media_image(
    media_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    media = _get_owned_media(db, media_id, user)
    path = Path(settings.upload_dir) / media.stored_path
    if not path.exists():
        raise not_found("媒体文件")
    if media.media_type == MediaType.video:
        raise ApiError(
            "MEDIA_UNSUPPORTED_FORMAT",
            "视频没有单帧原图，请先跑一次检测再按帧取图",
            422,
        )
    return FileResponse(path)


@router.delete("/{media_id}", status_code=204, response_class=Response, summary="删除媒体")
def delete_media(
    media_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """级联删除：任务、检测框、帧记录、区域、告警都会跟着删（外键 ON DELETE CASCADE）。"""
    media = _get_owned_media(db, media_id, user)
    db.delete(media)
    db.commit()
    return Response(status_code=204)


@router.get("/{media_id}/poster", summary="首帧预览图（视频也适用，用于画框）")
def get_media_poster(
    media_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """返回可画框的静态预览图。

    图片直接用原图；视频取第一帧转成 JPEG 返回（不落盘）。
    前端上传视频后要立刻画警戒区域，就需要这张图。
    """
    media = _get_owned_media(db, media_id, user)
    path = Path(settings.upload_dir) / media.stored_path
    if not path.exists():
        raise not_found("媒体文件")

    if media.media_type == MediaType.image:
        return FileResponse(path)

    cap = cv2.VideoCapture(str(path))
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise ApiError("MEDIA_UNSUPPORTED_FORMAT", "无法从视频中解出首帧", 422)

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise ApiError("INFERENCE_FAILED", "首帧编码失败", 500)
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/{media_id}/video", summary="原始视频流（用于前端播放与跳看）")
def get_media_video(
    media_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """返回原始视频文件。

    Starlette 的 FileResponse 支持 HTTP Range，所以 <video> 能拖进度条跳看。
    注意：<video src> 本身带不了 Authorization 头，前端应先用带鉴权的 fetch
    取回 blob 再播放（见 frontend/app/app.js）。
    """
    media = _get_owned_media(db, media_id, user)
    if media.media_type != MediaType.video:
        raise ApiError("MEDIA_UNSUPPORTED_FORMAT", "该媒体不是视频", 422)
    path = Path(settings.upload_dir) / media.stored_path
    if not path.exists():
        raise not_found("视频文件")
    return FileResponse(
        path,
        media_type=media.mime_type or "video/mp4",
        filename=media.original_name,
    )


@router.get("/{media_id}/frames/{frame_index}", summary="处理过的某一帧")
def get_frame_image(
    media_id: int,
    frame_index: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    _get_owned_media(db, media_id, user)
    path = frame_image_path(media_id, frame_index)
    if not path.exists():
        raise HTTPException(status_code=404, detail="该帧还没有生成，先跑一次检测")
    return FileResponse(path)
