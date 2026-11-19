"""数据库会话与依赖。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# pool_pre_ping：连接空闲被网络掐断后自动重连，避免 "server closed the connection unexpectedly"
# expire_on_commit=False：commit 后仍可读对象属性，返回给接口层更方便
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个会话，用完关掉。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
