import { StrictMode } from "react";

import { createRoot } from "react-dom/client";

import App from "./microfrontend/App";
import { installSwReloadHandler } from "./lib/swReload";
import "@xyflow/react/dist/style.css";
import "./styles/index.css";

// 部署新版本后 SW 接管 → 自动刷新到新 bundle（防旧 chunk 404）
installSwReloadHandler();

// Standalone 独立模式入口：无 Host props，App 内部使用自身 Router。
// basename="/saios"：saiOS 是子应用，挂载在 /saios 前缀下（根 / 留给总台/备案页）。
// React Router 的 navigate/Link/Navigate 会自动加 basename；API(/api/v1) 与静态资源(/static)
// 是根绝对路径，不受影响（由 nginx 转发）。
const container = document.getElementById("root");
if (!container) {
  throw new Error("根节点 #root 不存在");
}

createRoot(container).render(
  <StrictMode>
    <App basename="/saios" />
  </StrictMode>,
);
