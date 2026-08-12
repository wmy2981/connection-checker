# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 目录结构

```
backend/       FastAPI 后端（Python 3.10+）
  app/         主包：api/ 端点、checkers/ 检查器、存储/调度/告警/日志等核心模块
  tests/       后端测试（pytest，asyncio_mode=auto）
frontend/      Vue3 + naive-ui 前端（Vite + vue-tsc）
  src/         views/ 页面、components/ 组件、api/ 请求封装、composables/ 组合式函数
  public/      静态资源（favicon.svg）
docs/          手动维护的 API 参考文档（api.md，改接口须同步）
.github/       CI / 镜像构建 / 发版工作流（含版本检查脚本）
data/          运行时数据（config.json / secrets.json / results.jsonl / logs/），不入库
```

> 后端与前端各自更详细的文件分工、规则与约束见 `backend/CLAUDE.md` 与 `frontend/CLAUDE.md`。本机环境信息见 `CLAUDE.local.md`（不入库）。

## 项目概览

自托管网络连通性监控工具（Ping / TCP / HTTP / DNS 检查 + Web 仪表盘 + Webhook 告警）。FastAPI 后端 + Vue3 前端，单 Docker 镜像（ghcr）部署，数据用 JSON/JSONL 文件存储，无数据库。

## 常用命令

- 测试（根目录）：`pytest` — pyproject.toml 已配 `testpaths = ["backend/tests"]`、`asyncio_mode = "auto"`
- 后端 lint：`ruff check backend` — 仅 check，无 format；规则 E/F/I/UP/B，行宽 100
- 前端 typecheck：`cd frontend && npm run typecheck`（vue-tsc）；`npm run build` 会先跑 typecheck
- 前端开发：`cd frontend && npm run dev`（localhost:5173，`/api` 代理到 8000）

## 通用规则与约束

### 提交流程

- 遵循 Conventional Commits（`fix:` / `feat:` / BREAKING `!`），提交信息英文、命令式；按改动点拆分提交，每个提交前测试全绿
- **所有改动必须在 dev（或其他分支）上进行，不得直接操作 main**；main 只接收 dev 的合并（`git merge dev` 到 main 后推送）
- **手动维护 `pyproject.toml` 的 version 字段**（版本号不再自动生成）：
  - dev 上开发：预发行号（`x.y.z.alpha.n` / `x.y.z.beta.n`，推送即触发预发行）或正式版号（代表即将发正式版，跳过发版）
  - main 上发正式版：`x.y.z`，必须大于已发版 tag（含 dev 的预发行 tag）
  - 版本号与已发版相同/倒退会使 release 工作流报错
- 改动接口（新增/修改端点、字段）须同步更新 `docs/api.md`

### 版本与发布

版本发布由 CI 全自动驱动，以下机制改动需格外谨慎：

- 版本规则（见 `.github/scripts/release_check.py`）：合法正式版 `x.y.z`；合法预发行 `x.y.z.alpha.n` / `x.y.z.beta.n`。main 只接受正式版（无变化/倒退报错，前进才发行）；dev 预发行号前进发预发行、正式版号前进跳过、无变化跳过、倒退报错。比较基准是仓库中最大版本 tag
- `.github/workflows/release.yml`：main/dev push 触发，脚本产出 version/is_prerelease/skip，然后打 tag `v{version}` + `gh release create`（预发行带 `--prerelease`）；发行说明范围始终是「最后一个正式版 tag → HEAD」
- `.github/workflows/build.yml` 镜像标签：main 推 `v{version}` + `latest`；dev 预发行号推 `v{version}` + `dev`；**dev 上正式版号只推 `dev`**（避免版本标签与 main 正式版冲突）。main 的构建由 Release workflow_run 触发（Release 失败则跳过）、dev 的镜像 push 直接构建。**版本号无变化时构建跳过**（要出新镜像必须 bump 版本）
- 前端页脚版本号：`/api/v1/meta` 返回 `version`（从 pyproject.toml 读原始格式，规避 setuptools 的 PEP 440 归一化如 `1.8.0b1`；Docker 内 `/app/pyproject.toml` 存在故同样正确），`AppFooter.vue` 三页面共享显示
- 三个拆分的工作流：`.github/workflows/ci.yml`（test）、`build.yml`（镜像构建）、`release.yml`（发版），均有 `concurrency: cancel-in-progress`（连续推送时旧构建被取消属正常）

### 配置与运行

- `backend/app/config.py` 中 `CONNECTCHECKER_` 环境变量：`ACCESS_CODE`（留空=免登录）、`JWT_*`、`APP_PORT`、`DATA_DIR`、`COOKIE_SECURE`、`HTTP_SUCCESS_CODES`；检查参数（`RESULT_MAX_RECORDS`/`PING_COUNT`/`CONNECT_TIMEOUT`/`HTTP_TIMEOUT`）与 `STATS_WINDOW` 在 config.json 的 `app` 节
- `config.json` 每 5 秒热加载（外部编辑立即生效）：检查目标、`webhook` 告警、`app` 全局检查参数（结果保留条数/Ping 发包数/超时/日志等级/统计窗口/日志清理/存储模式/品牌图标，结果上限修改立即裁剪）、`s3` 节
- 访问码以 `CONNECTCHECKER_ACCESS_CODE` 为权威且每次运行重新校验；**留空则免认证**（内网部署可用，勿暴露公网）
- 容器运行需 `--cap-add=NET_RAW`（ping 依赖原始套接字）；`/api/v1/auth/me` 端点被 Docker HEALTHCHECK 依赖（免认证模式恒返回 authenticated=true）

### 日志系统

- 日志文件：`data/logs/app-YYYY-MM-DD.log`，按本地时区（`datetime.now().astimezone()`，容器 TZ 生效）每天轮转；同时输出控制台
- 行格式：`时间 | 级别 | logger名 | 文件:行号 | 消息`（`%(filename)s:%(lineno)d`，精细到产生日志的 Python 文件）；旧版无来源段的 4 段行解析时兼容（source 为 null）
- 级别存 `config.json` 的 `app.log_level`（DEBUG/INFO/WARN/ERROR，默认 INFO），watchdog 检测到配置变更时热更新
- 日志分级约定：检查 error → ERROR、失败/超时 → WARN、成功 → INFO、检查器内部明细与 HTTP 访问日志 → DEBUG（uvicorn.access 固定 DEBUG，默认级别不刷屏）
- 自动清理：`app.log_cleanup_mode`（none/delete/upload）+ `log_retention_days`（默认 30），由 `log_cleaner.py` 每 6 小时执行；upload 模式上传 S3 成功后删本地，S3 永久保留
- 查看/导出：`GET /api/v1/logs`（参数 level=多选逗号分隔、start/end=本地时间 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS、source=来源筛选（文件名如 scheduler.py 或模块名如 app.scheduler，多选逗号分隔、子串匹配、大小写不敏感）、page/page_size，倒序分页，traceback 续行合并）、`GET /api/v1/logs/export`（导出 .log 文本）、`GET /api/v1/logs/sources`（日志中出现过的来源去重枚举，供前端筛选下拉）
- **运行时日志消息必须英文**（用户要求），代码注释/docstring 中文不受限；前端配置页有「日志管理」弹窗（级别/来源/时间筛选，弹窗可拖拽调整大小）与「日志等级」设置

### API 与安全

- POST/PUT/PATCH 强制要求 `Content-Type: application/json`（CSRF 纵深防御，否则返回 415）
- 认证双方式：会话 Cookie（HttpOnly `session`，浏览器）或 API Token（`Authorization: Bearer <token>`，外部调用；存 secrets.json，重新生成后旧 token 失效）
- `backend/app/main.py` 的 `_mount_frontend` SPA 静态托管逻辑（发版相关，改动需谨慎）
- `/api/v1/meta` 的 `version` 字段必须保持 pyproject 原始格式（`x.y.z[.alpha|beta.n]`），测试 `test_meta_public` 断言了该格式

### 存储约定

- `config.json`：顶层 `version` / `last_updated` / `check_targets` / `webhook` / `app` / `s3` 节，原子写（临时文件 + os.replace），watchdog 热加载
- `secrets.json`：密钥类数据（jwt_secret、access_code_hash、S3 凭据、api_token），**明文凭据不落 config.json、接口不回读**（GET /settings/s3 只返回 has_credentials）
- `results.jsonl`：检查记录追加写、超上限整文件重写；存储模式 `app.storage_mode`（local/s3/both，S3 按天对象永久保留、写失败降级本地）；启用 S3（启动或切换存储模式）时本地全部历史按天补传，同步失败的日期保留待下次 append 自动重试（跨天失败不丢数据）
