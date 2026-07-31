# ============================================================
# 后端 Dockerfile — 多阶段构建
# ============================================================

# ---------- Stage 1: 依赖安装 ----------
FROM python:3.11-slim AS deps

WORKDIR /app

# 系统依赖（编译用，不进最终镜像）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 2: 生产镜像 ----------
FROM python:3.11-slim AS runtime

WORKDIR /app

# 运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmariadb3 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false appuser

# 从 deps 阶段拷贝已安装的 Python 包
COPY --from=deps /install /usr/local

# 拷贝应用代码
COPY . .

# 创建上传目录
RUN mkdir -p /app/uploads && chown appuser:appuser /app/uploads

# 非 root 用户运行
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
