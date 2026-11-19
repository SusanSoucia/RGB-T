"""推理适配层。

**这是整个后端里唯一知道"模型怎么跑"的地方。** 换模型、换框架、换成假的，
只改这一个文件，上层（pipeline/api）一行都不用动。

两种实现：
- `StubDetector`         —— 假检测器。模型还没训好时用它把系统跑通，
                             输出是**确定性的**（同一帧每次结果一样），方便测试和联调。
- `UltralyticsDetector` —— 真检测器，调用 `ml.infer.UAVDetector` 加载权重。

切换方式：环境变量 `DETECTOR_BACKEND=stub|ultralytics`（见 config.py）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np

from app.core.config import settings


@dataclass
class Box:
    """归一化检测框。与数据库 detections 表的坐标约定一致。"""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    class_name: str = "uav"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


class Detector(Protocol):
    name: str

    def detect(
        self, image_bgr: np.ndarray, modality: str = "rgb", frame_index: int = 0
    ) -> list[Box]: ...


def _clip(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class StubDetector:
    """假检测器：不加载任何权重，产出确定性的"像样"的框。

    设计目的是让系统**今天就能端到端跑通**。它刻意做出三种情况，
    好让"无目标 / 区域外目标 / 区域侵入"三种页面状态都能被验证到：

    - `frame_index % 7 == 0` 且 `frame_index != 0` → 该帧无目标
    - `frame_index % 5 == 0` → 该帧 2 个目标
    - 其它                  → 该帧 1 个目标

    注意 `frame_index != 0` 这个例外：单张图片的帧号恒为 0，
    如果 0 也返回空，图片场景就永远测不出目标了。

    位置由帧号推导，所以同一帧重跑结果完全一致——这对回归测试很重要。
    """

    name = "stub"

    def detect(
        self, image_bgr: np.ndarray, modality: str = "rgb", frame_index: int = 0
    ) -> list[Box]:
        if frame_index != 0 and frame_index % 7 == 0:
            return []

        count = 2 if frame_index % 5 == 0 else 1
        boxes: list[Box] = []
        shift = 100 if modality == "ir" else 0  # 红外给一点位移，模拟两路不完全重合

        for k in range(count):
            seed = (frame_index * 37 + k * 13 + shift) % 100
            cx = 0.15 + 0.70 * (seed / 100.0)
            cy = 0.20 + 0.60 * (((seed * 7) % 100) / 100.0)
            w = 0.10 + 0.02 * (seed % 5)
            h = w * 0.9
            score = 0.55 + 0.40 * (((seed * 3) % 100) / 100.0)

            x1, y1 = _clip(cx - w / 2), _clip(cy - h / 2)
            x2, y2 = _clip(cx + w / 2), _clip(cy + h / 2)
            if x2 - x1 <= 1e-6 or y2 - y1 <= 1e-6:
                continue
            boxes.append(Box(x1=x1, y1=y1, x2=x2, y2=y2, score=round(score, 4)))
        return boxes


class UltralyticsDetector:
    """真检测器。权重没准备好时会抛出明确的错误，而不是静默返回空。"""

    name = "ultralytics"

    def __init__(self, weights: str, imgsz: int | None = None) -> None:
        if not weights:
            from app.core.errors import ApiError

            raise ApiError(
                "MODEL_NOT_LOADED",
                "未配置模型权重（RGB_WEIGHTS / IR_WEIGHTS）",
                503,
            )
        from ml.infer import UAVDetector  # 延迟导入：没有 torch 时不影响其他接口

        self._det = UAVDetector(
            weights,
            imgsz=imgsz or settings.default_imgsz,
            conf=settings.default_confidence,
            iou=settings.default_iou,
            device="0",
        )

    def detect(
        self, image_bgr: np.ndarray, modality: str = "rgb", frame_index: int = 0
    ) -> list[Box]:
        raw = self._det.detect(image_bgr)
        return [
            Box(
                x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2,
                score=b.score, class_name=b.class_name,
            )
            for b in raw
        ]


_detector: Detector | None = None


def get_detector(modality: str = "rgb") -> Detector:
    """按配置返回检测器（进程内缓存）。"""
    global _detector
    if settings.detector_backend == "stub":
        if _detector is None:
            _detector = StubDetector()
        return _detector

    # 真实后端：RGB 和 IR 是两份权重，不能共用一个实例
    weights = settings.ir_weights if modality == "ir" else settings.rgb_weights
    return UltralyticsDetector(weights)


def reset_detector() -> None:
    """测试用：清掉缓存，让配置变更生效。"""
    global _detector
    _detector = None


def _iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def merge_boxes(
    boxes_rgb: list[Box], boxes_ir: list[Box], iou_threshold: float = 0.5
) -> list[Box]:
    """结果级融合的最小实现：两路框按 IoU 去重，保留分高的那个。

    注意：这只是"结果级融合"的草案（README §7.2 里最简单的路线），
    不是特征级融合。好处是**零训练成本**，单模态模型训好就能直接用。
    """
    merged = sorted(boxes_rgb + boxes_ir, key=lambda b: -b.score)
    kept: list[Box] = []
    for b in merged:
        if all(_iou(b, k) < iou_threshold for k in kept):
            kept.append(b)
    return kept
