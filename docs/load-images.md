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
curl -s http://localhost:8000/health/db
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
| 业务前端 | <http://localhost:5173/> |
| 接口文档 | <http://localhost:8000/docs> |

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
