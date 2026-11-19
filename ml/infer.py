"""统一推理接口 —— **后端只认这一个文件**。

README §8 的约定：
    输入: 帧(RGB[, IR]) + 模式
    输出: {boxes, scores, mode_actual, reason, elapsed_ms}

这个文件负责前半句（单模态）；自适应选择策略在 selector/，双模态融合在
models/fusion/。后端 import 这里，不要让它直接碰 ultralytics。

坐标约定：**输出的框一律是归一化 [0,1]**，与数据库 detections 表一致。
后端拿 `media.width/height` 乘一下就是像素坐标。

用法：
    from ml.infer import UAVDetector
    det = UAVDetector("weights/rgb_best.pt")
    boxes = det.detect(frame_bgr)
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Box:
    """一个检测结果。坐标为归一化 [0,1]。"""

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
        """框中心点 —— 区域侵入判定用的就是它（需求 FR-09）。"""
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


class UAVDetector:
    """单模态检测器。

    一个实例对应一份权重（RGB 或 IR）。不要用一个实例混跑两种模态，
    权重不同，容易把 RGB 权重拿去跑 IR 然后奇怪为什么效果差。
    """

    def __init__(
        self,
        weights: str | Path,
        imgsz: int = 640,
        conf: float = 0.25,
        iou: float = 0.45,
        device: str = "0",
        half: bool = True,
        warmup: bool = True,
    ) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                f"缺少 ultralytics（{exc}）。推理需要 GPU 镜像，"
                f"或在本机装好 ml/requirements.txt。"
            ) from exc

        self.weights = str(weights)
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = device
        self.half = half
        self.model = YOLO(self.weights)

        if warmup:
            # 首次推理会把 CUDA kernel 编译等开销算进去，
            # 不预热的话第一个请求的耗时会难看得离谱（§3.2.2 要测耗时）
            import numpy as np

            dummy = np.zeros((imgsz, imgsz, 3), dtype="uint8")
            for _ in range(2):
                self.detect(dummy, warmup=False)

    def detect(self, image_bgr, warmup: bool = False) -> list[Box]:
        """对单帧做检测。

        Args:
            image_bgr: OpenCV 读出来的 BGR 图（HWC, uint8）。灰度图也行，
                       ultralytics 内部会转 3 通道——这正好让红外图能复用
                       RGB 预训练主干，不需要额外处理。
        Returns:
            Box 列表，坐标已归一化并裁剪到 [0,1]。
        """
        t0 = time.perf_counter()
        results = self.model.predict(
            source=image_bgr,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            half=self.half,
            verbose=False,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        boxes: list[Box] = []
        h, w = image_bgr.shape[:2]
        for r in results:
            if r.boxes is None:
                continue
            names = r.names or {}
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                # 用模型看到的图像尺寸归一化，避免预处理缩放导致偏差
                bw = float(r.orig_shape[1]) if r.orig_shape else w
                bh = float(r.orig_shape[0]) if r.orig_shape else h
                boxes.append(
                    Box(
                        x1=_clip(x1 / bw),
                        y1=_clip(y1 / bh),
                        x2=_clip(x2 / bw),
                        y2=_clip(y2 / bh),
                        score=float(b.conf[0]),
                        class_name=str(names.get(int(b.cls[0]), "uav")),
                    )
                )

        self.last_elapsed_ms = elapsed_ms
        return boxes


def _clip(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def main() -> int:
    ap = argparse.ArgumentParser(description="对单张图/一个目录做推理，验证权重可用")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--source", required=True, help="图片路径或目录")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args()

    import cv2

    det = UAVDetector(args.weights, imgsz=args.imgsz, conf=args.conf)
    src = Path(args.source)
    files = [src] if src.is_file() else sorted(
        p for p in src.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    )
    if not files:
        print(f"[FAIL] {src} 下没有图片")
        return 1

    for f in files[:20]:
        img = cv2.imread(str(f))
        if img is None:
            print(f"  [skip] 读不了 {f.name}")
            continue
        boxes = det.detect(img)
        print(f"\n{f.name}  {img.shape[1]}×{img.shape[0]}  "
              f"检出 {len(boxes)} 个  耗时 {det.last_elapsed_ms:.1f}ms")
        for b in sorted(boxes, key=lambda x: -x.score)[:5]:
            print(f"    {b.class_name} score={b.score:.3f} "
                  f"box=({b.x1:.3f},{b.y1:.3f},{b.x2:.3f},{b.y2:.3f}) "
                  f"center=({b.center[0]:.3f},{b.center[1]:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
