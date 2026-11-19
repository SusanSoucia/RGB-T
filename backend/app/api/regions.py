"""警戒区域（docs/api.md §6）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import current_user, get_db, owned_or_admin
from app.core.errors import not_found
from app.models import Media, Region, User
from app.schemas import RegionIn, RegionOut

router = APIRouter(prefix="/regions", tags=["regions"])


def _get_media(db: Session, media_id: int, user: User) -> Media:
    media = db.get(Media, media_id)
    if media is None:
        raise not_found("媒体")
    owned_or_admin(user, media.owner_id)
    return media


@router.post("", response_model=RegionOut, status_code=201, summary="创建区域")
def create_region(
    payload: RegionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RegionOut:
    _get_media(db, payload.media_id, user)

    region = Region(
        owner_id=user.id,
        media_id=payload.media_id,
        name=payload.name,
        shape_type=payload.shape_type,
        # JSONB 存 [[x,y],...]，与前端提交格式一致
        points=[[float(p[0]), float(p[1])] for p in payload.points],
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return RegionOut.model_validate(region)


@router.get("", response_model=list[RegionOut], summary="按媒体查区域")
def list_regions(
    media_id: int = Query(..., description="媒体 ID"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[RegionOut]:
    _get_media(db, media_id, user)
    rows = db.scalars(
        select(Region).where(Region.media_id == media_id).order_by(Region.id.desc())
    ).all()
    return [RegionOut.model_validate(r) for r in rows]


@router.delete(
    "/{region_id}",
    status_code=204,
    # 204 不能带响应体，必须显式声明 Response，否则 FastAPI 启动时直接断言失败
    response_class=Response,
    summary="删除区域",
)
def delete_region(
    region_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    region = db.get(Region, region_id)
    if region is None:
        raise not_found("区域")
    owned_or_admin(user, region.owner_id)
    db.delete(region)
    db.commit()
