"""枚举定义。

统一用 `native_enum=False`，落库是 **VARCHAR 而不是 Postgres 原生 ENUM**。

注意一个容易误解的点：SQLAlchemy 2.0 的 `Enum` **默认不生成 CHECK 约束**
（`create_constraint` 默认 False），所以这些列目前是**纯粹的 varchar**。
这是一个有意的取舍：

- **好处**：后期加/改枚举值（比如给告警加 `dismissed` 状态、给模式加一个
  `rgb_ir_early`）**不需要任何迁移**，改一下这里的 Python 枚举即可。这个项目
  后期必然要调，原生 ENUM 每次都要 `ALTER TYPE`，很麻烦。
- **代价**：数据库层不拦非法值，写错值（比如 `'succeded'`）会静默存进去。
  所以**合法性由应用层保证**——Pydantic schema 里用同样的枚举做校验。

如果你想要数据库层的硬约束，把对应列改成：

    SAEnum(Xxx, name="xxx", native_enum=False, length=16, create_constraint=True)

代价是以后加值要写迁移。
"""

from enum import Enum


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class MediaType(str, Enum):
    video = "video"
    image = "image"


class MediaStatus(str, Enum):
    uploaded = "uploaded"   # 已上传，未解析
    parsing = "parsing"     # 正在解析/分帧
    ready = "ready"         # 可检测
    failed = "failed"


class DetectionMode(str, Enum):
    """实际用到的检测模式（双模态输出统一到参考画面）。"""
    rgb = "rgb"
    ir = "ir"
    fusion = "fusion"


class RequestMode(str, Enum):
    """用户可请求的模式，多一个 auto。"""
    rgb = "rgb"
    ir = "ir"
    fusion = "fusion"
    auto = "auto"


class ReferenceModality(str, Enum):
    """坐标系基准。本项目建议以 rgb 为基准（UI 展示彩色图）。"""
    rgb = "rgb"
    ir = "ir"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    timeout = "timeout"


class RegionShape(str, Enum):
    rect = "rect"
    polygon = "polygon"


class AlertStatus(str, Enum):
    """告警业务状态。确认只表示"已查看并确认"，不代表重新判定检测真伪。"""
    unconfirmed = "unconfirmed"
    confirmed = "confirmed"
