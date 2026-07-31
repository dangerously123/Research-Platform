# ============================================================
# 前端 Dockerfile — 构建 + Nginx 静态服务
# ============================================================

# ---------- Stage 1: 构建 ----------
FROM node:18-alpine AS build

WORKDIR /app

# 先拷贝依赖文件（利用 Docker 缓存）
COPY package.json package-lock.json* ./
RUN npm ci --registry=https://registry.npmmirror.com

# 拷贝源码并构建
COPY . .
RUN npm run build

# ---------- Stage 2: Nginx 静态服务 ----------
FROM nginx:alpine AS runtime

# 拷贝 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 拷贝构建产物
COPY --from=build /app/dist /usr/share/nginx/html

# 确保目录权限正确
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chown -R nginx:nginx /var/cache/nginx \
    && chown -R nginx:nginx /var/log/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid \
    && sed -i 's/listen       80;/listen       8080;/' /etc/nginx/conf.d/default.conf

# 非 root 用户运行（使用 8080 端口）
USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
