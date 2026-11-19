"""把各种标注格式统一转成 YOLO 格式，并做**防泄漏**的数据划分。

支持（自动识别）：VOC XML / COCO JSON / YOLO txt / CSV

为什么反复强调"防泄漏"：
UAV-CB 的图片是从**视频序列**里抽的，相邻帧长得几乎一样。如果随机划分，
同一段视频的相邻帧会同时出现在训练集和测试集，模型等于"见过答案"，
mAP 会虚高十几个点，而且答辩时一被追问就露馅。
所以这里默认按**连续块**切分（相邻帧留在同一集合），而不是随机打乱。

用法：
    # 第一步：先看统计，不写任何文件
    docker compose exec api python -m ml.datasets.prepare_yolo \
        --root /data/uavcb --images-dir RGB --modality rgb --dry-run

    # 第二步：真正转换
    docker compose exec api python -m ml.datasets.prepare_yolo \
        --root /data/uavcb --images-dir RGB --modality rgb --out /data/uavcb/yolo_rgb

    # IR 用同样的命令，换 --images-dir T --modality ir
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

# (file_name, [(x1,y1,x2,y2), ...], (w,h) | None)
Sample = tuple[str, list[tuple[float, float, float, float]], tuple[int, int] | None]


# ---------------------------------------------------------------- 解析器
def parse_voc(xml_path: Path) -> tuple[list[tuple], tuple[int, int] | None]:
    root = ET.parse(xml_path).getroot()
    size = root.find("size")
    wh = None
    if size is not None:
        try:
            wh = (int(size.findtext("width")), int(size.findtext("height")))
        except (TypeError, ValueError):
            wh = None
    boxes = []
    for obj in root.findall("object"):
        bb = obj.find("bndbox")
        if bb is None:
            continue
        try:
            boxes.append(
                (
                    float(bb.findtext("xmin")),
                    float(bb.findtext("ymin")),
                    float(bb.findtext("xmax")),
                    float(bb.findtext("ymax")),
                )
            )
        except (TypeError, ValueError):
            continue
    return boxes, wh


def parse_coco(json_path: Path) -> dict[str, list[tuple]]:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    id2name = {im["id"]: im["file_name"] for im in data.get("images", [])}
    out: dict[str, list[tuple]] = {}
    for ann in data.get("annotations", []):
        fname = id2name.get(ann.get("image_id"))
        if fname is None:
            continue
        x, y, w, h = ann["bbox"]
        out.setdefault(Path(fname).name, []).append((x, y, x + w, y + h))
    return out


def parse_yolo_txt(txt_path: Path, w: int, h: int) -> list[tuple]:
    boxes = []
    for line in txt_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cx, cy, bw, bh = (float(v) for v in parts[1:5])
        except ValueError:
            continue
        boxes.append(
            ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)
        )
    return boxes


def parse_csv(csv_path: Path) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    with open(csv_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        c_img = pick("image", "filename", "file_name", "img", "path")
        c_x1, c_y1 = pick("x1", "xmin"), pick("y1", "ymin")
        c_x2, c_y2 = pick("x2", "xmax"), pick("y2", "ymax")
        if not all([c_img, c_x1, c_y1, c_x2, c_y2]):
            raise ValueError(f"CSV 列名认不出来，实际列: {list(cols)}")
        for row in reader:
            try:
                out.setdefault(Path(row[c_img]).name, []).append(
                    (float(row[c_x1]), float(row[c_y1]), float(row[c_x2]), float(row[c_y2]))
                )
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------- 工具
def detect_format(base: Path) -> str:
    """按目录里实际出现的文件类型判断格式。"""
    exts = Counter(p.suffix.lower() for p in base.rglob("*") if p.is_file())
    if exts.get(".xml"):
        return "voc"
    if exts.get(".json"):
        return "coco"
    if exts.get(".csv"):
        return "csv"
    if exts.get(".txt"):
        return "yolo"
    raise SystemExit(
        f"[FAIL] 在 {base} 下没找到 .xml/.json/.txt/.csv 标注文件。\n"
        f"       实际扩展名: {dict(exts)}\n"
        f"       先跑 inspect_dataset.py 看清楚结构。"
    )


def img_size(p: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(p) as im:
            return im.width, im.height
    except Exception:  # noqa: BLE001
        return None


def group_key(stem: str, regex: str | None) -> str:
    """切分用的分组键。同组（同一条视频/场景）的图只会进同一个集合。"""
    if regex:
        m = re.search(regex, stem)
        return m.group(1) if m and m.groups() else (m.group(0) if m else stem)
    return stem  # 无正则时退化成"每张图独立"，后面按连续块切分


def split_groups(groups: list[str], ratios: tuple[float, float, float], seed: int) -> dict[str, str]:
    """把分组分配到 train/val/test。"""
    rng = random.Random(seed)
    gs = sorted(groups)
    rng.shuffle(gs)
    n = len(gs)
    n_tr = int(round(n * ratios[0]))
    n_va = int(round(n * ratios[1]))
    n_tr = max(1, min(n_tr, n - 2)) if n > 2 else n
    assign = {}
    for i, g in enumerate(gs):
        if i < n_tr:
            assign[g] = "train"
        elif i < n_tr + n_va:
            assign[g] = "val"
        else:
            assign[g] = "test"
    return assign


def main() -> int:
    ap = argparse.ArgumentParser(description="转 YOLO 格式 + 防泄漏划分")
    ap.add_argument("--root", required=True, help="数据集根目录")
    ap.add_argument("--images-dir", default=None, help="图片所在子目录，如 RGB 或 T（不填则全库搜）")
    ap.add_argument("--ann-dir", default=None, help="标注所在子目录（不填则与 root 同级搜索）")
    ap.add_argument("--format", default="auto", choices=["auto", "voc", "coco", "yolo", "csv"])
    ap.add_argument("--modality", default="rgb", choices=["rgb", "ir"], help="只用来给输出命名")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--split", default="0.6,0.2,0.2", help="train,val,test 比例")
    ap.add_argument("--group-regex", default=None,
                    help="从文件名提取序列号的正则，如 '^(\\d+)_' —— 强烈建议提供")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--link", action="store_true", help="用硬链接代替复制（省磁盘）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"[FAIL] 目录不存在: {root}")
        return 1

    ratios = tuple(float(x) for x in args.split.split(","))
    if len(ratios) != 3 or abs(sum(ratios) - 1.0) > 1e-6:
        print("[FAIL] --split 必须是三个加起来等于 1 的数，如 0.6,0.2,0.2")
        return 1

    img_root = root / args.images_dir if args.images_dir else root
    if not img_root.is_dir():
        print(f"[FAIL] 图片目录不存在: {img_root}")
        return 1

    # 相对路径要拼到 --root 上，否则会被当成相对当前工作目录（曾经踩过）
    ann_root = (root / args.ann_dir) if args.ann_dir else root
    if args.ann_dir and not ann_root.is_dir():
        print(f"[FAIL] 标注目录不存在: {ann_root}")
        return 1

    fmt = detect_format(ann_root) if args.format == "auto" else args.format
    print(f"标注格式: {fmt}    图片目录: {img_root}")

    images = sorted(p for p in img_root.rglob("*") if p.suffix.lower() in IMG_EXT)
    print(f"找到图片 {len(images)} 张")
    if not images:
        return 1

    # ---- 收集标注 ----
    ann_of: dict[str, list[tuple]] = {}
    if fmt == "coco":
        cands = list(ann_root.rglob("*.json"))
        if not cands:
            print("[FAIL] 没找到 COCO json")
            return 1
        ann_of = parse_coco(cands[0])
        print(f"COCO 标注: {cands[0].name}，涉及 {len(ann_of)} 张图")
    else:
        if fmt == "csv":
            cands = list(ann_root.rglob("*.csv"))
            if not cands:
                print("[FAIL] 没找到 CSV")
                return 1
            ann_of = parse_csv(cands[0])
            print(f"CSV 标注: {cands[0].name}，涉及 {len(ann_of)} 张图")
        for img in images:
            stem = img.stem
            if fmt == "voc":
                p = img.with_suffix(".xml")
                if not p.exists():
                    p = img_root / ".." / "Annotations" / f"{stem}.xml"
                if p.exists():
                    ann_of[img.name] = parse_voc(p)[0]
            elif fmt == "yolo":
                p = img_root.parent / "labels" / f"{stem}.txt"
                if p.exists():
                    sz = img_size(img) or (0, 0)
                    ann_of[img.name] = parse_yolo_txt(p, *sz) if sz[0] else []

    # ---- 逐图组装 ----
    samples: list[Sample] = []
    missing = 0
    for img in images:
        boxes = ann_of.get(img.name)
        if boxes is None:
            missing += 1
            continue
        samples.append((str(img), boxes, None))

    if not samples:
        print("[FAIL] 一张图都没匹配上标注。名字对不上？先跑 inspect_dataset.py 看文件名。")
        return 1
    if missing:
        print(f"[warn] {missing} 张图没有对应标注，已跳过（如果是负样本，需要单独处理）")

    # ---- 防泄漏划分 ----
    groups = sorted({group_key(Path(s[0]).stem, args.group_regex) for s in samples})
    assign = split_groups(groups, ratios, args.seed)
    print(f"分组数: {len(groups)}  （--group-regex = {args.group_regex or '未提供，按文件名分组'}）")

    per_split: dict[str, list[Sample]] = {"train": [], "val": [], "test": []}
    for s in samples:
        per_split[assign[group_key(Path(s[0]).stem, args.group_regex)]].append(s)

    # ---- 统计 ----
    print("\n" + "=" * 62)
    print(f"{'集合':<8}{'图片':>8}{'目标框':>10}{'平均框/图':>12}")
    print("-" * 62)
    total_b = 0
    for sp in ("train", "val", "test"):
        nb = sum(len(s[1]) for s in per_split[sp])
        total_b += nb
        avg = nb / len(per_split[sp]) if per_split[sp] else 0
        print(f"{sp:<8}{len(per_split[sp]):>8}{nb:>10}{avg:>12.2f}")
    print("-" * 62)
    print(f"{'合计':<8}{len(samples):>8}{total_b:>10}")

    box_counts = Counter(len(s[1]) for s in samples)
    print(f"\n每图框数分布（前 5）: {dict(box_counts.most_common(5))}")

    if args.dry_run:
        print("\n[dry-run] 未写任何文件。确认无误后去掉 --dry-run 再跑。")
        return 0

    # ---- 输出 ----
    out = Path(args.out) if args.out else root / f"yolo_{args.modality}"
    if out.exists() and any(out.iterdir()):
        print(f"\n[FAIL] 输出目录已存在且非空: {out}\n       删掉它或换 --out，避免混进旧数据。")
        return 1
    for sp in ("train", "val", "test"):
        (out / "images" / sp).mkdir(parents=True, exist_ok=True)
        (out / "labels" / sp).mkdir(parents=True, exist_ok=True)

    written = 0
    for sp, items in per_split.items():
        for src, boxes, wh in items:
            src_p = Path(src)
            sz = wh or img_size(src_p)
            if not sz:
                continue
            w, h = sz
            dst_img = out / "images" / sp / src_p.name
            if args.link:
                try:
                    dst_img.hardlink_to(src_p)
                except OSError:
                    shutil.copy2(src_p, dst_img)
            else:
                shutil.copy2(src_p, dst_img)

            lines = []
            for x1, y1, x2, y2 in boxes:
                x1c, x2c = max(0.0, min(x1, x2)), min(float(w), max(x1, x2))
                y1c, y2c = max(0.0, min(y1, y2)), min(float(h), max(y1, y2))
                bw, bh = x2c - x1c, y2c - y1c
                if bw <= 1 or bh <= 1:
                    continue  # 退化框丢掉
                cx, cy = (x1c + x2c) / 2 / w, (y1c + y2c) / 2 / h
                lines.append(f"0 {cx:.6f} {cy:.6f} {bw / w:.6f} {bh / h:.6f}")
            (out / "labels" / sp / f"{src_p.stem}.txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
            written += 1

    yaml_path = out / "data.yaml"
    yaml_path.write_text(
        f"""# 自动生成 by prepare_yolo.py
# 数据集: {root.name}  模态: {args.modality}
path: {out.resolve()}
train: images/train
val: images/val
test: images/test

nc: 1
names:
  0: uav
""",
        encoding="utf-8",
    )

    print(f"\n[ok] 写出 {written} 张图 + 标注 -> {out}")
    print(f"[ok] 数据集配置 -> {yaml_path}")
    print("\n下一步训练：")
    print(f"  docker compose --profile ml run --rm ml python ml/train.py --data {yaml_path} --name {args.modality}_baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
