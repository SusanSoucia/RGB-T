"""后端入口。

目前只提供健康检查，用来确认「服务活着 + 能连上数据库 + 表已建好」。
业务路由（auth / media / detect / region / alert / export）按模块加到 app/api/ 下。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings  # noqa: F401  (统一配置入口，后续路由会用)
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时探一次库。失败只告警不退出：数据库可能还在初始化，
    # 让服务起来、用 /health/db 暴露问题，比直接崩掉好排查。
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        print("[info] 数据库连接正常")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 数据库连接失败: {exc}")
    yield


app = FastAPI(title="UAV Alert API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "uav-alert-api"}


@app.get("/health/db")
def health_db():
    """连库 + 统计 public 下的表数量。

    public_tables 用来快速判断迁移有没有跑：
    空库是 0；跑完当前所有迁移后是 8（7 张业务表 + alembic_version）。
    注意这个数每加一张表就会变，只当粗检查用。
    """
    try:
        with engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
            tables = conn.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_schema = 'public'"
                )
            ).scalar_one()
        return {"db": "ok", "version": version, "public_tables": tables}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"db": "error", "detail": str(exc)}, status_code=503)
