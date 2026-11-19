# 独立前端（frontend/app）

> 依据：`docs/登录界面.docx` 里你画的前端构想
> 状态：**已实现并通过实际渲染验证**（用无头 Edge 截图核对过四个页面）

---

## 1. 怎么跑

```powershell
docker compose up -d                       # 后端 8000 + 数据库
docker compose --profile web up -d         # 前端 5173
```

打开 **<http://localhost:5173/>**，用 `admin / Admin@12345` 登录。

### 多页结构（每个界面一个独立 URL）

```
http://localhost:5173/login.html         登录
http://localhost:5173/register.html      注册
http://localhost:5173/tasks.html         检测任务列表
http://localhost:5173/task.html?id=17    检测详情
http://localhost:5173/alerts.html        报警情况
```

`index.html` 只是个跳转入口：有 token 去 `tasks.html`，否则去 `login.html`。
页面之间用普通 `<a href>` 跳转，没有 hash 路由。

前端是**纯静态站点、无需构建**：原生 JS，没有任何 npm 依赖。
`frontend/app` 通过 bind mount 挂进一个 `python:3.11-slim` 容器，
用 `python -m http.server` 托管（这个镜像本地已有，不用拉新镜像）。

> 以后前端组员要上 Vue，只需替换 `frontend/app` 的内容，
> 或者把 compose 的 `web` 服务换回 `docker/web.Dockerfile`（已留好）。

---

## 2. 页面与后端接口的对应

| 文档里的界面 | 实现页面 | 用到的接口 |
|---|---|---|
| 登录界面 1：常规登录 | `login.html` | `POST /api/auth/login`、`GET /api/auth/me` |
| 登录界面 2：常规注册 | `register.html` | `POST /api/auth/register`（**受开关控制**） |
| 业务界面 1：检测任务列表 | `tasks.html` | `GET /api/detect-tasks` |
| 业务界面 2：检测详情 | `task.html?id=N` | `GET /api/detect-tasks/{id}`、`/frames`、`/detections`、`GET /api/media/{id}/video` |
| 业务界面 3：报警情况 | `alerts.html` | `GET /api/alerts`、`POST /api/alerts/{id}/confirm` |

### 界面 1 的字段（文档要求逐条对上）

文档要求「媒体名+扩展名、长、宽、帧率、总帧数、总时长」，表格列依次是：

```
ID | 媒体文件 | 分辨率 | 帧率 | 总帧数 | 总时长 | 模式 | 状态 | 处理帧数 | 耗时 | 创建时间
```

双击任意行进入界面 2（**只响应双击**，避免单击误跳）。

### 界面 2 的实现方式

- **自动播放**：进页面即播（见下面 §5.3，浏览器要求静音）
- **进度条 + 播放/暂停 + 跳看**：`<video>` 元素原生能力，后端 `/media/{id}/video` 支持 HTTP Range
- **逐帧**：`currentTime ± 1/fps`（用 `media.fps`）
- **报警帧醒目标记**：进度条上按 `frame_ts_ms / duration_ms` 定位红色竖标；下方另有「报警帧」快捷按钮，点击跳到该帧时间点并**自动恢复播放**
- **检测框叠加**：canvas 覆盖层，按当前播放时间选**最接近的已处理帧**绘制；绿色=区域外，红色=侵入

### 界面 3 的实现方式

缩略图卡片网格，每张卡显示：媒体名、帧号、时间、分数、出现次数、确认状态 + 确认按钮。
点卡片跳到界面 2 的对应任务。

---

## 3. 后端为这个前端补了什么

四件事，都很小但缺一不可：

| 补充 | 为什么需要 |
|---|---|
| **CORS**（只放行 5173 / 8000） | 前端和后端不同源，浏览器默认拦跨域请求 |
| `GET /api/media/{id}/video` | 播放和跳看需要原始视频；`FileResponse` 自带 Range → 可拖进度条 |
| 任务响应带 `media` 摘要 | 界面 1 要显示媒体名/分辨率/帧率/帧数/时长。放进任务响应里，20 条任务就省掉 20 次额外请求（避免 N+1） |
| 告警响应带 `snapshot_url` + `media_name` | 界面 3 的缩略图与媒体名。（媒体名是批量查的，同样避免 N+1） |

另外加了 `POST /api/auth/register`，但**默认关闭**——原因见下。

---

## 4. ⚠️ 注册与需求说明书冲突

`docs/登录界面.docx` 要求登录页有「注册」跳转。但**需求说明书 FR-01 明确写着**：

> 支持登录和退出；管理员创建、禁用账户及重置密码，**不开放自主注册**。

而且 §5.1 的验收里会检查这套账户体系。所以直接做开放注册有验收风险。

**处理方式**：接口存在但由开关控制，默认关闭。

```python
# backend/app/core/config.py
allow_self_register: bool = False    # 默认 False，合规
```

- 默认行为：注册页可以打开、可以填，提交后返回
  `403 REGISTER_DISABLED` → 页面提示「本系统不开放自主注册，请联系管理员开通账号」
- 演示/比赛想开放：在 `docker-compose.yml` 的 `api.environment` 里加
  `ALLOW_SELF_REGISTER: "true"`，重启即生效
- 自主注册的用户**只能拿到 `user` 角色**，不可能注册出管理员

> 这条建议你跟老师确认一下口径。如果老师同意开放注册，把开关打开就行；
> 如果严格按需求书，那这个「注册」按钮最好改成「申请账号」（走管理员审批），
> 而不是直接开注册。

---

## 5. 两个技术上的坑（都已处理，别再踩）

### 5.1 取图取视频必须走 fetch + blob

`<img src>` 和 `<video src>` 发出的请求**带不了 `Authorization` 头**，
而媒体接口都要鉴权 → 直接 401，页面表现为白屏/黑屏。

所以 `app.js` 里统一用 `blobUrl(apiPath)`：带 token fetch → `res.blob()` →
`URL.createObjectURL()`。带 Map 缓存，避免重复拉同一张缩略图。

> 这是把接口全部加密后的必然代价。更"正规"的做法是签发短时效的签名 URL
> （token 不进 URL、也不进浏览器历史），后续可以升级。

### 5.2 演示视频必须能被浏览器解码

**Chromium 内核不支持 MPEG-4 Part 2（`mp4v`）编码。** 用 OpenCV 生成的
`mp4v` 视频在浏览器里表现为黑屏 + 解码失败。

本项目 api 镜像里的 OpenCV **没有 libx264 编码器**（实测 `avc1`/`H264` 都
`opened=False`），所以**不要用 OpenCV 造 H.264 演示视频**。两条可行路线：

| 路线 | 命令 / 做法 |
|---|---|
| 真实素材（推荐） | 手机/相机录的 mp4 通常是 H.264，直接可用；不确定就转一次：<br>`ffmpeg -i in.mp4 -c:v libx264 -pix_fmt yuv420p out.mp4` |
| 没有 ffmpeg 时造测试片 | 用 OpenCV 写 **WebM + VP8**（Chromium 原生支持）：<br>`cv2.VideoWriter('x.webm', cv2.VideoWriter_fourcc(*'VP80'), 25, (w, h))`<br>实测 `readyState=4 / 640×360 / duration=3.00 / err=none`，可正常播放 |

前端已做兜底：6 秒拿不到元数据或触发 `error` 时，直接在画面上写出
「浏览器无法播放该视频」+ 转码命令，不会一直转圈。

### 5.3 自动播放需要静音

浏览器策略：**未静音的视频不允许自动播放**。所以 `task.html` 里：

```js
vid.muted = true;        // 静音是自动播放的前提
await vid.play();        // 被拦截则退回手动，并提示用户点「播放」
```

本项目的视频没有音轨，静音对体验没有影响。
如果自动播放被策略拦下（例如某些企业策略），页面会提示并保留播放按钮，
不会出现"点了没反应"。

> 实测：`play()` 返回 resolved，视频播到 `00:03/00:03`，画面与叠加框正常渲染。

---

## 6. 已知限制

| 限制 | 说明 |
|---|---|
| 叠加框只在"已处理帧"上更新 | 抽帧步长 5，所以框会每 5 帧跳一次（不是卡顿，是没有那些帧的数据） |
| 视频整段读进内存 | 为了鉴权走 blob；几分钟的演示视频没问题，长视频要改成签名 URL + Range |
| 逐帧步进依赖 `fps` | `fps` 缺失时按 25 兜底 |
| 报警框染色只标第一个框 | 前端不做几何判定，直接复用后端的 `intrusion_count`；精确到"哪个框侵入"以后端为准 |
| 没有上传入口 | 上传目前仍在 MVP 控制台（`/ui/`）；文档里的三个业务界面没提上传，如果需要可以加 |

---

## 7. 交给前端组员的建议

1. **先跑一遍再改**：`docker compose --profile web up -d` → 5173 看四个页面
2. **换 Vue 时接口不用动**：契约在 `docs/api.md`，本次新增的 video / media 摘要 /
   snapshot_url 已经写进该文档
3. **两个坑务必保留处理方式**：blob 取媒体、H.264 要求（见 §5）
4. **坐标是归一化的**：画框、画框叠加都基于 `[0,1]`，页面缩放要正确换算
   （需求 §3.2.1 是验收必查项）。MVP 里 `norm()` 的写法可以直接抄

### 文件结构

```
frontend/app/
├── index.html      入口，只做跳转（有 token → tasks，否则 login）
├── login.html      登录页
├── register.html   注册页
├── tasks.html      检测任务列表
├── task.html       检测详情（?id=N）
├── alerts.html     报警情况
├── common.js       公共逻辑：请求封装、鉴权、取 blob、格式化、顶栏注入
├── style.css       全部样式
└── pages/
    ├── login.js
    ├── register.js
    ├── tasks.js
    ├── task.js
    └── alerts.js
```

**加新页面**的做法：建一个 `xxx.html`（引入 `common.js` + `pages/xxx.js`），
在 `pages/xxx.js` 开头调 `await requireAuth(); mountTopbar('xxx');`，
再把入口加到 `mountTopbar` 的 `<nav>` 里。
