"""检测管线编排。

一条任务跑完的完整链路：

    读帧 → 自适应选模态（或校验手动模式）→ 逐帧检测
         → 落框（detections）→ 侵入判定 → 告警归并（alerts）
         → 帧级汇总（frame_results）→ 回填任务状态与耗时

设计要点：
- 这里**不碰 HTTP**，只依赖 Session 和 services，所以可以被脚本/测试直接调用；
- 检测能力通过 `get_detector()` 注入，换成真模型时本文件不用改；
- 时间口径严格按 docs/api.md：`elapsed_ms = finished_at - queued_at`（端到端），
  `inference_ms_total` 只统计模型推理那部分。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.models import (
    Alert,
    AlertStatus,
    Detection,
    DetectTask,
    FrameResult,
    Media,
    ReferenceModality,
    Region,
    TaskStatus,
)
from app.models.enums import DetectionMode, RequestMode
from app.services.detector import Box, get_detector, merge_boxes
from app.services.frames import iter_frame_pairs, save_frame_image
from app.services.imaging import ImageStats
from app.services.intrusion import bbox_center, region_contains
from app.services.selector import decide_mode, validate_manual_mode


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _abs(rel: str | None) -> Path | None:
    if not rel:
        return None
    return Path(settings.upload_dir) / rel


def _resolve_mode(
    task: DetectTask, *, has_rgb: bool, has_ir: bool, stats_rgb: ImageStats | None
) -> tuple[DetectionMode, str]:
    """手动模式只校验，自动模式才走选择器。"""
    if task.requested_mode == RequestMode.auto:
        decision = decide_mode(has_rgb=has_rgb, has_ir=has_ir, stats_rgb=stats_rgb)
        return decision.mode, decision.reason

    mode = DetectionMode(task.requested_mode.value)
    validate_manual_mode(mode, has_rgb=has_rgb, has_ir=has_ir)
    return mode, "用户手动指定模式"


def _upsert_alert(
    db: Session,
    task: DetectTask,
    media: Media,
    region: Region,
    box: Box,
    detection: Detection,
    frame_index: int,
    ts_ms: int | None,
    snapshot_rel: str | None,
    now: datetime,
) -> None:
    """告警归并（docs/api.md §8.1）。

    同一 (media, region) 上，时间窗内且位置相近的判定并入原告警，
    只累加 occurrence_count——避免视频 25fps 下告警刷屏。
    """
    last = db.scalar(
        select(Alert)
        .where(
            Alert.media_id == media.id,
            Alert.region_id == region.id,
            Alert.status == AlertStatus.unconfirmed,
        )
        .order_by(Alert.last_seen_at.desc())
        .limit(1)
    )

    if last is not None:
        delta_s = (now - last.last_seen_at).total_seconds()
        same_place = True
        if last.detection_id is not None:
            prev = db.get(Detection, last.detection_id)
            if prev is not None:
                px, py = bbox_center(prev.x1, prev.y1, prev.x2, prev.y2)
                cx, cy = box.center
                same_place = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 <= settings.alert_merge_distance

        if delta_s <= settings.alert_merge_window_s and same_place:
            last.occurrence_count += 1
            last.last_seen_at = now
            last.score_max = max(last.score_max, box.score)
            if snapshot_rel and not last.snapshot_path:
                last.snapshot_path = snapshot_rel
            return

    db.add(
        Alert(
            owner_id=task.owner_id,
            task_id=task.id,
            media_id=media.id,
            region_id=region.id,
            detection_id=detection.id,
            frame_index=frame_index,
            frame_ts_ms=ts_ms,
            score_max=box.score,
            snapshot_path=snapshot_rel,
            status=AlertStatus.unconfirmed,
            first_seen_at=now,
            last_seen_at=now,
            occurrence_count=1,
        )
    )


def run_task(db: Session, task: DetectTask, media: Media) -> None:
    """执行一条检测任务。异常会被写进 task.status / error_message 后抛出。"""
    t0 = time.perf_counter()
    task.status = TaskStatus.running
    task.started_at = _now()
    db.flush()

    try:
        rgb_path = _abs(media.stored_path)
        ir_path = _abs(media.ir_stored_path) if media.has_ir else None
        has_rgb = rgb_path is not None and rgb_path.exists()
        has_ir = ir_path is not None and ir_path.exists()
        is_video = media.media_type.value == "video"

        if not has_rgb and not has_ir:
            raise ApiError("MEDIA_NOT_FOUND", "媒体文件不存在或不可读", 422)

        frames = list(
            iter_frame_pairs(
                rgb_path if has_rgb else ir_path,
                ir_path,
                is_video=is_video,
                stride=media.frame_stride or 1,
                max_frames=settings.max_process_frames,
            )
        )
        if not frames:
            raise ApiError("MEDIA_UNSUPPORTED_FORMAT", "无法从该媒体中解出任何帧", 415)

        # ---- 选模态：用第一帧的可见光统计量做判断 ----
        first = frames[0]
        stats_rgb = (
            ImageStats.from_bgr(first.rgb) if first.rgb is not None else None
        )
        mode, reason = _resolve_mode(
            task, has_rgb=has_rgb or (first.rgb is not None), has_ir=has_ir, stats_rgb=stats_rgb
        )
        task.actual_mode = mode
        task.decision_reason = reason
        task.ref_modality = (
            ReferenceModality.ir if mode == DetectionMode.ir else ReferenceModality.rgb
        )

        det_rgb = get_detector("rgb")
        det_ir = get_detector("ir") if (has_ir or mode == DetectionMode.ir) else None

        regions = list(
            db.scalars(
                select(Region).where(
                    Region.media_id == media.id, Region.is_active.is_(True)
                )
            )
        )

        inference_ms_total = 0
        processed = 0
        ref_modality = task.ref_modality

        for fp in frames:
            # ---------- 检测 ----------
            t_inf = time.perf_counter()
            boxes: list[Box] = []
            if mode == DetectionMode.rgb:
                if fp.rgb is not None:
                    boxes = det_rgb.detect(fp.rgb, "rgb", fp.frame_index)
            elif mode == DetectionMode.ir:
                if fp.ir is not None and det_ir is not None:
                    boxes = det_ir.detect(fp.ir, "ir", fp.frame_index)
            else:  # fusion：两路各测一遍，再按 IoU 合并（结果级融合）
                b_rgb = det_rgb.detect(fp.rgb, "rgb", fp.frame_index) if fp.rgb is not None else []
                b_ir = (
                    det_ir.detect(fp.ir, "ir", fp.frame_index)
                    if (fp.ir is not None and det_ir is not None)
                    else []
                )
                boxes = merge_boxes(b_rgb, b_ir)
            infer_ms = int((time.perf_counter() - t_inf) * 1000)
            inference_ms_total += infer_ms

            # ---------- 落图（前端要按帧取图叠加框）----------
            ref_img = fp.ir if mode == DetectionMode.ir else fp.rgb
            if ref_img is None:
                ref_img = fp.rgb if fp.rgb is not None else fp.ir
            snapshot_rel = save_frame_image(media.id, fp.frame_index, ref_img)

            # ---------- 落框 ----------
            det_rows: list[Detection] = []
            for b in boxes:
                row = Detection(
                    task_id=task.id,
                    frame_index=fp.frame_index,
                    frame_ts_ms=fp.ts_ms,
                    class_name=b.class_name,
                    score=b.score,
                    x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2,
                    ref_modality=ref_modality,
                )
                db.add(row)
                det_rows.append(row)
            db.flush()  # 拿到 detection.id，告警要引用

            # ---------- 侵入判定 ----------
            hits: dict[int, tuple[Region, Box, Detection]] = {}
            if regions:
                for b, row in zip(boxes, det_rows):
                    cx, cy = b.center
                    for r in regions:
                        if region_contains(
                            r.points, cx, cy,
                            boundary_inclusive=settings.region_boundary_inclusive,
                        ):
                            key = r.id
                            if key not in hits or b.score > hits[key][1].score:
                                hits[key] = (r, b, row)
                            break

            # ---------- 告警（按区域聚合，一帧一区域最多一条）----------
            now = _now()
            for r, b, row in hits.values():
                _upsert_alert(
                    db, task, media, r, b, row,
                    fp.frame_index, fp.ts_ms, snapshot_rel, now,
                )

            # ---------- 帧级汇总 ----------
            db.add(
                FrameResult(
                    task_id=task.id,
                    frame_index=fp.frame_index,
                    frame_ts_ms=fp.ts_ms,
                    target_count=len(boxes),
                    intrusion_count=len(hits),
                    max_score=max((b.score for b in boxes), default=None),
                    inference_ms=infer_ms,
                    snapshot_path=snapshot_rel,
                )
            )
            processed += 1

        # ---------- 回填任务 ----------
        task.frames_processed = processed
        task.inference_ms_total = inference_ms_total
        task.finished_at = _now()
        task.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        task.model_version = f"{settings.detector_backend}-v1"
        task.confidence_threshold = settings.default_confidence
        task.iou_threshold = settings.default_iou
        task.imgsz = settings.default_imgsz
        task.status = TaskStatus.succeeded
        task.error_message = None
        db.commit()

    except ApiError as exc:
        db.rollback()
        task.status = TaskStatus.failed
        task.error_message = exc.message
        task.finished_at = _now()
        task.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        db.commit()
        raise

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task.status = TaskStatus.failed
        task.error_message = f"{type(exc).__name__}: {exc}"
        task.finished_at = _now()
        task.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        db.commit()
        raise ApiError(
            "INFERENCE_FAILED", "推理过程出错", 500, {"error": f"{type(exc).__name__}: {exc}"}
        ) from exc
