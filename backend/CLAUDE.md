# CLAUDE.md — backend

FastAPI 单体后端（`requires-python >=3.10`），包位于 `backend/app`（setuptools 包发现已配置，可 pip editable install）。启动与生命周期装配在 `app/main.py` 的 `lifespan`。

## 文件分工

| 文件/目录 | 职责 |
| --- | --- |
| `main.py` | 应用装配（lifespan 启动 store / scheduler / log_cleaner）、`_mount_frontend` SPA 静态托管（发版相关，改动需谨慎） |
| `config.py` | pydantic-settings 配置，`CONNECTCHECKER_` 环境变量（见根 CLAUDE.md「配置与运行」） |
| `models.py` | pydantic 模型：Target / CheckResult / AppSettings / S3Config / WebhookConfig / ResultFilter 等，字段校验与默认值 |
| `storage.py` | 持久化：ConfigStore（config.json 原子写 + 热加载）、ResultStore（results.jsonl 追加 + 裁剪 + S3 同步）、SecretsStore（secrets.json，密钥类数据） |
| `scheduler.py` | 每目标一个 asyncio 任务循环检查；config watchdog 热加载（5s）；`manual_run` 手动检查（跳过禁用目标） |
| `notifier.py` | Webhook 告警：连续失败达阈值触发、恢复通知；`observe` 决策 + `send_test` |
| `auth.py` | 访问码 argon2 哈希、JWT + HttpOnly Cookie、API Token（Bearer）、`require_auth` 依赖 |
| `logging_setup.py` | 日志装配：控制台 + 按天文件（DailyFileHandler）、级别热更新、uvicorn.access 固定 DEBUG |
| `log_cleaner.py` | 日志自动清理（none/delete/upload），每 6 小时轮询 |
| `s3_storage.py` | minio SDK 封装：endpoint 解析（http/https 前缀）、对象读写、bucket 探测 |
| `icon_validate.py` | 品牌图标正方形校验（PNG/JPEG/GIF/WebP 文件头 + SVG width/height/viewBox，零新增依赖） |
| `timeutil.py` | 时间窗口判断（支持跨午夜）、时区名 |
| `api/` | 端点：auth / meta / targets / results / checks / stats / stream(SSE) / settings / logs；除 auth、meta 外均挂 `require_auth` |
| `checkers/` | 检查器：base（CheckOutcome 结构）、ping / port / http / dns；`build_checker` 工厂按 target 构造 |
| `tests/` | pytest 测试；conftest 提供 client / logged_client / fake_checker / no_scheduler fixture |

## 规则与约束

### 语言与兼容

- **代码须保持 Python 3.10 兼容**：本地 venv 是 3.10，CI/Docker 用 3.12
- Windows 下 venv 在 `.venv/Scripts/python`（非 `.venv/bin`）
- **运行时日志消息必须英文**（用户要求）；注释 / docstring 中文不受限

### 测试与 lint

- 测试：根目录 `pytest`（testpaths=backend/tests、asyncio_mode=auto）；每个改动点提交前必须全绿
- lint：根目录 `ruff check backend`（仅 check 无 format；规则 E/F/I/UP/B，行宽 100）
- 常用 fixture：`fake_checker`（monkeypatch `build_checker` 返回假结果）、`no_scheduler`（reconcile noop）、`logged_client`（已登录 TestClient）
- 测试要覆盖新端点/新行为（含 4 级日志断言），mock 依赖用 monkeypatch，不依赖真实网络

### 关键坑（生产事故教训）

- **更新目标禁止 `model_copy(update=dict)`**：它不重新验证嵌套模型，`time_ranges` 会变成 dict，调度循环 `is_time_in_ranges` 抛 AttributeError 使定时任务**静默死亡**（2026-08 生产事故：用户编辑目标后全部定时检查停止 23 小时且无日志）。必须 `Target.model_validate({**existing.model_dump(), **payload.model_dump(exclude_unset=True)})` 整体重验证
- **不要 `await` 同步方法**：如 `ResultStore.resize` 是同步方法，`await resize(...)` 在 Python 3.12 抛 TypeError 杀死 config watchdog（配置热加载失效）。同步方法直接调用
- 调度任务异常退出不会自动续跑：`_run_loop` 循环体已包 try/except（单次异常不杀任务），任务意外死亡后 `reconcile()` 检测 `task.done()` 并重建（打 warning 日志）；手动检查（`manual_run`）不经过 `is_time_in_ranges`，与定时检查路径不同
- **认证 cookie 优先**：有效会话 cookie 存在时不再校验 Authorization Bearer 头（残留/轮换后的失效 token 不得使有效会话 401，auth.py）
- **uvicorn.access 挡刷屏用过滤器不用 setLevel**：access 记录是 INFO 级，setLevel(DEBUG) 挡不住；`logging_setup._AccessFilter` 只在根 logger 为 DEBUG 时放行
- **手动检查崩溃以 error 结果返回**：`manual_run` 的 `_guarded` 捕获检查器异常后构造 status=error 的 CheckResult（message 含异常），不静默丢弃（否则前端误报「全部正常」）

### 数据与存储约定

- config.json 原子写（`atomic_write`：临时文件 + os.replace）；密钥/凭据存 secrets.json，**接口不回读明文**（含 GET /settings/api-token 只返回 has_token，明文仅在生成时返回一次）
- ResultStore：本地文件追加写 + 超限整文件重写（resize 是同步方法）；`storage_mode` 与 S3 配置变更由 scheduler watchdog 调 `set_s3_mode` 热更新
- S3 对象按天（`datapath/results/YYYY-MM-DD.jsonl`）永久保留：合并去重后整对象上传，写失败 ERROR 日志并降级本地（结果不丢）；ResultStore 维护待补传日期集合（`_dirty_dates`）：启动 / `set_s3_mode` 新启用 S3 时本地全部历史按天补传（`_schedule_backfill` 后台任务，不阻塞启动），append 只产生当天日期，同步失败的日期保留待下次 append 自动重试（跨天失败自愈）
- **S3 同步必须在 append 临界区外执行**（`_sync_s3_async` 持锁内快照、锁外 to_thread）：慢/故障 S3 不得冻结读写接口；**拉取既有对象失败时跳过该日期绝不覆盖**（防 S3 历史被内存子集覆盖）；单日期失败不中断其余日期；`_sync_to_s3` 返回 bool 表示是否成功
- 加载（`_load`）后按 `checked_at` 排序（S3 对象返回顺序不保证时间序）；`_trim_to_max` 裁剪时同步收缩 `_seen_ids`，内存有界
- 日志清理在 `log_cleaner.py` 独立循环，不依赖 DailyFileHandler 轮转；upload 上传成功后才删本地；delete 模式 unlink 失败（OSError）ERROR 日志并保留待下轮，不中断其余文件
