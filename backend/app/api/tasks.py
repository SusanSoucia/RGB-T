"""检测任务（docs/api.md §7）。

MVP 阶段**同步执行**：POST 返回时任务已经跑完。
好处是前端逻辑简单、调试直观；坏处是长视频会阻塞请求。
所以 `settings.max_process_frames` 限制了单次处理的帧数。

后续要改成异步（后台任务 + 轮询）时，只需把 `run_task` 丢进
BackgroundTasks 或队列，接口形状不用变——前端本来就在轮询状态。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import current_user, get_db, owned_or_admin
from app.core.errors import ApiError, not_found
from app.models import Detection, DetectTask, FrameResult, Media, MediaStatus, User
from app.models.enums import TaskStatus
from app.schemas import DetectionOut, FrameOut, Page, TaskCreate, TaskOut
from app.services.frames import frame_image_path
from app.services.pipeline import run_task

router = APIRouter(prefix="/detect-tasks", tags=["detect"])


def _get_task(db: Session, task_id: int, user: User) -> DetectTask:
    task = db.get(DetectTask, task_id)
    if task is None:
        raise not_found("检测任务")
    owned_or_admin(user, task.owner_id)
    return task


@router.post("", response_model=TaskOut, status_code=201, summary="发起检测")
def create_task(
    payload: TaskCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    media = db.get(Media, payload.media_id)
    if media is None:
        raise not_found("媒体")
    owned_or_admin(user, media.owner_id)

    if media.status != MediaStatus.ready:
        raise ApiError(
            "MEDIA_UNSUPPORTED_FORMAT",
            f"媒体状态为 {media.status.value}，无法检测（{media.error_message or '未就绪'}）",
            422,
        )

    task = DetectTask(
        owner_id=user.id,
        media_id=media.id,
        requested_mode=payload.requested_mode,
        status=TaskStatus.pending,
        queued_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    run_task(db, task, media)
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.get("", response_model=Page[TaskOut], summary="我的检测任务")
def list_tasks(
    media_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    stmt = select(DetectTask)
    if user.role.value != "admin":
        stmt = stmt.where(DetectTask.owner_id == user.id)
    if media_id is not None:
        stmt = stmt.where(DetectTask.media_id == media_id)
    rows = db.scalars(
        stmt.order_by(DetectTask.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[TaskOut](
        items=[TaskOut.model_validate(r) for r in rows],
        total=len(db.scalars(stmt).all()), page=page, page_size=page_size,
    )


@router.get("/{task_id}", response_model=TaskOut, summary="任务详情")
def get_task(
    task_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    return TaskOut.model_validate(_get_task(db, task_id, user))


@router.get("/{task_id}/frames", response_model=list[FrameOut], summary="帧级结果（时间轴）")
def get_task_frames(
    task_id: int,
    intrusion_only: bool = Query(False, description="只看有侵入的帧"),
    with_target: bool = Query(False, description="只看检出了目标的帧"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[FrameOut]:
    task = _get_task(db, task_id, user)
    stmt = select(FrameResult).where(FrameResult.task_id == task.id)
    if intrusion_only:
        stmt = stmt.where(FrameResult.intrusion_count > 0)
    if with_target:
        stmt = stmt.where(FrameResult.target_count > 0)
    rows = db.scalars(stmt.order_by(FrameResult.frame_index)).all()

    out: list[FrameOut] = []
    for r in rows:
        item = FrameOut.model_validate(r)
        item.has_image = frame_image_path(task.media_id, r.frame_index).exists()
        out.append(item)
    return out


@router.get(
    "/{task_id}/detections",
    response_model=list[DetectionOut],
    summary="某一帧的检测框",
)
def get_task_detections(
    task_id: int,
    frame_index: int | None = Query(None, description="不传则返回全部"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[DetectionOut]:
    task = _get_task(db, task_id, user)
    stmt = select(Detection).where(Detection.task_id == task.id)
    if frame_index is not None:
        stmt = stmt.where(Detection.frame_index == frame_index)
    rows = db.scalars(stmt.order_by(Detection.frame_index, Detection.id)).all()
    return [DetectionOut.model_validate(r) for r in rows]
