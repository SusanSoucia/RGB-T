"""数据集结构探针。

**第一步永远是这个脚本。** 在不知道标注格式的情况下写转换器是瞎猜，
所以先让脚本把目录结构、标注格式、图片尺寸、样本内容都打印出来，
看清楚之后再跑 prepare_yolo.py。

用法：
    docker compose exec api python -m ml.datasets.inspect_dataset --root /data/uavcb

    # 或者直接指定绝对路径
    python ml/datasets/inspect_dataset.py --root /data/uavcb --samples 3
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
ANN_EXT = {".xml", ".json", ".txt", ".csv"}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def scan(root: Path) -> dict:
    """遍历目录，统计每个子目录里的图片/标注文件。"""
    stats: dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = str(Path(dirpath).relative_to(root)) or "."
        imgs, anns, others = [], [], 0
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext in IMG_EXT:
                imgs.append(fn)
            elif ext in ANN_EXT:
                anns.append(fn)
            else:
                others += 1
        if imgs or anns:
            stats[rel] = {
                "images": imgs,
                "anns": anns,
                "others": others,
                "img_ext": Counter(Path(f).suffix.lower() for f in imgs),
                "ann_ext": Counter(Path(f).suffix.lower() for f in anns),
            }
    return stats


def peek_text(path: Path, n: int = 12) -> list[str]:
    try:
        if path.suffix.lower() == ".json":
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(200_000)
            data = json.loads(head) if head.strip().endswith("}") else None
            if isinstance(data, dict):
                keys = list(data.keys())
                out = [f"  顶层键: {keys[:10]}"]
                for k in ("images", "annotations", "categories"):
                    if k in data and isinstance(data[k], list):
                        out.append(f"  {k}: {len(data[k])} 条，样例:")
                        out.append("    " + json.dumps(data[k][0], ensure_ascii=False)[:300])
                return out
            return [f"  (JSON 解析失败或非对象，前 300 字符) {head[:300]}"]
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip() for _, ln in zip(range(n), f)]
        return ["  " + ln[:200] for ln in lines]
    except Exception as exc:  # noqa: BLE001
        return [f"  (读取失败: {exc})"]


def image_sizes(paths: list[Path], k: int) -> list[tuple[str, int, int, str]]:
    try:
        from PIL import Image
    except ImportError:
        return []
    out = []
    for p in random.sample(paths, min(k, len(paths))):
        try:
            with Image.open(p) as im:
                out.append((p.name, im.width, im.height, im.mode))
        except Exception:  # noqa: BLE001
            continue
    return out


def guess_format(stats: dict) -> list[str]:
    """根据目录里出现的标注文件类型给出猜测。"""
    hits = []
    ext_counter = Counter()
    for s in stats.values():
        ext_counter.update(s["ann_ext"])
    names = [n.lower() for s in stats.values() for n in s["anns"]]

    if ext_counter.get(".xml"):
        hits.append("VOC XML	（每张图一个 .xml，含 <bndbox>）")
    if ext_counter.get(".json"):
        hits.append("COCO JSON	（单个 .json，含 images/annotations/categories）")
    if ext_counter.get(".txt") and not ext_counter.get(".xml"):
        hits.append("YOLO txt	（每张图一个 .txt，'cls cx cy w h' 归一化）")
    if ext_counter.get(".csv"):
        hits.append("CSV	（表格，每行一个框）")
    if any("label" in n for n in names) or any(d.lower().startswith("label") for d in stats):
        hits.append("看起来有 labels/ 目录，大概率是 YOLO 格式")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="数据集结构探针")
    ap.add_argument("--root", required=True, help="数据集根目录，如 /data/uavcb")
    ap.add_argument("--samples", type=int, default=2, help="每个格式打印几个样本文件")
    ap.add_argument("--size-samples", type=int, default=8, help="抽样检查多少张图片的尺寸")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"[FAIL] 目录不存在: {root}")
        return 1

    print("=" * 70)
    print(f"数据根目录: {root.resolve()}")
    print("=" * 70)

    stats = scan(root)
    if not stats:
        print("目录里没有找到图片或标注文件。确认路径对不对？")
        return 1

    total_img = total_ann = 0
    print("\n【目录概览】")
    for rel in sorted(stats):
        s = stats[rel]
        total_img += len(s["images"])
        total_ann += len(s["anns"])
        ext = ", ".join(f"{k}×{v}" for k, v in s["img_ext"].most_common())
        aext = ", ".join(f"{k}×{v}" for k, v in s["ann_ext"].most_common()) or "无"
        print(f"  {rel:<32} 图片 {len(s['images']):>6} [{ext}]   标注 {len(s['anns']):>6} [{aext}]")

    print(f"\n  合计：图片 {total_img} 张，标注文件 {total_ann} 个")

    print("\n【格式猜测】")
    for h in guess_format(stats) or ["没认出来，需要人工看一下上面的扩展名统计"]:
        print(f"  - {h}")

    print("\n【标注样本】")
    shown = 0
    for rel in sorted(stats):
        if shown >= args.samples:
            break
        anns = stats[rel]["anns"]
        if not anns:
            continue
        for fn in anns[: args.samples]:
            p = root / rel / fn
            print(f"  --- {rel}/{fn} ---")
            for line in peek_text(p):
                print(line)
            shown += 1
            print()

    print("【文件名样本】（用于判断能否按序列分组切分）")
    all_imgs = [(rel, fn) for rel in sorted(stats) for fn in stats[rel]["images"]]
    for rel, fn in all_imgs[:10]:
        print(f"  {rel}/{fn}")
    if len(all_imgs) > 10:
        print(f"  ... 共 {len(all_imgs)} 个")

    print("\n【图片尺寸抽样】")
    all_paths = [root / rel / fn for rel, fn in all_imgs]
    sizes = image_sizes(all_paths, args.size_samples)
    if sizes:
        from collections import Counter as C
        dist = C((w, h) for _, w, h, _ in sizes)
        for (w, h), n in dist.most_common():
            print(f"  {w}×{h}  ×{n} 张")
        modes = C(m for _, _, _, m in sizes)
        print(f"  色彩模式: {dict(modes)}   （IR 常见 L 或 RGB 三通道灰度）")
    else:
        print("  （PIL 不可用，跳过）")

    print("\n【下一步】")
    print("  1. 确认上面的『格式猜测』对不对；")
    print("  2. 按实际格式跑：")
    print("     python -m ml.datasets.prepare_yolo --help")
    print("  3. 先用 --dry-run 看统计，再真正转换。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
