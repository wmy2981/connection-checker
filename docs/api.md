# API 参考

基础路径：`/api/v1`。所有响应为 JSON（SSE 流除外）。除登录与 `/auth/me` 外，均需登录会话（HttpOnly Cookie）。

> 交互式文档：部署后访问 `/docs`（Swagger UI）或 `/redoc`。

## 通用约定

- 认证：登录后服务端下发 `session` Cookie（HttpOnly）。客户端不需要手动携带 token。
- 错误：`{"detail": "错误信息"}`，状态码：`401` 未授权、`404` 资源不存在、`415` 写请求未带 `application/json`、`422` 参数校验失败。
- 时间：ISO 8601（如 `2026-08-06T08:00:00+00:00`）。

## 认证

### POST /auth/login

请求：

```json
{ "access_code": "你的访问码" }
```

成功：`200`，设置 `session` Cookie，`{"ok": true}`。访问码错误：`401`。

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
| `check_method` | string | 是 | `ping` / `port` / `http` |
| `name` | string | 否 | 名称 |
| `check_interval` | int | 否 | 秒，默认 60，最小 5 |
| `time_ranges` | array | 否 | `[{start, end}]`，默认全天，支持跨午夜 |
| `enabled` | bool | 否 | 默认 true |
| `port` | int | 条件 | `port` 方式必填；`http` 方式可覆盖默认端口 |
| `scheme` | string | 否 | `http` / `https`，默认 `http` |
| `url_path` | string | 否 | `http` 方式路径，默认 `/` |
| `http_success_codes` | array | 否 | `http` 方式期望状态码，默认 200–399 |
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
| `status` | `success` / `fail` / `timeout` / `error` / `all` |
| `ip` | IP 模糊匹配 |
| `target_id` | 按目标过滤 |
| `date` | 日期 `YYYY-MM-DD` |
| `time_start` / `time_end` | 时间段 `HH:MM`（支持跨午夜） |
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
      "extra": { "packet_loss_pct": 0.0, "min_ms": 11.0, "max_ms": 14.0 },
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
      "last_message": "平均延迟 12ms，丢包率 0%"
    }
  ]
}
```

状态计数为最近 50 条检查结果的统计；`target_status` 为每个目标的最新一次结果。

## 实时推送（SSE）

### GET /stream

Server-Sent Events 流。事件：

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
