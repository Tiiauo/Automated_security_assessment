# 前端

React 19 + TypeScript + Vite，包含 PRD 6.1 的 9 个业务页面与 404 页面。

## 运行

```bash
npm ci
npm run dev     # http://localhost:5173，/api 代理到 http://127.0.0.1:8000
npm run build
npm run lint
```

开发期通过 Vite 代理保持同源，登录 Cookie 才能正常携带（PRD 15.10）。

## 演示数据回退

监控、漏洞、攻击路径、报告及隔离环境维护均接入真实接口，完整运行步骤见[项目 README](../README.md)。
开发环境（`import.meta.env.DEV`）或显式设置 `VITE_DEMO_MODE=1` 时，部分 HTTP 页面仅在未注册接口返回裸 404 时使用
`src/api/demo.ts` 中的原型数据并标注「演示数据」；业务资源不存在（40401）正常显示空态，不回退演示报告。
实时通道默认重连，只有显式 `VITE_DEMO_MODE=1` 才启用演示快照；生产构建默认关闭 HTTP 演示回退。

```bash
VITE_DEMO_MODE=1 npm run dev
```

## 目录

```text
src/
├── api/          请求封装、类型定义与演示数据
├── auth/         登录态上下文
├── components/   布局、图标、项目头部、通用 UI
├── hooks/        项目详情与 WebSocket 组合逻辑
├── pages/        9 个业务页面 + 404
├── utils/        时间格式化
├── App.tsx       路由表
└── main.tsx      入口
```

## 页面

| 页面 | 路由 |
| --- | --- |
| 登录 / 初始化 | `/login` |
| 项目列表 | `/projects` |
| 项目创建 | `/projects/new` |
| 项目详情 | `/projects/:id` |
| 实时监控 | `/projects/:id/monitor` |
| 漏洞列表 | `/projects/:id/vulnerabilities` |
| 攻击路径 | `/projects/:id/attack-paths` |
| 报告 | `/projects/:id/report` |
| 系统配置 | `/settings`（管理员） |

子页面支持 `?run_id=` 查看历史轮次。监控页通过 `WS /api/projects/{id}/stream` 接收 `snapshot` 与增量消息，
断线后指数退避重连并按首帧快照恢复。报告页订阅增量事件刷新，预览与下载使用所选轮次。
