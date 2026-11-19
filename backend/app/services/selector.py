"""自适应模态选择 —— 本项目的核心逻辑。

为什么单独一个模块：
1. 它是需求 FR-06 的核心，必须能被**独立测试**（不依赖数据库、不依赖模型）；
2. 阈值要反复调，隔离出来改起来不会牵动其它地方；
3. 以后想从规则式升级成学习式（小分类器），只需要替换 `decide_mode` 的实现，
   调用方一行都不用改。

**当前是规则式**，依据可见光帧的三个指标（亮度/对比度/清晰度）+ 模态可用性。
阈值来自 `settings.selector_*`，是待标定的经验值，必须用基线实验重定。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.models.enums import DetectionMode
from app.services.imaging import ImageStats


@dataclass
class ModeDecision:
    mode: DetectionMode
    reason: str
    # 便于落库/前端展示的判定依据
    evidence: dict

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def decide_mode(
    *,
    has_rgb: bool,
    has_ir: bool,
    stats_rgb: ImageStats | None = None,
) -> ModeDecision:
    """按规则挑一个检测模式，并给出**人能读懂**的理由。

    判定用可见光帧的统计量，因为"光照条件"只有可见光能反映；
    热红外的亮度值由探测器增益决定，不能当环境光用（这点很容易搞错）。

    优先级（与 README §7.3 一致）：
        模态缺失   → 退到唯一可用的那个
        低照度     → 热红外
        质量差     → 双模态协同
        否则       → 可见光
    """
    ev: dict = {"has_rgb": has_rgb, "has_ir": has_ir}
    if stats_rgb is not None:
        ev.update(stats_rgb.as_dict())

    # ---- 1. 模态可用性优先：缺哪个就不能用哪个 ----
    if not has_rgb and not has_ir:
        # 调用方应提前拦掉；这里作为最后防线，退回 rgb 让上层报错
        return ModeDecision(DetectionMode.rgb, "无可用模态", ev)

    if not has_ir:
        return ModeDecision(DetectionMode.rgb, "红外通道缺失，使用可见光", ev)

    if not has_rgb:
        return ModeDecision(DetectionMode.ir, "可见光通道缺失，使用热红外", ev)

    # ---- 2. 亮度：低照度优先热红外 ----
    if stats_rgb is None:
        return ModeDecision(DetectionMode.rgb, "无法读取可见光统计量，默认可见光", ev)

    dark = settings.selector_dark_threshold
    contrast_th = settings.selector_contrast_threshold
    sharp_th = settings.selector_sharpness_threshold

    if stats_rgb.brightness < dark:
        return ModeDecision(
            DetectionMode.ir,
            f"低照度（亮度均值={stats_rgb.brightness:.1f} < {dark:.0f}），切热红外",
            ev,
        )

    # ---- 3. 图像质量：糊/低对比时用两路互补 ----
    bad_contrast = stats_rgb.contrast < contrast_th
    bad_sharp = stats_rgb.sharpness < sharp_th
    if bad_contrast or bad_sharp:
        bits = []
        if bad_contrast:
            bits.append(f"对比度低({stats_rgb.contrast:.1f} < {contrast_th:.0f})")
        if bad_sharp:
            bits.append(f"清晰度低({stats_rgb.sharpness:.0f} < {sharp_th:.0f})")
        return ModeDecision(
            DetectionMode.fusion,
            "图像质量差（" + "、".join(bits) + "），启用双模态协同",
            ev,
        )

    # ---- 4. 正常情况 ----
    return ModeDecision(
        DetectionMode.rgb,
        f"光照与质量正常（亮度={stats_rgb.brightness:.1f}，"
        f"对比度={stats_rgb.contrast:.1f}），使用可见光",
        ev,
    )


def validate_manual_mode(
    requested: DetectionMode, *, has_rgb: bool, has_ir: bool
) -> None:
    """手动模式要校验输入是否匹配（需求 FR-05：不匹配就提示原因，不能硬跑）。"""
    from app.core.errors import ApiError

    if requested == DetectionMode.ir and not has_ir:
        raise ApiError(
            "MODE_INPUT_MISMATCH",
            "请求热红外模式，但该媒体没有红外通道",
            422,
            {"has_ir": has_ir},
        )
    if requested == DetectionMode.fusion and not (has_rgb and has_ir):
        raise ApiError(
            "MODE_INPUT_MISMATCH",
            "请求双模态模式，但可见光与红外没有同时提供",
            422,
            {"has_rgb": has_rgb, "has_ir": has_ir},
        )
    if requested == DetectionMode.rgb and not has_rgb:
        raise ApiError("MODE_INPUT_MISMATCH", "请求可见光模式，但没有可见光帧", 422)
