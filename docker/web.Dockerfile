# 前端开发镜像（可选）
# 前提：frontend/ 已由 Vite 脚手架生成
#   npm create vite@latest frontend -- --template vue
# 日常更推荐在主机直接 npm run dev，见 docs/docker-dev.md §7
#
# ⚠️ 不要加 "# syntax=docker/dockerfile:1.X"（会额外依赖 Docker Hub 拉 frontend 镜像）

FROM node:20-alpine AS dev
ENV TZ=Asia/Shanghai
WORKDIR /app

# 先只拷依赖清单，利用层缓存：改代码不会重装依赖
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
