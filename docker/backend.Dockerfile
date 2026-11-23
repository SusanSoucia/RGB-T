# 后端 API 镜像（CPU，体积小 ~300MB）
#   dev  : 带 --reload + 代码 bind mount，日常开发用
#   prod : 拷贝代码 + 非 root 运行
#
# ⚠️ 不要加 "# syntax=docker/dockerfile:1.X"
#   那行会让 BuildKit 额外去 Docker Hub 拉一个 frontend 镜像，网络一抖就
#   BUILD FAILED（实测踩过）。本项目没用到任何 BuildKit 专有语法
#   （heredoc / RUN --mount / 多平台构建），不需要它。

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai
WORKDIR /app

# 只装真正需要的运行时库：
#   curl        —— 容器健康检查用
#   tzdata      —— 时区（Asia/Shanghai）
#   libglib2.0-0, libgomp1 —— opencv / numpy 的运行依赖
#
# **不装 build-essential / libpq-dev**：psycopg[binary] 是预编译 wheel，
# 不需要编译器和 libpq 头文件。带上它们会多拉 100 多个包（gcc/perl/binutils…），
# 构建时间和镜像体积都翻倍，受限网络下极易失败。
#
# **不装 ffmpeg**：改用 pip 的 imageio-ffmpeg（自带静态 ffmpeg，25MB），
# 见 requirements.txt 的说明。
#
# 源换成阿里云镜像（**必须 https**）：实测容器内
#   - 直连 deb.debian.org：限速到 ~900B/s
#   - 走宿主代理：随机 502
#   - 阿里云 80 端口：404/连接失败
#   - 阿里云 443：6 秒拿到索引，稳定
RUN set -e; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
        if [ -f "$f" ]; then \
            sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' "$f"; \
            sed -i 's|http://mirrors.aliyun.com|https://mirrors.aliyun.com|g' "$f"; \
        fi; \
    done; \
    apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=3 \
        curl ca-certificates tzdata libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

# ---------------- 推理依赖（torch + ultralytics）----------------
# 用 build arg 控制 CPU / GPU 版本，一份 Dockerfile 出两种镜像：
#   CPU（默认，镜像约 1.3GB）:  docker compose build api
#   GPU（镜像约 3.3GB）      :  docker compose build api --build-arg TORCH_INDEX=cu126
#
# torch 和 torchvision 必须**成对编译**，所以这里故意不分别 pin 版本，
# 交给 pip 解析出互相兼容的一对；只 pin ultralytics（与训练时一致 8.4.216）。
#
# GPU 版体积大是因为 CUDA 运行时全打包在 torch 的 wheel 里（约 2.6GB），
# **不需要**在镜像里再装 CUDA toolkit —— 驱动由宿主机透传。
#
# 两个 pip 步骤**故意分成两层**：torch 那层有 2.6GB 下载，
# 如果 ultralytics 那步失败，重试时这层能命中缓存，不用重下。
#
# 超时给到 180 秒、重试 15 次：实测国内直连 files.pythonhosted.org
# 偶尔 15 秒读超时，把 2.6GB 下完却卡在一个小包的元数据上（踩过）。
ARG TORCH_INDEX=cpu
RUN pip install --no-cache-dir --timeout 180 --retries 15 \
        torch torchvision \
        --index-url https://download.pytorch.org/whl/${TORCH_INDEX}

# ultralytics 走默认 PyPI。
# 别用清华源：实测它对这个包返回空索引（"from versions: none"），
# 而默认 PyPI 直连可用（只是慢一点，靠 timeout/retries 兜住）。
RUN pip install --no-cache-dir --timeout 180 --retries 15 \
        ultralytics==8.4.216

# ultralytics 会把 opencv-python（GUI 版，不是 headless）装进来，
# 它依赖 libxcb / libGL 这些 X 库，缺了 import 就报
#   ImportError: libxcb.so.1: cannot open shared object file
#
# ⚠️ 这一层**必须放在 torch 之后**：如果合并到上面那个 apt 层，
# 会把它后面的 2.6GB torch 缓存层全部作废，重试时又得重下。
RUN apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=3 \
        libgl1 libxcb1 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# ---------------- 开发 ----------------
FROM base AS dev
EXPOSE 8000
# 代码不打进镜像，由 compose 的 bind mount 提供
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------- 生产 ----------------
FROM base AS prod
COPY backend/ /app
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
