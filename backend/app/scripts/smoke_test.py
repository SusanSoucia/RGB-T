"""数据模型冒烟测试。

在**一个事务里**把「用户 → 媒体 → 检测任务 → 检测结果 → 帧记录 → 区域 → 告警」
整条链写一遍再查回来，最后 **rollback**，不留任何脏数据。

用途：
1. 验证 SQLAlchemy 模型与数据库 schema 一致；
2. 验证外键、JSONB、枚举、时区字段真的能用；
3. 以后改模型后跑一次，能立刻发现哪里断了。

用法：
    docker compose exec api python -m app.scripts.smoke_test
"""

import sys
from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import (
    Alert,
    AlertStatus,
    Detection,
    DetectionMode,
    DetectTask,
    FrameResult,
    Media,
    MediaStatus,
    MediaType,
    ReferenceModality,
    Region,
    RegionShape,
    RequestMode,
    TaskStatus,
    User,
    UserRole,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main() -> int:
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        # ---- 1. 用户 ----
        user = User(
            username="__smoke_test__",
            password_hash=pwd_context.hash("dummy-password"),
            display_name="冒烟测试",
            role=UserRole.user,
        )
        db.add(user)
        db.flush()
        print(f"[1/7] user         ok id={user.id}")

        # ---- 2. 媒体（RGB 1920x1080 + IR 640x512，模拟 UAV-CB）----
        media = Media(
            owner_id=user.id,
            original_name="test.mp4",
            stored_path="uploads/2026/11/test.mp4",
            media_type=MediaType.video,
            mime_type="video/mp4",
            size_bytes=1024,
            width=1920,
            height=1080,
            has_ir=True,
            ir_width=640,
            ir_height=512,
            fps=25.0,
            duration_ms=60_000,
            total_frames=1500,
            frame_stride=5,
            status=MediaStatus.ready,
        )
        db.add(media)
        db.flush()
        print(f"[2/7] media        ok id={media.id} 1920x1080 / ir 640x512")

        # ---- 3. 检测任务 ----
        task = DetectTask(
            owner_id=user.id,
            media_id=media.id,
            requested_mode=RequestMode.auto,
            actual_mode=DetectionMode.ir,
            decision_reason="低照度(亮度=12.3)，切红外",
            ref_modality=ReferenceModality.rgb,
            status=TaskStatus.succeeded,
            model_version="rgb_v1+ir_v1",
            confidence_threshold=0.25,
            iou_threshold=0.45,
            imgsz=640,
            elapsed_ms=840,
            inference_ms_total=610,
            frames_processed=300,
        )
        db.add(task)
        db.flush()
        print(f"[3/7] task         ok id={task.id} auto->{task.actual_mode}")

        # ---- 4. 检测结果（归一化坐标）----
        det = Detection(
            task_id=task.id,
            frame_index=120,
            frame_ts_ms=4_800,
            score=0.87,
            x1=0.42, y1=0.31, x2=0.48, y2=0.39,
            ref_modality=ReferenceModality.rgb,
        )
        db.add(det)
        db.flush()
        print(f"[4/7] detection    ok id={det.id} score={det.score}")

        # ---- 5. 帧级记录：一帧有目标、一帧无目标 ----
        # 关键验证点：无目标的帧也要有行，否则前端分不清"无目标"和"没处理到"
        hit = FrameResult(
            task_id=task.id, frame_index=120, frame_ts_ms=4_800,
            target_count=1, intrusion_count=1, max_score=0.87,
            inference_ms=2, snapshot_path="uploads/snapshots/f120.jpg",
        )
        miss = FrameResult(
            task_id=task.id, frame_index=125, frame_ts_ms=5_000,
            target_count=0, intrusion_count=0, max_score=None, inference_ms=2,
        )
        db.add_all([hit, miss])
        db.flush()

        n_no_target = db.scalar(
            select(func.count()).select_from(FrameResult)
            .where(FrameResult.task_id == task.id, FrameResult.target_count == 0)
        )
        # frame_index 应为原始视频帧号（0,5,10...），允许跳跃
        assert n_no_target == 1, f"无目标帧统计异常: {n_no_target}"
        print(f"[5/7] frame        ok 2 帧，其中无目标 {n_no_target} 帧（可区分）")

        # ---- 6. 区域（归一化点序列，JSONB）----
        region = Region(
            owner_id=user.id,
            media_id=media.id,
            name="东侧围墙",
            shape_type=RegionShape.rect,
            points=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        )
        db.add(region)
        db.flush()
        print(f"[6/7] region       ok id={region.id} points={len(region.points)} 个顶点")

        # ---- 7. 告警（含归并字段）----
        alert = Alert(
            owner_id=user.id,
            task_id=task.id,
            media_id=media.id,
            region_id=region.id,
            detection_id=det.id,
            frame_index=det.frame_index,
            frame_ts_ms=det.frame_ts_ms,
            score_max=det.score,
            snapshot_path="uploads/snapshots/alert_1.jpg",
            status=AlertStatus.unconfirmed,
            first_seen_at=now,
            last_seen_at=now,
            occurrence_count=3,
        )
        db.add(alert)
        db.flush()
        print(f"[7/7] alert        ok id={alert.id} x{alert.occurrence_count}")

        # ---- 回读校验 ----
        got = db.scalar(select(Alert).where(Alert.id == alert.id))
        assert got is not None and got.status == AlertStatus.unconfirmed
        assert got.region_id == region.id

        # 帧按帧号排序取回（时间轴查询的实际形态）
        frames = db.scalars(
            select(FrameResult)
            .where(FrameResult.task_id == task.id)
            .order_by(FrameResult.frame_index)
        ).all()
        assert [f.frame_index for f in frames] == [120, 125], "帧顺序异常"

        # 关联关系能用
        assert len(task.frame_results) == 2, "task.frame_results 关系异常"

        # JSONB 能按路径查询，这是选 Postgres 的理由之一
        jb = db.scalar(select(Region.points[0][0]).where(Region.id == region.id))
        assert abs(float(jb) - 0.1) < 1e-9, f"JSONB 读取异常: {jb}"

        print("\n回读校验通过：外键、JSONB 路径查询、枚举、timestamptz、帧序列、关系均正常")
        print("（以下数据将全部回滚，数据库保持干净）")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] {type(exc).__name__}: {exc}")
        return 1
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
