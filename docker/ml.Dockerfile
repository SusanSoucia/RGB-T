# 训练 / 推理镜像（GPU，体积 ~7GB）
# 基础镜像已自带 torch 2.5.1 + CUDA 12.4 + cuDNN9，避免自己装 CUDA
#
# ⚠️ 不要加 "# syntax=docker/dockerfile:1.X"（会额外依赖 Docker Hub 拉 frontend 镜像）

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# opencv / ultralytics 的常见坑：缺 libGL.so.1 直接 ImportError。
# 即便用 headless 版，也一并装上 libglib2.0-0 更稳。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
        ffmpeg tzdata git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY ml/requirements.txt /tmp/ml-requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/ml-requirements.txt

# 自检：容器起来就能看到 torch / CUDA 是否正常
RUN python -c "import torch; print('torch', torch.__version__, '| cuda build', torch.version.cuda, '| available', torch.cuda.is_available())"

CMD ["bash"]
