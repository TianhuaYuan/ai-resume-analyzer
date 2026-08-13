# frontend

React 19 + TypeScript + Vite 8 + Tailwind CSS 4 单页应用。

## 构建配置

**Vite** (`vite.config.ts`)：dev server 在 5173 端口，`/api/*` 自动代理到 `http://127.0.0.1:8081`。插件：`@vitejs/plugin-react` + `@tailwindcss/vite`。

**TypeScript** (`tsconfig*.json`)：3 个配置文件——`tsconfig.json`（引用入口）、`tsconfig.app.json`（应用源码）、`tsconfig.node.json`（Vite/ESLint 配置）。strict 模式。

**Tailwind CSS 4**：通过 Vite 插件引入，CSS 入口在 `src/index.css`，无需 `tailwind.config.js`。

**Oxlint** 替代 ESLint（`.oxlintrc.json`）：启用了 react、typescript、oxc 三个插件。当前只配了 `rules-of-hooks` 为 error。`npm run lint` 执行。

## Docker 构建

`Dockerfile` 分两阶段：
1. builder（node:20-alpine）：`npm ci` → `npm run build`
2. runtime（nginx:alpine）：复制 dist 到 nginx 静态目录，使用自定义 `nginx.conf`

CI 中 `frontend-build` job 执行：`npm ci` → `oxlint` → `tsc -b` → `vite build`。

## nginx 配置要点

`nginx.conf`：
- API 反代 `/api/` → `http://backend:8000`（生产环境 nginx 直接连 backend 容器）
- SSE 支持：`proxy_buffering off`，`proxy_read_timeout 86400s`
- SPA fallback：`try_files $uri $uri/ /index.html`
- 静态资源缓存 1 年，`cache-control: public, immutable`
- 安全头通过后端 `main.py` 中间件注入

## 开发模式

```bash
npm install
npm run dev       # Vite dev server，端口 5173
npm run build     # 生产构建，输出到 dist/
npm run lint      # Oxlint 检查
npm run preview   # 本地预览构建产物
```

`npm run dev` 时 Vite 代理 `/api`，不需要启动 nginx。生产构建直接 `npm run build` 然后 nginx 托管 `dist/`。
