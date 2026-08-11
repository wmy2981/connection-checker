# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

自托管网络连通性监控工具（Ping / TCP / HTTP / DNS 检查 + Web 仪表盘 + Webhook 告警）。FastAPI 后端 + Vue3 前端，单 Docker 镜像（ghcr）部署，数据用 JSON/JSONL 文件存储，无数据库。

## 常用命令

- 测试（根目录）：`pytest` — pyproject.toml 已配 `testpaths = ["backend/tests"]`、`asyncio_mode = "auto"`
- 后端 lint：`ruff check backend` — 仅 check，无 format；规则 E/F/I/UP/B，行宽 100
- 前端 typecheck：`cd frontend && npm run typecheck`（vue-tsc）；`npm run build` 会先跑 typecheck
- 前端开发：`cd frontend && npm run dev`（localhost:5173，`/api` 代理到 8000）

## 结构要点

- 后端包位于 `backend/app`（setuptools 包发现已配置，pip editable install）
- 生产环境由 FastAPI 托管前端构建产物（`backend/app/static/`，此目录在 gitignore 且仓库中不存在）；裸跑 uvicorn 不带前端，本地开发用 vite dev server
- 前端 UI 用 naive-ui（组件必须显式 import，见关键坑）；图标用配套本地库 `@vicons/ionicons5`（npm 依赖，勿用 CDN）
- 日志装配在 `backend/app/logging_setup.py`，日志查看/导出 API 在 `backend/app/api/logs.py`（见「日志系统」）

## 日志系统

- 日志文件：`data/logs/app-YYYY-MM-DD.log`，按本地时区（`datetime.now().astimezone()`，容器 TZ 生效）每天轮转，保留 30 天；同时输出控制台
- 行格式：`时间 | 级别 | logger名 | 文件:行号 | 消息`（`%(filename)s:%(lineno)d`，精细到产生日志的 Python 文件）；旧版无来源段的 4 段行解析时兼容（source 为 null）
- 级别存 `config.json` 的 `app.log_level`（DEBUG/INFO/WARN/ERROR，默认 INFO），watchdog 检测到配置变更时热更新；检查器（ping/http/port/dns）在 DEBUG 级别记录每次检查细节（丢包率、状态码、解析结果、连接耗时等）
- 查看/导出：`GET /api/v1/logs`（参数 level=最低级别、start/end=本地时间 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS、source=来源筛选（文件名如 scheduler.py 或模块名如 app.scheduler，子串匹配、大小写不敏感）、page/page_size，倒序分页，traceback 续行合并）、`GET /api/v1/logs/export`（导出 .log 文本）、`GET /api/v1/logs/sources`（日志中出现过的来源去重枚举，供前端筛选下拉）
- **运行时日志消息必须英文**（用户要求），代码注释/docstring 中文不受限；前端配置页有「日志管理」弹窗（级别/来源/时间筛选，弹窗可拖拽调整大小，`resize: both`）与「日志等级」设置

## 发版雷区

版本发布由 CI 全自动驱动，**版本号以 `pyproject.toml` 的 `project.version` 为准（手动维护，不再自动 bump）**，以下机制改动需格外谨慎：

- 版本规则（见 `.github/scripts/release_check.py`）：合法正式版 `x.y.z`；合法预发行 `x.y.z.alpha.n` / `x.y.z.beta.n`。main 分支只接受正式版（无变化/倒退报错，前进才发行）；dev 分支只接受预发行（无变化跳过、倒退报错、前进预发行）。比较基准是仓库中最大版本 tag
- `.github/workflows/release.yml`：main/dev push 触发，脚本产出 version/is_prerelease/skip，然后打 tag `v{version}` + `gh release create`（预发行带 `--prerelease`）；发行说明范围始终是「最后一个正式版 tag → HEAD」
- 三个拆分的工作流：`.github/workflows/ci.yml`（test）、`build.yml`（镜像构建，main 的 latest 由 Release workflow_run 触发、dev 的 dev 镜像 push 直接构建）、`release.yml`（发版）
- `backend/app/main.py` 的 `_mount_frontend` SPA 静态托管逻辑
- `backend/app/config.py` 中 `CONNECTCHECKER_` 环境变量语义：`ACCESS_CODE`（留空=免登录）、`JWT_*`、`APP_PORT`、`DATA_DIR`、`COOKIE_SECURE`、`HTTP_SUCCESS_CODES`；检查参数（`RESULT_MAX_RECORDS`/`PING_COUNT`/`CONNECT_TIMEOUT`/`HTTP_TIMEOUT`）与 `STATS_WINDOW`（仪表盘统计近 N 次，默认 50）在 config.json 的 `app` 节
- `/api/v1/auth/me` 端点（Docker HEALTHCHECK 依赖它；免认证模式恒返回 authenticated=true）

## 提交流程

- 遵循 Conventional Commits（`fix:` / `feat:` / BREAKING `!`）
- 直接提交到 main，无 PR 流程；**手动维护 `pyproject.toml` 的 version 字段**：main 上发正式版（x.y.z，必须大于已发版 tag），dev 上开发用预发行号（x.y.z.alpha.n / x.y.z.beta.n，改动后推送即触发预发行）；版本号与已发版相同/倒退会导致 release 工作流报错

## 关键坑

- 代码须保持 Python 3.10 兼容：本地 venv 是 3.10，而 CI/Docker 用 3.12
- Windows 下 venv 在 `.venv/Scripts/python`（非 `.venv/bin`）
- POST/PUT/PATCH 强制要求 `Content-Type: application/json`（CSRF 纵深防御，否则返回 415）
- `config.json` 每 5 秒热加载（外部编辑立即生效）：检查目标、`webhook` 告警、`app` 全局检查参数（结果保留条数/Ping 发包数/超时/日志等级，结果上限修改立即裁剪）；`results.jsonl` 追加写、超上限时整文件重写
- 访问码以 `CONNECTCHECKER_ACCESS_CODE` 为权威且每次运行重新校验；**留空则免认证**（内网部署可用，勿暴露公网）
- 容器运行需 `--cap-add=NET_RAW`（ping 依赖原始套接字）
- **更新目标禁止 `model_copy(update=dict)`**：它不重新验证嵌套模型，`time_ranges` 会变成 dict，调度循环 `is_time_in_ranges` 抛 AttributeError 使定时任务**静默死亡**（2026-08 生产事故：用户编辑目标后全部定时检查停止 23 小时且无日志）。必须 `Target.model_validate({**existing.model_dump(), **payload.model_dump(exclude_unset=True)})` 整体重验证
- **不要 `await` 同步方法**：如 `ResultStore.resize` 是同步方法，`await resize(...)` 在 Python 3.12 抛 TypeError 杀死 config watchdog（配置热加载失效）。同步方法直接调用
- **naive-ui 组件必须显式 import**：模板用了 `<n-layout>`/`<n-layout-header>`/`<n-layout-content>` 等但漏 import 时，Vue 渲染成自定义元素、布局错乱且仅 console 报 warning（曾因此布局崩溃）
- **naive-ui n-select 的 v-model 初始值禁用 `''`**：空字符串被当作"有选中值"，导致不显示 placeholder 且误显示清除叉号（2026-08 bug：仪表盘目标名称筛选框）。初始/重置用 `null`（clear 事件 emit 的也是 null）
- 调度任务异常退出不会自动续跑：`_run_loop` 循环体已包 try/except（单次异常不杀任务），任务意外死亡后 `reconcile()` 会检测 `task.done()` 并重建（打 warning 日志）；手动检查（`manual_run`）不经过 `is_time_in_ranges`，与定时检查路径不同
- 前端主题三模式（跟随系统/浅色/深色）由 `useDark.ts` 管理，选择存 `localStorage` 的 `cc-theme-mode`（默认跟随系统），`ThemeToggle.vue` 下拉切换；所有页面共用该组件
