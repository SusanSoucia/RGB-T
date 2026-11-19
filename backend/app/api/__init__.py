"""API 路由汇总。

所有子路由在这里挂一次，main.py 只需 include 这一个 router。
加新模块（如 export、users）时在这里补一行即可。
"""

from fastapi import APIRouter

from app.api import alerts, auth, media, regions, tasks

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(media.router)
api_router.include_router(regions.router)
api_router.include_router(tasks.router)
api_router.include_router(alerts.router)

__all__ = ["api_router"]
