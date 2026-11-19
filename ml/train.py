"""单模态训练入口（RGB 或 IR，二选一跑）。

设计取舍：
- **不自己写训练循环**，直接用 ultralytics 的 `model.train()`。原因是在 8 周
  的项目里重写训练框架纯属浪费，而且人家已经处理好了 AMP、EMA、cosine LR、
  数据增强、日志和断点续训。
- 但**参数要显式传满**，写进命令行和最终报告，否则"可复现"是空话（FR-13）。

关于小目标（这是本项目最大的技术难点）：
UAV-CB 里大多数无人机占画面面积 < 5%（论文数据），YOLO 默认的 P3/P4/P5 检测头
对这么小的目标召回率很低。三个有效的招数，按性价比排序：
  1. **提高 imgsz**：640 → 960 或 1280。最有效，代价是显存和速度。先试这个。
  2. **换 s 以下的模型**：n/s 版本对小目标相对友好（特征图分辨率占比高）。
  3. **加 P2 检测头**：需要改模型结构，工作量最大，最后再考虑。

6GB 显存的现实配置参考（RTX 4050 Laptop）：
    imgsz=640  batch=16   ≈ 3.5GB   ← 起步用这个
    imgsz=960  batch=8    ≈ 5GB
    imgsz=1280 batch=4    ≈ 5.5GB   ← 有 OOM 风险，开 AMP

用法：
    docker compose --profile ml run --rm ml \
        python ml/train.py --data /data/uavcb/yolo_rgb/data.yaml --name rgb_yolo11s_960 --imgsz 960
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="单模态 UAV 检测训练")
    ap.add_argument("--data", required=True, help="prepare_yolo.py 生成的数据集 yaml")
    ap.add_argument("--model", default="yolo11s.pt", help="yolo11n/s/m 或 yolov8n/s/m，自动下载预训练权重")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=16, help="6GB 显存建议 640 用 16 / 960 用 8")
    ap.add_argument("--device", default="0", help="0 = 第一张 GPU，cpu = 用 CPU")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--patience", type=int, default=30, help="多少轮不提升就早停")
    ap.add_argument("--name", default="run", help="实验名，输出到 runs/<name>")
    ap.add_argument("--project", default="/workspace/runs")
    ap.add_argument("--resume", action="store_true", help="断点续训")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    try:
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"[FAIL] 缺少依赖: {exc}\n       要用 GPU 镜像：docker compose --profile ml run --rm ml ...")
        return 1

    # ---- 环境自检（先报清楚，别等训练到一半才发现是 CPU）----
    print("=" * 60)
    print(f"torch {torch.__version__} | CUDA 可用: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        i = 0 if args.device != "cpu" else None
        if i is not None:
            props = torch.cuda.get_device_properties(i)
            print(f"GPU: {props.name}  显存 {props.total_memory / 1024**3:.1f} GB")
    else:
        print("[warn] 没有可用 GPU，训练会非常慢。确认容器启动时带了 --gpus。")
    print(f"数据: {args.data}")
    print(f"参数: model={args.model} imgsz={args.imgsz} batch={args.batch} "
          f"epochs={args.epochs} seed={args.seed}")
    print("=" * 60)

    model = YOLO(args.model)

    # 参数说明：
    #   amp=True        混合精度，6GB 显存必须开
    #   cache=False     不要缓存到内存，图像多会 OOM
    #   cos_lr=True     小数据集上更稳
    #   close_mosaic     最后 10 轮关掉 mosaic，让框回归收敛得更准
    model.train(
        data=args.data,
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        project=args.project,
        name=args.name,
        exist_ok=True,
        resume=args.resume,
        amp=True,
        cache=False,
        cos_lr=True,
        close_mosaic=10,
        seed=args.seed,
        deterministic=True,
        plots=True,
        val=True,
        verbose=True,
    )

    best = f"{args.project}/{args.name}/weights/best.pt"
    print("\n" + "=" * 60)
    print(f"训练完成。最佳权重: {best}")
    print(f"下一步评估：\n"
          f"  docker compose --profile ml run --rm ml python ml/evaluate.py "
          f"--weights {best} --data {args.data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
