# API 参考

基础路径：`/api/v1`。所有响应为 JSON（SSE 流除外）。除登录与 `/auth/me` 外，均需认证（见下方两种认证方式）。

> 未设置 `CONNECTCHECKER_ACCESS_CODE` 时为**免认证模式**：所有接口直接放行，`/auth/me` 恒返回 `{"authenticated": true}`，无需登录。

> 交互式文档：部署后访问 `/docs`（Swagger UI）或 `/redoc`。

## 通用约定

- 认证：支持两种方式，二选一即可：
  - **会话 Cookie（浏览器）**：登录后服务端下发 `session` Cookie（HttpOnly），客户端不需要手动携带。
  - **API Token（外部调用）**：请求头携带 `Authorization: Bearer <token>`。Token 在「API 访问令牌」接口生成（见下文），存于 `secrets.json`；重新生成后旧 Token 立即失效。
- 错误：`{"detail": "错误信息"}`，状态码：`400` 请求缺失必要信息、`401` 未授权、`404` 资源不存在、`415` 写请求未带 `application/json`、`422` 参数校验失败、`502` 依赖服务不可用。
- 时间：ISO 8601（如 `2026-08-06T08:00:00+00:00`）。

## 认证

### POST /auth/login

请求：

```json
{ "access_code": "你的访问码" }
```

成功：`200`，设置 `session` Cookie，`{"ok": true}`。访问码错误：`401`。免认证模式下任意访问码均成功。

### POST /auth/logout

清除会话 Cookie。成功：`200`，`{"ok": true}`。

### GET /auth/me

返回当前会话是否有效。

```json
{ "authenticated": true }
```

## 检查目标

### GET /targets

返回全部目标。

```json
[
  {
    "id": "ab12cd34ef56",
    "name": "外网 DNS",
    "ip": "8.8.8.8",
    "check_method": "ping",
    "check_interval": 60,
    "time_ranges": [{ "start": "00:00", "end": "23:59" }],
    "enabled": true,
    "notify_enabled": true,
    "ping_count": null,
    "port": null,
    "scheme": "http",
    "url_path": "/",
    "http_success_codes": null,
    "timeout": null,
    "created_at": "2026-08-06T08:00:00+00:00",
    "updated_at": "2026-08-06T08:00:00+00:00"
  }
]
```

### POST /targets

新增目标。请求字段见下表（`id`/`created_at`/`updated_at` 由服务端生成）。成功：`201`，返回完整目标。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ip` | string | 是 | IP 或主机名 |
| `check_method` | string | 是 | `ping` / `port` / `http` / `dns` |
| `name` | string | 否 | 名称 |
| `check_interval` | int | 否 | 秒，默认 60；`0` = 关闭定时检查（仅手动触发） |
| `time_ranges` | array | 否 | `[{start, end}]`，默认全天，支持跨午夜 |
| `enabled` | bool | 否 | 默认 true |
| `notify_enabled` | bool | 否 | 目标级告警开关，默认 true；关闭后该目标不推送告警与恢复通知 |
| `ping_count` | int | 否 | 覆盖全局发包数（`ping` 方式） |
| `port` | int | 条件 | `port` 方式必填；`http` 方式可覆盖默认端口 |
| `scheme` | string | 否 | `http` / `https`，默认 `http` |
| `url_path` | string | 否 | `http` 方式路径，默认 `/` |
| `http_success_codes` | array | 否 | `http` 方式期望状态码，默认 200–399；须为 100–599 的整数，越界 422 |
| `timeout` | number | 否 | 覆盖全局超时（秒） |

### PUT /targets/{target_id}

部分更新目标，仅提交要修改的字段。成功：`200`，返回更新后的目标。目标不存在：`404`。

```json
{ "check_interval": 120, "enabled": false }
```

### DELETE /targets/{target_id}

删除目标。成功：`204`，无响应体。目标不存在：`404`。

## 检查结果

### GET /results

查询检查结果，服务端分页。

查询参数：

| 参数 | 说明 |
| --- | --- |
| `status` | `success` / `fail` / `timeout` / `error` / `all`（逗号分隔多选） |
| `check_method` | `ping` / `port` / `http` / `dns`（逗号分隔多选） |
| `ip` | IP 模糊匹配（含 `*` / `?` 时按通配符全匹配） |
| `target_id` | 按目标过滤（逗号分隔多选） |
| `target_name` | 按目标名称/地址过滤（逗号分隔多选） |
| `date` | 日期 `YYYY-MM-DD` |
| `time_start` / `time_end` | 时间段 `HH:MM`（支持跨午夜） |
| `start_at` / `end_at` | 完整时间范围（本地时间 ISO，如 `2026-08-09T22:00:00`），支持跨日 |
| `page` | 页码，默认 1 |
| `page_size` | 每页条数，默认 20，最大 200 |

响应：

```json
{
  "results": [
    {
      "id": "f1e2d3c4b5a6",
      "target_id": "ab12cd34ef56",
      "target_name": "外网 DNS",
      "ip": "8.8.8.8",
      "check_method": "ping",
      "status": "success",
      "latency_ms": 12.3,
      "message": "平均延迟 12ms，丢包率 0%",
      "extra": {
        "packet_loss_pct": 0.0,
        "min_ms": 11.0,
        "max_ms": 14.0,
        "jitter_ms": 1.2,
        "stddev_ms": 0.8,
        "sent": 4,
        "received": 4,
        "samples_ms": [11.0, 12.5, 13.1, 14.0]
      },
      "checked_at": "2026-08-06T08:00:00+00:00"
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```

`status` 取值：

- `success` — 检查通过
- `fail` — 明确失败（如目标不可达、状态码不符）
- `timeout` — 超时
- `error` — 检查过程异常

## 手动检查

### POST /checks/run

立即对全部启用目标（或指定目标）执行一次检查。请求体可选：

```json
{ "target_id": "ab12cd34ef56" }   // 指定目标；空对象 {} 表示全部
```

响应：新产生的检查结果数组（与 `/results` 单条结构相同）。指定目标不存在：`404`。

## 全局设置

### GET /settings/app

返回全局检查参数（存于 `config.json` 的 `app` 节）。

```json
{
  "result_max_records": 50000,
  "ping_count": 4,
  "connect_timeout": 3.0,
  "http_timeout": 5.0,
  "stats_window": 50,
  "log_level": "INFO",
  "log_cleanup_mode": "delete",
  "log_retention_days": 30,
  "storage_mode": "local",
  "brand_icon": null
}
```

| 字段 | 说明 |
| --- | --- |
| `result_max_records` | 结果保留条数，超出自动裁掉最旧 |
| `ping_count` | Ping 发包数（全局默认，单个 `ping` 目标可在 `check_targets[].ping_count` 覆盖） |
| `connect_timeout` | Ping/TCP 超时（秒） |
| `http_timeout` | HTTP 超时（秒） |
| `stats_window` | 仪表盘统计的近 N 次检查 |
| `log_level` | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `log_cleanup_mode` | 日志清理：`none` 不清理 / `delete` 删除 n 天前 / `upload` 上传 S3 后删除本地 |
| `log_retention_days` | 日志保留天数，默认 30 |
| `storage_mode` | 检查记录存储：`local` 仅本地 / `s3` 仅 S3 / `both` 本地+S3 双写（S3 按天对象永久保留） |
| `brand_icon` | 品牌图标：base64 data URI 或 http(s) URL，必须为正方形；`null` = 默认图标 |

### PUT /settings/app

更新配置，请求体同上（全量提交）。成功：`200`，返回更新后的配置。

- `result_max_records` 修改立即生效，超出部分即时裁剪
- `brand_icon` 服务端校验：支持 PNG/JPEG/GIF/WebP/SVG，必须正方形（URL 会下载校验，超时 10s），非正方形或无法解析：`422`
- `log_cleanup_mode=upload` 或 `storage_mode=s3/both` 依赖 S3：未完整配置 S3（含凭据）时返回 `422`

## 告警设置

### GET /settings/webhook

返回 Webhook 告警配置（存于 `config.json`）。

```json
{ "enabled": true, "url": "https://gotify.example.com/message?token=...", "fail_threshold": 3 }
```

### PUT /settings/webhook

更新配置，请求体同上。成功：`200`，返回更新后的配置。

### POST /settings/webhook/test

向 Webhook 地址推送一条测试消息，验证地址可用。请求体可选：

```json
{ "url": "https://gotify.example.com/message?token=..." }   // 不传则用已保存的配置
```

成功：`200`，`{ "ok": true, "info": "HTTP 200" }`。地址未填写：`400`；推送失败（连接失败 / 非 2xx）：`502`。

## S3 存储配置

S3 配置存于 `config.json` 的 `s3` 节；凭据（Access ID / Access Key）存于 `secrets.json`，接口不回读明文。用于检查记录存储、日志自动上传（见「全局设置」）。

### GET /settings/s3

返回当前 S3 配置（不含凭据明文）。

```json
{
  "enabled": false,
  "endpoint": "",
  "bucket": "",
  "region": null,
  "datapath": "",
  "has_credentials": false
}
```

`has_credentials` 表示凭据是否已配置；`region` 可选（部分 S3 服务要求）。

### PUT /settings/s3

更新配置。请求体：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否启用 |
| `endpoint` | S3 服务地址，如 `https://s3.example.com` 或 `http://minio:9000` |
| `bucket` | 存储桶名称 |
| `region` | 可选，部分服务要求 |
| `datapath` | 数据在 bucket 中的路径前缀 |
| `access_id` / `access_key` | 可选；不传/留空 = 不修改已保存的凭据；传空字符串 = 清除 |

启用时 `endpoint` / `bucket` / `datapath` 必填，否则：`422`。成功：`200`，返回与 GET 相同的结构（不含凭据）。

### POST /settings/s3/test

测试 S3 连接（验证凭据与网络连通性，检查 bucket 是否存在）。请求体可选，字段同 PUT（不传或空对象 = 用已保存配置；凭据留空自动回退已保存值）。

成功：`200`，`{ "ok": true, "info": "连接成功，bucket「xx」存在" }`（bucket 不存在时 info 提示需在服务端创建）。未填写 endpoint/bucket 或凭据：`400`；连接失败（网络 / 凭据错误）：`502`。

## API 访问令牌

供外部程序调用 API 使用（认证方式见「通用约定」）。Token 存于 `secrets.json`，单 Token 制：重新生成后旧 Token 立即失效。

### GET /settings/api-token

返回当前 Token 明文（供配置页掩码展示/复制；密钥类接口中唯一回读明文的例外，凭登录保护）。已设置：`{ "has_token": true, "token": "..." }`；未设置：`{ "has_token": false, "token": null }`。

### POST /settings/api-token/generate

生成新 Token，旧 Token 立即失效。成功：`200`，`{ "token": "..." }`。

### DELETE /settings/api-token

删除 Token，外部 API 调用立即禁用。成功：`200`，`{ "ok": true }`。

调用示例：

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/targets
```

## 统计概览

### GET /stats/summary

仪表盘概览数据。

```json
{
  "total_targets": 2,
  "enabled_targets": 2,
  "last_total_checks": 50,
  "last_success": 48,
  "last_fail": 1,
  "last_timeout": 1,
  "last_error": 0,
  "latest_check_at": "2026-08-06T08:00:00+00:00",
  "target_status": [
    {
      "target_id": "ab12cd34ef56",
      "name": "外网 DNS",
      "ip": "8.8.8.8",
      "check_method": "ping",
      "enabled": true,
      "check_interval": 60,
      "last_status": "success",
      "last_latency_ms": 12.3,
      "last_checked_at": "2026-08-06T08:00:00+00:00",
      "last_message": "平均延迟 12ms，丢包率 0%",
      "uptime_pct": 99.9,
      "uptime_total": 1438,
      "consecutive_fails": 0
    }
  ]
}
```

状态计数为最近 50 条检查结果的统计；`target_status` 为每个目标的最新一次结果；`uptime_pct` / `uptime_total` 为该目标近 24 小时滚动窗口的可用率（无样本时为 `null`）与检查次数；`consecutive_fails` 为当前连续失败次数（告警模块跟踪，成功或未失败过为 0）。

### GET /stats/trend

按小时聚合的成功率趋势（本地时区，空时段补齐为 0）。

查询参数：

| 参数 | 说明 |
| --- | --- |
| `hours` | 窗口小时数，默认 24，范围 1–168 |
| `target_id` | 只统计指定目标；缺省为全部目标 |
| `unit` | 聚合粒度：`hour` 按小时（默认）/ `day` 按天（小时数折算为天数） |

```json
{
  "hours": 24,
  "target_id": null,
  "unit": "hour",
  "buckets": [
    {
      "bucket": "2026-08-12T00:00",
      "total": 60,
      "success": 59,
      "fail": 1,
      "timeout": 0,
      "error": 0,
      "avg_latency_ms": 12.4
    }
  ]
}
```

## 实时推送（SSE）

### GET /stream

Server-Sent Events 流。认证走会话 Cookie（`EventSource` 无法携带自定义请求头，需先通过浏览器会话登录；API Token 认证不适用于 SSE）。事件：

- `ready` — 连接建立
- `result` — 新检查结果，`data` 为单个结果对象（结构与 `/results` 单条一致）

示例（前端）：

```js
const es = new EventSource('/api/v1/stream')
es.addEventListener('result', (e) => {
  const result = JSON.parse(e.data)
  // 刷新结果列表
})
```

连接空闲时每 15 秒发送一次心跳注释行保持存活。

## 日志查看与导出

日志按天写入 `data/logs/app-YYYY-MM-DD.log`，行格式：
`时间 | 级别 | logger名 | 文件:行号 | 消息`（旧版无来源段的行解析时兼容）。

### GET /logs

分页查看日志（倒序，最新在前）。查询参数：

| 参数 | 说明 |
| --- | --- |
| `level` | 级别筛选，逗号分隔多值（`DEBUG,WARN`），精确匹配 |
| `start` \ `end` | 本地时间 `YYYY-MM-DD` 或 `YYYY-MM-DDTHH:MM:SS` |
| `source` | 来源筛选，逗号分隔多值（OR）：文件名（如 `scheduler.py`）或模块名，子串匹配、大小写不敏感 |
| `page` | 页码，默认 1 |
| `page_size` | 每页条数，默认 100，最大 500 |

```json
{
  "results": [
    {
      "time": "2026-08-12 10:30:36,123",
      "level": "INFO",
      "name": "app.scheduler",
      "source": "scheduler.py:72",
      "message": "Scheduled target 公网 (ab12cd34ef56)"
    }
  ],
  "total": 1234,
  "page": 1,
  "page_size": 100,
  "pages": 13
}
```

### GET /logs/export

导出筛选后的日志为 `.log` 文本（参数同列表接口，含文件头 `Content-Disposition`）。

### GET /logs/sources

日志中出现过的来源枚举（文件名或模块名，去重排序），供筛选下拉使用；结果缓存 30 秒。

```json
{ "sources": ["scheduler.py", "storage.py", "app.notifier", "uvicorn"] }
```
