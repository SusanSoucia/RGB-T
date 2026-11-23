# Docker 开发环境指南

> 适用：三人小组，Windows 11 + RTX 4050 Laptop（6GB）
> 目标：**三人环境一致、环境搭一次就能重建、交付时能复现**

---

## 0. 先明确：什么进容器，什么不进

这是最重要的一节。全塞进容器是常见的新手误区——会花三天调环境，然后用上八周都觉得别扭。

| 组件 | 进容器？ | 理由 |
|---|---|---|
| **PostgreSQL** | ✅ 一定 | 收益最大。零安装、版本统一、`down -v` 就能重置，彻底消灭"我这表结构不一样" |
| **后端 FastAPI** | ✅ 建议 | Python 依赖地狱的克星；CI/部署直接复用同一个镜像 |
| **前端 Vue** | ⚠️ 可选 | 默认**在主机跑**。容器里的 Vite HMR 在 Windows 上要开轮询，反而更慢 |
| **训练 / 推理** | ⚠️ 双轨 | 日常炼丹用**主机 venv**（快）；复现和上服务器用**容器**（准） |

一句话：**容器解决"环境一致性"，不解决"训练速度"**。别拿它当加速器。

---

## 1. 安装 Docker Desktop（Windows）

### 1.1 检查前置条件

你已经满足：

```
WSL 版本       2.6.1.0        ✅
WSL 内核       6.6.87.2-1     ✅
Windows        10.0.26100     ✅（Win11 24H2）
显卡驱动       596.49         ✅（CUDA 12.x 容器需要 ≥527.41）
Docker         ❌ 未安装
```

### 1.2 安装步骤

1. 下载 **Docker Desktop for Windows (AMD64)**：<https://www.docker.com/products/docker-desktop/>
2. 双击安装，保持默认勾选 **Use WSL 2 instead of Hyper-V**
3. 安装完**重启电脑**
4. 启动 Docker Desktop，等左下角变绿（Engine running）
5. `Settings → Resources → WSL Integration`，勾选你要用的发行版
6. `Settings → General`，确认 **Use the WSL 2 based engine** 已勾选

> ⚠️ **驱动不要装在 WSL 里**。Windows 主机装好 NVIDIA 驱动即可，WSL 和容器会自动继承。
> 千万别在容器里装显卡驱动，会直接把 GPU 弄坏。

### 1.3 验证

打开**新的** PowerShell（旧终端不认新 PATH）：

```powershell
docker --version          # Docker version 27.x
docker compose version    # Docker Compose version v2.x
docker run --rm hello-world
```

### 1.4 国内网络加速（重要，**本机实测已确认必须配**）

> **实测记录（2026-11-16，本机）**：未配镜像加速器时，`postgres:16-alpine` 的单个层下载速度在
> **0 ~ 1MB/分钟**之间反复卡顿，420MB 的镜像耗时十几分钟；`python:3.11-slim` 与 pip 依赖处于同一情况。
> 配好加速器后速度通常会提升一个数量级。

去阿里云**容器镜像服务**控制台 → 镜像工具 → 镜像加速器，拿到专属地址，然后
`Settings → Docker Engine` 里改成：

```json
{
  "registry-mirrors": ["https://<你的ID>.mirror.aliyuncs.com"]
}
```

点 **Apply & Restart**。

**验证加速器是否生效**：

```powershell
docker info --format '{{json .RegistryConfig.Mirrors}}'
# 应该输出你的加速器地址；输出 [] 说明没配上
```

> 配好之后建议**先拉基础镜像**，把大件一次性拿到本地，后面构建就快了：
>
> ```powershell
> docker pull postgres:16-alpine
> docker pull python:3.11-slim
> ```

### 1.5 docker 命令找不到？

Docker Desktop 是**按用户安装**的（本机路径 `C:\Users\susan\AppData\Local\Programs\DockerDesktop`），
安装时会写进**用户 PATH**，但**已经打开的终端不会自动刷新**。

→ **关掉终端重开一个**就好了，不需要重启电脑。验证：`docker --version`。

### 1.6 ⚠️ 构建报 `failed to fetch oauth token` （本机实测会遇到）

**症状**：

```
failed to solve: failed to fetch oauth token: Post "https://auth.docker.io/token":
dial tcp 128.242.240.20:443: connectex: A connection attempt failed...
```

**原因**：BuildKit 构建时需要向 `auth.docker.io` 换 token，这条连接在当前网络下会超时；
但 `docker pull` 走守护进程是通的。所以会出现「能 pull、不能 build」的诡异现象。

**验证**：`docker pull hello-world` 能用（几秒），`docker compose build` 却失败 → 就是这个问题。

**两个解法，按顺序试**：

1. **配镜像加速器**（见 §1.4）——修好之后 BuildKit 也能用，这是正解。
2. **临时绕过：用传统构建器**

   ```powershell
   $env:DOCKER_BUILDKIT = "0"
   docker compose build api
   docker compose up -d
   ```

   注意 `DOCKER_BUILDKIT=0` 只对**当前终端窗口**有效，新开窗口要重新设。

   > 前提是基础镜像已在本地（`docker pull python:3.11-slim` 先拉好），
   > 否则传统构建器也会去 registry 取镜像，只是那条路径恰好能通。

**顺带一条经验**：Dockerfile 里**不要写** `# syntax=docker/dockerfile:1.7` 这类指令。
它会让 BuildKit 额外去 Docker Hub 拉一个 frontend 镜像，凭空多一次网络依赖，
网络一抖就 `BUILD FAILED`。本项目没用到任何 BuildKit 专有语法，不需要它。

> **许可证说明**：Docker Desktop 对学生、教育用途、个人使用、小型企业（<250 人且年收入 <1000 万美元）免费。学校课程项目属于免费范围。如果将来进企业做商用项目，需要订阅。

---

## 2. 验证 GPU 直通（最关键的一步）

**先单独验证，再谈项目。** 这一步不通，后面全是白费。

```powershell
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

**成功**：能看到和主机一样的 RTX 4050 表格。
**失败**：见 §8 排错表。

再验一次 PyTorch 能不能真用上 GPU：

```powershell
docker run --rm --gpus all pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime `
  python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

必须输出 `True NVIDIA GeForce RTX 4050 Laptop GPU`。

> 第一次跑要下载 ~7GB 镜像，慢是正常的。

---

## 3. 启动项目

```powershell
cd uav-alert-system

# 1) 准备本地配置（.env 不进仓库）
Copy-Item .env.example .env

# 2) 起数据库 + 后端
docker compose up -d

# 3) 看状态
docker compose ps
```

验证链路：

```powershell
curl http://localhost:17800/health        # {"status":"ok",...}
curl http://localhost:17800/health/db     # {"db":"ok","version":"PostgreSQL 16.x ..."}
```

**`/health/db` 返回 ok 才算环境搭好了**——它证明「容器网络 + 后端 → 数据库」整条链路通。

打开接口文档：<http://localhost:17800/docs>

---

## 4. 日常命令速查

```powershell
# 起 / 停 / 看
docker compose up -d                 # 后台启动 db + api
docker compose ps                    # 状态
docker compose logs -f api           # 跟后端日志
docker compose stop                  # 停止（保留数据）
docker compose down                  # 删除容器（保留数据卷）
docker compose down -v               # 连数据卷一起删 ⚠️ 数据库清空

# 改了 requirements.txt 之后
docker compose build api
docker compose up -d api

# 进容器里手动操作
docker compose exec api bash
docker compose exec db psql -U uav -d uav

# GPU 训练容器
docker compose --profile ml build ml                    # 首次构建（~7GB）
docker compose --profile ml run --rm ml bash            # 进容器
docker compose --profile ml run --rm ml python ml/train.py --config ml/configs/rgb.yaml

# 清理磁盘
docker system df                     # 看占用
docker system prune -a               # ⚠️ 清掉所有未使用镜像/容器
```

**PowerShell 小抄**：`curl` 是 `Invoke-WebRequest` 的别名，直接 `curl http://...` 会报错。
用 `curl.exe http://localhost:17800/health`（带 `.exe`）或者 `Invoke-RestMethod`。

---

## 5. 三人协作流程

### 5.1 仓库里放什么

✅ **提交**：`docker-compose.yml`、`docker/*.Dockerfile`、`requirements.txt`、`.env.example`、`.dockerignore`、`.gitattributes`
❌ **不提交**：`.env`、`data/`、`runs/`、`*.pt`、`node_modules/`

`.gitignore` 已经配好了。

### 5.2 怎么把环境给组员（三种方式，先看对比）

先明确一件事：**组员不需要你现在的「容器状态」，只需要能重建出一样的环境。**
容器、数据卷、数据库里的数据都是可以重新生成的；真正要共享的只有
`docker-compose.yml` + `Dockerfile` + `requirements.txt` 这几份**已经在 git 里的东西**。

| 方式 | 传什么 | 组员要做什么 | 体积 | 适合 |
|---|---|---|---|---|
| **A. 只给代码** | git 仓库 | `clone` 后本地构建 | 几百 KB | ✅ **默认选这个** |
| **B. 导出镜像 tar** | 一个 `.tar.gz` | `docker load` | ~400–500MB | 组员网络差、构建老是失败 |
| **C. 推镜像仓库** | 仓库地址 | `docker pull` | 0（走网络） | 长期协作、要反复更新 |

---

#### 方式 A：只给代码（推荐起点）

仓库里已经齐了。组员只需：

```powershell
git clone <仓库地址>
cd uav-alert-system
Copy-Item .env.example .env

$env:DOCKER_BUILDKIT = "0"      # ⚠️ 必须，否则大概率 BUILD FAILED（原因见 §1.6）
docker compose up -d --build
```

**前提**：组员能访问 Docker Hub。`docker pull` 是通的，慢但在走。

**优点**：零额外维护，改了依赖自动同步。
**缺点**：每人首次构建要下载基础镜像 + 装依赖，网络差时比较熬人。

---

#### 方式 B：导出镜像 tar（网络差时最稳）

组长这边导出已经构建好的镜像，组员直接导入，**完全不用构建、不用访问 Docker Hub**。

**直接用脚本，别手敲**（会自动打包三个镜像 + 压缩 + 生成校验和）：

```bash
bash scripts/export-images.sh
```

产物在 `dist/`（已 gitignore）：

```
uav-images-20261120.tar.gz         实测约 300MB
uav-images-20261120.tar.gz.sha256
```

把这两个文件传到网盘。**组员的上手步骤见 [docs/load-images.md](load-images.md)**，要点：

```bash
sha256sum -c uav-images-20261120.tar.gz.sha256   # 先验完整性
docker load -i uav-images-20261120.tar.gz        # 实测约 17 秒
docker compose up -d                             # 不能加 --build
docker compose exec api alembic upgrade head     # ← 建表（漏了会 500）
docker compose exec api python -m app.scripts.seed_admin  # ← 建管理员
```

> ⚠️ 三个坑：
> 1. 用 `--build` 会触发重新构建，导入的镜像就白导了 —— **组员起的时候不要带 `--build`**
> 2. **镜像里没有数据**，必须跑 `alembic upgrade head` 建表，否则页面直接 500
> 3. 镜像层本来就是压缩的，所以 1.4GB 的镜像导出后只有 **300MB**，
>    再 gzip 也压不下去 —— 上传网盘时按 300MB 估计时间

**优点**：不依赖任何网络，也绕开 apt/pip 的坑。
**缺点**：改了 `Dockerfile` 或 `requirements.txt` 后要重新导一次。
**日常改代码不用重导**——`backend/`、`frontend/` 都是 bind mount，改完保存就生效。

---

#### 方式 C：推到镜像仓库（长期最省事）

阿里云容器镜像服务（ACR）**个人版免费**，国内速度快。

```powershell
# 组长：登录 + 推送
docker login registry.cn-hangzhou.aliyuncs.com
docker tag uav-alert-api:dev registry.cn-hangzhou.aliyuncs.com/<命名空间>/uav-alert-api:dev
docker push registry.cn-hangzhou.aliyuncs.com/<命名空间>/uav-alert-api:dev
```

组员在 `docker-compose.yml` 的 `api` 服务下加一行，然后直接 pull：

```yaml
  api:
    image: registry.cn-hangzhou.aliyuncs.com/<命名空间>/uav-alert-api:dev
    build:                      # 保留，方便改了代码的人自己重建
      context: .
      dockerfile: docker/backend.Dockerfile
      target: dev
```

```powershell
docker compose pull api
docker compose up -d
```

> 有 `build:` + `image:` 两者时，Compose 的行为是：**本地找不到镜像才构建**。
> pull 下来之后就不会再构建了。

**优点**：一条命令更新，适合 12 月到 1 月频繁改依赖的阶段。
**缺点**：要注册账号、首次推送 1.15GB 上传也要等。

---

**给你的建议**：先用 **A** 让组员各自跑通一遍（这样他们能看懂环境是怎么来的），
谁构建失败就切 **B**。等 11 月底依赖稳定了，再上 **C** 做日常更新。

### 5.3 每人本地要做的（汇总）

不管用上面哪种方式，组员最终都是这套动作：

```powershell
git clone <仓库地址>
cd uav-alert-system
Copy-Item .env.example .env      # 改成本人端口，避免和别人冲突

# 路线 A（自建）：先拉基础镜像，再用传统构建器
docker pull python:3.11-slim
$env:DOCKER_BUILDKIT = "0"
docker compose up -d --build

# 路线 B（导入 tar）：先 docker load，再直接起，不要带 --build
# docker load -i uav-alert-api-dev.tar.gz
# docker compose up -d
```

`.env` 里各人的 `POSTGRES_PASSWORD` **可以不一样**（各自独立数据库），但**不能提交**。

**验收**：`docker compose ps` 两个服务都 `healthy`，且

```powershell
curl.exe http://localhost:17800/health/db    # {"db":"ok",...}
```

### 5.4 数据集怎么共享

`data/` 不进 git（3000+ 对图有几百 MB ~ 几 GB）。三个选择：

| 方式 | 适用 |
|---|---|
| 学校网盘 / 群里传压缩包 | 最省事，够用 |
| 放在课题组服务器，SSH 拉取 | 有服务器之后 |
| DVC / Git LFS | 版本化需求强时，但学习成本高，本项目不必 |

### 5.5 ❌ 不要分享这些

| 不要给 | 原因 |
|---|---|
| `.env` | 含密码。每人自己从 `.env.example` 拷一份 |
| 数据卷 `uav-alert_pgdata` | 每人独立数据库；表结构靠 `alembic upgrade head` 重建，不靠拷数据 |
| `data/uploads/` | 你的测试视频，跟别人无关，还占体积 |
| `runs/`、`*.pt` | 训练产物，各人自己跑自己的 |
| `__pycache__` | 会和别人的 Python 版本打架 |

**组员拿到环境后的第一件事不是「拷文件」，而是验证自己的能跑起来**：

```powershell
curl.exe http://localhost:17800/health/db
# {"db":"ok",...} 才算通
```


---

## 6. ⚠️ Windows 专用性能坑（会真实影响你）

### 6.1 bind mount 慢——训练时尤其明显

Windows 目录挂进 Linux 容器，**随机小文件读取可能慢 5–10 倍**。

```
❌ D:\datasets\uav\  →  /data        （NTFS → 9p/virtiofs，训练时帧读取会卡成 PPT）
✅ WSL2 内路径       →  /data        （原生 ext4，快得多）
```

**建议**：
- 数据集、`runs/` 输出放 **WSL2 文件系统里**（`\\wsl$\<发行版>\home\<你>\datasets`）
- 只有**代码**用 bind mount（文件少，且需要热更新）
- 实在要放 Windows 盘，就在 `ml` 服务里改用**命名卷**，先 `docker cp` 拷进去

### 6.2 文件监听不触发

Windows 的 bind mount 上 `inotify` 事件常常失效，表现为：**改了代码，`--reload` 没反应**。

已经处理：compose 里给 `api` 设了 `WATCHFILES_FORCE_POLLING=true`。
前端如果也用容器，需要额外的 `CHOKIDAR_USEPOLLING=true`（这也是**推荐前端在主机跑**的原因之一）。

### 6.3 换行符

Windows 写的 `.sh` 带 CRLF，在 Linux 容器里报 `bad interpreter: No such file or directory`。
已经用 `.gitattributes` 强制 `eol=lf`，团队统一即可。

### 6.4 内存

WSL2 默认最多吃主机一半内存，笔电容易卡。在 `C:\Users\<你>\.wslconfig` 里限制：

```ini
[wsl2]
memory=8GB
processors=6
swap=2GB
```

改完 `wsl --shutdown` 生效。

### 6.5 改了密码没生效（**最常见的坑**）

`POSTGRES_PASSWORD` 只在**数据卷第一次创建时**生效。改了 `.env` 但卷里存的是旧密码 → 连不上。

```powershell
docker compose down -v      # ⚠️ 会清空数据库
docker compose up -d
```

### 6.6 中文注释被写坏（**本项目真实踩过**）

PowerShell 5.1 的 `Set-Content` / `Out-File` **默认按系统 ANSI（GBK）编码写文件**，
用它改带中文注释的 `.py` / `.vue` / `.sql`，会把 UTF-8 中文写成乱码，直接导致
`SyntaxError: unterminated triple-quoted string literal` 这类莫名报错。

**规则**：

| 场景 | 正确做法 |
|---|---|
| 在编辑器（VS Code、PyCharm）里改 | 正常改，确保编码是 **UTF-8** |
| 用脚本批量改文件 | 必须显式指定 UTF-8：`Set-Content -Encoding utf8`，或改用 Python 读写 |
| 更推荐 | 用 VS Code 全局替换，别用 PowerShell 改源码 |

**排查命令**（怀疑某个文件被写坏）：

```powershell
python -c "open('backend/app/main.py','rb').read().decode('utf-8'); print('ok')"
```

报 `UnicodeDecodeError` 就是这个原因。

> 同理，`Out-File` 在 5.1 下写出的中文日志也别直接丢给 `docker build` 之外的流程。
> **VS Code 右下角确认编码是 UTF-8**，改完可以省掉一堆玄学问题。

---

## 7. 前端为什么默认不放容器

Vite 的 HMR 依赖大量文件监听，而 Windows bind mount 上监听又慢又不可靠。放容器里通常要开轮询，CPU 白烧。

**推荐做法**：前端在主机跑，只把**后端和数据库**容器化。

```powershell
cd frontend
npm install
npm run dev          # localhost:17880，代理到 localhost:17800
```

真要容器化（比如统一给答辩机器演示），用 `--profile web`，前提是先有 `frontend/`：

```powershell
docker compose --profile web up -d
```

> `web_node_modules` 命名卷的作用：盖住主机的 `node_modules` 目录。
> 不然主机的空目录会把容器里装好的依赖冲掉，报 "vite: not found"。

---

## 8. 排错表

| 症状 | 原因 | 解决 |
|---|---|---|
| `docker : 无法将"docker"项识别为…` | PATH 没刷新 / Docker Desktop 没启动 | 重开终端；确认右下角鲸鱼图标是绿的 |
| `nvidia-smi` 在容器里报 `command not found` | 基础镜像里没这个命令 | 用 `nvidia/cuda:*-base` 镜像验证，或直接 `torch.cuda.is_available()` |
| `could not select device driver "" with capabilities: gpu` | 没装 NVIDIA Container Toolkit / 不是 WSL2 后端 | 检查 Docker Desktop 用的是 WSL2 引擎；更新显卡驱动 |
| `torch.cuda.is_available()` 返回 `False` | ① 启动时没带 `--gpus` ② 拉到了 CPU 版 torch | 检查 compose 的 `deploy.resources`；确认 requirements 里**没写** torch |
| `ImportError: libGL.so.1` | opencv-python（非 headless）缺系统库 | 镜像已装 `libgl1`；本地则改 `opencv-python-headless` |
| `DataLoader worker ... Bus error` | 共享内存不足 | 调大 `shm_size`（已设 8gb） |
| `port is already allocated` | 端口被占 | 改 `.env` 里的 `API_PORT` / `POSTGRES_PORT` |
| 后端连不上数据库 | ① 用了 `localhost` ② 密码改了但卷是旧的 | 容器内必须用 `db`；执行 `down -v` 重建 |
| 改了代码不生效 | 挂载点没对上 / 没开轮询 | 检查 `volumes`；确认 `WATCHFILES_FORCE_POLLING` |
| WSL 报 `E_ACCESS_DENIED` | 沙箱或权限限制 | 用管理员 PowerShell 重试 |
| 构建特别慢 | `.dockerignore` 没生效，把 data/ 传进去了 | 确认 `.dockerignore` 存在；`docker system df` 看占用 |
| 磁盘爆了 | 旧镜像堆积 | `docker system prune -a` |

---

## 9. 什么情况下**别**用容器

诚实地说，以下几种情况容器是负担，直接用主机环境：

- 临时调一个训练脚本、想看 loss 曲线 → **主机 venv** 更快
- 需要用带图形的标注工具（labelImg 之类）→ 主机
- 数据集巨大且必须留在 Windows 盘 → 容器 I/O 会拖死你
- 赶 deadline 需要立刻出结果 → 别在那时候折腾环境

**判断标准**：如果这件事"只影响你自己、不产出给别人用的东西"，就用主机；如果"别人要复用、要复现、要部署"，就进容器。

---

## 10. 检查清单

搭环境时逐条打勾：

- [ ] `docker run --rm hello-world` 成功
- [ ] `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` 能看到 4050
- [ ] `torch.cuda.is_available()` 为 `True`
- [ ] `docker compose up -d` 后 `docker compose ps` 两个服务都是 `healthy` / `running`
- [ ] `curl.exe http://localhost:17800/health` 返回 ok
- [ ] `curl.exe http://localhost:17800/health/db` 返回 `"db":"ok"`
- [ ] `.env` 已在 `.gitignore` 里，`git status` 看不到它
- [ ] `docker compose down && docker compose up -d` 能干净重建

八条全过，环境就算搭好了，可以开始写业务代码。

---

## GPU 推理（可选，模型训好后才有意义）

### 前置：宿主机条件

Docker 用宿主机的 NVIDIA 驱动，**镜像里不需要装 CUDA toolkit**。
本机实测（RTX 4050 Laptop / 驱动 596.49）：

```powershell
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

能看到显卡就说明 Docker 已注册 `nvidia` runtime，可以直接用。
**不需要**在 WSL 里装 CUDA，也不需要给 Docker Desktop 额外配什么。

### 构建 GPU 版 api 镜像

```bash
# GPU 版（体积 12.2GB！见下）
docker compose build api --build-arg TORCH_INDEX=cu126

# CPU 版（默认，约 1.3GB）
docker compose build api
```

`docker-compose.yml` 的 api 服务已经声明了 GPU 设备：

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

### ⚠️ GPU 版镜像有 12.2GB，别打包分发

实测各层占用：

| 层 | 大小 |
|---|---|
| torch + 整套 NVIDIA CUDA 库 | **6.76 GB** |
| ultralytics | 666 MB |
| X 库（libgl1/libxcb1…） | 212 MB |
| 原有 Python 依赖 | 451 MB |

体积大的原因：torch 2.14 依赖 `cuda-toolkit` 元包，把 cudnn/cublas/nccl/triton/nvshmem
全套都装了（下载 2.6GB，解包后 6.76GB）。

所以**分发方式是给配方，不是给镜像**：组员有 N 卡就自己跑
`docker compose build api --build-arg TORCH_INDEX=cu126`。
实测 `download.pytorch.org` 国内直连 12 MB/s，约 5 分钟下完；
网盘传 12GB 反而更慢。给没显卡的同学仍然用 CPU 版（1.3GB）。

### 两个踩过的坑

**① ultralytics 会拉 opencv-python（GUI 版）**

它依赖 `libgl1` / `libxcb1` / `libsm6` / `libxext6`，缺了 `import ultralytics` 直接报
`ImportError: libxcb.so.1: cannot open shared object file`。

Dockerfile 里**单独一层**装这几个 X 库，而且**必须放在 torch 之后**——
合并到上面的 apt 层会让 6.76GB 的 torch 缓存层失效，重试时又得重下。

**② 别用清华源装 ultralytics**

实测清华源对这个包返回空索引（`from versions: none`），默认 PyPI 直连可用。

### 配置

`.env`：

```ini
DETECTOR_BACKEND=ultralytics
DETECT_DEVICE=0
DETECT_HALF=true
```

`docker-compose.yml` 里 `IR_WEIGHTS` / `RGB_WEIGHTS` 指向 `/app/ml/weights/*.pt`
（宿主机 `ml/weights/`，该目录被 bind mount 到容器的 `/app/ml`）。

> 只有热红外模型时，`RGB_WEIGHTS` 先指同一个文件占位；否则单张图（判定为 rgb 模式）
> 会回落到 StubDetector，演示时看到的是假框。可见光模型训好后换掉这一行。

### 验证

```bash
docker compose exec -T api nvidia-smi
docker compose exec -T api python -c "import torch;print(torch.__version__, torch.cuda.is_available())"
docker compose exec -T api python -c "
import cv2, glob
from app.services.detector import get_detector
d = get_detector('ir')
img = cv2.imread(sorted(glob.glob('/data/uploads/uavcb/building/thermal/*.jpg'))[0])
print(d.name, len(d.detect(img, 'ir')), '个框')
"
```

实测结果：RTX 4050 上 **10~13 ms/张**（640×512），热红外图各检出 1 个框。