# connection-checker

自托管网络连通性监控工具。定时对目标执行 **Ping / TCP 端口 / HTTP 状态码** 检查，在 Web 仪表盘实时查看结果，支持按状态、IP、目标、时间筛选与分页，故障连续发生可推送 **Webhook 告警**。

后端 FastAPI + Vue 3 前端，单一 Docker 镜像部署，数据以 JSON / JSONL 文件存储，无需数据库。

## 功能特性

- 三种检查方式：ICMP Ping（ping3）、TCP 端口连通、HTTP(S) 状态码（httpx）
- 每个目标独立检查间隔、独立时间窗口（支持跨午夜，如 `22:00–06:00`）、独立超时
- 异步调度：asyncio 每目标一个任务，配置变更即时生效，可手动「立即检查」
- 实时结果：SSE 推送，仪表盘秒级更新，无需轮询
- 结果查询：状态 / IP / 目标 / 日期 / 时间段筛选 + 服务端分页，JSONL 追加存储（默认保留最近 50000 条）
- 告警通知：目标连续失败达阈值（默认 3 次）触发 Webhook，恢复时通知；兼容 Gotify / 企业微信 / 自建服务
- 认证：单访问码 + argon2 哈希存储，JWT 写入 HttpOnly Cookie，CSRF 纵深防御
- 开箱即用：单一镜像 + 挂载数据卷即可运行

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | FastAPI · uvicorn · Pydantic v2 · Python 3.12 |
| 前端 | Vue 3 · TypeScript · Vite · Naive UI |
| 检查 | ping3 · httpx · asyncio |
| 认证 | argon2-cffi · PyJWT |
| 存储 | config.json（配置）· results.jsonl（结果，append-only） |
| 部署 | Docker（多阶段构建，非 root，amd64 + arm64）· docker-compose |

## 目录结构

```
.
├── backend/              # Python 后端
│   ├── app/
│   │   ├── main.py       # 应用装配 / 生命周期
│   │   ├── config.py     # 应用设置（环境变量）
│   │   ├── models.py     # Pydantic 领域模型
│   │   ├── storage.py    # JSON / JSONL 持久化
│   │   ├── scheduler.py  # asyncio 调度器
│   │   ├── notifier.py   # Webhook 告警
│   │   ├── auth.py       # argon2 + JWT + Cookie
│   │   ├── checkers/     # ping / port / http 检查器插件
│   │   └── api/          # REST API 路由
│   └── tests/            # pytest 单测 + 集成测试
├── frontend/             # Vue 3 前端
│   └── src/              # 页面 / 组件 / API 客户端
├── docs/api.md           # API 参考文档
├── Dockerfile            # 多阶段构建（node 构建 → python 运行）
├── docker-compose.yml    # 示例部署
├── pyproject.toml        # Python 依赖 / 工具链 / 发行配置
└── CHANGELOG.md          # 版本变更记录（主要里程碑人工维护）
```

## 快速开始（Docker）

```bash
docker run -d --name connection-checker \
  -p 8000:8000 \
  -e CONNECTCHECKER_ACCESS_CODE=你的访问码 \
  -v ./data:/app/data \
  ghcr.io/wmy2981/connection-checker:latest
```

打开 `http://localhost:8000`，用访问码登录。

> 未设置 `CONNECTCHECKER_ACCESS_CODE` 时，首次启动会生成随机访问码并打印到容器日志中。

### docker-compose

```bash
# 先编辑 docker-compose.yml，把 CONNECTCHECKER_ACCESS_CODE 改为你的访问码
docker compose up -d            # 拉取 ghcr 镜像启动
docker compose up -d --build    # 或本地构建镜像启动
```

> 注意：Ping 检查需要原始套接字权限，compose 已配置 `cap_add: [NET_RAW]`；使用 `docker run` 时需加 `--cap-add=NET_RAW`。

### 数据目录

挂载的 `./data` 目录下会产生：

| 文件 | 说明 |
| --- | --- |
| `config.json` | 检查目标配置（经 API 修改时自动写入） |
| `results.jsonl` | 检查结果，每行一条 JSON，追加写入 |
| `secrets.json` | JWT 密钥与访问码哈希（明文访问码不落盘） |

## 本地开发

后端：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"        # Windows
.venv/bin/python -m pip install -e ".[dev]"            # Linux/macOS
CONNECTCHECKER_ACCESS_CODE=dev .venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload
```

前端：

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173，/api 已代理到后端 8000
```

测试与代码检查：

```bash
.venv/Scripts/python -m pytest backend/tests
.venv/Scripts/python -m ruff check backend
cd frontend && npm run build
```

## 配置（环境变量）

所有变量可选，前缀 `CONNECTCHECKER_`：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CONNECTCHECKER_ACCESS_CODE` | 随机生成 | 登录访问码 |
| `CONNECTCHECKER_JWT_SECRET` | 随机生成 | JWT 签名密钥；不设置则持久化在 `secrets.json` |
| `CONNECTCHECKER_JWT_EXPIRE_MINUTES` | `720` | 会话有效期（分钟） |
| `CONNECTCHECKER_APP_PORT` | `8000` | 服务端口 |
| `CONNECTCHECKER_DATA_DIR` | `./data` | 数据目录 |
| `CONNECTCHECKER_RESULT_MAX_RECORDS` | `50000` | 结果保留条数上限 |
| `CONNECTCHECKER_PING_COUNT` | `4` | Ping 单次检查发包数 |
| `CONNECTCHECKER_CONNECT_TIMEOUT` | `3.0` | Ping / TCP 默认超时（秒） |
| `CONNECTCHECKER_HTTP_TIMEOUT` | `5.0` | HTTP 默认超时（秒） |
| `CONNECTCHECKER_NOTIFY_FAIL_THRESHOLD` | `3` | 连续失败触发告警的阈值 |
| `CONNECTCHECKER_WEBHOOK_URL` | 空 | 告警推送地址（POST JSON） |
| `CONNECTCHECKER_COOKIE_SECURE` | `false` | HTTPS 部署时设为 `true` |

## 检查目标

每个检查目标支持字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 可选名称，便于识别 |
| `ip` | IP 或主机名 |
| `check_method` | `ping` / `port` / `http` |
| `check_interval` | 检查间隔（秒，≥5） |
| `time_ranges` | 时间段数组，支持跨午夜；留空则全天 |
| `enabled` | 是否启用 |
| `port` | `port` 方式必填；`http` 方式可覆盖默认端口 |
| `scheme` / `url_path` | `http` 方式的协议与路径 |
| `http_success_codes` | `http` 方式的期望状态码集合（默认 200–399） |
| `timeout` | 覆盖全局超时（秒） |

## Webhook 告警

设置 `CONNECTCHECKER_WEBHOOK_URL` 后，目标连续失败达到阈值时 POST 如下 JSON；恢复时再推送一次：

```json
{
  "title": "[告警] 目标名称",
  "message": "连续 3 次检查失败: ping 超时（丢包 100%）",
  "event": "connection_checker",
  "target": {
    "id": "ab12cd34ef56",
    "name": "目标名称",
    "ip": "8.8.8.8",
    "check_method": "ping",
    "status": "timeout",
    "latency_ms": null
  },
  "ts": "2026-08-06T08:00:00+00:00"
}
```

Gotify 可直接使用；企业微信等可在入口处做格式转换。

## API 文档

- 交互式文档（OpenAPI / Swagger UI）：部署后访问 `/docs`
- 手写参考：[docs/api.md](docs/api.md)

## CI/CD 与发行

GitHub Actions 在每次 `main` 推送时执行：

1. ruff 代码检查 + pytest 测试
2. buildx 构建 amd64 / arm64 镜像，推送至 `ghcr.io/wmy2981/connection-checker`（`latest` + `sha`）
3. python-semantic-release 依据 Conventional Commits 自动生成 **GitHub Release 说明**、打 `vX.Y.Z` tag 并发布 Release

> GitHub Release 说明由 commit 历史自动生成；仓库内 `CHANGELOG.md` 为人工维护的版本变更记录，主要里程碑由维护者整理。

版本号以 `pyproject.toml` 为基准、以 git tag 为准。

## 许可证

MIT
