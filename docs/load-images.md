# 给协作者：用离线镜像包跑起来（无需构建）

> 适用：拿到组长给的 `uav-images-YYYYMMDD.tar.gz` 的同学
> 目的：**跳过镜像构建**，绕开 apt/pip 的网络问题

---

## 0. 你会拿到什么

| 文件 | 说明 |
|---|---|
| `uav-images-YYYYMMDD.tar.gz` | 三个镜像打成一个包，**实测约 300MB** |
| `uav-images-YYYYMMDD.tar.gz.sha256` | 校验和，用来确认下载没坏 |

包里是：

- `uav-alert-api:dev` —— 后端镜像（Python 依赖全在里面，**不用 pip**）
- `postgres:16-alpine` —— 数据库
- `python:3.11-slim` —— 前端静态服务器的底座

> 为什么只有 300MB：镜像的层本来就是**压缩存储**的，`docker save` 写出的就是压缩块，
> 再 gzip 也压不下去。所谓"1.4GB"是解压后的体积，不是传输体积。
> `docker load` 实测约 **17 秒**。

---

## 0.5 端口速查（先看这张表）

| 用途 | 你**在浏览器里**用 | 容器内 | 谁来配 |
|---|---|---|---|
| 前端页面 | **17880** | 5173 | `.env` 的 `WEB_PORT` |
| 后端接口 | **17800** | 8000 | `.env` 的 `API_PORT` |
| 数据库（一般不用连） | **15432** | 5432 | `.env` 的 `POSTGRES_PORT` |

打开：**<http://localhost:17880/>**

> **为什么不是 8000 / 5173**：这两个是最常见的开发端口，容易被别的服务占；
> 而且 Windows 的 Hyper-V/WSL 会**动态保留整段端口**——实测 5173 曾被
> 5142–5241 整段吃掉，前端容器直接起不来，报
> `bind: An attempt was made to access a socket in a way forbidden by its access permissions`。
> 所以本项目把宿主端口放在 15k–18k 冷门区间。
>
> 容器内端口**没有变**，所以容器里的脚本（e2e 等）不受影响。

### ⚠️ 必须用新的 `.env`

前端和后端端口是**两个地方各写一份**的：

```
.env                        API_PORT=17800    WEB_PORT=17880
frontend/app/config.js      apiPort: 17800
```

所以：

- **一定要** `cp .env.example .env`（示例里已经是新端口）
- 如果你**沿用旧的 `.env`**（写着 8000/5173），而代码里的 `config.js` 是 17800，
  就会出现**页面能打开、但所有接口都失败**（控制台里是一串 CORS / 连接错误）
- 想换端口：`.env` 和 `config.js` **两个都要改**，然后
  `docker compose --profile web up -d` 重建容器
  （后端 CORS 已放行 localhost 任意端口，不用动后端代码）

### 端口被占用/被保留怎么办

```bash
# 查 Windows 当前保留的端口段（Hyper-V/WSL 动态占用）
netsh interface ipv4 show excludedportrange protocol=tcp
```

换一个不在保留段、也没被占用的端口，改 `.env` + `config.js` 即可。
建议继续待在 15k–18k 区间，别用 49152 以上（那是动态端口区，极易被保留）。

---

## 1. 先验完整性（重要，网盘下载容易坏）

Git Bash 里：

```bash
sha256sum -c uav-images-20261120.tar.gz.sha256
# 输出 ...: OK 才继续；FAILED 就重新下载
```

> PowerShell 也可以用：
> `Get-FileHash .\uav-images-20261120.tar.gz -Algorithm SHA256`

---

## 2. 导入镜像

```bash
docker load -i uav-images-20261120.tar.gz
```

会看到三行 `Loaded image: ...`。确认一下：

```bash
docker images
# 应该有 uav-alert-api:dev / postgres:16-alpine / python:3.11-slim
```

> ⚠️ **注意平台**：镜像是 `linux/amd64`。
> Windows + WSL2、Intel/AMD 的 Mac 直接可用；
> **Apple Silicon（M 系列）** 需要 Rosetta 模拟，能跑但很慢，建议改用 `--build` 本地构建。

---

## 3. 拿代码并起服务

镜像只包含**运行时环境**，代码是从仓库读取的（后端目录是 bind mount），
所以还要 clone 仓库：

```bash
git clone https://github.com/SusanSoucia/RGB-T.git
cd RGB-T

cp .env.example .env

docker compose up -d          # ← 千万不要加 --build，否则会重新构建，白导入了
```

确认容器起来了：

```bash
docker compose ps
# api 和 db 都应该是 healthy
```

---

## 4. 初始化数据库（**最容易漏的两步**）

镜像里**没有数据**。数据库是空卷，必须建表 + 建管理员，否则页面会报 500：

```bash
# ① 建表（7 张业务表 + alembic_version）
docker compose exec api alembic upgrade head

# ② 建管理员账号
docker compose exec api python -m app.scripts.seed_admin
```

验证：

```bash
curl -s http://localhost:17800/health/db
# {"db":"ok", ..., "public_tables":8, "detector_backend":"stub"}
```

`public_tables` 必须是 **8**。如果是 0，说明第 ① 步没成功。

---

## 5. 起前端

```bash
docker compose --profile web up -d
```

打开：

| 入口 | 地址 |
|---|---|
| 业务前端 | <http://localhost:17880/> |
| 接口文档 | <http://localhost:17800/docs> |

登录：`admin` / `Admin@12345`（也可以自己注册一个普通用户）

---

## 6. 自检一遍

```bash
docker compose exec api python -m app.scripts.e2e_test
```

全部 `[ok]` 就说明环境没问题了。这个脚本会用合成图片跑完整链路，
不需要数据集也不需要模型，跑完自动清理。

---

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `docker compose up` 开始重新构建 | 你加了 `--build`。去掉它；或 `docker compose up -d --no-build` |
| 页面报 500、日志说 `relation "users" does not exist` | 忘了跑 §4 的 `alembic upgrade head` |
| 登录提示用户名或密码错误 | 忘了跑 `seed_admin`，库里没有账号 |
| `docker load` 报 `unexpected EOF` | 下载不完整，重新下载并用 §1 校验 |
| `port is already allocated` | 改 `.env` 里的 `API_PORT` / `WEB_PORT` / `POSTGRES_PORT` |
| web 容器报 `bind: An attempt was made to access a socket in a way forbidden` | **不是被占用，是落在 Windows 保留端口段里**（Hyper-V/WSL 会动态占段）。用 `netsh interface ipv4 show excludedportrange protocol=tcp` 查，然后换一个不在段内的 `WEB_PORT`（比如 5280）。后端 CORS 已放行 localhost 任意端口，不用改后端 |
| 改了 `requirements.txt` 之后要装新包 | 这时必须自己构建：`docker compose build api`（见下） |

---

## 什么时候需要自己重新构建

**日常改代码不需要重建**——`backend/` 和 `frontend/` 都是 bind mount，
改完保存就生效（uvicorn 有 `--reload`）。

只有这两种情况需要 `docker compose build api`：

1. 改了 `backend/requirements.txt`（要装新依赖）
2. 改了 `docker/backend.Dockerfile`

构建时如果 apt/pip 卡住，把 apt 源指向阿里云 https（`Dockerfile` 里已经这么做了），
pip 一般能直连；实在不行参考 `docs/docker-dev.md` §1.6。
