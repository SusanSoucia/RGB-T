"""应用配置。

值全部来自环境变量（由 docker-compose 注入），不在代码里硬编码密码。
Host 直接跑时，先 `export` 同名环境变量，或用 `docker compose run` 进容器。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # 数据库：容器内主机名是 db，不是 localhost
    database_url: str = "postgresql+psycopg://uav:uav@db:5432/uav"

    # 认证
    secret_key: str = "dev-only-change-me"
    access_token_expire_minutes: int = 720

    # 存储（与 compose 里的挂载点一致）
    upload_dir: str = "/data/uploads"
    snapshot_dir: str = "/data/uploads/snapshots"
    max_upload_mb: int = 2048

    # 推理默认参数（写进任务记录，便于复现）
    default_confidence: float = 0.25
    default_iou: float = 0.45
    default_imgsz: int = 640

    # ---- 告警归并（视频场景必须，见 docs/api.md §8.1）----
    # 同一 (media, region) 上，间隔小于该秒数且位置相近的判定并入原告警，
    # 只累加 occurrence_count，不新增记录。避免 25fps 下告警刷屏。
    alert_merge_window_s: float = 3.0
    # 中心点距离阈值（归一化单位）
    alert_merge_distance: float = 0.1

    # ---- 侵入判定 ----
    # True = 落在区域边界上的点视为区域内（需求里的候选规则）
    region_boundary_inclusive: bool = True

    # ---- 前端分页 ----
    max_page_size: int = 100


settings = Settings()
