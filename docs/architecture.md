# 后端架构与接手说明

> 适用范围：MVP 阶段（模型未训练，检测用桩替代）
> 目标读者：接手继续开发的三位组员

---

## 1. 一句话

**核心逻辑是真的，模型是假的。** 自适应选模态、侵入判定、告警归并、权限隔离全部按需求实现并可测；
只有"这一帧哪里有无人机"由桩检测器返回假框。等单模态模型训好，改一个配置就切过去，**上层代码不用动**。

---

## 2. 分层与依赖方向

```
        HTTP 请求
           │
           ▼
   app/api/           ← 只做：参数校验、鉴权、调服务、返回 schema
           │           （不许写业务逻辑、不许直接构造 SQL）
           ▼
   app/services/      ← 业务逻辑。不碰 HTTP，可被脚本/测试直接调用
           │           （不许 import app.api）
           ▼
   app/models/  app/schemas/  app/core/
```

**依赖方向是单向的：api → services → models/schemas。**
违反这条最典型的后果是：想在脚本里复用逻辑，结果一 import 就把 FastAPI 拖进来。

| 目录 | 放什么 | 不许放什么 |
|---|---|---|
| `app/api/` | 路由、依赖注入、HTTP 状态码 | 算法、SQL 拼接、业务分支 |
| `app/services/` | 选择器、检测适配、侵入判定、分帧、编排 | Request/Response、Depends |
| `app/models/` | SQLAlchemy ORM | 业务规则 |
| `app/schemas/` | Pydantic 请求/响应 | 数据库查询 |
| `app/core/` | 配置、安全、鉴权依赖、错误类型 | 具体业务 |

---

## 3. 一次检测请求的完整调用链

以 `POST /api/detect-tasks` 为例，这是最值得看懂的一条路径：

```
api/tasks.py : create_task()
  ├─ 校验媒体存在 + 归属（owned_or_admin）
  ├─ 校验媒体 status == ready
  ├─ 建 DetectTask(status=pending) 并提交
  └─ services/pipeline.py : run_task()
        ├─ services/frames.py    读帧（stride 抽帧，最多 max_process_frames 帧）
        ├─ services/imaging.py   算第一帧的 亮度/对比度/清晰度
        ├─ services/selector.py  ① 决定模式 + 生成理由
        │                        （auto 走规则；手动模式只做输入校验）
        ├─ services/detector.py  ② 逐帧检测（桩 or 真模型）
        │                        fusion 模式下两路各测一次再 merge_boxes
        ├─ services/intrusion.py ③ 框中心是否落在区域内
        ├─ 告警归并（时间窗 + 位置相近 → 并入原告警）
        └─ 回填 task：actual_mode / decision_reason / 耗时 / frames_processed
```

**关键设计**：`run_task` 只依赖 `Session` 和 services。所以它既能被 API 同步调用，
也能直接丢进后台队列或脚本里跑，不用改一行。

---

## 4. 五个服务模块各自的职责

| 文件 | 职责 | 状态 |
|---|---|---|
| `services/selector.py` | **自适应选模态**（项目核心） | ✅ 真实实现，规则式 |
| `services/detector.py` | 推理适配层：`StubDetector` / `UltralyticsDetector` | ⚠️ 默认用桩 |
| `services/intrusion.py` | 点在多边形内判定（射线法，矩形=4 点多边形） | ✅ 真实实现 |
| `services/frames.py` | 分帧、`frame_index` 语义、帧图落盘 | ✅ 真实实现 |
| `services/pipeline.py` | 串联上面全部，写库 | ✅ 真实实现 |

### 4.1 自适应选模态的当前规则

判据来自**可见光帧**（热红外的亮度由探测器增益决定，不能当环境光用）：

```
无红外通道                → rgb   "红外通道缺失"
无可见光通道              → ir    "可见光通道缺失"
亮度 < 40                 → ir    "低照度（亮度均值=12.9 < 40），切热红外"
对比度 < 25 或 清晰度 < 100 → fusion "图像质量差，启用双模态协同"
否则                      → rgb   "光照与质量正常，使用可见光"
```

阈值在 `core/config.py` 的 `selector_*`，**是待标定的经验值**。
标定方法：拿标注集跑统计，看不同亮度/质量分箱下 RGB 与 T 各自的表现，再定分界点。
标完之后 `decision_reason` 里的数字会自动跟着变，因为理由是用实际值拼的。

### 4.2 桩检测器做了什么

`StubDetector` 按帧号确定性地产框，故意造出三种情况，好让页面状态都能被测到：

| 条件 | 行为 |
|---|---|
| `frame_index % 7 == 0` 且 `≠ 0` | 该帧**无目标**（`target_count=0`） |
| `frame_index % 5 == 0` | 该帧 2 个目标 |
| 其它 | 1 个目标 |

同一帧永远同样结果，所以回归测试稳定。

---

## 5. 怎么把桩换成真模型

**只需要两处改动，业务代码零改动：**

1. 训练出 RGB / IR 两份权重（见 `docs/training.md`）
2. 改环境变量（`docker-compose.yml` 的 `api.environment` 或 `.env`）：

```yaml
DETECTOR_BACKEND: ultralytics
RGB_WEIGHTS: /app/ml/weights/rgb_best.pt
IR_WEIGHTS:  /app/ml/weights/ir_best.pt
```

`services/detector.py` 会改用 `ml/infer.UAVDetector` 加载权重。
接口、表结构、前端一行都不用改——这正是把推理隔离成一层的目的。

> ⚠️ 真模型需要 torch，而当前 api 镜像是精简的（没有 torch）。
> 两种做法：
> - **推荐**：把推理拆成独立服务（用 `ml` 镜像），api 通过 HTTP 调用；
> - 或者把 api 镜像换成 CUDA 底座（体积会到 ~7GB，但 docker-compose 里已留好 `ml` 服务）。

---

## 6. 三人从哪接手

### 前端同学（C）

**现状**：`frontend/mvp/index.html` 单文件，由后端托管在 `/ui`，够用不好看。

**接手**：
1. 用 Vite 建 Vue 3 工程到 `frontend/`（保留 `frontend/mvp/` 作为参考）
2. 按 `docs/api.md` 对接，接口已经全部实现且可调
3. 重点做：**Canvas 画框的缩放换算**（需求 §3.2.1 必查）、六种状态区分、告警弹窗

MVP 里已经实现了拖拽画框 + 框叠加，可以直接抄坐标换算那段逻辑
（`norm()` 和 `render()`，用 `getBoundingClientRect` + 归一化，不用管 canvas 尺寸）。

**画框逻辑有回归测试**，改完先跑一次（不需要浏览器）：

```powershell
node frontend/mvp/test/draw.test.js frontend/mvp/index.html
```

它用桩 DOM 驱动真实脚本，断言 18 项行为：单击不留退化矩形、松开鼠标后移动不再改框、
反向拖拽要归一化、已保存区域必须被填充/描边/标名。坐标换算是需求 §3.2.1 的验收点，
肉眼看不出对错，靠这个兜。

### 后端同学（B）

**现状**：`auth / media / regions / tasks / alerts` 五个路由已通；缺 `users`（账户管理）和 `export`（Excel）。

**接手顺序**：
1. `users` 路由（管理员建号/禁用/重置密码）——契约在 `docs/api.md` §4
2. `export.xlsx` —— 列定义在 `docs/api.md` §8.2，**时间与状态的中文化要和页面共用同一个函数**
3. 检测改成异步（`BackgroundTasks` 或队列）+ 前端轮询——接口形状不用变，前端本来就在轮询

### 算法同学（A/B）

**现状**：`ml/` 五个脚本齐了，前两个（探数据、转格式）已实测；训练/评估/推理只做了语法检查。

**接手**：
1. 跑 `inspect_dataset.py` 看清 UAV-CB 标注格式
2. `prepare_yolo.py` 转格式（注意 `--group-regex` 防泄漏）
3. 训 RGB 与 IR 基线，追平 YOLOv5s 的数字（RGB 65.4 / IR 78.2 AP50，见 `docs/training.md` §9）
4. 有了权重再回 §5 切 `DETECTOR_BACKEND`

---

## 7. 自测怎么做

**每次改完 api/services，跑这个：**

```powershell
docker compose exec api python -m app.scripts.e2e_test
```

它用合成图片跑完整条链路（12 组断言），**不需要数据集、不需要模型**：

```
[1] 登录（含错误密码 401）
[2] 上传亮场景成对图
[3] 上传暗场景成对图
[4] 上传仅可见光
[5] 自适应 → 亮场景选 rgb
[6] 自适应 → 暗场景选 ir
[7] 手动指定 ir 但无通道 → 422
[8] 建区域（含退化区域被拒）
[9] 带区域重跑 → 侵入 → 告警
[10] 确认告警（重复确认 → 409）
[11] 未授权/伪造 token → 401
[12] /ui 可访问
```

跑完会自动删掉测试数据，不留脏数据。

另外还有 `python -m app.scripts.smoke_test`，它只测数据库层（建表对不对）。

---

## 8. 已知限制（MVP 有意为之，别当 bug）

| 限制 | 原因 | 什么时候解决 |
|---|---|---|
| 检测**同步**执行，长视频会阻塞请求 | 简化前端逻辑 | 后端同学下一步 |
| 单任务最多处理 `max_process_frames=30` 帧 | 前端不卡住 | 异步化后放开 |
| 没有 Excel 导出 | 没排进 MVP | 后端同学 |
| 没有用户管理界面 | 只有 seed 出的 admin | 后端同学 |
| 告警归并只用"时间窗 + 位置相近" | 够用 | 演示后看效果再调 |
| 帧图全量落盘（每帧一张 jpg） | 前端要按帧取图 | 量大后改成按需生成 |
| 视频的 RGB/IR 同步靠**按顺序同帧号读取** | 未做时间戳对齐 | 见 README §12-Q4 |

---

## 9. 加新接口的步骤（照抄这个顺序）

1. `app/schemas/xxx.py` 定义请求/响应模型 → 在 `schemas/__init__.py` 导出
2. `app/services/xxx.py` 写业务逻辑（不碰 HTTP）
3. `app/api/xxx.py` 写路由（依赖 `current_user`、`owned_or_admin`）
4. `app/api/__init__.py` 里 `include_router`
5. `app/scripts/e2e_test.py` 里补一组断言
6. 更新 `docs/api.md`

**别跳第 5 步**——e2e 是唯一能在模型换掉后仍然有效的回归网。


---

## 附录：待优化 —— 检测改为异步（交给后端同学）

### 现状

`POST /api/detect-tasks` 是**同步**的：请求一直阻塞到整段视频跑完才返回。
实测（5610 帧 / 93 秒视频，RTX 4050 GPU 推理）：

| max_process_frames | 采样间隔 | 耗时 | 覆盖率 |
|---|---|---|---|
| 30（旧） | 只覆盖开头 | 22.6 秒 | **0.5%** ❌ |
| 100（现用） | 0.95 秒 | **39.6 秒** | 99.6% |
| 200 | 0.48 秒 | 58.8 秒 | 99.8% |

所以现在取 **100**：200 帧已经接近浏览器/反向代理的 60 秒超时线，视频再长必超时。

### 改造建议（接口形状不用变）

前端已经在轮询 `GET /api/detect-tasks/{id}`，所以只需要后端改成"先返回再算"：

1. `POST /api/detect-tasks` 立刻返回 `202` + `{id, status: "queued"}`
2. 用 FastAPI 的 `BackgroundTasks` 或一个后台线程调 `run_task`
3. `status` 自然流转：`queued → running → succeeded/failed`（枚举已存在）
4. 前端把「开始检测」改成"跳详情页 + 轮询状态"，并显示进度
5. 跑通后可以把 `max_process_frames` 放开到 300（每 0.32 秒一个样本）

### 两个注意点

- `run_task` 内部自己 commit，不需要额外事务包装
- **并发会抢 GPU**：加一个简单的信号量（全局同一时刻只允许一个检测任务在跑），
  否则两个用户同时上传会让显存 OOM


---

## 附录二：接入真模型后暴露的两个集成问题（2026-11-24）

### 问题 1：fusion 模式对同一架无人机会输出两个框

**现象**（实测，同一帧成对上传，`DETECTOR_BACKEND=ultralytics`）：

| 请求模式 | 实际模式 | 检出数 | 分数 |
|---|---|---|---|
| `auto` | rgb | 1 | 0.807 |
| `ir` | ir | 1 | 0.791 |
| **`fusion`** | fusion | **2** | 0.807 + 0.791 |

同一架无人机被检出两次。

**根因**：两个模态的归一化坐标**不在同一坐标系**。

- 可见光模型输出的框是相对**整幅 16:9 画面**
- 热红外模型输出的框是相对 **5:4 视场**（只覆盖可见光中间一块）
- `merge_boxes` 用 IoU > 0.5 去重，但两组框的 IoU 远低于 0.5，匹配不上

实测两组坐标的残差（UAV-CB 上量的）：即使按「居中裁 5:4」这个最优假设，
中位残差仍有 **31 px（1.6% 图宽）**，纵向还有 **36 px 的固定偏移**——
两台相机的安装基线不为零，不是简单裁剪能对齐的。

**影响**：

- fusion 模式目前**不能用于演示**（会看到两个框）
- 任何结果级融合（包括 WBF）在坐标对齐之前都无法正确工作
- 用户做的「块级模态选择」也依赖这一步

**三种修法**：

| 方案 | 做法 | 误差 | 适用场景 |
|---|---|---|---|
| **A. 相机标定（推荐）** | 拍棋盘格求一个固定单应矩阵 H，把热红外框映射到可见光坐标 | 1~2 px | 自己的设备，一次标定长期可用 |
| B. 5:4 居中裁剪近似 | 假设热红外视场 = 可见光居中 5:4 区域 | ~1.6% 图宽 + 36 px 纵向偏移 | 只有 UAV-CB 这类没给标定参数的数据 |
| C. 分屏显示 | 热红外块改用热红外画面显示 | 无误差（但画面割裂） | 播放器能同时拿到两路视频 |

**先做 A**：真实系统必须标定，否则框会系统性偏移，演示效果会很差。

### 问题 2：单张热红外图会被判成「可见光模式」

**现象**：直接把一张热红外图传到上传页的「可见光」槽位 → 判定为 rgb 模式 →
用**可见光模型**去跑热红外图 → **0 检出**。

接入真 RGB 模型之前没暴露这个问题：当时 `RGB_WEIGHTS` 指向热红外模型占位，歪打正着能出框。

**根因**：模态判定依据是「哪个通道的文件存在」（`has_ir`），**不是图像内容**。
单个文件上传时 `has_ir=False`，`selector` 只能选 rgb。

**两种修法**：

| 方案 | 做法 | 工作量 |
|---|---|---|
| **A. 上传页加模态选择（推荐）** | 加「素材类型：自动 / 可见光 / 热红外」下拉；显式选择时直接指定 modality | 前端半天 + 后端 `TaskCreate` 接受显式 `ref_modality` |
| B. 只写文档 | 热红外图必须放到「红外」槽位、并与可见光成对上传 | 0（但很容易踩） |

推荐 A：用户不需要理解「槽位」概念，演示时也不会踩。

### 复现命令

```bash
# 前提：ml/weights 下有两份权重，.env 里 DETECTOR_BACKEND=ultralytics
docker compose exec -T api python -c "
import httpx
c = httpx.Client(base_url='http://localhost:8000', timeout=300)
tok = c.post('/api/auth/login', json={'username':'admin','password':'Admin@12345'}).json()['access_token']
H = {'Authorization': 'Bearer ' + tok}
vp = '/data/uploads/uavcb/building/visible/building_visible_1_000002.jpg'
tp = '/data/uploads/uavcb/building/thermal/building_thermal_1_000002.jpg'
with open(vp,'rb') as fv, open(tp,'rb') as ft:
    m = c.post('/api/media', headers=H, files={
        'file': ('pair_visible.jpg', fv, 'image/jpeg'),
        'ir_file': ('pair_thermal.jpg', ft, 'image/jpeg')}).json()
for mode in ('auto','ir','fusion'):
    t = c.post('/api/detect-tasks', headers=H,
               json={'media_id': m['id'], 'requested_mode': mode}).json()
    d = c.get(f\"/api/detect-tasks/{t['id']}/detections\", headers=H).json()
    print(mode, '->', t.get('actual_mode'), len(d), [round(x['score'],3) for x in d])
"
```

预期输出里 `fusion -> fusion 2 [...]`，就是问题 1 的症状。
