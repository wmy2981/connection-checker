# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。自 v1.0.0 起，本文件由 **python-semantic-release** 依据 Conventional Commits 自动维护。

## [Unreleased]

## [1.0.1] - 2026-08-06

### 修复

- **ui**：仪表盘布局贴边、统计/目标卡片竖直排列问题；深色浅色模式与响应式适配（新增主题切换按钮）

## [1.0.0] - 2026-08-06

从零重构，摒弃原 Flask 单体脚本，采用 FastAPI + Vue 3 现代架构。

### 新增

- 三种检查方式：ICMP Ping（ping3 库，跨平台、不依赖系统 locale）、TCP 端口连通（asyncio）、HTTP(S) 状态码（httpx，状态码集合可配）
- asyncio 每目标独立调度：独立检查间隔、跨午夜时间窗口、独立超时，配置变更即时生效
- 手动立即检查（单个目标 / 全部目标）
- Web 仪表盘：概览统计卡片、目标实时状态、结果表筛选（状态 / IP / 目标 / 日期 / 时间段）与分页、详情弹窗
- SSE 实时推送，结果秒级更新
- Webhook 告警：连续失败达阈值触发 + 恢复通知，兼容 Gotify / 企业微信 / 自建服务
- 认证：单访问码 argon2 哈希存储、JWT 写入 HttpOnly Cookie、CSRF 纵深防御；未配置访问码时自动生成并打印
- 配置管理页：目标增删改查、启用停用、时间窗口编辑
- 数据存储：`config.json` 原子写 + `results.jsonl` 追加写，默认保留最近 50000 条结果
- API 文档：内置 OpenAPI（`/docs`）+ 手写 `docs/api.md`
- 单一 Docker 镜像（多阶段构建、非 root、amd64 + arm64），镜像发布至 ghcr.io
- GitHub Actions：ruff + pytest → buildx 多架构镜像 → semantic-release 自动发版

### 变更

- 结果保留策略由「落盘仅 1000 条」改为 JSONL 追加 + 可配置上限（默认 50000 条）
- 检查间隔单位由毫秒改为秒
- 原硬编码访问码 `admin123` 移除，改为环境变量 / 自动生成的访问码，哈希化存储

### 修复

- 时间窗口支持跨午夜（原 `start > end` 时永远不命中）
- 消除对系统 ping 中文输出的解析依赖
- 结果文件改为追加写与原子替换，避免整文件重写损坏
