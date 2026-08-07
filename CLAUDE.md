# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

自托管网络连通性监控工具（Ping / TCP / HTTP 检查 + Web 仪表盘 + Webhook 告警）。FastAPI 后端 + Vue3 前端，单 Docker 镜像（ghcr）部署，数据用 JSON/JSONL 文件存储，无数据库。

## 常用命令

- 测试（根目录）：`pytest` — pyproject.toml 已配 `testpaths = ["backend/tests"]`、`asyncio_mode = "auto"`
- 后端 lint：`ruff check backend` — 仅 check，无 format；规则 E/F/I/UP/B，行宽 100
- 前端 typecheck：`cd frontend && npm run typecheck`（vue-tsc）；`npm run build` 会先跑 typecheck
- 前端开发：`cd frontend && npm run dev`（localhost:5173，`/api` 代理到 8000）

## 结构要点

- 后端包位于 `backend/app`（setuptools 包发现已配置，pip editable install）
- 生产环境由 FastAPI 托管前端构建产物（`backend/app/static/`，此目录在 gitignore 且仓库中不存在）；裸跑 uvicorn 不带前端，本地开发用 vite dev server

## 发版雷区

版本发布由 CI 全自动驱动（python-semantic-release），以下机制改动需格外谨慎：

- `pyproject.toml` 的 `[tool.semantic_release]` 配置
- `.github/workflows/ci.yml` 的 release job，以及 `[skip ci]` 防循环机制（发版 commit 回推 main 时避免重新触发 CI）
- `backend/app/main.py` 的 `_mount_frontend` SPA 静态托管逻辑
- `backend/app/config.py` 中 `CONNECTCHECKER_` 环境变量语义
- `/api/v1/auth/me` 端点（Docker HEALTHCHECK 依赖它）

## 提交流程

- 必须遵循 Conventional Commits（`fix:` / `feat:` / BREAKING `!`）——semantic-release 依据 commit message 决定版本 bump，错误提交会破坏自动发版
- 直接提交到 main，无 PR 流程；发版 commit 由 CI 自动生成（`chore(release): X [skip ci]`），不要手动改版本号

## 关键坑

- 代码须保持 Python 3.10 兼容：本地 venv 是 3.10，而 CI/Docker 用 3.12
- Windows 下 venv 在 `.venv/Scripts/python`（非 `.venv/bin`）
- POST/PUT/PATCH 强制要求 `Content-Type: application/json`（CSRF 纵深防御，否则返回 415）
- `config.json` 每 5 秒热加载（外部编辑立即生效）；`results.jsonl` 追加写、超上限时整文件重写
- 容器运行需 `--cap-add=NET_RAW`（ping 依赖原始套接字）
