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
