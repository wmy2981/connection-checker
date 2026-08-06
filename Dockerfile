# ===== 第一阶段：前端构建 =====
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ===== 第二阶段：Python 运行时 =====
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONNECTCHECKER_DATA_DIR=/app/data \
    CONNECTCHECKER_APP_PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend/ ./backend/
# 前端构建产物直接进入后端静态目录，由 FastAPI 托管
COPY --from=frontend /build/dist ./backend/app/static/

# 安装 Python 依赖与应用元数据（版本号来源）
RUN pip install --no-cache-dir .

# 非 root 运行；数据目录可写
RUN useradd --system --uid 10001 --home-dir /app checker \
    && mkdir -p /app/data \
    && chown -R checker:checker /app

USER checker

EXPOSE 8000
VOLUME ["/app/data"]

# ping 需要原始套接字（容器 cap_add: NET_RAW）；此处做存活探针
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/auth/me', timeout=3)"

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
