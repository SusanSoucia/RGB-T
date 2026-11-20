#!/usr/bin/env bash
# ============================================================================
# 把本项目需要的镜像导出成一个压缩包，方便传到网盘给协作者。
#
# 用法（Git Bash，在项目根目录）：
#     bash scripts/export-images.sh
#
# 产物（dist/ 目录，已在 .gitignore 里）：
#     uav-images-YYYYMMDD.tar.gz          实测约 300MB
#     uav-images-YYYYMMDD.tar.gz.sha256   校验和，一并上传
#
# 为什么 1.4GB 的镜像导出后只有 300MB：
#   镜像的层本来就是压缩存储的，docker save 写出的就是压缩块，
#   再 gzip 也压不下去。1.4GB 是解压后的体积，不是传输体积。
#
# 为什么导出这三个：
#   uav-alert-api:dev   我们自己构建的后端镜像（含全部 Python 依赖）
#   postgres:16-alpine  数据库
#   python:3.11-slim    前端静态服务器用的底座
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

STAMP=$(date +%Y%m%d)
OUT_DIR="dist"
TAR="$OUT_DIR/uav-images-$STAMP.tar"
GZ="$TAR.gz"

IMAGES=(
  "uav-alert-api:dev"
  "postgres:16-alpine"
  "python:3.11-slim"
)

echo "== 1/4 检查镜像 =="
MISSING=0
for img in "${IMAGES[@]}"; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    printf '  ok    %s\n' "$img"
  else
    printf '  缺失  %s\n' "$img"
    MISSING=1
  fi
done
if [ "$MISSING" -eq 1 ]; then
  echo
  echo "有镜像缺失。先把它们准备好："
  echo "  docker compose build api                        # 构建后端"
  echo "  docker pull postgres:16-alpine python:3.11-slim  # 拉底座"
  exit 1
fi

mkdir -p "$OUT_DIR"

echo
echo "== 2/4 导出为 tar =="
docker save -o "$TAR" "${IMAGES[@]}"
echo "  原始 tar: $(du -h "$TAR" | cut -f1)"

echo
echo "== 3/4 压缩 =="
gzip -6 -f "$TAR"
echo "  压缩后: $(du -h "$GZ" | cut -f1)"

echo
echo "== 4/4 生成校验和 =="
sha256sum "$GZ" > "$GZ.sha256"
cat "$GZ.sha256"

echo
echo "============================================================"
echo "完成。把这两个文件传到网盘："
echo "  $(basename "$GZ")"
echo "  $(basename "$GZ.sha256")"
echo
echo "协作者的完整上手步骤见：docs/load-images.md"
echo "（重要：load 之后还要跑数据库迁移和建管理员，否则会 500）"
echo "============================================================"
