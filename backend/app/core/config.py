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
    jwt_algorithm: str = "HS256"

    # 是否开放自主注册。
    # 需求说明书 V1.0 的 FR-01 原本写的是"不开放自主注册"，**经确认该条为笔误**，
    # 实际要支持用户在登录页自行注册，所以默认开启。
    # 自主注册只能拿到 user 角色，注册不出管理员。
    # 如需临时关闭（比如演示前锁定），把 ALLOW_SELF_REGISTER 设为 false 即可。
    allow_self_register: bool = True

    # 前端独立部署时的跨域来源（独立前端跑在 5173）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # 存储（与 compose 里的挂载点一致）
    upload_dir: str = "/data/uploads"
    snapshot_dir: str = "/data/uploads/snapshots"
    frames_dir: str = "/data/uploads/frames"
    max_upload_mb: int = 2048

    # 推理默认参数（写进任务记录，便于复现）
    default_confidence: float = 0.25
    default_iou: float = 0.45
    default_imgsz: int = 640

    # ---- 检测管线 ----
    # MVP 阶段每个任务最多处理多少帧，防止一段长视频把单次请求拖死
    max_process_frames: int = 30
    # 推理后端：stub（假框，模型没训好时用）/ ultralytics（接真实权重）
    detector_backend: str = "stub"
    rgb_weights: str = ""
    ir_weights: str = ""

    # ---- 标注视频导出 ----
    render_dir: str = "/data/uploads/renders"
    # 导出视频最多渲染多少帧（防止长视频把 CPU 占满）
    render_max_frames: int = 900

    # ---- 自适应模态选择阈值（需求 FR-06 / README §7.3）----
    # 注意：这三个值是**待标定**的初始经验值，必须用基线实验重定
    #   亮度均值低于此值 → 判为低照度，倾向热红外
    selector_dark_threshold: float = 40.0
    #   对比度（灰度标准差）低于此值 → 判为低质量
    selector_contrast_threshold: float = 25.0
    #   清晰度（拉普拉斯方差）低于此值 → 判为模糊
    selector_sharpness_threshold: float = 100.0

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
