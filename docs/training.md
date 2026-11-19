# 单模态 UAV 检测实现指南

> 目标：先把 **RGB 单独能测** 和 **IR 单独能测** 做扎实（README §5 的 M2）。
> 不涉及区域判定、告警、双模态融合——那些是后面的事。
> **顺序很重要**：单帧单模态链路是所有功能的底座，地基不牢后面全是返工。

---

## 0. 全景

```
原始数据 ──inspect──▶ 看清格式 ──prepare──▶ YOLO 格式 + 防泄漏划分
                                              │
                                              ▼
                                          train ──▶ weights/best.pt
                                              │
                                    ┌─────────┴─────────┐
                                    ▼                   ▼
                                evaluate             infer（给后端用）
                              P/R/mAP + 耗时        归一化框 + 置信度
```

| 步骤 | 脚本 | 能不能现在跑 |
|---|---|---|
| ① 探结构 | `ml/datasets/inspect_dataset.py` | ✅ 本机就能跑 |
| ② 转格式 | `ml/datasets/prepare_yolo.py` | ✅ 本机就能跑 |
| ③ 训练 | `ml/train.py` | 需要 GPU 镜像（7GB） |
| ④ 评估 | `ml/evaluate.py` | 同上 |
| ⑤ 推理 | `ml/infer.py` | 同上 |

---

## 1. 第一步：先看清数据（别急着写代码）

**我还不知道 UAV-CB 的具体标注格式**（GitHub 拉不到，DNS 解析失败）。
VOC XML / COCO JSON / YOLO txt 都有可能。所以先让脚本告诉你：

```powershell
docker compose exec api python -m ml.datasets.inspect_dataset --root /data/uploads/uavcb
```

它会打印：

- 每个子目录有多少张图 / 多少个标注、扩展名分布
- **格式猜测**（VOC / COCO / YOLO / CSV）
- 标注文件的实际内容前几行
- 文件名样本（判断能不能按序列分组）
- 图片尺寸分布和色彩模式

**先看这个，再决定下一步。** 拿到输出后告诉我，我可以把转换器调成精确匹配。

> 实测样例（合成数据）：
> ```
> 【格式猜测】
>   - VOC XML	（每张图一个 .xml，含 <bndbox>）
> 【图片尺寸抽样】
>   320×256 ×5 张
>   640×360 ×3 张
>   色彩模式: {'RGB': 8}
> ```

---

## 2. 第二步：转成 YOLO 格式 + 防泄漏划分

```powershell
# 先 dry-run 看统计，不写文件
docker compose exec api python -m ml.datasets.prepare_yolo `
    --root /data/uploads/uavcb --images-dir RGB --ann-dir Annotations `
    --modality rgb --group-regex "^(scene\d+)_" --out /data/uploads/uavcb/yolo_rgb --dry-run
```

去掉 `--dry-run` 就是真正转换。输出：

```
yolo_rgb/
├── images/{train,val,test}/*.png
├── labels/{train,val,test}/*.txt    # YOLO: cls cx cy w h，全部 0~1
└── data.yaml                        # 直接喂给 train.py
```

### ⚠️ 防泄漏是这一步最重要的设计

UAV-CB 的图是从**视频序列**里抽的，相邻帧几乎一样。随机划分会让同一段视频的
相邻帧同时出现在训练集和测试集——模型等于"见过答案"，**mAP 会虚高十几个点**，
答辩时一追问就穿帮。

所以脚本默认**按分组切分**：

- 给了 `--group-regex` → 按正则提取序列号，同一序列整组进同一个集合；
- 没给 → 按文件名排序后**连续切块**（相邻帧仍然留在一起）。

实测（3 个序列 × 8 帧）：

```
集合            图片       目标框       平均框/图
train          8        12        1.50
val            8        14        1.75
test           8        11        1.38
```

验证无泄漏：`train=scene02 / val=scene01 / test=scene03`，三个集合场景完全互斥。

> **务必**去看一眼实际文件名，然后把 `--group-regex` 写对。
> 序列号长什么样只有你的数据知道（`scene01_0001` / `20231015_seq3_f0042` / …）。

---

## 3. 第三步：训练

先起 GPU 容器（首次要下载约 7GB 底座）：

```powershell
docker compose --profile ml build ml
```

然后：

```powershell
# RGB
docker compose --profile ml run --rm ml python ml/train.py `
    --data /data/uavcb/yolo_rgb/data.yaml --name rgb_y11s_960 --imgsz 960 --batch 8

# IR：换数据 yaml 和实验名就行
docker compose --profile ml run --rm ml python ml/train.py `
    --data /data/uavcb/yolo_ir/data.yaml --name ir_y11s_960 --imgsz 960 --batch 8
```

### 3.1 小目标是本项目最大的技术难点

论文数据：UAV-CB 里大多数无人机**占画面面积不到 5%**。YOLO 默认检测头
（P3/P4/P5）对这么小的目标召回率会明显偏低。三个招数按性价比排序：

| 招数 | 效果 | 代价 | 建议 |
|---|---|---|---|
| **提高 `imgsz`** 640→960/1280 | 最明显 | 显存 + 变慢 | ✅ **先试这个** |
| 选小模型 `yolo11n/s` | 相对友好 | 精度上限低 | 先用 s 起步 |
| 加 P2 检测头 | 强 | 要改模型结构 | 最后再考虑 |

### 3.2 6GB 显存的现实配置

以下是**经验估计，实测为准**（跑起来看 `nvidia-smi`）：

| imgsz | batch | 估计显存 | 说明 |
|---|---|---|---|
| 640 | 16 | ~3.5GB | 起步基线 |
| 960 | 8 | ~5GB | **推荐起点** |
| 1280 | 4 | ~5.5GB | 有 OOM 风险，开 AMP |

显存不够就降 `--batch`，比降 `imgsz` 划算——**小目标任务里分辨率优先于 batch**。

### 3.3 训练脚本已经替你设好的参数

| 参数 | 值 | 为什么 |
|---|---|---|
| `amp` | True | 6GB 显存必须开混合精度 |
| `cache` | False | 缓存到内存会 OOM |
| `cos_lr` | True | 小数据集上更稳 |
| `close_mosaic` | 10 | 最后 10 轮关 mosaic，让框回归收敛更准 |
| `patience` | 30 | 早停，省时间 |
| `deterministic` | True | 可复现（FR-13 要求） |

---

## 4. 第四步：评估（口径比数字重要）

```powershell
docker compose --profile ml run --rm ml python ml/evaluate.py `
    --weights /workspace/runs/rgb_y11s_960/weights/best.pt `
    --data /data/uavcb/yolo_rgb/data.yaml --split test --confs 0.25,0.5
```

输出 Precision / Recall / mAP@0.5 / mAP@0.5:0.95 + 每类细分 + 推理耗时，
同时写一份 JSON 到 `runs/<name>/eval_test.json`。

**报告里必须注明**（需求 §3.2.1 明列的）：

- 置信度阈值
- IoU 口径（NMS 用的 `--iou` 和评估用的 IoU 是两回事，别混）
- 输入尺寸 `imgsz`
- 测试划分与**样本数**
- 推理耗时 vs 端到端耗时（§3.2.2 要求分开）

**红线**：不得用测试集调参，否则指标不作数。

---

## 5. 第五步：推理接口（后端只认这一个文件）

`ml/infer.py` 是 README §8 约定的那个稳定接口：

```python
from ml.infer import UAVDetector

det = UAVDetector("weights/rgb_best.pt", imgsz=960)
boxes = det.detect(frame_bgr)      # frame_bgr: OpenCV 的 BGR ndarray
for b in boxes:
    print(b.x1, b.y1, b.x2, b.y2, b.score)   # 全部归一化到 [0,1]
    print(b.center)                          # 框中心，区域侵入判定用这个
print(det.last_elapsed_ms)                   # 纯推理耗时
```

三个刻意的设计：

1. **输出归一化坐标**，和数据库 `detections` 表的约定完全一致，后端不用再换算。
2. **`Box.center` 直接给中心点**——FR-09 的侵入判定就是"框中心是否在区域内"，
   后面写区域逻辑时不用再算。
3. **构造时自动 warmup**，否则第一个请求的耗时会因为 CUDA 首次编译难看得很，
   测端到端耗时时会误判。

---

## 6. 红外图为什么能直接丢给 YOLO

红外是**单通道灰度**，但 ImageNet/COCO 预训练权重是 3 通道。

**不需要手动转 3 通道。** `cv2.imread` 默认按 `IMREAD_COLOR` 读，灰度图会自动
复制成 3 通道 BGR；ultralytics 内部也是这样处理的。所以红外图可以直接复用
RGB 预训练主干——这是标准做法，不要自己写灰度→RGB 的转换。

> 反过来说，**数据准备阶段也不用管这件事**，`prepare_yolo.py` 只管坐标。

---

## 7. 常见问题

| 症状 | 原因 | 处理 |
|---|---|---|
| `一张图都没匹配上标注` | 图片名和标注名对不上 | 跑 `inspect_dataset.py` 比对文件名 |
| `[FAIL] 没找到 .xml/.json` | `--ann-dir` 传错 | 检查目录；相对路径会拼到 `--root` 上 |
| 训练 `CUDA out of memory` | batch/imgsz 太大 | 降 `--batch`，或开 AMP（已默认开） |
| `torch.cuda.is_available() == False` | 容器没带 `--gpus` | 用 `--profile ml`，确认 compose 里 `deploy.resources` |
| mAP 高得离谱（>0.95） | **数据泄漏** | 检查 `--group-regex`，看三个集合场景是否互斥 |
| 小目标基本检不出 | 分辨率不够 | 提高 `--imgsz`，别只调置信度阈值 |

---

## 8. 单模态做完之后

两条线可以并行：

- **算法**：双模态融合（`models/fusion/`，先做结果级）、自适应策略（`selector/`）
- **工程**：把 `infer.py` 接进后端，跑通「上传 → 检测 → 存库」闭环

工程线不依赖算法线的最终精度，**先接通再优化**，这样 12 月一定有能演示的东西。

---

## 9. 该数据集上的公开基线（论文 Table 2）

训练前先知道"及格线"在哪。以下数字来自 UAV-CB 原论文（CVPR 2026）在**本数据集**上的实测，
可以直接作为你们报告里的对照组和追赶目标：

| 方法 | 模态 | AP50 | AP75 | AP(.5:.95) | 参数量 | FLOPs |
|---|---|---|---|---|---|---|
| YOLOv5s | 可见光 | 65.4 | 37.1 | 37.6 | 7.2M | 13.5G |
| YOLOv5s | **热红外** | **78.2** | 48.1 | 41.2 | 7.2M | 13.5G |
| YOLOv5s+Add（朴素拼接融合） | RGB+T | 72.8 | 45.2 | 38.5 | 13.5M | 26.4G |
| YOLOv5s+CMX | RGB+T | 74.3 | 46.5 | 39.8 | 15.2M | 30.4G |
| SFDFusion | RGB+T | 79.2 | 51.8 | 49.0 | 21.5M | 58.5G |
| C2Former | RGB+T | 79.4 | 53.8 | 49.1 | 100.8M | 324G |
| LFBNet（该论文） | RGB+T | **84.6** | **57.2** | **54.4** | 30.2M | 65.2G |

### 三个直接影响你们结论的发现

**① 热红外单模态明显强于可见光**

AP50 是 78.2 vs 65.4，高了将近 13 个点。这**动摇了「自适应选择」的默认叙事**——
如果红外在整体上一直更强，那"根据光照自动切模式"的价值就要重新论证。

建议：把分析从"整体谁强"改到"**分场景谁强**"（论文把背景分成建筑 / 植被 / 电塔 /
云层 / 地面五类）。自适应策略真正的价值应该体现在**分场景的互补性**上，
而不是总平均值。这条想清楚了，报告才有说服力。

**② 朴素融合会让效果变差**

`YOLOv5s+Add` 只有 72.8，**低于热红外单模态的 78.2**。加了两路信息反而退步。

原因就是两模态未配准——直接按通道拼接，等于往特征里灌噪声。
所以你们的对比实验里**必须包含单模态基线**，否则无法说明融合到底有没有用。

**③ 融合要涨点，必须自带对齐机制**

SFDFusion / C2Former 能到 79+，都是在融合前做了跨模态对齐。
而能从 79 跳到 84.6 的 LFBNet，核心贡献正是频率域对齐。
**结论：对齐模块才是融合的关键，融合操作本身不是。**

### 论文的训练设置（说明复现难度）

| 项 | 值 |
|---|---|
| GPU | **A100 40GB** |
| backbone | ResNet-50 |
| 输入尺寸 | 640×512（RGB 先裁剪粗配准到热红外视场，再 resize） |
| epochs | 200 |
| batch | 16 |
| 优化器 | SGD, lr=0.01, momentum=0.9, weight_decay=5e-4, cosine |
| 数据划分 | 6:2:2（3442 对） |

> 注意它对**融合层"未配准"是用两种手段一起处理的**：预处理阶段把 RGB 裁剪粗配准到
> 热红外视场，网络里再用 FGSA 做可变形精对齐。也就是说**光靠网络结构不够**，
> 预处理那一步也得跟上——这条很容易被漏掉。

在 6GB 的 4050 上照搬这套（双流 ResNet-50 + 640×512 + batch 16）**必然 OOM**。
现实目标是：用 YOLO11s 级别的轻量 backbone，跑通单模态基线，再把融合做在特征层。
**先追平 YOLOv5s 的单模态数字，再谈超越。**
