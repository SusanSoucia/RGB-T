# 接口与业务约定（冻结草案）

> 版本 **v0.1-draft**｜2026-11-16
> **这份文档的目的：让前端、后端、算法三方在模型还没训出来之前就能并行开发。**

为什么现在就要冻结它：算法精度、融合效果、自适应阈值都必须等训练结果，但
**接口形状、坐标约定、状态取值、错误码**完全不依赖精度。这几样一旦后期才定，
前后端已经写好的代码都要返工，而且是最烦的那种返工。

字段名与 `backend/app/models/` 中的 ORM 模型**严格一致**，改这里必须同步改模型
（或反之），否则前后端对接时会对不上。

---

## 1. 三条最容易翻车的全局约定

先看这三条。它们被违反的话，后期返工量最大。

### 1.1 坐标：一律归一化到 [0,1]

- 所有框和区域坐标都是 **`[0,1]` 的浮点数**，原点是左上角。
- 基准画面由 **`ref_modality`** 指定，**默认 `rgb`**。
- 换算像素：`px = x * media.width`（红外用 `media.ir_width/ir_height`）。

**前端注意**：Canvas 画框时先按显示尺寸取像素，再除以 canvas 的实际绘制尺寸转成
归一化值提交。**永远不要在接口里传像素值**，否则页面一缩放就错位。

### 1.2 时间：全部 ISO 8601 带时区

- 统一 `2026-11-16T18:32:00+08:00` 格式（Asia/Shanghai）。
- 数据库字段是 `timestamptz`。
- **`created_at` 是系统处理时间，不是拍摄时间**。视频里的拍摄时刻用
  `frame_ts_ms`（该帧在源视频中的毫秒偏移）表达。需求 §3.3 明确要求区分这两者。

### 1.3 状态：取值固定，不允许自由发挥

| 字段 | 允许值 |
|---|---|
| `users.role` | `admin` / `user` |
| `media.media_type` | `video` / `image` |
| `media.status` | `uploaded` / `parsing` / `ready` / `failed` |
| `detect_tasks.requested_mode` | `rgb` / `ir` / `fusion` / `auto` |
| `detect_tasks.actual_mode` | `rgb` / `ir` / `fusion`（**不含 auto**） |
| `detect_tasks.status` | `pending` / `running` / `succeeded` / `failed` / `timeout` |
| `detect_tasks.ref_modality` | `rgb` / `ir` |
| `regions.shape_type` | `rect` / `polygon` |
| `alerts.status` | `unconfirmed` / `confirmed` |

> 注意 `requested_mode` 和 `actual_mode` 是**两个字段**。
> 用户可以请求 `auto`，但实际执行的一定是三个具体模式之一，而且必须能说明为什么
> （`decision_reason`）。这是需求 FR-05/FR-06 的硬要求。

### 1.4 帧号：`frame_index` 是原始视频帧号

- **定义**：原视频中的帧号，**从 0 起**，不是"抽帧后的第几个样本"。
- `frame_stride = 5` 时它会是 `0, 5, 10, 15...`，**跳跃是正常行为**。
- 换算时间：`frame_ts_ms = frame_index / fps * 1000`。

> 这两者的区别是 **5 倍**，而且"看起来都对"。定死它是为了避免前后端和报告里
> 出现互相矛盾的帧号。

---

## 2. 通用约定

### 2.1 统一响应包装

```json
{ "items": [...], "total": 128, "page": 1, "page_size": 20 }
```
单对象直接返回对象本体，不做包装。

### 2.2 统一错误格式

```json
{ "code": "MODE_INPUT_MISMATCH", "message": "请求红外模式，但该视频没有红外通道", "detail": null }
```

**前端按 `code` 做分支，不要靠 `message` 文本匹配**（改文案就崩）。

### 2.3 认证

- `Authorization: Bearer <token>`（JWT）
- 除 `/api/auth/login` 外全部需要认证。
- Token 过期返回 `401 AUTH_TOKEN_EXPIRED`，前端跳登录页。

### 2.4 分页参数

`?page=1&page_size=20`（`page_size` 上限 100）。列表接口默认按 `created_at` 倒序。

---

## 3. 认证 `/api/auth`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/logout` | 退出 |
| GET | `/api/auth/me` | 当前用户信息 |

**登录请求**
```json
{ "username": "admin", "password": "********" }
```
**登录响应**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": { "id": 1, "username": "admin", "display_name": "系统管理员", "role": "admin" }
}
```

> 需求说明书的 FR-01 原写「不开放自主注册」，**已确认该条为笔误**，实际支持自主注册。
>
> | 情形 | 返回 |
> |---|---|
> | 开关开启（**默认**） | `201` + 用户信息；用户名重复返回 `409 AUTH_USERNAME_TAKEN` |
> | 开关关闭（`ALLOW_SELF_REGISTER=false`） | `403 REGISTER_DISABLED`「管理员暂时关闭了自主注册」 |
>
> 自主注册只能得到 `user` 角色，不可能注册出管理员。详见 `docs/frontend.md` §4。

---

## 4. 用户管理 `/api/users`（仅 admin）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users` | 列表 |
| POST | `/api/users` | 创建（含初始密码） |
| PATCH | `/api/users/{id}` | 改昵称 / 启用禁用 / 改角色 |
| POST | `/api/users/{id}/reset-password` | 重置密码 |

**创建请求**
```json
{ "username": "member_c", "password": "temp-pwd-123", "display_name": "成员C", "role": "user" }
```

> 密码只进不出。任何接口都**不得返回 `password_hash`**。

---

## 5. 媒体 `/api/media`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/media` | 上传（`multipart/form-data`） |
| GET | `/api/media` | 列表（仅本人；admin 看全部） |
| GET | `/api/media/{id}` | 详情（含解析结果） |
| DELETE | `/api/media/{id}` | 删除（级联删任务/区域/告警） |
| GET | `/api/media/{id}/image` | 原始画面（画框用；**仅图片类型**，视频返回 422） |
| GET | `/api/media/{id}/frames/{frame_index}` | 处理过的某一帧（视频取图用这个） |
| GET | `/api/media/{id}/video` | 原始视频流（支持 HTTP Range，可拖进度条跳看） |

**上传字段**

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | ✅ | 可见光视频/图片 |
| `ir_file` | ❌ | 红外文件，成对时提供 |

**返回**
```json
{
  "id": 12,
  "original_name": "site_a_night.mp4",
  "media_type": "video",
  "status": "parsing",
  "has_ir": true,
  "width": 1920, "height": 1080,
  "ir_width": 640, "ir_height": 512,
  "fps": 25.0, "duration_ms": 60000, "total_frames": 1500,
  "frame_stride": 5,
  "error_message": null,
  "created_at": "2026-11-16T18:32:00+08:00"
}
```

**上传后是异步解析**：立刻返回 `status=parsing`，前端轮询 `GET /api/media/{id}`
直到 `ready` 或 `failed`。不要同步阻塞（视频解析可能几十秒）。

---

## 6. 警戒区域 `/api/regions`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/regions` | 创建 |
| GET | `/api/regions?media_id=12` | 按媒体查 |
| PATCH | `/api/regions/{id}` | 改名 / 改点 / 启停 |
| DELETE | `/api/regions/{id}` | 删除 |

**创建请求**
```json
{
  "media_id": 12,
  "name": "东侧围墙",
  "shape_type": "rect",
  "points": [[0.10, 0.20], [0.55, 0.20], [0.55, 0.70], [0.10, 0.70]]
}
```

**`points` 规则（前后端都要遵守）**

- 归一化 `[0,1]`，`[[x, y], ...]`。
- `rect`：**恰好 4 个点**，顺序为「左上 → 右上 → 右下 → 左下」，前端必须按此顺序提交
  （不做凹多边形合法性推断，避免双方理解不一致）。
- `polygon`：≥ 3 个点，按顶点顺序。
- 后端校验：点数、取值范围、矩形是否退化（宽或高为 0）。
- 区域**绑定到具体 media**，不跨场景复用（FR-08）。

**侵入判定的约定（后端实现，前端只需知道规则）**

- 判定依据：**检测框中心点**是否落在区域内。
- **边界上的点算作区域内**（候选规则，见需求「需补充」项，若导师改口径要一起改）。
- 未设置区域时：**只检测、不产生区域告警**。
- 多区域：命中任一区域即告警，`alerts.region_id` 记录命中的那个。

---

## 7. 检测任务 `/api/detect-tasks`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/detect-tasks` | 发起检测 |
| GET | `/api/detect-tasks` | 列表 |
| GET | `/api/detect-tasks/{id}` | 详情（含进度与耗时） |
| GET | `/api/detect-tasks/{id}/detections` | 分页取检测框 |
| POST | `/api/detect-tasks/{id}/cancel` | 取消（可选） |

**发起请求**
```json
{ "media_id": 12, "requested_mode": "auto" }
```

**返回 202**
```json
{
  "id": 88,
  "media_id": 12,
  "requested_mode": "auto",
  "actual_mode": null,
  "decision_reason": null,
  "ref_modality": "rgb",
  "status": "pending",
  "queued_at": "2026-11-16T18:32:00+08:00"
}
```

**状态机（固定）**
```
pending ──► running ──► succeeded
                │
                ├──► failed    （模型未加载 / 显存不足 / 推理异常）
                └──► timeout
```

**完成后**
```json
{
  "id": 88, "status": "succeeded",
  "requested_mode": "auto",
  "actual_mode": "ir",
  "decision_reason": "低照度(亮度均值=12.3 < 40)，切红外",
  "ref_modality": "rgb",
  "started_at": "...", "finished_at": "...",
  "elapsed_ms": 840,
  "inference_ms_total": 610,
  "frames_processed": 300
}
```

> **`decision_reason` 是给人看的**，要能直接展示在页面上。写成人话，不要写枚举。

**检测框列表**
```json
{
  "items": [
    { "id": 9001, "frame_index": 120, "frame_ts_ms": 4800,
      "class_name": "uav", "score": 0.87,
      "x1": 0.42, "y1": 0.31, "x2": 0.48, "y2": 0.39,
      "ref_modality": "rgb" }
  ],
  "total": 300, "page": 1, "page_size": 20
}
```

> 一个视频可能几万个框。**不要一次全返回**，前端要按帧翻页或请求当前帧。

### 7.1 帧级结果（时间轴）`GET /api/detect-tasks/{id}/frames`

每处理一帧就有一条记录，**包含没有检出目标的帧**。

| 参数 | 说明 |
|---|---|
| `intrusion_only` | `true` 时只返回有侵入的帧 |
| `with_target` | `true` 时只返回检出了目标的帧 |
| `page` / `page_size` | 分页 |

```json
{
  "items": [
    { "frame_index": 120, "frame_ts_ms": 4800,
      "target_count": 1, "intrusion_count": 1,
      "max_score": 0.87, "inference_ms": 2 },
    { "frame_index": 125, "frame_ts_ms": 5000,
      "target_count": 0, "intrusion_count": 0,
      "max_score": null, "inference_ms": 2 }
  ],
  "total": 300, "page": 1, "page_size": 50
}
```

前端用它做两件事：

1. **判断某帧的状态**：`target_count == 0` → 无目标；`intrusion_count > 0` → 区域侵入
2. **画时间轴**：横轴帧号、纵轴 `max_score`，标出 `intrusion_count > 0` 的区间

> ⚠️ `frame_index` 是**原始视频帧号**，`frame_stride=5` 时是 `0,5,10...`，**跳跃是正常的**。
> 不要假设它连续，也不要把它当成"第几个样本"。

---

## 8. 告警 `/api/alerts`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/alerts` | 列表 + 筛选 |
| GET | `/api/alerts/{id}` | 详情（含截图 URL） |
| POST | `/api/alerts/{id}/confirm` | 确认 |
| GET | `/api/alerts/export.xlsx` | 导出（**筛选条件与列表完全一致**） |

**筛选参数（列表和导出共用同一套，保证结果一致）**

`?status=&mode=&from=&to=&media_id=&page=&page_size=`

**确认识别**
```json
{ "id": 301, "status": "confirmed",
  "confirmed_by": { "id": 3, "display_name": "成员C" },
  "confirmed_at": "2026-11-16T18:35:00+08:00" }
```

> 需求 FR-10：确认状态必须持久化。重复确认返回 `409 ALERT_ALREADY_CONFIRMED`。

### 8.1 告警归并规则（视频场景必须定）

同一 `(media_id, region_id)` 上，若新判定与**最上一条未确认告警**满足：

- 时间间隔 < `alert_merge_window_s`（**建议默认 3 秒，可配置**），且
- 目标位置相近（中心点距离 < `alert_merge_distance`，建议 0.1 归一化单位）

则**并入原告警**：`occurrence_count += 1`，`last_seen_at = 本帧时间`，
`score_max = max(score_max, 本次)`，**不新增记录**。

否则新建一条。

> 这不是目标跟踪，只是告警去重（README §12-Q2）。参数放配置，不要写死。

### 8.2 Excel 导出列（先定下来，前端和报告都要用）

| # | 列名 | 来源 |
|---|---|---|
| 1 | 告警编号 | `alerts.id` |
| 2 | 告警时间 | `first_seen_at`（按 Asia/Shanghai 格式化） |
| 3 | 来源文件 | `media.original_name` |
| 4 | 检测模式 | `detect_tasks.actual_mode` |
| 5 | 置信度 | `alerts.score_max`（保留 3 位小数） |
| 6 | 目标位置 | `x1,y1,x2,y2`（归一化，注明"归一化坐标"） |
| 7 | 区域名称 | `regions.name` |
| 8 | 出现次数 | `occurrence_count` |
| 9 | 确认状态 | `unconfirmed` → "未确认" / `confirmed` → "已确认" |
| 10 | 确认人 | `users.display_name` |
| 11 | 确认时间 | `confirmed_at` |

> 需求 §3.3：**导出里的时间和状态表达必须和页面一致**。中文化转换只做一次，
> 封装成公共函数，别在页面和导出里各写一套。

---

## 9. 权限矩阵

| 操作 | 普通用户 | 管理员 |
|---|---|---|
| 登录 / 退出 | ✅ | ✅ |
| 上传媒体 | ✅ | ✅ |
| 查看媒体/任务/检测结果 | **仅本人** | 全部 |
| 创建/修改区域 | 仅本人 | 全部 |
| 查看告警 | 仅本人 | 全部 |
| 确认告警 | **仅本人** | 全部（代确认需留痕） |
| 导出 | 仅本人 | 全部 |
| 用户管理 | ❌ | ✅ |

**实现要求**：每一条查询都必须带 `owner_id` 过滤（admin 走"不过滤"分支）。
**不要靠前端隐藏按钮来实现权限**——需求 FR-02 明确要求"后端须校验访问权限"，
验收时会直接用接口越权访问来测。

---

## 10. 错误码表

| code | HTTP | 含义 |
|---|---|---|
| `AUTH_INVALID_CREDENTIALS` | 401 | 用户名或密码错 |
| `AUTH_TOKEN_EXPIRED` | 401 | 登录失效 |
| `AUTH_ACCOUNT_DISABLED` | 403 | 账户已禁用 |
| `FORBIDDEN_NOT_OWNER` | 403 | 访问了别人的资源 |
| `RESOURCE_NOT_FOUND` | 404 | 资源不存在 |
| `MEDIA_UNSUPPORTED_FORMAT` | 415 | 格式不支持 |
| `MEDIA_TOO_LARGE` | 413 | 超出大小上限 |
| `MEDIA_IR_PAIR_MISSING` | 422 | 请求双模态但缺红外文件 |
| `MODE_INPUT_MISMATCH` | 422 | 请求的模式与实际输入不匹配（如请求 IR 但无 IR 通道） |
| `REGION_INVALID_POINTS` | 422 | 区域点非法（点数/范围/退化） |
| `TASK_NOT_READY` | 409 | 任务还没跑完就取结果 |
| `TASK_ALREADY_RUNNING` | 409 | 重复发起 |
| `ALERT_ALREADY_CONFIRMED` | 409 | 重复确认 |
| `MODEL_NOT_LOADED` | 503 | 模型未加载 |
| `INFERENCE_FAILED` | 500 | 推理异常 |
| `STORAGE_FAILED` | 500 | 落盘失败（明确提示保存失败，不能假装成功） |

---

## 11. 明确**现在不能定**的部分

以下内容依赖训练结果，本文档故意留空。**接口字段已经预留，等数字出来只填值，不改结构。**

| 待定项 | 依赖 | 接口里预留的字段 |
|---|---|---|
| 自适应选择的阈值（亮度/质量） | 基线实验统计 | `decision_reason` |
| 置信度/IOU 默认值 | 精度-召回权衡实验 | `confidence_threshold` / `iou_threshold` |
| 精度达标线 | 与导师商定 | — |
| 是否上特征级融合 | 时间与显存 | `actual_mode` 已含 `fusion` |
| `imgsz` 最终取值 | 小目标实验 | `imgsz` |
| 告警归并窗口 T | 演示效果调参 | 配置项，非字段 |

> 这就是"解耦"的核心：**把不确定的东西关进几个字段和配置项里**，
> 让它们的变化不会传导到接口和页面。

---

## 12. 独立前端（`frontend/app`）带来的增补

为支撑《登录界面.docx》里的三个业务界面，补了四处。**都是向后兼容的新增字段/接口**，
原有调用方不受影响。

### 12.1 `TaskOut` 增加 `media` 摘要

任务列表要显示媒体名/分辨率/帧率/帧数/时长。放进任务响应里，
避免前端为每条任务再查一次媒体（N 个任务 = N 次请求）。

```json
{
  "id": 17,
  "media_id": 14,
  "media": {
    "id": 14,
    "original_name": "site_night.mp4",
    "media_type": "video",
    "width": 640, "height": 360,
    "fps": 25.0,
    "total_frames": 60,
    "duration_ms": 2400,
    "frame_stride": 5,
    "has_ir": false
  }
}
```

### 12.2 `AlertOut` 增加两个展示字段

```json
{
  "id": 301,
  "media_name": "site_night.mp4",
  "snapshot_url": "/media/14/frames/35"
}
```

- `snapshot_url` 是**相对接口路径**（不含 `/api`），前端拼 base 后带 token 取图；
  该帧图不存在时为 `null`。
- 媒体名是**批量查询**后映射的，不做 N+1。

### 12.3 媒体资源的取用方式（重要）

`/media/{id}/image`、`/media/{id}/frames/{n}`、`/media/{id}/video` 都需要鉴权，
而 `<img src>` / `<video src>` **带不了 `Authorization` 头**，直接用会 401。

前端必须先用带 token 的 `fetch` 取回 blob，再 `URL.createObjectURL()` 交给标签：

```js
const res = await fetch(API_BASE + '/api' + path, {
  headers: { Authorization: 'Bearer ' + token },
});
const url = URL.createObjectURL(await res.blob());
```

> 更正规的方案是签发短时效签名 URL（token 不进 URL）。现阶段用 blob，
> 代价是视频要整段进内存，长视频需要升级。

### 12.5 上传后画框用的预览图

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/media/{id}/poster` | 可画框的静态预览图。图片返回原图；**视频取首帧转 JPEG**（不落盘） |

前端上传视频后要立刻划定警戒区域，就需要这张图——否则得先跑一次检测才能拿到帧。

### 12.6 导出标注视频

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/detect-tasks/{id}/render?refresh=false&format=auto` | 渲染并下载**区域轮廓 + 检测框**烧进画面的视频 |

- `format`：`auto`（默认）→ 有 ffmpeg 就出 **MP4/H.264**，否则 **WebM/VP8**；
  也可显式指定 `mp4` / `webm`。
- MP4 的编码器来自 pip 包 `imageio-ffmpeg` 自带的静态 ffmpeg（不依赖 apt）。
- 只对 `media_type=video` 的任务有效，静态图片返回 `422`。
- 结果缓存在 `settings.render_dir`，`refresh=true` 强制重渲染。
- 渲染是**同步**的：帧数上限由 `settings.render_max_frames`（默认 900）控制，
  超出按步长抽帧保证时长不变。
- 视频里的区域名默认英文 `Region N`（`cv2.putText` 只支持 ASCII）；
  把开源中文字体放进 `backend/app/assets/fonts/` 即可显示中文。

### 12.4 跨域

前端与后端不同源，属于跨域。后端已开 CORS：
除 `settings.cors_origins` 白名单外，用正则放行 `localhost` / `127.0.0.1` 的**任意端口**（不用 `*` 敞开公网来源）。

---

## 12. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1-draft | 2026-11-16 | 初版：全局约定、认证、媒体、区域、任务、告警、权限、错误码 |
