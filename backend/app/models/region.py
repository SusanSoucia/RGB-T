"""警戒区域（需求 FR-08）。

坐标一律**归一化到 [0,1]**，存 JSONB 的点序列：

- 矩形：4 个角点，`[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]`
- 多边形：N 个顶点（"描绘边框"的扩展空间）

统一成点序列的好处：前端 Canvas 只有一套绘制/编辑逻辑，后端只有一套
"点是否在区域内"的射线法判定，不用为矩形和平行维护两套代码。
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import RegionShape
from app.models.mixins import TimestampMixin


class Region(Base, TimestampMixin):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 区域绑定到具体媒体画面，不默认跨场景复用（FR-08 明确要求）
    media_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="默认区域", server_default="默认区域"
    )
    shape_type: Mapped[RegionShape] = mapped_column(
        SAEnum(RegionShape, name="region_shape", native_enum=False, length=16),
        nullable=False,
        default=RegionShape.rect,
        server_default=RegionShape.rect.value,
    )

    # [[x, y], ...]，全部归一化到 [0,1]；顺序为多边形顶点顺序
    points: Mapped[list] = mapped_column(JSONB, nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    note: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Region {self.id} media={self.media_id} {self.shape_type}>"
