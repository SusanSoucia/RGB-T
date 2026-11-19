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

# build-essential / libpq-dev 给 psycopg 与可能的源码编译用
# libglib2.0-0 + libgomp1 是 opencv 与 numpy 的运行依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl ca-certificates tzdata \
        libglib2.0-0 libgomp1 \
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
