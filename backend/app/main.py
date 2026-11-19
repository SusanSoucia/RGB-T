"""后端入口。

分层约定（不要破坏）：
    app/api/        ← HTTP 层：只做参数校验、鉴权、调用服务、返回 schema
    app/services/   ← 业务层：不碰 HTTP，可被脚本/测试直接调用
    app/models/     ← ORM
    app/schemas/    ← 请求/响应模型
    app/core/       ← 配置、安全、依赖、错误

依赖方向单向：api → services → models/schemas。services 不许 import api。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import api_router
from app.core.config import settings  # noqa: F401
from app.core.errors import ApiError
from app.db.session import engine

# MVP 前端：单文件、无需构建。后续换成 Vue 时，把这里指向构建产物即可。
FRONTEND_DIR = Path("/app/frontend/mvp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        print("[info] 数据库连接正常")
        print(f"[info] 推理后端 = {settings.detector_backend}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 数据库连接失败: {exc}")
    yield


app = FastAPI(
    title="UAV Alert API",
    version="0.2.0",
    lifespan=lifespan,
    description="反无人机检测与预警系统。接口契约见 docs/api.md。",
)


# ---- 统一错误响应（docs/api.md §2.2）----
@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )


app.include_router(api_router)


# ---- 健康检查（保留，环境自检用）----
@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "service": "uav-alert-api"}


@app.get("/health/db", tags=["health"])
def health_db():
    try:
        with engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
            tables = conn.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_schema = 'public'"
                )
            ).scalar_one()
        return {
            "db": "ok",
            "version": version,
            "public_tables": tables,
            "detector_backend": settings.detector_backend,
        }
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"db": "error", "detail": str(exc)}, status_code=503)


# ---- MVP 前端 ----
if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")
