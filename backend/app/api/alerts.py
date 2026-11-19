"""告警（docs/api.md §8）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import current_user, get_db, owned_or_admin
from app.core.errors import ApiError, not_found
from app.models import Alert, AlertStatus, Media, User
from app.schemas import AlertConfirmOut, AlertOut, Page
from app.services.frames import frame_image_path

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _enrich(db: Session, alerts: list[Alert]) -> list[AlertOut]:
    """补上展示用字段：缩略图地址、媒体名。

    媒体名一次查完再映射，避免每行都去查一次库（N+1）。
    """
    media_ids = {a.media_id for a in alerts}
    names: dict[int, str] = {}
    if media_ids:
        rows = db.scalars(select(Media).where(Media.id.in_(media_ids))).all()
        names = {m.id: m.original_name for m in rows}

    out: list[AlertOut] = []
    for a in alerts:
        item = AlertOut.model_validate(a)
        item.media_name = names.get(a.media_id)
        if frame_image_path(a.media_id, a.frame_index).exists():
            # 相对接口路径，前端自己拼 base 并带 token 取图
            item.snapshot_url = f"/media/{a.media_id}/frames/{a.frame_index}"
        out.append(item)
    return out


@router.get("", response_model=Page[AlertOut], summary="告警列表")
def list_alerts(
    status: AlertStatus | None = Query(None),
    media_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[AlertOut]:
    stmt = select(Alert)
    if user.role.value != "admin":
        stmt = stmt.where(Alert.owner_id == user.id)
    if status is not None:
        stmt = stmt.where(Alert.status == status)
    if media_id is not None:
        stmt = stmt.where(Alert.media_id == media_id)

    rows = db.scalars(
        stmt.order_by(Alert.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[AlertOut](
        items=_enrich(db, list(rows)),
        total=len(db.scalars(stmt).all()), page=page, page_size=page_size,
    )


@router.post("/{alert_id}/confirm", response_model=AlertConfirmOut, summary="确认告警")
def confirm_alert(
    alert_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AlertConfirmOut:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise not_found("告警")
    owned_or_admin(user, alert.owner_id)

    if alert.status == AlertStatus.confirmed:
        raise ApiError("ALERT_ALREADY_CONFIRMED", "该告警已确认过", 409)

    alert.status = AlertStatus.confirmed
    alert.confirmed_by_id = user.id
    alert.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return AlertConfirmOut.model_validate(alert)
