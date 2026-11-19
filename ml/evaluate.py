"""单模态评估入口。

为什么单独一个脚本而不是直接用 `yolo val`：
需求 §3.2.1 要求记录 **Precision / Recall / mAP + 置信度阈值 + IoU 口径 +
输入尺寸 + 测试划分 + 样本数**。`yolo val` 能出数，但不会帮你整理成一份
可比对的记录。这个脚本把这些元信息一起写进 JSON，方便以后汇总成表格。

用法：
    docker compose --profile ml run --rm ml python ml/evaluate.py \
        --weights /workspace/runs/rgb/weights/best.pt \
        --data /data/uavcb/yolo_rgb/data.yaml \
        --split test --confs 0.25,0.5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def count_split_images(data_yaml: str, split: str) -> int | None:
    """数出该 split 的图片数。

    ultralytics 的 val 结果不直接暴露样本数，而需求 §3.2.1 明确要求记录它，
    所以自己按 data.yaml 的 path + split 目录去数。数不到就返回 None。
    """
    try:
        import yaml
    except ImportError:
        return None
    try:
        cfg = yaml.safe_load(Path(data_yaml).read_text(encoding="utf-8"))
        base = Path(cfg.get("path", Path(data_yaml).parent))
        sub = cfg.get(split) or cfg.get("val")
        if not sub:
            return None
        d = Path(sub)
        d = d if d.is_absolute() else base / d
        if not d.is_dir():
            return None
        return sum(1 for p in d.rglob("*") if p.suffix.lower() in IMG_EXT)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="检测模型评估")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--split", default="test", choices=["train", "val", "test"])
    ap.add_argument("--iou", type=float, default=0.6, help="NMS 的 IoU 阈值")
    ap.add_argument("--confs", default="0.25", help="逗号分隔，逐个报告，如 0.25,0.5")
    ap.add_argument("--out", default=None, help="结果 JSON 路径")
    args = ap.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"[FAIL] 缺少依赖: {exc}")
        return 1

    confs = [float(c) for c in args.confs.split(",")]
    model = YOLO(args.weights)

    records = []
    for conf in confs:
        print(f"\n{'='*60}\n置信度阈值 conf={conf}\n{'='*60}")
        # 注意：mAP 本身是对所有置信度积分得到的，conf 只影响 P/R 的报告点
        metrics = model.val(
            data=args.data,
            imgsz=args.imgsz,
            split=args.split,
            conf=conf,
            iou=args.iou,
            plots=False,
            verbose=False,
        )
        box = metrics.box
        rec = {
            "conf_threshold": conf,
            "iou_threshold": args.iou,
            "imgsz": args.imgsz,
            "split": args.split,
            "precision": float(box.mp),
            "recall": float(box.mr),
            "map50": float(box.map50),
            "map50_95": float(box.map),
            "per_class": {
                name: {"precision": float(box.p[i]), "recall": float(box.r[i]),
                       "map50": float(box.ap50[i]), "map50_95": float(box.ap[i])}
                for i, name in enumerate(metrics.names.values())
            },
            "n_images": count_split_images(args.data, args.split),
        }
        records.append(rec)

        print(f"  Precision : {rec['precision']:.4f}")
        print(f"  Recall    : {rec['recall']:.4f}")
        print(f"  mAP@0.5   : {rec['map50']:.4f}")
        print(f"  mAP@.5:.95: {rec['map50_95']:.4f}")
        print(f"  推理耗时  : {metrics.speed.get('inference', 0):.2f} ms/张"
              f"（预处理 {metrics.speed.get('preprocess', 0):.2f} / "
              f"后处理 {metrics.speed.get('postprocess', 0):.2f}）")

    payload = {
        "weights": str(args.weights),
        "data": str(args.data),
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "results": records,
        "note": "置信度表示模型输出分数，不是经过校准的真实概率（需求 §3.2.1）",
    }

    out = Path(args.out) if args.out else Path(args.weights).parent.parent / f"eval_{args.split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] 结果已写入 {out}")

    print("\n提醒：报告里务必注明 imgsz / conf / IoU 口径 / 测试集样本数，"
          "并且**不能用测试集调参**（需求 §3.2.1）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
