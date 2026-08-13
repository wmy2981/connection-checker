# CLAUDE.md — frontend

Vue 3 + TypeScript + Vite 前端，UI 组件库 naive-ui（2.40），图标 @vicons/ionicons5（本地 npm 依赖，勿用 CDN）。

## 文件分工

| 文件/目录 | 职责 |
| --- | --- |
| `views/LoginView.vue` | 登录页（访问码） |
| `views/DashboardView.vue` | 仪表盘：统计卡、目标状态卡、趋势图、检查记录（筛选/导出/分页）、SSE 实时刷新 |
| `views/ConfigView.vue` | 配置页：目标管理表格、全局检查设置、告警、S3 配置、API 访问令牌、品牌图标、数据管理（导入/导出/备份）、日志管理弹窗 |
| `components/StatsCards.vue` | 统计卡（成功/失败/超时/错误 + 百分比，近 N 次） |
| `components/TrendChart.vue` | 手绘 SVG 成功率趋势折线 |
| `components/TargetFormModal.vue` | 新增/编辑目标弹窗（含目标 ID 只读展示 + 复制按钮） |
| `components/DataImportDialog.vue` | 数据导入/恢复弹窗（文件选择 + 内容勾选，双模式，供数据管理卡片复用） |
| `components/AppFooter.vue` | 页脚：API 文档链接、版本号（/meta）、GitHub 链接 |
| `components/BrandLogo.vue` | 品牌图标（自定义 icon，加载失败回退 favicon.svg） |
| `components/ThemeToggle.vue` | 主题三模式切换（跟随系统/浅/深） |
| `api/client.ts` | fetch 封装：BASE=/api/v1、自动 JSON Content-Type、401 统一跳 /login |
| `api/index.ts` | `api` 对象：全部端点封装（新增端点在此注册） |
| `composables/useAppTime.ts` | 按容器时区格式化时间 |
| `composables/useDark.ts` | 主题模式管理（localStorage `cc-theme-mode`，默认跟随系统） |
| `composables/useClipboard.ts` | 复制工具 `copyText`：Clipboard API → execCommand → 提示手动（三级兜底） |
| `store/auth.ts` | 登录态 |
| `router/index.ts` | 路由与登录守卫（beforeEach） |
| `types/index.ts` | TS 类型（与后端模型一一对应，改后端模型须同步） |
| `main.ts` / `App.vue` | 入口与 Provider 装配（NConfigProvider + NMessageProvider + NDialogProvider，zhCN），自定义主题变量（--cc-*） |

## 规则与约束

### 常用命令

- typecheck：`npm run typecheck`（vue-tsc --noEmit）；`npm run build` 会先跑 typecheck
- 开发：`npm run dev`（localhost:5173，`/api` 代理到 8000）
- 前端无测试框架（仅 vue-tsc）；每个改动点提交前必须 typecheck 通过

### naive-ui 关键坑

- **组件必须显式 import**：模板用了 `<n-layout>` / `<n-layout-header>` / `<n-layout-content>` 等但漏 import 时，Vue 渲染成自定义元素、布局错乱且仅 console 报 warning（曾因此布局崩溃）
- **n-select 的 v-model 初始值禁用 `''`**：空字符串被当作「有选中值」，导致不显示 placeholder 且误显示清除叉号（2026-08 bug：仪表盘目标名称筛选框）。初始/重置用 `null`（多选用 `[]`；clear 事件 emit 的也是 null，参数序列化需防御 `Array.isArray` 检查）
- **naive-ui 2.40 的 Select 用 `:menu-props` 而不是 `popup-class`**：下拉弹出列表加宽（宽于触发器）通过 `menu-props="{ class: 'wide-popup' }"` + 全局样式 `min-width: 360px`（App.vue）
- **NStatistic 无 `#value` 插槽**：值内容用默认插槽、后缀用 `#suffix`（2026-08 迭代踩坑，vue-tsc 捕获）
- **DataTable 列排序用 `sorter` 函数属性**（无 `sortable` 布尔属性）；列固定用 `fixed: 'left' | 'right'`（时间列曾固定左置，移动端挤占空间后移除）
- **NEmpty 的 `description` 是 prop 非插槽**；弹窗卡片窄屏用 `style="width: 600px; max-width: 94vw"`
- 主题三模式由 `useDark.ts` 管理（`cc-theme-mode` 存 localStorage，默认跟随系统），`ThemeToggle.vue` 下拉切换，所有页面共用；localStorage 访问须 try/catch（隐私模式禁用时降级）
- 复制文本一律用 `composables/useClipboard.ts` 的 `copyText`（http 内网下 Clipboard API 不可用会自动降级），勿直接用 navigator.clipboard；降级分支的 textarea **必须挂在焦点元素所在的 `[role="dialog"]` 容器内**——naive-ui NModal 的 focus trap 会拉回挂到 body 的 textarea 焦点并清除选区，导致 modal 内复制静默失败（2026-08 线上 bug：id/检查数据复制失效、页面本体令牌复制正常）
- 按钮弹窗等交互组件（NPopconfirm 等）确认按钮改红色用 `positive-button-props="{ type: 'error' }"`

### 约束

- 新增页面须在 `router/index.ts` 注册并置于登录守卫后
- 改后端接口/模型时，`types/index.ts` 与 `api/index.ts` 须同步更新
- 图表用手绘 SVG（TrendChart.vue 模式），不引入图表库
- **API 令牌明文回显**：`getApiToken` 返回 `{ has_token, token }`（后端回读明文），配置页默认掩码显示（`n-input type="password" show-password-on="click"` 眼睛图标切换）；删除按钮以「已设置」状态（`apiTokenSet`）控制
- 请求超时在 `api/client.ts`（15s）与 `downloadExport`（60s）：timer 在 finally 清理，**必须覆盖响应体读取阶段**（fetch resolve 后不清 timer，否则停滞流挂死界面）
- 数据导入走 multipart 上传（`api/index.ts` 的 `uploadImport`）：fetch + FormData + **必须带 `X-Requested-With: XMLHttpRequest` 头**（后端 CSRF JSON 检查的唯一例外条件）、超时 120s；不走 `request()`（其强制 JSON Content-Type）
- 移动端适配基线（≤640px）：目标卡两行布局（主行 + 元数据行可换行）、n-card header 窄屏 `flex-wrap` 标题独占一行、表格不固定列；用 `:deep(.n-card-header__main)` 等覆盖 naive 内部结构
